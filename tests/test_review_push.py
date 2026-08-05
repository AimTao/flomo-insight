"""Tests for the review-push to D1 (frequency-rotation cards)."""

from __future__ import annotations

from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


class _DummyDb:
    """Stand-in for DatabaseManager exposing migrate/get_connection over tmp_conn."""

    def __init__(self, conn):
        self._conn = conn

    def get_connection(self):
        return self._conn

    def migrate(self, conn):
        return None


def _fake_run(sql):
    return [{"results": []}]


def test_review_push_schema_and_rows(tmp_conn, monkeypatch):
    """review-push emits DROP, CREATE with served_count, and one INSERT per memo."""
    _upsert_memo(tmp_conn, make_memo(
        slug="push-1", content="<p>#效率 两分钟法则</p>",
        tags=[{"name": "效率"}],
        created_at=1700000000000, updated_at=1700000000000,
    ))
    _upsert_memo(tmp_conn, make_memo(
        slug="push-2", content="<p>焦虑是自由的眩晕</p>",
        created_at=1700000000000, updated_at=1700000000000,
    ))

    calls = []
    monkeypatch.setattr(
        "src.backup.d1._run_wrangler",
        lambda db_id, sql: calls.append(sql) or _fake_run(sql),
    )
    monkeypatch.setattr("src.backup.d1.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "src.config.require_d1_database_id", lambda: "test-db-uuid"
    )

    # Point review_push_cmd at the temp DB instead of the real config.toml one.
    from src.main import review_push_cmd
    monkeypatch.setattr("src.main._get_db", lambda: _DummyDb(tmp_conn))

    review_push_cmd()

    ddl = [c for c in calls if "DROP TABLE" in c or "CREATE TABLE" in c]
    inserts = [c for c in calls if "INSERT INTO" in c]

    assert any("DROP TABLE IF EXISTS daily_reviews" in c for c in ddl)
    create = [c for c in ddl if "CREATE TABLE" in c][0]
    # New frequency-rotation columns present; no scheduling columns
    assert "served_count" in create
    assert "due_at" not in create
    assert "interval_days" not in create

    assert len(inserts) == 2
    push1 = [i for i in inserts if "'push-1'" in i][0]
    # Tags stripped from content, no raw HTML
    assert "<p>" not in push1
    assert "#效率" not in push1
    assert "两分钟法则" in push1
    # served_count starts at 0
    assert ",0," in push1
