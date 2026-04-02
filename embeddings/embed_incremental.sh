#!/bin/bash
set -e
cd "$(dirname "$0")"

# Decrypt API key via sops
export GOOGLE_API_KEY=$(sops --decrypt --extract '["google_api_key"]' ~/ai_projects/photopulse/secrets.yaml 2>/dev/null)
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "Failed to decrypt API key" >> embed.log
    exit 1
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting incremental embedding..." >> embed.log

python3.11 embed_photos.py --limit 200 >> embed.log 2>&1
python3.11 embed_notes.py --limit 400 >> embed.log 2>&1
python3.11 search.py --stats >> embed.log 2>&1

echo "[$TIMESTAMP] Incremental embedding complete." >> embed.log
