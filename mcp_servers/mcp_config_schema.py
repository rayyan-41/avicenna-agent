"""MCP Server Configuration Schema"""
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server"""
    name: str
    script: str  # Path to server script
    enabled: bool = True
    description: Optional[str] = None
    env: Optional[dict] = None  # Environment variables for server

@dataclass
class MCPConfiguration:
    """Complete MCP configuration"""
    servers: List[MCPServerConfig]
    
    @classmethod
    def from_file(cls, path: Path) -> 'MCPConfiguration':
        """Load configuration from JSON file"""
        with open(path, 'r') as f:
            data = json.load(f)
        
        servers = [
            MCPServerConfig(**server_data) 
            for server_data in data.get('mcp_servers', [])
        ]
        return cls(servers=servers)
    
    @classmethod
    def default(cls) -> 'MCPConfiguration':
        """Create default configuration"""
        return cls(servers=[
            MCPServerConfig(
                name="basic",
                script="mcp_servers/basic_server.py",
                enabled=True,
                description="Basic tools: time, calculator"
            ),
            MCPServerConfig(
                name="gmail",
                script="mcp_servers/gmail_server.py",
                enabled=True,
                description="Gmail email sending capabilities"
            )
        ])
    
    def save(self, path: Path):
        """Save configuration to JSON file"""
        data = {
            "mcp_servers": [
                {
                    "name": server.name,
                    "script": server.script,
                    "enabled": server.enabled,
                    "description": server.description,
                    "env": server.env
                }
                for server in self.servers
            ]
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
