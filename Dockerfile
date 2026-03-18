FROM python:3.12-slim

# System deps for Pillow (JPEG / PNG / WebP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev zlib1g-dev libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV SCRAPY_SETTINGS_MODULE=crawler.settings

ENTRYPOINT ["python", "huginn.py"]

# Override in ECS task definition:
#   crawler task: CMD ["crawl"]
#   bot task:     CMD ["bot"]
CMD ["--help"]
