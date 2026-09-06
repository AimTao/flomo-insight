"""Insight material + retag commands (LLM writes conclusions)."""
from __future__ import annotations

import typer
from rich.table import Table

from flomo_insight.cli import context
from flomo_insight.cli.context import console


def perspectives_cmd():
    """List all insight types (material for LLM — this CLI does not conclude)."""
    from flomo_insight.insight.templates import list_perspectives

    analytical = [
        ("topics", "思维全景"),
        ("stagnant", "停滞检测"),
        ("declining", "兴趣消退"),
        ("connections", "跨界连接"),
        ("draft", "写作草稿"),
    ]
    t = Table(title="Insight Types (CLI packs prompt; Claude writes the insight)")
    t.add_column("Key", style="cyan")
    t.add_column("Title", style="bold")
    t.add_column("Family")
    for key, title in analytical:
        t.add_row(key, title, "analytical")
    for p in list_perspectives():
        t.add_row(p["key"], p["title"], f"perspective / {p['author']}")
    console.print(t)
    console.print("\n[dim]Run: flomo insight <type>  → prompt + notes for Claude[/dim]")


def insight_cmd(
    insight_type: str = typer.Argument("topics", help="Insight type key"),
):
    """Print prompt + raw notes for a type. Claude (Skill) writes the analysis."""
    from flomo_insight.insight.engine import generate_insight

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        material = generate_insight(conn, insight_type=insight_type)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
    # Plain print — this is LLM material, not a rich table
    print(material)


def retag_cmd(
    batch_size: int = typer.Option(10, "--batch", "-n", help="Memos per batch"),
    source: str = typer.Option("", "--source", help="flomo | weread | empty=all"),
    include_optimized: bool = typer.Option(
        False, "--all", help="Include memos already LLM-optimized (tags_llm_at set)"
    ),
):
    """Print taxonomy + pending memos (tags_llm_at IS NULL) for Claude to retag."""
    from flomo_insight.tags.classifier import build_retag_prompt, count_pending_retag

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        stats = count_pending_retag(conn)
        console.print(
            f"[dim]tags_llm: {stats['optimized']}/{stats['total']} optimized, "
            f"{stats['pending']} pending[/dim]"
        )
        material = build_retag_prompt(
            conn,
            batch_size=batch_size,
            source=source if source else None,
            include_optimized=include_optimized,
        )
    finally:
        conn.close()
    print(material)
    print("\n---\n先输出方案表并等用户确认，再 `flomo update`，成功后 `flomo tags-optimized <slug>`")


def tags_optimized_cmd(
    slugs: list[str] = typer.Argument(..., help="One or more memo slugs"),
):
    """Mark memos as LLM-tag-optimized (sets tags_llm_at). Skip in future retag."""
    from flomo_insight.tags.classifier import count_pending_retag, mark_tags_llm_optimized

    db = context._get_db()
    conn = db.get_connection()
    db.migrate(conn)
    try:
        n = mark_tags_llm_optimized(conn, list(slugs))
        stats = count_pending_retag(conn)
    finally:
        conn.close()
    console.print(
        f"[green]✓ Marked {n} memo(s) as tags-optimized[/green] "
        f"(pending left: {stats['pending']})"
    )
