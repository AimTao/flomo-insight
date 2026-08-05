# flomo-insight

AI 驱动的 flomo（浮墨笔记）知识引擎 —— 全部基于 LLM 推理，不做聚类、不做向量化、不做预处理。

**核心能力**：同步笔记到本地 / 微信读书划线导入 / 11 种 LLM 洞察 / 每日复习推送 / D1 云端备份

---

## 快速开始

```bash
git clone <repo>
cd flomo-insight
uv sync
cp config.toml.example config.toml
```

编辑 `config.toml`，填入你的 token：

```toml
flomo_token = "..."       # Chrome F12 → Network → /api/ → Authorization → Bearer 后面的值
weread_key = ""           # 可选，微信读书 Skills API key
d1_database_id = ""       # 可选，Cloudflare D1 数据库 UUID（备份用）
```

首次同步：

```bash
flomo sync
```

---

## CLI 命令

### 数据同步

```bash
flomo sync                 # 增量同步（默认）
flomo sync --full          # 全量重新同步
```

### 笔记操作

```bash
flomo create "内容"                    # 创建一条笔记（推送到 flomo 云端）
flomo create "内容" --tags "标签1,标签2"  # 带标签创建
flomo search "关键词"                   # 全文搜索
flomo search "关键词" --tags "AI,学习"   # 标签过滤搜索
flomo recent -n 20                     # 最近 20 条笔记
```

### 微信读书导入

```bash
flomo import weread              # 拉取划线+书评，生成 LLM 打标 prompt
flomo import weread --auto       # 自动导入（仅打 #微信读书 标签）
flomo weread-stats               # 查看导入统计
```

详细流程 → 见 `.claude/skills/tagging.md`

### 洞察分析

```bash
flomo perspectives              # 列出 11 种洞察类型
flomo insight topics            # 思维全景分析（输出 prompt + 笔记原文）
```

洞察类型：
- **分析型**：`topics` / `stagnant` / `declining` / `connections` / `draft`
- **视角型**：`default` / `value-clarification` / `inversion` / `second-order` / `cbt` / `mbti`

详细流程 → 见 `.claude/skills/insight.md`

### 标签管理

```bash
flomo tags                     # 列出所有标签及使用频次
flomo tags --sort name         # 按名称排序
flomo retag                    # 批量重新打标（LLM 驱动）
```

标签分类体系在 `src/tags/taxonomy.py` 中定义。

### 备份到 Cloudflare D1

```bash
flomo backup                   # 增量推送到 D1（仅推送更新的笔记）
```

首次运行推送全部笔记，后续只推送 `updated_at` 有变化的。认证通过 macOS 钥匙串（`npx wrangler login`）。

详细流程 → 见 `.claude/skills/backup.md`

### 每日复习

```bash
flomo sync                         # 先同步最新笔记
flomo review-daily -o queue.json   # 间隔重复:今天到期的笔记(你的原文)
# Claude 为每条到期笔记写一条「钩子」→ 回填 queue.json
flomo review grade <slug> good     # 逐条评分,系统安排下次复习时间
flomo review-push                  # 把复习节奏推送到 D1(供 Worker 用)
```

复习节奏由简化 SM-2 间隔重复决定:`again`→1 天、`hard`→×1.3、`good`→×2、`easy`→×3(封顶 60 天),新笔记在 30 天内逐步引入。

主题回顾(可选):`flomo review` 两阶段深潜,Claude 从候选池挑关联笔记写主题回顾 → `flomo review --push --json reviews.json`。

复习通过 Cloudflare Worker 在 `memo.example.com` 提供,每次返回一条到期的复习。

详细流程 → 见 `.claude/skills/review.md`

### 其他

```bash
flomo stats                    # 数据库统计
flomo config show              # 显示当前配置
flomo config set-token <t>     # 设置并验证 flomo token
flomo config set-weread-key <k> # 设置微信读书 API key
flomo mcp                      # 启动 MCP Server
flomo version                  # 版本号
```

---

## MCP 集成（Claude Code）

在 `.claude/mcp.json` 中配置：

```json
{
  "mcpServers": {
    "flomo": {
      "command": "uv",
      "args": ["run", "flomo", "mcp"],
      "cwd": "/path/to/flomo-insight"
    }
  }
}
```

### 可用 MCP 工具

| 工具 | 用途 |
|------|------|
| `flomo_search` | FTS5 全文搜索 + 标签过滤 |
| `flomo_create` | 创建笔记（自动同步到云端） |
| `flomo_sync` | 从 flomo 云端同步笔记到本地 |
| `flomo_insight` | 11 种 LLM 洞察（拉取笔记 + system prompt） |
| `flomo_recent` | 获取最近的笔记 |
| `flomo_tags` | 标签列表及计数 |
| `flomo_tags_taxonomy` | 查看标签分类体系 |
| `flomo_import_weread` | 拉取微信读书划线+书评 |
| `flomo_import_weread_auto` | 自动导入微信读书到 flomo |
| `flomo_weread_mark_imported` | 标记为已导入（去重用） |
| `flomo_weread_stats` | 微信读书导入统计 |
| `flomo_retag` | 获取笔记+prompt 用于批量重打标 |
| `flomo_tag_update` | 更新某条笔记的标签 |

---

## 架构

```
微信读书 API ──→ importers/weread.py ──→ Claude 打标签 ──→ flomo 云端
                                                              │
flomo API ──→ sync/exporter.py ──→ SQLite (data/flomo.db) ──→ insight engine
                                         │                      │
                                         │                  11 种洞察
                                         │                      │
                                    backup/d1.py ──→ Cloudflare D1
                                                          │
                                                    Worker 每日复习
```

**核心原则**：
- 不做聚类、不做向量化、不做预处理。所有洞察由 LLM 读原文生成
- 数据链路：flomo 云端 → 本地 SQLite → D1 备份 / 洞察引擎
- 标签分类体系在 `src/tags/taxonomy.py` 版本控制，保持一致性

---

## 项目结构

```
src/
├── main.py              # CLI 入口（Typer）
├── mcp_server.py        # MCP Server（FastMCP）
├── config.py            # 配置管理
├── api/                 # flomo HTTP 客户端 + MD5 签名
│   ├── client.py        # FlomoClient（操作笔记）
│   └── sign.py          # MD5 签名算法
├── sync/                # 笔记同步
│   └── exporter.py      # 分页拉取 + upsert + 标签解析
├── search/              # 全文搜索
│   └── engine.py        # FTS5 + 标签过滤 + 统计
├── insight/             # 洞察引擎
│   ├── engine.py        # 笔记拉取 + prompt 组装
│   └── templates.py     # 6 种视角型洞察
├── importers/           # 微信读书导入
│   └── weread.py        # Skills API 调用 + 书评匹配 + 去重
├── review/              # 每日复习
│   └── engine.py        # 4 种关联策略（同标签/同书/近时间/双标签）
├── tags/                # 标签体系
│   ├── taxonomy.py      # 分类体系定义
│   └── classifier.py    # LLM 打标 prompt 生成
├── backup/              # 云端备份
│   └── d1.py            # wrangler CLI 封装
└── db/                  # 数据库
    └── __init__.py       # Schema + 迁移

config.toml.example       # 配置模板
config.toml               # 实际配置（gitignored）
data/                     # 本地数据库（gitignored）
worker/                   # Cloudflare Worker 部署文件
docs/                     # 文档
.claude/skills/           # Claude Code Skills
```

---

## Cloudflare Worker（每日复习）

部署在 `memo.example.com`，按 `due_at` 返回一条到期的复习卡片。

```bash
# 部署
cd worker
npx wrangler secret put REVIEW_KEY   # 访问密钥
npx wrangler secret put FLOMO_TOKEN  # flomo 同步用
npx wrangler deploy

# 访问(返回今天到期的一条卡片)
curl "https://memo.example.com/?key=<REVIEW_KEY>"
# → {"slug": "...", "content": "...", "hook": "...", "due": "2026-08-05"}

# 评分(推进下次复习时间)
curl -X POST "https://memo.example.com/?key=<REVIEW_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"slug":"...","grade":"good"}'
# → {"slug":"...","grade":"good","next_due":"2026-08-07","interval_days":2}
```

Worker 功能：
- `GET /?key=xxx` — 返回 `due_at <= 今天` 的卡片（最少访问优先）
- `POST /?key=xxx` — 接收评分，推进 SM-2 间隔
- Cron 每 2 天自动增量同步 flomo 笔记到 D1
- Ai binding（Kimi K2.6）已配置，暂未启用

---

## Skills（AI Agent 用）

本项目包含 4 个 Claude Code Skill，在 `.claude/skills/` 下：

| Skill | 文件 | 用途 |
|-------|------|------|
| 微信读书导入 | `tagging.md` | 导入流程、标签规则、过滤策略 |
| 洞察分析 | `insight.md` | 11 种洞察类型、操作步骤、推荐组合 |
| D1 备份 | `backup.md` | 备份原理、验证方法、定时配置 |
| 每日复习 | `review.md` | 生成流程、关联策略、Worker 部署 |

AI Agent 打开项目后读 `AGENTS.md`，自动发现这些 Skill。

---

## 微信读书导入流程

1. `flomo import weread` 拉取有书评的划线
2. Claude 从分类体系中为每篇选 1-2 个标签
3. 逐条调用 `flomo_create`（格式：`#标签 内容 ——《书名》作者 书评`）
4. 每条创建后调 `flomo_weread_mark_imported` 防重复
5. 重复直到 `flomo import weread` 返回"没有新笔记"

**过滤规则**（自动跳过的书评）：
- 纠错型：只是指出笔误（如"这里应该是 L 对 z 的偏导数"）
- 复述型：划线是 `y=exp(x)`，书评是 `y=eˣ`
- 灌水型：少于 5 个字且无实质内容

---

## 提交代码检查

提交前确认不包含：

```bash
# 检查敏感信息
git diff --staged | grep -iE 'token|secret|key|password|Bearer' \
  | grep -vE 'require_token|require_weread|_mask_token|api_key=flomo|config\.|\.example'

# 输出应为空
```

禁止提交的内容：
- `config.toml` 中的任何真实 token/key
- 调试产物（`.playwright-mcp/`、截图、临时脚本）
- `data/flomo.db`（已 gitignored）
- `worker/wrangler.toml` 中的 secret（通过 `wrangler secret put` 注入）

---

## 技术栈

- Python 3.12+ / Typer / FastMCP / httpx / pydantic
- SQLite + FTS5 全文搜索
- Cloudflare D1 / Workers
- 微信读书 Skills API
- flomo 内部 API（MD5 签名认证）
