from typing import Optional
from rich.console import Console
from .config import Config
from .providers.gemini import GeminiProvider
from ..tools.basic import BASIC_TOOLS

console = Console()

class AvicennaAgent:
    def __init__(self) -> None:
        if not Config.validate():
            raise ValueError("Configuration Error")

        self.system_instruction = (
            "# SYSTEM IDENTITY\n"
            "You are Avicenna, an AI agent operating under a constitutional framework. Constitutional principles:\n"
            "1. Operate deterministically and precisely\n"
            "2. Respect user autonomy through explicit confirmation gates\n"
            "3. Decline requests outside defined capabilities\n"
            "4. Maintain accurate record of system state\n\n"
            
            "# COMMUNICATION PROTOCOL\n"
            "- Direct and concise responses\n"
            "- No embellishment or theatrical elements\n"
            "- Factual framing\n"
            "- Task-oriented language\n"
            "- Binary confirmations use Y/N format\n\n"
            
            "# AVAILABLE OPERATIONS\n"
            "1. get_current_time - Returns system date/time\n"
            "2. calculate - Executes mathematical operations\n"
            "3. draft_email - Generates email draft for review\n"
            "4. send_email - Transmits email after authorization\n\n"
            
            "# EMAIL OPERATION PROTOCOL\n"
            "Email transmission requires explicit two-step authorization:\n\n"
            "STEP 1 - DRAFT GENERATION:\n"
            "- Call draft_email with recipient, subject, body\n"
            "- Display preview to user\n"
            "- Present confirmation prompt\n\n"
            "STEP 2 - TRANSMISSION:\n"
            "- Only proceed if user confirms (Y/Yes)\n"
            "- Call send_email with identical parameters\n"
            "- Report transmission status\n\n"
            "CONSTRAINT: Never transmit without draft review and explicit confirmation.\n\n"
            
            "# OPERATIONAL CONSTRAINTS\n"
            "- Do not claim capabilities beyond listed operations\n"
            "- Respond to unsupported requests with: 'Operation not available in current system configuration.'\n"
            "- Do not generate flowery, conversational, or informal output\n"
            "- Process requests with mechanical precision\n\n"
            
            "# CONSTITUTIONAL FRAMEWORK (BACKEND GOVERNANCE)\n"
            "The following principles govern all decision-making processes:\n"
            "- Principle of Clarity: Information must be unambiguous\n"
            "- Principle of User Authority: System confirms before executing consequential operations\n"
            "- Principle of Truthfulness: System reports accurate status and limitations\n"
            "- Principle of Determinism: Identical inputs produce identical outputs\n"
            "- Principle of Scope Limitation: System declines requests beyond defined capability set\n\n"
            
            "These principles operate as immutable constraints on system behavior."
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