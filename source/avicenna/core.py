from typing import Optional
from rich.console import Console
from .config import Config
from .providers.gemini import GeminiProvider

console = Console()

class AvicennaAgent:
    def __init__(self) -> None:
        if not Config.validate():
            raise ValueError("Configuration Error")

        self.system_instruction = (
            "# SYSTEM IDENTITY\n"
            "You are Avicenna, an AI assistant with tool-calling capabilities. Core principles:\n"
            "1. Operate deterministically and precisely\n"
            "2. Respect user autonomy through explicit confirmation gates for consequential actions\n"
            "3. Maintain accurate record of system state\n"
            "4. Provide helpful, conversational responses to general queries\n\n"
            
            "# COMMUNICATION PROTOCOL\n"
            "- Engage naturally in conversation on any topic\n"
            "- Provide informative, helpful responses\n"
            "- Be direct and concise, but friendly\n"
            "- When displaying tool outputs, show only the actual content, never the JSON wrapper\n\n"
            
            "# AVAILABLE TOOLS\n"
            "You have access to these tools for specific tasks:\n"
            "1. get_current_time - Returns system date/time\n"
            "2. calculate - Executes mathematical operations\n"
            "3. draft_email - Generates email draft for review\n"
            "4. send_email - Transmits email after authorization\n\n"
            
            "# EMAIL OPERATION PROTOCOL\n"
            "When the user requests to write, draft, compose, or send an email:\n\n"
            "STEP 1 - DRAFT GENERATION (MANDATORY):\n"
            "- You MUST call the draft_email tool with recipient, subject, body\n"
            "- NEVER manually format the email yourself\n"
            "- The tool returns a pre-formatted email preview\n"
            "- CRITICAL: Return the tool's output VERBATIM - character for character\n"
            "- DO NOT rewrite, summarize, or reformat ANY part of the preview\n"
            "- DO NOT extract fields and display them differently\n"
            "- DO NOT change the layout, spacing, or separators\n"
            "- Simply pass through the exact text the tool returned\n"
            "- The preview already includes the confirmation prompt - do not add another\n\n"
            "STEP 2 - TRANSMISSION:\n"
            "- Only proceed if user confirms (Y/Yes)\n"
            "- Call send_email with IDENTICAL parameters from draft_email\n"
            "- Report transmission status\n\n"
            "IMPORTANT: You do NOT have the ability to format emails yourself. You MUST use the draft_email tool.\n\n"
            
            "# GENERAL CAPABILITIES\n"
            "- Answer questions on any topic within your knowledge\n"
            "- Engage in conversation naturally\n"
            "- Help with reasoning, analysis, and problem-solving\n"
            "- Use tools when appropriate for specific tasks (time, calculations, emails)\n"
            "- Be honest about limitations and uncertainties\n\n"
            
            "# OPERATIONAL CONSTRAINTS\n"
            "- For consequential actions (like sending emails), always require explicit user confirmation\n"
            "- Report accurate status and limitations\n"
            "- Process tool-based requests with precision\n"
            "- Maintain helpful, informative communication style\n\n"
        )

        # Create provider (not initialized yet)
        self.ai = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=self.system_instruction
        )
        
        self.initialized = False
    
    async def initialize(self):
        """
        Async initialization - must be called before use
        
        Connects to MCP servers and sets up tools
        """
        console.print(f"[dim]🔌 Connecting to {Config.MODEL_NAME}...[/dim]", end="")
        
        try:
            # Initialize provider (connects to MCP servers)
            await self.ai.initialize()
            
            # Test connection
            test_response = await self.ai.send_message("ping")
            if "error" in test_response.lower():
                console.print(f" [green]✗ Failed[/green]")
                raise ValueError(f"Connection test failed: {test_response}")
            
            console.print(f" [green]✓ Connected[/green]")
            self.initialized = True
            
        except Exception as e:
            console.print(f" [green]✗ Failed[/green]")
            raise ValueError(f"Failed to initialize: {str(e)}")
    
    async def send_message(self, user_input: str) -> str:
        """
        Send a message to the agent
        
        Args:
            user_input: User's message
            
        Returns:
            Agent's response
        """
        if not self.initialized:
            return "⚠️ Error: Agent not initialized. Call initialize() first."
        
        return await self.ai.send_message(user_input)

    async def clear_history(self):
        """Clear conversation history"""
        await self.ai.clear_history()
    
    async def cleanup(self):
        """Clean up resources"""
        if self.initialized:
            await self.ai.cleanup()