# flomo-insight

AI-powered analysis and insight engine for your flomo (浮墨笔记) notes + WeRead (微信读书) import.

Pull your notes locally, search them, and discover hidden patterns in your thinking — topics you focus on, ideas that repeat, connections you hadn't noticed. All insights are LLM-driven via Claude Code MCP.

## Quick Start

```bash
# 1. Clone and install
git clone <repo>
cd flomo-insight
uv sync

# 2. Configure
cp config.toml.example config.toml
# Edit config.toml — set your flomo_token
# Get it: Chrome F12 → Network → /api/ → Authorization → value after "Bearer "

# 3. Sync & analyze
flomo sync
flomo analyze
```

## MCP Integration (Claude Code)

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

## CLI Commands

```
flomo sync          Sync notes from flomo
flomo search "xxx"  Full-text search
flomo create "xxx"  Create a memo
flomo analyze       Run analysis pipeline
flomo stats         Database statistics
flomo config show   Show configuration
flomo mcp           Start MCP server
```

## Requirements

- Python 3.11+
- flomo account (token from browser)
