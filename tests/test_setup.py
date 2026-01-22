import sys
import os

# Ensure we are running from project root
sys.path.append(os.getcwd())

from rich.console import Console

try:
    from source.avicenna.core import AvicennaAgent
except ImportError as e:
    print(f"❌ Import Error: {e}")
    sys.exit(1)

console = Console()

def test_integration():
    console.rule("[bold blue]🧪 Avicenna System Integration Test[/bold blue]")
    
    # 1. Test Configuration Loading
    console.print("\n[bold yellow]Step 1: Initializing Agent...[/bold yellow]")
    try:
        agent = AvicennaAgent() 
        console.print("[green]✅ Configuration loaded & Agent initialized.[/green]")
    except Exception as e:
        console.print(f"[bold red]❌ Initialization Failed:[/bold red] {e}")
        return

    # 2. Test Gemini Connection
    console.print("\n[bold yellow]Step 2: Testing Neural Link (API Call)...[/bold yellow]")
    try:
        user_query = "Hello. Reply with 'OK'."
        console.print(f"[dim]Sending: {user_query}[/dim]")
        
        response = agent.send_message(user_query)
        
        console.print(f"\n[cyan]🤖 Avicenna says:[/cyan]\n{response}")

        # STRICTER CHECK: Fail if we see "Error" or specific error codes
        if "Error" in response or "404" in response or "429" in response:
             console.print("\n[bold red]❌ TEST FAILED: The agent returned an API error.[/bold red]")
        elif response:
            console.print("\n[bold green]✅ SUCCESS: The core system is fully operational.[/bold green]")
        else:
            console.print("[red]❌ Error: Received empty response.[/red]")
            
    except Exception as e:
        console.print(f"[bold red]❌ Connection Failed:[/bold red] {e}")

if __name__ == "__main__":
    test_integration()