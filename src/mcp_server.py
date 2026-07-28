"""FastMCP server — 9 MCP tools for Claude Code integration.

Launched via `flomo mcp`. Configure in Claude Code:
{
  "mcpServers": {
    "flomo": {
      "command": "uv",
      "args": ["run", "flomo", "mcp"],
      "cwd": "/path/to/flomo-insight"
    }
  }
}
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from src.config import load_config, require_token
from src.db import DatabaseManager

mcp = FastMCP(name="flomo-insight")


def _get_db() -> DatabaseManager:
    return DatabaseManager(load_config().db_path)


# ── Search ───────────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_search(query: str, tags: Optional[list[str]] = None, limit: int = 20, offset: int = 0) -> dict:
    """Search flomo memos by full-text query and optional tag filter."""
    from src.search.engine import search
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        hits, total = search(conn, query, tags=tags, limit=limit, offset=offset)
        return {"total": total, "results": [
            {"slug": h.slug, "content_snippet": h.snippet, "tags": h.tags, "created_at": h.created_at}
            for h in hits
        ]}
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_create(content: str, tags: Optional[list[str]] = None, source: str = "mcp") -> dict:
    """Create a new flomo memo (synced to cloud). Tags get # prefix automatically."""
    from src.api.client import FlomoClient
    with FlomoClient(require_token()) as client:
        result = client.create_memo(content, tags=tags, source=source)
        return {"slug": result.get("data", {}).get("slug", ""), "content": content, "tags": tags or [], "status": "created"}


# ── Sync ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_sync(full: bool = False) -> dict:
    """Sync memos from flomo API to local database."""
    from src.sync.exporter import sync
    from src.api.client import FlomoClient
    db = _get_db()
    with FlomoClient(require_token()) as client:
        result = sync(client, db, full=full, show_progress=False)
    return {"new": result.new, "updated": result.updated, "total": result.total, "last_sync_at": "now"}


# ── Insight (11 types, all LLM-driven) ───────────────────────────────────────

@mcp.tool()
def flomo_insight(insight_type: str = "topics") -> str:
    """Fetch notes + system prompt for Claude Code to analyze. 11 insight types.

    Analytical: topics, stagnant, declining, connections, draft
    Perspectives: default, value-clarification, inversion, second-order, cbt, mbti

    HOW: Call flomo_insight(type), read the returned prompt+notes,
    then generate a thoughtful Chinese insight analysis.
    No pre-analysis required — reads raw notes directly.
    """
    from src.insight.engine import generate_insight
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        return generate_insight(conn, insight_type=insight_type)
    finally:
        conn.close()


# ── Recent ───────────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_recent(limit: int = 20) -> list[dict]:
    """Get the most recent memos."""
    from src.search.engine import recent_memos
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        hits = recent_memos(conn, limit=limit)
        return [{"slug": h.slug, "content": h.content[:300], "tags": h.tags, "created_at": h.created_at} for h in hits]
    finally:
        conn.close()


# ── Tags ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_tags(sort_by: str = "count", limit: int = 50) -> list[dict]:
    """List tags with memo counts."""
    from src.search.engine import get_tags
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        return get_tags(conn, sort_by=sort_by, limit=limit)
    finally:
        conn.close()


# ── WeRead Import ────────────────────────────────────────────────────────────

@mcp.tool()
def flomo_import_weread(batch_size: int = 15) -> str:
    """Fetch reviewed highlights from WeRead Skills API + return prompt for Claude."""
    from src.config import require_weread_key
    from src.importers.weread import WereadClient, fetch_reviewed_highlights, build_import_prompt
    key = require_weread_key()
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        with WereadClient(key) as client:
            items = fetch_reviewed_highlights(client, db_conn, batch_size=batch_size)
        return build_import_prompt(items)
    finally:
        db_conn.close()


@mcp.tool()
def flomo_weread_mark_imported(review_id: str, book_id: str, book_title: str, mark_text: str, flomo_slug: str = "") -> dict:
    """Mark a WeRead highlight as imported (dedup). Call AFTER flomo_create()."""
    from src.importers.weread import mark_imported
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        mark_imported(db_conn, review_id, book_id, book_title, mark_text, flomo_slug)
        return {"status": "marked", "review_id": review_id}
    finally:
        db_conn.close()


@mcp.tool()
def flomo_weread_stats() -> dict:
    """WeRead import stats — total highlights and per-book breakdown."""
    from src.importers.weread import build_weread_stats
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        return build_weread_stats(db_conn)
    finally:
        db_conn.close()


# ── Runner ───────────────────────────────────────────────────────────────────

def run_mcp():
    mcp.run(transport="stdio")
