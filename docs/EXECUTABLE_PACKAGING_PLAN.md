# Avicenna Executable Packaging Plan

Comprehensive development plan for converting Avicenna into a standalone Windows executable that can be double-clicked to launch in PowerShell.

---

## Table of Contents

- [Overview](#overview)
- [Architecture Decisions](#architecture-decisions)
- [Phase 1: PyInstaller Setup & Basic Build](#phase-1-pyinstaller-setup--basic-build)
- [Phase 2: Path Resolution & Resource Management](#phase-2-path-resolution--resource-management)
- [Phase 3: MCP Server Subprocess Compatibility](#phase-3-mcp-server-subprocess-compatibility)
- [Phase 4: PowerShell Launcher & User Experience](#phase-4-powershell-launcher--user-experience)
- [Phase 5: Testing & Distribution Package](#phase-5-testing--distribution-package)

---

## Overview

### Goal
Transform Avicenna from a Python application requiring `python -m source.avicenna.main chat` into a standalone executable that:
- Can be double-clicked to launch
- Opens in PowerShell terminal with full functionality
- Requires no Python installation on user's machine
- Includes all dependencies bundled within
- Works with MCP servers running as subprocesses

### Current State
```
User's Machine:
├── Python 3.9+ installed
├── pip install -r requirements.txt
└── Run: python -m source.avicenna.main chat

Dependencies:
- google-genai
- python-dotenv
- typer
- rich
- google-api-python-client
- mcp, fastmcp
```

### Target State
```
User's Machine:
├── Avicenna/
│   ├── avicenna.exe          ← Double-click this
│   ├── .env                  ← User creates
│   ├── credentials.json      ← User provides (optional)
│   └── mcp_servers/          ← Bundled MCP server scripts
│       ├── basic_server.py
│       └── gmail_server.py
└── ~\.avicenna\
    └── mcp_config.json       ← Auto-generated

No Python installation required!
```

---

## Architecture Decisions

### 1. Packaging Approach: One-Folder Mode

**Decision:** Use PyInstaller's `--onedir` (one-folder) mode

**What This Means:**
- PyInstaller creates a folder containing:
  - `avicenna.exe` - Main executable
  - `_internal/` - Folder with Python runtime, DLLs, and dependencies
  - External files: `mcp_servers/`, `.env`, `credentials.json`

**Why One-Folder:**
- ✅ **Faster startup**: Doesn't extract files to temp every run
- ✅ **Easier debugging**: Can inspect bundled files directly
- ✅ **Better for development**: See what's bundled, modify if needed
- ✅ **MCP compatibility**: Easier to locate and execute MCP server scripts
- ❌ **More files**: Not a single `.exe`, but still portable as a folder

**Alternative (Not Using):**
- One-file mode (`--onefile`): Single `.exe`, but slower startup (extracts to temp) and harder to debug MCP server paths

---

### 2. MCP Server Bundling: External Scripts

**Decision:** Keep MCP server Python scripts as external files in `mcp_servers/` folder

**What This Means:**
```
Avicenna/
├── avicenna.exe
├── _internal/          ← PyInstaller bundled files
│   ├── python311.dll
│   ├── library.zip
│   └── ...
└── mcp_servers/        ← External Python scripts
    ├── basic_server.py
    └── gmail_server.py
```

**Why External:**
- ✅ **Simple subprocess execution**: Can directly spawn `python mcp_servers/basic_server.py`
- ✅ **User can modify**: Advanced users can edit MCP servers without rebuilding
- ✅ **Easier development**: Test MCP server changes without rebuilding exe
- ✅ **Clear structure**: Users can see what tools are available
- ❌ **More files**: Not everything embedded in exe

**Alternative (Not Using):**
- Embedded scripts: Bundle as PyInstaller data, extract to temp - more complex, harder to debug

---

### 3. Python Interpreter Inclusion (Simplified Explanation)

**The Problem:**
Avicenna needs to run MCP servers as separate programs (subprocesses). MCP servers are Python scripts. On a machine without Python installed, how do we run these Python scripts?

**The Solution:**
PyInstaller bundles a complete Python runtime inside the `_internal/` folder. This includes:
- `python311.dll` - The Python engine
- Standard library - All Python built-in modules
- All dependencies - Everything from `requirements.txt`

**What This Means for Us:**

**Scenario 1: Running the Main Executable**
```
User double-clicks avicenna.exe
  ↓
avicenna.exe contains bundled Python
  ↓
Runs source/avicenna/main.py using bundled Python
  ↓
Works! ✓
```

**Scenario 2: MCP Servers (The Tricky Part)**
```
avicenna.exe needs to spawn MCP server subprocess
  ↓
subprocess.Popen([python_executable, "mcp_servers/basic_server.py"])
  ↓
❓ What should python_executable be?
```

**Options:**

**Option A: Use sys.executable** ✅ **RECOMMENDED**
```python
import sys
python_path = sys.executable  # Points to avicenna.exe when frozen
subprocess.Popen([python_path, "mcp_servers/basic_server.py"])
```
- **Pros:** Uses the same bundled Python that's running the main exe
- **Cons:** PyInstaller one-folder mode might need special handling
- **Our Choice:** This is what we'll implement

**Option B: Bundle a separate Python interpreter**
```
Avicenna/
├── avicenna.exe
├── python/               ← Separate Python installation
│   ├── python.exe
│   └── ...
└── mcp_servers/
```
- **Pros:** Clean separation, definitely works
- **Cons:** Huge size increase (2 Python runtimes), redundant
- **Not using this**

**What We'll Do:**
1. Use `sys.executable` to get the bundled Python
2. Test that it can execute external `.py` files (MCP servers)
3. If issues arise, we'll add special handling for PyInstaller's frozen state

**Simple Analogy:**
- Think of PyInstaller like packaging a portable app
- It includes its own "engine" (Python runtime)
- The exe uses this engine to run
- MCP servers also need to use this same engine
- We just need to point them to the right engine location

---

### 4. Configuration File Locations: Exe Directory (Shipping-Friendly)

**Decision:** All user-editable files in the same folder as the executable

**Structure:**
```
Avicenna/                        ← This whole folder is portable
├── avicenna.exe                 ← Launch this
├── .env                         ← User creates/edits
├── credentials.json             ← User provides (for Gmail)
├── avicenna.log                 ← Created on first run
├── mcp_servers/                 ← Bundled MCP servers
└── _internal/                   ← PyInstaller files (don't touch)

User Profile:
└── C:\Users\YourName\.avicenna\
    └── mcp_config.json          ← Auto-generated MCP configuration
```

**Why This Setup:**
- ✅ **Portable**: Copy entire `Avicenna/` folder to USB, works anywhere
- ✅ **User-friendly**: All editable files in one place
- ✅ **Clear documentation**: "Put your .env file here"
- ✅ **Logging visible**: User can check `avicenna.log` for errors
- ✅ **MCP config in profile**: Per-user settings, doesn't travel with exe

**Path Resolution Strategy:**
```python
# Get exe directory (where user's files are)
if getattr(sys, 'frozen', False):
    # Running as exe
    exe_dir = Path(sys.executable).parent
else:
    # Running as Python script (development)
    exe_dir = Path(__file__).parent.parent.parent

# Look for .env in exe directory
env_path = exe_dir / ".env"

# MCP config still in user profile
mcp_config_path = Path.home() / '.avicenna' / 'mcp_config.json'
```

---

## Phase 1: PyInstaller Setup & Basic Build

**Objective:** Create a basic executable that launches successfully, even if full functionality isn't working yet.

### 1.1 Install PyInstaller

```bash
pip install pyinstaller
```

### 1.2 Create Build Specification File

**File:** `build_exe.spec`

Create a PyInstaller spec file that defines how to build the executable:

```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['source/avicenna/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle MCP server scripts as external files
        ('mcp_servers/*.py', 'mcp_servers'),
    ],
    hiddenimports=[
        # MCP and async dependencies
        'mcp',
        'mcp.server',
        'mcp.server.fastmcp',
        'mcp.client',
        'mcp.client.stdio',
        'mcp.types',
        'fastmcp',
        
        # Google dependencies
        'google.genai',
        'google.genai.types',
        'google.ai',
        'google_auth_oauthlib',
        'google_auth_httplib2',
        'googleapiclient',
        'googleapiclient.discovery',
        
        # Other dependencies
        'typer',
        'rich',
        'dotenv',
        
        # Stdlib async
        'asyncio',
        'contextvars',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # One-folder mode
    name='avicenna',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Show console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon later
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='avicenna',
)
```

### 1.3 Create Build Script

**File:** `build.bat`

Create a batch script to automate the build process:

```batch
@echo off
echo ========================================
echo Building Avicenna Executable
echo ========================================

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build executable
echo.
echo Running PyInstaller...
pyinstaller build_exe.spec --clean

REM Copy external files to dist
echo.
echo Copying external files...
xcopy /E /I /Y mcp_servers dist\avicenna\mcp_servers

REM Create .env template
echo.
echo Creating .env template...
(
echo # Avicenna Configuration
echo # Get your API key from: https://aistudio.google.com/apikey
echo.
echo GOOGLE_API_KEY=your_api_key_here
echo AVICENNA_MODEL=gemini-2.0-flash-exp
) > dist\avicenna\.env.template

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Executable location: dist\avicenna\avicenna.exe
echo.
echo Next steps:
echo 1. Navigate to dist\avicenna\
echo 2. Rename .env.template to .env
echo 3. Add your GOOGLE_API_KEY to .env
echo 4. Double-click avicenna.exe
echo.
pause
```

### 1.4 Initial Build Test

Run the build:

```bash
.\build.bat
```

**Expected Result:**
- `dist/avicenna/` folder created
- `avicenna.exe` present
- `_internal/` folder with Python runtime
- `mcp_servers/` folder with `.py` files

**Test:**
```bash
cd dist\avicenna
.\avicenna.exe --help
```

**Expected Output:**
```
Usage: avicenna [OPTIONS] COMMAND [ARGS]...

Commands:
  chat  Start Avicenna chat session
```

### 1.5 Commit Point

**Git Commit:**
```
Phase 1 Complete: PyInstaller Basic Build

- Added build_exe.spec configuration
- Created build.bat automation script
- Successfully builds one-folder executable
- MCP servers bundled as external files
- Basic exe launches and shows help
```

---

## Phase 2: Path Resolution & Resource Management

**Objective:** Make the application correctly locate all resources when running as a frozen executable.

### 2.1 Create Resource Path Utility

**File:** `source/avicenna/utils.py` (new file)

```python
"""Utility functions for Avicenna"""
import sys
from pathlib import Path


def get_base_dir() -> Path:
    """
    Get the base directory for the application.
    
    When running as a PyInstaller executable:
        Returns the directory containing the .exe file
        (This is where .env and credentials.json should be)
    
    When running as a Python script:
        Returns the project root directory
    
    Returns:
        Path: Absolute path to the base directory
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # sys.executable points to avicenna.exe
        # We want the directory containing it
        return Path(sys.executable).parent
    else:
        # Running as Python script
        # This file is at: source/avicenna/utils.py
        # Go up 3 levels to reach project root
        return Path(__file__).resolve().parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a resource file.
    
    Works in both development and frozen executable modes.
    
    Args:
        relative_path: Path relative to base directory (e.g., "mcp_servers/basic_server.py")
    
    Returns:
        Path: Absolute path to the resource
    
    Example:
        >>> get_resource_path("mcp_servers/basic_server.py")
        Path("C:/Avicenna/mcp_servers/basic_server.py")
    """
    base = get_base_dir()
    return base / relative_path


def is_frozen() -> bool:
    """
    Check if running as a PyInstaller executable.
    
    Returns:
        bool: True if frozen (running as .exe), False if running as Python script
    """
    return getattr(sys, 'frozen', False)
```

### 2.2 Update Config Path Resolution

**File:** `source/avicenna/config.py`

Update to use the new utility functions:

```python
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from rich.console import Console
from mcp_servers.mcp_config_schema import MCPConfiguration
from .utils import get_base_dir, is_frozen  # NEW IMPORT

# Initialize Rich console for pretty error messages
console = Console()

# Use utility function for base directory
BASE_DIR = get_base_dir()

# Load environment variables from .env in base directory
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
    MODEL_NAME: str = os.getenv("AVICENNA_MODEL", "gemini-2.0-flash-exp")
    
    # MCP Configuration (stays in user profile)
    MCP_CONFIG_PATH = Path.home() / '.avicenna' / 'mcp_config.json'
    
    # Log file in base directory (next to exe)
    LOG_FILE = BASE_DIR / "avicenna.log"
    
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
            
            if is_frozen():
                console.print("\n[cyan]📝 Instructions for setting up .env:[/cyan]")
                console.print(f"1. Open: {env_path.parent}")
                console.print("2. Rename .env.template to .env")
                console.print("3. Edit .env and add your GOOGLE_API_KEY")
                console.print("4. Get API key from: https://aistudio.google.com/apikey")
            
            return False
        return True

# Import-time check
if not Config.API_KEY:
    console.print("[yellow]⚠️  Warning: Config loaded but API Key is missing.[/yellow]")
```

### 2.3 Update Main.py Logging Path

**File:** `source/avicenna/main.py`

Change log file to use Config.LOG_FILE:

```python
# Before:
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('avicenna.log')  # ← OLD
    ]
)

# After:
from .config import Config  # Already imported

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE)  # ← NEW
    ]
)
```

### 2.4 Update MCP Config Schema Default Paths

**File:** `mcp_servers/mcp_config_schema.py`

Update default server script paths to be relative:

```python
@classmethod
def default(cls) -> 'MCPConfiguration':
    """Create default configuration with relative paths"""
    return cls(servers=[
        MCPServerConfig(
            name="basic",
            script="mcp_servers/basic_server.py",  # ← Already relative, good!
            enabled=True,
            description="Basic tools: time, calculator"
        ),
        MCPServerConfig(
            name="gmail",
            script="mcp_servers/gmail_server.py",  # ← Already relative, good!
            enabled=True,
            description="Gmail email sending capabilities"
        )
    ])
```

### 2.5 Test Resource Resolution

Create a test script:

**File:** `test_paths.py` (temporary, for testing)

```python
"""Test path resolution in frozen and unfrozen modes"""
import sys
from pathlib import Path

# Add source to path
sys.path.insert(0, str(Path(__file__).parent / "source"))

from avicenna.utils import get_base_dir, get_resource_path, is_frozen
from avicenna.config import Config

print("=== Path Resolution Test ===")
print(f"Frozen: {is_frozen()}")
print(f"Base Dir: {get_base_dir()}")
print(f"Env Path: {Config.BASE_DIR / '.env'}")
print(f"Log File: {Config.LOG_FILE}")
print(f"MCP Config: {Config.MCP_CONFIG_PATH}")
print(f"MCP Server: {get_resource_path('mcp_servers/basic_server.py')}")
print(f"Exists: {get_resource_path('mcp_servers/basic_server.py').exists()}")
```

**Test in development:**
```bash
python test_paths.py
```

**Rebuild and test as exe:**
```bash
.\build.bat
cd dist\avicenna
.\avicenna.exe --help  # Should work without errors
```

### 2.6 Commit Point

**Git Commit:**
```
Phase 2 Complete: Path Resolution & Resource Management

- Added source/avicenna/utils.py with path utilities
- Updated config.py to use get_base_dir()
- Log file now writes to exe directory
- .env searched in exe directory
- MCP config stays in user profile
- Tested in both dev and frozen modes
```

---

## Phase 3: MCP Server Subprocess Compatibility

**Objective:** Enable MCP servers to run as subprocesses when launched from the frozen executable.

### 3.1 Update MCP Client Server Spawning

**File:** `mcp_servers/mcp_client.py`

Update the `connect_server` method to work with frozen executable:

```python
async def connect_server(self, server_config: MCPServerConfig) -> bool:
    """
    Connect to a single MCP server
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        logger.info(f"Connecting to MCP server: {server_config.name}")
        
        # Resolve script path
        script_path = Path(server_config.script)
        
        # If not absolute, make it relative to base directory
        if not script_path.is_absolute():
            # Import here to avoid circular dependency
            import sys
            if getattr(sys, 'frozen', False):
                # Running as exe - base dir is exe's parent
                base_dir = Path(sys.executable).parent
            else:
                # Running as script - base dir is project root
                base_dir = Path(__file__).parent.parent
            
            script_path = base_dir / script_path
        
        if not script_path.exists():
            logger.error(f"Server script not found: {script_path}")
            return False
        
        # Find Python interpreter
        # When frozen, sys.executable points to avicenna.exe
        # PyInstaller's exe can execute .py files directly
        python_path = sys.executable
        
        # Fallback to system Python if not frozen
        if not getattr(sys, 'frozen', False):
            # Development mode - use current Python
            if not python_path:
                python_path = shutil.which("python")
            if not python_path:
                python_path = shutil.which("python3")
        
        if not python_path:
            logger.error("Python interpreter not found")
            return False
        
        logger.debug(f"Using Python: {python_path}")
        logger.debug(f"Server script: {script_path.absolute()}")
        
        # Configure server parameters
        server_params = StdioServerParameters(
            command=python_path,
            args=[str(script_path.absolute())],
            env=server_config.env or {}
        )
        
        # Rest of the method stays the same...
        # Start stdio connection
        read, write = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        
        # Create session
        session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        
        # Initialize session
        await session.initialize()
        
        # List available tools
        response = await session.list_tools()
        
        # Store session and tools
        self.sessions[server_config.name] = session
        for tool in response.tools:
            self.tools[tool.name] = tool
            self.tool_to_server[tool.name] = server_config.name
            logger.debug(f"  Registered tool: {tool.name}")
        
        logger.info(f"  ✓ {server_config.name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to connect to {server_config.name}: {e}", exc_info=True)
        return False
```

### 3.2 Test MCP Server Path in Frozen Mode

Add debug logging to verify MCP server discovery:

**File:** `source/avicenna/providers/gemini.py`

Add more verbose logging during initialization:

```python
async def initialize(self):
    """
    Async initialization - connects to MCP servers and discovers tools
    
    Must be called before using the provider
    """
    # Load MCP configuration
    mcp_config = Config.load_mcp_config()
    
    # Create MCP client manager
    self.mcp_manager = MCPClientManager()
    
    # Connect to all servers
    logger.info("Connecting to MCP servers...")
    logger.debug(f"MCP config has {len(mcp_config.servers)} servers")
    
    for server in mcp_config.servers:
        logger.debug(f"  Server: {server.name}, Script: {server.script}, Enabled: {server.enabled}")
    
    connection_results = await self.mcp_manager.connect_all(mcp_config.servers)
    
    # Report connection status
    for server_name, success in connection_results.items():
        if success:
            logger.debug(f"  Connected: {server_name}")
        else:
            logger.warning(f"  Failed: {server_name}")
    
    # Get tools in Gemini format
    gemini_tools = self.mcp_manager.get_gemini_tools()
    
    logger.info(f"Loaded {len(self.mcp_manager.list_available_tools())} tools from MCP servers")
    logger.debug(f"Tools: {[tool for tool in self.mcp_manager.list_available_tools()]}")
    
    # ... rest of method
```

### 3.3 Handle MCP Server Import Paths

**File:** `mcp_servers/basic_server.py` and `mcp_servers/gmail_server.py`

Update the path handling at the top of each server file:

```python
# At the top of basic_server.py
import sys
from pathlib import Path

# Add parent directory to path for imports when run as main
if __name__ == "__main__":
    # When frozen, we're already in the right location
    if not getattr(sys, 'frozen', False):
        # Development mode - add project root to path
        sys.path.insert(0, str(Path(__file__).parent.parent))

# Then the rest of the imports
from fastmcp import FastMCP
# ... etc
```

Same update for `gmail_server.py`.

### 3.4 Create MCP Server Test Script

**File:** `test_mcp_subprocess.py` (temporary)

```python
"""Test that MCP servers can be spawned as subprocesses"""
import sys
import subprocess
from pathlib import Path

def test_mcp_server(server_script):
    """Test spawning an MCP server"""
    python_exe = sys.executable
    
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent
    
    script_path = base_dir / server_script
    
    print(f"Testing MCP server: {server_script}")
    print(f"  Python: {python_exe}")
    print(f"  Script: {script_path}")
    print(f"  Exists: {script_path.exists()}")
    
    if not script_path.exists():
        print(f"  ❌ FAIL: Script not found")
        return False
    
    try:
        # Try to spawn the server (will fail without MCP client, but should start)
        result = subprocess.Popen(
            [python_exe, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Give it a moment to start
        import time
        time.sleep(2)
        
        # Check if process is still running (good) or crashed (bad)
        if result.poll() is None:
            print(f"  ✓ Process started successfully")
            result.terminate()
            return True
        else:
            stdout, stderr = result.communicate()
            print(f"  ❌ Process crashed")
            print(f"  STDERR: {stderr}")
            return False
            
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return False

if __name__ == "__main__":
    print("=== MCP Server Subprocess Test ===\n")
    
    servers = [
        "mcp_servers/basic_server.py",
        "mcp_servers/gmail_server.py"
    ]
    
    results = []
    for server in servers:
        success = test_mcp_server(server)
        results.append(success)
        print()
    
    if all(results):
        print("✓ All MCP servers can be spawned")
    else:
        print("❌ Some MCP servers failed")
        sys.exit(1)
```

### 3.5 Build and Test

```bash
# Rebuild
.\build.bat

# Test MCP server spawning
cd dist\avicenna
python ..\..\test_mcp_subprocess.py  # Use project Python to run test

# Test full Avicenna with debug logging
.\avicenna.exe chat --debug
```

### 3.6 Commit Point

**Git Commit:**
```
Phase 3 Complete: MCP Server Subprocess Compatibility

- Updated mcp_client.py to resolve server paths in frozen mode
- MCP servers can now be spawned from frozen executable
- Added debug logging for MCP initialization
- Fixed import paths in MCP server files
- Tested subprocess spawning in both modes
```

---

## Phase 4: PowerShell Launcher & User Experience

**Objective:** Create a polished user experience with easy launching and clear documentation.

### 4.1 Create PowerShell Launcher Batch File

**File:** `Avicenna.bat` (will be copied to dist/avicenna/)

```batch
@echo off
REM Avicenna Launcher
REM This opens PowerShell and runs Avicenna

REM Get the directory where this batch file is located
set SCRIPT_DIR=%~dp0

REM Change to that directory
cd /d "%SCRIPT_DIR%"

REM Check if .env exists
if not exist ".env" (
    echo.
    echo ========================================
    echo   Avicenna Configuration Missing
    echo ========================================
    echo.
    echo The .env file is missing. Please create it first.
    echo.
    echo Steps:
    echo   1. Rename .env.template to .env
    echo   2. Edit .env and add your GOOGLE_API_KEY
    echo   3. Get API key from: https://aistudio.google.com/apikey
    echo.
    echo Press any key to open the folder...
    pause > nul
    explorer .
    exit /b 1
)

REM Launch in PowerShell with -NoExit to keep window open
powershell.exe -NoExit -ExecutionPolicy Bypass -Command "& '%SCRIPT_DIR%avicenna.exe' chat"
```

### 4.2 Create User Documentation

**File:** `README_EXE.md` (will be copied to dist/avicenna/)

```markdown
# Avicenna - AI Agent

A powerful AI assistant with tool capabilities, powered by Google Gemini.

## Quick Start

### First Time Setup

1. **Get Google API Key**
   - Visit: https://aistudio.google.com/apikey
   - Create a new API key
   - Copy it to clipboard

2. **Configure Avicenna**
   - Rename `.env.template` to `.env`
   - Open `.env` in a text editor
   - Replace `your_api_key_here` with your actual API key
   - Save and close

3. **Launch Avicenna**
   - Double-click `Avicenna.bat`
   - PowerShell will open with Avicenna running

### Optional: Gmail Integration

If you want to send emails through Avicenna:

1. Download OAuth credentials from Google Cloud Console
2. Save as `credentials.json` in this folder
3. First time you send an email, you'll be asked to authorize

## What's In This Folder?

```
Avicenna/
├── Avicenna.bat          ← Double-click this to launch
├── avicenna.exe          ← Main executable (can also run directly)
├── .env                  ← Your configuration (you create this)
├── .env.template         ← Template for .env
├── credentials.json      ← Gmail OAuth (optional, you provide)
├── avicenna.log          ← Log file (created automatically)
├── README_EXE.md         ← This file
├── mcp_servers/          ← Tool servers (don't modify unless you know what you're doing)
└── _internal/            ← Python runtime and dependencies (don't touch)
```

## Usage

### Example Commands

```
> What time is it?
> Calculate 42 * 1337
> What's the weather like? (general knowledge)
> Draft an email to john@example.com subject "Hello" body "Test message"
```

### Special Commands

- `clear` or `cls` - Clear screen
- `exit` or `quit` - Exit Avicenna

## Troubleshooting

### "API Key not found"
- Make sure `.env` file exists (rename `.env.template`)
- Check that `GOOGLE_API_KEY=` line has your actual key
- No spaces around the `=` sign

### "MCP server connection failed"
- Check `avicenna.log` for detailed errors
- Ensure `mcp_servers/` folder exists with `.py` files
- Try running with `--debug` flag: `avicenna.exe chat --debug`

### "Permission denied" or OAuth errors (Gmail)
- Ensure `credentials.json` is in the same folder as `avicenna.exe`
- Delete `token.json` and try again to re-authenticate

## Advanced

### Running from Command Line

Open PowerShell in this folder and run:

```powershell
.\avicenna.exe chat
```

### Debug Mode

```powershell
.\avicenna.exe chat --debug
```

This shows detailed logs in the console.

### Custom Model

Change in `.env`:
```
AVICENNA_MODEL=gemini-2.0-flash-exp
```

## Support

For issues and updates, visit: https://github.com/rayyan-41/avicenna-agent
```

### 4.3 Update Build Script to Include Launcher

**File:** `build.bat`

Add steps to copy the launcher and documentation:

```batch
@echo off
echo ========================================
echo Building Avicenna Executable
echo ========================================

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build executable
echo.
echo Running PyInstaller...
pyinstaller build_exe.spec --clean

REM Copy external files to dist
echo.
echo Copying external files...
xcopy /E /I /Y mcp_servers dist\avicenna\mcp_servers

REM Create .env template
echo.
echo Creating .env template...
(
echo # Avicenna Configuration
echo # Get your API key from: https://aistudio.google.com/apikey
echo.
echo GOOGLE_API_KEY=your_api_key_here
echo AVICENNA_MODEL=gemini-2.0-flash-exp
) > dist\avicenna\.env.template

REM Copy launcher batch file
echo.
echo Copying launcher...
copy Avicenna.bat dist\avicenna\Avicenna.bat

REM Copy user documentation
echo.
echo Copying documentation...
copy README_EXE.md dist\avicenna\README_EXE.md

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Distribution package: dist\avicenna\
echo.
echo Next steps:
echo 1. Navigate to dist\avicenna\
echo 2. Read README_EXE.md
echo 3. Rename .env.template to .env
echo 4. Add your GOOGLE_API_KEY to .env
echo 5. Double-click Avicenna.bat
echo.
pause
```

### 4.4 Improve Error Messages

**File:** `source/avicenna/main.py`

Enhance error messages for frozen mode:

```python
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
        
        # Provide helpful error information in frozen mode
        if getattr(sys, 'frozen', False):
            console.print(f"\n[{DARK_GREEN}]Troubleshooting:[/]")
            console.print(f"[{DARK_GREEN}]1. Check avicenna.log for details[/]")
            console.print(f"[{DARK_GREEN}]2. Ensure .env file exists with valid API key[/]")
            console.print(f"[{DARK_GREEN}]3. Run with --debug flag for more info[/]")
            console.print(f"\n[{DARK_GREEN}]Press Enter to exit...[/]")
            input()
        
        raise typer.Exit(1)
```

### 4.5 Add Application Icon (Optional)

Create or download an icon file:

**File:** `icon.ico` (place in project root)

Update `build_exe.spec`:

```python
exe = EXE(
    # ... other parameters ...
    icon='icon.ico',  # Add this line
)
```

### 4.6 Test Complete User Experience

**Full workflow test:**

1. Build: `.\build.bat`
2. Navigate to `dist\avicenna\`
3. Verify all files present:
   - `Avicenna.bat`
   - `avicenna.exe`
   - `.env.template`
   - `README_EXE.md`
   - `mcp_servers/` folder
4. Create `.env` from template
5. Add valid API key
6. Double-click `Avicenna.bat`
7. Test commands:
   - `what time is it?`
   - `calculate 10 * 10`
   - `clear`
   - `exit`

### 4.7 Commit Point

**Git Commit:**
```
Phase 4 Complete: PowerShell Launcher & User Experience

- Created Avicenna.bat launcher for easy launching
- Added README_EXE.md user documentation
- Improved error messages for frozen mode
- Build script copies all distribution files
- Added .env.template generation
- Polished first-time user experience
```

---

## Phase 5: Testing & Distribution Package

**Objective:** Thoroughly test the executable and prepare for distribution.

### 5.1 Create Comprehensive Test Plan

**File:** `tests/test_frozen_build.md` (documentation)

```markdown
# Frozen Build Test Checklist

## Environment Setup
- [ ] Fresh Windows machine or VM
- [ ] No Python installed
- [ ] No prior Avicenna installation

## Installation Test
- [ ] Extract `Avicenna.zip` to desktop
- [ ] All files present and readable
- [ ] No missing dependencies errors

## First Launch Test
- [ ] Double-click `Avicenna.bat`
- [ ] Error message shown if .env missing
- [ ] Clear instructions displayed

## Configuration Test
- [ ] Rename `.env.template` to `.env`
- [ ] Add API key
- [ ] Launch `Avicenna.bat` again
- [ ] Avicenna starts successfully
- [ ] Logo displays correctly
- [ ] Model name shown correctly

## Basic Functionality
- [ ] `what time is it?` - Returns current time
- [ ] `calculate 15 * 24` - Returns 360
- [ ] General questions work (knowledge queries)
- [ ] `clear` command clears screen
- [ ] `exit` command closes gracefully

## MCP Server Test
- [ ] Check `avicenna.log` for MCP server connections
- [ ] Both servers (basic, gmail) connected
- [ ] No subprocess errors in log

## Gmail Integration Test (Optional)
- [ ] Add `credentials.json`
- [ ] `draft email to test@example.com subject "Test" body "Test"`
- [ ] Email preview displays
- [ ] OAuth flow works if sending
- [ ] Token saved correctly

## Error Handling
- [ ] Invalid API key shows clear error
- [ ] Missing .env shows helpful message
- [ ] Network errors handled gracefully
- [ ] Bad commands don't crash app

## Performance
- [ ] Startup time < 10 seconds
- [ ] Response time reasonable
- [ ] No memory leaks (check Task Manager after 10+ queries)
- [ ] CPU usage normal

## Files Generated
- [ ] `avicenna.log` created
- [ ] `token.json` created (if Gmail used)
- [ ] `~\.avicenna\mcp_config.json` created

## Cleanup Test
- [ ] Delete folder
- [ ] `~\.avicenna\` folder remains (expected)
- [ ] No orphaned processes
```

### 5.2 Create Automated Test Script

**File:** `tests/test_exe_functionality.py`

```python
"""Automated tests for frozen executable"""
import subprocess
import time
from pathlib import Path

def test_exe_help():
    """Test that exe can show help"""
    exe_path = Path("dist/avicenna/avicenna.exe")
    if not exe_path.exists():
        print("❌ Executable not found. Build first.")
        return False
    
    try:
        result = subprocess.run(
            [str(exe_path), "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and "chat" in result.stdout:
            print("✓ Help command works")
            return True
        else:
            print(f"❌ Help failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def test_mcp_servers_exist():
    """Test that MCP server files are bundled"""
    servers = [
        "dist/avicenna/mcp_servers/basic_server.py",
        "dist/avicenna/mcp_servers/gmail_server.py",
    ]
    
    for server in servers:
        if not Path(server).exists():
            print(f"❌ Missing: {server}")
            return False
    
    print("✓ MCP servers bundled")
    return True

def test_launcher_exists():
    """Test that launcher files exist"""
    files = [
        "dist/avicenna/Avicenna.bat",
        "dist/avicenna/README_EXE.md",
        "dist/avicenna/.env.template",
    ]
    
    for file in files:
        if not Path(file).exists():
            print(f"❌ Missing: {file}")
            return False
    
    print("✓ Launcher files present")
    return True

if __name__ == "__main__":
    print("=== Frozen Build Tests ===\n")
    
    tests = [
        test_exe_help,
        test_mcp_servers_exist,
        test_launcher_exists,
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    if all(results):
        print("✓ All automated tests passed")
        print("\nNext: Manual testing with test_frozen_build.md checklist")
    else:
        print("❌ Some tests failed")
```

### 5.3 Create Distribution Package Script

**File:** `create_distribution.bat`

```batch
@echo off
echo ========================================
echo Creating Avicenna Distribution Package
echo ========================================

REM Ensure build exists
if not exist "dist\avicenna" (
    echo Error: Build not found. Run build.bat first.
    pause
    exit /b 1
)

REM Create distribution folder
echo.
echo Creating distribution package...
if exist "Avicenna_Distribution" rmdir /s /q Avicenna_Distribution
mkdir Avicenna_Distribution

REM Copy all files
echo Copying files...
xcopy /E /I /Y dist\avicenna Avicenna_Distribution\Avicenna

REM Create installation instructions
echo.
echo Creating installation guide...
(
echo ========================================
echo   Avicenna Installation Guide
echo ========================================
echo.
echo Thank you for downloading Avicenna!
echo.
echo STEP 1: GET API KEY
echo   1. Visit: https://aistudio.google.com/apikey
echo   2. Sign in with your Google account
echo   3. Click "Create API Key"
echo   4. Copy the key to your clipboard
echo.
echo STEP 2: CONFIGURE
echo   1. Open the Avicenna folder
echo   2. Rename .env.template to .env
echo   3. Edit .env in Notepad
echo   4. Paste your API key after GOOGLE_API_KEY=
echo   5. Save and close
echo.
echo STEP 3: LAUNCH
echo   1. Double-click Avicenna.bat
echo   2. PowerShell will open with Avicenna running
echo   3. Try: "What time is it?"
echo.
echo OPTIONAL: Gmail Integration
echo   - Download OAuth credentials from Google Cloud Console
echo   - Save as credentials.json in Avicenna folder
echo   - See README_EXE.md for details
echo.
echo TROUBLESHOOTING
echo   - Check avicenna.log for errors
echo   - Read README_EXE.md for help
echo   - GitHub: https://github.com/rayyan-41/avicenna-agent
echo.
echo ========================================
) > Avicenna_Distribution\INSTALL.txt

REM Create ZIP archive
echo.
echo Creating ZIP archive...
powershell Compress-Archive -Path Avicenna_Distribution\Avicenna -DestinationPath Avicenna_Distribution\Avicenna.zip -Force

echo.
echo ========================================
echo Distribution Package Created!
echo ========================================
echo.
echo Location: Avicenna_Distribution\
echo   - Avicenna\ (folder for extraction)
echo   - Avicenna.zip (for easy distribution)
echo   - INSTALL.txt (user instructions)
echo.
echo Ready to distribute!
echo.
pause
```

### 5.4 Version Information

**File:** `version.txt` (create in project root)

```
Avicenna v1.0.0-exe
Build Date: 2026-01-23
Python: 3.11
PyInstaller: One-Folder Mode
Platform: Windows x64
```

Add version display to main.py:

**File:** `source/avicenna/main.py`

```python
# Add to TIPS list:
TIPS = [
    "Version 1.0.0",  # ← Update this
    "Type 'exit' or 'quit' to end the session",
    "Latest features: Gmail integration!",
    "Packaged with PyInstaller",  # ← Add this
]
```

### 5.5 Final Build and Test

```bash
# Clean build
.\build.bat

# Run automated tests
python tests\test_exe_functionality.py

# Create distribution
.\create_distribution.bat

# Manual testing
# 1. Copy Avicenna_Distribution\Avicenna\ to another location
# 2. Follow INSTALL.txt
# 3. Complete test_frozen_build.md checklist
```

### 5.6 Create Release Notes

**File:** `RELEASE_NOTES.md`

```markdown
# Avicenna v1.0.0 - Executable Release

## What's New

- **Standalone Executable**: No Python installation required
- **One-Click Launch**: Double-click `Avicenna.bat` to start
- **PowerShell Integration**: Runs in native PowerShell terminal
- **Bundled MCP Servers**: All tools included
- **Portable**: Copy the folder anywhere, it just works

## Features

- Google Gemini AI integration
- Time and calculator tools
- Gmail email drafting and sending (with OAuth)
- MCP-based tool architecture
- Async/await performance
- Beautiful terminal UI

## System Requirements

- Windows 10 or later (64-bit)
- Internet connection
- Google API key (free from Google AI Studio)

## Installation

See `INSTALL.txt` in the distribution package.

## Known Issues

- First launch may be slow (~10 seconds) as Python runtime initializes
- Large download size (~100MB) due to bundled Python runtime
- OAuth flow for Gmail opens browser window

## Future Plans

- Smaller download size (optimize bundled dependencies)
- Linux and macOS support
- Additional MCP tool servers
- Web interface
```

### 5.7 Commit Point

**Git Commit:**
```
Phase 5 Complete: Testing & Distribution Package

- Created comprehensive test plan (test_frozen_build.md)
- Added automated test script (test_exe_functionality.py)
- Created distribution packaging script (create_distribution.bat)
- Added version information and release notes
- Ready for distribution
```

---

## Summary

### What We've Accomplished

✅ **Phase 1**: PyInstaller setup and basic build working  
✅ **Phase 2**: Path resolution for .env, logs, and resources  
✅ **Phase 3**: MCP servers can run as subprocesses from frozen exe  
✅ **Phase 4**: Polished launcher and user documentation  
✅ **Phase 5**: Testing infrastructure and distribution package  

### Deliverables

1. **Avicenna.exe** - Standalone executable
2. **Avicenna.bat** - PowerShell launcher
3. **README_EXE.md** - User documentation
4. **INSTALL.txt** - Installation instructions
5. **Avicenna.zip** - Distribution archive

### File Structure

```
Avicenna_Distribution/
└── Avicenna/
    ├── Avicenna.bat          ← Double-click to launch
    ├── avicenna.exe          ← Main executable
    ├── README_EXE.md         ← User guide
    ├── .env.template         ← Configuration template
    ├── mcp_servers/          ← Tool servers
    │   ├── basic_server.py
    │   └── gmail_server.py
    └── _internal/            ← Python runtime (auto-generated)
```

### Testing Checklist

Before distributing:
- [ ] Tested on clean Windows machine
- [ ] No Python required
- [ ] All commands work
- [ ] MCP servers connect
- [ ] Gmail OAuth flow works
- [ ] Error messages are helpful
- [ ] Documentation is clear

### Next Steps (Post-Implementation)

Once all phases are complete:
1. Tag release: `git tag v1.0.0-exe`
2. Create GitHub release with `Avicenna.zip`
3. Update main README.md with download link
4. Create demo video/screenshots
5. Share with users for feedback

---

## Development Workflow

For each phase:

1. **Implement**: Make the code changes listed
2. **Test**: Run the test commands provided
3. **Commit**: Use the commit message template
4. **Document**: Update any affected documentation
5. **Move to next phase**

### Git Branch Strategy

```bash
# Create executable packaging branch
git checkout -b feature/executable-packaging

# After each phase
git add .
git commit -m "[Phase X Complete: ...]"

# After all phases
git checkout master
git merge feature/executable-packaging
git tag v1.0.0-exe
```

### Build Commands Quick Reference

```bash
# Development
python -m source.avicenna.main chat

# Build executable
.\build.bat

# Test executable
cd dist\avicenna
.\avicenna.exe chat

# Create distribution
.\create_distribution.bat

# Run tests
python tests\test_exe_functionality.py
```

---

## Troubleshooting Guide

### Common Issues During Development

**Issue: "Module not found" when running exe**
- Solution: Add to `hiddenimports` in `build_exe.spec`

**Issue: MCP servers fail to connect**
- Check: `avicenna.log` for subprocess errors
- Verify: MCP server files in `dist/avicenna/mcp_servers/`
- Test: Run server manually with `python mcp_servers/basic_server.py`

**Issue: .env not found**
- Check: Path resolution in `config.py`
- Verify: `get_base_dir()` returns correct directory
- Test: Add debug print to show env_path

**Issue: Large exe size**
- Optimize: Add more modules to `excludes` in spec file
- Consider: UPX compression (enabled by default)
- Profile: Use `pyinstaller --log-level DEBUG` to see what's bundled

---

*Ready to begin Phase 1? Let's start building!*
