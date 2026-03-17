# Huginn: A Manga Archive Pipeline

**Project Overview**

Huginn is a monorepo that feeds a self-hosted manga archive. Named after Odin's raven of *thought* — the one sent out to observe the world and return with knowledge — it continuously scouts MangaDex, collects chapters, and delivers them home. It ships two ECS workloads sharing a single container image: a scheduled crawler and a long-running traffic bot.

**Key Components**

*The Crawler* wakes up every hour, consults a priority list of series it must never fall behind on, fetches only the chapters the archive does not yet have, then fills the remaining budget with random discovery. It speaks directly to the MangaDex API, downloads pages in data-saver quality, zips each chapter, and pushes everything to the archive before going back to sleep. On a budget of 350 chapters it comfortably finishes within the hour.

*The Bot* never sleeps. It runs 20 concurrent async workers that simulate real readers browsing the archive — opening listings, clicking into manga, reading chapters, occasionally bookmarking something that caught their eye. Seventy percent of sessions are anonymous; the remaining thirty percent log in as one of the bot users the container registered on its first boot. When the container is replaced the old users are abandoned and new ones are born, which is fine because they were never real to begin with.

**Architecture**

Both workloads are invoked through a single CLI entrypoint:

```
python huginn.py crawl   # scheduled ECS task
python huginn.py bot     # long-running ECS task
```

The crawler pipeline runs in three stages — download, metadata extraction via Pillow, then zip — before handing off to the uploader, which upserts manga and skips chapters already present in the archive. The bot is pure asyncio over aiohttp with no shared state between workers.

**Deployment**

Pushing to `master` builds the image and tags it with the short commit SHA before pushing to ECR. Both ECS task definitions pull the same image and differ only in their command override.

**Metadata**

- **Author:** Yumiko Kawaii
- **Contact:** yumiko.stl@gmail.com
- **Platform:** AWS ECS Fargate + MangaDex API
