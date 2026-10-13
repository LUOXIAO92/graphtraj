import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { Graph as X6, Shape, MiniMap, NodeView, type Cell } from '@antv/x6';
import type { Graph, Ticket } from '../electron/types';
import { taskFocus, taskRouterOptions, monitorGraph, taskChildren, taskStatus, dependencyTerminals, projectBounds, type Size, type MonitorEdge } from './monitor-graph';
import './task-canvas.css';

export type TaskCanvasHandle = { fit: () => void; locate: (id: string) => void };
type Props = { graph: Graph; projectName: string; expanded: ReadonlySet<string>; selected: string | null;
  matches: ReadonlySet<string>; active: boolean; select: (id: string | null) => void; toggle: (id: string) => void };

// Reuse the shared model without moving the main canvas HTML into the minimap.
class MapNodeView extends NodeView {
  update(): void {
    super.update();
    // HTML nodes carry invisible SVG bodies. Override only this thumbnail DOM,
    // never the shared model or the main canvas node attributes.
    if (this.cell.shape === 'native-task') {
      const body = this.container.querySelector('rect');
      body?.setAttribute('fill', '#94a3b8');
      body?.setAttribute('stroke', '#64748b');
    }
  }
  protected renderMarkup(): void {
    this.renderJSONMarkup([{ tagName: 'rect', selector: 'body', attrs: {
      width: this.cell.size().width, height: this.cell.size().height, fill: '#94a3b8', stroke: '#64748b',
    } }]);
  }
}

Shape.HTML.register({ shape: 'native-task', html: cell => cell.getData().element });
X6.registerNode('task-frame', { inherit: 'rect', attrs: { body: {
  fill: '#eef2f780', stroke: '#bdcbd9', strokeWidth: 1, rx: 12, ry: 12,
} } });

/** Build a text-only card shared by measurement and X6; task content is never HTML. */
function card(ticket: Ticket, children: Ticket[], open: boolean, select: () => void, toggle: () => void): HTMLDivElement {
  const element = document.createElement('div');
  element.className = 'native-task-card';
  element.dataset.taskId = ticket.ticket_id;
  element.setAttribute('role', 'group');
  element.setAttribute('aria-label', ticket.title);
  const title = document.createElement('button');
  title.className = 'native-task-title';
  title.textContent = ticket.title;
  title.onclick = event => { event.stopPropagation(); select(); };
  element.append(title);
  const meta = document.createElement('div');
  meta.className = 'native-task-meta';
  meta.textContent = `#${ticket.ticket_id} · ${taskStatus(ticket)}${ticket.replaced_by.length ? ` · → ${ticket.replaced_by.map(id => `#${id}`).join(', ')}` : ''}`;
  element.append(meta);
  const delivery = document.createElement('div');
  delivery.className = 'native-task-meta';
  const receipts = (ticket.delivery ?? []).filter(fact => fact.ticket_id !== ticket.ticket_id);
  const own = ticket.delivery?.find(fact => fact.ticket_id === ticket.ticket_id);
  delivery.textContent = receipts.length ? `Accepted in ${receipts.map(fact => `#${fact.ticket_id}`).join(', ')}`
    : own?.dev_commit ? `Integrated · ${own.dev_commit.slice(0, 8)}`
    : own ? 'Own acceptance recorded'
    : taskStatus(ticket) === 'integrated' ? 'Delivery evidence unavailable' : '';
  if (delivery.textContent) element.append(delivery);
  const footer = document.createElement('div');
  footer.className = 'native-task-footer';
  const facts = document.createElement('span');
  facts.textContent = children.length
    ? ticket.progress ? `${ticket.progress.completed}/${ticket.progress.total} children delivered` : `${children.length} child tasks`
    : `${ticket.dependencies.length} dependencies`;
  footer.append(facts);
  if (children.length) {
    const button = document.createElement('button');
    button.textContent = open ? 'Collapse' : 'Expand';
    button.setAttribute('aria-label', `${button.textContent} ${ticket.title}`);
    button.setAttribute('aria-expanded', String(open));
    button.onclick = event => { event.stopPropagation(); toggle(); };
    footer.append(button);
  } else if (ticket.parent_known === false || ticket.parent_id === undefined) {
    const unknown = document.createElement('span');
    unknown.textContent = 'Parent unknown';
    footer.append(unknown);
  }
  element.append(footer);
  // Card controls do not start an editor drag or its deferred edge rerouting.
  element.onmousedown = event => event.stopPropagation();
  element.onclick = () => select();
  return element;
}

/** Own the read-only X6 canvas; selection never changes its cells or layout. */
export const TaskCanvas = forwardRef<TaskCanvasHandle, Props>(function TaskCanvas(props, ref) {
  const container = useRef<HTMLDivElement>(null);
  const engine = useRef<X6 | null>(null);
  const minimap = useRef<HTMLDivElement>(null);
  const current = useRef(props);
  current.current = props;
  const projection = useRef<ReturnType<typeof monitorGraph> | null>(null);
  const cards = useRef(new Map<string, HTMLElement>());
  const first = useRef(true);
  const pendingLocate = useRef<string | null>(null);
  const pendingToggle = useRef<string | null>(null);
  const pathLabel = useRef<HTMLOutputElement>(null);
  // Polling unchanged native facts must not rebuild cells or move the viewport.
  const topology = JSON.stringify([props.projectName, props.graph.tickets, [...props.expanded].sort()]);

  function fit(minScale = .05): void {
    const graph = engine.current;
    if (!graph || !container.current?.clientWidth) return;
    graph.zoomToFit({ padding: 36, minScale, maxScale: 1, useCellGeometry: false });
    graph.positionContent('top-left', { useCellGeometry: false });
    const translation = graph.translate();
    graph.translate(translation.tx + 36, translation.ty + 36);
  }
  function locate(id: string): void {
    const graph = engine.current;
    const cell = graph?.getCellById(id);
    if (!graph || !cell) { pendingLocate.current = id; return; }
    graph.zoomTo(1);
    graph.centerCell(cell);
    pendingLocate.current = null;
  }
  useImperativeHandle(ref, () => ({ fit, locate }));

  useEffect(() => {
    const graph = new X6({ container: container.current!, autoResize: true,
      background: { color: '#f7f8fa' }, grid: { visible: true, size: 20 },
      interacting: false, panning: { enabled: true, eventTypes: ['leftMouseDown', 'mouseWheel'] },
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'], minScale: .1, maxScale: 2 },
      connecting: { connectionPoint: 'anchor', router: { name: 'metro', args: {
        ...taskRouterOptions, startDirections: ['right'], endDirections: ['left'],
      } }, connector: { name: 'jumpover', args: { type: 'gap', size: 6, radius: 8 } } },
    });
    graph.use(new MiniMap({ container: minimap.current!, width: 220, height: 140,
      graphOptions: { createCellView: cell => cell.isNode() ? MapNodeView : null } }));
    engine.current = graph;
    graph.on('blank:click', () => current.current.select(null));
    // A single readable label avoids collisions inside dense routing channels.
    graph.on('edge:mouseenter', ({ edge }) => {
      const data = edge.getData<MonitorEdge>();
      const title = (id: string) => current.current.graph.tickets.find(ticket => ticket.ticket_id === id)?.title ?? '';
      if (pathLabel.current) pathLabel.current.textContent = data.relations.map(item => `#${item.source} ${title(item.source)} ${item.kind === 'replacement' ? 'replaced by' : item.kind === 'acceptance' ? 'accepted into' : '→'} #${item.target} ${title(item.target)}${item.event_id ? ` · ${item.event_id}` : ''}`).join(' · ');
    });
    graph.on('edge:mouseleave', () => { if (pathLabel.current) pathLabel.current.textContent = ''; });
    return () => { graph.dispose(); engine.current = null; };
  }, []);

  useEffect(() => {
    const graph = engine.current!;
    const data = current.current;
    const children = taskChildren(data.graph);
    const tickets = new Map(data.graph.tickets.map(ticket => [ticket.ticket_id, ticket]));
    const sizes: Record<string, Size> = {};
    const measure = document.createElement('div');
    measure.className = 'native-task-measure';
    container.current!.append(measure);
    cards.current.clear();
    if (pathLabel.current) pathLabel.current.textContent = '';
    for (const ticket of data.graph.tickets) {
      const element = card(ticket, children.get(ticket.ticket_id)!.map(id => tickets.get(id)!), data.expanded.has(ticket.ticket_id),
        () => current.current.select(ticket.ticket_id), () => {
          pendingToggle.current = ticket.ticket_id;
          current.current.toggle(ticket.ticket_id);
        });
      measure.append(element);
      sizes[ticket.ticket_id] = { width: 320, height: Math.ceil(element.getBoundingClientRect().height) };
      cards.current.set(ticket.ticket_id, element);
    }
    // Reserve ports for visible directed pairs, not hidden internal endpoints.
    const preliminary = monitorGraph(data.graph, data.expanded, sizes);
    for (const node of preliminary.nodes) {
      const outgoing = preliminary.edges.filter(edge => edge.source !== edge.target && (edge.source === node.id || edge.kind === 'acceptance' && edge.target === node.id)).length;
      const incoming = preliminary.edges.filter(edge => edge.target === node.id && edge.source !== edge.target).length;
      sizes[node.id].height = Math.max(sizes[node.id].height, (Math.max(outgoing, incoming) + 1) * 18);
    }
    const result = monitorGraph(data.graph, data.expanded, sizes);
    projection.current = result;
    const visibleEdges = result.edges.filter(edge => edge.source !== edge.target);
    const terminals = dependencyTerminals(result.nodes, visibleEdges);
    const cells: Cell[] = [];
    if (result.nodes.length) {
      const bounds = projectBounds(result.nodes);
      // View-only containment, never a Ticket or an execution dependency.
      cells.push(graph.createNode({ id: 'project-frame', shape: 'task-frame', ...bounds, zIndex: -4,
        attrs: { body: { fill: '#f8fafc', stroke: '#94a3b8', strokeWidth: 2, pointerEvents: 'none' } } }));
      cells.push(graph.createNode({ id: 'project-heading', shape: 'task-frame',
        x: bounds.x + 16, y: bounds.y + 12, width: Math.min(760, bounds.width - 32), height: 48, zIndex: -3,
        attrs: { body: { fill: 'none', stroke: 'none', pointerEvents: 'none' },
          label: { text: `Project · ${data.projectName}`, textAnchor: 'start', refX: 16,
            fontSize: 16, fontWeight: 600, fill: '#334155', pointerEvents: 'none' } } }));
    }
    for (const node of result.nodes) {
      if (node.frame) cells.push(graph.createNode({ id: `frame:${node.id}`, shape: 'task-frame',
        x: node.x - 12, y: node.y - 12, width: node.frame.width + 24, height: node.frame.height + 24, zIndex: -2 }));
      const element = cards.current.get(node.id)!;
      element.style.height = `${node.height}px`;
      const port = { attrs: { circle: { r: 3, magnet: false, fill: '#71849a', stroke: '#fff', strokeWidth: 1 } } };
      cells.push(graph.createNode({ id: node.id, shape: 'native-task', x: node.x, y: node.y,
        width: node.width, height: node.height, zIndex: 2, data: { element },
        ports: { groups: { in: { position: 'absolute', ...port }, out: { position: 'absolute', ...port } },
          items: visibleEdges.flatMap(edge => [
            ...(edge.source === node.id ? [{ id: `out:${edge.id}`, group: 'out', args: terminals.get(edge.id)!.source }] : []),
            ...(edge.target === node.id ? [{ id: `in:${edge.id}`, group: 'in', args: terminals.get(edge.id)!.target }] : []),
          ]) },
      }));
    }
    for (const edge of visibleEdges) {
      // Explicit normal terminal segments leave X6 free to avoid other cards.
      cells.push(graph.createEdge({ id: edge.id,
      source: { cell: edge.source, port: `out:${edge.id}` }, target: { cell: edge.target, port: `in:${edge.id}` },
      ...(edge.kind === 'acceptance' ? { router: { name: 'metro', args: { ...taskRouterOptions, startDirections: ['right'], endDirections: ['right'] } } } : {}),
      zIndex: 1, data: edge, vertices: terminals.get(edge.id)!.vertices,
      attrs: { line: { stroke: edge.kind === 'replacement' ? '#986528' : edge.kind === 'acceptance' ? '#178271' : '#8192a6',
        strokeDasharray: edge.kind === 'replacement' ? '8 5' : edge.kind === 'acceptance' ? '3 3' : '', strokeWidth: 1.6,
        targetMarker: { name: 'block', width: 10, height: 8 } } },
    }));
    }
    graph.once('render:done', () => {
      if (pendingLocate.current) locate(pendingLocate.current);
      else if (pendingToggle.current) {
        // Explicit expansion reveals the heading and first children at reading scale.
        const cell = graph.getCellById(pendingToggle.current);
        if (cell) {
          graph.zoomTo(Math.max(.8, graph.zoom()));
          graph.positionCell(cell, 'top-left');
          const translation = graph.translate();
          graph.translate(translation.tx + 36, translation.ty + 36);
          cards.current.get(pendingToggle.current)?.querySelector<HTMLButtonElement>('.native-task-footer button')?.focus({ preventScroll: true });
        }
        pendingToggle.current = null;
      } else if (first.current && result.nodes.length && current.current.active) { fit(.65); first.current = false; }
    });
    graph.resetCells(cells);
    measure.remove();
  }, [topology]);

  useEffect(() => {
    const graph = engine.current;
    const result = projection.current;
    if (!graph || !result) return;
    const focus = taskFocus(props.graph, props.selected);
    const emphasized = new Set([...focus].map(id => result.endpoints.get(id)));
    const matches = new Set([...props.matches].map(id => result.endpoints.get(id)));
    for (const node of result.nodes) {
      const element = cards.current.get(node.id)!;
      const selected = node.id === props.selected;
      element.classList.toggle('selected', selected);
      element.classList.toggle('related', !!props.selected && emphasized.has(node.id));
      element.querySelector('button')!.setAttribute('aria-pressed', String(selected));
      element.style.opacity = matches.has(node.id) && emphasized.has(node.id) ? '1' : '.25';
    }
    for (const edge of graph.getEdges()) {
      const data = edge.getData<MonitorEdge>();
      const related = data.relations.some(item => focus.has(item.source) && focus.has(item.target));
      const visible = data.relations.some(item => focus.has(item.source) && focus.has(item.target)
        && props.matches.has(item.source) && props.matches.has(item.target));
      edge.attr('line/stroke', data.kind === 'replacement' ? '#986528' : data.kind === 'acceptance' ? '#178271' : props.selected && related ? '#365f9c' : '#8192a6');
      edge.attr('line/strokeWidth', props.selected && related ? 3 : 1.6);
      edge.attr('line/opacity', visible ? 1 : .15);
    }
  }, [topology, props.selected, props.matches]);

  useEffect(() => {
    if (props.active && first.current && projection.current?.nodes.length) { fit(.65); first.current = false; }
  }, [props.active]);

  return <><div className="native-task-canvas" ref={container} aria-label="Native task canvas"/>
    <div className="native-minimap" ref={minimap} aria-label="Task map navigator"/>
    <div className="native-relation-legend"><span>→ Dependency</span><span>⇢ Replacement</span><span>⋯▶ Accepted delivery</span></div>
    <output ref={pathLabel} className="native-path-label" aria-live="polite"/>
    <div className="native-task-zoom"><button aria-label="Zoom in" onClick={() => engine.current?.zoom(.15)}>+</button>
      <button aria-label="Zoom out" onClick={() => engine.current?.zoom(-.15)}>−</button>
      <span>Drag to pan · Ctrl/⌘ + scroll to zoom</span></div></>;
});
