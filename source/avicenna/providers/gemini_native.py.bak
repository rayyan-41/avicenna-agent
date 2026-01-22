import logging
import time
from typing import Optional, Dict, Any, Callable, List
from google import genai
from google.genai import types
from . import LLMProvider
# Import the new tool
from ...tools.gmail import GmailTool

# Configure logging
logger = logging.getLogger(__name__)

class GeminiProvider(LLMProvider):
    """
    Modern implementation using the new 'google-genai' SDK (2025 Standard).
    """
    
    MAX_HISTORY_MESSAGES = 50  # Prevent unbounded memory growth
    
    def __init__(self, api_key: str, model_name: str, system_instruction: str, tools=None) -> None:
        # The new SDK client
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        # 1. Initialize Tools
        # Extract actual functions from Tool objects for Gemini SDK
        tool_functions = []
        self.tool_map = {}
        
        # Process basic tools (Tool objects)
        for tool in (tools or []):
            if hasattr(tool, 'func') and hasattr(tool, 'name'):
                # It's a Tool object - extract the function
                func = tool.func
                tool_functions.append(func)
                self.tool_map[tool.name] = func
        
        # Add Gmail tools
        try:
            self.gmail = GmailTool()
            # Add both draft and send as raw functions
            tool_functions.append(self.gmail.draft_email)
            tool_functions.append(self.gmail.send_email)
            self.tool_map['draft_email'] = self.gmail.draft_email
            self.tool_map['send_email'] = self.gmail.send_email
        except Exception as e:
            print(f"⚠️ Warning: Gmail tool failed to load: {e}")

        # 2. Configure Chat with Tools
        # Pass the actual Python functions to Gemini
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            tools=tool_functions,  # Pass raw functions
            # Disable automatic function calling so we can handle it manually
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        )
        
        # Initialize chat history
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )

    def send_message(self, message: str, timeout: int = 30, max_retries: int = 3) -> str:
        """
        Send a message to Gemini with retry logic and timeout handling.
        
        Args:
            message: The user's input message
            timeout: Maximum time to wait for response (seconds)
            max_retries: Maximum number of retry attempts for transient errors
            
        Returns:
            The model's response text or error message
        """
        # Input validation
        if not message or not message.strip():
            return "⚠️ Error: Empty message received. Please provide a valid input."
        
        if len(message) > 100000:  # 100K character limit
            return "⚠️ Error: Message too long. Please limit input to 100,000 characters."
        
        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                # New SDK call format with timeout simulation
                start_time = time.time()
                response = self.chat.send_message(message)
                
                # Check if we exceeded timeout (basic check)
                if time.time() - start_time > timeout:
                    logger.warning(f"Request took {time.time() - start_time:.2f}s, exceeding timeout of {timeout}s")
                
                # Check if response was blocked by safety filters
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    
                    # Check finish reason for blocks
                    if hasattr(candidate, 'finish_reason'):
                        finish_reason = str(candidate.finish_reason)
                        if 'SAFETY' in finish_reason:
                            logger.warning(f"Response blocked by safety filters: {finish_reason}")
                            return "⚠️ Response blocked by safety filters. Please rephrase your message."
                        elif 'RECITATION' in finish_reason:
                            logger.warning(f"Response blocked due to recitation: {finish_reason}")
                            return "⚠️ Response blocked due to recitation concerns. Please try a different query."
                    
                    # Check for function calls
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            # Check for function call
                            if hasattr(part, 'function_call') and part.function_call:
                                function_name = part.function_call.name
                                function_args = dict(part.function_call.args)
                                
                                logger.info(f"Function call requested: {function_name}")
                                
                                # Execute the function manually
                                if function_name in self.tool_map:
                                    try:
                                        result = self.tool_map[function_name](**function_args)
                                    except TypeError as e:
                                        logger.error(f"Invalid arguments for {function_name}: {e}")
                                        return f"⚠️ Error: Invalid arguments for function '{function_name}'"
                                    except Exception as e:
                                        logger.error(f"Function execution error: {e}")
                                        return f"⚠️ Error executing function '{function_name}': {str(e)}"
                                    
                                    # For draft_email, return the result directly (it's already formatted for display)
                                    if function_name == 'draft_email':
                                        return result
                                    
                                    # For other functions, send the result back to the model
                                    function_response = self.chat.send_message(
                                        types.Part.from_function_response(
                                            name=function_name,
                                            response={"result": result}
                                        )
                                    )
                                    
                                    # Return the model's response after processing the function result
                                    if function_response.text:
                                        return function_response.text
                                    else:
                                        return str(result)
                                else:
                                    logger.error(f"Unknown function requested: {function_name}")
                                    return f"⚠️ Error: Unknown function '{function_name}'"
                
                # Handle text response
                if response.text:
                    return response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    # Try to extract content from candidates
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and candidate.content.parts:
                        parts_text = []
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                parts_text.append(part.text)
                        if parts_text:
                            return ''.join(parts_text)
                
                # Empty response handling
                logger.warning(f"Empty response received from model")
                return "AI model provides no response. Reconsider prompt."
                
            except ConnectionError as e:
                logger.error(f"Connection error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                return f"⚠️ Connection Error: Unable to reach Gemini API. Please check your internet connection."
                
            except TimeoutError as e:
                logger.error(f"Timeout error: {e}")
                return f"⚠️ Timeout Error: Request took too long. Please try again."
                
            except ValueError as e:
                error_msg = str(e)
                logger.error(f"Value error: {error_msg}")
                if "429" in error_msg or "quota" in error_msg.lower():
                    return "⚠️ Error: Gemini Quota Exceeded. Switch models in .env or check Google AI Studio."
                return f"⚠️ Error: {error_msg}"
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Unexpected error: {type(e).__name__} - {error_msg}")
                
                # Check for specific error types in message
                if "429" in error_msg or "Quota" in error_msg or "quota" in error_msg:
                    return "⚠️ Error: Gemini Quota Exceeded. Switch models in .env or check Google AI Studio."
                elif "401" in error_msg or "authentication" in error_msg.lower():
                    return "⚠️ Error: Authentication failed. Please check your API key in .env file."
                elif "403" in error_msg or "permission" in error_msg.lower():
                    return "⚠️ Error: Permission denied. Please verify API key permissions."
                elif "503" in error_msg or "unavailable" in error_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.info(f"Service unavailable. Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
                    return "⚠️ Error: Gemini service temporarily unavailable. Please try again later."
                
                return f"⚠️ Error communicating with Gemini: {error_msg}"
        
        return "⚠️ Error: Maximum retry attempts exceeded. Please try again later."

    def clear_history(self):
        # Re-initialize the chat object to clear memory
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )