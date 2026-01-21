#ifndef SCHEDULE_PLAYER_H
#define SCHEDULE_PLAYER_H

#include <Arduino.h>
#include <vector>
#include "../config/Config.h"

// ============================================================================
// SchedulePlayer: Event-based brightness schedule with millisecond precision
// ============================================================================

struct TimedCommand {
    uint64_t timestamp;            // Unix timestamp in milliseconds
    uint8_t values[NUM_CHANNELS];  // Brightness values

    TimedCommand() = default;
    TimedCommand(uint64_t ts, const uint8_t* vals) : timestamp(ts) {
        if (vals) memcpy(values, vals, NUM_CHANNELS * sizeof(uint8_t));
    }

    bool operator<(const TimedCommand& other) const {
        return timestamp < other.timestamp;
    }
};

class SchedulePlayer {
public:
    // Initialize the schedule player
    void begin();
    
    // CHANGED: Now takes uint64_t (milliseconds) instead of unsigned long (seconds)
    bool addCommand(uint64_t timestamp, const uint8_t* values, size_t len);
    
    // Clear the current schedule
    void clearSchedule();
    
    // Get current frame based on system time
    bool getCurrentFrame(uint8_t* outValues, size_t len);
    
    // Check if a schedule is loaded and valid
    bool hasValidSchedule() const;
    
    // Get schedule info for debugging
    void printScheduleInfo() const;
    
private:
    std::vector<TimedCommand> commands;
    uint8_t lastFrame[NUM_CHANNELS] = {0};
    uint64_t lastExecutedTimestamp = 0;
    bool hasExecutedCommand = false;
    
    // Execute commands at or before the given timestamp
    bool executeCommandsAt(uint64_t currentTimestamp, uint8_t* outValues, size_t len);
};

// Global instance
extern SchedulePlayer schedulePlayer;

#endif // SCHEDULE_PLAYER_H

