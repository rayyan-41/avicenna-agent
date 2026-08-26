"""Wire format for the stdio bridge.

One JSON object per line, in both directions. Newline-delimited rather than
length-prefixed so a human can watch the traffic with a pipe and read it.

    frontend -> backend   {"type":"req","id":"7","method":"run.note","params":{}}
    backend  -> frontend  {"type":"res","id":"7","ok":true,"result":{}}
                          {"type":"res","id":"7","ok":false,"error":{...}}
                          {"type":"event","event":"SectionCompleted","data":{}}

Events are the avicenna.events dataclasses, serialised structurally: the class
name becomes `event` and the fields become `data`. The frontend therefore never
needs a hand-maintained copy of the taxonomy beyond its type declarations, and
adding an event to events.py surfaces it without touching this file.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1


def _plain(value: Any) -> Any:
    """Make an arbitrary value JSON-safe without losing its shape."""
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def encode(payload: dict[str, Any]) -> str:
    """One line of wire traffic. Never raises on odd values."""
    return json.dumps(_plain(payload), ensure_ascii=False, separators=(",", ":"))


def event_frame(event: Any) -> dict[str, Any]:
    """An avicenna.events dataclass as a wire frame."""
    data = {k: _plain(v) for k, v in dataclasses.asdict(event).items()}
    return {
        "type": "event",
        "event": type(event).__name__,
        "runId": data.pop("run_id", ""),
        "seq": data.pop("seq", 0),
        "ts": data.pop("ts", 0.0),
        "data": data,
    }


def ok_frame(req_id: str, result: Any) -> dict[str, Any]:
    return {"type": "res", "id": req_id, "ok": True, "result": _plain(result)}


def err_frame(req_id: str, message: str, kind: str = "error") -> dict[str, Any]:
    return {
        "type": "res", "id": req_id, "ok": False,
        "error": {"kind": kind, "message": message},
    }


__all__ = [
    "PROTOCOL_VERSION", "encode", "event_frame", "ok_frame", "err_frame",
]
