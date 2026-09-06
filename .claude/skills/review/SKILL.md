---
name: review
description: 把本地笔记原文推送到 Cloudflare D1 复习卡，或把写好的洞察推成复习卡。当用户要求「更新复习」「推送卡片」「review-push」时使用。
---

# Review Skill

复习数据在 D1 `daily_reviews`，Worker 用 `REVIEW_KEY` 对外提供轮转 API。

## 硬性规则

- `flomo review-push`：同步**本地已有的原文卡**到 D1；执行前向用户说明会 upsert 哪些，或等用户明确要求再跑。
- `flomo insight-push`：**LLM 产物**，必须先展示洞察全文并**等用户确认**，禁止自动推送。

## 卡片类型

| kind | 来源 | 命令 |
|------|------|------|
| `memo` | 笔记原文（去 HTML/去标签） | `flomo review-push` |
| `insight` | LLM 写好的洞察全文 | `flomo insight-push --type T --file f.md`（需确认） |

## 操作

```bash
flomo sync
flomo review-push
```

- **不会 DROP 表**，`served_count` 轮转进度会保留  
- 近重复卡会去重；空卡跳过  

洞察卡见 `insight` Skill；推送前必须用户同意。

## Worker

同步是 **Cloudflare Cron**（`wrangler.toml` 的 `[triggers] crons` + Worker 的 `scheduled()`），不是本机 crontab。部署与改频率见 README「Cloudflare Worker」。

```bash
curl "https://<worker>/?key=<REVIEW_KEY>"
curl "https://<worker>/?key=<REVIEW_KEY>&kind=insight"
```

Worker cron **不会**生成洞察，只镜像 flomo / 微信读书到 D1；洞察只能本地 LLM 写完再 `insight-push`。
