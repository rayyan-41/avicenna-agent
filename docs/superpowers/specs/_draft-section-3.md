## Section 3 — the face

The face is the illuminated headpiece: it opens the page when idle and retreats
into the margin once there is text to gloss. It is also the only animated
element in the interface. There are no spinners, no progress bars, no pulsing
dots anywhere else. Every other piece of motion in the design is a state glyph
changing once (`U+2713` done, `U+25B8` running, `U+00B7` pending). The face is
the one orchestrated moment, and it is load-bearing: nothing in the codebase
streams, so every chat reply arrives whole after a silent pause, and the face is
what covers that pause. If the face fails to convey that the system is working,
the interface feels broken during every interaction.

### a. How the image becomes terminal cells

The source image (`avicenna.png`, 1024×1024, RGB) is effectively two-tone.
Verified measurements: 64.5% of pixels are pure `#000000`; a further 16.7% are
near-black JPEG compression artifacts (values like `#000100`, `#010000`) that
are visually indistinguishable from black. The remaining 18.8% are a single
green averaging `#0BB926`, with the ten most common values all falling within
`#0BB_26`–`#0CBD27`. There is no mid-tone, no anti-aliased edge, no gradient.
A luminance ramp (` .:;+*#@`) would therefore invent shading that is not in the
source: it would map the JPEG noise floor to visible grey speckle and give the
face a texture it does not have.

**Half-block rendering with two colours is correct.** Each terminal cell
contains two vertical pixels from the resampled image. The mapping:

| Top pixel | Bottom pixel | Cell character | Foreground |
| --- | --- | --- | --- |
| lit | lit | `U+2588` (full block) | `phosphor` |
| lit | dark | `U+2580` (upper half block) | `phosphor` |
| dark | lit | `U+2584` (lower half block) | `phosphor` |
| dark | dark | `U+0020` (space) | n/a (ink ground shows through) |

The foreground is always `phosphor` (`#0BBA26`) or absent; the background is
always `ink` (`#000000`). No cell carries both foreground and background colour
because no cell straddles the silhouette boundary in a way that would require
it — the source has no anti-aliased edges.

**The pipeline, specified precisely:**

1. **Crop.** The content bounding box within the source is (204, 88, 788, 964)
   — verified as (202, 86, 789, 965) with a 2-pixel tolerance for JPEG edge
   artefacts. This yields a content region of 584×876 pixels, a portrait aspect
   ratio of 0.667. Rendering this region square (say, 34×34 cells) distorts the
   face: the jaw stretches, the forehead compresses. The aspect ratio must be
   preserved.

2. **Resample.** Resize the cropped region to the target cell width, with the
   height calculated to preserve aspect ratio and produce an even number of
   pixel rows (since two rows become one cell row):
   `rows = round(width × (876 / 584) / 2)`. The resampling filter is Lanczos
   (Lanczos3). Nearest-neighbour produces aliasing at small sizes; bilinear
   blurs the silhouette edge. Lanczos preserves the sharp boundary the source
   already has.

3. **Threshold.** A pixel is "lit" if its luminance exceeds 60 (Rec. 709
   coefficients: `0.2126R + 0.7152G + 0.0722B > 60`). This is a perceptual
   threshold, not a channel check: it correctly classifies the near-black JPEG
   artefacts as dark and the green silhouette as lit, without needing to know
   the palette in advance.

4. **Cell assignment.** For each column in each pair of rows, apply the table
   above. Empty columns (all cells in a column are spaces) are trimmed so the
   face pins to its column edge rather than floating with leading whitespace.

**Why half-blocks rather than a ramp.** A ramp maps luminance to glyph density,
which is the right tool for photographs and gradients. The source has neither.
It has exactly two values, and the ramp would spread them across10 or16 levels,
inventing detail that a viewer would then try to interpret. Half-blocks with
two colours give a lossless representation of a two-tone source at double the
vertical resolution of full-block-only rendering.

**Why the portrait aspect ratio matters.** The content box is 584 wide and 876
tall — a portrait aspect of 0.667. At34 cells wide, the face is34×26 cells. If
rendered as34×34 (square), the face would be stretched vertically by31%, turning
the oval head into an egg and the narrow jaw into a rectangle. The aspect ratio
is part of the face's identity; discarding it discards the silhouette.

**Degradation under reduced colour capability.**

- **256 colours.** The16 ANSI colours plus their bright variants map to256 via
  the6×6×6 colour cube. `#0BBA26` lands on cube index (0, 5, 2), which is
  `#00AF5F` — recognisably green, shifted toward teal. The face remains
  legible. The palette tokens `leaf`, `oxide` and `gloss` similarly land on
  their nearest cube neighbours; the design weakens but holds.

- **16 colours.** ANSI green (colour2) is the only candidate for `phosphor`.
  Its exact value varies by terminal theme — it may be `#00AA00`, `#00CD00`,
  or something else entirely. The face remains a recognisable green shape on
  black. The rest of the palette collapses: `page`, `gloss` and `leaf` all
  compete for the same yellow/brown slots, and `oxide` may land on the same
  red as an error glyph. The documented fallback is that speaker labels and
  rubricated words gain the only casing in the design (the shared context
  specifies this).

- **`NO_COLOR`.** The face renders as Unicode half-blocks with no colour escape
  sequences. Every cell is the terminal's default foreground on its default
  background. The silhouette is still visible — half-blocks give double
  vertical resolution — but it is monochrome and relies on the terminal's
  contrast ratio between foreground and background. On a light-theme terminal
  the face inverts (green-on-black becomes foreground-on-background, which may
  be dark-on-light). This is the expected cost of `NO_COLOR`; the design does
  not attempt to compensate.

### b. Where the frame data lives and what generates it

This is the part where a naive design goes wrong, and the failure mode of each
option is worth recording.

**The three options.**

1. **Commit only the generated output.** The frontend loads a JSON file
   containing pre-rendered frame data. No generator is checked in.

   *Failure mode.* When the source image changes — a new logo, a revised
   silhouette, a palette adjustment — the next person has a blob and no way to
   regenerate it. They must reverse-engineer the rendering pipeline from the
   spec and reimplement it. If the spec is ambiguous (and it will be, two years
   from now), they will produce a different result and not know whether the
   difference matters.

2. **Generate at build time in `tui/`.** A build step in `package.json` runs a
   script that reads `avicenna.png` and emits the JSON. The committed repo
   contains the generator and the source image; the built output is in
   `dist/` or similar.

   *Failure mode.* The frontend is TypeScript on Bun. Its only Python is the
   bridge subprocess; it has no image-processing library. Adding Sharp or
   `@napi-rs/image` as a build dependency for one file is disproportionate, and
   installing a native addon in CI adds a platform-specific compilation step
   that the current `tui/` job (ubuntu-latest, npm ci) does not have. More
   importantly, the generator needs to run on the developer's machine too —
   during design iteration, during palette changes, during testing — and
   requiring a full `tui/` build to regenerate a static asset couples two
   concerns that have no reason to share a lifecycle.

3. **Commit the generator script and its output, with a CI gate that fails if
   they disagree.** The generator is a Python script in `scripts/` that reads
   `avicenna.png` and writes the JSON. The JSON is committed alongside it. CI
   regenerates the JSON and compares it to the committed version; a diff fails
   the build.

   *Failure mode.* The generator needs Pillow, which is not currently a dev
   dependency. Adding it is one line in `pyproject.toml` under `[dev]`. If
   Pillow is absent, the gate fails — which is the correct behaviour: it means
   someone changed the image without regenerating, and the gate catches it.

**Recommendation: option 3.** It preserves reproducibility (the generator is
the source of truth), it keeps the frontend clean (TypeScript loads a JSON
file, no image processing), and it catches drift at the same point in CI that
catches every other form of drift.

**The generator script.** `scripts/generate_face_frames.py`. It reads
`avicenna.png` from the repository root, crops to the content bounding box,
resamples to each declared size, applies the threshold and half-block pipeline
from §3a, and writes the output. It takes no arguments; the sizes and
parameters are constants in the script, matching this spec. Running it
idempotently overwrites the output file. The script must declare
`from __future__ import annotations` at the top, per the repository convention.

**The output file.** `tui/src/components/face-frames.generated.json`. Section 1
of this spec names this path provisionally; it is accepted here. The file
contains:

```json
{
  "meta": {
    "source": "avicenna.png",
    "crop": [204, 88, 788, 964],
    "threshold": 60,
    "generator": "scripts/generate_face_frames.py"
  },
  "sizes": {
    "large": {
      "cellWidth": 34,
      "cellHeight": 26,
      "rows": ["██  ████...", "..."]
    },
    "small": {
      "cellWidth": 22,
      "cellHeight": 16,
      "rows": ["██  ████...", "..."]
    }
  }
}
```

Each row string contains the half-block characters (`U+2588`, `U+2580`,
`U+2584`, `U+0020`) for that row. The frontend applies `phosphor` as the
foreground colour to every non-space character. The `meta` block records the
parameters that produced the file, so a reader can verify the provenance
without reading the generator.

**The CI gate.** A new step in the `hygiene` job, after the existing MAP.md
check:

```yaml
- name: Face frames are up to date
  shell: pwsh
  run: |
    python scripts/generate_face_frames.py --check
```

The `--check` flag regenerates the JSON to a temporary path and compares it
byte-for-byte to the committed file. If they differ, the script exits 1 and
prints the diff. The gate is in `hygiene` because it operates on source files,
not on runtime behaviour, and because `hygiene` already runs on `ubuntu-latest`
with Python available.

Pillow is added to `[dev]` in `pyproject.toml` (one line: `"Pillow>=10.0"`).
It is not a runtime dependency; it is needed only by the generator and by the
gate.

**Rejected alternative: a gate that checks only file hash.** A simpler gate
would hash the committed JSON and compare it to a hash stored in the script.
This fails when the JSON is regenerated with a different serialiser version or
whitespace convention. Byte-for-byte comparison of the regenerated output is
strict and unambiguous.

### c. The eyes

**There are no isolable pupils in the source.** Verified: scanning the eye band
(36%–55% of face height, y=402 to y=569 in the content region) for dark pixels
surrounded on all eight sides by green found zero candidates. The eye band row
analysis confirms the structure: the eyes are open notches in the green
silhouette, connected to the black background. At y=417–447 the pattern is
three green blocks (each ~37 source pixels wide) separated by two dark gaps
(~109 and ~146 pixels wide). The green blocks are the brow ridge and cheek; the
dark gaps are the eye sockets, open to the background. Lower in the band
(y=452–562), the pattern becomes more complex — the brow, nose bridge, and
cheekbone create ten transitions per row — but the eyes remain open notches,
never enclosed islands.

Eye tracking (decision 4) is therefore **synthesis drawn on top of the mask**,
not existing pixels moved. The design must specify where the synthetic pupils
sit, what they are made of, and how many gaze positions exist.

**Pupil placement.** Two synthetic pupil regions, one per eye, specified as
coordinates relative to the content bounding box so the placement survives a
change of render size:

- **Left eye.** The notch centre is at approximately 38% across the content
  width and 44% down the content height. In the cell grid at34 cells wide, this
  is cell column 13, row 11. At22 cells wide, cell column 8, row 7.

- **Right eye.** The notch centre is at approximately 65% across the content
  width and 44% down the content height. In the cell grid at34 cells wide, this
  is cell column 22, row 11. At22 cells wide, cell column 14, row 7.

These are the centre gaze positions. The pupils shift from here.

**What a pupil is made of.** The eye sockets are ink (black). The face
silhouette is phosphor (green). A pupil drawn in `phosphor` on `ink` is a dot —
a single green cell in a field of black. A pupil drawn in `ink` on `phosphor`
is a hole — a single black cell in a field of green. The eye sockets are ink,
so the pupils are phosphor dots: small green cells placed within the black
socket, creating the impression of an iris looking in a direction.

At the small render size (22 cells wide), each eye socket is approximately 3–4
cells wide. A single-cell pupil therefore occupies roughly one-third of the
socket width, which is proportionally correct for a gaze shift. At the large
size (34 cells wide), each socket is approximately 5–6 cells wide, and the
pupil is one cell — proportionally smaller, but the face is also farther from
the viewer's focal point (it occupies more of the screen).

**Gaze positions.** Five discrete positions, because continuous tracking is not
possible on a cell grid and because fewer than five produces a mechanical
oscillation rather than a natural glance:

| Position | Label | Pupil offset from centre | Appearance |
| --- | --- | --- | --- |
| 0 | far left | −2 cells | Looking at the edge of the terminal |
| 1 | left | −1 cell | Looking at the text block's left margin |
| 2 | centre | 0 cells | Looking at the viewer / forward |
| 3 | right | +1 cell | Looking at the margin gloss |
| 4 | far right | +2 cells | Looking at the terminal edge |

The offset is applied to both pupils simultaneously; cross-eyed states are not
used. At the small render size, positions 0 and 4 may place the pupil at the
edge of the socket or one cell beyond it; in that case the pupil clamps to the
socket boundary. This is acceptable — a gaze that hits the wall of the socket
reads as a sidelong glance.

**Mapping from caret to gaze.** When the interface is idle and the user is
typing, the caret's horizontal position in the composer maps to a gaze
position. The text block occupies roughly the left 60% of the terminal width;
the mapping divides that span into five bands, one per gaze position. The
mapping is recalculated on each caret move, not on a timer — the eyes snap to
the new position rather than tracking smoothly, because smooth animation
between cell positions would require fractional-cell rendering that
half-blocks do not support.

**When there is no caret to follow.** The eyes default to position 2 (centre).
During a run, when the face is in the margin and the user is not typing, the
eyes shift to position 1 (left) — looking toward the text block where the run
progress is unfolding. This is a fixed offset, not a tracking behaviour: the
eyes do not follow individual stage completions.

**During a run.** The eyes remain at position 1 (left, toward the text block)
for the duration of the run. State changes are conveyed by the animation
vocabulary (§3d), not by eye movement. Moving the eyes during state transitions
would create two competing signals.

**Blinking.** In scope. Every 4–6 seconds (randomised, uniform distribution),
the pupils disappear for 0.15 seconds — the eye sockets return to solid ink.
This is the only periodic animation in the interface. The blink timer is
frontend-only (a `setInterval` in the face component); it does not involve the
backend or the event stream. Blinking is disabled when the terminal signals
reduced-motion preference: the implementation checks for the `NO_COLOR`
environment variable as a proxy for minimal terminal capability, and also for a
dedicated `AVICENNA_REDUCED_MOTION` variable. When either is set, the pupils
remain static. This is a graceful degradation — the face still works, it simply
does not blink.

**If eye tracking is not worth building.** The case against is that at 22 cells
wide, a single-cell pupil shift is a 3-pixel movement on a 1080p monitor —
barely perceptible, and possibly distracting if the user's eyes are on the text
block rather than the face. The case for is that the face is the interface's
one animated element and the eyes are what make it a presence rather than a
logo. Decision 4 specifies both eye tracking and state animation; this design
honours both. If implementation reveals that the small-form pupil shifts are
unreadable, the fallback is to restrict eye tracking to the large (idle) form
and keep the small form's eyes fixed at centre. That is a reduction, not a
redesign.

### d. The state animation vocabulary

The face has six animation states. Each is triggered by real events from
`avicenna/events.py`; none are invented for the design. The face is the only
animated element in the interface — no spinners, no progress bars, no pulsing
indicators exist anywhere else. A later implementer must not add them.

**The mapping from events to states.**

| State | Trigger(s) | Duration | Visual |
| --- | --- | --- | --- |
| **Idle** | No active run | Until a run starts | Large, centred. Eyes track the caret (§3c). Occasional blink. |
| **Listening** | User sends a message (`chat.submit` called); ends when the response arrives | The silent pause — typically 2–10 seconds | Large, centred. Eyes shift to position 2 (centre). A slow pulse: the face dims from `phosphor` to a 70%-brightness variant over 1.2 seconds and back. This is the only visual feedback that the system heard the user. |
| **Planning** | `RunStarted` fires; ends when `PreflightDeclared` fires | Typically 3–15 seconds | Large, centred (the face has not yet moved to the margin). Eyes shift to position 1 (left, toward the text block). Pulse continues but faster: 0.8-second cycle. |
| **Writing** | `SectionStarted` fires; persists through `SectionCompleted`/`SectionFailed` cycles until `RunComplete` or `RunFailed` | The bulk of the run — 2–20 minutes | Small, in the margin (§3e). Eyes at position 1 (left). The pulse stops — the face is static except for blinking. State transitions within this state (section completed, section failed) are shown in the text block's stage tree, not by face animation. The face's job during a run is to be a calm presence, not to mirror every event. |
| **Complete** | `RunComplete` fires | 3 seconds, then returns to Idle | Small, in the margin. Eyes shift to position 2 (centre) — looking at the user. A single brightening: the face pulses to full brightness once, holds for 0.5 seconds, and settles. |
| **Error** | `RunFailed` fires; also a `SectionFailed` with `will_retry=False` when no sections remain | Until the user dismisses or a new run starts | Small, in the margin. Eyes shift to position 2 (centre). The face does not pulse. The error is communicated by the text block (the `oxide`-coloured failure glyph and message); the face's stillness is the signal — the absence of the pulse that `Listening` and `Planning` use. |

**Why the pulse matters.** Nothing in the codebase streams. `chat.send` is
request/response; `LLMProvider` has no streaming method. A chat reply arrives
whole after a silent pause of2–10 seconds. A generation run begins with a
`PlanApprovalRequested` event that may take15 seconds to arrive. During these
pauses, the face is the only indication that the system is working. The pulse
animation — a slow, rhythmic dimming and brightening — fills that silence. It
is not decorative; it is the interface's equivalent of a typing indicator. If
the pulse is removed, every silent pause becomes a freeze.

**Why the face does not animate during `Writing`.** A run fires dozens of events
per minute — `SectionStarted`, `ToolInvoked`, `ToolReturned`,
`SectionCompleted`, `StageEntered`, `StageCompleted`. Mirroring these on the
face would create a strobe effect that competes with the stage tree in the text
block, which is the actual progress display. The face's role during a run is to
be still: a calm presence in the margin that says "I am here" without saying
"look at me." The stage tree does the talking.

**The one orchestrated moment.** The face is the interface's single animated
element. There are no spinners in the status bar, no pulsing dots in the
composer, no loading indicators on the confirm dialog. Every other piece of
motion is a discrete state change: a glyph appearing, a colour switching, a
line being appended. The face's pulse is the only continuous animation, and it
exists only during the two states (`Listening`, `Planning`) where the user has
no other feedback.

**Interaction with reduced motion.** When `NO_COLOR` or
`AVICENNA_REDUCED_MOTION` is set, all continuous animation is disabled: no
pulse, no blink. The face still changes state (large/small, centre/margin,
different eye positions), because those are discrete transitions rather than
continuous animation. The `Listening` state, which relies on the pulse for
feedback, falls back to a single brightness change: the face brightens when the
state enters and dims when it leaves, with no cycling.

### e. The large-to-small transition

Decision 10: the face is persistent, large and centred when idle, small in the
margin during a run. The measured legibility floor (verified against the preview
renderer) is that the face reads at34×26 cells and at22×16, and is
unrecognisable at14×10 — below about20 cells wide it stops being a face. A
status-bar thumbnail is therefore not possible.

**The transition is instant.** When a run starts (the user accepts the plan and
`RunStarted` fires), the face moves from centre to margin in a single frame.
There is no animated shrink, no interpolation through intermediate sizes. The
reasons:

1. Intermediate sizes would require pre-rendered frames at every possible
   width, or a runtime resample. Pre-rendering every width from 22 to 34 is13
   frames; runtime resampling violates the principle that the frontend does not
   process images. Neither is justified for a transition that takes 16
   milliseconds.

2. An animated shrink draws the eye to the face during the exact moment the
   eye should be moving to the stage tree. The run has started; the user's
   attention should shift to the text block. A smooth animation that takes0.3
   seconds to complete holds attention on the wrong element for0.3 seconds.

3. The face's role changes discontinuously — from "I am the page" to "I am
   the gloss" — and a discontinuous change in appearance is the honest
   representation of that shift.

**What happens at intermediate sizes.** Nothing. There are no intermediate
sizes. The face is either large (34 cells wide, idle) or small (22 cells wide,
running). If the terminal is resized during a run, the face re-renders at its
current size; it does not interpolate.

**The two-column layout and its minimum width.** The text block occupies56
columns (the `BLOCK` constant from the preview). The margin occupies whatever
remains after the text block, the left rule (`U+258F`, 1 column), and inter-
column spacing (3 columns). The small face (22 cells wide) sits in the margin's
upper portion, with margin annotations (routing, tags, links) beside or below
it.

The minimum terminal width for the two-column layout is therefore:

- Left padding: 2 columns
- Left rule: 1 column
- Text block: 56 columns
- Inter-column gap: 3 columns
- Small face: 22 columns
- Right padding: 1 column
- **Total: 85 columns**

Below 85 columns, the margin cannot hold the face beside the text block. The
fallback is a single-column layout: the face sits above the text block, centred,
and the margin annotations appear below the text block rather than beside it.
The face remains small (22 cells wide) during a run; it does not grow to fill
the available width, because growing it past 34 cells would require a pre-
rendered frame that large, and the face at 34 cells wide in an 80-column
terminal leaves only 46 columns for the text block — too narrow for comfortable
reading.

Below 60 columns (the text block width), the text block itself wraps. This is
a degenerate case — the interface is not designed for 50-column terminals — and
the face is simply omitted. A face that is14 cells wide is mush, and mush is
worse than nothing. The status line in the catchword area still reports the
run state; the face's job is taken over by the stage tree glyphs (`U+2713`,
`U+25B8`, `U+00B7`).

**Summary of fallback tiers.**

| Terminal width | Layout | Face |
| --- | --- | --- |
| ≥ 85 columns | Two-column: text block left, margin right | Small (22×16) in the margin during a run; large (34×26) centred when idle |
| 60–84 columns | Single-column: face above text, annotations below | Small (22×16) above the text block during a run; large (34×26) centred when idle |
| < 60 columns | Single-column, text wraps | No face. Stage tree glyphs carry all state. |

The transition between tiers is also instant: it happens on terminal resize,
and the face simply re-renders or disappears. No animation, no interpolation.
