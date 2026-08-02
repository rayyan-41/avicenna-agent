"""Console entry point — Typer CLI with init, note, run-prompt, mcp subcommands.

With no arguments, launches the TUI. Pass --no-tui for headless mode.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(no_args_is_help=False, add_completion=False)

# Subcommand groups
config_app = typer.Typer()
app.add_typer(config_app, name="config")
mcp_app = typer.Typer()
app.add_typer(mcp_app, name="mcp")

from avicenna.cli.mcp_cmd import mcp_test  # noqa: E402  (registered below)

mcp_app.command("test")(mcp_test)


# ---------------------------------------------------------------------------
# Callback: no subcommand => launch TUI
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    vault: Optional[Path] = typer.Option(None, "--vault", help="Path to Obsidian vault"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Run in headless mode"),
    reconfigure: bool = typer.Option(False, "--reconfigure", help="Force re-onboarding"),
) -> None:
    if ctx.invoked_subcommand is None:
        if no_tui:
            _headless_launch(vault)
        else:
            _tui_launch(vault, reconfigure)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

@app.command("init")
def init_cmd(
    vault_arg: Optional[Path] = typer.Argument(None, metavar="[VAULT]",
                                               help="Path to scaffold the vault"),
    vault_opt: Optional[Path] = typer.Option(None, "--vault",
                                             help="Same as the positional argument"),
) -> None:
    """Scaffold a minimal working vault."""
    from avicenna.vault.init_scaffold import init_vault
    path = vault_arg or vault_opt or Path.cwd() / "avicenna-vault"
    result = init_vault(path)
    typer.echo(f"Vault scaffolded at {result}")


@app.command("route")
def route_cmd(
    topic: str = typer.Argument(..., help="Topic to classify"),
    vault: Optional[Path] = typer.Option(None, "--vault"),
) -> None:
    """Show which agent a topic routes to, and why."""
    from avicenna.vault.discovery import discover_vault
    from avicenna.vault.routing import route_request, score_domains
    from avicenna.vault.vault import Vault

    bound = Vault.load(discover_vault(explicit=vault))
    chosen = route_request(bound, topic)

    typer.echo(f"topic: {topic}")
    typer.echo(f"routed to: {chosen.name if chosen else '(ambiguous - escalates to user)'}")
    typer.echo("")
    typer.echo(f"  {'agent':14s} {'score':>5s}  matched terms")
    for s_ in score_domains(bound, topic):
        typer.echo(f"  {s_}")


@app.command("note")
def note_cmd(
    topic: str = typer.Argument(..., help="Topic for the note"),
    vault: Optional[Path] = typer.Option(None, "--vault"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Headless run"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    resume: bool = typer.Option(False, "--resume"),
    concurrency: int = typer.Option(3, "--concurrency"),
) -> None:
    """Generate a note from a topic."""
    from avicenna.providers.registry import get_provider
    from avicenna.pipeline.run import execute_run
    from avicenna.secrets import read_api_key
    from avicenna.config import Config
    from avicenna.vault.discovery import discover_vault
    from avicenna.vault.vault import Vault

    vault_path = discover_vault(explicit=vault)
    bound_vault = Vault.load(vault_path)

    # Dry run still calls the model: it performs routing AND pre-flight, which
    # is the whole point (it exercises the riskiest parser for one completion).
    key = read_api_key()
    if not key:
        typer.echo(
            "No API key found. Set MISTRAL_API_KEY in .env, or run `avicenna` to configure.",
            err=True,
        )
        raise typer.Exit(1)
    provider = get_provider("mistral", api_key=key, model=Config.MISTRAL_MODEL)

    asyncio.run(execute_run(
        topic, provider, bound_vault,
        dry_run=dry_run, concurrency=concurrency,
        resume=resume, fresh=not resume,
    ))
    typer.echo("Done.")


@app.command("run-prompt")
def run_prompt_cmd(
    file: Path = typer.Argument(..., help="Path to prompt file"),
    vault: Optional[Path] = typer.Option(None, "--vault"),
) -> None:
    """Run a prompt file (for DEANIMA_AGENT_CMD integration)."""
    from avicenna.secrets import read_api_key
    from avicenna.session import one_shot
    from avicenna.config import Config
    from avicenna.providers.registry import get_provider

    prompt = file.read_text(encoding="utf-8")
    key = read_api_key()
    if not key:
        typer.echo("No API key configured.", err=True)
        raise typer.Exit(1)
    provider = get_provider("mistral", api_key=key, model=Config.MISTRAL_MODEL)
    result = asyncio.run(one_shot(provider, "You are a helpful assistant.", prompt))
    typer.echo(result)


# ---------------------------------------------------------------------------
# Config subcommands
# ---------------------------------------------------------------------------

@config_app.command("reset")
def config_reset() -> None:
    """Delete stored config and API key, restoring first-run behavior."""
    from pathlib import Path
    from avicenna.config import Config

    cfg = Config.USER_CONFIG_PATH
    if cfg.exists():
        cfg.unlink()
        typer.echo(f"Deleted {cfg}")
    key_path = Path.home() / ".avicenna" / "mcp_config.json"
    if key_path.exists():
        key_path.unlink()
        typer.echo(f"Deleted {key_path}")
    typer.echo("Config reset. Next run will re-onboard.")


# ---------------------------------------------------------------------------
# MCP subcommands (Phase 10 surface — wired now)
# ---------------------------------------------------------------------------

@mcp_app.command("list")
def mcp_list() -> None:
    """Show every configured MCP server, its transport, enabled state, and tool count."""
    from avicenna.config import Config
    cfg = Config.load_mcp_config()
    if not cfg.servers:
        typer.echo("No MCP servers configured. Add servers to ~/.avicenna/mcp_config.json.")
        return
    for s in cfg.servers:
        status = "enabled" if s.enabled else "disabled"
        typer.echo(f"  {s.name} [{s.type}] — {status}: {s.description or ''}")


@mcp_app.command("path")
def mcp_path() -> None:
    """Print the path to mcp_config.json."""
    from avicenna.config import Config
    typer.echo(str(Config.MCP_CONFIG_PATH))


@mcp_app.command("tools")
def mcp_tools() -> None:
    """List every discovered MCP tool and whether it is model-callable."""
    typer.echo("MCP tools are discovered at run time. Start avicenna and check the welcome sequence.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tui_launch(vault_path: Path | None, reconfigure: bool) -> None:
    from avicenna.tui.app import AvicennaApp
    from avicenna.vault.discovery import discover_vault, VaultNotFound
    from avicenna.vault.vault import Vault
    from avicenna.bus import EventBus

    try:
        vault_root = discover_vault(explicit=vault_path)
        bound_vault = Vault.load(vault_root)
    except VaultNotFound:
        typer.echo("No vault found. Run 'avicenna init' first, or pass --vault.", err=True)
        raise typer.Exit(1)

    bus = EventBus()
    app = AvicennaApp(vault=bound_vault, bus=bus)
    app.run()


def _headless_launch(vault_path: Path | None) -> None:
    typer.echo("Headless mode — ready for batch runs. Use 'avicenna note <topic>'.")
    from avicenna.vault.discovery import discover_vault
    try:
        v = discover_vault(explicit=vault_path)
        typer.echo(f"Vault: {v}")
    except Exception as exc:
        typer.echo(f"Warning: {exc}")


def main() -> None:
    app()
