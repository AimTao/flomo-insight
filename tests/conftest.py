"""Test fixtures — synthetic data only, never real user data."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.db import DatabaseManager


# ── Known-correct sign fixture (captured from a real flomo web request) ──────
# URL: /api/v1/memo/updated/?limit=200&latest_updated_at=1785153897
#      &latest_slug=MTQ0NzU1NDQz&tz=8:0&timestamp=1785203012
#      &api_key=flomo_web&app_version=4.0&platform=web&webp=1
#      &sign=abdcd080f48134d9f2a0459c61d11dab
KNOWN_SIGN_PARAMS = {
    "limit": "200",
    "latest_updated_at": "1785153897",
    "latest_slug": "MTQ0NzU1NDQz",
    "tz": "8:0",
    "timestamp": "1785203012",
    "api_key": "flomo_web",
    "app_version": "4.0",
    "platform": "web",
    "webp": "1",
}
KNOWN_SIGN = "abdcd080f48134d9f2a0459c61d11dab"


@pytest.fixture
def tmp_db() -> DatabaseManager:
    """Fresh in-memory-ish SQLite database in a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = DatabaseManager(path)
    conn = db.get_connection()
    db.migrate(conn)
    conn.close()
    yield db
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def tmp_conn(tmp_db: DatabaseManager) -> sqlite3.Connection:
    """Connection to the temp DB. Caller closes via fixture teardown."""
    conn = tmp_db.get_connection()
    yield conn
    conn.close()


# ── Synthetic memos (clearly fake content, never real notes) ─────────────────


def make_memo(
    slug: str = "synthetic-1",
    content: str = "synthetic test memo content",
    tags: list[Any] | None = None,
    created_at: int = 1700000000000,  # ms epoch
    updated_at: int = 1700000000000,
    source: str = "flomo",
) -> dict[str, Any]:
    """Build a fake flomo memo dict (matches API response shape)."""
    return {
        "slug": slug,
        "content": content,
        "raw_content": content,
        "source": source,
        "created_at": created_at,
        "updated_at": updated_at,
        "tags": tags if tags is not None else [],
    }


@pytest.fixture
def synthetic_memos() -> list[dict[str, Any]]:
    """A small batch of synthetic memos for sync/search tests."""
    return [
        make_memo(
            slug="syn-1",
            content="<p>#时间管理 两分钟法则</p>",
            tags=[{"name": "时间管理"}],
            created_at=1700000000000,
            updated_at=1700000000000,
        ),
        make_memo(
            slug="syn-2",
            content="<p>#阅读 读书笔记</p>",
            tags=[{"name": "阅读"}],
            created_at=1700100000000,
            updated_at=1700100000000,
        ),
        make_memo(
            slug="syn-3",
            content="<p>#时间管理 番茄工作法</p>",
            tags=[{"name": "时间管理"}],
            created_at=1700200000000,
            updated_at=1700200000000,
        ),
    ]
