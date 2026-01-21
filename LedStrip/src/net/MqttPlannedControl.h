#ifndef MQTT_PLANNED_CONTROL_H
#define MQTT_PLANNED_CONTROL_H

#include <Arduino.h>
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "../config/Config.h"
#include "../control/SchedulePlayer.h"
#include "../control/ModeManager.h"

// ============================================================================
// MqttPlannedControl: MQTT client with NTP time sync for scheduled control
// ============================================================================

class MqttPlannedControl {
public:
    // Initialize MQTT and NTP
    void begin();
    
    // Update MQTT (call from main loop)
    void update();
    
    // Check if MQTT is connected
    bool isConnected();
    
    // Check if time is synced
    bool isTimeSynced();
    
    // Publish status/heartbeat message
    void publishHeartbeat();
    
    // Get current Unix timestamp
    unsigned long getCurrentTimestamp();
    
private:
    WiFiClient wifiClient;
    PubSubClient mqttClient;
    
    bool timeSynced = false;
    unsigned long lastReconnectAttempt = 0;
    unsigned long lastHeartbeatPublish = 0;
    bool connectionStable = false;  // Track if connection is stable
    unsigned long lastConnectionTime = 0;  // Track when we last successfully connected
    
    // MQTT callback for incoming messages
    static void mqttCallback(char* topic, byte* payload, unsigned int length);
    
    // Handle incoming static message
    void handleStaticMessage(byte* payload, unsigned int length);

    // Handle incoming plan message
    void handlePlanMessage(byte* payload, unsigned int length);
    
    // Connect/reconnect to MQTT broker
    bool reconnect();
    
    // Initialize NTP time sync
    void initTimeSync();
    
    // Check if time is valid
    bool checkTimeValid();
    
    // Update planned brightness from schedule
    void updatePlannedBrightness();
};

// Global instance
extern MqttPlannedControl mqttPlannedControl;

#endif // MQTT_PLANNED_CONTROL_H

