# flomo-insight PRD

## 这是什么

一个开源 Python 工具，把你的 flomo（浮墨笔记）数据拉到本地，通过 Claude Code
的 MCP 协议让 LLM 直接读取原始笔记并生成深度洞察。

**不做聚类，不做向量化，不做中间分析。** 所有洞察都由 LLM 从原始笔记中直接产出。

## 为什么做

flomo 是优秀的轻量笔记工具，但缺乏跨笔记的深度分析能力。用户想知道：
- 我最常思考什么？有什么反复出现的模式？
- 哪些想法反复记录但没有推进？
- 表面无关的笔记之间有什么隐藏关联？
- 我的笔记能自动生成一篇什么文章？

这些不是"搜索关键词匹配几条笔记"能回答的——需要 LLM 读完全部笔记后才能洞察。

## 架构

```
flomo API (Bearer token)
    │
    ▼
sync (拉取笔记, 存入 SQLite)
    │
    ▼
MCP Server (9个工具)
    │
    ▼
Claude Code ← 读取原始笔记 + 系统 prompt → 生成洞察
```

## 核心原则

- **全部 LLM 驱动**：不依赖任何预处理、聚类或统计模型。LLM 读原文出洞察。
- **一行配置**：`cp config.toml.example config.toml` → 填入 token → 完成。
- **数据安全**：所有数据本地存储（SQLite），config.toml 和 data/ 目录 gitignored。
- **CLI 操作 + MCP 洞察**：CLI 做数据同步和搜索，MCP 做 LLM 洞察。

## 功能清单

### 数据管线
- [x] flomo API 同步（Bearer token 鉴权，MD5 签名）
- [x] 增量同步（只拉更新）
- [x] FTS5 全文搜索
- [x] 标签提取与管理

### 洞察引擎（MCP，11种）
- [x] topics — 主题全景分析
- [x] stagnant — 停滞检测
- [x] declining — 兴趣消退分析
- [x] connections — 跨界连接
- [x] draft — 写作草稿生成
- [x] default — 默认洞察（flomo 官方）
- [x] value-clarification — 价值澄清（shaonan）
- [x] inversion — 芒格逆向思考
- [x] second-order — 二阶思考（shaonan）
- [x] cbt — CBT 认知行为疗法
- [x] mbti — MBTI 人格分析

### 外部导入
- [x] 微信读书划线+书评导入（官方 Skills API，wrk-xxx）
- [x] 自动打标签 #微信读书 + LLM 分类
- [x] 去重追踪

## 不做的事

- 不聚类/不向量化：笔记量 < 200 时聚类反而丢失信息
- 不做 Web UI：只做 CLI + MCP
- 不自动同步：手动触发 `flomo sync`

## 技术选型

| 选型 | 理由 |
|------|------|
| Python + Typer | CLI 最成熟的生态 |
| SQLite + FTS5 | 零配置全文搜索，个人规模笔记绰绰有余 |
| FastMCP | 一行装饰器注册 MCP 工具 |
| httpx | 现代 Python HTTP 客户端 |
| TOML config | Python 标准库自带解析，用户编辑友好 |
