"""Declarative manifest of vault PowerShell tools.

Maps script filename to display name, description, JSON Schema
parameters, and access class. Scripts absent from the manifest register
as PIPELINE_ONLY with a warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from avicenna.tools.base import ToolAccess
from avicenna.tools.powershell import PowerShellTool
from avicenna.tools.registry import ToolRegistry


class ToolEntry(TypedDict):
    """One manifest row.

    Typed rather than `dict[str, object]` so the fields keep their types all
    the way to the PowerShellTool constructor; with a bare object-valued dict
    every field arrived as `object` and had to be cast at the call site.
    """

    name: str
    description: str
    parameters: dict[str, object]
    access: ToolAccess


VAULT_TOOL_MANIFEST: dict[str, ToolEntry] = {
    "write_manifest.ps1": {
        "name": "write_manifest",
        "description": "Create the generated-note manifest spec tracking all chunks and state",
        "parameters": {"type": "object", "properties": {
            "Slug": {"type": "string"},
            "Headings": {"type": "string", "description": "Comma-separated heading list"},
        }, "required": ["Slug", "Headings"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "update_pipeline_state.ps1": {
        "name": "update_pipeline_state",
        "description": "Record pipeline stage progress in a manifest sidecar",
        "parameters": {"type": "object", "properties": {
            "Slug": {"type": "string"},
            "Stage": {"type": "string"},
            "Status": {"type": "string"},
            "Note": {"type": "string"},
        }, "required": ["Slug", "Stage", "Status"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "verify_chunks.ps1": {
        "name": "verify_chunks",
        "description": "Verify all expected chunk files exist (verify mode) or read them back (read mode)",
        "parameters": {"type": "object", "properties": {
            "Slug": {"type": "string"},
            "ExpectedCount": {"type": "integer"},
            "Mode": {"type": "string", "enum": ["verify", "read"]},
        }, "required": ["Slug", "ExpectedCount"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "validate_wordcount.ps1": {
        "name": "validate_wordcount",
        "description": "Check a note meets the minimum word-count threshold",
        "parameters": {"type": "object", "properties": {
            "FilePath": {"type": "string"},
            "MinWords": {"type": "integer"},
            "Template": {"type": "string"},
        }, "required": ["FilePath", "MinWords"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "validate_tags.ps1": {
        "name": "validate_tags",
        "description": "Validate a comma-separated tag line against the taxonomy",
        "parameters": {"type": "object", "properties": {
            "TagLine": {"type": "string"},
            "Explain": {"type": "string"},
        }, "required": ["TagLine"]},
        "access": ToolAccess.MODEL_CALLABLE,
    },
    "generate_toc.ps1": {
        "name": "generate_toc",
        "description": "Insert a table of contents into a note",
        "parameters": {"type": "object", "properties": {
            "FilePath": {"type": "string"},
            "MinHeadings": {"type": "integer"},
            "Force": {},
            "WhatIfOnly": {},
        }, "required": ["FilePath"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "get_related_notes.ps1": {
        "name": "get_related_notes",
        "description": "Find notes related by tags and link policy",
        "parameters": {"type": "object", "properties": {
            "NotePath": {"type": "string"},
            "CoreTags": {"type": "string"},
            "SupportingTags": {"type": "string"},
            "ExcludedMentions": {"type": "string"},
            "TopN": {"type": "integer"},
            "MinScore": {"type": "number"},
        }, "required": ["NotePath", "CoreTags"]},
        "access": ToolAccess.MODEL_CALLABLE,
    },
    "update_moc.ps1": {
        "name": "update_moc",
        "description": "Update the Map of Content for a domain",
        "parameters": {"type": "object", "properties": {
            "Domain": {"type": "string"},
            "NoteTitle": {"type": "string"},
            "NoteFilename": {"type": "string"},
            "Category": {"type": "string"},
            "Rebuild": {},
        }, "required": ["Domain"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "cleanup_chunks.ps1": {
        "name": "cleanup_chunks",
        "description": "Delete temporary chunk and sidecar files after assembly",
        "parameters": {"type": "object", "properties": {
            "Slug": {"type": "string"},
        }, "required": ["Slug"]},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "count_citations.ps1": {
        "name": "count_citations",
        "description": "Verify citation integrity in a note",
        "parameters": {"type": "object", "properties": {
            "FilePath": {"type": "string"},
            "WordCount": {"type": "integer"},
        }, "required": ["FilePath"]},
        "access": ToolAccess.MODEL_CALLABLE,
    },
    "generate_index.ps1": {
        "name": "generate_index",
        "description": "Generate an index of vault notes",
        "parameters": {"type": "object", "properties": {
            "Domain": {"type": "string"},
            "Format": {"type": "string", "enum": ["text", "json"]},
            "IncludeOrphans": {},
        }},
        "access": ToolAccess.MODEL_CALLABLE,
    },
    "audit_skill_sync.ps1": {
        "name": "audit_skill_sync",
        "description": "Audit agent/skill definitions for consistency",
        "parameters": {"type": "object", "properties": {
            "VerboseOutput": {},
        }},
        "access": ToolAccess.MODEL_CALLABLE,
    },
    "run_standardize.ps1": {
        "name": "run_standardize",
        "description": "Standardize note formatting for a domain",
        "parameters": {"type": "object", "properties": {
            "domain": {"type": "string"},
            "AgentCommand": {"type": "string"},
        }},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "run_vault_wide_standardize.ps1": {
        "name": "run_vault_wide_standardize",
        "description": "Batch standardize all notes in the vault",
        "parameters": {"type": "object", "properties": {
            "AgentCommand": {"type": "string"},
        }},
        "access": ToolAccess.PIPELINE_ONLY,
    },
    "word_count.ps1": {
        "name": "word_count",
        "description": "Count words in a file",
        "parameters": {"type": "object", "properties": {
            "FilePath": {"type": "string"},
        }, "required": ["FilePath"]},
        "access": ToolAccess.MODEL_CALLABLE,
    },
}


def register_vault_tools(vault_root: Path, registry: ToolRegistry) -> None:
    tools_dir = vault_root / ".agents" / "tools"
    if not tools_dir.is_dir():
        return

    for script_path in sorted(tools_dir.glob("*.ps1")):
        filename = script_path.name
        entry = VAULT_TOOL_MANIFEST.get(filename)
        if entry is None:
            # Script absent from manifest — register as pipeline-only with warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("vault tool %s has no manifest entry; registering as pipeline-only", filename)
            entry = ToolEntry(
                name=script_path.stem,
                description=f"Vault tool: {script_path.stem}",
                parameters={"type": "object", "properties": {}},
                access=ToolAccess.PIPELINE_ONLY,
            )
        tool = PowerShellTool(
            name=entry["name"],
            script=script_path,
            vault_root=vault_root,
            description=entry["description"],
            parameters=entry["parameters"],
            access=entry["access"],
        )
        registry.register(tool)
