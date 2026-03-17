# huginn

## Python environment
Use `.venv/bin/python` — run all commands as `.venv/bin/python ...`

## Components

## Commands

```bash
# Install dependencies
.venv/bin/pip install -r requirements.txt

# Run crawler (priority sync → discovery → download → upload)
.venv/bin/python huginn.py crawl

# Run bot (long-running, 20 CCU)
.venv/bin/python huginn.py bot

# Run MangaDex spider directly
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex -a max_manga=50 -a max_chapters=3
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex -a manga_id=<uuid>
```

### Crawler (ECS scheduled task — hourly)
Fetches new MangaDex chapters and uploads them to the archive.

### Bot (EC2 t3.micro — manual Docker deployment)
Simulates user traffic against the archive. Registers bot users on first start,
then runs 20 concurrent async workers indefinitely.

**Deploy bot manually:**
```bash
# SSH into t3.micro
ssh ec2-user@<instance-ip>

# Authenticate to ECR and pull latest image
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
docker pull $ECR_REGISTRY/huginn:latest

# Run bot (detached, with restart)
docker run -d --restart unless-stopped \
  -e API_BASE_URL=https://sherry-archive.com/api/v1 \
  -e BOT_CCU=20 \
  -e BOT_USER_COUNT=20 \
  --name huginn-bot \
  $ECR_REGISTRY/huginn:latest bot
```

## Architecture

**Crawler flow:**
1. `crawler/runner.py` — entrypoint; orchestrates all phases
2. `crawler/sync.py` — for each priority title: search MangaDex + check archive → return only new chapter IDs
3. Scrapy (`crawler/spiders/mangadex_spider.py`) — downloads images, zips per chapter
4. `crawler/uploader.py` — pushes zips to archive API

**Scrapy pipeline order** (set in `crawler/settings.py`):
1. `ImageDownloadPipeline` — downloads images to `output/images/<group_id>/`
2. `ImageMetaPipeline` — fills width/height/format via Pillow
3. `ZipGroupPipeline` — zips completed chapters to `output/zips/`

**Bot flow:**
- `bot/users.py` — registers BOT_USER_COUNT accounts on first run, saves to `/tmp/bot_creds.json`
- `bot/behaviors.py` — `anonymous_session()` and `authenticated_session()`
- `bot/runner.py` — 20 CCU asyncio workers; 30% auth / 70% anonymous

## Output structure
```
output/
  images/
    oneshots/<chapter_uuid>/1.jpg ...
    series/<chapter_uuid>/1.jpg ...
  zips/
    oneshots/<chapter_uuid>.zip
    series/<chapter_uuid>.zip
```

## Configuration

Copy `.env.example` to `.env`:
```
API_BASE_URL=https://sherry-archive.com/api/v1
API_EMAIL=your@email.com
API_PASSWORD=yourpassword
MAX_CHAPTERS=350
MAX_RANDOM_MANGA=100
BOT_CCU=20
```

## Key Files

| File | Purpose |
|---|---|
| `crawler/runner.py` | Crawler entrypoint (priority → discovery → download → upload) |
| `crawler/sync.py` | Incremental sync: find new chapters not yet in archive |
| `crawler/uploader.py` | Upload oneshot + series zips to archive API |
| `crawler/spiders/mangadex_spider.py` | MangaDex spider (priority/direct/discovery modes) |
| `crawler/pipelines.py` | Download → metadata → zip pipeline |
| `crawler/priority.txt` | Pinned series titles (one per line) |
| `bot/runner.py` | Bot entrypoint (20 CCU long-running) |
| `bot/behaviors.py` | Session behavior functions |
| `bot/users.py` | Bot user registration + credential management |
| `shared/api_client.py` | Authenticated HTTP client for sherry-archive.com |
| `Dockerfile` | Single image for both crawler and bot |
| `huginn.py` | Unified CLI entrypoint (`crawl` / `bot`) |

## Metadata format (inside each zip)
```json
{
  "manga_id": "<mangadex-uuid>",
  "manga_title": "...",
  "cover_url": "...",
  "chapter_number": 1,
  "chapter_title": "...",
  "author": "...",
  "artist": "...",
  "tags": ["..."],
  "category": "shounen",
  "language": "english"
}
```

## CI / Deploy

On push to `master`, GitHub Actions lints then builds and pushes `latest` to ECR.

**GitHub Secrets:**

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `AWS_REGION` | e.g. `ap-southeast-1` |
| `ECR_REPO` | ECR repository name e.g. `huginn` |

**Crawler ECS Task:**

| Variable | Default | Required |
|---|---|---|
| `API_BASE_URL` | — | ✓ |
| `API_EMAIL` | — | ✓ |
| `API_PASSWORD` | — | ✓ |
| `MAX_CHAPTERS` | `350` | |
| `MAX_RANDOM_MANGA` | `100` | |
| `CRAWL_LANGUAGE` | `en` | |

**Bot (EC2 t3.micro — docker run env vars):**

| Variable | Default | Required |
|---|---|---|
| `API_BASE_URL` | — | ✓ |
| `BOT_CCU` | `20` | |
| `BOT_USER_COUNT` | `20` | |
| `BOT_CREDS_FILE` | `/tmp/bot_creds.json` | |

CI only pushes the image to ECR. Bot deployment is manual — SSH + docker pull + docker run.
