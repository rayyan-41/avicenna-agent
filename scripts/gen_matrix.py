"""Live generation matrix: prove the pipeline works end to end.

Runs one real generation per domain agent, spending real money and writing real
files into a real Obsidian vault. The safety net is the vault's own git history:
HEAD is recorded, revert instructions are printed, and the harness never mutates
git state on its own.

This script was written with the knowledge that it spends money. Every safety
mechanism exists because an accidental invocation of a six-cell matrix is a bill
the operator did not agree to.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from avicenna.bus import EventBus, drain
from avicenna.events import Event, NoteWritten, PreflightDeclared, RunComplete, RunFailed
from avicenna.pipeline.preflight import TEMPLATE_MINIMUMS
from avicenna.pipeline.run import execute_run
from avicenna.providers.base import LLMProvider
from avicenna.vault.models import Taxonomy
from avicenna.vault.vault import Vault

# The weaver alone allows 600s (WEAVER_TIMEOUT_S in stages.py). A full run
# touches 14 stages, several of which make model calls. 1800s (30 minutes) is
# generous enough to cover a slow weaver plus everything else, without letting a
# truly hung cell block the matrix forever.
CELL_TIMEOUT_S: float = 1800.0

# Each domain gets its own topic — a genuine half-formed idea, the kind this
# product exists to turn into a note. The mapping is keyed by the vault's own
# domain names (derived from taxonomy.json at runtime, never hardcoded).
#
# A single epistemology topic forced into six different domains would produce
# five off-domain notes: the art agent writing about knowledge and belief, filed
# under Art, is off-voice and the wikilink assertion will fail because the art
# corpus contains nothing about epistemology. That is a FALSE failure that looks
# like a product bug.
#
# Topics mention their target domain's vocabulary directly so the deterministic
# router (keyword scoring with W_DOMAIN=4.0) picks the right agent without
# needing domain_override. If a domain has no topic defined here, that cell is
# reported as SKIP rather than invented.
_DOMAIN_TOPICS: dict[str, str] = {
    "art": (
        "What makes an object art, and how does the artist's intention shape "
        "whether we encounter beauty or mere decoration"
    ),
    "history": (
        "How empires decline: whether the fall of Rome was driven by military "
        "overreach, internal decadence, or external pressure, and what the "
        "historical parallels teach about civilisational fragility"
    ),
    "islam": (
        "Islamic jurisprudence and the relationship between revelation and "
        "human reason in determining divine law"
    ),
    "literature": (
        "How literary fiction creates a kind of knowledge that philosophy and "
        "science cannot: the way narrative structure shapes what a reader "
        "understands about moral experience"
    ),
    "reason": (
        "Whether pure reason can establish moral obligations without appeal "
        "to experience, revelation, or tradition"
    ),
    "science": (
        "Why mathematical elegance in physics so often turns out to track "
        "truth: the unreasonable effectiveness of beautiful formalism in "
        "describing the physical world"
    ),
}


def _topic_for_domain(domain: str) -> str | None:
    """Return the topic for *domain*, or None if none is defined.

    The mapping covers the domains this vault ships with. A vault whose owner
    has added a new domain will see that cell reported as SKIP — a clear signal
    to extend this mapping rather than silently test a made-up topic.
    """
    return _DOMAIN_TOPICS.get(domain)


# Minimum word count for the general template, which every cell uses.
MIN_WORDS: int = TEMPLATE_MINIMUMS["general"]


# ---- data ----------------------------------------------------------------

@dataclass
class CellResult:
    domain: str
    agent: str
    status: str = ""        # PASS, FAIL, SKIP, TIMEOUT, ERROR, WARN
    words: int = 0
    elapsed: float = 0.0
    note_path: str = ""
    failed_assertions: list[str] = field(default_factory=list)
    routing_domain: str = ""  # domain routing actually chose (from PreflightDeclared)


# ---- git safety -----------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    """Run a read-only git command against a specific directory and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _git_head(vault_root: Path) -> str:
    head = _git(vault_root, "rev-parse", "HEAD")
    if not head:
        print(
            f"FATAL: {vault_root} is not inside a git repository.\n"
            "The vault must be a git repo so revert is possible.",
            file=sys.stderr,
        )
        sys.exit(1)
    return head


def _git_is_clean(vault_root: Path) -> bool:
    return _git(vault_root, "status", "--porcelain") == ""


def _git_revert_commands(head: str, vault_root: Path) -> list[str]:
    """Print the exact commands to restore the vault to its pre-matrix state.

    These exist so they are visible even if the process is killed mid-run. The
    harness NEVER executes them — deciding what to keep is the vault owner's call.
    """
    return [
        f"git -C {vault_root} checkout {head} -- .",
        f"git -C {vault_root} clean -fd",
    ]


# ---- note inspection helpers ----------------------------------------------

_WIKILINK = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")


def _body_and_frontmatter(
    text: str,
) -> tuple[dict[str, Any] | None, str]:
    """Split a note into parsed frontmatter and body text."""
    if not text.startswith("---"):
        return None, text
    end = text.find("---", 3)
    if end < 0:
        return None, text
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None, text[end + 3 :]
    body = text[end + 3 :].strip()
    return (fm if isinstance(fm, dict) else None), body


def _all_valid_tags(taxonomy: Taxonomy) -> set[str]:
    """Every string the closed taxonomy considers a valid tag."""
    tags: set[str] = set()
    tags.update(d.lower() for d in taxonomy.domains)
    for domain_cats in taxonomy.domains.values():
        tags.update(c.lower() for c in domain_cats)
    tags.update(c.lower() for c in taxonomy.universal_categories)
    tags.update(t.lower() for t in taxonomy.types)
    tags.update(t.lower() for t in taxonomy.themes)
    tags.update(m.lower() for m in taxonomy.markers)
    tags.update(r.lower() for r in taxonomy.reserved_modifiers)
    tags.add("moc")
    return tags


def _vault_note_index(vault: Vault) -> dict[str, Path]:
    """Map lowercased note stem -> absolute path for wikilink resolution."""
    index: dict[str, Path] = {}
    for md in vault.root.rglob("*.md"):
        rel = md.relative_to(vault.root).parts
        if not rel or rel[0].startswith(".") or rel[0] == "_tmp":
            continue
        index[md.stem.lower()] = md
    return index


# ---- per-cell assertions --------------------------------------------------

def _run_assertions(
    result: CellResult,
    note_path: Path,
    vault: Vault,
    valid_tags: set[str],
    note_index: dict[str, Path],
) -> None:
    """Check each assertion separately and record failures. Never stop early."""

    # 1. Note exists on disk.
    if not note_path.is_file():
        result.failed_assertions.append("note_missing")
        return                    # nothing else to check if the file is gone

    text = note_path.read_text(encoding="utf-8", errors="replace")

    # 2. Word count at or above the template minimum.
    #    Matches the pipeline's own counting: whitespace-split of the full text.
    words = len(text.split())
    result.words = words
    if words < MIN_WORDS:
        result.failed_assertions.append(f"wordcount ({words} < {MIN_WORDS})")

    # 3. YAML frontmatter parses.
    fm, body = _body_and_frontmatter(text)
    if fm is None:
        result.failed_assertions.append("frontmatter_parse")
        # Cannot check tags if frontmatter did not parse.
    else:
        # 4. Every tag drawn from the closed taxonomy.
        tags = fm.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                tag_str = str(tag).strip().lower()
                if tag_str and tag_str not in valid_tags:
                    result.failed_assertions.append(f"invalid_tag ({tag_str})")

    # 5. Every wikilink resolves to a note that exists in the vault.
    for match in _WIKILINK.finditer(body):
        target = match.group(1).strip().lower()
        if target not in note_index:
            result.failed_assertions.append(f"broken_wikilink ([[{match.group(1)}]])")

    # 6. Domain MOC contains an entry for the new note.
    domain_folder_name = (result.domain or "general").replace("-", " ").title()
    domain_dir = vault.root / domain_folder_name
    if domain_dir.is_dir():
        moc_files = list(domain_dir.glob("*MOC*.md")) + list(domain_dir.glob("*moc*.md"))
        if not moc_files:
            result.failed_assertions.append("no_moc_file")
        else:
            note_stem = note_path.stem.lower()
            found_in_moc = False
            for moc_file in moc_files:
                moc_text = moc_file.read_text(encoding="utf-8", errors="replace").lower()
                if note_stem in moc_text:
                    found_in_moc = True
                    break
            if not found_in_moc:
                result.failed_assertions.append("note_not_in_moc")
    else:
        result.failed_assertions.append("domain_folder_missing")


# ---- event collection from a single run -----------------------------------

@dataclass
class _RunEvents:
    """Accumulates facts from the EventBus during one run."""
    note_path: str = ""
    words: int = 0
    elapsed: float = 0.0
    failed: bool = False
    error: str = ""
    routed_domain: str = ""

    def on_event(self, event: Event) -> None:
        if isinstance(event, PreflightDeclared):
            self.routed_domain = event.domain
        elif isinstance(event, NoteWritten):
            self.note_path = event.path
            self.words = event.words
        elif isinstance(event, RunComplete):
            self.elapsed = event.elapsed
        elif isinstance(event, RunFailed):
            self.failed = True
            self.error = event.error


# ---- output ---------------------------------------------------------------

def _print_table(results: list[CellResult], elapsed: float) -> None:
    header = f"{'domain':<14} {'agent':<14} {'status':<8} {'words':>6} {'secs':>6}  failed"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for r in results:
        failed_desc = ", ".join(r.failed_assertions) if r.failed_assertions else "-"
        words_str = "-" if r.words < 0 else str(r.words)
        print(
            f"{r.domain:<14} {r.agent:<14} {r.status:<8} {words_str:>6} "
            f"{r.elapsed:>6.1f}  {failed_desc}"
        )
    print(sep)
    n_passed = sum(1 for r in results if r.status == "PASS")
    n_failed = sum(1 for r in results if r.status == "FAIL")
    n_skipped = sum(1 for r in results if r.status == "SKIP")
    n_warned = sum(1 for r in results if r.status == "WARN")
    warn_text = f", {n_warned} warned" if n_warned else ""
    print(f"{n_passed} passed, {n_failed} failed, {n_skipped} skipped{warn_text}  ({elapsed:.1f}s total)")


def _print_json(results: list[CellResult], elapsed: float) -> None:
    print(json.dumps({
        "cells": [
            {
                "domain": r.domain,
                "agent": r.agent,
                "status": r.status,
                "words": r.words if r.words >= 0 else None,
                "elapsed_s": round(r.elapsed, 1),
                "note_path": r.note_path,
                "failed_assertions": r.failed_assertions,
                "routing_domain": r.routing_domain or None,
            }
            for r in results
        ],
        "summary": {
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
            "skipped": sum(1 for r in results if r.status == "SKIP"),
            "warnings": sum(1 for r in results if r.status == "WARN"),
            "total_s": round(elapsed, 1),
        },
    }))


# ---- single cell ----------------------------------------------------------

async def _run_cell(
    domain: str,
    topic: str | None,
    provider: LLMProvider,
    vault: Vault,
    dry_run: bool,
    timeout: float,
    valid_tags: set[str],
    note_index: dict[str, Path],
    *,
    force_domain: bool = False,
) -> CellResult:
    """Execute one cell and return a populated CellResult."""

    # No topic for this domain — report as SKIP rather than invent one.
    if not topic:
        return CellResult(
            domain=domain, agent="(none)", status="SKIP",
            failed_assertions=["no_topic_defined"],
        )

    # Content agents are keyed by name, not by domain. Walk the registry.
    agent = None
    for a in vault.agents.values():
        if a.type == "content" and a.domain == domain:
            agent = a
            break
    if agent is None:
        return CellResult(domain=domain, agent="(none)", status="SKIP")

    result = CellResult(domain=domain, agent=agent.name)

    bus = EventBus()
    collector = _RunEvents()
    q = bus.subscribe()

    # domain_override is off by default because overriding the domain hides
    # exactly the failure this matrix exists to catch: routing sending a topic
    # to the wrong agent. force_domain re-enables it for single-cell debugging.
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            execute_run(
                topic,
                provider,
                vault,
                bus=bus,
                dry_run=dry_run,
                domain_override=domain if force_domain else None,
                template_override="general",
            ),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, TimeoutError):
        result.status = "TIMEOUT"
        result.elapsed = time.monotonic() - t0
        await bus.close()
        async for event in drain(q):
            collector.on_event(event)
        return result
    except Exception as exc:
        result.status = "ERROR"
        result.elapsed = time.monotonic() - t0
        result.failed_assertions.append(str(exc)[:120])
        await bus.close()
        async for event in drain(q):
            collector.on_event(event)
        return result

    # Close the bus (sends the None sentinel) then drain everything. The
    # drain loop exits when it hits the sentinel, so this never hangs.
    await bus.close()
    async for event in drain(q):
        collector.on_event(event)

    result.elapsed = time.monotonic() - t0
    result.note_path = collector.note_path
    result.routing_domain = collector.routed_domain

    # A failed run must be caught before anything else — both in live and in
    # dry-run mode.  The old code set PASS inside the dry-run branch and
    # returned before this check, so a dry-run cell whose pipeline actually
    # failed was reported as PASS.
    if collector.failed:
        result.status = "ERROR"
        result.failed_assertions.append(collector.error[:120] or "run_failed")
        return result

    if dry_run:
        # In dry-run the pipeline ran routing + preflight only. Record the
        # routing decision and compare it to the expected domain.
        result.words = -1  # no note was written; display as "-"

        if not force_domain:
            if not collector.routed_domain:
                # Routing returned None — the cell's topic could not be
                # assigned to a domain.  That is a legitimate product
                # behaviour, but it means the cell did not verify anything.
                result.status = "FAIL"
                result.failed_assertions.append("routing_refused")
            elif collector.routed_domain != domain:
                result.failed_assertions.append(
                    f"routing_mismatch (expected={domain}, "
                    f"got={collector.routed_domain})"
                )
                result.status = "WARN"
            else:
                result.status = "PASS"
        else:
            result.status = "PASS"
        return result

    # Compare routing decision to the expected domain. A mismatch is a WARN,
    # not a FAIL: routing is vault-tuned and the owner may have tuned it so a
    # topic lands elsewhere. But a silent mismatch would mean the note was
    # filed somewhere the operator did not expect.
    if not force_domain and collector.routed_domain:
        if collector.routed_domain != domain:
            result.failed_assertions.append(
                f"routing_mismatch (expected={domain}, "
                f"got={collector.routed_domain})"
            )

    note_path = Path(collector.note_path) if collector.note_path else Path()
    _run_assertions(result, note_path, vault, valid_tags, note_index)

    if result.failed_assertions:
        result.status = "WARN" if all(
            a.startswith("routing_mismatch") for a in result.failed_assertions
        ) else "FAIL"
    else:
        result.status = "PASS"
    return result


# ---- CLI ------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Live generation matrix: one note per domain agent.",
    )
    p.add_argument("--vault", type=Path, default=None, help="Path to the Obsidian vault")
    p.add_argument(
        "--yes", action="store_true",
        help="Actually run the matrix. Without this flag, the plan is printed and nothing happens.",
    )
    p.add_argument("--dry-run", action="store_true", help="Routing + preflight only; write nothing")
    p.add_argument("--only", type=str, default=None, help="Run a single domain only")
    p.add_argument("--json", action="store_true", dest="json_mode", help="Machine-readable JSON output")
    p.add_argument(
        "--force-domain", action="store_true", dest="force_domain",
        help=(
            "Override routing and force the expected domain. For single-cell "
            "debugging only (use with --only). Off by default because overriding "
            "the domain hides exactly the failure this matrix exists to catch."
        ),
    )
    p.add_argument(
        "--timeout", type=float, default=CELL_TIMEOUT_S,
        help=f"Per-cell timeout in seconds (default {CELL_TIMEOUT_S:.0f})",
    )
    return p


async def _async_main(args: argparse.Namespace) -> int:
    # -- vault discovery ----------------------------------------------------
    from avicenna.vault.context import VaultContext

    ctx = VaultContext.detect(explicit=args.vault)
    if not ctx.found:
        print("No vault found. Pass --vault or run from inside a vault.", file=sys.stderr)
        return 1
    assert ctx.root is not None
    vault_root = ctx.root

    # -- git safety (record state, block later only when --yes) -------------
    head = _git_head(vault_root)
    is_clean = _git_is_clean(vault_root)

    # -- load the vault -----------------------------------------------------
    vault = Vault.load(vault_root)

    # -- derive the domain list from the taxonomy, not from a hardcoded list -
    all_domains = sorted(vault.taxonomy.domains.keys())

    if args.only:
        if args.only not in all_domains:
            print(
                f"Unknown domain {args.only!r}. Known: {all_domains}",
                file=sys.stderr,
            )
            return 1
        domains = [args.only]
    else:
        domains = all_domains

    # --force-domain overrides routing for a single cell. Using it across the
    # whole matrix defeats the purpose: every cell would be forced to the same
    # domain on different topics, producing one real note and N duplicates.
    if args.force_domain and not args.only:
        print(
            "--force-domain requires --only (debugging a single cell). "
            "Running the full matrix with forced domains would bypass routing "
            "for every cell, which is the exact failure this matrix catches.",
            file=sys.stderr,
        )
        return 1

    # -- print the plan (always) --------------------------------------------
    revert_cmds = _git_revert_commands(head, vault_root)

    if not args.json_mode:
        tree_label = "clean" if is_clean else "DIRTY"
        print(f"vault:  {vault_root}")
        print(f"HEAD:   {head}")
        print(f"tree:   {tree_label}")
        print(f"mode:   {'dry-run' if args.dry_run else 'live'}")
        if args.force_domain:
            print(f"force:  domain_override ON (--only {args.only})")
        print(f"timeout per cell: {args.timeout:.0f}s")
        print()
        print("domains:")
        for d in domains:
            topic = _topic_for_domain(d)
            has_agent = any(
                a.type == "content" and a.domain == d for a in vault.agents.values()
            )
            agent_name = next(
                (a.name for a in vault.agents.values()
                 if a.type == "content" and a.domain == d),
                "(none)",
            )
            if not topic:
                status = "SKIP (no topic defined)"
            elif not has_agent:
                status = "SKIP (no content agent)"
            else:
                status = agent_name
            topic_preview = (topic or "")[:60]
            if topic and len(topic) > 60:
                topic_preview += "..."
            print(f"  {d:<14} {status:<20} {topic_preview}")
        print()
        print("revert commands (run these if you need to undo):")
        for cmd in revert_cmds:
            print(f"  {cmd}")
        print()

    if not args.yes:
        if not args.json_mode:
            print("Pass --yes to generate. Exiting without running.")
        return 0

    # -- safety gate: dirty tree blocks generation --------------------------
    if not is_clean:
        print(
            "FATAL: vault working tree is dirty. Commit or stash your changes first.\n"
            "A dirty tree means the revert instructions cannot be trusted.",
            file=sys.stderr,
        )
        return 1

    # Pre-compute shared state for assertions.
    valid_tags = _all_valid_tags(vault.taxonomy)
    note_index = _vault_note_index(vault)

    # -- provider (routing + preflight call the model even in dry-run) ------
    from avicenna.secrets import read_api_key
    from avicenna.config import Config
    from avicenna.providers.registry import get_provider

    key = read_api_key()
    if not key:
        print(
            "No API key found. Set MISTRAL_API_KEY in .env or run `avicenna` to configure.",
            file=sys.stderr,
        )
        return 1
    provider = get_provider("mistral", api_key=key, model=Config.MISTRAL_MODEL)

    # -- execute the matrix, sequentially -----------------------------------
    results: list[CellResult] = []
    t0 = time.monotonic()

    for domain in domains:
        topic = _topic_for_domain(domain)
        if not args.json_mode:
            label = "dry-run" if args.dry_run else "generate"
            print(f"[{label}] {domain} ...", file=sys.stderr, flush=True)
        result = await _run_cell(
            domain,
            topic,
            provider,
            vault,
            args.dry_run,
            args.timeout,
            valid_tags,
            note_index,
            force_domain=args.force_domain,
        )
        results.append(result)
        if not args.json_mode:
            words_label = "-" if result.words < 0 else f"{result.words} words"
            print(
                f"[{result.status}] {domain} ({result.elapsed:.1f}s, {words_label})",
                file=sys.stderr,
                flush=True,
            )

    total_elapsed = time.monotonic() - t0

    # -- output -------------------------------------------------------------
    if args.json_mode:
        _print_json(results, total_elapsed)
    else:
        print()
        _print_table(results, total_elapsed)

    any_failed = any(r.status in ("FAIL", "TIMEOUT", "ERROR") for r in results)
    return 1 if any_failed else 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    code = asyncio.run(_async_main(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
