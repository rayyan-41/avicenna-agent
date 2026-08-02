# Avicenna MCP Tools - Current & Recommendations

## 📦 Currently Available Tools (100+ Total)

### 📁 Filesystem Server (14 tools)
**Package:** `@modelcontextprotocol/server-filesystem`  
**Status:** ✅ Enabled by default

1. **`create_directory`** - Create new directories
2. **`directory_tree`** - Get recursive directory structure as JSON
3. **`edit_file`** - Make line-based edits to text files
4. **`get_file_info`** - Get file/directory metadata (size, dates, permissions)
5. **`list_allowed_directories`** - Show which directories are accessible
6. **`list_directory`** - List files and folders in a directory
7. **`list_directory_with_sizes`** - List directory with size information
8. **`move_file`** - Move or rename files and directories
9. **`read_file`** - Read complete file contents (deprecated, use read_text_file)
10. **`read_media_file`** - Read images/audio as base64 encoded data
11. **`read_multiple_files`** - Read multiple files simultaneously
12. **`read_text_file`** - Read text file contents
13. **`search_files`** - Search for files matching patterns
14. **`write_file`** - Create or overwrite files

**Use Cases:**
- File management and organization
- Reading/writing configuration files
- Code file analysis
- Document processing
- Log file analysis

---

### 🧠 Sequential Thinking Server (1 tool)
**Package:** `@modelcontextprotocol/server-sequential-thinking`  
**Status:** ✅ Enabled by default

1. **`sequentialthinking`** - Enhanced step-by-step reasoning for complex problems

**Use Cases:**
- Multi-step problem solving
- Complex analysis requiring structured thinking
- Breaking down large tasks
- Decision-making processes

---

### 🗃️ SQLite Server (10+ tools)
**Package:** `@modelcontextprotocol/server-sqlite`  
**Status:** ✅ Enabled by default

**Key Tools:**
- `read-query` - Execute SELECT queries
- `write-query` - Execute INSERT, UPDATE, DELETE
- `create-table` - Create new tables
- `list-tables` - List all database tables
- `describe-table` - Get table schema
- And more...

**Use Cases:**
- Local database operations
- Data analysis and querying
- Application data storage
- Configuration management

---

### 🔧 Git Server (20+ tools)
**Package:** `@modelcontextprotocol/server-git`  
**Status:** ✅ Enabled by default

**Key Tools:**
- `git_status` - Check repository status
- `git_diff` - View file changes
- `git_commit` - Commit changes
- `git_log` - View commit history
- `git_branch` - Branch operations
- And more...

**Use Cases:**
- Version control operations
- Code history analysis
- Branch management
- Commit tracking

---

### 🐙 GitHub Server (40+ tools)
**Package:** `@modelcontextprotocol/server-github`  
**Status:** ⚠️ Disabled (requires GITHUB_TOKEN)

**Key Tools:**
- Repository management (create, fork, list)
- Issue operations (create, update, list, comment)
- Pull request management
- Branch and tag operations
- Search repositories, issues, code
- Workflow and release management
- And more...

**Use Cases:**
- GitHub automation
- Issue tracking
- PR management
- Repository analysis

**Setup:**
1. Create GitHub Personal Access Token at https://github.com/settings/tokens
2. Add to your `.env` file: `GITHUB_TOKEN=ghp_your_token_here`
3. Enable in config or set `enabled=True` in default config

---

### 📧 Google Workspace Server (100+ tools)
**Package:** `workspace-mcp` (via uvx)  
**Status:** ⚠️ Disabled (requires OAuth credentials)

**Services Included:**
- **Gmail** - Send, read, search, label, draft emails
- **Calendar** - Create/update events, check availability, manage calendars
- **Drive** - Upload, download, search, share files and folders
- **Docs** - Create, edit, read documents
- **Sheets** - Read, write, format spreadsheets
- **Slides** - Create and manage presentations
- **Forms** - Create forms, collect responses
- **Tasks** - Manage task lists
- **Chat** - Send messages to spaces

**Use Cases:**
- Email automation
- Calendar scheduling
- Document collaboration
- Data analysis in Sheets
- Team communication
- File management

**Setup:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create OAuth 2.0 Desktop Client credentials
3. Download credentials and add to `.env`:
   ```
   GOOGLE_OAUTH_CLIENT_ID=your-client-id
   GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
   ```
4. Enable in config or set `enabled=True` in default config
5. First use will open browser for OAuth authentication

---

## 🎯 Additional Optional Servers

### Web & Content

#### 1. **Web Fetch (TypeScript)** ⭐⭐
**Package:** `mcp-server-fetch-typescript`  
**Status:** ⚠️ Disabled (requires Playwright)
**Tools:** ~3-5 tools
- Fetch web pages
- Extract content
- Screenshot capture

**Why Add:**
- Web scraping capabilities
- Content extraction
- Page monitoring

**Setup:**
```json
{
  "name": "fetch",
  "type": "node",
  "package": "mcp-server-fetch-typescript",
  "enabled": true,
  "description": "Fetch web content (requires: npx playwright install)"
}
```

**Note:** Already included in default config but disabled. Run `npx playwright install` first.

---

#### 2. **Brave Search** ⭐⭐
**Package:** `@modelcontextprotocol/server-brave-search`  
**Status:** ⚠️ Disabled (requires BRAVE_API_KEY)
**Tools:** ~2 tools
- Web search
- Local search

**Why Add:**
- Real-time information access
- Research capabilities
- Fact-checking
- Current events awareness

**Setup:**
Get API key from [Brave Search API](https://brave.com/search/api/), then add to `.env`:
```
BRAVE_API_KEY=your-api-key-here
```

**Note:** Already included in default config but disabled.

---

### Specialized - Domain Specific

#### 3. **Puppeteer (Browser Automation)** 
**Package:** `@modelcontextprotocol/server-puppeteer`  
**Tools:** ~8 tools
- Navigate to URLs
- Click elements
- Fill forms
- Take screenshots
- Extract data

**Why Add:**
- Web automation
- Testing websites
- Form filling
- Screenshot capture

---

#### 4. **PostgreSQL**
**Package:** `@modelcontextprotocol/server-postgres`  
**Tools:** Similar to SQLite

**Why Add:**
- Production database access
}
```

**Get API Key:** https://brave.com/search/api/ (2,000 free queries/month)

---

#### 4. **Web Fetch/Scraping** ⭐⭐
**Package:** `mcp-server-fetch-typescript`  
**Tools:** ~3 tools
- Fetch web page content
- Extract text from HTML
- Download PDFs

**Why Add:**
- Read articles and documentation
- Extract information from websites
- Monitor web content
- Research automation

**Setup:**
```json
{
  "name": "fetch",
  "type": "node",
  "package": "mcp-server-fetch-typescript",
  "enabled": true,
  "description": "Web content fetching"
}
```

**Requires:** `npx playwright install`

---

### Medium Priority - Enhanced Capabilities

#### 5. **Git Integration** ⭐⭐
**Package:** `@modelcontextprotocol/server-git`  
**Tools:** ~10 tools
- Git status, diff, log
- Commit changes
- Branch management
- File history

**Why Add:**
- Version control from chat
- Code repository management
- Automated commits
- Track file changes

---

#### 6. **GitHub API** ⭐⭐
**Package:** `@modelcontextprotocol/server-github`  
**Tools:** ~15 tools
- Create/list issues
- Pull request management
- Repository info
- Search code

**Why Add:**
- Issue tracking
- Code collaboration
- Project management
- Repository automation

**Setup:** Requires GitHub Personal Access Token

---

#### 7. **Google Calendar** ⭐
**Package:** `@modelcontextprotocol/server-gcalendar` (if available)  
**Tools:** ~6 tools
- List events
- Create/update events
- Schedule management

**Why Add:**
- Schedule appointments
- Event reminders
- Time management
- Meeting coordination

---

#### 8. **Memory/Notes** ⭐
**Package:** `@modelcontextprotocol/server-memory`  
**Tools:** ~4 tools
- Store key-value pairs
- Retrieve stored info
- Search memory
- Context persistence

**Why Add:**
- Remember user preferences
- Store important information
- Context across sessions
- Personalization

---

### Specialized - Domain Specific

#### 9. **Puppeteer (Browser Automation)** 
**Package:** `@modelcontextprotocol/server-puppeteer`  
**Tools:** ~8 tools
- Navigate to URLs
- Click elements
- Fill forms
- Take screenshots
- Extract data

**Why Add:**
- Web automation
- Testing websites
- Form filling
- Screenshot capture

---

#### 10. **PostgreSQL**
**Package:** `@modelcontextprotocol/server-postgres`  
**Tools:** Similar to SQLite

**Why Add:**
- Production database access
- Data analytics
- Multi-user databases

---

#### 5. **Memory/Notes** 
**Package:** `@modelcontextprotocol/server-memory`  
**Tools:** ~4 tools
- Store key-value pairs
- Retrieve stored info
- Search memory
- Context persistence

**Why Add:**
- Remember user preferences
- Store important information
- Context across sessions
- Personalization

---

#### 6. **Slack**
**Package:** `@modelcontextprotocol/server-slack` (if available)  
**Tools:** ~6 tools
- Send messages
- Read channels
- File uploads

**Why Add:**
- Team communication
- Notifications
- Collaboration

---

## 📊 Impact Analysis

### Before (Legacy v1.0)
- **Total Tools:** 4 (basic time/calc + deprecated Gmail)
- **Capabilities:** Minimal

### After (Current v2.0)
- **Total Tools:** 100+ across 6 servers
- **Breakdown:**
  - Filesystem: 14 tools ✅
  - Sequential Thinking: 1 tool ✅
  - SQLite: 10+ tools ✅
  - Git: 20+ tools ✅
  - GitHub: 40+ tools (requires token)
  - Google Workspace: 100+ tools (requires OAuth)

### Maximum Potential (With All Optional Servers)
- **Total Tools:** 150+ tools
- **Additional servers available:**
  - Brave Search: 2 tools
  - Web Fetch: 5 tools
  - Puppeteer: 8 tools
  - PostgreSQL: 10+ tools
  - Memory: 4 tools
  - Slack: 6 tools

---

## 🚀 Quick Start - Enable All Current Servers

To enable all currently configured servers:

### 1. Set up environment variables

Create/update your `.env` file:

```env
# Google API for Gemini
GOOGLE_API_KEY=your_gemini_api_key

# Google Workspace (100+ tools)
GOOGLE_OAUTH_CLIENT_ID=your_google_oauth_client_id
GOOGLE_OAUTH_CLIENT_SECRET=your_google_oauth_client_secret

# GitHub (40+ tools)
GITHUB_TOKEN=ghp_your_github_token

# Brave Search (optional)
BRAVE_API_KEY=your_brave_api_key
```

### 2. Remove old config (if upgrading)

```powershell
Remove-Item "$env:USERPROFILE\.avicenna\mcp_config.json"
```

### 3. Start Avicenna

```powershell
avicenna
```

The first run will:
- Create a new v2.0 config with all servers
- Auto-enable: filesystem, sequential-thinking, sqlite, git
- Leave disabled: google-workspace, github, brave-search (require credentials)

### 4. Enable Optional Servers

Edit `~/.avicenna/mcp_config.json` and set `"enabled": true` for:
- **google-workspace** (after adding OAuth credentials)
- **github** (after adding GITHUB_TOKEN)
- **brave-search** (after adding BRAVE_API_KEY)

---

## 📋 Server Configuration Examples

### Google Workspace Setup

Full setup guide: https://github.com/taylorwilsdon/google_workspace_mcp

1. **Create OAuth Credentials:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create new project or select existing
   - APIs & Services → Credentials → Create OAuth Client ID
   - Select "Desktop Application"
   - Download credentials

2. **Add to `.env`:**
```env
GOOGLE_OAUTH_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-your_secret_here
```

3. **Enable APIs:**
   Visit these links to enable:
   - [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
   - [Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
   - [Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
   - [Docs API](https://console.cloud.google.com/apis/library/docs.googleapis.com)
   - [Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
   - [Slides API](https://console.cloud.google.com/apis/library/slides.googleapis.com)

4. **Set enabled in config:**
```json
{
  "name": "google-workspace",
  "enabled": true
}
```

---

### GitHub Setup

1. **Create Personal Access Token:**
   - Go to https://github.com/settings/tokens
   - Generate new token (classic)
   - Select scopes: `repo`, `read:org`, `workflow`

2. **Add to `.env`:**
```env
GITHUB_TOKEN=ghp_your_token_here_1234567890
```

3. **Set enabled in config:**
```json
{
  "name": "github",
  "enabled": true
}
```

---

## 🔧 Troubleshooting

### Server Not Connecting

Check the status table at startup:
```
┌────────────┬──────┬────────────────┬───────┐
│ Name       │ Type │ Status         │ Tools │
├────────────┼──────┼────────────────┼───────┤
│ filesystem │ node │ ✅ Connected   │ 14    │
│ git        │ node │ ❌ Failed      │ 0     │
└────────────┴──────┴────────────────┴───────┘
```

Common issues:
- **Node.js not installed**: Install from https://nodejs.org/
- **npx not found**: Restart terminal after Node.js installation
- **Package not found**: npx auto-installs on first run, wait for it
- **OAuth errors**: Check credentials in `.env` file
- **Permission errors**: Run terminal as administrator

### Google Workspace OAuth Flow

First use will:
1. Print OAuth URL in terminal
2. Open browser automatically
3. Prompt you to authorize
4. Save credentials for future use

If OAuth fails:
- Check `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
- Ensure APIs are enabled in Google Cloud Console
- Try removing `~/.avicenna/credentials.json` and re-authenticating

---

## 📈 Roadmap

Future server additions being considered:
- **Notion** - Note-taking and project management
- **Trello** - Board-based project tracking
- **Jira** - Issue tracking and agile boards
- **Confluence** - Team documentation
- **Discord** - Community communication
- **Telegram** - Messaging integration

---

## 🤝 Contributing

Want to add a new MCP server? 

1. Find the server package (npm or PyPI)
2. Add to `mcp_config_schema.py` in the `default()` method
3. Add corresponding env vars to `config.py` if needed
4. Update this guide
5. Submit a PR!

---

## 📚 Resources

- **MCP Documentation:** https://modelcontextprotocol.io/
- **Official MCP Servers:** https://github.com/modelcontextprotocol/servers
- **Google Workspace MCP:** https://github.com/taylorwilsdon/google_workspace_mcp
- **Avicenna Repository:** Your repo link here

---

**Last Updated:** January 28, 2026  
**Version:** 2.0
| **Browser Automation** | 1 | 8 | ⭐ Low |
| **Communication** | 1 | 6 | ⭐ Low |

---

## 🚀 Quick Start: Adding Your First Server

1. **Check if package exists:**
   ```bash
   npm view @modelcontextprotocol/server-brave-search
   ```

2. **Add to config** (`~/.avicenna/mcp_config.json`):
   ```json
   {
     "name": "brave-search",
     "type": "node",
     "package": "@modelcontextprotocol/server-brave-search",
     "enabled": true,
     "env": {"BRAVE_API_KEY": ""}
   }
   ```

3. **Restart Avicenna:**
   ```bash
   python -m source.avicenna.main
   ```

4. **Verify in startup table:**
   ```
   ✓ brave-search  Node.js  2  Connected
   ```

---

## 🔗 Find More MCP Servers

- **Official Registry:** https://github.com/modelcontextprotocol/servers
- **NPM Search:** `npm search mcp server`
- **MCP Website:** https://modelcontextprotocol.io

---

**Current Status:** 15 tools from 2 servers  
**Potential With Recommendations:** 50+ tools from 8+ servers  
**Version:** Avicenna 2.0
