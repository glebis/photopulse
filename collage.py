#!/usr/bin/env python3
"""
Generate a photo collage grid for a given date.

Usage:
    python3 collage.py 2025-12-28
    python3 collage.py 2025-12-28 --output /path/to/output.jpg
"""

import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw

DB_PATH = Path.home() / "ai_projects" / "photoimport" / "photoindex.sqlite"
ASSETS_DIR = Path.home() / "ai_projects" / "photoimport" / "assets"
OUTPUT_DIR = Path(__file__).parent / "output"

THUMB_SIZE = 300
MAX_PHOTOS = 12
BG_COLOR = (10, 10, 15)  # #0a0a0f
PADDING = 4


def get_day_photos(target_date):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT path, uuid FROM images "
        "WHERE date(captured) = ? AND is_screenshot = 0 AND lat > -100 "
        "ORDER BY captured",
        (target_date,),
    ).fetchall()
    conn.close()
    return rows


def find_image_file(path_field, uuid):
    """Resolve the actual image file on disk."""
    # path is relative like "assets/UUID.jpg"
    full = ASSETS_DIR.parent / path_field
    if full.exists():
        return full
    # Try direct in assets with common extensions
    for ext in (".jpg", ".jpeg", ".png"):
        candidate = ASSETS_DIR / f"{uuid}{ext}"
        if candidate.exists():
            return candidate
    return None


def make_collage(target_date, output_path=None):
    photos = get_day_photos(target_date)
    if not photos:
        print(f"No photos for {target_date}")
        return None

    # Limit to MAX_PHOTOS, evenly sampled
    if len(photos) > MAX_PHOTOS:
        step = len(photos) / MAX_PHOTOS
        photos = [photos[int(i * step)] for i in range(MAX_PHOTOS)]

    # Load and resize thumbnails
    thumbs = []
    for p in photos:
        img_path = find_image_file(p["path"], p["uuid"])
        if not img_path:
            continue
        try:
            img = Image.open(img_path)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            # Create square thumbnail with dark bg
            square = Image.new("RGB", (THUMB_SIZE, THUMB_SIZE), BG_COLOR)
            offset_x = (THUMB_SIZE - img.width) // 2
            offset_y = (THUMB_SIZE - img.height) // 2
            square.paste(img, (offset_x, offset_y))
            thumbs.append(square)
        except Exception as e:
            print(f"  Skip {img_path.name}: {e}")
            continue

    if not thumbs:
        print(f"No valid images for {target_date}")
        return None

    # Compute grid dimensions
    n = len(thumbs)
    if n <= 3:
        cols, rows = n, 1
    elif n <= 6:
        cols, rows = 3, 2
    elif n <= 9:
        cols, rows = 3, 3
    else:
        cols, rows = 4, 3

    # Create canvas
    width = cols * THUMB_SIZE + (cols + 1) * PADDING
    height = rows * THUMB_SIZE + (rows + 1) * PADDING
    canvas = Image.new("RGB", (width, height), BG_COLOR)

    for i, thumb in enumerate(thumbs):
        if i >= cols * rows:
            break
        r, c = divmod(i, cols)
        x = PADDING + c * (THUMB_SIZE + PADDING)
        y = PADDING + r * (THUMB_SIZE + PADDING)
        canvas.paste(thumb, (x, y))

    if output_path is None:
        output_path = OUTPUT_DIR / f"{target_date}-collage.jpg"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "JPEG", quality=85)
    print(f"Saved: {output_path} ({n} photos, {cols}x{rows})")
    return output_path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    output = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--output" and i + 2 < len(sys.argv):
            output = sys.argv[i + 2]

    if not args:
        print("Usage: python3 collage.py YYYY-MM-DD [--output path.jpg]")
        sys.exit(1)

    make_collage(args[0], output)
