import google.generativeai as genai
from avicenna.config import Config

class AvicennaClient:
    """Client for interacting with Google Gemini."""

    def __init__(self):
        Config.validate()
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        # Using gemini-1.5-flash for speed and efficiency
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.chat = self.model.start_chat(history=[])

    def send_message(self, message: str) -> str:
        """
        Send a message to the model and get the response.
        
        Args:
            message: The user's input message.
            
        Returns:
            The model's text response.
        """
        try:
            response = self.chat.send_message(message)
            return response.text
        except Exception as e:
            return f"Error communicating with Gemini: {str(e)}"
