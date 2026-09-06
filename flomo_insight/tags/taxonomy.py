"""Stable tag taxonomy for flomo-insight.

LLM tagging **prefers this closed set**. Same subject → same tag.
Exception: a clear theme the set cannot cover (person, product name)
may use **one** short free-form tag; never invent synonyms of in-set tags.
WeRead imports always add MANDATORY_TAG (微信读书).

Version-controlled — changes affect future imports and re-tags.
"""

from __future__ import annotations

# ── Mandatory tag ───────────────────────────────────────────────────────────

MANDATORY_TAG = "微信读书"  # auto-added for WeRead imports


# ── Taxonomy ────────────────────────────────────────────────────────────────

def all_tags() -> dict[str, list[str]]:
    """domain → preferred tags (closed set; one-off exceptions allowed)."""
    return {
        "生产力": [
            "效率",
            "决策",
            "习惯",
            "学习",
            "目标",
            "专注",
            "笔记术",
        ],
        "心理": [
            "认知偏误",
            "情绪",
            "动机",
            "自我认同",
            "焦虑",
            "社交",
            "斯多葛",
        ],
        "财富": [
            "投资",
            "记账",
            "商业",
            "极简消费",
        ],
        "人文": [
            "哲学",
            "历史",
            "文学",
            "古诗",
            "写作",
            "社会学",
        ],
        "生活": [
            "健康",
            "关系",
            "收纳",
            "日常",
            "早起",
            "拖延",
        ],
        "科技": [
            "AI",
            "编程",
            "产品",
            "工具",
        ],
        "读书": [
            "书评",        # 你的想法/感想，区别于划线和摘要
            "金句",        # 值得收藏的原句
            "书单",        # 推荐/想读清单
            "精读",        # 深度笔记
        ],
    }


# ── Formatted for LLM (used in prompts) ────────────────────────────────────

def taxonomy_for_llm() -> str:
    """Pretty-print the taxonomy as a markdown table for LLM consumption."""
    lines = ["## 标签分类体系（优先从这里选）\n"]
    for domain, tags in all_tags().items():
        line = f"- **{domain}**：" + " / ".join(f"#{t}" for t in tags)
        lines.append(line)
    lines.append(
        "\n例外：体系确实覆盖不了的明确主题，最多用 1 个简短标签；禁止发明同义标签。"
    )
    return "\n".join(lines)
