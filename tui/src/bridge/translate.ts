/**
 * Pipeline events into something the interface can draw.
 *
 * Pure: no rendering, no I/O, no React. That is what lets the whole event
 * vocabulary be tested without a terminal, and it is why the switch below is
 * the one place a new event has to be handled.
 *
 * `scripts/check_protocol_parity.py` reads the `case` labels here and fails the
 * build if any event in avicenna/events.py is missing one. The `never` check at
 * the end of `applyEvent` makes the compiler point at the same gap.
 *
 * FIELD NAMES ARE snake_case. The bridge serialises with `dataclasses.asdict`
 * (avicenna/bridge/protocol.py:49), which keeps Python's own field names on the
 * wire. So it is `target_words`, `will_retry`, `total_words` — not the camelCase
 * a TypeScript reader expects. Getting this wrong fails silently: the field
 * reads as undefined and renders as a zero.
 */

import type { EventFrame, EventName, Stage } from './protocol.ts';

/* -- the shapes the interface draws --------------------------------------- */

export type SectionState = 'pending' | 'writing' | 'done' | 'failed';

export interface SectionView {
  index: number;
  heading: string;
  state: SectionState;
  words: number;
}

/** A line in the margin: a decision the run made, as opposed to its sequence. */
export interface GlossLine {
  label: string;
  value: string;
}

export type RunOutcome = 'running' | 'complete' | 'failed';

export interface RunView {
  runId: string;
  topic: string;
  domain: string;
  template: string;
  targetWords: number;
  sections: SectionView[];
  stage: Stage | null;
  stagesDone: Stage[];
  outcome: RunOutcome;
  summary: string;
  totalWords: number;
  notePath: string;
  error: string;
  gloss: GlossLine[];
}

export interface Notice {
  tone: 'info' | 'warn' | 'error';
  text: string;
}

export interface Applied {
  run: RunView;
  notice?: Notice;
}

export function emptyRun(runId: string, topic = ''): RunView {
  return {
    runId,
    topic,
    domain: '',
    template: '',
    targetWords: 0,
    sections: [],
    stage: null,
    stagesDone: [],
    outcome: 'running',
    summary: '',
    totalWords: 0,
    notePath: '',
    error: '',
    gloss: [],
  };
}

/* -- reading the untyped payload ------------------------------------------ */

const str = (d: Record<string, unknown>, k: string): string =>
  typeof d[k] === 'string' ? (d[k] as string) : '';

const num = (d: Record<string, unknown>, k: string): number =>
  typeof d[k] === 'number' ? (d[k] as number) : 0;

const bool = (d: Record<string, unknown>, k: string): boolean => d[k] === true;

const list = (d: Record<string, unknown>, k: string): string[] =>
  Array.isArray(d[k]) ? (d[k] as unknown[]).map((v) => String(v)) : [];

const gloss = (run: RunView, label: string, value: string): RunView =>
  value ? { ...run, gloss: [...run.gloss, { label, value }] } : run;

function setSection(
  run: RunView,
  index: number,
  patch: Partial<SectionView>,
): RunView {
  const sections = run.sections.map((s) =>
    s.index === index ? { ...s, ...patch } : s,
  );
  // A section can complete without ever having been declared, if pre-flight
  // was resumed from a manifest rather than re-run. Append rather than drop it.
  if (!sections.some((s) => s.index === index)) {
    sections.push({
      index,
      heading: patch.heading ?? '',
      state: patch.state ?? 'pending',
      words: patch.words ?? 0,
    });
    sections.sort((a, b) => a.index - b.index);
  }
  return { ...run, sections };
}

/* -- the switch ----------------------------------------------------------- */

export function applyEvent(run: RunView, frame: EventFrame): Applied {
  const d = frame.data;
  const name: EventName = frame.event;

  switch (name) {
    case 'RunStarted':
      return {
        run: gloss(
          { ...run, topic: str(d, 'topic') || run.topic },
          'model',
          [str(d, 'provider'), str(d, 'model')].filter(Boolean).join(' '),
        ),
      };

    case 'PreflightDeclared': {
      const headings = list(d, 'headings');
      return {
        run: gloss(
          {
            ...run,
            topic: str(d, 'topic') || run.topic,
            domain: str(d, 'domain'),
            template: str(d, 'template'),
            targetWords: num(d, 'target_words'),
            sections: headings.map((heading, index) => ({
              index,
              heading,
              state: 'pending' as const,
              words: 0,
            })),
          },
          'routed',
          str(d, 'domain'),
        ),
      };
    }

    case 'ManifestWritten':
      return { run };

    case 'SectionStarted':
      return {
        run: setSection(run, num(d, 'index'), {
          heading: str(d, 'heading'),
          state: 'writing',
        }),
      };

    case 'SectionCompleted':
      return {
        run: setSection(run, num(d, 'index'), {
          heading: str(d, 'heading'),
          state: 'done',
          words: num(d, 'words'),
        }),
      };

    case 'SectionFailed': {
      const retrying = bool(d, 'will_retry');
      return {
        run: setSection(run, num(d, 'index'), {
          heading: str(d, 'heading'),
          state: retrying ? 'writing' : 'failed',
        }),
        notice: {
          tone: retrying ? 'warn' : 'error',
          text: retrying
            ? `retrying "${str(d, 'heading')}" (attempt ${num(d, 'attempt')})`
            : `failed "${str(d, 'heading')}": ${str(d, 'error')}`,
        },
      };
    }

    case 'StageEntered':
      return { run: { ...run, stage: str(d, 'stage') as Stage } };

    case 'StageCompleted': {
      const stage = str(d, 'stage') as Stage;
      return {
        run: {
          ...run,
          stagesDone: run.stagesDone.includes(stage)
            ? run.stagesDone
            : [...run.stagesDone, stage],
        },
      };
    }

    // Tool traffic is diagnostics, not the sequence. It is on the wire so a
    // failing vault script can be found; it does not belong in the transcript.
    case 'ToolInvoked':
    case 'ToolReturned':
      return { run };

    case 'WordCountChecked':
      return { run: gloss(run, 'words', String(num(d, 'total'))) };

    case 'MarkdownNormalised':
      return { run };

    case 'TagsProposed':
      return { run };

    case 'TagsValidated':
      return { run: gloss(run, 'tags', list(d, 'tags').join(', ')) };

    case 'SchemaDetected':
      return { run };

    case 'ThemeMinted':
      return { run: gloss(run, 'minted', str(d, 'theme')) };

    case 'TransitionsApplied':
      return { run };

    case 'SemanticGuardDecision':
      return { run: gloss(run, 'guard', str(d, 'decision')) };

    case 'EntitiesDerived':
      return { run: gloss(run, 'entities', list(d, 'entities').join(', ')) };

    case 'TagsAssignedMechanically':
      return { run };

    case 'NotesLinked': {
      const inline = num(d, 'inline');
      const related = num(d, 'related');
      return {
        run: gloss(run, 'links', `${inline} inline, ${related} related`),
      };
    }

    case 'MocUpdated':
      return { run: gloss(run, 'map', str(d, 'path')) };

    case 'NoteWritten':
      return { run: { ...run, notePath: str(d, 'path') } };

    // Rendered by the plan-review screen in stage 3. Until then the bridge
    // auto-approves, so there is nothing for the interface to decide.
    case 'PlanApprovalRequested':
      return { run };

    case 'RunFailed':
      return {
        run: { ...run, outcome: 'failed', error: str(d, 'error') },
        notice: { tone: 'error', text: str(d, 'error') },
      };

    case 'RunComplete':
      return {
        run: {
          ...run,
          outcome: 'complete',
          stage: null,
          summary: str(d, 'summary'),
          totalWords: num(d, 'total_words'),
        },
      };

    case 'LogMessage': {
      const level = str(d, 'level');
      if (level === 'debug' || level === 'info') return { run };
      return {
        run,
        notice: {
          tone: level === 'error' ? 'error' : 'warn',
          text: str(d, 'text'),
        },
      };
    }

    default: {
      // Compile error here means an event exists in protocol.ts with no case.
      const unhandled: never = name;
      return { run, notice: { tone: 'warn', text: `unhandled ${String(unhandled)}` } };
    }
  }
}
