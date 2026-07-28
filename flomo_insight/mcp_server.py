"""FastMCP server — exposes flomo operations as MCP tools for Claude Code.

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

Tools:
  flomo_search    — Full-text search + tag filter
  flomo_create    — Create memo (cloud + local)
  flomo_sync      — Incremental/full sync from flomo API
  flomo_analyze   — Run analysis pipeline
  flomo_insight   — LLM-driven insight (all types)
  flomo_recent    — Recent memos
  flomo_tags      — Tag list with counts
"""

from __future__ import annotations

import json
from typing import Optional

from fastmcp import FastMCP

from flomo_insight.config import load_config, default_db_path, require_token
from flomo_insight.db import DatabaseManager

mcp = FastMCP(name="flomo-insight")


def _get_db() -> DatabaseManager:
    cfg = load_config()
    return DatabaseManager(cfg.storage.db_path or default_db_path())


# ── Search ───────────────────────────────────────────────────────────────────


@mcp.tool()
def flomo_search(
    query: str,
    tags: Optional[list[str]] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search flomo memos by full-text query and optional tag filter.

    Args:
        query: Search keywords. Supports boolean operators (AND, OR).
        tags: Filter to memos that have ALL of these tags.
        limit: Max results to return.
        offset: Pagination offset.
    """
    from flomo_insight.search.engine import search

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        hits, total = search(conn, query, tags=tags, limit=limit, offset=offset)
        results = [
            {
                "slug": h.slug,
                "content_snippet": h.snippet,
                "tags": h.tags,
                "created_at": h.created_at,
            }
            for h in hits
        ]
        return {"total": total, "results": results}
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────────────


@mcp.tool()
def flomo_create(
    content: str, tags: Optional[list[str]] = None, source: str = "mcp"
) -> dict:
    """Create a new flomo memo (synced to flomo cloud + local database).

    Args:
        content: Memo content (markdown supported).
        tags: Tags to attach (without # prefix).
        source: Source identifier, defaults to 'mcp'.
    """
    from flomo_insight.api.client import FlomoClient

                    with FlomoClient(require_token()) as client:
        result = client.create_memo(content, tags=tags, source=source)
        slug = result.get("data", {}).get("slug", "")
        slug = result.get("data", {}).get("slug", "")
        return {
            "slug": slug,
            "content": content,
            "tags": tags or [],
            "status": "created",
        }


# ── Sync ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def flomo_sync(full: bool = False) -> dict:
    """Sync memos from flomo API to the local database.

    Args:
        full: If true, re-sync everything from scratch (otherwise incremental).
    """
    from flomo_insight.sync.exporter import sync
    from flomo_insight.api.client import FlomoClient

    db = _get_db()
            with FlomoClient(require_token()) as client:
        result = sync(client, db, full=full, show_progress=False)

    return {
        "new": result.new,
        "updated": result.updated,
        "total": result.total,
        "last_sync_at": "now",
    }


# ── Analyze ──────────────────────────────────────────────────────────────────


@mcp.tool()
def flomo_analyze(force: bool = False) -> dict:
    """Run the full analysis pipeline: embeddings, clustering, trends, keywords.

    This is a potentially slow operation. Run after syncing new data.
    Required before flomo_insight will work.

    Args:
        force: Recompute all embeddings from scratch (slow).
    """
    import warnings

    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        cfg = load_config()

        from flomo_insight.analysis.embeddings import compute_embeddings

        embedded = compute_embeddings(
            conn, model_name=cfg.analysis.embedding_model, force=force
        )

        from flomo_insight.analysis.clustering import cluster_memos
        from flomo_insight.analysis.keywords import extract_keywords_per_cluster

        n_clusters = cluster_memos(
            conn, min_cluster_size=cfg.analysis.cluster_min_size
        )
        extract_keywords_per_cluster(conn)

        from flomo_insight.analysis.trends import compute_trends

        compute_trends(conn)

        from flomo_insight.analysis.cooccurrence import compute_cooccurrence

        compute_cooccurrence(conn)

        clusters = conn.execute(
            "SELECT keywords, size FROM clusters WHERE cluster_label != -1 ORDER BY size DESC LIMIT 5"
        ).fetchall()
        top_topics = []
        for c in clusters:
            kws = json.loads(c["keywords"]) if c["keywords"] else []
            top_topics.append(", ".join(kws[:3]) if kws else "(untitled)")

        return {
            "clusters_found": n_clusters,
            "total_memos_analyzed": embedded,
            "top_topics": top_topics,
            "summary": f"Found {n_clusters} topic clusters from {embedded} memos.",
        }
    finally:
        conn.close()


# ── Insight (all types, LLM-driven) ──────────────────────────────────────────


@mcp.tool()
def flomo_insight(insight_type: str = "topics") -> str:
    """Generate an LLM-driven insight package from analyzed flomo data.

    This tool fetches relevant notes + statistics from your database,
    wraps them with a detailed system prompt, and returns the package for
    Claude Code to interpret. No hardcoded conclusions — you do the thinking.

    HOW TO USE: Call flomo_insight, read the returned prompt+notes carefully,
    then generate a thoughtful insight analysis in Chinese following the
    instructions embedded in the response.

    Args:
        insight_type: One of the following insight types:

        Analytical (notes + cluster data + prompt):
          topics      — Cluster analysis + representative notes. Find themes,
                        patterns, blind spots, and energy distribution.
          stagnant    — Ideas spanning 60+ days in the same cluster. Detect
                        thought loops and suggest what to do about them.
          declining   — Topics with negative monthly trend. Interpret what's
                        fading, whether to reclaim or let go.
          connections — Tag co-occurrence + bridge notes. Find surprising
                        cross-domain links hidden in your thinking.
          draft       — All notes from your largest topic. Design an article
                        structure with outline, gap analysis, and opening.

        Perspective lenses (notes + perspective system prompt):
          default              — Core themes, contradictions, blind spots,
                                 growth trajectory (by flomo)
          value-clarification  — Find what you truly value, from chaos to
                                 clarity (by shaonan)
          inversion            — Munger-style reverse thinking: what would
                                 ensure failure? (by flomo)
          second-order         — Find problems above problems through
                                 layered questioning (by shaonan)
          cbt                  — Cognitive distortion detection with
                                 reframing suggestions (by flomo)
          mbti                 — Infer personality type from writing
                                 patterns (by flomo)

    Returns markdown: system prompt + data section. You read and respond.
    """
    from flomo_insight.insight.engine import generate_insight

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
    """Get the most recent memos from the local database.

    Args:
        limit: Number of recent memos to return.
    """
    from flomo_insight.search.engine import recent_memos

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        hits = recent_memos(conn, limit=limit)
        return [
            {
                "slug": h.slug,
                "content": h.content[:300],
                "tags": h.tags,
                "created_at": h.created_at,
            }
            for h in hits
        ]
    finally:
        conn.close()


# ── Tags ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def flomo_tags(sort_by: str = "count", limit: int = 50) -> list[dict]:
    """List all tags with memo counts.

    Args:
        sort_by: 'count' (most used first) or 'name' (alphabetical).
        limit: Max tags to return.
    """
    from flomo_insight.search.engine import get_tags

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
    """Fetch reviewed highlights (划线+书评) from WeRead via the official Skills API.

    Only returns highlights that have personal reviews attached — your actual
    书评/想法 written after highlighting a passage.

    HOW TO USE:
    1. Call flomo_import_weread(batch_size=15) to get the next batch
    2. Read each item: it has both 划线 (highlight) AND 书评 (your review)
    3. For each item, call flomo_create() with:
       content:
         > 划线内容

         书评内容

         ——《书名》作者
       tags: MUST include "微信读书" plus 1-3 classification tags
    4. After each, call flomo_weread_mark_imported(review_id=..., ...)

    Args:
        batch_size: Number of reviewed highlights to fetch (max 30).

    Requires: WeRead API key from https://weread.qq.com/r/weread-skills
    Set via: flomo config set-weread-key wrk-xxxxxxxx
    """
    from flomo_insight.config import require_weread_key
    from flomo_insight.importers.weread import (
        WereadClient,
        fetch_reviewed_highlights,
        build_import_prompt,
    )

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
def flomo_weread_mark_imported(
    review_id: str,
    book_id: str,
    book_title: str,
    mark_text: str,
    flomo_slug: str = "",
) -> dict:
    """Mark a Weread reviewed highlight as imported.

    Call AFTER flomo_create() succeeds.

    Args:
        review_id: The review ID from the import prompt (shown as [review:xxx]).
        book_id: Book ID.
        book_title: Book title.
        mark_text: The highlight text.
        flomo_slug: The slug returned by flomo_create().

    Returns: {"status": "marked", "review_id": "..."}
    """
    from flomo_insight.importers.weread import mark_imported

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        mark_imported(db_conn, review_id, book_id, book_title, mark_text, flomo_slug)
        return {"status": "marked", "review_id": review_id}
    finally:
        db_conn.close()


@mcp.tool()
def flomo_weread_stats() -> dict:
    """Show WeRead import statistics (how many highlights imported, per-book breakdown)."""
    from flomo_insight.importers.weread import build_weread_stats

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        return build_weread_stats(db_conn)
    finally:
        db_conn.close()


# ── Runner ───────────────────────────────────────────────────────────────────


def run_mcp():
    """Entry point for `flomo mcp`."""
    mcp.run(transport="stdio")
