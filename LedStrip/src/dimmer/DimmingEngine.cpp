#include "DimmingEngine.h"

// Global instance
DimmingEngine dimmingEngine;

// Static ISR buffers (avoid stack allocation in ISRs)
unsigned long DimmingEngine::isrDelays[NUM_CHANNELS];
bool DimmingEngine::isrFired[NUM_CHANNELS];

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
    
    // Initialize Timer1 (will be armed on zero-cross)
    timer1_attachInterrupt(timerISR);
    timer1_disable();  // Start disabled
    
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
    // Filter noise - reject interrupts that come too quickly
    unsigned long now = micros();
    unsigned long elapsed = now - lastZeroCrossUs;
    
    // For 50Hz, minimum half-cycle is ~9.5ms, reject anything faster (use 8ms for safety)
    if (elapsed < 9500) {
        return;
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
    // Read channel states atomically to avoid race conditions (use static buffers)
    for (int i = 0; i < NUM_CHANNELS; i++) {
        isrDelays[i] = channelDelayUs[i];
        isrFired[i] = channelFired[i];
    }
    
    unsigned long minNextDelay = HALF_CYCLE_US + 5000;
    bool foundPending = false;

    // Find minimum delay among channels that haven't fired yet
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!isrFired[i] && isrDelays[i] < HALF_CYCLE_US) {
            if (isrDelays[i] < minNextDelay) {
                minNextDelay = isrDelays[i];
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
        
        // Convert to ticks (5MHz timer: 1us = 5 ticks)
        unsigned long ticks = deltaUs * 5;
        
        // Protection against too small values
        if (ticks < 10) ticks = 10;
        
        timer1_write(ticks);
        timer1_enable(TIM_DIV16, TIM_EDGE, TIM_SINGLE);
        timerArmed = true;
    } else {
        timer1_disable();
        timerArmed = false;
    }
}

void IRAM_ATTR DimmingEngine::handleTimerFire() {
    // 1. Read all channel delays atomically to avoid race conditions
    // Store them in static buffers to ensure consistent reads and avoid stack allocation
    for (int i = 0; i < NUM_CHANNELS; i++) {
        isrDelays[i] = channelDelayUs[i];
        isrFired[i] = channelFired[i];
    }
    
    // 2. Find the target delay for this fire event
    // Find the minimum delay among channels that haven't fired yet
    unsigned long targetDelay = HALF_CYCLE_US + 5000;
    bool foundTarget = false;

    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!isrFired[i] && isrDelays[i] < HALF_CYCLE_US) {
            if (isrDelays[i] < targetDelay) {
                targetDelay = isrDelays[i];
                foundTarget = true;
            }
        }
    }
    
    // If no target found, no more channels to fire - disable timer
    if (!foundTarget) {
        timer1_disable();
        timerArmed = false;
        return;
    }
    
    // 3. Fire ALL channels that should fire at this target delay
    // Use a small tolerance (10us) to account for channels with very close delays
    // This ensures channels with identical or nearly identical delays fire together
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (!isrFired[i] && isrDelays[i] <= targetDelay + 10) {
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

void DimmingEngine::emergencyOff() {
    emergencyShutoff = true;
    allOff();
    timer1_disable();
    DEBUG_PRINTLN("WARNING: Zero-cross lost. Emergency OFF.");
}

void DimmingEngine::allOff() {
    for (int i = 0; i < NUM_CHANNELS; i++) {
        digitalWrite(CHANNEL_PINS[i], LOW);
    }
}
