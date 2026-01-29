"""MCP Server Configuration Schema - Version 2.0

Supports multiple server types:
- Python scripts (type: "python")
- Node.js packages via npx (type: "node")
- Direct executables (type: "executable")
"""
from typing import List, Optional
from dataclasses import dataclass, field
from pathlib import Path
import json


# Server type constants
SERVER_TYPE_PYTHON = "python"
SERVER_TYPE_NODE = "node"
SERVER_TYPE_EXECUTABLE = "executable"


@dataclass
class MCPServerConfig:
    """
    Configuration for a single MCP server.
    
    Supports multiple server types:
    - Python: Local Python scripts (script path required)
    - Node: npm packages run via npx (package name required)
    - Executable: Direct command execution (command required)
    
    Attributes:
        name: Unique identifier for the server
        type: Server type ("python", "node", or "executable")
        enabled: Whether the server should be started
        description: Human-readable description
        
        # Python-specific
        script: Path to Python script (relative to project root)
        
        # Node-specific  
        package: npm package name (e.g., "@modelcontextprotocol/server-fetch")
        
        # Executable-specific
        command: Command to run
        
        # Common
        args: Command-line arguments
        env: Environment variables
    """
    name: str
    type: str = SERVER_TYPE_NODE  # Default to node for new servers
    enabled: bool = True
    description: Optional[str] = None
    
    # Python servers
    script: Optional[str] = None
    
    # Node.js servers
    package: Optional[str] = None
    
    # Executable servers
    command: Optional[str] = None
    
    # Common options
    args: Optional[List[str]] = None
    env: Optional[dict] = None
    
    def __post_init__(self):
        """Validate configuration based on server type"""
        if self.type == SERVER_TYPE_PYTHON and not self.script:
            raise ValueError(f"Python server '{self.name}' requires 'script' path")
        if self.type == SERVER_TYPE_NODE and not self.package:
            raise ValueError(f"Node server '{self.name}' requires 'package' name")
        if self.type == SERVER_TYPE_EXECUTABLE and not self.command:
            raise ValueError(f"Executable server '{self.name}' requires 'command'")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = {
            "name": self.name,
            "type": self.type,
            "enabled": self.enabled,
        }
        
        # Add optional fields only if they have values
        if self.description:
            data["description"] = self.description
        if self.script:
            data["script"] = self.script
        if self.package:
            data["package"] = self.package
        if self.command:
            data["command"] = self.command
        if self.args:
            data["args"] = self.args
        if self.env:
            data["env"] = self.env
            
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MCPServerConfig':
        """Create from dictionary, handling legacy format"""
        # Handle legacy format (no 'type' field, only 'script')
        if 'type' not in data and 'script' in data:
            data['type'] = SERVER_TYPE_PYTHON
        
        # Filter to only valid fields
        valid_fields = {
            'name', 'type', 'enabled', 'description', 
            'script', 'package', 'command', 'args', 'env'
        }
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered)


@dataclass
class MCPConfiguration:
    """Complete MCP configuration"""
    servers: List[MCPServerConfig]
    version: str = "2.0"
    
    @classmethod
    def from_file(cls, path: Path) -> 'MCPConfiguration':
        """Load configuration from JSON file"""
        with open(path, 'r') as f:
            data = json.load(f)
        
        servers = [
            MCPServerConfig.from_dict(server_data) 
            for server_data in data.get('mcp_servers', [])
        ]
        version = data.get('version', '1.0')
        
        return cls(servers=servers, version=version)
    
    @classmethod
    def default(cls) -> 'MCPConfiguration':
        """
        Create default configuration with recommended MCP servers.
        
        Includes:
        - filesystem: Local file operations (primary tool)
        - sequential-thinking: Enhanced reasoning
        - fetch: Web content fetching (TypeScript version)
        - brave-search: Web search (disabled, requires API key)
        """
        return cls(
            version="2.0",
            servers=[
                # File System - most commonly used
                MCPServerConfig(
                    name="filesystem",
                    type=SERVER_TYPE_NODE,
                    package="@modelcontextprotocol/server-filesystem",
                    enabled=True,
                    description="Read/write local files (configure allowed directories in args)",
                    args=[]  # User should add allowed directories like: ["C:\\Users\\Name\\Documents"]
                ),
                # Reasoning - helps with complex tasks
                MCPServerConfig(
                    name="sequential-thinking",
                    type=SERVER_TYPE_NODE,
                    package="@modelcontextprotocol/server-sequential-thinking",
                    enabled=True,
                    description="Enhanced step-by-step reasoning for complex problems"
                ),
                # Puppeteer - Browser Automation (OFFICIAL MICROSOFT)
                MCPServerConfig(
                    name="playwright",
                    type=SERVER_TYPE_NODE,
                    package="@microsoft/playwright-mcp",
                    enabled=True,
                    description="Official Microsoft Playwright browser automation: screenshots, navigation, scraping (run 'npx playwright install' first)"
                ),
                # Google Workspace - Gmail, Calendar, Drive, Docs, Sheets, Slides
                MCPServerConfig(
                    name="google-workspace",
                    type=SERVER_TYPE_EXECUTABLE,
                    command="uvx",
                    args=["workspace-mcp", "--single-user"],
                    enabled=True,
                    description="Full Google Workspace: Gmail, Calendar, Drive, Docs, Sheets, Slides (requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)",
                    env={
                        "GOOGLE_OAUTH_CLIENT_ID": "",
                        "GOOGLE_OAUTH_CLIENT_SECRET": ""
                    }
                ),
                # Web Search - SerpAPI (Multi-Engine Search)
                MCPServerConfig(
                    name="serpapi-search",
                    type=SERVER_TYPE_EXECUTABLE,
                    command="uvx",
                    args=["serpapi-mcp"],
                    enabled=False,
                    description="Multi-engine search (Google, Bing, DuckDuckGo, YouTube) via SerpAPI (requires SERPAPI_API_KEY)",
                    env={"SERPAPI_API_KEY": ""}
                ),
                # Gmail - Working Google Workspace Component
                MCPServerConfig(
                    name="gmail",
                    type=SERVER_TYPE_PYTHON,
                    script="tools/gmail.py",
                    enabled=True,
                    description="Gmail integration: send, read, search emails (requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)",
                    env={
                        "GOOGLE_API_KEY": "",
                        "GOOGLE_OAUTH_CLIENT_ID": "",
                        "GOOGLE_OAUTH_CLIENT_SECRET": ""
                    }
                ),
                # Legacy Python servers (deprecated)
                MCPServerConfig(
                    name="basic",
                    type=SERVER_TYPE_PYTHON,
                    script="mcp_servers/deprecated/basic_server.py",
                    enabled=False,  # Deprecated - use filesystem instead
                    description="[DEPRECATED] Basic tools: time, calculator"
                ),
            ]
        )
    
    def save(self, path: Path):
        """Save configuration to JSON file"""
        data = {
            "version": self.version,
            "mcp_servers": [server.to_dict() for server in self.servers]
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """Get list of enabled servers only"""
        return [s for s in self.servers if s.enabled]
    
    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """Get a server by name"""
        for server in self.servers:
            if server.name == name:
                return server
        return None
