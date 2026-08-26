/**
 * The application skeleton: state, key handling, event translation, and the
 * smallest frame that can carry them.
 *
 * This file is deliberately unstyled. There is no palette, no glyph set, no
 * box drawing and no overlay chrome — the visual design is being rebuilt from
 * scratch, and what remains here is the mechanism a design attaches to:
 *
 *   - a transcript of plain paragraphs, wrapped at render time,
 *   - an event translator that turns pipeline events into those paragraphs,
 *   - a dispatcher for the slash commands,
 *   - the onboarding state machine,
 *   - a render() that stacks transcript, input rows and one status line.
 *
 * Rendering stays pull-based. Nothing draws directly: handlers mutate state and
 * request a frame, and one scheduled render coalesces them, so a burst of
 * twenty pipeline events costs one repaint rather than twenty.
 */

import { Bridge, BridgeError } from './bridge.js';
import { Composer } from './composer.js';
import { COMMANDS, complete, isCommand, parse, type CommandSpec } from './commands.js';
import { decode, type Key } from './keys.js';
import type { AgentInfo, AuthStatus, EventFrame, VaultInfo } from './protocol.js';
import { Screen } from './screen.js';
import { truncate, width, wrap } from './text.js';

export const VERSION = '2.0.0';

type Mode = 'chat' | 'onboarding';

type OnboardingStage = 'choice' | 'key' | 'validating' | 'local' | 'done';

interface OnboardingState {
  stage: OnboardingStage;
  choice: number;
  keyBuffer: string;
  message: string;
  error: string;
}

interface Busy {
  /** A note run is cancellable and event-driven; a chat turn is neither. */
  kind: 'run' | 'chat';
  label: string;
  runId?: string;
  startedAt: number;
}

interface RunStats {
  sectionsDone: number;
  sectionsTotal: number;
  words: number;
  tools: number;
}

export interface AppOptions {
  bridge: Bridge;
  screen: Screen;
}

/** The prompt marker on the first input row. Two columns, ASCII, no colour. */
const PROMPT = '> ';
const CONTINUATION = '  ';

export class App {
  private readonly bridge: Bridge;
  private readonly screen: Screen;
  private readonly composer = new Composer();

  /** Transcript entries are unwrapped paragraphs; wrapping happens per frame. */
  private transcript: string[] = [];
  private version = 0;
  private cache: { cols: number; version: number; lines: string[] } | null = null;

  private mode: Mode = 'chat';
  private scroll = 0;
  private busy: Busy | null = null;
  private stats: RunStats = { sectionsDone: 0, sectionsTotal: 0, words: 0, tools: 0 };

  private vault: VaultInfo | null = null;
  private auth: AuthStatus | null = null;
  private agents: AgentInfo[] = [];
  private activeAgent: string | null = null;
  private model = '';

  private completionIndex = 0;
  /** Identifies the in-flight chat turn, so a stale one cannot clear busy. */
  private chatToken = 0;
  private ticker: NodeJS.Timeout | null = null;
  private renderQueued = false;
  private pendingQuit = false;
  private notice = '';
  private noticeTimer: NodeJS.Timeout | null = null;
  private stopped = false;

  private onboarding: OnboardingState = {
    stage: 'choice',
    choice: 0,
    keyBuffer: '',
    message: '',
    error: '',
  };

  constructor(opts: AppOptions) {
    this.bridge = opts.bridge;
    this.screen = opts.screen;
  }

  /* -- lifecycle ---------------------------------------------------------- */

  async start(): Promise<void> {
    this.screen.start();
    this.bindInput();
    this.bindBridge();

    try {
      const hello = await this.bridge.hello();
      this.auth = hello.auth;
      this.model = hello.auth.model;
    } catch (err) {
      this.write(`error: could not talk to the Avicenna backend — ${describe(err)}`);
    }

    try {
      this.vault = await this.bridge.vaultInfo();
    } catch (err) {
      this.write(`error: could not resolve a vault — ${describe(err)}`);
    }

    this.write(`avicenna ${VERSION}${this.model ? `  model ${this.model}` : ''}`);
    this.write(this.vault?.found ? `vault: ${this.vault.root}` : 'vault: none bound');
    if (this.vault?.found && !this.vault.inside) {
      this.write('You are standing outside the vault; notes will still be written into it.');
    }
    this.write('Type a topic to generate a note, or / for commands.');

    const forced = process.env.AVICENNA_FORCE_ONBOARD === '1';
    if (forced || !this.auth?.configured) {
      this.mode = 'onboarding';
    } else if (this.vault?.found) {
      void this.loadAgents();
    }

    this.startTicker();
    this.requestRender();
  }

  async stop(): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    if (this.ticker) clearInterval(this.ticker);
    if (this.noticeTimer) clearTimeout(this.noticeTimer);
    if (process.stdin.isTTY) process.stdin.setRawMode(false);
    process.stdin.pause();
    this.screen.stop();
    await this.bridge.stop();
  }

  private bindInput(): void {
    const stdin = process.stdin;
    if (stdin.isTTY) stdin.setRawMode(true);
    stdin.setEncoding('utf8');
    stdin.resume();
    stdin.on('data', (chunk: string) => {
      for (const key of decode(chunk)) this.onKey(key);
    });
    process.stdout.on('resize', () => {
      this.screen.invalidate();
      this.cache = null;
      this.requestRender();
    });
  }

  private bindBridge(): void {
    this.bridge.on('event', (frame: EventFrame) => this.onEvent(frame));
    this.bridge.on('exit', () => {
      if (this.stopped) return;
      this.write('error: the Avicenna backend stopped unexpectedly. Press Ctrl+C to exit.');
      this.busy = null;
      this.requestRender();
    });
  }

  /**
   * One tick a second, only while something is in flight.
   *
   * The status line reports elapsed seconds, so it goes stale without a clock
   * of its own. Anything finer than a second would be animation, which this
   * skeleton deliberately has none of.
   */
  private startTicker(): void {
    this.ticker = setInterval(() => {
      if (this.busy || this.onboarding.stage === 'validating') this.requestRender();
    }, 1000);
    this.ticker.unref?.();
  }

  /* -- transcript --------------------------------------------------------- */

  /** Append one or more paragraphs. Embedded newlines become separate rows. */
  private write(text: string): void {
    for (const line of text.split('\n')) this.transcript.push(line);
    this.version += 1;
    this.scroll = 0; // new output pins the view to the bottom
    this.requestRender();
  }

  private writeRows(rows: Array<[string, string]>, title?: string): void {
    if (title) this.write(title);
    const label = rows.reduce((max, row) => Math.max(max, row[0].length), 0);
    for (const [key, value] of rows) this.write(`  ${key.padEnd(label)}  ${value}`);
  }

  private mutate(fn: () => void): void {
    fn();
    this.version += 1;
    this.requestRender();
  }

  private flash(message: string): void {
    this.notice = message;
    if (this.noticeTimer) clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      this.notice = '';
      this.requestRender();
    }, 2600);
    this.noticeTimer.unref?.();
    this.requestRender();
  }

  private requestRender(): void {
    if (this.renderQueued || this.stopped) return;
    this.renderQueued = true;
    setImmediate(() => {
      this.renderQueued = false;
      this.render();
    });
  }

  /* -- input -------------------------------------------------------------- */

  private onKey(key: Key): void {
    if (this.mode === 'onboarding') {
      void this.onOnboardingKey(key);
      return;
    }

    // Ctrl+C escalates: it cancels work, then clears input, then quits.
    if (key.name === 'ctrl+c') {
      if (this.busy) {
        void this.cancelRun();
        return;
      }
      if (!this.composer.isEmpty) {
        this.composer.clear();
        this.pendingQuit = false;
        this.requestRender();
        return;
      }
      if (this.pendingQuit) {
        void this.quit();
        return;
      }
      this.pendingQuit = true;
      this.flash('Press Ctrl+C again to exit.');
      return;
    }
    this.pendingQuit = false;

    if (key.name === 'ctrl+d' || key.name === 'ctrl+q') {
      void this.quit();
      return;
    }

    if (key.name === 'ctrl+l') {
      this.mutate(() => {
        this.transcript = [];
        this.cache = null;
      });
      return;
    }

    const completions = this.completions();
    const completing = completions.length > 0;

    switch (key.name) {
      case 'pageup':
        this.scrollBy(-Math.max(1, this.viewportRows() - 2));
        return;
      case 'pagedown':
        this.scrollBy(Math.max(1, this.viewportRows() - 2));
        return;
      case 'shift+up':
        this.scrollBy(-1);
        return;
      case 'shift+down':
        this.scrollBy(1);
        return;

      case 'escape':
        if (completing) {
          this.composer.clear();
          this.requestRender();
          return;
        }
        if (this.busy) void this.cancelRun();
        return;

      case 'up':
        if (completing) {
          this.completionIndex = Math.max(0, this.completionIndex - 1);
          this.requestRender();
          return;
        }
        if (this.composer.atFirstLine() && this.composer.historyPrev()) {
          this.requestRender();
        }
        return;

      case 'down':
        if (completing) {
          this.completionIndex = Math.min(completions.length - 1, this.completionIndex + 1);
          this.requestRender();
          return;
        }
        if (this.composer.atLastLine() && this.composer.historyNext()) {
          this.requestRender();
        }
        return;

      case 'tab':
        if (completing) {
          const match = completions[this.completionIndex];
          if (match) {
            this.composer.set(`/${match.name}${match.args ? ' ' : ''}`);
            this.requestRender();
          }
        }
        return;

      case 'enter': {
        // Enter on a bare, still-ambiguous prefix accepts the highlight rather
        // than dispatching something the user has not finished typing.
        if (completing && this.composer.value.trim() === `/${this.currentPrefix()}`) {
          const match = completions[this.completionIndex];
          if (match && match.name !== this.currentPrefix()) {
            this.composer.set(`/${match.name}${match.args ? ' ' : ''}`);
            this.requestRender();
            return;
          }
        }
        void this.submit();
        return;
      }

      default:
        break;
    }

    if (this.composer.handle(key)) {
      this.completionIndex = 0;
      this.requestRender();
    }
  }

  private currentPrefix(): string {
    const value = this.composer.value;
    if (!isCommand(value)) return '';
    const rest = value.slice(1);
    const space = rest.indexOf(' ');
    return (space === -1 ? rest : rest.slice(0, space)).toLowerCase();
  }

  /** Completion is for choosing a command, so it stops once arguments begin. */
  private completions(): CommandSpec[] {
    const value = this.composer.value;
    if (!isCommand(value) || value.includes(' ') || value.includes('\n')) return [];
    return complete(value);
  }

  private scrollBy(delta: number): void {
    const total = this.transcriptLines().length;
    const max = Math.max(0, total - this.viewportRows());
    this.scroll = Math.max(0, Math.min(max, this.scroll - delta));
    this.requestRender();
  }

  /* -- submission --------------------------------------------------------- */

  private async submit(): Promise<void> {
    const text = this.composer.value.trim();
    if (text === '') return;
    this.composer.take();
    this.completionIndex = 0;

    if (isCommand(text)) {
      await this.dispatch(text);
      return;
    }

    this.write(`${PROMPT}${text}`);

    // A bare prompt means different things depending on what is selected: with
    // an agent chosen it is a conversation, otherwise it is a note topic.
    if (this.activeAgent) await this.sendChat(text);
    else await this.startRun(text, {});
  }

  private async dispatch(input: string): Promise<void> {
    const { name, args } = parse(input);
    this.write(`${PROMPT}${input}`);

    switch (name) {
      case 'help':
        this.showHelp();
        return;

      case 'quit':
      case 'exit':
        await this.quit();
        return;

      case 'clear':
        this.mutate(() => {
          this.transcript = [];
          this.cache = null;
        });
        return;

      case 'note':
        if (!args) return this.usage('/note <topic>');
        await this.startRun(args, {});
        return;

      case 'dry':
        if (!args) return this.usage('/dry <topic>');
        await this.startRun(args, { dryRun: true });
        return;

      case 'resume':
        await this.startRun('', { resume: true });
        return;

      case 'cancel':
        await this.cancelRun();
        return;

      case 'agents':
        await this.showAgents();
        return;

      case 'agent':
        await this.selectAgent(args);
        return;

      case 'route':
        if (!args) return this.usage('/route <topic>');
        await this.explainRoute(args);
        return;

      case 'vault':
        await this.showVault();
        return;

      case 'tools':
        await this.showTools();
        return;

      case 'mcp':
        await this.showMcp();
        return;

      case 'init':
        await this.initVault(args);
        return;

      case 'login':
        this.mode = 'onboarding';
        this.onboarding = {
          stage: 'choice',
          choice: 0,
          keyBuffer: '',
          message: '',
          error: '',
        };
        this.requestRender();
        return;

      case 'diagnostics': {
        const lines = this.bridge.diagnostics();
        if (lines.length === 0) {
          this.write('No backend diagnostics this session.');
          return;
        }
        this.write('Backend stderr:');
        for (const line of lines.slice(-20)) this.write(`  ${line}`);
        return;
      }

      default:
        this.write(`Unknown command /${name}. Type /help to see what exists.`);
    }
  }

  private usage(text: string): void {
    this.write(`Usage: ${text}`);
  }

  private showHelp(): void {
    this.write('Commands');
    const visible = COMMANDS.filter((cmd) => !cmd.hidden);
    const label = visible.reduce(
      (max, cmd) => Math.max(max, `/${cmd.name} ${cmd.args ?? ''}`.trim().length),
      0,
    );
    for (const cmd of visible) {
      const call = `/${cmd.name} ${cmd.args ?? ''}`.trim();
      this.write(`  ${call.padEnd(label)}  ${cmd.summary}`);
    }
    this.write('Keys');
    for (const [key, what] of [
      ['enter', 'send'],
      ['alt+enter', 'newline'],
      ['tab', 'accept the highlighted command'],
      ['up / down', 'prompt history, or move the highlight'],
      ['pgup / pgdn', 'scroll the transcript'],
      ['esc', 'dismiss completion, or cancel a run'],
      ['ctrl+l', 'clear the transcript'],
      ['ctrl+c', 'cancel a run, then quit'],
    ] as Array<[string, string]>) {
      this.write(`  ${key.padEnd(12)}  ${what}`);
    }
  }

  /* -- backend actions ---------------------------------------------------- */

  private async startRun(topic: string, params: Record<string, unknown>): Promise<void> {
    if (this.busy) {
      this.write('A run is already in flight. Esc cancels it.');
      return;
    }
    if (!this.vault?.found) {
      this.write('No vault bound. Run /init <path> to scaffold one.');
      return;
    }
    this.stats = { sectionsDone: 0, sectionsTotal: 0, words: 0, tools: 0 };
    this.busy = {
      kind: 'run',
      label: params.dryRun ? 'pre-flight' : 'generating',
      startedAt: Date.now(),
    };
    this.requestRender();
    try {
      const handle = await this.bridge.runNote({ topic, ...params });
      if (this.busy) this.busy.runId = handle.runId;
    } catch (err) {
      this.busy = null;
      this.write(`error: ${describe(err)}`);
    }
  }

  private async cancelRun(): Promise<void> {
    if (!this.busy) return;
    // Esc during a chat turn used to reach here with runId undefined, which the
    // backend reads as "cancel everything" — silently killing a note run the
    // user had not asked to stop. A chat turn is not cancellable, so say so.
    if (this.busy.kind === 'chat') {
      this.write('A chat reply is in flight; it cannot be cancelled.');
      return;
    }
    const runId = this.busy.runId;
    if (!runId) {
      this.write('The run has not been acknowledged yet; try again in a moment.');
      return;
    }
    try {
      await this.bridge.runCancel(runId);
      this.write('Run cancelled.');
      // Only cleared on a confirmed cancel. Clearing optimistically in a
      // `finally` meant a *failed* cancel still looked like a stopped run.
      if (this.busy?.runId === runId) this.busy = null;
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    } finally {
      this.requestRender();
    }
  }

  private async sendChat(text: string): Promise<void> {
    // Guarded like startRun. Two quick Enters used to issue two concurrent
    // chat.send requests whose appends interleaved into one shared history
    // list, producing user/user/assistant/assistant orderings.
    if (this.busy) {
      this.write(
        this.busy.kind === 'chat'
          ? 'Still waiting on the previous reply.'
          : 'A run is in flight. Esc cancels it.',
      );
      return;
    }
    const token = ++this.chatToken;
    this.busy = { kind: 'chat', label: this.activeAgent ?? 'chat', startedAt: Date.now() };
    this.requestRender();
    try {
      const result = await this.bridge.chatSend(text, this.activeAgent ?? undefined);
      this.write(`${result.agent}: ${result.text}`);
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    } finally {
      // Only clear the busy state this call created. A finished chat turn used
      // to clear the busy state of whatever was running at the time.
      if (this.busy?.kind === 'chat' && token === this.chatToken) this.busy = null;
      this.requestRender();
    }
  }

  private async loadAgents(): Promise<void> {
    try {
      this.agents = await this.bridge.agents();
    } catch (err) {
      // A vault with no agents is legitimate; a vault whose agents failed to
      // load is not, and reporting the second as the first hid exactly the
      // validation errors AgentDef.from_file exists to raise.
      this.agents = [];
      this.write(`Could not load agents: ${describe(err)}`);
    }
  }

  private async showAgents(): Promise<void> {
    await this.loadAgents();
    if (this.agents.length === 0) {
      this.write('This vault defines no agents.');
      return;
    }
    this.writeRows(
      this.agents.map(
        (a) =>
          [a.name, `[${a.type}${a.domain ? `/${a.domain}` : ''}] ${a.description}`] as [
            string,
            string,
          ],
      ),
      `Agents (${this.agents.length})`,
    );
    this.write('Use /agent <name> to start a conversation with one.');
  }

  private async selectAgent(name: string): Promise<void> {
    if (!name) {
      if (this.activeAgent) {
        this.activeAgent = null;
        this.write('Left the agent chat. Prompts generate notes again.');
      } else {
        await this.showAgents();
      }
      return;
    }
    try {
      const result = await this.bridge.chatSelect(name);
      this.activeAgent = result.agent;
      this.write(
        `Talking to ${result.agent}. Send /agent with no name to go back to note generation.`,
      );
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    }
  }

  private async explainRoute(topic: string): Promise<void> {
    try {
      const result = await this.bridge.route(topic);
      this.write(`Routing "${topic}"`);
      this.write(`  routed to  ${result.routedTo ?? 'ambiguous — escalates to you'}`);
      for (const line of result.scores) this.write(`  ${line}`);
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    }
  }

  private async showVault(): Promise<void> {
    try {
      this.vault = await this.bridge.vaultInfo();
    } catch (err) {
      this.write(`error: ${describe(err)}`);
      return;
    }
    const v = this.vault;
    const rows: Array<[string, string]> = [['status', v.summary]];
    if (v.found) {
      rows.push(['root', v.root ?? '']);
      rows.push(['resolved by', v.source]);
      rows.push(['cwd', v.cwd]);
      if (v.domains) rows.push(['domains', v.domains.join(', ')]);
      if (v.agentCount !== undefined) {
        rows.push(['contents', `${v.agentCount} agents, ${v.skillCount ?? 0} skills`]);
      }
      if (v.hintDomain) {
        rows.push([
          'location hint',
          `${v.hintDomain}${v.hintCategory ? ` / ${v.hintCategory}` : ''}`,
        ]);
      }
    }
    this.writeRows(rows, 'Vault');
  }

  private async showTools(): Promise<void> {
    try {
      const tools = await this.bridge.tools();
      if (tools.length === 0) {
        this.write('No tools registered.');
        return;
      }
      this.writeRows(
        tools.map((t) => [t.name, `[${t.source}/${t.access}] ${t.description}`] as [string, string]),
        `Tools (${tools.length})`,
      );
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    }
  }

  private async showMcp(): Promise<void> {
    try {
      const servers = await this.bridge.mcp();
      if (servers.length === 0) {
        this.write('No MCP servers configured.');
        return;
      }
      this.writeRows(
        servers.map(
          (srv) =>
            [
              srv.name,
              `${srv.enabled ? 'enabled' : 'disabled'} [${srv.type}] ${srv.description}`,
            ] as [string, string],
        ),
        `MCP servers (${servers.length})`,
      );
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    }
  }

  private async initVault(path: string): Promise<void> {
    try {
      const result = await this.bridge.vaultInit(path || undefined);
      this.write(`Vault scaffolded at ${result.root}`);
      this.vault = await this.bridge.vaultInfo();
      await this.loadAgents();
    } catch (err) {
      this.write(`error: ${describe(err)}`);
    }
  }

  private async quit(): Promise<void> {
    await this.stop();
    process.exit(0);
  }

  /* -- onboarding --------------------------------------------------------- */

  private async onOnboardingKey(key: Key): Promise<void> {
    const state = this.onboarding;

    if (key.name === 'ctrl+c' || key.name === 'ctrl+d') {
      await this.quit();
      return;
    }

    if (state.stage === 'validating') return;

    if (state.stage === 'local') {
      if (key.name === 'escape' || key.name === 'enter') {
        state.stage = 'choice';
        this.requestRender();
      }
      return;
    }

    if (state.stage === 'choice') {
      if (key.name === 'up') state.choice = Math.max(0, state.choice - 1);
      else if (key.name === 'down') state.choice = Math.min(1, state.choice + 1);
      else if (key.name === 'enter') {
        if (state.choice === 0) {
          state.stage = 'key';
          state.error = '';
        } else {
          try {
            const stub = await this.bridge.localStub();
            state.message = stub.message;
          } catch {
            state.message = 'Local model support is planned for a future release.';
          }
          state.stage = 'local';
        }
      }
      this.requestRender();
      return;
    }

    // stage === 'key'
    if (key.name === 'escape') {
      state.stage = 'choice';
      state.keyBuffer = '';
      state.error = '';
      this.requestRender();
      return;
    }
    if (key.name === 'backspace') {
      state.keyBuffer = state.keyBuffer.slice(0, -1);
      this.requestRender();
      return;
    }
    if (key.name === 'paste') {
      state.keyBuffer += key.text.trim();
      this.requestRender();
      return;
    }
    if (key.name === 'enter') {
      await this.submitKey();
      return;
    }
    if (key.text && !key.ctrl && !key.alt) {
      state.keyBuffer += key.text;
      this.requestRender();
    }
  }

  private async submitKey(): Promise<void> {
    const state = this.onboarding;
    const value = state.keyBuffer.trim();
    if (!value) {
      state.error = 'Enter a key, or press Escape to go back.';
      this.requestRender();
      return;
    }
    state.stage = 'validating';
    state.error = '';
    this.requestRender();

    try {
      const result = await this.bridge.authValidate(value);
      if (!result.ok) {
        state.stage = 'key';
        state.keyBuffer = '';
        state.error = result.detail;
        this.requestRender();
        return;
      }
      const stored = await this.bridge.authPersist(value);
      this.auth = await this.bridge.authStatus();
      this.model = this.auth.model;
      this.mode = 'chat';
      state.stage = 'done';
      state.keyBuffer = '';
      this.write(`${result.detail} Key stored in your ${stored.store}.`);
      if (this.vault?.found) await this.loadAgents();
    } catch (err) {
      state.stage = 'key';
      state.keyBuffer = '';
      state.error = describe(err);
      this.requestRender();
    }
  }

  /** The onboarding screen, as plain rows. */
  private onboardingLines(): string[] {
    const state = this.onboarding;
    const lines: string[] = ['Avicenna needs a provider before it can write.', ''];

    switch (state.stage) {
      case 'choice': {
        const options = ['Use a Mistral API key', 'Use a local model'];
        options.forEach((option, index) => {
          lines.push(`  ${index === state.choice ? '>' : ' '} ${option}`);
        });
        lines.push('', '  up/down choose   enter confirm   ctrl+c quit');
        break;
      }
      case 'key':
        lines.push('  Paste a Mistral API key and press Enter.');
        lines.push(`  ${state.keyBuffer ? '*'.repeat(Math.min(state.keyBuffer.length, 48)) : ''}`);
        if (state.error) lines.push('', `  ${state.error}`);
        lines.push('', '  enter validate   esc back   ctrl+c quit');
        break;
      case 'validating':
        lines.push('  Validating the key with one live request...');
        break;
      case 'local':
        lines.push(`  ${state.message}`);
        lines.push('', '  esc back   ctrl+c quit');
        break;
      case 'done':
        break;
    }
    return lines;
  }

  /* -- events ------------------------------------------------------------- */

  private onEvent(frame: EventFrame): void {
    // Events from a run that is no longer the active one are dropped. Without
    // this, tail events from a cancelled run kept mutating the stats of the run
    // that replaced it, and a late RunComplete/RunFailed cleared the new run's
    // busy state — the interface reporting one run's ending as another's.
    if (frame.runId && this.busy?.kind === 'run' && this.busy.runId &&
        frame.runId !== this.busy.runId) {
      return;
    }
    const d = frame.data;
    const str = (k: string) => String(d[k] ?? '');
    const num = (k: string) => Number(d[k] ?? 0);
    const list = (k: string): string[] => (Array.isArray(d[k]) ? (d[k] as string[]) : []);

    switch (frame.event) {
      case 'RunStarted':
        this.write(
          `run ${frame.runId}: ${str('topic')} (${str('provider')} ${str('model') || this.model})`,
        );
        return;

      case 'PreflightDeclared': {
        const headings = list('headings');
        this.stats.sectionsTotal = headings.length;
        this.write(
          `preflight: ${str('domain')}/${str('template')} — ${headings.length} headings, ` +
            `target ${num('target_words')} words, slug ${str('slug')}`,
        );
        headings.forEach((heading, index) => this.write(`  ${index + 1}. ${heading}`));
        return;
      }

      case 'ManifestWritten':
        this.write(`manifest ${str('slug')} — ${num('expected_count')} chunks expected`);
        return;

      case 'StageEntered':
        this.write(`stage ${str('stage')}`);
        return;

      case 'StageCompleted':
        this.write(`stage ${str('stage')} done (${num('elapsed').toFixed(1)}s)`);
        return;

      case 'SectionStarted':
        this.write(`  section ${num('index')} started — ${str('heading')}`);
        return;

      case 'SectionCompleted':
        this.stats.sectionsDone += 1;
        this.stats.words += num('words');
        this.write(
          `  section ${num('index')} done — ${str('heading')} ` +
            `(${num('words')}w, ${num('elapsed').toFixed(1)}s)`,
        );
        return;

      case 'SectionFailed':
        this.write(
          `  section ${num('index')} failed — ${str('error')}${d.will_retry ? ' (retrying)' : ''}`,
        );
        return;

      case 'ToolInvoked':
        this.stats.tools += 1;
        this.write(`  tool ${str('name')} [${str('source')}] ${formatArgs(d.args)}`);
        return;

      case 'ToolReturned':
        this.write(
          `  tool ${str('name')} -> ${str('contract') || (d.ok === false ? 'failed' : 'ok')} ` +
            `(${num('elapsed').toFixed(1)}s)`,
        );
        return;

      case 'WordCountChecked':
        this.write(
          d.verdict === 'fail'
            ? `word count ${num('actual')} is below the ${num('minimum')} minimum`
            : `word count ${num('actual')} — passes`,
        );
        return;

      case 'TagsProposed':
        this.write(`tags proposed: ${list('tags').join(', ')}`);
        return;

      case 'TagsValidated':
        this.write(
          d.verdict === 'fail'
            ? `tag validation failed: ${str('message')}`
            : `tags accepted: ${list('accepted').join(', ')}`,
        );
        return;

      case 'LinkCandidatesFound':
        this.write(`${num('count')} link candidates found`);
        return;

      case 'MocUpdated':
        this.write(`MOC updated: ${str('result')}`);
        return;

      case 'NoteWritten':
        this.write(`note written to ${str('path')} (${num('words')} words)`);
        return;

      case 'RunComplete':
        this.busy = null;
        this.write(
          `run complete: ${str('summary')} — ${num('total_words')} words in ` +
            `${num('elapsed').toFixed(1)}s`,
        );
        return;

      case 'RunFailed':
        this.busy = null;
        this.write(`run failed${d.stage ? ` in ${str('stage')}` : ''}: ${str('error')}`);
        return;

      case 'LogMessage':
        this.write(`${str('level')}: ${str('text')}`);
        return;

      default: {
        // Exhaustiveness check. Adding a dataclass to events.py and a name to
        // EventName without adding a case here used to compile cleanly and drop
        // the event silently at runtime; now the compiler names the omission.
        const unhandled: never = frame.event;
        this.write(`unhandled event: ${String(unhandled)}`);
        return;
      }
    }
  }

  /* -- layout ------------------------------------------------------------- */

  private bodyWidth(): number {
    return Math.max(24, this.screen.size.cols - 2);
  }

  private transcriptLines(): string[] {
    const cols = this.bodyWidth();
    if (this.cache && this.cache.cols === cols && this.cache.version === this.version) {
      return this.cache.lines;
    }
    const lines: string[] = [];
    for (const entry of this.transcript) {
      for (const line of wrap(entry, cols)) lines.push(line);
    }
    this.cache = { cols, version: this.version, lines };
    return lines;
  }

  private inputRows(): number {
    return this.composer.layout(this.bodyWidth() - PROMPT.length).lines.length;
  }

  private viewportRows(): number {
    const { rows } = this.screen.size;
    const completionRows = Math.min(this.completions().length, 6);
    return Math.max(3, rows - this.inputRows() - 1 /* status */ - completionRows);
  }

  private render(): void {
    const { rows, cols } = this.screen.size;
    const lines: string[] = [];

    if (this.mode === 'onboarding') {
      for (const line of this.onboardingLines()) lines.push(` ${line}`);
      while (lines.length < rows - 1) lines.push('');
      lines.push(` ${truncate(this.status(), cols - 2)}`);
      this.screen.render({ lines });
      return;
    }

    // Transcript, clipped to the viewport and honouring the scroll offset.
    const all = this.transcriptLines();
    const view = this.viewportRows();
    const end = Math.max(0, all.length - this.scroll);
    const start = Math.max(0, end - view);
    const visible = all.slice(start, end);
    for (let i = visible.length; i < view; i++) lines.push('');
    for (const line of visible) lines.push(` ${line}`);

    // Command completion, as a plain list directly above the input.
    const completions = this.completions();
    if (completions.length > 0) {
      this.completionIndex = Math.min(this.completionIndex, completions.length - 1);
      completions.slice(0, 6).forEach((cmd, index) => {
        const marker = index === this.completionIndex ? '>' : ' ';
        const call = `/${cmd.name} ${cmd.args ?? ''}`.trim();
        lines.push(truncate(` ${marker} ${call.padEnd(14)}  ${cmd.summary}`, cols));
      });
    }

    const layout = this.composer.layout(this.bodyWidth() - PROMPT.length);
    const inputTop = lines.length;
    layout.lines.forEach((line, index) => {
      lines.push(` ${index === 0 ? PROMPT : CONTINUATION}${line}`);
    });
    lines.push(` ${truncate(this.status(), cols - 2)}`);

    this.screen.render({
      lines,
      cursor: {
        // +1 twice: rows and columns are 1-indexed, and every row is written
        // with a single leading space.
        row: inputTop + layout.cursorRow + 1,
        col: 1 + 1 + PROMPT.length + layout.cursorCol,
      },
    });
  }

  private status(): string {
    if (this.notice) return this.notice;

    if (this.mode === 'onboarding') {
      return this.onboarding.stage === 'validating' ? 'validating...' : '';
    }

    if (this.busy) {
      const elapsed = ((Date.now() - this.busy.startedAt) / 1000).toFixed(0);
      const bits = [this.busy.label, `${elapsed}s`];
      if (this.stats.sectionsTotal > 0) {
        bits.push(`${this.stats.sectionsDone}/${this.stats.sectionsTotal} sections`);
      }
      if (this.stats.words > 0) bits.push(`${this.stats.words}w`);
      if (this.stats.tools > 0) bits.push(`${this.stats.tools} tools`);
      bits.push('esc cancels');
      return bits.join('   ');
    }

    const hints = this.completions().length
      ? 'tab accept   enter run   esc dismiss'
      : 'enter send   alt+enter newline   / commands   pgup scroll   ctrl+c quit';
    const scrolled = this.scroll > 0 ? `scrolled ${this.scroll} lines` : '';
    if (!scrolled) return hints;
    const gap = Math.max(1, this.screen.size.cols - width(hints) - width(scrolled) - 2);
    return `${hints}${' '.repeat(gap)}${scrolled}`;
  }
}

/* -- helpers -------------------------------------------------------------- */

function describe(err: unknown): string {
  if (err instanceof BridgeError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

/** Render tool arguments compactly enough to sit on one line. */
function formatArgs(args: unknown): string {
  if (!args || typeof args !== 'object') return '';
  const entries = Object.entries(args as Record<string, unknown>);
  if (entries.length === 0) return '';
  return entries
    .map(([key, value]) => {
      const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
      return `${key}=${truncate(text.replace(/\s+/g, ' '), 40)}`;
    })
    .join(', ');
}
