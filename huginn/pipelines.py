"""
Pipelines (execution order set in settings.py):

1. ImageDownloadPipeline  — downloads raw image to FILES_STORE/<group_id>/
2. ImageMetaPipeline      — opens saved file with Pillow → fills width/height/format
3. ZipGroupPipeline       — zips a gallery the moment all its pages are downloaded;
                            any incomplete galleries are zipped at spider close.
"""

import os
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from itemadapter import ItemAdapter
from PIL import Image
from scrapy.http import Request
from scrapy.pipelines.files import FilesPipeline


# ---------------------------------------------------------------------------
# 1. Download
# ---------------------------------------------------------------------------

class ImageDownloadPipeline(FilesPipeline):
    """
    Thin wrapper around FilesPipeline.

    - Reads image_url from ImageItem instead of the default 'file_urls' list.
    - Stores files at FILES_STORE/<group_id>/<original-filename>.
    - Writes the final on-disk path back to item['file_path'].
    """

    def get_media_requests(self, item, info):
        adapter = ItemAdapter(item)
        url = adapter.get("image_url")
        if url:
            yield Request(
                url,
                headers={"Referer": "https://nhentai.net/"},
                meta={"item": item},
            )

    def file_path(self, request, response=None, info=None, *, item=None):
        _item = item or request.meta.get("item")
        adapter = ItemAdapter(_item) if _item else {}
        group_id = (
            adapter.get("group_id", "ungrouped")
            if isinstance(adapter, ItemAdapter)
            else "ungrouped"
        )
        filename = os.path.basename(urlparse(request.url).path) or "image"
        return f"{group_id}/{filename}"

    def item_completed(self, results, item, info):
        adapter = ItemAdapter(item)
        store_dir = info.spider.settings.get("FILES_STORE", "output/images")
        for ok, value in results:
            if ok:
                adapter["file_path"] = os.path.join(store_dir, value["path"])
        return item


# ---------------------------------------------------------------------------
# 2. Extract image metadata with Pillow
# ---------------------------------------------------------------------------

class ImageMetaPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def process_item(self, item):
        adapter = ItemAdapter(item)
        file_path = adapter.get("file_path")

        if not file_path or not os.path.isfile(file_path):
            return item

        try:
            with Image.open(file_path) as img:
                if not adapter.get("width"):
                    adapter["width"] = img.width
                if not adapter.get("height"):
                    adapter["height"] = img.height
                adapter["image_format"] = img.format
        except Exception as exc:
            self.crawler.spider.logger.warning(
                f"Pillow could not read {file_path}: {exc}"
            )

        return item


# ---------------------------------------------------------------------------
# 3. Zip each gallery as soon as all its pages are downloaded
# ---------------------------------------------------------------------------

class ZipGroupPipeline:
    """
    Tracks downloaded pages per group_id.

    When the number of downloaded files reaches the expected page count
    (read from spider.gallery_page_counts[group_id]), the gallery is zipped
    immediately and removed from memory.

    Any groups that didn't reach their expected count (partial failures)
    are zipped at spider close as a safety net.
    """

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def open_spider(self):
        settings = self.crawler.settings
        self.files_store = Path(settings.get("FILES_STORE", "output/images"))
        self.zips_store = Path(settings.get("ZIPS_STORE", "output/zips"))
        self.zips_store.mkdir(parents=True, exist_ok=True)
        # group_id -> set of downloaded file paths
        self._groups: dict[str, set[str]] = defaultdict(set)
        # group_ids that have already been zipped
        self._zipped: set[str] = set()

    def process_item(self, item):
        adapter = ItemAdapter(item)
        group_id = adapter.get("group_id", "ungrouped")
        file_path = adapter.get("file_path")

        if file_path and os.path.isfile(file_path):
            self._groups[group_id].add(file_path)

        if group_id not in self._zipped:
            expected = getattr(
                self.crawler.spider, "gallery_page_counts", {}
            ).get(group_id)
            if expected and len(self._groups[group_id]) >= expected:
                self._zip_group(group_id)

        return item

    def close_spider(self):
        # Safety net: zip any groups that never reached their expected count
        for group_id in list(self._groups.keys()):
            if group_id not in self._zipped and self._groups[group_id]:
                self.crawler.spider.logger.warning(
                    f"[ZipGroupPipeline] {group_id}: incomplete download, "
                    f"zipping {len(self._groups[group_id])} available file(s)"
                )
                self._zip_group(group_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _zip_group(self, group_id: str):
        paths = self._groups.get(group_id, set())
        if not paths:
            return

        zip_path = self.zips_store / f"{group_id}.zip"

        # Include metadata.json if it was saved by the spider
        all_files = set(paths)
        meta_file = self.files_store / group_id / "metadata.json"
        if meta_file.is_file():
            all_files.add(str(meta_file))

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(all_files):
                zf.write(path, arcname=os.path.basename(path))

        self._zipped.add(group_id)
        # Free memory — files already on disk
        del self._groups[group_id]

        self.crawler.spider.logger.info(
            f"[ZipGroupPipeline] '{group_id}' done — "
            f"{len(all_files)} file(s) → {zip_path}"
        )
