# MCP Migration Implementation Plan

## Overview

This document provides a detailed, step-by-step implementation plan for migrating Avicenna from native Gemini function calling to the Model Context Protocol (MCP) architecture.

**Estimated Time:** 6-8 hours  
**Complexity:** High  
**Risk Level:** Medium

---

## Pre-Migration Checklist

### Prerequisites
- [x] MCP SDK installed (`pip install mcp`)
- [ ] Clean git working directory
- [ ] Create migration branch: `git checkout -b feature/mcp-migration`
- [ ] Backup current working version: `git tag pre-mcp-migration`
- [ ] Python 3.11+ confirmed (async features)
- [ ] All current tests passing

### Environment Setup
```bash
# Create clean test environment
python -m venv venv-mcp-test
source venv-mcp-test/bin/activate  # Windows: venv-mcp-test\Scripts\activate
pip install -r requirements.txt
```

---

## Phase 1: Configuration Infrastructure

**Goal:** Create MCP configuration system before touching existing code  
**Duration:** 30 minutes  
**Risk:** Low

### Step 1.1: Create MCP Configuration Schema

**File:** `source/avicenna/mcp_config_schema.py`

```python
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
                script="source/tools/basic_server.py",
                enabled=True,
                description="Basic tools: time, calculator"
            ),
            MCPServerConfig(
                name="gmail",
                script="source/tools/gmail_server.py",
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
```

**Test:**
```python
# Quick test in Python REPL
from source.avicenna.mcp_config_schema import MCPConfiguration
config = MCPConfiguration.default()
print(config)
```

---

### Step 1.2: Create Default Configuration File

**File:** `~/.avicenna/mcp_config.json`

```json
{
  "mcp_servers": [
    {
      "name": "basic",
      "script": "source/tools/basic_server.py",
      "enabled": true,
      "description": "Basic tools: time, calculator"
    },
    {
      "name": "gmail",
      "script": "source/tools/gmail_server.py",
      "enabled": true,
      "description": "Gmail email sending capabilities"
    }
  ]
}
```

**Implementation Location:** Add to `source/avicenna/config.py`

```python
# Add to existing Config class
from pathlib import Path
from .mcp_config_schema import MCPConfiguration

class Config:
    # ... existing config ...
    
    # MCP Configuration
    MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'
    
    @classmethod
    def load_mcp_config(cls) -> MCPConfiguration:
        """Load MCP configuration, creating default if needed"""
        if not cls.MCP_CONFIG_PATH.exists():
            config = MCPConfiguration.default()
            config.save(cls.MCP_CONFIG_PATH)
            print(f"✅ Created default MCP config: {cls.MCP_CONFIG_PATH}")
            return config
        
        try:
            return MCPConfiguration.from_file(cls.MCP_CONFIG_PATH)
        except Exception as e:
            print(f"⚠️ Error loading MCP config, using defaults: {e}")
            return MCPConfiguration.default()
```

**Test:**
```python
from source.avicenna.config import Config
config = Config.load_mcp_config()
assert len(config.servers) == 2
```

---

## Phase 2: MCP Server Implementation

**Goal:** Create standalone MCP servers for existing tools  
**Duration:** 1.5 hours  
**Risk:** Low

### Step 2.1: Create Basic Tools MCP Server

**File:** `source/tools/basic_server.py`

```python
"""MCP Server for Basic Tools (time, calculator)"""
import asyncio
from datetime import datetime
import ast
import operator
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Basic Tools")

# Safe math operators
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

def evaluate_expression(node):
    """Safely evaluate a mathematical expression AST node"""
    if isinstance(node, ast.Num):
        return node.n
    elif isinstance(node, ast.BinOp):
        left = evaluate_expression(node.left)
        right = evaluate_expression(node.right)
        return OPERATORS[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = evaluate_expression(node.operand)
        return OPERATORS[type(node.op)](operand)
    else:
        raise ValueError(f"Unsupported operation: {type(node).__name__}")

@mcp.tool()
def get_current_time() -> str:
    """
    Returns the current system date and time.
    
    Use this when the user asks for the current time, date, or day.
    Returns a human-readable timestamp.
    """
    return datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

@mcp.tool()
def calculate(expression: str) -> str:
    """
    Safely evaluates a mathematical expression.
    
    Supports: +, -, *, /, %, ** (power), parentheses
    Example: "2 + 2" returns "4"
    Example: "10 ** 2" returns "100"
    
    Args:
        expression: A mathematical expression as a string
        
    Returns:
        The result of the calculation as a string
    """
    try:
        # Remove whitespace
        expression = expression.strip()
        
        # Parse into AST
        tree = ast.parse(expression, mode='eval')
        
        # Evaluate safely
        result = evaluate_expression(tree.body)
        
        return str(result)
    except Exception as e:
        return f"❌ Calculation error: {str(e)}"

if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
```

**Test Server:**
```bash
# Run server manually to test
python source/tools/basic_server.py

# In another terminal, test with MCP client (will do in Phase 4)
```

---

### Step 2.2: Create Gmail MCP Server

**File:** `source/tools/gmail_server.py`

```python
"""MCP Server for Gmail Tools"""
import asyncio
from mcp.server.fastmcp import FastMCP
from .gmail import GmailTool

# Initialize FastMCP server
mcp = FastMCP("Gmail")

# Initialize Gmail tool (authentication happens here)
try:
    gmail_service = GmailTool()
    print("✅ Gmail authentication successful")
except Exception as e:
    print(f"⚠️ Gmail authentication failed: {e}")
    gmail_service = None

@mcp.tool()
def draft_email(recipient_email: str, subject: str, body: str) -> str:
    """
    Creates an email draft and shows a preview WITHOUT sending.
    
    This is the REQUIRED first step before sending any email.
    Shows the user exactly what will be sent and asks for confirmation.
    
    Args:
        recipient_email: The email address of the receiver
        subject: The subject line of the email
        body: The content/body of the email
        
    Returns:
        A formatted preview of the email with confirmation prompt
    """
    if gmail_service is None:
        return "❌ Gmail service not authenticated. Run gmail_server.py directly first."
    
    return gmail_service.draft_email(recipient_email, subject, body)

@mcp.tool()
def send_email(recipient_email: str, subject: str, body: str) -> str:
    """
    Sends an email using the authorized Gmail account.
    
    IMPORTANT: Should ONLY be called after draft_email and explicit user confirmation.
    
    Args:
        recipient_email: The email address of the receiver
        subject: The subject line of the email
        body: The content/body of the email
        
    Returns:
        Confirmation message with email ID or error message
    """
    if gmail_service is None:
        return "❌ Gmail service not authenticated. Run gmail_server.py directly first."
    
    return gmail_service.send_email(recipient_email, subject, body)

if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
```

**Test Server:**
```bash
# Run server manually to test authentication
python source/tools/gmail_server.py

# Should show Gmail authentication flow if needed
```

**Important Note:** The import `from .gmail import GmailTool` might fail when run as `__main__`. Fix:

```python
# Add this at the top of gmail_server.py
import sys
from pathlib import Path

# Add parent directory to path for imports
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from source.tools.gmail import GmailTool
else:
    from .gmail import GmailTool
```

---

## Phase 3: MCP Client Implementation

**Goal:** Create MCP client that discovers and connects to servers  
**Duration:** 2 hours  
**Risk:** High

### Step 3.1: Create MCP Client Manager

**File:** `source/avicenna/mcp_client.py`

```python
"""MCP Client Manager for Avicenna"""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from google.genai import types as genai_types

from .mcp_config_schema import MCPServerConfig

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
            if not script_path.exists():
                logger.error(f"Server script not found: {script_path}")
                return False
            
            # Find Python interpreter
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
                env=server_config.env
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
    
    async def call_tool(self, tool_name: str, arguments: dict) -> any:
        """
        Call a tool via its MCP server
        
        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of arguments to pass
            
        Returns:
            Tool result
        """
        if tool_name not in self.tool_to_server:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        server_name = self.tool_to_server[tool_name]
        session = self.sessions.get(server_name)
        
        if not session:
            raise RuntimeError(f"Server not connected: {server_name}")
        
        # Call tool via MCP protocol
        result = await session.call_tool(tool_name, arguments=arguments)
        
        # Extract content from result
        if result.content:
            # Return first text content
            for content in result.content:
                if hasattr(content, 'text'):
                    return content.text
        
        return str(result)
    
    def get_gemini_tools(self) -> List[genai_types.Tool]:
        """
        Convert MCP tools to Gemini Tool format
        
        Returns:
            List of Gemini Tool objects
        """
        gemini_tools = []
        
        for tool_name, mcp_tool in self.tools.items():
            # Convert MCP tool to Gemini FunctionDeclaration
            function_decl = genai_types.FunctionDeclaration(
                name=mcp_tool.name,
                description=mcp_tool.description or f"Tool: {mcp_tool.name}",
                parameters=self._convert_schema(mcp_tool.inputSchema)
            )
            
            # Wrap in Tool object
            gemini_tool = genai_types.Tool(
                function_declarations=[function_decl]
            )
            
            gemini_tools.append(gemini_tool)
        
        return gemini_tools
    
    def _convert_schema(self, json_schema: dict) -> dict:
        """
        Convert JSON Schema to Gemini parameter format
        
        MCP uses JSON Schema, Gemini uses a similar but different format
        """
        if not json_schema:
            return {"type": "object", "properties": {}}
        
        # Basic conversion - JSON Schema and Gemini format are similar
        # May need refinement for complex schemas
        return {
            "type": json_schema.get("type", "object"),
            "properties": json_schema.get("properties", {}),
            "required": json_schema.get("required", [])
        }
    
    async def cleanup(self):
        """Clean up all server connections"""
        logger.info("Closing MCP server connections...")
        await self.exit_stack.aclose()
        logger.info("✅ All MCP servers disconnected")
```

**Test:**
```python
# Test script: test_mcp_client.py
import asyncio
from source.avicenna.mcp_client import MCPClientManager
from source.avicenna.mcp_config_schema import MCPServerConfig

async def test():
    manager = MCPClientManager()
    
    config = MCPServerConfig(
        name="basic",
        script="source/tools/basic_server.py",
        enabled=True
    )
    
    success = await manager.connect_server(config)
    assert success
    
    result = await manager.call_tool("get_current_time", {})
    print(f"Result: {result}")
    
    await manager.cleanup()

asyncio.run(test())
```

---

## Phase 4: GeminiProvider Refactoring

**Goal:** Convert GeminiProvider to use MCP instead of native tools  
**Duration:** 2 hours  
**Risk:** High

### Step 4.1: Backup Current Provider

```bash
cp source/avicenna/providers/gemini.py source/avicenna/providers/gemini_native.py.bak
```

### Step 4.2: Refactor GeminiProvider

**File:** `source/avicenna/providers/gemini.py`

Complete rewrite:

```python
"""Gemini Provider with MCP Integration"""
import logging
import time
from typing import Optional
from google import genai
from google.genai import types
from . import LLMProvider
from ..mcp_client import MCPClientManager
from ..config import Config

logger = logging.getLogger(__name__)

class GeminiProvider(LLMProvider):
    """Gemini implementation using MCP for tool execution"""
    
    def __init__(self, api_key: str, model_name: str, system_instruction: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.mcp_manager: Optional[MCPClientManager] = None
        self.chat = None
        self.config = None
    
    async def initialize(self):
        """
        Async initialization - connects to MCP servers and discovers tools
        
        Must be called before using the provider
        """
        # Load MCP configuration
        mcp_config = Config.load_mcp_config()
        
        # Create MCP client manager
        self.mcp_manager = MCPClientManager()
        
        # Connect to all servers
        print("🔌 Connecting to MCP servers...")
        connection_results = await self.mcp_manager.connect_all(mcp_config.servers)
        
        # Report connection status
        for server_name, success in connection_results.items():
            if success:
                print(f"  ✓ {server_name}")
            else:
                print(f"  ✗ {server_name} (failed)")
        
        # Get tools in Gemini format
        gemini_tools = self.mcp_manager.get_gemini_tools()
        
        print(f"📦 Loaded {len(gemini_tools)} tools")
        
        # Configure chat with discovered tools
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            temperature=0.7,
            tools=gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True  # We handle function calling manually
            )
        )
        
        # Initialize chat
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )
    
    async def send_message(self, message: str, timeout: int = 30, max_retries: int = 3) -> str:
        """
        Send a message to Gemini with MCP tool support
        
        Args:
            message: The user's input message
            timeout: Maximum time to wait for response (seconds)
            max_retries: Maximum number of retry attempts
            
        Returns:
            The model's response text or error message
        """
        # Input validation
        if not message or not message.strip():
            return "⚠️ Error: Empty message received. Please provide a valid input."
        
        if len(message) > 100000:
            return "⚠️ Error: Message too long. Please limit input to 100,000 characters."
        
        # Check initialization
        if not self.mcp_manager or not self.chat:
            return "⚠️ Error: Provider not initialized. Call initialize() first."
        
        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                response = self.chat.send_message(message)
                
                # Check timeout
                if time.time() - start_time > timeout:
                    logger.warning(f"Request took {time.time() - start_time:.2f}s")
                
                # Check for safety blocks
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    
                    if hasattr(candidate, 'finish_reason'):
                        finish_reason = str(candidate.finish_reason)
                        if 'SAFETY' in finish_reason:
                            return "⚠️ Response blocked by safety filters. Please rephrase your message."
                        elif 'RECITATION' in finish_reason:
                            return "⚠️ Response blocked due to recitation concerns. Please try a different query."
                    
                    # Check for function calls
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                function_name = part.function_call.name
                                function_args = dict(part.function_call.args)
                                
                                logger.info(f"🔧 Tool call: {function_name}")
                                
                                # Execute tool via MCP
                                try:
                                    result = await self.mcp_manager.call_tool(
                                        function_name, 
                                        function_args
                                    )
                                except ValueError as e:
                                    logger.error(f"Unknown tool: {function_name}")
                                    return f"⚠️ Error: Unknown tool '{function_name}'"
                                except Exception as e:
                                    logger.error(f"Tool execution error: {e}")
                                    return f"⚠️ Error executing tool '{function_name}': {str(e)}"
                                
                                # Special handling for draft_email - return preview directly
                                if function_name == 'draft_email':
                                    return result
                                
                                # For other tools, send result back to model
                                function_response = self.chat.send_message(
                                    types.Part.from_function_response(
                                        name=function_name,
                                        response={"result": result}
                                    )
                                )
                                
                                if function_response.text:
                                    return function_response.text
                                else:
                                    return str(result)
                
                # Handle text response
                if response.text:
                    return response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        parts_text = []
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                parts_text.append(part.text)
                        if parts_text:
                            return ''.join(parts_text)
                
                # Empty response
                logger.warning("Empty response received from model")
                return "AI model provides no response. Reconsider prompt."
                
            except ConnectionError as e:
                logger.error(f"Connection error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                return "⚠️ Connection Error: Unable to reach Gemini API."
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Unexpected error: {type(e).__name__} - {error_msg}")
                
                # Handle specific error codes
                if "429" in error_msg or "quota" in error_msg.lower():
                    return "⚠️ Error: Gemini Quota Exceeded. Switch models in .env or check Google AI Studio."
                elif "401" in error_msg or "authentication" in error_msg.lower():
                    return "⚠️ Error: Authentication failed. Please check your API key in .env file."
                
                return f"⚠️ Error communicating with Gemini: {error_msg}"
        
        return "⚠️ Error: Maximum retry attempts exceeded. Please try again later."
    
    async def clear_history(self):
        """Clear chat history"""
        if self.mcp_manager and self.config:
            self.chat = self.client.chats.create(
                model=self.model_name,
                config=self.config
            )
    
    async def cleanup(self):
        """Clean up MCP connections"""
        if self.mcp_manager:
            await self.mcp_manager.cleanup()
```

**Key Changes:**
1. ✅ Removed native tool imports and `tool_map`
2. ✅ Added `MCPClientManager` integration
3. ✅ Added async `initialize()` method
4. ✅ All methods now `async`
5. ✅ Tool calls routed through `mcp_manager.call_tool()`
6. ✅ Added `cleanup()` for graceful shutdown

---

## Phase 5: Core Agent Refactoring

**Goal:** Update AvicennaAgent to async and integrate MCP initialization  
**Duration:** 1 hour  
**Risk:** Medium

### Step 5.1: Refactor core.py

**File:** `source/avicenna/core.py`

```python
"""Core Agent with MCP Support"""
from typing import Optional
from rich.console import Console
from .config import Config
from .providers.gemini import GeminiProvider

console = Console()

class AvicennaAgent:
    """Async Avicenna Agent with MCP tool support"""
    
    def __init__(self) -> None:
        if not Config.validate():
            raise ValueError("Configuration Error")

        self.system_instruction = (
            "# SYSTEM IDENTITY\n"
            "You are Avicenna, an AI agent operating under a constitutional framework. Constitutional principles:\n"
            "1. Operate deterministically and precisely\n"
            "2. Respect user autonomy through explicit confirmation gates\n"
            "3. Decline requests outside defined capabilities\n"
            "4. Maintain accurate record of system state\n\n"
            
            "# COMMUNICATION PROTOCOL\n"
            "- Direct and concise responses\n"
            "- No embellishment or theatrical elements\n"
            "- Factual framing\n"
            "- Task-oriented language\n"
            "- Binary confirmations use Y/N format\n\n"
            
            "# AVAILABLE OPERATIONS\n"
            "1. get_current_time - Returns system date/time\n"
            "2. calculate - Executes mathematical operations\n"
            "3. draft_email - Generates email draft for review\n"
            "4. send_email - Transmits email after authorization\n\n"
            
            "# EMAIL OPERATION PROTOCOL\n"
            "Email transmission requires explicit two-step authorization:\n\n"
            "STEP 1 - DRAFT GENERATION:\n"
            "- Call draft_email with recipient, subject, body\n"
            "- Display preview to user\n"
            "- Present confirmation prompt\n\n"
            "STEP 2 - TRANSMISSION:\n"
            "- Only proceed if user confirms (Y/Yes)\n"
            "- Call send_email with identical parameters\n"
            "- Report transmission status\n\n"
            "CONSTRAINT: Never transmit without draft review and explicit confirmation.\n\n"
            
            "# OPERATIONAL CONSTRAINTS\n"
            "- Do not claim capabilities beyond listed operations\n"
            "- Respond to unsupported requests with: 'Operation not available in current system configuration.'\n"
            "- Do not generate flowery, conversational, or informal output\n"
            "- Process requests with mechanical precision\n\n"
            
            "# CONSTITUTIONAL FRAMEWORK (BACKEND GOVERNANCE)\n"
            "The following principles govern all decision-making processes:\n"
            "- Principle of Clarity: Information must be unambiguous\n"
            "- Principle of User Authority: System confirms before executing consequential operations\n"
            "- Principle of Truthfulness: System reports accurate status and limitations\n"
            "- Principle of Determinism: Identical inputs produce identical outputs\n"
            "- Principle of Scope Limitation: System declines requests beyond defined capability set\n\n"
            
            "These principles operate as immutable constraints on system behavior."
        )

        # Create provider (not initialized yet)
        self.ai = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=self.system_instruction
        )
        
        self.initialized = False
        
    async def initialize(self):
        """
        Async initialization - must be called before use
        
        Connects to MCP servers and sets up tools
        """
        console.print(f"[dim]🔌 Connecting to {Config.MODEL_NAME}...[/dim]")
        
        try:
            # Initialize provider (connects to MCP servers)
            await self.ai.initialize()
            
            # Test connection
            test_response = await self.ai.send_message("ping")
            if "error" in test_response.lower():
                console.print(f" [red]✗ Failed[/red]")
                raise ValueError(f"Connection test failed: {test_response}")
            
            console.print(f" [green]✓ Connected[/green]")
            self.initialized = True
            
        except Exception as e:
            console.print(f" [red]✗ Failed[/red]")
            raise ValueError(f"Failed to initialize: {str(e)}")
    
    async def send_message(self, user_input: str) -> str:
        """
        Send a message to the agent
        
        Args:
            user_input: User's message
            
        Returns:
            Agent's response
        """
        if not self.initialized:
            return "⚠️ Error: Agent not initialized. Call initialize() first."
        
        return await self.ai.send_message(user_input)

    async def clear_history(self):
        """Clear conversation history"""
        await self.ai.clear_history()
    
    async def cleanup(self):
        """Clean up resources"""
        if self.initialized:
            await self.ai.cleanup()
```

**Key Changes:**
1. ✅ Removed `BASIC_TOOLS` import
2. ✅ Added `async def initialize()`
3. ✅ All methods now `async`
4. ✅ Added `initialized` flag
5. ✅ Added `cleanup()` method

---

## Phase 6: CLI Entry Point Refactoring

**Goal:** Convert main.py to async  
**Duration:** 1 hour  
**Risk:** Medium

### Step 6.1: Refactor main.py

**File:** `source/avicenna/main.py`

```python
"""Avicenna CLI - Async with MCP Support"""
import asyncio
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from .core import AvicennaAgent
from .config import Config

app = typer.Typer(help="Avicenna - A Constitutional AI Agent")
console = Console()

async def async_main():
    """Async main loop"""
    try:
        # Create agent
        agent = AvicennaAgent()
        
        # Initialize (connects to MCP servers)
        await agent.initialize()
        
        # Welcome message
        console.print("\n[bold cyan]╔═══════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║         AVICENNA AI AGENT             ║[/bold cyan]")
        console.print("[bold cyan]╚═══════════════════════════════════════╝[/bold cyan]\n")
        console.print("[dim]Type '/clear' to reset conversation[/dim]")
        console.print("[dim]Type '/exit' to quit[/dim]\n")
        
        # Main loop
        while True:
            try:
                # Get user input
                user_input = Prompt.ask("\n[bold blue]YOU[/bold blue]").strip()
                
                # Handle meta commands
                if user_input.lower() in ['/exit', '/quit', 'exit', 'quit']:
                    console.print("\n[dim]Goodbye! 👋[/dim]\n")
                    break
                    
                if user_input.lower() in ['/clear', 'clear']:
                    await agent.clear_history()
                    console.print("\n[green]✓[/green] [dim]Conversation history cleared[/dim]\n")
                    continue
                
                if not user_input:
                    continue
                
                # Send message to agent
                console.print()  # Blank line
                response = await agent.send_message(user_input)
                
                # Display response
                console.print("\n[bold green]AVICENNA[/bold green]:")
                
                # Check if response looks like markdown
                if any(marker in response for marker in ['```', '#', '*', '-', '>']):
                    console.print(Markdown(response))
                else:
                    console.print(response)
                
            except KeyboardInterrupt:
                console.print("\n\n[dim]Use '/exit' to quit[/dim]\n")
                continue
                
            except Exception as e:
                console.print(f"\n[red]Error:[/red] {str(e)}\n")
        
        # Cleanup
        await agent.cleanup()
        
    except Exception as e:
        console.print(f"\n[red]Fatal Error:[/red] {str(e)}\n")
        raise

@app.command()
def main():
    """Run Avicenna agent"""
    # Run async main loop
    asyncio.run(async_main())

if __name__ == "__main__":
    app()
```

**Key Changes:**
1. ✅ Created `async_main()` function
2. ✅ Wrapped in `asyncio.run()` in `main()`
3. ✅ All agent calls now `await`
4. ✅ Added `await agent.cleanup()` on exit

---

## Phase 7: Testing and Validation

**Goal:** Ensure migration works correctly  
**Duration:** 1 hour  
**Risk:** Medium

### Step 7.1: Manual Testing Checklist

```bash
# 1. Test basic startup
avicenna

# Expected: Should connect to MCP servers and show tool count

# 2. Test time tool
YOU: what time is it?
# Expected: Should show current time

# 3. Test calculator
YOU: calculate 2 + 2
# Expected: Should return 4

# 4. Test email draft
YOU: draft an email to test@example.com with subject "Test" and body "Hello"
# Expected: Should show formatted email preview

# 5. Test clear history
YOU: /clear
# Expected: Should clear conversation

# 6. Test exit
YOU: /exit
# Expected: Should cleanup and exit gracefully
```

### Step 7.2: Error Testing

```bash
# 1. Test with disabled server
# Edit ~/.avicenna/mcp_config.json - set gmail.enabled = false
avicenna
YOU: draft an email to test@example.com
# Expected: Should show error about unavailable tool

# 2. Test with missing server script
# Edit ~/.avicenna/mcp_config.json - set invalid path
avicenna
# Expected: Should show connection failure but continue with other servers

# 3. Test with invalid tool arguments
YOU: calculate
# Expected: Should handle gracefully
```

### Step 7.3: Create Test Suite

**File:** `tests/test_mcp_migration.py`

```python
"""Test suite for MCP migration"""
import asyncio
import pytest
from source.avicenna.core import AvicennaAgent

@pytest.mark.asyncio
async def test_agent_initialization():
    """Test that agent initializes with MCP servers"""
    agent = AvicennaAgent()
    await agent.initialize()
    
    assert agent.initialized
    await agent.cleanup()

@pytest.mark.asyncio
async def test_time_tool():
    """Test get_current_time tool via MCP"""
    agent = AvicennaAgent()
    await agent.initialize()
    
    response = await agent.send_message("what time is it?")
    assert "day" in response.lower() or ":" in response
    
    await agent.cleanup()

@pytest.mark.asyncio
async def test_calculator_tool():
    """Test calculate tool via MCP"""
    agent = AvicennaAgent()
    await agent.initialize()
    
    response = await agent.send_message("calculate 2 + 2")
    assert "4" in response
    
    await agent.cleanup()

@pytest.mark.asyncio
async def test_clear_history():
    """Test clearing conversation history"""
    agent = AvicennaAgent()
    await agent.initialize()
    
    await agent.send_message("test message")
    await agent.clear_history()
    # If no exception, test passes
    
    await agent.cleanup()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Run tests:**
```bash
pip install pytest pytest-asyncio
pytest tests/test_mcp_migration.py -v
```

---

## Phase 8: Documentation and Cleanup

**Goal:** Document changes and clean up old code  
**Duration:** 30 minutes  
**Risk:** Low

### Step 8.1: Update README.md

Add MCP section to README:

```markdown
## Architecture

Avicenna uses the **Model Context Protocol (MCP)** for tool integration. Tools run as independent servers that communicate via stdio.

### Tool Configuration

Configure MCP servers in `~/.avicenna/mcp_config.json`:

\`\`\`json
{
  "mcp_servers": [
    {
      "name": "basic",
      "script": "source/tools/basic_server.py",
      "enabled": true,
      "description": "Basic tools: time, calculator"
    }
  ]
}
\`\`\`

### Adding New Tools

1. Create MCP server script using FastMCP
2. Add server to MCP configuration
3. Restart Avicenna

See `MCP_MIGRATION_IMPLEMENTATION_PLAN.md` for details.
```

### Step 8.2: Clean Up Old Code

```bash
# Remove backup file
rm source/avicenna/providers/gemini_native.py.bak

# Remove old basic tools if no longer needed
# (Keep the classes for now in case they're referenced elsewhere)
# git rm source/tools/basic.py  # Only if completely unused
```

### Step 8.3: Update requirements.txt

Ensure MCP is listed:

```txt
google-genai>=0.3.0
python-dotenv>=1.0.0
typer>=0.9.0
rich>=13.0.0
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
mcp>=1.0.0
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

---

## Rollback Plan

If migration fails, revert to native implementation:

```bash
# Restore from backup branch
git checkout pre-mcp-migration

# Or restore specific files
git checkout HEAD~1 source/avicenna/main.py
git checkout HEAD~1 source/avicenna/core.py
git checkout HEAD~1 source/avicenna/providers/gemini.py

# Remove MCP files
rm source/tools/*_server.py
rm source/avicenna/mcp_client.py
rm source/avicenna/mcp_config_schema.py
```

---

## Post-Migration Validation

### Checklist

- [ ] All existing functionality works
- [ ] Performance is acceptable (< 10% regression)
- [ ] Error messages are helpful
- [ ] Documentation is updated
- [ ] Tests pass
- [ ] Configuration file is created on first run
- [ ] MCP servers start and stop cleanly
- [ ] No zombie processes left behind
- [ ] Logging is comprehensive
- [ ] User experience is unchanged

---

## Timeline Summary

| Phase | Duration | Risk Level |
|-------|----------|------------|
| 1. Configuration Infrastructure | 30 min | Low |
| 2. MCP Server Implementation | 1.5 hrs | Low |
| 3. MCP Client Implementation | 2 hrs | High |
| 4. GeminiProvider Refactoring | 2 hrs | High |
| 5. Core Agent Refactoring | 1 hr | Medium |
| 6. CLI Entry Point Refactoring | 1 hr | Medium |
| 7. Testing and Validation | 1 hr | Medium |
| 8. Documentation and Cleanup | 30 min | Low |
| **Total** | **~8 hours** | **Medium** |

---

## Success Criteria

### Functional Requirements
✅ Agent starts and connects to MCP servers  
✅ All tools work via MCP protocol  
✅ Email workflow (draft → confirm → send) preserved  
✅ Configuration file created automatically  
✅ Graceful error handling for server failures

### Non-Functional Requirements
✅ Startup time < 3 seconds  
✅ Tool execution latency < 500ms  
✅ Clean shutdown with no zombie processes  
✅ Helpful error messages  
✅ Comprehensive logging

### Documentation Requirements
✅ Architecture decisions documented  
✅ User guide updated  
✅ Developer guide for adding tools  
✅ Troubleshooting section

---

## Next Steps After Migration

1. **Performance Optimization**
   - Profile MCP communication overhead
   - Optimize schema conversion
   - Consider connection pooling

2. **Tool Ecosystem Expansion**
   - Web search MCP server
   - File system operations
   - Calendar integration

3. **Advanced Features**
   - Tool health monitoring
   - Automatic server restart
   - Remote MCP server support (SSE)

4. **Community Integration**
   - Publish tools to MCP marketplace
   - Accept community-contributed servers
   - Create tool template generator

---

## Conclusion

This implementation plan provides a systematic, step-by-step approach to migrating Avicenna from native tool calling to the MCP architecture. Each phase builds on the previous, with clear validation points and rollback options.

**Estimated completion:** 1-2 days for experienced developer

**Key principle:** Preserve user experience while modernizing architecture.