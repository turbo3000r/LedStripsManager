#include <Arduino.h>
#include "config/Config.h"
#include "ota.h"
#include "dimmer/DimmingEngine.h"
#include "control/ModeManager.h"
#include "control/SchedulePlayer.h"
#include "net/MqttPlannedControl.h"
#include "net/UdpFastControl.h"

// ============================================================================
// AC Phase Control Dimmer - ESP8266/ESP32
// ============================================================================
// Architecture:
// - DimmingEngine: Interrupt-driven phase control with zero-cross detection
// - ModeManager: Coordinates between Planned (MQTT) and Fast (UDP) modes
// - SchedulePlayer: Time-based brightness interpolation
// - MqttPlannedControl: NTP sync + MQTT schedule receiver
// - UdpFastControl: UDP immediate brightness control
// ============================================================================

// ESP32 dual-core support removed for stability - single-core operation only

void setup() {
    Serial.begin(SERIAL_BAUD_RATE);
    delay(100);
    
    DEBUG_PRINTLN("\n\n=================================");
    DEBUG_PRINTLN("AC Phase Control Dimmer");
    DEBUG_PRINTLN("=================================");
    
    // Initialize WiFi
    if (!setupWiFi()) {
        DEBUG_PRINTLN("ERROR: WiFi setup failed!");
        DEBUG_PRINTLN("Restarting in 5 seconds...");
        delay(5000);
        ESP.restart();
    }
    
    // Initialize OTA
    setupOTA();
    
    // Initialize dimming engine (hardware interrupts)
    DEBUG_PRINTLN("Initializing dimming engine...");
    dimmingEngine.begin();
    
    // Initialize mode manager
    DEBUG_PRINTLN("Initializing mode manager...");
    modeManager.begin();
    
    // Initialize schedule player
    DEBUG_PRINTLN("Initializing schedule player...");
    schedulePlayer.begin();
    
    // Initialize MQTT planned control
    DEBUG_PRINTLN("Initializing MQTT control...");
    mqttPlannedControl.begin();
    
    // Initialize UDP fast control
    DEBUG_PRINTLN("Initializing UDP control...");
    udpFastControl.begin();

    DEBUG_PRINTLN("=================================");
    DEBUG_PRINTLN("System ready!");
    DEBUG_PRINTLN("=================================\n");
}

void loop() {
    // Handle OTA
    ArduinoOTA.handle();

    // Update dimming engine (safety watchdog)
    dimmingEngine.update();

    // Update mode manager (timeout checks)
    modeManager.update();

    // Update MQTT (connection, messages, NTP sync)
    mqttPlannedControl.update();

    // Update UDP (receive packets)
    udpFastControl.update();

    // Small delay to prevent watchdog timeout
    // All modules use non-blocking operations
    delay(10);
}
