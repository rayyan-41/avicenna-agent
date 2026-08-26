"""The stdio bridge: the whole agent core behind one line protocol.

The frontend is a separate process in another language, so everything it needs
has to cross a pipe. This module is the only place that knows that.

Two invariants hold the protocol together:

  * stdout belongs to the protocol and nothing else. The core prints to stdout
    in several places (rich consoles in config.py, typer echoes), and one stray
    line would desync the frontend's parser, so sys.stdout is redirected to
    stderr for the process lifetime and frames are written to a private handle.
  * A request never blocks the event stream. Long work (a note run, a chat
    turn) is dispatched to a task and answered immediately with an id; progress
    arrives as events.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from avicenna.bridge.protocol import (
    PROTOCOL_VERSION,
    encode,
    err_frame,
    event_frame,
    ok_frame,
)
from avicenna.bus import EventBus, drain


class BridgeError(RuntimeError):
    """A failure that is the user's problem, not a crash."""


class Bridge:
    def __init__(self, vault_path: str | None = None) -> None:
        self._vault_arg = vault_path
        self._out: io.TextIOBase = sys.stdout  # replaced in run()
        self._write_lock = asyncio.Lock()
        self._bus = EventBus()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._runs: dict[str, asyncio.Task[Any]] = {}
        self._stopping = asyncio.Event()

        # Lazily resolved so a missing vault or key is a reportable state
        # rather than a startup crash.
        self._ctx: Any = None
        self._vault: Any = None
        self._provider: Any = None
        self._chat: Any = None

    # -- plumbing -----------------------------------------------------------

    async def _send(self, frame: dict[str, Any]) -> None:
        line = encode(frame)
        async with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        """Discard a finished task, and never let its exception vanish.

        This callback used to only discard. A task that died of an unexpected
        exception was therefore silently forgotten — nothing called
        `task.exception()`, so nothing surfaced it, and a request could go
        permanently unanswered with no trace on either side of the pipe.
        """
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print(f"avicenna.bridge: background task failed: {exc!r}", file=sys.stderr)
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)

    async def _pump_events(self) -> None:
        """Forward every bus event to the frontend, forever.

        Wrapped, because this task dying is the worst failure mode the bridge
        has. The bus blocks its emitter when a non-LogMessage queue fills
        (maxsize 1000), so with the pump dead every `bus.emit` in the pipeline
        awaits forever and the run deadlocks mid-note with no error anywhere.
        A broken pipe here means the frontend is gone and we should stop; any
        other exception is reported and the pump keeps running.
        """
        queue = self._bus.subscribe()
        try:
            async for event in drain(queue):
                try:
                    await self._send(event_frame(event))
                except (BrokenPipeError, ConnectionResetError):
                    self._stopping.set()
                    return
                except Exception as exc:  # noqa: BLE001 - one bad event must not
                    # take the whole event stream down with it.
                    print(f"avicenna.bridge: dropped an event: {exc!r}", file=sys.stderr)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - boundary
            traceback.print_exc(file=sys.stderr)
            self._stopping.set()

    # -- lazy core state ----------------------------------------------------

    def _context(self) -> Any:
        from avicenna.vault.context import VaultContext

        if self._ctx is None:
            self._ctx = VaultContext.detect(explicit=self._vault_arg)
        return self._ctx

    def _load_vault(self) -> Any:
        from avicenna.vault.vault import Vault

        if self._vault is None:
            ctx = self._context()
            if not ctx.found:
                raise BridgeError(
                    "No vault found. Run `avicenna init <path>`, pass --vault, "
                    "or cd into a folder containing AGENTS.md and .agents/."
                )
            # Builtins come from Vault.load now, so every entry point — bridge,
            # headless CLI, tests — sees one tool surface.
            self._vault = Vault.load(ctx.root)
        return self._vault

    def _get_provider(self) -> Any:
        from avicenna.auth import build_provider

        if self._provider is None:
            self._provider = build_provider()
        if self._provider is None:
            raise BridgeError("No API key configured. Complete onboarding first.")
        return self._provider

    def _chat_controller(self) -> Any:
        from avicenna.chat import AgentChatController

        if self._chat is None:
            vault = self._load_vault()
            self._chat = AgentChatController(
                vault, self._get_provider(), self._bus, vault.tools
            )
        return self._chat

    # -- methods ------------------------------------------------------------

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"_m_{method.replace('.', '_')}", None)
        if handler is None:
            raise BridgeError(f"unknown method {method!r}")
        result = handler(params)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _m_hello(self, _: dict[str, Any]) -> dict[str, Any]:
        from avicenna.auth import auth_status

        return {
            "protocol": PROTOCOL_VERSION,
            "python": sys.version.split()[0],
            "cwd": str(Path.cwd()),
            "pid": os.getpid(),
            "auth": auth_status(),
        }

    def _m_vault_info(self, _: dict[str, Any]) -> dict[str, Any]:
        ctx = self._context()
        info: dict[str, Any] = {
            "found": ctx.found,
            "badge": ctx.badge,
            "summary": ctx.summary,
            "inside": ctx.inside,
            "source": ctx.source,
            "cwd": str(ctx.cwd),
            "root": str(ctx.root) if ctx.root else None,
            "name": ctx.root.name if ctx.root else None,
            "relative": str(ctx.relative) if ctx.relative else None,
        }
        if not ctx.found:
            return info
        vault = self._load_vault()
        domain, category = ctx.location_hint(vault)
        info.update(
            agentCount=len(vault.agents),
            skillCount=len(vault.skills),
            domains=sorted(vault.taxonomy.domains),
            hintDomain=domain,
            hintCategory=category,
        )
        return info

    def _m_vault_init(self, params: dict[str, Any]) -> dict[str, Any]:
        from avicenna.vault.init_scaffold import init_vault

        target = params.get("path") or str(Path.cwd() / "avicenna-vault")
        root = init_vault(Path(target))
        # A freshly scaffolded vault replaces whatever we resolved before.
        # The chat controller has to go too: it holds the *previous* Vault and
        # its ToolRegistry, so leaving it cached meant /agent resolved against
        # the old vault's agents and its tools wrote into the old vault.
        self._ctx = None
        self._vault = None
        self._chat = None
        return {"root": str(root)}

    def _m_agents_list(self, _: dict[str, Any]) -> list[dict[str, Any]]:
        vault = self._load_vault()
        return [
            {
                "name": a.name,
                "description": a.description,
                "type": a.type,
                "domain": a.domain,
                "stage": a.stage,
                "mcp": list(a.mcp),
            }
            for a in sorted(vault.agents.values(), key=lambda a: (a.type, a.name))
        ]

    def _m_tools_list(self, _: dict[str, Any]) -> list[dict[str, Any]]:
        vault = self._load_vault()
        return [
            {
                "name": t.name,
                "description": t.description,
                "source": t.source.value,
                "access": t.access.value,
            }
            for t in vault.tools
        ]

    def _m_mcp_list(self, _: dict[str, Any]) -> list[dict[str, Any]]:
        from avicenna.config import Config

        cfg = Config.load_mcp_config()
        return [
            {
                "name": s.name,
                "type": s.type,
                "enabled": s.enabled,
                "description": s.description or "",
            }
            for s in cfg.servers
        ]

    def _m_auth_status(self, _: dict[str, Any]) -> dict[str, Any]:
        from avicenna.auth import auth_status

        return auth_status()

    async def _m_auth_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        from avicenna.auth import DEFAULT_MODEL, DEFAULT_PROVIDER, validate_key

        key = (params.get("key") or "").strip()
        if not key:
            raise BridgeError("No key supplied.")
        result = await validate_key(DEFAULT_PROVIDER, key, DEFAULT_MODEL)
        return {"ok": result.ok, "detail": result.detail}

    def _m_auth_persist(self, params: dict[str, Any]) -> dict[str, Any]:
        from avicenna.auth import persist_key

        key = (params.get("key") or "").strip()
        if not key:
            raise BridgeError("No key supplied.")
        ctx = self._context()
        store = persist_key(key, vault_root=ctx.root if ctx.found else None)
        self._provider = None  # rebuild against the new key
        self._chat = None
        return {"store": store}

    def _m_auth_local_stub(self, _: dict[str, Any]) -> dict[str, Any]:
        from avicenna.auth import LOCAL_MODEL_STUB_MESSAGE

        return {"message": LOCAL_MODEL_STUB_MESSAGE}

    def _m_route_explain(self, params: dict[str, Any]) -> dict[str, Any]:
        from avicenna.vault.routing import route_request, score_domains

        topic = params.get("topic") or ""
        if not topic:
            raise BridgeError("No topic supplied.")
        vault = self._load_vault()
        chosen = route_request(vault, topic)
        return {
            "topic": topic,
            "routedTo": chosen.name if chosen else None,
            "ambiguous": chosen is None,
            "scores": [str(s) for s in score_domains(vault, topic)],
        }

    def _m_run_note(self, params: dict[str, Any]) -> dict[str, Any]:
        from avicenna.pipeline.run import execute_run

        topic = (params.get("topic") or "").strip()
        vault = self._load_vault()
        resume = bool(params.get("resume"))
        if not topic:
            # `/resume` sends no topic, and this used to reject it outright —
            # so the documented recovery path for a cancelled run errored every
            # single time. Recover the topic from the last run's manifest.
            if resume:
                from avicenna.pipeline.resume import find_resumable

                manifest = find_resumable(Path(vault.tmp_dir), "")
                if manifest is None or not manifest.topic:
                    raise BridgeError(
                        "Nothing to resume: no interrupted run found in this vault's _tmp."
                    )
                topic = manifest.topic
            else:
                raise BridgeError("No topic supplied.")
        provider = self._get_provider()
        ctx = self._context()

        run_id = str(uuid.uuid4())[:8]
        hint_domain, _hint_category = ctx.location_hint(vault)

        async def _run() -> None:
            try:
                await execute_run(
                    topic, provider, vault,
                    bus=self._bus,
                    run_id=run_id,
                    concurrency=int(params.get("concurrency") or 3),
                    dry_run=bool(params.get("dryRun")),
                    resume=resume,
                    fresh=not resume,
                    domain_override=params.get("domain") or hint_domain,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - boundary
                from avicenna.events import RunFailed

                await self._bus.emit(RunFailed(run_id=run_id, error=str(exc)))
            finally:
                self._runs.pop(run_id, None)

        self._runs[run_id] = self._spawn(_run())
        return {"runId": run_id, "topic": topic, "hintDomain": hint_domain}

    async def _m_run_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = params.get("runId")
        targets = [run_id] if run_id else list(self._runs)
        cancelled = []
        for rid in targets:
            task = self._runs.get(rid)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                cancelled.append(rid)
        return {"cancelled": cancelled}

    def _m_chat_select(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("agent") or ""
        controller = self._chat_controller()
        if name not in controller.vault.agents:
            raise BridgeError(
                f"unknown agent {name!r}; known: "
                f"{', '.join(sorted(controller.vault.agents))}"
            )
        agent = controller.select(name)
        return {"agent": agent.name, "type": agent.type, "domain": agent.domain}

    async def _m_chat_send(self, params: dict[str, Any]) -> dict[str, Any]:
        text = (params.get("text") or "").strip()
        if not text:
            raise BridgeError("Nothing to send.")
        controller = self._chat_controller()
        agent = params.get("agent")
        if agent:
            controller.select(agent)
        if controller.active is None:
            raise BridgeError("No agent selected. Use /agent <name> first.")
        run_id = str(uuid.uuid4())[:8]
        completion = await controller.send(text, run_id)
        chat = controller.chats[controller.active]
        return {
            "agent": controller.active,
            "text": completion.text or "",
            "turns": chat.turns,
            "promptTokens": chat.prompt_tokens,
            "completionTokens": chat.completion_tokens,
        }

    def _m_chat_clear(self, params: dict[str, Any]) -> dict[str, Any]:
        controller = self._chat_controller()
        controller.clear(params.get("agent"))
        return {"cleared": params.get("agent") or controller.active}

    def _m_shutdown(self, _: dict[str, Any]) -> dict[str, Any]:
        self._stopping.set()
        return {"bye": True}

    # -- request loop -------------------------------------------------------

    async def _handle_line(self, line: str) -> None:
        import json

        try:
            frame = json.loads(line)
        except json.JSONDecodeError as exc:
            await self._send(err_frame("", f"malformed frame: {exc}", "protocol"))
            return
        # `123` and `"hi"` are valid JSON. Reading .get off them raised
        # AttributeError outside the try below, which escaped the handler and
        # left the request with no response of any kind.
        if not isinstance(frame, dict):
            await self._send(err_frame(
                "", f"frame must be a JSON object, got {type(frame).__name__}", "protocol"))
            return
        req_id = str(frame.get("id", ""))
        method = str(frame.get("method", ""))
        raw_params = frame.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        try:
            result = await self._dispatch(method, params)
            await self._send(ok_frame(req_id, result))
        except BridgeError as exc:
            await self._send(err_frame(req_id, str(exc), "user"))
        except Exception as exc:  # noqa: BLE001 - boundary
            print(traceback.format_exc(), file=sys.stderr)
            await self._send(
                err_frame(req_id, f"{type(exc).__name__}: {exc}", "internal")
            )

    async def run(self) -> None:
        # stdout is the protocol; hand the core stderr so its prints are safe.
        real_stdout = sys.stdout
        with contextlib.suppress(Exception):
            real_stdout.reconfigure(encoding="utf-8", newline="\n")
        with contextlib.suppress(Exception):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        self._out = real_stdout
        sys.stdout = sys.stderr

        stdin = sys.stdin
        with contextlib.suppress(Exception):
            stdin.reconfigure(encoding="utf-8")

        pump = self._spawn(self._pump_events())
        await self._send({"type": "ready", "protocol": PROTOCOL_VERSION})

        stopping = asyncio.ensure_future(self._stopping.wait())
        try:
            while not self._stopping.is_set():
                reader = asyncio.ensure_future(asyncio.to_thread(stdin.readline))
                done, _ = await asyncio.wait(
                    {reader, stopping}, return_when=asyncio.FIRST_COMPLETED)
                if stopping in done:
                    # `shutdown` used to only set the flag, which was checked
                    # after the blocking readline returned — so the bridge kept
                    # waiting for a line that would never come, and exited only
                    # because the frontend closed stdin behind it.
                    reader.cancel()
                    break
                line = reader.result()
                if not line:  # frontend closed the pipe
                    break
                line = line.strip()
                if not line:
                    continue
                self._spawn(self._handle_line(line))
        finally:
            stopping.cancel()
            for task in list(self._runs.values()):
                task.cancel()
            # Bounded: bus.close() puts a sentinel on every subscriber queue and
            # would block forever against a full queue if the pump had died.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._bus.close(), timeout=5.0)
            pump.cancel()
            for task in list(self._tasks):
                task.cancel()
            sys.stdout = real_stdout


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    vault: str | None = None
    if "--vault" in args:
        i = args.index("--vault")
        if i + 1 < len(args):
            vault = args[i + 1]
    try:
        asyncio.run(Bridge(vault).run())
    except KeyboardInterrupt:
        return 130
    return 0


__all__ = ["Bridge", "BridgeError", "main"]
