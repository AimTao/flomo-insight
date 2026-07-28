# AGENTS.md — flomo-insight

AI-powered analysis and insight engine for flomo + WeRead import.

## Project structure

```
src/                         # Python package
├── main.py                  # CLI (Typer)
├── mcp_server.py            # MCP Server (FastMCP) — 10 tools
├── config.py                # All settings from config.toml
├── api/                     # flomo HTTP client + MD5 sign
├── sync/                    # Paginated memo sync
├── search/                  # FTS5 full-text search
├── analysis/                # Embeddings, clustering, trends, cooccurrence
├── insight/                 # LLM-driven insight engine (11 types)
├── importers/               # WeRead highlight+review import
└── utils/                   # jieba tokenization
config.toml.example          # Template — user copies to config.toml
config.toml                  # Secrets + settings (gitignored)
data/                        # Database (gitignored)
pyproject.toml
AGENTS.md
README.md
```

## Setup (for a new developer)

```bash
uv sync
cp config.toml.example config.toml
# Edit config.toml with flomo_token and optionally weread_key
flomo sync
flomo analyze
```

## Key decisions

- **All settings in config.toml**: Secrets + non-sensitive settings in one file. User copies `config.toml.example` to get started. Both `config.toml` and `data/` are gitignored.
- **Insights are MCP-only**: The insight engine fetches notes + wraps them with a system prompt. Claude Code reads the package and generates the analysis. CLI only prepares data.
- **WeRead import uses official Skills API**: API key from https://weread.qq.com/r/weread-skills (format `wrk-xxxxxxxx`).
- **Tests use synthetic data only**: No real user data in test fixtures.

## MCP Tools (10)

| Tool | Purpose |
|------|---------|
| `flomo_search` | FTS5 search + tag filter |
| `flomo_create` | Create memo (cloud + local) |
| `flomo_sync` | Sync from flomo API |
| `flomo_analyze` | Run analysis pipeline |
| `flomo_insight` | LLM-driven insight (11 types) |
| `flomo_recent` | Recent memos |
| `flomo_tags` | Tag list + counts |
| `flomo_import_weread` | Fetch WeRead highlights + reviews |
| `flomo_weread_mark_imported` | Dedup tracking |
| `flomo_weread_stats` | Import stats |

## Insight types (MCP: flomo_insight)

### Analytical (notes + cluster data + prompt)
- `topics`, `stagnant`, `declining`, `connections`, `draft`

### Perspective lenses (notes + thinking lens prompt)
- `default`, `value-clarification`, `inversion`, `second-order`, `cbt`, `mbti`

## File locations

| What | Where | In git? |
|------|-------|---------|
| Source code | `src/` | ✅ |
| Config template | `config.toml.example` | ✅ |
| Config (secrets) | `config.toml` | ❌ |
| Database | `data/` | ❌ |
