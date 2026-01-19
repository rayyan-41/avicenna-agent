import sys
from rich.console import Console

# Import our new core class
# If this fails, it means the folder structure or __init__.py files are missing
try:
    from source.avicenna.core import AvicennaAgent
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("Ensure you are running this from the root 'avicenna-agent' directory.")
    sys.exit(1)

console = Console()

def test_integration():
    console.rule("[bold blue]🧪 Avicenna System Integration Test[/bold blue]")
    
    # 1. Test Configuration Loading
    console.print("\n[bold yellow]Step 1: Initializing Agent...[/bold yellow]")
    try:
        # This triggers Config.validate() automatically
        agent = AvicennaAgent() 
        console.print("[green]✅ Configuration loaded & Agent initialized.[/green]")
    except Exception as e:
        console.print(f"[bold red]❌ Initialization Failed:[/bold red] {e}")
        return

    # 2. Test Gemini Connection
    console.print("\n[bold yellow]Step 2: Testing Neural Link (API Call)...[/bold yellow]")
    try:
        user_query = "Hello Avicenna. Are you online? Reply with a short confirmation."
        console.print(f"[dim]Sending: {user_query}[/dim]")
        
        response = agent.send_message(user_query)
        
        if response:
            console.print(f"\n[cyan]🤖 Avicenna says:[/cyan]\n{response}")
            console.print("\n[bold green]✅ SUCCESS: The core system is fully operational.[/bold green]")
        else:
            console.print("[red]❌ Error: Received empty response.[/red]")
            
    except Exception as e:
        console.print(f"[bold red]❌ Connection Failed:[/bold red] {e}")

if __name__ == "__main__":
    test_integration()