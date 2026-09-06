"""Note sync / CRUD / search commands."""
from __future__ import annotations

import time
from typing import Optional

import typer
from rich.table import Table

from flomo_insight.api.client import FlomoAPIError
from flomo_insight.cli import context
from flomo_insight.cli.context import _format_output, _get_client, console


def sync_cmd(
    full: bool = typer.Option(False, "--full", help="Full re-sync from scratch"),
    no_progress: bool = typer.Option(
        False, "--no-progress", help="Disable progress bar"
    ),
):
    """Sync memos from flomo to the local database."""
    from flomo_insight.sync.exporter import sync

    db = context._get_db()
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

    db = context._get_db()
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


def create_cmd(
    content: str = typer.Argument(..., help="Memo content (markdown supported)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tags, comma-separated"),
):
    """Create a memo: first flomo, then mirror to local SQLite."""
    from flomo_insight.sync.local_write import apply_create_locally

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    if tag_list:
        prefixes = " ".join(f"#{t}" for t in tag_list)
        if not content.strip().startswith("#"):
            content = f"{prefixes}\n{content}"

    with _get_client() as client:
        try:
            result = client.create_memo(content, tags=tag_list)
        except FlomoAPIError as e:
            console.print(f"[red]Failed to create memo on flomo: {e}[/red]")
            raise typer.Exit(1)

    slug = result.get("data", {}).get("slug", "")
    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        payload = result.get("data") or {}
        if not payload.get("content"):
            payload = {
                "slug": slug,
                "content": content,
                "raw_content": content,
                "source": "flomo",
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
                "tags": [{"name": t} for t in (tag_list or [])],
            }
        apply_create_locally(conn, payload)
    finally:
        conn.close()

    console.print(f"[green]✓ Memo created: {slug or 'ok'}[/green]")
    if tag_list:
        console.print(f"  Tags: {', '.join(f'#{t}' for t in tag_list)}")


def update_cmd(
    slug: str = typer.Argument(..., help="Memo slug"),
    content: str = typer.Option(..., "--content", "-c", help="New content"),
):
    """Update a memo: first flomo, then mirror to local SQLite."""
    from flomo_insight.sync.local_write import apply_update_locally

    with _get_client() as client:
        try:
            client.update_memo(slug, content)
        except FlomoAPIError as e:
            console.print(f"[red]Failed to update on flomo: {e}[/red]")
            raise typer.Exit(1)

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        apply_update_locally(conn, slug, content)
    finally:
        conn.close()
    console.print(f"[green]✓ Updated {slug}[/green]")


def delete_cmd(
    slug: str = typer.Argument(..., help="Memo slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a memo: first flomo, then remove from local SQLite."""
    from flomo_insight.sync.local_write import apply_delete_locally

    if not yes:
        confirm = typer.confirm(f"Delete memo {slug} on flomo and locally?")
        if not confirm:
            raise typer.Abort()

    with _get_client() as client:
        try:
            client.delete_memo(slug)
        except FlomoAPIError as e:
            console.print(f"[red]Failed to delete on flomo: {e}[/red]")
            raise typer.Exit(1)

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        apply_delete_locally(conn, slug)
    finally:
        conn.close()
    console.print(f"[green]✓ Deleted {slug}[/green]")


# ── recent ───────────────────────────────────────────────────────────────────


def recent_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent memos"),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, md"
    ),
):
    """Show recent memos."""
    from flomo_insight.search.engine import recent_memos

    db = context._get_db()
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


def tags_cmd(
    sort: str = typer.Option("count", "--sort", help="Sort by: count, name"),
    limit: int = typer.Option(50, "--limit", "-n"),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output: table, json, md"
    ),
):
    """List tags with memo counts."""
    from flomo_insight.search.engine import get_tags

    db = context._get_db()
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


def stats_cmd(
    fmt: str = typer.Option("table", "--format", "-f", help="Output: table, json"),
):
    """Show database statistics."""
    from flomo_insight.search.engine import db_stats

    db = context._get_db()
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


def push_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Max local notes to push"),
):
    """Push source=local notes to flomo (create), then update local SQLite.

    Does not invent notes — only rows already marked source='local'.
    """
    from flomo_insight.sync.local_write import push_local_pending

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        with _get_client() as client:
            result = push_local_pending(conn, client, limit=limit)
    finally:
        conn.close()

    console.print(
        f"[green]✓ Pushed {result['pushed']}/{result['pending']} local notes to flomo[/green]"
    )
    for s in result.get("errors") or []:
        console.print(f"  [red]{s}[/red]")
    if result["pushed"] == 0 and result["pending"] == 0:
        console.print("[dim]No source=local notes to push.[/dim]")
