from google import genai
from google.genai import types
from . import LLMProvider
# Import the new tool
from ...tools.gmail import GmailTool

class GeminiProvider(LLMProvider):
    """
    Modern implementation using the new 'google-genai' SDK (2025 Standard).
    """
    
    def __init__(self, api_key: str, model_name: str, system_instruction: str, tools=None):
        # The new SDK client
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        # 1. Initialize Tools
        self.tools = tools or []
        try:
            self.gmail = GmailTool()
            # Register both draft and send functions for the model
            self.tools.append(self.gmail.draft_email)
            self.tools.append(self.gmail.send_email)
        except Exception as e:
            print(f"⚠️ Warning: Gmail tool failed to load: {e}")

        # 2. Configure Chat with Tools
        # We pass the tools list to the config so Gemini knows they exist.
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            tools=self.tools,  # <--- The Critical Link
            # Disable automatic function calling so we can see the results
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        )
        
        # Create a tool map for manual function execution
        self.tool_map = {}
        for tool in self.tools:
            # Handle both Tool objects and raw functions
            if hasattr(tool, 'name'):
                # It's a Tool object
                self.tool_map[tool.name] = tool.func if hasattr(tool, 'func') else tool
            elif hasattr(tool, '__name__'):
                # It's a raw function
                self.tool_map[tool.__name__] = tool
        
        # Initialize chat history
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )

    def send_message(self, message: str) -> str:
        try:
            # New SDK call format
            response = self.chat.send_message(message)
            
            # Check if the model wants to call a function
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and candidate.content.parts:
                    for part in candidate.content.parts:
                        # Check for function call
                        if hasattr(part, 'function_call') and part.function_call:
                            function_name = part.function_call.name
                            function_args = dict(part.function_call.args)
                            
                            # Execute the function manually
                            if function_name in self.tool_map:
                                result = self.tool_map[function_name](**function_args)
                                
                                # Send the function result back to the model
                                function_response = self.chat.send_message(
                                    types.Part.from_function_response(
                                        name=function_name,
                                        response={"result": result}
                                    )
                                )
                                
                                # Return the model's response after processing the function result
                                if function_response.text:
                                    # Include the function result in the response
                                    return f"{result}\n\n{function_response.text}"
                                else:
                                    return result
            
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
            
            # If we still have no text, return a debug message
            return f"⚠️ Empty response received. Response type: {type(response).__name__}"
                
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Quota" in error_msg:
                return "⚠️ Error: Gemini Quota Exceeded. Switch models in .env or check Google AI Studio."
            return f"Error communicating with Gemini: {error_msg}"

    def clear_history(self):
        # Re-initialize the chat object to clear memory
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )