# MAP: docs/superpowers/specs/

> Design specs, one per architectural change, written before the change and
> committed alongside it. A spec here records the problem, the approaches that
> were considered and rejected, and the decision that was taken — the reasoning
> that a diff cannot carry. These are historical records: a spec describes the
> design as approved, not necessarily the code as it stands today. When the two
> disagree, the code is the truth and the spec is the argument that produced it.

**Depends on:** nothing · **Depended on by:** nothing at runtime
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `2026-09-06-map-context-tree-design.md` | 119 | Why the MAP.md tree exists and what makes it trustworthy. Records the load-bearing decision — a drifted map is worse than no map, because it is believed — and the split into a machine-checked inventory and a hand-written judgment section that follows from it. Specifies the gate now implemented in `scripts/check_maps.py`. |
<!-- map:files:end -->

## Invariants

- Filenames are `YYYY-MM-DD-<topic>-design.md`. The date is the date of
  approval, and it never changes when the spec is later edited.
- A spec is committed before or with the work it describes, never after. A spec
  written afterwards is a summary, and summaries omit the approaches that were
  rejected — which is the half worth keeping.
- Specs are not updated to match drifting code. If a decision is reversed, write
  a new spec that says so and supersedes the old one by name.

## Entry points

- To add a spec, follow the structure of the existing one: problem, the failure
  mode the design exists to prevent, approaches considered with the reason each
  was rejected, the format or mechanism, and the constraints it must hold.

## See also

- `../../MAP.md` — the docs tree and what else lives there
- `../../../MAP.md` — state of the world, and the map tree this spec describes
