# Avicenna — terminal interface

The TypeScript frontend for the Avicenna agent harness. It renders the interface
and owns every keystroke; it runs no agent logic of its own. All work happens in
the Python backend, reached over a newline-delimited JSON protocol on stdio.

> **The visual design has been removed on purpose.** What is here is the
> skeleton: the process bridge, the wire contract, the frame renderer, key
> decoding, width measurement, the edit buffer, the command catalogue, and an
> unstyled translator from pipeline events to plain text. There is no palette,
> no glyph set, no wordmark, no boxes and no overlays. The aesthetic is being
> rebuilt from scratch; build it as a layer on top of this, not by restoring
> what was deleted.

## Build

```bash
npm install
npm run build     # -> dist/main.js
npm test          # builds, then runs node:test
npm run typecheck
```

Launch through the CLI rather than directly — `avicenna` resolves the
interpreter and the entry point for you:

```bash
avicenna --vault ~/my-vault
```

## Layout

| File | Responsibility |
| --- | --- |
| `main.ts` | Argument parsing, interpreter resolution, startup failure reporting |
| `app.ts` | State, key handling, event translation, dispatch, the minimal frame |
| `bridge.ts` | Child process, framing, request/response correlation |
| `protocol.ts` | The wire contract — mirrors `avicenna/events.py` |
| `screen.ts` | Alt-screen lifecycle and the differential frame renderer |
| `composer.ts` | Edit buffer, caret, history, and wrapping to visual rows |
| `commands.ts` | The slash-command catalogue and prefix completion |
| `keys.ts` | Raw-mode key decoding, including bracketed paste |
| `text.ts` | Display-width measurement, wrapping, truncation, ASCII fallback |
| `ansi.ts` | Escape sequences and colour-depth detection |

## Design notes

**Rendering is pull-based and differential.** Views produce a full array of
lines each frame; `Screen` writes only the rows that changed. Handlers never
draw — they mutate state and request a frame, and one scheduled render coalesces
the lot, so a burst of twenty pipeline events costs one repaint.

**Everything is measured in display columns.** A CJK glyph is two columns, a
combining mark zero, an escape sequence none. Measuring in `String.length`
instead puts the right edge of every line in the wrong place as soon as someone
pastes an accented name.

**Colour is available but unused.** `ansi.ts` still detects depth (truecolour,
nearest xterm-256, or nothing under `NO_COLOR`) and can emit foreground,
background and attribute codes. The skeleton emits none of it. `--ascii` (or
`AVICENNA_ASCII=1`) restricts output to ASCII for legacy consoles, and is a
capability flag rather than a style: it lives in `text.ts` because measurement
is what depends on it.

**The backend's stdout belongs to the protocol.** The Python core prints to
stdout in several places, so the bridge redirects `sys.stdout` to stderr and
writes frames to a private handle. Backend diagnostics are captured and shown by
`/diagnostics` rather than inline, where they would shred the frame.

## Where a design attaches

The seams a visual layer is meant to use, so a redesign does not have to touch
the plumbing:

- **`App.write(text)`** — every piece of output in the app goes through it. A
  richer transcript means giving entries a type here instead of a bare string.
- **`App.transcriptLines()`** — turns transcript entries into wrapped rows. This
  is the one place that decides what a transcript looks like.
- **`App.render()`** — stacks transcript, completion list, input rows and one
  status line, and reports where the caret goes.
- **`App.status()`** — the single status line.
- **`Composer.layout(cols)`** — returns unstyled rows plus a caret row/column.
  Chrome around the input belongs to the caller, not to the composer.
- **`App.onboardingLines()`** — the first-run screen, as plain rows.

## Adding an event

1. Add the dataclass to `avicenna/events.py`. The bridge serialises it
   structurally, so no Python change is needed beyond that.
2. Add its name to `EventName` in `src/protocol.ts`.
3. Add a case to `App.onEvent`. The switch is exhaustive over `EventName`, so
   the compiler will point at the one you still owe it.
