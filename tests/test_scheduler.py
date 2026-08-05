"""Tests for review card content cleaning (to_plain_text)."""

from __future__ import annotations

from src.review.scheduler import strip_known_tags, to_plain_text


# ── HTML stripping ───────────────────────────────────────────────────────────

def test_strips_html_block_tags():
    html = "<p>#效率</p><p>两<span>分钟法则</span></p><div>开始学习</div>"
    assert to_plain_text(html) == "两分钟法则\n开始学习"


def test_handles_lists_and_links():
    html = ('<ul><li>第一项</li><li><a href="/x">第二项</a></li></ul>'
            '<br>换行')
    out = to_plain_text(html)
    assert "第一项" in out
    assert "第二项" in out
    assert "<a" not in out
    assert "换行" in out


def test_unescapes_entities():
    assert to_plain_text("<p>a &amp; b</p>") == "a & b"


def test_empty_and_none():
    assert to_plain_text("") == ""
    assert to_plain_text(None) == ""


# ── tag-line removal ─────────────────────────────────────────────────────────

def test_drops_tag_only_lines():
    """Lines that are just #tags are noise and removed."""
    html = "<p>#情绪</p><p>#效率 </p><p>两分钟法则</p>"
    assert to_plain_text(html) == "两分钟法则"


def test_drops_multi_tag_line():
    html = "<p>#古诗 #哲理 #苏轼</p><p>莫听穿林打叶声</p>"
    assert to_plain_text(html) == "莫听穿林打叶声"


def test_keeps_inline_tag_in_prose():
    """A #tag embedded in real text is content, not a tag row — keep it."""
    html = "<p>这条正文里有 #标签 穿插</p><p>#独立标签行</p>"
    assert to_plain_text(html) == "这条正文里有 #标签 穿插"


def test_keeps_prose_without_tags():
    html = "<p>焦虑的反义词是具体,近义词是懒惰。——《逻辑思维》</p>"
    assert to_plain_text(html) == "焦虑的反义词是具体,近义词是懒惰。——《逻辑思维》"


# ── strip_known_tags ─────────────────────────────────────────────────────────

def test_strips_leading_tag_markers():
    """#tags that lead a line before prose are removed exactly."""
    text = "#微信读书 #商业 #金句获得财富的一个途径"
    assert strip_known_tags(text, ["微信读书", "商业", "金句"]) == "获得财富的一个途径"


def test_strips_tags_after_to_plain_text():
    html = "<p>#微信读书 #焦虑</p><p>反刍式思维 ——《纳瓦尔宝典》</p>"
    plain = to_plain_text(html)
    assert plain == "反刍式思维 ——《纳瓦尔宝典》"


def test_strip_keeps_prose_words_matching_tag():
    """A tag name appearing as prose without '#' is untouched."""
    text = "#苏轼 莫听穿林打叶声,苏轼是宋代词人"
    assert strip_known_tags(text, ["苏轼"]) == "莫听穿林打叶声,苏轼是宋代词人"


def test_strip_longest_tag_first():
    """#金句 shouldn't partially match a longer tag like #金句收藏."""
    text = "#金句收藏 #金句 精华在收藏里"
    assert strip_known_tags(text, ["金句收藏", "金句"]) == "精华在收藏里"


def test_strip_no_tags_returns_text():
    assert strip_known_tags("hello world", []) == "hello world"
    assert strip_known_tags("hello world", ["absent"]) == "hello world"
