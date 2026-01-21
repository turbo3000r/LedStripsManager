#include "SchedulePlayer.h"
#include <sys/time.h>
#include <algorithm>
#include <cstring>

// Global instance
SchedulePlayer schedulePlayer;

// Helper function for current time in milliseconds
static uint64_t getNowMs() {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)(tv.tv_usec / 1000);
}

void SchedulePlayer::begin() {
    commands.clear();
    // lastFrame is zero-initialized in class definition
    lastExecutedTimestamp = 0;
    hasExecutedCommand = false;
    DEBUG_PRINTLN("SchedulePlayer initialized (event-based ms-precision mode)");
}

bool SchedulePlayer::addCommand(uint64_t timestamp, const uint8_t* values, size_t len) {
    // Guard clauses for invalid input
    if (!values || len == 0) return false;
    if (len < NUM_CHANNELS) return false;
    if (commands.size() >= MAX_SCHEDULE_VALUES) return false;

    // Find insertion point using binary search (O(log n))
    auto insertPos = std::lower_bound(commands.begin(), commands.end(), timestamp,
        [](const TimedCommand& cmd, uint64_t ts) { return cmd.timestamp < ts; });

    // Insert at the correct position to maintain sorted order (O(n) worst case, but efficient)
    commands.insert(insertPos, TimedCommand{timestamp, values});

    return true;
}

void SchedulePlayer::clearSchedule() {
    commands.clear();
    // lastFrame will be updated on next command execution
    lastExecutedTimestamp = 0;
    hasExecutedCommand = false;
}

bool SchedulePlayer::getCurrentFrame(uint8_t* outValues, size_t len) {
    if (!outValues || len == 0) return false;
    
    uint64_t currentTimestamp = getNowMs();  // Use getNowMs() instead of time()
    
    if (executeCommandsAt(currentTimestamp, outValues, len)) {
        return true;
    }
    
    if (hasExecutedCommand) {
        // Return last frame
        for (size_t i = 0; i < len && i < NUM_CHANNELS; i++) {
            outValues[i] = lastFrame[i];
        }
        return true;
    }
    
    return false;
}

bool SchedulePlayer::executeCommandsAt(uint64_t currentTimestamp, uint8_t* outValues, size_t len) {
    bool executed = false;

    // Process commands in chronological order (vector is sorted)
    for (auto it = commands.begin(); it != commands.end(); ) {
        if (it->timestamp > currentTimestamp) {
            break;  // Commands are sorted, rest are in future
        }

        // Execute command - copy values efficiently
        size_t copyLen = (len < NUM_CHANNELS) ? len : NUM_CHANNELS;
        memcpy(outValues, it->values, copyLen * sizeof(uint8_t));
        memcpy(lastFrame, it->values, NUM_CHANNELS * sizeof(uint8_t));

        lastExecutedTimestamp = it->timestamp;
        hasExecutedCommand = true;
        executed = true;

        // Remove executed command
        it = commands.erase(it);
    }

    return executed;
}

bool SchedulePlayer::hasValidSchedule() const {
    return !commands.empty();
}

void SchedulePlayer::printScheduleInfo() const {
    if (commands.empty()) {
        DEBUG_PRINTLN("No valid schedule");
        return;
    }
    
    DEBUG_PRINT("Schedule: ");
    DEBUG_PRINT(commands.size());
    DEBUG_PRINT(" commands");
    if (!commands.empty()) {
        DEBUG_PRINT(", first: ");
        DEBUG_PRINT(commands.front().timestamp);
        DEBUG_PRINT(", last: ");
        DEBUG_PRINT(commands.back().timestamp);
    }
    DEBUG_PRINTLN("");
}

