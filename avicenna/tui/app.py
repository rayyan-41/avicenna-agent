"""AvicennaApp: the two-pane Textual application.

Subscribes to the Phase 3 EventBus via pump_bus and dispatches every
event to the handlers built in dispatch.py. Pipeline runs in an
exclusive worker; the bus pump is non-exclusive.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input
from textual.worker import Worker

from avicenna import events as ev
from avicenna.bus import EventBus
from avicenna.pipeline.run import execute_run
from avicenna.tui.dispatch import build_table
from avicenna.tui.messages import EventMessage, pump_bus
from avicenna.tui.panels import MetadataPanel
from avicenna.tui.widgets import ChatView


class AvicennaApp(App[None]):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "cancel_run", "Cancel run"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
        ("f1", "help", "Help"),
    ]

    def __init__(
        self,
        vault: Any = None,
        bus: EventBus | None = None,
        provider: Any = None,
        context: Any = None,
    ) -> None:
        super().__init__()
        self._vault = vault
        self._bus = bus or EventBus()
        self._provider = provider
        self._vault_context = context
        self._run_worker: Worker[None] | None = None
        self._table: dict[type[ev.Event], Callable[[ev.Event], None]] = build_table(self)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield MetadataPanel(id="meta")
            yield ChatView(id="chat")
        yield Input(id="chat-input", placeholder="Type a topic or /command...")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(pump_bus(self._bus, self), name="bus-pump", exclusive=False)
        self._refresh_vault_card()

        if self._provider is None:
            self.call_after_refresh(self._begin_onboarding)
            return

        self._announce_ready()

    # -- onboarding ---------------------------------------------------------

    def _begin_onboarding(self) -> None:
        from avicenna.tui.screens.onboarding import (
            DEFAULT_MODEL,
            DEFAULT_PROVIDER,
            ProviderSelectScreen,
        )

        def finished(key: str | None) -> None:
            if not key:
                return
            from avicenna.config import Config
            from avicenna.providers.registry import get_provider
            from avicenna.secrets import write_api_key

            store = write_api_key(DEFAULT_PROVIDER, key)
            cfg = Config.load_user_config()
            cfg.update(
                onboarded=True, provider=DEFAULT_PROVIDER,
                model=DEFAULT_MODEL, key_store=store,
            )
            if self._vault is not None:
                cfg["default_vault"] = str(self._vault.root)
            Config.save_user_config(cfg)

            self._provider = get_provider(
                DEFAULT_PROVIDER, api_key=key, model=DEFAULT_MODEL
            )
            chat = self.query_one(ChatView)
            chat.write_assistant(
                f"Key saved to your {store}. Configured {DEFAULT_MODEL}."
            )
            self._refresh_vault_card()
            self._announce_ready()

        self.push_screen(ProviderSelectScreen(), finished)

    def _announce_ready(self) -> None:
        chat = self.query_one(ChatView)
        if self._vault_context is not None:
            chat.write_assistant(self._vault_context.summary)
            if not getattr(self._vault_context, "inside", False) and self._vault_context.found:
                chat.write_assistant(
                    "You are outside the vault; notes will still be written into it."
                )
        chat.write_assistant(
            "Ready. Type a topic to generate a note, or /help for commands."
        )
        self.set_focus(self.query_one("#chat-input", Input))

    def _refresh_vault_card(self) -> None:
        if not self._vault:
            return
        meta = self.query_one(MetadataPanel)
        provider_name = getattr(self._provider, "name", "not configured") if self._provider else "not configured"
        model_name = getattr(self._provider, "_model", "") if self._provider else ""
        ctx = self._vault_context
        meta.vault_card.set_info(
            self._vault.root.name, str(self._vault.root),
            provider_name, model_name,
            badge=getattr(ctx, "badge", "") if ctx else "",
            where=str(getattr(ctx, "relative", "") or "") if ctx else "",
        )

    async def on_unmount(self) -> None:
        try:
            await self._bus.close()
        except Exception:  # noqa: BLE001 - shutdown must never raise
            pass

    def on_event_message(self, message: EventMessage) -> None:
        handler = self._table.get(type(message.event))
        if handler is not None:
            handler(message.event)

    def start_run(self, topic: str) -> None:
        rid = str(uuid.uuid4())[:8]
        self.query_one(ChatView).write_user(topic)
        vault = self._vault
        provider = self._provider
        if vault is None or provider is None:
            self.query_one(ChatView).write_error("No vault or provider configured. Run avicenna init first.")
            return
        self._run_worker = self.run_worker(
            execute_run(
                topic, provider, vault,
                bus=self._bus, run_id=rid, concurrency=3,
            ),
            name="pipeline", exclusive=True,
        )

    def action_cancel_run(self) -> None:
        if self._run_worker is not None and self._run_worker.is_running:
            self._run_worker.cancel()
            self.query_one(ChatView).write_error("Run cancelled.")

    def action_clear_chat(self) -> None:
        self.query_one(ChatView).write_assistant("Chat cleared.")

    def action_help(self) -> None:
        self.query_one(ChatView).write_assistant(
            "Commands: Ctrl+C cancel, Ctrl+Q quit, Ctrl+L clear.\n"
            "Type a topic to generate a note."
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_run_started(self, e: ev.RunStarted) -> None:
        self.query_one(ChatView).write_pipeline(f"Run started: {e.topic}")

    def _on_preflight_declared(self, e: ev.PreflightDeclared) -> None:
        meta = self.query_one(MetadataPanel)
        meta.grid.seed(e.headings)
        meta.stats.set_total_sections(len(e.headings))
        self.query_one(ChatView).write_pipeline(
            f"Pre-flight: {e.topic} ({e.domain}/{e.template}) — {len(e.headings)} headings, ~{e.target_words} words"
        )

    def _on_manifest_written(self, e: ev.ManifestWritten) -> None:
        self.query_one(ChatView).write_pipeline(f"Manifest written: {e.slug} ({e.expected_count} chunks)")

    def _on_section_started(self, e: ev.SectionStarted) -> None:
        self.query_one(MetadataPanel).grid.started(e)

    def _on_section_completed(self, e: ev.SectionCompleted) -> None:
        meta = self.query_one(MetadataPanel)
        meta.grid.completed(e)
        meta.stats.mark_section_done()
        meta.stats.add_words(e.words)
        self.query_one(ChatView).write_pipeline(f"  [{e.index}] {e.heading} — {e.words} words ({e.elapsed:.1f}s)")

    def _on_section_failed(self, e: ev.SectionFailed) -> None:
        self.query_one(MetadataPanel).grid.failed(e)
        if e.will_retry:
            self.query_one(ChatView).write_error(f"  [{e.index}] {e.heading} failed, retrying...")
        else:
            self.query_one(ChatView).write_error(f"  [{e.index}] {e.heading} FAILED: {e.error}")

    def _on_stage_entered(self, e: ev.StageEntered) -> None:
        self.query_one(MetadataPanel).tracker.set_stage(e.stage)
        self.query_one(ChatView).write_pipeline(f"--- Stage: {e.stage} ---")

    def _on_stage_completed(self, e: ev.StageCompleted) -> None:
        self.query_one(MetadataPanel).tracker.mark_done(e.stage)

    def _on_tool_invoked(self, e: ev.ToolInvoked) -> None:
        self.query_one(MetadataPanel).stats.inc_tool()
        self.query_one(ChatView).write_pipeline(f"  Tool: {e.name} [{e.source}]")

    def _on_tool_returned(self, e: ev.ToolReturned) -> None:
        status = "OK" if e.ok else "FAIL"
        self.query_one(ChatView).write_pipeline(f"  Tool done: {e.name} {status} ({e.elapsed:.1f}s)")

    def _on_wordcount_checked(self, e: ev.WordCountChecked) -> None:
        if e.verdict == "fail":
            self.query_one(ChatView).write_error(f"Word count: {e.actual}/{e.minimum} — below target")
        else:
            self.query_one(ChatView).write_pipeline(f"Word count: {e.actual} — OK")

    def _on_tags_proposed(self, e: ev.TagsProposed) -> None:
        self.query_one(MetadataPanel).stats.set_tags(list(e.tags))

    def _on_tags_validated(self, e: ev.TagsValidated) -> None:
        if e.verdict == "fail":
            self.query_one(ChatView).write_error(f"Tag validation: {e.message}")
        else:
            self.query_one(ChatView).write_pipeline(f"Tags accepted: {', '.join(e.accepted)}")

    def _on_link_candidates_found(self, e: ev.LinkCandidatesFound) -> None:
        self.query_one(ChatView).write_pipeline(f"Link candidates: {e.count}")

    def _on_moc_updated(self, e: ev.MocUpdated) -> None:
        self.query_one(ChatView).write_pipeline(f"MOC: {e.result}")

    def _on_note_written(self, e: ev.NoteWritten) -> None:
        self.query_one(ChatView).write_pipeline(f"Note written: {e.path} ({e.words} words)")

    def _on_run_failed(self, e: ev.RunFailed) -> None:
        stage = f" [{e.stage}]" if e.stage else ""
        self.query_one(ChatView).write_error(f"RUN FAILED{stage}: {e.error}")

    def _on_run_complete(self, e: ev.RunComplete) -> None:
        self.query_one(ChatView).write_assistant(
            f"Done! {e.summary}\n{e.total_words} words in {e.elapsed:.1f}s"
        )

    def _on_log_message(self, e: ev.LogMessage) -> None:
        if e.level in ("warning", "error"):
            self.query_one(ChatView).write_error(f"[{e.level}] {e.text}")
        else:
            self.query_one(ChatView).write_pipeline(f"[{e.level}] {e.text}")
