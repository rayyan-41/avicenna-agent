import google.generativeai as genai
from . import LLMProvider

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model_name: str, system_instruction: str):
        # Configure API
        genai.configure(api_key=api_key)
        
        # Initialize Model
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction
        )
        self.chat = self.model.start_chat(history=[])

    def send_message(self, message: str, history: list = None) -> str:
        try:
            response = self.chat.send_message(message)
            return response.text
        except Exception as e:
            # Check for that specific 429 quota error
            if "429" in str(e):
                return "⚠️ Error: Gemini Quota Exceeded. Please try again later or switch models."
            return f"Error: {e}"

    def clear_history(self):
        self.chat = self.model.start_chat(history=[])