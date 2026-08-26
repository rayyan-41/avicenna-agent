/**
 * Width measurement, wrapping and truncation.
 *
 * These are the functions every box border depends on, so a regression here
 * shows up as a frame that tears rather than as a wrong answer.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { center, padEnd, truncate, width, wrap } from '../dist/text.js';
import { ESC, setColorDepth } from '../dist/ansi.js';

setColorDepth('truecolor');

const GREEN = `${ESC}[38;2;57;255;20m`;
const RESET = `${ESC}[0m`;

test('escape sequences have no display width', () => {
  assert.equal(width(`${GREEN}abc${RESET}`), 3);
  assert.equal(width('abc'), 3);
});

test('wide characters count as two columns', () => {
  assert.equal(width('日本'), 4);
  assert.equal(width('a日'), 3);
});

test('combining marks add nothing', () => {
  assert.equal(width('é'), 1);
});

test('padEnd pads to display width, not code units', () => {
  assert.equal(width(padEnd(`${GREEN}ab${RESET}`, 6)), 6);
  assert.equal(width(padEnd('日', 6)), 6);
});

test('center distributes remainder to the right', () => {
  assert.equal(center('ab', 6), '  ab  ');
  assert.equal(center('abc', 6), ' abc  ');
});

test('truncate respects the column budget', () => {
  const out = truncate('abcdefghij', 5);
  assert.ok(width(out) <= 5);
});

test('truncate keeps text shorter than the budget untouched', () => {
  assert.equal(truncate('abc', 10), 'abc');
});

test('wrap breaks on words', () => {
  assert.deepEqual(wrap('one two three', 7), ['one two', 'three']);
});

test('wrap hard-breaks a word longer than the viewport', () => {
  // Overflowing instead would push the right border off the frame.
  const lines = wrap('supercalifragilistic', 6);
  assert.ok(lines.every((line) => width(line) <= 6));
  assert.equal(lines.join(''), 'supercalifragilistic');
});

test('wrap preserves blank lines between paragraphs', () => {
  assert.deepEqual(wrap('a\n\nb', 10), ['a', '', 'b']);
});
