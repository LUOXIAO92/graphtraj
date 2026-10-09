/** Explicitly loaded Pi extension for one authorized, directly owned usage check. */
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Type } from '@earendil-works/pi-ai';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

export default function (pi: ExtensionAPI) {
  let child: ChildProcess | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let output = '';
  let outcome: { code: number | null; signal: string | null } | undefined;
  let used = false;

  /** Stop only this extension's child, giving its Electron cleanup time to run. */
  async function stop(): Promise<void> {
    clearTimeout(timer);
    if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
    const owned = child;
    await new Promise<void>(resolve => {
      const force = setTimeout(() => owned.kill('SIGKILL'), 2500);
      owned.once('exit', () => { clearTimeout(force); resolve(); });
      owned.kill('SIGTERM');
    });
  }
  pi.on('session_shutdown', stop);
  pi.registerTool({
    name: 'usage_dashboard_check', label: 'Owned usage dashboard check',
    description: 'Start one explicitly authorized native Dashboard check, inspect its result, or stop only its owned child. Requires current project, Ticket, absolute deadline and executable paths. Does not authorize resources, sandbox exceptions or extra time.',
    parameters: Type.Object({
      action: Type.Union([Type.Literal('start'), Type.Literal('status'), Type.Literal('stop')]),
      project: Type.Optional(Type.String()), ticket: Type.Optional(Type.String()),
      deadline: Type.Optional(Type.String({ description: 'Approved absolute ISO execution deadline with timezone; no time extension.' })),
      tool: Type.Optional(Type.String({ description: 'Current approved absolute graphtraj-tool path.' })),
      electron: Type.Optional(Type.String({ description: 'Approved absolute Electron executable path.' })),
      artifacts: Type.Optional(Type.String({ description: 'Approved absolute artifact/socket directory.' })),
      noSandbox: Type.Optional(Type.Boolean({ default: false, description: 'True only after THIS263 exact native/host execution approval; this argument does not grant approval.' })),
      node: Type.Optional(Type.String({ description: 'Absolute Node executable; defaults to this Pi process executable.' })),
    }),
    executionMode: 'sequential',
    async execute(_id, args) {
      if (args.action === 'stop') await stop();
      if (args.action === 'start') {
        if (!process.env.GRAPHTRAJ_CLI_CONNECTION) throw new Error('Requires an existing native GraphTraj connection.');
        if (used) throw new Error('This extension already used its one authorized launch.');
        for (const value of [args.project, args.tool, args.electron, args.artifacts, args.node || process.execPath]) {
          if (!value || !path.isAbsolute(value)) throw new Error('Supply the approved absolute resource paths.');
        }
        if (!args.ticket) throw new Error('Supply the current Ticket.');
        const deadline = args.deadline && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(args.deadline) ? Date.parse(args.deadline) : NaN;
        if (!Number.isFinite(deadline) || deadline <= Date.now() + 10000) throw new Error('Supply the approved future absolute deadline.');
        used = true;
        const script = fileURLToPath(new URL('./usage-live.test.mjs', import.meta.url));
        child = spawn(args.node || process.execPath, ['--preserve-symlinks', '--preserve-symlinks-main', '--test', script], {
          cwd: args.project, stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, GRAPHTRAJ_TOOL: args.tool,
            GRAPHTRAJ_LIVE_NO_SANDBOX: args.noSandbox ? '1' : '0',
            GRAPHTRAJ_LIVE_PROJECT: args.project, GRAPHTRAJ_LIVE_TICKET: args.ticket,
            GRAPHTRAJ_LIVE_DEADLINE: args.deadline, GRAPHTRAJ_ELECTRON_EXECUTABLE: args.electron,
            GRAPHTRAJ_LIVE_ARTIFACTS: args.artifacts, MAC_CHROMIUM_TMPDIR: args.artifacts },
        });
        // No detached process, shell, identity override or alternate Runtime.
        const append = (chunk: Buffer) => { output = (output + chunk.toString()).slice(-65536); };
        child.stdout?.on('data', append); child.stderr?.on('data', append);
        child.once('error', error => { output += `\nChild launch failed: ${error.message}`; clearTimeout(timer); });
        child.once('exit', (code, signal) => { outcome = { code, signal }; clearTimeout(timer); });
        timer = setTimeout(() => { void stop(); }, deadline - Date.now() - 3000);
      }
      const result = { started: used, running: Boolean(child?.pid && child.exitCode === null && child.signalCode === null),
        pid: child?.pid, outcome, output };
      return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], details: result };
    },
  });
}
