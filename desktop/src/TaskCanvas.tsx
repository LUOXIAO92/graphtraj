import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Graph as X6, Shape, NodeView, type Cell } from '@antv/x6';
import type { Graph, Task } from '../electron/types';
import { taskFocus, taskRouterOptions, monitorGraph, taskChildren, taskStatus, taskPaths, projectBounds, type Size, type MonitorEdge } from './monitor-graph';
import './task-canvas.css';
import { TaskMiniMap } from './task-minimap';
import { Icon } from './ui';

/** The minimap's fixed size (advice mockup 01); fit() keeps the content above it. */
const MINIMAP = { width: 176, height: 108 } as const;

export type TaskCanvasHandle = { fit: () => void; locate: (id: string) => void };
type Props = { graph: Graph; projectName: string; expanded: ReadonlySet<string>; selected: string | null;
  matches: ReadonlySet<string>; active: boolean; select: (id: string | null) => void; toggle: (id: string) => void };

// X6 attributes are SVG strings that CSS var() cannot reach, so the canvas reads
// the design tokens (tokens.css) whenever it draws, and redraws on theme change.
const tokenNames = { surface: '--surface', surfaceAlt: '--surface-alt', ink: '--ink', muted: '--muted', faint: '--faint',
  borderStrong: '--border-strong', accent: '--accent-ui', accentInk: '--accent-ink',
  dependency: '--edge-dep', replacement: '--edge-repl', acceptance: '--edge-accept' } as const;
type Palette = Record<keyof typeof tokenNames, string>;
function canvasPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  return Object.fromEntries(Object.entries(tokenNames).map(([key, name]) => [key, style.getPropertyValue(name).trim()])) as Palette;
}
const edgeColor = (kind: string, colors: Palette) => kind === 'replacement' ? colors.replacement
  : kind === 'acceptance' ? colors.acceptance : colors.dependency;

// Reuse the shared model without moving the main canvas HTML into the minimap.
class MapNodeView extends NodeView {
  update(): void {
    super.update();
    // HTML nodes carry invisible SVG bodies. Override only this thumbnail DOM,
    // never the shared model or the main canvas node attributes.
    if (this.cell.shape === 'native-task') {
      const colors = canvasPalette(this.graph.container);
      const body = this.container.querySelector('rect');
      body?.setAttribute('fill', colors.faint);
      body?.setAttribute('stroke', colors.muted);
    }
  }
  protected renderMarkup(): void {
    const colors = canvasPalette(this.graph.container);
    this.renderJSONMarkup([{ tagName: 'rect', selector: 'body', attrs: {
      width: this.cell.size().width, height: this.cell.size().height, fill: colors.faint, stroke: colors.muted,
    } }]);
  }
}

Shape.HTML.register({ shape: 'native-task', html: cell => cell.getData().element });
X6.registerNode('task-frame', { inherit: 'rect', attrs: { body: { strokeWidth: 1, rx: 12, ry: 12 } } });

/** Build a text-only card shared by measurement and X6; task content is never HTML. */
function card(task: Task, children: Task[], open: boolean, select: () => void, toggle: () => void): HTMLDivElement {
  const element = document.createElement('div');
  element.className = 'native-task-card';
  element.dataset.taskId = task.task_id;
  element.setAttribute('role', 'group');
  element.setAttribute('aria-label', task.title);
  // V5: a '#id + status chip' row above the title. V3: the unchanged status word sits in the
  // same chip + shape as ui.tsx Status. The row's text stays `#id · status[ · → #ids]`; the
  // separator is only hidden visually and CSS puts the chip at the row's right end.
  const meta = document.createElement('div');
  meta.className = 'native-task-meta native-task-top';
  const status = taskStatus(task);
  const tone = status.toLowerCase().replaceAll(' ', '-');
  element.dataset.status = tone;
  const id = document.createElement('span');
  id.className = 'native-task-id';
  id.textContent = `#${task.task_id}`;
  const separator = document.createElement('span');
  separator.className = 'native-task-separator';
  separator.textContent = ' · ';
  const chip = document.createElement('span');
  chip.className = `status status-${tone}`;
  const dot = document.createElement('span');
  dot.className = 'status-dot';
  chip.append(dot, status);
  meta.append(id, separator, chip);
  if (task.replaced_by.length) {
    const replaced = document.createElement('span');
    replaced.className = 'native-task-replaced';
    replaced.textContent = ` · → ${task.replaced_by.map(item => `#${item}`).join(', ')}`;
    meta.append(replaced);
  }
  element.append(meta);
  const title = document.createElement('button');
  title.className = 'native-task-title';
  title.textContent = task.title;
  title.onclick = event => { event.stopPropagation(); select(); };
  element.append(title);
  const delivery = document.createElement('div');
  delivery.className = 'native-task-meta';
  const receipts = (task.delivery ?? []).filter(fact => fact.task_id !== task.task_id);
  const own = task.delivery?.find(fact => fact.task_id === task.task_id);
  delivery.textContent = receipts.length ? `Accepted in ${receipts.map(fact => `#${fact.task_id}`).join(', ')}`
    : own?.dev_commit ? `Integrated · ${own.dev_commit.slice(0, 8)}`
    : own ? 'Own acceptance recorded'
    : taskStatus(task) === 'integrated' ? 'Delivery evidence unavailable' : '';
  if (delivery.textContent) element.append(delivery);
  const footer = document.createElement('div');
  footer.className = 'native-task-footer';
  const facts = document.createElement('span');
  facts.textContent = children.length
    ? task.progress ? `${task.progress.completed}/${task.progress.total} children delivered` : `${children.length} child tasks`
    : `${task.dependencies.length} dependencies`;
  footer.append(facts);
  if (children.length) {
    const button = document.createElement('button');
    button.textContent = open ? 'Collapse' : 'Expand';
    button.setAttribute('aria-label', `${button.textContent} ${task.title}`);
    button.setAttribute('aria-expanded', String(open));
    button.onclick = event => { event.stopPropagation(); toggle(); };
    footer.append(button);
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
  // The system light/dark theme recolours the X6 cells (tokens are read when drawing).
  const [theme, setTheme] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const [zoom, setZoom] = useState(1);
  // Polling unchanged native facts must not rebuild cells or move the viewport.
  const topology = JSON.stringify([props.projectName, props.graph.tasks, [...props.expanded].sort(), theme]);

  function fit(minScale = .05): void {
    const graph = engine.current;
    if (!graph || !container.current?.clientWidth) return;
    // V5: the bottom overlays (legend and zoom at the left, the minimap at the right) take
    // MINIMAP.height + 16 px; the fitted content keeps clear of them (626 leftover at 1000 px).
    graph.zoomToFit({ padding: { top: 36, left: 36, right: 36, bottom: MINIMAP.height + 44 }, minScale, maxScale: 1, useCellGeometry: false });
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
    // The canvas background comes from CSS (.native-task-canvas uses --bg); the grid dots are drawn by X6.
    const graph = new X6({ container: container.current!, autoResize: true,
      grid: { visible: true, size: 20, type: 'dot', args: { color: canvasPalette(container.current!).borderStrong, thickness: 1 } },
      interacting: false, panning: { enabled: true, eventTypes: ['leftMouseDown', 'mouseWheel'] },
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'], minScale: .1, maxScale: 2 },
      connecting: { connectionPoint: 'anchor', router: { name: 'metro', args: {
        ...taskRouterOptions, startDirections: ['right'], endDirections: ['left'],
      } }, connector: { name: 'jumpover', args: { type: 'gap', size: 6, radius: 8 } } },
    });
    graph.use(new TaskMiniMap({ container: minimap.current!, ...MINIMAP,
      graphOptions: { createCellView: cell => cell.isNode() ? MapNodeView : null } }));
    engine.current = graph;
    graph.on('blank:click', () => current.current.select(null));
    // A single readable label avoids collisions inside dense routing channels.
    graph.on('edge:mouseenter', ({ edge }) => {
      const data = edge.getData<MonitorEdge>();
      const title = (id: string) => current.current.graph.tasks.find(task => task.task_id === id)?.title ?? '';
      if (pathLabel.current) pathLabel.current.textContent = data.relations.map(item => `#${item.source} ${title(item.source)} ${item.kind === 'replacement' ? 'replaced by' : item.kind === 'acceptance' ? 'accepted into' : '→'} #${item.target} ${title(item.target)}${item.event_id ? ` · ${item.event_id}` : ''}`).join(' · ');
    });
    graph.on('edge:mouseleave', () => { if (pathLabel.current) pathLabel.current.textContent = ''; });
    graph.on('scale', ({ sx }) => setZoom(sx));
    const media = matchMedia('(prefers-color-scheme: dark)');
    const follow = () => setTheme(media.matches ? 'dark' : 'light');
    media.addEventListener('change', follow);
    return () => { media.removeEventListener('change', follow); graph.dispose(); engine.current = null; };
  }, []);

  useEffect(() => {
    const graph = engine.current!;
    const data = current.current;
    const colors = canvasPalette(container.current!);
    graph.drawGrid({ type: 'dot', args: { color: colors.borderStrong, thickness: 1 } });
    const children = taskChildren(data.graph);
    const tasks = new Map(data.graph.tasks.map(task => [task.task_id, task]));
    const sizes: Record<string, Size> = {};
    const measure = document.createElement('div');
    measure.className = 'native-task-measure';
    container.current!.append(measure);
    cards.current.clear();
    if (pathLabel.current) pathLabel.current.textContent = '';
    for (const task of data.graph.tasks) {
      const element = card(task, children.get(task.task_id)!.map(id => tasks.get(id)!), data.expanded.has(task.task_id),
        () => current.current.select(task.task_id), () => {
          pendingToggle.current = task.task_id;
          current.current.toggle(task.task_id);
        });
      measure.append(element);
      sizes[task.task_id] = { width: 320, height: Math.ceil(element.getBoundingClientRect().height) };
      cards.current.set(task.task_id, element);
    }
    // Reserve ports for visible directed pairs, not hidden internal endpoints.
    const preliminary = monitorGraph(data.graph, data.expanded, sizes);
    for (const node of preliminary.nodes) {
      const outgoing = preliminary.edges.filter(edge => edge.source !== edge.target && edge.source === node.id).length;
      const incoming = preliminary.edges.filter(edge => edge.target === node.id && edge.source !== edge.target).length;
      sizes[node.id].height = Math.max(sizes[node.id].height, (Math.max(outgoing, incoming) + 1) * 18);
    }
    const result = monitorGraph(data.graph, data.expanded, sizes);
    projection.current = result;
    const visibleEdges = result.edges.filter(edge => edge.source !== edge.target);
    const drawing = taskPaths(result.nodes, visibleEdges);
    const cells: Cell[] = [];
    if (result.nodes.length) {
      const bounds = projectBounds(result.nodes);
      // View-only containment, never a Task or an execution dependency.
      cells.push(graph.createNode({ id: 'project-frame', shape: 'task-frame', ...bounds, zIndex: -4,
        attrs: { body: { fill: colors.surface, stroke: colors.borderStrong, strokeWidth: 2, pointerEvents: 'none' } } }));
      cells.push(graph.createNode({ id: 'project-heading', shape: 'task-frame',
        x: bounds.x + 16, y: bounds.y + 12, width: Math.min(760, bounds.width - 32), height: 48, zIndex: -3,
        attrs: { body: { fill: 'none', stroke: 'none', pointerEvents: 'none' },
          label: { text: `Project · ${data.projectName}`, textAnchor: 'start', refX: 16,
            fontSize: 16, fontWeight: 600, fill: colors.ink, pointerEvents: 'none' } } }));
    }
    for (const node of result.nodes) {
      if (node.frame) cells.push(graph.createNode({ id: `frame:${node.id}`, shape: 'task-frame',
        ...node.frame, zIndex: -2, attrs: { body: { fill: colors.surfaceAlt, fillOpacity: .5, stroke: colors.borderStrong } } }));
      const element = cards.current.get(node.id)!;
      element.style.height = `${node.height}px`;
      const port = { attrs: { circle: { r: 3, magnet: false, fill: colors.dependency, stroke: colors.surface, strokeWidth: 1 } } };
      cells.push(graph.createNode({ id: node.id, shape: 'native-task', x: node.x, y: node.y,
        width: node.width, height: node.height, zIndex: 2, data: { element },
        ports: { groups: { in: { position: 'absolute', ...port }, out: { position: 'absolute', ...port } },
          items: drawing.ports.get(node.id)! },
      }));
    }
    for (const path of drawing.paths) {
      const edge = path.data;
      // Shared receipt segments are drawn once; only the final entry has an arrow.
      cells.push(graph.createEdge({ id: path.id,
      source: path.source, target: path.target,
      zIndex: 1, data: edge, vertices: path.vertices,
      ...(path.direct ? { router: { name: 'normal' } } : !('cell' in path.target) ? {
        router: { name: 'metro', args: { ...taskRouterOptions,
          startDirections: ['right'], endDirections: ['left', 'right', 'top', 'bottom'] } },
      } : {}),
      ...(path.arrow && edge.kinds.length > 1 ? { labels: [{ position: .5, attrs: {
        label: { text: edge.kinds.map(kind => kind === 'dependency' ? 'Dependency' : kind === 'acceptance' ? 'Accepted delivery' : 'Replacement').join(' + '), fontSize: 11, fill: colors.accentInk },
        body: { fill: colors.surface, stroke: colors.borderStrong, rx: 3, ry: 3 },
      } }] } : {}),
      attrs: { line: { stroke: edgeColor(edge.kind, colors),
        strokeDasharray: edge.kind === 'replacement' ? '8 5' : edge.kind === 'acceptance' ? '3 3' : '', strokeWidth: 1.6,
        targetMarker: path.arrow ? { name: 'block', width: 10, height: 8 } : null } },
    }));
    }
    graph.once('render:done', () => {
      if (pendingLocate.current) locate(pendingLocate.current);
      else if (pendingToggle.current) {
        // Keep the receiving summary at the right, with its inputs visible to the left.
        const cell = graph.getCellById(pendingToggle.current);
        if (cell) {
          graph.zoomTo(Math.max(.8, graph.zoom()));
          graph.positionCell(cell, 'top-right');
          const translation = graph.translate();
          graph.translate(translation.tx - 36, translation.ty + 36);
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
    const colors = canvasPalette(container.current!);
    const focus = taskFocus(props.graph, props.selected);
    const emphasized = new Set([...focus].map(id => result.endpoints.get(id)));
    const matches = new Set([...props.matches].map(id => result.endpoints.get(id)));
    for (const node of result.nodes) {
      const element = cards.current.get(node.id)!;
      const selected = node.id === props.selected;
      element.classList.toggle('selected', selected);
      element.classList.toggle('related', !!props.selected && emphasized.has(node.id));
      element.querySelector('button')!.setAttribute('aria-pressed', String(selected));
      element.style.opacity = matches.has(node.id) && emphasized.has(node.id) ? '1' : '.5';
    }
    for (const edge of graph.getEdges()) {
      const data = edge.getData<MonitorEdge>();
      const related = data.relations.some(item => focus.has(item.source) && focus.has(item.target));
      const visible = data.relations.some(item => focus.has(item.source) && focus.has(item.target)
        && props.matches.has(item.source) && props.matches.has(item.target));
      edge.attr('line/stroke', data.kind !== 'replacement' && data.kind !== 'acceptance' && props.selected && related ? colors.accent : edgeColor(data.kind, colors));
      edge.attr('line/strokeWidth', props.selected && related ? 3 : 1.6);
      edge.attr('line/opacity', visible ? 1 : .15);
    }
  }, [topology, props.selected, props.matches]);

  useEffect(() => {
    if (props.active && first.current && projection.current?.nodes.length) { fit(.65); first.current = false; }
  }, [props.active]);

  // V5: one legend with the real line types (the same dash patterns as the edges above), bottom-left
  // above the zoom controls; the minimap sits bottom-right.
  return <><div className="native-task-canvas" ref={container} aria-label="Native task canvas"/>
    <div className="native-minimap" ref={minimap} aria-label="Task map navigator"/>
    <div className="native-canvas-overlays">
      <div className="native-relation-legend">
        <span className="legend-dependency"><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4"/></svg>Dependency</span>
        <span className="legend-replacement"><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" strokeDasharray="8 5"/></svg>Replacement</span>
        <span className="legend-acceptance"><svg width="28" height="8" aria-hidden="true"><line x1="0" y1="4" x2="28" y2="4" strokeDasharray="3 3"/></svg>Accepted delivery</span>
        <span className="legend-crossing"><svg width="28" height="8" aria-hidden="true"><path d="M0 6H9a5 5 0 0 1 10 0H28"/></svg>Crossing</span>
      </div>
      <div className="native-task-zoom" title="Drag to pan · Ctrl/⌘ + scroll to zoom">
        <button aria-label="Zoom out" onClick={() => engine.current?.zoom(-.15)}><Icon name="minus" size={16}/></button>
        <span>{Math.round(zoom * 100)}%</span>
        <button aria-label="Zoom in" onClick={() => engine.current?.zoom(.15)}><Icon name="plus" size={16}/></button>
      </div>
    </div>
    <output ref={pathLabel} className="native-path-label" aria-live="polite"/></>;
});
