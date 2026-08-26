/**
 * Slash commands and their completion palette.
 *
 * The catalogue is data so the palette, the help screen and the dispatcher
 * cannot disagree about what exists — the old frontend kept three separate
 * lists and they drifted.
 */

export interface CommandSpec {
  name: string;
  args?: string;
  summary: string;
  /** Hidden from the palette but still dispatchable. */
  hidden?: boolean;
}

export const COMMANDS: readonly CommandSpec[] = [
  { name: 'help', summary: 'Show keys, commands and what Avicenna does' },
  { name: 'note', args: '<topic>', summary: 'Generate a full note through the pipeline' },
  { name: 'dry', args: '<topic>', summary: 'Route and pre-flight only — no writing' },
  { name: 'resume', summary: 'Resume the last interrupted run' },
  { name: 'cancel', summary: 'Cancel the run in flight' },
  { name: 'agent', args: '<name>', summary: 'Chat with a vault agent' },
  { name: 'agents', summary: 'List the agents this vault defines' },
  { name: 'route', args: '<topic>', summary: 'Explain which agent a topic routes to' },
  { name: 'vault', summary: 'Show the bound vault and where you are standing' },
  { name: 'tools', summary: 'List every registered tool and its source' },
  { name: 'mcp', summary: 'List configured MCP servers' },
  { name: 'init', args: '[path]', summary: 'Scaffold a new vault' },
  { name: 'login', summary: 'Set or replace the provider API key' },
  { name: 'clear', summary: 'Clear the transcript' },
  { name: 'diagnostics', summary: 'Show backend stderr for the current session' },
  { name: 'quit', summary: 'Exit Avicenna' },
  { name: 'exit', summary: 'Exit Avicenna', hidden: true },
];

export interface ParsedCommand {
  name: string;
  args: string;
  argv: string[];
}

export function isCommand(text: string): boolean {
  return text.startsWith('/');
}

export function parse(text: string): ParsedCommand {
  const body = text.slice(1);
  const space = body.indexOf(' ');
  const name = (space === -1 ? body : body.slice(0, space)).toLowerCase();
  const args = space === -1 ? '' : body.slice(space + 1).trim();
  return { name, args, argv: args ? args.split(/\s+/) : [] };
}

/** Commands whose name starts with the typed prefix, best match first. */
export function complete(prefix: string): CommandSpec[] {
  const term = prefix.replace(/^\//, '').toLowerCase();
  const visible = COMMANDS.filter((cmd) => !cmd.hidden);
  if (term === '') return [...visible];
  const starts = visible.filter((cmd) => cmd.name.startsWith(term));
  const contains = visible.filter(
    (cmd) => !cmd.name.startsWith(term) && cmd.name.includes(term),
  );
  return [...starts, ...contains];
}

export function find(name: string): CommandSpec | undefined {
  return COMMANDS.find((cmd) => cmd.name === name);
}
