#ifndef OTA_H
#define OTA_H

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ArduinoOTA.h>
#include "config/Config.h"

// ============================================================================
// WiFi and OTA Setup
// ============================================================================

bool setupWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    DEBUG_PRINT("Connecting to WiFi");
    
    unsigned long startAttempt = millis();
    
    while (WiFi.status() != WL_CONNECTED) {
        // Check for timeout
        if (millis() - startAttempt > WIFI_CONNECT_TIMEOUT_MS) {
            DEBUG_PRINTLN("\nWiFi connection timeout!");
            return false;
        }
        
        delay(500);
        DEBUG_PRINT(".");
    }
    
    DEBUG_PRINTLN("\nWiFi connected");
    DEBUG_PRINT("IP address: ");
    DEBUG_PRINTLN(WiFi.localIP());
    DEBUG_PRINT("MAC address: ");
    DEBUG_PRINTLN(WiFi.macAddress());

    
    return true;
}

void setupOTA() {
    // Set hostname
    ArduinoOTA.setHostname(OTA_HOSTNAME);
    
    // Optional: Set password for OTA
    // ArduinoOTA.setPassword("admin");
    
    // OTA callbacks for debugging
    ArduinoOTA.onStart([]() {
        String type;
        if (ArduinoOTA.getCommand() == U_FLASH) {
            type = "sketch";
        } else {  // U_FS
            type = "filesystem";
        }
        DEBUG_PRINTLN("OTA: Start updating " + type);
    });
    
    ArduinoOTA.onEnd([]() {
        DEBUG_PRINTLN("\nOTA: Update complete");
    });
    
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        DEBUG_PRINT("OTA Progress: ");
        DEBUG_PRINT(progress / (total / 100));
        DEBUG_PRINTLN("%");
    });
    
    ArduinoOTA.onError([](ota_error_t error) {
        DEBUG_PRINT("OTA Error: ");
        DEBUG_PRINTLN(error);
    });
    
    ArduinoOTA.begin();
    DEBUG_PRINTLN("OTA ready");
}

#endif // OTA_H
