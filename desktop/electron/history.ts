import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type { ActivityEvent } from './activity.ts';
import { collect, type Call } from './usage.ts';

/** Store only normalized usage facts; serial writes keep monitor and backfill idempotent. */
export class UsageHistory {
  private directory: string;
  private writes: Promise<unknown> = Promise.resolve();

  constructor(directory: string) { this.directory = directory; }

  /** A project ID comes from the controlled index, never a renderer-supplied path. */
  private file(project: string): string {
    return path.join(this.directory, createHash('sha256').update(project).digest('hex') + '.json');
  }

  private async load(project: string): Promise<Map<string, Call>> {
    let text: string;
    try { text = await readFile(this.file(project), 'utf8'); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return new Map();
      throw error;
    }
    const saved = JSON.parse(text);
    if (saved.version !== 1 || !Array.isArray(saved.calls) || saved.calls.some((call: Call) =>
      !call || call.project !== project || typeof call.key !== 'string' || !call.tokens)) {
      throw new Error('Usage history is unreadable; the saved file was left unchanged.');
    }
    return new Map(saved.calls.map((call: Call) => [call.key, call]));
  }

  /** Atomic snapshots retain reported fields and counter observations, without messages or Traces. */
  receive(project: string, events: ActivityEvent[] = []): Promise<Call[]> {
    const next = this.writes.then(async () => {
      const calls = await this.load(project);
      const before = JSON.stringify([...calls.values()]);
      collect(calls, project, events);
      const after = JSON.stringify([...calls.values()]);
      if (after !== before) {
        // ponytail: rewrite one project's normalized facts; use a database if history size warrants it.
        await mkdir(this.directory, { recursive: true, mode: 0o700 });
        const file = this.file(project);
        await writeFile(file + '.tmp', `{"version":1,"calls":${after}}\n`, { mode: 0o600 });
        await rename(file + '.tmp', file);
      }
      return [...calls.values()];
    });
    this.writes = next.catch(() => undefined);
    return next;
  }
}
