from google import genai
from google.genai import types
from . import LLMProvider

class GeminiProvider(LLMProvider):
    """
    Modern implementation using the new 'google-genai' SDK (2025 Standard).
    Now with Tool/Function Calling support.
    """
    
    def __init__(self, api_key: str, model_name: str, system_instruction: str, tools: list = None):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        # 1. Convert our custom Tool objects into raw functions for the SDK
        # The Google SDK inspects the functions directly to build the schema.
        self.sdk_tools = [t.func for t in tools] if tools else None

        # 2. Configure the chat with tools and auto-function calling
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            tools=self.sdk_tools, 
            automatic_function_calling=dict(disable=False) # <--- The magic setting
        )
        
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )

    def send_message(self, message: str) -> str:
        try:
            # automatic_function_calling handles the loop:
            # Model asks -> SDK runs function -> SDK sends result -> Model answers
            response = self.chat.send_message(message)
            
            if response.text:
                return response.text
            
            return "[Avicenna executed a task silently]"
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Quota" in error_msg:
                return "⚠️ Error: Gemini Quota Exceeded. Switch models in .env."
            return f"Error communicating with Gemini: {error_msg}"

    def clear_history(self):
        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )