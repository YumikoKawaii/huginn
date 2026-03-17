import scrapy


class ImageItem(scrapy.Item):
    # Grouping key — all images sharing the same group_id end up in one zip
    group_id = scrapy.Field()

    # Original image URL
    image_url = scrapy.Field()

    # Page the image was found on
    source_url = scrapy.Field()

    # Filled in by the download pipeline after the file is saved
    file_path = scrapy.Field()     # absolute path on disk
    width = scrapy.Field()         # pixels
    height = scrapy.Field()        # pixels
    image_format = scrapy.Field()  # e.g. "JPEG", "PNG", "WEBP"
