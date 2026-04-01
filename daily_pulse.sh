#!/bin/bash
# Daily Photo Pulse — runs at 9:00 AM via LaunchAgent
# Generates behavioral health insights and saves to output directory

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
DATE=$(date '+%Y-%m-%d')
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$OUTPUT_DIR"

echo "[$TIMESTAMP] Running Photo Pulse..."

# Generate pulse for yesterday (most recent data)
OUTPUT=$(python3 "$SCRIPT_DIR/photopulse.py" 2>&1)

if [ $? -eq 0 ]; then
    echo "$OUTPUT" > "$OUTPUT_DIR/$DATE.md"
    echo "[$TIMESTAMP] Saved to $OUTPUT_DIR/$DATE.md"
    echo "$OUTPUT"
else
    echo "[$TIMESTAMP] ERROR: Photo Pulse failed"
    echo "$OUTPUT"
fi
