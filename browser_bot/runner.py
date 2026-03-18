"""
browser_bot/runner.py — Playwright-based browser traffic bot.

Runs CCU concurrent async workers. Each worker loops indefinitely:
  - 30% chance: authenticated session (inject JWT → browse → maybe bookmark)
  - 70% chance: anonymous session (browse → read)

Environment variables:
  API_BASE_URL         archive API base URL        (required)
  API_EMAIL            bot account email           (required)
  API_PASSWORD         bot account password        (required)
  WEB_BASE_URL         frontend URL                (default: https://sherry-archive.com)
  BROWSER_BOT_CCU      concurrent workers          (default: 5)
  BROWSER_BOT_COUNT    number of bot users         (default: 10)
  BOT_CREDS_FILE       path to creds file          (default: /tmp/browser_bot_creds.json)
"""

import asyncio
import logging
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

from shared.api_client import ApiClient, load_env
from bot.users import load_or_setup_users
from browser_bot.behaviors import anonymous_session, authenticated_session

log = logging.getLogger(__name__)

CCU = int(os.environ.get("BROWSER_BOT_CCU") or "5")
_AUTH_RATIO = 0.30
_SESSION_PAUSE = (3.0, 8.0)
_LOG_EVERY = 10


def _get_token(base_url: str, creds: dict) -> str | None:
    try:
        client = ApiClient(base_url, creds["email"], creds["password"])
        client.login()
        return client.access_token
    except Exception as exc:
        log.warning("Failed to get token for %s: %s", creds["email"], exc)
        return None


async def _worker(worker_id: int, base_url: str, users: list[dict], browser):
    sessions = 0
    errors = 0

    while True:
        use_auth = bool(users) and random.random() < _AUTH_RATIO
        kind = "auth" if use_auth else "anon"

        try:
            if use_auth:
                creds = random.choice(users)
                token = await asyncio.get_event_loop().run_in_executor(
                    None, _get_token, base_url, creds
                )
                if token:
                    await authenticated_session(browser, token)
                else:
                    await anonymous_session(browser)
            else:
                await anonymous_session(browser)

            sessions += 1
            if sessions % _LOG_EVERY == 0:
                log.info(
                    "worker-%d: %d sessions completed (%d errors, last: %s)",
                    worker_id, sessions, errors, kind,
                )

        except Exception as exc:
            errors += 1
            log.warning(
                "worker-%d: %s session error [total errors: %d]: %s",
                worker_id, kind, errors, exc,
            )

        await asyncio.sleep(random.uniform(*_SESSION_PAUSE))


async def main():
    load_env()

    base_url = os.environ.get("API_BASE_URL", "").rstrip("/")
    if not base_url:
        raise SystemExit("API_BASE_URL is not set")

    log.info("=== Huginn Browser Bot starting — %d workers, auth_ratio=%.0f%% ===",
             CCU, _AUTH_RATIO * 100)

    # Override creds file so browser bot users don't clash with api bot users
    os.environ.setdefault("BOT_CREDS_FILE", "/tmp/browser_bot_creds.json")
    os.environ.setdefault("BOT_USER_COUNT", os.environ.get("BROWSER_BOT_COUNT", "10"))

    users = load_or_setup_users(base_url)
    log.info("%d bot user(s) available", len(users))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        log.info("Browser launched — starting %d workers", CCU)
        try:
            await asyncio.gather(
                *[_worker(i, base_url, users, browser) for i in range(CCU)]
            )
        finally:
            await browser.close()
