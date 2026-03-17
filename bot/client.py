"""
Async API clients for the bot.

AnonClient  — unauthenticated read-only access
AuthClient  — adds login/logout/bookmark on top of AnonClient
"""

import aiohttp


class AnonClient:
    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base = base_url.rstrip("/")
        self._session = session

    async def list_mangas(self, **params) -> dict:
        async with self._session.get(f"{self._base}/mangas", params=params) as r:
            r.raise_for_status()
            return await r.json()

    async def get_manga(self, manga_id: str) -> dict:
        async with self._session.get(f"{self._base}/mangas/{manga_id}") as r:
            r.raise_for_status()
            return await r.json()

    async def list_chapters(self, manga_id: str) -> list:
        async with self._session.get(f"{self._base}/mangas/{manga_id}/chapters") as r:
            r.raise_for_status()
            data = await r.json()
            return data.get("data", [])

    async def get_chapter(self, manga_id: str, chapter_id: str) -> dict:
        async with self._session.get(
            f"{self._base}/mangas/{manga_id}/chapters/{chapter_id}"
        ) as r:
            r.raise_for_status()
            return await r.json()


class AuthClient(AnonClient):
    def __init__(self, base_url: str, session: aiohttp.ClientSession, email: str, password: str):
        super().__init__(base_url, session)
        self._email = email
        self._password = password
        self._access_token = ""

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    async def login(self):
        async with self._session.post(
            f"{self._base}/auth/login",
            json={"email": self._email, "password": self._password},
        ) as r:
            r.raise_for_status()
            data = (await r.json())["data"]
            self._access_token = data["access_token"]

    async def logout(self):
        if not self._access_token:
            return
        async with self._session.post(
            f"{self._base}/auth/logout",
            headers=self._auth_headers(),
        ) as r:
            pass
        self._access_token = ""

    async def list_bookmarks(self) -> list:
        async with self._session.get(
            f"{self._base}/users/me/bookmarks",
            headers=self._auth_headers(),
        ) as r:
            r.raise_for_status()
            return (await r.json()).get("data", [])

    async def upsert_bookmark(self, manga_id: str):
        async with self._session.put(
            f"{self._base}/users/me/bookmarks/{manga_id}",
            headers=self._auth_headers(),
            json={},
        ) as r:
            r.raise_for_status()

    async def delete_bookmark(self, manga_id: str):
        async with self._session.delete(
            f"{self._base}/users/me/bookmarks/{manga_id}",
            headers=self._auth_headers(),
        ) as r:
            r.raise_for_status()
