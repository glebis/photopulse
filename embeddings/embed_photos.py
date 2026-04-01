#!/usr/bin/env python3
"""Embed photo thumbnails using Google Gemini Embedding 2.

Reads thumbnails from the photoimport assets directory, embeds them via
Gemini's multimodal embedding API, and stores results in ChromaDB.

Usage:
    python3.11 embed_photos.py              # Process all unembedded photos
    python3.11 embed_photos.py --limit 100  # Test batch of 100
    python3.11 embed_photos.py --dry-run    # Count photos to process
"""

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

PHOTO_DB = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
ASSETS_DIR = Path.home() / "ai_projects" / "photoimport" / "thumbs"
CHROMA_DIR = Path.home() / "ai_projects" / "photopulse" / "embeddings" / "chroma_db"
COLLECTION_NAME = "photo_pulse"
BATCH_SIZE = 50  # paid tier — 1500 RPM
MODEL = "gemini-embedding-2-preview"  # latest multimodal embedding model


def get_api_key():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        key_file = Path.home() / ".config" / "gemini" / "api_key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        print("ERROR: No API key found. Set GOOGLE_API_KEY or GEMINI_API_KEY env var.")
        print("  Or save key to ~/.config/gemini/api_key")
        sys.exit(1)
    return key


def get_photos_to_embed(limit=None):
    """Get photos that have asset files and haven't been embedded yet."""
    conn = sqlite3.connect(str(PHOTO_DB))
    conn.row_factory = sqlite3.Row

    photos = conn.execute("""
        SELECT uuid, captured, lat, lon
        FROM images
        WHERE (is_screenshot != 1 OR is_screenshot IS NULL)
          AND captured IS NOT NULL
        ORDER BY captured DESC
    """).fetchall()

    # Get faces
    faces_raw = conn.execute("""
        SELECT f.image_uuid, f.person_name
        FROM faces f
        WHERE f.person_name IS NOT NULL AND f.person_name != '' AND f.person_name != 'Gleb'
    """).fetchall()
    from collections import defaultdict
    faces_by_uuid = defaultdict(list)
    for r in faces_raw:
        faces_by_uuid[r["image_uuid"]].append(r["person_name"])

    # Get objects
    objects_raw = conn.execute("""
        SELECT d.image_uuid, d.label
        FROM detections d
    """).fetchall()
    objects_by_uuid = defaultdict(list)
    for r in objects_raw:
        objects_by_uuid[r["image_uuid"]].append(r["label"])

    conn.close()

    # Filter to photos with assets
    result = []
    for p in photos:
        uuid = p["uuid"]
        # Check for asset file (jpg or webp)
        asset_path = None
        for ext in [".jpg", ".webp", ".png"]:
            path = ASSETS_DIR / f"{uuid}{ext}"
            if path.exists():
                asset_path = path
                break

        if asset_path is None:
            continue

        faces = list(set(faces_by_uuid.get(uuid, [])))
        objects = list(set(objects_by_uuid.get(uuid, [])))[:5]

        result.append({
            "uuid": uuid,
            "captured": p["captured"],
            "lat": p["lat"] if p["lat"] and p["lat"] > -179 else None,
            "lon": p["lon"] if p["lon"] and p["lon"] > -179 else None,
            "faces": faces,
            "objects": objects,
            "asset_path": str(asset_path),
        })

    # Don't limit here — limit is applied in main() AFTER filtering already-embedded
    return result


def setup_chroma():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def get_already_embedded(collection):
    """Get set of IDs already in ChromaDB."""
    try:
        result = collection.get(include=[])
        return set(result["ids"])
    except Exception:
        return set()


def embed_single(client, image_data, mime, model_name, max_retries=5):
    """Embed a single image with exponential backoff on rate limit."""
    from google.genai import types

    for attempt in range(max_retries):
        try:
            response = client.models.embed_content(
                model=model_name,
                contents=types.Part.from_bytes(data=image_data, mime_type=mime),
            )
            return response.embeddings[0].values
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                wait = 2 ** attempt * 5  # 5, 10, 20, 40, 80 seconds
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    return None


def embed_batch(client, photos, model_name):
    """Embed a batch of photos using Gemini with retry logic."""
    results = []
    for photo in photos:
        try:
            with open(photo["asset_path"], "rb") as f:
                image_data = f.read()

            ext = Path(photo["asset_path"]).suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime = mime_map.get(ext, "image/jpeg")

            embedding = embed_single(client, image_data, mime, model_name)
            if embedding:
                results.append({"uuid": photo["uuid"], "embedding": embedding})

        except Exception as e:
            print(f"  Error embedding {photo['uuid']}: {e}")
            continue

    return results


def main():
    parser = argparse.ArgumentParser(description="Embed photos with Gemini")
    parser.add_argument("--limit", type=int, help="Max photos to process")
    parser.add_argument("--dry-run", action="store_true", help="Just count, don't embed")
    args = parser.parse_args()

    print("Loading photos with assets...")
    photos = get_photos_to_embed(None)  # get all, limit after dedup
    print(f"Found {len(photos)} photos with asset files")

    if args.dry_run:
        print("Dry run — exiting.")
        return

    if len(photos) == 0:
        print("No photos to embed.")
        return

    # Setup
    api_key = get_api_key()
    from google import genai
    gemini_client = genai.Client(api_key=api_key)

    _, collection = setup_chroma()
    already = get_already_embedded(collection)
    photos = [p for p in photos if p["uuid"] not in already]
    # Apply limit AFTER filtering (so we always get fresh unembedded photos)
    if args.limit and len(photos) > args.limit:
        photos = photos[:args.limit]
    print(f"After filtering already embedded: {len(photos)} remaining")

    if len(photos) == 0:
        print("All photos already embedded.")
        return

    # Process in batches
    total = len(photos)
    embedded = 0
    start = time.time()

    for i in range(0, total, BATCH_SIZE):
        batch = photos[i:i + BATCH_SIZE]
        print(f"Batch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}: "
              f"embedding {len(batch)} photos...")

        results = embed_batch(gemini_client, batch, MODEL)

        if results:
            # Store in ChromaDB
            ids = [r["uuid"] for r in results]
            embeddings = [r["embedding"] for r in results]
            metadatas = []
            for r in results:
                photo = next(p for p in batch if p["uuid"] == r["uuid"])
                meta = {
                    "type": "photo",
                    "captured": photo["captured"] or "",
                    "faces": ",".join(photo["faces"]) if photo["faces"] else "",
                    "objects": ",".join(photo["objects"]) if photo["objects"] else "",
                }
                if photo["lat"]:
                    meta["lat"] = photo["lat"]
                if photo["lon"]:
                    meta["lon"] = photo["lon"]
                metadatas.append(meta)

            collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
            embedded += len(results)

        elapsed = time.time() - start
        rate = embedded / max(elapsed, 1)
        eta = (total - embedded) / max(rate, 0.01)
        print(f"  {embedded}/{total} done ({rate:.1f}/s, ETA {eta:.0f}s)")

        # Paid tier: minimal delay
        time.sleep(0.1)

    elapsed = time.time() - start
    print(f"\nDone. Embedded {embedded} photos in {elapsed:.0f}s ({embedded/max(elapsed,1):.1f}/s)")
    print(f"ChromaDB at: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
