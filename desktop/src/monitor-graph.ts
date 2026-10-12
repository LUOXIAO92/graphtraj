import dagre from '@dagrejs/dagre';
import type { Graph, Ticket } from '../electron/types';

export type Size = { width: number; height: number };
export type MonitorNode = Size & { id: string; ticket: Ticket; x: number; y: number;
  children: string[]; expanded: boolean; frame?: Size };
export type MonitorEdge = { id: string; source: string; target: string;
  dependency: string; ticket: string; projected: boolean; vertices: { x: number; y: number }[] };

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
  const nativeEdges = graph.tickets.flatMap(ticket => ticket.dependencies.filter(id => tickets.has(id))
    .map(dependency => ({ id: JSON.stringify([dependency, ticket.ticket_id]), dependency, ticket: ticket.ticket_id })));

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
    const layout = new dagre.graphlib.Graph().setGraph({ rankdir: 'LR', ranksep: 120, nodesep: 64, edgesep: 28, marginx: 0, marginy: 0 });
    for (const branch of branches) layout.setNode(branch.node.id, branch.size);
    // Map each real endpoint to its branch at this hierarchy level solely for layout.
    const owners = new Map<string, string>();
    function own(id: string, root: string): void {
      owners.set(id, root);
      for (const child of children.get(id) ?? []) own(child, root);
    }
    ids.forEach(id => own(id, id));
    // Parallel projected dependencies share one weighted ordering constraint.
    // Dagre can produce NaN routes for parallel edges; native edges and ports
    // remain separate below and in the canvas.
    for (const edge of nativeEdges) {
      const from = owners.get(edge.dependency), to = owners.get(edge.ticket);
      if (from && to && from !== to) layout.setEdge(from, to, { weight: (layout.edge(from, to)?.weight ?? 0) + 1 });
    }
    dagre.layout(layout);
    const routes = new Map<string, { x: number; y: number }[]>();
    for (const edge of nativeEdges) {
      const from = owners.get(edge.dependency), to = owners.get(edge.ticket);
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
  const edges = nativeEdges.map(edge => ({ ...edge, source: endpoints.get(edge.dependency)!, target: endpoints.get(edge.ticket)!,
    vertices: placed.routes.get(edge.id) ?? [],
    projected: endpoints.get(edge.dependency) !== edge.dependency || endpoints.get(edge.ticket) !== edge.ticket }));
  return { nodes, edges, endpoints };
}

/** Trace real upstream/downstream paths, including the selected summary's internals. */
export function dependencyFocus(graph: Graph, selected: string | null): Set<string> {
  if (!selected) return new Set(graph.tickets.map(ticket => ticket.ticket_id));
  const children = taskChildren(graph);
  const seeds = new Set<string>();
  function include(id: string): void { seeds.add(id); (children.get(id) ?? []).forEach(include); }
  include(selected);
  const upstream = new Map(graph.tickets.map(ticket => [ticket.ticket_id, ticket.dependencies]));
  const downstream = new Map(graph.tickets.map(ticket => [ticket.ticket_id, [] as string[]]));
  for (const ticket of graph.tickets) for (const dep of ticket.dependencies) downstream.get(dep)?.push(ticket.ticket_id);
  const focus = new Set(seeds);
  for (const direction of [upstream, downstream]) {
    const seen = new Set(seeds), queue = [...seeds];
    for (let index = 0; index < queue.length; index++) for (const id of direction.get(queue[index]) ?? []) {
      if (!seen.has(id)) { seen.add(id); focus.add(id); queue.push(id); }
    }
  }
  return focus;
}
