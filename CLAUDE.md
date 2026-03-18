# huginn

## Rules
- **Never `git push` unless explicitly asked.**

## Python environment
Use `.venv/bin/python` — run all commands as `.venv/bin/python ...`

## Components

## Commands

```bash
# Install dependencies
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Run crawler (priority sync → discovery → download → upload)
.venv/bin/python huginn.py crawl

# Run API bot (long-running, aiohttp)
.venv/bin/python huginn.py bot

# Run browser bot (long-running, Playwright headless Chromium)
BROWSER_BOT_CCU=1 .venv/bin/python huginn.py browser-bot

# Run MangaDex spider directly
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex -a max_manga=50 -a max_chapters=3
SCRAPY_SETTINGS_MODULE=crawler.settings .venv/bin/python -m scrapy crawl mangadex -a manga_id=<uuid>
```

### Crawler (ECS scheduled task — hourly)
Fetches new MangaDex chapters and uploads them to the archive.

### Bot (EC2 t3.micro — auto-deployed by CI)
Simulates user traffic against the archive via direct API calls. Registers bot users on first start,
then runs concurrent async workers indefinitely.

CI SSHes into the t3.micro after every push to `master`, pulls the new image,
and restarts the container automatically.

### Browser Bot (EC2 t3.small — auto-deployed by CI)
Simulates user traffic using headless Chromium (Playwright). Triggers real JS/analytics events.
Fetches a random manga from the API each session, then navigates the frontend directly.
Auth sessions inject JWT into localStorage; anon sessions browse without credentials.

CI SSHes into the t3.small after every push to `master`, pulls the new image,
and restarts the container automatically.

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
- `bot/runner.py` — asyncio workers; 30% auth / 70% anonymous

**Browser bot flow:**
- Shares `bot/users.py` for user registration (creds saved to `/tmp/browser_bot_creds.json`)
- `browser_bot/behaviors.py` — Playwright sessions; picks random manga via API, navigates frontend
- `browser_bot/runner.py` — asyncio workers with shared browser + per-session contexts; 30% auth / 70% anonymous

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
BOT_CCU=10
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
| `bot/runner.py` | API bot entrypoint |
| `bot/behaviors.py` | API bot session behaviors |
| `bot/users.py` | Bot user registration + credential management (shared by both bots) |
| `browser_bot/runner.py` | Browser bot entrypoint |
| `browser_bot/behaviors.py` | Playwright session behaviors |
| `shared/api_client.py` | Authenticated HTTP client for sherry-archive.com |
| `Dockerfile` | Single image for crawler, api bot, and browser bot |
| `huginn.py` | Unified CLI entrypoint (`crawl` / `bot` / `browser-bot`) |

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

On push to `master`, GitHub Actions runs: **lint → build & push to ECR → deploy api bot → deploy browser bot**

**GitHub Secrets (shared):**

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `AWS_REGION` | e.g. `ap-southeast-1` |
| `ECR_REPO` | ECR repository name e.g. `huginn` |
| `ECR_REGISTRY` | Full ECR registry URL |
| `API_BASE_URL` | `https://sherry-archive.com/api/v1` |

**Crawler ECS Task:**

| Variable | Default | Required |
|---|---|---|
| `API_BASE_URL` | — | ✓ |
| `API_EMAIL` | — | ✓ |
| `API_PASSWORD` | — | ✓ |
| `MAX_CHAPTERS` | `350` | |
| `MAX_RANDOM_MANGA` | `100` | |
| `CRAWL_LANGUAGE` | `en` | |

**API Bot (EC2 t3.micro):**

| Secret | Description |
|---|---|
| `EC2_HOST` | t3.micro IP |
| `EC2_USER` | SSH user |
| `EC2_SSH_KEY` | PEM key content |
| `BOT_CCU` | Concurrent workers (app default: `10`) |
| `BOT_USER_COUNT` | Bot accounts (app default: `20`) |

**Browser Bot (EC2 t3.small):**

| Secret | Description |
|---|---|
| `EC2_BROWSER_HOST` | Comma-separated IPs — deploys to all instances e.g. `1.2.3.4,5.6.7.8` |
| `BROWSER_BOT_CCU` | Concurrent workers per instance (app default: `5`) |
| `BROWSER_BOT_COUNT` | Bot accounts (app default: `10`) |

Reuses `EC2_USER` and `EC2_SSH_KEY` from the api bot secrets.

`AUTH_TOKEN_KEY` env var (default: `token`) must match the localStorage key the frontend uses for JWT.
