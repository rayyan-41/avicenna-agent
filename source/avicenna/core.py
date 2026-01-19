import google.generativeai as genai
from rich.console import Console
from .config import Config

console = Console()

class AvicennaAgent:
    """
    The main AI Agent class.
    Wraps the Gemini model and manages conversation state.
    """
    
    def __init__(self):
        """
        Initialize the agent.
        1. Validates configuration.
        2. Configures the Gemini API.
        3. Starts a chat session with history.
        """
        # Fail fast if config is bad
        if not Config.validate():
            raise ValueError("Invalid Configuration. Missing API Key.")
            
        # Configure the SDK with the key from our Config class
        genai.configure(api_key=Config.API_KEY)
        
        # Define the AI's persona
        # This 'System Instruction' tells Gemini how to behave before the chat starts.
        self.system_instruction = (
            "You are Avicenna, an advanced AI assistant running in a terminal. "
            "You are helpful, precise, and expert in software engineering. "
            "Your responses should be formatted for a CLI environment (concise, using Markdown). "
            "When writing code, provide production-ready examples."
        )
        
        # Initialize the specific model (Flash or Pro)
        self.model = genai.GenerativeModel(
            model_name=Config.MODEL_NAME,
            system_instruction=self.system_instruction
        )
        
        # Start the Chat Session
        # 'history=[]' initializes an empty memory.
        # As we send messages, this object automatically stores the context.
        self.chat_session = self.model.start_chat(history=[])
        
    def send_message(self, user_input: str) -> str:
        """
        Sends a user message to Gemini and retrieves the text response.
        Wraps the call in try/except to prevent the app from crashing on network errors.
        """
        try:
            # The SDK handles the API call and updating history automatically
            response = self.chat_session.send_message(user_input)
            return response.text
            
        except Exception as e:
            # Log the error to the console with red formatting
            console.print(f"[bold red]❌ Connection Error:[/bold red] {e}")
            return "I apologize, but I encountered an error connecting to my neural core."

    def clear_history(self):
        """
        Wipes the agent's memory.
        Useful if the conversation gets too long or off-topic.
        """
        self.chat_session = self.model.start_chat(history=[])
        console.print("[dim italic]Context memory cleared.[/dim italic]")