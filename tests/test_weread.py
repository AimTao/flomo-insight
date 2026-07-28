"""Tests for WeRead importer — dedup and prompt building (no network)."""

from __future__ import annotations

import pytest

from src.importers.weread import (
    fetch_reviewed_highlights,
    mark_imported,
    build_import_prompt,
    build_weread_stats,
)
from src.db import DatabaseManager


def _mock_weread_client(books_with_highlights):
    """books_with_highlights: [{book_id, title, author, bookmarks:[{bookmarkId, markText, range, chapterName}], reviews:[{reviewId, content, range, chapterName}]}]"""
    from unittest.mock import MagicMock
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)

    notebooks = [
        {"book": {"bookId": b["book_id"], "title": b["title"], "author": b.get("author", "")},
         "noteCount": len(b["bookmarks"]), "reviewCount": len(b["reviews"])}
        for b in books_with_highlights
    ]
    client.get_notebooks = MagicMock(return_value=notebooks)

    def get_bookmarks(book_id):
        for b in books_with_highlights:
            if b["book_id"] == book_id:
                return b["bookmarks"]
        return []

    def get_reviews(book_id):
        for b in books_with_highlights:
            if b["book_id"] == book_id:
                return b["reviews"]
        return []

    client.get_bookmarks = get_bookmarks
    client.get_reviews = get_reviews
    return client


@pytest.fixture
def weread_data():
    return [
        {
            "book_id": "bk1",
            "title": "测试书",
            "author": "作者A",
            "bookmarks": [
                {"bookmarkId": "bm1", "markText": "划线内容一", "range": "100-110", "chapterName": "第一章"},
                {"bookmarkId": "bm2", "markText": "划线内容二", "range": "200-210", "chapterName": "第二章"},
            ],
            "reviews": [
                {"reviewId": "rv1", "content": "这段话让我想到...", "range": "100-110", "chapterName": "第一章"},
            ],
        }
    ]


def test_fetch_returns_matched_pairs(tmp_db, weread_data):
    """Only reviews that match a bookmark by range are returned."""
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    client = _mock_weread_client(weread_data)

    items = fetch_reviewed_highlights(client, conn, batch_size=10)
    conn.close()

    assert len(items) == 1
    item = items[0]
    assert item["review_id"] == "rv1"
    assert item["mark_text"] == "划线内容一"  # matched by range 100-110
    assert item["review_text"] == "这段话让我想到..."
    assert item["book_title"] == "测试书"


def test_fetch_dedup_already_imported(tmp_db, weread_data):
    """Already-imported review_ids are skipped."""
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    # Pre-mark rv1 as imported
    mark_imported(conn, "rv1", "bk1", "测试书", "划线内容一")

    client = _mock_weread_client(weread_data)
    items = fetch_reviewed_highlights(client, conn, batch_size=10)
    conn.close()

    assert items == []  # rv1 already imported


def test_fetch_skips_review_without_matching_highlight(tmp_db):
    """Review with no matching bookmark range → uses abstract, or skipped if no abstract."""
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    data = [{
        "book_id": "bk2", "title": "书B", "author": "",
        "bookmarks": [{"bookmarkId": "bmX", "markText": "原文", "range": "1-2"}],
        "reviews": [{"reviewId": "rvX", "content": "想法", "range": "999-999"}],  # no match
    }]
    client = _mock_weread_client(data)
    items = fetch_reviewed_highlights(client, conn, batch_size=10)
    conn.close()
    # No abstract → skipped (mark_text too short / none)
    assert items == []


def test_mark_imported_idempotent(tmp_db):
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    mark_imported(conn, "rv1", "bk1", "书", "text")
    mark_imported(conn, "rv1", "bk1", "书", "text")  # second time no error
    count = conn.execute("SELECT COUNT(*) FROM weread_imports WHERE review_id='rv1'").fetchone()[0]
    conn.close()
    assert count == 1


def test_build_import_prompt_empty():
    result = build_import_prompt([])
    assert "No new" in result or "没有" in result or len(result) < 50


def test_build_import_prompt_contains_mandatory_tag(tmp_db, weread_data):
    """Prompt must instruct to use #微信读书 tag."""
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    client = _mock_weread_client(weread_data)
    items = fetch_reviewed_highlights(client, conn, batch_size=10)
    prompt = build_import_prompt(items)
    conn.close()

    assert "微信读书" in prompt
    assert "测试书" in prompt
    assert "划线内容一" in prompt


def test_build_weread_stats(tmp_db):
    conn = tmp_db.get_connection()
    tmp_db.migrate(conn)
    mark_imported(conn, "rv1", "bk1", "书A", "t1")
    mark_imported(conn, "rv2", "bk1", "书A", "t2")
    mark_imported(conn, "rv3", "bk2", "书B", "t3")

    stats = build_weread_stats(conn)
    conn.close()

    assert stats["total_imported"] == 3
    titles = {b["title"]: b["count"] for b in stats["books"]}
    assert titles["书A"] == 2
    assert titles["书B"] == 1
