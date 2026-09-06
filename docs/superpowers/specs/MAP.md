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
| `2026-09-06-backend-shippability-design.md` | 135 | Why the repo had fourteen blocking gates and no evidence: every one tested the code in isolation and none had ever run the product. Specifies the healthcheck surface (the bridge's seventeen methods, MCP servers, vault PowerShell tools and provider reachability are the endpoints, since there is no HTTP), the six-agent live generation matrix and why it runs against the real vault rather than `_tmp/`, the tag-triggered release workflow and why it carries no PyPI job, and two gate corrections. |
| `2026-09-06-layered-configuration-design.md` | 118 | Turning the harness into an engine someone else can tune. Splits settings by ownership — vault policy in `.agents/config.json`, user preferences in `user_config.json` — behind one precedence chain (CLI flag, env var, scope file, default) and one resolver. Records the defect that motivated it: a hardcoded default model plus two disagreeing code paths meant the model chosen at onboarding was never used by `avicenna note`, and `persist_key` actively overwrote the user's choice on every key save. Names the single deliberate exception, `PROTOCOL_VERSION`, and why it must stay constant. |
| `2026-09-06-llm-assisted-routing-design.md` | 94 | Why routing inverted: keyword scoring got three of six domains right on the reference vault, and two of the three causes were not bugs but what a bag-of-words scorer does. Records the resolution order (model classifier, closed-set validation, deterministic scorer, refusal), why this does not violate the prime directive — the model proposes a classification, the closed set disposes — and why an unparseable answer must never become a confident domain. |
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
