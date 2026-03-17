"""
Bot session behaviors.

Each behavior function runs one realistic user session:
- anonymous_session     : browse listing → open manga → read chapters
- authenticated_session : login → browse → maybe bookmark → logout
"""

import asyncio
import logging
import random

from bot.client import AnonClient, AuthClient

log = logging.getLogger(__name__)

_THINK_TIME = (1.0, 4.0)
_BOOKMARK_CHANCE = 0.35
_CHECK_BOOKMARKS_CHANCE = 0.40


async def _think():
    await asyncio.sleep(random.uniform(*_THINK_TIME))


async def _browse_and_read(client: AnonClient) -> str | None:
    """
    Browse the listing, pick a manga, read some chapters.
    Returns the manga_id most engaged with (for bookmarking), or None.
    """
    page = random.randint(1, 15)
    log.debug("Browsing listing page %d", page)
    try:
        result = await client.list_mangas(page=page, limit=20)
        mangas = result.get("data", [])
    except Exception as exc:
        log.warning("Failed to fetch listing page %d: %s", page, exc)
        return None

    if not mangas:
        log.debug("Listing page %d returned no results", page)
        return None

    await _think()

    picks = random.sample(mangas, min(random.randint(1, 3), len(mangas)))
    log.debug("Picked %d manga(s) to open", len(picks))
    engaged_manga_id: str | None = None

    for manga in picks:
        manga_id = manga.get("id", "")
        manga_title = manga.get("title", manga_id)[:40]
        if not manga_id:
            continue

        log.debug("Opening manga '%s' (%s)", manga_title, manga_id)
        try:
            await client.get_manga(manga_id)
        except Exception as exc:
            log.warning("Failed to get manga %s: %s", manga_id, exc)
            continue

        await _think()

        log.debug("Fetching chapter list for '%s'", manga_title)
        try:
            chapters = await client.list_chapters(manga_id)
        except Exception as exc:
            log.warning("Failed to list chapters for %s: %s", manga_id, exc)
            continue

        if not chapters:
            log.debug("No chapters for '%s'", manga_title)
            await _think()
            continue

        await _think()

        reads = random.sample(chapters, min(random.randint(1, 2), len(chapters)))
        for chapter in reads:
            chapter_id = chapter.get("id", "")
            ch_num = chapter.get("number", "?")
            if not chapter_id:
                continue
            log.debug("Reading chapter #%s of '%s'", ch_num, manga_title)
            try:
                await client.get_chapter(manga_id, chapter_id)
            except Exception as exc:
                log.warning("Failed to read chapter %s: %s", chapter_id, exc)
            await _think()

        engaged_manga_id = manga_id

    return engaged_manga_id


async def anonymous_session(client: AnonClient):
    """A single anonymous browsing session."""
    log.debug("Starting anonymous session")
    await _browse_and_read(client)
    log.debug("Anonymous session complete")


async def authenticated_session(client: AuthClient):
    """A single authenticated session with optional bookmarking."""
    log.debug("Starting authenticated session for %s", client._email)
    try:
        await client.login()
    except Exception as exc:
        log.warning("Login failed for %s: %s", client._email, exc)
        return

    try:
        if random.random() < _CHECK_BOOKMARKS_CHANCE:
            log.debug("Checking bookmarks for %s", client._email)
            try:
                bookmarks = await client.list_bookmarks()
                log.debug("%s has %d bookmark(s)", client._email, len(bookmarks))
                await _think()
            except Exception as exc:
                log.warning("Failed to fetch bookmarks: %s", exc)

        engaged = await _browse_and_read(client)

        if engaged and random.random() < _BOOKMARK_CHANCE:
            log.debug("Bookmarking manga %s", engaged)
            try:
                await client.upsert_bookmark(engaged)
                log.info("Bookmarked manga %s for %s", engaged, client._email)
            except Exception as exc:
                log.warning("Bookmark failed: %s", exc)

    finally:
        await client.logout()
        log.debug("Authenticated session complete for %s", client._email)
