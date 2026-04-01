#!/usr/bin/env python3
"""Pre-compute 4 spatial layouts for the folding photo explorer."""

import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path.home() / "ai_projects/photoimport/photoindex.sqlite"
OUT = Path(__file__).parent

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

# Load photos
photos = conn.execute("""
    SELECT uuid, captured, lat, lon, people_count
    FROM images
    WHERE strftime('%Y-%m', captured) IN ('2025-10','2025-11','2025-12')
      AND is_screenshot = 0 AND lat > -100
    ORDER BY captured
""").fetchall()

# Load faces
faces_raw = conn.execute("""
    SELECT i.uuid, f.person_name
    FROM faces f JOIN images i ON f.image_uuid = i.uuid
    WHERE strftime('%Y-%m', i.captured) IN ('2025-10','2025-11','2025-12')
      AND f.person_name IS NOT NULL AND f.person_name != '' AND f.person_name != 'Gleb'
      AND i.is_screenshot = 0
""").fetchall()
face_map = defaultdict(list)
for r in faces_raw:
    face_map[r["uuid"]].append(r["person_name"])

# Load objects
obj_raw = conn.execute("""
    SELECT d.image_uuid as uuid, d.label, COUNT(*) as cnt
    FROM detections d JOIN images i ON d.image_uuid = i.uuid
    WHERE strftime('%Y-%m', i.captured) IN ('2025-10','2025-11','2025-12')
      AND i.is_screenshot = 0 AND d.label != 'person'
    GROUP BY d.image_uuid, d.label ORDER BY d.image_uuid, cnt DESC
""").fetchall()
obj_map = defaultdict(list)
for r in obj_raw:
    if len(obj_map[r["uuid"]]) < 3:
        obj_map[r["uuid"]].append(r["label"])

# Daily stats for engagement layout
from datetime import datetime

daily_counts = Counter()
daily_radius = {}
HOME_LAT, HOME_LON = 52.553, 13.400

for p in photos:
    day = p["captured"][:10]
    daily_counts[day] += 1
    lat, lon = p["lat"], p["lon"]
    R = 6371
    dlat = math.radians(lat - HOME_LAT)
    dlon = math.radians(lon - HOME_LON)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(HOME_LAT)) * math.cos(math.radians(lat)) * math.sin(dlon/2)**2
    dist = R * 2 * math.asin(math.sqrt(a))
    if day not in daily_radius or dist > daily_radius[day]:
        daily_radius[day] = dist

max_daily = max(daily_counts.values()) if daily_counts else 1
max_radius = max(daily_radius.values()) if daily_radius else 1

# Reference date for day index
from datetime import date
ref_date = date(2025, 10, 1)

SPREAD = 800  # Canvas spread in pixels


def temporal_layout():
    """X = day index (0-91), Y = hour of day."""
    positions = {}
    for p in photos:
        d = date.fromisoformat(p["captured"][:10])
        day_idx = (d - ref_date).days
        try:
            hour = int(p["captured"][11:13])
            minute = int(p["captured"][14:16])
        except (ValueError, IndexError):
            hour, minute = 12, 0
        frac_hour = hour + minute / 60

        x = (day_idx / 92) * SPREAD - SPREAD / 2
        y = (frac_hour / 24) * SPREAD * 0.6 - SPREAD * 0.3
        # Jitter to avoid stacking
        x += (hash(p["uuid"][:8]) % 100 - 50) * 0.08
        y += (hash(p["uuid"][8:16]) % 100 - 50) * 0.08
        positions[p["uuid"]] = [round(x, 1), round(y, 1)]
    return positions


def geographic_layout():
    """X = longitude, Y = latitude (normalized to Berlin)."""
    lats = [p["lat"] for p in photos]
    lons = [p["lon"] for p in photos]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_range = max(max_lat - min_lat, 0.001)
    lon_range = max(max_lon - min_lon, 0.001)

    positions = {}
    for p in photos:
        x = ((p["lon"] - min_lon) / lon_range) * SPREAD - SPREAD / 2
        y = -((p["lat"] - min_lat) / lat_range) * SPREAD * 0.6 + SPREAD * 0.3  # Flip Y
        x += (hash(p["uuid"][:6]) % 60 - 30) * 0.05
        y += (hash(p["uuid"][6:12]) % 60 - 30) * 0.05
        positions[p["uuid"]] = [round(x, 1), round(y, 1)]
    return positions


def social_layout():
    """Force-directed: photos with same person cluster together."""
    positions = {}

    # Group by primary face
    groups = defaultdict(list)
    for p in photos:
        faces = face_map.get(p["uuid"], [])
        key = faces[0] if faces else "_solo"
        groups[key].append(p["uuid"])

    # Assign cluster centers in a circle
    group_names = sorted(groups.keys())
    n_groups = len(group_names)
    centers = {}
    for i, name in enumerate(group_names):
        if name == "_solo":
            # Solo photos scatter in the outer ring
            centers[name] = (0, 0, SPREAD * 0.45)  # center + large radius
        else:
            angle = (i / max(n_groups - 1, 1)) * math.pi * 1.6 - math.pi * 0.8
            r = SPREAD * 0.25
            centers[name] = (math.cos(angle) * r, math.sin(angle) * r, SPREAD * 0.12)

    for name, uuids in groups.items():
        cx, cy, spread = centers[name]
        n = len(uuids)
        for j, uuid in enumerate(uuids):
            if name == "_solo":
                # Scatter in outer ring
                a = (j / max(n, 1)) * math.pi * 2
                r = spread + (hash(uuid[:8]) % 100) * 0.5
                x = math.cos(a) * r
                y = math.sin(a) * r
            else:
                # Cluster around center with chronological spiral
                a = (j / max(n, 1)) * math.pi * 4
                r = spread * (0.3 + 0.7 * j / max(n, 1))
                x = cx + math.cos(a) * r
                y = cy + math.sin(a) * r
            positions[uuid] = [round(x, 1), round(y, 1)]

    return positions


def engagement_layout():
    """X = daily photo count, Y = radius from home."""
    positions = {}
    for p in photos:
        day = p["captured"][:10]
        cnt = daily_counts.get(day, 1)
        rad = daily_radius.get(day, 0)

        x = (cnt / max_daily) * SPREAD * 0.8 - SPREAD * 0.4
        y = -(rad / max(max_radius, 0.1)) * SPREAD * 0.5 + SPREAD * 0.25

        # Jitter within day cluster
        x += (hash(p["uuid"][:8]) % 80 - 40) * 0.15
        y += (hash(p["uuid"][8:16]) % 80 - 40) * 0.15
        positions[p["uuid"]] = [round(x, 1), round(y, 1)]
    return positions


# Compute all layouts
print("Computing layouts...")
layouts = {
    "time": temporal_layout(),
    "place": geographic_layout(),
    "people": social_layout(),
    "engagement": engagement_layout(),
}

# Build combined data
data = []
for p in photos:
    uid = p["uuid"]
    data.append({
        "id": uid,
        "t": p["captured"],
        "faces": face_map.get(uid, []),
        "objects": obj_map.get(uid, []),
        "pos": {
            "time": layouts["time"].get(uid, [0, 0]),
            "place": layouts["place"].get(uid, [0, 0]),
            "people": layouts["people"].get(uid, [0, 0]),
            "engagement": layouts["engagement"].get(uid, [0, 0]),
        },
    })

(OUT / "fold_data.json").write_text(json.dumps(data, separators=(",", ":")))
print(f"Exported {len(data)} photos with 4 layouts to fold_data.json")
conn.close()
