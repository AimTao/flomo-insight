# flomo-insight 开发任务清单

> 给后续 agent 接手用。每项标注状态、优先级、要点。

## 项目定位

把 flomo 笔记拉到本地 SQLite，通过 MCP 让 Claude Code 读原始笔记出深度洞察。
**全部 LLM 驱动，不做聚类/向量化/预处理。**

---

## ✅ 已完成

### 数据管线
- [x] flomo API 同步（Bearer token + MD5 签名，已实测 88 条笔记）
- [x] 增量同步游标（latest_slug / latest_updated_at）— 修复末页游标 bug
- [x] FTS5 全文搜索 + 标签过滤（修复 external content 模式 + snippet 索引）
- [x] 创建笔记（推送 flomo 云端）
- [x] 标签提取与多对多关系（修复 #tag HTML 后缀 bug）

### 洞察引擎（MCP，11 种，全部 LLM 驱动）
- [x] topics / stagnant / declining / connections / draft（5 分析型）
- [x] default / value-clarification / inversion / second-order / cbt / mbti（6 视角）

### 微信读书导入
- [x] 官方 Skills API 接入（wrk-xxx key，POST gateway）
- [x] 拉取有书评的划线（bookmarklist + review/list/mine，按 range 匹配）
- [x] 去重表 weread_imports（按 review_id）
- [x] 导入 prompt 生成（强制 #微信读书 标签 + LLM 分类）
- [x] **自动导入闭环**（auto_import + flomo_import_weread_auto MCP + --auto CLI）

### 备份
- [x] **Cloudflare D1 备份**（flomo backup 命令，增量，批量 upsert）
- [x] config.toml 支持 d1_account_id / d1_database_id / d1_api_token

### 错误处理
- [x] **FlomoAuthError**（token 过期 code -10/-100，不重试，友好提示）
- [x] **网络超时/5xx 重试**（3 次指数退避）
- [x] **flomo 限流监控**（x-ratelimit-remaining ≤ 10 时 sleep）

### 工程
- [x] 单文件配置 config.toml（gitignored）+ config.toml.example（模板）
- [x] 数据隔离：config.toml / data/ 全部 gitignored
- [x] 9 → 11 个 MCP 工具（含 weread_auto）
- [x] flat src/ 布局
- [x] PRD.md / AGENTS.md / README.md / LICENSE (MIT)
- [x] 删除聚类管线（analysis/、jieba、torch 等，省 2GB 依赖）
- [x] 修复删聚类后的死引用（templates.py / db_stats / snippet 索引）

### 测试（79 passed）
- [x] test_sign.py — MD5 签名（用真实抓取参数验证）
- [x] test_sync.py — upsert/增量游标/tags解析/幂等
- [x] test_search.py — FTS5 查询/标签过滤/snippet/recent/tags/stats
- [x] test_insight.py — 11 种洞察类型返回非空
- [x] test_weread.py — 去重/prompt 构建/统计/auto_import
- [x] test_client.py — auth 错误/重试/限流/verify
- [x] test_backup.py — D1 增量/批量/schema/错误处理（mocked HTTP）

---

## 🟢 P2 — 增强（可选）

- [ ] CI（GitHub Actions 跑 pytest）
- [ ] 导出功能：按标签导出 Markdown 文件
- [ ] config.toml.example 补充 token 获取截图说明
- [ ] `flomo doctor` 命令：检查 token 有效性、DB 完整性、依赖版本
- [ ] MCP flomo_backup 工具（让 Claude Code 触发备份）

---

## ❌ 明确不做

- **聚类 / 向量化 / embedding** — 笔记量 < 200 时聚类反而丢失信息，LLM 读原文更准
- **Web UI** — 只做 CLI + MCP
- **自动同步** — 手动触发 `flomo sync`，不做后台轮询
- **LLM 生成洞察** — 洞察由 Claude Code 读取 prompt 后生成，本项目只负责取数据 + 包装 prompt
- **邮箱密码登录** — 只用 Bearer token，不存密码
- **微信读书写入** — 只读划线/书评，不写回微信读书
