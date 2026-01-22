"""MCP Client Manager for Avicenna"""
import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from google.genai import types as genai_types

from mcp_servers.mcp_config_schema import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages connections to multiple MCP servers"""
    
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.tools: Dict[str, MCPTool] = {}  # tool_name -> MCPTool
        self.tool_to_server: Dict[str, str] = {}  # tool_name -> server_name
        
    async def connect_server(self, server_config: MCPServerConfig) -> bool:
        """
        Connect to a single MCP server
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to MCP server: {server_config.name}")
            
            # Resolve script path
            script_path = Path(server_config.script)
            if not script_path.is_absolute():
                # Make relative to project root
                project_root = Path(__file__).parent.parent.parent
                script_path = project_root / script_path
            
            if not script_path.exists():
                logger.error(f"Server script not found: {script_path}")
                return False
            
            # Find Python interpreter - prefer current interpreter
            python_path = sys.executable
            if not python_path:
                python_path = shutil.which("python")
            if not python_path:
                python_path = shutil.which("python3")
            
            if not python_path:
                logger.error("Python interpreter not found")
                return False
            
            # Configure server parameters
            server_params = StdioServerParameters(
                command=python_path,
                args=[str(script_path.absolute())],
                env=server_config.env or {}
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
                logger.info(f"  ✓ Registered tool: {tool.name}")
            
            logger.info(f"✅ Connected to {server_config.name}: {len(tools_list.tools)} tools")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to {server_config.name}: {e}")
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
        if result.content:
            # Concatenate all text content
            text_parts = []
            for content in result.content:
                if hasattr(content, 'text'):
                    text_parts.append(content.text)
            
            if text_parts:
                return '\n'.join(text_parts)
        
        return str(result)
    
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
        logger.info("✅ All MCP servers disconnected")
