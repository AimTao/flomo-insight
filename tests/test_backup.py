"""Tests for D1 backup — mocked HTTP, no real Cloudflare calls."""

from __future__ import annotations

import unittest.mock
import pytest
import httpx
from unittest.mock import MagicMock

from src.backup.d1 import D1Backup, D1BackupError, backup_to_d1, CREATE_SCHEMA_SQL
from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


@pytest.fixture
def memos_db(tmp_conn):
    """DB with a few memos to back up."""
    for i in range(5):
        _upsert_memo(tmp_conn, make_memo(
            slug=f"bk-{i}", content=f"content {i}",
            created_at=1700000000000 + i, updated_at=1700000000000 + i,
        ))
    return tmp_conn


def _mock_d1():
    """Mock D1Backup that records queries and returns canned responses."""
    d1 = MagicMock(spec=D1Backup)
    d1.queries = []

    def _query(sql, params=None):
        d1.queries.append({"sql": sql, "params": params})
        # If it's the MAX(updated_at) query, return empty (first backup)
        if "MAX" in sql.upper():
            return {"result": [{"results": [{"m": None}]}]}
        return {"result": [{"results": []}]}

    d1._query = _query
    d1.create_schema = MagicMock()
    d1.get_latest_backed_up_at = MagicMock(return_value="")
    return d1


def test_backup_pushes_all_memos_first_run(memos_db):
    """First backup (no D1 data) pushes all memos."""
    d1 = _mock_d1()
    result = backup_to_d1(memos_db, d1, batch_size=50)

    assert result["backed_up"] == 5
    assert result["total"] == 5
    # One insert query with all 5 memos
    insert_queries = [q for q in d1.queries if "INSERT" in q["sql"]]
    assert len(insert_queries) == 1
    # 5 memos × 6 params each = 30 params
    assert len(insert_queries[0]["params"]) == 30


def test_backup_incremental(memos_db):
    """Second backup with cursor only pushes newer memos."""
    d1 = _mock_d1()
    # Set cursor to the latest memo's updated_at — nothing newer exists
    d1.get_latest_backed_up_at = MagicMock(return_value="2023-11-14T22:13:20.004000+00:00")

    result = backup_to_d1(memos_db, d1, batch_size=50)
    assert result["total"] == 0
    assert result["backed_up"] == 0


def test_backup_batches_large_sets(tmp_conn):
    """More memos than batch_size → multiple INSERT queries."""
    for i in range(12):
        _upsert_memo(tmp_conn, make_memo(
            slug=f"b-{i}", content=f"c{i}",
            created_at=1700000000000 + i, updated_at=1700000000000 + i,
        ))
    d1 = _mock_d1()
    result = backup_to_d1(tmp_conn, d1, batch_size=5)

    assert result["backed_up"] == 12
    insert_queries = [q for q in d1.queries if "INSERT" in q["sql"]]
    # 12 memos / 5 per batch = 3 batches
    assert len(insert_queries) == 3


def test_backup_calls_create_schema(memos_db):
    """create_schema is called on every backup (idempotent IF NOT EXISTS)."""
    d1 = _mock_d1()
    backup_to_d1(memos_db, d1, batch_size=50)
    d1.create_schema.assert_called_once()


def test_d1_query_raises_on_failure():
    """D1 API returning success=false raises D1BackupError."""
    d1 = D1Backup("acct", "db", "token")
    # Mock the httpx client to return a failure response
    fail_resp = httpx.Response(
        200, json={"success": False, "errors": [{"message": "bad sql"}]},
        request=httpx.Request("POST", "https://api.cloudflare.com/x"),
    )
    with unittest.mock.patch.object(d1._client, "post", return_value=fail_resp):
        with pytest.raises(D1BackupError, match="D1 query failed"):
            d1._query("SELECT 1")
    d1.close()


def test_d1_get_latest_backed_up_at_parses_response():
    """get_latest_backed_up_at extracts MAX(updated_at) from D1 response."""
    d1 = D1Backup("acct", "db", "token")
    resp = httpx.Response(
        200, json={"success": True, "result": [{"results": [{"m": "2024-01-01T00:00:00+00:00"}]}]},
        request=httpx.Request("POST", "https://api.cloudflare.com/x"),
    )
    with unittest.mock.patch.object(d1._client, "post", return_value=resp):
        latest = d1.get_latest_backed_up_at()
    assert latest == "2024-01-01T00:00:00+00:00"
    d1.close()
