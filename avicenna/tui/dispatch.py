"""Event dispatch table: type[Event] -> bound handler method.

An explicit dict beats singledispatchmethod under
`from __future__ import annotations` on Python 3.10.
"""

from __future__ import annotations

from collections.abc import Callable

from avicenna import events as ev


def build_table(app) -> dict[type[ev.Event], Callable[[ev.Event], None]]:
    """Return a dict mapping every event class to an on_<name> handler."""
    return {
        ev.RunStarted:          app._on_run_started,
        ev.PreflightDeclared:   app._on_preflight_declared,
        ev.ManifestWritten:     app._on_manifest_written,
        ev.SectionStarted:      app._on_section_started,
        ev.SectionCompleted:    app._on_section_completed,
        ev.SectionFailed:       app._on_section_failed,
        ev.StageEntered:        app._on_stage_entered,
        ev.StageCompleted:      app._on_stage_completed,
        ev.ToolInvoked:         app._on_tool_invoked,
        ev.ToolReturned:        app._on_tool_returned,
        ev.WordCountChecked:    app._on_wordcount_checked,
        ev.TagsProposed:        app._on_tags_proposed,
        ev.TagsValidated:       app._on_tags_validated,
        ev.LinkCandidatesFound: app._on_link_candidates_found,
        ev.MocUpdated:          app._on_moc_updated,
        ev.NoteWritten:         app._on_note_written,
        ev.RunFailed:           app._on_run_failed,
        ev.RunComplete:         app._on_run_complete,
        ev.LogMessage:          app._on_log_message,
    }
