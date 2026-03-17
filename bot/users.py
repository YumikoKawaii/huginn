"""
Bot user management.

On first startup the bot registers BOT_USER_COUNT fresh accounts and saves
their credentials to CREDS_FILE (within the container). Subsequent restarts
reuse the saved file; when the container is replaced, new users are registered.

Since bot accounts have no value, this churn is acceptable.
"""

import json
import logging
import os
import random
import string
from pathlib import Path

from shared.api_client import ApiClient

log = logging.getLogger(__name__)

CREDS_FILE = Path(os.environ.get("BOT_CREDS_FILE", "/tmp/bot_creds.json"))
BOT_USER_COUNT = int(os.environ.get("BOT_USER_COUNT", "20"))


def _random_str(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def load_or_setup_users(base_url: str) -> list[dict]:
    """
    Return a list of bot user credentials dicts with keys: email, password, username.
    Loads from CREDS_FILE if it exists; otherwise registers fresh users.
    """
    if CREDS_FILE.exists():
        try:
            users = json.loads(CREDS_FILE.read_text())
            if users:
                log.info("Loaded %d existing bot users from %s", len(users), CREDS_FILE)
                return users
        except Exception as exc:
            log.warning("Failed to read creds file, re-registering: %s", exc)

    log.info("Registering %d new bot users...", BOT_USER_COUNT)
    client = ApiClient(base_url)

    users = []
    for _ in range(BOT_USER_COUNT):
        uid = _random_str(8)
        cred = {
            "email": f"bot_{uid}@bot.internal",
            "password": _random_str(16),
            "username": f"reader_{uid}",
        }
        try:
            client.register(cred["email"], cred["password"], cred["username"])
            users.append(cred)
            log.debug("Registered bot user %s", cred["username"])
        except Exception as exc:
            log.warning("Failed to register %s: %s", cred["username"], exc)

    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps(users, indent=2))
    log.info("Registered %d bot users → %s", len(users), CREDS_FILE)
    return users
