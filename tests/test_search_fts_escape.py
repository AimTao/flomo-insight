"""TDD: FTS query must not treat hyphens as column filters."""

from flomo_insight.search.engine import _escape_fts5
from flomo_insight.sync.exporter import _upsert_memo
from tests.conftest import make_memo


def test_escape_fts5_strips_column_like_tokens():
    q = _escape_fts5("flomo-insight-lab")
    assert ":" not in q
    assert "-" not in q or '"' in q
    # should be safe to MATCH
    assert q


def test_search_lab_marker_does_not_crash(tmp_conn):
    from flomo_insight.search.engine import search

    _upsert_memo(
        tmp_conn,
        make_memo(slug="s1", content="<p>flomo-insight-lab-123 测试</p>"),
    )
    hits, total = search(tmp_conn, "flomo-insight-lab")
    assert total >= 1
    assert hits
