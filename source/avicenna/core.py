from rich.console import Console
from .config import Config
from .providers.gemini import GeminiProvider
from ..tools.basic import BASIC_TOOLS

console = Console()

class AvicennaAgent:
    def __init__(self):
        if not Config.validate():
            raise ValueError("Configuration Error")

        self.system_instruction = (
            "You are Avicenna, an advanced AI assistant. "
            "You are helpful, precise, and expert in coding.\n\n"
            "IMPORTANT: You have access to ONLY the following tools:\n"
            "1. get_current_time - Get the current date and time\n"
            "2. calculate - Perform mathematical calculations\n"
            "3. send_email - Send emails via Gmail\n\n"
            "DO NOT claim to have access to any other tools or services. "
            "If asked about tools you don't have, be honest and say you don't have access to them."
        )

        # FACTORY PATTERN:
        # Here we decide which brain to load based on Config.
        # Later, we can add: if Config.PROVIDER == "claude": ...
        
        console.print(f"[dim]🔌 Connecting to {Config.MODEL_NAME}...[/dim]", end="")
        
        self.ai = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=self.system_instruction,
            tools=BASIC_TOOLS
        )
        
        # Test the connection with a simple ping
        try:
            test_response = self.ai.send_message("ping")
            if "error" in test_response.lower() or "503" in test_response or "429" in test_response:
                console.print(f" [red]✗ Failed[/red]")
                raise ValueError(f"Connection test failed: {test_response}")
            console.print(f" [green]✓ Connected[/green]")
        except Exception as e:
            console.print(f" [red]✗ Failed[/red]")
            raise ValueError(f"Failed to connect to {Config.MODEL_NAME}: {str(e)}")
        
    def send_message(self, user_input: str) -> str:
        # We delegate the work to the loaded provider
        return self.ai.send_message(user_input)

    def clear_history(self):
        self.ai.clear_history()