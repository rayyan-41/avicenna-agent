from google import genai
from google.genai import types
from . import LLMProvider

class GeminiProvider(LLMProvider):
    """
    Modern implementation using the new 'google-genai' SDK (2025 Standard).
    """
    
    def __init__(self, api_key: str, model_name: str, system_instruction: str):
        # The new SDK client
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        # Configure the chat config (System Prompt goes here now)
        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7, # Standard creativity
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
            return response.text
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