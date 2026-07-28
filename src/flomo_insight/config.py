"""Load/save configuration from ~/.config/flomo-insight/config.toml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import tomli_w
from pydantic import BaseModel


class AuthConfig(BaseModel):
    token: str = ""


class StorageConfig(BaseModel):
    db_path: str = ""


class AnalysisConfig(BaseModel):
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    cluster_min_size: int = 5


class Config(BaseModel):
    auth: AuthConfig = AuthConfig()
    storage: StorageConfig = StorageConfig()
    analysis: AnalysisConfig = AnalysisConfig()


def _config_dir() -> Path:
    """Return ~/.config/flomo-insight, creating it if needed."""
    path = Path.home() / ".config" / "flomo-insight"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def default_db_path() -> str:
    """Default SQLite path: ~/.local/share/flomo-insight/flomo.db"""
    path = Path.home() / ".local" / "share" / "flomo-insight"
    path.mkdir(parents=True, exist_ok=True)
    return str(path / "flomo.db")


def load_config() -> Config:
    """Load config from disk, returning defaults if file is missing."""
    cfg_path = _config_path()
    if not cfg_path.exists():
        cfg = Config(storage=StorageConfig(db_path=default_db_path()))
        save_config(cfg)
        return cfg

    raw = cfg_path.read_text(encoding="utf-8")
    # tomli for reading, but since we only write with tomli-w we use a simple
    # approach: parse as a flat dict and feed into our model
    import tomllib

    data = tomllib.loads(raw)
    return Config(
        auth=AuthConfig(**data.get("auth", {})),
        storage=StorageConfig(**data.get("storage", {})),
        analysis=AnalysisConfig(**data.get("analysis", {})),
    )


def save_config(cfg: Config) -> None:
    """Persist config to disk as TOML."""
    raw = {
        "auth": {"token": cfg.auth.token},
        "storage": {"db_path": cfg.storage.db_path},
        "analysis": {
            "embedding_model": cfg.analysis.embedding_model,
            "cluster_min_size": cfg.analysis.cluster_min_size,
        },
    }
    _config_path().write_text(tomli_w.dumps(raw), encoding="utf-8")
