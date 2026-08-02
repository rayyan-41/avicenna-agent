"""Agent chat controller: one AgentChat per vault agent.

Uses Phase 3 Session with the agent's system_prompt and a persisted
message list. Tools are restricted to read-only builtins plus the
agent's declared MCP tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from avicenna.bus import EventBus
from avicenna.providers.base import Completion, LLMProvider, Message, ToolSpec
from avicenna.session import Session
from avicenna.tools.registry import ToolRegistry
from avicenna.vault.models import AgentDef

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


class AgentChatController:
    def __init__(
        self,
        vault,
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

    def tools_for(self, agent: AgentDef) -> list[ToolSpec]:
        allow = list(CHAT_SAFE_TOOLS) + list(getattr(agent, 'mcp', []))
        return self.registry.spec_for_model(allow=allow)

    def select(self, name: str) -> AgentDef:
        agent = self.vault.agents[name]
        self.chats.setdefault(name, AgentChat(agent=agent))
        self.active = name
        return agent

    async def send(self, text: str, run_id: str) -> Completion:
        assert self.active is not None
        chat = self.chats[self.active]
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
        session.messages = chat.history
        completion = await session.send(text)
        chat.history = session.messages
        chat.turns += 1
        if completion.usage is not None:
            chat.prompt_tokens += completion.usage.prompt_tokens
            chat.completion_tokens += completion.usage.completion_tokens
        return completion
