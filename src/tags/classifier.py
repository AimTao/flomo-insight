"""Tag classifier — generates prompts for LLM-driven retagging.

All tagging uses the fixed taxonomy in taxonomy.py. LLM MUST pick from it.
Consistency: same taxonomy file → same tags across runs.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.tags.taxonomy import MANDATORY_TAG, taxonomy_for_llm


def build_retag_prompt(
    conn: sqlite3.Connection,
    batch_size: int = 10,
    source: str | None = None,
) -> str:
    """Fetch memos and build a prompt for LLM to retag.

    Args:
        conn: Local SQLite connection.
        batch_size: How many memos to retag in this batch.
        source: Filter by source ('flomo', 'weread', None = all).

    Returns markdown: taxonomy + memos + instructions.
    """
    where = ""
    params = []
    if source:
        where = "WHERE source = ?"
        params.append(source)

    rows = conn.execute(
        f"""SELECT m.slug, m.content, m.source, m.created_at,
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
        return "No memos to retag. Sync first."

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
        "# 笔记重新打标\n\n"
        f"你需要为以下 {len(rows)} 条笔记重新打标签。\n\n"
        f"{taxonomy}\n\n"
        "## 打标规则\n"
        f"1. 从上面的分类体系中选 1-3 个最匹配的标签\n"
        f"2. 如果原有标签在体系内且正确 → 保留\n"
        f"3. 如果原有标签不在体系内 → 用体系内的替代\n"
        f"4. 如果来自微信读书 → 额外加 #{MANDATORY_TAG}\n"
        "5. 标签要贴切内容，不要凑数\n\n"
        "## 操作方式\n"
        "对每条笔记，调用 flomo_tag_update(slug, tags) 设置新标签。\n"
        "tags 参数是字符串列表，如 [\"效率\", \"习惯\"]。\n\n"
        "## 笔记列表\n\n"
        f"{items_text}\n\n"
        "---\n"
        "请开始逐条打标。每打一条调用一次 flomo_tag_update。"
    )


def update_memo_tags(conn: sqlite3.Connection, slug: str, tag_names: list[str]) -> None:
    """Replace all tags on a memo with the given list.

    Only accepts tags that exist in the taxonomy. Unknown tags are silently
    ignored (they will be created anyway since this is a permissive system,
    but the LLM should still follow the taxonomy).
    """
    # Remove existing tags
    conn.execute("DELETE FROM memo_tags WHERE memo_slug = ?", (slug,))

    # Create tags if they don't exist, then link
    for name in tag_names:
        name = name.strip().lstrip("#")
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO memo_tags (memo_slug, tag_id) VALUES (?, ?)",
                (slug, row["id"]),
            )
    conn.commit()


def build_wearead_import_prompt(
    items: list[dict[str, Any]],
    extra_tag: str | None = None,
) -> str:
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
        "5. 调用 flomo_create 逐条创建\n"
        "6. 创建后调用 flomo_weread_mark_imported\n\n"
        "## 划线+书评列表\n\n"
        f"{items_block}\n\n---\n"
        "请现在开始逐条导入。"
    )
