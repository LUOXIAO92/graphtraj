const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

/** Compile the real component, replacing only the already-tested UI library shell. */
async function components(t) {
  const folder = await fs.mkdtemp(path.join(__dirname, '../node_modules/.activity-check-'));
  t.after(() => fs.rm(folder, { recursive: true, force: true }));
  const output = path.join(folder, 'activity.cjs');
  await build({
    entryPoints: [path.join(__dirname, '../src/Activity.tsx')], outfile: output,
    bundle: true, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' },
    plugins: [{ name: 'ui-shell', setup(builder) {
      builder.onResolve({ filter: /^@heroui\/react$/ }, () => ({ path: 'shell', namespace: 'ui-shell' }));
      builder.onLoad({ filter: /.*/, namespace: 'ui-shell' }, () => ({ contents: `
        import React from 'react';
        export const Button = ({ onPress, children, ...props }) => React.createElement('button', { ...props, onClick: onPress }, children);
        export const Card = ({ children, ...props }) => React.createElement('article', props, children);
        for (const name of ['Header','Title','Description','Content']) Card[name] = ({children, ...props}) => React.createElement('div', props, children);
      `, resolveDir: path.join(__dirname, '..') }));
    }}],
  });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const oldWindow = globalThis.window;
  t.after(() => { globalThis.window = oldWindow; });
  return require(output);
}

const event = (id, extra = {}) => ({ id: String(id), kind: 'message', role: 'assistant', text: `record ${id}`,
  time: null, source: { runtime: 'codex', offset: id }, ...extra });
const text = tree => JSON.stringify(tree.toJSON());
const button = (tree, label) => tree.root.findAllByType('button').find(node =>
  typeof node.props.children === 'string' && node.props.children.startsWith(label));

for (const runtime of ['codex', 'dsh']) {
  test(`${runtime} work diagnostics are visible and copied with their label`, async t => {
    const { EventCard } = await components(t);
    let copied;
    globalThis.window = { graphtraj: { copyText: async value => { copied = value; } } };
    const details = { type: 'error', message: 'Permission denied at src/main.py:14', code: 'EACCES' };
    let tree;
    await act(async () => { tree = create(React.createElement(EventCard, { event: event(1, {
      kind: 'work', text: 'error', details, source: { runtime, offset: 1 },
    }) })); });
    t.after(async () => { await act(async () => tree.unmount()); });
    assert.match(text(tree), /Permission denied at src\/main.py:14/);
    assert.match(text(tree), /EACCES/);
    await act(async () => { button(tree, 'Copy').props.onClick(); });
    assert.equal(copied, 'error\n\n' + JSON.stringify(details, null, 2));
  });
}

test('Follow drains long pages and reconnect replay; pause preserves the older view', async t => {
  const { ActivityView } = await components(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const member = { alias: 'worker', historical: false, runtime: 'codex', state: 'running' };
  const base = { ticket_id: '1', agents: [member], updated_at: '2026-10-06T00:00:00Z' };
  const records = Array.from({ length: 405 }, (_, i) => event(i));
  let reconnect = false;
  const requests = [];
  globalThis.window = { graphtraj: { activity: async (_project, request) => {
    requests.push(request);
    if (!request.alias) return base;
    if (reconnect && request.cursor) {
      reconnect = false;
      return { ...base, availability: 'cursor-expired', events: [], cursor: null };
    }
    const start = Number(request.cursor || 0);
    const end = Math.min(start + 200, records.length);
    return { ...base, availability: 'available', events: records.slice(start, end), cursor: String(end), has_more: end < records.length };
  } } };
  let tree;
  // Layout/programmatic scroll while a page is replaced must not pause fetching.
  const historyNode = { scrollHeight: 1000, scrollTop: 0, clientHeight: 300 };
  await act(async () => { tree = create(React.createElement(ActivityView, { projectId: 'p', ticketId: '1' }), {
    createNodeMock: element => element.props.className === 'activity-history' ? historyNode : {
      scrollIntoView() {
        const history = tree.root.findAll(node => node.props.className === 'activity-history')[0];
        history?.props.onScroll?.({ currentTarget: historyNode });
      },
    },
  }); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const advance = async (ms = 1) => { await act(async () => t.mock.timers.tick(ms)); };
  assert.ok(button(tree, 'Pause following'), 'page layout must keep follow active');
  await act(async () => button(tree, 'Pause following').props.onClick());
  await advance();
  assert.equal(requests.filter(request => request.alias).length, 1);
  assert.doesNotMatch(text(tree), /record 404/);
  await act(async () => button(tree, 'Follow new').props.onClick());
  await advance(3000); await advance(); await advance();
  assert.match(text(tree), /record 404/);
  assert.deepEqual(requests.filter(request => request.alias).slice(0, 3).map(request => request.cursor), [undefined, '200', '400']);

  await act(async () => button(tree, 'Pause following').props.onClick());
  records.push(event(405));
  await advance(3000);
  assert.doesNotMatch(text(tree), /record 405/);
  assert.match(text(tree), /Follow new messages \(1\)/);
  await act(async () => button(tree, 'Follow new').props.onClick());
  assert.match(text(tree), /record 405/);

  reconnect = true;
  records.push(event(406));
  await advance(3000); await advance(3000); await advance(); await advance();
  assert.match(text(tree), /record 406/);
  assert.equal(tree.root.findAll(node => node.props.className === 'activity-event').filter(node => node.type === 'article').length, 100);
  assert.match(text(tree), /407/);
});


test('result selection requires the real expansion control, not quoted phase text', async t => {
  const { EventCard } = await components(t);
  const marker = '262-live-regression';
  let tree;
  await act(async () => { tree = create(React.createElement(React.Fragment, null,
    React.createElement(EventCard, { event: event(1, { text: `${marker} · result diagnostic` }) }),
    React.createElement(EventCard, { event: event(2, { kind: 'tool', phase: 'call', name: 'bash',
      text: undefined, arguments: { command: `echo '${marker} · result diagnostic'` } }) }),
    React.createElement(EventCard, { event: event(3, { kind: 'tool', phase: 'result', name: 'bash',
      text: undefined, result: `${marker} diagnostic` }) }),
  )); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const cards = tree.root.findAllByType('article');
  const candidates = cards.filter(card => card.findAllByType('summary')
    .some(summary => summary.props.children === 'Result / details'));
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].findByType('pre').props.children, `${marker} diagnostic`);
});


test('parallel current/history columns retain independent pause and cursor state while hidden', async t => {
  const { ActivityView } = await components(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const members = [{ alias: 'current', historical: false, state: 'running' },
    { alias: 'old', historical: true, state: 'retired' }];
  const requests = [];
  let count = 2;
  globalThis.window = { graphtraj: { activity: async (projectId, request) => {
    requests.push({ projectId, ...request });
    const base = { ticket_id: '1', agents: members, updated_at: '2026-10-11T00:00:00Z' };
    if (!request.alias) return base;
    return { ...base, availability: 'available', cursor: String(count), events:
      Array.from({ length: count }, (_, i) => event(i, { text: `${request.alias} message ${i}` })) };
  } } };
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityView, { projectId: 'one', ticketId: '1' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const columns = tree.root.findAll(node => node.type === 'article' && node.props.className === 'agent-column');
  assert.equal(columns.length, 2);
  assert.match(text(tree), /Historical/);
  await act(async () => { columns[0].findAllByType('button')[0].props.onClick(); });
  count = 3;
  await act(async () => t.mock.timers.tick(3000));
  assert.match(text(tree), /current message 2/);
  assert.ok(button(tree, 'Follow new messages (1)'));
  assert.ok(button(tree, 'Pause following'));
  await act(async () => { tree.update(React.createElement(ActivityView, { projectId: 'one', ticketId: '1', active: false })); });
  const before = requests.length;
  await act(async () => t.mock.timers.tick(6000));
  assert.equal(requests.length, before, 'hidden monitor must stop polling');
  await act(async () => { tree.update(React.createElement(ActivityView, { projectId: 'one', ticketId: '1', active: true })); });
  assert.ok(button(tree, 'Follow new messages (1)'));
  assert.deepEqual(requests.filter(request => request.alias).slice(-2).map(request => request.cursor), ['3', '3']);
  assert.ok(requests.every(request => request.projectId === 'one'));
});
