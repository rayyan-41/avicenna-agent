# MAP: .github/workflows/

> The CI pipeline. Three jobs, no `continue-on-error` anywhere — by policy, a
> check that cannot fail the build is documentation, not a gate. If a step
> cannot be enforced yet, it is deleted rather than left lying. This invariant
> once carried a `continue-on-error` "temporarily"; the result was a green tick
> on top of 17 type errors and a violated invariant for weeks.

**Depends on:** `pyproject.toml`, `tui/package-lock.json`, `scripts/` · **Depended on by:** every PR and push to `master` or `harness`
**Reads:** source tree, `tui/` · **Writes:** nothing (read-only gates)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `ci.yml` | 265 | The sole workflow file. Defines all three CI jobs and every enforcement gate. Runs on push/PR to `master` and `harness`. |
<!-- map:files:end -->

## Jobs and steps

### `build` — `windows-latest`

Windows is the real target because vault tools shell out to PowerShell.

| Step | What it enforces |
| --- | --- |
| **Checkout** | Source at HEAD. |
| **Set up Python 3.12** | Correct interpreter; pip cache keyed on `pyproject.toml`. |
| **Install package and dev dependencies** | `pip install -e ".[dev]"` — editable install with test extras. |
| **Tests** | `pytest -q` — the full backend test suite. |
| **Type check (strict)** | `mypy --strict avicenna/providers avicenna/pipeline` — the two modules under strict typing. |
| **Lint bridge for blocking calls** | PowerShell grep for `subprocess.run`, `time.sleep`, `requests.` and friends under `avicenna/bridge/`. A blocking call there stalls the NDJSON event pump and freezes the interface. |
| **Vendor neutrality** | Importing `avicenna.providers` must not leak a vendor SDK into `sys.modules`. |
| **Vendor SDK containment** | No `from mistralai/openai/anthropic/google.genai` import outside `avicenna/providers/`. |
| **No reference-vault name outside tests** | The reference vault's literal name must not appear in `avicenna/`. |
| **Future annotations everywhere** | Every `.py` under `avicenna/` must begin with `from __future__ import annotations`. |
| **No stray prints to stdout** | `print()` to stdout outside `avicenna/cli/` fails the build — stdout belongs to the NDJSON protocol. |
| **Protocol parity** | `scripts/check_protocol_parity.py` — `events.py` and `tui/src/protocol.ts` must declare the same event names. |
| **Bridge smoke test** | Pipes a `vault.info` request through `python -m avicenna.bridge` and verifies every output line is valid JSON (at least 2 frames). |

### `tui` — `ubuntu-latest`

The frontend is a separate TypeScript toolchain.

| Step | What it enforces |
| --- | --- |
| **Checkout** | Source at HEAD. |
| **Set up Node 20** | Correct runtime; npm cache keyed on `tui/package-lock.json`. |
| **Install** | `npm ci` in `tui/`. |
| **Type check** | `npm run typecheck` — TypeScript strict mode. |
| **Build** | `npm run build` — compile to `tui/dist/`. |
| **Tests** | `npm test` — the frontend test suite. |
| **Frontend stays unstyled** | Grep for raw SGR escapes (`\x1b[...m`) outside `ansi.ts`. The skeleton is unstyled on purpose; colour must not creep back in through a patch. |

### `hygiene` — `ubuntu-latest`

Encoding, line endings, dependency manifest, and MAP.md tree invariants.

| Step | What it enforces |
| --- | --- |
| **Checkout** | Source at HEAD. |
| **Set up Python 3.12** | This job is otherwise a bare checkout; the map gate needs an interpreter, and relying on whichever `python3` the runner image ships is the kind of thing that breaks silently later. |
| **MAP.md inventory parity** | `scripts/check_maps.py`: every tracked directory holding source has a `MAP.md`, its marker block lists exactly that directory's tracked files, and no row carries an unwritten placeholder. |
| **UTF-8 without BOM, LF endings** | Every `.py`, `.ts`, `.md`, `.json`, `.yml` is checked for BOM and CRLF. PowerShell `.ps1` files are exempted (Windows requires CRLF). |
| **requirements.txt stays deleted** | `pyproject.toml` is the only dependency manifest; recreating `requirements.txt` fails the build. |

## Invariants

- No step carries `continue-on-error`. A green build means every gate passed.
- CI runs Python on Windows because the vault tools depend on PowerShell;
  frontend and hygiene run on Ubuntu where the toolchain is cheaper.
- `harness` is a protected branch alongside `master`.

## Entry points

- To add a new CI gate, add a step to the appropriate job in `ci.yml`.
- To add a new event to the protocol, you must also pass the protocol parity
  step — see `scripts/check_protocol_parity.py`.

## See also

- `../../scripts/MAP.md` — the scripts invoked by CI steps.
- `../../CLAUDE.md` — the rules these gates enforce.
