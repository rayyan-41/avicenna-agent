# Avicenna - AI Agent with MCP Ecosystem Integration

**Version 2.0 - MCP Ecosystem**

A constitutional AI agent built on the Model Context Protocol (MCP), named after the Persian polymath Ibn Sina (Avicenna). Now integrated with the official MCP ecosystem for powerful, extensible tooling.

## ✨ What's New in Version 2.0

- **🌐 MCP Ecosystem Integration**: Connect to official MCP servers from the community
- **📦 Node.js Server Support**: Run npm packages directly via `npx`
- **📁 Filesystem Operations**: 14 file/directory tools for local file access
- **🧠 Sequential Thinking**: Enhanced reasoning for complex problems
- **📊 Server Status Display**: See which servers are connected at startup
- **⚙️ Multi-Type Servers**: Support for Python, Node.js, and executable servers
- **🔧 Better Configuration**: Version-aware config with backward compatibility

## Features

### Core Capabilities
- **Constitutional AI Framework**: Operates under ethical principles and user authority
- **MCP Architecture**: Tools run as independent MCP servers (stdio protocol)
- **Async Design**: Modern async/await Python architecture
- **Retro Terminal UI**: Green-on-black aesthetic with Rich formatting
- **Auto-Discovery**: Tools are automatically discovered from connected servers

### Available MCP Servers

#### Default (Enabled)
- **📁 Filesystem** (`@modelcontextprotocol/server-filesystem`) - 14 tools
  - Read/write files, create directories, search files, file info, directory trees
  - Configure allowed directories in config for security
  
- **🧠 Sequential Thinking** (`@modelcontextprotocol/server-sequential-thinking`) - 1 tool
  - Enhanced multi-step reasoning for complex problems

#### Optional (Disabled by Default)
- **🌐 Fetch** (`mcp-server-fetch-typescript`)
  - Web content fetching and extraction
  - Requires: `npx playwright install`
  
- **🔍 Brave Search** (`@modelcontextprotocol/server-brave-search`)
  - Web search via Brave Search API
  - Requires: `BRAVE_API_KEY` environment variable

## Installation

### Prerequisites
- Python 3.10+
- Node.js 16+ (for MCP ecosystem servers)
- Git

### Setup

```bash
# Clone repository
git clone https://github.com/rayyan-41/avicenna-agent.git
cd avicenna-agent

# Install dependencies
pip install -r requirements.txt

# Verify Node.js is installed
node --version
npx --version
```

## Configuration

### 1. API Keys

Create `.env` file in project root:

```env
GOOGLE_API_KEY=your_gemini_api_key_here
AVICENNA_MODEL=gemini-2.0-flash
```

### 2. MCP Server Configuration

First run creates `~/.avicenna/mcp_config.json` with defaults:

```json
{
  "version": "2.0",
  "mcp_servers": [
    {
      "name": "filesystem",
      "type": "node",
      "package": "@modelcontextprotocol/server-filesystem",
      "enabled": true,
      "description": "Read/write local files",
      "args": []
    },
    {
      "name": "sequential-thinking",
      "type": "node",
      "package": "@modelcontextprotocol/server-sequential-thinking",
      "enabled": true,
      "description": "Enhanced reasoning"
    }
  ]
}
```

**Security Note**: Add allowed directories to filesystem server:
```json
{
  "name": "filesystem",
  "type": "node",
  "package": "@modelcontextprotocol/server-filesystem",
  "enabled": true,
  "args": ["C:\\Users\\YourName\\Documents", "C:\\Users\\YourName\\Downloads"]
}
```

## Usage

```bash
# Start Avicenna
python -m source.avicenna.main

# Or if installed:
avicenna
```

### Startup Display

```
> SYSTEM ONLINE
Model: gemini-2.0-flash

🔌 Initializing MCP servers...

                    MCP Servers                     
┏━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┓
┃ Status ┃ Server         ┃ Type    ┃ Tools ┃ Info      ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━┩
│   ✓    │ filesystem     │ Node.js │    14 │ Connected │
│   ✓    │ sequential-... │ Node.js │     1 │ Connected │
└────────┴────────────────┴─────────┴───────┴───────────┘
📦 2/2 servers connected, 15 tools available

🤖 Testing gemini-2.0-flash... ✓ Ready
```

### Example Commands

```
> List files in my documents folder
> Create a new file called notes.txt
> What's the current time?
> Help me solve this complex problem step by step
> exit
```

## Project Structure

```
avicenna/
├── mcp_servers/                  # MCP infrastructure
│   ├── __init__.py
│   ├── mcp_client.py            # MCP client manager (v2.0)
│   ├── mcp_config_schema.py     # Configuration schema (v2.0)
│   └── deprecated/              # Legacy servers (v1.0)
│       ├── basic_server.py      # Time/calculator (deprecated)
│       ├── gmail_server.py      # Gmail (deprecated)
│       └── README.md
├── source/
│   ├── avicenna/
│   │   ├── config.py            # Configuration management
│   │   ├── core.py              # Main agent logic (v2.0)
│   │   ├── main.py              # CLI entry point (v2.0)
│   │   └── providers/
│   │       └── gemini.py        # Gemini + MCP provider (v2.0)
│   └── tools/
│       ├── __init__.py
│       └── deprecated/          # Legacy tool implementations
│           ├── gmail.py
│           └── README.md
├── docs/                         # Documentation
│   ├── MCP_ECOSYSTEM_MIGRATION.md
│   ├── MCP_MIGRATION_ARCHITECTURE.md
│   └── AVICENNA_VERSION_HISTORY.md
├── tests/                        # Verification scripts
├── .env                          # API keys (not in git)
├── pyproject.toml               # Project metadata
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Adding Custom MCP Servers

### Option 1: Node.js Package from npm

```json
{
  "name": "my-server",
  "type": "node",
  "package": "@username/mcp-server-name",
  "enabled": true,
  "description": "My custom server",
  "env": {
    "API_KEY": "your-key"
  }
}
```

### Option 2: Local Python Script

```python
# mcp_servers/my_server.py
from fastmcp import FastMCP

mcp = FastMCP("My Server")

@mcp.tool()
def my_tool(arg: str) -> str:
    """Tool description"""
    return f"Result: {arg}"

if __name__ == "__main__":
    mcp.run()
```

Add to config:
```json
{
  "name": "my-server",
  "type": "python",
  "script": "mcp_servers/my_server.py",
  "enabled": true
}
```

### Option 3: Direct Executable

```json
{
  "name": "my-command",
  "type": "executable",
  "command": "/path/to/executable",
  "enabled": true,
  "args": ["--option", "value"]
}
```

## Configuration Reference

### Server Types

- **`node`**: npm packages run via `npx -y <package>`
- **`python`**: Local Python scripts
- **`executable`**: Direct command execution

### Required Fields by Type

| Type | Required Fields |
|------|----------------|
| `node` | `name`, `type`, `package` |
| `python` | `name`, `type`, `script` |
| `executable` | `name`, `type`, `command` |

### Optional Fields (All Types)

- `enabled` (boolean): Enable/disable server
- `description` (string): Human-readable description
- `args` (array): Command-line arguments
- `env` (object): Environment variables

- `enabled` (boolean): Enable/disable server
- `description` (string): Human-readable description
- `args` (array): Command-line arguments
- `env` (object): Environment variables

## Troubleshooting

### No servers connected

Check Node.js installation:
```bash
node --version  # Should be v16+
npx --version
```

### Server connection fails

1. Check the MCP server status display at startup
2. Enable debug logging: `python -m source.avicenna.main --debug`
3. Check `avicenna.log` for detailed error messages
4. Verify package names are correct (npm package must exist)

### Filesystem server: Permission denied

Add allowed directories to the server configuration:
```json
{
  "name": "filesystem",
  "args": ["C:\\Users\\YourName\\Documents"]
}
```

## Testing

Run verification tests:

```bash
# Test MCP servers
python tests/verify_mcp_servers.py

# Test MCP client
python tests/verify_mcp_client.py

# Test Gemini provider
python tests/verify_gemini_provider.py
```

## Architecture

Avicenna uses the **Model Context Protocol (MCP)** for tool integration:

### Components

- **Gemini API**: Large Language Model provider (Google)
- **MCP Client Manager**: Discovers and manages tool servers
- **MCP Servers**: Independent processes providing tools
  - Python servers: Run via Python interpreter
  - Node.js servers: Run via `npx` package execution
  - Executables: Run directly
- **Async Runtime**: Modern asyncio-based execution
- **Rich UI**: Terminal interface with formatted output

### Communication Flow

```
User Input
    ↓
Avicenna Core
    ↓
Gemini API (with tool definitions)
    ↓
Tool Call Request
    ↓
MCP Client Manager
    ↓
MCP Server (stdio protocol)
    ↓
Tool Execution
    ↓
Result back to Gemini
    ↓
Response to User
```

See [docs/MCP_ECOSYSTEM_MIGRATION.md](docs/MCP_ECOSYSTEM_MIGRATION.md) for migration details.

## Migrating from Version 1.0

If you're upgrading from Avicenna v1.0:

1. **Backup your config**: Copy `~/.avicenna/mcp_config.json`
2. **Install Node.js**: Required for MCP ecosystem servers
3. **Delete old config**: Remove `~/.avicenna/mcp_config.json` to regenerate
4. **First run**: New default config will be created with v2.0 servers
5. **Review servers**: Check the startup table to see which servers connected

### What Changed

- Custom Python servers (basic, gmail) → Deprecated
- New: Official MCP ecosystem servers (filesystem, sequential-thinking)
- Configuration: Now supports `type` field for server types
- More tools: 15 tools from 2 servers (vs 4 tools from 2 servers in v1.0)

## Constitutional Framework

Avicenna operates under these principles:

1. **Clarity**: Unambiguous communication
2. **User Authority**: Explicit confirmation for consequential actions
3. **Truthfulness**: Accurate reporting of capabilities and limitations
4. **Determinism**: Consistent behavior
5. **Scope Limitation**: Only claims available capabilities

## Version History

- **2.0.0** (2026-01-28): MCP Ecosystem Integration
  - Node.js MCP server support
  - Official MCP ecosystem servers (filesystem, sequential-thinking)
  - Multi-type server support (Python, Node.js, Executable)
  - Server status display at startup
  - Deprecated custom servers
  
- **1.0.0** (2025): Initial Release
  - Basic MCP architecture
  - Custom Python servers (basic, gmail)
  - Gmail integration with OAuth
  - Constitutional AI framework

## License

MIT

## Credits

Created by CLANCY-41

Named after Ibn Sina (Avicenna), the Persian polymath whose synthesis of reason and wisdom revolutionized medieval thought.

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Links

- [Model Context Protocol](https://modelcontextprotocol.io)
- [MCP Ecosystem Servers](https://github.com/modelcontextprotocol/servers)
- [Gemini API Documentation](https://ai.google.dev/docs)

---

**Avicenna v2.0** - Because even AI agents benefit from a rich ecosystem.

