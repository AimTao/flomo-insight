# Review Skill

当用户要求生成复习内容时使用此 Skill。

## 原理

两阶段 MCP 流程，全程 LLM 决策：

**Phase 1 — 概览**：`flomo_review_candidates()` 返回所有笔记池的轻量预览
（标签/内容摘要/标签分布），不做任何过滤。
**Phase 2 — 深潜**：对选中的池调用 `flomo_review_pool(strategy, label)` 获取完整笔记。

SQL 不做任何选择——全部交给 LLM 判断。

## 操作

```
1. 确保本地 DB 最新：flomo sync
2. （推荐）先了解近期思维模式：flomo_insight("topics")
3. Phase 1：MCP: flomo_review_candidates() → 看全局概览，挑选有潜力的池
4. Phase 2：对每个选中的池，MCP: flomo_review_pool(strategy, label) → 拿完整笔记
5. 阅读完整笔记，决定分组 + 写复习
6. 保存到 /tmp/reviews.json
7. 推送到 D1：flomo review --push --json /tmp/reviews.json
```

## 4 种策略

| 策略 | pool label | 含义 |
|------|-----------|------|
| same_book | 书名 | 同一本书的划线笔记 |
| tag_cluster | 标签名 | 同一标签下的笔记 |
| near_time | 日期 | 同一天写的笔记 |
| co_tag | "A × B" | 同时带两个标签的笔记 |

## 挑选标准

**值得深潜的池**：
- 标签虽然大，但 sample 显示内容有多个子主题可以交叉 → 值得看
- 标签小但很聚焦，sample 之间有化学反应
- 几个不同标签的 pool 之间可能有跨池关联 → 可单独拉出来分组
- 同一本书但不同章节的划线指向同一个问题

**直接跳过的池**：
- sample 全是流水账 / 随手记
- 标签很大但内容高度同质（例：30 条笔记全是「今天看到一篇 AI 文章」）

## 分组和写作要求

你是编辑 + 写作者，两步一起做：

**编辑 — 分组**：
- 仔细阅读每条笔记全文（Phase 2 不含截断）
- 找出真正有内在联系的笔记组合，不论条数
- 每条笔记只能出现在一个分组里
- 同一池内挑不出好组合就跳过，不要硬凑
- 如果多个标签池的笔记之间有跨域关联，大胆跨池组合

**写作 — 口语化复习**：
- 1-2 句话，像发微信给朋友分享一个发现
- 串联笔记，加上感受或判断
- 有洞察（深层联系）、有趣味（有态度）、有新知（模式或矛盾）
- 不要说教、不要分号、不要长句

**每条复习字段**：
- slug：涉及的笔记 slug 列表
- content：口语化复习
- connection：一句话关联洞察（如「#效率 × #拖延 的时间感知冲突」）
- mood：共鸣 / 启发 / 吐槽 / 温暖 / 扎心
- strategy：same_book / tag_cluster / near_time / co_tag（选主要来源）

## 输出 JSON

```json
[
  {
    "slugs": ["slug1", "slug2"],
    "content": "口语化复习文字",
    "connection": "一句话关联洞察",
    "mood": "共鸣",
    "strategy": "tag_cluster"
  }
]
```

保存到 `/tmp/reviews.json`。

## 推送到 D1

```
flomo review --push --json /tmp/reviews.json
```

首次推送 DROP + CREATE 新 schema（含 strategy/connection/mood），后续 INSERT。
