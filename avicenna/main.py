import asyncio
import logging
import typer
from rich.console import Console
from rich.text import Text
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.markup import escape  
from typing import Optional

from .core import AvicennaAgent
from .config import Config

app = typer.Typer()
console = Console()

# Configure logging - only log to file by default, not console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('avicenna.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# --- Aesthetic Constants ---
NEON_GREEN = "#00ff00"
DARK_GREEN = "#005500"
AVICENNA_ART = [
    "  █████╗ ██╗   ██╗██╗ ██████╗███████╗███╗   ██╗███╗   ██╗ █████╗ ",
    " ██╔══██╗██║   ██║██║██╔════╝██╔════╝████╗  ██║████╗  ██║██╔══██╗",
    " ███████║██║   ██║██║██║     █████╗  ██╔██╗ ██║██╔██╗ ██║███████║",
    " ██╔══██║╚██╗ ██╔╝██║██║     ██╔══╝  ██║╚██╗██║██║╚██╗██║██╔══██║",
    " ██║  ██║ ╚████╔╝ ██║╚██████╗███████╗██║ ╚████║██║ ╚████║██║  ██║",
    " ╚═╝  ╚═╝  ╚═══╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═══╝╚═╝  ╚═╝"
]

TIPS = [
    "Version 2.0 - MCP Ecosystem",
    "Type 'exit' or 'quit' to end the session",
    "New: Node.js MCP server support!",
]

def print_header(model_name: str):
    console.clear()
    logo_text = Text("\n".join(AVICENNA_ART), style=f"bold {NEON_GREEN}")
    console.print(logo_text)
    console.print()
    console.print(f"[bold {NEON_GREEN}]> SYSTEM ONLINE[/bold {NEON_GREEN}]")
    console.print(f"[{DARK_GREEN}]Model: {model_name}[/]") 
    console.print()
    console.print(f"[{DARK_GREEN}]Meta:[/]")
    for tip in TIPS:
        console.print(f"[{DARK_GREEN}] {tip}[/]")
    console.print()

@app.command()
def chat(
    model: Optional[str] = typer.Option(None, help="Override the model"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging to console"),
):
    """Start Avicenna chat session"""
    if debug:
        # Add console handler for debug mode
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter('%(name)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(console_handler)
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Debug mode enabled - logging to console and file")
    asyncio.run(async_chat(model))

async def async_chat(model: Optional[str] = None):
    """Async chat implementation with MCP support"""
    current_model = model or Config.MODEL_NAME
    print_header(current_model)
    
    try:
        agent = AvicennaAgent()
        # Initialize MCP connections
        await agent.initialize()
    except Exception as e:
        console.print(f"[bold {NEON_GREEN}]SYSTEM FAILURE:[/bold {NEON_GREEN}] {escape(str(e))}")
        raise typer.Exit(1)

    try:
        while True:
            try:
                user_input = Prompt.ask(f"[bold {NEON_GREEN}]>[/bold {NEON_GREEN}]")
                
                if user_input.lower() in ["exit", "quit", "/bye"]:
                    console.print(f"[{DARK_GREEN}]The intellect is only acquired in order to know things unknown...[/]")
                    break
                if user_input.lower() in ["clear", "cls"]:
                    print_header(current_model)
                    continue
                if not user_input.strip():
                    continue

                with console.status(f"[bold {NEON_GREEN}]PROCESSING...[/]", spinner="dots", spinner_style=NEON_GREEN):
                    response = await agent.send_message(user_input)
                
                console.print()
                console.print(f"[bold {NEON_GREEN}]AVICENNA:[/bold {NEON_GREEN}]")
                
                try:
                    # Render markdown with green text
                    md = Markdown(response)
                    md.style = NEON_GREEN
                    console.print(md, style=NEON_GREEN)
                except Exception as markup_error:
                    # Fallback: print as escaped text if Markdown fails
                    console.print(f"[{NEON_GREEN}]{escape(response)}[/]")
                
                console.print(f"[{DARK_GREEN}]" + "_" * console.width + "[/]") 
                console.print()
                
            except KeyboardInterrupt:
                console.print(f"\n[{NEON_GREEN}]Session interrupted.[/]")
                break
            except Exception as e:
                console.print(f"[bold {NEON_GREEN}]ERROR:[/bold {NEON_GREEN}] {escape(str(e))}")
    finally:
        # Clean up MCP connections
        await agent.cleanup()

if __name__ == "__main__":
    app()