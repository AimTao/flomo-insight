# AGENTS.md — flomo-insight

AI-powered analysis and insight engine for flomo (浮墨笔记) + WeRead (微信读书) import.

## Architecture

```
CLI (Typer)          MCP Server (FastMCP)
    │                      │
    ├─ sync                ├─ flomo_search
    ├─ search              ├─ flomo_create
    ├─ create              ├─ flomo_sync
    ├─ analyze             ├─ flomo_analyze
    ├─ recent              ├─ flomo_insight  (all types)
    ├─ tags                ├─ flomo_recent
    ├─ stats               ├─ flomo_tags
    ├─ perspectives        ├─ flomo_import_weread
    ├─ weread-stats        ├─ flomo_weread_mark_imported
    ├─ import weread       └─ flomo_weread_stats
    ├─ config
    └─ mcp

        ┌───────────┴───────────┐
        │     SQLite (FTS5)     │
        │  + embedding vectors  │
        │  + cluster assignments│
        │  + trend data         │
        │  + weread_imports     │
        └───────────────────────┘
            │               │
    ┌───────┴──────┐  ┌─────┴──────────┐
    │ flomo API    │  │ WeRead API     │
    │ (token)      │  │ (cookie)       │
    └──────────────┘  └────────────────┘
```

## Key decisions

- **Insights are MCP-only**: The insight engine fetches notes + wraps them
  with a system prompt. Claude Code reads the package and generates the
  analysis. CLI cannot produce insights — it only prepares data (sync/analyze).
- **WeRead import uses the official Skills API**: API key from
  https://weread.qq.com/r/weread-skills (format `wrk-xxxxxxxx`).
  Authenticated via `Authorization: Bearer wrk-xxx` header.
- **All secrets in one file**: `~/.local/share/flomo-insight/.secrets` (0600 TOML).
  Contains `flomo_token` and `weread_key`. Never in git.
- **All user data is outside the repo**: Database, tokens, cookies, and config
  all live under `~/.local/share/flomo-insight/` and `~/.config/flomo-insight/`.
- **Tests use synthetic data only**: No real flomo or weread data in test fixtures.

## Setup

```bash
uv sync
# Edit ~/.local/share/flomo-insight/.secrets :
#   flomo_token = "xxx"
#   weread_key = "wrk-xxx"
flomo sync                                       # pull all flomo notes
flomo analyze                                    # embeddings + clustering + trends
```

## MCP Integration

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

## Insight types (MCP: flomo_insight)

### Analytical (notes + cluster data + prompt)
- `topics` — Cluster analysis, themes, patterns, blind spots
- `stagnant` — Ideas spanning 60+ days, thought loop detection
- `declining` — Topics with negative trend, interest trajectory
- `connections` — Tag co-occurrence, cross-domain bridges
- `draft` — Article structure from largest topic cluster

### Perspective lenses (notes + thinking lens prompt)
- `default` — Core themes, contradictions, blind spots (by flomo)
- `value-clarification` — Find what you truly value (by shaonan)
- `inversion` — Munger-style reverse thinking (by flomo)
- `second-order` — Problems above problems (by shaonan)
- `cbt` — Cognitive distortion detection (by flomo)
- `mbti` — Personality type inference (by flomo)

## WeRead import flow (MCP)

```
1. flomo_import_weread(batch_size=15)
   → Fetches reviewed highlights (划线+书评) from WeRead Skills API
   → Only returns highlights that have personal reviews attached
   → Returns formatted prompt with highlight text + review text
2. Claude reads each pair, classifies with tags
3. For each: flomo_create(content, tags=["微信读书", ...])
   content format:
     > 划线内容

     书评内容

     ——《书名》作者
4. After each: flomo_weread_mark_imported(review_id=..., ...)
```

API: `POST https://i.weread.qq.com/api/agent/gateway`
Auth: `Authorization: Bearer wrk-xxxxxxxx`

## Security & Privacy — NEVER leak these into git

This project is designed to be open-source. All user-specific data lives
outside the repo. Here's what you must protect:

### Secrets (single file, 0600)
- `.secrets` — `~/.local/share/flomo-insight/.secrets` — TOML format:
  ```toml
  flomo_token = "xxx"
  weread_key = "wrk-xxx"
  ```

This file NEVER appears in:
- `pyproject.toml` or any source file
- `config.toml` (TOML config only stores non-secret settings)
- Environment variables checked into the repo
- Test fixtures or test code
- Commit messages, comments, or documentation

### User data (stored outside the repo)
- `flomo.db` — full flomo note database (contains all your notes, tags, embeddings)
- `config.toml` — local configuration paths

### .gitignore checklist
The `.gitignore` blocks:
```
*.db *.sqlite *.sqlite3    # all databases
.secrets                   # all auth tokens
```

### Before committing, always verify
```bash
git status                  # check no secrets staged
git diff --cached           # review staged changes
grep -r "token\|wrk-" src/  # confirm no secrets in source
```

### If a secret is accidentally committed
```bash
git filter-branch --force --env-filter '...'  # or git filter-repo
```
Rotate the compromised credential immediately (re-login on weread.qq.com
or get a new flomo token from browser).

## File locations

| What | Where | In git? |
|------|-------|---------|
| Source code | `src/flomo_insight/` | ✅ |
| Config | `~/.config/flomo-insight/config.toml` | ❌ |
| Flomo + WeRead secrets | `~/.local/share/flomo-insight/.secrets` | ❌ |
| Database | `~/.local/share/flomo-insight/flomo.db` | ❌ |
| Test data | `tests/fixtures/` (synthetic only) | ✅ |
