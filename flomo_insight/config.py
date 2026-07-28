"""Configuration — .env at project root, data/ directory.

.env — secrets (gitignored), copy .env.example to get started.
data/— database and local files (gitignored).
config.toml — non-sensitive settings at project root.
"""

from __future__ import annotations

import os
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


# ── Project root discovery ───────────────────────────────────────────────────

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


def default_db_path() -> str:
    return str(data_dir() / "flomo.db")


# ── .env ─────────────────────────────────────────────────────────────────────

_env: dict[str, str] | None = None


def _load_dotenv() -> dict[str, str]:
    global _env
    if _env is not None:
        return _env

    from dotenv import dotenv_values

    ep = project_root() / ".env"
    _env = {}
    if ep.exists():
        _env.update(dotenv_values(ep))

    for key in ("FLOMO_****** ***********_KEY"):
        if key in os.environ:
            _env[key] = os.environ[key]
    return _env


def _read_env(key: str) -> str | None:
    v = _load_dotenv().get(key, "")
    return v if v else None


def _write_env(key: str, value: str) -> None:
    ep = project_root() / ".env"
    lines = ep.read_text().splitlines() if ep.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ep.write_text("\n".join(lines).rstrip() + "\n")
    global _env
    _env = None


# ── Flomo Token ──────────────────────────────────────────────────────────────


def read_token() -> str | None:
    return _read_env("FLOMO_TOKEN")


def save_token(token: str) -> None:
    _write_env("FLOMO_TOKEN", token)


def require_token() -> str:
    t = read_token()
    if not t:
        raise RuntimeError(
            "FLOMO_TOKEN not set. Copy .env.example to .env and fill in your token.\n"
            "Get it: Chrome F12 → Network → /api/ → Authorization → value after 'Bearer '"
        )
    return t


# ── WeRead Key ───────────────────────────────────────────────────────────────


def read_weread_key() -> str | None:
    return _read_env("WEREAD_KEY")


def save_weread_key(key: str) -> None:
    _write_env("WEREAD_KEY", key)


def require_weread_key() -> str:
    k = read_weread_key()
    if not k:
        raise RuntimeError(
            "WEREAD_KEY not set. Copy .env.example to .env and set WEREAD_KEY.\n"
            "Get it: https://weread.qq.com/r/weread-skills"
        )
    return k


# ── Config ───────────────────────────────────────────────────────────────────


def load_config() -> Config:
    p = project_root() / "config.toml"
    if not p.exists():
        c = Config(storage=StorageConfig(db_path=default_db_path()))
        save_config(c)
        return c

    import tomllib

    d = tomllib.loads(p.read_text())
    return Config(
        storage=StorageConfig(**d.get("storage", {})),
        analysis=AnalysisConfig(**d.get("analysis", {})),
    )


def save_config(cfg: Config) -> None:
    raw = {
        "storage": {"db_path": cfg.storage.db_path},
        "analysis": {
            "embedding_model": cfg.analysis.embedding_model,
            "cluster_min_size": cfg.analysis.cluster_min_size,
        },
    }
    (project_root() / "config.toml").write_text(tomli_w.dumps(raw))
