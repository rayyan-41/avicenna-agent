"""Agent chat controller: one AgentChat per vault agent.

Frontend-agnostic. Lives in the core rather than the frontend because the
tool-allowlist below is a safety boundary, not a presentation detail: chat
turns get read-only tools, and the pipeline-only mutators (update_moc,
cleanup_chunks) must stay unreachable from a chat prompt no matter which
frontend is driving.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from avicenna.bus import EventBus
from avicenna.providers.base import Completion, LLMProvider, Message, ToolSpec
from avicenna.session import Session
from avicenna.tools.registry import ToolRegistry
from avicenna.vault.models import AgentDef
from avicenna.vault.vault import Vault

CHAT_SAFE_TOOLS: tuple[str, ...] = (
    "read_note", "search_vault", "list_notes", "get_related_notes", "validate_tags",
)


@dataclass
class AgentChat:
    agent: AgentDef
    history: list[Message] = field(default_factory=list)
    turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatError(RuntimeError):
    """A chat turn that cannot proceed, phrased for the user."""


class AgentChatController:
    def __init__(
        self,
        vault: Vault,
        provider: LLMProvider,
        bus: EventBus,
        registry: ToolRegistry,
    ) -> None:
        self.vault = vault
        self.provider = provider
        self.bus = bus
        self.registry = registry
        self.chats: dict[str, AgentChat] = {}
        self.active: str | None = None
        # One turn per agent at a time. Two concurrent sends against the same
        # chat interleaved their appends into a single shared history list and
        # produced user/user/assistant/assistant orderings.
        self._locks: dict[str, asyncio.Lock] = {}

    def tools_for(self, agent: AgentDef) -> list[ToolSpec]:
        allow = list(CHAT_SAFE_TOOLS) + [str(m) for m in (getattr(agent, "mcp", None) or [])]
        return self.registry.spec_for_model(allow=allow)

    def select(self, name: str) -> AgentDef:
        agent = self.vault.agents[name]
        self.chats.setdefault(name, AgentChat(agent=agent))
        self.active = name
        return agent

    def clear(self, name: str | None = None) -> None:
        """Drop history for one agent, or for the active one."""
        target = name or self.active
        if target and target in self.chats:
            chat = self.chats[target]
            chat.history = []
            chat.turns = 0

    async def send(self, text: str, run_id: str) -> Completion:
        # Not an assert: under `python -O` asserts vanish, and this one was
        # load-bearing — without it the next line raises KeyError(None).
        if self.active is None:
            raise ChatError("No agent selected. Use /agent <name> first.")
        active = self.active
        chat = self.chats[active]
        lock = self._locks.setdefault(active, asyncio.Lock())
        async with lock:
            session = Session(
                provider=self.provider,
                system=chat.agent.system_prompt,
                tools=self.tools_for(chat.agent),
                tool_runner=self.registry.runner,
                bus=self.bus,
                run_id=run_id,
                section_index=None,
                temperature=0.7,
            )
            # A copy, not the list itself. Session appends in place, so sharing
            # the object meant a failed turn still mutated the stored history.
            session.messages = list(chat.history)
            completion = await session.send(text)
            chat.history = session.messages
            chat.turns += 1
            if completion.usage is not None:
                chat.prompt_tokens += completion.usage.prompt_tokens
                chat.completion_tokens += completion.usage.completion_tokens
            return completion


__all__ = ["CHAT_SAFE_TOOLS", "AgentChat", "AgentChatController", "ChatError"]
