/**
 * The wire contract with `python -m avicenna.bridge`.
 *
 * These declarations mirror avicenna/events.py and avicenna/bridge/server.py.
 * They are the frontend's only model of the backend, so anything the interface
 * displays has to appear here first.
 *
 * `scripts/check_protocol_parity.py` reads the `EventName` union below and
 * compares it against the Event subclasses in events.py, then checks that
 * `translate.ts` carries a `case` for each. Adding an event on the Python side
 * and forgetting it here would otherwise cross the wire, match nothing, and be
 * dropped in silence.
 */

export const PROTOCOL_VERSION = 1;

/* -- frames --------------------------------------------------------------- */

export interface ReadyFrame {
  type: 'ready';
  protocol: number;
}

export interface ResponseFrame {
  type: 'res';
  id: string;
  ok: boolean;
  result?: unknown;
  error?: { kind: string; message: string };
}

export interface EventFrame {
  type: 'event';
  event: EventName;
  runId: string;
  seq: number;
  ts: number;
  data: Record<string, unknown>;
}

export type Frame = ReadyFrame | ResponseFrame | EventFrame;

/* -- events --------------------------------------------------------------- */

export type EventName =
  | 'RunStarted'
  | 'PreflightDeclared'
  | 'ManifestWritten'
  | 'SectionStarted'
  | 'SectionCompleted'
  | 'SectionFailed'
  | 'StageEntered'
  | 'StageCompleted'
  | 'ToolInvoked'
  | 'ToolReturned'
  | 'WordCountChecked'
  | 'MarkdownNormalised'
  | 'TagsProposed'
  | 'TagsValidated'
  | 'SchemaDetected'
  | 'ThemeMinted'
  | 'TransitionsApplied'
  | 'SemanticGuardDecision'
  | 'EntitiesDerived'
  | 'TagsAssignedMechanically'
  | 'NotesLinked'
  | 'MocUpdated'
  | 'NoteWritten'
  | 'PlanApprovalRequested'
  | 'RunFailed'
  | 'RunComplete'
  | 'LogMessage';

export const STAGES = [
  'preflight',
  'manifest',
  'sections',
  'assembly',
  'transitions',
  'wordcount',
  'tagging',
  'linking',
  'moc',
  'write',
] as const;

export type Stage = (typeof STAGES)[number];

/* -- method results ------------------------------------------------------- */

export interface AuthStatus {
  configured: boolean;
  onboarded: boolean;
  provider: string;
  model: string;
  keyStore: string | null;
}

export interface HelloResult {
  protocol: number;
  python: string;
  cwd: string;
  pid: number;
  auth: AuthStatus;
}

export interface VaultInfo {
  found: boolean;
  badge: string;
  summary: string;
  inside: boolean;
  source: string;
  cwd: string;
  root: string | null;
  name: string | null;
  relative: string | null;
  agentCount?: number;
  skillCount?: number;
  domains?: string[];
  hintDomain?: string | null;
  hintCategory?: string | null;
}

export interface AgentInfo {
  name: string;
  description: string;
  type: 'content' | 'pipeline' | 'audit';
  domain: string | null;
  stage: number | null;
  mcp: string[];
}

export interface ToolInfo {
  name: string;
  description: string;
  source: string;
  access: string;
}

export interface McpServerInfo {
  name: string;
  type: string;
  enabled: boolean;
  description: string;
}

export interface RouteResult {
  topic: string;
  routedTo: string | null;
  ambiguous: boolean;
  scores: string[];
}

export interface RunHandle {
  runId: string;
  topic: string;
  hintDomain: string | null;
}

export interface ChatResult {
  agent: string;
  text: string;
  turns: number;
  promptTokens: number;
  completionTokens: number;
}

export interface ValidateResult {
  ok: boolean;
  detail: string;
}

/* -- the client contract -------------------------------------------------- */

/**
 * What the rest of the interface is allowed to know about the bridge.
 *
 * Stated as an interface rather than a class so the render layer can be built
 * and tested against a fake. The rule the old frontend held and this one keeps:
 * nothing above this line imports a child process, and nothing below it knows
 * what a transcript is.
 */
export interface BridgeClient {
  /** Resolves once the backend has sent its `ready` frame. */
  ready(): Promise<HelloResult>;

  /** One request/response round trip. Rejects on a non-ok response. */
  request<T>(method: string, params?: Record<string, unknown>): Promise<T>;

  /** Every event frame, in arrival order. */
  onEvent(listener: (frame: EventFrame) => void): void;

  /**
   * Fired when the connection is unusable: the child exited, or a line
   * arrived that was not JSON. Both are fatal — see `client.ts` for why a
   * desync must not be skipped.
   */
  onFatal(listener: (reason: string) => void): void;

  /** Backend stderr, which is diagnostics rather than protocol. */
  onDiagnostic(listener: (line: string) => void): void;

  dispose(): void;
}
