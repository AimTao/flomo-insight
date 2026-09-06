---
name: backup
description: 将本地 memos 增量备份到 Cloudflare D1。当用户要求「备份到 D1」「backup」时使用。日常云端镜像应依赖 Worker cron，本命令是本地补充手段。
---

# Backup Skill

```bash
flomo sync
flomo backup
```

## 原理

- 首次全量；之后只推 `updated_at > D1.MAX(updated_at)`  
- `ON CONFLICT(slug) DO UPDATE`  
- **不推标签关系**；本地删除**不会**删 D1 行  
- 鉴权：本机 `wrangler` OAuth（`npx wrangler login`），不是 API Token  

## 与 Worker cron

| | 本地 `flomo backup` | Worker cron |
|--|---------------------|-------------|
| 触发 | 你手动 | 定时 |
| 源 | 本地 SQLite | 直接拉 flomo API |
| 适合 | 无 cron 时的补充 | 常态镜像 |

两边写的是同一张 D1 `memos` 表（若 `d1_database_id` 一致）。

## 验证

```bash
flomo stats
# 再用 wrangler d1 execute 对比 COUNT(*)（需已 login）
```
