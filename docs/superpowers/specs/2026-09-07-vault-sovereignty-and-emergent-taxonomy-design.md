# Vault sovereignty and emergent taxonomy — design

Status: approved 2026-09-07.

Supersedes the vault-structure portions of
`2026-09-06-layered-configuration-design.md`, which assumed configuration would
*declare* vault structure. It will not. Structure is read from the vault.

## Problem

The harness and the vault each hold an opinion about how the vault is shaped,
and where those opinions differ the harness loses — silently, and in the user's
data.

Three instances landed in one day of live testing:

1. `gen_matrix` located Maps of Content with `glob("*MOC*.md")`. The vault names
   them `Map of Contents - <Domain>.md`, which contains no such substring. Every
   cell reported `no_moc_file`, and the assertion that actually mattered was
   never reached. A harness assumption masked the defect it existed to catch.

2. The matrix validated tags against a closed enumeration built from
   `taxonomy.json`. The vault's contract allows 0–6 *entity* tags from an open
   vocabulary. A correct note carrying `intention` was failed as invalid. A
   closed list can never validate an open vocabulary.

3. `_note_destination` title-cased the domain to pick a folder; `MocStage`
   passed the raw lowercase key to the same vault's tool, which builds both the
   filename and the directory path from the caller's casing. A run wrote the
   note to `Reason/` and the MOC to `Map of Contents - reason.md`, renaming a
   file with months of history. Windows hid it. A case-sensitive filesystem
   would have produced two competing MOCs and two domain folders.

These are not three bugs. They are one bug three times: **the harness restating
something the vault already knows.** No amount of care prevents the next
instance, because the failure is structural. The only fix that generalises is to
remove the second opinion.

## Doctrine

**The vault is the single source of truth for structure. The harness reads it
and never restates it.**

- Domains are the vault's root folders. Categories are the folders within them.
  Depth, naming and organisation belong to the user, and each vault is
  legitimately different.
- The frontmatter schema is whatever the vault's existing notes use, detected by
  sampling, not imposed by the harness.
- `avicenna init` scaffolds a vault for someone who has none. It never becomes a
  second definition of a vault that already exists.

**The harness owns exactly two things: generation, and cohesion.**

Cohesion means correct tagging and semantically grounded backlinks. Both are
tedious by hand and both are inference problems, which is precisely what a
language model is good at. Everything else is the user's.

The user's entire job is to supply a topic:

    write a note on Jean Jacques Rousseau and how he can be considered
    a pillar of nationalism

Nothing else is asked of them. Any design that requires the user to maintain a
vocabulary, declare a structure, or approve a classification has failed this
test.

## 1. Derivation: the vault describes itself

`taxonomy.json` currently *declares* domains and the categories valid within
each. That declaration duplicates the folder tree, and duplication is the defect
above. Domains and categories become derived:

- **Domains** are the immediate subdirectories of the vault root, excluding
  dotted directories, `_tmp`, and anything the vault's own ignore policy
  excludes. The folder's on-disk name is canonical — its casing is the casing,
  which removes the class of defect that renamed a MOC.
- **Categories** are the immediate subdirectories of a domain folder. A domain
  with no subfolders has no categories, and that is legitimate; the category
  slot then falls to the note's inferred subject rather than its location.
- **Routing** already picks a domain from the topic. It now picks from the
  derived set rather than a declared one. `validate_domain` keeps its job: the
  model proposes, the closed set disposes — but the set is closed *by the
  filesystem*, not by a file the user must maintain.

The harness must never create a domain folder to satisfy a route. If routing
proposes something with no folder, that is a routing failure, not licence to
invent structure in the user's vault.

### Frontmatter schema detection

The pipeline currently writes `title / domain / template / tags`. The vault's
own notes use `date / status / tags / note`. Which one a generated note receives
today depends on whether the weaver happened to emit a block — an accident.

The schema is detected instead: sample existing notes in the target domain (then
the vault at large), take the most common key set and ordering, and write that.
`tags` is always present because the harness owns it. Keys the harness has no
value for are preserved from the model's output when present and omitted
otherwise; keys the vault expects but nothing supplies (a `date`, say) are
filled with a sensible value rather than a literal placeholder like the observed
`date: YYYY-MM-DD`.

A vault with no existing notes gets the scaffold's schema. That is the one case
where the harness may choose, because there is nothing to read.

## 2. Emergent taxonomy: a map of the reader's mind

Themes and types are **inferred by the harness, per note, and accumulated**.
They are not a vocabulary the user maintains.

This inverts `taxonomy.json`: it stops being an input the model must satisfy and
becomes an output the harness maintains — a registry recording where this
reader's attention has actually gone. Over many notes it answers a question no
declared taxonomy can: *what have I been thinking about, and how many distinct
regions does that cover?*

- **Type** is what kind of thing the note is about (`person`, `concept`,
  `event`, `work`, …). A small ontology that grows rarely.
- **Themes** are the substrate of intellectual connection, and the part that
  grows. A note on Rousseau and nationalism might carry `nationalism`,
  `political-philosophy`, `enlightenment`.

The interesting event is whether a proposed theme has appeared before. If it
has, the note joins an existing region of the reader's thinking. If it has not,
the reader has entered new territory, and that is worth surfacing rather than
hiding.

### Drift is the failure mode that matters

An unconstrained growing vocabulary destroys the thing it is meant to produce.
Left alone, a model will mint `nationalism`, `national-identity`, `nationhood`
and `the-nation-state` across four notes about one region of thought. The
registry then answers "how many themes have I read on?" with noise, and the map
stops being a map.

So minting is guarded. Before a proposed theme enters the registry:

1. Embed it, together with the sentence-level context that produced it.
2. Compare against every theme already in the registry.
3. Above a similarity threshold, **reuse the existing theme**. Below it, mint.

This is the same discipline as routing and linking — the model proposes, and a
deterministic check disposes — applied to vocabulary. The registry grows only
where the reader's thinking actually did.

A minted theme is recorded as a first-class event and reported. It is **not**
held for approval. Blocking a note on "is this a new theme?" would make the user
a bottleneck again, which contradicts the one-job doctrine. A registry is
prunable after the fact; an interruption is not undoable.

### What `validate_tags` becomes

It stops gatekeeping *vocabulary* and keeps enforcing *structure*: exactly one
domain, one category, one type, one to three themes, the marker last, positional
order intact. Structure is checkable; vocabulary is emergent. The tool remains
the authority — the harness asks it and never reimplements its rules, which is
the lesson of the three defects above.

## 3. The knowledge graph

`get_related_notes` scores tag overlap in PowerShell. That works only when tags
already agree, which is exactly the case where the reader least needs help. The
connections worth surfacing are the ones a tag match misses.

1. **Index.** Embed every note — title, headings, and lead paragraphs, chunked
   for long notes — into a vault-local store keyed by path and content hash.
   Incremental: a note edited in Obsidian invalidates by hash, and nothing
   triggers a full re-embed. The store is harness bookkeeping, not vault
   content, and must not pollute the note tree or the vault's git history.
2. **Retrieve.** For each section of a new note, the nearest existing notes.
   This is a closed set of real notes by construction.
3. **Decide.** The model receives a section and those candidates and chooses
   where a link genuinely belongs. This is the inference the reader cannot do at
   scale and the model can.
4. **Verify.** Every `[[target]]` resolves against the index or is unwrapped to
   plain text. Already implemented: the linker was observed wrapping the note's
   own section headings in brackets, eight in one note, and asking the model
   more firmly is not a fix.

Embeddings need a provider. It gets the same treatment as `LLMProvider` — an
abstract interface, vendor SDKs confined to `avicenna/providers/`, selectable by
configuration — so a vault can run on a hosted embedding API or a local model
without the pipeline knowing which.

## 4. Maps of Content

A per-domain MOC is a navigational index shaped like a folder. Under this
doctrine the real map is the theme registry and the graph, both of which cut
across folders. The harness should stop hand-maintaining MOC files: three of the
day's defects were the harness reaching into a structure it does not own.

Navigation is generated from the graph and the registry instead. Whether a vault
continues to keep MOC files is then the vault's business, served by the vault's
own tooling, on the vault owner's schedule.

## Worked example

    write a note on Jean Jacques Rousseau and how he can be considered
    a pillar of nationalism

| slot | source | value |
| --- | --- | --- |
| domain | the vault's root folders | `Reason` |
| category | that domain's subfolders | `philosophy` |
| type | harness infers | `person` |
| themes | harness infers, registry-checked | `nationalism`, `political-philosophy` |
| entities | open vocabulary | `jean-jacques-rousseau`, `general-will` |
| marker | vault convention | `cli` |

If `nationalism` is already in the registry, the note joins that region. If a
proposed `national-identity` embeds close to it, it is folded in rather than
minted. If nothing close exists, a new theme is recorded and reported.

## What this changes

| today | after |
| --- | --- |
| `taxonomy.json` declares domains and categories | derived from folders; the file becomes a harness-maintained registry |
| themes and types drawn from a closed declared set | inferred per note, accumulated, drift-guarded |
| `_note_destination` computes `root / domain.title()` | resolves the user's actual folder |
| frontmatter schema imposed by the harness | detected from the vault's own notes |
| `get_related_notes` scores tag overlap | embedding retrieval over the whole vault |
| the harness writes MOC files | navigation generated from graph and registry |

## Sequencing

1. **Derivation** — folders to domains and categories; canonical folder
   resolution; routing over the derived set. Mostly deletion, and it removes the
   class of defect that motivated this document.
2. **Schema detection** — sample and match the vault's frontmatter convention.
3. **Registry** — accumulate inferred themes and types; report new ones.
4. **Embeddings** — provider interface, vault-local index, incremental
   invalidation.
5. **Graph-driven linking** — retrieval feeds the linker; the existing
   resolution guard stays as the floor.
6. **Retire MOC writing** once navigation is generated.

Steps 1 and 2 are independent of 4 and 5 and should land first: they are small,
they are mostly removal, and they stop the harness corrupting vault structure
while the larger work proceeds.

## Risks

**Derivation is only as good as the folder tree.** A vault with an idiosyncratic
root — attachments, templates, archives beside domains — will route into
nonsense. The exclusion policy must be readable and overridable by the vault, and
the harness must refuse to invent folders when routing fails.

**The similarity threshold is a judgement call.** Too high and the registry
fragments into synonyms; too low and distinct ideas collapse into one theme. It
must be configurable and its decisions must be visible in the event stream, so a
bad threshold is diagnosable rather than mysterious.

**Embedding introduces cost and latency per note**, and an index that can drift
from a vault edited outside the harness. Content-hash keying is the mitigation;
a full rebuild must always be available and cheap to trigger.

**A registry the harness writes is a write surface the harness did not have.**
It is justified — the registry is the harness's own bookkeeping about inference
it performed, not a restatement of vault structure — but it must live where a
user can inspect, prune and delete it without breaking their notes.
