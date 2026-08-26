/**
 * The wire contract with `python -m avicenna.bridge`.
 *
 * These declarations mirror avicenna/events.py and avicenna/bridge/server.py.
 * They are the frontend's only model of the backend, so anything the TUI
 * displays has to appear here first.
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
  | 'TagsProposed'
  | 'TagsValidated'
  | 'LinkCandidatesFound'
  | 'MocUpdated'
  | 'NoteWritten'
  | 'RunFailed'
  | 'RunComplete'
  | 'LogMessage';

export const STAGES = [
  'preflight',
  'manifest',
  'sections',
  'assembly',
  'wordcount',
  'toc',
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
