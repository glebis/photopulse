#!/usr/bin/env python3
"""Generate pre-computed layouts for the Folding Photo Explorer."""

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
OUTPUT = Path(__file__).parent / "layouts.json"

HOME_LAT = 52.553
HOME_LON = 13.400


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def get_photos():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    photos = conn.execute("""
        SELECT uuid, captured, lat, lon
        FROM images
        WHERE captured >= '2025-01-01' AND captured < '2026-01-01'
          AND (is_screenshot != 1 OR is_screenshot IS NULL)
          AND lat > -179
        ORDER BY captured
    """).fetchall()

    faces_raw = conn.execute("""
        SELECT f.image_uuid, f.person_name
        FROM faces f JOIN images i ON f.image_uuid = i.uuid
        WHERE i.captured >= '2025-01-01' AND i.captured < '2026-01-01'
          AND f.person_name IS NOT NULL AND f.person_name != '' AND f.person_name != 'Gleb'
          AND (i.is_screenshot != 1 OR i.is_screenshot IS NULL)
    """).fetchall()

    objects_raw = conn.execute("""
        SELECT d.image_uuid, d.label
        FROM detections d JOIN images i ON d.image_uuid = i.uuid
        WHERE i.captured >= '2025-01-01' AND i.captured < '2026-01-01'
          AND (i.is_screenshot != 1 OR i.is_screenshot IS NULL)
          AND d.label != 'person'
    """).fetchall()

    conn.close()

    faces_map = defaultdict(set)
    for r in faces_raw:
        faces_map[r["image_uuid"]].add(r["person_name"])

    objects_map = defaultdict(set)
    for r in objects_raw:
        objects_map[r["image_uuid"]].add(r["label"])

    result = []
    for p in photos:
        uuid = p["uuid"]
        result.append({
            "id": uuid,
            "t": p["captured"],
            "lat": p["lat"],
            "lon": p["lon"],
            "faces": list(faces_map.get(uuid, set())),
            "objects": list(objects_map.get(uuid, set()))[:5],
        })
    return result


def compute_temporal(photos):
    """X = day index (0-91), Y = hour of day (0-23)."""
    epoch = datetime(2025, 1, 1)
    layout = {}
    for p in photos:
        dt = datetime.fromisoformat(p["t"].replace("+00:00", "+00:00").split("+")[0])
        day_idx = (dt - epoch).days
        hour = dt.hour + dt.minute / 60.0
        # Normalize to roughly -50..50 range (365 days)
        x = (day_idx / 365.0) * 100 - 50
        y = (hour / 24.0) * 80 - 40
        layout[p["id"]] = [round(x, 2), round(y, 2)]
    return layout


def compute_geographic(photos):
    """X = longitude (normalized), Y = latitude (normalized)."""
    lats = [p["lat"] for p in photos]
    lons = [p["lon"] for p in photos]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_range = max(lat_max - lat_min, 0.001)
    lon_range = max(lon_max - lon_min, 0.001)

    layout = {}
    for p in photos:
        x = ((p["lon"] - lon_min) / lon_range) * 100 - 50
        y = ((p["lat"] - lat_min) / lat_range) * 80 - 40
        # Add small jitter to prevent overlap
        import random
        random.seed(hash(p["id"]))
        x += random.uniform(-0.3, 0.3)
        y += random.uniform(-0.3, 0.3)
        layout[p["id"]] = [round(x, 2), round(y, 2)]
    return layout


def compute_social(photos):
    """Force-directed: photos with same person attract. Simple simulation."""
    import random

    # Group photos by person
    person_groups = defaultdict(list)
    solo = []
    for p in photos:
        if p["faces"]:
            for face in p["faces"]:
                person_groups[face].append(p["id"])
        else:
            solo.append(p["id"])

    # Assign initial positions: each person gets a cluster center
    person_centers = {}
    angle_step = 2 * math.pi / max(len(person_groups) + 1, 1)
    for i, person in enumerate(sorted(person_groups.keys())):
        angle = i * angle_step
        r = 25
        person_centers[person] = (math.cos(angle) * r, math.sin(angle) * r)

    # Solo photos get scattered in outer ring
    layout = {}
    random.seed(42)

    for person, ids in person_groups.items():
        cx, cy = person_centers[person]
        for j, pid in enumerate(ids):
            # Spiral within cluster
            angle = j * 0.5
            r = math.sqrt(j + 1) * 1.5
            x = cx + math.cos(angle) * r
            y = cy + math.sin(angle) * r
            layout[pid] = [round(x, 2), round(y, 2)]

    # Solo photos in outer scattered ring
    for j, pid in enumerate(solo):
        angle = j * 0.1 + random.uniform(-0.05, 0.05)
        r = 35 + random.uniform(0, 15)
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        layout[pid] = [round(x, 2), round(y, 2)]

    return layout


def compute_engagement(photos):
    """X = photo count that day (engagement), Y = radius from home."""
    # Count photos per day
    day_counts = defaultdict(int)
    for p in photos:
        day = p["t"][:10]
        day_counts[day] += 1

    max_count = max(day_counts.values()) if day_counts else 1

    layout = {}
    for p in photos:
        day = p["t"][:10]
        count = day_counts[day]
        radius = haversine_km(HOME_LAT, HOME_LON, p["lat"], p["lon"])

        # Normalize
        x = (count / max_count) * 80 - 40
        y = min(radius, 20) / 20.0 * 60 - 30

        # Jitter within day cluster
        import random
        random.seed(hash(p["id"]) + 1)
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)

        layout[p["id"]] = [round(x, 2), round(y, 2)]
    return layout


def compute_radius(photos):
    """Concentric circles from home. Angle = chronological order."""
    import random
    epoch = datetime(2025, 10, 1)
    layout = {}
    for i, p in enumerate(photos):
        dist = haversine_km(HOME_LAT, HOME_LON, p["lat"], p["lon"])
        # Radius in layout space: log scale so nearby variation is visible
        r = math.log1p(dist * 5) * 12  # 0km→0, 1km→~10, 5km→~20, 20km→~35

        # Angle = chronological position (full circle = all photos)
        angle = (i / max(len(photos) - 1, 1)) * 2 * math.pi - math.pi / 2

        random.seed(hash(p["id"]) + 2)
        r += random.uniform(-0.5, 0.5)
        angle += random.uniform(-0.01, 0.01)

        x = math.cos(angle) * r
        y = math.sin(angle) * r
        layout[p["id"]] = [round(x, 2), round(y, 2)]
    return layout


def compute_objects(photos):
    """Labeled columns: top 12 object types (excluding 'person'), photos sorted by date."""
    from collections import Counter

    SKIP = {"person"}  # too common
    MIN_COUNT = 10

    # Count objects across all photos (each photo contributes its objects)
    label_photos = defaultdict(list)  # label → list of photo ids, sorted by date
    for p in photos:
        if not p["objects"]:
            continue
        for obj in p["objects"]:
            if obj not in SKIP:
                label_photos[obj].append(p["id"])

    # Top 12 by count, with minimum threshold
    top_labels = [
        label for label, ids in
        sorted(label_photos.items(), key=lambda x: -len(x[1]))
        if len(ids) >= MIN_COUNT
    ][:12]

    # Column layout
    COL_WIDTH = 8   # horizontal spacing between columns
    ROW_HEIGHT = 1.2  # vertical spacing between photos in column

    layout = {}
    placed = set()

    for col_idx, label in enumerate(top_labels):
        ids = label_photos[label]
        x = (col_idx - len(top_labels) / 2) * COL_WIDTH

        for row_idx, pid in enumerate(ids):
            if pid in placed:
                continue  # each photo placed once (by first matching label)
            placed.add(pid)
            y = -row_idx * ROW_HEIGHT + 30  # newest at top (positive y = up)
            layout[pid] = [round(x, 2), round(y, 2)]

    # Photos with no objects or not in top 12: push far off
    unclassified_x = round(len(top_labels) / 2 * COL_WIDTH + 20, 2)
    unclassified_ids = []
    for p in photos:
        if p["id"] not in layout:
            layout[p["id"]] = [unclassified_x, 0]
            unclassified_ids.append(p["id"])

    # Column metadata for labeling
    columns = []
    for col_idx, label in enumerate(top_labels):
        x = (col_idx - len(top_labels) / 2) * COL_WIDTH
        count = len([pid for pid in label_photos[label] if pid in placed])
        columns.append({"label": label, "x": round(x, 2), "count": count})

    return layout, columns, set(unclassified_ids)


def main():
    print("Loading photos...")
    photos = get_photos()
    print(f"Found {len(photos)} photos")

    print("Computing temporal layout...")
    temporal = compute_temporal(photos)

    print("Computing geographic layout...")
    geographic = compute_geographic(photos)

    print("Computing social layout...")
    social = compute_social(photos)

    print("Computing engagement layout...")
    engagement = compute_engagement(photos)

    print("Computing radius layout...")
    radius = compute_radius(photos)

    print("Computing objects layout...")
    objects_layout, objects_columns, objects_unclassified = compute_objects(photos)

    # Build output: photo data + all layouts
    output = {
        "photos": photos,
        "layouts": {
            "time": temporal,
            "place": geographic,
            "people": social,
            "engagement": engagement,
            "radius": radius,
            "objects": objects_layout,
        },
        "objectColumns": [{"label": c["label"], "x": c["x"], "count": c["count"]} for c in objects_columns],
        "objectsUnclassified": list(objects_unclassified),
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f)

    print(f"Saved to {OUTPUT} ({len(photos)} photos x 6 layouts)")


if __name__ == "__main__":
    main()
