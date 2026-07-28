"""Stable tag taxonomy for flomo-insight.

LLM-assisted tagging MUST pick from this closed set. No free-form tags.
Version-controlled — changes here affect all future imports and re-tags.

Structure: domain / category / tags.
- domain: broad area of life (生产力, 心理, 财富, 人文, 生活, 科技)
- category: sub-topic
- tags: concrete labels (only these are written to flomo)
"""

from __future__ import annotations

# ── Mandatory tag ───────────────────────────────────────────────────────────

MANDATORY_TAG = "微信读书"  # auto-added for WeRead imports


# ── Taxonomy ────────────────────────────────────────────────────────────────

def all_tags() -> dict[str, list[str]]:
    """Return domain → tags mapping. These are the ONLY valid tags."""
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
    lines = ["## 标签分类体系（只能从这里选，禁止自创）\n"]
    for domain, tags in all_tags().items():
        line = f"- **{domain}**：" + " / ".join(f"#{t}" for t in tags)
        lines.append(line)
    return "\n".join(lines)
