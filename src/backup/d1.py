"""Cloudflare D1 backup — push flomo memos via wrangler CLI.

Uses `npx wrangler d1 execute` which reads the macOS Keychain OAuth token.
No API token needed — just configure the database ID in config.toml.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from typing import Any


CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memos (
    slug TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'flomo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    backed_up_at TEXT NOT NULL
);
"""


class D1BackupError(Exception):
    pass


def _run_wrangler(database_id: str, sql: str) -> list[dict[str, Any]]:
    """Execute a SQL statement on D1 via wrangler CLI. Returns list of result rows."""
    cmd = [
        "npx", "wrangler", "d1", "execute", database_id,
        "--remote", "--command", sql, "--json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise D1BackupError("wrangler d1 execute timed out after 60s")
    except FileNotFoundError:
        raise D1BackupError(
            "npx not found. Install Node.js: https://nodejs.org"
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise D1BackupError(f"wrangler failed: {stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise D1BackupError(f"wrangler returned non-JSON: {result.stdout[:200]}")

    if isinstance(data, list):
        return data
    # Single result object
    return [data]


def _get_latest_backed_up_at(database_id: str) -> str:
    """Get the max updated_at currently in D1."""
    rows = _run_wrangler(database_id, "SELECT MAX(updated_at) AS m FROM memos")
    if rows:
        results = rows[0].get("results", [])
        if results and results[0].get("m"):
            return results[0]["m"]
    return ""


def _create_schema(database_id: str) -> None:
    _run_wrangler(database_id, CREATE_SCHEMA_SQL)


def _escape_sql_value(v: str) -> str:
    """Escape a string for safe embedding in SQL. Single quotes only."""
    return v.replace("'", "''")


def backup_to_d1(
    conn: sqlite3.Connection,
    database_id: str,
    batch_size: int = 50,
) -> dict[str, int]:
    """Backup all memos (incremental) to D1 via wrangler CLI.

    Args:
        conn: Local SQLite connection.
        database_id: D1 database UUID.
        batch_size: Memos per batch.

    Returns: {"backed_up": int, "total": int}
    """
    _create_schema(database_id)

    latest = _get_latest_backed_up_at(database_id)
    if latest:
        rows = conn.execute(
            "SELECT slug, content, source, created_at, updated_at FROM memos "
            "WHERE updated_at > ? ORDER BY updated_at",
            (latest,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT slug, content, source, created_at, updated_at FROM memos ORDER BY updated_at"
        ).fetchall()

    total = len(rows)
    backed_up = 0
    for i in range(0, total, batch_size):
        batch = rows[i : i + batch_size]
        now = str(int(time.time()))

        # Build a multi-row INSERT ... ON CONFLICT
        values_parts = []
        for r in batch:
            slug = _escape_sql_value(r["slug"])
            content = _escape_sql_value(r["content"])
            source = _escape_sql_value(r["source"])
            created = _escape_sql_value(r["created_at"])
            updated = _escape_sql_value(r["updated_at"])
            values_parts.append(
                f"('{slug}','{content}','{source}','{created}','{updated}','{now}')"
            )

        sql = (
            "INSERT INTO memos (slug, content, source, created_at, updated_at, backed_up_at) "
            f"VALUES {','.join(values_parts)} "
            "ON CONFLICT(slug) DO UPDATE SET "
            "content=excluded.content, source=excluded.source, "
            "updated_at=excluded.updated_at, backed_up_at=excluded.backed_up_at"
        )
        _run_wrangler(database_id, sql)
        backed_up += len(batch)
        time.sleep(0.5)

    return {"backed_up": backed_up, "total": total}
