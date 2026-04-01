#!/usr/bin/env python3
"""Export full dataset for calendar, EKG, and replay visualizations."""

import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
OUT_DIR = Path(__file__).parent

HOME_LAT = 52.553
HOME_LON = 13.400

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    photos = conn.execute("""
        SELECT uuid, captured, lat, lon
        FROM images
        WHERE (is_screenshot != 1 OR is_screenshot IS NULL)
          AND captured IS NOT NULL
        ORDER BY captured
    """).fetchall()

    faces_raw = conn.execute("""
        SELECT f.image_uuid, f.person_name
        FROM faces f JOIN images i ON f.image_uuid = i.uuid
        WHERE f.person_name IS NOT NULL AND f.person_name != '' AND f.person_name != 'Gleb'
          AND (i.is_screenshot != 1 OR i.is_screenshot IS NULL)
    """).fetchall()
    faces_by_uuid = defaultdict(set)
    for r in faces_raw:
        faces_by_uuid[r["image_uuid"]].add(r["person_name"])

    conn.close()

    # --- Calendar + EKG data ---
    day_data = defaultdict(lambda: {"count": 0, "faces": set(), "lats": [], "lons": [], "face_count": 0, "best_uuid": None, "best_faces": -1})
    for p in photos:
        day = p["captured"][:10]
        d = day_data[day]
        d["count"] += 1
        ufaces = faces_by_uuid.get(p["uuid"], set())
        d["faces"].update(ufaces)
        d["face_count"] += len(ufaces)
        if p["lat"] and p["lat"] > -179 and p["lon"] and p["lon"] > -179:
            d["lats"].append(p["lat"])
            d["lons"].append(p["lon"])
        # Pick representative photo: most faces, or first photo of the day
        n_faces = len(ufaces)
        if n_faces > d["best_faces"] or d["best_uuid"] is None:
            d["best_uuid"] = p["uuid"]
            d["best_faces"] = n_faces

    calendar = []
    for day in sorted(day_data.keys()):
        d = day_data[day]
        lat = sum(d["lats"]) / len(d["lats"]) if d["lats"] else None
        lon = sum(d["lons"]) / len(d["lons"]) if d["lons"] else None
        radius = haversine_km(HOME_LAT, HOME_LON, lat, lon) if lat else 0
        calendar.append({
            "d": day,
            "n": d["count"],       # photo count
            "id": d["best_uuid"],  # representative photo UUID
            "f": sorted(d["faces"])[:3],
            "fc": d["face_count"],  # face detection count
            "r": round(radius, 1),  # radius from home km
        })

    with open(OUT_DIR / "calendar_data.json", "w") as f:
        json.dump(calendar, f)
    print(f"calendar_data.json: {len(calendar)} days")

    # EKG uses same format
    with open(OUT_DIR / "ekg_data.json", "w") as f:
        json.dump(calendar, f)
    print(f"ekg_data.json: {len(calendar)} days")

    # --- Replay data: every photo with VALID GPS ---
    replay = []
    for p in photos:
        if p["lat"] and p["lat"] > -179 and p["lon"] and p["lon"] > -179:
            if p["lat"] < -90 or p["lat"] > 90:
                continue  # invalid latitude
            replay.append({
                "t": p["captured"],
                "lat": round(p["lat"], 5),
                "lon": round(p["lon"], 5),
                "id": p["uuid"],
            })

    with open(OUT_DIR / "replay_data.json", "w") as f:
        json.dump(replay, f)
    print(f"replay_data.json: {len(replay)} photos with valid GPS")

if __name__ == "__main__":
    main()
