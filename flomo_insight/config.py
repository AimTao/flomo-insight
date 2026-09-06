"""Configuration — single config.toml at project root.

config.toml — all settings + secrets (gitignored)
config.toml.example — template committed to git
"""

from __future__ import annotations

from pathlib import Path

import tomli_w
from pydantic import BaseModel


class Config(BaseModel):
    flomo_token: str = ""
    weread_key: str = ""
    db_path: str = ""
    d1_database_id: str = ""
    review_key: str = ""
    flomo_sign_salt: str = ""


_root: Path | None = None


def project_root() -> Path:
    global _root
    if _root is not None:
        return _root
    current = Path(__file__).resolve().parent.parent
    for p in [current, current.parent, current.parent.parent]:
        if (p / "pyproject.toml").exists():
            _root = p
            return p
    _root = Path.cwd()
    return _root


def data_dir() -> Path:
    d = project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


_config: Config | None = None


def load_config() -> Config:
    global _config
    if _config is not None:
        return _config
    import tomllib

    p = project_root() / "config.toml"
    if not p.exists():
        _config = Config(db_path=str(data_dir() / "flomo.db"))
        return _config
    d = tomllib.loads(p.read_text())
    _config = Config(
        flomo_token=d.get("flomo_token", ""),
        weread_key=d.get("weread_key", ""),
        db_path=d.get("db_path", str(data_dir() / "flomo.db")),
        d1_database_id=d.get("d1_database_id", ""),
        review_key=d.get("review_key", ""),
        flomo_sign_salt=d.get("flomo_sign_salt", ""),
    )
    return _config


def save_config(cfg: Config) -> None:
    raw = {
        "flomo_token": cfg.flomo_token,
        "weread_key": cfg.weread_key,
        "db_path": cfg.db_path,
        "d1_database_id": cfg.d1_database_id,
        "review_key": cfg.review_key,
        "flomo_sign_salt": cfg.flomo_sign_salt,
    }
    (project_root() / "config.toml").write_text(tomli_w.dumps(raw))
    global _config
    _config = cfg


def require_d1_database_id() -> str:
    cfg = load_config()
    if not cfg.d1_database_id:
        raise RuntimeError(
            "D1 backup not configured. Set d1_database_id in config.toml\n"
            "Create a D1 database: npx wrangler d1 create flomo-backup"
        )
    return cfg.d1_database_id


def require_token() -> str:
    t = load_config().flomo_token
    if not t:
        raise RuntimeError(
            "flomo_token not set in config.toml.\n"
            "Copy config.toml.example to config.toml and fill in your token."
        )
    return t


def require_weread_key() -> str:
    k = load_config().weread_key
    if not k:
        raise RuntimeError(
            "weread_key not set in config.toml.\n"
            "Get it from https://weread.qq.com/r/weread-skills"
        )
    return k
