#ifndef UDP_FAST_CONTROL_H
#define UDP_FAST_CONTROL_H

#include <Arduino.h>
#include <WiFiUdp.h>
#include "../config/Config.h"
#include "../control/ModeManager.h"

// ============================================================================
// UdpFastControl: UDP receiver for immediate brightness control
// ============================================================================

class UdpFastControl {
public:
    // Initialize UDP listener
    void begin();
    
    // Update UDP (call from main loop)
    void update();
    
    // Check if UDP is listening
    bool isListening() const;
    
    // Get packet count for debugging
    unsigned long getPacketCount() const;
    
private:
    WiFiUDP udp;
    bool listening = false;
    unsigned long packetCount = 0;
    
    // Buffer for incoming packets
    static const size_t UDP_BUFFER_SIZE = 512;
    uint8_t packetBuffer[UDP_BUFFER_SIZE];
    
    // Process received packet
    void processPacket(uint8_t* data, size_t length);
    
    // Parse simple LED v1 packet
    bool parseLedV1(uint8_t* data, size_t length, uint8_t* outFrame, size_t len);
};

// Global instance
extern UdpFastControl udpFastControl;

#endif // UDP_FAST_CONTROL_H

