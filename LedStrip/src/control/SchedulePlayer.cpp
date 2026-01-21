#include "SchedulePlayer.h"
#include <time.h>
#include <sys/time.h>
#include <algorithm>

// Global instance
SchedulePlayer schedulePlayer;

// Helper to get current time in milliseconds
static uint64_t getNowMs() {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)(tv.tv_usec / 1000);
}

void SchedulePlayer::begin() {
    commandCount = 0;
    headIndex = 0;
    memset(lastFrame, 0, sizeof(lastFrame));
    lastExecutedTimestamp = 0;
    hasExecutedCommand = false;
    DEBUG_PRINTLN("SchedulePlayer initialized (event-based ms-precision mode)");
}

bool SchedulePlayer::addCommand(uint64_t timestamp, const uint8_t* values, size_t len) {
    if (!values || len == 0) {
        DEBUG_PRINTLN("Invalid command parameters");
        return false;
    }

    if (commandCount >= MAX_SCHEDULE_VALUES) {
        DEBUG_PRINTLN("Command queue full, cannot add more commands");
        return false;
    }

    // Create new command
    TimedCommand cmd;
    cmd.timestamp = timestamp;

    // Copy values
    for (size_t i = 0; i < NUM_CHANNELS; i++) {
        cmd.values[i] = (i < len) ? values[i] : 0;
    }

    // Insert in sorted order
    if (!insertSorted(cmd)) {
        return false;
    }

    // Reduced debug output for command additions
    static unsigned long lastCmdDebugPrint = 0;
    unsigned long now = millis();
    if (now - lastCmdDebugPrint > 10000) {  // Print at most once every 10 seconds
        DEBUG_PRINT("Cmd added, queue: ");
        DEBUG_PRINTLN(commandCount);
        lastCmdDebugPrint = now;
    }

    return true;
}

void SchedulePlayer::clearSchedule() {
    commandCount = 0;
    headIndex = 0;
    memset(lastFrame, 0, sizeof(lastFrame));
    lastExecutedTimestamp = 0;
    hasExecutedCommand = false;
    DEBUG_PRINTLN("All commands cleared");
}

bool SchedulePlayer::getCurrentFrame(uint8_t* outValues, size_t len) {
    if (!outValues || len == 0) {
        return false;
    }
    
    // Get current Unix timestamp in ms
    uint64_t currentTimestamp = getNowMs();
    
    // Execute any commands that should run at or before current time
    if (executeCommandsAt(currentTimestamp, outValues, len)) {
        return true;
    }
    
    // If no commands to execute but we have executed before, return last frame
    if (hasExecutedCommand) {
        for (size_t i = 0; i < len && i < NUM_CHANNELS; i++) {
            outValues[i] = lastFrame[i];
        }
        return true;
    }
    
    // No commands executed yet and no current commands - return false
    return false;
}

bool SchedulePlayer::executeCommandsAt(uint64_t currentTimestamp, uint8_t* outValues, size_t len) {
    bool executed = false;

    // Process commands from the head (oldest) until we find one in the future
    while (commandCount > 0) {
        const TimedCommand& cmd = getCommand(0); // Get oldest command

        if (cmd.timestamp <= currentTimestamp) {
            // This command should be executed

            // Copy values to output
            for (size_t i = 0; i < len && i < NUM_CHANNELS; i++) {
                outValues[i] = cmd.values[i];
                lastFrame[i] = cmd.values[i];
            }

            lastExecutedTimestamp = cmd.timestamp;
            hasExecutedCommand = true;
            executed = true;

            // Reduced debug output - only print timestamp for executed commands
            static unsigned long lastDebugPrint = 0;
            unsigned long now = millis();
            if (now - lastDebugPrint > 5000) {  // Print at most once every 5 seconds
                DEBUG_PRINT("Exec: ");
                DEBUG_PRINT((unsigned long)(cmd.timestamp / 1000));
                DEBUG_PRINT(".");
                DEBUG_PRINT((unsigned long)(cmd.timestamp % 1000));
                DEBUG_PRINTLN("");
                lastDebugPrint = now;
            }

            // Remove executed command (advance head)
            headIndex = (headIndex + 1) % MAX_SCHEDULE_VALUES;
            commandCount--;
        } else {
            // Commands are sorted, so if this one is in the future, all following ones are too
            break;
        }
    }

    return executed;
}

void SchedulePlayer::cleanupOldCommands(uint64_t currentTimestamp) {
    // Remove commands older than current timestamp (already executed or missed)
    size_t removed = 0;

    while (commandCount > 0) {
        const TimedCommand& cmd = getCommand(0);
        if (cmd.timestamp < currentTimestamp) {
            // Remove old command
            headIndex = (headIndex + 1) % MAX_SCHEDULE_VALUES;
            commandCount--;
            removed++;
        } else {
            // Commands are sorted, no more old commands
            break;
        }
    }

    if (removed > 0) {
        DEBUG_PRINT("Cleaned up ");
        DEBUG_PRINT(removed);
        DEBUG_PRINTLN(" old commands");
    }
}

uint8_t SchedulePlayer::interpolate(uint8_t v1, uint8_t v2, float fraction) {
    // Linear interpolation (kept for future use if needed)
    fraction = constrain(fraction, 0.0f, 1.0f);
    return (uint8_t)(v1 + (v2 - v1) * fraction);
}

bool SchedulePlayer::hasValidSchedule() const {
    return hasExecutedCommand || (commandCount > 0);
}

void SchedulePlayer::printScheduleInfo() const {
    DEBUG_PRINT("Queue size: ");
    DEBUG_PRINTLN(commandCount);

    if (commandCount > 0) {
        DEBUG_PRINT("Next at: ");
        DEBUG_PRINT((unsigned long)(getCommand(0).timestamp / 1000));
    }
}

// Circular buffer helper methods
TimedCommand& SchedulePlayer::getCommand(size_t index) {
    return commands[(headIndex + index) % MAX_SCHEDULE_VALUES];
}

const TimedCommand& SchedulePlayer::getCommand(size_t index) const {
    return commands[(headIndex + index) % MAX_SCHEDULE_VALUES];
}

bool SchedulePlayer::insertSorted(const TimedCommand& cmd) {
    if (commandCount >= MAX_SCHEDULE_VALUES) {
        return false;
    }

    // Find insertion point (commands are sorted by timestamp)
    size_t insertPos = 0;
    while (insertPos < commandCount) {
        if (cmd.timestamp < getCommand(insertPos).timestamp) {
            break;
        }
        insertPos++;
    }

    // Shift elements to make room for insertion
    if (insertPos < commandCount) {
        // Move elements from insertPos to end one position back
        for (size_t i = commandCount; i > insertPos; i--) {
            getCommand(i) = getCommand(i - 1);
        }
    }

    // Insert the new command
    size_t physicalIndex = (headIndex + insertPos) % MAX_SCHEDULE_VALUES;
    commands[physicalIndex] = cmd;
    commandCount++;

    return true;
}

