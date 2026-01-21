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

// ESP32 dual-core task stubs (for future implementation)
#ifdef ESP32
// Task handles for ESP32 dual-core operation
TaskHandle_t networkTaskHandle = NULL;
TaskHandle_t controlTaskHandle = NULL;

// Network task (Core 0) - handles WiFi, MQTT, UDP
void networkTask(void* parameter) {
    for (;;) {
        ArduinoOTA.handle();
        mqttPlannedControl.update();
        udpFastControl.update();
        
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}

// Control task (Core 1) - handles dimming logic and mode management
void controlTask(void* parameter) {
    for (;;) {
        dimmingEngine.update();
        modeManager.update();
        
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}
#endif

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
    
#ifdef ESP32
    // Create FreeRTOS tasks for dual-core operation
    DEBUG_PRINTLN("Creating ESP32 dual-core tasks...");
    
    // Network task on Core 0
    xTaskCreatePinnedToCore(
        networkTask,
        "NetworkTask",
        4096,
        NULL,
        1,
        &networkTaskHandle,
        0  // Core 0
    );
    
    // Control task on Core 1
    xTaskCreatePinnedToCore(
        controlTask,
        "ControlTask",
        4096,
        NULL,
        2,  // Higher priority
        &controlTaskHandle,
        1  // Core 1
    );
    
    DEBUG_PRINTLN("ESP32 tasks created");
#endif
    
    DEBUG_PRINTLN("=================================");
    DEBUG_PRINTLN("System ready!");
    DEBUG_PRINTLN("=================================\n");
}

void loop() {
#ifdef ESP32
    // On ESP32, tasks handle everything
    // Main loop just yields, but we can use it for status reporting
    
    static unsigned long lastDebugTime = 0;
    if (millis() - lastDebugTime > 5000) {
        lastDebugTime = millis();
        DEBUG_PRINTLN("\n--- Status Report ---");
        DEBUG_PRINT("ZC Healthy: ");
        DEBUG_PRINTLN(dimmingEngine.isZeroCrossHealthy() ? "YES" : "NO");
        DEBUG_PRINT("Last ZC (us): ");
        DEBUG_PRINTLN(dimmingEngine.getLastZeroCrossUs());
        DEBUG_PRINT("Last Fire Delay (us): ");
        DEBUG_PRINTLN(dimmingEngine.getLastFireDelayUs());
        
        DEBUG_PRINT("Channel Brightness: [");
        for (int i=0; i<NUM_CHANNELS; i++) {
            DEBUG_PRINT(dimmingEngine.getChannelBrightness(i));
            if (i<NUM_CHANNELS-1) DEBUG_PRINT(", ");
        }
        DEBUG_PRINTLN("]");
        
        DEBUG_PRINT("Channel Delays: [");
        for (int i=0; i<NUM_CHANNELS; i++) {
            DEBUG_PRINT(dimmingEngine.getChannelDelay(i));
            if (i<NUM_CHANNELS-1) DEBUG_PRINT(", ");
        }
        DEBUG_PRINTLN("]");
        DEBUG_PRINTLN("---------------------\n");
    }
    
    delay(100);
#else
    // ESP8266 single-core: run everything in main loop
    
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
#endif
}
