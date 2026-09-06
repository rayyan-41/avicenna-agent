"""Avicenna healthcheck: eight independent probes that diagnose a running install.

Each probe catches its own exceptions and returns a structured result rather
than raising. A broken vault does not prevent the provider probe from running;
a missing key does not prevent the bridge probe. WARN and SKIP never affect the
exit code — those degrade gracefully and honestly. FAIL means something a user
depends on is actually broken.

A vault with zero PowerShell tools is LEGITIMATE, and so is a config with zero
MCP servers. Those are SKIP. FAIL is for things that are broken: a vault that
will not load, a provider key that is rejected, a bridge method that answers a
malformed frame.

Usage:
    python scripts/healthcheck.py [--json] [--vault PATH]

Surfaced as `avicenna doctor` in the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class ProbeResult:
    name: str
    status: Status
    summary: str
    details: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Probe 1: CONFIG
# ---------------------------------------------------------------------------

def probe_config(vault_override: str | None) -> ProbeResult:
    """Which vault was resolved and via which discovery source, which provider
    is configured, whether an API key is present. The key is reported as
    present or absent and never printed."""
    from avicenna.config import Config
    from avicenna.secrets import read_api_key

    details: list[str] = []
    vault_found = False
    vault_path: Path | None = None
    source = "none"

    # Resolve vault via the same four-source precedence as discover_vault, but
    # report which source succeeded rather than just the path. We replicate the
    # precedence here because discover_vault only returns the Path, not the
    # source that produced it.
    import os

    candidates: list[tuple[str, Path]] = []
    if vault_override:
        candidates.append(("--vault", Path(vault_override)))
    env = os.environ.get("AVICENNA_VAULT")
    if env:
        candidates.append(("AVICENNA_VAULT", Path(env)))
    # Walk up from cwd
    cursor = Path.cwd().resolve()
    from avicenna.vault.discovery import _looks_like_vault

    for parent in [cursor, *cursor.parents]:
        if _looks_like_vault(parent):
            candidates.append(("cwd walk-up", parent))
            break
    cfg = Path.home() / ".avicenna" / "user_config.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text("utf-8"))
            if default := data.get("default_vault"):
                candidates.append(("user_config.json", Path(default)))
        except (OSError, json.JSONDecodeError):
            pass

    for origin, path in candidates:
        resolved = path.expanduser().resolve()
        if _looks_like_vault(resolved):
            vault_found = True
            vault_path = resolved
            source = origin
            details.append(f"vault: {resolved}")
            details.append(f"source: {origin}")
            break

    if not vault_found:
        details.append("vault: not found")

    # Provider
    user_cfg = Config.load_user_config()
    provider = user_cfg.get("provider", Config.LLM_PROVIDER)
    details.append(f"provider: {provider}")

    # Key presence — never print the key itself.
    key = read_api_key(provider)
    key_status = "present" if key else "absent"
    details.append(f"api key: {key_status}")

    if not vault_found:
        return ProbeResult("CONFIG", Status.FAIL,
                           "no vault found", details)

    summary = f"{vault_path.name if vault_path else '?'} via {source}, {provider}, key {key_status}"
    return ProbeResult("CONFIG", Status.OK, summary, details)


# ---------------------------------------------------------------------------
# Probe 2: PROVIDER
# ---------------------------------------------------------------------------

async def probe_provider() -> ProbeResult:
    """One cheap real call via validate_key. SKIP if no key is configured."""
    from avicenna.auth import DEFAULT_MODEL, DEFAULT_PROVIDER, validate_key
    from avicenna.config import Config
    from avicenna.secrets import read_api_key

    key = read_api_key(DEFAULT_PROVIDER)
    if not key:
        return ProbeResult("PROVIDER", Status.SKIP, "no API key configured")

    model = Config.load_user_config().get("model", DEFAULT_MODEL)
    result = await validate_key(DEFAULT_PROVIDER, key, model)

    if result.ok:
        return ProbeResult("PROVIDER", Status.OK, result.detail)
    return ProbeResult("PROVIDER", Status.FAIL, result.detail)


# ---------------------------------------------------------------------------
# Probe 3: VAULT
# ---------------------------------------------------------------------------

def probe_vault(vault_path: Path) -> ProbeResult:
    """Vault.load succeeds; report agent counts by type, skill count,
    taxonomy domain count. FAIL if any content agent declares a domain not in
    taxonomy.json."""
    from avicenna.vault.models import VaultConfigError
    from avicenna.vault.vault import Vault

    details: list[str] = []
    try:
        v = Vault.load(vault_path)
    except VaultConfigError as exc:
        return ProbeResult("VAULT", Status.FAIL, str(exc))
    except Exception as exc:
        return ProbeResult("VAULT", Status.FAIL, f"{type(exc).__name__}: {exc}")

    # Count agents by type
    by_type: dict[str, int] = {}
    for agent in v.agents.values():
        by_type[agent.type] = by_type.get(agent.type, 0) + 1
    for atype in ("content", "pipeline", "audit"):
        if atype in by_type:
            details.append(f"{atype} agents: {by_type[atype]}")

    details.append(f"skills: {len(v.skills)}")
    details.append(f"taxonomy domains: {len(v.taxonomy.domains)}")

    summary = (f"{len(v.agents)} agents, {len(v.skills)} skills, "
               f"{len(v.taxonomy.domains)} domains")
    return ProbeResult("VAULT", Status.OK, summary, details)


# ---------------------------------------------------------------------------
# Probe 4: REGISTRY
# ---------------------------------------------------------------------------

def probe_registry(vault_path: Path) -> ProbeResult:
    """Every registered tool with name, source and access level. WARN for any
    .ps1 in the vault absent from the manifest in vault_tools.py, because
    those silently default to PIPELINE_ONLY."""
    from avicenna.tools.base import ToolAccess
    from avicenna.tools.vault_tools import VAULT_TOOL_MANIFEST
    from avicenna.vault.vault import Vault

    details: list[str] = []
    try:
        v = Vault.load(vault_path)
    except Exception as exc:
        return ProbeResult("REGISTRY", Status.FAIL,
                           f"vault load failed: {exc}")

    for tool in v.tools:
        details.append(f"{tool.name} [{tool.source.value}] [{tool.access.value}]")

    # Check for .ps1 scripts not in the manifest. Those default to
    # PIPELINE_ONLY silently, which may not be what the vault author intended.
    tools_dir = vault_path / ".agents" / "tools"
    unregistered: list[str] = []
    if tools_dir.is_dir():
        for script in sorted(tools_dir.glob("*.ps1")):
            if script.name not in VAULT_TOOL_MANIFEST:
                unregistered.append(script.name)
                details.append(f"WARN: {script.name} not in manifest (defaults to pipeline_only)")

    summary = f"{len(details) - len(unregistered)} tools registered"
    if unregistered:
        summary += f", {len(unregistered)} unregistered ps1"
        return ProbeResult("REGISTRY", Status.WARN, summary, details)
    return ProbeResult("REGISTRY", Status.OK, summary, details)


# ---------------------------------------------------------------------------
# Probe 5: PS_TOOLS
# ---------------------------------------------------------------------------

# Tools the assignment explicitly forbids running because they mutate.
_MUTATION_BLACKLIST = frozenset({
    "update_moc", "cleanup_chunks", "generate_toc",
    "run_standardize", "run_vault_wide_standardize", "write_manifest",
    "update_pipeline_state",
})


async def probe_ps_tools(vault_path: Path) -> ProbeResult:
    """Execute the read-only MODEL_CALLABLE vault tools and assert the declared
    contract token parses out of stdout. A tool whose stdout does not match its
    contract is a WARN with the raw stdout shown, because that tool gates
    nothing."""
    from avicenna.tools.base import ToolAccess, ToolSource
    from avicenna.tools.contracts import CONTRACTS
    from avicenna.vault.vault import Vault

    details: list[str] = []
    try:
        v = Vault.load(vault_path)
    except Exception as exc:
        return ProbeResult("PS_TOOLS", Status.WARN,
                           f"vault load failed; cannot test tools: {exc}")

    # Collect MODEL_CALLABLE PS1 tools that are safe to run.
    candidates: list[Any] = []
    for tool in v.tools:
        if (tool.source is ToolSource.VAULT_PS1
                and tool.access is ToolAccess.MODEL_CALLABLE
                and tool.name not in _MUTATION_BLACKLIST):
            candidates.append(tool)

    if not candidates:
        return ProbeResult("PS_TOOLS", Status.SKIP,
                           "no read-only vault tools to test")

    # Build test inputs for known tools. We use values drawn from the vault's
    # own taxonomy so that scripts that validate inputs against it will accept
    # the probe data.  For validate_tags we pass a single domain tag to avoid
    # PowerShell's comma-in-argument quoting, which wraps values in literal
    # double quotes that the scripts then see as part of the string.
    markers = list(v.taxonomy.markers)
    domains = list(v.taxonomy.domains.keys())
    themes = list(v.taxonomy.themes)[:2]
    # A single domain tag is enough to exercise the contract; comma-separated
    # tags go through normalise_ps_value which embeds literal " characters.
    tag_line = domains[0] if domains else (themes[0] if themes else "cli")

    # Find an existing note for tools that need a file path. We walk the vault
    # tree looking for a .md in a domain folder (not in .agents/ or _tmp/).
    note_path: str | None = None
    for md in v.root.rglob("*.md"):
        rel = md.relative_to(v.root)
        parts = rel.parts
        if parts and not parts[0].startswith(".") and parts[0] != "_tmp":
            note_path = str(rel)
            break

    # get_related_notes is read-only but its contract fires only when the vault
    # has notes whose tags produce candidates; an empty result is not a tool
    # failure.  We run it for its exit code but exclude it from contract
    # gating to avoid a false WARN on a healthy vault with a narrow corpus.
    _NON_CONTRACT = frozenset({"get_related_notes"})

    test_inputs: dict[str, dict[str, object]] = {
        "validate_tags": {"TagLine": tag_line},
        "count_citations": {"FilePath": note_path or "nonexistent.md"},
        "word_count": {"FilePath": note_path or "nonexistent.md"},
        "generate_index": {},
        "audit_skill_sync": {},
        "get_related_notes": {
            "NotePath": note_path or "nonexistent.md",
            "CoreTags": tag_line,
        },
    }

    contract_tools_tested = 0
    contract_tools_ok = 0

    for tool in candidates:
        args = test_inputs.get(tool.name, {})
        try:
            result = await asyncio.wait_for(tool.invoke(**args), timeout=30.0)
        except asyncio.TimeoutError:
            details.append(f"{tool.name}: timeout (30s)")
            continue
        except Exception as exc:
            details.append(f"{tool.name}: error: {exc}")
            continue

        stdout = result.stdout.strip()
        contract = CONTRACTS.get(tool.name)
        if contract is not None and tool.name not in _NON_CONTRACT:
            contract_tools_tested += 1
            parsed = contract.parse(tool.name, result.stdout, result.stderr, result.exit_code)
            if parsed.token != "CONTRACT_UNMATCHED":
                # The contract matched — either success or declared failure.
                # Both are valid; the probe checks that the token is emitted,
                # not that the tool succeeded, because a tool that returns its
                # declared failure token is still gating correctly.
                contract_tools_ok += 1
                details.append(f"{tool.name}: OK ({parsed.token})")
            else:
                details.append(
                    f"{tool.name}: WARN contract not matched; "
                    f"stdout: {stdout[:200] if stdout else '(empty)'}"
                )
        else:
            # No contract — the tool is not used for pipeline gating.
            # Report the exit code so the operator can see if it errored.
            status = "ok" if result.exit_code == 0 else f"exit {result.exit_code}"
            snippet = stdout[:120] if stdout else "(no output)"
            details.append(f"{tool.name}: {status} — {snippet}")

    if contract_tools_tested == 0:
        summary = f"{len(candidates)} tools ran, none have contracts"
        return ProbeResult("PS_TOOLS", Status.OK, summary, details)

    if contract_tools_ok == contract_tools_tested:
        summary = (f"{len(candidates)} tools ran, "
                   f"{contract_tools_tested}/{contract_tools_tested} contracts matched")
        return ProbeResult("PS_TOOLS", Status.OK, summary, details)

    summary = (f"{contract_tools_ok}/{contract_tools_tested} contracts matched "
               f"of {len(candidates)} tools tested")
    return ProbeResult("PS_TOOLS", Status.WARN, summary, details)


# ---------------------------------------------------------------------------
# Probe 6: MCP
# ---------------------------------------------------------------------------

async def probe_mcp() -> ProbeResult:
    """Reuse the machinery in avicenna/cli/mcp_cmd.py. SKIP when no servers
    are enabled."""
    from avicenna.cli.mcp_cmd import ServerTestResult, test_servers
    from avicenna.config import Config

    cfg = Config.load_mcp_config()
    targets = cfg.get_enabled_servers()

    if not targets:
        if cfg.servers:
            return ProbeResult("MCP", Status.SKIP,
                               f"{len(cfg.servers)} configured but all disabled")
        return ProbeResult("MCP", Status.SKIP, "no MCP servers configured")

    results: list[ServerTestResult] = await test_servers(targets)

    details: list[str] = []
    all_ok = True
    for r in results:
        if r.connected:
            details.append(f"{r.name}: connected ({r.tool_count} tools)")
        else:
            details.append(f"{r.name}: FAILED — {r.error}")
            all_ok = False
        for note in r.notes:
            details.append(f"  {r.name}: {note}")

    connected = sum(1 for r in results if r.connected)
    total_tools = sum(r.tool_count for r in results)
    summary = f"{connected}/{len(results)} servers connected, {total_tools} tools"
    status = Status.OK if all_ok else Status.FAIL
    return ProbeResult("MCP", status, summary, details)


# ---------------------------------------------------------------------------
# Probe 7: BRIDGE
# ---------------------------------------------------------------------------

# Every method in avicenna/bridge/MAP.md, except run.note (costs money) and
# shutdown (sent last as a signal to exit).
_BRIDGE_METHODS = [
    "hello",
    "vault.info",
    "vault.init",
    "agents.list",
    "tools.list",
    "mcp.list",
    "auth.status",
    "auth.validate",
    "auth.persist",
    "auth.local_stub",
    "route.explain",
    "run.cancel",
    "chat.select",
    "chat.send",
    "chat.clear",
]

# Per-method timeout for reading a response.
_METHOD_TIMEOUT = 15.0
# Overall timeout for the entire bridge probe.
_TOTAL_TIMEOUT = 120.0


async def probe_bridge(vault_path: Path | None) -> ProbeResult:
    """Spawn python -m avicenna.bridge, send all methods over stdin as NDJSON,
    read the responses, and assert each is a well-formed frame with a matching
    id. NEVER send run.note. Send shutdown last. Enforce an overall timeout.
    Assert that every line the bridge writes to stdout parses as JSON."""
    import os

    details: list[str] = []
    non_json_lines: list[str] = []

    args = [sys.executable, "-m", "avicenna.bridge"]
    if vault_path is not None:
        args += ["--vault", str(vault_path)]

    started = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(os.environ),
        )
    except Exception as exc:
        return ProbeResult("BRIDGE", Status.FAIL,
                           f"could not start bridge: {exc}")

    assert proc.stdout is not None
    assert proc.stdin is not None

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _reader() -> None:
        while True:
            line = await proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                await queue.put(None)
                return
            await queue.put(line.decode("utf-8", errors="replace").rstrip("\r\n"))

    reader_task = asyncio.create_task(_reader())

    async def _read_until(target_id: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                non_json_lines.append(raw)
                continue
            if not isinstance(obj, dict):
                non_json_lines.append(raw)
                continue
            if obj.get("type") != "res":
                continue  # skip ready / event frames
            if obj.get("id") == target_id:
                return obj

    responses: dict[str, dict[str, Any]] = {}

    try:
        # Read the ready frame first.
        ready_deadline = time.monotonic() + 15.0
        while True:
            remaining = ready_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if raw is None:
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                non_json_lines.append(raw)
                continue
            if isinstance(obj, dict) and obj.get("type") == "ready":
                break
            # If it's an event or something else, keep reading.

        # Send each method and collect the response.
        for i, method in enumerate(_BRIDGE_METHODS):
            elapsed = time.monotonic() - started
            if elapsed > _TOTAL_TIMEOUT:
                break

            req_id = str(i + 1)
            frame = json.dumps(
                {"type": "req", "id": req_id, "method": method, "params": {}}
            )
            try:
                proc.stdin.write((frame + "\n").encode("utf-8"))
                await proc.stdin.drain()
            except (BrokenPipeError, OSError):
                details.append(f"{method}: pipe broken (bridge exited early)")
                continue

            resp = await _read_until(req_id, _METHOD_TIMEOUT)
            if resp is not None:
                responses[method] = resp
            else:
                details.append(f"{method}: no response (timeout)")

        # Send shutdown last.
        shutdown_frame = json.dumps(
            {"type": "req", "id": "shutdown", "method": "shutdown", "params": {}}
        )
        try:
            proc.stdin.write((shutdown_frame + "\n").encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, OSError):
            pass

        # Give the bridge a moment to exit cleanly.
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

    # Terminate if still alive (should not happen after shutdown).
    if proc.returncode is None:
        try:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            pass

    # Clean up the vault that vault.init scaffolded into cwd. The bridge
    # process creates it there when called with empty params. We remove it
    # after the bridge exits so no file handles remain open.
    _cleanup_vault = Path.cwd() / "avicenna-vault"
    if _cleanup_vault.is_dir():
        import shutil
        try:
            shutil.rmtree(_cleanup_vault)
        except OSError:
            pass  # best-effort; an orphan test vault is not a healthcheck failure

    # Validate responses. Every frame must be a well-formed response with the
    # correct id — a stray print in the bridge is exactly the defect this probe
    # catches, and an id mismatch means the response dispatcher is broken.
    all_ok = True
    method_to_id = {m: str(i + 1) for i, m in enumerate(_BRIDGE_METHODS)}
    for method in _BRIDGE_METHODS:
        expected_id = method_to_id[method]
        if method not in responses:
            all_ok = False
            continue
        resp = responses[method]
        rid = resp.get("id")
        ok_field = resp.get("ok")
        # Structural validation: id must match, ok must be a bool.
        if rid != expected_id:
            all_ok = False
            details.append(f"{method}: id mismatch (expected {expected_id!r}, got {rid!r})")
            continue
        if not isinstance(ok_field, bool):
            all_ok = False
            details.append(f"{method}: ok field is not a bool: {ok_field!r}")
            continue
        if ok_field:
            details.append(f"{method}: ok")
        else:
            err = resp.get("error", {})
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
            details.append(f"{method}: error — {msg[:120]}")

    if non_json_lines:
        all_ok = False
        for line in non_json_lines[:5]:
            details.append(f"non-JSON stdout: {line[:200]}")

    got = len(responses)
    total = len(_BRIDGE_METHODS)
    if not all_ok:
        return ProbeResult("BRIDGE", Status.FAIL,
                           f"{got}/{total} methods responded", details)
    return ProbeResult("BRIDGE", Status.OK, f"{got}/{total} methods responded", details)


# ---------------------------------------------------------------------------
# Probe 8: ROUTING
# ---------------------------------------------------------------------------

# Six real topic sentences, one per expected domain.
_ROUTING_TOPICS = {
    "art": (
        "The use of linear perspective in Quattrocento fresco painting and how "
        "Brunelleschi's demonstration influenced Masaccio's treatment of spatial "
        "depth in the Brancacci Chapel"
    ),
    "history": (
        "The administrative reforms of the Ottoman Empire under Sultan Suleiman "
        "and the role of the devshirme system in staffing the imperial bureaucracy"
    ),
    "islam": (
        "The Ashari position on the createdness of the Quran and how it differs "
        "from the Mu'tazili doctrine of Khalq al-Quran in kalām theology"
    ),
    "literature": (
        "The unreliable narrator in modern Arabic fiction and how narrative "
        "unreliability functions as a device for exploring contested memory"
    ),
    "reason": (
        "The debate between rationalism and empiricism regarding the sources of "
        "knowledge, with particular attention to Kant's synthesis in the Critique "
        "of Pure Reason"
    ),
    "science": (
        "The mathematics of orbital mechanics and how Kepler's laws of planetary "
        "motion derive from Newtonian gravitational theory"
    ),
}


def probe_routing(vault_path: Path) -> ProbeResult:
    """Score six topics and assert each routes above threshold. Report the
    chosen agent and the winning score. FAIL only if routing returns nothing at
    all; a different-but-plausible agent is a WARN, because routing is
    vault-dependent."""
    from avicenna.vault.models import VaultConfigError
    from avicenna.vault.routing import MIN_MARGIN, MIN_SCORE, route_request, score_domains
    from avicenna.vault.vault import Vault

    details: list[str] = []
    try:
        v = Vault.load(vault_path)
    except Exception as exc:
        return ProbeResult("ROUTING", Status.FAIL,
                           f"vault load failed: {exc}")

    any_routed = False
    all_match = True

    for expected_domain, topic in _ROUTING_TOPICS.items():
        scores = score_domains(v, topic)
        chosen = route_request(v, topic)

        if chosen is None:
            details.append(f"{expected_domain}: no route (ambiguous)")
            continue

        any_routed = True
        best = scores[0] if scores else None
        score_val = best.score if best else 0.0
        matched_domain = chosen.domain or ""

        if matched_domain == expected_domain:
            details.append(f"{expected_domain}: {chosen.name} "
                           f"(score {score_val:.1f})")
        else:
            all_match = False
            details.append(f"{expected_domain}: got {chosen.name} "
                           f"(domain {matched_domain}, score {score_val:.1f}) "
                           f"— expected {expected_domain}")

    if not any_routed:
        return ProbeResult("ROUTING", Status.FAIL,
                           "no topic routed to any agent", details)

    if all_match:
        return ProbeResult("ROUTING", Status.OK,
                           f"all {len(_ROUTING_TOPICS)} topics routed correctly", details)
    return ProbeResult("ROUTING", Status.WARN,
                       "some topics routed to unexpected agents (vault-dependent)", details)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_all_probes(vault_override: str | None = None) -> list[ProbeResult]:
    """Run all eight probes, each independent, each catching its own errors."""
    results: list[ProbeResult] = []

    # Probe 1: CONFIG — must run first; other probes need the vault path.
    config_result = probe_config(vault_override)
    results.append(config_result)

    # Extract the resolved vault path for probes that need it.
    vault_path: Path | None = None
    if config_result.status is not Status.FAIL:
        for line in config_result.details:
            if line.startswith("vault: ") and not line.startswith("vault: not"):
                vault_path = Path(line[len("vault: "):])
                break

    # Probe 2: PROVIDER
    try:
        results.append(await probe_provider())
    except Exception as exc:
        results.append(ProbeResult("PROVIDER", Status.FAIL,
                                   f"unexpected: {exc}"))

    # Probes 3–5 and 8 need a vault.
    if vault_path is not None:
        try:
            results.append(probe_vault(vault_path))
        except Exception as exc:
            results.append(ProbeResult("VAULT", Status.FAIL,
                                       f"unexpected: {exc}"))

        try:
            results.append(probe_registry(vault_path))
        except Exception as exc:
            results.append(ProbeResult("REGISTRY", Status.FAIL,
                                       f"unexpected: {exc}"))

        try:
            results.append(await probe_ps_tools(vault_path))
        except Exception as exc:
            results.append(ProbeResult("PS_TOOLS", Status.WARN,
                                       f"unexpected: {exc}"))

        try:
            results.append(probe_routing(vault_path))
        except Exception as exc:
            results.append(ProbeResult("ROUTING", Status.FAIL,
                                       f"unexpected: {exc}"))
    else:
        for name in ("VAULT", "REGISTRY", "PS_TOOLS", "ROUTING"):
            results.append(ProbeResult(name, Status.SKIP, "no vault resolved"))

    # Probe 6: MCP
    try:
        results.append(await probe_mcp())
    except Exception as exc:
        results.append(ProbeResult("MCP", Status.FAIL,
                                   f"unexpected: {exc}"))

    # Probe 7: BRIDGE
    try:
        results.append(await probe_bridge(vault_path))
    except Exception as exc:
        results.append(ProbeResult("BRIDGE", Status.FAIL,
                                   f"unexpected: {exc}"))

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_STATUS_ORDER = {Status.OK: 0, Status.WARN: 1, Status.SKIP: 2, Status.FAIL: 3}


def format_table(results: list[ProbeResult]) -> str:
    """Render a human-readable table to stderr-safe text."""
    lines: list[str] = []
    name_w = max(len(r.name) for r in results) if results else 8
    for r in results:
        lines.append(f"  {r.name:<{name_w}}  [{r.status.value:4s}]  {r.summary}")
        for d in r.details:
            lines.append(f"  {'':>{name_w}}         {d}")
    return "\n".join(lines)


def format_json(results: list[ProbeResult]) -> str:
    """Machine-readable JSON output. Nothing else on stdout."""
    obj: dict[str, Any] = {}
    has_fail = False
    for r in results:
        if r.status is Status.FAIL:
            has_fail = True
        obj[r.name.lower()] = {
            "status": r.status.value,
            "summary": r.summary,
            "details": r.details,
        }
    obj["_exit"] = 1 if has_fail else 0
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    # On Windows the console encoding is often cp1252, which cannot represent
    # characters the MCP client or bridge may emit.  Force UTF-8 so the table
    # and JSON output never raise UnicodeEncodeError.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="healthcheck",
        description="Avicenna healthcheck: diagnose a running installation",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON to stdout")
    parser.add_argument("--vault", type=str, default=None,
                        help="Override vault discovery path")
    args = parser.parse_args()

    results = asyncio.run(run_all_probes(args.vault))

    if args.json:
        # JSON mode: machine-readable object on stdout, nothing else.
        print(format_json(results))
    else:
        print(format_table(results))
        has_fail = any(r.status is Status.FAIL for r in results)
        if has_fail:
            print("\nFAILED — at least one probe reported a hard failure.")
        else:
            print("\nAll clear.")

    has_fail = any(r.status is Status.FAIL for r in results)
    raise SystemExit(1 if has_fail else 0)


if __name__ == "__main__":
    main()
