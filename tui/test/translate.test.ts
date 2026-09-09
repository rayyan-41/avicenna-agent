/**
 * The event translator, tested without a terminal.
 *
 * That this is possible at all is the point of keeping `translate.ts` pure:
 * the whole event vocabulary can be exercised here, and the render layer only
 * has to be trusted with how things look, not with what they mean.
 *
 * Field names are snake_case on purpose — see the note at the top of
 * translate.ts. A test written with camelCase would pass against a translator
 * that silently reads undefined, which is the bug these assertions exist for.
 */

import { describe, expect, test } from 'bun:test';
import { applyEvent, emptyRun } from '../src/bridge/translate.ts';
import type { EventFrame, EventName } from '../src/bridge/protocol.ts';

function frame(event: EventName, data: Record<string, unknown> = {}): EventFrame {
  return { type: 'event', event, runId: 'r1', seq: 0, ts: 0, data };
}

describe('the outline', () => {
  test('pre-flight declares every heading as pending', () => {
    const { run } = applyEvent(
      emptyRun('r1'),
      frame('PreflightDeclared', {
        topic: 'the epistemic gap',
        domain: 'Philosophy',
        headings: ['One', 'Two', 'Three'],
        target_words: 4500,
      }),
    );
    expect(run.sections.map((s) => s.state)).toEqual([
      'pending',
      'pending',
      'pending',
    ]);
    expect(run.targetWords).toBe(4500);
    expect(run.domain).toBe('Philosophy');
  });

  test('target_words is read as snake_case, not camelCase', () => {
    // The wire carries Python's field names. Reading `targetWords` would give
    // undefined and render as 0 without failing anything, so assert the zero.
    const { run } = applyEvent(
      emptyRun('r1'),
      frame('PreflightDeclared', { targetWords: 4500 }),
    );
    expect(run.targetWords).toBe(0);
  });

  test('a section completing does not disturb its neighbours', () => {
    let run = applyEvent(
      emptyRun('r1'),
      frame('PreflightDeclared', { headings: ['One', 'Two'] }),
    ).run;
    run = applyEvent(run, frame('SectionStarted', { index: 1, heading: 'Two' })).run;
    run = applyEvent(
      run,
      frame('SectionCompleted', { index: 1, heading: 'Two', words: 1612 }),
    ).run;
    expect(run.sections[0]!.state).toBe('pending');
    expect(run.sections[1]!.state).toBe('done');
    expect(run.sections[1]!.words).toBe(1612);
  });

  test('a section completing without a declared outline is appended, not dropped', () => {
    // Resuming from a manifest replays completions for sections pre-flight
    // never re-declared in this process.
    const { run } = applyEvent(
      emptyRun('r1'),
      frame('SectionCompleted', { index: 4, heading: 'Late', words: 900 }),
    );
    expect(run.sections).toHaveLength(1);
    expect(run.sections[0]!.heading).toBe('Late');
  });
});

describe('failure', () => {
  test('a retryable section failure keeps it writing and warns', () => {
    const { run, notice } = applyEvent(
      emptyRun('r1'),
      frame('SectionFailed', {
        index: 0,
        heading: 'One',
        will_retry: true,
        attempt: 2,
      }),
    );
    expect(run.sections[0]!.state).toBe('writing');
    expect(notice?.tone).toBe('warn');
  });

  test('a terminal section failure marks it failed and errors', () => {
    const { run, notice } = applyEvent(
      emptyRun('r1'),
      frame('SectionFailed', { index: 0, heading: 'One', error: 'timeout' }),
    );
    expect(run.sections[0]!.state).toBe('failed');
    expect(notice?.tone).toBe('error');
  });

  test('RunFailed records the error and ends the run', () => {
    const { run } = applyEvent(emptyRun('r1'), frame('RunFailed', { error: 'no key' }));
    expect(run.outcome).toBe('failed');
    expect(run.error).toBe('no key');
  });
});

describe('the gloss', () => {
  test('decisions collect in the margin, the sequence does not', () => {
    let run = emptyRun('r1');
    run = applyEvent(run, frame('PreflightDeclared', { domain: 'Philosophy' })).run;
    run = applyEvent(run, frame('ThemeMinted', { theme: 'epistemology' })).run;
    run = applyEvent(run, frame('NotesLinked', { inline: 4, related: 9 })).run;
    run = applyEvent(run, frame('StageEntered', { stage: 'tagging' })).run;
    expect(run.gloss.map((g) => g.label)).toEqual(['routed', 'minted', 'links']);
    expect(run.gloss[2]!.value).toBe('4 inline, 9 related');
  });

  test('an empty decision is not glossed', () => {
    const { run } = applyEvent(emptyRun('r1'), frame('ThemeMinted', { theme: '' }));
    expect(run.gloss).toHaveLength(0);
  });
});

describe('noise', () => {
  test('tool traffic and debug logs stay out of the transcript', () => {
    for (const f of [
      frame('ToolInvoked', { name: 'validate_tags' }),
      frame('ToolReturned', { name: 'validate_tags' }),
      frame('LogMessage', { level: 'debug', text: 'x' }),
      frame('LogMessage', { level: 'info', text: 'x' }),
    ]) {
      expect(applyEvent(emptyRun('r1'), f).notice).toBeUndefined();
    }
  });

  test('a warning log surfaces', () => {
    const { notice } = applyEvent(
      emptyRun('r1'),
      frame('LogMessage', { level: 'warning', text: 'vault tool missing' }),
    );
    expect(notice).toEqual({ tone: 'warn', text: 'vault tool missing' });
  });
});

describe('completion', () => {
  test('RunComplete reads total_words and clears the active stage', () => {
    let run = applyEvent(emptyRun('r1'), frame('StageEntered', { stage: 'write' })).run;
    run = applyEvent(
      run,
      frame('RunComplete', { summary: 'done', total_words: 13500 }),
    ).run;
    expect(run.outcome).toBe('complete');
    expect(run.totalWords).toBe(13500);
    expect(run.stage).toBeNull();
  });
});
