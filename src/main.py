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

from src import __version__
from src.config import load_config, save_config, require_token
from src.db import DatabaseManager
from src.api.client import FlomoClient, FlomoAPIError

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
    return DatabaseManager(cfg.db_path)


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
    table = Table(title="flomo-insight Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Token", _mask_token(cfg.flomo_token))
    table.add_row("WeRead Key", _mask_token(cfg.weread_key))
    table.add_row("DB Path", cfg.db_path)
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
            console.print("[red]Token validation failed.[/red]")
            raise typer.Exit(1)

    cfg = load_config()
    cfg.flomo_token = token
    save_config(cfg)
    console.print("[green]✓ Token saved and validated![/green]")


@config_app.command(name="set-weread-key")
def config_set_weread_key(
    key: str = typer.Argument(..., help="WeRead API key (wrk-xxxxxxxx)"),
):
    """Set and validate your WeRead Skills API key."""
    from src.importers.weread import WereadClient

    console.print("[cyan]Validating WeRead API key...[/cyan]")
    with WereadClient(key) as client:
        if not client.verify():
            console.print("[red]API key validation failed.[/red]")
            raise typer.Exit(1)

    cfg = load_config()
    cfg.weread_key = key
    save_config(cfg)
    console.print("[green]✓ WeRead API key saved and validated![/green]")


# ── import (weread) ──────────────────────────────────────────────────────────

import_app = typer.Typer(help="Import data from external sources")
app.add_typer(import_app, name="import")


@import_app.command(name="weread")
def import_weread_cmd(
    batch_size: int = typer.Option(15, "--batch", "-n", help="Items per batch"),
    auto: bool = typer.Option(False, "--auto", help="Auto-import to flomo (no LLM tagging, only #微信读书)"),
    tag: str = typer.Option("", "--tag", help="Extra tag for --auto mode (besides 微信读书)"),
):
    """Fetch WeRead reviewed highlights (划线+书评) and import to flomo.

    Default: prints highlights+reviews as a prompt for LLM-assisted import via MCP.
    With --auto: imports directly to flomo with #微信读书 tag (no LLM classification).
    """
    from src.config import require_weread_key

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        if auto:
            from src.importers.weread import WereadClient, auto_import
            from src.api.client import FlomoClient

            extra_tag = [tag] if tag else None
            classifier = (lambda text, title: extra_tag) if extra_tag else None

            with WereadClient(require_weread_key()) as wclient, FlomoClient(require_token()) as fclient:
                console.print("[cyan]Auto-importing to flomo...[/cyan]")
                result = auto_import(wclient, fclient, db_conn, batch_size=batch_size, classifier=classifier)

            console.print(f"[green]✓ Imported: {result['imported']}[/green]")
            if result["skipped"]:
                console.print(f"[yellow]Skipped: {result['skipped']}[/yellow]")
            for e in result["errors"]:
                console.print(f"  [red]{e}[/red]")
        else:
            from src.importers.weread import (
                WereadClient,
                fetch_reviewed_highlights,
            )
            from src.tags.classifier import build_wearead_import_prompt
            with WereadClient(require_weread_key()) as client:
                items = fetch_reviewed_highlights(client, db_conn, batch_size=batch_size)

            if not items:
                console.print("[green]No new reviewed highlights. All caught up! 📚[/green]")
                return

            prompt = build_wearead_import_prompt(items)
            console.print(prompt)
    finally:
        db_conn.close()


@app.command(name="weread-stats")
def weread_stats_cmd():
    """Show WeRead import statistics."""
    from src.importers.weread import build_weread_stats
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
    from src.sync.exporter import sync

    db = _get_db()
    with _get_client() as client:
        console.print("[cyan]Starting sync...[/cyan]")
        result = sync(client, db, full=full, show_progress=not no_progress)

    console.print(
        f"[green]Sync complete: {result.total} total, {result.new} new[/green]"
    )
    if result.errors:
        for e in result.errors:
            if "Auth error" in e:
                console.print(f"[bold red]{e}[/bold red]")
            else:
                console.print(f"[yellow]Warning: {e}[/yellow]")


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
    from src.search.engine import search

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
    from src.search.engine import recent_memos

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
    from src.search.engine import get_tags

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
    from src.search.engine import db_stats

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


# ── perspectives ────────────────────────────────────────────────────────────


@app.command(name="perspectives")
def perspectives_cmd():
    """List all available insight types and thinking lenses."""
    from src.insight.templates import list_perspectives
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


# ── backup ───────────────────────────────────────────────────────────────────


@app.command(name="review")
def review_cmd(
    count: int = typer.Option(50, "--count", "-n", help="Groups per strategy"),
    push: bool = typer.Option(False, "--push", help="Push reviews JSON to D1"),
    json_file: str = typer.Option("", "--json", help="Read reviews from JSON file"),
):
    """Generate review groups and print as LLM prompt, or push reviews to D1.

    Without --push: prints memo groups as a prompt for Claude to write reviews.
    With --push --json <file>: reads reviews from a JSON file and pushes to D1.
    """
    from src.review.engine import find_groups
    from src.backup.d1 import _run_wrangler, _escape_sql_value

    db_conn = _get_db().get_connection()
    _get_db().migrate(db_conn)

    try:
        if push and json_file:
            # Push mode: read reviews from JSON, push to D1
            from src.config import require_d1_database_id
            import json as _json
            d1_id = require_d1_database_id()

            _run_wrangler(d1_id, """
                CREATE TABLE IF NOT EXISTS daily_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    memo_slugs TEXT NOT NULL,
                    content TEXT NOT NULL,
                    served_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            with open(json_file) as f:
                reviews = _json.load(f)

            today = __import__("datetime").date.today().isoformat()
            pushed = 0
            for r in reviews:
                slugs_json = _json.dumps(r["slugs"], ensure_ascii=False)
                content_esc = _escape_sql_value(r["content"])
                import time
                now = str(int(time.time()))
                sql = (
                    f"INSERT INTO daily_reviews (date, memo_slugs, content, served_count, created_at) "
                    f"VALUES ('{today}','{slugs_json}','{content_esc}',0,'{now}')"
                )
                _run_wrangler(d1_id, sql)
                pushed += 1
                if pushed % 20 == 0:
                    console.print(f"  Pushed {pushed}/{len(reviews)}...")
                time.sleep(0.3)

            console.print(f"[green]✓ Pushed {pushed} reviews to D1[/green]")
            return

        # Generate mode: find groups and output as prompt
        console.print(f"[cyan]Finding memo groups (target: {count} per strategy)...[/cyan]")
        groups = find_groups(db_conn, count_per_strategy=count)
        console.print(f"[green]Found {len(groups)} groups[/green]")

        # Output as JSON for subagent consumption
        output = []
        for g in groups:
            output.append({
                "slugs": g["slugs"],
                "contents": g["contents"],
                "strategy": g["strategy"],
            })

        import json as _json
        print(_json.dumps(output, ensure_ascii=False, indent=2))

    finally:
        db_conn.close()


# ── backup ───────────────────────────────────────────────────────────────────


@app.command(name="backup")
def backup_cmd(
    batch_size: int = typer.Option(50, "--batch", "-n", help="Memos per D1 batch"),
):
    """Backup local memos to Cloudflare D1 (incremental via wrangler CLI).

    Requires d1_database_id in config.toml. Auth via macOS Keychain (wrangler login).
    First run pushes all memos; subsequent runs only push new/updated ones.
    """
    from src.config import require_d1_database_id
    from src.backup.d1 import backup_to_d1

    database_id = require_d1_database_id()
    db = _get_db()
    conn = db.get_connection()
    db.migrate(conn)

    try:
        console.print("[cyan]Backing up to Cloudflare D1...[/cyan]")
        result = backup_to_d1(conn, database_id, batch_size=batch_size)
        console.print(
            f"[green]✓ Backed up {result['backed_up']}/{result['total']} memos to D1[/green]"
        )
    except Exception as e:
        console.print(f"[red]Backup failed: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


# ── mcp ──────────────────────────────────────────────────────────────────────


@app.command(name="mcp")
def mcp_cmd():
    """Start the MCP server for Claude Code integration."""
    from src.mcp_server import run_mcp
    run_mcp()


# ── version ──────────────────────────────────────────────────────────────────


@app.command(name="version")
def version_cmd():
    """Show version."""
    console.print(f"flomo-insight v{__version__}")


# ── Entry point ──────────────────────────────────────────────────────────────


def main():
    app()
