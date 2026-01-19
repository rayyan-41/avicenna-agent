import typer
from rich.console import Console
from rich.text import Text
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from typing import Optional

from .core import AvicennaAgent
from .config import Config

app = typer.Typer()
console = Console()

# --- Aesthetic Constants ---
# Pure Neon Green Palette
NEON_GREEN = "#00ff00"     # Main Text / Bright
DARK_GREEN = "#005500"     # Dimmed Text / Backgrounds
SHADOW_GREEN = "#003300"   # The deep shadow color

# Custom 3D "Shadow" Font for AVICENNA
# We use full blocks (█) for the face and mixed blocks (▓▒) for the shadow depth.
AVICENNA_ART = [
    # Layer 1
    "  █████╗ ██╗   ██╗██╗ ██████╗███████╗███╗   ██╗███╗   ██╗ █████╗ ",
    " ██╔══██╗██║   ██║██║██╔════╝██╔════╝████╗  ██║████╗  ██║██╔══██╗",
    " ███████║██║   ██║██║██║     █████╗  ██╔██╗ ██║██╔██╗ ██║███████║",
    " ██╔══██║╚██╗ ██╔╝██║██║     ██╔══╝  ██║╚██╗██║██║╚██╗██║██╔══██║",
    " ██║  ██║ ╚████╔╝ ██║╚██████╗███████╗██║ ╚████║██║ ╚████║██║  ██║",
    " ╚═╝  ╚═╝  ╚═══╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═══╝╚═╝  ╚═╝"
]

TIPS = [
    "Ask questions, edit files, or run commands.",
    "Be specific for the best results.",
    "/help for more information."
]

def print_header(model_name: str):
    """Renders the Neon Green Header with Shadow Effect"""
    console.clear()
    
    # 1. Render the 3D Logo
    # We print it in solid Neon Green to get that 'monitor glow' effect
    logo_text = Text("\n".join(AVICENNA_ART), style=f"bold {NEON_GREEN}")
    console.print(logo_text)
    console.print()

    # 2. Render Tips in Monochromatic Style
    console.print(f"[bold {NEON_GREEN}]> SYSTEM ONLINE[/bold {NEON_GREEN}]")
    console.print(f"[{DARK_GREEN}]Model: {model_name}[/{DARK_GREEN}]")
    console.print()
    
    console.print(f"[{DARK_GREEN}]Tips for getting started:[/{DARK_GREEN}]")
    for i, tip in enumerate(TIPS, 1):
        console.print(f"[{DARK_GREEN}] {i}. {tip}[/{DARK_GREEN}]")
    console.print()

@app.command()
def chat(
    model: Optional[str] = typer.Option(None, help="Override the model"),
):
    """Start the Avicenna Interactive Session"""
    
    # 1. Render UI
    current_model = model or Config.MODEL_NAME
    print_header(current_model)
    
    # 2. Initialize Agent
    try:
        agent = AvicennaAgent()
    except Exception as e:
        console.print(f"[bold red]SYSTEM FAILURE:[/bold red] {e}")
        raise typer.Exit(1)

    # 3. Input Loop
    while True:
        try:
            # Monochromatic Prompt
            # We use a custom symbol and color
            user_input = Prompt.ask(f"[bold {NEON_GREEN}]>[/bold {NEON_GREEN}]")
            
            # --- Commands ---
            if user_input.lower() in ["exit", "quit", "/bye"]:
                console.print(f"[{DARK_GREEN}]Terminating session...[/]")
                break
                
            if user_input.lower() in ["clear", "cls"]:
                print_header(current_model)
                continue
                
            if not user_input.strip():
                continue

            # --- Processing Animation ---
            # We use a simple text spinner to match the minimal aesthetic
            with console.status(f"[bold {NEON_GREEN}]PROCESSING...[/]", spinner="square", spinner_style=NEON_GREEN):
                response = agent.send_message(user_input)
            
            # --- Output ---
            console.print()
            console.print(f"[bold {NEON_GREEN}]AVICENNA:[/bold {NEON_GREEN}]")
            
            # Render Markdown but force code blocks to align with the green theme if possible
            # (Rich's default markdown theme is usually good, but we can style it)
            md = Markdown(response)
            console.print(md)
            
            # Retro scanline separator
            console.print(f"[{DARK_GREEN}]" + "_" * console.width + "[/{DARK_GREEN}]")
            console.print()
            
        except KeyboardInterrupt:
            console.print(f"\n[{DARK_GREEN}]Session interrupted.[/]")
            break
        except Exception as e:
            console.print(f"[bold red]ERROR:[/bold red] {e}")

if __name__ == "__main__":
    app()