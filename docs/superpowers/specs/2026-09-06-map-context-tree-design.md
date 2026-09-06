# MAP.md context tree — design

Status: approved 2026-09-06. Supersedes nothing.

## Problem

An agent entering this repository pays for orientation twice: once to find the
directory that owns a concern, and again to read enough source to be sure. A
`Glob` plus four `Read` calls over `avicenna/pipeline/` costs roughly fifteen
thousand tokens and produces an understanding that is thrown away at the end of
the session.

The recurring cost is the target. A per-directory context file that answers
*what is this for, what is in it, what will bite me* lets an agent skip the
reads entirely for every question it can answer from the map, and start from the
right file for every question it cannot.

## The failure mode this design exists to prevent

A map that has drifted from the code is worse than no map, because it is
believed. Documentation that nothing verifies decays silently and is trusted
right up until it causes a wrong edit.

This repository already states the principle for CI: a check that cannot fail
the build is documentation, not a gate. The same standard applies to the maps
themselves. Every MAP.md is therefore split into a region a script can verify
and a region only judgment can write, and the verifiable region is gated.

## Approaches considered

1. **Hand-written prose.** Highest value per token, no drift resistance, cannot
   be checked. Rejected.
2. **Fully generated from docstrings.** Cannot drift, but reproduces
   information already reachable by grep. It would save no meaningful tokens.
   Rejected.
3. **Hybrid, machine-checked inventory plus hand-written judgment.** Adopted.

## Format

Every MAP.md carries, in order:

- an H1 of the form `# MAP: <path>`,
- a one-paragraph statement of the directory's purpose,
- a dependency line naming what the directory depends on and what depends on it,
- a `## Files` section wrapping a table in `<!-- map:files:start -->` and
  `<!-- map:files:end -->` markers, one row per source file: name, approximate
  line count, and a one-line role,
- `## Invariants` — the rules that bite, stated where they apply rather than
  only in the root doctrine,
- `## Entry points` — "to change X, start at `file.py:NN`",
- `## See also` — sibling maps worth reading next.

Line counts inside the table are advisory. They are refreshed by the checker's
`--fix` mode and are not themselves gated, because exact counts would fail the
build on every unrelated edit.

## The gate

`scripts/check_maps.py` enforces three properties and is wired into the CI
`hygiene` job with no `continue-on-error`:

1. **Coverage.** Every tracked directory containing source files has a MAP.md.
   This makes the "one map per directory" rule self-enforcing as the repository
   grows, rather than a convention that erodes.
2. **Inventory parity.** The filename set inside the markers equals the set of
   source files on disk, exactly. A file added without a map row fails the
   build, as does a row naming a file that was deleted.
3. **No placeholders.** A literal `TODO:` inside any MAP.md fails, so `--fix`
   cannot quietly land a row with an unwritten role.

`--fix` adds rows for new files, removes rows for deleted ones, and refreshes
line counts. It deliberately writes new rows with a `TODO:` role, so that a
mechanical fix cannot satisfy the gate on its own; a human or agent must supply
the sentence.

## Coverage

Nineteen maps: the repository root, `avicenna/` and its seven subpackages,
`scripts/`, `tests/` and `tests/fixtures/`, `tui/` and its `src/` and `test/`,
`docs/` and `docs/archive/`, `.github/workflows/`, and `.claude/`. Generated and
vendored trees are excluded: `tui/dist/`, `node_modules/`, `.venv/`, and every
cache directory.

Small directories get short maps. A ten-line map for a one-file directory is
correct, not padding.

## The root map is a different document

`MAP.md` at the root is state-of-the-world rather than inventory. It records
what actually ships today against what is stubbed, the shape of the runtime
(agents, domains, the single implemented provider), the build and test commands,
the cross-cutting invariants, and a routing table from a concern to a directory.

It points to `AGENTS.md` for doctrine instead of restating it. `AGENTS.md`
answers *why the system is built this way*; the root map answers *what is true
right now*. Keeping those separate is what stops the root map from becoming a
second, competing doctrine document.

## Discovery

Maps that nothing points at are dead weight. `CLAUDE.md` and `AGENTS.md` each
gain a short pointer near the top: read the root `MAP.md` first, then the
directory's own `MAP.md`, before opening source.

## Constraints

- UTF-8 without BOM, LF endings, enforced by the existing hygiene job.
- The reference vault's name appears in no file outside `tests/`.
- `pyproject.toml` remains the only dependency manifest.
- Maps describe; they never become a place to put behaviour.
