# Photo Pulse

Behavioral health insights and visual exploration from 20 years of photo data.

Combines photo metadata (GPS, timestamps, face detection, object detection) with Obsidian vault notes via multimodal embeddings to surface patterns in engagement, movement, social connection, and daily rhythms.

## Architecture

```
photoindex.sqlite (39k photos)     Obsidian vault (11k notes)
        ↓                                  ↓
   Gemini Embedding 2              Gemini Embedding 2
        ↓                                  ↓
           ChromaDB (shared embedding space)
                       ↓
              6 interactive visualizations
              Photo Pulse daily reports
              Note ↔ Photo linking
              Similarity clustering
```

## Components

### Daily Pulse (`photopulse.py`)
Behavioral health signal from daily photo patterns. Runs at 9 AM via LaunchAgent.

```bash
python3 photopulse.py                    # Most recent day
python3 photopulse.py 2025-03-28         # Specific date
python3 photopulse.py --inject           # Append to Obsidian daily note
```

Outputs engagement level, movement radius, social presence, energy rhythm, novelty detection, and weekly trend summary. Framed as behavioral health language, not photography metrics.

### Note ↔ Photo Linking (`link_photos.py`)
Links vault notes to related photos via face detection + date matching.

```bash
python3 link_photos.py ~/Research/vault/some-note.md           # Show related photos
python3 link_photos.py ~/Research/vault/some-note.md --inject  # Embed in note
python3 link_photos.py --person Yulia --limit 20               # Person query
```

Copies thumbnails to `vault/Attachments/photos/` and uses Obsidian `![[]]` embeds with source links to the full-res server.

### Similarity Scanner (`similarity_scan.py`)
Finds visually similar/duplicate photos using embedding cosine similarity.

```bash
python3 similarity_scan.py                    # Full scan (threshold 0.95)
python3 similarity_scan.py --threshold 0.98   # Stricter
python3 similarity_scan.py --stats            # Show cluster stats
python3 similarity_scan.py --cluster UUID     # Show a photo's cluster
```

Stores results in `photoindex.sqlite` tables: `similarity_clusters`, `similarity_members`, `similarity_pairs`.

### Collage Generator (`collage.py`)
Photo grid collages for specific dates.

```bash
python3 collage.py 2025-12-28                          # 4x3 grid
python3 collage.py 2025-12-28 --output ~/Desktop/out.jpg
```

## Embeddings (`embeddings/`)

Multimodal embedding pipeline using Google Gemini Embedding 2 (3072-dim).

| Script | Purpose |
|--------|---------|
| `embed_photos.py` | Embed photo thumbnails → ChromaDB |
| `embed_notes.py` | Embed vault .md files → ChromaDB |
| `search.py` | Cross-modal text/image search |
| `export_umap.py` | UMAP 2D projection → JSON for explorer |
| `embed_incremental.sh` | Hourly batch wrapper for LaunchAgent |

```bash
# Search across photos and notes
python3.11 search.py "sunset on balcony"
python3.11 search.py --image ~/photo.jpg    # Image-to-image
python3.11 search.py --stats                # Show counts

# Embed new items
python3.11 embed_photos.py --limit 200
python3.11 embed_notes.py --limit 400

# Regenerate UMAP projection
python3.11 export_umap.py
```

## Visual Explorer (`explorer/`)

7 interactive HTML visualizations served at `http://100.97.18.14:8081/`.

| Page | Description |
|------|-------------|
| `hub.html` | Index page linking all visualizations |
| `index.html` | Folding Explorer — 6 layout projections with animated fold transitions, physics panel, 4D fold-into |
| `calendar.html` | Calendar Wall — 20 years as heatmap, click for daily photos |
| `ekg.html` | Behavioral EKG — continuous waveform of photo density |
| `replay.html` | Life Replay — GPS timelapse on dark map |
| `absence.html` | Absence Map — inverted heatmap showing gaps |
| `embeddings.html` | Embedding Explorer — UMAP scatter of photos + notes with spotlight, focus mode, search |

### Explorer Controls

**Folding Explorer (index.html):**
- `1-6` — Switch layouts (Time, Place, People, Engagement, Radius, Objects)
- `F` — Fold into selected photo (4D dive)
- `Esc` — Unfold / deselect
- `P` or `Shift+,` — Physics settings panel
- `G` — Grid mode toggle
- `R` — Reflow / reset view
- `Space` — Auto-fold cycle

**Embedding Explorer (embeddings.html):**
- `L` — Toggle spotlight mode
- `1/2/3` — Layer filter (Photos / Notes / Both)
- `G` — Grid layout toggle
- `D` — Date filter timeline
- `P` — Settings panel
- `R` — Reset view
- `Arrow keys` — Navigate between neighbors
- Click → Focus mode with breadcrumb trail

### Serving

```bash
# Thumbnail server (39k JPGs at 400px)
python3 explorer/serve.py 8080 ~/ai_projects/photoimport/thumbs

# Explorer server
python3 explorer/serve.py 8081 ~/ai_projects/photopulse/explorer
```

## Data Sources

| Source | Path | Records |
|--------|------|---------|
| Photo index | `~/ai_projects/photoimport/photoindex.sqlite` | 39,200 photos |
| Thumbnails | `~/ai_projects/photoimport/thumbs/` | 39,120 JPGs (400px, 1.5GB) |
| Obsidian vault | `~/Research/vault/` | 11,364 notes |
| Embeddings | `embeddings/chroma_db/` | 22k+ (growing) |
| Health data | `/Users/server/data/health.db` | 19.5M records |

## LaunchAgents

| Agent | Schedule | Purpose |
|-------|----------|---------|
| `com.photopulse.daily` | 9:00 AM | Daily Photo Pulse report |
| `com.photopulse.embed` | Hourly | Incremental embedding (paused when running full batch) |

## Dependencies

- Python 3.11 (`/opt/homebrew/bin/python3.11`)
- `google-genai` — Gemini API
- `chromadb` — Vector database
- `umap-learn` — Dimensionality reduction
- `numpy`, `Pillow` — Computation and imaging
- SQLite3 — Data storage (stdlib)

## Environment

```bash
export GOOGLE_API_KEY="..."  # Gemini API key (paid tier for full-speed embedding)
```
