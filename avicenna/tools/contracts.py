"""Declarative tool contracts.

A contract is a pair of regex patterns (success, failure). The runner
branches on the regex match, never on the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Mapping
from re import Pattern


@dataclass(slots=True)
class ParsedContract:
    tool: str
    ok: bool
    token: str                       # e.g. "ALL_PRESENT", "WORDCOUNT_FAIL"
    captures: dict[str, str] = field(default_factory=dict)
    detail: str = ""

    def render(self) -> str:
        caps = " ".join(f"{k}={v}" for k, v in self.captures.items())
        return f"{self.token}{' ' + caps if caps else ''} {self.detail}".strip()


@dataclass(slots=True)
class ToolContract:
    tool: str
    success: Pattern[str]
    failure: Pattern[str] | None = None
    trust_exit_code: bool = True

    def parse(self, tool: str, stdout: str, stderr: str, exit_code: int) -> ParsedContract:
        blob = f"{stdout}\n{stderr}"
        m = self.success.search(blob)
        if m and (not self.trust_exit_code or exit_code == 0):
            return ParsedContract(tool, True, m.group(0).split(":")[0].strip(),
                                  {k: v for k, v in (m.groupdict() or {}).items() if v},
                                  detail=m.group(0).strip())
        if self.failure is not None:
            f = self.failure.search(blob)
            if f:
                return ParsedContract(tool, False, f.group(0).split(":")[0].strip(),
                                      {k: v for k, v in (f.groupdict() or {}).items() if v},
                                      detail=f.group(0).strip())
        return ParsedContract(tool, False, "CONTRACT_UNMATCHED",
                              detail=(stdout or stderr).strip()[:400])


CONTRACTS: Mapping[str, ToolContract] = {
    "write_manifest": ToolContract(
        "write_manifest",
        success=re.compile(r"MANIFEST_WRITTEN:\s*(?P<path>.+?)\s*\((?P<chunks>\d+)\s+chunks expected\)"),
        failure=re.compile(r"MANIFEST_ERROR:\s*(?P<reason>.+)"),
    ),
    "verify_chunks": ToolContract(
        "verify_chunks",
        success=re.compile(r"ALL_PRESENT:\s*(?P<present>\d+)/(?P<expected>\d+)"),
        failure=re.compile(r"MISSING:\s*(?P<missing>\d+)/(?P<expected>\d+)"),
    ),
    "validate_wordcount": ToolContract(
        "validate_wordcount",
        success=re.compile(r"WORDCOUNT_PASS"),
        failure=re.compile(r"WORDCOUNT_FAIL:\s*(?P<short>\d+)\s+words short"),
    ),
    "validate_tags": ToolContract(
        "validate_tags",
        success=re.compile(r"^PASS\b", re.MULTILINE),
        failure=re.compile(r"^FAIL:\s*(?P<reasons>.+)", re.MULTILINE),
    ),
    "generate_toc": ToolContract(
        "generate_toc",
        success=re.compile(r"TOC_WRITTEN:\s*(?P<headings>\d+)\s+headings"),
        failure=re.compile(r"TOC_SKIPPED:\s*(?P<reason>.+)"),
    ),
    "get_related_notes": ToolContract(
        "get_related_notes",
        success=re.compile(r"CANDIDATES_FOUND:\s*(?P<count>[1-9]\d*)"),
        failure=re.compile(r"CANDIDATES_FOUND:\s*0|NO_POLICY_VALID_CANDIDATES:\s*(?P<why>.*)"),
    ),
    "update_moc": ToolContract(
        "update_moc",
        success=re.compile(r"(?P<token>MOC_UPDATED|MOC_CREATED|MOC_REBUILT|ALREADY_LISTED):\s*(?P<detail>.*)"),
        failure=re.compile(r"(?P<token>MOC_ERROR|MOC_WARNING):\s*(?P<detail>.*)"),
    ),
    "cleanup_chunks": ToolContract(
        "cleanup_chunks",
        success=re.compile(r"DELETED:\s*(?P<chunks>\d+)\s+chunk file\(s\)"),
        failure=re.compile(r"PARTIAL"),
    ),
    "count_citations": ToolContract(
        "count_citations",
        success=re.compile(r"CITATION_INTEGRITY:\s*PASS"),
        failure=re.compile(r"CITATION_INTEGRITY:\s*FAIL"),
    ),
}
