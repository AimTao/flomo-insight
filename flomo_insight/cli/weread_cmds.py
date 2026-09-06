"""WeRead import commands."""
from __future__ import annotations

import typer
from rich.table import Table

from flomo_insight.cli import context
from flomo_insight.cli.context import console
from flomo_insight.config import require_token

import_app = typer.Typer(help="Import data from external sources")


@import_app.command(name="weread")
def import_weread_cmd(
    batch_size: int = typer.Option(15, "--batch", "-n", help="Items per batch"),
    auto: bool = typer.Option(False, "--auto", help="Auto-import to flomo (no LLM tagging, only #微信读书)"),
    tag: str = typer.Option("", "--tag", help="Extra tag for --auto mode (besides 微信读书)"),
):
    """Fetch WeRead reviewed highlights (划线+书评) and import to flomo.

    Default: prints highlights+reviews as a prompt for LLM-assisted import via CLI.
    With --auto: imports directly to flomo with #微信读书 tag (no LLM classification).
    """
    from flomo_insight.config import require_weread_key

    db_conn = context._get_db().get_connection()
    context._get_db().migrate(db_conn)

    try:
        if auto:
            from flomo_insight.importers.weread import WereadClient, auto_import
            from flomo_insight.api.client import FlomoClient

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
            from flomo_insight.importers.weread import (
                WereadClient,
                fetch_reviewed_highlights,
            )
            from flomo_insight.tags.classifier import build_wearead_import_prompt
            with WereadClient(require_weread_key()) as client:
                items = fetch_reviewed_highlights(client, db_conn, batch_size=batch_size)

            if not items:
                console.print("[green]No new reviewed highlights. All caught up! 📚[/green]")
                return

            prompt = build_wearead_import_prompt(items)
            console.print(prompt)
    finally:
        db_conn.close()


def weread_stats_cmd():
    """Show WeRead import statistics."""
    from flomo_insight.importers.weread import build_weread_stats
    from rich.table import Table

    db_conn = context._get_db().get_connection()
    context._get_db().migrate(db_conn)

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


def weread_mark_cmd(
    review_id: str = typer.Argument(..., help="WeRead review id"),
    book_id: str = typer.Option(..., "--book-id"),
    book_title: str = typer.Option(..., "--book-title"),
    mark: str = typer.Option("", "--mark", help="Highlight text"),
    slug: str = typer.Option("", "--slug", help="Created flomo slug"),
):
    """Mark a WeRead highlight as imported (dedup). Call after create."""
    from flomo_insight.importers.weread import mark_imported

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        mark_imported(conn, review_id, book_id, book_title, mark, slug)
    finally:
        conn.close()
    console.print(f"[green]✓ Marked imported: {review_id}[/green]")
