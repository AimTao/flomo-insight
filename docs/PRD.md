# flomo-insight PRD

产品需求与边界。安装、命令、架构见 `README.md`；Agent 红线见 `AGENTS.md`。

## 这是什么

把 flomo（浮墨笔记）同步到本地 SQLite 与 Cloudflare D1，并用**本地 LLM** 做洞察与标签整理。

- **flomo 是唯一权威源**；本地与 Cloudflare 都是副本。
- **智能只在本地**：Claude + Skills 写结论；Python / Worker 只搬运、打包 prompt。

## 为什么做

- flomo 缺少跨笔记的深度分析
- 希望笔记多端镜像，不依赖一台常开电脑
- 复习要能同时看到原文卡与洞察卡
- AI 能力用 Skills 组合，不绑死 MCP

## 关于 flomo API

无公开 Open API。使用 Web 内部接口 + Bearer + MD5（`flomo_insight/api/sign.py`）。与抓包对齐，不保证长期稳定。

## 核心原则

1. 写操作最终落在 flomo；**先 flomo、后副本**  
2. 冲突：`updated_at` 新者胜  
3. 洞察与打标由 LLM 完成，代码只取数 + 包 prompt  
4. 无 MCP；Agent 用 CLI + Skills  
5. LLM 产物写入存储前须用户确认  
6. 密钥：`flomo_token` / `weread_key` / `REVIEW_KEY` 分离，不入库  

架构示意与表结构见 README。

## 功能范围

### 数据

- [x] flomo ↔ 本地增量/全量同步  
- [x] 单条 create / update / delete（先 flomo 后本地）  
- [x] FTS5 搜索、标签  
- [x] 微信读书划线+书评导入（本地 LLM 打标需确认；`--auto` 仅 `#微信读书`）  
- [x] Worker cron：flomo → D1（含 tags）  
- [x] 本地 backup → D1  

### 智能（仅本地 LLM）

- [x] 11 种洞察素材 CLI（prompt + 笔记，无结论）  
- [x] 洞察可推送为复习卡（`insight-push`，需确认）  
- [x] 闭集 taxonomy + retag；`tags_llm_at` 区分是否已优化  
- [x] Skills：insight / tagging / review / backup  

### 复习（Cloudflare）

- [x] `GET /?key=REVIEW_KEY`，按 `served_count` 轮转  
- [x] `kind=memo|insight|all`  

## 明确不做

聚类/向量化 · Web UI · MCP · Worker 对外 sync/CRUD · Python/JS 生成洞察结论 · 写回微信读书 · 账号密码登录

## 技术选型

| 选型 | 理由 |
|------|------|
| Python + Typer | 本地 CLI 与同步 |
| SQLite + FTS5 | 洞察数据源 |
| Cloudflare Worker + D1 | 云端镜像与复习 |
| Claude Skills | 可组合智能 |

## 安全与开源

- `config.toml`、`data/`、真实 `wrangler.toml` gitignore  
- 仓库只留 `*.example`  
- 源码不硬编码 token  
