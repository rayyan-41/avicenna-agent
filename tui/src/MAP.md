# MAP: tui/src/

> The runtime source for the Avicenna terminal frontend. Ten modules split
> cleanly by concern: the process bridge owns the child process and the wire;
> the app owns state, key dispatch, event translation and the frame; and six
> small modules handle rendering, input decoding, text measurement, command
> parsing, and escape-sequence encoding. No module imports a UI toolkit; no
> module reaches past the bridge protocol into backend internals.

**Depends on:** `node:child_process`, `node:events`, `node:fs`, `node:path`, `node:url` · **Depended on by:** `tui/test/` imports the compiled JS from `dist/`
**Reads:** stdin (raw bytes), child-process stdout (NDJSON) · **Writes:** stdout (alt-screen frames), stderr (uncaught exceptions)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `ansi.ts` | 112 | Escape sequences and colour-depth detection. The only module that knows what the bytes mean. Detects truecolour, xterm-256, or `NO_COLOR`/`dumb` once at startup. Exports `fg()`, `bg()`, `strip()`, cursor movement, and the alt-screen/paste sequences. The CI "Frontend stays unstyled" gate scans every other `.ts` file for raw SGR escapes to enforce that all colour flows through this module. |
| `app.ts` | 1165 | The application skeleton. Owns the transcript, the onboarding state machine, the slash-command dispatcher, the busy/run state, and the event translator. `onEvent()` switches over `EventName` with a `never` exhaustiveness check so the compiler points at a missing event case. `render()` stacks transcript, completions, input rows and one status line into a single frame. Every piece of output flows through `write()`. |
| `bridge.ts` | 368 | Client for the Python backend. Spawns `python -m avicenna.bridge` as a child process, frames stdout as newline-delimited JSON, correlates request/response by id, emits events on an `EventEmitter`, and captures stderr for `/diagnostics`. Per-method timeout budgets prevent a stalled backend from hanging the interface. Prepend the project root to `PYTHONPATH` so the frontend works from any directory. |
| `commands.ts` | 69 | The slash-command catalogue and prefix completion. `COMMANDS` is the single source of truth for the palette, the help screen, and the dispatcher — the three cannot disagree. `complete()` returns prefix-first, then substring matches. `parse()` lowercases the command name but preserves argument casing. |
| `composer.ts` | 249 | The edit buffer. Holds the text, the caret, and a 200-entry history ring. Applies editing keys (word movement, line kill, newline on alt+enter). `layout()` wraps the buffer to a column budget and reports the caret position in display coordinates so the renderer can place the terminal cursor. No chrome lives here — no prompt glyph, no border, no colour. |
| `keys.ts` | 164 | Raw-mode key decoding. Turns a byte stream into discrete `Key` events: CSI sequences for arrows and paging, modifier parameters (shift/alt/ctrl), C0 control characters back to their letter, bracketed paste as a single key with a `paste` flag, and full codepoint consumption so astral characters survive. |
| `main.ts` | 171 | Entry point. Parses CLI args, resolves the Python interpreter (preferring a local `.venv`), spawns the `Bridge`, creates the `App` and `Screen`, installs signal and crash handlers, and starts the event loop. Everything that can fail before the alt screen opens is reported as plain text on the normal buffer. |
| `protocol.ts` | 157 | The wire contract — mirrors `avicenna/events.py` and `avicenna/bridge/server.py`. Declares `EventName` (the union of all event names), `EventFrame`, `Frame`, the `STAGES` list, and every typed result interface (`HelloResult`, `VaultInfo`, `RunHandle`, etc.). `PROTOCOL_VERSION` is checked at handshake; a mismatch rejects startup with a clear message. `App.onEvent`'s `never` check depends on `EventName` being a union, not a string. |
| `screen.ts` | 125 | Alt-screen lifecycle and the differential frame renderer. `render()` compares each row against the previous frame and writes only changed rows plus cursor placement. `start()`/`stop()` manage the alt screen, bracketed paste, and cursor visibility. `invalidate()` forces a full repaint on resize. |
| `text.ts` | 185 | Display-width measurement, word-wrapping, truncation, and padding. Every layout decision uses display columns: CJK = 2, combining mark = 0, escape sequence = 0. `--ascii` (or `AVICENNA_ASCII=1`) restricts output to ASCII for legacy consoles — it is a capability flag, not a style choice, and lives here because measurement is what depends on it. |
<!-- map:files:end -->

## Invariants

- **The skeleton emits no escape codes.** `ansi.ts` can encode colour, but nothing imports `fg()` or `bg()` in the current codebase. The CI gate "Frontend stays unstyled" (`ci.yml`, `tui` job) runs `grep -rnE '\\x1b\[[0-9;]*m|\\u001b\[[0-9;]*m' tui/src --include=*.ts` excluding `ansi.ts` and fails on any match. Do not put raw SGR codes in any file other than `ansi.ts`.
- **`App.onEvent` is exhaustive over `EventName`.** The `default` branch assigns `frame.event` to `never`. Adding an event to `protocol.ts` without a case in the switch produces a type error at compile time, not a silent drop at runtime.
- **Rendering is pull-based.** Nothing draws directly — handlers mutate state and call `requestRender()`, and one `setImmediate` coalesces a burst of changes into a single frame. Do not call `screen.render()` from an event handler.
- **`protocol.ts` mirrors `avicenna/events.py`.** `scripts/check_protocol_parity.py` compares the two and fails the build on drift. When adding an event, update both files.
- **Display columns, not `String.length`.** CJK glyphs are 2 columns, combining marks 0, escape sequences 0. Using `String.length` anywhere that touches the right edge of a line is a bug visible the moment someone pastes an accented name.
- **The project root goes on `PYTHONPATH`.** `Bridge.start()` prepends it so the backend is importable from any working directory, not just a repo checkout.

## Entry points

- To change what the screen looks like, start at `app.ts:1067` (`render()`).
- To change what events display, start at `app.ts:903` (`onEvent()`).
- To change the keyboard bindings, start at `app.ts:243` (`onKey()`).
- To change how the backend is spawned, start at `bridge.ts:101` (`start()`).
- To add a new event: dataclass in `avicenna/events.py`, name in `protocol.ts:39`, case in `app.ts:917`.
- To change colour encoding or depth detection, start at `ansi.ts`.

## See also

- `../MAP.md` — the `tui/` directory, build scripts, CI job config.
- `../test/MAP.md` — the test suite, which imports compiled JS from `dist/`.
- `../../CLAUDE.md` — the seam list where a visual design layer attaches (`write()`, `transcriptLines()`, `render()`, `status()`, `composer.layout()`).
