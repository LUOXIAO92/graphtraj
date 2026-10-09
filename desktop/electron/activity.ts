import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';

export type Agent = {
  alias: string; parent?: string | null; runtime?: string; model?: string | null;
  historical: boolean; state: string; last_outcome?: string; reason?: string;
};
export type ActivityEvent = {
  id: string; kind: string; time: string | number | null;
  source: { runtime: string; trace?: string; offset: number }; role?: string; text?: string;
  name?: string; phase?: string; call_id?: string; arguments?: unknown;
  result?: unknown; error?: unknown; details?: unknown; model?: string;
  usage?: { tokens: Record<string, number>; provider_usage: unknown; identity?: string;
    phase: string; attributable: boolean; [key: string]: unknown };
};
export type Activity = {
  ticket_id: string; scope?: 'self' | 'human'; agents: Agent[]; updated_at: string; events?: ActivityEvent[];
  cursor?: string | null; has_more?: boolean; waiting_for_record?: boolean;
  availability?: string; reason?: string;
};
export type ActivityRequest = { ticket_id: string; alias?: string; cursor?: string };

/** One optional observer process retains only volatile byte cursors, never Traces. */
export class ActivityReader {
  private processes = new Map<string, {
    child: ChildProcessWithoutNullStreams;
    queue: { resolve: (value: Activity) => void; reject: (error: Error) => void }[];
  }>();
  private executable: string;
  constructor(executable = process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool') { this.executable = executable; }

  read(root: string, request: ActivityRequest): Promise<Activity> {
    let process = this.processes.get(root);
    if (!process) {
      const child = spawn(this.executable, ['--desktop-observer', '--allowed-features', 'desktop_activity'], {
        cwd: root, windowsHide: true, stdio: 'pipe',
      });
      process = { child, queue: [] };
      this.processes.set(root, process);
      const connection = process;
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
    const connection = process;
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
