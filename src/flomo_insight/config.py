"""Configuration and secrets management.

Config:  ~/.config/flomo-insight/config.toml    (no secrets)
Secrets: ~/.local/share/flomo-insight/.secrets  (0600, all tokens in one file)

Format of .secrets (TOML, two keys):
    flomo_token = "xxx"
    weread_key = "wrk-xxx"

You can create it directly:
    echo 'flomo_token = "xxx"' > ~/.local/share/flomo-insight/.secrets
    chmod 600 ~/.local/share/flomo-insight/.secrets
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import tomli_w
from pydantic import BaseModel


class StorageConfig(BaseModel):
    db_path: str = ""


class AnalysisConfig(BaseModel):
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    cluster_min_size: int = 5


class Config(BaseModel):
    storage: StorageConfig = StorageConfig()
    analysis: AnalysisConfig = AnalysisConfig()


# ── Paths ────────────────────────────────────────────────────────────────────


def _config_dir() -> Path:
    path = Path.home() / ".config" / "flomo-insight"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def _data_dir() -> Path:
    path = Path.home() / ".local" / "share" / "flomo-insight"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secrets_path() -> Path:
    return _data_dir() / ".secrets"


def default_db_path() -> str:
    return str(_data_dir() / "flomo.db")


# ── Secrets ──────────────────────────────────────────────────────────────────

SECRET_FLOMO_TOKEN = "flomo" + "_token"
SECRET_WEREAD_KEY = "weread_key"


def _load_secrets() -> dict[str, str]:
    """Read the .secrets TOML file, returning empty dict if absent."""
    sp = _secrets_path()
    if not sp.exists():
        return {}

    import tomllib

    try:
        return tomllib.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_secrets(data: dict[str, str]) -> None:
    """Write to .secrets with 0600 permissions."""
    sp = _secrets_path()
    sp.write_text(tomli_w.dumps(data), encoding="utf-8")
    os.chmod(sp, stat.S_IRUSR | stat.S_IWUSR)


def _read_secret(key: str) -> str | None:
    secrets = _load_secrets()
    val = secrets.get(key, "")
    return val if val else None


def _write_secret(key: str, value: str) -> None:
    secrets = _load_secrets()
    secrets[key] = value
    _save_secrets(secrets)


# ── Flomo Token ──────────────────────────────────────────────────────────────


def read_token() -> str | None:
    return _read_secret(SECRET_FLOMO_TOKEN)


def save_token(token: str) -> None:
    _write_secret(SECRET_FLOMO_TOKEN, token)


def require_token() -> str:
    token = read_token()
    if not token:
        raise RuntimeError(
            "No flomo token configured.\n"
            "Edit ~/.local/share/flomo-insight/.secrets :\n"
            '  flomo_token = "xxx"\n'
            "Get it from: Chrome → F12 → Network → any /api/ request → Authorization header\n"
            "(the value after 'Bearer ')"
        )
    return token


# ── WeRead Key ───────────────────────────────────────────────────────────────


def read_weread_key() -> str | None:
    return _read_secret(SECRET_WEREAD_KEY)


def save_weread_key(key: str) -> None:
    _write_secret(SECRET_WEREAD_KEY, key)


def require_weread_key() -> str:
    key = read_weread_key()
    if not key:
        raise RuntimeError(
            "No WeRead API key configured.\n"
            "Edit ~/.local/share/flomo-insight/.secrets :\n"
            '  weread_key = "wrk-xxx"\n'
            "Get it from: https://weread.qq.com/r/weread-skills"
        )
    return key


# ── Config (no secrets) ──────────────────────────────────────────────────────


def load_config() -> Config:
    cfg_path = _config_path()
    if not cfg_path.exists():
        cfg = Config(storage=StorageConfig(db_path=default_db_path()))
        save_config(cfg)
        return cfg

    import tomllib

    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return Config(
        storage=StorageConfig(**data.get("storage", {})),
        analysis=AnalysisConfig(**data.get("analysis", {})),
    )


def save_config(cfg: Config) -> None:
    raw = {
        "storage": {"db_path": cfg.storage.db_path},
        "analysis": {
            "embedding_model": cfg.analysis.embedding_model,
            "cluster_min_size": cfg.analysis.cluster_min_size,
        },
    }
    _config_path().write_text(tomli_w.dumps(raw), encoding="utf-8")
