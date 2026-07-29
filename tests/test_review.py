"""Tests for review two-phase engine (overview + deep-dive)."""

from __future__ import annotations

import pytest
from tests.conftest import make_memo
from src.sync.exporter import _upsert_memo


@pytest.fixture
def review_db(tmp_conn):
    """Database with diverse memos for review testing."""
    memos = [
        make_memo(slug="r1", content="<p>#效率 番茄工作法真的有用吗</p>",
                  tags=[{"name": "效率"}], created_at=1700000000000,
                  updated_at=1700000000000),
        make_memo(slug="r2", content="<p>#效率 两分钟法则实践</p>",
                  tags=[{"name": "效率"}], created_at=1700100000000,
                  updated_at=1700100000000),
        make_memo(slug="r3", content="<p>#效率 批量处理邮件技巧</p>",
                  tags=[{"name": "效率"}], created_at=1700200000000,
                  updated_at=1700200000000),
        make_memo(slug="r4", content="<p>#拖延 今天又没写周报</p>",
                  tags=[{"name": "拖延"}], created_at=1700300000000,
                  updated_at=1700300000000),
        make_memo(slug="r5", content="<p>#拖延 #效率 不是懒，是怕做不好</p>",
                  tags=[{"name": "拖延"}, {"name": "效率"}],
                  created_at=1700400000000, updated_at=1700400000000),
    ]
    for m in memos:
        _upsert_memo(tmp_conn, m)

    tmp_conn.execute("""
        INSERT INTO weread_imports (review_id, book_id, book_title, mark_text, flomo_slug)
        VALUES ('w1','b1','测试书','划线1','r1'),
               ('w2','b1','测试书','划线2','r2')
    """)
    tmp_conn.commit()

    return tmp_conn


# ── Phase 1: Overview ──────────────────────────────────────────────────────

def test_overview_returns_four_strategies(review_db):
    from src.review.engine import get_overview

    overview = get_overview(review_db)

    assert set(overview.keys()) == {"same_book", "tag_cluster", "near_time", "co_tag"}


def test_overview_has_samples_not_full_content(review_db):
    from src.review.engine import get_overview

    overview = get_overview(review_db)

    for pool in overview["tag_cluster"]:
        assert "samples" in pool
        assert "total_memos" in pool
        assert "tag_distribution" in pool
        assert "notes" not in pool  # overview never has full content
        for s in pool["samples"]:
            assert len(s) <= 83  # 80 chars + "..." max


def test_overview_same_book(review_db):
    from src.review.engine import get_overview

    overview = get_overview(review_db)

    books = {p["label"]: p for p in overview["same_book"]}
    assert "测试书" in books
    assert books["测试书"]["total_memos"] == 2


def test_overview_tag_cluster_returns_all_tags(review_db):
    """No HAVING filter — all tags included, even with 1 memo."""
    from src.review.engine import get_overview

    overview = get_overview(review_db)
    labels = {p["label"] for p in overview["tag_cluster"]}

    assert "效率" in labels  # 4 memos
    assert "拖延" in labels  # 2 memos


def test_overview_co_tag(review_db):
    from src.review.engine import get_overview

    overview = get_overview(review_db)
    labels = {p["label"] for p in overview["co_tag"]}

    assert "效率 × 拖延" in labels


# ── Phase 2: Deep-dive ─────────────────────────────────────────────────────

def test_get_pool_same_book(review_db):
    from src.review.engine import get_pool

    pool = get_pool(review_db, "same_book", "测试书")

    assert pool is not None
    assert pool["total_memos"] == 2
    assert len(pool["notes"]) == 2
    for note in pool["notes"]:
        assert "slug" in note
        assert "content" in note
        assert "tags" in note
        assert "date" in note
        assert "source" in note
        # Full content, not truncated (> 0 means content is present)
        assert len(note["content"]) > 0


def test_get_pool_tag_cluster(review_db):
    from src.review.engine import get_pool

    pool = get_pool(review_db, "tag_cluster", "效率")

    assert pool is not None
    assert pool["total_memos"] == 4  # r1, r2, r3, r5


def test_get_pool_near_time(review_db):
    from src.review.engine import get_pool, get_overview

    # Get the actual date from the overview
    overview = get_overview(review_db)
    date_pools = overview["near_time"]
    assert len(date_pools) > 0
    test_date = date_pools[0]["label"]
    expected_count = date_pools[0]["total_memos"]

    pool = get_pool(review_db, "near_time", test_date)

    assert pool is not None
    assert pool["total_memos"] == expected_count


def test_get_pool_co_tag(review_db):
    from src.review.engine import get_pool

    pool = get_pool(review_db, "co_tag", "效率 × 拖延")

    assert pool is not None
    assert pool["total_memos"] == 1  # only r5


def test_get_pool_unknown_returns_none(review_db):
    from src.review.engine import get_pool

    assert get_pool(review_db, "same_book", "不存在的书") is None
    assert get_pool(review_db, "tag_cluster", "不存在的标签") is None


# ── Legacy compat ──────────────────────────────────────────────────────────

def test_legacy_find_groups_still_works(review_db):
    from src.review.engine import find_groups

    groups = find_groups(review_db, count_per_strategy=3)
    assert isinstance(groups, list)
    for g in groups:
        assert "slugs" in g
        assert "contents" in g
        assert "strategy" in g
        assert len(g["slugs"]) == len(g["contents"])
