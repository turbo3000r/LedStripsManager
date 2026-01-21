#include "DimmingEngine.h"

// Global instance
DimmingEngine dimmingEngine;

// ============================================================================
// ISR Wrappers
// ============================================================================

void IRAM_ATTR zeroCrossISR() {
    dimmingEngine.handleZeroCross();
}

void IRAM_ATTR timerISR() {
    dimmingEngine.handleTimerFire();
}

// ============================================================================
// DimmingEngine Implementation
// ============================================================================

void DimmingEngine::begin() {
    // Initialize GPIO pins
    for (int i = 0; i < NUM_CHANNELS; i++) {
        pinMode(CHANNEL_PINS[i], OUTPUT);
        digitalWrite(CHANNEL_PINS[i], LOW);
        channelBrightness[i] = 0;
        channelDelayUs[i] = HALF_CYCLE_US + 2000; // Default OFF
        channelFired[i] = false;
    }
    
    // Initialize zero-cross pin
    pinMode(ZERO_CROSS_PIN, INPUT_PULLUP);
    
    // Attach zero-cross interrupt
    attachInterrupt(digitalPinToInterrupt(ZERO_CROSS_PIN), zeroCrossISR, FALLING);
    
    // Initialize timer (will be armed on zero-cross)
#ifdef ESP32
    // ESP32: Use hardware timer 0, prescaler 80 (1MHz), count up
    timer = timerBegin(0, 80, true);
    timerAttachInterrupt(timer, timerISR, true);  // true = edge-triggered
    timerAlarmDisable(timer);  // Start disabled
    timerWrite(timer, 0);      // Reset counter
#else
    // ESP8266: Use Timer1
    timer1_attachInterrupt(timerISR);
    timer1_disable();  // Start disabled
#endif
    
    lastFireDelayUs = 0;
    
    DEBUG_PRINTLN("DimmingEngine initialized");
}

void DimmingEngine::setBrightness(uint8_t brightness) {
    for (int i = 0; i < NUM_CHANNELS; i++) {
        setChannelBrightness(i, brightness);
    }
}

void DimmingEngine::setChannelBrightness(uint8_t channel, uint8_t brightness) {
    if (channel >= NUM_CHANNELS) return;
    
    // Clamp brightness to valid range (0-9)
    brightness = constrain(brightness, 0, 9);
    
    unsigned long newDelay = brightnessToDelayUs(brightness);
    
    // Update brightness atomically
    noInterrupts();
    channelBrightness[channel] = brightness;
    channelDelayUs[channel] = newDelay;
    interrupts();
}

unsigned long DimmingEngine::brightnessToDelayUs(uint8_t brightness) {
    // Brightness is now 0-9 levels
    if (brightness == 0) {
        // Off - use max delay (beyond half cycle)
        return HALF_CYCLE_US + 2000;
    }
    
    if (brightness >= 9) {
        // Full brightness - minimum delay
        return MIN_DELAY_US;
    }
    
    // Map brightness to delay
    // Brightness 1 (low) -> ~8500us
    // Brightness 9 (high) -> ~500us
    unsigned long maxDelay = 8500;
    return map(9 - brightness, 0, 9, MIN_DELAY_US, maxDelay);
}

// ----------------------------------------------------------------------------
// CRITICAL ISR LOGIC
// ----------------------------------------------------------------------------

void IRAM_ATTR DimmingEngine::handleZeroCross() {
    // DEBOUNCE FILTER: Reject interrupts that come too quickly
    // This prevents double-triggering from zero-cross pulse width and noise spikes
    unsigned long now = micros();
    unsigned long elapsed = now - lastZeroCrossUs;
    
    // Use debounce filter from config (ZC_DEBOUNCE_US = 3ms)
    // Filters out: noise spikes (1-3us), double-triggers from ZC pulse width (~1.5ms)
    // Real zero-cross events are ~10ms apart for 50Hz AC, so 3ms is safe
    if (elapsed < ZC_DEBOUNCE_US) {
        return;  // Ignore this interrupt - too soon after last valid ZC
    }
    
    // 1. ALWAYS update timestamp, even if there was an emergency
    // This allows recovery detection in update()
    lastZeroCrossUs = now;
    zcSignalHealthy = true;
    
    // Reset state for new half-cycle
    for (int i = 0; i < NUM_CHANNELS; i++) {
        channelFired[i] = false;
    }
    lastFireDelayUs = 0; // Start counting from ZC
    
    // If there was an emergency, but we're here - signal exists.
    // But we'll clear the emergencyShutoff flag in update() to avoid blocking ISR.
    // Here we just allow operation.
    
    if (!emergencyShutoff) {
        scheduleNextFire();
    }
}

// This function finds the NEXT channel to fire and arms the timer
void IRAM_ATTR DimmingEngine::scheduleNextFire() {
    // Read channel states atomically to avoid race conditions
    unsigned long delays[NUM_CHANNELS];
    bool fired[NUM_CHANNELS];
    
    for (int i = 0; i < NUM_CHANNELS; i++) {
        delays[i] = channelDelayUs[i];
        fired[i] = channelFired[i];
    }
    
    unsigned long minNextDelay = HALF_CYCLE_US + 5000;
    bool foundPending = false;
    
    // Find minimum delay among channels that haven't fired yet
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!fired[i] && delays[i] < HALF_CYCLE_US) {
            if (delays[i] < minNextDelay) {
                minNextDelay = delays[i];
                foundPending = true;
            }
        }
    }
    
    if (foundPending) {
        // Calculate how long to wait FROM CURRENT MOMENT (or from previous fire)
        // ESP timer counts "ticks to go".
        // We need (TargetTime - TimeAlreadyPassed).
        // TimeAlreadyPassed ≈ lastFireDelayUs (time when previous timer fired relative to ZC)
        
        unsigned long deltaUs;
        if (minNextDelay > lastFireDelayUs) {
            deltaUs = minNextDelay - lastFireDelayUs;
        } else {
            deltaUs = 1; // Should fire almost immediately (groups with same brightness)
        }
        
        // DO NOT update lastFireDelayUs here - it will be updated in handleTimerFire()
        // after all channels at this time have fired. This ensures channels with
        // the same or very close delays all fire together.
        
        // Protection against too small values
        if (deltaUs < 10) deltaUs = 10;
        
#ifdef ESP32
        // ESP32: 1MHz timer (80MHz / 80), so 1us = 1 tick
        // CRITICAL: Reset timer counter to 0 before arming
        // Otherwise the alarm will match against a free-running counter that might be way past deltaUs
        timerWrite(timer, 0);
        timerAlarmWrite(timer, deltaUs, false);  // false = one-shot
        timerAlarmEnable(timer);
#else
        // ESP8266: 5MHz timer (80MHz / 16), so 1us = 5 ticks
        unsigned long ticks = deltaUs * 5;
        if (ticks < 10) ticks = 10;
        timer1_write(ticks);
        timer1_enable(TIM_DIV16, TIM_EDGE, TIM_SINGLE);
#endif
        timerArmed = true;
    } else {
#ifdef ESP32
        timerAlarmDisable(timer);
#else
        timer1_disable();
#endif
        timerArmed = false;
    }
}

void IRAM_ATTR DimmingEngine::handleTimerFire() {
    // 1. Read all channel delays atomically to avoid race conditions
    // Store them in local variables to ensure consistent reads
    unsigned long delays[NUM_CHANNELS];
    bool fired[NUM_CHANNELS];
    
    // Atomic read of all channel states
    for (int i = 0; i < NUM_CHANNELS; i++) {
        delays[i] = channelDelayUs[i];
        fired[i] = channelFired[i];
    }
    
    // 2. Find the target delay for this fire event
    // Find the minimum delay among channels that haven't fired yet
    unsigned long targetDelay = HALF_CYCLE_US + 5000;
    bool foundTarget = false;
    
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!fired[i] && delays[i] < HALF_CYCLE_US) {
            if (delays[i] < targetDelay) {
                targetDelay = delays[i];
                foundTarget = true;
            }
        }
    }
    
    // If no target found, no more channels to fire - disable timer
    if (!foundTarget) {
#ifdef ESP32
        timerAlarmDisable(timer);
#else
        timer1_disable();
#endif
        timerArmed = false;
        return;
    }
    
    // 3. Fire ALL channels that should fire at this target delay
    // Use a small tolerance (10us) to account for channels with very close delays
    // This ensures channels with identical or nearly identical delays fire together
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!fired[i] && delays[i] <= targetDelay + 10) {
            digitalWrite(CHANNEL_PINS[i], HIGH);
            channelFired[i] = true;  // Update volatile flag immediately
        }
    }
    
    // Short delay for pulse (blocking, but very short)
    delayMicroseconds(TRIAC_PULSE_US);
    
    // Turn off pins
    for (int i = 0; i < NUM_CHANNELS; i++) {
        digitalWrite(CHANNEL_PINS[i], LOW);
    }
    
    // 4. Update lastFireDelayUs to the target delay we just fired at
    // This is critical - update AFTER firing, not before
    lastFireDelayUs = targetDelay;
    
    // 5. Schedule next fire for less bright channels (those with higher delays)
    scheduleNextFire();
}

// ----------------------------------------------------------------------------
// Main Loop Logic
// ----------------------------------------------------------------------------

void DimmingEngine::update() {
    // Safety watchdog - check if zero-cross signal is still present
    unsigned long now = micros();
    unsigned long elapsed = now - lastZeroCrossUs;
    
    // Emergency logic and RECOVERY
    if (elapsed > ZC_LOST_TIMEOUT_US) {
        if (zcSignalHealthy) {
            zcSignalHealthy = false;
            emergencyOff();
            // Here we only turn off lights, but don't block ZC ISR
        }
    } else {
        // If signal returned
        if (!zcSignalHealthy || emergencyShutoff) {
            zcSignalHealthy = true;
            emergencyShutoff = false; // Clear blocking flag
            DEBUG_PRINTLN("Zero-cross signal recovered!");
        }
    }
}

bool DimmingEngine::isZeroCrossHealthy() {
    return zcSignalHealthy;
}

unsigned long DimmingEngine::getLastZeroCrossUs() {
    return lastZeroCrossUs;
}

unsigned long DimmingEngine::getChannelDelay(uint8_t channel) {
    if (channel >= NUM_CHANNELS) return 0;
    noInterrupts();
    unsigned long delay = channelDelayUs[channel];
    interrupts();
    return delay;
}

uint8_t DimmingEngine::getChannelBrightness(uint8_t channel) {
    if (channel >= NUM_CHANNELS) return 0;
    noInterrupts();
    uint8_t brightness = channelBrightness[channel];
    interrupts();
    return brightness;
}

unsigned long DimmingEngine::getLastFireDelayUs() {
    return lastFireDelayUs;
}

void DimmingEngine::emergencyOff() {
    emergencyShutoff = true;
    allOff();
#ifdef ESP32
    timerAlarmDisable(timer);
#else
    timer1_disable();
#endif
    DEBUG_PRINTLN("WARNING: Zero-cross lost. Emergency OFF.");
}

void DimmingEngine::allOff() {
    for (int i = 0; i < NUM_CHANNELS; i++) {
        digitalWrite(CHANNEL_PINS[i], LOW);
    }
}
