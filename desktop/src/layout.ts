import type { Ticket } from '../electron/types';

/** Place each DAG rank in a column, preserving native ticket order within ranks. */
export function layout(tickets: Pick<Ticket, 'ticket_id' | 'dependencies'>[], sizes: Record<string, { width: number; height: number }> = {}): Record<string, { x: number; y: number }> {
  const ids = new Set(tickets.map(ticket => ticket.ticket_id));
  const remaining = new Map(tickets.map(ticket => [ticket.ticket_id, ticket.dependencies.filter(id => ids.has(id)).length]));
  const dependents = new Map<string, string[]>();
  const ranks = new Map<string, number>();
  for (const ticket of tickets) {
    for (const dependency of ticket.dependencies) {
      if (!ids.has(dependency)) continue;
      if (!dependents.has(dependency)) dependents.set(dependency, []);
      dependents.get(dependency)!.push(ticket.ticket_id);
    }
  }
  const queue = tickets.filter(ticket => remaining.get(ticket.ticket_id) === 0).map(ticket => ticket.ticket_id);
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    for (const child of dependents.get(id) ?? []) {
      ranks.set(child, Math.max(ranks.get(child) ?? 0, (ranks.get(id) ?? 0) + 1));
      remaining.set(child, remaining.get(child)! - 1);
      if (remaining.get(child) === 0) queue.push(child);
    }
  }
  // Contracting interleaved groups can produce a cycle, though Ticket edges are
  // acyclic. Keep every such group visible without inventing or deleting edges.
  for (const [id, count] of remaining) if (count > 0) ranks.set(id, 0);
  const widths = new Map<number, number>();
  for (const ticket of tickets) {
    const rank = ranks.get(ticket.ticket_id) ?? 0;
    widths.set(rank, Math.max(widths.get(rank) ?? 0, sizes[ticket.ticket_id]?.width ?? 280));
  }
  const columns = new Map<number, number>();
  let left = 0;
  for (const rank of [...widths.keys()].sort((a, b) => a - b)) { columns.set(rank, left); left += widths.get(rank)! + 80; }
  const rows = new Map<number, number>();
  return Object.fromEntries(tickets.map(ticket => {
    const rank = ranks.get(ticket.ticket_id) ?? 0;
    const row = rows.get(rank) ?? 0;
    rows.set(rank, row + (sizes[ticket.ticket_id]?.height ?? 150) + 80);
    // ponytail: rank columns; use a layout library if edge crossings impede reading.
    return [ticket.ticket_id, { x: columns.get(rank) ?? 0, y: row }];
  }));
}
