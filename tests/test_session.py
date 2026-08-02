"""Session tests using FakeProvider."""

from __future__ import annotations

import pytest

from avicenna.providers.base import Completion, Message, ToolCall
from avicenna.providers.fake import FakeProvider
from avicenna.session import MAX_TOOL_ITERATIONS, Session, one_shot


@pytest.mark.asyncio
async def test_session_simple_reply():
    p = FakeProvider(script=[Completion(text="hello")])
    session = Session(provider=p, system="sys")
    result = await session.send("hi")
    assert result.text == "hello"
    assert len(session.messages) == 2  # user + assistant


@pytest.mark.asyncio
async def test_session_multi_turn():
    replies = [Completion(text="a"), Completion(text="b")]
    p = FakeProvider(script=replies)
    session = Session(provider=p, system="sys")
    r1 = await session.send("1")
    r2 = await session.send("2")
    assert r1.text == "a"
    assert r2.text == "b"
    assert len(session.messages) == 4


@pytest.mark.asyncio
async def test_tool_loop():
    call_count = 0

    class FakeRunner:
        async def call(self, name, args):
            nonlocal call_count
            call_count += 1
            return "done"

        def source_of(self, name):
            return "test"

        def specs(self):
            return []

    replies = [
        Completion(text="", tool_calls=(ToolCall(id="c1", name="f", arguments={}),)),
        Completion(text="final"),
    ]
    p = FakeProvider(script=replies)
    session = Session(provider=p, system="sys", tool_runner=FakeRunner())
    result = await session.send("go")
    assert result.text == "final"
    assert call_count == 1
    # user, assistant (with tool calls), tool result, assistant (final)
    assert len(session.messages) == 4
    assert session.messages[2].role == "tool"
    assert session.messages[2].tool_call_id == "c1"


@pytest.mark.asyncio
async def test_tool_loop_exceeded():
    tool_call = ToolCall(id="c1", name="f", arguments={})
    # always returns a tool call — infinite loop
    p = FakeProvider(script=[Completion(text="", tool_calls=(tool_call,))] * (MAX_TOOL_ITERATIONS + 1))

    class FakeRunner:
        async def call(self, name, args):
            return "done"

        def source_of(self, name):
            return "test"

        def specs(self):
            return []

    session = Session(provider=p, system="sys", tool_runner=FakeRunner())
    with pytest.raises(RuntimeError, match="tool loop exceeded"):
        await session.send("go")


@pytest.mark.asyncio
async def test_one_shot_fresh_context():
    """Fresh-context proof: two one_shot calls each have messages length 1."""
    calls: list[list[Message]] = []

    def script(system: str, messages: list[Message]) -> Completion:
        calls.append(list(messages))
        return Completion(text="ok")

    p = FakeProvider(script=script)
    await one_shot(p, "sys", "first")
    await one_shot(p, "sys", "second")
    assert len(calls) == 2
    assert len(calls[0]) == 1
    assert len(calls[1]) == 1
