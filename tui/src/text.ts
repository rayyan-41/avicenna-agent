/**
 * Width-aware text measurement, wrapping and padding.
 *
 * Every layout decision in the TUI is made in display columns, never in
 * `String.length`. A CJK glyph occupies two columns, a combining mark zero,
 * and an escape sequence none at all — measuring in code units instead puts
 * the right border of every box in the wrong place the moment a user pastes
 * a name with an accent in it.
 */

import { ESC, resetStyle, strip } from './ansi.js';

/**
 * Whether the terminal can be trusted with non-ASCII.
 *
 * This is a capability flag, not a style choice: a Windows console started in
 * a legacy code page renders U+2026 as mojibake and throws the column count
 * off by the width of the garbage. It lives here rather than in a theme module
 * because measurement is the only thing in the skeleton that needs it.
 */
let unicode = true;

export function setUnicode(enabled: boolean): void {
  unicode = enabled;
}

export function unicodeEnabled(): boolean {
  return unicode;
}

/** The truncation marker for the active capability level. */
export function ellipsisMark(): string {
  return unicode ? '…' : '...';
}

/** Codepoint ranges that occupy two terminal columns. */
function isWide(cp: number): boolean {
  return (
    cp >= 0x1100 &&
    (cp <= 0x115f || // Hangul Jamo
      cp === 0x2329 ||
      cp === 0x232a ||
      (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) || // CJK, Kangxi
      (cp >= 0xac00 && cp <= 0xd7a3) || // Hangul syllables
      (cp >= 0xf900 && cp <= 0xfaff) || // CJK compatibility ideographs
      (cp >= 0xfe30 && cp <= 0xfe6f) ||
      (cp >= 0xff00 && cp <= 0xff60) || // Fullwidth forms
      (cp >= 0xffe0 && cp <= 0xffe6) ||
      (cp >= 0x1f300 && cp <= 0x1f64f) || // Emoji
      (cp >= 0x1f900 && cp <= 0x1f9ff) ||
      (cp >= 0x20000 && cp <= 0x3fffd))
  );
}

/** Combining marks and variation selectors add nothing to the advance. */
function isZeroWidth(cp: number): boolean {
  return (
    cp === 0x200b ||
    (cp >= 0x0300 && cp <= 0x036f) ||
    (cp >= 0x200c && cp <= 0x200f) ||
    (cp >= 0xfe00 && cp <= 0xfe0f) ||
    (cp >= 0xfe20 && cp <= 0xfe2f)
  );
}

export function charWidth(cp: number): number {
  if (cp === 0x09) return 4;
  if (cp < 0x20 || (cp >= 0x7f && cp < 0xa0)) return 0;
  if (isZeroWidth(cp)) return 0;
  return isWide(cp) ? 2 : 1;
}

/** Display width of a string, ignoring any escape sequences inside it. */
export function width(text: string): number {
  let total = 0;
  for (const ch of strip(text)) {
    total += charWidth(ch.codePointAt(0) ?? 0);
  }
  return total;
}

/** Pad on the right to an exact column count. */
export function padEnd(text: string, target: number): string {
  const w = width(text);
  return w >= target ? text : text + ' '.repeat(target - w);
}

export function padStart(text: string, target: number): string {
  const w = width(text);
  return w >= target ? text : ' '.repeat(target - w) + text;
}

export function center(text: string, target: number): string {
  const w = width(text);
  if (w >= target) return text;
  const left = Math.floor((target - w) / 2);
  return ' '.repeat(left) + text + ' '.repeat(target - w - left);
}

/**
 * Truncate to a column budget, preserving escape sequences.
 *
 * Styling codes are copied through without consuming budget so a truncated
 * line keeps its colour and still terminates cleanly.
 */
export function truncate(text: string, max: number, ellipsis = true): string {
  if (width(text) <= max) return text;
  const tail = ellipsis ? ellipsisMark() : '';
  const budget = Math.max(0, max - width(tail));
  let out = '';
  let used = 0;
  let i = 0;
  while (i < text.length) {
    if (text[i] === ESC) {
      const end = text.indexOf('m', i);
      if (end === -1) break;
      out += text.slice(i, end + 1);
      i = end + 1;
      continue;
    }
    const cp = text.codePointAt(i);
    if (cp === undefined) break;
    const ch = String.fromCodePoint(cp);
    const w = charWidth(cp);
    if (used + w > budget) break;
    out += ch;
    used += w;
    i += ch.length;
  }
  return out + tail + resetStyle;
}

/**
 * Word-wrap to a column budget.
 *
 * Escape sequences are measured as zero width, but a wrapped line does not
 * re-open the style it inherited, so callers colour whole lines rather than
 * spans that cross a wrap boundary.
 */
export function wrap(text: string, max: number): string[] {
  if (max <= 0) return [text];
  const out: string[] = [];
  for (const paragraph of text.split('\n')) {
    if (paragraph === '') {
      out.push('');
      continue;
    }
    if (width(paragraph) <= max) {
      out.push(paragraph);
      continue;
    }
    let line = '';
    for (const word of paragraph.split(' ')) {
      const candidate = line === '' ? word : `${line} ${word}`;
      if (width(candidate) <= max) {
        line = candidate;
        continue;
      }
      if (line !== '') out.push(line);
      // A single word longer than the viewport is broken hard rather than
      // allowed to overflow and corrupt the frame.
      if (width(word) > max) {
        let chunk = '';
        for (const ch of word) {
          if (width(chunk + ch) > max) {
            out.push(chunk);
            chunk = ch;
          } else {
            chunk += ch;
          }
        }
        line = chunk;
      } else {
        line = word;
      }
    }
    if (line !== '') out.push(line);
  }
  return out;
}

/** A horizontal rule of the given width. */
export function rule(cols: number, ch = '-'): string {
  return ch.repeat(Math.max(0, cols));
}
