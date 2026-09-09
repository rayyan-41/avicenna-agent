# MAP: tui/src/bridge/

> The wire, and nothing else. This directory owns the contract with
> `python -m avicenna.bridge` and the translation of what comes back into
> shapes the render layer can draw. Nothing here imports React, OpenTUI, or
> any renderer; nothing above it imports a child process. That split is what
> lets the entire event vocabulary be tested without a terminal.

**Depends on:** `node:child_process` (client only) · **Depended on by:** `tui/src/state/`, `tui/src/components/`, `scripts/check_protocol_parity.py`
**Reads:** child-process stdout (NDJSON), child-process stderr (diagnostics) · **Writes:** child-process stdin (NDJSON requests)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `protocol.ts` | 197 | The wire contract, mirroring `avicenna/events.py` and `avicenna/bridge/server.py`. Declares `EventName` (the union of all 27 event names), the frame types, the `STAGES` list, every typed method result, and the `BridgeClient` interface. `PROTOCOL_VERSION` is compared at handshake, because the constant existed on both sides and was checked by neither until a version bump would have been silently ignored. `BridgeClient` is an interface rather than a class so the render layer can be built and tested against a fake. |
| `translate.ts` | 312 | Pipeline events into drawable state. Pure — no React, no I/O, no renderer — which is what makes the whole vocabulary testable headlessly. `applyEvent` switches over `EventName` with a `never` check so the compiler points at a missing case, and `scripts/check_protocol_parity.py` reads these `case` labels as the second half of its gate. Splits what the interface shows: the run's *sequence* (stages, sections) from its *decisions* (routing, tags, links), which is the text-block-versus-margin distinction the design is built on. |
<!-- map:files:end -->

## Invariants

- **Field names on the wire are `snake_case`.** The bridge serialises with
  `dataclasses.asdict` (`avicenna/bridge/protocol.py:49`), which keeps Python's
  own field names. So `target_words`, not `targetWords`. Getting this wrong
  fails silently: the field reads as `undefined` and renders as a zero.
- `translate.ts` stays pure. The moment it needs a renderer, the parity gate
  stops being runnable outside a terminal and the event vocabulary stops being
  testable.
- A non-JSON line on stdout is a fatal desync, not a line to skip. The old
  `bridge.ts` logged and continued; that was the defect, not the design.

## Entry points

- To add an event: dataclass in `avicenna/events.py`, name in `EventName`
  here, `case` in `translate.ts`. `scripts/check_protocol_parity.py` fails the
  build if you skip a step.

## See also

- `../MAP.md` — the frontend tree
- `../../../avicenna/bridge/MAP.md` — the other half of this protocol
