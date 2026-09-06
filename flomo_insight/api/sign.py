"""MD5 signature builder for flomo API requests.

The flomo internal API requires a `sign` parameter:
    MD5(sorted_query_params_joined_with_& + SALT)

The salt is **not** shipped in this repository. Obtain it from the flomo
web app's client bundle (same value for every user) and put it in
`config.toml` → `flomo_sign_salt`, or env `FLOMO_SIGN_SALT`.
"""

from __future__ import annotations

import hashlib
import os
import time


class MissingSignSalt(RuntimeError):
    """Raised when the flomo request signing salt is not configured."""


def get_sign_salt() -> str:
    """Return signing salt: env FLOMO_SIGN_SALT wins, else config.toml."""
    salt = (os.environ.get("FLOMO_SIGN_SALT") or "").strip()
    if salt:
        return salt
    from flomo_insight.config import load_config

    salt = (load_config().flomo_sign_salt or "").strip()
    if salt:
        return salt
    raise MissingSignSalt(
        "flomo_sign_salt is not set.\n"
        "Copy it from the flomo web client bundle into config.toml "
        "(flomo_sign_salt = \"...\") or export FLOMO_SIGN_SALT."
    )


def sign_params(params: dict[str, str], salt: str | None = None) -> dict[str, str]:
    """Return a copy of `params` with a `sign` field added."""
    if salt is None:
        salt = get_sign_salt()
    ordered = sorted(params.items(), key=lambda x: x[0])
    raw = "&".join(f"{k}={v}" for k, v in ordered) + salt
    sig = hashlib.md5(raw.encode()).hexdigest()
    result = dict(params)
    result["sign"] = sig
    return result


def build_create_payload(
    content: str,
    source: str = "web",
    extra: dict[str, str] | None = None,
    salt: str | None = None,
) -> dict[str, str]:
    """Build signed JSON body for PUT /api/v1/memo (write operations)."""
    payload: dict[str, str] = {
        "content": content,
        "source": source,
        "tz": "8:0",
        "timestamp": str(int(time.time())),
        "api_key": "flomo_web",
        "app_version": "4.0",
        "platform": "web",
        "webp": "1",
    }
    if extra:
        payload.update(extra)
    return sign_params(payload, salt=salt)


def build_memo_params(
    limit: int = 200,
    latest_slug: str | None = None,
    latest_updated_at: str | None = None,
    salt: str | None = None,
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
    return sign_params(params, salt=salt)
