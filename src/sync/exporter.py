"""Paginated memo export from flomo API into local SQLite."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from src.db import DatabaseManager
from src.api.client import FlomoClient, FlomoAPIError


@dataclass
class SyncResult:
    new: int = 0
    updated: int = 0
    total: int = 0
    errors: list[str] = field(default_factory=list)


def sync(client: FlomoClient, db: DatabaseManager, full: bool = False, show_progress: bool = True) -> SyncResult:
    """Pull memos from flomo and upsert into the local database.

    Args:
        client: Authenticated flomo HTTP client.
        db: Database manager for the local SQLite store.
        full: If True, re-sync everything from the beginning.
        show_progress: If True, display a rich progress bar.
    """
    result = SyncResult()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        # Determine starting cursor
        latest_slug: str | None = None
        latest_updated_at: str | None = None

        if not full:
            row = conn.execute("SELECT value FROM sync_state WHERE key = 'latest_slug'").fetchone()
            if row:
                latest_slug = row["value"]
            row = conn.execute("SELECT value FROM sync_state WHERE key = 'latest_updated_at'").fetchone()
            if row:
                latest_updated_at = row["value"]

        total_before = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]

        page = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("({task.completed} memos)"),
            TimeElapsedColumn(),
            disable=not show_progress,
        ) as progress:
            task = progress.add_task("[cyan]Syncing memos...", total=None)

            while True:
                try:
                    data = client.get_updated(
                        limit=200,
                        latest_slug=latest_slug,
                        latest_updated_at=latest_updated_at,
                    )
                except FlomoAPIError as e:
                    result.errors.append(f"API error on page {page}: {e}")
                    break

                memos = data.get("data", [])
                if not memos:
                    break

                for memo in memos:
                    _upsert_memo(conn, memo)

                page += 1
                progress.update(task, completed=result.total)

                # Always advance cursor from the last memo of this page
                last = memos[-1]
                latest_slug = last.get("slug")
                latest_updated_at = str(last.get("updated_at", ""))
                _update_sync_state(conn, latest_slug, latest_updated_at)

                # If fewer than limit, we've reached the end
                if len(memos) < 200:
                    break

                # Rate limiting — 1-1.5s between API calls to avoid limits
                time.sleep(1.0 + 0.5 * (page % 3 == 0))

        # Final sync state
        total_after = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
        result.total = total_after
        result.new = total_after - total_before

        _update_sync_state(conn, latest_slug, latest_updated_at)
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
            ("last_sync_at", str(int(time.time()))),
        )
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
            ("total_memos", str(result.total)),
        )
        conn.commit()

    finally:
        conn.close()

    return result


def _upsert_memo(conn: Any, memo: dict[str, Any]) -> None:
    """Insert or update a single memo and its tags."""
    slug = memo.get("slug", "")
    content = memo.get("content", "")
    raw = memo.get("raw_content") or content
    source = memo.get("source", "flomo")
    created_at = _ts_to_iso(memo.get("created_at"))
    updated_at = _ts_to_iso(memo.get("updated_at"))

    # Check if this memo exists and whether the content changed
    existing = conn.execute(
        "SELECT content, updated_at FROM memos WHERE slug = ?", (slug,)
    ).fetchone()

    if existing:
        if existing["updated_at"] == updated_at:
            return  # unchanged
        conn.execute(
            """UPDATE memos SET content=?, raw_content=?, source=?, updated_at=?,
               synced_at=datetime('now')
               WHERE slug=?""",
            (content, raw, source, updated_at, slug),
        )
        conn.execute("DELETE FROM memo_tags WHERE memo_slug = ?", (slug,))
    else:
        conn.execute(
            """INSERT INTO memos (slug, content, raw_content, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (slug, content, raw, source, created_at, updated_at),
        )

    # Parse and insert tags
    tag_names = _parse_tags_from_memo(memo)
    for tag_name in tag_names:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if tag_row:
            conn.execute(
                "INSERT OR IGNORE INTO memo_tags (memo_slug, tag_id) VALUES (?, ?)",
                (slug, tag_row["id"]),
            )


def _parse_tags_from_memo(memo: dict[str, Any]) -> list[str]:
    """Extract tag names from a memo's tag list or from content."""
    tags = memo.get("tags", [])
    if tags:
        result = []
        for t in tags:
            if isinstance(t, dict):
                name = t.get("name", "")
                if name:
                    result.append(name)
            elif isinstance(t, str):
                result.append(t)
        if result:
            return result

    # Fallback: parse #tags from content
    content = memo.get("content", "")
    import re
    raw_tags = re.findall(r"#([^\s<#]+)", content)
    # strip trailing punctuation/HTML that may cling to the tag
    return [t.rstrip("</p>.,;:!?，。；：！？") for t in raw_tags if t]


def _ts_to_iso(ts: Any) -> str:
    """Convert a flomo timestamp (ms epoch or string) to ISO 8601."""
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    return str(ts)


def _update_sync_state(conn: Any, slug: str | None, updated_at: str | None) -> None:
    """Persist the current sync cursor."""
    if slug:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
            ("latest_slug", slug),
        )
    if updated_at:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
            ("latest_updated_at", updated_at),
        )
