"""Push memo cards and LLM insight cards to D1 daily_reviews.

Schema (latest only — no legacy migration):
  id, kind ('memo'|'insight'), slug, content, insight_type,
  date, served_count, created_at

Never DROP the table — served_count (rotation progress) must survive.
If an old table lacks kind/insight_type, DROP it once and re-push.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any

from flomo_insight.backup.d1 import _escape_sql_value, _run_wrangler
from flomo_insight.review.scheduler import dedupe_cards, strip_known_tags, to_plain_text

DAILY_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS daily_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'memo',
    slug TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    insight_type TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    served_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def ensure_daily_reviews_schema(database_id: str) -> None:
    """Create daily_reviews if missing. Latest schema only — no ALTER."""
    _run_wrangler(database_id, DAILY_REVIEWS_DDL)


def push_memo_cards(
    conn: sqlite3.Connection,
    database_id: str,
    batch_size: int = 50,
) -> dict[str, int]:
    """Clean local memos → upsert kind=memo cards. Preserves served_count."""
    ensure_daily_reviews_schema(database_id)

    rows = conn.execute(
        "SELECT slug, content, created_at FROM memos ORDER BY created_at DESC"
    ).fetchall()

    tag_rows = conn.execute(
        """
        SELECT mt.memo_slug, t.name FROM memo_tags mt
        JOIN tags t ON t.id = mt.tag_id
        """
    ).fetchall()
    slug_tags: dict[str, list[str]] = {}
    for tr in tag_rows:
        slug_tags.setdefault(tr["memo_slug"], []).append(tr["name"])

    cards: list[tuple[str, str, str]] = []
    for r in rows:
        content = strip_known_tags(
            to_plain_text(r["content"]),
            slug_tags.get(r["slug"], []),
        ).strip()
        if not content:
            continue
        cards.append((r["slug"], content, (r["created_at"] or "")[:10]))
    cards = dedupe_cards(cards)

    now = str(int(time.time()))
    pushed = 0
    for i in range(0, len(cards), batch_size):
        batch = cards[i : i + batch_size]
        values_parts = []
        for slug, content, date_str in batch:
            values_parts.append(
                f"('memo','{_escape_sql_value(slug)}','{_escape_sql_value(content)}','',"
                f"'{_escape_sql_value(date_str)}',0,'{now}')"
            )
        sql = (
            "INSERT INTO daily_reviews "
            "(kind, slug, content, insight_type, date, served_count, created_at) "
            f"VALUES {','.join(values_parts)} "
            "ON CONFLICT(slug) DO UPDATE SET "
            "kind=excluded.kind, content=excluded.content, "
            "insight_type=excluded.insight_type, date=excluded.date"
        )
        _run_wrangler(database_id, sql)
        pushed += len(batch)
        time.sleep(0.3)

    return {"pushed": pushed, "total_memos": len(rows), "skipped": len(rows) - len(cards)}


def push_insight_card(
    database_id: str,
    insight_type: str,
    content: str | None = None,
    file_path: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Push one LLM-written insight as kind=insight review card."""
    if content is None and file_path is None:
        raise ValueError("content or file_path required")
    if content is None:
        content = Path(file_path).read_text(encoding="utf-8")
    content = (content or "").strip()
    if not content:
        raise ValueError("insight content is empty")

    ensure_daily_reviews_schema(database_id)

    from datetime import date as _date

    day = date or _date.today().isoformat()
    digest = hashlib.sha1(f"{insight_type}:{content}".encode()).hexdigest()[:12]
    slug = f"insight-{insight_type}-{digest}"
    now = str(int(time.time()))

    sql = (
        "INSERT INTO daily_reviews "
        "(kind, slug, content, insight_type, date, served_count, created_at) "
        f"VALUES ('insight','{_escape_sql_value(slug)}','{_escape_sql_value(content)}',"
        f"'{_escape_sql_value(insight_type)}','{_escape_sql_value(day)}',0,'{now}') "
        "ON CONFLICT(slug) DO UPDATE SET "
        "content=excluded.content, insight_type=excluded.insight_type, date=excluded.date"
    )
    _run_wrangler(database_id, sql)
    return {
        "slug": slug,
        "kind": "insight",
        "insight_type": insight_type,
        "content_len": len(content),
        "date": day,
    }
