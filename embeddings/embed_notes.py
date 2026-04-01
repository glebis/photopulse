#!/usr/bin/env python3
"""Embed Obsidian vault notes using Google Gemini Embedding 2.

Reads .md files from the vault, embeds text via Gemini, and stores
in the same ChromaDB collection as photos for cross-modal search.

Usage:
    python3.11 embed_notes.py              # Process all unembedded notes
    python3.11 embed_notes.py --limit 50   # Test batch of 50
    python3.11 embed_notes.py --dry-run    # Count notes to process
"""

import argparse
import os
import sys
import time
from pathlib import Path

VAULT_DIR = Path.home() / "Research" / "vault"
CHROMA_DIR = Path.home() / "ai_projects" / "photopulse" / "embeddings" / "chroma_db"
COLLECTION_NAME = "photo_pulse"
BATCH_SIZE = 50
MODEL = "gemini-embedding-2-preview"
MAX_TEXT_LEN = 8000  # truncate long notes


def get_api_key():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        key_file = Path.home() / ".config" / "gemini" / "api_key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        print("ERROR: No API key found. Set GOOGLE_API_KEY or GEMINI_API_KEY env var.")
        sys.exit(1)
    return key


def get_notes(limit=None):
    """Find all .md files in the vault."""
    notes = []
    skip_dirs = {".obsidian", ".trash", ".git", ".smart-connections", ".vector_store", "node_modules"}

    for md_file in VAULT_DIR.rglob("*.md"):
        # Skip hidden/system directories
        if any(part in skip_dirs for part in md_file.parts):
            continue

        rel_path = md_file.relative_to(VAULT_DIR)
        folder = str(rel_path.parent) if str(rel_path.parent) != "." else "root"

        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if len(text.strip()) < 50:
            continue  # skip near-empty notes

        # Truncate for embedding
        if len(text) > MAX_TEXT_LEN:
            text = text[:MAX_TEXT_LEN]

        notes.append({
            "id": f"note:{rel_path}",
            "title": md_file.stem,
            "folder": folder,
            "text": text,
            "path": str(md_file),
        })

    # Don't limit here — limit after dedup in main()
    return notes


def setup_chroma():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def get_already_embedded(collection):
    try:
        result = collection.get(include=[], where={"type": "note"})
        return set(result["ids"])
    except Exception:
        return set()


def embed_text_single(client, text, model_name, max_retries=5):
    """Embed single text with exponential backoff on rate limit."""
    for attempt in range(max_retries):
        try:
            response = client.models.embed_content(
                model=model_name,
                contents=text,
            )
            return response.embeddings[0].values
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 2 ** attempt * 5
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    return None


def embed_text_batch(client, texts, model_name):
    """Embed a batch of texts using Gemini with retry logic."""
    results = []
    for item in texts:
        try:
            embedding = embed_text_single(client, item["text"], model_name)
            if embedding:
                results.append({"id": item["id"], "embedding": embedding})
        except Exception as e:
            print(f"  Error embedding {item['id']}: {e}")
            continue
    return results


def main():
    parser = argparse.ArgumentParser(description="Embed vault notes with Gemini")
    parser.add_argument("--limit", type=int, help="Max notes to process")
    parser.add_argument("--dry-run", action="store_true", help="Just count")
    args = parser.parse_args()

    print("Scanning vault notes...")
    notes = get_notes(args.limit)
    print(f"Found {len(notes)} notes with content")

    if args.dry_run:
        print(f"Folders: {len(set(n['folder'] for n in notes))}")
        from collections import Counter
        folders = Counter(n['folder'] for n in notes)
        for f, c in folders.most_common(10):
            print(f"  {f}: {c}")
        return

    if len(notes) == 0:
        print("No notes to embed.")
        return

    api_key = get_api_key()
    from google import genai
    gemini_client = genai.Client(api_key=api_key)

    _, collection = setup_chroma()
    already = get_already_embedded(collection)
    notes = [n for n in notes if n["id"] not in already]
    if args.limit:
        notes = notes[:args.limit]
    print(f"After filtering already embedded: {len(notes)} remaining (limit: {args.limit or 'none'})")

    if len(notes) == 0:
        print("All notes already embedded.")
        return

    total = len(notes)
    embedded = 0
    start = time.time()

    for i in range(0, total, BATCH_SIZE):
        batch = notes[i:i + BATCH_SIZE]
        print(f"Batch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}: "
              f"embedding {len(batch)} notes...")

        results = embed_text_batch(gemini_client, batch, MODEL)

        if results:
            ids = [r["id"] for r in results]
            embeddings = [r["embedding"] for r in results]
            metadatas = []
            for r in results:
                note = next(n for n in batch if n["id"] == r["id"])
                metadatas.append({
                    "type": "note",
                    "title": note["title"],
                    "folder": note["folder"],
                })

            collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
            embedded += len(results)

        elapsed = time.time() - start
        rate = embedded / max(elapsed, 1)
        eta = (total - embedded) / max(rate, 0.01)
        print(f"  {embedded}/{total} done ({rate:.1f}/s, ETA {eta:.0f}s)")

        time.sleep(0.1)  # paid tier

    elapsed = time.time() - start
    print(f"\nDone. Embedded {embedded} notes in {elapsed:.0f}s")
    print(f"ChromaDB at: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
