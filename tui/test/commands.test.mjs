/**
 * Slash-command parsing and completion.
 *
 * This is the behaviour the old Python CommandDispatcher tests covered before
 * the frontend moved languages, plus the palette matching that replaced its
 * "unknown command falls through" rule.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { COMMANDS, complete, find, isCommand, parse } from '../dist/commands.js';

test('detects commands', () => {
  assert.ok(isCommand('/agent'));
  assert.ok(isCommand('/help'));
  assert.ok(isCommand('/note'));
  assert.ok(!isCommand('hello'));
  assert.ok(!isCommand('slashed/but_not_command'));
});

test('parses a command into name, args and argv', () => {
  assert.deepEqual(parse('/test arg1 arg2'), {
    name: 'test',
    args: 'arg1 arg2',
    argv: ['arg1', 'arg2'],
  });
  assert.deepEqual(parse('/help'), { name: 'help', args: '', argv: [] });
});

test('keeps multi-word arguments intact', () => {
  // A topic is one argument with spaces in it, not a list of words.
  const parsed = parse('/note The life and work of Ibn Sina');
  assert.equal(parsed.name, 'note');
  assert.equal(parsed.args, 'The life and work of Ibn Sina');
});

test('lowercases the command name but not its arguments', () => {
  const parsed = parse('/NOTE Ibn Sina');
  assert.equal(parsed.name, 'note');
  assert.equal(parsed.args, 'Ibn Sina');
});

test('unknown commands are not found', () => {
  assert.equal(find('unknown'), undefined);
  assert.ok(find('help'));
});

test('completion prefers prefix matches over substring matches', () => {
  const matches = complete('/ag');
  assert.equal(matches[0].name, 'agent');
  assert.equal(matches[1].name, 'agents');
});

test('completion of a bare slash lists every visible command', () => {
  const matches = complete('/');
  assert.equal(matches.length, COMMANDS.filter((cmd) => !cmd.hidden).length);
  assert.ok(!matches.some((cmd) => cmd.hidden));
});

test('every command has a summary so the palette is never blank', () => {
  for (const cmd of COMMANDS) {
    assert.ok(cmd.summary && cmd.summary.length > 5, `${cmd.name} needs a summary`);
  }
});
