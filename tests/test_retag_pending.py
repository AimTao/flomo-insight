"""TDD: retag only processes memos with tags_llm_at IS NULL."""

from __future__ import annotations

from flomo_insight.sync.exporter import _upsert_memo
from flomo_insight.tags.classifier import (
    build_retag_prompt,
    count_pending_retag,
    mark_tags_llm_optimized,
)
from tests.conftest import make_memo


def _seed(conn):
    _upsert_memo(conn, make_memo(slug="pend-1", content="<p>#旧 待优化</p>", tags=[{"name": "旧"}]))
    _upsert_memo(conn, make_memo(slug="done-1", content="<p>#AI 已优化</p>", tags=[{"name": "AI"}]))
    conn.execute("UPDATE memos SET tags_llm_at = '2026-01-01T00:00:00+00:00' WHERE slug='done-1'")
    conn.commit()


def test_count_pending(tmp_conn):
    _seed(tmp_conn)
    stats = count_pending_retag(tmp_conn)
    assert stats["total"] == 2
    assert stats["optimized"] == 1
    assert stats["pending"] == 1


def test_retag_prompt_skips_optimized(tmp_conn):
    _seed(tmp_conn)
    prompt = build_retag_prompt(tmp_conn, batch_size=10)
    assert "pend-1" in prompt or "待优化" in prompt
    assert "done-1" not in prompt
    assert "已优化" not in prompt
    assert "tags-optimized" in prompt


def test_retag_prompt_all_includes_optimized(tmp_conn):
    _seed(tmp_conn)
    prompt = build_retag_prompt(tmp_conn, batch_size=10, include_optimized=True)
    assert "done-1" in prompt or "已优化" in prompt


def test_mark_optimized(tmp_conn):
    _seed(tmp_conn)
    n = mark_tags_llm_optimized(tmp_conn, ["pend-1"])
    assert n == 1
    row = tmp_conn.execute("SELECT tags_llm_at FROM memos WHERE slug='pend-1'").fetchone()
    assert row["tags_llm_at"]
    assert count_pending_retag(tmp_conn)["pending"] == 0


def test_retag_empty_when_all_optimized(tmp_conn):
    _seed(tmp_conn)
    mark_tags_llm_optimized(tmp_conn, ["pend-1", "done-1"])
    prompt = build_retag_prompt(tmp_conn)
    assert "没有待" in prompt or "pending" in prompt.lower() or "tags_llm_at" in prompt
