"""First-run onboarding.

Two choices, presented as a modal on first launch:

  * Local model - a stub. Deferred honestly, with the real reason: the pipeline
    depends on reliable structured tool calling across ten stages, and local
    models are still inconsistent at emitting well-formed tool calls, so
    shipping it now would produce silent mid-run failures.
  * API key - paste a key, Avicenna validates it live and configures the model
    behind the scenes. There is deliberately no model picker.

The key is validated with one real, cheap completion. That is the only honest
way to tell a good key from a typo, and it is worth a handful of tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, LoadingIndicator, Static

DEFAULT_PROVIDER = "mistral"
DEFAULT_MODEL = "mistral-large-latest"

LOCAL_MODEL_STUB_MESSAGE = (
    "Local model support is planned for a future release. "
    "The pipeline depends on reliable structured tool calling across ten stages, "
    "and local models are still inconsistent at emitting well-formed tool calls, "
    "so shipping it now would produce silent mid-run failures."
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    detail: str


async def validate_key(
    provider_name: str, api_key: str, model: str
) -> ValidationResult:
    """One cheap real call. Maps failures to something a human can act on."""
    from avicenna.providers.base import Message
    from avicenna.providers.errors import AuthError, RateLimitError, TransientError
    from avicenna.providers.registry import get_provider

    provider = get_provider(provider_name, api_key=api_key, model=model)
    try:
        await provider.complete(
            system="Reply with the single word: ok",
            messages=[Message(role="user", content="ping")],
            tools=None,
            temperature=0.0,
            max_tokens=5,
        )
    except AuthError:
        return ValidationResult(False, "Key rejected. Check for a typo or an expired key.")
    except RateLimitError:
        return ValidationResult(False, "Key works but is rate limited right now. Try again shortly.")
    except TransientError as exc:
        return ValidationResult(False, f"Network problem reaching the provider: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface anything else verbatim
        return ValidationResult(False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await provider.close()
        except Exception:  # noqa: BLE001
            pass
    return ValidationResult(True, f"Validated against {model}.")


class LocalModelStubScreen(ModalScreen[None]):
    """Deferred, and says why."""

    BINDINGS = [("escape", "dismiss_screen", "Back")]

    def compose(self) -> ComposeResult:
        with Middle(), Center(), Vertical(id="onboard-box"):
            yield Static("[bold]Local model support[/bold]", classes="onboard-title")
            yield Static(
                "\nPlanned for a future release.\n\n"
                "[bold]Why it is not here yet[/bold]\n"
                "The generation pipeline depends on reliable structured tool calling\n"
                "across ten stages. Local models are still inconsistent at emitting\n"
                "well-formed tool calls, and shipping that now would produce silent\n"
                "mid-run failures rather than clean errors.\n\n"
                "[bold]When it lands it will support[/bold]\n"
                "  - LM Studio and Ollama endpoints\n"
                "  - per-agent model selection\n"
                "  - automatic fallback to a hosted model for tool-heavy stages\n"
            )
            yield Button("Back", variant="primary", id="stub-back")

    @on(Button.Pressed, "#stub-back")
    def _back(self) -> None:
        self.dismiss(None)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


class ApiKeyScreen(ModalScreen[Optional[str]]):
    """Paste a key. The model is configured behind the scenes."""

    BINDINGS = [("escape", "cancel", "Back")]

    def compose(self) -> ComposeResult:
        with Middle(), Center(), Vertical(id="onboard-box"):
            yield Static("[bold]Enter your API key[/bold]", classes="onboard-title")
            yield Static(
                f"\nAvicenna will configure [bold]{DEFAULT_MODEL}[/bold] for you.\n"
                "The key is checked with one small live request, then stored in your\n"
                "OS keyring. It is never written into the repository or into logs.\n"
            )
            yield Input(
                placeholder="paste key, then press Enter",
                password=True,
                id="api-key-input",
            )
            yield Label("", id="api-key-status")
            yield LoadingIndicator(id="api-key-spinner")

    def on_mount(self) -> None:
        self.query_one("#api-key-spinner", LoadingIndicator).display = False
        self.set_focus(self.query_one("#api-key-input", Input))

    @on(Input.Submitted, "#api-key-input")
    def _submit(self, event: Input.Submitted) -> None:
        key = event.value.strip()
        if not key:
            self._status("[red]Enter a key, or press Escape to go back.[/red]")
            return
        self._busy(True)
        self._status("[dim]Validating...[/dim]")
        self._validate(key)

    @work(exclusive=True)
    async def _validate(self, key: str) -> None:
        result = await validate_key(DEFAULT_PROVIDER, key, DEFAULT_MODEL)
        self._busy(False)
        if result.ok:
            self._status(f"[green]{result.detail}[/green]")
            self.dismiss(key)
        else:
            self._status(f"[red]{result.detail}[/red]")
            field = self.query_one("#api-key-input", Input)
            field.value = ""
            self.set_focus(field)

    def _status(self, text: str) -> None:
        self.query_one("#api-key-status", Label).update(text)

    def _busy(self, active: bool) -> None:
        self.query_one("#api-key-spinner", LoadingIndicator).display = active

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProviderSelectScreen(ModalScreen[Optional[str]]):
    """First thing a new user sees. Returns a validated key, or None."""

    def compose(self) -> ComposeResult:
        with Middle(), Center(), Vertical(id="onboard-box"):
            yield Static("[bold]Welcome to Avicenna[/bold]", classes="onboard-title")
            yield Static(
                "\nA harness for generating long-form notes into an Obsidian vault.\n\n"
                "How would you like to run it?\n"
            )
            yield Button("Use an API key   (recommended)", variant="primary", id="pick-api")
            yield Button("Use a local model", id="pick-local")
            yield Static("\n[dim]Ctrl+Q quits at any time.[/dim]")

    @on(Button.Pressed, "#pick-local")
    def _local(self) -> None:
        # Stub: explain, then return to this screen so the user can pick again.
        self.app.push_screen(LocalModelStubScreen())

    @on(Button.Pressed, "#pick-api")
    def _api(self) -> None:
        def done(key: Optional[str]) -> None:
            if key:
                self.dismiss(key)

        self.app.push_screen(ApiKeyScreen(), done)
