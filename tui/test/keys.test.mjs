/**
 * Key decoding.
 *
 * In raw mode a keystroke is a byte sequence, and getting this wrong is what
 * makes a TUI "barely function": arrows insert garbage, pastes submit halfway
 * through, Ctrl+C does nothing.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { decode } from '../dist/keys.js';
import { ESC } from '../dist/ansi.js';

const names = (chunk) => decode(chunk).map((k) => k.name);

test('printable characters carry their text', () => {
  const [key] = decode('a');
  assert.equal(key.name, 'a');
  assert.equal(key.text, 'a');
  assert.equal(key.ctrl, false);
});

test('arrow keys decode from CSI sequences', () => {
  assert.deepEqual(names(`${ESC}[A${ESC}[B${ESC}[C${ESC}[D`), [
    'up',
    'down',
    'right',
    'left',
  ]);
});

test('home, end, delete and paging decode', () => {
  assert.deepEqual(names(`${ESC}[3~${ESC}[5~${ESC}[6~`), ['delete', 'pageup', 'pagedown']);
  assert.deepEqual(names(`${ESC}[H${ESC}[F`), ['home', 'end']);
});

test('modifier parameters become part of the name', () => {
  assert.deepEqual(names(`${ESC}[1;5C`), ['ctrl+right']);
  assert.deepEqual(names(`${ESC}[1;2A`), ['shift+up']);
});

test('shift+tab decodes', () => {
  assert.deepEqual(names(`${ESC}[Z`), ['shift+tab']);
});

test('control characters map back to their letter', () => {
  assert.deepEqual(names('\u0003'), ['ctrl+c']);
  assert.deepEqual(names('\u000C'), ['ctrl+l']);
});

test('enter, tab and backspace are named', () => {
  assert.deepEqual(names('\r'), ['enter']);
  assert.deepEqual(names('\t'), ['tab']);
  assert.deepEqual(names('\u007F'), ['backspace']);
});

test('a bare escape is escape, not an unfinished sequence', () => {
  assert.deepEqual(names(ESC), ['escape']);
});

test('bracketed paste arrives whole and is never parsed as keys', () => {
  const body = 'line one\nline two';
  const keys = decode(`${ESC}[200~${body}${ESC}[201~`);
  assert.equal(keys.length, 1);
  assert.equal(keys[0].name, 'paste');
  assert.equal(keys[0].text, body);
  assert.equal(keys[0].paste, true);
});

test('a burst of characters decodes in order', () => {
  assert.deepEqual(names('abc'), ['a', 'b', 'c']);
});

test('astral characters survive as one key', () => {
  const keys = decode('😀');
  assert.equal(keys.length, 1);
  assert.equal(keys[0].text, '😀');
});
