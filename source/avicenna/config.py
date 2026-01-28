import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from rich.console import Console
from mcp_servers.mcp_config_schema import MCPConfiguration

# Initialize Rich console for pretty error messages
console = Console()

# 1. Resolve the Project Root Directory
# We use Path(__file__) to find *this* file's location, then go up 3 levels:
# src/avicenna/config.py -> src/avicenna -> src -> ROOT
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 2. Load Environment Variables
# We explicitly point to the .env file in the root directory.
# This ensures it works even if you run the script from a different folder.
env_path = BASE_DIR / ".env"
load_dotenv(env_path)

class Config:
    """
    Central configuration class.
    All application settings should be accessed via this class,
    never by calling os.getenv() directly in other files.
    """
    
    # The Google API Key for Gemini
    API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
    
    # The Model Name
    # We default to 'gemini-2.0-flash' for speed and reliability.
    # You can change this in your .env file without touching code.
    MODEL_NAME: str = os.getenv("AVICENNA_MODEL", "gemini-2.0-flash")
    
    # MCP Configuration
    MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'
    
    @classmethod
    def load_mcp_config(cls) -> MCPConfiguration:
        """Load MCP configuration, creating default if needed"""
        if not cls.MCP_CONFIG_PATH.exists():
            config = MCPConfiguration.default()
            config.save(cls.MCP_CONFIG_PATH)
            console.print(f"[green]✅ Created default MCP config:[/green] {cls.MCP_CONFIG_PATH}")
            return config
        
        try:
            return MCPConfiguration.from_file(cls.MCP_CONFIG_PATH)
        except Exception as e:
            console.print(f"[yellow]⚠️ Error loading MCP config, using defaults:[/yellow] {e}")
            return MCPConfiguration.default()
    
    @classmethod
    def validate(cls) -> bool:
        """
        Verifies that critical configuration is present.
        Returns False if the API key is missing, stopping the app early.
        """
        if not cls.API_KEY:
            console.print("[bold red]❌ CRITICAL ERROR: GOOGLE_API_KEY not found.[/bold red]")
            console.print(f"[yellow]   Expected .env location:[/yellow] {env_path}")
            console.print("[dim]   Please create the .env file with your API key.[/dim]")
            return False
        return True

# 3. Import-time Check
# This runs as soon as this file is imported anywhere.
# It gives immediate feedback if the key is missing.
if not Config.API_KEY:
    console.print("[yellow]⚠️  Warning: Config loaded but API Key is missing.[/yellow]")