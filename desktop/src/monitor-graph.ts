import dagre from '@dagrejs/dagre';
import type { Graph, Ticket } from '../electron/types';

/** Metro must turn through 90 degrees at the explicit normal terminal waypoints.
 * Its 45-degree default otherwise loops around a waypoint before entering a card.
 */
export const taskRouterOptions = {
  padding: 24, step: 8, snapToGrid: false, maxDirectionChange: 90,
  excludeShapes: ['task-frame'], maxLoopCount: 25000,
};

export type Size = { width: number; height: number };
export type MonitorNode = Size & { id: string; ticket: Ticket; x: number; y: number;
  children: string[]; expanded: boolean; frame?: Size };
export type TaskRelation = { source: string; target: string; kind: 'dependency' | 'replacement' | 'acceptance'; event_id?: string };
export type MonitorEdge = TaskRelation & { id: string;
  relations: TaskRelation[]; kinds: TaskRelation['kind'][]; projected: boolean; vertices: { x: number; y: number }[] };

/** Preserve direct native relationships, including each step of replacement chains. */
export function taskRelations(graph: Graph): TaskRelation[] {
  const ids = new Set(graph.tickets.map(ticket => ticket.ticket_id));
  return graph.tickets.flatMap(ticket => [
    ...ticket.dependencies.filter(id => ids.has(id)).map(source => ({ source, target: ticket.ticket_id, kind: 'dependency' as const })),
    ...(ticket.delivery ?? []).filter(fact => fact.event === 'ticket-completed' && fact.ticket_id !== ticket.ticket_id && ids.has(fact.ticket_id))
      .map(fact => ({ source: ticket.ticket_id, target: fact.ticket_id, kind: 'acceptance' as const, event_id: fact.event_id })),
    ...ticket.replaced_by.filter(id => ids.has(id)).map(target => ({ source: ticket.ticket_id, target, kind: 'replacement' as const })),
  ]);
}

/** Read only explicit native parents; legacy unknown parents remain unknown. */
export function taskChildren(graph: Graph): Map<string, string[]> {
  const children = new Map(graph.tickets.map(ticket => [ticket.ticket_id, [] as string[]]));
  for (const ticket of graph.tickets) {
    if (ticket.parent_id) children.get(ticket.parent_id)?.push(ticket.ticket_id);
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
  const tickets = new Map(graph.tickets.map(ticket => [ticket.ticket_id, ticket]));
  const children = taskChildren(graph);
  const roots = graph.tickets.filter(ticket => !ticket.parent_id || !tickets.has(ticket.parent_id)).map(ticket => ticket.ticket_id);
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
      const ticket = tickets.get(id)!;
      const descendants = children.get(id)!;
      const open = expanded.has(id) && descendants.length > 0;
      const size = sizes[id] ?? { width: 320, height: 150 };
      const inner = open ? place(descendants) : null;
      const frame = inner ? { width: Math.max(size.width + 48, inner.width + 48), height: size.height + inner.height + 88 } : undefined;
      const node: MonitorNode = { id, ticket, ...size, x: 0, y: 0, children: descendants, expanded: open, frame };
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
      if (edge.kind === 'acceptance') continue; // Receipt is not an execution ordering constraint.
      const from = owners.get(edge.source), to = owners.get(edge.target);
      if (from && to && from !== to) layout.setEdge(from, to, { weight: (layout.edge(from, to)?.weight ?? 0) + 1 });
    }
    dagre.layout(layout);
    const routes = new Map<string, { x: number; y: number }[]>();
    for (const edge of nativeEdges) {
      if (edge.kind === 'acceptance') continue; // Receipt is not an execution ordering constraint.
      const from = owners.get(edge.source), to = owners.get(edge.target);
      if (from && to && from !== to) routes.set(edge.id, layout.edge(from, to).points.slice(1, -1));
    }
    const result: MonitorNode[] = [];
    for (const branch of branches) {
      const pos = layout.node(branch.node.id);
      const x = pos.x - branch.size.width / 2, y = pos.y - branch.size.height / 2;
      result.push({ ...branch.node, x, y });
      if (branch.inner) {
        const offsetX = x + 24, offsetY = y + branch.node.height + 64;
        result.push(...branch.inner.nodes.map(node => ({ ...node, x: node.x + offsetX, y: node.y + offsetY })));
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
  if (!selected) return new Set(graph.tickets.map(ticket => ticket.ticket_id));
  const children = taskChildren(graph);
  const seeds = new Set<string>();
  function include(id: string): void { seeds.add(id); (children.get(id) ?? []).forEach(include); }
  include(selected);
  const upstream = new Map(graph.tickets.map(ticket => [ticket.ticket_id, [] as string[]]));
  const downstream = new Map(graph.tickets.map(ticket => [ticket.ticket_id, [] as string[]]));
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
export function taskStatus(ticket: Ticket): string {
  return ticket.disposition && ticket.disposition !== 'active' ? ticket.disposition
    : !ticket.active ? 'inactive' : ticket.status;
}

/** Order card ports by their opposite card and reserve perpendicular end segments.
 * X6 still owns obstacle routing between these two terminal waypoints.
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
    // Incoming receipts and outgoing results share the physical right border;
    // order them together so opposite directions never occupy the same port.
    const ordered = visible.flatMap(edge => [
      ...(side === 'right' && edge.source === node.id ? [{ edge, end: 'source' as const, other: edge.target }] : []),
      ...(edge.target === node.id && (edge.kind === 'acceptance' ? 'right' : 'left') === side
        ? [{ edge, end: 'target' as const, other: edge.source }] : []),
    ]).sort((a, b) => {
      const first = positions.get(a.other)!, second = positions.get(b.other)!;
      return (first.y + first.height / 2) - (second.y + second.height / 2)
        || first.x - second.x || a.edge.id.localeCompare(b.edge.id);
    });
    ordered.forEach(({ edge, end }, index) => ports.set(`${end}:${edge.id}`, {
      x: side === 'right' ? node.width : 0,
      y: Math.round(node.height * (index + 1) / (ordered.length + 1)),
      clearance: 40 + index * 12,
    }));
  }
  for (const edge of visible) {
    const source = ports.get(`source:${edge.id}`)!, target = ports.get(`target:${edge.id}`)!;
    const from = positions.get(edge.source)!, to = positions.get(edge.target)!;
    // An expanded summary's header is above its children. Keep independent
    // exits at their port heights until they clear that frame; otherwise the
    // shortest obstacle routes can collapse onto the same lane below the card.
    const summaryExit = from.frame && to.x >= from.x + from.frame.width
      ? [{ x: from.x + from.frame.width + source.clearance, y: from.y + source.y }]
      : [];
    ends.set(edge.id, { source: { x: source.x, y: source.y }, target: { x: target.x, y: target.y },
      vertices: [{ x: from.x + source.x + source.clearance, y: from.y + source.y },
        ...summaryExit,
        { x: to.x + target.x + (edge.kind === 'acceptance' ? target.clearance : -target.clearance), y: to.y + target.y }] });
  }
  return ends;
}


/** Enclose all visible native tasks and summary frames in their project view. */
export function projectBounds(nodes: MonitorNode[]): { x: number; y: number; width: number; height: number } {
  const left = Math.min(0, ...nodes.map(node => node.x)) - 36;
  const top = Math.min(0, ...nodes.map(node => node.y)) - 96;
  const right = Math.max(320, ...nodes.map(node => node.x + (node.frame ?? node).width)) + 36;
  const bottom = Math.max(150, ...nodes.map(node => node.y + (node.frame ?? node).height)) + 36;
  return { x: left, y: top, width: right - left, height: bottom - top };
}
