/**
 * Keyboard decoding for raw mode.
 *
 * In raw mode the terminal hands over bytes, not keystrokes: an arrow key is
 * three characters, a paste is a burst of hundreds. This module turns that
 * stream back into discrete events so the rest of the app never parses an
 * escape sequence.
 */

import { ESC } from './ansi.js';

export interface Key {
  /** Canonical name: 'a', 'enter', 'up', 'ctrl+c', 'shift+tab', … */
  name: string;
  /** Literal text to insert, when the key produces any. */
  text: string;
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
  /** True when the chunk arrived as a bracketed paste. */
  paste: boolean;
}

function key(name: string, text = '', extra: Partial<Key> = {}): Key {
  return { name, text, ctrl: false, alt: false, shift: false, paste: false, ...extra };
}

const CSI_FINAL: Record<string, string> = {
  A: 'up',
  B: 'down',
  C: 'right',
  D: 'left',
  H: 'home',
  F: 'end',
};

const TILDE_CODES: Record<string, string> = {
  '1': 'home',
  '2': 'insert',
  '3': 'delete',
  '4': 'end',
  '5': 'pageup',
  '6': 'pagedown',
  '7': 'home',
  '8': 'end',
};

/** xterm modifier parameter: 1 + bit flags (shift 1, alt 2, ctrl 4). */
function modifiers(param: string | undefined): Pick<Key, 'ctrl' | 'alt' | 'shift'> {
  const n = param ? parseInt(param, 10) - 1 : 0;
  return {
    shift: (n & 1) !== 0,
    alt: (n & 2) !== 0,
    ctrl: (n & 4) !== 0,
  };
}

const PASTE_START = `${ESC}[200~`;
const PASTE_END = `${ESC}[201~`;

/**
 * Decode one chunk from stdin into zero or more keys.
 *
 * Bracketed paste is handled first and whole: pasted text must never be
 * interpreted as commands, or a pasted newline submits half a message.
 */
export function decode(chunk: string): Key[] {
  const keys: Key[] = [];
  let i = 0;

  while (i < chunk.length) {
    if (chunk.startsWith(PASTE_START, i)) {
      const end = chunk.indexOf(PASTE_END, i);
      const body =
        end === -1
          ? chunk.slice(i + PASTE_START.length)
          : chunk.slice(i + PASTE_START.length, end);
      keys.push(key('paste', body, { paste: true }));
      i = end === -1 ? chunk.length : end + PASTE_END.length;
      continue;
    }

    const ch = chunk[i] as string;

    if (ch === ESC) {
      const next = chunk[i + 1];

      // Bare ESC.
      if (next === undefined) {
        keys.push(key('escape'));
        i += 1;
        continue;
      }

      // CSI sequence: ESC [ params final
      if (next === '[' || next === 'O') {
        const seq = /^([0-9;]*)([A-Za-z~])/.exec(chunk.slice(i + 2));
        if (seq) {
          const [, params = '', final = ''] = seq;
          const parts = params.split(';');
          const mods = modifiers(parts[1]);
          if (final === '~') {
            const name = TILDE_CODES[parts[0] ?? ''] ?? 'unknown';
            keys.push(key(withMods(name, mods), '', mods));
          } else if (final === 'Z') {
            keys.push(key('shift+tab', '', { shift: true }));
          } else if (CSI_FINAL[final]) {
            keys.push(key(withMods(CSI_FINAL[final] as string, mods), '', mods));
          } else {
            keys.push(key('unknown'));
          }
          i += 2 + seq[0].length;
          continue;
        }
      }

      // ESC followed by a character is Alt+char.
      keys.push(key(`alt+${next}`, '', { alt: true }));
      i += 2;
      continue;
    }

    const code = ch.charCodeAt(0);

    if (ch === '\r' || ch === '\n') {
      keys.push(key('enter', ''));
      i += 1;
      continue;
    }
    if (ch === '\t') {
      keys.push(key('tab', ''));
      i += 1;
      continue;
    }
    if (code === 127 || code === 8) {
      keys.push(key('backspace', ''));
      i += 1;
      continue;
    }
    // C0 control characters map back to their letter.
    if (code < 32) {
      const letter = String.fromCharCode(code + 96);
      keys.push(key(`ctrl+${letter}`, '', { ctrl: true }));
      i += 1;
      continue;
    }

    // Printable: consume the whole codepoint so astral characters survive.
    const cp = chunk.codePointAt(i);
    const text = cp === undefined ? ch : String.fromCodePoint(cp);
    keys.push(key(text, text));
    i += text.length;
  }

  return keys;
}

function withMods(name: string, mods: Pick<Key, 'ctrl' | 'alt' | 'shift'>): string {
  let out = name;
  if (mods.shift) out = `shift+${out}`;
  if (mods.alt) out = `alt+${out}`;
  if (mods.ctrl) out = `ctrl+${out}`;
  return out;
}
