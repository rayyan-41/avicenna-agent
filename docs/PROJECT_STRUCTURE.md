# Project Structure Overview

## Directory Tree

```
avicenna/
│
├── 📁 mcp_servers/                  MCP Server Implementations
│   ├── __init__.py                   Package marker
│   ├── basic_server.py              Time & calculator tools
│   ├── gmail_server.py              Gmail email tools
│   ├── mcp_client.py                MCP client manager
│   └── mcp_config_schema.py         Configuration schema
│
├── 📁 source/                       Source Code
│   ├── __init__.py
│   │
│   ├── 📁 avicenna/                 Core Agent Package
│   │   ├── __init__.py
│   │   ├── config.py                Configuration management
│   │   ├── core.py                  Agent orchestration
│   │   ├── main.py                  CLI entry point
│   │   │
│   │   └── 📁 providers/            LLM Provider Implementations
│   │       ├── __init__.py          Provider interface
│   │       └── gemini.py            Gemini with MCP integration
│   │
│   └── 📁 tools/                    Tool Utilities
│       ├── __init__.py
│       └── gmail.py                 Gmail API wrapper
│
├── 📁 tests/                        Test & Verification
│   ├── test_setup.py                Basic integration test
│   ├── verify_mcp_servers.py        Phase 2 verification
│   ├── verify_mcp_client.py         Phase 3 verification
│   ├── verify_gemini_provider.py    Phase 4 verification
│   └── verify_phase5.py             Phase 5 verification
│
├── 📁 docs/                         Documentation
│   ├── MCP_MIGRATION_ARCHITECTURE.md
│   ├── MCP_MIGRATION_IMPLEMENTATION_PLAN.md
│   └── PHASE5_SUMMARY.md
│
├── 📁 avicenna_agent.egg-info/      Build Artifacts
│
├── 📄 .env                          Environment Variables (SECRET)
├── 📄 .gitignore                    Git ignore rules
├── 📄 credentials.json              Gmail OAuth (SECRET)
├── 📄 pyproject.toml                Project metadata
├── 📄 requirements.txt              Python dependencies
└── 📄 ReadME.md                     Project documentation
```

## Component Relationships

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI (main.py)                            │
│                   asyncio.run()                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│               AvicennaAgent (core.py)                        │
│         - async initialize()                                 │
│         - async send_message()                               │
│         - async cleanup()                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│          GeminiProvider (providers/gemini.py)                │
│         - async initialize() → connects MCP                  │
│         - async send_message() → routes tool calls           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│          MCPClientManager (mcp_servers/mcp_client.py)        │
│         - connect_all() → spawns servers                     │
│         - call_tool() → executes via MCP protocol            │
│         - get_gemini_tools() → schema conversion             │
└────────────────────┬────────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
┌──────────────────┐  ┌──────────────────┐
│  basic_server.py │  │  gmail_server.py │
│  (subprocess)    │  │  (subprocess)    │
│                  │  │                  │
│ - get_time()     │  │ - draft_email()  │
│ - calculate()    │  │ - send_email()   │
└──────────────────┘  └──────────────────┘
```

## Data Flow: Email Example

```
1. User: "Draft email to test@example.com"
   │
   ▼
2. main.py: await agent.send_message(input)
   │
   ▼
3. core.py: await provider.send_message(input)
   │
   ▼
4. gemini.py: Send to Gemini API
   │
   ▼
5. Gemini: Returns function_call(draft_email, {...})
   │
   ▼
6. gemini.py: await mcp_manager.call_tool("draft_email", args)
   │
   ▼
7. mcp_client.py: Route to gmail_server via stdio
   │
   ▼
8. gmail_server.py: Execute draft_email() → return preview
   │
   ▼
9. gemini.py: Special handling - return preview directly
   │
   ▼
10. User sees formatted email preview
```

## Configuration Flow

```
~/.avicenna/mcp_config.json
         │
         ▼
   Config.load_mcp_config()
         │
         ▼
   MCPClientManager.connect_all()
         │
         ▼
   Spawns MCP servers as subprocesses
         │
         ▼
   Discovers tools via MCP protocol
         │
         ▼
   Converts to Gemini Tool format
         │
         ▼
   Ready for agent use
```

## File Purposes

### Core Agent Files
- **main.py**: CLI interface, async main loop
- **core.py**: Agent initialization, message routing
- **config.py**: Environment variables, MCP config loading
- **providers/gemini.py**: Gemini API integration with MCP

### MCP Files
- **mcp_servers/mcp_client.py**: Manages connections to MCP servers
- **mcp_servers/mcp_config_schema.py**: Configuration data structures
- **mcp_servers/basic_server.py**: Time and calculator MCP server
- **mcp_servers/gmail_server.py**: Gmail integration MCP server

### Tool Files
- **tools/gmail.py**: Gmail API wrapper (OAuth, sending)

### Testing Files
- **tests/test_setup.py**: Basic integration smoke test
- **tests/verify_*.py**: Phase-specific verification scripts

### Documentation Files
- **docs/MCP_MIGRATION_*.md**: Migration architecture docs
- **docs/PHASE5_SUMMARY.md**: Phase 5 completion summary

## Key Design Decisions

1. **MCP Servers Isolated**: `mcp_servers/` at project root (avoids conflict with mcp package)
2. **Source Separation**: Agent code in `source/`, servers in `mcp_servers/`
3. **Async Throughout**: All agent operations use async/await
4. **Config in Home**: User config in `~/.avicenna/` not project
5. **Modular Tools**: Each tool is independent MCP server

## Adding Components

### New MCP Server
1. Create `mcp_servers/new_server.py`
2. Use FastMCP framework
3. Add to `~/.avicenna/mcp_config.json`
4. Restart Avicenna

### New Provider
1. Create `source/avicenna/providers/new_provider.py`
2. Implement `LLMProvider` interface
3. Update `core.py` factory pattern
4. Set `AVICENNA_PROVIDER=new` in `.env`

### New Test
1. Create `tests/test_new_feature.py`
2. Follow existing async test patterns
3. Add to verification suite
