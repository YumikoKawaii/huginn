BOT_NAME = "huginn"

SPIDER_MODULES = ["huginn.spiders"]
NEWSPIDER_MODULE = "huginn.spiders"

# --- Politeness ---
ROBOTSTXT_OBEY = False          # nhentai's robots.txt disallows crawlers; set True for other sites
DOWNLOAD_DELAY = 1.5            # seconds between requests to the same domain
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

# --- Browser-like headers (reduces chance of 403s) ---
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Item pipelines (lower number = runs first) ---
ITEM_PIPELINES = {
    "huginn.pipelines.ImageDownloadPipeline": 100,
    "huginn.pipelines.ImageMetaPipeline": 200,
    "huginn.pipelines.ZipGroupPipeline": 300,
}

# --- Output directories ---
FILES_STORE = "output/images"   # raw downloaded images (FilesPipeline key)
ZIPS_STORE = "output/zips"      # finished zip archives

# --- Logging ---
LOG_LEVEL = "INFO"
