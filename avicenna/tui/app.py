"""AvicennaApp: the two-pane Textual application.

Subscribes to the Phase 3 EventBus via pump_bus and dispatches every
event to the handlers built in dispatch.py. Pipeline runs in an
exclusive worker; the bus pump is non-exclusive.
"""

from __future__ import annotations

import asyncio
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
from avicenna.tui.panels import ChatPanel, MetadataPanel


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
    ) -> None:
        super().__init__()
        self._vault = vault
        self._bus = bus or EventBus()
        self._provider = provider
        self._run_worker: Worker[None] | None = None
        self._table: dict[type[ev.Event], Callable[[ev.Event], None]] = build_table(self)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield MetadataPanel(id="meta")
            yield ChatPanel(id="chat")
        yield Input(id="chat-input", placeholder="Type a topic or /command...")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(pump_bus(self._bus, self), name="bus-pump", exclusive=False)
        self.set_focus(self.query_one("#chat-input", Input))
        # Welcome message
        chat = self.query_one(ChatPanel)
        chat.append_assistant("Avicenna ready. Type a topic to generate a note, or /help for commands.")
        # Seed vault card
        if self._vault:
            meta = self.query_one(MetadataPanel)
            provider_name = getattr(self._provider, "name", "none") if self._provider else "none"
            model_name = getattr(self._provider, "_model", "") if self._provider else ""
            meta.vault_card.set_info(
                self._vault.root.name, str(self._vault.root),
                provider_name, model_name,
            )

    def on_event_message(self, message: EventMessage) -> None:
        handler = self._table.get(type(message.event))
        if handler is not None:
            handler(message.event)
        self.query_one(ChatPanel).log_event(message.event)

    def start_run(self, topic: str) -> None:
        rid = str(uuid.uuid4())[:8]
        self.query_one(ChatPanel).append_user(topic)
        vault = self._vault
        provider = self._provider
        if vault is None or provider is None:
            self.query_one(ChatPanel).append_error("No vault or provider configured. Run avicenna init first.")
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
            self.query_one(ChatPanel).append_error("Run cancelled.")

    def action_clear_chat(self) -> None:
        self.query_one(ChatPanel).append_assistant("Chat cleared.")

    def action_help(self) -> None:
        self.query_one(ChatPanel).append_assistant(
            "Commands: Ctrl+C cancel, Ctrl+Q quit, Ctrl+L clear.\n"
            "Type a topic to generate a note."
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_run_started(self, e: ev.RunStarted) -> None:
        self.query_one(ChatPanel).append_pipeline(f"Run started: {e.topic}")

    def _on_preflight_declared(self, e: ev.PreflightDeclared) -> None:
        meta = self.query_one(MetadataPanel)
        meta.preflight.update_from(e)
        meta.grid.seed(e.headings)
        meta.stats.set_total_sections(len(e.headings))
        self.query_one(ChatPanel).append_pipeline(
            f"Pre-flight: {e.topic} ({e.domain}/{e.template}) — {len(e.headings)} headings, ~{e.target_words} words"
        )

    def _on_manifest_written(self, e: ev.ManifestWritten) -> None:
        self.query_one(ChatPanel).append_pipeline(f"Manifest written: {e.slug} ({e.expected_count} chunks)")

    def _on_section_started(self, e: ev.SectionStarted) -> None:
        self.query_one(MetadataPanel).grid.started(e)

    def _on_section_completed(self, e: ev.SectionCompleted) -> None:
        meta = self.query_one(MetadataPanel)
        meta.grid.completed(e)
        meta.stats.mark_section_done()
        meta.stats.add_words(e.words)
        self.query_one(ChatPanel).append_pipeline(f"  [{e.index}] {e.heading} — {e.words} words ({e.elapsed:.1f}s)")

    def _on_section_failed(self, e: ev.SectionFailed) -> None:
        self.query_one(MetadataPanel).grid.failed(e)
        if e.will_retry:
            self.query_one(ChatPanel).append_error(f"  [{e.index}] {e.heading} failed, retrying...")
        else:
            self.query_one(ChatPanel).append_error(f"  [{e.index}] {e.heading} FAILED: {e.error}")

    def _on_stage_entered(self, e: ev.StageEntered) -> None:
        self.query_one(MetadataPanel).tracker.set_stage(e.stage)
        self.query_one(ChatPanel).append_pipeline(f"--- Stage: {e.stage} ---")

    def _on_stage_completed(self, e: ev.StageCompleted) -> None:
        self.query_one(MetadataPanel).tracker.mark_done(e.stage)

    def _on_tool_invoked(self, e: ev.ToolInvoked) -> None:
        self.query_one(MetadataPanel).stats.inc_tool()
        self.query_one(ChatPanel).append_pipeline(f"  Tool: {e.name} [{e.source}]")

    def _on_tool_returned(self, e: ev.ToolReturned) -> None:
        status = "OK" if e.ok else "FAIL"
        self.query_one(ChatPanel).append_pipeline(f"  Tool done: {e.name} {status} ({e.elapsed:.1f}s)")

    def _on_wordcount_checked(self, e: ev.WordCountChecked) -> None:
        if e.verdict == "fail":
            self.query_one(ChatPanel).append_error(f"Word count: {e.actual}/{e.minimum} — below target")
        else:
            self.query_one(ChatPanel).append_pipeline(f"Word count: {e.actual} — OK")

    def _on_tags_proposed(self, e: ev.TagsProposed) -> None:
        self.query_one(MetadataPanel).stats.set_tags(list(e.tags))

    def _on_tags_validated(self, e: ev.TagsValidated) -> None:
        if e.verdict == "fail":
            self.query_one(ChatPanel).append_error(f"Tag validation: {e.message}")
        else:
            self.query_one(ChatPanel).append_pipeline(f"Tags accepted: {', '.join(e.accepted)}")

    def _on_link_candidates_found(self, e: ev.LinkCandidatesFound) -> None:
        self.query_one(ChatPanel).append_pipeline(f"Link candidates: {e.count}")

    def _on_moc_updated(self, e: ev.MocUpdated) -> None:
        self.query_one(ChatPanel).append_pipeline(f"MOC: {e.result}")

    def _on_note_written(self, e: ev.NoteWritten) -> None:
        self.query_one(ChatPanel).append_pipeline(f"Note written: {e.path} ({e.words} words)")

    def _on_run_failed(self, e: ev.RunFailed) -> None:
        stage = f" [{e.stage}]" if e.stage else ""
        self.query_one(ChatPanel).append_error(f"RUN FAILED{stage}: {e.error}")

    def _on_run_complete(self, e: ev.RunComplete) -> None:
        self.query_one(ChatPanel).append_assistant(
            f"Done! {e.summary}\n{e.total_words} words in {e.elapsed:.1f}s"
        )

    def _on_log_message(self, e: ev.LogMessage) -> None:
        if e.level in ("warning", "error"):
            self.query_one(ChatPanel).append_error(f"[{e.level}] {e.text}")
        else:
            self.query_one(ChatPanel).append_pipeline(f"[{e.level}] {e.text}")
