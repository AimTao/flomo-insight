# flomo-insight 开发任务清单

> 给后续 agent 接手用。每项标注状态、优先级、要点。

## 项目定位

把 flomo 笔记拉到本地 SQLite，通过 MCP 让 Claude Code 读原始笔记出深度洞察。
**全部 LLM 驱动，不做聚类/向量化/预处理。**

---

## ✅ 已完成

### 数据管线
- [x] flomo API 同步（Bearer token + MD5 签名，已实测 88 条笔记）
- [x] 增量同步游标（latest_slug / latest_updated_at）
- [x] FTS5 全文搜索 + 标签过滤（snippet 列索引已修）
- [x] 创建笔记（推送 flomo 云端）
- [x] 标签提取与多对多关系

### 洞察引擎（MCP，11 种，全部 LLM 驱动）
- [x] topics — 主题全景分析
- [x] stagnant — 停滞检测
- [x] declining — 兴趣消退分析
- [x] connections — 跨界连接（含标签共现提示）
- [x] draft — 写作草稿生成
- [x] default / value-clarification / inversion / second-order / cbt / mbti（6 种视角）

### 微信读书导入
- [x] 官方 Skills API 接入（wrk-xxx key，POST gateway）
- [x] 拉取有书评的划线（bookmarklist + review/list/mine，按 range 匹配）
- [x] 去重表 weread_imports（按 review_id）
- [x] 导入 prompt 生成（强制 #微信读书 标签 + LLM 分类）

### 工程
- [x] 单文件配置 config.toml（gitignored）+ config.toml.example（模板）
- [x] 数据隔离：config.toml / data/ 全部 gitignored
- [x] 9 个 MCP 工具
- [x] flat src/ 布局
- [x] PRD.md / AGENTS.md / README.md
- [x] 删除聚类管线（analysis/、jieba、torch 等，省 2GB 依赖）
- [x] 修复删聚类后的死引用（templates.py / db_stats / snippet 索引）

---

## 🔴 P0 — 开源前必做

### 测试套件
- [ ] `tests/conftest.py` — 临时 SQLite fixture
- [ ] `tests/test_sign.py` — MD5 签名（用真实抓到的请求参数做 fixture，已知正确 sign）
- [ ] `tests/test_sync.py` — upsert 逻辑、增量游标、tags 解析
- [ ] `tests/test_search.py` — FTS5 查询、标签过滤、snippet
- [ ] `tests/test_insight.py` — 11 种洞察类型都返回非空字符串
- [ ] 合成测试数据 fixture（**严禁用真实用户数据**）

### LICENSE
- [ ] 添加 MIT LICENSE 文件

### 增量同步验证
- [ ] 第二次 `flomo sync` 不重复拉、不漏拉（游标逻辑）
- [ ] full=True 全量重灌正确

---

## 🟡 P1 — 核心功能补全

### 微信读书自动导入闭环
- [ ] 现状：`flomo_import_weread` 只返回 prompt，需 Claude 手动逐条调 flomo_create
- [ ] 目标：加 `flomo_import_weread_auto` 工具，内部循环调 create + mark_imported
- [ ] 或者：在 prompt 里明确编排指令让 Claude 批量执行

### Cloudflare D1 备份
- [ ] 用户明确要求过，未实现
- [ ] 设计：`flomo backup` 命令，把 memos 表推到 D1
- [ ] 配置项：d1_account_id / d1_database_id / d1_api_token（加到 config.toml）
- [ ] 增量备份（按 updated_at）

### 错误处理
- [ ] token 过期 → 友好提示重新设置（现在是裸 RuntimeError）
- [ ] 网络超时 → 重试 3 次，指数退避
- [ ] flomo 限流 → 监控 `x-ratelimit-remaining`，接近时 sleep

---

## 🟢 P2 — 增强

- [ ] CI（GitHub Actions 跑 pytest）
- [ ] 导出功能：按标签导出 Markdown 文件
- [ ] config.toml.example 补充 token 获取截图说明
- [ ] `flomo doctor` 命令：检查 token 有效性、DB 完整性、依赖版本

---

## ❌ 明确不做

- **聚类 / 向量化 / embedding** — 笔记量 < 200 时聚类反而丢失信息，LLM 读原文更准
- **Web UI** — 只做 CLI + MCP
- **自动同步** — 手动触发 `flomo sync`，不做后台轮询
- **LLM 生成洞察** — 洞察由 Claude Code 读取 prompt 后生成，本项目只负责取数据 + 包装 prompt
- **邮箱密码登录** — 只用 Bearer token，不存密码
- **微信读书写入** — 只读划线/书评，不写回微信读书
