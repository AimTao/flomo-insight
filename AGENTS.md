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
- **Tokens/cookies are stored separately**: `~/.local/share/flomo-insight/.token`
  and `.weread_cookie`, both 0600. Never in config.toml, never in git.
- **All user data is outside the repo**: Database, tokens, cookies, and config
  all live under `~/.local/share/flomo-insight/` and `~/.config/flomo-insight/`.
- **Tests use synthetic data only**: No real flomo or weread data in test fixtures.

## Setup

```bash
uv sync
flomo config set-token YOUR_FLOMO_TOKEN         # Chrome DevTools → Cookies → flomoapp.com → token
flomo config set-weread-key wrk-xxxxxxxx          # https://weread.qq.com/r/weread-skills
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

### Secrets (0600 files under ~/.local)
- `.token` — flomo API token (from browser cookies)
- `.weread_key` — WeRead Skills API key (format `wrk-xxx`)

These NEVER appear in:
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
.token *.token             # all auth tokens
.weread_key               # WeRead API key
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
| Flomo token | `~/.local/share/flomo-insight/.token` | ❌ |
| WeRead key | `~/.local/share/flomo-insight/.weread_key` | ❌ |
| Database | `~/.local/share/flomo-insight/flomo.db` | ❌ |
| Test data | `tests/fixtures/` (synthetic only) | ✅ |
