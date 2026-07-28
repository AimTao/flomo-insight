# flomo-insight

AI-powered insight engine for your flomo (浮墨笔记) notes — all LLM-driven, no clustering.

Sync your notes locally, then use Claude Code (via MCP) to get deep insights:
what topics you think about most, hidden connections between ideas, writing
drafts from your notes, and more.

## Quick Start

```bash
uv sync
cp config.toml.example config.toml
# Edit config.toml — set flomo_token
# Get it: Chrome F12 → Network → /api/ → Authorization → value after "Bearer "

flomo sync
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

Then in Claude Code: "分析我的笔记" or "用 CBT 视角看我的焦虑相关笔记"

## CLI Commands

```
flomo sync          Pull notes from flomo
flomo search "xxx"  Full-text search
flomo create "xxx"  Create a memo
flomo stats         Database stats
flomo recent        Recent memos
flomo tags          Tag list
flomo perspectives  List insight types
flomo mcp           Start MCP server
```

## Requirements

- Python 3.11+
- flomo account
