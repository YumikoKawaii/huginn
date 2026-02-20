"""
Spider for nhentai.net galleries.

--- Direct mode (specific galleries) ---
    scrapy crawl nhentai -a gallery_id=627265
    scrapy crawl nhentai -a gallery_id=627265,123456,789012

--- Discovery mode (crawl N galleries from the listing) ---
    scrapy crawl nhentai                          # default: 100 galleries
    scrapy crawl nhentai -a max_galleries=50
    scrapy crawl nhentai -a max_galleries=100 -a start_page=3
"""

import json
import re
from pathlib import Path

import scrapy

from huginn.items import ImageItem

# API type code → file extension
_EXT = {"j": "jpg", "p": "png", "w": "webp"}

# nhentai full-image CDN
_CDN = "https://i1.nhentai.net"

# Galleries per listing page (nhentai constant)
_PER_PAGE = 25


class NhentaiSpider(scrapy.Spider):
    name = "nhentai"

    custom_settings = {
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    def __init__(
        self,
        gallery_id: str = "",
        max_galleries: int = 100,
        start_page: int = 1,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.gallery_ids = [g.strip() for g in gallery_id.split(",") if g.strip()]
        self.max_galleries = int(max_galleries)
        self.start_page = int(start_page)

        # Tracks expected page count per gallery_id.
        # ZipGroupPipeline reads this to know when a gallery is complete.
        self.gallery_page_counts: dict[str, int] = {}

        # Internal discovery state
        self._discovered: set[str] = set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def start(self):
        if self.gallery_ids:
            # Direct mode — crawl only the specified IDs
            for gid in self.gallery_ids:
                yield self._api_request(gid)
        else:
            # Discovery mode — scrape listing pages to collect gallery IDs
            self.logger.info(
                f"Discovery mode: targeting {self.max_galleries} galleries "
                f"starting from page {self.start_page}"
            )
            yield scrapy.Request(
                url=f"https://nhentai.net/?page={self.start_page}",
                headers={"Referer": "https://nhentai.net/"},
                callback=self.parse_listing,
            )

    # ------------------------------------------------------------------
    # Discovery: listing pages
    # ------------------------------------------------------------------

    def parse_listing(self, response):
        # Extract all gallery IDs from href="/g/NUMBER/" links
        ids = re.findall(r"/g/(\d+)/", response.text)
        new_ids = [gid for gid in dict.fromkeys(ids) if gid not in self._discovered]

        for gid in new_ids:
            if len(self._discovered) >= self.max_galleries:
                return
            self._discovered.add(gid)
            yield self._api_request(gid)

        # Follow the next listing page if we still need more galleries
        if len(self._discovered) < self.max_galleries:
            next_href = response.css("a.next::attr(href)").get()
            if next_href:
                yield response.follow(
                    next_href,
                    headers={"Referer": response.url},
                    callback=self.parse_listing,
                )
            else:
                # Fallback: increment page number manually
                current_page = int(
                    re.search(r"[?&]page=(\d+)", response.url).group(1)
                    if re.search(r"[?&]page=(\d+)", response.url)
                    else self.start_page
                )
                next_page = current_page + 1
                yield scrapy.Request(
                    url=f"https://nhentai.net/?page={next_page}",
                    headers={"Referer": response.url},
                    callback=self.parse_listing,
                )

    # ------------------------------------------------------------------
    # Parse gallery API response
    # ------------------------------------------------------------------

    def parse_gallery(self, response, gallery_id: str):
        if response.status != 200:
            self.logger.warning(f"Gallery {gallery_id}: HTTP {response.status}")
            return

        data = response.json()
        media_id = data["media_id"]
        num_pages = data["num_pages"]
        pages = data["images"]["pages"]

        # Register expected count so ZipGroupPipeline knows when to zip
        self.gallery_page_counts[gallery_id] = num_pages

        # Save metadata JSON alongside the images
        self._save_metadata(data, gallery_id)

        # Yield one ImageItem per page
        for page_num, page_info in enumerate(pages, start=1):
            ext = _EXT.get(page_info.get("t", "j"), "jpg")
            yield ImageItem(
                group_id=gallery_id,
                image_url=f"{_CDN}/galleries/{media_id}/{page_num}.{ext}",
                source_url=f"https://nhentai.net/g/{gallery_id}/",
                width=page_info.get("w"),
                height=page_info.get("h"),
            )

        self.logger.info(
            f"Gallery {gallery_id}: queued {num_pages} pages "
            f"(media_id={media_id})"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _api_request(self, gallery_id: str) -> scrapy.Request:
        return scrapy.Request(
            url=f"https://nhentai.net/api/gallery/{gallery_id}",
            headers={"Referer": "https://nhentai.net/"},
            callback=self.parse_gallery,
            errback=self.on_error,
            cb_kwargs={"gallery_id": gallery_id},
        )

    def _save_metadata(self, data: dict, gallery_id: str):
        store = self.settings.get("FILES_STORE", "output/images")
        dest_dir = Path(store) / gallery_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Group tags by type for easy lookup
        tags_by_type: dict[str, list[str]] = {}
        for t in data.get("tags", []):
            tags_by_type.setdefault(t["type"], []).append(t["name"])

        title = data.get("title", {})

        meta = {
            "chapter_number": 1,
            "chapter_title": title.get("english") or title.get("pretty") or title.get("japanese", ""),
            "author": ", ".join(tags_by_type.get("group", tags_by_type.get("artist", []))),
            "artist": ", ".join(tags_by_type.get("artist", [])),
            "tags": tags_by_type.get("tag", []),
            "category": ", ".join(tags_by_type.get("category", [])),
            "language": ", ".join(tags_by_type.get("language", [])),
            "status": "completed",
        }

        with open(dest_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Metadata saved → {dest_dir}/metadata.json")

    def on_error(self, failure):
        self.logger.error(
            f"Request failed: {failure.request.url} — {failure.value}"
        )
