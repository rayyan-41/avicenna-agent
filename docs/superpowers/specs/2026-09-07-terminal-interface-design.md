# The terminal interface — design

Status: proposed 2026-09-07.

Design only. Implementation waits for the event taxonomy to close (graph-driven
linking is the last thing that adds events) and for the pipeline to produce a
green matrix. The purpose of designing first is that it tells the backend what
to emit, and an event is cheapest to add while the stage that would emit it is
already open.

## What this interface is for

The user has one job: supply a topic.

    write a note on Jean Jacques Rousseau and how he can be considered
    a pillar of nationalism

Everything else is consequence. So the interface has three jobs, in this order:
take one line of input, make a long concurrent run legible, and show what the
harness decided. A fourth — recovery — matters the moment a run fails, which it
will.

## Why this is not chrome

For most tools a terminal UI is polish over a CLI. Here one part of it is the
product.

The registry records where the reader's attention has gone: themes accumulate,
and a genuinely new one means they have entered territory they have not read
before. **That only exists if it can be seen.** A theme registry nobody looks at
is a database. The moment the harness says *nationalism is new — you have not
read here before* is the feature, not a status line.

The same holds for the other decisions. Which domain it routed to and what it
nearly chose instead. Which tags were accepted and which were assigned
mechanically because the tagger failed. Which links resolved against real notes
and which were discarded as invented. Those are the harness's judgements about
the user's own thinking, and they should be legible without reading a log.

## The prime directive applies here

`CLAUDE.md` is explicit that features which make Avicenna a better general
assistant and worse at connected notes are regressions however well built. A
terminal interface is the easiest place in this codebase to violate that: a chat
pane invites conversation, and conversation is what this program is not.

So there is no chat. The input is a topic, not a message. The interface never
asks the user to make a decision the harness should make — a new theme is
reported, never held for approval, because blocking on that would make the user
a bottleneck again.

## The waiting problem

A run is two to twenty minutes. Most of that is section generation, and sections
run concurrently — a forty-heading note is forty-plus calls in flight. A
scrolling log is the wrong shape for concurrency: interleaved lines from
parallel work read as noise, and the reader cannot tell what is finished from
what is stuck.

**The outline is the progress display.** Pre-flight declares the structure up
front — that is already how the pipeline works, and it is the thing AGENTS.md
says the program is for. One line per heading, each carrying its own state:
pending, writing, written with its word count, or failed. Forty lines that
change in place, rather than four hundred lines that scroll past.

That gives the reader the two things a log cannot: the shape of the whole note
before it exists, and which specific heading is slow.

## Progress is transient; decisions are the record

These are different kinds of information and should not share a surface.

Progress answers *what is happening now* and is worthless once it has happened —
a section that is writing becomes a section that is written, and the intermediate
state has no value afterwards. It belongs in the outline, in place.

Decisions answer *what did it conclude*, and they are worth reading after the
run is over. Routing, tag validation, minted themes, resolved and discarded
links. They accumulate rather than replace, and they are what the user reviews
when deciding whether to trust a note.

## Three surfaces

**Compose.** One line. The topic. Nothing else on screen competes with it. This
is the whole input surface of the product, and it should look like it.

**Run.** The topic and the routed domain at the top — routing is the first
decision and everything downstream depends on it. Then the outline, filling in.
Then the decisions, accumulating. The run surface should be readable at a glance
from across a desk: how far along, anything failed, anything surprising.

**Map.** The registry as a view rather than as events: how many themes the
reader has accumulated, which are recent, which regions are dense and which are
single notes. This is the map-of-the-mind idea made visible, and it is the one
surface that is worth opening when no run is happening at all.

## Failure and recovery

Failure is normal here: a provider rate-limits, a key is bad, a section times
out, a tool is missing. The interface should distinguish three cases the
pipeline already distinguishes internally, and never present them identically:

- **Degraded but complete** — a vault tool was absent and the stage said so. The
  note exists and is fine. This is not an error and must not look like one.
- **Partial** — some sections failed, the note was written from the rest.
  The reader needs to know which headings are missing.
- **Interrupted** — the run stopped with chunks on disk. `_tmp` survives
  deliberately so `--resume` works. The interface should say so and offer the
  resume, because a user who does not know resume exists will regenerate from
  scratch and pay twice.

## Events the design requires that do not exist yet

This is the reason to design before building the rest of the backend. Each of
these is cheap to emit now and expensive to retrofit.

1. **Routing rationale.** `PreflightDeclared` carries the chosen domain but not
   what it nearly chose. The runner-up and the margin are what let a reader
   judge a questionable route — and routing has already been wrong in ways that
   were invisible until a note landed in the wrong folder.
2. **A typed link-resolution result.** T29 emits kept and dropped counts through
   `LogMessage`. The interface wants a typed event carrying both counts and a
   few examples of what was discarded, because "the model invented nine links"
   is exactly the sort of thing a user should see without reading warnings.
3. **The near-miss on a mint.** `ThemeMinted` says a theme is new. The
   interesting part is what it was nearest to and by how much — *minted
   `nationalism`; closest existing `political-philosophy` at 0.61*. Without it a
   user cannot tell a genuinely new region from a threshold that is set wrong.
4. **Registry totals.** How many themes exist and how many are new this run.
   `avicenna doctor` has this; the interface needs it per run.
5. **Resume availability.** After a failure, whether resumable chunks exist and
   how many. Nothing currently says this.
6. **Mechanical tag assignment as a distinct signal.** The floor emits a
   `LogMessage` warning today. It deserves to be visible as a decision, because
   a note tagged mechanically is one the user may want to correct.

## Constraints inherited from the skeleton

`tui/README.md` records that the visual design was removed deliberately and that
a new one must be built as a layer on top of the skeleton, not by restoring what
was deleted. The skeleton already provides the process bridge, the wire
protocol, an alt-screen differential renderer, raw key decoding, display-width
measurement, the edit buffer, the command catalogue, and an unstyled event
translator.

So this design attaches at the translator and above. It does not touch the
transport, and it does not reintroduce the box-drawing and panel system that was
stripped.

Three practical constraints the renderer imposes:

- **Display width, not string length.** `text.ts` exists because the vault's
  content is not ASCII — transliterated Arabic, em dashes, quotation marks.
  Anything that aligns columns must measure, not count.
- **Differential rendering.** The outline updates in place, so a frame is a
  diff. A design that reflows the whole screen on every event will flicker.
- **The terminal may be narrow.** Forty headings and long topics; the outline
  must degrade to something legible at eighty columns.

## What this design does not settle

**The aesthetic.** Palette, glyphs, a wordmark, how a heading in flight is
distinguished from one that is done — none of that is decided here, and it
should be decided by looking at something rather than by reading a document.

**Whether the map surface is a view or a command.** A registry view might be a
mode in the interface or might be `avicenna map` on the CLI. The CLI is the only
functional surface today, so the content matters more than the placement.

## Sequencing

1. Verify the pipeline: a green matrix, twice.
2. Emit the six missing events above, as part of the backend work already
   scheduled — the semantic guard and graph-driven linking both touch the
   stages that would emit four of them.
3. Close the event taxonomy when graph linking lands.
4. Then build, as a layer on the skeleton.

Building the interface before step 3 means rendering an incomplete vocabulary.
Building it before step 1 means polishing a pipeline that is not yet known to
work, which is the failure the prime directive warns about in its own words: a
better-looking assistant that is worse at connected notes.
