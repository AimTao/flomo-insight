# AGENTS.md — flomo-insight

新开对话的 Agent 入口。**用法与架构见 `README.md`；产品边界见 `docs/PRD.md`。**

动手前：读红线 → 读对应 `.claude/skills/` → 再改代码/跑 CLI。

---

## 红线

1. **先 flomo，后副本**：写操作成功后再写本地 SQLite / D1。  
2. **限速**：打 flomo 必须节流（本地 ≥1.2s，写更长；Worker 分页 sleep）。  
3. **LLM 产物写入前征得用户同意**（洞察、改标签等）。  
4. **不要加 MCP**（无 `fastmcp` / `mcp_server`）。  
5. **D1 只保留最新表结构**；旧表 DROP 重建。  
6. **不提交密钥**：`config.toml`、真实 `worker/wrangler.toml`、`data/`、`*.db`。  
7. **Python 不写洞察结论**；`flomo insight` 只出 prompt + 笔记。
8. **签名盐不入库**：`flomo_sign_salt` / secret `FLOMO_SIGN_SALT` 从 flomo 网页 bundle 自行配置。

---

## 改哪里

| 要改 | 位置 |
|------|------|
| CLI | `flomo_insight/main.py` |
| flomo HTTP / 签名 / 限速 | `flomo_insight/api/` |
| 同步、本地写镜像 | `flomo_insight/sync/` |
| 洞察 prompt | `flomo_insight/insight/` |
| 打标 / `tags_llm_at` | `flomo_insight/tags/` + `db/`（v4） |
| 复习卡推 D1 | `flomo_insight/review/push.py` |
| backup → D1 | `flomo_insight/backup/d1.py` |
| Worker | `worker/review-worker.js`、`worker/lib/` |
| Agent 行为 | `.claude/skills/*/SKILL.md` |

本地库与 D1 表结构见 README「数据模型」。冲突：`updated_at` 新者胜。

---

## 验证

```bash
uv run pytest -q
cd worker && npm test
```

命令清单、部署与 curl 示例：**只看 README**，本文不重复。

---

## Skills

| 目录 | 用途 |
|------|------|
| `.claude/skills/insight/` | 洞察；写入前确认 |
| `.claude/skills/tagging/` | 仅 `tags_llm_at` 为空的笔记；方案→确认→改→`tags-optimized` |
| `.claude/skills/review/` | review-push / insight-push |
| `.claude/skills/backup/` | 本地 backup 与 Worker cron |

---

## 提交前

```bash
git diff --cached | grep -iE 'Bearer |wrk-|REVIEW_KEY|flomo_token' \
  | grep -vE 'require_|_mask_|flomo_token|weread_key|REVIEW_KEY|FLOMO_TOKEN|config\.|\.example|Bearer <|Bearer \$\{'
# 应为空
```
