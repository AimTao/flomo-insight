"""Tests for FTS5 search, tag filtering, recent, tags, stats."""

from __future__ import annotations

import pytest

from src.search.engine import search, recent_memos, get_tags, db_stats
from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


@pytest.fixture
def populated_db(tmp_conn):
    """DB with a few tagged memos for search tests."""
    memos = [
        make_memo(slug="s1", content="<p>时间管理 两分钟法则</p>",
                  tags=[{"name": "时间管理"}], created_at=1700000000000),
        make_memo(slug="s2", content="<p>番茄工作法很有效</p>",
                  tags=[{"name": "时间管理"}], created_at=1700100000000),
        make_memo(slug="s3", content="<p>读书笔记 三体</p>",
                  tags=[{"name": "阅读"}], created_at=1700200000000),
        make_memo(slug="s4", content="<p>时间管理 番茄钟</p>",
                  tags=[{"name": "时间管理"}, {"name": "效率"}], created_at=1700300000000),
    ]
    for m in memos:
        _upsert_memo(tmp_conn, m)
    return tmp_conn


def test_search_finds_matching(populated_db):
    hits, total = search(populated_db, "时间管理")
    assert total >= 1
    assert any("时间管理" in h.content for h in hits)


def test_search_returns_snippet(populated_db):
    hits, _ = search(populated_db, "番茄")
    assert len(hits) >= 1
    # snippet should contain the match marker or content
    assert hits[0].snippet


def test_search_no_results(populated_db):
    hits, total = search(populated_db, "不存在的关键词zzz")
    assert total == 0
    assert hits == []


def test_search_with_tag_filter(populated_db):
    """Filter to memos tagged 时间管理."""
    hits, total = search(populated_db, "番茄", tags=["时间管理"])
    assert total >= 1
    assert all("时间管理" in h.tags for h in hits)


def test_search_with_multiple_tags_and(populated_db):
    """AND logic: must have both tags."""
    hits, total = search(populated_db, "番茄", tags=["时间管理", "效率"])
    # only s4 has both tags and contains 番茄
    assert total == 1
    assert hits[0].slug == "s4"


def test_search_tag_filter_excludes(populated_db):
    """Tag filter excludes memos without the tag."""
    hits, total = search(populated_db, "时间", tags=["阅读"])
    # s3 has 阅读 but no "时间" in content
    assert total == 0


def test_search_limit(populated_db):
    hits, total = search(populated_db, "时间管理", limit=1)
    assert len(hits) == 1
    assert total >= 2  # total is unfiltered count


def test_search_offset(populated_db):
    hits1, _ = search(populated_db, "时间管理", limit=10, offset=0)
    hits2, _ = search(populated_db, "时间管理", limit=10, offset=1)
    # offset shifts results
    if len(hits1) > 1:
        assert hits1[1].slug == hits2[0].slug


# ── recent_memos ─────────────────────────────────────────────────────────────


def test_recent_ordered_desc(populated_db):
    hits = recent_memos(populated_db, limit=10)
    # most recent first (s4 has latest created_at)
    assert hits[0].slug == "s4"


def test_recent_limit(populated_db):
    hits = recent_memos(populated_db, limit=2)
    assert len(hits) == 2


# ── get_tags ─────────────────────────────────────────────────────────────────


def test_tags_count_sort(populated_db):
    tags = get_tags(populated_db, sort_by="count")
    # 时间管理 appears 3 times, most frequent
    assert tags[0]["name"] == "时间管理"
    assert tags[0]["count"] == 3


def test_tags_name_sort(populated_db):
    tags = get_tags(populated_db, sort_by="name")
    names = [t["name"] for t in tags]
    assert names == sorted(names)


# ── db_stats ─────────────────────────────────────────────────────────────────


def test_db_stats(populated_db):
    stats = db_stats(populated_db)
    assert stats["total_memos"] == 4
    assert stats["total_tags"] == 3  # 时间管理, 阅读, 效率
    # last_sync may be "never" if not set
    assert "last_sync" in stats


def test_db_stats_no_embeddings_or_clusters_field(populated_db):
    """After removing clustering, stats must not reference those tables."""
    stats = db_stats(populated_db)
    assert "total_embeddings" not in stats
    assert "total_clusters" not in stats
