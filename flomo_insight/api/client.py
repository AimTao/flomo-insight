"""HTTP client for flomo's internal API — with retry and friendly errors."""

from __future__ import annotations

import time
from typing import Any

import httpx

from flomo_insight.api.sign import build_memo_params, build_create_payload

BASE_URL = "https://flomoapp.com"
TIMEOUT = 30.0
MAX_RETRIES = 3
# Sleep when remaining rate limit is at or below this
RATE_LIMIT_THRESHOLD = 10
# Minimum seconds between ANY two flomo requests (anti-ban throttle)
MIN_REQUEST_INTERVAL = 1.2
# Longer pause after write operations (create/update/delete)
WRITE_COOLDOWN = 2.0


class FlomoAPIError(Exception):
    """Raised when the flomo API returns an error."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class FlomoAuthError(FlomoAPIError):
    """Token expired or invalid. User should re-set it."""


class FlomoRateLimitError(FlomoAPIError):
    """Rate limit hit. Caller should back off."""


def _classify_error(code: int, message: str) -> FlomoAPIError:
    """Map flomo API error codes to specific exception types."""
    if code in (-10, -100):
        # -10: 请先登录, -100: sign 错误 (often stale token/session)
        return FlomoAuthError(
            f"Authentication failed (code {code}): {message}\n"
            "Your token may have expired. Re-set it: flomo config set-token NEW_TOKEN",
            code=code,
        )
    return FlomoAPIError(f"API error (code {code}): {message}", code=code)


class FlomoClient:
    """Thin httpx wrapper for the flomo internal API.

    Token: Bearer value from Chrome F12 → Network → /api/ → Authorization.
    Every request is throttled to MIN_REQUEST_INTERVAL to reduce ban risk.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self._last_request_at = 0.0
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

    def _throttle(self, extra: float = 0.0) -> None:
        """Ensure MIN_REQUEST_INTERVAL between consecutive flomo calls."""
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL - (now - self._last_request_at) + extra
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _request_with_retry(
        self, method: str, url: str, *, params: dict | None = None, json: dict | None = None
    ) -> dict[str, Any]:
        """Execute a request with throttle + exponential backoff on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                extra = WRITE_COOLDOWN if method in ("PUT", "POST", "DELETE") and attempt == 0 else 0.0
                self._throttle(extra=extra)
                resp = self._client.request(method, url, params=params, json=json)
                resp.raise_for_status()
                data = resp.json()

                # Rate limit monitoring
                remaining = resp.headers.get("x-ratelimit-remaining")
                if remaining and int(remaining) <= RATE_LIMIT_THRESHOLD:
                    time.sleep(2.0)

                if data.get("code") != 0:
                    code = data.get("code", -1)
                    msg = data.get("message", "unknown")
                    raise _classify_error(code, msg)
                return data

            except FlomoAuthError:
                # Don't retry auth errors — they won't fix themselves
                raise
            except FlomoRateLimitError:
                # Explicit backoff for rate limits
                time.sleep(2.0 ** (attempt + 1))
                last_exc = FlomoRateLimitError("Rate limited")
                continue
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2.0 ** attempt)  # 1s, 2s, 4s
                    continue
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    time.sleep(2.0 ** attempt)
                    last_exc = e
                    continue
                raise

        if last_exc:
            raise last_exc
        raise FlomoAPIError("Max retries exceeded")

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
        return self._request_with_retry("GET", "/api/v1/memo/updated/", params=params)

    # ── Write ─────────────────────────────────────────────────────────────

    def create_memo(self, content: str, tags: list[str] | None = None, source: str = "web") -> dict[str, Any]:
        """Create a new memo via PUT /api/v1/memo

        All fields (content + metadata) go into the JSON body and participate
        in the signature. No query params — the web app sends everything as body.
        Tags are inlined into content by the caller (flomo parses #tag from text);
        the `tags` arg here is only used to reconfirm them are not re-appended.
        """
        body = build_create_payload(content, source=source)
        return self._request_with_retry("PUT", "/api/v1/memo", json=body)

    def update_memo(self, slug: str, content: str) -> dict[str, Any]:
        """Update an existing memo's content via PUT /api/v1/memo/{slug}.

        Tags are inlined in content (#tag). The slug stays the same.
        Body must NOT contain slug (it's in the URL path); including it
        breaks the signature.
        """
        body = build_create_payload(content, source="web")
        return self._request_with_retry("PUT", f"/api/v1/memo/{slug}", json=body)

    def delete_memo(self, slug: str) -> dict[str, Any]:
        """Delete (trash) a memo via DELETE /api/v1/memo/{slug}.

        Returns the API response; the memo's content becomes null and it
        stops appearing in future syncs. The signature needs a non-empty
        content field even though deletion ignores it.
        """
        body = build_create_payload("delete", source="web")
        return self._request_with_retry("DELETE", f"/api/v1/memo/{slug}", json=body)

    # ── Health ────────────────────────────────────────────────────────────

    def verify(self) -> bool:
        """Verify the token is valid by making a lightweight request."""
        try:
            self.get_updated(limit=1)
            return True
        except (FlomoAuthError, FlomoAPIError):
            return False
