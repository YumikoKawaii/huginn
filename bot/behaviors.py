"""
Bot session behaviors.

Each behavior function runs one realistic user session:
- anonymous_session : browse listing → open manga → read chapters
- authenticated_session : login → browse → maybe bookmark → logout
"""

import asyncio
import random

from bot.client import AnonClient, AuthClient

# Seconds to pause between individual actions within a session
_THINK_TIME = (1.0, 4.0)

# Probability of bookmarking a manga during an authenticated session
_BOOKMARK_CHANCE = 0.35

# Probability of checking bookmarks at the start of an authenticated session
_CHECK_BOOKMARKS_CHANCE = 0.40


async def _think():
    await asyncio.sleep(random.uniform(*_THINK_TIME))


async def _browse_and_read(client: AnonClient) -> str | None:
    """
    Browse the listing, pick a manga, read some chapters.
    Returns the manga_id that was most engaged with (for bookmarking), or None.
    """
    # Pick a random page from the listing
    page = random.randint(1, 15)
    try:
        result = await client.list_mangas(page=page, limit=20)
        mangas = result.get("data", [])
    except Exception:
        return None

    if not mangas:
        return None

    await _think()

    # Open 1–3 manga detail pages
    picks = random.sample(mangas, min(random.randint(1, 3), len(mangas)))
    engaged_manga_id: str | None = None

    for manga in picks:
        manga_id = manga.get("id", "")
        if not manga_id:
            continue

        try:
            await client.get_manga(manga_id)
        except Exception:
            continue

        await _think()

        try:
            chapters = await client.list_chapters(manga_id)
        except Exception:
            continue

        if not chapters:
            await _think()
            continue

        await _think()

        # Read 1–2 chapters
        reads = random.sample(chapters, min(random.randint(1, 2), len(chapters)))
        for chapter in reads:
            chapter_id = chapter.get("id", "")
            if not chapter_id:
                continue
            try:
                await client.get_chapter(manga_id, chapter_id)
            except Exception:
                pass
            await _think()

        engaged_manga_id = manga_id  # last manga with chapters read

    return engaged_manga_id


async def anonymous_session(client: AnonClient):
    """A single anonymous browsing session."""
    await _browse_and_read(client)


async def authenticated_session(client: AuthClient):
    """A single authenticated session with optional bookmarking."""
    await client.login()

    try:
        # Occasionally check existing bookmarks first
        if random.random() < _CHECK_BOOKMARKS_CHANCE:
            try:
                await client.list_bookmarks()
                await _think()
            except Exception:
                pass

        engaged = await _browse_and_read(client)

        # Maybe bookmark the most-read manga
        if engaged and random.random() < _BOOKMARK_CHANCE:
            try:
                await client.upsert_bookmark(engaged)
            except Exception:
                pass

    finally:
        await client.logout()
