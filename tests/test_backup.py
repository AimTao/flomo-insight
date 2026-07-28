"""Tests for D1 backup via wrangler CLI (mocked subprocess)."""

from __future__ import annotations

import json
import unittest.mock
import pytest
import subprocess

from src.backup.d1 import (
    backup_to_d1, _run_wrangler, D1BackupError,
    _escape_sql_value, _get_latest_backed_up_at, _create_schema,
)
from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


DB_ID = "test-db-uuid"


@pytest.fixture
def memos_db(tmp_conn):
    for i in range(5):
        _upsert_memo(tmp_conn, make_memo(
            slug=f"bk-{i}", content=f"content {i}",
            created_at=1700000000000 + i, updated_at=1700000000000 + i,
        ))
    return tmp_conn


# ── _escape_sql_value ────────────────────────────────────────────────────────

def test_escape_quotes():
    assert _escape_sql_value("it's") == "it''s"


# ── _run_wrangler ────────────────────────────────────────────────────────────

def test_run_wrangler_success():
    result = unittest.mock.MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = 0
    result.stdout = json.dumps([{"results": [{"m": "2024-01-01"}]}])
    with unittest.mock.patch("subprocess.run", return_value=result):
        rows = _run_wrangler(DB_ID, "SELECT 1")
        assert rows[0]["results"][0]["m"] == "2024-01-01"


def test_run_wrangler_failure():
    result = unittest.mock.MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = 1
    result.stderr = "some wrangler error"
    with unittest.mock.patch("subprocess.run", return_value=result):
        with pytest.raises(D1BackupError, match="wrangler failed"):
            _run_wrangler(DB_ID, "SELECT 1")


def test_run_wrangler_timeout():
    with unittest.mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
        with pytest.raises(D1BackupError, match="timed out"):
            _run_wrangler(DB_ID, "SELECT 1")


# ── backup_to_d1 ─────────────────────────────────────────────────────────────

def test_backup_creates_schema_then_inserts(memos_db):
    calls = []

    def fake_run(db_id, sql):
        calls.append({
            "db_id": db_id,
            "is_create": "CREATE TABLE" in sql,
            "is_select": "SELECT MAX" in sql,
            "is_insert": "INSERT" in sql,
        })
        if "SELECT MAX" in sql:
            return [{"results": [{"m": None}]}]  # no existing data
        return [{"results": []}]

    with unittest.mock.patch("src.backup.d1._run_wrangler", side_effect=fake_run):
        with unittest.mock.patch("src.backup.d1.time.sleep"):
            result = backup_to_d1(memos_db, DB_ID, batch_size=50)

    assert result["backed_up"] == 5
    assert result["total"] == 5
    assert calls[0]["is_create"]
    assert calls[1]["is_select"]
    assert calls[2]["is_insert"]


def test_backup_skips_if_nothing_new(memos_db):
    """All memos already in D1 → backs up 0."""
    def fake_run(db_id, sql):
        if "SELECT MAX" in sql:
            return [{"results": [{"m": "2099-01-01T00:00:00+00:00"}]}]
        return [{"results": []}]

    with unittest.mock.patch("src.backup.d1._run_wrangler", side_effect=fake_run):
        result = backup_to_d1(memos_db, DB_ID, batch_size=50)

    assert result["backed_up"] == 0
    assert result["total"] == 0


def test_backup_batches_large_sets(tmp_conn):
    """12 memos with batch_size=5 → 3 INSERT calls."""
    for i in range(12):
        _upsert_memo(tmp_conn, make_memo(
            slug=f"b-{i}", content=f"c{i}",
            created_at=1700000000000 + i, updated_at=1700000000000 + i,
        ))

    insert_calls = 0

    def fake_run(db_id, sql):
        nonlocal insert_calls
        if "INSERT" in sql:
            insert_calls += 1
        if "SELECT MAX" in sql:
            return [{"results": [{"m": None}]}]
        return [{"results": []}]

    with unittest.mock.patch("src.backup.d1._run_wrangler", side_effect=fake_run):
        with unittest.mock.patch("src.backup.d1.time.sleep"):
            result = backup_to_d1(tmp_conn, DB_ID, batch_size=5)

    assert result["backed_up"] == 12
    assert insert_calls == 3
