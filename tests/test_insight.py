"""Tests for insight engine — all 11 types return non-empty strings."""

from __future__ import annotations

import pytest

from src.insight.engine import generate_insight
from src.sync.exporter import _upsert_memo
from tests.conftest import make_memo


@pytest.fixture
def notes_db(tmp_conn):
    """DB with enough notes for insight generation."""
    contents = [
        "<p>#时间管理 两分钟法则：每个习惯都可以缩减为两分钟版本</p>",
        "<p>#阅读 读书笔记：三体讲述了宇宙社会学</p>",
        "<p>#时间管理 番茄工作法很有效，专注25分钟休息5分钟</p>",
        "<p>#心理学 认知偏误影响决策</p>",
        "<p>#阅读 刻意练习是提升技能的关键</p>",
    ]
    for i, c in enumerate(contents):
        _upsert_memo(tmp_conn, make_memo(slug=f"ins-{i}", content=c, created_at=1700000000000 + i))
    return tmp_conn


ANALYTICAL_TYPES = ["topics", "stagnant", "declining", "connections", "draft"]
PERSPECTIVE_TYPES = ["default", "value-clarification", "inversion", "second-order", "cbt", "mbti"]
ALL_TYPES = ANALYTICAL_TYPES + PERSPECTIVE_TYPES


@pytest.mark.parametrize("insight_type", ANALYTICAL_TYPES)
def test_analytical_insight_returns_nonempty(notes_db, insight_type):
    result = generate_insight(notes_db, insight_type)
    assert isinstance(result, str)
    assert len(result) > 100, f"{insight_type} returned too-short output"
    # Should contain the instruction marker
    assert "指令" in result or "笔记" in result


@pytest.mark.parametrize("insight_type", PERSPECTIVE_TYPES)
def test_perspective_insight_returns_nonempty(notes_db, insight_type):
    result = generate_insight(notes_db, insight_type)
    assert isinstance(result, str)
    assert len(result) > 100, f"{insight_type} returned too-short output"


def test_unknown_type_raises(notes_db):
    with pytest.raises(ValueError, match="Unknown insight type"):
        generate_insight(notes_db, "nonexistent")


def test_empty_db_raises(tmp_conn):
    """No notes synced → insight should raise with helpful message."""
    with pytest.raises(ValueError, match="No notes found"):
        generate_insight(tmp_conn, "topics")


def test_topics_insight_contains_notes(notes_db):
    """topics insight must include actual note content for the LLM to read."""
    result = generate_insight(notes_db, "topics")
    assert "两分钟法则" in result or "时间管理" in result


def test_connections_includes_tag_hint(notes_db):
    """connections insight includes tag co-occurrence hint when available."""
    result = generate_insight(notes_db, "connections")
    # Should mention notes
    assert "笔记" in result


def test_perspective_includes_system_prompt(notes_db):
    """Perspective insight must include the perspective's system prompt."""
    result = generate_insight(notes_db, "cbt")
    # CBT prompt mentions cognitive distortions
    assert "认知" in result or "思维" in result or "CBT" in result or "扭曲" in result


def test_insight_does_not_reference_removed_tables(notes_db):
    """Guard: insight output must not crash by querying removed cluster tables."""
    for t in ALL_TYPES:
        # Each must complete without OperationalError
        result = generate_insight(notes_db, t)
        assert isinstance(result, str)
