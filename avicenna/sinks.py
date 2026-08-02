"""Event sinks.

JsonlSink writes one flushed JSON line per event; ConsoleSink
formats events for headless mode. Both consume drain(queue) and
terminate on the None sentinel.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import TextIO

from avicenna.events import Event


class JsonlSink:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f: TextIO = open(path, "w", encoding="utf-8", newline="\n")

    def write_event(self, event: Event) -> None:
        record: dict = {"type": type(event).__name__}
        record.update(dataclasses.asdict(event))
        self._f.write(json.dumps(record, default=str) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


class ConsoleSink:
    def handle(self, event: Event) -> str | None:
        name = type(event).__name__
        try:
            return f"[{name}] {event!r}"
        except Exception:
            return f"[{name}]"
