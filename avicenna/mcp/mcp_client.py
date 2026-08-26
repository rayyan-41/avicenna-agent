"""MCP Client Manager for Avicenna - Version 2.0

Manages connections to multiple MCP servers with support for:
- Python scripts
- Node.js packages (via npx)
- Direct executables
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from avicenna.mcp.mcp_config_schema import (
    MCPServerConfig,
    SERVER_TYPE_PYTHON,
    SERVER_TYPE_NODE,
    SERVER_TYPE_EXECUTABLE
)

if TYPE_CHECKING:
    from avicenna.providers.base import ToolSpec

logger = logging.getLogger(__name__)


def _tool_schema(tool: object) -> dict[str, Any]:
    """Read an MCP tool's JSON Schema across SDK major versions.

    mcp 1.x exposed `Tool.inputSchema`. mcp 2.x renamed the attribute to
    `input_schema` and kept `inputSchema` only as a pydantic serialisation
    alias, which is NOT an attribute. The previous
    `getattr(t, "inputSchema", {})` therefore silently returned {} for every
    tool under 2.x, handing the model tools with empty parameter schemas.
    """
    for attr in ("input_schema", "inputSchema"):
        schema = getattr(tool, attr, None)
        if isinstance(schema, dict):
            return schema
    return {"type": "object", "properties": {}}


class MCPClientManager:
    """
    Manages connections to multiple MCP servers.
    
    Supports multiple server types:
    - Python: Local Python scripts
    - Node: npm packages run via npx
    - Executable: Direct command execution
    """
    
    def __init__(self) -> None:
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.tools: Dict[str, MCPTool] = {}  # tool_name -> MCPTool
        self.tool_to_server: Dict[str, str] = {}  # tool_name -> server_name
    
    def _get_server_command(self, server_config: MCPServerConfig) -> Tuple[str, List[str]]:
        """
        Determine the command and arguments for a server based on its type.
        
        Returns:
            Tuple of (command, args_list)
            
        Raises:
            ValueError: If server type is unknown or required paths not found
        """
        server_type = server_config.type
        extra_args = server_config.args or []
        
        if server_type == SERVER_TYPE_PYTHON:
            # Python script
            # MCPServerConfig.__post_init__ guarantees `script` is set for
            # python-type servers, which mypy cannot see through.
            script_path = Path(cast(str, server_config.script))
            if not script_path.is_absolute():
                # Make relative to project root
                project_root = Path(__file__).parent.parent
                script_path = project_root / script_path
            
            if not script_path.exists():
                raise ValueError(f"Server script not found: {script_path}")
            
            # Find Python interpreter
            python_path = sys.executable or shutil.which("python") or shutil.which("python3")
            if not python_path:
                raise ValueError("Python interpreter not found")
            
            return python_path, [str(script_path.absolute())] + extra_args
        
        elif server_type == SERVER_TYPE_NODE:
            # Node.js package via npx
            npx_path = shutil.which("npx")
            if not npx_path:
                # Try common Node.js installation paths on Windows
                possible_paths = [
                    Path(os.environ.get("PROGRAMFILES", "")) / "nodejs" / "npx.cmd",
                    Path(os.environ.get("APPDATA", "")) / "npm" / "npx.cmd",
                    Path.home() / "AppData" / "Roaming" / "npm" / "npx.cmd",
                ]
                for p in possible_paths:
                    if p.exists():
                        npx_path = str(p)
                        break
            
            if not npx_path:
                raise ValueError(
                    "npx not found. Please install Node.js: https://nodejs.org/\n"
                    "After installing, restart your terminal."
                )
            
            package = server_config.package
            if not package:
                raise ValueError(f"Node server '{server_config.name}' requires 'package' name")
            
            # npx -y <package> [args...]
            # -y flag auto-installs the package if not present
            return npx_path, ["-y", package] + extra_args
        
        elif server_type == SERVER_TYPE_EXECUTABLE:
            # Direct executable
            command = server_config.command
            if not command:
                raise ValueError(f"Executable server '{server_config.name}' requires 'command'")
            
            # Try to find the command
            exec_path = shutil.which(command)
            if not exec_path:
                # Try as absolute path
                if Path(command).exists():
                    exec_path = command
                else:
                    raise ValueError(f"Executable not found: {command}")
            
            return exec_path, extra_args
        
        else:
            raise ValueError(f"Unknown server type: {server_type}")
        
    async def connect_server(self, server_config: MCPServerConfig) -> bool:
        """
        Connect to a single MCP server.
        
        Supports Python scripts, Node.js packages, and executables.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to MCP server: {server_config.name} (type: {server_config.type})")
            
            # Get command and args based on server type
            command, args = self._get_server_command(server_config)
            
            logger.debug(f"  Command: {command}")
            logger.debug(f"  Args: {args}")
            
            # Merge environment variables
            env = os.environ.copy()
            
            # CRITICAL: Set OAUTHLIB_INSECURE_TRANSPORT for Google OAuth with http://localhost
            # Without this, OAuth will fail with "InvalidOAuthRedirectSchemeError"
            env["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
            
            if server_config.env:
                # Only add non-empty values from server config
                # Empty strings indicate "use value from .env/environment" (don't override!)
                for key, value in server_config.env.items():
                    if value:  # Only set if not empty string
                        env[key] = value
            
            # Configure server parameters
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env
            )
            
            # Start stdio connection
            read, write = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            
            # Create session
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            
            # Initialize session
            await session.initialize()
            
            # Store session
            self.sessions[server_config.name] = session
            
            # Discover tools from this server
            tools_list = await session.list_tools()
            
            for tool in tools_list.tools:
                self.tools[tool.name] = tool
                self.tool_to_server[tool.name] = server_config.name
                logger.debug(f"  Registered tool: {tool.name}")
            
            logger.info(f"✓ Connected to {server_config.name}: {len(tools_list.tools)} tools")
            return True
            
        except ValueError as e:
            # Configuration errors
            logger.error(f"✗ Config error for {server_config.name}: {e}")
            return False
        except Exception as e:
            logger.error(f"✗ Failed to connect to {server_config.name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_email_provider: Optional[Callable[[], Optional[str]]] = None,
    ) -> str:
        """
        Call a tool via its MCP server
        
        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of arguments to pass
            user_email_provider: Optional callable that returns user's Google email when needed
            
        Returns:
            Tool result as string
        """
        if tool_name not in self.tool_to_server:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        server_name = self.tool_to_server[tool_name]
        session = self.sessions.get(server_name)
        
        if not session:
            raise RuntimeError(f"Server not connected: {server_name}")
        
        # Auto-inject user_google_email for workspace-mcp tools if needed
        if server_name == "google-workspace":
            tool = self.tools.get(tool_name)
            if tool is not None:
                schema = _tool_schema(tool)
                # Check if tool requires user_google_email and it's not provided
                if (isinstance(schema, dict) and 
                    'required' in schema and 
                    'user_google_email' in schema.get('required', []) and
                    'user_google_email' not in arguments):
                    
                    # Try to get email from provider
                    if user_email_provider and callable(user_email_provider):
                        email = user_email_provider()
                        if email:
                            arguments = {**arguments, 'user_google_email': email}
                            logger.info(f"Auto-injected user_google_email for {tool_name}")
                        else:
                            logger.warning(f"Tool {tool_name} requires user_google_email but none available")
        
        logger.info(f"Calling tool {tool_name} on server {server_name}")
        logger.debug(f"Arguments: {arguments}")
        
        # Call tool via MCP protocol
        result = await session.call_tool(tool_name, arguments=arguments)
        
        # Extract content from result
        if result and hasattr(result, 'content') and result.content:
            # Concatenate all text content
            text_parts = []
            for content in result.content:
                if hasattr(content, 'text') and content.text:
                    text_parts.append(content.text)
            
            if text_parts:
                return '\n'.join(text_parts)
        
        return str(result) if result else "Tool execution completed with no output."
    
    def tool_specs(self) -> "List[ToolSpec]":
        """Return neutral ToolSpec objects from discovered MCP tools.

        This is the vendor-neutral export path; each provider converts at its edge.
        """
        from avicenna.providers.base import ToolSpec

        specs: List[ToolSpec] = []
        for tool_name, mcp_tool in self.tools.items():
            specs.append(ToolSpec(
                name=mcp_tool.name,
                description=mcp_tool.description or "",
                parameters=_tool_schema(mcp_tool),
            ))
        return specs

    async def cleanup(self) -> None:
        """Clean up all server connections"""
        logger.info("Closing MCP server connections...")
        await self.exit_stack.aclose()
        self.sessions.clear()
        self.tools.clear()
        self.tool_to_server.clear()
        logger.info("All MCP servers disconnected")
