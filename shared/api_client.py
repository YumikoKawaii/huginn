"""
Shared authenticated API client for sherry-archive.com.

Used by both the crawler uploader and bot user setup.
"""

import os
import requests
from pathlib import Path


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


class ApiClient:
    def __init__(self, base_url: str, email: str = "", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.session = requests.Session()

    def _headers(self) -> dict:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def login(self):
        r = self.session.post(
            f"{self.base_url}/auth/login",
            json={"email": self.email, "password": self.password},
        )
        r.raise_for_status()
        data = r.json()["data"]
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    def _refresh(self):
        r = self.session.post(
            f"{self.base_url}/auth/refresh",
            json={"refresh_token": self.refresh_token},
        )
        if not r.ok:
            self.login()
            return
        data = r.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        r = self.session.request(
            method, f"{self.base_url}{path}",
            headers=self._headers(), **kwargs,
        )
        if r.status_code == 401 and self.access_token:
            self._refresh()
            r = self.session.request(
                method, f"{self.base_url}{path}",
                headers=self._headers(), **kwargs,
            )
        r.raise_for_status()
        return r

    # --- Auth ---

    def register(self, email: str, password: str, username: str) -> dict:
        r = self.session.post(
            f"{self.base_url}/auth/register",
            json={"email": email, "password": password, "username": username},
        )
        r.raise_for_status()
        return r.json()

    # --- Manga ---

    def list_mangas(self, q: str = "", page: int = 1, limit: int = 20, **filters) -> dict:
        params: dict = {"page": page, "limit": limit}
        if q:
            params["q"] = q
        params.update(filters)
        return self._request("GET", "/mangas", params=params).json()

    def get_manga(self, manga_id: str) -> dict:
        return self._request("GET", f"/mangas/{manga_id}").json()

    def create_manga(self, meta: dict) -> str:
        payload = {
            "title": meta.get("manga_title") or meta.get("chapter_title", "Untitled"),
            "type": meta.get("type", "oneshot"),
            "status": meta.get("status", "completed"),
            "author": meta.get("author", ""),
            "artist": meta.get("artist", ""),
            "category": meta.get("category", ""),
            "tags": meta.get("tags", []),
        }
        return self._request("POST", "/mangas", json=payload).json()["data"]["id"]

    def upload_cover(self, manga_id: str, image_data: bytes, filename: str, content_type: str):
        self._request(
            "PUT", f"/mangas/{manga_id}/cover",
            files={"cover": (filename, image_data, content_type)},
        )

    def upload_oneshot(self, manga_id: str, zip_path: Path) -> dict:
        with open(zip_path, "rb") as f:
            r = self._request(
                "POST", f"/mangas/{manga_id}/oneshot/upload",
                files={"file": (zip_path.name, f, "application/zip")},
            )
        return r.json()["data"]

    # --- Chapters ---

    def list_chapters(self, manga_id: str) -> list:
        return self._request("GET", f"/mangas/{manga_id}/chapters").json().get("data", [])

    def get_chapter(self, manga_id: str, chapter_id: str) -> dict:
        return self._request("GET", f"/mangas/{manga_id}/chapters/{chapter_id}").json()

    def create_chapter(self, manga_id: str, meta: dict) -> str:
        payload = {
            "number": meta.get("chapter_number", 0),
            "title": meta.get("chapter_title", ""),
        }
        return self._request("POST", f"/mangas/{manga_id}/chapters", json=payload).json()["data"]["id"]

    def upload_chapter_zip(self, manga_id: str, chapter_id: str, zip_path: Path) -> dict:
        with open(zip_path, "rb") as f:
            r = self._request(
                "POST", f"/mangas/{manga_id}/chapters/{chapter_id}/pages/zip",
                files={"file": (zip_path.name, f, "application/zip")},
            )
        return r.json()["data"]

    # --- Users ---

    def list_bookmarks(self) -> list:
        return self._request("GET", "/users/me/bookmarks").json().get("data", [])

    def upsert_bookmark(self, manga_id: str):
        self._request("PUT", f"/users/me/bookmarks/{manga_id}", json={})

    def delete_bookmark(self, manga_id: str):
        self._request("DELETE", f"/users/me/bookmarks/{manga_id}")
