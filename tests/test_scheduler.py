"""Tests for the spaced-repetition review scheduler."""

from __future__ import annotations

import pytest

from src.review.scheduler import (
    ensure_scheduled,
    get_due,
    mark_done,
    overview,
    record_grade,
    set_hook,
    to_plain_text,
    MAX_INTERVAL_DAYS,
)
from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


@pytest.fixture
def sched_db(tmp_conn):
    """DB with 5 memos, all scheduled for review."""
    for i in range(5):
        _upsert_memo(tmp_conn, make_memo(
            slug=f"s-{i}", content=f"<p>memo {i}</p>",
            created_at=1700000000000 + i, updated_at=1700000000000 + i,
        ))
    tmp_conn.commit()
    return tmp_conn


# ── ensure_scheduled ─────────────────────────────────────────────────────────

def test_ensure_scheduled_spreads_over_days(sched_db):
    created = ensure_scheduled(sched_db)
    assert created == 5

    due_at = [r["due_at"] for r in sched_db.execute(
        "SELECT due_at FROM review_state").fetchall()]
    # All due within the 30-day spread window
    assert len(due_at) == 5
    assert len(set(due_at)) >= 2  # spread, not all same day


def test_ensure_scheduled_idempotent(sched_db):
    ensure_scheduled(sched_db)
    assert ensure_scheduled(sched_db) == 0


def test_ensure_scheduled_new_memos_after_backfill(sched_db):
    ensure_scheduled(sched_db)
    _upsert_memo(sched_db, make_memo(slug="s-new", content="<p>new one</p>"))
    assert ensure_scheduled(sched_db) == 1


# ── get_due ──────────────────────────────────────────────────────────────────

def test_get_due_returns_plain_text_content(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    due = get_due(sched_db, today="2026-01-30")
    assert len(due) == 5
    for d in due:
        assert "<p>" not in d["content"]
        assert d["content"].strip() == d["content"]
        assert "hook" in d
        assert "state" in d


def test_get_due_excludes_marked_done(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    first = get_due(sched_db, today="2026-01-30")[0]
    mark_done(sched_db, first["slug"], today="2026-01-30")
    again = get_due(sched_db, today="2026-01-30")
    assert first["slug"] not in {d["slug"] for d in again}


def test_get_due_respects_limit(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    assert len(get_due(sched_db, today="2026-01-30", limit=2)) == 2


# ── record_grade ─────────────────────────────────────────────────────────────

def test_record_grade_good_doubles_interval(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    due = get_due(sched_db, today="2026-01-30", limit=1)[0]

    r1 = record_grade(sched_db, due["slug"], "good", today="2026-01-30")
    assert r1["interval_days"] == 2  # 1 * 2
    assert r1["due_at"] == "2026-02-01"
    assert r1["review_count"] == 1
    assert r1["state"] == "review"

    r2 = record_grade(sched_db, due["slug"], "good", today="2026-02-01")
    assert r2["interval_days"] == 4  # 2 * 2
    assert r2["due_at"] == "2026-02-05"


def test_record_grade_easy_triples_capped(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    due = get_due(sched_db, today="2026-01-30", limit=1)[0]

    # Push interval up to the cap
    r = record_grade(sched_db, due["slug"], "easy", today="2026-01-30")
    assert r["interval_days"] == 3
    assert r["interval_days"] <= MAX_INTERVAL_DAYS


def test_record_grade_again_resets_to_one(sched_db):
    ensure_scheduled(sched_db, today="2026-01-01")
    due = get_due(sched_db, today="2026-01-30", limit=1)[0]

    record_grade(sched_db, due["slug"], "good", today="2026-01-30")  # → 2d
    r = record_grade(sched_db, due["slug"], "again", today="2026-01-31")
    assert r["interval_days"] == 1
    assert r["state"] == "learning"
    assert r["due_at"] == "2026-02-01"


def test_record_grade_unknown_slug_raises(sched_db):
    ensure_scheduled(sched_db)
    with pytest.raises(KeyError):
        record_grade(sched_db, "missing", "good")


def test_record_grade_invalid_grade_raises(sched_db):
    ensure_scheduled(sched_db)
    due = get_due(sched_db, limit=1)[0]
    with pytest.raises(ValueError, match="grade"):
        record_grade(sched_db, due["slug"], "maybe")


# ── set_hook / overview ──────────────────────────────────────────────────────

def test_set_hook(sched_db):
    ensure_scheduled(sched_db)
    due = get_due(sched_db, limit=1)[0]
    set_hook(sched_db, due["slug"], "  这招现在还在用吗?  ")
    assert get_due(sched_db, limit=1)[0]["hook"] == "这招现在还在用吗?"


def test_overview_counts(sched_db):
    ensure_scheduled(sched_db)
    stats = overview(sched_db)
    assert stats["new"] == 5
    assert stats["unscheduled"] == 0
    assert stats["done"] == 0


# ── to_plain_text ────────────────────────────────────────────────────────────

def test_to_plain_text_strips_html():
    html = "<p>#效率</p><p>两<span>分钟法则</span></p><div>开始学习</div>"
    assert to_plain_text(html) == "#效率\n两分钟法则\n开始学习"


def test_to_plain_text_handles_lists_and_links():
    html = ('<ul><li>第一项</li><li><a href="/x">第二项</a></li></ul>'
            '<br>换行')
    out = to_plain_text(html)
    assert "第一项" in out
    assert "第二项" in out
    assert "<a" not in out
    assert "换行" in out


def test_to_plain_text_unescapes_entities():
    assert to_plain_text("<p>a &amp; b</p>") == "a & b"
