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
    tags TEXT NOT NULL DEFAULT '',
    source TEXT DEFAULT 'flomo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    backed_up_at TEXT NOT NULL
);
"""

# Re-push rows within this window of the D1 watermark to tolerate clock skew
# and out-of-order updated_at values. Upserts are idempotent.
BACKUP_LOOKBACK_SECONDS = 86400


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


def _load_slug_tags(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """slug → tag names from local memo_tags (same set as SQLite)."""
    rows = conn.execute(
        """
        SELECT mt.memo_slug, t.name FROM memo_tags mt
        JOIN tags t ON t.id = mt.tag_id
        """
    ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["memo_slug"], []).append(r["name"])
    return out


def _format_tags_column(tags: list[str] | None) -> str:
    """Comma-separated tag names, matching local tag vocabulary."""
    return ",".join(tags or [])


def _apply_lookback(watermark: str, lookback_seconds: int = BACKUP_LOOKBACK_SECONDS) -> str:
    """Shift an ISO watermark backwards so near-boundary rows are re-upserted."""
    if not watermark:
        return watermark
    try:
        from datetime import datetime, timedelta, timezone

        dt = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - timedelta(seconds=lookback_seconds)).isoformat()
    except ValueError:
        return watermark


def backup_to_d1(
    conn: sqlite3.Connection,
    database_id: str,
    batch_size: int = 50,
) -> dict[str, int]:
    """Backup all memos (incremental) to D1 via wrangler CLI.

    Pushes content + tags (from local memo_tags). Schema is latest-only;
    if D1 still has an old memos table without `tags`, DROP it once then re-run.

    Incremental uses MAX(updated_at) minus BACKUP_LOOKBACK_SECONDS so
    clock skew / slight out-of-order updates still get re-upserted.

    Args:
        conn: Local SQLite connection.
        database_id: D1 database UUID.
        batch_size: Memos per batch.

    Returns: {"backed_up": int, "total": int}
    """
    _create_schema(database_id)

    latest = _get_latest_backed_up_at(database_id)
    if latest:
        cutoff = _apply_lookback(latest)
        rows = conn.execute(
            "SELECT slug, content, source, created_at, updated_at FROM memos "
            "WHERE updated_at > ? ORDER BY updated_at",
            (cutoff,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT slug, content, source, created_at, updated_at FROM memos ORDER BY updated_at"
        ).fetchall()

    slug_tags = _load_slug_tags(conn)
    total = len(rows)
    backed_up = 0
    for i in range(0, total, batch_size):
        batch = rows[i : i + batch_size]
        now = str(int(time.time()))

        values_parts = []
        for r in batch:
            slug = _escape_sql_value(r["slug"])
            content = _escape_sql_value(r["content"])
            tags = _escape_sql_value(_format_tags_column(slug_tags.get(r["slug"])))
            source = _escape_sql_value(r["source"])
            created = _escape_sql_value(r["created_at"])
            updated = _escape_sql_value(r["updated_at"])
            values_parts.append(
                f"('{slug}','{content}','{tags}','{source}','{created}','{updated}','{now}')"
            )

        sql = (
            "INSERT INTO memos (slug, content, tags, source, created_at, updated_at, backed_up_at) "
            f"VALUES {','.join(values_parts)} "
            "ON CONFLICT(slug) DO UPDATE SET "
            "content=excluded.content, tags=excluded.tags, source=excluded.source, "
            "updated_at=excluded.updated_at, backed_up_at=excluded.backed_up_at"
        )
        _run_wrangler(database_id, sql)
        backed_up += len(batch)
        time.sleep(0.5)

    return {"backed_up": backed_up, "total": total}
