"""FTS5 full-text search engine for flomo memos."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass
class SearchHit:
    slug: str
    content: str
    snippet: str
    tags: list[str]
    created_at: str
    updated_at: str


def search(
    conn: sqlite3.Connection,
    query: str,
    tags: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[SearchHit], int]:
    """Search memos by full-text query and optional tag filter.

    Returns (hits, total_count).
    """
    safe_query = _escape_fts5(query)
    if not safe_query:
        return [], 0
    # Quote phrase when multi-token so hyphens never become FTS column filters
    if " " in safe_query:
        fts_query = f'"{safe_query}"'
    else:
        fts_query = f'"{safe_query}"*'

    if tags:
        return _search_with_tags(conn, fts_query, tags, limit, offset)
    else:
        return _search_fts_only(conn, fts_query, limit, offset)


def _escape_fts5(query: str) -> str:
    """Make a user string safe for FTS5 MATCH.

    Strips FTS operators and turns hyphens/underscores into spaces so
    tokens like `flomo-insight` never parse as `column:token`.
    """
    import re

    cleaned = re.sub(r'["*^():{}\[\]]', " ", query)
    cleaned = re.sub(r"[-_]+", " ", cleaned)
    return " ".join(cleaned.split())


def _search_fts_only(
    conn: sqlite3.Connection, fts_query: str, limit: int, offset: int
) -> tuple[list[SearchHit], int]:
    """Search using only FTS5."""
    # Get total count
    count_row = conn.execute(
        "SELECT COUNT(*) FROM memos_fts WHERE memos_fts MATCH ?", (fts_query,)
    ).fetchone()
    total = count_row[0] if count_row else 0

    # Get results with snippets
    rows = conn.execute(
        """SELECT m.slug, m.content, m.created_at, m.updated_at,
                  snippet(memos_fts, 0, '<mark>', '</mark>', '...', 32) AS snippet
           FROM memos_fts
           JOIN memos m ON m.rowid = memos_fts.rowid
           WHERE memos_fts MATCH ?
           ORDER BY rank
           LIMIT ? OFFSET ?""",
        (fts_query, limit, offset),
    ).fetchall()

    hits = _rows_to_hits(conn, rows)
    return hits, total


def _search_with_tags(
    conn: sqlite3.Connection,
    fts_query: str,
    tags: list[str],
    limit: int,
    offset: int,
) -> tuple[list[SearchHit], int]:
    """Search with FTS5 AND tag intersection."""
    placeholders = ",".join("?" for _ in tags)
    tag_count = len(tags)

    # Memos that contain ALL requested tags
    tag_filter = f"""m.slug IN (
        SELECT memo_slug FROM memo_tags
        JOIN tags ON tags.id = memo_tags.tag_id
        WHERE tags.name IN ({placeholders})
        GROUP BY memo_slug
        HAVING COUNT(DISTINCT tags.name) = ?
    )"""

    params: list[Any] = [fts_query, *tags, tag_count]

    count_row = conn.execute(
        f"""SELECT COUNT(*) FROM memos_fts
            JOIN memos m ON m.rowid = memos_fts.rowid
            WHERE memos_fts MATCH ? AND {tag_filter}""",
        params,
    ).fetchone()
    total = count_row[0] if count_row else 0

    rows = conn.execute(
        f"""SELECT m.slug, m.content, m.created_at, m.updated_at,
                   snippet(memos_fts, 0, '<mark>', '</mark>', '...', 32) AS snippet
            FROM memos_fts
            JOIN memos m ON m.rowid = memos_fts.rowid
            WHERE memos_fts MATCH ? AND {tag_filter}
            ORDER BY rank
            LIMIT ? OFFSET ?""",
        [fts_query, *tags, tag_count, limit, offset],
    ).fetchall()

    hits = _rows_to_hits(conn, rows)
    return hits, total


def _rows_to_hits(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[SearchHit]:
    """Convert result rows to SearchHit objects with tags populated."""
    hits = []
    for row in rows:
        tag_rows = conn.execute(
            """SELECT t.name FROM tags t
               JOIN memo_tags mt ON mt.tag_id = t.id
               WHERE mt.memo_slug = ?""",
            (row["slug"],),
        ).fetchall()
        tag_names = [t["name"] for t in tag_rows]
        hits.append(
            SearchHit(
                slug=row["slug"],
                content=row["content"],
                snippet=row["snippet"] or row["content"][:200],
                tags=tag_names,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    return hits


def recent_memos(
    conn: sqlite3.Connection, limit: int = 20, offset: int = 0
) -> list[SearchHit]:
    """Get most recent memos."""
    rows = conn.execute(
        """SELECT slug, content, created_at, updated_at,
                  substr(content, 1, 300) AS snippet
           FROM memos ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return _rows_to_hits(conn, rows)


def get_tags(
    conn: sqlite3.Connection, sort_by: str = "count", limit: int = 50
) -> list[dict[str, Any]]:
    """List tags with memo counts."""
    order = "cnt DESC" if sort_by == "count" else "name ASC"
    rows = conn.execute(
        f"""SELECT t.name, COUNT(mt.memo_slug) AS cnt
            FROM tags t
            LEFT JOIN memo_tags mt ON mt.tag_id = t.id
            GROUP BY t.id
            ORDER BY {order}
            LIMIT ?""",
        (limit,),
    ).fetchall()
    return [{"name": row["name"], "count": row["cnt"]} for row in rows]


def db_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return quick database statistics."""
    total = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
    tags_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    last_sync = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'last_sync_at'"
    ).fetchone()

    from datetime import datetime

    return {
        "total_memos": total,
        "total_tags": tags_count,
        "last_sync": datetime.fromtimestamp(
            int(last_sync["value"])
        ).isoformat() if last_sync else "never",
    }


# Export the modules in __init__
__all__ = ["search", "recent_memos", "get_tags", "db_stats", "SearchHit"]
