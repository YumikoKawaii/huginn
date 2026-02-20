"""
Example image spider — replace START_URLS and the parse logic with your target site.

Usage:
    scrapy crawl images -a group=my_group -a start=https://example.com/gallery
"""

import scrapy

from huginn.items import ImageItem


class ImageSpider(scrapy.Spider):
    name = "images"

    # Override via -a start=<url> on the command line
    start_urls: list[str] = []

    def __init__(self, group: str = "default", start: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.default_group = group
        if start:
            self.start_urls = [start]

    # ------------------------------------------------------------------
    # Override this method to match your target site's HTML structure
    # ------------------------------------------------------------------

    def parse(self, response):
        """Extract all <img> tags from the page and yield ImageItems."""
        for img in response.css("img"):
            src = img.attrib.get("src") or img.attrib.get("data-src")
            if not src:
                continue

            absolute_url = response.urljoin(src)

            yield ImageItem(
                group_id=self.default_group,
                image_url=absolute_url,
                source_url=response.url,
            )

        # Follow pagination / next links — adjust the selector to your site
        next_page = response.css("a[rel='next']::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
