"""
Upload crawled zips to the archive API.
Handles both oneshot and series zips.
"""

import json
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

from shared.api_client import ApiClient


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


def _upload_oneshots(client: ApiClient, zips: list[Path]) -> tuple[int, int, list]:
    ok, skipped, failed = 0, 0, []
    for i, zip_path in enumerate(zips, 1):
        prefix = f"[oneshot {i}/{len(zips)}]"
        if not zip_path.exists():
            print(f"{prefix} SKIP {zip_path.name}: not found")
            skipped += 1
            continue

        meta = _read_meta(zip_path)
        title = (meta.get("chapter_title") or zip_path.stem)[:70]
        print(f"{prefix} {title}")

        try:
            meta["type"] = "oneshot"
            manga_id = client.create_manga(meta)
            result = client.upload_oneshot(manga_id, zip_path)
            pages = len(result.get("pages", []))
            print(f"        ✓ manga_id={manga_id} pages={pages}")
            ok += 1
        except requests.HTTPError as exc:
            body = exc.response.text[:120] if exc.response is not None else str(exc)
            print(f"        ✗ HTTP {getattr(exc.response, 'status_code', '?')}: {body}")
            failed.append((zip_path.name, body))
        except Exception as exc:
            print(f"        ✗ {exc}")
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
        # Deduplicate by chapter number (multiple scanlation groups)
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
        display_title = (first_meta.get("manga_title") or mid)[:60]
        print(f"\nSeries: {display_title}  ({len(chapters)} chapter(s))")

        try:
            first_meta["type"] = "series"
            first_meta.setdefault("status", "ongoing")
            api_manga_id = client.create_manga(first_meta)
            print(f"  ✓ manga created  manga_id={api_manga_id}")
        except requests.HTTPError as exc:
            body = exc.response.text[:120] if exc.response is not None else str(exc)
            print(f"  ✗ manga creation failed: {body}")
            for _, zp, _ in chapters:
                failed.append((zp.name, f"manga creation: {body}"))
            done += len(chapters)
            continue

        # Upload cover — try cover_url first, fall back to first page
        cover_uploaded = False
        cover_url = first_meta.get("cover_url", "")
        if cover_url:
            try:
                r = requests.get(cover_url, timeout=30)
                r.raise_for_status()
                ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
                filename = cover_url.rsplit("/", 1)[-1]
                client.upload_cover(api_manga_id, r.content, filename, ct)
                print(f"  ✓ cover uploaded")
                cover_uploaded = True
            except Exception as exc:
                print(f"  ! cover_url failed ({exc}), trying first page")

        if not cover_uploaded:
            img = _first_image(chapters[0][1])
            if img:
                try:
                    client.upload_cover(api_manga_id, img[0], "cover.jpg", img[1])
                    print(f"  ✓ cover from first page")
                except Exception as exc:
                    print(f"  ! cover fallback failed: {exc}")

        for ch_num, zip_path, meta in chapters:
            done += 1
            prefix = f"  [{done}/{total}] ch#{ch_num}"

            if not zip_path.exists():
                print(f"{prefix} SKIP {zip_path.name}: not found")
                skipped += 1
                continue

            print(f"{prefix}  {zip_path.stem[:36]}")
            try:
                chapter_id = client.create_chapter(api_manga_id, meta)
                result = client.upload_chapter_zip(api_manga_id, chapter_id, zip_path)
                pages = len(result.get("pages", []))
                print(f"         ✓ chapter_id={chapter_id}  pages={pages}")
                ok += 1
            except requests.HTTPError as exc:
                body = exc.response.text[:120] if exc.response is not None else str(exc)
                print(f"         ✗ HTTP {getattr(exc.response, 'status_code', '?')}: {body}")
                failed.append((zip_path.name, body))
            except Exception as exc:
                print(f"         ✗ {exc}")
                failed.append((zip_path.name, str(exc)))

            time.sleep(0.3)

    return ok, skipped, failed


def upload_all(client: ApiClient, zips_dir: Path):
    oneshot_dir = zips_dir / "oneshots"
    series_dir = zips_dir / "series"

    oneshot_zips = sorted(oneshot_dir.glob("*.zip")) if oneshot_dir.exists() else []
    series_zips = sorted(series_dir.glob("*.zip")) if series_dir.exists() else []

    print(f"Uploading {len(oneshot_zips)} oneshot(s) + {len(series_zips)} series chapter(s)")

    ok, skipped, failed = 0, 0, []

    if oneshot_zips:
        o, s, f = _upload_oneshots(client, oneshot_zips)
        ok += o; skipped += s; failed += f

    if series_zips:
        o, s, f = _upload_series(client, series_zips)
        ok += o; skipped += s; failed += f

    print(f"\n{'─' * 50}")
    print(f"Upload done — {ok} succeeded / {skipped} skipped / {len(failed)} failed")
    if failed:
        print("\nFailed:")
        for name, err in failed:
            print(f"  • {name}: {err}")
