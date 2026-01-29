# Debugging Help Request: Avicenna MCP Server Integration Issues

## Context

I'm working on **Avicenna**, a conversational AI agent that uses Google's Gemini API with the Model Context Protocol (MCP) for tool execution. I recently migrated from native function calling to MCP servers and I'm experiencing several issues.

## System Architecture

- **Project**: Avicenna AI Agent
- **Language**: Python 3.x (async/await)
- **LLM**: Google Gemini 2.5 Flash
- **Protocol**: Model Context Protocol (MCP) for tool orchestration
- **OS**: Windows
- **MCP Transports**: stdio (Python), npx (Node.js), executable (direct commands)

### Architecture Flow
```
User → CLI (main.py) → AvicennaAgent (core.py) → GeminiProvider (providers/gemini.py)
                                                            ↓
                                                    MCPClientManager
                                                            ↓
                                    ┌──────────────────────┼──────────────────────┐
                                    ↓                      ↓                      ↓
                            Python MCP Servers     Node.js MCP Servers    Executable Servers
                            (subprocess)           (npx commands)         (direct execution)
```

## Current Errors (from logs)

### Error 1: Playwright Connection Failure
```
2026-01-29 11:47:45,018 - mcp_servers.mcp_client - ERROR - ✗ Failed to connect to playwright: Connection closed
```
**Repeats every session startup**

### Error 2: Gmail Server Path Not Found
```
2026-01-29 11:47:52,208 - mcp_servers.mcp_client - ERROR - ✗ Config error for gmail: Server script not found: D:\Code Repositories\VSCode Repository\avicenna\tools\gmail.py
```
**Looking for file in wrong directory** - should be `mcp_servers/gmail_server.py`

### Error 3: Configuration Mismatch
The system is looking for `tools/gmail.py` but the actual structure is:
```
avicenna/
├── mcp_servers/
│   ├── gmail_server.py        ← Actual location
│   ├── basic_server.py
│   ├── mcp_client.py
│   └── mcp_config_schema.py
├── source/
│   └── tools/
│       └── gmail.py           ← Old native tools (deprecated)
└── .env
```

## What I've Tried

### Attempt 1: Check MCP Configuration
- **Issue**: Can't find `mcp_config.json` file anywhere in project
- **Expected location**: `~/.avicenna/mcp_config.json` (according to `config.py`)
- **Result**: File search returned "No files found"
- **Code reference**: `Config.MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'`

### Attempt 2: Review Log Files
- **Found**: `avicenna.log` with 1427 lines of logs
- **Key observations**:
  - Successfully connects to 3 servers: `filesystem`, `sequential-thinking`, `google-workspace`
  - Total of **134 tools** loaded successfully
  - Playwright consistently fails
  - Gmail server path is wrong
  - Agent otherwise functions (makes API calls successfully)

### Attempt 3: Check Working Servers
**Successful connections:**
- ✅ `filesystem` (Node.js) - 14 tools
- ✅ `sequential-thinking` (Node.js) - 1 tool  
- ✅ `google-workspace` (executable) - 119 tools

**Failed connections:**
- ❌ `playwright` (Node.js) - "Connection closed"
- ❌ `gmail` (Python) - Wrong path

### Attempt 4: Review Code Structure
**MCP Client Manager** (`mcp_servers/mcp_client.py`):
- Supports 3 server types: `python`, `node`, `executable`
- Uses `stdio_client` for communication
- Handles graceful degradation (continues even if servers fail)
- Validates script paths relative to project root

**Configuration Schema** (`mcp_config_schema.py`):
- Defines `MCPServerConfig` dataclass
- Server types: `SERVER_TYPE_PYTHON`, `SERVER_TYPE_NODE`, `SERVER_TYPE_EXECUTABLE`
- Validation in `__post_init__` ensures required fields are present

## Questions I Need Help With

1. **Where is the MCP config file?**
   - Code expects `~/.avicenna/mcp_config.json`
   - Can't find it anywhere
   - Should it be auto-generated? If so, why isn't it?

2. **How to fix the Gmail server path issue?**
   - Current (wrong): `D:\Code Repositories\VSCode Repository\avicenna\tools\gmail.py`
   - Should be: `mcp_servers/gmail_server.py`
   - Where is this path configured?

3. **Why is Playwright failing?**
   - Error: "Connection closed"
   - Other Node.js servers work fine (`filesystem`, `sequential-thinking`)
   - Is this a Playwright-specific issue or configuration problem?

4. **How does the default config generation work?**
   ```python
   if not cls.MCP_CONFIG_PATH.exists():
       config = MCPConfiguration.default()
       config.save(cls.MCP_CONFIG_PATH)
   ```
   - This should create the config on first run
   - Why might this not be happening?

5. **How to debug MCP server connections?**
   - What diagnostic steps can I take?
   - How to verify Node.js servers are properly installed?
   - How to test individual server connections?

## Relevant Code Snippets

### Config Loading (source/avicenna/config.py)
```python
MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'

@classmethod
def load_mcp_config(cls) -> MCPConfiguration:
    """Load MCP configuration, creating default if needed"""
    if not cls.MCP_CONFIG_PATH.exists():
        config = MCPConfiguration.default()
        config.save(cls.MCP_CONFIG_PATH)
        console.print(f"[green]✅ Created default MCP config:[/green] {cls.MCP_CONFIG_PATH}")
        return config
    
    try:
        return MCPConfiguration.from_file(cls.MCP_CONFIG_PATH)
    except Exception as e:
        console.print(f"[yellow]⚠️ Error loading MCP config, using defaults:[/yellow] {e}")
        return MCPConfiguration.default()
```

### MCP Client Connection (mcp_servers/mcp_client.py)
```python
async def connect_server(self, server_config: MCPServerConfig) -> bool:
    try:
        logger.info(f"Connecting to MCP server: {server_config.name}")
        
        # Resolve script path
        script_path = Path(server_config.script)
        if not script_path.is_absolute():
            # Make relative to project root
            project_root = Path(__file__).parent.parent
            script_path = project_root / script_path
        
        if not script_path.exists():
            logger.error(f"Server script not found: {script_path}")
            return False
        
        # ... rest of connection logic
```

### Environment Variables (.env)
```env
GOOGLE_API_KEY=AIzaSy... (valid key)
AVICENNA_MODEL=gemini-2.5-flash
GOOGLE_OAUTH_CLIENT_ID=547357431166-...
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-5PV_...
GITHUB_TOKEN=ghp_your_github_personal_access_token
BRAVE_API_KEY=BSAJaxVeMe1pb-UQ9...
```

## Expected Behavior

- All MCP servers should connect successfully on startup
- Gmail server should load from `mcp_servers/gmail_server.py`
- Playwright should connect (or provide a meaningful error)
- `mcp_config.json` should exist and contain proper server configurations

## Actual Behavior

- 3/5 servers connect successfully
- Gmail server fails with wrong path
- Playwright fails with "Connection closed"
- Agent still functions with 134 tools from working servers
- No visible `mcp_config.json` file

## Additional Information

- **No VS Code errors** reported in editor
- **Agent runs successfully** - just missing some tools
- **Last command**: `avicenna` (exit code 0)
- **Log shows**: Successful API calls to Gemini, tool execution works for available tools

## What I Need

1. **Root cause analysis** of the path mismatch issue
2. **Steps to debug** the Playwright connection failure
3. **How to verify** the MCP config is being generated correctly
4. **Best practices** for MCP server configuration and troubleshooting
5. **How to fix** the gmail server path without breaking other servers

---

**Note**: The system uses graceful degradation, so it continues working even with failed servers. However, I want to get all servers working properly for full functionality.
