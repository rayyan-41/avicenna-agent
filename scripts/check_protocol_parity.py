"""Fail if the two halves of the wire protocol have drifted apart.

The protocol is defined twice, in two languages: event dataclasses in
`avicenna/events.py`, and the `EventName` union in `tui/src/protocol.ts`. The
bridge serialises structurally, which is what makes adding an event cheap — and
also what makes an omission invisible. An event added on the Python side and
forgotten on the TypeScript side crosses the wire, matches no case, and is
dropped in silence.

The frontend has a compile-time `never` check for the switch, but that only
fires once the name is in the union; nothing compared the two files themselves.
This does.

Run directly: `python scripts/check_protocol_parity.py`
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PY = ROOT / "avicenna" / "events.py"
PROTOCOL_TS = ROOT / "tui" / "src" / "protocol.ts"
APP_TS = ROOT / "tui" / "src" / "app.ts"

#: Not an event: the base class every event inherits from.
BASE = "Event"


def python_events() -> set[str]:
    """Every concrete Event subclass declared in events.py."""
    tree = ast.parse(EVENTS_PY.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name == BASE:
            continue
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        if BASE in bases:
            found.add(node.name)
    return found


def typescript_events() -> set[str]:
    """Every member of the EventName union in protocol.ts."""
    source = PROTOCOL_TS.read_text(encoding="utf-8")
    match = re.search(r"export type EventName\s*=(?P<body>.*?);", source, re.DOTALL)
    if match is None:
        sys.exit("could not find `export type EventName` in protocol.ts")
    return set(re.findall(r"'([A-Za-z0-9_]+)'", match.group("body")))


def handled_events() -> set[str]:
    """Every event name with a `case` in the app's event switch."""
    source = APP_TS.read_text(encoding="utf-8")
    return set(re.findall(r"case '([A-Za-z0-9_]+)':", source))


def main() -> int:
    py = python_events()
    ts = typescript_events()
    handled = handled_events()

    problems: list[str] = []
    for name in sorted(py - ts):
        problems.append(
            f"{name}: emitted by events.py, missing from EventName in protocol.ts"
        )
    for name in sorted(ts - py):
        problems.append(
            f"{name}: declared in protocol.ts, has no dataclass in events.py"
        )
    for name in sorted(py & ts - handled):
        problems.append(f"{name}: no `case '{name}':` in app.ts onEvent")

    if problems:
        print("::error::Wire protocol parity check failed.")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nAdding an event means three edits: the dataclass in "
            "avicenna/events.py, the name in EventName in tui/src/protocol.ts, "
            "and a case in App.onEvent."
        )
        return 1

    print(f"Protocol parity OK: {len(py)} events, all declared and all handled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
