import { nativeCommand } from './native.ts';
import { spawn, type ChildProcess } from 'node:child_process';
import { createInterface } from 'node:readline';
import type { Connections, ConnectionsRequest, Settings, SettingsDraft } from './types';

/** Own the restricted native settings pipe for direct human saves. */
export class SettingsClient {
  private children = new Set<ChildProcess>();
  constructor(private executable?: string) {}

  request(root: string, draft?: SettingsDraft): Promise<Settings> {
    return this.exchange<Settings>(root, draft ? { action: 'save', ...draft } : { action: 'read' });
  }

  connections(root: string, request: ConnectionsRequest): Promise<Connections> {
    return this.exchange<Connections>(root, { ...request, scope: 'user' });
  }

  private exchange<T>(root: string, request: Record<string, unknown> & { action: string }): Promise<T> {
    return new Promise((resolve, reject) => {
      const command = nativeCommand(this.executable);
      const child = spawn(command.executable, [...command.args, '--desktop-settings'], {
        cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      });
      this.children.add(child);
      let finished = false;
      const fail = (error: unknown) => { if (!finished) { finished = true; reject(error); } child.kill(); };
      child.on('error', () => fail(new Error('Native settings unavailable. Check the matching GraphTraj installation.')));
      child.stdin.on('error', () => fail(new Error('Native settings connection closed. Reload to check the saved state.')));
      // Native diagnostics are not copied into renderer logs or error strings.
      child.stderr.resume();
      const lines = createInterface({ input: child.stdout });
      lines.on('line', line => {
        void (async () => {
          const reply = JSON.parse(line);
          if (reply.failed) {
            const guidance = reply.error_kind === 'conflict'
              ? 'Configuration conflict: Reload the current configuration and reapply your changes.'
              : reply.error_kind === 'write'
                ? 'Write failed: Check that the destination is writable, then retry Save.'
                : 'Validation failed: Correct the reported setting, then retry Save.';
            fail(new Error(`${reply.error || 'Settings were not saved.'} ${guidance}`));
          } else if (reply.result && !finished) {
            finished = true;
            resolve(reply.result);
            child.stdin.end();
          } else throw new Error('Native settings returned an invalid response.');
        })().catch(fail);
      });
      child.on('close', () => {
        this.children.delete(child);
        lines.close();
        if (!finished) fail(new Error('Native settings connection ended. Reload to check the saved state.'));
      });
      child.stdin.write(JSON.stringify(request) + '\n');
    });
  }

  close(): void {
    for (const child of this.children) child.kill();
    this.children.clear();
  }
}
