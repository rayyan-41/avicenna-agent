/**
 * Client for the Python backend.
 *
 * Owns the child process, the newline framing and the request/response
 * correlation, and exposes a promise-per-call API plus an event stream. The
 * rest of the TUI never sees a pipe.
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { delimiter } from 'node:path';
import { PROTOCOL_VERSION } from './protocol.js';
import type {
  AgentInfo,
  ChatResult,
  EventFrame,
  Frame,
  HelloResult,
  McpServerInfo,
  RouteResult,
  RunHandle,
  ToolInfo,
  ValidateResult,
  VaultInfo,
} from './protocol.js';

export class BridgeError extends Error {
  constructor(
    message: string,
    readonly kind: string = 'error',
  ) {
    super(message);
    this.name = 'BridgeError';
  }
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer?: ReturnType<typeof setTimeout> | undefined;
}

/** Cap on unterminated frame data held in memory. */
const MAX_BUFFER = 8 * 1024 * 1024;

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Per-method response budgets.
 *
 * A note run and a chat turn are answered immediately with an id — progress
 * arrives as events — so their budget covers dispatch, not generation. The
 * only method given no budget is `shutdown`, which races a timer in `stop()`.
 */
const TIMEOUTS: Record<string, number> = {
  hello: 20_000,
  'vault.info': 15_000,
  'vault.init': 30_000,
  'auth.validate': 60_000,
  'auth.persist': 30_000,
  'route.explain': 60_000,
  'run.note': 30_000,
  'run.cancel': 15_000,
  'chat.send': 300_000,
  shutdown: 0,
};

export interface BridgeOptions {
  python: string;
  cwd: string;
  vault?: string | undefined;
  /**
   * Repository root, prepended to PYTHONPATH.
   *
   * The backend is spawned with the user's vault as its cwd, so `avicenna` is
   * not importable from the current directory the way it is in a repo shell.
   * Relying on the editable install alone is fragile — it breaks whenever the
   * checkout is moved, which leaves a working tree that fails only when
   * launched from elsewhere. Putting the root on the path makes the frontend
   * work from any directory and survive a stale install.
   */
  projectRoot?: string | undefined;
  /** Extra args placed before `-m avicenna.bridge`, e.g. `-X utf8`. */
  pythonArgs?: string[];
}

export class Bridge extends EventEmitter {
  private child?: ChildProcessWithoutNullStreams;
  private buffer = '';
  private nextId = 1;
  private readonly pending = new Map<string, Pending>();
  private readyPromise?: Promise<void>;
  private stderrTail: string[] = [];
  private closed = false;

  constructor(private readonly opts: BridgeOptions) {
    super();
  }

  /** Spawn the backend and resolve once it announces itself. */
  start(): Promise<void> {
    if (this.readyPromise) return this.readyPromise;

    const args = [...(this.opts.pythonArgs ?? []), '-m', 'avicenna.bridge'];
    if (this.opts.vault) args.push('--vault', this.opts.vault);

    const child = spawn(this.opts.python, args, {
      cwd: this.opts.cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUNBUFFERED: '1',
        ...(this.opts.projectRoot
          ? {
              PYTHONPATH: [this.opts.projectRoot, process.env.PYTHONPATH]
                .filter(Boolean)
                .join(delimiter),
            }
          : {}),
      },
    });
    this.child = child;

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => this.consume(chunk));

    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk: string) => {
      // The backend's diagnostics are kept but never rendered inline; they
      // surface through /diagnostics so a traceback is recoverable without
      // shredding the frame.
      for (const line of chunk.split('\n')) {
        if (line.trim()) this.stderrTail.push(line.trimEnd());
      }
      if (this.stderrTail.length > 200) {
        this.stderrTail = this.stderrTail.slice(-200);
      }
      this.emit('stderr', chunk);
    });

    this.readyPromise = new Promise<void>((resolve, reject) => {
      const onReady = () => {
        cleanup();
        resolve();
      };
      const onExit = (code: number | null) => {
        cleanup();
        reject(
          new BridgeError(
            `The Avicenna backend exited before it was ready (code ${code ?? '?'}).\n` +
              this.diagnostics().join('\n'),
            'startup',
          ),
        );
      };
      const onError = (err: Error) => {
        cleanup();
        reject(
          new BridgeError(
            `Could not start "${this.opts.python}": ${err.message}`,
            'spawn',
          ),
        );
      };
      const cleanup = () => {
        this.off('ready', onReady);
        child.off('exit', onExit);
        child.off('error', onError);
      };
      this.once('ready', onReady);
      child.once('exit', onExit);
      child.once('error', onError);
    });

    child.on('exit', (code, signal) => {
      this.closed = true;
      const err = new BridgeError(
        `Backend exited (code ${code ?? '?'}${signal ? `, signal ${signal}` : ''}).`,
        'exit',
      );
      this.rejectAll(err);
      this.emit('exit', code, signal);
    });

    // A persistent listener, deliberately outside readyPromise. That one is
    // removed by cleanup() the instant `ready` fires, which left the child with
    // no 'error' listener at all — so any later emission (EPIPE on stdin,
    // EACCES) became an unhandled 'error' event, which Node throws, killing the
    // app with a raw stack trace instead of a readable message.
    child.on('error', (err: Error) => {
      this.stderrTail.push(`child process error: ${err.message}`);
      if (!this.closed) {
        this.closed = true;
        this.rejectAll(new BridgeError(`Backend failed: ${err.message}`, 'io'));
        this.emit('exit', null, null);
      }
    });

    return this.readyPromise;
  }

  private rejectAll(err: BridgeError): void {
    for (const [, pending] of this.pending) {
      if (pending.timer) clearTimeout(pending.timer);
      pending.reject(err);
    }
    this.pending.clear();
  }

  /** Record a protocol problem where the user can actually find it. */
  private diagnose(message: string): void {
    this.stderrTail.push(message);
    if (this.stderrTail.length > 200) this.stderrTail = this.stderrTail.slice(-200);
    this.emit('stderr', message + '\n');
  }

  private consume(chunk: string): void {
    this.buffer += chunk;
    // A frame that never terminates must not grow the heap without bound.
    if (this.buffer.length > MAX_BUFFER) {
      this.diagnose(
        `protocol: dropped ${this.buffer.length} bytes of unterminated frame data`,
      );
      this.buffer = '';
      return;
    }
    let index: number;
    while ((index = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        // Went to a channel with no subscribers, so a desync left no trace on
        // either side — the one failure the stdout invariant exists to prevent.
        this.diagnose(`protocol: unparsable frame: ${line.slice(0, 400)}`);
        continue;
      }
      if (typeof parsed !== 'object' || parsed === null) {
        this.diagnose(`protocol: frame was not an object: ${line.slice(0, 200)}`);
        continue;
      }
      this.routeFrame(parsed as Frame);
    }
  }

  private routeFrame(frame: Frame): void {
    if (frame.type === 'ready') {
      // The version constant existed on both sides and was compared by
      // neither, so a protocol bump would have been silently ignored — which
      // is precisely the scenario it exists to catch.
      const theirs = (frame as { protocol?: number }).protocol;
      if (typeof theirs === 'number' && theirs !== PROTOCOL_VERSION) {
        this.diagnose(
          `protocol: backend speaks v${theirs}, this interface speaks v${PROTOCOL_VERSION}`,
        );
        this.closed = true;
        this.rejectAll(
          new BridgeError(
            `Protocol mismatch: the backend speaks v${theirs} but this interface ` +
              `speaks v${PROTOCOL_VERSION}. Rebuild the frontend (cd tui && npm run build).`,
            'startup',
          ),
        );
        return;
      }
      this.emit('ready', frame);
      return;
    }
    if (frame.type === 'event') {
      this.emit('event', frame as EventFrame);
      return;
    }
    if (frame.type === 'res') {
      const pending = this.pending.get(frame.id);
      if (!pending) {
        this.diagnose(`protocol: response for unknown request id ${JSON.stringify(frame.id)}`);
        return;
      }
      this.pending.delete(frame.id);
      if (pending.timer) clearTimeout(pending.timer);
      if (frame.ok) pending.resolve(frame.result);
      else {
        pending.reject(
          new BridgeError(frame.error?.message ?? 'unknown error', frame.error?.kind),
        );
      }
      return;
    }
    this.diagnose(`protocol: unknown frame type ${JSON.stringify((frame as Frame).type)}`);
  }

  /** Issue a request and wait for its response. */
  request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (this.closed || !this.child) {
      return Promise.reject(new BridgeError('Backend is not running.', 'exit'));
    }
    const id = String(this.nextId++);
    const payload = JSON.stringify({ type: 'req', id, method, params });
    const budget = TIMEOUTS[method] ?? DEFAULT_TIMEOUT_MS;
    return new Promise<T>((resolve, reject) => {
      // Without a timeout the only rejection paths were process exit and a
      // write error, so a backend that stalled — a dead event pump, a keyring
      // prompt on a locked store — left the interface busy forever, with Esc
      // issuing a cancel request that would hang in exactly the same way.
      const timer =
        budget > 0
          ? setTimeout(() => {
              this.pending.delete(id);
              this.diagnose(`protocol: ${method} timed out after ${budget}ms`);
              reject(new BridgeError(`${method} timed out after ${budget}ms.`, 'timeout'));
            }, budget)
          : undefined;
      if (timer && typeof timer.unref === 'function') timer.unref();
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer });
      this.child?.stdin.write(payload + '\n', (err) => {
        if (err) {
          const entry = this.pending.get(id);
          if (entry?.timer) clearTimeout(entry.timer);
          this.pending.delete(id);
          reject(new BridgeError(`write failed: ${err.message}`, 'io'));
        }
      });
    });
  }

  /** Recent backend stderr, for the diagnostics view. */
  diagnostics(): string[] {
    return [...this.stderrTail];
  }

  async stop(): Promise<void> {
    if (!this.child || this.closed) return;
    try {
      await Promise.race([
        this.request('shutdown'),
        new Promise((r) => setTimeout(r, 400)),
      ]);
    } catch {
      // Shutting down is best-effort; the kill below is the guarantee.
    }
    this.child.stdin.end();
    this.child.kill();
  }

  /* -- typed calls -------------------------------------------------------- */

  hello = () => this.request<HelloResult>('hello');
  vaultInfo = () => this.request<VaultInfo>('vault.info');
  vaultInit = (path?: string) => this.request<{ root: string }>('vault.init', { path });
  agents = () => this.request<AgentInfo[]>('agents.list');
  tools = () => this.request<ToolInfo[]>('tools.list');
  mcp = () => this.request<McpServerInfo[]>('mcp.list');
  authStatus = () => this.request<import('./protocol.js').AuthStatus>('auth.status');
  authValidate = (key: string) => this.request<ValidateResult>('auth.validate', { key });
  authPersist = (key: string) => this.request<{ store: string }>('auth.persist', { key });
  localStub = () => this.request<{ message: string }>('auth.local_stub');
  route = (topic: string) => this.request<RouteResult>('route.explain', { topic });
  runNote = (params: Record<string, unknown>) => this.request<RunHandle>('run.note', params);
  runCancel = (runId?: string) => this.request<{ cancelled: string[] }>('run.cancel', { runId });
  chatSelect = (agent: string) => this.request<{ agent: string }>('chat.select', { agent });
  chatSend = (text: string, agent?: string) =>
    this.request<ChatResult>('chat.send', { text, agent });
  chatClear = (agent?: string) => this.request<{ cleared: string }>('chat.clear', { agent });
}
