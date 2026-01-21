#include "ModeManager.h"

// Global instance
ModeManager modeManager;

void ModeManager::begin() {
    currentMode = MODE_STATIC;
    memset(&staticFrame, 0, sizeof(staticFrame));
    memset(&plannedFrame, 0, sizeof(plannedFrame));
    memset(&fastFrame, 0, sizeof(fastFrame));
    memset(&currentFrame, 0, sizeof(currentFrame));
    hasStaticFrame = false;
    hasPlannedFrame = false;
    lastUdpPacketMs = 0;
    lastModeChangeMs = millis();
    
    DEBUG_PRINTLN("ModeManager initialized in STATIC mode");
}

void ModeManager::update() {
    checkModeTimeout();
}

void ModeManager::setStaticBrightness(const uint8_t* values, size_t len) {
    if (!values || len == 0) return;

    // Copy into static frame
    DEBUG_PRINT("Setting static brightness: [");
    for (size_t i = 0; i < NUM_CHANNELS; i++) {
        staticFrame.values[i] = (i < len) ? values[i] : 0;
        DEBUG_PRINT(staticFrame.values[i]);
        if (i < NUM_CHANNELS - 1) DEBUG_PRINT(", ");
    }
    DEBUG_PRINTLN("]");
    
    hasStaticFrame = true;

    // Switch to static mode and apply
    currentMode = MODE_STATIC;
    lastModeChangeMs = millis();
    memcpy(currentFrame.values, staticFrame.values, sizeof(currentFrame.values));
    applyBrightness();
}

void ModeManager::setPlannedBrightness(const uint8_t* values, size_t len) {
    if (!values || len == 0) return;

    // Copy into planned frame
    for (size_t i = 0; i < NUM_CHANNELS; i++) {
        plannedFrame.values[i] = (i < len) ? values[i] : 0;
    }
    hasPlannedFrame = true;

    // Only apply if we're in planned mode
    if (currentMode == MODE_PLANNED) {
        memcpy(currentFrame.values, plannedFrame.values, sizeof(currentFrame.values));
        applyBrightness();
    }
}

void ModeManager::setFastBrightness(const uint8_t* values, size_t len) {
    if (!values || len == 0) return;

    // Copy into fast frame
    for (size_t i = 0; i < NUM_CHANNELS; i++) {
        fastFrame.values[i] = (i < len) ? values[i] : 0;
    }
    lastUdpPacketMs = millis();
    
    // Switch to fast mode if not already
    if (currentMode != MODE_FAST) {
        currentMode = MODE_FAST;
        lastModeChangeMs = millis();
        DEBUG_PRINTLN("Switched to FAST mode");
    }
    
    // Apply immediately
    memcpy(currentFrame.values, fastFrame.values, sizeof(currentFrame.values));
    applyBrightness();
}

void ModeManager::checkModeTimeout() {
    // Only check timeout if we're in fast mode
    if (currentMode != MODE_FAST) return;
    
    unsigned long now = millis();
    unsigned long elapsed = now - lastUdpPacketMs;
    
    if (elapsed > UDP_TIMEOUT_MS) {
        // Timeout - revert to static if available, otherwise planned
        if (hasStaticFrame) {
            currentMode = MODE_STATIC;
            memcpy(currentFrame.values, staticFrame.values, sizeof(currentFrame.values));
            DEBUG_PRINTLN("UDP timeout - reverting to STATIC mode");
        } else if (hasPlannedFrame) {
            currentMode = MODE_PLANNED;
            memcpy(currentFrame.values, plannedFrame.values, sizeof(currentFrame.values));
            DEBUG_PRINTLN("UDP timeout - reverting to PLANNED mode");
        } else {
            memset(currentFrame.values, 0, sizeof(currentFrame.values));
            currentMode = MODE_STATIC;
            DEBUG_PRINTLN("UDP timeout - no fallback frame, output OFF");
        }
        lastModeChangeMs = now;
        applyBrightness();
    }
}

void ModeManager::applyBrightness() {
    // Map 0-255 input to 0-9 brightness levels
    for (int i = 0; i < NUM_CHANNELS; i++) {
        uint8_t mapped = map(currentFrame.values[i], 0, 255, 0, 9);
        dimmingEngine.setChannelBrightness(i, mapped);
    }
}

ControlMode ModeManager::getCurrentMode() const {
    return currentMode;
}

const char* ModeManager::getCurrentModeString() const {
    switch (currentMode) {
        case MODE_STATIC:
            return "STATIC";
        case MODE_PLANNED:
            return "PLANNED";
        case MODE_FAST:
            return "FAST";
        default:
            return "UNKNOWN";
    }
}

uint8_t ModeManager::getCurrentBrightnessAvg() const {
    uint16_t sum = 0;
    for (int i = 0; i < NUM_CHANNELS; i++) {
        sum += currentFrame.values[i];
    }
    return (uint8_t)(sum / NUM_CHANNELS);
}

void ModeManager::getCurrentFrame(uint8_t* out, size_t len) const {
    if (!out || len == 0) return;
    for (size_t i = 0; i < len && i < NUM_CHANNELS; i++) {
        out[i] = currentFrame.values[i];
    }
}

void ModeManager::forceMode(ControlMode mode) {
    if (currentMode == mode) return;

    currentMode = mode;
    lastModeChangeMs = millis();

    DEBUG_PRINT("Force switched to mode: ");
    DEBUG_PRINTLN(getCurrentModeString());

    // Apply appropriate brightness
    switch (mode) {
        case MODE_STATIC:
            memcpy(currentFrame.values, staticFrame.values, sizeof(currentFrame.values));
            break;
        case MODE_PLANNED:
            memcpy(currentFrame.values, plannedFrame.values, sizeof(currentFrame.values));
            break;
        case MODE_FAST:
            memcpy(currentFrame.values, fastFrame.values, sizeof(currentFrame.values));
            break;
    }
    applyBrightness();
}

