import type { Node, Edge } from '@xyflow/react';
import type { Graph, Ticket, SummaryGroup } from '../electron/types';
import { layout } from './layout';

export type MonitorNode = Node<{ ticket?: Ticket; group?: SummaryGroup; expanded?: boolean;
  memberships?: string[]; toggle?: () => void }>;

// These are display collections, never native membership or dependency records.
export const ungroupedCollection = 'view:ungrouped';
export const sharedCollection = 'view:shared';
/** Add view-only collections without changing any Ticket's native memberships. */
export function displayGroups(graph: Graph): SummaryGroup[] {
  const groups = graph.groups ?? [];
  const count = new Map<string, number>();
  for (const group of groups) for (const id of group.ticket_ids) count.set(id, (count.get(id) ?? 0) + 1);
  return [...groups,
    { id: ungroupedCollection, title: 'Ungrouped tasks', ticket_ids: graph.tickets.filter(ticket => !count.has(ticket.ticket_id)).map(ticket => ticket.ticket_id) },
    { id: sharedCollection, title: 'Shared tasks', ticket_ids: graph.tickets.filter(ticket => (count.get(ticket.ticket_id) ?? 0) > 1).map(ticket => ticket.ticket_id) },
  ].filter(group => group.ticket_ids.length);
}

/** Collapse explicit ownership and clearly labelled shared/unassigned collections.
 * Each displayed edge retains its real ticket endpoints, even when several
 * dependencies share collapsed endpoints. Group boxes never create dependencies.
 */
export function monitorGraph(graph: Graph, expanded: ReadonlySet<string>): { nodes: MonitorNode[]; edges: Edge[] } {
  const tickets = new Map(graph.tickets.map(ticket => [ticket.ticket_id, ticket]));
  const groups = displayGroups(graph).filter(group => group.ticket_ids.some(id => tickets.has(id)));
  const memberships = new Map<string, SummaryGroup[]>();
  for (const group of graph.groups ?? []) for (const id of group.ticket_ids) {
    if (tickets.has(id)) memberships.set(id, [...memberships.get(id) ?? [], group]);
  }
  const owner = (id: string) => memberships.get(id)?.length === 1 ? memberships.get(id)![0].id
    : memberships.has(id) ? sharedCollection : ungroupedCollection;
  const groupId = (id: string) => `summary:${id}`;
  const endpoint = (id: string) => !expanded.has(owner(id)) ? groupId(owner(id)) : id;
  const nodes: MonitorNode[] = [];
  const sizes: Record<string, { width: number; height: number }> = {};
  for (const group of groups) {
    const members = graph.tickets.filter(ticket => owner(ticket.ticket_id) === group.id);
    const open = expanded.has(group.id);
    const positions = layout(members);
    const width = open && members.length ? Math.max(...Object.values(positions).map(pos => pos.x)) + 280 : 240;
    const height = open && members.length ? Math.max(...Object.values(positions).map(pos => pos.y)) + 280 : 100;
    sizes[groupId(group.id)] = { width, height };
    nodes.push({ id: groupId(group.id), type: 'summary', position: { x: 0, y: 0 },
      data: { group, expanded: open }, style: { width, height } });
    if (open) for (const ticket of members) nodes.push({ id: ticket.ticket_id, type: 'ticket',
      parentId: groupId(group.id), extent: 'parent',
      position: { x: positions[ticket.ticket_id].x + 28, y: positions[ticket.ticket_id].y + 90 },
      data: { ticket, memberships: (memberships.get(ticket.ticket_id)?.length ?? 0) > 1 ? memberships.get(ticket.ticket_id)!.map(group => group.title) : undefined } });
  }
  const edges: Edge[] = [];
  for (const ticket of graph.tickets) for (const dependency of ticket.dependencies) {
    if (!tickets.has(dependency)) continue;
    const source = endpoint(dependency), target = endpoint(ticket.ticket_id);
    if (source !== target) edges.push({ id: `${dependency}-${ticket.ticket_id}`, source, target, type: 'smoothstep',
      data: { dependency, ticket: ticket.ticket_id }, ariaLabel: `#${dependency} → #${ticket.ticket_id}` });
  }
  // Summary contraction can introduce cycles. A compact overview avoids treating
  // those cycles as one unbounded DAG rank; arrows retain the actual relations.
  const roots = nodes.filter(node => !node.parentId);
  const closed = roots.filter(node => !node.data.expanded);
  const columns = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(closed.length * 2))));
  closed.forEach((node, index) => { node.position = { x: (index % columns) * 260, y: Math.floor(index / columns) * 132 }; });
  let top = Math.ceil(closed.length / columns) * 132 + 48;
  for (const node of roots.filter(node => node.data.expanded)) {
    node.position = { x: 0, y: top };
    top += sizes[node.id].height + 80;
  }
  return { nodes, edges };
}
