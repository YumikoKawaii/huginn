"""
Upload crawled zips to the archive API.
Handles both oneshot and series zips.
"""

import json
import logging
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

from shared.api_client import ApiClient

log = logging.getLogger(__name__)


def _read_meta(zip_path: Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if "metadata.json" in zf.namelist():
                return json.loads(zf.read("metadata.json"))
    except Exception:
        pass
    return {}


def _first_image(zip_path: Path) -> tuple[bytes, str] | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            images = sorted(
                n for n in zf.namelist()
                if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            )
            if images:
                data = zf.read(images[0])
                ext = images[0].rsplit(".", 1)[-1].lower()
                ct = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
                return data, ct
    except Exception:
        pass
    return None


def _find_archive_manga(client: ApiClient, title: str) -> tuple[str | None, set[int]]:
    """
    Search the archive for an existing manga by title.
    Returns (api_manga_id, existing_chapter_numbers) or (None, set()).
    """
    try:
        results = client.list_mangas(q=title, limit=5)
        data = results.get("data", {})
        items = data.get("items", []) if isinstance(data, dict) else data
        match = next(
            (m for m in items if m.get("title", "").lower() == title.lower()),
            items[0] if items else None,
        )
        if not match:
            return None, set()

        api_manga_id = match["id"]
        chapters = client.list_chapters(api_manga_id)
        existing = {int(float(ch.get("number", 0))) for ch in chapters}
        log.debug("Archive lookup '%s': found manga_id=%s, %d existing chapter(s)",
                  title, api_manga_id, len(existing))
        return api_manga_id, existing
    except Exception as exc:
        log.warning("Archive lookup failed for '%s': %s", title, exc)
        return None, set()


def _upload_oneshots(client: ApiClient, zips: list[Path]) -> tuple[int, int, list]:
    ok, skipped, failed = 0, 0, []
    for i, zip_path in enumerate(zips, 1):
        prefix = f"[oneshot {i}/{len(zips)}]"
        if not zip_path.exists():
            log.warning("%s SKIP %s: file not found", prefix, zip_path.name)
            skipped += 1
            continue

        meta = _read_meta(zip_path)
        title = (meta.get("chapter_title") or zip_path.stem)[:70]
        log.info("%s %s", prefix, title)

        existing_id, _ = _find_archive_manga(client, title)
        if existing_id:
            log.info("%s already in archive (manga_id=%s) — skipping", prefix, existing_id)
            skipped += 1
            continue

        try:
            meta["type"] = "oneshot"
            manga_id = client.create_manga(meta)
            result = client.upload_oneshot(manga_id, zip_path)
            pages = len(result.get("pages", []))
            log.info("%s ✓ uploaded  manga_id=%s  pages=%d", prefix, manga_id, pages)
            ok += 1
        except requests.HTTPError as exc:
            body = exc.response.text[:120] if exc.response is not None else str(exc)
            log.error("%s ✗ HTTP %s: %s", prefix, getattr(exc.response, "status_code", "?"), body)
            failed.append((zip_path.name, body))
        except Exception as exc:
            log.error("%s ✗ %s", prefix, exc)
            failed.append((zip_path.name, str(exc)))

        time.sleep(0.3)
    return ok, skipped, failed


def _upload_series(client: ApiClient, zips: list[Path]) -> tuple[int, int, list]:
    ok, skipped, failed = 0, 0, []

    # Group chapters by manga_id from metadata
    groups: dict[str, list[tuple[int, Path, dict]]] = defaultdict(list)
    for zip_path in zips:
        meta = _read_meta(zip_path)
        mid = meta.get("manga_id") or zip_path.stem
        groups[mid].append((meta.get("chapter_number", 0), zip_path, meta))

    for mid in groups:
        groups[mid].sort(key=lambda x: x[0])
        seen: set[int] = set()
        deduped = []
        for entry in groups[mid]:
            if entry[0] not in seen:
                seen.add(entry[0])
                deduped.append(entry)
        groups[mid] = deduped

    total = sum(len(v) for v in groups.values())
    done = 0

    for mid, chapters in groups.items():
        first_meta = chapters[0][2]
        manga_title = first_meta.get("manga_title") or mid
        log.info("Series: '%s'  (%d chapter(s) to process)", manga_title[:60], len(chapters))

        # Upsert: reuse existing manga or create new
        api_manga_id, existing_chapters = _find_archive_manga(client, manga_title)

        if api_manga_id:
            log.info("  Found in archive — manga_id=%s, %d chapter(s) already present",
                     api_manga_id, len(existing_chapters))
        else:
            try:
                first_meta["type"] = "series"
                first_meta.setdefault("status", "ongoing")
                api_manga_id = client.create_manga(first_meta)
                log.info("  ✓ Manga created — manga_id=%s", api_manga_id)
            except requests.HTTPError as exc:
                body = exc.response.text[:120] if exc.response is not None else str(exc)
                log.error("  ✗ Manga creation failed: HTTP %s: %s",
                          getattr(exc.response, "status_code", "?"), body)
                for _, zp, _ in chapters:
                    failed.append((zp.name, f"manga creation: {body}"))
                done += len(chapters)
                continue

            # Upload cover only for newly created manga
            cover_uploaded = False
            cover_url = first_meta.get("cover_url", "")
            if cover_url:
                try:
                    r = requests.get(cover_url, timeout=30)
                    r.raise_for_status()
                    ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
                    filename = cover_url.rsplit("/", 1)[-1]
                    client.upload_cover(api_manga_id, r.content, filename, ct)
                    log.info("  ✓ Cover uploaded from cover_url")
                    cover_uploaded = True
                except Exception as exc:
                    log.warning("  cover_url failed (%s), trying first page fallback", exc)

            if not cover_uploaded:
                img = _first_image(chapters[0][1])
                if img:
                    try:
                        client.upload_cover(api_manga_id, img[0], "cover.jpg", img[1])
                        log.info("  ✓ Cover uploaded from first page")
                    except Exception as exc:
                        log.warning("  Cover fallback also failed: %s", exc)
                else:
                    log.warning("  No cover available for '%s'", manga_title)

        for ch_num, zip_path, meta in chapters:
            done += 1
            prefix = f"  [{done}/{total}] ch#{ch_num}"

            if not zip_path.exists():
                log.warning("%s SKIP %s: file not found", prefix, zip_path.name)
                skipped += 1
                continue

            if ch_num in existing_chapters:
                log.debug("%s SKIP — already in archive", prefix)
                skipped += 1
                continue

            log.info("%s  %s", prefix, zip_path.stem[:36])
            try:
                chapter_id = client.create_chapter(api_manga_id, meta)
                result = client.upload_chapter_zip(api_manga_id, chapter_id, zip_path)
                pages = len(result.get("pages", []))
                log.info("%s ✓ chapter_id=%s  pages=%d", prefix, chapter_id, pages)
                ok += 1
            except requests.HTTPError as exc:
                body = exc.response.text[:120] if exc.response is not None else str(exc)
                log.error("%s ✗ HTTP %s: %s", prefix, getattr(exc.response, "status_code", "?"), body)
                failed.append((zip_path.name, body))
            except Exception as exc:
                log.error("%s ✗ %s", prefix, exc)
                failed.append((zip_path.name, str(exc)))

            time.sleep(0.3)

    return ok, skipped, failed


def upload_all(client: ApiClient, zips_dir: Path):
    oneshot_dir = zips_dir / "oneshots"
    series_dir = zips_dir / "series"

    oneshot_zips = sorted(oneshot_dir.glob("*.zip")) if oneshot_dir.exists() else []
    series_zips = sorted(series_dir.glob("*.zip")) if series_dir.exists() else []

    log.info("Upload starting — %d oneshot(s), %d series chapter(s)",
             len(oneshot_zips), len(series_zips))

    ok, skipped, failed = 0, 0, []

    if oneshot_zips:
        o, s, f = _upload_oneshots(client, oneshot_zips)
        ok += o
        skipped += s
        failed += f

    if series_zips:
        o, s, f = _upload_series(client, series_zips)
        ok += o
        skipped += s
        failed += f

    log.info("Upload done — %d succeeded / %d skipped / %d failed", ok, skipped, len(failed))
    for name, err in failed:
        log.error("  failed: %s — %s", name, err)
