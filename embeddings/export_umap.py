#!/usr/bin/env python3
"""Export ChromaDB embeddings as 2D UMAP projection for the Embedding Explorer.

Outputs embeddings_2d.json with coordinates, metadata, and note content.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import umap

CHROMA_DIR = Path(__file__).parent / "chroma_db"
PHOTO_DB = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
VAULT_DIR = Path.home() / "Research" / "vault"
OUTPUT = Path.home() / "ai_projects" / "photopulse" / "explorer" / "embeddings_2d.json"
COLLECTION_NAME = "photo_pulse"
MAX_NOTE_TEXT = 2000


def main():
    import chromadb

    # Snapshot ChromaDB to avoid conflicts with active writers
    import shutil
    snapshot_dir = CHROMA_DIR.parent / "chroma_snapshot"
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.copytree(CHROMA_DIR, snapshot_dir)
    print(f"Snapshot created at {snapshot_dir}")

    print("Loading embeddings from snapshot...")
    client = chromadb.PersistentClient(path=str(snapshot_dir))
    col = client.get_collection(COLLECTION_NAME)

    # Fetch in batches to handle large collections
    total = col.count()
    print(f"Collection has {total} items, fetching in batches...")
    all_ids, all_embeddings, all_metadatas = [], [], []
    FETCH_BATCH = 500
    for offset in range(0, total, FETCH_BATCH):
        try:
            batch = col.get(include=["embeddings", "metadatas"], limit=FETCH_BATCH, offset=offset)
            all_ids.extend(batch["ids"])
            all_embeddings.extend(batch["embeddings"])
            all_metadatas.extend(batch["metadatas"])
            print(f"  Fetched {len(all_ids)}/{total}...")
        except Exception as e:
            print(f"  Batch at offset {offset} failed: {e}, skipping...")
            continue

    result = {"ids": all_ids, "embeddings": all_embeddings, "metadatas": all_metadatas}
    ids = result["ids"]
    embeddings = result["embeddings"]
    metadatas = result["metadatas"]

    if len(ids) == 0:
        print("No embeddings found.")
        return

    print(f"Loaded {len(ids)} embeddings ({sum(1 for m in metadatas if m.get('type')=='photo')} photos, "
          f"{sum(1 for m in metadatas if m.get('type')=='note')} notes)")

    # UMAP projection
    print("Computing UMAP 2D projection...")
    X = np.array(embeddings)

    # L2-normalize embeddings to reduce modality separation
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1
    X = X / norms

    reducer = umap.UMAP(n_components=2, n_neighbors=30, min_dist=0.8, spread=2.0, metric="cosine", random_state=42)
    coords = reducer.fit_transform(X)

    # Post-UMAP repulsion: push overlapping items apart
    print("Running repulsion pass...")
    MIN_DIST = 1.5  # minimum distance between items in UMAP space
    for iteration in range(80):
        moved = 0
        for i in range(len(coords)):
            fx, fy = 0, 0
            for j in range(len(coords)):
                if i == j:
                    continue
                dx = coords[i, 0] - coords[j, 0]
                dy = coords[i, 1] - coords[j, 1]
                dist = np.sqrt(dx * dx + dy * dy)
                if dist < MIN_DIST and dist > 0.01:
                    force = (MIN_DIST - dist) * 0.1
                    fx += (dx / dist) * force
                    fy += (dy / dist) * force
                    moved += 1
            coords[i, 0] += fx
            coords[i, 1] += fy
        if moved == 0:
            break
    print(f"  Repulsion: {iteration + 1} iterations, {moved} pushes last iter")

    # Normalize to roughly -50..50 range
    cx = coords[:, 0]
    cy = coords[:, 1]
    cx = (cx - cx.min()) / (cx.max() - cx.min() + 1e-8) * 100 - 50
    cy = (cy - cy.min()) / (cy.max() - cy.min() + 1e-8) * 80 - 40
    coords[:, 0] = cx
    coords[:, 1] = cy

    # Post-UMAP grid snap to prevent overlaps
    print("Applying grid snap to prevent overlaps...")
    CELL_SIZE = 1.2  # minimum spacing between items
    occupied = {}  # (gx, gy) -> True
    for i in range(len(coords)):
        gx = round(coords[i, 0] / CELL_SIZE)
        gy = round(coords[i, 1] / CELL_SIZE)
        # Spiral outward to find free cell
        if (gx, gy) not in occupied:
            occupied[(gx, gy)] = True
            coords[i, 0] = gx * CELL_SIZE
            coords[i, 1] = gy * CELL_SIZE
        else:
            found = False
            for radius in range(1, 50):
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        if abs(dx) != radius and abs(dy) != radius:
                            continue  # only check perimeter
                        nx, ny = gx + dx, gy + dy
                        if (nx, ny) not in occupied:
                            occupied[(nx, ny)] = True
                            coords[i, 0] = nx * CELL_SIZE
                            coords[i, 1] = ny * CELL_SIZE
                            found = True
                            break
                    if found:
                        break
                if found:
                    break

    # Load note content for preview
    note_texts = {}
    for i, meta in enumerate(metadatas):
        if meta.get("type") == "note":
            note_id = ids[i]
            # note_id format: "note:relative/path.md"
            rel_path = note_id.replace("note:", "", 1)
            note_path = VAULT_DIR / rel_path
            if note_path.exists():
                try:
                    text = note_path.read_text(encoding="utf-8", errors="ignore")[:MAX_NOTE_TEXT]
                    note_texts[note_id] = text
                except Exception:
                    pass

    # Build output
    items = []
    for i, (id_, meta, coord) in enumerate(zip(ids, metadatas, coords)):
        item = {
            "id": id_,
            "type": meta.get("type", "unknown"),
            "x": round(float(coord[0]), 2),
            "y": round(float(coord[1]), 2),
        }

        if meta.get("type") == "photo":
            item["captured"] = meta.get("captured", "")
            item["faces"] = meta.get("faces", "")
            item["objects"] = meta.get("objects", "")
            if "lat" in meta:
                item["lat"] = meta["lat"]
            if "lon" in meta:
                item["lon"] = meta["lon"]
        elif meta.get("type") == "note":
            item["title"] = meta.get("title", "")
            item["folder"] = meta.get("folder", "")
            item["text"] = note_texts.get(id_, "")[:MAX_NOTE_TEXT]

        items.append(item)

    # Full data file
    with open(OUTPUT, "w") as f:
        json.dump(items, f)

    # Lightweight summary: positions + type + minimal metadata (no note text)
    summary = []
    for item in items:
        s = {"id": item["id"], "type": item["type"], "x": item["x"], "y": item["y"]}
        if item["type"] == "photo":
            s["captured"] = item.get("captured", "")[:10]
        elif item["type"] == "note":
            s["title"] = item.get("title", "")
            s["folder"] = item.get("folder", "")
        summary.append(s)

    summary_path = OUTPUT.parent / "embeddings_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f)

    full_kb = OUTPUT.stat().st_size / 1024
    summary_kb = summary_path.stat().st_size / 1024
    print(f"Saved {len(items)} items: full={full_kb:.0f}KB, summary={summary_kb:.0f}KB")


if __name__ == "__main__":
    main()
