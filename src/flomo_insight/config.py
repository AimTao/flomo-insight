"""Load/save configuration and token management.

Config:  ~/.config/flomo-insight/config.toml  (no secrets)
Tokens: ~/.local/share/flomo-insight/.token   (flomo, 0600)
        ~/.local/share/flomo-insight/.weread_cookie  (weread, 0600)
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


def _token_path() -> Path:
    return _data_dir() / ".token"


def _weread_cookie_path() -> Path:
    return _data_dir() / ".weread_cookie"


def default_db_path() -> str:
    return str(_data_dir() / "flomo.db")


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value.strip(), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _read_secret(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


# ── Flomo Token ──────────────────────────────────────────────────────────────


def read_token() -> str | None:
    return _read_secret(_token_path())


def save_token(token: str) -> None:
    _write_secret(_token_path(), token)


def require_token() -> str:
    token = read_token()
    if not token:
        raise RuntimeError(
            "No flomo token configured.\n"
            "Get it from: Chrome DevTools → Application → Cookies → flomoapp.com → token\n"
            "Then run: flomo config set-token YOUR_TOKEN"
        )
    return token


# ── WeRead Cookie ────────────────────────────────────────────────────────────


def read_weread_cookie() -> str | None:
    return _read_secret(_weread_cookie_path())


def save_weread_cookie(cookie: str) -> None:
    _write_secret(_weread_cookie_path(), cookie)


def require_weread_cookie() -> str:
    cookie = read_weread_cookie()
    if not cookie:
        raise RuntimeError(
            "No WeRead cookie configured.\n"
            "Get it from: Chrome DevTools → Application → Cookies → weread.qq.com\n"
            "Copy the full cookie string, then run: flomo config set-weread-cookie COOKIE"
        )
    return cookie


# ── Config ───────────────────────────────────────────────────────────────────


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
