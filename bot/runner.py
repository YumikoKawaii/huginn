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

CCU = int(os.environ.get("BOT_CCU", "20"))

# Pause between sessions within a single worker (seconds)
_SESSION_PAUSE = (3.0, 10.0)

# Fraction of sessions that use an authenticated user
_AUTH_RATIO = 0.30


async def _worker(worker_id: int, base_url: str, users: list[dict], http: aiohttp.ClientSession):
    """Single worker — runs sessions in an infinite loop."""
    while True:
        use_auth = bool(users) and random.random() < _AUTH_RATIO

        try:
            if use_auth:
                creds = random.choice(users)
                client = AuthClient(base_url, http, creds["email"], creds["password"])
                await authenticated_session(client)
            else:
                client = AnonClient(base_url, http)
                await anonymous_session(client)
        except Exception as exc:
            # Never crash a worker — log and continue
            print(f"[worker-{worker_id}] session error: {exc}")

        await asyncio.sleep(random.uniform(*_SESSION_PAUSE))


async def main():
    load_env()

    base_url = os.environ.get("API_BASE_URL", "").rstrip("/")
    if not base_url:
        raise SystemExit("API_BASE_URL is not set")

    print(f"[bot] Initialising — {CCU} concurrent workers, auth_ratio={_AUTH_RATIO}")

    users = load_or_setup_users(base_url)
    print(f"[bot] {len(users)} bot user(s) available")
    print(f"[bot] Starting {CCU} workers against {base_url}\n")

    connector = aiohttp.TCPConnector(limit=CCU + 5)
    async with aiohttp.ClientSession(connector=connector) as http:
        await asyncio.gather(
            *[_worker(i, base_url, users, http) for i in range(CCU)]
        )


if __name__ == "__main__":
    asyncio.run(main())
