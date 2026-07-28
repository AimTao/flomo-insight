"""MD5 signature builder for flomo API requests.

The flomo internal API requires a `sign` parameter computed as:
    MD5(sorted_query_params_joined_with_& + SALT)

Salt is extracted from the flomo web app's source: "dbbc3dd73364b4084c3a69346e0ce2b2"
"""

from __future__ import annotations

import hashlib
import time


SALT = "dbbc3dd73364b4084c3a69346e0ce2b2"


def sign_params(params: dict[str, str]) -> dict[str, str]:
    """Return a copy of `params` with a `sign` field added."""
    # Sort by key, join as k=v, append salt, MD5
    ordered = sorted(params.items(), key=lambda x: x[0])
    raw = "&".join(f"{k}={v}" for k, v in ordered) + SALT
    sig = hashlib.md5(raw.encode()).hexdigest()
    result = dict(params)
    result["sign"] = sig
    return result


def build_memo_params(
    limit: int = 200,
    latest_slug: str | None = None,
    latest_updated_at: str | None = None,
) -> dict[str, str]:
    """Build signed query parameters for GET /api/v1/memo/updated/"""
    params: dict[str, str] = {
        "limit": str(limit),
        "tz": "8:0",
        "timestamp": str(int(time.time())),
        "api_key": "flomo_web",
        "app_version": "4.0",
        "platform": "web",
        "webp": "1",
    }
    if latest_slug:
        params["latest_slug"] = latest_slug
    if latest_updated_at:
        params["latest_updated_at"] = latest_updated_at
    return sign_params(params)
