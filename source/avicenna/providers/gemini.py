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
        logger.info("Connecting to MCP servers...")
        connection_results = await self.mcp_manager.connect_all(mcp_config.servers)
        
        # Report connection status
        for server_name, success in connection_results.items():
            if success:
                logger.info(f"  ✓ {server_name}")
            else:
                logger.warning(f"  ✗ {server_name} (failed)")
        
        # Get tools in Gemini format
        gemini_tools = self.mcp_manager.get_gemini_tools()
        
        logger.info(f"Loaded {len(self.mcp_manager.list_available_tools())} tools from MCP servers")
        
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
                                
                                logger.info(f"Tool call: {function_name}")
                                
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