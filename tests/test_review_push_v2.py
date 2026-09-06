"""TDD: review-push upsert (no DROP) + insight-push kind=insight."""

from __future__ import annotations

import json
from pathlib import Path

from flomo_insight.review.push import (
    ensure_daily_reviews_schema,
    push_insight_card,
    push_memo_cards,
)
from flomo_insight.sync.exporter import _upsert_memo
from tests.conftest import make_memo


class _Recorder:
    """Fake wrangler that records SQL and pretends D1 returns empty results."""

    def __init__(self):
        self.sqls: list[str] = []

    def __call__(self, database_id: str, sql: str):
        self.sqls.append(sql)
        return [{"results": []}]


def test_ensure_schema_never_drops(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("flomo_insight.review.push._run_wrangler", rec)
    ensure_daily_reviews_schema("db-uuid")
    joined = "\n".join(rec.sqls)
    assert "DROP TABLE" not in joined
    assert "ALTER TABLE" not in joined
    assert "CREATE TABLE IF NOT EXISTS daily_reviews" in joined
    assert "kind" in joined
    assert "insight_type" in joined
    assert "served_count" in joined


def test_ensure_schema_no_legacy_alter(monkeypatch):
    """Latest schema only — never ALTER for old tables."""
    rec = _Recorder()
    monkeypatch.setattr("flomo_insight.review.push._run_wrangler", rec)
    ensure_daily_reviews_schema("db-uuid")
    joined = "\n".join(rec.sqls)
    assert "ALTER" not in joined.upper()
    assert "pragma" not in joined.lower()


def test_push_memo_cards_upserts_without_resetting_served(tmp_conn, monkeypatch, tmp_path):
    _upsert_memo(
        tmp_conn,
        make_memo(slug="m1", content="<p>#效率 两分钟法则</p>", tags=[{"name": "效率"}]),
    )
    rec = _Recorder()
    monkeypatch.setattr("flomo_insight.review.push._run_wrangler", rec)
    monkeypatch.setattr("flomo_insight.review.push.time.sleep", lambda _: None)
    monkeypatch.setattr("flomo_insight.config.require_d1_database_id", lambda: "db-uuid")

    result = push_memo_cards(tmp_conn, "db-uuid")
    inserts = [s for s in rec.sqls if "INSERT INTO daily_reviews" in s]
    assert result["pushed"] == 1
    assert len(inserts) == 1
    sql = inserts[0]
    assert "'m1'" in sql
    assert "kind" in sql
    assert "'memo'" in sql
    assert "两分钟法则" in sql
    assert "#效率" not in sql
    # must not force served_count back to 0 on conflict of existing cards
    assert "served_count=excluded.served_count" not in sql
    assert "ON CONFLICT" in sql


def test_push_insight_card_kind_insight(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("flomo_insight.review.push._run_wrangler", rec)
    monkeypatch.setattr("flomo_insight.review.push.time.sleep", lambda _: None)

    md = tmp_write = None
    content = "# 洞察\n\n核心主题是效率与专注。"
    result = push_insight_card(
        "db-uuid",
        insight_type="topics",
        content=content,
        date="2026-08-05",
    )
    inserts = [s for s in rec.sqls if "INSERT INTO daily_reviews" in s]
    assert result["kind"] == "insight"
    assert len(inserts) == 1
    sql = inserts[0]
    assert "'insight'" in sql
    assert "'topics'" in sql
    assert "效率与专注" in sql
    assert "slug" in sql


def test_push_insight_from_file(tmp_path, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("flomo_insight.review.push._run_wrangler", rec)
    monkeypatch.setattr("flomo_insight.review.push.time.sleep", lambda _: None)
    f = tmp_path / "insight.md"
    f.write_text("## 结论\n\n你的时间分配失衡。", encoding="utf-8")
    result = push_insight_card("db-uuid", insight_type="cbt", file_path=str(f))
    assert result["content_len"] > 0
    assert any("失衡" in s for s in rec.sqls)
