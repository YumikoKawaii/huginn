#!/usr/bin/env python3
"""
crawler/runner.py — ECS scheduled task entrypoint.

Flow:
  1. Priority sync  — resolve new chapter IDs for titles in priority.txt (no cap)
  2. Discovery      — fill remaining chapter budget with random manga
  3. Scrapy         — download images + zip
  4. Upload         — push all new zips to archive

Environment variables:
  API_BASE_URL       archive API base URL
  API_EMAIL          crawler account email
  API_PASSWORD       crawler account password
  MAX_CHAPTERS       total chapter budget per run (default: 350)
  MAX_RANDOM_MANGA   max manga titles for random discovery (default: 100)
  CRAWL_LANGUAGE     MangaDex language code (default: en)
"""

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from shared.api_client import ApiClient, load_env
from crawler.sync import resolve_priority_chapters
from crawler.uploader import upload_all

log = logging.getLogger(__name__)

MAX_CHAPTERS = int(os.environ.get("MAX_CHAPTERS", "350"))
MAX_RANDOM_MANGA = int(os.environ.get("MAX_RANDOM_MANGA", "100"))
LANGUAGE = os.environ.get("CRAWL_LANGUAGE", "en")
PRIORITY_FILE = Path(__file__).parent / "priority.txt"
ZIPS_DIR = Path("output/zips")


def _load_priority_titles() -> list[str]:
    if not PRIORITY_FILE.exists():
        return []
    return [
        line.strip()
        for line in PRIORITY_FILE.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _build_client() -> ApiClient:
    client = ApiClient(
        base_url=os.environ["API_BASE_URL"],
        email=os.environ["API_EMAIL"],
        password=os.environ["API_PASSWORD"],
    )
    client.login()
    log.info("Authenticated as %s", os.environ["API_EMAIL"])
    return client


def _run_scrapy(priority_chapter_ids: list[str], random_chapter_budget: int):
    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "crawler.settings")
    settings = get_project_settings()

    from crawler.spiders.mangadex_spider import MangadexSpider

    process = CrawlerProcess(settings)

    if priority_chapter_ids:
        log.info("Scrapy: queuing %d priority chapter(s)", len(priority_chapter_ids))
        process.crawl(
            MangadexSpider,
            chapter_ids=",".join(priority_chapter_ids),
            language=LANGUAGE,
        )

    if random_chapter_budget > 0:
        manga_count = min(max(1, random_chapter_budget // 3), MAX_RANDOM_MANGA)
        log.info(
            "Scrapy: discovery — %d manga title(s), chapter budget %d",
            manga_count, random_chapter_budget,
        )
        process.crawl(
            MangadexSpider,
            max_manga=manga_count,
            max_chapters=3,
            language=LANGUAGE,
            data_saver="1",
        )

    process.start()


def main():
    load_env()

    missing = [k for k in ("API_BASE_URL", "API_EMAIL", "API_PASSWORD") if not os.environ.get(k)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    run_start = time.time()
    log.info("=== Huginn Crawler starting (budget=%d chapters, language=%s) ===",
             MAX_CHAPTERS, LANGUAGE)

    # ── Phase 1: Priority sync ──────────────────────────────────────────
    titles = _load_priority_titles()
    priority_chapter_ids: list[str] = []

    t = time.time()
    if titles:
        log.info("[Phase 1] Priority sync — %d title(s): %s", len(titles), ", ".join(titles))
        client = _build_client()
        priority_chapter_ids = resolve_priority_chapters(client, titles, LANGUAGE)
        log.info("[Phase 1] Done in %.1fs — %d new priority chapter(s)",
                 time.time() - t, len(priority_chapter_ids))
    else:
        log.info("[Phase 1] No priority titles configured — skipping")

    # ── Phase 2: Calculate discovery budget ────────────────────────────
    random_budget = max(0, MAX_CHAPTERS - len(priority_chapter_ids))
    log.info(
        "[Phase 2] Budget: %d total | %d priority | %d discovery",
        MAX_CHAPTERS, len(priority_chapter_ids), random_budget,
    )

    # ── Phase 3: Download ───────────────────────────────────────────────
    t = time.time()
    if priority_chapter_ids or random_budget > 0:
        log.info("[Phase 3] Starting Scrapy download")
        _run_scrapy(priority_chapter_ids, random_budget)
        log.info("[Phase 3] Scrapy finished in %.1fs", time.time() - t)
    else:
        log.info("[Phase 3] Nothing to download — skipping Scrapy")

    # ── Phase 4: Upload ─────────────────────────────────────────────────
    t = time.time()
    log.info("[Phase 4] Uploading zips to archive")
    client = _build_client()  # re-authenticate after potentially long crawl
    upload_all(client, ZIPS_DIR)
    log.info("[Phase 4] Upload finished in %.1fs", time.time() - t)

    log.info("=== Crawler done — total elapsed %.1fs ===", time.time() - run_start)


if __name__ == "__main__":
    main()
