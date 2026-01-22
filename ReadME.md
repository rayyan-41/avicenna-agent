# Avicenna - AI Agent with MCP Integration

A constitutional AI agent built on the Model Context Protocol (MCP), named after the Persian polymath Ibn Sina (Avicenna).

## Features

- **MCP Architecture**: Tools run as independent MCP servers
- **Gmail Integration**: Draft and send emails with confirmation workflow
- **Basic Tools**: Time queries and mathematical calculations
- **Constitutional Framework**: Operates under ethical principles and user authority
- **Async Design**: Modern async/await Python architecture
- **Retro Terminal UI**: Green-on-black aesthetic

## Installation

```bash
# Clone repository
git clone https://github.com/rayyan-41/avicenna-agent.git
cd avicenna-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

1. Create `.env` file in project root:
```env
GOOGLE_API_KEY=your_gemini_api_key_here
AVICENNA_MODEL=gemini-2.0-flash-exp
```

2. For Gmail integration:
   - Download OAuth credentials from Google Cloud Console
   - Save as `credentials.json` in project root
   - First run will authenticate via browser

## Usage

```bash
# Start Avicenna
python -m source.avicenna.main chat

# Or if installed:
avicenna
```

### Example Commands

```
> What time is it?
> Calculate 15 * 24
> Draft an email to test@example.com subject "Hello" body "Test message"
> exit
```

## Project Structure

```
avicenna/
├── mcp_servers/                  # MCP server implementations
│   ├── __init__.py
│   ├── basic_server.py          # Time and calculator tools
│   ├── gmail_server.py          # Gmail email tools
│   ├── mcp_client.py            # MCP client manager
│   └── mcp_config_schema.py     # Configuration schema
├── source/
│   ├── avicenna/
│   │   ├── config.py            # Configuration management
│   │   ├── core.py              # Main agent logic
│   │   ├── main.py              # CLI entry point
│   │   └── providers/
│   │       └── gemini.py        # Gemini provider with MCP
│   └── tools/
│       └── gmail.py             # Gmail API wrapper
├── tests/                        # Test and verification scripts
│   ├── test_setup.py
│   ├── verify_mcp_servers.py
│   ├── verify_mcp_client.py
│   ├── verify_gemini_provider.py
│   └── verify_phase5.py
├── docs/                         # Documentation
│   ├── MCP_MIGRATION_ARCHITECTURE.md
│   ├── MCP_MIGRATION_IMPLEMENTATION_PLAN.md
│   └── PHASE5_SUMMARY.md
├── .env                          # API keys (not in git)
├── credentials.json              # Gmail OAuth (not in git)
├── pyproject.toml               # Project metadata
├── requirements.txt             # Python dependencies
└── ReadME.md                    # This file
```

## MCP Configuration

MCP servers are configured in `~/.avicenna/mcp_config.json`:

```json
{
  "mcp_servers": [
    {
      "name": "basic",
      "script": "mcp_servers/basic_server.py",
      "enabled": true,
      "description": "Basic tools: time, calculator"
    },
    {
      "name": "gmail",
      "script": "mcp_servers/gmail_server.py",
      "enabled": true,
      "description": "Gmail email sending capabilities"
    }
  ]
}
```

## Adding New Tools

1. Create MCP server in `mcp_servers/` directory:

```python
from fastmcp import FastMCP

mcp = FastMCP("My Tool Server")

@mcp.tool()
def my_tool(arg: str) -> str:
    """Tool description"""
    return f"Result: {arg}"

if __name__ == "__main__":
    mcp.run()
```

2. Add to MCP configuration:

```json
{
  "name": "mytool",
  "script": "mcp_servers/mytool_server.py",
  "enabled": true,
  "description": "My custom tool"
}
```

3. Restart Avicenna - tool will be auto-discovered!

## Testing

```bash
# Run all verification tests
python tests/verify_mcp_servers.py
python tests/verify_mcp_client.py
python tests/verify_gemini_provider.py
python tests/verify_phase5.py

# Run basic integration test
python tests/test_setup.py
```

## Architecture

Avicenna uses the **Model Context Protocol (MCP)** for tool integration:

- **Gemini API**: LLM provider
- **MCP Client**: Discovers and manages tool servers
- **MCP Servers**: Independent processes providing tools
- **Async Runtime**: Modern asyncio-based execution

See [docs/MCP_MIGRATION_ARCHITECTURE.md](docs/MCP_MIGRATION_ARCHITECTURE.md) for details.

## Constitutional Framework

Avicenna operates under these principles:

1. **Clarity**: Unambiguous communication
2. **User Authority**: Explicit confirmation for consequential actions
3. **Truthfulness**: Accurate reporting of capabilities and limitations
4. **Determinism**: Consistent behavior
5. **Scope Limitation**: Only claims available capabilities

## Version

**Current Version**: 1.0.0

## License

MIT

## Credits

Created by CLANCY-41

Named after Ibn Sina (Avicenna), the Persian polymath whose synthesis of reason and wisdom revolutionized medieval thought.

