# LedStrip (ESP8266) Secrets

Sensitive, device-specific configuration has been moved to src/config/secrets.h:

- WiFi SSID and password
- MQTT broker address and port
- OTA hostname (and optional OTA password)

Update these values in src/config/secrets.h for this device.
