#!/usr/bin/env python3
"""
push_data.py — Upload crawled manga zips to the API.

Configuration via environment variables (or a .env file):
    API_BASE_URL   e.g. http://localhost:8080
    API_EMAIL      account email
    API_PASSWORD   account password

Usage:
    # Push all zips in output/zips/
    python push_data.py

    # Push specific gallery IDs only
    python push_data.py 627265 631038
"""

import json
import os
import sys
import time
import zipfile
from pathlib import Path

import requests

ZIPS_DIR = Path("output/zips")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_env():
    """Load .env file into os.environ (if it exists)."""
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class ApiClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.session = requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def login(self):
        url = f"{self.base_url}/auth/login"
        print(f"  POST {url}")
        r = self.session.post(url, json={"email": self.email, "password": self.password})
        if not r.ok:
            print(f"  → {r.status_code} {r.text[:200]}")
        r.raise_for_status()
        data = r.json()["data"]
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    def _refresh(self):
        r = self.session.post(
            f"{self.base_url}/auth/refresh",
            json={"refresh_token": self.refresh_token},
        )
        r.raise_for_status()
        data = r.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an authenticated request; refresh token once on 401."""
        r = self.session.request(
            method, f"{self.base_url}{path}",
            headers=self._headers(), **kwargs,
        )
        if r.status_code == 401:
            self._refresh()
            r = self.session.request(
                method, f"{self.base_url}{path}",
                headers=self._headers(), **kwargs,
            )
        r.raise_for_status()
        return r

    def create_manga(self, meta: dict) -> str:
        """Create a manga entry and return its ID."""
        payload = {
            "title": meta.get("chapter_title", "Untitled"),
            "type": "oneshot",
            "status": meta.get("status", "completed"),
            "author": meta.get("author", ""),
            "artist": meta.get("artist", ""),
            "category": meta.get("category", ""),
            "tags": meta.get("tags", []),
        }
        r = self._request("POST", "/mangas", json=payload)
        return r.json()["data"]["id"]

    def upload_oneshot(self, manga_id: str, zip_path: Path) -> dict:
        """Upload a zip as a oneshot chapter (auto-creates chapter + pages)."""
        with open(zip_path, "rb") as f:
            r = self._request(
                "POST",
                f"/mangas/{manga_id}/oneshot/upload",
                files={"file": (zip_path.name, f, "application/zip")},
            )
        return r.json()["data"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_meta_from_zip(zip_path: Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "metadata.json" in zf.namelist():
                return json.loads(zf.read("metadata.json"))
    except Exception:
        pass
    return {}


def pick_zips(args: list[str]) -> list[Path]:
    if args:
        return [ZIPS_DIR / f"{gid}.zip" for gid in args]
    return sorted(ZIPS_DIR.glob("*.zip"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_env()

    base_url  = os.environ.get("API_BASE_URL", "").rstrip("/")
    email     = os.environ.get("API_EMAIL", "")
    password  = os.environ.get("API_PASSWORD", "")

    if not all([base_url, email, password]):
        print(
            "Error: set API_BASE_URL, API_EMAIL, API_PASSWORD "
            "(env vars or .env file)"
        )
        sys.exit(1)

    zips = pick_zips(sys.argv[1:])
    if not zips:
        print(f"No zip files found in {ZIPS_DIR}")
        sys.exit(0)

    client = ApiClient(base_url, email, password)

    print(f"Logging in as {email} → {base_url}")
    client.login()
    print(f"Authenticated. Pushing {len(zips)} manga(s)...\n")

    ok, skipped, failed = 0, 0, []

    for i, zip_path in enumerate(zips, start=1):
        prefix = f"[{i}/{len(zips)}]"

        if not zip_path.exists():
            print(f"{prefix} SKIP  {zip_path.name}: file not found")
            skipped += 1
            continue

        meta = read_meta_from_zip(zip_path)
        title = (meta.get("chapter_title") or zip_path.stem)[:70]
        print(f"{prefix} {title}")

        try:
            manga_id = client.create_manga(meta)
            result   = client.upload_oneshot(manga_id, zip_path)
            pages    = len(result.get("pages", []))
            print(f"        ✓  manga_id={manga_id}  pages={pages}")
            ok += 1
        except requests.HTTPError as exc:
            body = exc.response.text[:120] if exc.response is not None else str(exc)
            print(f"        ✗  HTTP {exc.response.status_code if exc.response is not None else '?'}: {body}")
            failed.append((zip_path.name, body))
        except Exception as exc:
            print(f"        ✗  {exc}")
            failed.append((zip_path.name, str(exc)))

        # Small pause between uploads to be kind to the server
        time.sleep(0.3)

    # Summary
    print(f"\n{'─'*50}")
    print(f"Done — {ok} succeeded / {skipped} skipped / {len(failed)} failed")
    if failed:
        print("\nFailed:")
        for name, err in failed:
            print(f"  • {name}: {err}")


if __name__ == "__main__":
    main()
