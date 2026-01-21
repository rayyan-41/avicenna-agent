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
    "Version 0.2",
    "Type 'exit' or 'quit' to end the session",
    "Latest features: Gmail integration!",
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
):
    current_model = model or Config.MODEL_NAME
    print_header(current_model)
    
    try:
        agent = AvicennaAgent()
    except Exception as e:
        # SAFETY FIX 1: Escape the error message
        console.print(f"[bold red]SYSTEM FAILURE:[/bold red] {escape(str(e))}")
        raise typer.Exit(1)

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
                response = agent.send_message(user_input)
            
            console.print()
            console.print(f"[bold {NEON_GREEN}]AVICENNA:[/bold {NEON_GREEN}]")
            
            # SAFETY FIX: Wrap Markdown in try-except to catch markup errors
            # If Markdown parsing fails, fall back to escaped plain text
            try:
                console.print(Markdown(response))
            except Exception as markup_error:
                # Fallback: print as escaped text if Markdown fails
                console.print(escape(response))
            
            # SAFETY FIX 2: Use [/] to close the color tag, NOT [/{DARK_GREEN}]
            console.print(f"[{DARK_GREEN}]" + "_" * console.width + "[/]") 
            console.print()
            
        except KeyboardInterrupt:
            console.print(f"\n[{DARK_GREEN}]Session interrupted.[/]")
            break
        except Exception as e:
            # SAFETY FIX 3: Escape the error message here too
            console.print(f"[bold red]ERROR:[/bold red] {escape(str(e))}")

if __name__ == "__main__":
    app()