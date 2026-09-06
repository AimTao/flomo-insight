"""Tests for sync: upsert, incremental cursor, tag parsing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from flomo_insight.sync.exporter import sync, _upsert_memo, _parse_tags_from_memo, _ts_to_iso
from flomo_insight.db import DatabaseManager
from tests.conftest import make_memo


# ── _upsert_memo ─────────────────────────────────────────────────────────────


def test_upsert_inserts_new_memo(tmp_conn):
    memo = make_memo(slug="new-1", content="hello", tags=[{"name": "tag1"}])
    _upsert_memo(tmp_conn, memo)

    row = tmp_conn.execute("SELECT * FROM memos WHERE slug='new-1'").fetchone()
    assert row["content"] == "hello"
    assert row["source"] == "flomo"


def test_upsert_inserts_tags(tmp_conn):
    memo = make_memo(slug="t-1", tags=[{"name": "阅读"}, {"name": "时间管理"}])
    _upsert_memo(tmp_conn, memo)

    rows = tmp_conn.execute(
        "SELECT t.name FROM tags t JOIN memo_tags mt ON mt.tag_id=t.id WHERE mt.memo_slug='t-1'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert names == {"阅读", "时间管理"}


def test_upsert_skips_unchanged(tmp_conn):
    """Same updated_at → no update (idempotent)."""
    memo = make_memo(slug="u-1", content="v1", updated_at=1700000000000)
    _upsert_memo(tmp_conn, memo)

    # update with different content but SAME updated_at → should skip
    memo2 = make_memo(slug="u-1", content="v2-different", updated_at=1700000000000)
    _upsert_memo(tmp_conn, memo2)

    row = tmp_conn.execute("SELECT content FROM memos WHERE slug='u-1'").fetchone()
    assert row["content"] == "v1"  # unchanged


def test_upsert_updates_on_changed(tmp_conn):
    memo = make_memo(slug="u-2", content="v1", updated_at=1700000000000)
    _upsert_memo(tmp_conn, memo)

    memo2 = make_memo(slug="u-2", content="v2", updated_at=1700000000001)
    _upsert_memo(tmp_conn, memo2)

    row = tmp_conn.execute("SELECT content FROM memos WHERE slug='u-2'").fetchone()
    assert row["content"] == "v2"


def test_upsert_replaces_tags_on_update(tmp_conn):
    """When a memo updates, old tags cleared and new ones inserted."""
    memo = make_memo(slug="rt-1", tags=[{"name": "old"}], updated_at=1000)
    _upsert_memo(tmp_conn, memo)

    memo2 = make_memo(slug="rt-1", tags=[{"name": "new"}], updated_at=1001)
    _upsert_memo(tmp_conn, memo2)

    rows = tmp_conn.execute(
        "SELECT t.name FROM tags t JOIN memo_tags mt ON mt.tag_id=t.id WHERE mt.memo_slug='rt-1'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert names == {"new"}


# ── _parse_tags_from_memo ────────────────────────────────────────────────────


def test_parse_tags_dict_format():
    """flomo API returns tags as [{name: ...}]."""
    memo = {"tags": [{"name": "阅读"}, {"name": "思考"}], "content": ""}
    assert _parse_tags_from_memo(memo) == ["阅读", "思考"]


def test_parse_tags_string_format():
    """Some responses return tags as plain strings."""
    memo = {"tags": ["阅读", "思考"], "content": ""}
    assert _parse_tags_from_memo(memo) == ["阅读", "思考"]


def test_parse_tags_fallback_to_content():
    """No tags field → parse #tags from content."""
    memo = {"tags": [], "content": "<p>#时间管理 两分钟法则 #效率</p>"}
    assert set(_parse_tags_from_memo(memo)) == {"时间管理", "效率"}


def test_parse_tags_empty():
    assert _parse_tags_from_memo({"tags": [], "content": "no tags here"}) == []


# ── _ts_to_iso ───────────────────────────────────────────────────────────────


def test_ts_to_iso_milliseconds():
    """flomo sends ms-epoch timestamps."""
    iso = _ts_to_iso(1700000000000)
    assert iso.startswith("2023-11-14")


def test_ts_to_iso_none():
    assert _ts_to_iso(None) == ""


def test_ts_to_iso_string_passthrough():
    assert _ts_to_iso("2024-01-01T00:00:00") == "2024-01-01T00:00:00"


# ── sync() with mocked client ────────────────────────────────────────────────


def _mock_client(pages: list[list[dict]]) -> MagicMock:
    """Create a mock FlomoClient that returns successive pages."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    calls = {"i": 0}

    def get_updated(**kwargs):
        i = calls["i"]
        calls["i"] += 1
        if i >= len(pages):
            return {"code": 0, "data": []}
        return {"code": 0, "data": pages[i]}

    client.get_updated = get_updated
    return client


def test_sync_full_pulls_all_pages(tmp_db):
    """Full sync: pulls 2 pages then empty → stops."""
    page1 = [make_memo(slug=f"p1-{i}") for i in range(200)]
    page2 = [make_memo(slug=f"p2-{i}") for i in range(50)]
    client = _mock_client([page1, page2])

    result = sync(client, tmp_db, full=True, show_progress=False)

    assert result.total == 250
    assert result.new == 250


def test_sync_incremental_uses_cursor(tmp_db):
    """Incremental sync reads cursor from sync_state."""
    # Pre-seed sync_state with a cursor
    conn = tmp_db.get_connection()
    conn.execute("INSERT INTO sync_state (key, value) VALUES ('latest_slug', 'OLD_SLUG')")
    conn.execute("INSERT INTO sync_state (key, value) VALUES ('latest_updated_at', '1000')")
    conn.commit()
    conn.close()

    client = _mock_client([[make_memo(slug="new-1")]])
    captured_kwargs = []
    orig = client.get_updated

    def spy(**kwargs):
        captured_kwargs.append(kwargs)
        return orig(**kwargs)

    client.get_updated = spy

    sync(client, tmp_db, full=False, show_progress=False)

    # First call must use the seeded cursor
    assert captured_kwargs[0]["latest_slug"] == "OLD_SLUG"
    assert captured_kwargs[0]["latest_updated_at"] == "1000"


def test_sync_persists_cursor(tmp_db):
    """After sync, the cursor is written to sync_state."""
    page = [make_memo(slug="last-slug", updated_at=9999999999999)]
    client = _mock_client([page])
    sync(client, tmp_db, full=True, show_progress=False)

    conn = tmp_db.get_connection()
    slug = conn.execute("SELECT value FROM sync_state WHERE key='latest_slug'").fetchone()
    assert slug["value"] == "last-slug"
    conn.close()


def test_sync_idempotent_second_run(tmp_db):
    """Running sync twice with same data doesn't duplicate."""
    page = [make_memo(slug="idem-1", updated_at=1700000000000)]
    client = _mock_client([page])

    sync(client, tmp_db, full=True, show_progress=False)
    # Second run: client returns same page then empty
    client2 = _mock_client([page])
    result = sync(client2, tmp_db, full=True, show_progress=False)

    # new should be 0 (already existed), total 1
    assert result.total == 1
    assert result.new == 0


def test_sync_removes_trashed_memo(tmp_db):
    """A memo that comes back with null content (trashed in flomo) is deleted
    from the local store, not just skipped."""
    # Pre-seed a memo that will be trashed on the next sync
    conn = tmp_db.get_connection()
    from flomo_insight.sync.exporter import _upsert_memo
    _upsert_memo(conn, make_memo(slug="doomed", content="<p>这条要被删</p>"))
    conn.commit()
    conn.close()

    # Next sync returns that memo with null content (trashed)
    trashed = make_memo(slug="doomed")
    trashed["content"] = None
    trashed["raw_content"] = None
    client = _mock_client([[trashed]])

    result = sync(client, tmp_db, full=True, show_progress=False)

    conn = tmp_db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM memos WHERE slug='doomed'").fetchone()[0] == 0
    assert result.total == 0
    conn.close()


def test_sync_removes_memo_with_deleted_at_but_content(tmp_db):
    """A memo with deleted_at set (recent trash) is removed even though flomo
    still returns its content."""
    conn = tmp_db.get_connection()
    from flomo_insight.sync.exporter import _upsert_memo
    _upsert_memo(conn, make_memo(slug="doomed2", content="<p>这条也被删</p>"))
    conn.commit()
    conn.close()

    deleted = make_memo(slug="doomed2")
    deleted["deleted_at"] = "2026-08-05 12:00:00"  # content still present
    client = _mock_client([[deleted]])

    result = sync(client, tmp_db, full=True, show_progress=False)

    conn = tmp_db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM memos WHERE slug='doomed2'").fetchone()[0] == 0
    conn.close()
