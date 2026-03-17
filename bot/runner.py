#!/usr/bin/env python3
"""
bot/runner.py — Long-running ECS bot entrypoint.

Runs CCU concurrent async workers. Each worker loops indefinitely:
  - 30% chance: authenticated session (login → browse → maybe bookmark → logout)
  - 70% chance: anonymous session (browse → read)

Environment variables:
  API_BASE_URL    archive API base URL  (required)
  BOT_CCU         concurrent workers    (default: 20)
  BOT_USER_COUNT  users to register     (default: 20)
  BOT_CREDS_FILE  path to creds file    (default: /tmp/bot_creds.json)
"""

import asyncio
import logging
import os
import random
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.api_client import load_env
from bot.client import AnonClient, AuthClient
from bot.users import load_or_setup_users
from bot.behaviors import anonymous_session, authenticated_session

log = logging.getLogger(__name__)

CCU = int(os.environ.get("BOT_CCU") or "10")
_SESSION_PAUSE = (3.0, 10.0)
_AUTH_RATIO = 0.30
_LOG_EVERY = 10  # log worker stats every N sessions


async def _worker(worker_id: int, base_url: str, users: list[dict], http: aiohttp.ClientSession):
    """Single worker — runs sessions in an infinite loop."""
    sessions = 0
    errors = 0

    while True:
        use_auth = bool(users) and random.random() < _AUTH_RATIO
        kind = "auth" if use_auth else "anon"

        try:
            if use_auth:
                creds = random.choice(users)
                client = AuthClient(base_url, http, creds["email"], creds["password"])
                await authenticated_session(client)
            else:
                client = AnonClient(base_url, http)
                await anonymous_session(client)

            sessions += 1
            if sessions % _LOG_EVERY == 0:
                log.info("worker-%d: %d sessions completed (%d errors, last: %s)",
                         worker_id, sessions, errors, kind)

        except Exception as exc:
            errors += 1
            log.warning("worker-%d: %s session error [total errors: %d]: %s",
                        worker_id, kind, errors, exc)

        await asyncio.sleep(random.uniform(*_SESSION_PAUSE))


async def main():
    load_env()

    base_url = os.environ.get("API_BASE_URL", "").rstrip("/")
    if not base_url:
        raise SystemExit("API_BASE_URL is not set")

    log.info("=== Huginn Bot starting — %d workers, auth_ratio=%.0f%% ===",
             CCU, _AUTH_RATIO * 100)

    users = load_or_setup_users(base_url)
    log.info("%d bot user(s) available", len(users))
    log.info("Starting %d workers against %s", CCU, base_url)

    connector = aiohttp.TCPConnector(limit=CCU + 5)
    async with aiohttp.ClientSession(connector=connector) as http:
        await asyncio.gather(
            *[_worker(i, base_url, users, http) for i in range(CCU)]
        )


if __name__ == "__main__":
    asyncio.run(main())
