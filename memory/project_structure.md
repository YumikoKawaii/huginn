---
name: Project structure after refactor
description: New monorepo layout with crawler/, bot/, shared/ after 2026-03-18 refactor
type: project
---

Project was refactored on 2026-03-18 from a flat Scrapy project into a structured monorepo.

- nhentai spider removed; only MangaDex remains
- Old `huginn/` package deleted; replaced by `crawler/`
- `push_data.py` and `balance_oneshots.py` deleted; replaced by `crawler/uploader.py` and `crawler/runner.py`

**Why:** Preparing for ECS deployment — crawler as hourly scheduled task, bot as long-running task.

**How to apply:** New entrypoints are `crawler/runner.py` and `bot/runner.py`. Scrapy commands need `SCRAPY_SETTINGS_MODULE=crawler.settings`.
