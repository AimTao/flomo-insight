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


# ── Review (two-phase: overview → deep-dive) ──────────────────────────────────

@mcp.tool()
def flomo_review_candidates() -> dict:
    """Phase 1: Return overview of ALL candidate memo pools (no full content).

    Returns all pools across 4 strategies: same_book, tag_cluster, near_time, co_tag.
    Each pool has: label, total_memos, content_samples (first ~80 chars),
    and tag_distribution.

    Claude should scan the landscape and pick promising pools using
    flomo_review_pool(strategy, label) to get full content for deep-dive.

    No SQL filtering — every book/tag/date/tag-pair is included.
    LLM decides what's worth exploring.
    """
    from src.review.engine import get_overview
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        return get_overview(conn)
    finally:
        conn.close()


@mcp.tool()
def flomo_review_pool(strategy: str, label: str) -> dict | None:
    """Phase 2: Return ALL complete notes for one specific candidate pool.

    Args:
        strategy: same_book | tag_cluster | near_time | co_tag
        label: exact label from flomo_review_candidates (book title, tag name,
               date string, or "A × B" for co-tag pairs)

    Returns:
        {label, total_memos, notes: [{slug, content, tags, date, source}]}
        Content is NEVER truncated — full memo text.

    Call this AFTER scanning flomo_review_candidates to deep-dive into
    pools that look promising for grouping and review writing.
    """
    from src.review.engine import get_pool
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        return get_pool(conn, strategy, label)
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
    """Fetch reviewed highlights from WeRead + return prompt with fixed taxonomy.

    LLM picks tags from the predefined classification system (not free-form).
    Includes both highlight text and your personal review for each item.
    """
    from src.config import require_weread_key
    from src.importers.weread import WereadClient, fetch_reviewed_highlights
    from src.tags.classifier import build_wearead_import_prompt
    key = require_weread_key()
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        with WereadClient(key) as client:
            items = fetch_reviewed_highlights(client, db_conn, batch_size=batch_size)
        return build_wearead_import_prompt(items)
    finally:
        db_conn.close()


@mcp.tool()
def flomo_import_weread_auto(batch_size: int = 15, tag: str = "") -> dict:
    """Automatically import WeRead reviewed highlights to flomo, one by one.

    No LLM tagging — applies only #微信读书 (+ optional extra tag).
    For smart LLM-based classification, use flomo_import_weread instead.

    Args:
        batch_size: How many highlights to import in this run.
        tag: Optional extra tag to add to every imported memo (besides 微信读书).

    Returns: {"imported": int, "skipped": int, "errors": list[str]}
    """
    from src.config import require_weread_key
    from src.importers.weread import WereadClient, auto_import
    from src.api.client import FlomoClient

    weread_key = require_weread_key()
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    extra_tag = [tag] if tag else None
    classifier = (lambda text, title: extra_tag) if extra_tag else None

    try:
        with WereadClient(weread_key) as wclient, FlomoClient(require_token()) as fclient:
            return auto_import(wclient, fclient, db_conn, batch_size=batch_size, classifier=classifier)
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


# ── Tag Management ───────────────────────────────────────────────────────────


@mcp.tool()
def flomo_tags_taxonomy() -> dict:
    """Return the fixed tag classification system used for all tagging.

    LLM must pick tags from this closed set. No free-form tag invention.
    Keyed by domain with per-domain tag lists.
    """
    from src.tags.taxonomy import all_tags
    return all_tags()


@mcp.tool()
def flomo_retag(batch_size: int = 10, source: str = "") -> str:
    """Fetch memos + current tags + taxonomy for LLM-driven retagging.

    Returns a prompt containing:
    - The fixed tag taxonomy (closed set — only these are valid)
    - Memos with their current tags
    - Instructions for Claude to assign proper taxonomy tags

    HOW: Call flomo_retag, read each memo, call flomo_tag_update(slug, tags)
    to set new tags. Tags MUST come from flomo_tags_taxonomy.

    Args:
        batch_size: Memos to process this round.
        source: Filter by source ('flomo' = original notes, 'weread' = weRead,
                '' = all).
    """
    from src.tags.classifier import build_retag_prompt
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        return build_retag_prompt(db_conn, batch_size=batch_size,
                                  source=source if source else None)
    finally:
        db_conn.close()


@mcp.tool()
def flomo_tag_update(slug: str, tags: list[str]) -> dict:
    """Replace all tags on a memo with the given list.

    This removes existing tags and sets exactly the provided tags.
    Use after flomo_retag() to apply LLM-chosen tags.

    Args:
        slug: Memo slug (shown in retag prompt as [slug_short]).
        tags: New tag list, e.g. ["效率", "习惯"]. No # prefix needed.

    Returns: {"slug": ..., "tags": [...], "status": "updated"}
    """
    from src.tags.classifier import update_memo_tags
    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)
    try:
        update_memo_tags(db_conn, slug, tags)
        return {"slug": slug, "tags": tags, "status": "updated"}
    finally:
        db_conn.close()


# ── Runner ───────────────────────────────────────────────────────────────────

def run_mcp():
    mcp.run(transport="stdio")
