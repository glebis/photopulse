#!/usr/bin/env python3
"""
Scan photo embeddings for visual similarity and store clusters in photoindex.sqlite.

Reads embeddings from ChromaDB, computes pairwise cosine similarity,
groups near-identical photos into clusters via union-find,
and stores results in similarity_clusters/members/pairs tables.

Usage:
    python3 similarity_scan.py                # Full scan, threshold 0.95
    python3 similarity_scan.py --threshold 0.98  # Stricter matching
    python3 similarity_scan.py --stats        # Show current cluster stats
    python3 similarity_scan.py --cluster UUID  # Show cluster for a photo
"""

import argparse
import sqlite3
from pathlib import Path

import chromadb
import numpy as np

CHROMA_DIR = Path(__file__).parent / "embeddings" / "chroma_db"
DB_PATH = Path.home() / "ai_projects/photoimport/photoindex.sqlite"
COLLECTION = "photo_pulse"
BATCH_SIZE = 100


def load_photo_embeddings():
    """Load all photo embeddings from ChromaDB in batches."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.get_collection(COLLECTION)

    all_photo_ids = col.get(where={"type": "photo"}, include=[], limit=50000)["ids"]
    print(f"{len(all_photo_ids)} photo IDs in ChromaDB")

    all_ids, all_embs, all_dates = [], [], []
    for i in range(0, len(all_photo_ids), BATCH_SIZE):
        batch = all_photo_ids[i : i + BATCH_SIZE]
        try:
            r = col.get(ids=batch, include=["embeddings", "metadatas"])
            all_ids.extend(r["ids"])
            all_embs.extend(r["embeddings"])
            all_dates.extend(
                m.get("captured", "")[:10] for m in r["metadatas"]
            )
        except Exception:
            for sid in batch:
                try:
                    r = col.get(ids=[sid], include=["embeddings", "metadatas"])
                    all_ids.extend(r["ids"])
                    all_embs.extend(r["embeddings"])
                    all_dates.extend(
                        m.get("captured", "")[:10] for m in r["metadatas"]
                    )
                except Exception:
                    pass
        if len(all_ids) % 2000 == 0 and all_ids:
            print(f"  {len(all_ids)} loaded...")

    print(f"Loaded {len(all_ids)} embeddings")
    return all_ids, np.array(all_embs), all_dates


def find_similar_pairs(ids, embeddings, threshold=0.95):
    """Find all pairs above cosine similarity threshold."""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = embeddings / norms

    pairs = []
    n = len(ids)
    for i in range(n):
        sims = normed[i] @ normed[i + 1 : n].T
        for j_off in np.where(sims > threshold)[0]:
            j = i + 1 + j_off
            pairs.append((ids[i], ids[j], float(sims[j_off])))
        if i % 2000 == 0 and i > 0:
            print(f"  {i}/{n} scanned, {len(pairs)} pairs...")

    pairs.sort(key=lambda x: -x[2])
    return pairs


def build_clusters(ids, pairs):
    """Union-find clustering from similarity pairs."""
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    for id1, id2, _ in pairs:
        union(id1, id2)

    clusters = {}
    for id_ in ids:
        clusters.setdefault(find(id_), []).append(id_)

    return {k: v for k, v in clusters.items() if len(v) >= 2}


def store_results(clusters, pairs):
    """Store clusters and pairs in photoindex.sqlite."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS similarity_clusters "
        "(cluster_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "member_count INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS similarity_members "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "cluster_id INTEGER, image_uuid TEXT, UNIQUE(image_uuid))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS similarity_pairs "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "uuid_a TEXT, uuid_b TEXT, cosine_similarity REAL, "
        "UNIQUE(uuid_a, uuid_b))"
    )

    cur.execute("DELETE FROM similarity_clusters")
    cur.execute("DELETE FROM similarity_members")
    cur.execute("DELETE FROM similarity_pairs")

    for members in clusters.values():
        cur.execute(
            "INSERT INTO similarity_clusters (member_count) VALUES (?)",
            (len(members),),
        )
        cid = cur.lastrowid
        for uuid in members:
            cur.execute(
                "INSERT OR IGNORE INTO similarity_members "
                "(cluster_id, image_uuid) VALUES (?, ?)",
                (cid, uuid),
            )

    for id1, id2, sim in pairs:
        a, b = min(id1, id2), max(id1, id2)
        cur.execute(
            "INSERT OR IGNORE INTO similarity_pairs "
            "(uuid_a, uuid_b, cosine_similarity) VALUES (?, ?, ?)",
            (a, b, round(sim, 4)),
        )

    conn.commit()
    conn.close()


def show_stats():
    """Show current similarity data stats."""
    conn = sqlite3.connect(str(DB_PATH))
    print("Similarity data in photoindex.sqlite:\n")

    clusters = conn.execute("SELECT COUNT(*) FROM similarity_clusters").fetchone()[0]
    members = conn.execute("SELECT COUNT(*) FROM similarity_members").fetchone()[0]
    pairs = conn.execute("SELECT COUNT(*) FROM similarity_pairs").fetchone()[0]
    print(f"  Clusters: {clusters}")
    print(f"  Photos in clusters: {members}")
    print(f"  Similarity pairs: {pairs}")

    print("\n  By similarity tier:")
    for lo, hi, label in [
        (0.995, 1.01, "≥0.995 (near-identical)"),
        (0.99, 0.995, "0.99–0.995"),
        (0.98, 0.99, "0.98–0.99"),
        (0.97, 0.98, "0.97–0.98"),
        (0.96, 0.97, "0.96–0.97"),
        (0.95, 0.96, "0.95–0.96"),
    ]:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM similarity_pairs "
            "WHERE cosine_similarity >= ? AND cosine_similarity < ?",
            (lo, hi),
        ).fetchone()[0]
        print(f"    {label}: {cnt}")

    print("\n  Largest clusters:")
    for row in conn.execute(
        "SELECT cluster_id, member_count FROM similarity_clusters "
        "ORDER BY member_count DESC LIMIT 5"
    ):
        print(f"    Cluster {row[0]}: {row[1]} photos")

    conn.close()


def show_cluster(uuid):
    """Show the cluster containing a specific photo."""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT cluster_id FROM similarity_members WHERE image_uuid = ?",
        (uuid,),
    ).fetchone()

    if not row:
        print(f"Photo {uuid} is not in any cluster.")
        conn.close()
        return

    cid = row[0]
    members = conn.execute(
        "SELECT sm.image_uuid, i.captured "
        "FROM similarity_members sm "
        "JOIN images i ON i.uuid = sm.image_uuid "
        "WHERE sm.cluster_id = ? ORDER BY i.captured",
        (cid,),
    ).fetchall()

    print(f"Cluster {cid}: {len(members)} photos\n")
    for uuid_, captured in members:
        print(f"  {(captured or '')[:16]}  {uuid_}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Photo similarity scanner")
    parser.add_argument("--threshold", type=float, default=0.95, help="Cosine similarity threshold")
    parser.add_argument("--stats", action="store_true", help="Show current stats")
    parser.add_argument("--cluster", help="Show cluster for a UUID")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.cluster:
        show_cluster(args.cluster)
        return

    print(f"Similarity scan (threshold={args.threshold})")
    ids, embeddings, dates = load_photo_embeddings()
    pairs = find_similar_pairs(ids, embeddings, args.threshold)
    print(f"\n{len(pairs)} pairs found")

    clusters = build_clusters(ids, pairs)
    total = sum(len(v) for v in clusters.values())
    print(f"{len(clusters)} clusters ({total} photos)")

    store_results(clusters, pairs)
    print("Stored in photoindex.sqlite")
    show_stats()


if __name__ == "__main__":
    main()
