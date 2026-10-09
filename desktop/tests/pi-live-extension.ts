/** Temporary Ticket262 acceptance resource; load explicitly, never auto-discover. */
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Type } from '@earendil-works/pi-ai';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const node = '/opt/homebrew/Cellar/node/26.5.0/bin/node';

export default function (pi: ExtensionAPI) {
  if (process.cwd() !== root || process.env.ASB_SANDBOX !== '1'
      || process.env.ASB_PROFILE !== 'custom' || !process.env.GRAPHTRAJ_CLI_CONNECTION) return;
  let child: ChildProcess | undefined;
  let mode: 'probe' | 'gui' | undefined;
  let usedGUI = false;
  let stage: Record<string, unknown> = {};
  let outcome: Record<string, unknown> = {};
  let timer: ReturnType<typeof setTimeout> | undefined;

  const close = async () => {
    if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
    const owned = child;
    await new Promise<void>(resolve => {
      owned.once('exit', () => resolve());
      // The tracked live test handles SIGTERM by closing its owned app handle.
      owned.kill('SIGTERM');
    });
  };
  pi.on('session_shutdown', close);
  pi.registerTool({
    name: 'ticket262_live', label: 'Ticket262 owned desktop test',
    description: 'Temporary one-launch fixture; probe/start require an explicitly authorized deadline. probe starts a non-GUI Pi-owned child; status returns actual stage; stop closes only that child. start launches the existing tracked live test once. Use ordinary bash tools for genuine markers.',
    parameters: Type.Object({ action: Type.Union([
      Type.Literal('probe'), Type.Literal('start'), Type.Literal('status'), Type.Literal('stop'),
    ]), deadline: Type.Optional(Type.String({ description: 'Required for probe/start: explicitly authorized ISO deadline with timezone; never extends Runner limits.' })) }),
    executionMode: 'sequential',
    async execute(_id, { action, deadline: deadlineInput }) {
      if (action === 'stop') await close();
      if (action === 'start' || action === 'probe') {
        const deadline = typeof deadlineInput === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(deadlineInput)
          ? Date.parse(deadlineInput) : NaN;
        if (!Number.isFinite(deadline)) throw new Error('Provide the explicitly authorized deadline with timezone.');
        if (child && child.exitCode === null && child.signalCode === null) throw new Error('Owned child is still running; stop it first.');
        if (Date.now() >= deadline - 5 * 60_000) throw new Error('Delivery reserve reached; no new child allowed.');
        if (action === 'start' && usedGUI) throw new Error('This extension permits only one GUI launch.');
        if (process.env.ASB_SANDBOX !== '1' || process.env.ASB_PROFILE !== 'custom') throw new Error('Expected existing managed ASB launch is absent.');
        mode = action === 'probe' ? 'probe' : 'gui';
        if (mode === 'gui') usedGUI = true;
        stage = {}; outcome = {};
        const args = mode === 'probe'
          ? ['-e', 'console.log(JSON.stringify({phase:"OWNED",pid:process.pid,ppid:process.ppid}));setInterval(()=>{},1000)']
          : ['--preserve-symlinks', '--preserve-symlinks-main', path.join(root, 'desktop/tests/activity-live.test.mjs')];
        // No shell, detached option, nohup or disown. Parent remains actual Pi.
        child = spawn(node, args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: {
          ...process.env,
          TMPDIR: '/tmp/claude/262-native-boundary', CLAUDE_TMPDIR: '/tmp/claude/262-native-boundary',
          ELECTRON_OVERRIDE_DIST_PATH: '/private/tmp/262-pi-runtime/electron',
          GRAPHTRAJ_TOOL: path.resolve(root, '../../../.venv-runner/bin/graphtraj-tool'),
          GRAPHTRAJ_LIVE_PROJECT: root, GRAPHTRAJ_LIVE_TICKET: '262', GRAPHTRAJ_LIVE_NO_SANDBOX: '1',
        } });
        const owned = child;
        let pending = '';
        owned.stdout!.on('data', chunk => {
          pending = (pending + chunk.toString()).slice(-16384);
          let newline;
          while ((newline = pending.indexOf('\n')) >= 0) {
            const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
            try {
              const value = JSON.parse(line);
              if (['OWNED', 'READY', 'PAUSED', 'CLOSED'].includes(value.phase)) stage = value;
            } catch { /* TAP is not a stage or a native message. */ }
          }
        });
        owned.stderr!.resume(); // Native errors stay in the tracked test evidence.
        owned.once('error', error => { clearTimeout(timer); outcome = { error: error.name }; });
        owned.once('exit', (code, signal) => {
          clearTimeout(timer); outcome = { ...outcome, code, signal };
        });
        // Leave one minute for owned app closure before the absolute stop.
        timer = setTimeout(() => { void close(); }, Math.max(1, deadline - Date.now() - 60_000));
      }
      const result = { mode, piPid: process.pid, childPid: child?.pid,
        running: Boolean(child?.pid && child.exitCode === null && child.signalCode === null), stage, outcome };
      return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], details: result };
    },
  });
}
