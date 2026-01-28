"""MCP Client Manager for Avicenna - Version 2.0

Manages connections to multiple MCP servers with support for:
- Python scripts
- Node.js packages (via npx)
- Direct executables
"""
import asyncio
import logging
import shutil
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from google.genai import types as genai_types

from mcp_servers.mcp_config_schema import (
    MCPServerConfig,
    SERVER_TYPE_PYTHON,
    SERVER_TYPE_NODE,
    SERVER_TYPE_EXECUTABLE
)

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    Manages connections to multiple MCP servers.
    
    Supports multiple server types:
    - Python: Local Python scripts
    - Node: npm packages run via npx
    - Executable: Direct command execution
    """
    
    def __init__(self):
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
            script_path = Path(server_config.script)
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
            if server_config.env:
                env.update(server_config.env)
            
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
    
    async def connect_all(self, server_configs: List[MCPServerConfig]) -> Dict[str, bool]:
        """
        Connect to all enabled servers
        
        Returns:
            Dict mapping server name to connection success status
        """
        results = {}
        
        for config in server_configs:
            if not config.enabled:
                logger.info(f"Skipping disabled server: {config.name}")
                results[config.name] = False
                continue
            
            results[config.name] = await self.connect_server(config)
        
        return results
    
    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Call a tool via its MCP server
        
        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of arguments to pass
            
        Returns:
            Tool result as string
        """
        if tool_name not in self.tool_to_server:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        server_name = self.tool_to_server[tool_name]
        session = self.sessions.get(server_name)
        
        if not session:
            raise RuntimeError(f"Server not connected: {server_name}")
        
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
    
    def get_gemini_tools(self) -> List[genai_types.Tool]:
        """
        Convert MCP tools to Gemini Tool format
        
        Returns:
            List of Gemini Tool objects
        """
        # Group tools by converting each MCP tool to a FunctionDeclaration
        function_declarations = []
        
        for tool_name, mcp_tool in self.tools.items():
            # Convert MCP tool to Gemini FunctionDeclaration
            function_decl = genai_types.FunctionDeclaration(
                name=mcp_tool.name,
                description=mcp_tool.description or f"Tool: {mcp_tool.name}",
                parameters=self._convert_schema(mcp_tool.inputSchema)
            )
            
            function_declarations.append(function_decl)
        
        # Gemini expects all function declarations in a single Tool object
        if function_declarations:
            return [genai_types.Tool(function_declarations=function_declarations)]
        
        return []
    
    def _convert_schema(self, json_schema: dict) -> dict:
        """
        Convert JSON Schema to Gemini parameter format
        
        MCP uses JSON Schema, Gemini uses a similar but different format
        """
        if not json_schema:
            return {"type": "object", "properties": {}}
        
        # Basic conversion - JSON Schema and Gemini format are similar
        # May need refinement for complex schemas
        converted = {
            "type": json_schema.get("type", "object"),
        }
        
        if "properties" in json_schema:
            converted["properties"] = json_schema["properties"]
        
        if "required" in json_schema:
            converted["required"] = json_schema["required"]
            
        return converted
    
    def list_available_tools(self) -> List[str]:
        """Get list of all available tool names"""
        return list(self.tools.keys())
    
    async def cleanup(self):
        """Clean up all server connections"""
        logger.info("Closing MCP server connections...")
        await self.exit_stack.aclose()
        self.sessions.clear()
        self.tools.clear()
        self.tool_to_server.clear()
        logger.info("All MCP servers disconnected")
