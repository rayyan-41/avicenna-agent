/**
 * Raw terminal escapes and colour encoding.
 *
 * Everything above this file composes strings; this is the only module that
 * knows what the bytes mean. Colours degrade on their own: a terminal that
 * does not advertise truecolour gets the nearest xterm-256 cube entry rather
 * than a wall of unreadable escape codes.
 */

export const ESC = '\u001B';
export const CSI = `${ESC}[`;

/* -- screen and cursor ---------------------------------------------------- */

export const enterAltScreen = `${CSI}?1049h`;
export const exitAltScreen = `${CSI}?1049l`;
export const hideCursor = `${CSI}?25l`;
export const showCursor = `${CSI}?25h`;
export const clearScreen = `${CSI}2J`;
export const clearLine = `${CSI}2K`;
export const clearToEnd = `${CSI}0K`;
export const home = `${CSI}H`;
export const resetStyle = `${CSI}0m`;

/** 1-indexed, matching the terminal's own coordinate system. */
export function moveTo(row: number, col: number): string {
  return `${CSI}${Math.max(1, row)};${Math.max(1, col)}H`;
}

export const enableBracketedPaste = `${CSI}?2004h`;
export const disableBracketedPaste = `${CSI}?2004l`;

/* -- colour --------------------------------------------------------------- */

export type Rgb = readonly [number, number, number];

export function hexToRgb(hex: string): Rgb {
  const clean = hex.replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((c) => c + c)
          .join('')
      : clean;
  const n = parseInt(full, 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

/** Nearest xterm-256 index, used when the terminal lacks truecolour. */
function to256(rgb: Rgb): number {
  const [r, g, b] = rgb;
  // Greys have their own ramp and look far better than the 6x6x6 cube.
  if (Math.abs(r - g) < 12 && Math.abs(g - b) < 12) {
    if (r < 8) return 16;
    if (r > 248) return 231;
    return 232 + Math.round(((r - 8) / 247) * 24);
  }
  const q = (v: number) => Math.round((v / 255) * 5);
  return 16 + 36 * q(r) + 6 * q(g) + q(b);
}

export type ColorDepth = 'truecolor' | 'ansi256' | 'none';

let depth: ColorDepth = 'truecolor';

export function setColorDepth(next: ColorDepth): void {
  depth = next;
}

export function getColorDepth(): ColorDepth {
  return depth;
}

/** Decide once, from the environment, how much colour we may emit. */
export function detectColorDepth(env: NodeJS.ProcessEnv, isTty: boolean): ColorDepth {
  if (env.NO_COLOR !== undefined && env.NO_COLOR !== '') return 'none';
  if (env.FORCE_COLOR === '0') return 'none';
  if (!isTty && env.FORCE_COLOR === undefined) return 'none';
  const term = (env.COLORTERM ?? '').toLowerCase();
  if (term.includes('truecolor') || term.includes('24bit')) return 'truecolor';
  if (env.WT_SESSION || env.TERM_PROGRAM === 'vscode' || env.TERM_PROGRAM === 'iTerm.app') {
    return 'truecolor';
  }
  if ((env.TERM ?? '').includes('256')) return 'ansi256';
  if (env.TERM === 'dumb') return 'none';
  return 'ansi256';
}

export function fg(rgb: Rgb): string {
  if (depth === 'none') return '';
  if (depth === 'truecolor') return `${CSI}38;2;${rgb[0]};${rgb[1]};${rgb[2]}m`;
  return `${CSI}38;5;${to256(rgb)}m`;
}

export function bg(rgb: Rgb): string {
  if (depth === 'none') return '';
  if (depth === 'truecolor') return `${CSI}48;2;${rgb[0]};${rgb[1]};${rgb[2]}m`;
  return `${CSI}48;5;${to256(rgb)}m`;
}

export const bold = `${CSI}1m`;
export const dim = `${CSI}2m`;
export const italic = `${CSI}3m`;
export const underline = `${CSI}4m`;
export const reverse = `${CSI}7m`;

/** Remove every escape sequence — for measuring and for no-colour output. */
export function strip(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\u001B\[[0-9;?]*[A-Za-z]/g, '');
}
