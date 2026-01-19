import typer
import random
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.panel import Panel
from rich.layout import Layout
from typing import Optional

from .core import AvicennaAgent
from .config import Config

app = typer.Typer()
console = Console()

# --- Visual Assets ---

# Custom Block Font for "AVICENNA" (Matches Gemini CLI style)
AVICENNA_ART = [
    "  █████  ██     ██ ██  ██████ ███████ ███    ██ ███    ██  █████  ",
    " ██   ██ ██     ██ ██ ██      ██      ████   ██ ████   ██ ██   ██ ",
    " ███████ ██  █  ██ ██ ██      █████   ██ ██  ██ ██ ██  ██ ███████ ",
    " ██   ██ ██ ███ ██ ██ ██      ██      ██  ██ ██ ██  ██ ██ ██   ██ ",
    " ██   ██  ███ ███  ██  ██████ ███████ ██   ████ ██   ████ ██   ██ "
]

TIPS = [
    "Ask questions, edit files, or run commands.",
    "Be specific for the best results.",
    "/help for more information."
]

def get_gradient_text(text_lines):
    """Applies a Blue -> Green gradient to the text lines."""
    # Colors: Ice Blue (#89CFF0) -> Mint Green (#98FF98)
    gradient_start = (137, 207, 240) 
    gradient_end = (152, 255, 152)
    
    output = Text()
    
    for i, line in enumerate(text_lines):
        # Calculate fade for this line (vertical gradient effect)
        # or we can do horizontal. Let's do a simple solid color per char for now
        # to ensure it looks crisp, or a distinct cyan-to-green per line.
        
        # Simple approach: Cyan for top, Green for bottom
        if i < 2:
            color = "#5bb7f5" # Gemini Blue
        elif i < 3:
            color = "#6ae4d7" # Mid Teal
        else:
            color = "#7dffb8" # Gemini Green
            
        output.append(line + "\n", style=f"bold {color}")
    return output

def print_header(model_name):
    console.clear()
    
    # 1. Load the Face (if it exists)
    face_path = Path(__file__).parent / "face.ans"
    face_art = Text("")
    if face_path.exists():
        with open(face_path, "r", encoding="utf-8") as f:
            # We print raw ANSI
            face_content = f.read()
            # Rich sometimes fights with raw ANSI, so we print it directly first
            pass
    
    # 2. Render the Logo Text
    logo = get_gradient_text(AVICENNA_ART)
    
    # 3. Layout: We want Face + Logo side by side? 
    # The screenshot shows just Logo. Let's put your Face ABOVE the logo 
    # or to the left. Let's try Face Left, Logo Right.
    
    # Since combining raw ANSI (face) and Rich Text (logo) in columns is hard,
    # We will print the Face first (centered), then the Logo, then the tips.
    
    # Print Face (Raw ANSI)
    if face_path.exists():
        print(face_content) 
    
    # Print Logo
    console.print(logo)
    console.print()

    # Print Tips
    console.print("[dim]Tips for getting started:[/dim]")
    for i, tip in enumerate(TIPS, 1):
        console.print(f"[dim]{i}. {tip}[/dim]")
    console.print()

@app.command()
def chat(
    model: Optional[str] = typer.Option(None, help="Override the model"),
):
    """Start the Avicenna Interactive Session"""
    
    # 1. Render UI
    print_header(model or Config.MODEL_NAME)
    
    # 2. Initialize Agent
    try:
        agent = AvicennaAgent()
    except Exception as e:
        console.print(f"[bold red]System Error:[/bold red] {e}")
        raise typer.Exit(1)

    # 3. Input Loop
    while True:
        try:
            # The classic Blue ">" Prompt
            # We use a custom prompt string
            prompt_text = Text("\n> ", style="bold #5bb7f5")
            user_input = console.input(prompt_text)
            
            # Commands
            if user_input.lower() in ["exit", "quit", "/bye"]:
                break
            if user_input.lower() in ["clear", "cls"]:
                print_header(model or Config.MODEL_NAME)
                continue
            if not user_input.strip():
                continue

            # Processing
            with console.status("[bold green]Generating...[/]", spinner="dots"):
                response = agent.send_message(user_input)
            
            # Output
            console.print(Markdown(response))
            
        except KeyboardInterrupt:
            console.print("\n[dim]Exiting...[/dim]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

if __name__ == "__main__":
    app()