"""Shared CLI helpers."""
from __future__ import annotations

import json

from rich.console import Console

from flomo_insight.api.client import FlomoClient
from flomo_insight.config import load_config, require_token
from flomo_insight.db import DatabaseManager

console = Console()


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
