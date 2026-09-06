"""LLM-driven insight engine — note fetching + system prompts.

No pre-computed analysis. No clustering. No embeddings.
All insights: fetch raw notes from SQLite, wrap with a system prompt,
return the package for Claude Code to interpret.
"""

from __future__ import annotations

import sqlite3
from typing import Callable


def generate_insight(conn: sqlite3.Connection, insight_type: str) -> str:
    from flomo_insight.insight.templates import PERSPECTIVES

    if insight_type in PERSPECTIVES:
        from flomo_insight.insight.templates import fetch_notes_for_perspective
        return fetch_notes_for_perspective(conn, insight_type)

    builders: dict[str, Callable] = {
        "topics": _build_topics,
        "stagnant": _build_stagnant,
        "declining": _build_declining,
        "connections": _build_connections,
        "draft": _build_draft,
    }
    if insight_type not in builders:
        valid = ", ".join(list(builders.keys()) + list(PERSPECTIVES.keys()))
        raise ValueError(f"Unknown insight type: {insight_type}. Valid: {valid}")
    return builders[insight_type](conn)


# ── Note fetchers ────────────────────────────────────────────────────────────


def _fetch_notes(conn: sqlite3.Connection, where: str = "", params: tuple = (),
                 order: str = "created_at DESC", limit: int = 50) -> list[dict]:
    sql = "SELECT slug, content, created_at, updated_at FROM memos"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {order} LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [{"slug": r["slug"], "content": r["content"],
             "date": (r["created_at"] or "")[:10]} for r in rows]


def _notes_with_tags(conn: sqlite3.Connection, slugs: list[str]) -> dict[str, list[str]]:
    if not slugs:
        return {}
    placeholders = ",".join("?" * len(slugs))
    rows = conn.execute(
        f"""SELECT mt.memo_slug, t.name FROM memo_tags mt
            JOIN tags t ON t.id = mt.tag_id
            WHERE mt.memo_slug IN ({placeholders})""",
        tuple(slugs),
    ).fetchall()
    tag_map: dict[str, list[str]] = {}
    for r in rows:
        tag_map.setdefault(r["memo_slug"], []).append(r["name"])
    return tag_map


def _render_notes(notes: list[dict], conn: sqlite3.Connection | None = None) -> str:
    tag_map = _notes_with_tags(conn, [n["slug"] for n in notes]) if conn else {}
    parts = []
    for i, n in enumerate(notes):
        tags = tag_map.get(n["slug"], [])
        tag_str = " " + ", ".join(f"#{t}" for t in tags) if tags else ""
        parts.append(f"### {i+1}. [{n['date']}]{tag_str}\n{n['content'][:800]}")
    return "\n\n".join(parts)


def _assemble(prompt: str, notes_text: str, label: str) -> str:
    return (
        f"<!-- insight:{label} -->\n\n"
        f"# 指令：{label}\n\n"
        f"{prompt}\n\n---\n\n# 笔记\n\n"
        f"{notes_text}\n\n---\n\n"
        f"请基于以上笔记，按指令要求输出洞察分析。中文，有判断，不客套。"
    )


# ── Prompts ──────────────────────────────────────────────────────────────────


TOPICS_PROMPT = """你是一位深度思维分析师。阅读以下笔记，分析这个人的思维模式和关注焦点。

请输出：
1. **核心主题**：给每个反复出现的主题一个精准的名字
2. **思维模式**：反映的思维习惯（抽象or具体？反思or行动？理性or感性？）
3. **隐藏连接**：哪些表面无关的笔记之间存在深层关联？
4. **缺失之处**：有什么重要话题完全没有出现？这同样有意义
5. **精力分布**：时间分配反映了什么价值观？有没有失衡？"""


STAGNANT_PROMPT = """你是一位思想停滞检测专家。阅读以下笔记，找出反复出现但缺乏进展的想法。

请输出：
1. 哪些观点/话题反复出现，但每次都是同样的表述没有深入？
2. 如果有停滞，原因是什么？不敢行动？缺乏契机？还是不需要行动？
3. 哪些反复出现的想法实际每次都在推进——应该肯定这种探索
4. 对于真正停滞的想法，给出第一步行动建议

不要逐条分析。挑选最明显的 2-3 个模式深入。"""


DECLINING_PROMPT = """你是一位兴趣轨迹分析师。阅读以下笔记（按时间排列），找出可能正在消退的话题。

请输出：
1. **时间线分析**：哪些话题出现频率在下降？
2. **消退原因**：自然完成？兴趣转移？被动遗忘？
3. **是否值得捡回来**：消退的话题里有金子吗？
4. **整体趋势**：思考方向在往哪里演进？

消退不一定是坏事。有些想法完成了它的使命。"""


CONNECTIONS_PROMPT = """你是一位跨界思维侦探。阅读以下笔记，找出隐藏的关联。

请输出：
1. **最意外的连接**：表面无关、实际在讲同一件事的笔记对
2. **共同底层**：跨越话题的问题意识或思维习惯
3. **命名洞见**：给最有趣的跨界关联命名
4. **值得深挖**：哪些连接值得进一步探索？

好的跨界洞察应该让人感到"我从没这样想过，但你一说我就懂了"。"""


DRAFT_PROMPT = """你是一位写作教练。从以下笔记中提炼可写的文章。

请输出：
1. **核心论点**（一到两句话）
2. **文章大纲**（3-5 章）
3. **每章素材**（引用笔记中的具体内容）
4. **缺口**（写成完整文章还缺什么）
5. **开头导语**（50-100 字）

目标是让作者看到"原来我已经想了这么多，只需要组装起来"。"""


# ── Builders ─────────────────────────────────────────────────────────────────


def _build_topics(conn: sqlite3.Connection) -> str:
    notes = _fetch_notes(conn, limit=40)
    if not notes:
        raise ValueError("No notes found. Run 'flomo sync' first.")
    return _assemble(TOPICS_PROMPT, _render_notes(notes, conn=conn), "思维全景分析")


def _build_stagnant(conn: sqlite3.Connection) -> str:
    notes = _fetch_notes(conn, order="created_at ASC", limit=40)
    if not notes:
        raise ValueError("No notes found. Run 'flomo sync' first.")
    return _assemble(STAGNANT_PROMPT, _render_notes(notes, conn=conn), "停滞检测")


def _build_declining(conn: sqlite3.Connection) -> str:
    notes = _fetch_notes(conn, order="created_at ASC", limit=40)
    if not notes:
        raise ValueError("No notes found. Run 'flomo sync' first.")
    return _assemble(DECLINING_PROMPT, _render_notes(notes, conn=conn), "兴趣消退分析")


def _build_connections(conn: sqlite3.Connection) -> str:
    notes = _fetch_notes(conn, limit=30)
    if not notes:
        raise ValueError("No notes found. Run 'flomo sync' first.")

    tag_rows = conn.execute("""
        SELECT t1.name AS a, t2.name AS b, COUNT(*) AS w
        FROM memo_tags mt1
        JOIN memo_tags mt2 ON mt1.memo_slug = mt2.memo_slug AND mt1.tag_id < mt2.tag_id
        JOIN tags t1 ON t1.id = mt1.tag_id
        JOIN tags t2 ON t2.id = mt2.tag_id
        GROUP BY t1.name, t2.name ORDER BY w DESC LIMIT 10
    """).fetchall()

    tag_hint = ""
    if tag_rows:
        tag_hint = "## 高频标签共现\n" + "\n".join(
            f"- #{r['a']} ↔ #{r['b']} — {r['w']} 次" for r in tag_rows
        ) + "\n\n"

    return _assemble(CONNECTIONS_PROMPT, tag_hint + _render_notes(notes, conn=conn), "跨界连接")


def _build_draft(conn: sqlite3.Connection) -> str:
    notes = _fetch_notes(conn, order="created_at ASC", limit=30)
    if not notes:
        raise ValueError("No notes found. Run 'flomo sync' first.")
    return _assemble(DRAFT_PROMPT, _render_notes(notes, conn=conn), "写作草稿")
