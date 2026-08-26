/**
 * The edit buffer.
 *
 * Holds the text, the caret and the history ring, applies editing keys, and
 * can lay itself out into visual rows so a renderer knows where the terminal
 * caret belongs. Multi-line input is supported because a prompt for a note is
 * often a paragraph rather than a phrase.
 *
 * There is no chrome here: no border, no prompt glyph, no colour. Layout
 * returns raw text rows and a caret offset within them, and whatever draws the
 * input decides what it looks like.
 */

import type { Key } from './keys.js';
import { width, wrap } from './text.js';

export interface ComposerLayout {
  /** Unstyled text rows, wrapped to the given width. */
  lines: string[];
  /** Caret row within `lines`, 0-indexed. */
  cursorRow: number;
  /** Caret column within its row, 0-indexed and measured in display columns. */
  cursorCol: number;
}

const MAX_HISTORY = 200;

export class Composer {
  private buffer = '';
  private cursor = 0;
  private history: string[] = [];
  private historyIndex = -1;
  private draft = '';

  get value(): string {
    return this.buffer;
  }

  get isEmpty(): boolean {
    return this.buffer.trim() === '';
  }

  get caret(): number {
    return this.cursor;
  }

  set(text: string, cursor = text.length): void {
    this.buffer = text;
    this.cursor = Math.max(0, Math.min(cursor, text.length));
  }

  clear(): void {
    this.buffer = '';
    this.cursor = 0;
    this.historyIndex = -1;
  }

  /** Commit the current buffer to history and empty it. */
  take(): string {
    const text = this.buffer;
    if (text.trim() !== '') {
      if (this.history[0] !== text) this.history.unshift(text);
      if (this.history.length > MAX_HISTORY) this.history.pop();
    }
    this.clear();
    return text;
  }

  insert(text: string): void {
    // Normalise pasted line endings so a paste does not smuggle in \r.
    const clean = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    this.buffer = this.buffer.slice(0, this.cursor) + clean + this.buffer.slice(this.cursor);
    this.cursor += clean.length;
  }

  /**
   * Apply an editing key. Returns true when the key was consumed, so the app
   * can fall through to global bindings for anything the editor ignores.
   */
  handle(key: Key): boolean {
    switch (key.name) {
      case 'backspace':
        if (this.cursor > 0) {
          this.buffer = this.buffer.slice(0, this.cursor - 1) + this.buffer.slice(this.cursor);
          this.cursor -= 1;
        }
        return true;

      case 'delete':
        if (this.cursor < this.buffer.length) {
          this.buffer = this.buffer.slice(0, this.cursor) + this.buffer.slice(this.cursor + 1);
        }
        return true;

      case 'left':
        this.cursor = Math.max(0, this.cursor - 1);
        return true;

      case 'right':
        this.cursor = Math.min(this.buffer.length, this.cursor + 1);
        return true;

      case 'ctrl+left':
      case 'alt+b':
        this.cursor = this.wordLeft();
        return true;

      case 'ctrl+right':
      case 'alt+f':
        this.cursor = this.wordRight();
        return true;

      case 'home':
      case 'ctrl+a':
        this.cursor = this.lineStart();
        return true;

      case 'end':
      case 'ctrl+e':
        this.cursor = this.lineEnd();
        return true;

      case 'ctrl+u':
        this.buffer = this.buffer.slice(this.cursor);
        this.cursor = 0;
        return true;

      case 'ctrl+k':
        this.buffer = this.buffer.slice(0, this.cursor);
        return true;

      case 'ctrl+w': {
        const start = this.wordLeft();
        this.buffer = this.buffer.slice(0, start) + this.buffer.slice(this.cursor);
        this.cursor = start;
        return true;
      }

      // A deliberate newline rather than a submit.
      case 'alt+enter':
      case 'ctrl+j':
        this.insert('\n');
        return true;

      case 'paste':
        this.insert(key.text);
        return true;

      default:
        if (key.text && !key.ctrl && !key.alt) {
          this.insert(key.text);
          return true;
        }
        return false;
    }
  }

  /* -- history ------------------------------------------------------------ */

  historyPrev(): boolean {
    if (this.history.length === 0) return false;
    if (this.historyIndex === -1) this.draft = this.buffer;
    this.historyIndex = Math.min(this.historyIndex + 1, this.history.length - 1);
    this.set(this.history[this.historyIndex] ?? '');
    return true;
  }

  historyNext(): boolean {
    if (this.historyIndex === -1) return false;
    this.historyIndex -= 1;
    this.set(this.historyIndex === -1 ? this.draft : (this.history[this.historyIndex] ?? ''));
    return true;
  }

  /** True when the caret sits on the first/last visual line of the buffer. */
  atFirstLine(): boolean {
    return !this.buffer.slice(0, this.cursor).includes('\n');
  }

  atLastLine(): boolean {
    return !this.buffer.slice(this.cursor).includes('\n');
  }

  /* -- layout ------------------------------------------------------------ */

  /**
   * Wrap the buffer to `cols` and report where the caret lands.
   *
   * Wrapping is done here rather than by the renderer because the caret has to
   * be mapped back to a row and column, and only this class knows the offset
   * the caret sits at in the unwrapped text.
   */
  layout(cols: number): ComposerLayout {
    const inner = Math.max(1, cols);
    const visual: Array<{ text: string; start: number }> = [];
    let offset = 0;

    for (const paragraph of this.buffer.split('\n')) {
      const pieces = paragraph === '' ? [''] : wrap(paragraph, inner);
      let consumed = 0;
      for (const piece of pieces) {
        visual.push({ text: piece, start: offset + consumed });
        // +1 for the space the wrapper consumed between words.
        consumed += piece.length + (consumed + piece.length < paragraph.length ? 1 : 0);
      }
      offset += paragraph.length + 1;
    }
    if (visual.length === 0) visual.push({ text: '', start: 0 });

    let cursorRow = 0;
    let cursorCol = 0;
    visual.forEach((line, index) => {
      const end = line.start + line.text.length;
      if (this.cursor >= line.start && this.cursor <= end) {
        cursorRow = index;
        cursorCol = width(line.text.slice(0, this.cursor - line.start));
      }
    });

    return { lines: visual.map((line) => line.text), cursorRow, cursorCol };
  }

  /* -- helpers ------------------------------------------------------------ */

  private lineStart(): number {
    const idx = this.buffer.lastIndexOf('\n', Math.max(0, this.cursor - 1));
    return idx === -1 ? 0 : idx + 1;
  }

  private lineEnd(): number {
    const idx = this.buffer.indexOf('\n', this.cursor);
    return idx === -1 ? this.buffer.length : idx;
  }

  private wordLeft(): number {
    let i = this.cursor;
    while (i > 0 && /\s/.test(this.buffer[i - 1] ?? '')) i -= 1;
    while (i > 0 && !/\s/.test(this.buffer[i - 1] ?? '')) i -= 1;
    return i;
  }

  private wordRight(): number {
    let i = this.cursor;
    const n = this.buffer.length;
    while (i < n && /\s/.test(this.buffer[i] ?? '')) i += 1;
    while (i < n && !/\s/.test(this.buffer[i] ?? '')) i += 1;
    return i;
  }
}
