#include "UdpFastControl.h"

// Global instance
UdpFastControl udpFastControl;

void UdpFastControl::begin() {
    // Start UDP listener
    if (udp.begin(UDP_PORT)) {
        listening = true;
        DEBUG_PRINT("UDP listening on port ");
        DEBUG_PRINTLN(UDP_PORT);
    } else {
        listening = false;
        DEBUG_PRINTLN("Failed to start UDP listener");
    }
}

void UdpFastControl::update() {
    if (!listening) return;
    
    // Check for incoming packets
    int packetSize = udp.parsePacket();
    
    if (packetSize > 0) {
        // Read packet
        size_t len = udp.read(packetBuffer, UDP_BUFFER_SIZE);
        
        if (len > 0) {
            packetCount++;
            processPacket(packetBuffer, len);
        }
    }
}

void UdpFastControl::processPacket(uint8_t* data, size_t length) {
    if (data == nullptr || length == 0) return;
    
    uint8_t frame[NUM_CHANNELS] = {0};

    // Expected protocol:
    // [0..2] = 'L','E','D'
    // [3]    = version (1)
    // [4]    = channel count N
    // [5..]  = N bytes of values
    bool parsed = parseLedV1(data, length, frame, NUM_CHANNELS);

    // Fallback: if not parsed, try raw brightness array (first N bytes)
    if (!parsed) {
        size_t count = min((size_t)NUM_CHANNELS, length);
        for (size_t i = 0; i < count; i++) {
            frame[i] = data[i];
        }
    }

    // Update mode manager with fast brightness
    modeManager.setFastBrightness(frame, NUM_CHANNELS);
}

bool UdpFastControl::parseLedV1(uint8_t* data, size_t length, uint8_t* outFrame, size_t len) {
    if (length < 6) return false;
    if (data[0] != 'L' || data[1] != 'E' || data[2] != 'D') return false;
    if (data[3] != 0x01) return false; // Version

    uint8_t channelCount = data[4];
    if (channelCount == 0) return false;
    
    // Check if we have enough data for what the packet CLAIMS to have
    size_t needed = 5 + channelCount;
    if (length < needed) return false;

    // Read up to what we can store (len), ignore extra channels in the packet
    for (size_t i = 0; i < channelCount && i < len; i++) {
        outFrame[i] = data[5 + i];
    }

    // Zero out remaining channels if any
    for (size_t i = channelCount; i < len; i++) {
        outFrame[i] = 0;
    }

    return true;
}

bool UdpFastControl::isListening() const {
    return listening;
}

unsigned long UdpFastControl::getPacketCount() const {
    return packetCount;
}

