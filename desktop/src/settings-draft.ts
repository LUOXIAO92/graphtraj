import type { RoleFields, RoleTree, SettingsDraft } from '../electron/types';

export const fieldLabels: Record<keyof RoleFields, string> = {
  approval_connection: 'Codex approval connection', approval_model: 'Codex approval model', approval_base_url: 'Codex approval Base URL', approval_api_key_env: 'Codex approval api_key_env name',
  connection: 'Global connection', runtime: 'Runtime', model: 'Model', base_url: 'Base URL', api_key_env: 'Credential environment variable (api_key_env)',
  reasoning_effort: 'Reasoning effort', instructions: 'Instruction file reference',
  system_prompt: 'System prompt', developer_prompt: 'Developer prompt',
};

/** Read only a declared role key, including names shared with Object.prototype. */
export function ownRole<T>(roles: Record<string, T> | undefined, reference: string): T | undefined {
  return roles && Object.hasOwn(roles, reference) ? roles[reference] : undefined;
}

/** Use an explicitly staged name in role controls and dispatch labels. */
export function roleName(renames: Record<string, string>, reference: string): string {
  return ownRole(renames, reference) ?? reference;
}

/** Build the renderer's serializable role edits and readable before/after rows. */
export function roleChanges(roles: Record<string, RoleFields>, saved?: Record<string, RoleFields>) {
  const edits: SettingsDraft['edits'] = Object.create(null);
  const changes: { label: string; before: string; after: string }[] = [];
  for (const [role, fields] of Object.entries(roles)) {
    for (const field of Object.keys(fieldLabels) as (keyof RoleFields)[]) {
      const before = ownRole(saved, role)?.[field] ?? null;
      const after = fields[field] || null;
      if (before !== after) {
        (edits[role] ??= {})[field] = after;
        changes.push({ label: `${role} · ${fieldLabels[field]}`, before: before ?? '(not set)', after: after ?? '(clear)' });
      }
    }
  }
  return { edits, changes };
}

/** Read direct edges without changing the nested native document. */
export function treeEdges(tree: RoleTree): [string, string][] {
  return Object.entries(tree).flatMap(([parent, children]) => [
    ...Object.keys(children).map(child => [parent, child] as [string, string]), ...treeEdges(children),
  ]);
}

/** Show complete native branches involving a team, plus its unattached presets. */
export function teamForest(tree: RoleTree, references: string[]): RoleTree {
  const members = new Set(references);
  function includesMember(nodes: RoleTree): boolean {
    return Object.entries(nodes).some(([ref, children]) => members.has(ref) || includesMember(children));
  }
  const forest = Object.fromEntries(Object.entries(tree).filter(([ref, children]) => includesMember({ [ref]: children })));
  const present = new Set([...Object.keys(forest), ...treeEdges(forest).flat()]);
  for (const ref of references) if (!present.has(ref)) forest[ref] = {};
  return forest;
}

/** Return all configured descendants, including repeated native role occurrences. */
export function branchRoles(tree: RoleTree, reference: string): Set<string> {
  const children = new Map<string, string[]>();
  for (const [parent, child] of treeEdges(tree)) children.set(parent, [...children.get(parent) ?? [], child]);
  const result = new Set<string>();
  const pending = [reference];
  while (pending.length) {
    const ref = pending.pop()!;
    if (result.has(ref)) continue;
    result.add(ref); pending.push(...children.get(ref) ?? []);
  }
  return result;
}

/** Union repeated role occurrences without losing their nested relationships. */
function mergeTrees(target: RoleTree, source: RoleTree): void {
  for (const [ref, children] of Object.entries(source)) {
    if (!Object.hasOwn(target, ref)) target[ref] = Object.create(null);
    mergeTrees(target[ref], children);
  }
}

/** Remove explicit nodes, optionally promoting surviving children to their parent. */
export function removeNodes(tree: RoleTree, removed: Set<string>, reconnect: boolean): RoleTree {
  const result: RoleTree = Object.create(null);
  for (const [ref, children] of Object.entries(tree)) {
    const next = removeNodes(children, removed, reconnect);
    if (!removed.has(ref)) mergeTrees(result, { [ref]: next });
    else if (reconnect) mergeTrees(result, next);
  }
  return result;
}

/** Move a complete branch, refusing cycles instead of losing nested edges. */
export function moveNode(tree: RoleTree, reference: string, parent: string): RoleTree {
  if (parent && branchRoles(tree, reference).has(parent)) throw new Error('Choose a parent outside this branch.');
  const children: RoleTree = {};
  function collect(nodes: RoleTree): void {
    for (const [ref, descendants] of Object.entries(nodes)) {
      if (ref === reference) mergeTrees(children, descendants);
      collect(descendants);
    }
  }
  collect(tree);
  const next = removeNodes(tree, new Set([reference]), false);
  if (!parent) next[reference] = children;
  else {
    let attached = false;
    function attach(nodes: RoleTree): void {
      for (const [ref, descendants] of Object.entries(nodes)) {
        if (ref === parent && !attached) { descendants[reference] = children; attached = true; }
        else attach(descendants);
      }
    }
    attach(next);
    if (!attached) next[parent] = { [reference]: children };
  }
  return next;
}

/** Move one displayed occurrence inside its team; retain all other native branches. */
export function connectTeamNode(tree: RoleTree, childPath: string[], parentPath: string[] | null): RoleTree {
  const child = childPath.at(-1)!;
  const parent = parentPath?.at(-1);
  const team = (ref: string) => ref.includes('.') ? ref.split('.')[0] : '';
  if (parent && team(parent) !== team(child)) throw new Error('Connect agents within the current team.');
  if (childPath.length > 1 && team(childPath.at(-2)!) !== team(child)) throw new Error('This occurrence has a historical cross-team parent. That relationship is preserved.');
  if (parent && branchRoles(tree, child).has(parent)) throw new Error('An agent cannot report to itself or its descendants.');
  const next = structuredClone(tree);
  function branch(path: string[]): RoleTree {
    let nodes = next;
    for (const ref of path) {
      if (!Object.hasOwn(nodes, ref)) throw new Error('The organization changed. Select the connection again.');
      nodes = nodes[ref];
    }
    return nodes;
  }
  const owner = branch(childPath.slice(0, -1));
  const children = ownRole(owner, child) ?? {};
  delete owner[child];
  if (parentPath?.length === 1 && !Object.hasOwn(next, parentPath[0])) Object.defineProperty(next, parentPath[0], { value: {}, enumerable: true, writable: true, configurable: true });
  const target = parentPath ? branch(parentPath) : next;
  if (Object.hasOwn(target, child)) throw new Error('That parent already has this agent. Existing branches are preserved.');
  Object.defineProperty(target, child, { value: children, enumerable: true, writable: true, configurable: true });
  return next;
}

/** One consistent display name, with a catalog name only when it distinguishes an entry. */
export function runtimeLabel(runtime: string, entry?: string): string {
  const label = ({ codex: 'Codex', pi: 'Pi', dsh: 'DSH' } as Record<string, string>)[runtime] || runtime;
  return entry && entry.toLowerCase() !== runtime.toLowerCase() ? `${label} · ${entry}` : label;
}
