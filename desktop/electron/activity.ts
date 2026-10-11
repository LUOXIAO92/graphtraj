import { nativeCommand } from './native.ts';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomBytes } from 'node:crypto';
import { link, mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

export type Agent = {
  alias: string; kind?: 'main' | 'member'; ticket_id?: string | null; session?: string; source?: string; parent?: string | null; runtime?: string; model?: string | null;
  historical: boolean; state: string; last_outcome?: string; reason?: string;
};
export type ActivityEvent = {
  id: string; kind: string; time: string | number | null;
  source: { runtime: string; trace?: string; offset: number }; role?: string; text?: string;
  name?: string; phase?: string; call_id?: string; arguments?: unknown; tool_type?: string;
  turn_id?: string | number | null; agent?: string; session?: string;
  result?: unknown; error?: unknown; details?: unknown; model?: string;
  usage?: { tokens: Record<string, number>; provider_usage: unknown; identity?: string;
    phase: string; attributable: boolean; [key: string]: unknown };
};
export type Activity = {
  ticket_id: string | null; notices?: string[]; read_records?: number; scope?: 'self' | 'human'; agents: Agent[]; updated_at: string; events?: ActivityEvent[];
  cursor?: string | null; has_more?: boolean; waiting_for_record?: boolean;
  availability?: string; reason?: string;
};
export type ActivityRequest = { ticket_id?: string; alias?: string; cursor?: string };

/** Optional project observers read authenticated, restartable source checkpoints. */
export class ActivityReader {
  private processes = new Map<string, {
    child: ChildProcessWithoutNullStreams;
    queue: { resolve: (value: Activity) => void; reject: (error: Error) => void }[];
  }>();
  private executable: string | undefined;
  private cursorKey?: Promise<string>;
  private cursorDirectory?: string;
  constructor(executable?: string, cursorDirectory?: string) {
    this.executable = executable;
    this.cursorDirectory = cursorDirectory;
  }

  /** Authenticate restartable cursors without granting any source selection authority. */
  private async key(directory?: string): Promise<string> {
    const fresh = randomBytes(32).toString('hex');
    if (!directory) return fresh;
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const file = path.join(directory, 'native-cursor-key');
    const temporary = file + '.' + fresh.slice(0, 16) + '.tmp';
    await writeFile(temporary, fresh, { mode: 0o600, flush: true });
    try { await link(temporary, file); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; }
    finally { await unlink(temporary); }
    const saved = await readFile(file, 'utf8');
    if (!/^[a-f0-9]{64}$/.test(saved)) throw new Error('Native cursor key is unreadable; saved history was preserved.');
    return saved;
  }

  async read(root: string, request: ActivityRequest): Promise<Activity> {
    const key = await (this.cursorKey ??= this.key(this.cursorDirectory));
    let observer = this.processes.get(root);
    if (!observer) {
      const command = nativeCommand(this.executable);
      const child = spawn(command.executable, [...command.args, '--desktop-observer', '--allowed-features', 'desktop_activity'], {
        cwd: root, windowsHide: true, stdio: 'pipe',
        env: { ...process.env, GRAPHTRAJ_DESKTOP_CURSOR_KEY: key },
      });
      observer = { child, queue: [] };
      this.processes.set(root, observer);
      const connection = observer;
      const fail = () => {
        if (this.processes.get(root) === connection) this.processes.delete(root);
        for (const pending of connection.queue.splice(0)) pending.reject(new Error('Native activity observer disconnected.'));
      };
      child.on('error', fail); child.on('exit', fail); child.stdin.on('error', fail);
      // Never forward native stderr, which can contain credential-bearing diagnostics.
      child.stderr.resume();
      createInterface({ input: child.stdout }).on('line', line => {
        const pending = connection.queue.shift();
        if (!pending) return;
        try {
          const reply = JSON.parse(line);
          if (reply.failed) throw new Error('Native activity query refused or unavailable.');
          pending.resolve(reply.result);
        } catch { pending.reject(new Error('Native activity query refused or unavailable.')); }
      });
    }
    const connection = observer;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        connection.child.kill();
        reject(new Error('Native activity observer timed out. Reconnect to retry.'));
      }, 15000);
      connection.queue.push({
        resolve: value => { clearTimeout(timeout); resolve(value); },
        reject: error => { clearTimeout(timeout); reject(error); },
      });
      connection.child.stdin.write(JSON.stringify({ action: 'execute', feature: 'desktop_activity', arguments: request }) + '\n');
    });
  }

  close(root?: string): void {
    for (const [key, { child }] of this.processes) {
      if (root === undefined || key === root) { child.kill(); this.processes.delete(key); }
    }
  }
}
