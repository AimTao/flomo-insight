# AGENTS.md — flomo-insight

AI-powered insight engine for flomo (浮墨笔记) + WeRead (微信读书) import.

**All insights are LLM-driven.** No clustering, no embeddings, no pre-analysis.
Data pipeline: `flomo sync` pulls raw notes into SQLite. MCP tools fetch notes
+ wrap them with a system prompt. Claude Code reads and generates the insight.

## Project structure

```
src/                  # Python package
├── main.py           # CLI (Typer)
├── mcp_server.py     # MCP Server (FastMCP) — 9 tools
├── config.py         # Config from config.toml
├── api/              # flomo HTTP client + MD5 sign
├── sync/             # Paginated memo sync
├── search/           # FTS5 full-text search
├── insight/          # LLM-driven insight engine (11 types)
├── importers/        # WeRead highlight+review import
└── db/               # SQLite schema + migrations
config.toml.example   # Template — user copies to config.toml
config.toml           # Secrets + settings (gitignored)
data/                 # Database (gitignored)
```

## Setup

```bash
uv sync
cp config.toml.example config.toml
# Edit config.toml — set flomo_token
flomo sync
```

## Architecture decision: No clustering

For datasets under ~200 notes, clustering is actively harmful — it obscures
connections that an LLM can find by reading the raw text. Insight engine
fetches notes directly from SQLite, wraps them with a system prompt, and
Claude Code does all the reasoning.

## MCP Tools (9)

| Tool | Purpose |
|------|---------|
| `flomo_search` | FTS5 search + tag filter |
| `flomo_create` | Create memo (cloud) |
| `flomo_sync` | Sync from flomo API |
| `flomo_insight` | LLM-driven insight (11 types) |
| `flomo_recent` | Recent memos |
| `flomo_tags` | Tag list + counts |
| `flomo_import_weread` | Fetch WeRead highlights+reviews |
| `flomo_weread_mark_imported` | Dedup tracking |
| `flomo_weread_stats` | Import stats |

## 常用工作流

### 微信读书导入
→ 参考 `.claude/skills/tagging.md`
```
flomo import weread          # 拉取划线+书评，生成 LLM 导入 prompt
# 然后逐条打标签 → flomo_create → flomo_weread_mark_imported
```

### 洞察分析
→ 参考 `.claude/skills/insight.md`
```
flomo sync                   # 先同步
flomo insight topics         # 或 connections / cbt / inversion 等
# CLI 输出 prompt+笔记原文，直接基于此写洞察
```

### 备份到 D1
→ 参考 `.claude/skills/backup.md`
```
flomo sync                   # 先同步
flomo backup                 # 增量推送至 Cloudflare D1
```

### 每日复习
→ 参考 `.claude/skills/review.md`
```
flomo sync
flomo review-daily                # 间隔重复:今天到期的笔记
# Claude 为每条写「钩子」→ 逐条 flomo review grade <slug> <grade>
flomo review-push                 # 推送到 D1(供 Worker 用)
```
Worker 部署在 memo.example.com，按 due_at 返回到期卡片。

## 提交前检查

提交代码之前必须确认不包含以下内容：

- `config.toml` 中的 flomo_token / weread_key / d1_api_token
- 任何硬编码的 Bearer token / API key / password
- 调试产物：`.playwright-mcp/`、截图 `.png`、临时脚本 `/tmp/`
- `data/flomo.db` — 数据库文件（已 gitignored）

```bash
# 快速检查改动中是否含敏感词
git diff --cached | grep -iE 'token|secret|key|password|Bearer' | grep -vE 'require_token|require_weread|_mask_token|api_key=flomo|config\.|\.example'
# 应返回空
```

**调试产物处理**：用 `>> .gitignore` 追加，然后 `git add .gitignore && git commit -m "chore: gitignore debug artifacts"`

## Security

config.toml and data/ are gitignored. No secrets in source code.
Tests use synthetic data only.
