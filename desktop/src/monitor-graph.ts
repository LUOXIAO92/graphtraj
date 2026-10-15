import dagre from '@dagrejs/dagre';
import type { Graph, Task } from '../electron/types';

/** Metro must turn through 90 degrees at the explicit normal terminal waypoints.
 * Its 45-degree default otherwise loops around a waypoint before entering a card.
 */
export const taskRouterOptions = {
  padding: 24, step: 8, snapToGrid: false, maxDirectionChange: 90,
  excludeShapes: ['task-frame'], maxLoopCount: 25000,
};

export type Size = { width: number; height: number };
export type Bounds = Size & { x: number; y: number };
export type MonitorNode = Size & { id: string; task: Task; x: number; y: number;
  children: string[]; expanded: boolean; frame?: Bounds };
export type TaskRelation = { source: string; target: string; kind: 'dependency' | 'replacement' | 'acceptance'; event_id?: string };
export type MonitorEdge = TaskRelation & { id: string;
  relations: TaskRelation[]; kinds: TaskRelation['kind'][]; projected: boolean; vertices: { x: number; y: number }[] };

/** Preserve direct native relationships, including each step of replacement chains. */
export function taskRelations(graph: Graph): TaskRelation[] {
  const ids = new Set(graph.tasks.map(task => task.task_id));
  return graph.tasks.flatMap(task => [
    ...task.dependencies.filter(id => ids.has(id)).map(source => ({ source, target: task.task_id, kind: 'dependency' as const })),
    ...(task.delivery ?? []).filter(fact => fact.event === 'task-completed' && fact.task_id !== task.task_id && ids.has(fact.task_id))
      .map(fact => ({ source: task.task_id, target: fact.task_id, kind: 'acceptance' as const, event_id: fact.event_id })),
    ...task.replaced_by.filter(id => ids.has(id)).map(target => ({ source: task.task_id, target, kind: 'replacement' as const })),
  ]);
}

/** Read only explicit native parents; legacy unknown parents remain unknown. */
export function taskChildren(graph: Graph): Map<string, string[]> {
  const children = new Map(graph.tasks.map(task => [task.task_id, [] as string[]]));
  for (const task of graph.tasks) {
    if (task.parent_id) children.get(task.parent_id)?.push(task.task_id);
  }
  return children;
}

/** Project hidden endpoints to visible ancestors without changing native dependencies.
 * Dagre places siblings using their complete measured subtree sizes. Contracted
 * edges may point both ways; that is a view of the DAG, never a native cycle.
 */
export function monitorGraph(graph: Graph, expanded: ReadonlySet<string>, sizes: Record<string, Size> = {}): {
  nodes: MonitorNode[]; edges: MonitorEdge[]; endpoints: Map<string, string>;
} {
  const tasks = new Map(graph.tasks.map(task => [task.task_id, task]));
  const children = taskChildren(graph);
  const roots = graph.tasks.filter(task => !task.parent_id || !tasks.has(task.parent_id)).map(task => task.task_id);
  const endpoints = new Map<string, string>();
  const nodes: MonitorNode[] = [];
  const nativeEdges = taskRelations(graph).map(edge => ({ ...edge, id: JSON.stringify([edge.kind, edge.source, edge.target]) }));

  function project(id: string, visible: string): void {
    endpoints.set(id, visible);
    for (const child of children.get(id) ?? []) project(child, visible === id && expanded.has(id) ? child : visible);
  }
  roots.forEach(id => project(id, id));

  function place(ids: string[]): { nodes: MonitorNode[]; width: number; height: number; routes: Map<string, { x: number; y: number }[]> } {
    const branches = ids.map(id => {
      const task = tasks.get(id)!;
      const descendants = children.get(id)!;
      const open = expanded.has(id) && descendants.length > 0;
      const size = sizes[id] ?? { width: 320, height: 150 };
      const inner = open ? place(descendants) : null;
      // Membership encloses the work; the real summary card receives its result
      // at the delivery side, rather than sending receipt arrows back over it.
      const frame = inner ? { x: 0, y: 0, width: inner.width + 140 + size.width + 48,
        height: Math.max(size.height, inner.height) + 48 } : undefined;
      const node: MonitorNode = { id, task, ...size, x: 0, y: 0, children: descendants, expanded: open, frame };
      return { node, inner, size: frame ?? size };
    });
    const layout = new dagre.graphlib.Graph().setGraph({ rankdir: 'LR', ranksep: 140, nodesep: 64, edgesep: 28, marginx: 0, marginy: 0 });
    for (const branch of branches) layout.setNode(branch.node.id, branch.size);
    // Map each real endpoint to its branch at this hierarchy level solely for layout.
    const owners = new Map<string, string>();
    function own(id: string, root: string): void {
      owners.set(id, root);
      for (const child of children.get(id) ?? []) own(child, root);
    }
    ids.forEach(id => own(id, id));
    // Parallel projected dependencies share one weighted ordering constraint.
    // Dagre can produce NaN routes for parallel edges. The display projection
    // below retains all native dependencies within each visible directed pair.
    for (const edge of nativeEdges) {
      // All real result flows guide display order, without becoming execution dependencies.
      const from = owners.get(edge.source), to = owners.get(edge.target);
      if (from && to && from !== to) layout.setEdge(from, to, { weight: (layout.edge(from, to)?.weight ?? 0) + 1 });
    }
    dagre.layout(layout);
    const routes = new Map<string, { x: number; y: number }[]>();
    for (const edge of nativeEdges) {
      const from = owners.get(edge.source), to = owners.get(edge.target);
      if (from && to && from !== to) routes.set(edge.id, layout.edge(from, to).points.slice(1, -1));
    }
    const result: MonitorNode[] = [];
    for (const branch of branches) {
      const pos = layout.node(branch.node.id);
      const x = pos.x - branch.size.width / 2, y = pos.y - branch.size.height / 2;
      result.push({ ...branch.node,
        x: branch.inner ? x + branch.inner.width + 164 : x,
        y: branch.inner ? y + (branch.size.height - branch.node.height) / 2 : y,
        ...(branch.node.frame ? { frame: { ...branch.node.frame, x, y } } : {}) });
      if (branch.inner) {
        const offsetX = x + 24, offsetY = y + 24;
        result.push(...branch.inner.nodes.map(node => ({ ...node, x: node.x + offsetX, y: node.y + offsetY,
          ...(node.frame ? { frame: { ...node.frame, x: node.frame.x + offsetX, y: node.frame.y + offsetY } } : {}) })));
        for (const [id, points] of branch.inner.routes) routes.set(id, points.map(point => ({ x: point.x + offsetX, y: point.y + offsetY })));
      }
    }
    return { nodes: result, width: layout.graph().width ?? 0, height: layout.graph().height ?? 0, routes };
  }
  const placed = place(roots);
  nodes.push(...placed.nodes);
  const pairs = new Map<string, MonitorEdge>();
  for (const edge of nativeEdges) {
    const source = endpoints.get(edge.source)!, target = endpoints.get(edge.target)!;
    const id = JSON.stringify([source, target]);
    const existing = pairs.get(id);
    const relation: TaskRelation = { source: edge.source, target: edge.target, kind: edge.kind, ...(edge.event_id ? { event_id: edge.event_id } : {}) };
    if (existing) {
      existing.relations.push(relation);
      if (!existing.kinds.includes(edge.kind)) existing.kinds.push(edge.kind);
      // A shared arrow has one pair of ports, but retains each meaning below.
      if (edge.kind === 'dependency') existing.kind = 'dependency';
      existing.projected ||= source !== edge.source || target !== edge.target;
    }
    else pairs.set(id, { id, source, target, kind: edge.kind,
      relations: [relation], kinds: [edge.kind],
      vertices: placed.routes.get(edge.id) ?? [],
      projected: source !== edge.source || target !== edge.target });
  }
  const edges = [...pairs.values()];
  return { nodes, edges, endpoints };
}

/** Trace native input and replacement paths, including selected summary internals. */
export function taskFocus(graph: Graph, selected: string | null): Set<string> {
  if (!selected) return new Set(graph.tasks.map(task => task.task_id));
  const children = taskChildren(graph);
  const seeds = new Set<string>();
  function include(id: string): void { seeds.add(id); (children.get(id) ?? []).forEach(include); }
  include(selected);
  const upstream = new Map(graph.tasks.map(task => [task.task_id, [] as string[]]));
  const downstream = new Map(graph.tasks.map(task => [task.task_id, [] as string[]]));
  for (const edge of taskRelations(graph)) {
    upstream.get(edge.target)?.push(edge.source);
    downstream.get(edge.source)?.push(edge.target);
  }
  const focus = new Set(seeds);
  for (const direction of [upstream, downstream]) {
    const seen = new Set(seeds), queue = [...seeds];
    for (let index = 0; index < queue.length; index++) for (const id of direction.get(queue[index]) ?? []) {
      if (!seen.has(id)) { seen.add(id); focus.add(id); queue.push(id); }
    }
  }
  return focus;
}

/** Prefer disposition over a retained historical execution stage. */
export function taskStatus(task: Task): string {
  return task.disposition && task.disposition !== 'active' ? task.disposition
    : !task.active ? 'inactive' : task.status;
}

/** Order ports and reserve separate horizontal passages between terminal points.
 * X6 still owns obstacle routing into and out of these intermediate waypoints.
 */
export function dependencyTerminals(nodes: MonitorNode[], edges: MonitorEdge[]): Map<string, {
  source: { x: number; y: number }; target: { x: number; y: number };
  vertices: { x: number; y: number }[];
}> {
  const positions = new Map(nodes.map(node => [node.id, node]));
  const visible = edges.filter(edge => edge.source !== edge.target);
  const ends = new Map<string, { source: { x: number; y: number }; target: { x: number; y: number }; vertices: { x: number; y: number }[] }>();
  const ports = new Map<string, { x: number; y: number; clearance: number }>();
  for (const node of nodes) for (const side of ['left', 'right'] as const) {
    const ordered = visible.flatMap(edge => [
      ...(side === 'right' && edge.source === node.id ? [{ edge, end: 'source' as const, other: edge.target }] : []),
      ...(edge.target === node.id && side === 'left'
        ? [{ edge, end: 'target' as const, other: edge.source }] : []),
    ]).sort((a, b) => {
      const first = positions.get(a.other)!, second = positions.get(b.other)!;
      return (first.y + first.height / 2) - (second.y + second.height / 2)
        || first.x - second.x || a.edge.id.localeCompare(b.edge.id);
    });
    ordered.forEach(({ edge, end }, index) => ports.set(`${end}:${edge.id}`, {
      x: side === 'right' ? node.width : 0,
      y: Math.round(node.height * (index + 1) / (ordered.length + 1)),
      // Both terminals must fit inside the existing 140px rank gap even at
      // high fan-in; unbounded offsets can put a waypoint inside another card.
      clearance: 40 + index * Math.min(12, 24 / Math.max(1, ordered.length - 1)),
    }));
  }
  const passages: { left: number; right: number; y: number }[] = [];
  // Stable ordering keeps lanes unchanged when native relationship order changes.
  for (const edge of [...visible].sort((a, b) => a.id.localeCompare(b.id))) {
    const source = ports.get(`source:${edge.id}`)!, target = ports.get(`target:${edge.id}`)!;
    const from = positions.get(edge.source)!, to = positions.get(edge.target)!;
    const first = { x: from.x + source.x + source.clearance, y: from.y + source.y };
    const last = { x: to.x + target.x - target.clearance, y: to.y + target.y };
    const left = Math.min(first.x, last.x), right = Math.max(first.x, last.x);
    // Dagre points guide the preferred passage, including translated nested
    // layouts. Distinct visible pairs must not inherit one shared branch route.
    const preferred = edge.vertices[0]?.y ?? first.y;
    const obstacles = nodes.filter(node => node.x - 24 < right && node.x + node.width + 24 > left);
    const occupied = passages.filter(p => p.left < right && p.right > left);
    const candidates = [preferred,
      ...obstacles.flatMap(node => [node.y - 32, node.y + node.height + 32]),
      ...occupied.flatMap(p => [p.y - 16, p.y + 16])];
    const y = candidates.sort((a, b) => Math.abs(a - preferred) - Math.abs(b - preferred) || a - b)
      .find(candidate => obstacles.every(node => candidate < node.y - 24 || candidate > node.y + node.height + 24)
        && occupied.every(p => Math.abs(p.y - candidate) >= 16))!;
    passages.push({ left, right, y });
    ends.set(edge.id, { source: { x: source.x, y: source.y }, target: { x: target.x, y: target.y },
      vertices: [first, { x: first.x, y }, { x: last.x, y }, last] });
  }
  return ends;
}

type Point = { x: number; y: number };
type PathTerminal = Point | { cell: string; port: string };
export type TaskPath = { id: string; source: PathTerminal; target: PathTerminal;
  vertices: Point[]; arrow: boolean; direct: boolean; data: MonitorEdge };

/** Render a common receipt once, retaining the real relations on every segment.
 * Point terminals are drawing junctions only, never graph nodes or dependencies.
 */
export function taskPaths(nodes: MonitorNode[], edges: MonitorEdge[]): {
  paths: TaskPath[];
  ports: Map<string, { id: string; group: 'in' | 'out'; args: Point }[]>;
} {
  const visible = edges.filter(edge => edge.source !== edge.target);
  const positions = new Map(nodes.map(node => [node.id, node]));
  const terminals = dependencyTerminals(nodes, visible);
  const ports = new Map(nodes.map(node => [node.id, [] as { id: string; group: 'in' | 'out'; args: Point }[]]));
  const groups = new Map<string, MonitorEdge[]>();
  const paths: TaskPath[] = [];
  for (const edge of visible) {
    const direction = Math.sign(positions.get(edge.target)!.x - positions.get(edge.source)!.x);
    const key = JSON.stringify([edge.target, [...edge.kinds].sort(), direction]);
    groups.set(key, [...(groups.get(key) ?? []), edge]);
    ports.get(edge.source)!.push({ id: `out:${edge.id}`, group: 'out', args: terminals.get(edge.id)!.source });
  }
  const rails: { x: number; top: number; bottom: number }[] = [];
  for (const [key, members] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
    members.sort((a, b) => terminals.get(a.id)!.target.y - terminals.get(b.id)!.target.y || a.id.localeCompare(b.id));
    const representative = members[Math.floor(members.length / 2)];
    const to = positions.get(representative.target)!;
    const end = terminals.get(representative.id)!;
    const port = `in:${representative.id}`;
    ports.get(to.id)!.push({ id: port, group: 'in', args: end.target });
    if (members.length === 1) {
      paths.push({ id: representative.id, source: { cell: representative.source, port: `out:${representative.id}` },
        target: { cell: to.id, port }, vertices: end.vertices, arrow: true, direct: false, data: representative });
      continue;
    }
    const rootY = to.y + end.target.y;
    const joins = members.map(edge => ({ edge, y: terminals.get(edge.id)!.vertices[1].y }));
    const levels = [...new Set([rootY, ...joins.map(join => join.y)])].sort((a, b) => a - b);
    const top = levels[0], bottom = levels.at(-1)!;
    // Find a free receiving column using existing card clearances. This reserves
    // a shared straight segment; X6 still routes each incoming source branch.
    const obstacles = nodes.filter(node => node.y - 24 < bottom && node.y + node.height + 24 > top);
    const occupied = rails.filter(rail => rail.top <= bottom && rail.bottom >= top);
    const candidates = [to.x - 48, ...obstacles.flatMap(node => [node.x - 32, node.x + node.width + 32]),
      ...occupied.flatMap(rail => [rail.x - 16, rail.x + 16])];
    const x = candidates.filter(value => value <= to.x - 40).sort((a, b) => b - a)
      .find(value => obstacles.every(node => value < node.x - 24 || value > node.x + node.width + 24)
        && occupied.every(rail => Math.abs(value - rail.x) >= 16))!;
    rails.push({ x, top, bottom });
    for (const { edge, y } of joins) {
      const first = terminals.get(edge.id)!.vertices[0];
      paths.push({ id: edge.id, source: { cell: edge.source, port: `out:${edge.id}` }, target: { x, y },
        vertices: [first, { x: first.x, y }], arrow: false, direct: false, data: edge });
    }
    const evidence = (included: MonitorEdge[]): MonitorEdge => ({ ...representative,
      relations: included.flatMap(edge => edge.relations), projected: included.some(edge => edge.projected) });
    for (let index = 1; index < levels.length; index++) {
      const low = levels[index - 1], high = levels[index];
      const included = joins.filter(join => Math.min(join.y, rootY) <= low && Math.max(join.y, rootY) >= high)
        .map(join => join.edge);
      if (!included.length) continue;
      const upwards = high <= rootY;
      paths.push({ id: `receipt:${key}:${index}`, source: { x, y: upwards ? low : high },
        target: { x, y: upwards ? high : low }, vertices: [], arrow: false, direct: true, data: evidence(included) });
    }
    paths.push({ id: `receipt:${key}:entry`, source: { x, y: rootY }, target: { cell: to.id, port },
      vertices: [{ x: to.x - 40, y: rootY }], arrow: true, direct: false, data: evidence(members) });
  }
  return { paths, ports };
}


/** Enclose all visible native tasks and summary frames in their project view. */
export function projectBounds(nodes: MonitorNode[]): { x: number; y: number; width: number; height: number } {
  const bounds = nodes.map(node => node.frame ?? node);
  const left = Math.min(0, ...bounds.map(node => node.x)) - 36;
  const top = Math.min(0, ...bounds.map(node => node.y)) - 96;
  const right = Math.max(320, ...bounds.map(node => node.x + node.width)) + 36;
  const bottom = Math.max(150, ...bounds.map(node => node.y + node.height)) + 36;
  return { x: left, y: top, width: right - left, height: bottom - top };
}
