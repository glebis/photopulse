#!/usr/bin/env python3
"""
Link vault notes to related photos from photoindex.

Reads a note, extracts people names, dates, and locations,
then finds matching photos via face detection + GPS + date.
Outputs a "Related Photos" section to append to the note.

Usage:
    python3 link_photos.py "~/Research/vault/20250507 two years with Yulia.md"
    python3 link_photos.py "~/Research/vault/20250507 two years with Yulia.md" --inject
    python3 link_photos.py --person Yulia --limit 20
    python3 link_photos.py --person Yulia --date-range 2025-01-01 2025-12-31
"""

import argparse
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / "ai_projects/photoimport/photoindex.sqlite"
THUMB_DIR = Path.home() / "ai_projects/photoimport/thumbs"

KNOWN_PEOPLE = {"Yulia", "Olga", "Alexander", "Mark", "Anastasia", "Gosha Kalinin", "Maria"}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def extract_note_context(note_path):
    """Extract people, dates, and keywords from a note."""
    text = Path(note_path).expanduser().read_text(errors="replace")
    title = Path(note_path).stem

    # Extract people mentioned
    people = set()
    for person in KNOWN_PEOPLE:
        if person.lower() in text.lower() or person.lower() in title.lower():
            people.add(person)

    # Also check for [[@Person]] wikilinks
    for match in re.findall(r'\[\[@?([^\]]+)\]\]', text):
        for person in KNOWN_PEOPLE:
            if person.lower() in match.lower():
                people.add(person)

    # Extract dates from title and content
    dates = set()
    # Title date: YYYYMMDD or YYYY-MM-DD
    for m in re.finditer(r'(\d{4})-?(\d{2})-?(\d{2})', title):
        dates.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    # Content dates
    for m in re.finditer(r'(\d{4})-(\d{2})-(\d{2})', text):
        dates.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")

    return {
        "people": people,
        "dates": dates,
        "text": text,
        "title": title,
    }


def find_photos_by_person(conn, person, limit=50, date_start=None, date_end=None):
    """Find photos containing a specific person."""
    query = """
        SELECT DISTINCT i.uuid, i.captured, i.lat, i.lon
        FROM images i JOIN faces f ON f.image_uuid = i.uuid
        WHERE f.person_name = ? AND i.is_screenshot = 0
    """
    params = [person]

    if date_start:
        query += " AND i.captured >= ?"
        params.append(date_start)
    if date_end:
        query += " AND i.captured <= ?"
        params.append(date_end)

    query += " ORDER BY i.captured DESC LIMIT ?"
    params.append(limit)

    return conn.execute(query, params).fetchall()


def find_photos_by_date(conn, date_str, margin_days=1):
    """Find photos from a specific date (±margin)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    start = (dt - timedelta(days=margin_days)).strftime("%Y-%m-%d")
    end = (dt + timedelta(days=margin_days + 1)).strftime("%Y-%m-%d")

    return conn.execute("""
        SELECT uuid, captured, lat, lon
        FROM images
        WHERE captured >= ? AND captured < ?
          AND is_screenshot = 0
        ORDER BY captured
        LIMIT 100
    """, (start, end)).fetchall()


def find_photos_for_note(conn, note_context, limit=30):
    """Find all related photos for a note. Person matches first, then date."""
    photos = {}  # uuid → {photo, reasons}

    # By person FIRST (highest priority)
    # If note has dates, scope person search to ±30 days of those dates
    for person in note_context["people"]:
        person_results = []
        if note_context["dates"]:
            for date_str in note_context["dates"]:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    start = (dt - timedelta(days=30)).strftime("%Y-%m-%d")
                    end = (dt + timedelta(days=30)).strftime("%Y-%m-%d")
                    person_results.extend(find_photos_by_person(conn, person, limit=500, date_start=start, date_end=end))
                except ValueError:
                    person_results.extend(find_photos_by_person(conn, person, limit=limit))
        else:
            person_results = find_photos_by_person(conn, person, limit=limit)
        for p in person_results:
            if p["uuid"] not in photos:
                photos[p["uuid"]] = {"photo": p, "reasons": set()}
            photos[p["uuid"]]["reasons"].add(f"face:{person}")

    # By date (adds to existing or creates new)
    for date_str in note_context["dates"]:
        results = find_photos_by_date(conn, date_str)
        for p in results:
            if p["uuid"] not in photos:
                photos[p["uuid"]] = {"photo": p, "reasons": set()}
            photos[p["uuid"]]["reasons"].add(f"date:{date_str}")

    # Sort by number of reasons (most connected first), then by date
    sorted_photos = sorted(
        photos.values(),
        key=lambda x: (-len(x["reasons"]), x["photo"]["captured"] or ""),
    )

    return sorted_photos[:limit]


VAULT_PHOTOS_DIR = Path.home() / "Research" / "vault" / "Attachments" / "photos"
THUMB_SERVER = "http://100.97.18.14:8080"


def ensure_photo_in_vault(uuid):
    """Copy thumbnail to vault Attachments if not already there. Returns filename."""
    VAULT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid}.jpg"
    dest = VAULT_PHOTOS_DIR / filename
    if not dest.exists():
        src = THUMB_DIR / filename
        if src.exists():
            import shutil
            shutil.copy2(src, dest)
    return filename


def format_photo_entry(entry):
    """Format a single photo as an Obsidian embed with source link."""
    p = entry["photo"]
    uuid = p["uuid"]
    date = (p["captured"] or "")[:16].replace("T", " ")
    filename = ensure_photo_in_vault(uuid)
    source_url = f"{THUMB_SERVER}/{uuid}.jpg"
    return f"![[photos/{filename}|200]]\n*{date}* · [source]({source_url})"


def format_photo_section(photos):
    """Format a markdown section with embedded photos and source links."""
    if not photos:
        return "\n## 📸 Related Photos\n\nNo matching photos found.\n"

    lines = ["\n## 📸 Related Photos\n"]
    lines.append(f"*{len(photos)} photos linked by face detection and date matching.*\n")

    # Group by primary reason
    by_person = {}
    by_date = {}
    seen = set()
    for entry in photos:
        reasons = entry["reasons"]
        persons = [r.split(":")[1] for r in reasons if r.startswith("face:")]
        dates = [r.split(":")[1] for r in reasons if r.startswith("date:")]

        if persons:
            for person in persons:
                by_person.setdefault(person, []).append(entry)
                seen.add(entry["photo"]["uuid"])
        if dates:
            for d in dates:
                by_date.setdefault(d, []).append(entry)

    # Format person groups
    for person, entries in sorted(by_person.items()):
        lines.append(f"\n### With {person} ({len(entries)} photos)\n")
        for entry in entries[:10]:
            lines.append(format_photo_entry(entry))
            lines.append("")

    # Format date groups (only photos not already shown under person)
    for date_str, entries in sorted(by_date.items()):
        new_entries = [e for e in entries if e["photo"]["uuid"] not in seen]
        if new_entries:
            lines.append(f"\n### From {date_str} ({len(new_entries)} photos)\n")
            for entry in new_entries[:10]:
                lines.append(format_photo_entry(entry))
                lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Link vault notes to photos")
    parser.add_argument("note", nargs="?", help="Path to vault note")
    parser.add_argument("--person", help="Find photos of a specific person")
    parser.add_argument("--date-range", nargs=2, metavar=("START", "END"),
                        help="Date range YYYY-MM-DD YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=30, help="Max photos")
    parser.add_argument("--inject", action="store_true",
                        help="Append to the note file")
    args = parser.parse_args()

    conn = get_db()

    if args.person:
        # Direct person query
        photos = find_photos_by_person(
            conn, args.person, limit=args.limit,
            date_start=args.date_range[0] if args.date_range else None,
            date_end=args.date_range[1] if args.date_range else None,
        )
        print(f"Found {len(photos)} photos with {args.person}")
        for p in photos[:10]:
            print(f"  {(p['captured'] or '')[:16]}  {p['uuid'][:12]}...")
        conn.close()
        return

    if not args.note:
        parser.error("Provide a note path or --person")

    note_path = Path(args.note).expanduser()
    if not note_path.exists():
        print(f"Note not found: {note_path}")
        return

    # Extract context and find photos
    context = extract_note_context(note_path)
    print(f"Note: {context['title']}")
    print(f"People mentioned: {context['people'] or 'none'}")
    print(f"Dates found: {context['dates'] or 'none'}")

    photos = find_photos_for_note(conn, context, limit=args.limit)
    print(f"Found {len(photos)} related photos")

    section = format_photo_section(photos)
    print(section)

    if args.inject:
        content = note_path.read_text(errors="replace")
        # Remove existing section if present
        marker = "## 📸 Related Photos"
        if marker in content:
            start = content.index(marker)
            # Find next ## or end
            rest = content[start + len(marker):]
            next_h2 = rest.find("\n## ")
            if next_h2 >= 0:
                end = start + len(marker) + next_h2
            else:
                end = len(content)
            content = content[:start].rstrip() + "\n" + content[end:].lstrip("\n")

        content = content.rstrip() + "\n" + section
        note_path.write_text(content)
        print(f"Injected into {note_path}")

    conn.close()


if __name__ == "__main__":
    main()
