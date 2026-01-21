#ifndef CONFIG_H
#define CONFIG_H

#include "secrets.h"

// ============================================================================
// Platform Detection
// ============================================================================
#if defined(ESP32)
  #define IS_DUAL_CORED true
#else
  #define IS_DUAL_CORED false
#endif

// ============================================================================
// Hardware Configuration
// ============================================================================

// Pin assignments for LED channels (Green, Yellow, Blue, Red)
// CHANGED Yellow from 14 to 0 (D3) because Pin 14 (HSCLK) cannot handle short pulses
// REQUIRED: Move Yellow wire from D5 to D3
constexpr int CHANNEL_PINS[4] = {4, 14, 12, 5};
constexpr int NUM_CHANNELS = 4;

// Zero-cross detection pin
constexpr int ZERO_CROSS_PIN = 13;

// ============================================================================
// AC Phase Control Parameters
// ============================================================================

// AC frequency parameters (50Hz default)
constexpr unsigned long HALF_CYCLE_US = 10000;  // 10ms for 50Hz
constexpr unsigned int MIN_DELAY_US = 100;      // Minimum safe delay
constexpr unsigned int GUARD_US = 500;          // Guard band at end of cycle
constexpr unsigned int TRIAC_PULSE_US = 500;    // Triac gate pulse width (Increased from 50us for reliability)

// Zero-cross lost detection timeout (safety)
constexpr unsigned long ZC_LOST_TIMEOUT_US = 100000;  // 100ms

// Brightness resolution (0-9 levels, mapped from 0-255 input)
constexpr int BRIGHTNESS_LEVELS = 10;  // 0-9

// ============================================================================
// WiFi Configuration
// ============================================================================
// WiFi credentials and OTA hostname are defined in secrets.h

// Device identification for telemetry/heartbeat
static constexpr const char* DEVICE_ID = "esp_livingroom_1";
static constexpr const char* FIRMWARE_VERSION = "1.0.0";

// WiFi connection timeout
constexpr unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;

// ============================================================================
// MQTT Configuration
// ============================================================================
// MQTT broker address and port are defined in secrets.h
static constexpr const char* MQTT_CLIENT_ID = DEVICE_ID;

// MQTT Topics (fully configurable per device)
static constexpr const char* MQTT_TOPIC_SET_STATIC   = "lights/room1/esp_dimmer_1/set_static";
static constexpr const char* MQTT_TOPIC_SET_PLAN     = "lights/room1/esp_dimmer_1/set_plan";
static constexpr const char* MQTT_TOPIC_HEARTBEAT    = "lights/room1/esp_dimmer_1/heartbeat";

// MQTT reconnect interval
constexpr unsigned long MQTT_RECONNECT_INTERVAL_MS = 5000;

// Heartbeat publish interval
constexpr unsigned long HEARTBEAT_PERIOD_MS = 5000;

// ============================================================================
// UDP Fast Control Configuration
// ============================================================================

constexpr unsigned int UDP_PORT = 5000;         // Server default
constexpr unsigned long UDP_TIMEOUT_MS = 3000;  // Revert to MQTT after 3s without UDP

// ============================================================================
// NTP Configuration
// ============================================================================

static constexpr const char* NTP_SERVER_1 = "pool.ntp.org";
static constexpr const char* NTP_SERVER_2 = "time.nist.gov";
// IMPORTANT: Keep timezone offset at 0 (UTC) to match server timestamps
// Server should send UTC timestamps, ESP uses UTC time for schedule synchronization
constexpr long NTP_TZ_OFFSET_SEC = 0;      // UTC offset in seconds (0 = UTC)
constexpr int NTP_DST_OFFSET_SEC = 0;       // DST offset in seconds (0 = no DST)

// Time epoch for validity check (Jan 1, 2024)
constexpr unsigned long TIME_VALID_EPOCH = 1704067200;

// ============================================================================
// Schedule Player Configuration
// ============================================================================

constexpr size_t MAX_SCHEDULE_VALUES = 1000;  // Max steps in schedule array
constexpr bool SCHEDULE_INTERPOLATE = true;   // Linear interpolation between steps

// ============================================================================
// Serial Configuration
// ============================================================================

constexpr unsigned long SERIAL_BAUD_RATE = 115200;

// ============================================================================
// Debug Configuration
// ============================================================================

#define DEBUG_SERIAL 1  // Enable serial debug output

#if DEBUG_SERIAL
  #define DEBUG_PRINT(x) Serial.print(x)
  #define DEBUG_PRINTLN(x) Serial.println(x)
#else
  #define DEBUG_PRINT(x)
  #define DEBUG_PRINTLN(x)
#endif

#endif // CONFIG_H

