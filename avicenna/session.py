"""Session and one_shot: the two runtime primitives.

Session owns a message list and layers multi-turn chat plus the tool
resolution loop on top of the stateless provider.
one_shot is SPAWN_SECTION: fresh context, used once, immediately discarded.
"""

from __future__ import annotations

import time
from typing import Optional

from avicenna.bus import EventBus
from avicenna.events import ToolInvoked, ToolReturned
from avicenna.providers.base import Completion, LLMProvider, Message, ToolCall, ToolSpec
from avicenna.tools.runner import ToolRunner

MAX_TOOL_ITERATIONS = 8


class Session:
    def __init__(
        self,
        provider: LLMProvider,
        system: str,
        tools: list[ToolSpec] | None = None,
        tool_runner: ToolRunner | None = None,
        bus: EventBus | None = None,
        run_id: str = "",
        section_index: int | None = None,
        temperature: float | None = None,
    ) -> None:
        self.provider = provider
        self.system = system
        self.tools = tools or []
        self.tool_runner = tool_runner
        self.bus = bus
        self.run_id = run_id
        self.section_index = section_index
        self.temperature = temperature
        self.messages: list[Message] = []

    async def send(self, user_text: str) -> Completion:
        self.messages.append(Message(role="user", content=user_text))
        return await self._resolve()

    async def _resolve(self) -> Completion:
        for _ in range(MAX_TOOL_ITERATIONS):
            completion = await self.provider.complete(
                system=self.system,
                messages=self.messages,
                tools=self.tools or None,
                temperature=self.temperature,
            )
            self.messages.append(
                Message(
                    role="assistant",
                    content=completion.text or "",
                    tool_calls=completion.tool_calls,
                )
            )
            if not completion.wants_tools:
                return completion
            if self.tool_runner is None:
                raise RuntimeError("model requested tools but no tool_runner was given")
            for call in completion.tool_calls:
                result = await self._run_tool(call)
                self.messages.append(
                    Message(
                        role="tool",
                        content=result,
                        name=call.name,
                        tool_call_id=call.id,
                    )
                )
        raise RuntimeError(
            f"tool loop exceeded {MAX_TOOL_ITERATIONS} iterations; aborting"
        )

    async def _run_tool(self, call: ToolCall) -> str:
        assert self.tool_runner is not None
        started = time.perf_counter()
        if self.bus:
            await self.bus.emit(ToolInvoked(
                run_id=self.run_id, name=call.name, args=call.arguments,
                source=self.tool_runner.source_of(call.name),
                section_index=self.section_index,
            ))
        try:
            result = await self.tool_runner.call(call.name, call.arguments)
            ok = True
        except Exception as exc:  # noqa: BLE001 - boundary
            result, ok = f"TOOL ERROR: {exc}", False
        if self.bus:
            await self.bus.emit(ToolReturned(
                run_id=self.run_id, name=call.name, contract=result[:400], ok=ok,
                elapsed=time.perf_counter() - started,
                section_index=self.section_index,
            ))
        return result


async def one_shot(
    provider: LLMProvider,
    system: str,
    prompt: str,
    tools: list[ToolSpec] | None = None,
    tool_runner: ToolRunner | None = None,
    bus: EventBus | None = None,
    run_id: str = "",
    section_index: int | None = None,
    temperature: float | None = None,
) -> str:
    session = Session(
        provider, system, tools, tool_runner, bus, run_id, section_index, temperature
    )
    completion = await session.send(prompt)
    return completion.text or ""
