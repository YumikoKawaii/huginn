"""
Incremental sync logic for priority series.

For each priority title:
1. Search MangaDex by title → take highest-relevance result
2. Query the archive for that title's latest known chapter number
3. Return only MangaDex chapter UUIDs with chapter_number > archive max

This means on most hourly runs, priority series that have no new chapters
produce zero download work.
"""

import logging

import requests

from shared.api_client import ApiClient

log = logging.getLogger(__name__)

_MANGADEX_API = "https://api.mangadex.org"


def _search_mangadex(title: str, language: str = "en") -> dict | None:
    """Search MangaDex by title, return the top result or None."""
    r = requests.get(
        f"{_MANGADEX_API}/manga",
        params={
            "title": title,
            "limit": 1,
            "order[relevance]": "desc",
            "availableTranslatedLanguage[]": language,
            "includes[]": ["author", "artist", "cover_art"],
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None


def _get_mangadex_chapters(manga_id: str, language: str, after_chapter: float) -> list[dict]:
    """Fetch all MangaDex chapter entries with chapter_number > after_chapter."""
    chapters = []
    offset = 0

    while True:
        r = requests.get(
            f"{_MANGADEX_API}/manga/{manga_id}/feed",
            params={
                "translatedLanguage[]": language,
                "limit": 100,
                "offset": offset,
                "order[chapter]": "asc",
                "includeEmptyPages": 0,
                "includeExternalUrl": 0,
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        batch = body.get("data", [])

        if not batch:
            break

        for ch in batch:
            attrs = ch.get("attributes", {})
            try:
                ch_num = float(attrs.get("chapter") or "0")
            except (ValueError, TypeError):
                ch_num = 0.0
            if ch_num > after_chapter:
                chapters.append(ch)

        offset += len(batch)
        if offset >= body.get("total", 0):
            break

    return chapters


def _archive_latest_chapter(api_client: ApiClient, title: str) -> tuple[str | None, float]:
    """
    Search the archive for a manga by title.
    Returns (archive_manga_id, max_chapter_number) or (None, 0.0).
    """
    try:
        results = api_client.list_mangas(q=title, limit=1)
        items = results.get("data", [])
        if not items:
            return None, 0.0
        manga = items[0]
        chapters = api_client.list_chapters(manga["id"])
        if not chapters:
            return manga["id"], 0.0
        max_ch = max((float(ch.get("number", 0)) for ch in chapters), default=0.0)
        return manga["id"], max_ch
    except Exception:
        return None, 0.0


def resolve_priority_chapters(
    api_client: ApiClient,
    titles: list[str],
    language: str = "en",
) -> list[str]:
    """
    For each priority title, resolve new MangaDex chapter IDs not yet in archive.
    Returns a flat list of chapter UUIDs to pass to the spider.
    """
    chapter_ids: list[str] = []

    for title in titles:
        title = title.strip()
        if not title:
            continue
        try:
            log.info("Syncing '%s'", title)
            manga = _search_mangadex(title, language)
            if not manga:
                log.warning("'%s': not found on MangaDex — skipping", title)
                continue

            mangadex_title = (manga.get("attributes", {}).get("title", {}) or {}).get("en", title)
            log.debug("'%s': matched MangaDex title '%s' (id=%s)", title, mangadex_title, manga["id"])

            _, latest_ch = _archive_latest_chapter(api_client, title)
            log.debug("'%s': archive latest chapter = %s", title, latest_ch)

            new_chapters = _get_mangadex_chapters(manga["id"], language, after_chapter=latest_ch)
            log.info("'%s': %d new chapter(s) to fetch (after ch%s)", title, len(new_chapters), latest_ch)
            chapter_ids.extend(ch["id"] for ch in new_chapters)

        except Exception as exc:
            log.error("'%s': sync failed — %s", title, exc)

    return chapter_ids
