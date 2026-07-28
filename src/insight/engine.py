"""LLM-driven insight engine — every insight type fetches notes + data, wraps
them with a system prompt, and returns the package for Claude Code to interpret.

No template-based output. No hardcoded conclusions. Claude Code does all the thinking.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Callable


# ── Insight type definitions ─────────────────────────────────────────────────


@dataclass
class InsightType:
    key: str
    title: str
    description: str
    system_prompt: str
    note_count: int = 20
    requires_analysis: bool = True
    requires_sync: bool = True


# ── Fetchers ─────────────────────────────────────────────────────────────────


def _build_cluster_summary(conn: sqlite3.Connection) -> str:
    """Human-readable cluster overview."""
    clusters = conn.execute(
        """SELECT id, cluster_label, keywords, size
           FROM clusters WHERE cluster_label != -1
           ORDER BY size DESC"""
    ).fetchall()

    if not clusters:
        return ""

    total = sum(c["size"] for c in clusters)
    parts = ["## 笔记聚类概览\n"]
    parts.append(f"共 {len(clusters)} 个主题，{total} 条笔记被聚类\n")
    for i, c in enumerate(clusters):
        kws = json.loads(c["keywords"]) if c["keywords"] else ["(未命名)"]
        pct = (c["size"] / total * 100) if total > 0 else 0
        parts.append(f"- **#{i+1}**: {', '.join(kws[:5])} — {c['size']} 条 ({pct:.0f}%)")
    return "\n".join(parts)


def _fetch_representative_notes(
    conn: sqlite3.Connection, count: int = 15
) -> list[tuple[str, str]]:
    """Mix of recent notes + high-confidence cluster members."""
    slugs: set[str] = set()
    results: list[tuple[str, str]] = []

    # 1. Recent notes
    for row in conn.execute(
        "SELECT slug, content, created_at FROM memos ORDER BY created_at DESC LIMIT ?",
        (count,),
    ).fetchall():
        if row["slug"] not in slugs:
            slugs.add(row["slug"])
            date = row["created_at"][:10] or "?"
            results.append((date, row["content"]))

    return results


def _fetch_cluster_notes(
    conn: sqlite3.Connection, cluster_id: int, limit: int = 10
) -> list[tuple[str, str]]:
    """Notes from a specific cluster."""
    rows = conn.execute(
        """SELECT m.content, m.created_at
           FROM memos m
           JOIN cluster_memos cm ON cm.memo_slug = m.slug
           WHERE cm.cluster_id = ? AND cm.membership_prob > 0.5
           ORDER BY m.created_at
           LIMIT ?""",
        (cluster_id, limit),
    ).fetchall()
    return [(r["created_at"][:10] or "?", r["content"]) for r in rows]


def _fetch_stagnant_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Clusters that span > 60 days with >= 3 memos."""
    clusters = conn.execute(
        "SELECT id, keywords, size FROM clusters WHERE cluster_label != -1 AND size >= 3"
    ).fetchall()

    candidates = []
    for c in clusters:
        row = conn.execute(
            """SELECT MIN(m.created_at) as first, MAX(m.created_at) as last, COUNT(*) as cnt
               FROM memos m
               JOIN cluster_memos cm ON cm.memo_slug = m.slug
               WHERE cm.cluster_id = ?""",
            (c["id"],),
        ).fetchone()
        if not row or not row["first"]:
            continue
        from datetime import datetime

        try:
            span = (datetime.fromisoformat(row["last"]) - datetime.fromisoformat(row["first"])).days
        except (ValueError, TypeError):
            continue
        if span >= 60:
            kws = json.loads(c["keywords"]) if c["keywords"] else ["(未命名)"]
            candidates.append(
                {
                    "cluster_id": c["id"],
                    "keywords": ", ".join(kws[:3]),
                    "size": row["cnt"],
                    "span_days": span,
                    "first": row["first"][:10],
                    "last": row["last"][:10],
                }
            )
    candidates.sort(key=lambda x: x["span_days"], reverse=True)
    return candidates[:5]


def _fetch_declining_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Clusters with negative monthly trend."""
    rows = conn.execute(
        """SELECT c.id, c.keywords, c.size, tt.trend_slope
           FROM clusters c
           JOIN topic_trends tt ON tt.cluster_id = c.id
           WHERE c.cluster_label != -1
           GROUP BY c.id
           HAVING tt.trend_slope < -0.05
           ORDER BY tt.trend_slope ASC
           LIMIT 5"""
    ).fetchall()

    candidates = []
    for r in rows:
        kws = json.loads(r["keywords"]) if r["keywords"] else ["(未命名)"]
        # Get monthly breakdown
        months = conn.execute(
            "SELECT month, memo_count FROM topic_trends WHERE cluster_id = ? ORDER BY month",
            (r["id"],),
        ).fetchall()
        candidates.append(
            {
                "cluster_id": r["id"],
                "keywords": ", ".join(kws[:3]),
                "size": r["size"],
                "trend_slope": r["trend_slope"],
                "monthly": [(m["month"], m["memo_count"]) for m in months],
            }
        )
    return candidates


def _fetch_tag_connections(conn: sqlite3.Connection) -> list[dict]:
    """Top tag co-occurrence pairs."""
    rows = conn.execute(
        """SELECT t1.name AS tag_a, t2.name AS tag_b, tc.weight
           FROM tag_cooccurrence tc
           JOIN tags t1 ON t1.id = tc.tag_a_id
           JOIN tags t2 ON t2.id = tc.tag_b_id
           ORDER BY tc.weight DESC LIMIT 10"""
    ).fetchall()
    return [{"tag_a": r["tag_a"], "tag_b": r["tag_b"], "weight": r["weight"]} for r in rows]


def _fetch_bridge_notes(
    conn: sqlite3.Connection, tag_a: str, tag_b: str, limit: int = 3
) -> list[str]:
    """Notes that contain both tags."""
    rows = conn.execute(
        """SELECT m.content FROM memos m
           JOIN memo_tags mt1 ON mt1.memo_slug = m.slug
           JOIN tags t1 ON t1.id = mt1.tag_id AND t1.name = ?
           JOIN memo_tags mt2 ON mt2.memo_slug = m.slug
           JOIN tags t2 ON t2.id = mt2.tag_id AND t2.name = ?
           LIMIT ?""",
        (tag_a, tag_b, limit),
    ).fetchall()
    return [r["content"][:500] for r in rows]


# ── Prompt templates ─────────────────────────────────────────────────────────

TOPICS_PROMPT = """你是一位深度思维分析师。请基于下面提供的聚类数据和代表性笔记，
分析这个人的思维模式和关注焦点。

## 你需要做

1. **命名主题**：聚类只给了关键词，请给每个聚类一个更精准的主题名称（一句话）
2. **找出模式**：这些主题反映了怎样的思维方式？有什么反复出现的底层关切？
3. **发现缺失**：有什么重要但没有出现的主题？（这可能和已出现的同样有意义）
4. **跨主题连接**：哪些主题之间存在深层的关联，尽管表面上无关？
5. **精力诊断**：时间分配反映了什么价值观？有没有失衡的迹象？

请用洞察式的语言输出，不要只是列出数据。要有判断，有观点。"""

STAGNANT_PROMPT = """你是一位思想停滞检测专家。以下是同一个主题跨越很长时间反复出现的笔记。

## 你需要做

1. **判断真停滞还是持续探索**：每次提到是同样的观点在循环，还是每次有新的推进？
2. **找到停滞原因**：为什么这个想法一直没有进展？是不敢行动、缺乏契机、还是本质上不需要行动？
3. **关键追问**：如果这个想法会说话，它想让你做什么？
4. **行动建议**：如果需要推进，第一步应该是什么？如果不需要，为什么还在反复记录？

对于停滞的想法，你要像一面诚实的镜子。对于持续深入的想法，你要肯定这种探索。"""

DECLINING_PROMPT = """你是一位兴趣轨迹分析师。以下是月度趋势数据 + 相关笔记。

## 你需要做

1. **判断消退原因**：自然完成（话题已消化）、兴趣转移（有新焦点替代）、还是被动遗忘？
2. **评估价值**：消退的主题里有没有值得重新捡回来的？为什么？
3. **发现模式**：消退的主题之间有没有共性？这反映了怎样的兴趣演化规律？
4. **预警信号**：有什么正在消退但应该被关注的主题？

记住：消退不一定是坏事。有些想法完成了它的使命。"有些路走到尽头，不是因为走错了，而是因为走完了。" """

CONNECTIONS_PROMPT = """你是一位跨界思维侦探。以下是一组同时出现在同一条笔记中的标签对，
以及跨越这些标签的笔记片段。

## 你需要做

1. **找到最意外的连接**：哪些标签组合最让你意外？为什么作者会把它们放在一起？
2. **发现隐藏范式**：这些看似无关的标签背后，有没有一个共同的问题意识或思维习惯？
3. **命名跨域洞见**：给几个最有趣的连接命名（比如 "#哲学 × #编程" → 一个洞见标签）
4. **建议深入方向**：哪些连接值得进一步探索？作者可能忽略的角度是什么？

好的跨界连接洞察应该让作者感到"我从来没这样想过，但你一说我就懂了。" """

DRAFT_PROMPT = """你是一位写作教练和编辑。以下是同一个主题下的全部相关笔记，按时间排列。

## 你需要做

1. **提炼核心论点**：这个主题下，作者最想表达的核心观点是什么？（一到两句话）
2. **设计文章结构**：把笔记中的碎片组织成一个有逻辑的提纲（章节级，3-5 章）
3. **标注素材来源**：每章下面，标注可以从哪些笔记中提取素材（引用日期即可）
4. **指出缺口**：要写成完整文章，还缺什么？哪些论点需要更多论据？
5. **给一个开头**：写一个 50-100 字的文章开头（导语），吸引读者进入

目标是让作者看到"原来我已经想了这么多，只需要把这些碎片组装起来。" """


# ── Unified entry point ──────────────────────────────────────────────────────


def generate_insight(conn: sqlite3.Connection, insight_type: str) -> str:
    """Fetch notes + data, wrap with system prompt, return for Claude Code to interpret."""
    from src.insight.templates import PERSPECTIVES

    # Perspective types (from flomo official + shaonan)
    if insight_type in PERSPECTIVES:
        from src.insight.templates import fetch_notes_for_perspective

        return fetch_notes_for_perspective(conn, insight_type)

    # LLM-driven analytical types
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


# ── Builders ─────────────────────────────────────────────────────────────────


def _build_topics(conn: sqlite3.Connection) -> str:
    """Cluster summary + representative notes + topics prompt."""
    cluster_text = _build_cluster_summary(conn)
    if not cluster_text:
        raise ValueError("No clusters found. Run 'flomo analyze' first.")

    # Fetch representative notes from each cluster
    clusters = conn.execute(
        "SELECT id, keywords FROM clusters WHERE cluster_label != -1 ORDER BY size DESC LIMIT 6"
    ).fetchall()

    notes_parts = []
    for i, c in enumerate(clusters):
        kws = json.loads(c["keywords"]) if c["keywords"] else ["未命名"]
        notes = _fetch_cluster_notes(conn, c["id"], limit=5)
        notes_parts.append(f"\n### 主题 #{i + 1}: {', '.join(kws[:3])}\n")
        for date, content in notes:
            notes_parts.append(f"[{date}] {content[:400]}\n")

    data_section = (
        cluster_text + "\n\n---\n\n## 各主题代表性笔记\n" + "\n".join(notes_parts)
    )

    return _assemble(TOPICS_PROMPT, data_section, "📊 思维全景分析")


def _build_stagnant(conn: sqlite3.Connection) -> str:
    """Stagnant cluster candidates + their notes + stagnant prompt."""
    candidates = _fetch_stagnant_candidates(conn)
    if not candidates:
        raise ValueError("No stagnant patterns found. Your thinking seems well-distributed.")

    parts = ["## 候选停滞主题\n"]
    for c in candidates:
        parts.append(
            f"- **{c['keywords']}**: {c['size']} 条笔记跨越 {c['span_days']} 天 "
            f"({c['first']} → {c['last']})"
        )
    summary = "\n".join(parts)

    notes_parts = []
    for c in candidates:
        notes = _fetch_cluster_notes(conn, c["cluster_id"], limit=8)
        notes_parts.append(f"\n### {c['keywords']} (跨度 {c['span_days']} 天)\n")
        for date, content in notes:
            notes_parts.append(f"[{date}] {content[:400]}\n")

    data = summary + "\n\n---\n\n## 详细笔记\n" + "\n".join(notes_parts)
    return _assemble(STAGNANT_PROMPT, data, "🔁 停滞检测")


def _build_declining(conn: sqlite3.Connection) -> str:
    """Declining clusters + monthly data + notes + declining prompt."""
    candidates = _fetch_declining_candidates(conn)
    if not candidates:
        raise ValueError("No declining trends found. Your interests are stable or growing.")

    parts = ["## 趋势下降的主题\n"]
    for c in candidates:
        months_str = ", ".join(f"{m[0]}={m[1]}" for m in c["monthly"])
        parts.append(
            f"- **{c['keywords']}**: {c['size']} 条, 趋势 {c['trend_slope']:+.2f}/月\n"
            f"  月度分布: {months_str}"
        )
    summary = "\n".join(parts)

    notes_parts = []
    for c in candidates:
        notes = _fetch_cluster_notes(conn, c["cluster_id"], limit=5)
        notes_parts.append(f"\n### {c['keywords']} (趋势 {c['trend_slope']:+.2f}/月)\n")
        for date, content in notes:
            notes_parts.append(f"[{date}] {content[:400]}\n")

    data = summary + "\n\n---\n\n## 相关笔记\n" + "\n".join(notes_parts)
    return _assemble(DECLINING_PROMPT, data, "📉 兴趣消退分析")


def _build_connections(conn: sqlite3.Connection) -> str:
    """Tag co-occurrence + bridge notes + connections prompt."""
    connections = _fetch_tag_connections(conn)
    if not connections:
        raise ValueError("No tag co-occurrence data. Run 'flomo analyze' first.")

    parts = ["## 高频标签共现\n"]
    for c in connections:
        parts.append(f"- **#{c['tag_a']}** ↔ **#{c['tag_b']}** — 共同出现在 {c['weight']} 条笔记")
    summary = "\n".join(parts)

    notes_parts = []
    for c in connections[:6]:
        bridge = _fetch_bridge_notes(conn, c["tag_a"], c["tag_b"], limit=2)
        if bridge:
            notes_parts.append(f"\n### #{c['tag_a']} × #{c['tag_b']} (共 {c['weight']} 次)\n")
            for content in bridge:
                notes_parts.append(f"{content[:400]}\n---\n")

    data = summary + "\n\n---\n\n## 跨界笔记示例\n" + "\n".join(notes_parts)
    return _assemble(CONNECTIONS_PROMPT, data, "🔗 跨界连接")


def _build_draft(conn: sqlite3.Connection) -> str:
    """All notes from largest cluster + draft prompt."""
    clusters = conn.execute(
        "SELECT id, keywords, size FROM clusters WHERE cluster_label != -1 ORDER BY size DESC LIMIT 1"
    ).fetchall()
    if not clusters:
        raise ValueError("No clusters found. Run 'flomo analyze' first.")

    c = clusters[0]
    kws = json.loads(c["keywords"]) if c["keywords"] else ["未命名"]
    topic = kws[0] if kws else "未命名主题"

    notes = conn.execute(
        """SELECT m.content, m.created_at
           FROM memos m
           JOIN cluster_memos cm ON cm.memo_slug = m.slug
           WHERE cm.cluster_id = ?
           ORDER BY m.created_at""",
        (c["id"],),
    ).fetchall()

    notes_parts = [f"## 主题: {topic}\n"]
    notes_parts.append(f"共 {len(notes)} 条笔记\n")
    for i, m in enumerate(notes):
        date = m["created_at"][:10] if m["created_at"] else "?"
        content = m["content"].strip()
        notes_parts.append(f"\n### 笔记 {i + 1} [{date}]\n{content[:800]}")

    data = "\n".join(notes_parts)
    return _assemble(DRAFT_PROMPT, data, "✍️ 写作草稿")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _assemble(system_prompt: str, data_section: str, label: str) -> str:
    return (
        f"<!-- insight:{label} -->\n\n"
        f"# 指令：{label}\n\n"
        f"{system_prompt}\n\n"
        f"---\n\n"
        f"# 数据\n\n"
        f"{data_section}\n\n"
        f"---\n\n"
        f"请基于以上数据，按照指令中的要求输出你的洞察分析。\n"
        f"语言：中文。风格：洞察式、有判断、不客套。"
    )
