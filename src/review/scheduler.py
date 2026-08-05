"""Daily review scheduler — spaced repetition over flomo memos.

The scheduler owns *when* a memo is reviewed. Content stays the user's own
memo; the LLM only writes a one-line "hook" (see .claude/skills/review.md).

Pure SQL + a simplified SM-2 curve:
  new      → due_at spread over the next SCHEDULE_SPREAD days
  again    → relearn: interval 1 day
  hard     → interval × 1.3
  good     → interval × 2.0
  easy     → interval × 3.0, capped at MAX_INTERVAL_DAYS

All timestamps are "YYYY-MM-DD" local dates. "Today" is the machine's
local date (the same date the user writes their notes, so a memo created
today is eligible for an intro slot a few days later).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any

GRADES = ("again", "hard", "good", "easy")

INITIAL_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 60
SCHEDULE_SPREAD_DAYS = 30  # new memos are spread over the next 30 days

INTERVAL_MULTIPLIER = {
    "again": 1.0,  # relearn — reset to 1 day regardless of prior interval
    "hard": 1.3,
    "good": 2.0,
    "easy": 3.0,
}


# ── HTML → plain text for card content ───────────────────────────────────────

# Block-level tags become a newline so <p>/<li>/<div> structure reads as lines.
_BLOCK_TAGS = (
    r"</?(p|div|li|ul|ol|blockquote|h[1-6])([^>]*)>"
)
_BR_TAG = r"<br\s*/?>"
_OTHER_TAGS = r"<[^>]+>"


def to_plain_text(html: str) -> str:
    """Convert flomo memo HTML to readable plain text (line per block).

    flomo memo content is HTML (e.g. <p>, <ul>/<li>, <span>, <div>). The
    review card must read as a plain-text note, not raw markup.
    """
    text = html or ""
    text = re.sub(_BLOCK_TAGS, "\n", text)
    text = re.sub(_BR_TAG, "\n", text)
    text = re.sub(_OTHER_TAGS, "", text)
    text = unescape(text)
    # Keep one line per block: trim, drop empties, collapse blank lines.
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


# ── Date helpers ──────────────────────────────────────────────────────────────


def _today() -> str:
    return date.today().isoformat()


def _days_from_today(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _hours_since_midnight(slug: str) -> int:
    """Deterministic pseudo-random 0-23 hash of a slug.

    Used to spread same-day creates across the day, so a batch of notes
    created in one sync don't all land on the same clock slot.
    """
    h = 0
    for ch in slug:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % 24


# ── Scheduling core ───────────────────────────────────────────────────────────


def ensure_scheduled(conn: sqlite3.Connection, today: str | None = None) -> int:
    """Assign due dates to memos that have no review_state row.

    New memos are spread deterministically across the next
    SCHEDULE_SPREAD_DAYS days (offset = slug hash % spread), which
    keeps a backfilled library from flooding day one while still
    introducing notes from today's batch soon.

    Returns the number of schedules created.
    """
    if today is None:
        today = _today()
    missing = conn.execute(
        """SELECT m.slug, m.created_at FROM memos m
           LEFT JOIN review_state r ON r.slug = m.slug
           WHERE r.slug IS NULL"""
    ).fetchall()
    if not missing:
        return 0

    rows = []
    for m in missing:
        offset = _hours_since_midnight(m["slug"]) % SCHEDULE_SPREAD_DAYS
        due = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=offset)).date()
        rows.append((m["slug"], due.isoformat()))

    conn.executemany(
        "INSERT INTO review_state (slug, state, due_at) VALUES (?, 'new', ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def get_due(
    conn: sqlite3.Connection,
    today: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return memos whose review_state.due_at <= today, oldest first.

    Each entry includes full memo content + tags, so the caller can render
    the review queue in one shot. Memos marked done for today (state='done')
    are excluded — a memo only surfaces once per day.
    """
    if today is None:
        today = _today()
    rows = conn.execute(
        """SELECT r.slug, r.state, r.due_at, r.interval_days, r.ease,
                  r.review_count, r.hook, m.content, m.created_at
           FROM review_state r
           JOIN memos m ON m.slug = r.slug
           WHERE r.due_at <= ? AND r.state != 'done'
           ORDER BY r.due_at ASC
           LIMIT ?""",
        (today, limit),
    ).fetchall()
    if not rows:
        return []

    slugs = [r["slug"] for r in rows]
    placeholders = ",".join("?" * len(slugs))
    tag_rows = conn.execute(
        f"""SELECT mt.memo_slug, t.name FROM memo_tags mt
            JOIN tags t ON t.id = mt.tag_id
            WHERE mt.memo_slug IN ({placeholders})""",
        tuple(slugs),
    ).fetchall()
    tag_map: dict[str, list[str]] = {}
    for tr in tag_rows:
        tag_map.setdefault(tr["memo_slug"], []).append(tr["name"])

    return [
        {
            "slug": r["slug"],
            "content": to_plain_text(r["content"]),
            "tags": tag_map.get(r["slug"], []),
            "date": (r["created_at"] or "")[:10],
            "state": r["state"],
            "due_at": r["due_at"],
            "review_count": r["review_count"],
            "hook": r["hook"],
        }
        for r in rows
    ]


def record_grade(
    conn: sqlite3.Connection,
    slug: str,
    grade: str,
    today: str | None = None,
) -> dict[str, Any]:
    """Record a review grade for one memo and advance its schedule.

    Grades follow a simplified SM-2:
      again → interval resets to 1 day
      hard  → interval = max(1, round(interval × 1.3))
      good  → interval = max(1, round(interval × 2))
      easy  → interval = max(1, round(interval × 3)) capped at 60

    Returns the updated schedule row (or raises KeyError for unknown slug).
    """
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}, got {grade!r}")
    if today is None:
        today = _today()

    row = conn.execute(
        "SELECT slug, state, interval_days, ease, review_count FROM review_state WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no review_state for memo {slug}")

    prior_interval = row["interval_days"] or INITIAL_INTERVAL_DAYS
    if grade == "again":
        interval = INITIAL_INTERVAL_DAYS
        state = "learning"
    else:
        interval = max(1, round(prior_interval * INTERVAL_MULTIPLIER[grade]))
        interval = min(interval, MAX_INTERVAL_DAYS)
        state = "review"

    due = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=interval)).date()
    conn.execute(
        """UPDATE review_state
           SET state = ?, interval_days = ?, due_at = ?, last_reviewed_at = ?,
               review_count = review_count + 1
           WHERE slug = ?""",
        (state, interval, due.isoformat(), today, slug),
    )
    conn.commit()

    return {
        "slug": slug,
        "grade": grade,
        "state": state,
        "interval_days": interval,
        "due_at": due.isoformat(),
        "review_count": row["review_count"] + 1,
    }


def set_hook(
    conn: sqlite3.Connection,
    slug: str,
    hook: str,
) -> None:
    """Store the one-line review hook for a memo (written by the LLM)."""
    conn.execute(
        "UPDATE review_state SET hook = ? WHERE slug = ?",
        (hook.strip(), slug),
    )
    conn.commit()


def mark_done(
    conn: sqlite3.Connection,
    slug: str,
    today: str | None = None,
) -> None:
    """Mark a memo as reviewed for today without advancing its interval.

    Used when the user reads a due memo but doesn't grade it — it won't
    re-surface until tomorrow.
    """
    if today is None:
        today = _today()
    conn.execute(
        """UPDATE review_state SET state = 'done', due_at = ?, last_reviewed_at = ?
           WHERE slug = ? AND due_at <= ?""",
        (today, today, slug, today),
    )
    conn.commit()


def overview(conn: sqlite3.Connection) -> dict[str, int]:
    """Counts by review state — for CLI /stats and sanity checks."""
    rows = conn.execute(
        "SELECT state, COUNT(*) AS n FROM review_state GROUP BY state"
    ).fetchall()
    out = {"new": 0, "learning": 0, "review": 0, "done": 0, "unscheduled": 0}
    for r in rows:
        if r["state"] in out:
            out[r["state"]] = r["n"]
    total_memos = conn.execute("SELECT COUNT(*) AS n FROM memos").fetchone()["n"]
    out["unscheduled"] = max(0, total_memos - sum(out.values()))
    return out
