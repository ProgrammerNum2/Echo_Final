from __future__ import annotations
from typing import Any
import httpx

class HttpClient:
    def __init__(self, timeout: float = 30.0):
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def post_json(self, url: str, *, headers: dict[str, str], body: dict[str, Any]):
        try:
            r = await self.client.post(url, headers=headers, json=body)
            try:
                data = r.json()
            except ValueError:
                data = {"raw": r.text[:500]}
            return r.status_code, data
        except httpx.HTTPError as e:
            raise RuntimeError(f"{type(e).__name__}: {e}") from e

    async def close(self):
        await self.client.aclose()
