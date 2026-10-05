import type { Ticket } from '../electron/types';

/** Place each DAG rank in a column, preserving native ticket order within ranks. */
export function layout(tickets: Ticket[]): Record<string, { x: number; y: number }> {
  const remaining = new Map(tickets.map(ticket => [ticket.ticket_id, ticket.dependencies.length]));
  const dependents = new Map<string, string[]>();
  const ranks = new Map<string, number>();
  for (const ticket of tickets) {
    for (const dependency of ticket.dependencies) {
      if (!dependents.has(dependency)) dependents.set(dependency, []);
      dependents.get(dependency)!.push(ticket.ticket_id);
    }
  }
  const queue = tickets.filter(ticket => !ticket.dependencies.length).map(ticket => ticket.ticket_id);
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    for (const child of dependents.get(id) ?? []) {
      ranks.set(child, Math.max(ranks.get(child) ?? 0, (ranks.get(id) ?? 0) + 1));
      remaining.set(child, remaining.get(child)! - 1);
      if (remaining.get(child) === 0) queue.push(child);
    }
  }
  const rows = new Map<number, number>();
  return Object.fromEntries(tickets.map(ticket => {
    const rank = ranks.get(ticket.ticket_id) ?? 0;
    const row = rows.get(rank) ?? 0;
    rows.set(rank, row + 1);
    // ponytail: fixed-size rank columns; use a layout library if edge crossing becomes a reading problem.
    return [ticket.ticket_id, { x: rank * 360, y: row * 230 }];
  }));
}
