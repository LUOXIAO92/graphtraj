const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let monitorGraph, dependencyFocus;
test.before(async () => {
  const result = await build({ entryPoints: [path.join(__dirname, '../src/monitor-graph.ts')],
    bundle: true, platform: 'node', format: 'cjs', write: false });
  const module = { exports: {} };
  vm.runInNewContext(result.outputFiles[0].text, { module, exports: module.exports, structuredClone });
  ({ monitorGraph, dependencyFocus } = module.exports);
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
      assert.ok(graph.tickets.find(ticket => ticket.ticket_id === edge.dependencies[0].ticket).dependencies.includes(edge.dependencies[0].dependency));
    }
    const first = result.edges.find(edge => edge.dependencies.some(item => item.dependency === '1'));
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
    assert.ok(node.x + a.width + 60 <= other.x || other.x + b.width + 60 <= node.x ||
      node.y + a.height + 60 <= other.y || other.y + b.height + 60 <= node.y);
  }
  for (const node of result.nodes.filter(node => node.ticket.parent_id)) {
    const parent = result.nodes.find(other => other.id === node.ticket.parent_id);
    assert.ok(parent.frame);
    assert.ok(node.x >= parent.x && node.y >= parent.y + parent.height);
    assert.ok(node.x + (node.frame ?? node).width <= parent.x + parent.frame.width);
    assert.ok(node.y + (node.frame ?? node).height <= parent.y + parent.frame.height);
  }
});

test('selection traces real dependencies and selected summary internals, excluding unrelated branches', () => {
  const graph = input();
  assert.deepEqual([...dependencyFocus(graph, 'A')].sort(), ['1', '2', '3', '4', 'A', 'C']);
  assert.deepEqual([...dependencyFocus(graph, '2')].sort(), ['1', '2', '3', '4']);
  assert.equal(dependencyFocus(graph, null).size, graph.tickets.length);
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
    assert.equal(view.edges.flatMap(edge => edge.dependencies).length, 3);
    assert.ok(view.nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y)));
    assert.ok(view.edges.every(edge => edge.vertices.every(point => Number.isFinite(point.x) && Number.isFinite(point.y))));
    for (const edge of view.edges) assert.ok(graph.tickets.find(ticket => ticket.ticket_id === edge.dependencies[0].ticket).dependencies.includes(edge.dependencies[0].dependency));
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
  assert.equal(collapsed.edges.find(e => e.source === '252' && e.target === '260').dependencies.length, 2);
  assert.equal(collapsed.edges.find(e => e.source === '260' && e.target === '275').dependencies.length, 2);
  assert.ok(collapsed.edges.some(e => e.source === '260' && e.target === '270'));
  assert.ok(collapsed.edges.some(e => e.source === '270' && e.target === '252'));
  const expanded = monitorGraph(graph, new Set(['252', '260', '275', '270']));
  assert.deepEqual(Array.from(expanded.edges.filter(e => e.target === '264'), e => e.source).sort(), ['261', '269']);
  for (const view of [collapsed, expanded]) {
    const native = view.edges.flatMap(e => e.dependencies.map(d => `${d.dependency}->${d.ticket}`)).sort();
    assert.deepEqual(Array.from(native), graph.tickets.flatMap(t => t.dependencies.map(d => `${d}->${t.ticket_id}`)).sort());
  }
  assert.equal(JSON.stringify(graph), original);
});
