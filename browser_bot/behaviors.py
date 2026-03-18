"""
Browser bot session behaviors using Playwright.

anonymous_session    — browse listing → open manga → scroll through chapters
authenticated_session — inject JWT → browse → maybe bookmark
"""

import asyncio
import logging
import math
import os
import random

import aiohttp
from playwright.async_api import Browser, BrowserContext, Page

log = logging.getLogger(__name__)

WEB_BASE = os.environ.get("WEB_BASE_URL", "https://sherry-archive.com").rstrip("/")
API_BASE = os.environ.get("API_BASE_URL", "https://sherry-archive.com/api/v1").rstrip("/")
AUTH_TOKEN_KEY = os.environ.get("AUTH_TOKEN_KEY", "token")

_THINK = (1.5, 4.0)
_SCROLL_STEPS = (4, 10)
_BOOKMARK_CHANCE = 0.35
_PAGE_SIZE = 20


async def _think():
    await asyncio.sleep(random.uniform(*_THINK))


async def _scroll(page: Page):
    steps = random.randint(*_SCROLL_STEPS)
    for _ in range(steps):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.6)")
        await asyncio.sleep(random.uniform(0.4, 1.2))


async def _new_context(browser: Browser, token: str | None = None) -> BrowserContext:
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    if token:
        await context.add_init_script(
            f"localStorage.setItem('{AUTH_TOKEN_KEY}', '{token}');"
        )
    return context


async def _random_manga_id(http: aiohttp.ClientSession) -> str | None:
    """Pick a random manga ID from the archive via API."""
    try:
        async with http.get(f"{API_BASE}/mangas", params={"page": 1, "limit": 1}) as r:
            r.raise_for_status()
            data = (await r.json()).get("data", {})
            total = data.get("total", 0)
        if not total:
            return None
        total_pages = math.ceil(total / _PAGE_SIZE)
        rand_page = random.randint(1, total_pages)
        async with http.get(
            f"{API_BASE}/mangas", params={"page": rand_page, "limit": _PAGE_SIZE}
        ) as r:
            r.raise_for_status()
            items = (await r.json()).get("data", {}).get("items", [])
        if not items:
            return None
        return random.choice(items)["id"]
    except Exception as exc:
        log.warning("Failed to fetch random manga from API: %s", exc)
        return None


async def _pick_and_read(page: Page, http: aiohttp.ClientSession) -> str | None:
    """Navigate to a random manga, read a random chapter. Returns manga_id or None."""
    manga_id = await _random_manga_id(http)
    if not manga_id:
        log.warning("No manga ID returned from API")
        return None

    manga_url = f"{WEB_BASE}/manga/{manga_id}"
    log.debug("Opening manga: %s", manga_url)
    try:
        await page.goto(manga_url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        log.warning("Failed to load manga page %s: %s", manga_id, exc)
        return None

    await _scroll(page)
    await _think()

    # Find chapter links on the manga page
    chapter_links = await page.eval_on_selector_all(
        "a[href*='/chapter']",
        "els => els.map(e => e.href)",
    )
    chapter_links = list({u for u in chapter_links if u.startswith(WEB_BASE)})
    if not chapter_links:
        log.debug("No chapter links found for manga %s", manga_id)
        return manga_id

    chapter_url = random.choice(chapter_links)
    log.debug("Reading chapter: %s", chapter_url)
    try:
        await page.goto(chapter_url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        log.warning("Failed to load chapter page: %s", exc)
        return manga_id

    await _scroll(page)
    await _think()

    return manga_id


async def anonymous_session(browser: Browser, http: aiohttp.ClientSession):
    context = await _new_context(browser)
    try:
        page = await context.new_page()
        log.info("anon session start")
        await _pick_and_read(page, http)
        log.info("anon session done")
    finally:
        await context.close()


async def authenticated_session(browser: Browser, http: aiohttp.ClientSession, token: str):
    context = await _new_context(browser, token=token)
    try:
        page = await context.new_page()
        log.info("auth session start")
        manga_id = await _pick_and_read(page, http)

        if manga_id and random.random() < _BOOKMARK_CHANCE:
            log.debug("Bookmarking manga %s via in-page fetch", manga_id)
            try:
                await page.evaluate(f"""
                    fetch('/api/v1/users/me/bookmarks/{manga_id}', {{
                        method: 'PUT',
                        headers: {{
                            'Authorization': 'Bearer ' + localStorage.getItem('{AUTH_TOKEN_KEY}'),
                            'Content-Type': 'application/json',
                        }},
                        body: '{{}}'
                    }})
                """)
            except Exception as exc:
                log.warning("Bookmark fetch failed: %s", exc)
    finally:
        log.info("auth session done")
        await context.close()
