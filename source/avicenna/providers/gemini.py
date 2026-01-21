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
            # Register the function implementation for the model
            self.tools.append(self.gmail.send_email)
        except Exception as e:
            print(f"⚠️ Warning: Gmail tool failed to load: {e}")

        # 2. Configure Chat with Tools
        # We pass the tools list to the config so Gemini knows they exist.
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            tools=self.tools,  # <--- The Critical Link
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=False, 
                maximum_remote_calls=3
            )
        )
        
        # Initialize chat history
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )

    def send_message(self, message: str) -> str:
        try:
            # New SDK call format
            response = self.chat.send_message(message)
            
            # If the model used a tool, the SDK executes it automatically
            # and returns the final text response here.
            if response.text:
                return response.text
            else:
                # Fallback if response is purely functional (rare with auto-execution)
                return "✅ Action completed."
                
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