import type { Node, Edge } from '@xyflow/react';
import type { Graph, Ticket, SummaryGroup } from '../electron/types';
import { layout } from './layout';

export type MonitorNode = Node<{ ticket?: Ticket; group?: SummaryGroup; expanded?: boolean;
  memberships?: string[]; toggle?: () => void }>;

/** Collapse only explicit, exclusive ownership; shared/unassigned tickets stay visible.
 * Each displayed edge retains its real ticket endpoints, even when several
 * dependencies share collapsed endpoints. Group boxes never create dependencies.
 */
export function monitorGraph(graph: Graph, expanded: ReadonlySet<string>): { nodes: MonitorNode[]; edges: Edge[] } {
  const tickets = new Map(graph.tickets.map(ticket => [ticket.ticket_id, ticket]));
  const groups = (graph.groups ?? []).filter(group => group.ticket_ids.some(id => tickets.has(id)));
  const memberships = new Map<string, SummaryGroup[]>();
  for (const group of groups) for (const id of group.ticket_ids) {
    if (tickets.has(id)) memberships.set(id, [...memberships.get(id) ?? [], group]);
  }
  const owner = (id: string) => memberships.get(id)?.length === 1 ? memberships.get(id)![0].id : undefined;
  const groupId = (id: string) => `summary:${id}`;
  const unit = (id: string) => owner(id) ? groupId(owner(id)!) : id;
  const endpoint = (id: string) => owner(id) && !expanded.has(owner(id)!) ? unit(id) : id;
  const nodes: MonitorNode[] = [];
  const sizes: Record<string, { width: number; height: number }> = {};
  for (const group of groups) {
    const members = graph.tickets.filter(ticket => owner(ticket.ticket_id) === group.id);
    const open = expanded.has(group.id);
    const positions = layout(members);
    const width = open && members.length ? Math.max(...Object.values(positions).map(pos => pos.x)) + 280 : 280;
    const height = open && members.length ? Math.max(...Object.values(positions).map(pos => pos.y)) + 280 : 120;
    sizes[groupId(group.id)] = { width, height };
    nodes.push({ id: groupId(group.id), type: 'summary', position: { x: 0, y: 0 },
      data: { group, expanded: open }, style: { width, height } });
    if (open) for (const ticket of members) nodes.push({ id: ticket.ticket_id, type: 'ticket',
      parentId: groupId(group.id), extent: 'parent',
      position: { x: positions[ticket.ticket_id].x + 28, y: positions[ticket.ticket_id].y + 90 }, data: { ticket } });
  }
  for (const ticket of graph.tickets) if (!owner(ticket.ticket_id)) {
    sizes[ticket.ticket_id] = { width: 250, height: 210 };
    nodes.push({ id: ticket.ticket_id, type: 'ticket', position: { x: 0, y: 0 },
      data: { ticket, memberships: memberships.get(ticket.ticket_id)?.map(group => group.title) } });
  }
  const dependencies = new Map(Object.keys(sizes).map(id => [id, new Set<string>()]));
  const edges: Edge[] = [];
  for (const ticket of graph.tickets) for (const dependency of ticket.dependencies) {
    if (!tickets.has(dependency)) continue;
    if (unit(ticket.ticket_id) !== unit(dependency)) dependencies.get(unit(ticket.ticket_id))!.add(unit(dependency));
    const source = endpoint(dependency), target = endpoint(ticket.ticket_id);
    if (source !== target) edges.push({ id: `${dependency}-${ticket.ticket_id}`, source, target, type: 'smoothstep',
      data: { dependency, ticket: ticket.ticket_id }, ariaLabel: `#${dependency} → #${ticket.ticket_id}` });
  }
  const positions = layout([...dependencies].map(([ticket_id, deps]) => ({ ticket_id, dependencies: [...deps] })), sizes);
  for (const node of nodes) if (!node.parentId) node.position = positions[node.id];
  return { nodes, edges };
}
