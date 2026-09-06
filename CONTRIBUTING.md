# Contributing

## 开发

```bash
uv sync
uv run pytest -q
cd worker && npm test
```

## 架构约定

- **flomo 是唯一权威源**；写路径先 flomo，成功后再写本地 SQLite / D1
- **智能只在本地 LLM**；Python / Worker 不生成洞察结论
- **无 MCP**；Agent 使用 CLI + `.claude/skills/`
- Worker **不**对外提供 sync/CRUD；同步只在 cron 内发生

详见 `docs/PRD.md`。

## 提交前检查

不得提交：

- `config.toml`、真实 `worker/wrangler.toml`
- `data/`、`*.db`、`.wrangler/`、调试截图
- 任何真实 token / key / 个人域名

```bash
git diff --cached | grep -iE 'Bearer |wrk-|REVIEW_KEY|flomo_token' \
  | grep -vE 'require_|_mask_|flomo_token|weread_key|REVIEW_KEY|FLOMO_TOKEN|config\.|\.example|Bearer <|Bearer \$\{'
# 应为空
```

## 测试

- 新功能先写失败测试（pytest / `node --test`）
- 不使用真实笔记数据；fixtures 用合成内容
