"""Cloudflare D1 backup — push flomo memos to a D1 database.

D1 is Cloudflare's serverless SQLite. We use the REST API to upsert memos.
Incremental: only pushes memos with updated_at > last backed-up timestamp.

Setup:
  1. Create a D1 database: wrangler d1 create flomo-backup
  2. Run the schema (see create_schema_sql below) via wrangler d1 execute
  3. Set in config.toml:
       d1_account_id = "..."
       d1_database_id = "..."
       d1_api_token = "..."  (Cloudflare API token with D1 edit permission)
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import httpx

D1_API_BASE = "https://api.cloudflare.com/client/v4"
TIMEOUT = 60.0


# D1 schema for the backup table
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


class D1Backup:
    """Push memos to Cloudflare D1 via REST API."""

    def __init__(self, account_id: str, database_id: str, api_token: str) -> None:
        self.account_id = account_id
        self.database_id = database_id
        self._client = httpx.Client(
            base_url=D1_API_BASE,
            timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {api_token}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "D1Backup":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _query(self, sql: str, params: list[Any] | None = None) -> dict[str, Any]:
        """Execute a SQL query on D1. Returns the raw API response."""
        url = f"/accounts/{self.account_id}/d1/database/{self.database_id}/query"
        body: dict[str, Any] = {"sql": sql}
        if params:
            body["params"] = [str(p) if not isinstance(p, (int, float, bool)) else p for p in params]
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            raise D1BackupError(f"D1 query failed: {errors}")
        return data

    def create_schema(self) -> None:
        """Create the memos table in D1 if it doesn't exist."""
        self._query(CREATE_SCHEMA_SQL)

    def upsert_memo(self, slug: str, content: str, source: str,
                    created_at: str, updated_at: str) -> None:
        """Upsert a single memo into D1."""
        sql = """
        INSERT INTO memos (slug, content, source, created_at, updated_at, backed_up_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            content=excluded.content,
            source=excluded.source,
            updated_at=excluded.updated_at,
            backed_up_at=excluded.backed_up_at
        """
        now = str(int(time.time()))
        self._query(sql, [slug, content, source, created_at, updated_at, now])

    def get_latest_backed_up_at(self) -> str:
        """Get the max updated_at currently in D1 (for incremental backup)."""
        data = self._query("SELECT MAX(updated_at) AS m FROM memos")
        result = data.get("result", [])
        if result and result[0].get("results"):
            row = result[0]["results"][0]
            return row.get("m") or ""
        return ""


class D1BackupError(Exception):
    pass


def backup_to_d1(
    conn: sqlite3.Connection,
    d1: D1Backup,
    batch_size: int = 50,
) -> dict[str, int]:
    """Backup all memos (incremental) to D1.

    Args:
        conn: Local SQLite connection.
        d1: Authenticated D1Backup client.
        batch_size: Memos per D1 batch (D1 has query size limits).

    Returns: {"backed_up": int, "total": int}
    """
    d1.create_schema()

    # Incremental: only memos newer than what's in D1
    latest = d1.get_latest_backed_up_at()
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
        placeholders = ",".join(["(?, ?, ?, ?, ?, ?)"] * len(batch))
        sql = f"""
        INSERT INTO memos (slug, content, source, created_at, updated_at, backed_up_at)
        VALUES {placeholders}
        ON CONFLICT(slug) DO UPDATE SET
            content=excluded.content,
            source=excluded.source,
            updated_at=excluded.updated_at,
            backed_up_at=excluded.backed_up_at
        """
        params: list[Any] = []
        for r in batch:
            params.extend([r["slug"], r["content"], r["source"], r["created_at"], r["updated_at"], now])

        d1._query(sql, params)
        backed_up += len(batch)
        time.sleep(0.5)  # D1 rate limit friendliness

    return {"backed_up": backed_up, "total": total}
