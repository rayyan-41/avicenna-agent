# Avicenna

## Overview
Avicenna is an AI agent with Model Context Protocol (MCP) integration, running via GeminiCLI.

## Setup
### Prerequisites
- Python 3.12+
- Git
- Node.js 20+ (for Web Interface)

### Installation
1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd avicenna
    ```

2.  **Install `uv` (if not installed):**
    Windows:
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
    Unix/MacOS:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

3.  **Install Dependencies:**
    ```bash
    uv sync
    ```

4.  **Environment Variables:**
    Create a `.env` file:
    ```
    GOOGLE_API_KEY=your_api_key_here
    ```

### Running Tests
```bash
uv run pytest
```

### Development
- **Linting:** `uv run ruff check .`
- **Type Checking:** `uv run mypy .`

## Architecture
- **Core:** Python (Gemini SDK)
- **MCP:** Integration for tool use.
- **Web:** Node.js/Express + Retro Terminal UI.
