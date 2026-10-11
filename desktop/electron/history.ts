import { createHash } from 'node:crypto';
import { appendFile, mkdir, readFile, truncate } from 'node:fs/promises';
import path from 'node:path';
import type { ActivityEvent } from './activity.ts';
import { collect, type Call } from './usage.ts';

type State = { calls: Map<string, Call>; cursors: Record<string, string | null> };

/** Retain original snapshots and append atomic page facts/checkpoints in the same transaction. */
export class UsageHistory {
  private directory: string;
  private states = new Map<string, Promise<State>>();
  private writes = new Map<string, Promise<unknown>>();

  constructor(directory: string) { this.directory = directory; }

  private file(project: string): string {
    return path.join(this.directory, createHash('sha256').update(project).digest('hex'));
  }

  /** Load once per project. Version-one facts stay untouched as correction provenance. */
  private load(project: string): Promise<State> {
    let cached = this.states.get(project);
    if (cached) return cached;
    cached = (async () => {
      const state: State = { calls: new Map(), cursors: {} };
      const read = async (file: string) => {
        try { return await readFile(file, 'utf8'); }
        catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return ''; throw error; }
      };
      const apply = (calls: Call[]) => {
        if (!Array.isArray(calls) || calls.some(call => !call || call.project !== project ||
            typeof call.key !== 'string' || !call.tokens)) throw new Error('Usage history is unreadable; saved facts were preserved.');
        for (const call of calls) state.calls.set(call.key, call);
      };
      const legacy = await read(this.file(project) + '.json');
      if (legacy) {
        const saved = JSON.parse(legacy);
        if (saved.version !== 1) throw new Error('Unknown usage history version; saved facts were preserved.');
        apply(saved.calls);
      }
      const file = this.file(project) + '.jsonl';
      const journal = await read(file);
      const complete = journal.lastIndexOf('\n') + 1;
      for (const line of journal.slice(0, complete).split('\n').filter(Boolean)) {
        const saved = JSON.parse(line);
        if (saved.version !== 2) throw new Error('Unknown usage history version; saved facts were preserved.');
        apply(saved.calls);
        Object.assign(state.cursors, saved.cursors);
      }
      if (complete < journal.length) {
        // Preserve interrupted bytes before removing the uncommitted page tail.
        await appendFile(file + '.interrupted', journal.slice(complete), { mode: 0o600 });
        await truncate(file, Buffer.byteLength(journal.slice(0, complete)));
      }
      return state;
    })();
    this.states.set(project, cached);
    cached.catch(() => this.states.delete(project));
    return cached;
  }

  async cursors(project: string): Promise<Record<string, string | null>> {
    return { ...(await this.load(project)).cursors };
  }

  /** Reads do not wait for native refreshes; writes serialize only within their project. */
  async receive(project: string, events: ActivityEvent[] = [], cursors: Record<string, string | null> = {}): Promise<Call[]> {
    if (!events.length && !Object.keys(cursors).length) return [...(await this.load(project)).calls.values()];
    const next = (this.writes.get(project) ?? Promise.resolve()).then(async () => {
      const state = await this.load(project);
      const working = new Map(state.calls);
      const changed = collect(working, project, events);
      const progress = Object.fromEntries(Object.entries(cursors).filter(([key, value]) => state.cursors[key] !== value));
      if (changed.length || Object.keys(progress).length) {
        await mkdir(this.directory, { recursive: true, mode: 0o700 });
        await appendFile(this.file(project) + '.jsonl', JSON.stringify({ version: 2, calls: changed, cursors: progress }) + '\n', { mode: 0o600, flush: true });
        state.calls = working;
        Object.assign(state.cursors, progress);
      }
      return [...state.calls.values()];
    });
    this.writes.set(project, next.catch(() => { this.states.delete(project); }));
    return next;
  }
}
