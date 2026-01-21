#ifndef SCHEDULE_PLAYER_H
#define SCHEDULE_PLAYER_H

#include <Arduino.h>
#include "../config/Config.h"

// ============================================================================
// SchedulePlayer: Event-based brightness commands at precise timestamps
// ============================================================================

struct TimedCommand {
    uint64_t timestamp;            // Unix timestamp in milliseconds
    uint8_t values[NUM_CHANNELS];  // Per-channel brightness values (0-255)
    
    // Comparison operator for sorting by timestamp
    bool operator<(const TimedCommand& other) const {
        return timestamp < other.timestamp;
    }
};

class SchedulePlayer {
public:
    // Initialize the schedule player
    void begin();

    // Add a single command to the schedule (maintains sorted order)
    bool addCommand(uint64_t timestamp, const uint8_t* values, size_t len);

    // Clear all commands from the schedule
    void clearSchedule();

    // Get current frame based on system time (executes commands at their exact time)
    bool getCurrentFrame(uint8_t* outValues, size_t len);

    // Check if there are commands in the schedule
    bool hasValidSchedule() const;

    // Get schedule info for debugging
    void printScheduleInfo() const;

    // Remove old commands that have already executed
    void cleanupOldCommands(uint64_t currentTimestamp);

private:
    // Fixed-size circular buffer for commands (prevents memory fragmentation)
    TimedCommand commands[MAX_SCHEDULE_VALUES];
    size_t commandCount = 0;  // Current number of commands
    size_t headIndex = 0;     // Index of oldest command

    uint8_t lastFrame[NUM_CHANNELS] = {0};  // Last executed frame
    uint64_t lastExecutedTimestamp = 0; // Timestamp of last executed command
    bool hasExecutedCommand = false;

    // Find and execute commands at current time
    bool executeCommandsAt(uint64_t currentTimestamp, uint8_t* outValues, size_t len);

    // Linear interpolation between two values (optional for future use)
    uint8_t interpolate(uint8_t v1, uint8_t v2, float fraction);

    // Get command at logical index (handles circular buffer)
    TimedCommand& getCommand(size_t index);
    const TimedCommand& getCommand(size_t index) const;

    // Insert command in sorted order (O(n) but with fixed small n)
    bool insertSorted(const TimedCommand& cmd);
};

// Global instance
extern SchedulePlayer schedulePlayer;

#endif // SCHEDULE_PLAYER_H

