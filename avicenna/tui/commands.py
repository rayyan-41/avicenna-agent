"""Slash command dispatcher.

Registered: /agent <name>, /agents, /note <topic>, /vault, /mcp, /clear,
/help, /save. Unknown commands fall through to the model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

Handler = Callable[[list[str]], Awaitable[None]]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        self._handlers[name] = handler

    def is_command(self, text: str) -> bool:
        return text.startswith("/")

    async def dispatch(self, text: str) -> bool:
        """Return True if handled, False if the text should go to the model."""
        name, _, rest = text[1:].partition(" ")
        handler = self._handlers.get(name.lower())
        if handler is None:
            return False
        await handler(rest.split() if rest else [])
        return True
