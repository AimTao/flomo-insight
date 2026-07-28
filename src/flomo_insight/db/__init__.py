"""Database: schema definitions, connection management, and migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── DDL ──────────────────────────────────────────────────────────────────────

SCHEMA_V1 = """
-- Version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Core memo storage
CREATE TABLE IF NOT EXISTS memos (
    slug TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    raw_content TEXT,
    source TEXT DEFAULT 'flomo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    embedding_dirty INTEGER NOT NULL DEFAULT 1,
    word_count INTEGER GENERATED ALWAYS AS (
        length(content) - length(replace(content, ' ', '')) + 1
    ) STORED
);

-- Tags
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

-- Cached embeddings (384-dim float vector as JSON array)
CREATE TABLE IF NOT EXISTS embeddings (
    memo_slug TEXT PRIMARY KEY REFERENCES memos(slug) ON DELETE CASCADE,
    vector_json TEXT NOT NULL,
    model_name TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cluster assignments
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_label INTEGER NOT NULL,
    label_name TEXT,
    keywords TEXT,
    size INTEGER NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Memo-to-cluster mapping
CREATE TABLE IF NOT EXISTS cluster_memos (
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    memo_slug TEXT NOT NULL REFERENCES memos(slug) ON DELETE CASCADE,
    membership_prob REAL,
    PRIMARY KEY (cluster_id, memo_slug)
);

-- Topic trend data (per cluster, per month)
CREATE TABLE IF NOT EXISTS topic_trends (
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    memo_count INTEGER NOT NULL,
    trend_slope REAL,
    PRIMARY KEY (cluster_id, month)
);

-- Tag co-occurrence edges
CREATE TABLE IF NOT EXISTS tag_cooccurrence (
    tag_a_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    tag_b_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (tag_a_id, tag_b_id),
    CHECK (tag_a_id < tag_b_id)
);

-- Cached insights
CREATE TABLE IF NOT EXISTS cached_insights (
    insight_type TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    content TEXT NOT NULL,
    params_json TEXT,
    PRIMARY KEY (insight_type, params_json)
);

-- Incremental sync state
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- FTS5 virtual table for full-text search
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
CREATE INDEX IF NOT EXISTS idx_embeddings_dirty ON memos(embedding_dirty)
    WHERE embedding_dirty = 1;
CREATE INDEX IF NOT EXISTS idx_cluster_memos_cluster ON cluster_memos(cluster_id);
"""

MIGRATIONS: dict[int, str] = {
    1: SCHEMA_V1,
}

CURRENT_SCHEMA_VERSION = max(MIGRATIONS.keys()) if MIGRATIONS else 0


# ── Database Manager ─────────────────────────────────────────────────────────


@dataclass
class DatabaseManager:
    """Manages a single SQLite connection with WAL mode and migration support."""

    db_path: str

    def __post_init__(self) -> None:
        # Ensure the parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Open and configure a connection. Caller must close it."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def current_version(self, conn: sqlite3.Connection) -> int:
        """Get the current schema version, or 0 if uninitialised."""
        try:
            row = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0

    def migrate(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Run any pending migrations."""
        close_after = conn is None
        if conn is None:
            conn = self.get_connection()

        try:
            current = self.current_version(conn)
            for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
                sql = MIGRATIONS[version]
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
        finally:
            conn.commit()
            if close_after:
                conn.close()
