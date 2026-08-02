import os
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from rich.console import Console
from avicenna.mcp.mcp_config_schema import MCPConfiguration

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
    
    # Legacy API Key (Google — kept as fallback so existing .env files don't break)
    API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
    
    # Mistral provider settings
    LLM_PROVIDER: str = os.getenv("AVICENNA_PROVIDER", "mistral")
    MISTRAL_API_KEY: str | None = os.getenv("MISTRAL_API_KEY") or os.getenv("GOOGLE_API_KEY")
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
    
    # Legacy Model Name (kept as fallback)
    MODEL_NAME: str = os.getenv("AVICENNA_MODEL", "gemini-2.0-flash")
    
    # Google OAuth credentials for workspace-mcp
    GOOGLE_OAUTH_CLIENT_ID: str | None = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    
    # Brave Search API key for search MCP server
    BRAVE_API_KEY: str | None = os.getenv("BRAVE_API_KEY")
    
    # GitHub Personal Access Token for GitHub MCP server
    GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
    
    # User email for Google Workspace (optional override in .env)
    GOOGLE_USER_EMAIL: str | None = os.getenv("GOOGLE_USER_EMAIL")
    
    # MCP Configuration
    MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'
    USER_CONFIG_PATH = Path.home() / '.avicenna' / 'user_config.json'
    
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
    def load_user_config(cls) -> dict[str, Any]:
        """Load user configuration (email, preferences, etc.)"""
        import json

        if not cls.USER_CONFIG_PATH.exists():
            return {}

        try:
            with open(cls.USER_CONFIG_PATH, 'r') as f:
                # json.load is typed Any; the file is written by save_user_config
                # and is always a JSON object. cast rather than re-validate so
                # behaviour is unchanged.
                return cast(dict[str, Any], json.load(f))
        except Exception as e:
            console.print(f"[yellow]⚠️ Error loading user config:[/yellow] {e}")
            return {}
    
    @classmethod
    def save_user_config(cls, config: dict[str, Any]) -> None:
        """Save user configuration"""
        import json
        
        cls.USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(cls.USER_CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            console.print(f"[red]✗ Error saving user config:[/red] {e}")
    
    @classmethod
    def get_google_user_email(cls) -> str | None:
        """
        Get Google user email with smart fallback:
        1. Check .env GOOGLE_USER_EMAIL (allows override)
        2. Check user_config.json (saved from previous sessions)
        3. Return None (will prompt user when needed)
        """
        # Priority 1: .env file (explicit override)
        if cls.GOOGLE_USER_EMAIL:
            return cls.GOOGLE_USER_EMAIL
        
        # Priority 2: User config (saved from previous session)
        user_config = cls.load_user_config()
        return cast("str | None", user_config.get('google_user_email'))

    @classmethod
    def set_google_user_email(cls, email: str) -> None:
        """Save Google user email to user config"""
        user_config = cls.load_user_config()
        user_config['google_user_email'] = email
        cls.save_user_config(user_config)
        console.print(f"[green]✓ Saved Google email to user config[/green]")
    
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
    try:
        console.print("[yellow]Warning: Config loaded but API Key is missing.[/yellow]")
    except UnicodeEncodeError:
        pass