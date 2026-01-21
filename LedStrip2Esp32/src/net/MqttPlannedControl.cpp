#include "MqttPlannedControl.h"
#include <vector>
#include <sys/time.h>
#ifdef ESP32
#include <WiFi.h>
#else
#include <ESP8266WiFi.h>
#endif

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
    mqttClient.setBufferSize(4096);  // Increased for sequence payloads
    
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
    
    // Handle MQTT connection
    if (!mqttClient.connected()) {
        unsigned long now = millis();
        if (now - lastReconnectAttempt > MQTT_RECONNECT_INTERVAL_MS) {
            lastReconnectAttempt = now;
            if (reconnect()) {
                lastReconnectAttempt = 0;
            }
        }
    } else {
        mqttClient.loop();

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
    
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
        DEBUG_PRINTLN("connected");
        
        // Subscribe to static and plan topics
        mqttClient.subscribe(MQTT_TOPIC_SET_STATIC);
        mqttClient.subscribe(MQTT_TOPIC_SET_PLAN);
        DEBUG_PRINT("Subscribed to: ");
        DEBUG_PRINTLN(MQTT_TOPIC_SET_STATIC);
        DEBUG_PRINT("Subscribed to: ");
        DEBUG_PRINTLN(MQTT_TOPIC_SET_PLAN);
        
        // Publish heartbeat immediately on connect
        publishHeartbeat();
        
        return true;
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

bool MqttPlannedControl::extractValuesFromJson(JsonArray valuesArray, uint8_t* values, size_t maxLen) {
    // Accept arrays with >= NUM_CHANNELS values (use first NUM_CHANNELS)
    // This allows servers to send more channels than the device supports
    if (valuesArray.size() < NUM_CHANNELS) return false;

    for (size_t ch = 0; ch < NUM_CHANNELS; ch++) {
        values[ch] = valuesArray[ch].as<uint8_t>();
    }
    return true;
}

void MqttPlannedControl::handlePlanMessage(byte* payload, unsigned int length) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload, length);
    if (error) {
        DEBUG_PRINT("JSON parse error (plan): ");
        DEBUG_PRINTLN(error.c_str());
        return;
    }
    
    // FORMAT 1: format_version 2 (NEW - highest priority)
    if (!doc["format_version"].isNull() && doc["format_version"].as<int>() == 2) {
        JsonArray stepsArray = doc["steps"];
        if (stepsArray.isNull()) return;

        size_t addedCount = 0;
        uint8_t values[NUM_CHANNELS];

        for (JsonVariant stepVar : stepsArray) {
            if (!stepVar.is<JsonObject>()) continue;

            JsonObject stepObj = stepVar.as<JsonObject>();
            if (stepObj["ts_ms"].isNull() || stepObj["values"].isNull()) continue;

            uint64_t execTimestamp = stepObj["ts_ms"].as<uint64_t>();
            if (!extractValuesFromJson(stepObj["values"], values, NUM_CHANNELS)) continue;

            if (schedulePlayer.addCommand(execTimestamp, values, NUM_CHANNELS)) {
                addedCount++;
            }
        }

        if (addedCount > 0) {
            modeManager.forceMode(MODE_PLANNED);
        }
        return;
    }
    
    // FORMAT 2: commands array (duration-based or absolute timestamps)
    if (!doc["commands"].isNull()) {
        JsonArray commandsArray = doc["commands"];

        // Determine base timestamp
        uint64_t baseTimestamp = 0;
        if (!doc["base_timestamp"].isNull()) {
            baseTimestamp = (uint64_t)doc["base_timestamp"].as<unsigned long>() * 1000ULL;
        } else {
            struct timeval tv;
            gettimeofday(&tv, nullptr);
            baseTimestamp = (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)(tv.tv_usec / 1000);
        }

        uint64_t currentTimestamp = baseTimestamp;
        uint8_t values[NUM_CHANNELS];

        for (JsonVariant cmdVar : commandsArray) {
            if (!cmdVar.is<JsonObject>()) continue;

            JsonObject cmdObj = cmdVar.as<JsonObject>();
            uint64_t execTimestamp = 0;

            // Determine execution timestamp
            if (!cmdObj["timestamp"].isNull()) {
                execTimestamp = (uint64_t)cmdObj["timestamp"].as<unsigned long>() * 1000ULL;
            } else if (!cmdObj["duration_ms"].isNull()) {
                execTimestamp = currentTimestamp + cmdObj["duration_ms"].as<unsigned long>();
                currentTimestamp = execTimestamp;
            } else {
                continue;
            }

            if (!extractValuesFromJson(cmdObj["values"], values, NUM_CHANNELS)) continue;
            schedulePlayer.addCommand(execTimestamp, values, NUM_CHANNELS);
        }

        modeManager.forceMode(MODE_PLANNED);
        return;
    }
    
    // FORMAT 3: Legacy sequence format
    if (!doc["sequence"].isNull()) {
        if (doc["timestamp"].isNull() || doc["interval_ms"].isNull()) return;

        JsonArray seqArray = doc["sequence"];
        if (seqArray.isNull()) return;

        schedulePlayer.clearSchedule();

        uint64_t currentTimestamp = (uint64_t)doc["timestamp"].as<unsigned long>() * 1000ULL;
        unsigned int stepInterval = doc["interval_ms"];
        uint8_t values[NUM_CHANNELS];

        for (JsonVariant stepVar : seqArray) {
            if (!stepVar.is<JsonArray>()) continue;
            if (!extractValuesFromJson(stepVar.as<JsonArray>(), values, NUM_CHANNELS)) continue;

            schedulePlayer.addCommand(currentTimestamp, values, NUM_CHANNELS);
            currentTimestamp += stepInterval;
        }

        modeManager.forceMode(MODE_PLANNED);
    }
}

void MqttPlannedControl::updatePlannedBrightness() {
    // Only update if we're in planned mode and time is synced
    if (!timeSynced) return;
    if (modeManager.getCurrentMode() != MODE_PLANNED) return;
    
    if (schedulePlayer.hasValidSchedule()) {
        uint8_t frame[NUM_CHANNELS] = {0};
        
        // With the fix in SchedulePlayer, we should ALWAYS get a frame if schedule is valid
        // (even before start time - it returns first step for "arming")
        if (schedulePlayer.getCurrentFrame(frame, NUM_CHANNELS)) {
            modeManager.setPlannedBrightness(frame, NUM_CHANNELS);
        } else {
            // Safety: if schedule exists but frame calculation failed (shouldn't happen),
            // we could turn off lights, but with the fix above this case is unlikely
            // Uncomment below if you want to force-off on error:
            // memset(frame, 0, NUM_CHANNELS);
            // modeManager.setPlannedBrightness(frame, NUM_CHANNELS);
        }
    }
}

void MqttPlannedControl::publishHeartbeat() {
    if (!mqttClient.connected()) return;

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

