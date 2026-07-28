"""Database: schema and connection management.

Tables:
  memos       — core note storage (synced from flomo)
  tags        — tag dictionary
  memo_tags   — many-to-many memo <-> tag
  memos_fts   — FTS5 full-text search index
  sync_state  — incremental sync cursor
  weread_imports — WeRead import dedup
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Core note storage
CREATE TABLE IF NOT EXISTS memos (
    slug TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    raw_content TEXT,
    source TEXT DEFAULT 'flomo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tag dictionary
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- Many-to-many memo <-> tag
CREATE TABLE IF NOT EXISTS memo_tags (
    memo_slug TEXT NOT NULL REFERENCES memos(slug) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (memo_slug, tag_id)
);

-- Incremental sync cursor
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- WeRead import tracking (dedup by review_id)
CREATE TABLE IF NOT EXISTS weread_imports (
    review_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    book_title TEXT NOT NULL,
    mark_text TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    flomo_slug TEXT
);

-- FTS5 full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS memos_fts USING fts5(
    content,
    source,
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memos_ai AFTER INSERT ON memos BEGIN
    INSERT INTO memos_fts(rowid, content, source)
    VALUES (new.rowid, new.content, new.source);
END;

CREATE TRIGGER IF NOT EXISTS memos_ad AFTER DELETE ON memos BEGIN
    INSERT INTO memos_fts(memos_fts, rowid, content, source)
    VALUES ('delete', old.rowid, old.content, old.source);
END;

CREATE TRIGGER IF NOT EXISTS memos_au AFTER UPDATE ON memos BEGIN
    INSERT INTO memos_fts(memos_fts, rowid, content, source)
    VALUES ('delete', old.rowid, old.content, old.source);
    INSERT INTO memos_fts(rowid, content, source)
    VALUES (new.rowid, new.content, new.source);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_memos_created_at ON memos(created_at);
CREATE INDEX IF NOT EXISTS idx_memos_updated_at ON memos(updated_at);
CREATE INDEX IF NOT EXISTS idx_memo_tags_tag ON memo_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_weread_imports_book ON weread_imports(book_id);
"""

MIGRATIONS: dict[int, str] = {1: SCHEMA_V1}
CURRENT_SCHEMA_VERSION = 1


@dataclass
class DatabaseManager:
    """Manages a single SQLite connection with WAL mode and migration support."""

    db_path: str

    def __post_init__(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def current_version(self, conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0

    def migrate(self, conn: sqlite3.Connection | None = None) -> None:
        close_after = conn is None
        if conn is None:
            conn = self.get_connection()
        try:
            current = self.current_version(conn)
            for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
        finally:
            conn.commit()
            if close_after:
                conn.close()
