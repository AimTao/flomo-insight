"""CLI entry point — Typer command tree for flomo-insight.

CLI handles data operations (sync, search, create, analyze, configure).
Insights are MCP-only — Claude Code reads the prompt + notes and generates analysis.
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from flomo_insight import __version__
from flomo_insight.config import (
    load_config,
    save_config,
    default_db_path,
    read_token,
    save_token,
    require_token,
)
from flomo_insight.db import DatabaseManager
from flomo_insight.api.client import FlomoClient, FlomoAPIError

app = typer.Typer(
    name="flomo",
    help="AI-powered insight engine for flomo notes",
    add_completion=False,
)
console = Console()

# ── Sub-apps ─────────────────────────────────────────────────────────────────

config_app = typer.Typer(help="Manage configuration")
app.add_typer(config_app, name="config")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_db() -> DatabaseManager:
    cfg = load_config()
    db_path = cfg.storage.db_path or default_db_path()
    return DatabaseManager(db_path)


def _get_client() -> FlomoClient:
    return FlomoClient(require_token())


def _format_output(data, fmt: str, table_builder=None):
    if fmt == "json":
        console.print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif fmt == "md":
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    console.print(f"- **{item.get('name', item.get('slug', ''))}**: {item}")
                else:
                    console.print(f"- {item}")
        else:
            console.print(data)
    else:
        if table_builder:
            table_builder()
        else:
            console.print(data)


def _mask_token(token: str | None) -> str:
    if not token or len(token) < 12:
        return "(not set)"
    return token[:8] + "..." + token[-4:]


# ── config ───────────────────────────────────────────────────────────────────


@config_app.command(name="show")
def config_show():
    """Show current configuration."""
    cfg = load_config()
    token = read_token()
    table = Table(title="flomo-insight Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Token", _mask_token(token))
    table.add_row("DB Path", cfg.storage.db_path or default_db_path())
    table.add_row("Embedding Model", cfg.analysis.embedding_model)
    table.add_row("Cluster Min Size", str(cfg.analysis.cluster_min_size))
    console.print(table)


@config_app.command(name="set-token")
def config_set_token(
    token: str = typer.Argument(..., help="Your flomo token from browser cookies"),
):
    """Set and validate your flomo API token.

    Get the token from Chrome DevTools → Application → Cookies → flomoapp.com → token.
    The token is stored in ~/.local/share/flomo-insight/.token (0600, not in git).
    """
    console.print("[cyan]Validating token...[/cyan]")
    with FlomoClient(token) as client:
        if not client.verify():
            console.print(
                "[red]Token validation failed. Check that the token is correct.[/red]"
            )
            console.print(
                "[yellow]Get it from: Chrome DevTools → Application → Cookies → flomoapp.com → token[/yellow]"
            )
            raise typer.Exit(1)

    save_token(token)
    console.print("[green]✓ Token saved and validated successfully![/green]")


@config_app.command(name="set-weread-key")
def config_set_weread_key(
    key: str = typer.Argument(..., help="WeRead API key (wrk-xxxxxxxx)"),
):
    """Set and validate your WeRead Skills API key.

    Get it from https://weread.qq.com/r/weread-skills — log in to get your key.
    Stored in ~/.local/share/flomo-insight/.weread_key (0600, not in git).
    """
    from flomo_insight.config import save_weread_key
    from flomo_insight.importers.weread import WereadClient

    console.print("[cyan]Validating WeRead API key...[/cyan]")
    with WereadClient(key) as client:
        if not client.verify():
            console.print(
                "[red]API key validation failed. Check that the key is correct.[/red]"
            )
            console.print(
                "[yellow]Get it from: https://weread.qq.com/r/weread-skills[/yellow]"
            )
            raise typer.Exit(1)

    save_weread_key(key)
    console.print("[green]✓ WeRead API key saved and validated![/green]")


# ── import (weread) ──────────────────────────────────────────────────────────

import_app = typer.Typer(help="Import data from external sources")
app.add_typer(import_app, name="import")


@import_app.command(name="weread")
def import_weread_cmd(
    batch_size: int = typer.Option(15, "--batch", "-n", help="Items per batch"),
):
    """Fetch WeRead reviewed highlights (划线+书评) for import.

    Shows the highlights and your personal reviews. Actual import (with LLM
    classification) happens via the MCP flomo_import_weread tool in Claude Code.
    """
    from flomo_insight.config import require_weread_key
    from flomo_insight.importers.weread import (
        WereadClient,
        fetch_reviewed_highlights,
        build_import_prompt,
    )

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        with WereadClient(require_weread_key()) as client:
            items = fetch_reviewed_highlights(client, db_conn, batch_size=batch_size)

        if not items:
            console.print("[green]No new reviewed highlights. All caught up! 📚[/green]")
            return

        prompt = build_import_prompt(items)
        console.print(prompt)
    finally:
        db_conn.close()


@app.command(name="weread-stats")
def weread_stats_cmd():
    """Show WeRead import statistics."""
    from flomo_insight.importers.weread import build_weread_stats
    from rich.table import Table

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        stats = build_weread_stats(db_conn)
        console.print(
            f"[bold]WeRead Imports: {stats['total_imported']} highlights[/bold]\n"
        )
        if stats["books"]:
            t = Table(title="By Book")
            t.add_column("Book", style="cyan")
            t.add_column("Highlights", style="green", justify="right")
            for b in stats["books"]:
                t.add_row(b["title"], str(b["count"]))
            console.print(t)
    finally:
        db_conn.close()
# ── sync ─────────────────────────────────────────────────────────────────────


@app.command(name="sync")
def sync_cmd(
    full: bool = typer.Option(False, "--full", help="Full re-sync from scratch"),
    no_progress: bool = typer.Option(
        False, "--no-progress", help="Disable progress bar"
    ),
):
    """Sync memos from flomo to the local database."""
    from flomo_insight.sync.exporter import sync

    db = _get_db()
    with _get_client() as client:
        console.print("[cyan]Starting sync...[/cyan]")
        result = sync(client, db, full=full, show_progress=not no_progress)

    console.print(
        f"[green]Sync complete: {result.total} total, {result.new} new[/green]"
    )
    if result.errors:
        console.print(f"[yellow]Warnings: {len(result.errors)}[/yellow]")
        for e in result.errors:
            console.print(f"  [dim]{e}[/dim]")


# ── search ───────────────────────────────────────────────────────────────────


@app.command(name="search")
def search_cmd(
    query: str = typer.Argument(..., help="Search query (supports boolean operators)"),
    tags: Optional[str] = typer.Option(
        None, "--tags", help="Filter by tags, comma-separated (AND logic)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Results per page"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, md"
    ),
):
    """Search memos by full-text query."""
    from flomo_insight.search.engine import search

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    hits, total = search(conn, query, tags=tag_list, limit=limit, offset=offset)

    def build_table():
        t = Table(title=f'Search: "{query}" ({total} results)')
        t.add_column("Date", style="dim", width=16)
        t.add_column("Content", style="green", width=60)
        t.add_column("Tags", style="cyan", width=20)
        for h in hits:
            t.add_row(
                h.created_at[:16] if h.created_at else "",
                h.snippet,
                ", ".join(h.tags),
            )
        console.print(t)

    _format_output(
        [
            {
                "slug": h.slug,
                "content": h.snippet,
                "tags": h.tags,
                "created_at": h.created_at,
            }
            for h in hits
        ],
        fmt,
        build_table,
    )
    conn.close()


# ── create ───────────────────────────────────────────────────────────────────


@app.command(name="create")
def create_cmd(
    content: str = typer.Argument(..., help="Memo content (markdown supported)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tags, comma-separated"),
):
    """Create a new flomo memo (synced to cloud)."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    with _get_client() as client:
        try:
            result = client.create_memo(content, tags=tag_list)
            console.print(
                f"[green]✓ Memo created: {result.get('data', {}).get('slug', 'ok')}[/green]"
            )
            if tag_list:
                console.print(f"  Tags: {', '.join(f'#{t}' for t in tag_list)}")
        except FlomoAPIError as e:
            console.print(f"[red]Failed to create memo: {e}[/red]")
            raise typer.Exit(1)


# ── recent ───────────────────────────────────────────────────────────────────


@app.command(name="recent")
def recent_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent memos"),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, md"
    ),
):
    """Show recent memos."""
    from flomo_insight.search.engine import recent_memos

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    hits = recent_memos(conn, limit=limit)

    def build_table():
        t = Table(title=f"Recent Memos ({len(hits)})")
        t.add_column("Date", style="dim", width=16)
        t.add_column("Content", style="green", width=60)
        t.add_column("Tags", style="cyan", width=20)
        for h in hits:
            snippet = (
                h.content[:120].replace("\n", " ")
                + ("..." if len(h.content) > 120 else "")
            )
            t.add_row(
                h.created_at[:16] if h.created_at else "", snippet, ", ".join(h.tags)
            )
        console.print(t)

    _format_output(
        [
            {
                "slug": h.slug,
                "content_snippet": h.content[:200],
                "tags": h.tags,
                "created_at": h.created_at,
            }
            for h in hits
        ],
        fmt,
        build_table,
    )
    conn.close()


# ── tags ─────────────────────────────────────────────────────────────────────


@app.command(name="tags")
def tags_cmd(
    sort: str = typer.Option("count", "--sort", help="Sort by: count, name"),
    limit: int = typer.Option(50, "--limit", "-n"),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output: table, json, md"
    ),
):
    """List tags with memo counts."""
    from flomo_insight.search.engine import get_tags

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    tag_list = get_tags(conn, sort_by=sort, limit=limit)

    def build_table():
        t = Table(title=f"Tags ({len(tag_list)})")
        t.add_column("Tag", style="cyan")
        t.add_column("Count", style="green", justify="right")
        for tag in tag_list:
            t.add_row(tag["name"], str(tag["count"]))
        console.print(t)

    _format_output(tag_list, fmt, build_table)
    conn.close()


# ── stats ────────────────────────────────────────────────────────────────────


@app.command(name="stats")
def stats_cmd(
    fmt: str = typer.Option("table", "--format", "-f", help="Output: table, json"),
):
    """Show database statistics."""
    from flomo_insight.search.engine import db_stats

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    stats = db_stats(conn)

    def build_table():
        t = Table(title="flomo-insight Statistics")
        t.add_column("Metric", style="cyan")
        t.add_column("Value", style="green")
        for k, v in stats.items():
            t.add_row(k.replace("_", " ").title(), str(v))
        console.print(t)

    _format_output(stats, fmt, build_table)
    conn.close()


# ── analyze ──────────────────────────────────────────────────────────────────


@app.command(name="analyze")
def analyze_cmd(
    force: bool = typer.Option(
        False, "--force", help="Recompute all embeddings from scratch"
    ),
    cluster_min_size: int = typer.Option(
        5, "--min-cluster", help="Minimum cluster size for HDBSCAN"
    ),
):
    """Run the analysis pipeline: embeddings → clustering → trends → keywords.

    This is the prerequisite for insight generation. Run after syncing new data.
    """
    import warnings

    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    cfg = load_config()

    console.print("[cyan]Step 1/4: Computing embeddings...[/cyan]")
    from flomo_insight.analysis.embeddings import compute_embeddings

    embedded = compute_embeddings(
        conn, model_name=cfg.analysis.embedding_model, force=force
    )
    console.print(f"  [green]Embeddings: {embedded} memos processed[/green]")

    console.print("[cyan]Step 2/4: Clustering...[/cyan]")
    from flomo_insight.analysis.clustering import cluster_memos
    from flomo_insight.analysis.keywords import extract_keywords_per_cluster

    n_clusters = cluster_memos(conn, min_cluster_size=cluster_min_size)
    console.print(f"  [green]Clusters: {n_clusters} found[/green]")
    extract_keywords_per_cluster(conn)

    console.print("[cyan]Step 3/4: Computing trends...[/cyan]")
    from flomo_insight.analysis.trends import compute_trends

    compute_trends(conn)
    console.print(f"  [green]Trends: computed for {n_clusters} clusters[/green]")

    console.print("[cyan]Step 4/4: Tag co-occurrence...[/cyan]")
    from flomo_insight.analysis.cooccurrence import compute_cooccurrence

    edge_count = compute_cooccurrence(conn)
    console.print(f"  [green]Co-occurrence: {edge_count} tag pair edges[/green]")

    conn.close()
    console.print("\n[bold green]✓ Analysis complete![/bold green]")
    console.print(
        "[dim]Insights are available via MCP — use Claude Code to explore.[/dim]"
    )


# ── perspectives ────────────────────────────────────────────────────────────


@app.command(name="perspectives")
def perspectives_cmd():
    """List all available insight types and thinking lenses."""
    from flomo_insight.insight.templates import list_perspectives
    from rich.table import Table

    ps = list_perspectives()
    t = Table(title="Available Insight Types (MCP-driven)")
    t.add_column("Key", style="cyan")
    t.add_column("Title", style="bold")
    t.add_column("Author", style="dim")
    t.add_column("Description")
    for p in ps:
        t.add_row(p["key"], p["title"], p["author"], p["description"])
    console.print(t)
    console.print(
        "\n[dim]These are available via the MCP flomo_insight tool in Claude Code.[/dim]"
    )


# ── mcp ──────────────────────────────────────────────────────────────────────


@app.command(name="mcp")
def mcp_cmd():
    """Start the MCP server for Claude Code integration."""
    console.print("[cyan]Starting flomo-insight MCP server...[/cyan]")
    console.print(
        "[dim]Configure in Claude Code: mcp add flomo -- uv run flomo mcp[/dim]"
    )
    from flomo_insight.mcp_server import run_mcp

    run_mcp()


# ── version ──────────────────────────────────────────────────────────────────


@app.command(name="version")
def version_cmd():
    """Show version."""
    console.print(f"flomo-insight v{__version__}")


# ── Entry point ──────────────────────────────────────────────────────────────


def main():
    app()
