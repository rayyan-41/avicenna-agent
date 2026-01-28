# Deprecated MCP Servers

**⚠️ These servers are deprecated and no longer maintained.**

## Migration to Version 2.0

Avicenna v2.0 uses the official MCP ecosystem servers instead of custom implementations.

### Deprecated Servers

#### `basic_server.py`
**Replaced by:** Node.js MCP servers with better functionality
- Time functions: Available in most LLMs natively
- Calculator: Available in most LLMs natively
- **Recommendation:** Remove from configuration (disabled by default)

#### `gmail_server.py`
**Replaced by:** `@modelcontextprotocol/server-gmail` (when available)
- Limited to draft/send functionality
- Requires complex OAuth setup
- **Recommendation:** Use official Gmail MCP server when published

### Why Were These Deprecated?

1. **Better Alternatives:** Official MCP ecosystem provides:
   - More features (14 filesystem tools vs our basic 2 tools)
   - Better maintenance and updates
   - Community support
   - Professional implementation

2. **Maintenance Burden:** Custom servers require ongoing maintenance

3. **Limited Functionality:** Our basic servers were proof-of-concept implementations

### If You Still Need These

These files are preserved for reference. To use them:

1. Copy the server file back to `mcp_servers/`
2. Add to your `~/.avicenna/mcp_config.json`:
   ```json
   {
     "name": "basic",
     "type": "python",
     "script": "mcp_servers/basic_server.py",
     "enabled": true
   }
   ```

### Recommended Upgrade Path

Replace legacy servers with MCP ecosystem alternatives:

```json
{
  "version": "2.0",
  "mcp_servers": [
    {
      "name": "filesystem",
      "type": "node",
      "package": "@modelcontextprotocol/server-filesystem",
      "enabled": true,
      "args": ["C:\\Users\\YourName\\Documents"]
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

For more information, see the main [README.md](../../README.md).
