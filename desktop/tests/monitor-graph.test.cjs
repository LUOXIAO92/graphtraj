const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');

const moduleObject = { exports: {} };
let monitorGraph;
test.before(async () => {
  const result = await build({ entryPoints: [path.join(__dirname, '../src/monitor-graph.ts')],
    bundle: true, platform: 'node', format: 'cjs', write: false });
  vm.runInNewContext(result.outputFiles[0].text, { module: moduleObject, exports: moduleObject.exports });
  monitorGraph = moduleObject.exports.monitorGraph;
});

test('summary expansion keeps shared/unassigned tickets and original crossing dependencies', () => {
  const tickets = Array.from({ length: 189 }, (_, index) => ({ ticket_id: String(index + 1),
    ticket_name: `task-${index + 1}`, title: `Task ${index + 1}`, active: true, ready: false,
    status: index < 170 ? 'integrated' : 'implementing', replaced_by: [],
    dependencies: index ? [String(index)] : [] }));
  const groups = [
    { id: 'a', title: 'Summary A', ticket_ids: tickets.slice(0, 80).map(ticket => ticket.ticket_id) },
    { id: 'b', title: 'Summary B', ticket_ids: tickets.slice(79, 175).map(ticket => ticket.ticket_id) },
    { id: 'c', title: 'Summary C', ticket_ids: tickets.slice(175, 185).map(ticket => ticket.ticket_id) },
  ];
  const graph = { tickets, groups }, original = JSON.stringify(graph);
  for (const expanded of [[], ['a'], ['a', 'b'], ['a', 'b', 'c'], []]) {
    const result = monitorGraph(graph, new Set(expanded));
    const ids = new Set(result.nodes.map(node => node.id));
    assert.equal(ids.size, result.nodes.length, 'shared tickets must not duplicate');
    assert.ok(ids.has('summary:view:shared'));
    assert.ok(ids.has('summary:view:ungrouped'));
    assert.equal(ids.has('1'), expanded.includes('a'));
    assert.equal(ids.has('81'), expanded.includes('b'));
    for (const edge of result.edges) {
      assert.ok(ids.has(edge.source) && ids.has(edge.target));
      assert.ok(tickets.find(ticket => ticket.ticket_id === edge.data.ticket).dependencies.includes(edge.data.dependency));
    }
    for (const edge of ['79-80', '80-81', '175-176', '185-186']) assert.ok(result.edges.some(item => item.id === edge));
    const roots = result.nodes.filter(node => !node.parentId);
    for (const [index, node] of roots.entries()) for (const other of roots.slice(index + 1)) {
      const width = node.style?.width ?? 250, height = node.style?.height ?? 210;
      const otherWidth = other.style?.width ?? 250, otherHeight = other.style?.height ?? 210;
      assert.ok(node.position.x + width <= other.position.x || other.position.x + otherWidth <= node.position.x ||
        node.position.y + height <= other.position.y || other.position.y + otherHeight <= node.position.y);
    }
  }
  assert.equal(JSON.stringify(graph), original);
});

test('interleaved summary dependencies remain visible even when contraction creates a cycle', () => {
  const graph = { tickets: [
    { ticket_id: '1', dependencies: [] }, { ticket_id: '2', dependencies: ['1'] }, { ticket_id: '3', dependencies: ['2'] },
  ], groups: [{ id: 'a', title: 'A', ticket_ids: ['1', '3'] }, { id: 'b', title: 'B', ticket_ids: ['2'] }] };
  const result = monitorGraph(graph, new Set());
  assert.equal(result.nodes.length, 2);
  assert.equal(result.edges.length, 2);
  assert.notEqual(JSON.stringify(result.nodes[0].position), JSON.stringify(result.nodes[1].position));
});

test('public real project projection has a compact overview and lossless reachable tasks', {
  skip: !process.env.GRAPHTRAJ_MONITOR_GRAPH,
}, () => {
  const projection = JSON.parse(require('node:fs').readFileSync(process.env.GRAPHTRAJ_MONITOR_GRAPH, 'utf8'));
  assert.equal(projection.failed, false);
  const graph = projection.result;
  const original = JSON.stringify(graph);
  const overview = monitorGraph(graph, new Set());
  assert.equal(graph.tickets.length, 191);
  assert.equal(graph.groups.length, 14);
  assert.equal(overview.nodes.length, 15);
  assert.equal(overview.nodes.find(node => node.data.group.id === 'view:ungrouped').data.group.ticket_ids.length, 44);
  const right = Math.max(...overview.nodes.map(node => node.position.x + node.style.width));
  const bottom = Math.max(...overview.nodes.map(node => node.position.y + node.style.height));
  assert.ok(right <= 1280 && bottom <= 400, `${right} x ${bottom}`);
  const expanded = monitorGraph(graph, new Set(overview.nodes.map(node => node.data.group.id)));
  assert.equal(expanded.nodes.filter(node => node.data.ticket).length, graph.tickets.length);
  const ticketIds = new Set(graph.tickets.map(ticket => ticket.ticket_id));
  const expected = graph.tickets.flatMap(ticket => ticket.dependencies.filter(id => ticketIds.has(id)).map(id => `${id}-${ticket.ticket_id}`)).sort();
  assert.deepEqual(Array.from(expanded.edges.map(edge => edge.id)).sort(), expected);
  const reached = new Set();
  for (const node of overview.nodes) {
    const opened = monitorGraph(graph, new Set([node.data.group.id]));
    opened.nodes.filter(item => item.data.ticket).forEach(item => reached.add(item.id));
  }
  assert.equal(reached.size, 191);
  assert.equal(JSON.stringify(graph), original);
});
