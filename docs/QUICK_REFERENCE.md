# Avicenna Quick Reference

## File Organization

```
📂 Root Level
├── .env                    → API keys (SECRET - not in git)
├── .gitignore              → Git ignore rules
├── credentials.json        → Gmail OAuth (SECRET - not in git)
├── pyproject.toml         → Project metadata & dependencies
├── requirements.txt       → Python package list
└── ReadME.md              → Main documentation

📂 mcp_servers/            → MCP Protocol Layer
├── __init__.py            → Package marker
├── basic_server.py        → Time & calculator MCP server
├── gmail_server.py        → Gmail MCP server
├── mcp_client.py          → MCP client manager
└── mcp_config_schema.py   → Config data structures

📂 source/                 → Core Application
├── avicenna/
│   ├── config.py          → Configuration management
│   ├── core.py            → Agent orchestration
│   ├── main.py            → CLI entry point
│   └── providers/
│       └── gemini.py      → Gemini + MCP provider
└── tools/
    └── gmail.py           → Gmail API wrapper

📂 tests/                  → Test Suite
├── test_setup.py          → Integration test
├── verify_mcp_servers.py  → Phase 2 tests
├── verify_mcp_client.py   → Phase 3 tests
├── verify_gemini_provider.py → Phase 4 tests
└── verify_phase5.py       → Phase 5 tests

📂 docs/                   → Documentation
├── MCP_MIGRATION_ARCHITECTURE.md
├── MCP_MIGRATION_IMPLEMENTATION_PLAN.md
├── PHASE5_SUMMARY.md
├── PROJECT_STRUCTURE.md
└── REORGANIZATION_SUMMARY.md
```

## Common Tasks

### Run Avicenna
```bash
python -m source.avicenna.main chat
```

### Run Tests
```bash
python tests/verify_phase5.py          # Latest phase
python tests/test_setup.py             # Integration test
```

### Add New MCP Server
1. Create `mcp_servers/my_server.py`
2. Add to `~/.avicenna/mcp_config.json`
3. Restart Avicenna

### View Logs
Logs appear in terminal output (no separate log files)

### Update Configuration
Edit `~/.avicenna/mcp_config.json` (created on first run)

## Import Paths

```python
# Core agent
from source.avicenna.core import AvicennaAgent
from source.avicenna.config import Config

# MCP components
from mcp_servers.mcp_client import MCPClientManager
from mcp_servers.mcp_config_schema import MCPConfiguration

# Providers
from source.avicenna.providers.gemini import GeminiProvider

# Tools
from source.tools.gmail import GmailTool
```

## File Purposes

| File | Purpose |
|------|---------|
| `mcp_servers/basic_server.py` | Time & math tools |
| `mcp_servers/gmail_server.py` | Email capabilities |
| `mcp_servers/mcp_client.py` | Connects to MCP servers |
| `mcp_servers/mcp_config_schema.py` | Config structure |
| `source/avicenna/main.py` | CLI interface |
| `source/avicenna/core.py` | Agent logic |
| `source/avicenna/config.py` | Settings management |
| `source/avicenna/providers/gemini.py` | Gemini integration |
| `source/tools/gmail.py` | Gmail API wrapper |

## Key Commands

```bash
# Development
pip install -r requirements.txt        # Install dependencies
python -m source.avicenna.main chat    # Start agent

# Testing
python tests/verify_phase5.py          # Run verification
python tests/test_setup.py             # Basic integration test

# Cleanup
Remove-Item -Recurse -Force __pycache__  # Clear Python cache
Remove-Item $env:USERPROFILE\.avicenna\gmail_token.json  # Reset Gmail auth
```

## Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `.env` | Project root | API keys, model settings |
| `mcp_config.json` | `~/.avicenna/` | MCP server configuration |
| `gmail_token.json` | `~/.avicenna/` | Gmail OAuth token |
| `credentials.json` | Project root | Gmail OAuth client |

## Troubleshooting

### Import Errors
```bash
# Ensure you're in project root
cd "d:\Code Repositories\VSCode Repository\avicenna"

# Test imports
python -c "from source.avicenna.core import AvicennaAgent"
```

### MCP Server Not Found
Check `~/.avicenna/mcp_config.json` paths use `mcp_servers/` not `mcp/`

### Gmail Auth Issues
```bash
# Delete token and re-authenticate
Remove-Item $env:USERPROFILE\.avicenna\gmail_token.json
```

## Environment Variables

Required in `.env`:
```env
GOOGLE_API_KEY=your_gemini_api_key
AVICENNA_MODEL=gemini-2.0-flash-exp
```

## Version Info

**Current Version**: 1.0.0  
**Python Required**: ≥ 3.9  
**Architecture**: Async + MCP  

## Quick Links

- [Full README](../ReadME.md)
- [Project Structure](PROJECT_STRUCTURE.md)
- [Reorganization Summary](REORGANIZATION_SUMMARY.md)
- [MCP Architecture](MCP_MIGRATION_ARCHITECTURE.md)
