# Backup Skill

当用户要求备份到 D1、上传到 Cloudflare、同步备份时使用此 Skill。

## 操作

```
flomo backup                    # 增量推送至 Cloudflare D1
```

## 原理

- **全量**：首次运行，所有本地笔记推送到 D1
- **增量**：后续运行，只推送 `updated_at > max(D1.updated_at)` 的笔记
- **去重**：`INSERT ... ON CONFLICT(slug) DO UPDATE`，重复 slug 自动覆盖
- **源数据**：来自**本地 SQLite**（`data/flomo.db`），不是实时 flomo API

## 前置条件

```
flomo sync                     # 先同步到本地，再备份
```

## 验证方法

```bash
# 快速检查三方数据量是否一致
uv run python -c "
from src.config import load_config; from src.db import DatabaseManager
from src.backup.d1 import _run_wrangler
cfg = load_config(); db = DatabaseManager(cfg.db_path); conn = db.get_connection()
local = conn.execute('SELECT COUNT(*) FROM memos').fetchone()[0]; conn.close()
d1 = _run_wrangler(cfg.d1_database_id, 'SELECT COUNT(*) as cnt FROM memos')
print(f'本地: {local}, D1: {d1[0][\"results\"][0][\"cnt\"]}')
"
```

## 定时备份

系统 crontab（持久化，Claude 退出后仍生效）：
```
37 9 * * * cd /path/to/flomo-insight && uv run flomo backup >> /tmp/flomo-backup.log 2>&1
```

## 注意事项

- D1 不会自动删除本地已删除的笔记——需要在 D1 手动 `DELETE FROM memos WHERE slug='...'` 清理
- 备份前务必先 `flomo sync` 确保本地是最新的
- 定期验证三方（API / 本地 / D1）数量一致性
