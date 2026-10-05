import { ActivityReader, type ActivityRequest, type Activity } from './activity.ts';
import { execFile, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { access, mkdir, readFile, realpath, rename, stat, writeFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import type { Graph, Observation, Preferences, Project } from './types';

/** Read a graph through the public, feature-restricted native bridge. */
export class GraphReader {
  private children = new Set<ChildProcess>();
  private closed = false;
  private executable: string;

  constructor(executable = process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool') {
    this.executable = executable;
  }

  async read(root: string): Promise<Graph> {
    if (this.closed) throw new Error('Desktop observer is closed.');
    return new Promise((resolve, reject) => {
      const child = execFile(this.executable, ['--allowed-features', 'ticket_graph'], {
        cwd: root, timeout: 15000, maxBuffer: 16 * 1024 * 1024, windowsHide: true,
      }, (error, stdout) => {
        this.children.delete(child);
        if (error) {
          reject(new Error(`Native graph unavailable: ${error.message}`));
          return;
        }
        try {
          const reply = JSON.parse(stdout);
          if (reply.failed) throw new Error(reply.error || reply.result?.error || 'Native query failed.');
          if (!reply.result || !Array.isArray(reply.result.tickets)) {
            throw new Error('Native query returned no task graph.');
          }
          if (reply.result.tickets.some((ticket: { title?: unknown }) => typeof ticket.title !== 'string')) {
            throw new Error('Install the matching Python GraphTraj version: ticket titles are missing.');
          }
          resolve(reply.result);
        } catch (error) { reject(error); }
      });
      this.children.add(child);
      child.stdin?.on('error', () => { /* execFile reports a failed process. */ });
      child.stdin?.end(JSON.stringify({ action: 'execute', feature: 'ticket_graph', arguments: {} }) + '\n');
    });
  }

  close(): void {
    this.closed = true;
    // Only these short-lived read processes belong to the desktop.
    for (const child of this.children) child.kill();
    this.children.clear();
  }
}

/** Keep only desktop preferences in userData; never write inside a project. */
export class Projects {
  private preferences: Preferences = { projects: [], selected: null };
  private file: string;
  private reader: GraphReader;
  private activityReader = new ActivityReader();

  constructor(file: string, reader: GraphReader) {
    this.file = file;
    this.reader = reader;
  }

  async load(): Promise<void> {
    let text: string;
    try { text = await readFile(this.file, 'utf8'); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
      throw error;
    }
    const value = JSON.parse(text);
    if (!Array.isArray(value.projects) || !value.projects.every((p: Project) =>
      p && typeof p.id === 'string' && typeof p.root === 'string' && path.isAbsolute(p.root)
    ) || !(value.selected === null || value.projects.some((p: Project) => p.id === value.selected))) {
      throw new Error('Desktop project preferences are invalid; the file was left unchanged.');
    }
    this.preferences = value;
  }

  list(): Preferences { return structuredClone(this.preferences); }

  private project(id: unknown): Project {
    const project = this.preferences.projects.find(p => p.id === id);
    if (typeof id !== 'string' || !project) throw new Error('Choose an added project.');
    return project;
  }

  private async save(value: Preferences): Promise<Preferences> {
    await mkdir(path.dirname(this.file), { recursive: true });
    await writeFile(this.file + '.tmp', JSON.stringify(value, null, 2), { mode: 0o600 });
    await rename(this.file + '.tmp', this.file);
    this.preferences = value;
    return this.list();
  }

  async add(folder: string): Promise<Preferences> {
    const root = await realpath(folder);
    if (!(await stat(root)).isDirectory()) throw new Error('Choose a project directory.');
    await access(root, constants.R_OK | constants.X_OK);
    // Native configuration validation rejects uninitialized roots without setup.
    await this.reader.read(root);
    const existing = this.preferences.projects.find(p => p.root === root);
    if (existing) return this.select(existing.id);
    const project = { id: randomUUID(), root };
    return this.save({ projects: [...this.preferences.projects, project], selected: project.id });
  }

  async select(id: unknown): Promise<Preferences> {
    const project = this.project(id);
    return this.save({ ...this.preferences, selected: project.id });
  }

  async remove(id: unknown): Promise<Preferences> {
    const project = this.project(id);
    this.activityReader.close(project.root);
    const projects = this.preferences.projects.filter(p => p.id !== project.id);
    return this.save({ projects, selected: this.preferences.selected === id
      ? projects[0]?.id ?? null : this.preferences.selected });
  }

  close(): void { this.activityReader.close(); }

  async activity(value: unknown): Promise<Activity> {
    if (!value || typeof value !== 'object') throw new Error('Choose a Ticket.');
    const { projectId, ticket_id, alias, cursor } = value as Record<string, unknown>;
    const project = this.project(projectId);
    if (typeof ticket_id !== 'string' || (alias !== undefined && typeof alias !== 'string') ||
        (cursor !== undefined && typeof cursor !== 'string')) throw new Error('Invalid activity selection.');
    if (await realpath(project.root) !== project.root) throw new Error('Project directory changed. Add it again.');
    const request: ActivityRequest = { ticket_id, ...(alias === undefined ? {} : { alias }),
      ...(cursor === undefined ? {} : { cursor }) };
    return this.activityReader.read(project.root, request);
  }

  async graph(id: unknown): Promise<Observation> {
    const project = this.project(id);
    if (await realpath(project.root) !== project.root) {
      throw new Error('Project directory now resolves elsewhere. Remove and add it again.');
    }
    const graph = await this.reader.read(project.root);
    return { projectId: project.id, graph, updatedAt: new Date().toISOString() };
  }
}
