#!/bin/bash
# Photo Pulse daily runner
# Generates pulse for most recent day, saves to output dir and logs

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

DATE=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/$DATE.log"

echo "$(date): Photo Pulse daily run started" >> "$LOG_FILE"

# Generate pulse and save
OUTPUT=$(python3 "$SCRIPT_DIR/photopulse.py" 2>> "$LOG_FILE")

if [ -n "$OUTPUT" ]; then
    echo "$OUTPUT" > "$OUTPUT_DIR/$DATE.md"
    echo "$(date): Output saved to $OUTPUT_DIR/$DATE.md" >> "$LOG_FILE"
    echo "$OUTPUT"
else
    echo "$(date): No output generated" >> "$LOG_FILE"
fi

echo "$(date): Photo Pulse daily run complete" >> "$LOG_FILE"
