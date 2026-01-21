#include "MqttPlannedControl.h"
#include <vector>
#include <ESP8266WiFi.h>
#include <sys/time.h>

// Global instance
MqttPlannedControl mqttPlannedControl;

// Static callback needs access to the instance
static MqttPlannedControl* mqttInstancePtr = nullptr;

void MqttPlannedControl::begin() {
    mqttInstancePtr = this;
    
    // Initialize MQTT client
    mqttClient.setClient(wifiClient);
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setBufferSize(1024);  // Reduced for memory efficiency
    mqttClient.setKeepAlive(60);  // 60 second keepalive to maintain connection
    mqttClient.setSocketTimeout(15);  // 15 second socket timeout
    
    // Initialize NTP
    initTimeSync();
    
    DEBUG_PRINTLN("MQTT Planned Control initialized");
}

void MqttPlannedControl::initTimeSync() {
    // Configure NTP time sync
    configTime(NTP_TZ_OFFSET_SEC, NTP_DST_OFFSET_SEC, NTP_SERVER_1, NTP_SERVER_2);
    
    DEBUG_PRINTLN("NTP time sync started");
}

bool MqttPlannedControl::checkTimeValid() {
    time_t now = time(nullptr);
    
    if (now > TIME_VALID_EPOCH && !timeSynced) {
        timeSynced = true;
        struct tm timeinfo;
        localtime_r(&now, &timeinfo);
        
        DEBUG_PRINT("Time synced: ");
        DEBUG_PRINTLN(asctime(&timeinfo));
    }
    
    return timeSynced;
}

void MqttPlannedControl::update() {
    // Check time sync status
    checkTimeValid();
    
    // Always call loop() to maintain connection and process messages
    mqttClient.loop();
    
    // Handle MQTT connection
    if (!mqttClient.connected()) {
        connectionStable = false;
        unsigned long now = millis();
        
        // Only attempt reconnect if enough time has passed since last attempt
        // AND enough time has passed since last successful connection (to avoid rapid reconnects)
        if (now - lastReconnectAttempt > MQTT_RECONNECT_INTERVAL_MS &&
            now - lastConnectionTime > 1000) {  // Wait at least 1 second after last connection
            lastReconnectAttempt = now;
            if (reconnect()) {
                lastReconnectAttempt = 0;
                lastConnectionTime = now;
                connectionStable = true;
            }
        }
    } else {
        // Connection is active
        if (!connectionStable) {
            // Just connected, mark as stable after a brief period
            unsigned long now = millis();
            if (now - lastConnectionTime > 500) {  // 500ms stabilization period
                connectionStable = true;
            }
        }
        
        // Update planned brightness from schedule
        updatePlannedBrightness();

        // Publish heartbeat
        unsigned long now = millis();
        if (now - lastHeartbeatPublish > HEARTBEAT_PERIOD_MS) {
            lastHeartbeatPublish = now;
            publishHeartbeat();
        }
    }
}

bool MqttPlannedControl::reconnect() {
    DEBUG_PRINT("Attempting MQTT connection...");
    
    // Disconnect any existing connection first to ensure clean state
    if (mqttClient.connected()) {
        mqttClient.disconnect();
    }
    
    // Attempt connection
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
        DEBUG_PRINTLN("connected");
        
        // Subscribe to static and plan topics
        bool sub1 = mqttClient.subscribe(MQTT_TOPIC_SET_STATIC);
        bool sub2 = mqttClient.subscribe(MQTT_TOPIC_SET_PLAN);
        
        if (sub1 && sub2) {
            DEBUG_PRINT("Subscribed to: ");
            DEBUG_PRINTLN(MQTT_TOPIC_SET_STATIC);
            DEBUG_PRINT("Subscribed to: ");
            DEBUG_PRINTLN(MQTT_TOPIC_SET_PLAN);
            
            // Call loop() to process any immediate messages and maintain connection
            mqttClient.loop();
            
            // Publish heartbeat immediately on connect
            publishHeartbeat();
            
            return true;
        } else {
            DEBUG_PRINTLN("Subscription failed");
            mqttClient.disconnect();
            return false;
        }
    } else {
        DEBUG_PRINT("failed, rc=");
        DEBUG_PRINTLN(mqttClient.state());
        return false;
    }
}

void MqttPlannedControl::mqttCallback(char* topic, byte* payload, unsigned int length) {
    if (mqttInstancePtr == nullptr) return;
    
    DEBUG_PRINT("MQTT message received on topic: ");
    DEBUG_PRINTLN(topic);
    
    // Handle plan or static messages
    if (strcmp(topic, MQTT_TOPIC_SET_PLAN) == 0) {
        mqttInstancePtr->handlePlanMessage(payload, length);
    } else if (strcmp(topic, MQTT_TOPIC_SET_STATIC) == 0) {
        mqttInstancePtr->handleStaticMessage(payload, length);
    }
}

void MqttPlannedControl::handleStaticMessage(byte* payload, unsigned int length) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload, length);
    if (error) {
        DEBUG_PRINT("JSON parse error (static): ");
        DEBUG_PRINTLN(error.c_str());
        return;
    }

    if (doc["values"].isNull()) {
        DEBUG_PRINTLN("Static payload missing values");
        return;
    }

    JsonArray valuesArray = doc["values"];
    size_t count = valuesArray.size();
    if (count == 0) {
        DEBUG_PRINTLN("Static values empty");
        return;
    }

    uint8_t frame[NUM_CHANNELS] = {0};
    DEBUG_PRINT("Static values: [");
    for (size_t i = 0; i < NUM_CHANNELS && i < count; i++) {
        frame[i] = valuesArray[i].as<uint8_t>();
        DEBUG_PRINT(frame[i]);
        if (i < NUM_CHANNELS - 1 && i < count - 1) DEBUG_PRINT(", ");
    }
    DEBUG_PRINTLN("]");

    modeManager.setStaticBrightness(frame, NUM_CHANNELS);
    DEBUG_PRINTLN("Static brightness applied");
}

void MqttPlannedControl::handlePlanMessage(byte* payload, unsigned int length) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload, length);
    if (error) {
        DEBUG_PRINT("JSON parse error (plan): ");
        DEBUG_PRINTLN(error.c_str());
        return;
    }

    // Check for format_version 2 (new format with ready-to-use timestamps)
    if (!doc["format_version"].isNull() && doc["format_version"].as<int>() == 2) {
        // Format version 2: steps with ts_ms (millisecond timestamps)
        if (doc["steps"].isNull()) {
            DEBUG_PRINTLN("Format v2 missing steps array");
            return;
        }
        
        JsonArray stepsArray = doc["steps"];
        if (stepsArray.size() == 0) {
            DEBUG_PRINTLN("Steps array is empty");
            return;
        }
        
        size_t addedCount = 0;
        
        for (JsonVariant stepVar : stepsArray) {
            if (!stepVar.is<JsonObject>()) {
                DEBUG_PRINTLN("Step is not an object");
                continue;
            }
            
            JsonObject stepObj = stepVar.as<JsonObject>();
            
            // Get timestamp in milliseconds (already absolute, ready to use)
            if (stepObj["ts_ms"].isNull()) {
                DEBUG_PRINTLN("Step missing ts_ms");
                continue;
            }
            
            // ts_ms is already in milliseconds, use directly
            uint64_t execTimestamp = stepObj["ts_ms"].as<uint64_t>();
            
            // Get values array
            if (stepObj["values"].isNull()) {
                DEBUG_PRINTLN("Step missing values");
                continue;
            }
            
            JsonArray valuesArray = stepObj["values"];
            if (valuesArray.size() < NUM_CHANNELS) {
                DEBUG_PRINTLN("Step has fewer channels than expected");
                continue;
            }
            
            // Extract values
            uint8_t values[NUM_CHANNELS];
            for (size_t ch = 0; ch < NUM_CHANNELS; ch++) {
                values[ch] = valuesArray[ch].as<uint8_t>();
            }
            
            // Add command to schedule (timestamp is already in milliseconds)
            if (schedulePlayer.addCommand(execTimestamp, values, NUM_CHANNELS)) {
                addedCount++;
            }
        }
        
        if (addedCount > 0) {
            DEBUG_PRINT("Added ");
            DEBUG_PRINT(addedCount);
            DEBUG_PRINTLN(" steps to schedule (format v2)");
            
            // Switch to planned mode when steps are added
            modeManager.forceMode(MODE_PLANNED);
            DEBUG_PRINTLN("Switched to PLANNED mode");
        } else {
            DEBUG_PRINTLN("No steps were added");
        }
        
        return;  // Format v2 handled, exit early
    }

    // Only format v2 is supported - reject legacy formats
    DEBUG_PRINTLN("Unsupported plan format - only format_version 2 is supported");
}

void MqttPlannedControl::updatePlannedBrightness() {
    // Only update if we're in planned mode and time is synced
    if (!timeSynced) return;
    if (modeManager.getCurrentMode() != MODE_PLANNED) return;
    
    if (schedulePlayer.hasValidSchedule()) {
        uint8_t frame[NUM_CHANNELS] = {0};
        
        // Get current frame from schedule player (executes commands at their precise time)
        if (schedulePlayer.getCurrentFrame(frame, NUM_CHANNELS)) {
            modeManager.setPlannedBrightness(frame, NUM_CHANNELS);
        }
        // If no frame is available yet (no commands executed), keep current brightness
    }
}

void MqttPlannedControl::publishHeartbeat() {
    if (!mqttClient.connected()) return;

    // Reduced debug output - heartbeat publishing is verbose
    static unsigned long lastHeartbeatDebug = 0;
    unsigned long now = millis();
    bool shouldDebug = (now - lastHeartbeatDebug > 30000); // Debug at most once per 30 seconds
    if (shouldDebug) {
        lastHeartbeatDebug = now;
    }

    char payload[256];
    IPAddress ip = WiFi.localIP();
    snprintf(payload, sizeof(payload),
             "{\"device_id\":\"%s\",\"uptime\":%lu,\"firmware\":\"%s\",\"ip\":\"%d.%d.%d.%d\",\"mode\":\"%s\"}",
             DEVICE_ID,
             millis() / 1000UL,
             FIRMWARE_VERSION,
             ip[0], ip[1], ip[2], ip[3],
             modeManager.getCurrentModeString());

    mqttClient.publish(MQTT_TOPIC_HEARTBEAT, payload);

    if (shouldDebug) {
        DEBUG_PRINT("Heartbeat published: uptime=");
        DEBUG_PRINTLN(millis() / 1000UL);
    }
}

bool MqttPlannedControl::isConnected() {
    return mqttClient.connected();
}

bool MqttPlannedControl::isTimeSynced() {
    return timeSynced;
}

unsigned long MqttPlannedControl::getCurrentTimestamp() {
    return (unsigned long)time(nullptr);
}

