"""HTTP client for flomo's internal API."""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.api.sign import build_memo_params, sign_params

BASE_URL = "https://flomoapp.com"
TIMEOUT = 30.0


class FlomoClient:
    """Thin httpx wrapper for the flomo internal API.

    Token is obtained from browser cookies (flomoapp.com → token).
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=TIMEOUT,
            headers={
                "authorization": f"Bearer {token}",
                "user-agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "content-type": "application/json; charset=utf-8",
                "x-requested-with": "XMLHttpRequest",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FlomoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Read ──────────────────────────────────────────────────────────────

    def get_updated(
        self,
        limit: int = 200,
        latest_slug: str | None = None,
        latest_updated_at: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a page of memos from /api/v1/memo/updated/"""
        params = build_memo_params(
            limit=limit,
            latest_slug=latest_slug,
            latest_updated_at=latest_updated_at,
        )
        resp = self._client.get("/api/v1/memo/updated/", params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FlomoAPIError(f"API returned code {data.get('code')}: {data.get('message', 'unknown')}")
        return data

    # ── Write ─────────────────────────────────────────────────────────────

    def create_memo(self, content: str, tags: list[str] | None = None, source: str = "mcp") -> dict[str, Any]:
        """Create a new memo via PUT /api/memo/"""
        # Build memo content with tags appended
        body_content = content
        if tags:
            tag_str = " ".join(f"#{t}" for t in tags)
            body_content = f"{body_content}\n{tag_str}"

        payload = {
            "content": body_content,
            "source": source,
            "created_at": int(time.time() * 1000),
        }
        params = sign_params({})  # empty base params + sign
        resp = self._client.put("/api/memo/", json=payload, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FlomoAPIError(f"Create memo failed: {data.get('message', 'unknown')}")
        return data

    # ── Health ────────────────────────────────────────────────────────────

    def verify(self) -> bool:
        """Verify the token is valid by making a lightweight request."""
        try:
            self.get_updated(limit=1)
            return True
        except Exception:
            return False


class FlomoAPIError(Exception):
    """Raised when the flomo API returns an error."""
    pass
