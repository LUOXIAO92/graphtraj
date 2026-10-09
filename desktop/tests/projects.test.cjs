const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { operate, ticket, makeProject } = require('./fixtures.cjs');

test('explicit project paths retain directory and native validation before saving', async t => {
  const { Projects } = await import('../electron/projects.ts');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-startup-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const valid = path.join(root, 'valid');
  const invalid = path.join(root, 'uninitialized');
  await fs.mkdir(valid);
  await fs.mkdir(invalid);
  const calls = [];
  const reader = { read: async folder => {
    calls.push(folder);
    if (folder === await fs.realpath(invalid)) throw new Error('Native configuration unavailable');
    return { tickets: [] };
  } };
  const projects = new Projects(path.join(root, 'prefs/projects.json'), reader);
  t.after(() => projects.close());
  await projects.load();
  for (const folder of ['', 'relative-project']) await assert.rejects(projects.add(folder), /absolute/);
  await assert.rejects(projects.add(path.join(root, 'missing')), /ENOENT/);
  const notDirectory = path.join(root, 'file');
  await fs.writeFile(notDirectory, 'not a directory');
  await assert.rejects(projects.add(notDirectory), /project directory/);
  const unreadable = path.join(root, 'unreadable');
  await fs.mkdir(unreadable, { mode: 0o000 });
  try { await assert.rejects(projects.add(unreadable), /EACCES|EPERM/); }
  finally { await fs.chmod(unreadable, 0o700); }
  assert.equal(calls.length, 0);
  await assert.rejects(projects.add(invalid), /Native configuration unavailable/);
  assert.deepEqual(projects.list(), { projects: [], selected: null });
  const added = await projects.add(valid);
  assert.equal(added.projects[0].root, await fs.realpath(valid));
  assert.equal(added.selected, added.projects[0].id);
  assert.equal((await projects.add(valid)).projects.length, 1);
  const reopened = new Projects(path.join(root, 'prefs/projects.json'), reader);
  t.after(() => reopened.close());
  await reopened.load();
  assert.deepEqual(reopened.list(), added);
});

test('native desktop bridge isolates projects, persists preferences and reconnects without project writes', async t => {
  const { Projects, GraphReader } = await import('../electron/projects.ts');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-desktop-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const first = await makeProject(path.join(root, 'first'), 'first-project');
  const second = await makeProject(path.join(root, 'second'), 'second-project');
  const reader = new GraphReader();
  t.after(() => reader.close());
  const file = path.join(root, 'userData/projects.json');
  const projects = new Projects(file, reader);
  t.after(() => projects.close());
  await projects.load();
  const a = await projects.add(first);
  const firstId = a.selected;
  const alias = path.join(root, 'first-alias');
  await fs.symlink(first, alias);
  assert.equal((await projects.add(alias)).projects.length, 1);
  const b = await projects.add(second);
  const secondId = b.selected;
  assert.equal(b.projects.length, 2);
  assert.notEqual(firstId, secondId);
  assert.equal((await projects.graph(firstId)).graph.tickets[0].title, 'first project');
  await assert.rejects(projects.activity({ projectId: '/', ticket_id: '1' }), /Choose an added project/);
  assert.equal((await projects.graph(secondId)).graph.tickets[0].title, 'second project');
  assert.deepEqual((await projects.graph(secondId)).graph.tickets[1].dependencies, ['1']);
  await assert.rejects(projects.graph(first), /Choose an added project/);
  await assert.rejects(projects.graph({ root: first }), /Choose an added project/);

  const blank = path.join(root, 'uninitialized');
  await fs.mkdir(blank);
  await assert.rejects(projects.add(blank), /Config was not found/);
  assert.deepEqual(await fs.readdir(blank), []);
  const unreadable = path.join(root, 'unreadable');
  await fs.mkdir(unreadable, { mode: 0o000 });
  try { await assert.rejects(projects.add(unreadable), /EACCES|EPERM/); }
  finally { await fs.chmod(unreadable, 0o700); }

  await projects.select(firstId);
  const reopened = new Projects(file, reader);
  await reopened.load();
  assert.deepEqual(reopened.list(), projects.list());
  const original = operate(first, 'ticket_graph');
  await projects.graph(firstId);
  assert.deepEqual(operate(first, 'ticket_graph'), original);

  // Public graph revision appears on the next read, including historical nodes.
  await fs.writeFile(path.join(first, 'evidence.txt'), 'Replace dependent with successor.\n');
  operate(first, 'ticket_revise', {
    product_preserving: true, caused_by_event_ids: [], evidence_refs: ['evidence.txt'],
    tickets: [
      { ...ticket('2', 'dependent', ['1']), title: 'Historical dependency', active: false, replaced_by: ['3'] },
      { ...ticket('3', 'successor', ['1']), active: true, replaced_by: [] },
    ],
  });
  const updated = (await projects.graph(firstId)).graph;
  assert.deepEqual(updated.tickets.map(t => t.ticket_id), ['1', '2', '3']);
  assert.equal(updated.tickets[1].active, false);
  assert.equal(updated.tickets[1].title, 'Historical dependency');
  assert.deepEqual(updated.tickets[1].replaced_by, ['3']);
  assert.equal((await projects.graph(secondId)).graph.tickets.length, 2);

  const moved = first + '-moved';
  await fs.rename(first, moved);
  await assert.rejects(projects.graph(firstId), /ENOENT/);
  await fs.rename(moved, first);
  assert.equal((await projects.graph(firstId)).graph.tickets.length, 3);
  await projects.remove(firstId);
  assert.deepEqual(operate(first, 'ticket_graph'), updated);
  assert.equal(projects.list().projects.length, 1);
  await assert.rejects(projects.graph(firstId), /Choose an added project/);
  reader.close();
  await assert.rejects(projects.graph(secondId), /observer is closed/);
  assert.equal(operate(second, 'ticket_graph').tickets.length, 2);
});

test('DAG layout ranks dependencies and keeps every historical node', async () => {
  const { layout } = await import('../src/layout.ts');
  const positions = layout([
    { ticket_id: '1', dependencies: [] },
    { ticket_id: '2', dependencies: [] },
    { ticket_id: '3', dependencies: ['1', '2'] },
    { ticket_id: '4', dependencies: ['3'], active: false },
  ]);
  assert.equal(Object.keys(positions).length, 4);
  assert.equal(positions['1'].x, positions['2'].x);
  assert.notEqual(positions['1'].y, positions['2'].y);
  assert.ok(positions['3'].x > positions['1'].x);
  assert.ok(positions['4'].x > positions['3'].x);
});
