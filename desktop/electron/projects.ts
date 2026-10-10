import { nativeCommand } from './native.ts';
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
  private executable: string | undefined;

  constructor(executable?: string) {
    this.executable = executable;
  }

  async read(root: string): Promise<Graph> {
    if (this.closed) throw new Error('Desktop observer is closed.');
    return new Promise((resolve, reject) => {
      const command = nativeCommand(this.executable);
      const child = execFile(command.executable, [...command.args, '--allowed-features', 'ticket_graph'], {
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

/** Persist the global project index without writing inside any project. */
export class Projects {
  private preferences: Preferences = { projects: [], selected: null };
  private file: string;
  private reader: GraphReader;
  private legacyFile?: string;
  private activityReader = new ActivityReader();

  constructor(file: string, reader: GraphReader, legacyFile?: string) {
    this.file = file;
    this.legacyFile = legacyFile;
    this.reader = reader;
  }

  private async readIndex(file: string): Promise<Preferences | null> {
    let text: string;
    try { text = await readFile(file, 'utf8'); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
    const value = JSON.parse(text);
    if (!Array.isArray(value.projects) || !value.projects.every((p: Project) =>
      p && typeof p.id === 'string' && typeof p.root === 'string' && path.isAbsolute(p.root)
    ) || !(value.selected === null || value.projects.some((p: Project) => p.id === value.selected)) ||
      (value.importedLegacy !== undefined && (!Array.isArray(value.importedLegacy) ||
        !value.importedLegacy.every((file: unknown) => typeof file === 'string')))) {
      throw new Error('Desktop project index is invalid; the file was left unchanged.');
    }
    return value;
  }

  async load(): Promise<void> {
    const saved = await this.readIndex(this.file);
    const value: Preferences = saved ?? { projects: [], selected: null };
    const legacy = this.legacyFile && !value.importedLegacy?.includes(this.legacyFile)
      ? await this.readIndex(this.legacyFile) : null;
    const projects: Project[] = [];
    let selected: string | null = null;
    const chosen = value.projects.find(project => project.id === value.selected)
      ?? legacy?.projects.find(project => project.id === legacy.selected);
    for (const item of [...value.projects, ...(legacy?.projects ?? [])]) {
      // Keep missing paths, but canonicalize accessible aliases before deduplication.
      const root = await realpath(item.root).catch(() => path.normalize(item.root));
      const existing = projects.find(project => project.root === root);
      const id = existing?.id ?? (projects.some(project => project.id === item.id) ? randomUUID() : item.id);
      if (!existing) projects.push({ id, root });
      if (item === chosen) selected = id;
    }
    this.preferences = { ...value, projects, selected };
    if (legacy && this.legacyFile) {
      this.preferences.importedLegacy = [...(value.importedLegacy ?? []), this.legacyFile];
    }
    if (saved || legacy) await this.save(this.preferences);
    await this.refreshAvailability();
  }

  /** Recheck indexed paths; a missing or uninitialized project stays in the list. */
  async refreshAvailability(): Promise<Preferences> {
    await Promise.all(this.preferences.projects.map(async project => {
      try {
        if (await realpath(project.root) !== project.root) throw new Error('Directory now resolves elsewhere. Relocate this project.');
        await this.reader.read(project.root);
        delete project.unavailable;
      } catch (error) { project.unavailable = String(error); }
    }));
    return this.list();
  }

  list(): Preferences { return structuredClone(this.preferences); }

  private project(id: unknown): Project {
    const project = this.preferences.projects.find(p => p.id === id);
    if (typeof id !== 'string' || !project) throw new Error('Choose an added project.');
    return project;
  }

  private async save(value: Preferences): Promise<Preferences> {
    await mkdir(path.dirname(this.file), { recursive: true });
    const stored = { ...value, projects: value.projects.map(({ id, root }) => ({ id, root })) };
    await writeFile(this.file + '.tmp', JSON.stringify(stored, null, 2), { mode: 0o600 });
    await rename(this.file + '.tmp', this.file);
    this.preferences = value;
    return this.list();
  }

  private async validate(folder: string): Promise<string> {
    if (typeof folder !== 'string' || !path.isAbsolute(folder)) throw new Error('Choose an absolute project directory.');
    const root = await realpath(folder);
    if (!(await stat(root)).isDirectory()) throw new Error('Choose a project directory.');
    await access(root, constants.R_OK | constants.X_OK);
    // Native configuration validation rejects uninitialized roots without setup.
    await this.reader.read(root);
    return root;
  }

  async add(folder: string): Promise<Preferences> {
    const root = await this.validate(folder);
    const existing = this.preferences.projects.find(p => p.root === root);
    if (existing) { delete existing.unavailable; return this.select(existing.id); }
    const project = { id: randomUUID(), root };
    return this.save({ ...this.preferences, projects: [...this.preferences.projects, project], selected: project.id });
  }

  /** Relocate one index entry, merging an already indexed destination. */
  async relocate(id: unknown, folder: string): Promise<Preferences> {
    const previous = this.project(id);
    const root = await this.validate(folder);
    const existing = this.preferences.projects.find(p => p.id !== id && p.root === root);
    if (existing) delete existing.unavailable;
    this.activityReader.close(previous.root);
    const projects = this.preferences.projects.flatMap(project => project.id !== id ? [project]
      : existing ? [] : [{ id: previous.id, root }]);
    return this.save({ ...this.preferences, projects,
      selected: this.preferences.selected === id ? existing?.id ?? previous.id : this.preferences.selected });
  }

  async select(id: unknown): Promise<Preferences> {
    const project = this.project(id);
    return this.save({ ...this.preferences, selected: project.id });
  }

  async remove(id: unknown): Promise<Preferences> {
    const project = this.project(id);
    this.activityReader.close(project.root);
    const projects = this.preferences.projects.filter(p => p.id !== project.id);
    return this.save({ ...this.preferences, projects, selected: this.preferences.selected === id
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

  async settingsRoot(id: unknown): Promise<string> {
    const project = this.project(id);
    if (await realpath(project.root) !== project.root) {
      throw new Error('Project directory now resolves elsewhere. Remove and add it again.');
    }
    return project.root;
  }
}
