"""Console entry point — Typer CLI with init, note, run-prompt, mcp subcommands.

With no arguments, launches the TypeScript interface in tui/. Pass --no-tui
for headless mode.
"""

from __future__ import annotations

import asyncio
import os
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
    ascii_only: bool = typer.Option(
        False, "--ascii", help="Restrict output to ASCII, for legacy consoles"),
) -> None:
    if ctx.invoked_subcommand is None:
        if no_tui:
            _headless_launch(vault)
        else:
            _tui_launch(vault, reconfigure, ascii_only)


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

    from avicenna.vault.context import VaultContext

    ctx = VaultContext.detect(explicit=vault)
    if not ctx.found:
        typer.echo("No vault found. Run `avicenna init` or pass --vault.", err=True)
        raise typer.Exit(1)
    bound = Vault.load(ctx.root)
    typer.echo(f"[{ctx.badge}] {ctx.summary}")
    typer.echo("")
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
    from avicenna.auth import build_provider
    from avicenna.pipeline.run import execute_run
    from avicenna.vault.discovery import discover_vault
    from avicenna.vault.vault import Vault

    from avicenna.vault.context import VaultContext

    ctx = VaultContext.detect(explicit=vault)
    if not ctx.found:
        typer.echo("No vault found. Run `avicenna init` or pass --vault.", err=True)
        raise typer.Exit(1)
    bound_vault = Vault.load(ctx.root)
    typer.echo(f"[{ctx.badge}] {ctx.summary}")

    # Standing inside History/Biographies is a strong statement about intent,
    # so use it rather than making the router guess from the topic alone.
    hint_domain, hint_category = ctx.location_hint(bound_vault)
    if hint_domain:
        typer.echo(f"location hint: domain={hint_domain} category={hint_category}")

    # Dry run still calls the model: it performs routing AND preflight, which
    # is the whole point (it exercises the riskiest parser for one completion).
    provider = build_provider()
    if not provider:
        typer.echo(
            "No API key found. Set MISTRAL_API_KEY in .env, or run `avicenna` to configure.",
            err=True,
        )
        raise typer.Exit(1)

    asyncio.run(execute_run(
        topic, provider, bound_vault,
        dry_run=dry_run, concurrency=concurrency,
        resume=resume, fresh=not resume,
        domain_override=hint_domain,
    ))
    typer.echo("Done.")


@app.command("bridge", hidden=True)
def bridge_cmd(
    vault: Optional[Path] = typer.Option(None, "--vault"),
) -> None:
    """Run the stdio bridge the interface speaks to. For debugging."""
    from avicenna.bridge.server import main as bridge_main

    args = ["--vault", str(vault)] if vault else []
    raise typer.Exit(bridge_main(args))


@app.command("run-prompt")
def run_prompt_cmd(
    file: Path = typer.Argument(..., help="Path to prompt file"),
    vault: Optional[Path] = typer.Option(None, "--vault"),
) -> None:
    """Run a prompt file (for DEANIMA_AGENT_CMD integration)."""
    from avicenna.auth import build_provider
    from avicenna.session import one_shot

    prompt = file.read_text(encoding="utf-8")
    provider = build_provider()
    if not provider:
        typer.echo("No API key configured.", err=True)
        raise typer.Exit(1)
    result = asyncio.run(one_shot(provider, "You are a helpful assistant.", prompt))
    typer.echo(result)


@app.command("doctor")
def doctor_cmd(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    vault: Optional[Path] = typer.Option(None, "--vault", help="Override vault path"),
) -> None:
    """Run healthcheck probes against this installation."""
    import subprocess

    script = PROJECT_ROOT / "scripts" / "healthcheck.py"
    argv = [sys.executable, str(script)]
    if as_json:
        argv.append("--json")
    if vault is not None:
        argv += ["--vault", str(vault)]
    result = subprocess.run(argv)
    raise typer.Exit(result.returncode)


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

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TUI_ENTRY = PROJECT_ROOT / "tui" / "dist" / "main.js"


def _find_node() -> str | None:
    """Node, from the environment or PATH."""
    import shutil

    override = os.environ.get("AVICENNA_NODE")
    if override:
        return override
    return shutil.which("node")


def _tui_launch(vault_path: Path | None, reconfigure: bool,
                ascii_only: bool = False) -> None:
    """Hand the terminal to the TypeScript frontend.

    The frontend starts its own backend over `python -m avicenna.bridge`, so
    this function only resolves the runtime and gets out of the way. Vault
    detection deliberately happens in the frontend too: it can offer to
    scaffold one, which an early exit here would prevent.
    """
    import subprocess

    node = _find_node()
    if node is None:
        typer.echo(
            "Avicenna's interface needs Node.js 18 or newer, which was not found.\n"
            "  - install it from https://nodejs.org, or\n"
            "  - point at it with AVICENNA_NODE=/path/to/node\n"
            "  - or run headless: avicenna note \"<topic>\"",
            err=True,
        )
        raise typer.Exit(1)

    if not TUI_ENTRY.is_file():
        typer.echo(
            f"The interface has not been built yet ({TUI_ENTRY} is missing).\n"
            f"  cd {PROJECT_ROOT / 'tui'}\n"
            "  npm install && npm run build",
            err=True,
        )
        raise typer.Exit(1)

    argv = [node, str(TUI_ENTRY), "--python", sys.executable, "--cwd", str(Path.cwd())]
    if vault_path is not None:
        argv += ["--vault", str(vault_path)]
    # Forwarded rather than dropped. The frontend has parsed --ascii all along,
    # but the launcher never passed it and the CLI rejected it outright, so the
    # flag the README documents was unreachable through the `avicenna` command.
    if ascii_only:
        argv += ["--ascii"]

    env = dict(os.environ)
    if reconfigure:
        # The frontend owns onboarding; this is how the CLI asks for it.
        env["AVICENNA_FORCE_ONBOARD"] = "1"

    try:
        completed = subprocess.run(argv, env=env)
    except KeyboardInterrupt:
        raise typer.Exit(130)
    raise typer.Exit(completed.returncode)


def _headless_launch(vault_path: Path | None) -> None:
    from avicenna.vault.context import VaultContext

    ctx = VaultContext.detect(explicit=vault_path)
    typer.echo(f"[{ctx.badge}] {ctx.summary}")
    if ctx.found:
        typer.echo("Headless mode. Use `avicenna note \"<topic>\"` to generate.")
    else:
        raise typer.Exit(1)


def main() -> None:
    app()
