# flomo-insight

AI-powered analysis and insight engine for your flomo (浮墨笔记) data.

Pull your flomo notes locally, search them, and discover hidden patterns in your
thinking — topics you focus on, ideas that repeat, connections you hadn't noticed.

## Quick Start

```bash
# Install
uv sync

# Set your flomo token (from browser DevTools → Application → Cookies → flomoapp.com → token)
flomo config set-token YOUR_TOKEN

# Pull all your notes
flomo sync

# Search
flomo search "思考" --tags 工作

# Analyze & get insights
flomo analyze
flomo insight --type topics
```

## Requirements

- Python 3.11+
- A flomo account (token from browser cookies)
