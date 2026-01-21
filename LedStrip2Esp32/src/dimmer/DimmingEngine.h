#ifndef DIMMING_ENGINE_H
#define DIMMING_ENGINE_H

#include <Arduino.h>
#include "../config/Config.h"
#ifdef ESP32
#include "esp32-hal-timer.h"
#endif

// ============================================================================
// DimmingEngine: Interrupt-driven AC phase control
// ============================================================================
// Handles zero-cross detection, timer-based triac firing, and safety watchdog

class DimmingEngine {
public:
    // Initialize the dimming engine
    void begin();
    
    // Set target brightness for all channels (0-9)
    void setBrightness(uint8_t brightness);
    
    // Set individual channel brightness (0-9)
    void setChannelBrightness(uint8_t channel, uint8_t brightness);
    
    // Check if zero-cross signal is healthy
    bool isZeroCrossHealthy();
    
    // Safety check - call from main loop
    void update();
    
    // Get last zero-cross timestamp
    unsigned long getLastZeroCrossUs();
    
    // Get current channel delay (for debugging)
    unsigned long getChannelDelay(uint8_t channel);
    
    // Get current channel brightness (for debugging)
    uint8_t getChannelBrightness(uint8_t channel);
    
    // Get last fire delay (for debugging)
    unsigned long getLastFireDelayUs();

    // Emergency shutoff
    void emergencyOff();
    
    // ISR handlers (must be public for attachInterrupt)
    void IRAM_ATTR handleZeroCross();
    void IRAM_ATTR handleTimerFire();
    
private:
    // Current brightness values (0-255) for each channel
    volatile uint8_t channelBrightness[NUM_CHANNELS] = {0};
    
    // Delay values in microseconds for each channel
    volatile unsigned long channelDelayUs[NUM_CHANNELS] = {0};
    
    // Zero-cross tracking
    volatile unsigned long lastZeroCrossUs = 0;
    volatile bool zcSignalHealthy = true;
    
    // Safety state
    volatile bool emergencyShutoff = false;
    
    // Timer state
    volatile bool timerArmed = false;
#ifdef ESP32
    hw_timer_t* timer = nullptr;
#endif
    
    // Multi-channel firing tracking
    volatile bool channelFired[NUM_CHANNELS] = {false};
    volatile unsigned long lastFireDelayUs = 0;  // Time of last fire event in current half-cycle
    
    // Convert brightness (0-9) to delay in microseconds
    unsigned long brightnessToDelayUs(uint8_t brightness);
    
    // Schedule next channel to fire in current half-cycle
    void IRAM_ATTR scheduleNextFire();
    
    // Turn off all outputs immediately
    void allOff();
};

// Global instance
extern DimmingEngine dimmingEngine;

// ISR wrappers for global interrupt handlers
void IRAM_ATTR zeroCrossISR();
void IRAM_ATTR timerISR();

#endif // DIMMING_ENGINE_H

