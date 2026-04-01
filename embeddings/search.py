#!/usr/bin/env python3
"""Cross-modal search: find photos and notes by text or image query.

Usage:
    python3.11 search.py "sunset on balcony"
    python3.11 search.py "Yulia in park"
    python3.11 search.py --image path/to/photo.jpg  # find similar photos
    python3.11 search.py "book" --type photo         # photos only
    python3.11 search.py "therapy" --type note        # notes only
"""

import argparse
import os
import sys
from pathlib import Path

CHROMA_DIR = Path.home() / "ai_projects" / "photopulse" / "embeddings" / "chroma_db"
COLLECTION_NAME = "photo_pulse"
MODEL = "gemini-embedding-2-preview"
THUMB_BASE = Path.home() / "ai_projects" / "photoimport" / "assets"


def get_api_key():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        key_file = Path.home() / ".config" / "gemini" / "api_key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        print("ERROR: No API key found.")
        sys.exit(1)
    return key


def embed_query(client, query_text=None, query_image=None):
    """Embed a text or image query with retry on rate limit."""
    import time as _time
    from google.genai import types

    for attempt in range(5):
        try:
            if query_image:
                with open(query_image, "rb") as f:
                    data = f.read()
                ext = Path(query_image).suffix.lower()
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
                response = client.models.embed_content(
                    model=MODEL,
                    contents=types.Part.from_bytes(data=data, mime_type=mime),
                )
            else:
                response = client.models.embed_content(
                    model=MODEL,
                    contents=query_text,
                )
            return response.embeddings[0].values
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 2 ** attempt * 3
                print(f"Rate limited, waiting {wait}s...")
                _time.sleep(wait)
            else:
                raise
    raise RuntimeError("Exceeded retry limit for query embedding")


def search(query_text=None, query_image=None, n_results=10, type_filter=None):
    """Search ChromaDB for nearest photos and/or notes."""
    import chromadb

    api_key = get_api_key()
    from google import genai
    gemini_client = genai.Client(api_key=api_key)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(name=COLLECTION_NAME)

    # Embed query
    query_embedding = embed_query(gemini_client, query_text, query_image)

    # Build filter
    where = None
    if type_filter:
        where = {"type": type_filter}

    # Search
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
        include=["metadatas", "distances"],
    )

    return results


def format_results(results):
    """Pretty-print search results."""
    ids = results["ids"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    print(f"\n{'='*60}")
    print(f"  {'Rank':<5} {'Type':<6} {'Score':<7} {'Info'}")
    print(f"{'='*60}")

    for i, (id_, meta, dist) in enumerate(zip(ids, metadatas, distances)):
        score = 1 - dist  # cosine similarity
        type_ = meta.get("type", "?")

        if type_ == "photo":
            captured = meta.get("captured", "")[:10]
            faces = meta.get("faces", "")
            objects = meta.get("objects", "")
            info = f"{captured}"
            if faces:
                info += f" | {faces}"
            if objects:
                info += f" | {objects}"
            # Check if thumbnail exists
            thumb = THUMB_BASE / f"{id_}.jpg"
            if thumb.exists():
                info += f" | {thumb}"
        elif type_ == "note":
            title = meta.get("title", "")
            folder = meta.get("folder", "")
            info = f"{title} ({folder})"
        else:
            info = str(meta)

        print(f"  {i+1:<5} {type_:<6} {score:<7.3f} {info}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Cross-modal search")
    parser.add_argument("query", nargs="?", help="Text query")
    parser.add_argument("--image", help="Image file to use as query")
    parser.add_argument("--type", choices=["photo", "note"], help="Filter by type")
    parser.add_argument("-n", type=int, default=10, help="Number of results")
    parser.add_argument("--stats", action="store_true", help="Show collection stats")
    args = parser.parse_args()

    if args.stats:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        try:
            collection = client.get_collection(name=COLLECTION_NAME)
            count = collection.count()
            print(f"Collection '{COLLECTION_NAME}': {count} items")
            # Count by type
            photos = collection.get(where={"type": "photo"}, include=[])
            notes = collection.get(where={"type": "note"}, include=[])
            print(f"  Photos: {len(photos['ids'])}")
            print(f"  Notes: {len(notes['ids'])}")
        except Exception as e:
            print(f"No collection found: {e}")
        return

    if not args.query and not args.image:
        parser.error("Provide a text query or --image")

    results = search(
        query_text=args.query,
        query_image=args.image,
        n_results=args.n,
        type_filter=args.type,
    )

    format_results(results)


if __name__ == "__main__":
    main()
