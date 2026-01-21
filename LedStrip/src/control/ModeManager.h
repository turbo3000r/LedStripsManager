#ifndef MODE_MANAGER_H
#define MODE_MANAGER_H

#include <Arduino.h>
#include "../config/Config.h"
#include "../dimmer/DimmingEngine.h"

// ============================================================================
// ModeManager: Coordinates between Static (MQTT), Planned (MQTT), and Fast (UDP)
// ============================================================================

enum ControlMode {
    MODE_STATIC,    // MQTT static frame
    MODE_PLANNED,   // MQTT scheduled control
    MODE_FAST       // UDP immediate control
};

struct BrightnessFrame {
    uint8_t values[NUM_CHANNELS] = {0};
};

class ModeManager {
public:
    // Initialize the mode manager
    void begin();
    
    // Update the mode manager (call from main loop)
    void update();
    
    // Set brightness from Static mode (MQTT)
    void setStaticBrightness(const uint8_t* values, size_t len);

    // Set brightness from Planned mode (MQTT schedule)
    void setPlannedBrightness(const uint8_t* values, size_t len);
    
    // Set brightness from Fast mode (UDP)
    void setFastBrightness(const uint8_t* values, size_t len);
    
    // Get current control mode
    ControlMode getCurrentMode() const;
    
    // Get current mode as string
    const char* getCurrentModeString() const;
    
    // Get current effective brightness (average of channels)
    uint8_t getCurrentBrightnessAvg() const;

    // Get copy of current frame
    void getCurrentFrame(uint8_t* out, size_t len) const;
    
    // Force mode switch (for testing/debugging)
    void forceMode(ControlMode mode);
    
private:
    ControlMode currentMode = MODE_STATIC;
    BrightnessFrame staticFrame;
    BrightnessFrame plannedFrame;
    BrightnessFrame fastFrame;
    BrightnessFrame currentFrame;

    bool hasStaticFrame = false;
    bool hasPlannedFrame = false;

    unsigned long lastUdpPacketMs = 0;
    unsigned long lastModeChangeMs = 0;

    // Apply current brightness to dimming engine
    void applyBrightness();

    // Check for mode timeout (for FAST -> fallback)
    void checkModeTimeout();
};

// Global instance
extern ModeManager modeManager;

#endif // MODE_MANAGER_H

