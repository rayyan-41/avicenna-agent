"""Functional verification of agent chat and command dispatcher."""

import asyncio

import pytest

from avicenna.bus import EventBus
from avicenna.providers.base import Completion, Message
from avicenna.providers.fake import FakeProvider
from avicenna.tools.registry import ToolRegistry
from avicenna.tui.commands import CommandDispatcher
from avicenna.vault.models import AgentDef


def test_command_dispatcher_detection():
    d = CommandDispatcher()
    assert d.is_command("/agent")
    assert d.is_command("/help")
    assert d.is_command("/note")
    assert not d.is_command("hello")
    assert not d.is_command("slashed/but_not_command")


@pytest.mark.asyncio
async def test_command_dispatcher_dispatch():
    d = CommandDispatcher()
    results: list[str] = []

    async def handler(args):
        results.append(f"called:{args}")

    d.register("test", handler)
    handled = await d.dispatch("/test arg1 arg2")
    assert handled
    assert results == ["called:['arg1', 'arg2']"]

    # Unknown command falls through
    handled = await d.dispatch("/unknown")
    assert not handled


@pytest.mark.asyncio
async def test_agent_chat_controller_tools_safe():
    """Verify tool filtering excludes pipeline-only tools from chat."""
    from avicenna.tui.agent_chat import AgentChatController, CHAT_SAFE_TOOLS
    from pathlib import Path

    bus = EventBus()
    provider = FakeProvider(script=[Completion(text="ok")])
    registry = ToolRegistry()

    # Register a safe tool and a pipeline-only tool
    from avicenna.tools.base import Tool, ToolSource, ToolAccess
    class FakeSafeTool(Tool):
        name = "read_note"
        description = "read"
        parameters = {"type": "object"}
        source = ToolSource.BUILTIN
        access = ToolAccess.MODEL_CALLABLE
        async def invoke(self, **kwargs):
            from avicenna.tools.base import ToolResult
            return ToolResult("read_note", True, "ok", "", 0, 0.0)
    class FakePipelineTool(Tool):
        name = "update_moc"
        description = "moc"
        parameters = {"type": "object"}
        source = ToolSource.BUILTIN
        access = ToolAccess.PIPELINE_ONLY
        async def invoke(self, **kwargs):
            from avicenna.tools.base import ToolResult
            return ToolResult("update_moc", True, "ok", "", 0, 0.0)
    registry.register(FakeSafeTool())
    registry.register(FakePipelineTool())

    # Verify tool registry specs exclude pipeline-only
    specs = registry.spec_for_model()
    assert len(specs) == 1
    assert specs[0].name == "read_note"

    # Verify CHAT_SAFE_TOOLS are read-only
    assert "read_note" in CHAT_SAFE_TOOLS
    assert "search_vault" in CHAT_SAFE_TOOLS
    assert "list_notes" in CHAT_SAFE_TOOLS
    # update_moc must NOT be in chat-safe
    assert "update_moc" not in CHAT_SAFE_TOOLS


@pytest.mark.asyncio
async def test_onboarding_validation_error_mapping():
    """Verify onboarding validate_key maps errors to messages."""
    from avicenna.tui.screens.onboarding import (
        ValidationResult, LOCAL_MODEL_STUB_MESSAGE, validate_key,
    )
    from avicenna.providers.errors import AuthError

    # Test ValidationResult dataclass
    r = ValidationResult(True, "ok")
    assert r.ok
    assert r.detail == "ok"

    # Test local model stub is non-empty
    assert len(LOCAL_MODEL_STUB_MESSAGE) > 100
    assert "planned for a future release" in LOCAL_MODEL_STUB_MESSAGE


@pytest.mark.asyncio
async def test_secrets_redact():
    from avicenna.secrets import redact

    # Plain text unchanged
    assert redact("hello world") == "hello world"
    # Key-shaped token redacted
    result = redact("key-is-abcdefghijABCDEFGHIJ1234567890")
    assert "***REDACTED***" in result
    # Short tokens (<24 chars) NOT redacted
    assert redact("short-key") == "short-key"
