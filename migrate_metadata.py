"""
One-time migration: convert all existing metadata.json files from the old format
to the new format.

Old format: raw nhentai API dump (id, media_id, title dict, tags as objects, ...)
New format: chapter_number, chapter_title, author, artist, tags, category, language
"""

import json
from pathlib import Path


IMAGES_DIR = Path("output/images")


def convert(old: dict) -> dict:
    # Group the flat tag list by type
    tags_by_type: dict[str, list[str]] = {}
    for t in old.get("tags", []):
        tags_by_type.setdefault(t["type"], []).append(t["name"])

    title = old.get("title", {})

    return {
        "chapter_number": 1,
        "chapter_title": (
            title.get("english")
            or title.get("pretty")
            or title.get("japanese", "")
        ),
        "author": ", ".join(
            tags_by_type.get("group", tags_by_type.get("artist", []))
        ),
        "artist": ", ".join(tags_by_type.get("artist", [])),
        "tags": tags_by_type.get("tag", []),
        "category": ", ".join(tags_by_type.get("category", [])),
        "language": ", ".join(tags_by_type.get("language", [])),
    }


def is_old_format(data: dict) -> bool:
    return "id" in data and "media_id" in data


def main():
    files = list(IMAGES_DIR.glob("*/metadata.json"))
    print(f"Found {len(files)} metadata file(s)")

    converted = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not is_old_format(data):
            print(f"  skip (already new format): {path}")
            continue

        new_data = convert(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        print(f"  converted: {path.parent.name} → {new_data['chapter_title'][:60]}")
        converted += 1

    print(f"\nDone. {converted}/{len(files)} file(s) converted.")


if __name__ == "__main__":
    main()
