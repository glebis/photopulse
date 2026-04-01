#!/usr/bin/env python3
"""
Photo Pulse — Behavioral health insights from your camera roll.

Queries photoindex.sqlite and generates a reflective daily note section
showing engagement, movement, connection, rhythm, and novelty patterns.
Framed as a behavioral health tool: photography patterns as proxy signals
for engagement, mood, movement, and social connection.

Usage:
    python3 photopulse.py                    # Yesterday (or most recent)
    python3 photopulse.py 2025-03-28         # Specific date
    python3 photopulse.py --inject           # Append to today's daily note
    python3 photopulse.py 2025-03-28 --inject
"""

import math
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
VAULT_DAILY = Path.home() / "Research" / "vault" / "Daily"

HOME_LAT = 52.553
HOME_LON = 13.400
BASELINE_DAYS = 30

NEIGHBORHOODS = [
    (52.555, 13.350, "Wedding"),
    (52.541, 13.413, "Prenzlauer Berg"),
    (52.520, 13.410, "Friedrichshain"),
    (52.497, 13.391, "Kreuzberg"),
    (52.520, 13.370, "Mitte"),
    (52.540, 13.350, "Gesundbrunnen"),
    (52.500, 13.450, "Lichtenberg"),
    (52.480, 13.430, "Treptow"),
    (52.470, 13.350, "Neukölln"),
    (52.510, 13.330, "Schöneberg"),
    (52.530, 13.300, "Moabit"),
    (52.510, 13.280, "Charlottenburg"),
    (52.560, 13.450, "Pankow"),
    (52.460, 13.400, "Tempelhof"),
]

# Objects too common to be interesting as novelty
COMMON_OBJECTS = {
    "person", "book", "car", "chair", "cell phone", "bottle", "tv", "cup",
    "bowl", "laptop", "potted plant", "traffic light", "bicycle", "dog",
    "cat", "bird", "backpack", "handbag", "umbrella", "bench", "clock",
}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def neighborhood_name(lat, lon):
    best, best_dist = None, float("inf")
    for nlat, nlon, name in NEIGHBORHOODS:
        d = haversine_km(lat, lon, nlat, nlon)
        if d < best_dist:
            best_dist, best = d, name
    return best if best_dist < 5 else None


def cluster_locations(coords, radius_m=200):
    """Cluster GPS points within radius_m of each other."""
    clusters = []
    for lat, lon in coords:
        merged = False
        for c in clusters:
            if haversine_km(lat, lon, c["lat"], c["lon"]) < radius_m / 1000:
                c["count"] += 1
                merged = True
                break
        if not merged:
            clusters.append({"lat": lat, "lon": lon, "count": 1})
    return clusters


def calc_median(values):
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_most_recent_day(conn):
    row = conn.execute(
        "SELECT date(MAX(captured)) as d FROM images "
        "WHERE is_screenshot = 0 AND lat > -100"
    ).fetchone()
    return row["d"] if row else None


def get_day_photos(conn, target_date):
    return conn.execute(
        "SELECT uuid, captured, lat, lon FROM images "
        "WHERE date(captured) = ? AND is_screenshot = 0 AND lat > -100 "
        "ORDER BY captured",
        (target_date,),
    ).fetchall()


def get_faces(conn, target_date):
    rows = conn.execute(
        "SELECT f.person_name, COUNT(*) as cnt "
        "FROM faces f JOIN images i ON f.image_uuid = i.uuid "
        "WHERE date(i.captured) = ? AND f.person_name IS NOT NULL "
        "AND f.person_name != '' AND i.is_screenshot = 0 "
        "GROUP BY f.person_name ORDER BY cnt DESC",
        (target_date,),
    ).fetchall()
    return {r["person_name"]: r["cnt"] for r in rows if r["person_name"] != "Gleb"}


def get_objects(conn, target_date):
    rows = conn.execute(
        "SELECT d.label, COUNT(*) as cnt "
        "FROM detections d JOIN images i ON d.image_uuid = i.uuid "
        "WHERE date(i.captured) = ? AND i.is_screenshot = 0 "
        "AND d.label != 'person' "
        "GROUP BY d.label ORDER BY cnt DESC",
        (target_date,),
    ).fetchall()
    return {r["label"]: r["cnt"] for r in rows}


def get_baseline(conn, target_date, days=BASELINE_DAYS):
    start = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date(captured) as d, COUNT(*) as cnt FROM images "
        "WHERE date(captured) BETWEEN ? AND ? "
        "AND is_screenshot = 0 AND lat > -100 "
        "GROUP BY d ORDER BY d",
        (start, target_date),
    ).fetchall()
    return [r["cnt"] for r in rows if r["d"] != target_date]


def get_week_counts(conn, target_date):
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    rows = conn.execute(
        "SELECT date(captured) as d, COUNT(*) as cnt FROM images "
        "WHERE date(captured) BETWEEN ? AND ? "
        "AND is_screenshot = 0 AND lat > -100 "
        "GROUP BY d ORDER BY d",
        (monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")),
    ).fetchall()
    return [(r["d"], r["cnt"]) for r in rows]


def get_recent_locations(conn, target_date, days=90):
    start = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT lat, lon FROM images "
        "WHERE date(captured) BETWEEN ? AND ? "
        "AND lat > -100 AND is_screenshot = 0 AND date(captured) != ?",
        (start, target_date, target_date),
    ).fetchall()
    return [(r["lat"], r["lon"]) for r in rows]


def get_object_baselines(conn, target_date, days=90):
    start = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    total_days = conn.execute(
        "SELECT COUNT(DISTINCT date(captured)) as d FROM images "
        "WHERE date(captured) BETWEEN ? AND ? AND is_screenshot = 0",
        (start, target_date),
    ).fetchone()["d"]
    total_days = max(total_days, 1)
    rows = conn.execute(
        "SELECT d.label, COUNT(*) as cnt "
        "FROM detections d JOIN images i ON d.image_uuid = i.uuid "
        "WHERE date(i.captured) BETWEEN ? AND ? AND i.is_screenshot = 0 "
        "GROUP BY d.label",
        (start, target_date),
    ).fetchall()
    return {r["label"]: r["cnt"] / total_days for r in rows}


def get_radius_history(conn, target_date, days=14):
    start = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date(captured) as d, lat, lon FROM images "
        "WHERE date(captured) BETWEEN ? AND ? "
        "AND is_screenshot = 0 AND lat > -100 ORDER BY d",
        (start, target_date),
    ).fetchall()
    daily = {}
    for r in rows:
        d = r["d"]
        dist = haversine_km(HOME_LAT, HOME_LON, r["lat"], r["lon"])
        if d not in daily or dist > daily[d]:
            daily[d] = dist
    return daily


def count_consecutive_quiet_days(conn, target_date, threshold):
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    streak = 0
    for i in range(1, 30):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt = conn.execute(
            "SELECT COUNT(*) as c FROM images WHERE date(captured) = ? "
            "AND is_screenshot = 0",
            (d,),
        ).fetchone()["c"]
        if cnt <= threshold:
            streak += 1
        else:
            break
    return streak


def compute_hours(photos):
    hours = []
    for p in photos:
        if p["captured"]:
            try:
                hours.append(int(p["captured"][11:13]))
            except (ValueError, IndexError):
                pass
    return hours


def describe_rhythm(hours, count):
    if not hours:
        return ""
    morning = sum(1 for h in hours if 6 <= h < 12)
    afternoon = sum(1 for h in hours if 12 <= h < 17)
    evening = sum(1 for h in hours if 17 <= h < 22)
    parts = []
    if morning > count * 0.2:
        parts.append("morning")
    if afternoon > count * 0.2:
        parts.append("afternoon")
    if evening > count * 0.2:
        parts.append("evening")
    if len(parts) >= 3:
        return "Spread across the day."
    elif len(parts) == 2:
        return f"Two windows — {parts[0]} and {parts[1]}."
    elif parts:
        return f"{parts[0].capitalize()} focus."
    return "Spread across the day."


def find_surprises(objects, obj_baselines, faces, clusters, recent_clusters, hours):
    """Find 1-2 interesting observations from multiple lenses."""
    surprises = []

    # Temporal anomaly
    if hours:
        if min(hours) < 7:
            surprises.append(
                f"First photo at {min(hours)}:00 — you were up early."
            )
        elif min(hours) >= 13 and len(hours) > 5:
            surprises.append(
                f"First photo at {min(hours)}:00. "
                f"Late start — rough night or slow morning?"
            )
        if max(hours) >= 23:
            surprises.append(f"Late-night photo after {max(hours)}:00.")

    # Object novelty (skip common objects)
    for obj, count in objects.items():
        if obj in COMMON_OBJECTS:
            continue
        baseline = obj_baselines.get(obj, 0)
        if baseline < 0.5 and count >= 2:
            surprises.append(
                f'"{obj}" appeared {count} times — '
                f"that almost never shows up. Something new?"
            )
            break
        elif baseline > 0 and count / max(baseline, 0.1) > 5 and count >= 3:
            surprises.append(
                f'"{obj}" ({count}×) — well above your usual. '
                f"New activities or new places?"
            )
            break

    # Location novelty
    if clusters and recent_clusters:
        new_places = 0
        new_hood = None
        for c in clusters:
            is_new = all(
                haversine_km(c["lat"], c["lon"], rc["lat"], rc["lon"]) >= 0.3
                for rc in recent_clusters
            )
            if is_new:
                new_places += 1
                if not new_hood:
                    new_hood = neighborhood_name(c["lat"], c["lon"])
        if new_places > 0:
            if new_hood:
                surprises.append(
                    f"You photographed somewhere new — {new_hood} "
                    f"hasn't appeared in your photos recently."
                )
            elif new_places >= 2:
                surprises.append(
                    f"{new_places} locations you haven't photographed "
                    f"in the last 90 days."
                )

    return surprises[:2]


def week_trend(week_counts):
    if len(week_counts) < 4:
        return "steady"
    counts = [c for _, c in week_counts]
    first = sum(counts[: len(counts) // 2]) / max(len(counts) // 2, 1)
    second = sum(counts[len(counts) // 2 :]) / max(
        len(counts) - len(counts) // 2, 1
    )
    if second > first * 1.3:
        return "expanding"
    elif second < first * 0.7:
        return "contracting"
    return "steady"


# --- Output ---


def generate_pulse(target_date=None):
    conn = get_db()

    most_recent = get_most_recent_day(conn)
    if not most_recent:
        conn.close()
        return "### 📸 Photo Pulse\n\nNo photos found in the database.\n"

    if target_date is None:
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        test = get_day_photos(conn, yesterday)
        target_date = yesterday if test else most_recent

    dt = datetime.strptime(target_date, "%Y-%m-%d")
    day_name = dt.strftime("%A")
    day_display = dt.strftime("%b %-d")
    days_stale = (datetime.now() - datetime.strptime(most_recent, "%Y-%m-%d")).days

    lines = [f"### 📸 Photo Pulse — {day_display}", ""]

    if days_stale > 7 and target_date == most_recent:
        lines.append(
            f"*Last photo: {most_recent}. Import may need attention "
            f"— {days_stale} days since last capture.*"
        )
        lines.append("")

    photos = get_day_photos(conn, target_date)
    count = len(photos)

    if count == 0:
        lines.append(f"**No photos** on {day_name}. A blank page.")
        lines.append("")
        conn.close()
        return "\n".join(lines)

    coords = [
        (p["lat"], p["lon"])
        for p in photos
        if p["lat"] is not None and p["lat"] > -100
    ]

    hours = compute_hours(photos)
    faces = get_faces(conn, target_date)
    objects = get_objects(conn, target_date)
    baseline_counts = get_baseline(conn, target_date)
    week_counts = get_week_counts(conn, target_date)
    clusters = cluster_locations(coords) if coords else []
    recent_coords = get_recent_locations(conn, target_date)
    recent_clusters = (
        cluster_locations(recent_coords, radius_m=300) if recent_coords else []
    )
    obj_baselines = get_object_baselines(conn, target_date)
    radius_km = (
        max(haversine_km(HOME_LAT, HOME_LON, lat, lon) for lat, lon in coords)
        if coords
        else 0
    )
    radius_history = get_radius_history(conn, target_date)

    bm = calc_median(baseline_counts)
    ratio = count / max(bm, 1)

    # --- Engagement ---
    if count <= 3:
        eng = f"**Quiet {day_name}.** {count} {'photo' if count == 1 else 'photos'}"
    elif ratio >= 2.5:
        eng = f"**Engaged day.** {count} photos — nearly {ratio:.0f}× your usual"
    elif ratio >= 1.5:
        eng = f"**Active {day_name}.** {count} photos — above your usual rhythm"
    elif ratio <= 0.5:
        eng = f"**Still day.** {count} photos — quieter than usual"
    else:
        eng = f"**Steady {day_name}.** {count} photos — close to your baseline"

    rhythm = describe_rhythm(hours, count)
    if rhythm:
        eng += f". {rhythm}"

    lines.append(eng)
    lines.append("")

    # --- Movement ---
    if clusters:
        n_loc = len(clusters)
        hoods = set()
        for c in clusters:
            n = neighborhood_name(c["lat"], c["lon"])
            if n:
                hoods.add(n)

        past_radii = [v for k, v in radius_history.items() if k != target_date]
        radius_ctx = ""
        if past_radii:
            if radius_km > max(past_radii) and radius_km > 1:
                radius_ctx = " Your widest radius in 2 weeks."
            elif radius_km < min(past_radii) and radius_km < 1:
                radius_ctx = " Smallest radius this week."

        if radius_km < 0.3:
            mv = "You stayed home."
        elif radius_km < 1:
            mv = f"Close to home — within {radius_km:.1f}km."
        elif radius_km < 3:
            mv = f"You covered ground — {radius_km:.1f}km from home."
        else:
            mv = f"Wide day — {radius_km:.1f}km from home."

        spots = "1 spot" if n_loc == 1 else f"{n_loc} spots"
        if hoods:
            hood_str = ", ".join(sorted(hoods))
            lines.append(
                f"**Movement:** {mv} {spots} across {hood_str}.{radius_ctx}"
            )
        else:
            lines.append(f"**Movement:** {mv}{radius_ctx}")
    else:
        lines.append("**Movement:** No GPS data for this day.")
    lines.append("")

    # --- Social ---
    if faces:
        top_name, top_cnt = next(iter(faces.items()))
        rest = [n for n in faces if n != top_name]
        if top_cnt >= 10:
            social = f"**Social:** {top_name} in {top_cnt} photos"
        elif top_cnt >= 3:
            social = f"**Social:** {top_name} was with you ({top_cnt} photos)"
        else:
            social = f"**Social:** {top_name} appeared briefly"
        if rest:
            social += f". Also: {', '.join(rest)}."
        else:
            social += "."
        lines.append(social)
    else:
        # Check if there are people around (just not recognized)
        person_objects = conn.execute(
            "SELECT COUNT(*) as cnt FROM detections d "
            "JOIN images i ON d.image_uuid = i.uuid "
            "WHERE date(i.captured) = ? AND d.label = 'person' "
            "AND i.is_screenshot = 0",
            (target_date,),
        ).fetchone()["cnt"]
        if person_objects > count * 0.5:
            lines.append("**Social:** No familiar faces, but people around you.")
        else:
            lines.append("**Social:** Solo — no familiar faces detected.")
    lines.append("")

    # --- Weekly Pattern ---
    if week_counts and len(week_counts) >= 3:
        wk_parts = []
        for d, c in week_counts:
            wk_parts.append(f"**{c}**" if d == target_date else str(c))
        wk_str = " → ".join(wk_parts)
        lines.append(f"**This week:** {wk_str}")
        lines.append("")

    # --- Surprises ---
    surprises = find_surprises(
        objects, obj_baselines, faces, clusters, recent_clusters, hours
    )
    if surprises:
        for s in surprises:
            lines.append(f"> {s}")
        lines.append("")

    # --- Week Summary ---
    if week_counts and len(week_counts) >= 3:
        trend = week_trend(week_counts)
        summaries = {
            "expanding": (
                "**Week summary: Expanding.** "
                "More movement and engagement than your baseline."
            ),
            "contracting": (
                "**Week summary: Contracting.** Energy winding down."
            ),
            "steady": (
                "**Week summary: Steady.** Close to your usual rhythm."
            ),
        }
        lines.append(summaries[trend])
        lines.append("")

    # --- Quiet Streak ---
    quiet_threshold = max(5, bm * 0.3) if bm > 0 else 5
    quiet_streak = count_consecutive_quiet_days(
        conn, target_date, quiet_threshold
    )
    if quiet_streak >= 5 and count <= quiet_threshold:
        lines.append(
            f"*{quiet_streak + 1} quiet days now. "
            f"Your radius has been small. How are you doing?*"
        )
        lines.append("")
    elif quiet_streak >= 3 and count <= quiet_threshold:
        lines.append(
            f"*Day {quiet_streak + 1} of quiet. "
            f"Could be rest. Could be withdrawal. "
            f"You know the difference.*"
        )
        lines.append("")

    conn.close()
    return "\n".join(lines)


def inject_into_daily_note(pulse_text, target_date=None):
    """Append pulse to today's Obsidian daily note."""
    if target_date is None:
        note_date = date.today()
    else:
        note_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    note_name = note_date.strftime("%Y%m%d") + ".md"
    note_path = VAULT_DAILY / note_name

    if not note_path.exists():
        note_path.write_text(
            f"# {note_date.strftime('%Y-%m-%d %A')}\n\n{pulse_text}\n"
        )
        print(f"Created daily note: {note_path}")
    else:
        content = note_path.read_text()
        marker = "### 📸 Photo Pulse"
        if marker in content:
            start = content.index(marker)
            rest = content[start + len(marker) :]
            next_section = rest.find("\n### ")
            if next_section >= 0:
                end = start + len(marker) + next_section
            else:
                end = len(content)
            content = (
                content[:start].rstrip()
                + "\n\n"
                + content[end:].lstrip()
            )
        content = content.rstrip() + "\n\n" + pulse_text + "\n"
        note_path.write_text(content)
        print(f"Updated daily note: {note_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    target = args[0] if args else None
    inject = "--inject" in flags

    pulse = generate_pulse(target)
    print(pulse)

    if inject:
        print("---")
        inject_into_daily_note(pulse, target)
