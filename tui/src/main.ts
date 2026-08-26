/**
 * Entry point: resolve the interpreter, start the backend, hand over to the app.
 *
 * Everything that can fail before the alt screen opens is reported as plain
 * text on the normal buffer. A TUI that dies inside the alt screen takes its
 * own error message with it, so nothing enters that screen until the backend
 * has answered.
 */

import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { detectColorDepth, setColorDepth } from './ansi.js';
import { App, VERSION } from './app.js';
import { Bridge } from './bridge.js';
import { Screen } from './screen.js';
import { setUnicode } from './text.js';

interface Options {
  vault?: string;
  python?: string;
  cwd: string;
  help: boolean;
  version: boolean;
  ascii: boolean;
}

function parseArgs(argv: string[]): Options {
  const opts: Options = { cwd: process.cwd(), help: false, version: false, ascii: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case '--vault':
        opts.vault = argv[++i];
        break;
      case '--python':
        opts.python = argv[++i];
        break;
      case '--cwd':
        opts.cwd = resolve(argv[++i] ?? process.cwd());
        break;
      case '--ascii':
        opts.ascii = true;
        break;
      case '-h':
      case '--help':
        opts.help = true;
        break;
      case '-v':
      case '--version':
        opts.version = true;
        break;
      default:
        // A bare argument is treated as the vault path, matching the CLI.
        if (arg && !arg.startsWith('-') && !opts.vault) opts.vault = arg;
    }
  }
  return opts;
}

const HELP = `
  avicenna ${VERSION}

  Usage
    avicenna [options]

  Options
    --vault <path>     Bind to a specific vault
    --python <path>    Interpreter that runs the backend
    --cwd <path>       Working directory for vault detection
    --ascii            Restrict output to ASCII, for legacy consoles
    -v, --version      Print the version
    -h, --help         This text
`;

/**
 * Find the interpreter that has `avicenna` installed.
 *
 * A repo checkout almost always has a .venv next to it, and picking the bare
 * `python` on PATH there produces a confusing ModuleNotFoundError, so the venv
 * wins when one is present.
 */
function resolvePython(explicit: string | undefined, root: string): string {
  if (explicit) return explicit;
  if (process.env.AVICENNA_PYTHON) return process.env.AVICENNA_PYTHON;

  const candidates =
    process.platform === 'win32'
      ? [join(root, '.venv', 'Scripts', 'python.exe'), join(root, 'venv', 'Scripts', 'python.exe')]
      : [join(root, '.venv', 'bin', 'python'), join(root, 'venv', 'bin', 'python')];

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

/** The repository root, two levels up from dist/main.js. */
function projectRoot(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, '..', '..');
}

async function main(): Promise<void> {
  const opts = parseArgs(process.argv.slice(2));

  setColorDepth(detectColorDepth(process.env, Boolean(process.stdout.isTTY)));
  if (opts.ascii || process.env.AVICENNA_ASCII === '1') setUnicode(false);

  if (opts.version) {
    process.stdout.write(`avicenna ${VERSION}\n`);
    return;
  }
  if (opts.help) {
    process.stdout.write(`${HELP}\n`);
    return;
  }

  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    process.stderr.write(
      'Avicenna needs an interactive terminal. ' +
        'For scripted use run `avicenna note "<topic>"` instead.\n',
    );
    process.exitCode = 1;
    return;
  }

  const root = projectRoot();
  const bridge = new Bridge({
    python: resolvePython(opts.python, root),
    cwd: opts.cwd,
    vault: opts.vault,
    projectRoot: root,
  });

  try {
    await bridge.start();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    process.stderr.write('\n  Avicenna could not start its backend.\n\n');
    process.stderr.write(`  ${message.split('\n').join('\n  ')}\n\n`);
    process.stderr.write(
      '  Check that the package is installed: pip install -e .\n' +
        '  Or point at an interpreter: avicenna --python /path/to/python\n\n',
    );
    process.exitCode = 1;
    return;
  }

  const screen = new Screen(process.stdout);
  const app = new App({ bridge, screen });

  // Restore the terminal whatever happens; a crashed TUI must not leave the
  // user in a raw-mode shell with no cursor.
  const shutdown = () => {
    void app.stop().finally(() => process.exit(0));
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  process.on('uncaughtException', (err) => {
    void app.stop().finally(() => {
      process.stderr.write(`\nAvicenna crashed: ${err.stack ?? err.message}\n`);
      process.exit(1);
    });
  });

  await app.start();
}

void main();
