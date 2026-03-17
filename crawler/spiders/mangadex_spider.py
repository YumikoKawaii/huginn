"""
Spider for MangaDex chapters via the official JSON API.

--- Priority mode (specific chapter UUIDs, used by runner.py) ---
    Fetches chapter info + manga metadata, then downloads pages.

--- Direct manga mode ---
    scrapy crawl mangadex -a manga_id=<uuid>
    scrapy crawl mangadex -a manga_id=<uuid1>,<uuid2>

--- Discovery mode (paginates up to max_manga) ---
    scrapy crawl mangadex
    scrapy crawl mangadex -a max_manga=100 -a max_chapters=5
    scrapy crawl mangadex -a language=en -a data_saver=0
    scrapy crawl mangadex -a oneshot_only=1 -a max_manga=500

Output layout:
    output/zips/oneshots/<chapter_id>.zip
    output/zips/series/<chapter_id>.zip
"""

import json
from pathlib import Path

import scrapy

from crawler.items import ImageItem

_API = "https://api.mangadex.org"
_PAGE_SIZE = 100

_ONESHOT_TAG = "0234a31e-a729-4e28-9d6a-3f87c4966b9e"

_LANG_NAMES = {
    "en": "english", "ja": "japanese", "zh": "chinese", "zh-hk": "chinese",
    "ko": "korean", "fr": "french", "es": "spanish", "es-la": "spanish",
    "de": "german", "it": "italian", "pt": "portuguese", "pt-br": "portuguese",
    "ru": "russian", "ar": "arabic", "th": "thai", "vi": "vietnamese",
    "id": "indonesian", "pl": "polish", "nl": "dutch", "tr": "turkish",
    "uk": "ukrainian", "cs": "czech", "hu": "hungarian", "ro": "romanian",
}


class MangadexSpider(scrapy.Spider):
    name = "mangadex"

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "application/json",
        },
    }

    def __init__(
        self,
        chapter_ids: str = "",   # priority mode: comma-separated chapter UUIDs
        manga_id: str = "",
        language: str = "en",
        max_manga: int = 1000,
        max_chapters: int = 3,
        data_saver: str = "1",
        oneshot_only: str = "0",
        series_only: str = "0",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.direct_chapter_ids = [c.strip() for c in chapter_ids.split(",") if c.strip()]
        self.manga_ids = [m.strip() for m in manga_id.split(",") if m.strip()]
        self.language = language
        self.max_manga = int(max_manga)
        self.max_chapters = int(max_chapters)
        self.data_saver = data_saver.strip() not in ("0", "false", "no")
        self.oneshot_only = oneshot_only.strip() not in ("0", "false", "no")
        self.series_only = series_only.strip() not in ("0", "false", "no")
        self.gallery_page_counts: dict[str, int] = {}
        self._discovered = 0

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def start(self):
        if self.direct_chapter_ids:
            quality = "data-saver" if self.data_saver else "original"
            self.logger.info(
                f"Priority mode: {len(self.direct_chapter_ids)} chapter(s), quality={quality}"
            )
            for cid in self.direct_chapter_ids:
                yield scrapy.Request(
                    f"{_API}/chapter/{cid}?includes[]=manga",
                    callback=self.parse_chapter_info,
                    errback=self.on_error,
                    cb_kwargs={"chapter_id": cid},
                )
        elif self.manga_ids:
            for mid in self.manga_ids:
                yield self._manga_request(mid)
        else:
            quality = "data-saver" if self.data_saver else "original"
            self.logger.info(
                f"Discovery mode: up to {self.max_manga} manga, "
                f"{self.max_chapters} chapter(s) each, "
                f"language={self.language}, quality={quality}"
            )
            yield self._listing_request(offset=0)

    # ------------------------------------------------------------------
    # Priority mode: fetch chapter info then manga metadata
    # ------------------------------------------------------------------

    def parse_chapter_info(self, response, chapter_id: str):
        """Fetch chapter attributes + manga relationship, then load manga metadata."""
        data = response.json().get("data", {})
        ch_attrs = data.get("attributes", {})

        manga_id = next(
            (r["id"] for r in data.get("relationships", []) if r["type"] == "manga"),
            None,
        )

        ch_num_raw = ch_attrs.get("chapter") or "0"
        try:
            ch_num = int(float(ch_num_raw))
        except (ValueError, TypeError):
            ch_num = 0

        ch_lang = ch_attrs.get("translatedLanguage", self.language)
        ch_title = ch_attrs.get("title") or ""

        if manga_id:
            yield scrapy.Request(
                f"{_API}/manga/{manga_id}?includes[]=author&includes[]=artist&includes[]=cover_art",
                callback=self.parse_manga_for_chapter,
                errback=self.on_error,
                cb_kwargs={
                    "chapter_id": chapter_id,
                    "ch_num": ch_num,
                    "ch_title": ch_title,
                    "ch_lang": ch_lang,
                },
            )
        else:
            # No manga relationship — fetch pages with minimal metadata
            chapter_meta = {
                "manga_id": "", "manga_title": "", "cover_url": "",
                "chapter_number": ch_num, "chapter_title": ch_title,
                "author": "", "artist": "", "tags": [],
                "category": "manga", "language": _LANG_NAMES.get(ch_lang, ch_lang),
                "is_oneshot": False,
            }
            yield scrapy.Request(
                f"{_API}/at-home/server/{chapter_id}",
                callback=self.parse_at_home,
                errback=self.on_error,
                cb_kwargs={"chapter_id": chapter_id, "chapter_meta": chapter_meta},
            )

    def parse_manga_for_chapter(self, response, chapter_id, ch_num, ch_title, ch_lang):
        """Parse manga metadata then go straight to at-home for this specific chapter."""
        data = response.json().get("data", {})
        chapter_meta = self._extract_manga_meta(data)
        chapter_meta.update({
            "chapter_number": ch_num,
            "chapter_title": ch_title or chapter_meta.get("title", ""),
            "language": _LANG_NAMES.get(ch_lang, ch_lang),
        })
        yield scrapy.Request(
            f"{_API}/at-home/server/{chapter_id}",
            callback=self.parse_at_home,
            errback=self.on_error,
            cb_kwargs={"chapter_id": chapter_id, "chapter_meta": chapter_meta},
        )

    # ------------------------------------------------------------------
    # Discovery: paginated manga listing
    # ------------------------------------------------------------------

    def _listing_request(self, offset: int) -> scrapy.Request:
        limit = min(_PAGE_SIZE, self.max_manga - offset)
        if self.oneshot_only:
            tag_filter = f"&includedTags[]={_ONESHOT_TAG}"
        elif self.series_only:
            tag_filter = f"&excludedTags[]={_ONESHOT_TAG}"
        else:
            tag_filter = ""
        return scrapy.Request(
            (
                f"{_API}/manga"
                f"?order[latestUploadedChapter]=desc"
                f"&limit={limit}"
                f"&offset={offset}"
                f"&includes[]=author&includes[]=artist"
                f"&contentRating[]=safe&contentRating[]=suggestive"
                f"&availableTranslatedLanguage[]={self.language}"
                f"{tag_filter}"
            ),
            callback=self.parse_manga_list,
            errback=self.on_error,
            cb_kwargs={"offset": offset},
        )

    def parse_manga_list(self, response, offset: int):
        body = response.json()
        items = body.get("data", [])
        total = body.get("total", 0)

        for manga in items:
            self._discovered += 1
            yield self._manga_request(manga["id"])

        next_offset = offset + len(items)
        if items and self._discovered < self.max_manga and next_offset < total:
            yield self._listing_request(offset=next_offset)

    # ------------------------------------------------------------------
    # Parse manga metadata + request chapter feed
    # ------------------------------------------------------------------

    def _manga_request(self, manga_id: str) -> scrapy.Request:
        return scrapy.Request(
            f"{_API}/manga/{manga_id}?includes[]=author&includes[]=artist&includes[]=cover_art",
            callback=self.parse_manga,
            errback=self.on_error,
            cb_kwargs={"manga_id": manga_id},
        )

    def parse_manga(self, response, manga_id: str):
        data = response.json().get("data", {})
        manga_meta = self._extract_manga_meta(data)
        is_oneshot = manga_meta["is_oneshot"]

        self.logger.info(
            f"Manga '{manga_meta['title']}' ({'oneshot' if is_oneshot else 'series'}): "
            f"fetching feed"
        )

        remaining = 1 if is_oneshot else self.max_chapters
        yield self._feed_request(manga_id, manga_meta, offset=0, remaining=remaining)

    def _feed_request(self, manga_id: str, manga_meta: dict, offset: int, remaining: int) -> scrapy.Request:
        limit = min(_PAGE_SIZE, remaining)
        return scrapy.Request(
            (
                f"{_API}/manga/{manga_id}/feed"
                f"?translatedLanguage[]={self.language}"
                f"&limit={limit}"
                f"&offset={offset}"
                f"&order[chapter]=asc"
                f"&includeEmptyPages=0"
                f"&includeExternalUrl=0"
            ),
            callback=self.parse_feed,
            errback=self.on_error,
            cb_kwargs={"manga_meta": manga_meta, "offset": offset, "remaining": remaining},
        )

    def parse_feed(self, response, manga_meta: dict, offset: int, remaining: int):
        body = response.json()
        chapters = body.get("data", [])
        total = body.get("total", 0)

        if not chapters:
            self.logger.info(f"No chapters found for: {manga_meta.get('title')}")
            return

        for chapter in chapters:
            cid = chapter["id"]
            ch_attrs = chapter.get("attributes", {})
            ch_num_raw = ch_attrs.get("chapter") or "0"
            ch_title = ch_attrs.get("title") or manga_meta.get("title", "")
            ch_lang = ch_attrs.get("translatedLanguage", self.language)

            try:
                ch_num = int(float(ch_num_raw))
            except (ValueError, TypeError):
                ch_num = 0

            chapter_meta = {
                **manga_meta,
                "chapter_number": ch_num,
                "chapter_title": ch_title,
                "language": _LANG_NAMES.get(ch_lang, ch_lang),
            }

            yield scrapy.Request(
                f"{_API}/at-home/server/{cid}",
                callback=self.parse_at_home,
                errback=self.on_error,
                cb_kwargs={"chapter_id": cid, "chapter_meta": chapter_meta},
            )

        fetched = len(chapters)
        next_remaining = remaining - fetched
        next_offset = offset + fetched
        if fetched == _PAGE_SIZE and next_remaining > 0 and next_offset < total:
            manga_id = manga_meta["manga_id"]
            yield self._feed_request(manga_id, manga_meta, offset=next_offset, remaining=next_remaining)

    # ------------------------------------------------------------------
    # Fetch page image URLs from the at-home CDN
    # ------------------------------------------------------------------

    def parse_at_home(self, response, chapter_id: str, chapter_meta: dict):
        data = response.json()
        base_url = data.get("baseUrl", "")
        ch_data = data.get("chapter", {})
        ch_hash = ch_data.get("hash", "")

        if self.data_saver:
            pages = ch_data.get("dataSaver", [])
            quality_path = "data-saver"
        else:
            pages = ch_data.get("data", [])
            quality_path = "data"

        if not pages:
            self.logger.warning(f"Chapter {chapter_id}: no pages returned")
            return

        is_oneshot = chapter_meta.get("is_oneshot", False)
        kind = "oneshots" if is_oneshot else "series"
        group_id = f"{kind}/{chapter_id}"

        self.gallery_page_counts[group_id] = len(pages)
        self._save_metadata(chapter_meta, group_id)

        self.logger.info(
            f"[{kind}] Chapter {chapter_id} "
            f"(#{chapter_meta.get('chapter_number')} "
            f"'{chapter_meta.get('chapter_title')}'): queued {len(pages)} pages"
        )

        for filename in pages:
            yield ImageItem(
                group_id=group_id,
                image_url=f"{base_url}/{quality_path}/{ch_hash}/{filename}",
                source_url=f"https://mangadex.org/chapter/{chapter_id}",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_manga_meta(self, data: dict) -> dict:
        """Extract standardised manga metadata from a MangaDex manga data object."""
        attrs = data.get("attributes", {})
        relationships = data.get("relationships", [])
        manga_id = data.get("id", "")

        title_obj = attrs.get("title", {})
        title = (
            title_obj.get("en")
            or title_obj.get("ja-ro")
            or next(iter(title_obj.values()), "")
        )

        authors = [
            r["attributes"]["name"]
            for r in relationships
            if r["type"] == "author" and r.get("attributes")
        ]
        artists = [
            r["attributes"]["name"]
            for r in relationships
            if r["type"] == "artist" and r.get("attributes")
        ]
        if not artists:
            artists = authors

        tags = [
            t["attributes"]["name"]["en"]
            for t in attrs.get("tags", [])
            if t.get("attributes", {}).get("name", {}).get("en")
        ]

        tag_ids = {t["id"] for t in attrs.get("tags", [])}
        is_oneshot = _ONESHOT_TAG in tag_ids
        demographic = attrs.get("publicationDemographic") or "manga"

        cover_url = ""
        for r in relationships:
            if r["type"] == "cover_art" and r.get("attributes"):
                filename = r["attributes"].get("fileName", "")
                if filename:
                    cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
                break

        return {
            "manga_id": manga_id,
            "title": title,
            "manga_title": title,
            "author": ", ".join(authors),
            "artist": ", ".join(artists),
            "tags": tags,
            "category": demographic,
            "is_oneshot": is_oneshot,
            "cover_url": cover_url,
        }

    def _save_metadata(self, chapter_meta: dict, group_id: str):
        store = self.settings.get("FILES_STORE", "output/images")
        dest_dir = Path(store) / group_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "manga_id": chapter_meta.get("manga_id", ""),
            "manga_title": chapter_meta.get("manga_title") or chapter_meta.get("title", ""),
            "cover_url": chapter_meta.get("cover_url", ""),
            "chapter_number": chapter_meta.get("chapter_number", 0),
            "chapter_title": chapter_meta.get("chapter_title", ""),
            "author": chapter_meta.get("author", ""),
            "artist": chapter_meta.get("artist", ""),
            "tags": chapter_meta.get("tags", []),
            "category": chapter_meta.get("category", "manga"),
            "language": chapter_meta.get("language", "english"),
        }

        with open(dest_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def on_error(self, failure):
        self.logger.error(
            f"Request failed: {failure.request.url} — {failure.value}"
        )
