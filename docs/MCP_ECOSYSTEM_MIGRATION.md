# MCP Ecosystem Migration Plan

## Overview

Migrate from custom MCP servers to **official MCP servers** from the Model Context Protocol ecosystem. These servers are production-ready, well-maintained, and provide rich functionality.

## Why Migrate?

### Current State (Custom Servers)
- ❌ Limited Gmail functionality (draft/send only)
- ❌ Need OAuth setup and credential management
- ❌ Basic calculator and time tools
- ❌ Maintenance burden for every new feature
- ❌ No web search, scraping, or advanced capabilities

### After Migration (Official MCP Servers)
- ✅ Full Google Workspace integration (Gmail, Drive, Calendar)
- ✅ Web search via Brave Search API
- ✅ Web scraping and content fetching
- ✅ File system operations
- ✅ Browser automation with Puppeteer
- ✅ Sequential thinking for complex reasoning
- ✅ Actively maintained by MCP community
- ✅ No OAuth setup required for many services

---

## Popular MCP Servers

### 🔍 Search & Web

#### 1. **Brave Search** 
- **Package:** `@modelcontextprotocol/server-brave-search`
- **Description:** Web search using Brave Search API
- **Tools:** `brave_web_search`, `brave_local_search`
- **Setup:** Requires Brave Search API key (free tier available)
- **Use Case:** "Search for latest Python tutorials", "Find news about AI"

#### 2. **Fetch** 
- **Package:** `@modelcontextprotocol/server-fetch`
- **Description:** Fetch and extract content from web pages
- **Tools:** `fetch`, `fetch_pdf`
- **Setup:** No API key required
- **Use Case:** "Read content from this URL", "Extract text from PDF"

#### 3. **Puppeteer** 
- **Package:** `@modelcontextprotocol/server-puppeteer`
- **Description:** Browser automation and web scraping
- **Tools:** `puppeteer_navigate`, `puppeteer_screenshot`, `puppeteer_click`
- **Setup:** Requires Node.js and Puppeteer
- **Use Case:** "Take screenshot of this page", "Automate form submission"

---

### 📁 File & System

#### 4. **Filesystem** 
- **Package:** `@modelcontextprotocol/server-filesystem`
- **Description:** Read/write files, directory operations
- **Tools:** `read_file`, `write_file`, `list_directory`, `move_file`
- **Setup:** Configure allowed directories for security
- **Use Case:** "Read my notes.txt", "Create a new file"

---

### 📧 Google Workspace

#### 5. **Gmail** ⭐ RECOMMENDED
- **Package:** `@modelcontextprotocol/server-gmail`
- **Description:** Full Gmail integration
- **Tools:** 
  - `gmail_send_email`
  - `gmail_search` (search emails by query)
  - `gmail_get_thread` (read email threads)
  - `gmail_create_draft`
  - `gmail_send_draft`
  - `gmail_list_labels`
- **Setup:** Google OAuth 2.0 (one-time setup)
- **Use Case:** "Search my emails from John", "Read latest newsletters"
- **Advantage:** Much richer than our custom server!

#### 6. **Google Drive**
- **Package:** `@modelcontextprotocol/server-gdrive`
- **Description:** Google Drive file access
- **Tools:** `drive_list_files`, `drive_download_file`, `drive_upload_file`
- **Setup:** Google OAuth 2.0
- **Use Case:** "List files in my Drive", "Download this document"

#### 7. **Google Maps**
- **Package:** `@modelcontextprotocol/server-google-maps`
- **Description:** Location and mapping services
- **Tools:** `maps_geocode`, `maps_directions`, `maps_search_places`
- **Setup:** Google Maps API key
- **Use Case:** "Find restaurants near me", "Get directions to office"

---

### 🧠 Reasoning & AI

#### 8. **Sequential Thinking**
- **Package:** `@modelcontextprotocol/server-sequential-thinking`
- **Description:** Enhanced multi-step reasoning
- **Tools:** `create_thinking_session`, `add_thought`, `revise_thought`
- **Setup:** None required
- **Use Case:** Complex problem solving with step-by-step thinking

---

### 🗄️ Database

#### 9. **SQLite**
- **Package:** `@modelcontextprotocol/server-sqlite`
- **Description:** SQLite database operations
- **Tools:** `query`, `execute`, `list_tables`
- **Setup:** Specify database file path
- **Use Case:** "Query my local database", "Create new table"

#### 10. **PostgreSQL**
- **Package:** `@modelcontextprotocol/server-postgres`
- **Description:** PostgreSQL database access
- **Tools:** Similar to SQLite
- **Setup:** Database connection string
- **Use Case:** Production database queries

---

### 🛠️ Development

#### 11. **Git**
- **Package:** `@modelcontextprotocol/server-git`
- **Description:** Git repository operations
- **Tools:** `git_status`, `git_diff`, `git_commit`, `git_log`
- **Setup:** None (uses local git)
- **Use Case:** "Show git status", "Commit these changes"

#### 12. **GitHub**
- **Package:** `@modelcontextprotocol/server-github`
- **Description:** GitHub API integration
- **Tools:** `create_issue`, `list_prs`, `get_repo_info`
- **Setup:** GitHub Personal Access Token
- **Use Case:** "Create issue for this bug", "List open PRs"

---

## Migration Strategy

### Phase 1: Install Node.js MCP Servers

Most official MCP servers are Node.js packages. We need to:

1. **Install Node.js** (if not already installed)
2. **Install npx** (comes with Node.js)
3. **Create MCP server wrapper**

### Phase 2: Update Configuration Schema

Current schema only supports Python scripts. Update to support:
- Node.js packages via `npx`
- Command-line executables
- Docker containers (future)

**New Schema:**

```python
@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server"""
    name: str
    type: str  # "python", "node", "executable"
    
    # For Python servers
    script: Optional[str] = None
    
    # For Node.js servers
    package: Optional[str] = None
    args: Optional[List[str]] = None
    
    # For all types
    enabled: bool = True
    description: Optional[str] = None
    env: Optional[dict] = None
```

**Example Configuration:**

```json
{
  "mcp_servers": [
    {
      "name": "brave-search",
      "type": "node",
      "package": "@modelcontextprotocol/server-brave-search",
      "enabled": true,
      "description": "Web search via Brave",
      "env": {
        "BRAVE_API_KEY": "your-api-key"
      }
    },
    {
      "name": "fetch",
      "type": "node",
      "package": "@modelcontextprotocol/server-fetch",
      "enabled": true,
      "description": "Web scraping and content fetching"
    },
    {
      "name": "gmail",
      "type": "node",
      "package": "@modelcontextprotocol/server-gmail",
      "enabled": true,
      "description": "Full Gmail integration",
      "args": ["--auth-file", "~/.avicenna/gmail_auth.json"]
    },
    {
      "name": "filesystem",
      "type": "node",
      "package": "@modelcontextprotocol/server-filesystem",
      "enabled": true,
      "description": "File operations",
      "args": ["--allowed-directories", "~/Documents", "~/Downloads"]
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

### Phase 3: Update MCP Client Manager

Update `connect_server()` to handle different server types:

```python
async def connect_server(self, server_config: MCPServerConfig) -> bool:
    """Connect to a single MCP server (Python or Node.js)"""
    try:
        if server_config.type == "python":
            # Current Python logic
            command = sys.executable
            args = [str(script_path.absolute())]
            
        elif server_config.type == "node":
            # Node.js package via npx
            command = "npx"
            args = ["-y", server_config.package] + (server_config.args or [])
            
        elif server_config.type == "executable":
            # Direct executable
            command = server_config.script
            args = server_config.args or []
        else:
            raise ValueError(f"Unknown server type: {server_config.type}")
        
        # Rest of connection logic remains same
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=server_config.env or {}
        )
        # ... continue with stdio_client, session creation, etc.
```

### Phase 4: Remove Custom Servers

Once official servers are working:
1. Deprecate `mcp_servers/gmail_server.py`
2. Deprecate `mcp_servers/basic_server.py`
3. Remove `source/tools/gmail.py` (no longer needed)
4. Keep `mcp_servers/` folder for any custom tools we might add later

### Phase 5: Update Documentation

Update README with:
- List of available MCP servers
- How to add new servers
- API key setup instructions
- Example queries for each server

---

## Recommended Initial Setup

Start with these essential servers:

```json
{
  "mcp_servers": [
    {
      "name": "brave-search",
      "type": "node",
      "package": "@modelcontextprotocol/server-brave-search",
      "enabled": true,
      "env": {"BRAVE_API_KEY": ""}
    },
    {
      "name": "fetch",
      "type": "node",
      "package": "@modelcontextprotocol/server-fetch",
      "enabled": true
    },
    {
      "name": "gmail",
      "type": "node",
      "package": "@modelcontextprotocol/server-gmail",
      "enabled": true
    },
    {
      "name": "filesystem",
      "type": "node",
      "package": "@modelcontextprotocol/server-filesystem",
      "enabled": false,
      "args": ["--allowed-directories", "~/Documents"]
    },
    {
      "name": "sequential-thinking",
      "type": "node",
      "package": "@modelcontextprotocol/server-sequential-thinking",
      "enabled": true
    }
  ]
}
```

---

## API Keys Required

### Brave Search API
- **Website:** https://brave.com/search/api/
- **Free Tier:** 2,000 queries/month
- **Setup:** Sign up → Get API key → Add to config

### Gmail (Google OAuth)
- **Console:** https://console.cloud.google.com
- **Setup:** 
  1. Create project
  2. Enable Gmail API
  3. Create OAuth 2.0 credentials
  4. Download credentials.json
  5. First run will open browser for authorization

---

## Implementation Timeline

### Week 1: Core Infrastructure
- [ ] Update `MCPServerConfig` schema with type support
- [ ] Update `connect_server()` for Node.js servers
- [ ] Test with `@modelcontextprotocol/server-fetch` (no API key needed)

### Week 2: Search & Web
- [ ] Add Brave Search server
- [ ] Add Fetch server
- [ ] Test web search queries

### Week 3: Google Workspace
- [ ] Migrate to official Gmail server
- [ ] Add Google Drive server
- [ ] Remove custom Gmail implementation

### Week 4: Polish
- [ ] Add Sequential Thinking server
- [ ] Update documentation
- [ ] Create example queries
- [ ] Add filesystem server (optional)

---

## Testing Plan

For each new server, test:

```python
# Test connection
manager = MCPClientManager()
success = await manager.connect_server(server_config)
assert success

# Test tool discovery
tools = manager.list_available_tools()
assert len(tools) > 0

# Test tool execution
result = await manager.call_tool("brave_web_search", {"query": "MCP servers"})
assert "results" in result
```

---

## Benefits Summary

### Capabilities Gained
- 🔍 **Web Search** - Real-time internet search
- 📄 **Web Scraping** - Extract content from any URL
- 📧 **Advanced Gmail** - Search, read threads, manage labels
- 💾 **File Operations** - Read/write local files
- 🧠 **Better Reasoning** - Sequential thinking tools
- 📁 **Google Drive** - Cloud file access
- 🗺️ **Maps & Location** - Geocoding, directions
- 🗄️ **Databases** - SQLite/PostgreSQL queries

### Maintenance Reduced
- ✅ No more OAuth credential management
- ✅ No custom tool development
- ✅ Community-maintained servers
- ✅ Regular updates and bug fixes
- ✅ Better error handling
- ✅ Comprehensive documentation

---

## Next Steps

Would you like me to:
1. **Implement the schema update** to support Node.js servers?
2. **Install and test** a simple server like `fetch` first?
3. **Create the updated configuration** with official servers?
4. **Set up Brave Search API** key for web search?

Let me know which approach you prefer!
