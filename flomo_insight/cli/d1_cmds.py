"""D1 push commands (insight / review / backup)."""
from __future__ import annotations

from pathlib import Path

import typer

from flomo_insight.cli import context
from flomo_insight.cli.context import console


def insight_push_cmd(
    insight_type: str = typer.Option(..., "--type", "-t", help="e.g. topics / cbt"),
    file: str = typer.Option(..., "--file", "-f", help="Path to LLM-written insight markdown"),
):
    """Push a finished LLM insight into D1 daily_reviews (kind=insight)."""
    from flomo_insight.config import require_d1_database_id
    from flomo_insight.review.push import push_insight_card

    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    try:
        d1_id = require_d1_database_id()
        result = push_insight_card(d1_id, insight_type=insight_type, file_path=str(path))
    except Exception as e:
        console.print(f"[red]insight-push failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]✓ Pushed insight card {result['slug']} "
        f"({result['content_len']} chars, type={result['insight_type']})[/green]"
    )


# ── review push ──────────────────────────────────────────────────────────────


def review_push_cmd():
    """Upsert cleaned memo cards into D1.daily_reviews (kind=memo).

    Never DROPs the table — served_count (rotation progress) is preserved.
    """
    from flomo_insight.config import require_d1_database_id
    from flomo_insight.review.push import push_memo_cards

    d1_id = require_d1_database_id()
    db_conn = context._get_db().get_connection()
    context._get_db().migrate(db_conn)

    try:
        console.print("[cyan]Pushing review cards to D1...[/cyan]")
        result = push_memo_cards(db_conn, d1_id)
        console.print(
            f"[green]✓ Pushed {result['pushed']} review cards to D1 "
            f"(from {result['total_memos']} memos, {result['skipped']} skipped)[/green]"
        )
    finally:
        db_conn.close()


# ── backup ───────────────────────────────────────────────────────────────────


def backup_cmd(
    batch_size: int = typer.Option(50, "--batch", "-n", help="Memos per D1 batch"),
):
    """Backup local memos to Cloudflare D1 (incremental via wrangler CLI).

    Requires d1_database_id in config.toml. Auth via wrangler login / OAuth.
    """
    from flomo_insight.config import require_d1_database_id
    from flomo_insight.backup.d1 import backup_to_d1

    database_id = require_d1_database_id()
    db = context._get_db()
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
