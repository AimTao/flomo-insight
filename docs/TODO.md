# TODO

产品范围见 `docs/PRD.md`；红线见 `AGENTS.md`；用法见 `README.md`。

## 待做

（当前无阻塞项。）

发布前可再跑一遍：

```bash
uv run pytest -q && cd worker && npm test
git ls-files | grep -iE 'config\.toml$|wrangler\.toml$|\.db$'
git diff --cached | grep -iE 'Bearer |wrk-|REVIEW_KEY|flomo_token' | grep -vE 'require_|_mask_|config\.|\.example|Bearer <|Bearer \$\{'
```

## 已收口

- `flomo push`（`source=local` → flomo）+ 测试  
- taxonomy 与 tagging skill 例外规则对齐  
- 调试目录已清理；`config.toml` / 真实 `wrangler.toml` 从未进 git  
- Worker 已 deploy；D1 已用本地 `backup`/`review-push` 回填（cron 周期后可再对一次数）  
