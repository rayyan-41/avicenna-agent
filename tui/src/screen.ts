/**
 * The frame renderer.
 *
 * Views produce a full array of styled lines each frame; this class works out
 * what actually changed and writes only those rows. Repainting everything on
 * every keystroke is what makes a TUI flicker and what makes it crawl over
 * SSH, so the diff is the whole point rather than an optimisation.
 */

import {
  clearLine,
  clearScreen,
  clearToEnd,
  disableBracketedPaste,
  enableBracketedPaste,
  enterAltScreen,
  exitAltScreen,
  hideCursor,
  home,
  moveTo,
  resetStyle,
  showCursor,
} from './ansi.js';
import { truncate, width } from './text.js';

export interface Size {
  rows: number;
  cols: number;
}

export interface Frame {
  lines: string[];
  /** Where the caret should sit, 1-indexed. Omit to keep it hidden. */
  cursor?: { row: number; col: number };
}

export class Screen {
  private prev: string[] = [];
  private active = false;
  private cursorVisible = false;

  constructor(private readonly out: NodeJS.WriteStream = process.stdout) {}

  get size(): Size {
    return {
      rows: Math.max(8, this.out.rows || 24),
      cols: Math.max(28, this.out.columns || 80),
    };
  }

  start(): void {
    if (this.active) return;
    this.active = true;
    // Bracketed paste on. Both sequences were defined and neither was ever
    // written, so terminals never entered the mode and the entire paste path
    // — decoder, composer, onboarding — was dead in practice: a pasted API key
    // with a trailing newline arrived as text followed by `enter`, submitting
    // whatever had been received so far.
    this.out.write(
      enterAltScreen + enableBracketedPaste + hideCursor + clearScreen + home,
    );
    this.prev = [];
  }

  stop(): void {
    if (!this.active) return;
    this.active = false;
    this.out.write(resetStyle + disableBracketedPaste + showCursor + exitAltScreen);
  }

  /** Force the next render to repaint every row (after a resize). */
  invalidate(): void {
    this.prev = [];
  }

  render(frame: Frame): void {
    if (!this.active) return;
    const { rows, cols } = this.size;
    const next = frame.lines.slice(0, rows);
    while (next.length < rows) next.push('');

    let out = '';
    for (let i = 0; i < rows; i++) {
      const line = fit(next[i] ?? '', cols);
      if (this.prev[i] === line) continue;
      out += moveTo(i + 1, 1) + clearLine + line + resetStyle;
      this.prev[i] = line;
    }

    // Cursor placement is part of the frame: an input caret that lags a frame
    // behind the text it belongs to reads as input lag even when it is not.
    const cursor = frame.cursor;
    if (cursor) {
      out += moveTo(cursor.row, cursor.col);
      if (!this.cursorVisible) {
        out += showCursor;
        this.cursorVisible = true;
      }
    } else if (this.cursorVisible) {
      out += hideCursor;
      this.cursorVisible = false;
    }

    if (out) this.out.write(out);
  }

  /** Write a line into the normal buffer — used after the alt screen closes. */
  writeDirect(text: string): void {
    this.out.write(text + '\n');
  }
}

/**
 * Clip a line to at most `cols` columns.
 *
 * Deliberately does not pad: every row write is preceded by `clearLine`, so
 * trailing blanks would be wasted bytes on each frame. The docstring used to
 * claim "clip or pad" while both short-line branches returned the line
 * untouched.
 */
function fit(line: string, cols: number): string {
  return width(line) <= cols ? line : truncate(line, cols, false);
}

export { clearToEnd };
