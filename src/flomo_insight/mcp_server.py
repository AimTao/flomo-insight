"""FastMCP server — exposes flomo operations as MCP tools for Claude Code.

Launched via `flomo mcp`. Configure in Claude Code's MCP settings:
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

import json
from typing import Optional

from fastmcp import FastMCP

from flomo_insight.config import load_config, default_db_path
from flomo_insight.db import DatabaseManager

mcp = FastMCP(name="flomo-insight")


def _get_db() -> DatabaseManager:
    cfg = load_config()
    return DatabaseManager(cfg.storage.db_path or default_db_path())


def _get_token() -> str:
    cfg = load_config()
    if not cfg.auth.token:
        raise RuntimeError("No flomo token configured. Run 'flomo config set-token YOUR_TOKEN'")
    return cfg.auth.token


# ── Tools ────────────────────────────────────────────────────────────────────


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


@mcp.tool()
def flomo_create(content: str, tags: Optional[list[str]] = None, source: str = "mcp") -> dict:
    """Create a new flomo memo (synced to flomo cloud + local database).

    Args:
        content: Memo content (markdown supported).
        tags: Tags to attach (without # prefix).
        source: Source identifier, defaults to 'mcp'.
    """
    from flomo_insight.api.client import FlomoClient

    with FlomoClient(_get_token()) as client:
        result = client.create_memo(content, tags=tags, source=source)
        slug = result.get("data", {}).get("slug", "")
        return {"slug": slug, "content": content, "tags": tags or [], "status": "created"}


@mcp.tool()
def flomo_sync(full: bool = False) -> dict:
    """Sync memos from flomo API to the local database.

    Args:
        full: If true, re-sync everything from scratch (otherwise incremental).
    """
    from flomo_insight.sync.exporter import sync
    from flomo_insight.api.client import FlomoClient

    db = _get_db()
    with FlomoClient(_get_token()) as client:
        result = sync(client, db, full=full, show_progress=False)

    return {
        "new": result.new,
        "updated": result.updated,
        "total": result.total,
        "last_sync_at": "now",
    }


@mcp.tool()
def flomo_analyze(force: bool = False) -> dict:
    """Run the full analysis pipeline: embeddings, clustering, trends, keywords.

    This is a potentially slow operation (seconds to minutes depending on memo count).
    Run after syncing new data.

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
        embedded = compute_embeddings(conn, model_name=cfg.analysis.embedding_model, force=force)

        from flomo_insight.analysis.clustering import cluster_memos
        from flomo_insight.analysis.keywords import extract_keywords_per_cluster
        n_clusters = cluster_memos(conn, min_cluster_size=cfg.analysis.cluster_min_size)
        extract_keywords_per_cluster(conn)

        from flomo_insight.analysis.trends import compute_trends
        compute_trends(conn)

        from flomo_insight.analysis.cooccurrence import compute_cooccurrence
        compute_cooccurrence(conn)

        # Get top topics summary
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


@mcp.tool()
def flomo_insight(insight_type: str = "topics") -> str:
    """Generate an AI insight from analyzed flomo data.

    Args:
        insight_type: Statistical insight type:
            - topics: What topics you think about most
            - stagnant: Ideas that appear repeatedly but may lack follow-through
            - declining: Topics losing interest over time
            - connections: Hidden connections between tags
            - draft: Writing draft from clustered notes
    """
    from flomo_insight.insight.engine import generate_insight

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        return generate_insight(conn, insight_type=insight_type)
    finally:
        conn.close()


@mcp.tool()
def flomo_perspectives() -> list[dict]:
    """List all available LLM-driven insight perspectives. Each perspective applies a
    specific thinking lens (e.g. CBT therapy, inversion, value clarification) to your notes.

    Returns a list with key, title, author, and description for each perspective.
    Use flomo_perspective with a chosen key to generate the full prompt + notes.
    """
    from flomo_insight.insight.templates import list_perspectives
    return list_perspectives()


@mcp.tool()
def flomo_perspective(lens: str = "default") -> str:
    """Fetch your notes wrapped with a specific thinking perspective prompt.

    This tool retrieves recent and representative notes from your database,
    packages them with a system prompt that applies the chosen thinking lens,
    and returns the result for Claude Code to interpret.

    Args:
        lens: The perspective key. Call flomo_perspectives first to see options.
            Available: default, value-clarification, inversion, second-order,
            cbt, mbti

    Returns markdown: perspective system prompt + cluster summary + note contents.
    You (Claude) should read this and generate the insight analysis.
    """
    from flomo_insight.insight.engine import generate_insight

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        return generate_insight(conn, insight_type="perspective", lens=lens)
    finally:
        conn.close()


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


# ── Runner ───────────────────────────────────────────────────────────────────


def run_mcp():
    """Entry point for `flomo mcp`."""
    mcp.run(transport="stdio")
