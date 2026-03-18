"""
Browser bot session behaviors using Playwright.

anonymous_session    — browse listing → open manga → scroll through chapters
authenticated_session — inject JWT → browse → maybe bookmark
"""

import asyncio
import logging
import os
import random

from playwright.async_api import Browser, BrowserContext, Page

log = logging.getLogger(__name__)

WEB_BASE = os.environ.get("WEB_BASE_URL", "https://sherry-archive.com").rstrip("/")
AUTH_TOKEN_KEY = os.environ.get("AUTH_TOKEN_KEY", "token")

_THINK = (1.5, 4.0)
_SCROLL_STEPS = (4, 10)
_BOOKMARK_CHANCE = 0.35


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


async def _pick_and_read(page: Page):
    """Navigate to listing, pick a manga, read a chapter."""
    log.debug("Navigating to listing: %s", WEB_BASE)
    try:
        await page.goto(WEB_BASE, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        log.warning("Failed to load listing: %s", exc)
        return None

    await _scroll(page)
    await _think()

    # Find manga links
    manga_links = await page.eval_on_selector_all(
        "a[href*='/manga']",
        "els => els.map(e => e.href)",
    )
    manga_links = list({u for u in manga_links if u.startswith(WEB_BASE)})
    if not manga_links:
        log.debug("No manga links found on listing page")
        return None

    manga_url = random.choice(manga_links)
    log.debug("Opening manga: %s", manga_url)
    try:
        await page.goto(manga_url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        log.warning("Failed to load manga page: %s", exc)
        return None

    await _scroll(page)
    await _think()

    # Find chapter links
    chapter_links = await page.eval_on_selector_all(
        "a[href*='/chapter']",
        "els => els.map(e => e.href)",
    )
    chapter_links = list({u for u in chapter_links if u.startswith(WEB_BASE)})
    if not chapter_links:
        log.debug("No chapter links on manga page")
        return manga_url

    chapter_url = random.choice(chapter_links)
    log.debug("Reading chapter: %s", chapter_url)
    try:
        await page.goto(chapter_url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        log.warning("Failed to load chapter page: %s", exc)
        return manga_url

    await _scroll(page)
    await _think()

    return manga_url


async def anonymous_session(browser: Browser):
    context = await _new_context(browser)
    try:
        page = await context.new_page()
        await _pick_and_read(page)
    finally:
        await context.close()


async def authenticated_session(browser: Browser, token: str):
    context = await _new_context(browser, token=token)
    try:
        page = await context.new_page()
        manga_url = await _pick_and_read(page)

        if manga_url and random.random() < _BOOKMARK_CHANCE:
            # Extract manga ID from URL and bookmark via JS fetch
            manga_id = manga_url.rstrip("/").split("/")[-1]
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
        await context.close()
