# Deprecated Tools

**⚠️ These tool implementations are deprecated.**

## `gmail.py`

This was a custom Gmail tool implementation used by the deprecated `gmail_server.py`.

### Why Deprecated?

- Limited to basic draft/send functionality
- Complex OAuth credential management
- Better alternatives available in MCP ecosystem

### Migration

Use official MCP servers for Gmail functionality (when available), or use the web interface directly for email operations.

The Gmail OAuth flow and credential management code in this file can serve as reference if you need to build custom Google API integrations.

For more information, see the main [README.md](../../../README.md).
