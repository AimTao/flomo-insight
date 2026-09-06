"""TDD: local write-through after flomo success (update / delete / create mirror)."""

from __future__ import annotations

from unittest.mock import MagicMock

from flomo_insight.sync.exporter import _upsert_memo, _delete_memo
from flomo_insight.sync.local_write import (
    apply_create_locally,
    apply_delete_locally,
    apply_update_locally,
    list_local_pending,
)
from tests.conftest import make_memo


def test_apply_update_locally_replaces_content_and_tags(tmp_conn):
    _upsert_memo(
        tmp_conn,
        make_memo(slug="u1", content="<p>#旧 旧内容</p>", tags=[{"name": "旧"}]),
    )
    apply_update_locally(tmp_conn, "u1", "<p>#新 新内容</p>")

    row = tmp_conn.execute("SELECT content FROM memos WHERE slug='u1'").fetchone()
    assert "新内容" in row["content"]
    tags = tmp_conn.execute(
        "SELECT t.name FROM memo_tags mt JOIN tags t ON t.id=mt.tag_id WHERE mt.memo_slug='u1'"
    ).fetchall()
    names = {t["name"] for t in tags}
    assert "新" in names
    assert "旧" not in names


def test_apply_delete_locally_removes_row(tmp_conn):
    _upsert_memo(tmp_conn, make_memo(slug="d1", content="<p>bye</p>"))
    apply_delete_locally(tmp_conn, "d1")
    assert tmp_conn.execute("SELECT 1 FROM memos WHERE slug='d1'").fetchone() is None


def test_apply_create_locally_upserts_flomo_response(tmp_conn):
    payload = make_memo(
        slug="cloud-1",
        content="<p>#AI 新建</p>",
        tags=[{"name": "AI"}],
        created_at=1700000001000,
        updated_at=1700000001000,
    )
    apply_create_locally(tmp_conn, payload)
    row = tmp_conn.execute("SELECT slug, content FROM memos WHERE slug='cloud-1'").fetchone()
    assert row is not None
    assert "新建" in row["content"]


def test_list_local_pending_only_source_local(tmp_conn):
    _upsert_memo(tmp_conn, make_memo(slug="from-cloud", content="<p>synced</p>", source="flomo"))
    _upsert_memo(tmp_conn, make_memo(slug="local-1", content="<p>#本地 待推送</p>", source="local"))
    pending = list_local_pending(tmp_conn)
    assert [p["slug"] for p in pending] == ["local-1"]


def test_write_path_calls_flomo_then_local(tmp_conn):
    """Order: flomo client first, then local apply — only local on flomo success."""
    client = MagicMock()
    client.update_memo.return_value = {"code": 0}
    calls: list[str] = []

    def flomo_update(slug, content):
        calls.append("flomo")
        return client.update_memo(slug, content)

    def local_apply(slug, content):
        calls.append("local")

    flomo_update("x", "y")
    local_apply("x", "y")
    assert calls == ["flomo", "local"]


def test_delete_memo_helper_cleans_tags(tmp_conn):
    _upsert_memo(
        tmp_conn,
        make_memo(slug="del-tag", content="<p>#标签 x</p>", tags=[{"name": "标签"}]),
    )
    _delete_memo(tmp_conn, "del-tag")
    assert tmp_conn.execute(
        "SELECT 1 FROM memo_tags WHERE memo_slug='del-tag'"
    ).fetchone() is None
