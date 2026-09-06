"""Tag classifier — generates prompts for LLM-driven retagging.

All tagging uses the fixed taxonomy in taxonomy.py. LLM MUST pick from it.
Consistency: same taxonomy file → same tags across runs.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from flomo_insight.tags.taxonomy import MANDATORY_TAG, taxonomy_for_llm


def build_retag_prompt(
    conn: sqlite3.Connection,
    batch_size: int = 10,
    source: str | None = None,
    include_optimized: bool = False,
) -> str:
    """Fetch untagged-by-LLM memos and build a retag prompt.

    Only memos with tags_llm_at IS NULL are included by default —
    already LLM-optimized notes are skipped.

    Args:
        conn: Local SQLite connection.
        batch_size: How many memos to retag in this batch.
        source: Filter by source ('flomo', 'weread', None = all).
        include_optimized: If True, also include already-optimized memos.

    Returns markdown: taxonomy + memos + instructions.
    """
    conditions = []
    params: list[Any] = []
    if source:
        conditions.append("m.source = ?")
        params.append(source)
    if not include_optimized:
        conditions.append("m.tags_llm_at IS NULL")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"""SELECT m.slug, m.content, m.source, m.created_at, m.tags_llm_at,
                   GROUP_CONCAT(t.name, ',') AS current_tags
            FROM memos m
            LEFT JOIN memo_tags mt ON mt.memo_slug = m.slug
            LEFT JOIN tags t ON t.id = mt.tag_id
            {where}
            GROUP BY m.slug
            ORDER BY m.created_at DESC
            LIMIT ?""",
        (*params, batch_size),
    ).fetchall()

    if not rows:
        return (
            "没有待 LLM 打标的笔记（tags_llm_at 均已设置）。\n"
            "如需强制重打：`flomo retag --all`"
        )

    taxonomy = taxonomy_for_llm()

    items = []
    for i, r in enumerate(rows):
        slug_short = r["slug"][:12]
        date = (r["created_at"] or "")[:10]
        current_tags = r["current_tags"] or "(无标签)"
        content = r["content"][:600]
        items.append(
            f"### #{i + 1} [{slug_short}]\n"
            f"**日期**: {date}  **来源**: {r['source']}  **当前标签**: {current_tags}\n"
            f"**内容**: {content}"
        )

    items_text = "\n\n".join(items)

    return (
        "# 笔记标签优化（仅未处理过）\n\n"
        f"以下 {len(rows)} 条笔记尚未经过 LLM 打标优化（tags_llm_at 为空）。\n\n"
        f"{taxonomy}\n\n"
        "## 打标规则\n"
        f"1. 从上面的分类体系中选 1-3 个最匹配的标签\n"
        f"2. 如果原有标签在体系内且正确 → 保留\n"
        f"3. 如果原有标签不在体系内 → 用体系内的替代\n"
        f"4. 如果来自微信读书 → 额外加 #{MANDATORY_TAG}\n"
        "5. 标签要贴切内容，不要凑数\n\n"
        "## 操作方式\n"
        "1. 先输出打标方案表（slug、摘要、当前标签 → 建议标签、理由）\n"
        "2. **停下来等用户确认**，不要直接改\n"
        "3. 用户同意后才执行：`flomo update <slug> --content \"...\"`\n"
        "   正文里保留/改写 `#标签`（先写 flomo，成功后再镜像本地 SQLite）。\n"
        "4. 写入成功后执行：`flomo tags-optimized <slug>` 标记已处理\n\n"
        "## 笔记列表\n\n"
        f"{items_text}\n\n"
        "---\n"
        "请先给出打标方案并等待确认，不要直接执行 flomo update。"
    )


def mark_tags_llm_optimized(conn: sqlite3.Connection, slugs: list[str]) -> int:
    """Mark memos as LLM-tag-optimized. Returns how many rows were updated."""
    from datetime import datetime, timezone

    if not slugs:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for slug in slugs:
        cur = conn.execute(
            "UPDATE memos SET tags_llm_at = ? WHERE slug = ?",
            (now, slug),
        )
        n += cur.rowcount or 0
    conn.commit()
    return n


def count_pending_retag(conn: sqlite3.Connection) -> dict[str, int]:
    """How many memos still need LLM tag optimization."""
    total = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM memos WHERE tags_llm_at IS NOT NULL"
    ).fetchone()[0]
    return {"total": total, "optimized": done, "pending": total - done}


def build_wearead_import_prompt(items: list[dict[str, Any]]) -> str:
    """Build WeRead import prompt using the fixed taxonomy."""
    if not items:
        return "No new reviewed highlights to import. All caught up! 📚"

    taxonomy = taxonomy_for_llm()
    book_names = sorted(set(h["book_title"] for h in items))
    book_list = "\n".join(f"- {b}" for b in book_names)

    item_texts: list[str] = []
    for i, h in enumerate(items):
        chapter = f"「{h['chapter']}」" if h["chapter"] else ""
        item_texts.append(
            f"### #{i + 1} [review:{h['review_id']}]\n"
            f"**书**: {h['book_title']}  作者: {h['author']}  {chapter}\n"
            f"**划线**: {h['mark_text']}\n"
            f"**书评**: {h['review_text']}"
        )

    items_block = "\n\n".join(item_texts)

    return (
        "# 微信读书划线+书评导入\n\n"
        f"你需要将以下 {len(items)} 条「划线 + 书评」逐条导入 flomo。\n"
        f"涉及书籍: {book_list}\n\n"
        f"{taxonomy}\n\n"
        "## 导入规则（必须遵守）\n"
        "1. 每条创建一个 flomo memo，内容格式：\n"
        "```\n"
        "> 划线内容\n\n"
        "书评内容\n\n"
        "——《书名》作者\n"
        "```\n"
        f"2. 每条必须打标签 **#{MANDATORY_TAG}**（硬性要求）\n"
        f"3. 从上述分类体系中选择 1-2 个最匹配的分类标签\n"
        "4. 标签要贴切，同一本书的划线优先用相同标签\n"
        "5. **先列出待导入清单（书名/划线/书评/标签），等用户确认后再写入**\n"
        "6. 确认后：`flomo create \"内容\" --tags \"标签1,标签2\"` 逐条创建\n"
        "7. 创建后用 `flomo weread-mark <review_id> --book-id <id> --book-title <题> --mark <划线> --slug <slug>` 去重\n\n"
        "## 划线+书评列表\n\n"
        f"{items_block}\n\n---\n"
        "请先输出导入方案并等待用户确认，不要直接 flomo create。"
    )
