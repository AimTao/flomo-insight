"""CLI entry point — Typer app assembly.

Data ops: sync / CRUD / weread import / D1 push.
Insights: Python only packs prompt + notes; Claude (Skills) writes conclusions.
No MCP — Agents use this CLI + Skills.
"""

from __future__ import annotations

import typer

from flomo_insight import __version__
from flomo_insight.cli.context import (  # noqa: F401  (re-export for tests / patching)
    _format_output,
    _get_client,
    _get_db,
    console,
)
from flomo_insight.cli.config_cmds import config_app
from flomo_insight.cli.d1_cmds import backup_cmd, insight_push_cmd, review_push_cmd
from flomo_insight.cli.insight_cmds import (
    insight_cmd,
    perspectives_cmd,
    retag_cmd,
    tags_optimized_cmd,
)
from flomo_insight.cli.note_cmds import (
    create_cmd,
    delete_cmd,
    push_cmd,
    recent_cmd,
    search_cmd,
    stats_cmd,
    sync_cmd,
    tags_cmd,
    update_cmd,
)
from flomo_insight.cli.weread_cmds import import_app, weread_mark_cmd, weread_stats_cmd

app = typer.Typer(
    name="flomo",
    help="AI-powered insight engine for flomo notes",
    add_completion=False,
)

app.add_typer(config_app, name="config")
app.add_typer(import_app, name="import")

app.command(name="sync")(sync_cmd)
app.command(name="search")(search_cmd)
app.command(name="create")(create_cmd)
app.command(name="update")(update_cmd)
app.command(name="delete")(delete_cmd)
app.command(name="recent")(recent_cmd)
app.command(name="tags")(tags_cmd)
app.command(name="stats")(stats_cmd)
app.command(name="perspectives")(perspectives_cmd)
app.command(name="insight")(insight_cmd)
app.command(name="retag")(retag_cmd)
app.command(name="tags-optimized")(tags_optimized_cmd)
app.command(name="insight-push")(insight_push_cmd)
app.command(name="review-push")(review_push_cmd)
app.command(name="backup")(backup_cmd)
app.command(name="push")(push_cmd)
app.command(name="weread-stats")(weread_stats_cmd)
app.command(name="weread-mark")(weread_mark_cmd)


@app.command(name="version")
def version_cmd():
    """Show version."""
    console.print(f"flomo-insight v{__version__}")


def main():
    app()
