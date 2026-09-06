"""TDD: CLI surface — insight material command, no MCP."""

from __future__ import annotations

from typer.testing import CliRunner

from flomo_insight.main import app
from flomo_insight.sync.exporter import _upsert_memo
from tests.conftest import make_memo

runner = CliRunner()


def test_insight_cmd_outputs_prompt_and_notes(tmp_conn, monkeypatch):
    for i in range(3):
        _upsert_memo(
            tmp_conn,
            make_memo(slug=f"cli-{i}", content=f"<p>#AI 笔记{i}</p>", created_at=1700000000000 + i),
        )

    class _DummyDb:
        def get_connection(self):
            return tmp_conn

        def migrate(self, conn):
            return None

    monkeypatch.setattr("flomo_insight.cli.context._get_db", lambda: _DummyDb())
    result = runner.invoke(app, ["insight", "topics"])
    assert result.exit_code == 0
    assert "笔记" in result.output or "指令" in result.output
    assert "笔记0" in result.output or "笔记" in result.output


def test_perspectives_lists_both_families(tmp_conn, monkeypatch):
    class _DummyDb:
        def get_connection(self):
            return tmp_conn

        def migrate(self, conn):
            return None

    monkeypatch.setattr("flomo_insight.cli.context._get_db", lambda: _DummyDb())
    result = runner.invoke(app, ["perspectives"])
    assert result.exit_code == 0
    assert "topics" in result.output
    assert "cbt" in result.output


def test_no_mcp_command_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "mcp" not in result.output.lower()


def test_retag_cmd_prints_taxonomy_and_memos(tmp_conn, monkeypatch):
    _upsert_memo(
        tmp_conn,
        make_memo(slug="rt-1", content="<p>#乱标 某条笔记</p>", tags=[{"name": "乱标"}]),
    )

    class _DummyDb:
        def get_connection(self):
            return tmp_conn

        def migrate(self, conn):
            return None

    monkeypatch.setattr("flomo_insight.cli.context._get_db", lambda: _DummyDb())
    result = runner.invoke(app, ["retag", "-n", "5"])
    assert result.exit_code == 0
    assert "分类体系" in result.output or "标签" in result.output
    assert "rt-1" in result.output or "某条笔记" in result.output
    assert "flomo_tag_update" in result.output or "update" in result.output.lower()
