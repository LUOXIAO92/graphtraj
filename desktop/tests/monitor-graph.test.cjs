const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let monitorGraph, taskFocus, dependencyTerminals, taskStatus, projectBounds;
test.before(async () => {
  const result = await build({ entryPoints: [path.join(__dirname, '../src/monitor-graph.ts')],
    bundle: true, platform: 'node', format: 'cjs', write: false });
  const module = { exports: {} };
  vm.runInNewContext(result.outputFiles[0].text, { module, exports: module.exports, structuredClone });
  ({ monitorGraph, taskFocus, dependencyTerminals, taskStatus, projectBounds } = module.exports);
});
const task = (id, parent_id, dependencies = []) => ({ ticket_id: id, title: `Real title ${id}`, parent_id,
  schema_version: 2, ticket_name: `task-${id}`, dependencies, active: true, status: 'pending', replaced_by: [] });
const input = () => ({ tickets: [task('A', null), task('B', null), task('C', 'A'),
  task('1', 'C'), task('2', 'B', ['1']), task('3', 'C', ['2']), task('4', null, ['3']), task('unrelated', null)] });

test('native hierarchy is lossless across nested expansion, contraction and projected return edges', () => {
  const graph = input(), original = JSON.stringify(graph);
  for (const open of [[], ['A'], ['A', 'C'], ['A', 'B', 'C'], []]) {
    const result = monitorGraph(graph, new Set(open));
    const ids = new Set(result.nodes.map(node => node.id));
    assert.equal(ids.size, result.nodes.length);
    assert.equal(ids.has('C'), open.includes('A'));
    assert.equal(ids.has('1'), open.includes('A') && open.includes('C'));
    assert.equal(result.edges.length, 3);
    for (const edge of result.edges) {
      assert.ok(ids.has(edge.source) && ids.has(edge.target));
      assert.ok(graph.tickets.find(ticket => ticket.ticket_id === edge.relations[0].target).dependencies.includes(edge.relations[0].source));
    }
    const first = result.edges.find(edge => edge.relations.some(item => item.source === '1'));
    assert.equal(first.source, open.includes('C') ? '1' : open.includes('A') ? 'C' : 'A');
    assert.equal(first.target, open.includes('B') ? '2' : 'B');
    assert.equal(JSON.stringify(graph), original);
  }
  const collapsed = monitorGraph(graph, new Set());
  assert.ok(collapsed.edges.some(edge => edge.source === 'A' && edge.target === 'B'));
  assert.ok(collapsed.edges.some(edge => edge.source === 'B' && edge.target === 'A'));
});

test('measured long titles and nested frames have separate sibling space', () => {
  const graph = input();
  const result = monitorGraph(graph, new Set(['A', 'B', 'C']), { '1': { width: 320, height: 320 } });
  for (const node of result.nodes) for (const other of result.nodes) {
    if (node.id === other.id || node.ticket.parent_id !== other.ticket.parent_id) continue;
    const a = node.frame ?? node, b = other.frame ?? other;
    assert.ok(a.x + a.width + 60 <= b.x || b.x + b.width + 60 <= a.x ||
      a.y + a.height + 60 <= b.y || b.y + b.height + 60 <= a.y);
  }
  for (const node of result.nodes.filter(node => node.ticket.parent_id)) {
    const parent = result.nodes.find(other => other.id === node.ticket.parent_id);
    assert.ok(parent.frame);
    const bounds = node.frame ?? node;
    assert.ok(bounds.x >= parent.frame.x && bounds.y >= parent.frame.y);
    assert.ok(bounds.x + bounds.width < parent.x, "the summary receives results at the delivery side");
    assert.ok(bounds.y + bounds.height <= parent.frame.y + parent.frame.height);
  }
});

test('selection traces real dependencies and selected summary internals, excluding unrelated branches', () => {
  const graph = input();
  assert.deepEqual([...taskFocus(graph, 'A')].sort(), ['1', '2', '3', '4', 'A', 'C']);
  assert.deepEqual([...taskFocus(graph, '2')].sort(), ['1', '2', '3', '4']);
  assert.equal(taskFocus(graph, null).size, graph.tickets.length);
});

test('legacy unknown parents remain standalone; old display groups cannot create parents', () => {
  const graph = { tickets: [task('1', undefined), task('2', undefined, ['1'])],
    groups: [{ id: 'invented', title: 'Body derived grouping', ticket_ids: ['1', '2'] }] };
  const result = monitorGraph(graph, new Set());
  assert.deepEqual(Array.from(result.nodes, node => node.id), ['1', '2']);
  assert.ok(result.nodes.every(node => node.children.length === 0));
});


test('dependency ranks retain inactive historical tasks', () => {
  const graph = { tickets: [task('1', null), task('2', null), task('3', null, ['1', '2']),
    { ...task('4', null, ['3']), active: false }] };
  const { nodes } = monitorGraph(graph, new Set());
  const positions = Object.fromEntries(nodes.map(node => [node.id, node]));
  assert.equal(nodes.length, 4);
  assert.equal(positions['1'].x, positions['2'].x);
  assert.notEqual(positions['1'].y, positions['2'].y);
  assert.ok(positions['3'].x > positions['1'].x);
  assert.ok(positions['4'].x > positions['3'].x);
});

test('parallel collapsed dependencies retain every native edge with finite routes', () => {
  const graph = { tickets: [task('126', null), task('127', null), task('147', null),
    task('133', '127'), task('143', '127'), task('139', '127'),
    task('148', '147', ['133', '143']), task('150', '147', ['139'])] };
  const original = JSON.stringify(graph);
  for (const expanded of [[], ['127'], ['127', '147']]) {
    const view = monitorGraph(graph, new Set(expanded));
    assert.equal(view.edges.length, expanded.length ? 3 : 1);
    assert.equal(new Set(view.edges.map(edge => edge.id)).size, view.edges.length);
    assert.equal(view.edges.flatMap(edge => edge.relations).length, 3);
    assert.ok(view.nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y)));
    assert.ok(view.edges.every(edge => edge.vertices.every(point => Number.isFinite(point.x) && Number.isFinite(point.y))));
    for (const edge of view.edges) assert.ok(graph.tickets.find(ticket => ticket.ticket_id === edge.relations[0].target).dependencies.includes(edge.relations[0].source));
  }
  assert.equal(JSON.stringify(graph), original);
});


test('collapsed visible pairs aggregate only matching directions and restore real endpoints on expansion', () => {
  const graph = { tickets: [task('252', null), task('260', null), task('275', null), task('270', null),
    task('a', '252'), task('b', '252'), task('261', '260', ['a']), task('269', '260', ['b']),
    task('264', '260', ['261', '269']), task('p', '275', ['261', '264']),
    task('q', '270', ['269']), task('r', '252', ['q'])] };
  const original = JSON.stringify(graph);
  const collapsed = monitorGraph(graph, new Set());
  assert.equal(collapsed.edges.filter(e => e.source === '252' && e.target === '260').length, 1);
  assert.equal(collapsed.edges.find(e => e.source === '252' && e.target === '260').relations.length, 2);
  assert.equal(collapsed.edges.find(e => e.source === '260' && e.target === '275').relations.length, 2);
  assert.ok(collapsed.edges.some(e => e.source === '260' && e.target === '270'));
  assert.ok(collapsed.edges.some(e => e.source === '270' && e.target === '252'));
  const expanded = monitorGraph(graph, new Set(['252', '260', '275', '270']));
  assert.deepEqual(Array.from(expanded.edges.filter(e => e.target === '264'), e => e.source).sort(), ['261', '269']);
  for (const view of [collapsed, expanded]) {
    const native = view.edges.flatMap(e => e.relations.map(d => `${d.source}->${d.target}`)).sort();
    assert.deepEqual(Array.from(native), graph.tickets.flatMap(t => t.dependencies.map(d => `${d}->${t.ticket_id}`)).sort());
  }
  assert.equal(JSON.stringify(graph), original);
});


test('ports follow opposite card position and leave horizontal clear terminal segments', () => {
  const graph = { tickets: [task('252', null), task('260', null, ['252']), task('283', null, ['252', '260'])] };
  const view = monitorGraph(graph, new Set());
  // Source insertion order deliberately opposes visual target order.
  const upper = view.nodes.find(n => n.id === '283'), lower = view.nodes.find(n => n.id === '260');
  upper.y = 0; lower.y = 500;
  const ports = dependencyTerminals(view.nodes, view.edges);
  const outgoing = view.edges.filter(e => e.source === '252');
  assert.ok(ports.get(outgoing.find(e => e.target === '283').id).source.y < ports.get(outgoing.find(e => e.target === '260').id).source.y);
  for (const edge of view.edges) {
    const p = ports.get(edge.id), source = view.nodes.find(n => n.id === edge.source), target = view.nodes.find(n => n.id === edge.target);
    assert.equal(p.source.x, source.width); assert.equal(p.target.x, 0);
    assert.equal(p.vertices[0].y, source.y + p.source.y);
    assert.equal(p.vertices[1].y, target.y + p.target.y);
    assert.ok(p.vertices[0].x >= source.x + source.width + 40);
    assert.ok(p.vertices[1].x <= target.x - 40);
  }
});

test('cancelled and superseded tasks never appear under their old execution status', () => {
  for (const status of ['pending', 'implementing', 'reworking', 'reviewing', 'integrated']) {
    for (const disposition of ['cancelled', 'superseded']) {
      assert.equal(taskStatus({ ...task('old', null), status, disposition, active: false }), disposition);
    }
    assert.equal(taskStatus({ ...task('current', null), status, disposition: 'active' }), status);
  }
});

test('expanded summary exits leave from the delivery side of its frame', () => {
  const graph = { tickets: [task('226', null), task('227', '226'),
    task('228', '226', ['227']), task('236', null, ['226']),
    task('240', null, ['226', '236'])] };
  const view = monitorGraph(graph, new Set(['226']));
  const source = view.nodes.find(node => node.id === '226');
  const routes = dependencyTerminals(view.nodes, view.edges);
  const exits = view.edges.filter(edge => edge.source === '226').map(edge => routes.get(edge.id));
  assert.equal(exits.length, 2);
  assert.notEqual(exits[0].source.y, exits[1].source.y);
  for (const route of exits) {
    assert.equal(route.vertices.length, 2);
    assert.equal(route.vertices[0].y, source.y + route.source.y);
    assert.ok(route.vertices[0].x > source.frame.x + source.frame.width);
  }
});

test('replacement chains preserve direction, kinds and native endpoints across summaries', () => {
  const graph = { tickets: [task('A', null), task('B', null),
    { ...task('101', 'A'), active: false, replaced_by: ['102'] },
    { ...task('102', 'B'), active: false, replaced_by: ['103'] }, task('103', 'B'),
    { ...task('104', 'A'), active: false, replaced_by: ['103'] },
    task('105', 'B', ['101']), task('106', 'A', ['103']), task('unrelated', null)] };
  const original = JSON.stringify(graph);
  const collapsed = monitorGraph(graph, new Set());
  const forward = collapsed.edges.filter(edge => edge.source === 'A' && edge.target === 'B');
  assert.equal(forward.length, 1, 'one visible directed pair uses one arrow');
  assert.equal(forward[0].relations.filter(edge => edge.kind === 'replacement').length, 2);
  assert.equal(forward[0].relations.filter(edge => edge.kind === 'dependency').length, 1);
  assert.deepEqual(Array.from(forward[0].kinds).sort(), ['dependency', 'replacement']);
  assert.ok(collapsed.edges.some(edge => edge.source === 'B' && edge.target === 'A' && edge.kind === 'dependency'));
  const expanded = monitorGraph(graph, new Set(['A', 'B']));
  assert.deepEqual(Array.from(expanded.edges.filter(edge => edge.kind === 'replacement'),
    edge => `${edge.source}->${edge.target}`).sort(), ['101->102', '102->103', '104->103']);
  for (const view of [collapsed, expanded]) {
    assert.equal(view.edges.flatMap(edge => edge.relations).length, 5);
    assert.ok(view.nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y)));
  }
  assert.deepEqual(Array.from(taskFocus(graph, '101')).sort(), ['101', '102', '103', '105', '106']);
  assert.ok(taskFocus(graph, '103').has('104'), 'selecting a replacement traces all actual replaced sources');
  assert.equal(JSON.stringify(graph), original);
});


test('a common project boundary contains independent tasks and native nested summary frames', () => {
  const graph = input(), original = JSON.stringify(graph);
  for (const open of [[], ['A', 'B', 'C']]) {
    const view = monitorGraph(graph, new Set(open)), bounds = projectBounds(view.nodes);
    assert.ok(view.nodes.some(node => node.id === 'unrelated'));
    for (const node of view.nodes) {
      const area = node.frame ?? node;
      assert.ok(bounds.x < area.x && bounds.y + 60 < area.y);
      assert.ok(bounds.x + bounds.width > area.x + area.width);
      assert.ok(bounds.y + bounds.height > area.y + area.height);
    }
    assert.equal(view.edges.flatMap(edge => edge.relations).length, 3);
  }
  assert.equal(JSON.stringify(graph), original);
});

test('accepted delivery is an evidenced relation, distinct from membership and execution ordering', () => {
  const graph = { tickets: [task('summary', null), task('next', null, ['summary']),
    { ...task('result', 'summary'), delivery: [{ event: 'ticket-completed', ticket_id: 'summary', event_id: 'accepted-1' }] },
    task('unaccepted', 'summary'),
    { ...task('cross', null), delivery: [{ event: 'ticket-completed', ticket_id: 'summary', event_id: 'accepted-1' }] }] };
  const original = JSON.stringify(graph);
  for (const expanded of [[], ['summary']]) {
    const view = monitorGraph(graph, new Set(expanded));
    const receipts = view.edges.flatMap(e => e.relations).filter(r => r.kind === 'acceptance');
    assert.deepEqual(Array.from(receipts, r => `${r.source}->${r.target}:${r.event_id}`).sort(),
      ['cross->summary:accepted-1', 'result->summary:accepted-1']);
    const edge = view.edges.find(e => e.relations.some(r => r.source === 'result'));
    assert.equal(edge.source, expanded.length ? 'result' : 'summary');
    assert.equal(edge.target, 'summary');
    assert.ok(view.nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y)));
    const terminals = dependencyTerminals(view.nodes, view.edges);
    for (const receipt of view.edges.filter(e => e.kind === 'acceptance' && e.source !== e.target)) {
      const end = terminals.get(receipt.id), target = view.nodes.find(n => n.id === receipt.target);
      assert.equal(end.target.x, 0);
      assert.ok(end.vertices.at(-1).x < target.x);
      assert.equal(end.vertices.at(-1).y, target.y + end.target.y);
    }
  }
  assert.ok(taskFocus(graph, 'result').has('next'));
  assert.ok(!taskFocus(graph, 'result').has('unaccepted'));
  assert.equal(JSON.stringify(graph), original);
});


test('a collapsed dependency and accepted receipt share an arrow while preserving both facts', () => {
  const graph = { tickets: [task('226', null), task('236', null, ['226']),
    { ...task('233', '226'), delivery: [{ event: 'ticket-completed', ticket_id: '236', event_id: 'accept-236' }] }] };
  const collapsed = monitorGraph(graph, new Set());
  assert.equal(collapsed.edges.length, 1);
  assert.deepEqual(Array.from(collapsed.edges[0].kinds).sort(), ['acceptance', 'dependency']);
  assert.equal(collapsed.edges[0].relations.find(r => r.kind === 'acceptance').event_id, 'accept-236');
  const expanded = monitorGraph(graph, new Set(['226']));
  assert.equal(expanded.edges.length, 2);
  assert.ok(expanded.edges.some(e => e.source === '233' && e.target === '236' && e.kind === 'acceptance'));
  assert.ok(expanded.edges.some(e => e.source === '226' && e.target === '236' && e.kind === 'dependency'));
});

test('nested and cross-summary accepted results flow toward their real delivery cards', () => {
  const receipt = target => [{ event: 'ticket-completed', ticket_id: target, event_id: `accepted-${target}` }];
  const graph = { tickets: [task('outer', null),
    { ...task('inner', 'outer'), delivery: receipt('outer') },
    { ...task('first', 'inner'), delivery: receipt('inner') },
    { ...task('last', 'inner', ['first']), delivery: receipt('inner') },
    { ...task('sibling', 'outer'), delivery: receipt('outer') },
    { ...task('external', null), delivery: receipt('outer') },
    task('consumer', null, ['outer'])] };
  const original = JSON.stringify(graph);
  for (const open of [[], ['outer'], ['outer', 'inner']]) {
    const view = monitorGraph(graph, new Set(open));
    const nodes = new Map(view.nodes.map(node => [node.id, node]));
    for (const edge of view.edges.filter(edge => edge.source !== edge.target)) {
      const source = nodes.get(edge.source), target = nodes.get(edge.target);
      assert.ok(source.x + source.width < target.x, `${edge.source} must precede ${edge.target}`);
    }
    assert.equal(view.edges.flatMap(edge => edge.relations).length, 7);
  }
  assert.equal(JSON.stringify(graph), original);
});

test('dense delivery terminals remain in the gap before their summary', () => {
  const graph = { tickets: [task('summary', null), ...Array.from({ length: 24 }, (_, index) => ({
    ...task(String(index), 'summary', index ? [String(index - 1)] : []),
    delivery: [{ event: 'ticket-completed', ticket_id: 'summary', event_id: 'accepted-summary' }],
  }))] };
  const view = monitorGraph(graph, new Set(['summary']), { summary: { width: 320, height: 500 } });
  const last = view.nodes.find(node => node.id === '23'), summary = view.nodes.find(node => node.id === 'summary');
  const terminals = dependencyTerminals(view.nodes, view.edges);
  for (const edge of view.edges.filter(edge => edge.target === 'summary')) {
    const terminal = terminals.get(edge.id).vertices.at(-1);
    assert.ok(terminal.x > last.x + last.width, 'receipt waypoint must not enter the final result card');
    assert.ok(terminal.x <= summary.x - 40, 'leave a straight visible arrow segment');
  }
});
