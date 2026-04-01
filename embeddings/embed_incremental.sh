#!/bin/bash
# Incremental embedding: runs photos then notes, respects rate limits.
# Designed to run via LaunchAgent every hour until all items are embedded.

set -e
cd "$(dirname "$0")"

export GOOGLE_API_KEY="AIzaSyBo_YU7zc9rQfEAMXGnkF1Hg0sxLFXes7w"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting incremental embedding..." >> embed.log

# Embed 200 photos per run (stay within rate limits)
echo "[$TIMESTAMP] Embedding photos (limit 200)..." >> embed.log
/opt/homebrew/bin/python3.11 embed_photos.py --limit 200 >> embed.log 2>&1

# Embed 400 notes per run (text is faster/cheaper)
echo "[$TIMESTAMP] Embedding notes (limit 400)..." >> embed.log
/opt/homebrew/bin/python3.11 embed_notes.py --limit 400 >> embed.log 2>&1

# Report stats
/opt/homebrew/bin/python3.11 search.py --stats >> embed.log 2>&1

echo "[$TIMESTAMP] Incremental embedding complete." >> embed.log
echo "" >> embed.log
