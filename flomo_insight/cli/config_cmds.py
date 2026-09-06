"""config subcommands."""
from __future__ import annotations

import typer
from rich.table import Table

from flomo_insight.api.client import FlomoClient
from flomo_insight.cli.context import _mask_token, console
from flomo_insight.config import load_config, save_config

config_app = typer.Typer(help="Manage configuration")


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
    token: str = typer.Argument(..., help="flomo token (Authorization: Bearer …)"),
):
    """Set and validate your flomo API token.

    Get the token from Chrome DevTools → Network → /api/ → Authorization: Bearer.
    Saved to config.toml (gitignored).
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
    from flomo_insight.importers.weread import WereadClient

    console.print("[cyan]Validating WeRead API key...[/cyan]")
    with WereadClient(key) as client:
        if not client.verify():
            console.print("[red]API key validation failed.[/red]")
            raise typer.Exit(1)

    cfg = load_config()
    cfg.weread_key = key
    save_config(cfg)
    console.print("[green]✓ WeRead API key saved and validated![/green]")
