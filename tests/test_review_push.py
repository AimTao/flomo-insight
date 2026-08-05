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


def _run_push(tmp_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.backup.d1._run_wrangler",
        lambda db_id, sql: calls.append(sql) or _fake_run(sql),
    )
    monkeypatch.setattr("src.backup.d1.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "src.config.require_d1_database_id", lambda: "test-db-uuid"
    )

    from src.main import review_push_cmd
    monkeypatch.setattr("src.main._get_db", lambda: _DummyDb(tmp_conn))

    review_push_cmd()
    return calls


def test_review_push_schema_and_rows(tmp_conn, monkeypatch):
    """review-push emits DROP, CREATE with served_count, and batch INSERT."""
    _upsert_memo(tmp_conn, make_memo(
        slug="push-1", content="<p>#效率 两分钟法则</p>",
        tags=[{"name": "效率"}],
        created_at=1700000000000, updated_at=1700000000000,
    ))
    _upsert_memo(tmp_conn, make_memo(
        slug="push-2", content="<p>焦虑是自由的眩晕</p>",
        created_at=1700000000000, updated_at=1700000000000,
    ))

    calls = _run_push(tmp_conn, monkeypatch)

    ddl = [c for c in calls if "DROP TABLE" in c or "CREATE TABLE" in c]
    inserts = [c for c in calls if "INSERT INTO" in c]

    assert any("DROP TABLE IF EXISTS daily_reviews" in c for c in ddl)
    create = [c for c in ddl if "CREATE TABLE" in c][0]
    # New frequency-rotation columns present; no scheduling columns
    assert "served_count" in create
    assert "due_at" not in create
    assert "interval_days" not in create

    # Batch insert: both memos in a single VALUES (...) multi-row statement
    assert len(inserts) == 1
    batch = inserts[0]
    assert "'push-1'" in batch
    assert "'push-2'" in batch
    # Tags stripped, no raw HTML
    assert "<p>" not in batch
    assert "#效率" not in batch
    assert "两分钟法则" in batch
    # served_count starts at 0
    assert ",0," in batch


def test_review_push_dedupes_and_filters_empty(tmp_conn, monkeypatch):
    """Near-duplicate memos collapse to one; empty content is skipped."""
    _upsert_memo(tmp_conn, make_memo(
        slug="d-1", content="<p>焦虑是自由的眩晕。</p>",
        created_at=1700000000000, updated_at=1700000000000,
    ))
    _upsert_memo(tmp_conn, make_memo(
        slug="d-2", content="<p>「焦虑是自由的眩晕。」</p>",
        created_at=1700000000000, updated_at=1700000000000,
    ))
    _upsert_memo(tmp_conn, make_memo(
        slug="d-3", content="<p>#只有标签</p>",
        created_at=1700000000000, updated_at=1700000000000,
    ))

    calls = _run_push(tmp_conn, monkeypatch)
    inserts = [c for c in calls if "INSERT INTO" in c]
    assert len(inserts) == 1
    batch = inserts[0]
    # d-1 and d-2 are near-dupes → the longer variant (d-2, quoted) survives;
    # d-3 cleaned to empty → skipped
    assert "'d-1'" not in batch
    assert "'d-2'" in batch
    assert "'d-3'" not in batch
