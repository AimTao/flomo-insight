"""TDD: push source=local memos to flomo (create), then replace local row."""

from __future__ import annotations

from unittest.mock import MagicMock

from flomo_insight.sync.exporter import _upsert_memo
from flomo_insight.sync.local_write import list_local_pending, push_local_pending
from tests.conftest import make_memo


def test_list_local_pending_filters_source(tmp_conn):
    _upsert_memo(tmp_conn, make_memo(slug="c1", content="<p>cloud</p>", source="flomo"))
    _upsert_memo(tmp_conn, make_memo(slug="l1", content="<p>#本地 待推</p>", source="local"))
    pending = list_local_pending(tmp_conn)
    assert [p["slug"] for p in pending] == ["l1"]


def test_push_local_pending_creates_on_flomo_and_replaces_row(tmp_conn):
    _upsert_memo(
        tmp_conn,
        make_memo(slug="tmp-local-1", content="<p>#AI 本地草稿</p>", source="local",
                  created_at=1700000000000, updated_at=1700000000000),
    )
    client = MagicMock()
    client.create_memo.return_value = {
        "code": 0,
        "data": {"slug": "cloud-slug-9"},
    }

    result = push_local_pending(tmp_conn, client, limit=10)

    assert result["pushed"] == 1
    assert result["slugs"] == ["cloud-slug-9"]
    client.create_memo.assert_called_once()
    # old local-only row gone
    assert tmp_conn.execute(
        "SELECT 1 FROM memos WHERE slug='tmp-local-1'"
    ).fetchone() is None
    # new row uses flomo slug + source flomo
    row = tmp_conn.execute(
        "SELECT source, content FROM memos WHERE slug='cloud-slug-9'"
    ).fetchone()
    assert row is not None
    assert row["source"] in ("flomo", "web")
    assert "本地草稿" in row["content"]


def test_push_local_pending_empty(tmp_conn):
    client = MagicMock()
    result = push_local_pending(tmp_conn, client)
    assert result["pushed"] == 0
    client.create_memo.assert_not_called()
