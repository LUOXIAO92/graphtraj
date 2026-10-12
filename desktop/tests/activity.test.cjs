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
        export const TextField = props => React.createElement('field', props);
        export const Input = props => React.createElement('input', props);
        export const Label = props => React.createElement('label', props);
        export const Description = props => React.createElement('span', props);
        export const Card = ({ children, ...props }) => React.createElement('article', props, children);
        for (const name of ['Header','Title','Description','Content']) Card[name] = ({children, ...props}) => React.createElement('div', props, children);
      `, resolveDir: path.join(__dirname, '..') }));
    }}],
  });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const oldObserver = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  t.after(() => { globalThis.ResizeObserver = oldObserver; });
  const oldWindow = globalThis.window;
  t.after(() => { globalThis.window = oldWindow; });
  return require(output);
}

const event = (id, extra = {}) => ({ id: String(id), kind: 'message', role: 'assistant', text: `record ${id}`,
  time: null, source: { runtime: 'codex', offset: id }, ...extra });
const text = tree => JSON.stringify(tree.toJSON());
const button = (tree, label) => (tree.root ?? tree).findAllByType('button').find(node =>
  node.children.filter(child => typeof child === 'string').join('').startsWith(label));

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
    createNodeMock: element => element.props.className?.includes('activity-history') ? historyNode : {
      scrollIntoView() {
        const history = tree.root.findAll(node => node.props.className?.includes('activity-history'))[0];
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
  assert.equal(tree.root.findAll(node => node.props.className?.includes('activity-event')).filter(node => node.type === 'article').length, 100);
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
  const candidates = tree.root.findAllByType('details').filter(card => card.findAllByType('span').some(node => node.props.className === 'tool-result' && node.children.includes('result')));
  assert.equal(candidates.length, 1);
  // The first pre is the readable result body; the raw field copy sits in Technical details.
  assert.equal(candidates[0].findAllByType('pre')[0].props.children, `${marker} diagnostic`);
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
  const columns = tree.root.findAll(node => node.type === 'article' && node.props.className?.split(' ').includes('agent-column'));
  assert.equal(columns.length, 2);
  assert.match(text(tree), /Historical/);
  await act(async () => { button(columns[0], 'Pause following').props.onClick(); });
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

test('Main conversations use project associations without inventing Ticket membership', async t => {
  const { ActivityView } = await components(t);
  const requests = [];
  const main = { alias: 'Main:codex:main-session', kind: 'main', runtime: 'codex', session: 'main-session', historical: false, state: 'associated' };
  globalThis.window = { graphtraj: { activity: async (projectId, request) => {
    requests.push({ projectId, ...request });
    return { ticket_id: null, updated_at: '2026-10-11T00:00:00Z',
      agents: [main, { alias: 'ticket-member', kind: 'member', historical: false, state: 'running' }],
      availability: 'available', events: request.alias ? [event(1, { text: 'Owned Main output' })] : [] };
  } } };
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityView, { projectId: 'one' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  assert.equal(tree.root.findAll(node => node.type === 'article' && node.props['data-agent-id'] === main.alias).length, 1);
  assert.equal(tree.root.findAll(node => node.type === 'article' && node.props['data-agent-id'] === 'ticket-member').length, 0);
  assert.match(text(tree), /Owned Main output/);
  assert.ok(requests.every(request => request.projectId === 'one' && !('ticket_id' in request)));
});

test('tool names resolve across pages and result-first records without guessing or changing output', async t => {
  const { ActivityRecords } = await components(t);
  const result = event(0, { kind: 'tool', role: undefined, text: undefined, phase: 'result', call_id: 'private-call-id', result: 'Formatted test: hook decision allow' });
  const records = [result, ...Array.from({ length: 100 }, (_, i) => event(i + 1)),
    event(101, { kind: 'tool', text: undefined, name: 'exec_command', phase: 'call', call_id: 'private-call-id' }),
    event(102, { kind: 'tool', text: undefined, phase: 'result', call_id: 'unknown-id', result: 'untouched' })];
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityRecords, { events: records.slice(0, 100), pageStart: 0, agent: 'worker' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const summaries = () => tree.root.findAllByType('summary').map(node => node.findAllByType('strong').map(child => child.children.join('')).join('')).join('\n');
  assert.match(summaries(), /Tool · Name not recorded/);
  assert.doesNotMatch(summaries(), /private-call-id/);
  await act(async () => { tree.update(React.createElement(ActivityRecords, { events: records, pageStart: 0, agent: 'worker' })); });
  assert.match(summaries(), /Tool · exec_command/);
  assert.equal(tree.root.findAllByType('pre')[0].props.children, 'Formatted test: hook decision allow');
  assert.match(text(tree), /private-call-id/);
  await act(async () => { tree.update(React.createElement(ActivityRecords, { events: records, pageStart: 100, agent: 'worker' })); });
  assert.match(summaries(), /Tool · Name not recorded/);
  assert.doesNotMatch(summaries(), /unknown-id/);
});


test('usage supplements the actual turn, keeps observation scopes, and never attaches unknown usage to a reply', async t => {
  const { ActivityRecords } = await components(t);
  const usage = (id, turn, count) => event(id, { kind: 'usage', text: undefined, turn_id: turn,
    usage: { identity: `counter:${count}`, phase: 'snapshot', attributable: true, scope: 'latest-response',
      tokens: { input: 10, output: 2 }, provider_usage: { input_tokens: 10, output_tokens: 2 },
      cumulative: { input_tokens: count, output_tokens: count / 5 } } });
  const records = [event(1, { turn_id: 'turn-a', text: 'Working response' }), usage(2, 'turn-a', 10),
    usage(3, 'turn-a', 20), usage(4, 'turn-a', 20),
    event(5, { turn_id: 'turn-b', text: 'Another turn' }), usage(6, undefined, 30)];
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityRecords, { events: records, pageStart: 0, agent: 'actual-worker' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  assert.equal(tree.root.findAllByType('article').length, 2, 'usage is never a chat message');
  const supplements = tree.root.findAllByType('footer');
  assert.equal(supplements.length, 2);
  assert.ok(supplements.every(node => node.props['aria-label'] === 'Usage for actual-worker'));
  assert.equal(supplements[0].findAll(node => node.props.className === 'usage-observation').length, 2, 'same counter replay is not a second observation');
  assert.match(text(tree), /Latest response observation/);
  assert.match(text(tree), /Cumulative native Session counter/);
  assert.match(text(tree), /Response \/ turn association unavailable/);
  assert.equal(tree.root.findAll(node => node.props.className === 'tool-card ').length, 0);
  const rendered = tree.toJSON();
  assert.equal(rendered[0].type, 'article');
  assert.equal(rendered[1].type, 'footer');
  assert.equal(rendered[2].type, 'article');
  assert.equal(rendered[3].type, 'footer');
});


test('reasoning and lifecycle events use different human labels', async t => {
  const { EventCard } = await components(t);
  let tree;
  await act(async () => { tree = create(React.createElement(React.Fragment, null,
    React.createElement(EventCard, { event: event(1, { role: 'reasoning', text: 'Recorded plaintext' }) }),
    React.createElement(EventCard, { event: event(2, { kind: 'work', role: undefined, text: 'task_started', details: { type: 'task_started' } }) }),
  )); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const titles = tree.root.findAllByType('strong').map(node => node.children.join(''));
  assert.deepEqual(titles, ['Reasoning', 'Execution event']);
  assert.match(text(tree), /Recorded plaintext/);
});


test('per-response usage uses the native source record; a usage-only page retains its known turn', async t => {
  const { ActivityRecords } = await components(t);
  const source = { runtime: 'pi', trace: 'sanitized', offset: 50 };
  const usage = { phase: 'final', attributable: true, identity: 'pi:message-1', tokens: {}, provider_usage: {} };
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityRecords, { agent: 'pi-worker', pageStart: 0,
    events: [event(1, { source, text: 'Recorded response' }), event(2, { source, kind: 'usage', text: undefined, usage })],
  })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  assert.match(text(tree), /Recorded response/);
  assert.doesNotMatch(text(tree), /association unavailable/);
  assert.equal(tree.root.findAllByType('footer').length, 1);
  assert.match(text(tree), /Unknown/);
  await act(async () => { tree.update(React.createElement(ActivityRecords, { agent: 'pi-worker', pageStart: 0,
    events: [event(3, { kind: 'usage', text: undefined, turn_id: 0, usage })],
  })); });
  assert.match(text(tree), /Recorded turn \(content outside this page\)/);
  assert.doesNotMatch(text(tree), /association unavailable/);
});


test('tool results render readable text, image previews and fallback notes without dumping encodings', async t => {
  const { EventCard } = await components(t);
  const image = 'iVBORw0KGgoAAAANSUhEUg';
  let tree;
  await act(async () => { tree = create(React.createElement(EventCard, { event: {
    id: '1', kind: 'tool', role: undefined, phase: 'result', name: 'view_image', time: null,
    call_id: 'call-1', tool_type: 'custom_tool_call_output', source: { runtime: 'codex', trace: 'sanitized', offset: 5 },
    result: `[{"type":"input_image","image_url":"data:image/png;base64,${image}"}]`,
    content: [ { type: 'text', text: 'Rendered **tool** text.' },
               { type: 'image', mime: 'image/png', data: image },
               { type: 'unknown', label: 'future_block' } ] } })); });
  t.after(async () => { await act(async () => tree.unmount()); });

  // Text is normal Markdown, an image becomes a bounded preview plus an attachment link.
  assert.ok(tree.root.findAllByType('strong').some(node => node.children.join('') === 'tool'));
  assert.equal(tree.root.findByType('img').props.src, `data:image/png;base64,${image}`);
  assert.ok(tree.root.findAllByType('a').some(node => String(node.props.download).startsWith('tool-image')));
  // The fallback points at the real on-demand disclosure, not a missing "record below".
  assert.match(text(tree), /Unsupported tool content \(/);
  assert.match(text(tree), /available under Technical details/);

  // Readable body and technical fields are layered: raw fields live only in the sub-disclosure.
  const strings = node => node.findAll(() => true).flatMap(child => child.children.filter(item => typeof item === 'string'));
  const content = tree.root.find(node => node.props.className === 'tool-content');
  assert.equal(content.findAllByType('pre').length, 0);
  assert.ok(!strings(content).some(item => item.includes('input_image')));
  const technical = tree.root.find(node => node.props.className === 'tool-technical');
  assert.ok(strings(technical).some(item => item.includes('call-1')));
  assert.ok(strings(technical).some(item => item.includes('input_image')));
});


test('plain tool text keeps its recorded newlines instead of collapsing into one paragraph', async t => {
  const { EventCard } = await components(t);
  let tree;
  await act(async () => { tree = create(React.createElement(EventCard, { event: {
    id: '2', kind: 'tool', phase: 'result', name: 'run_build', time: null, call_id: 'call-2',
    tool_type: 'function_call_output', source: { runtime: 'codex', trace: 'sanitized', offset: 9 },
    result: 'build 001: ok\nbuild 002: ok',
    content: [{ type: 'text', text: 'build 001: ok\nbuild 002: ok' }] } })); });
  t.after(async () => { await act(async () => tree.unmount()); });

  // The recorded line break survives into the rendered text node (CSS keeps it visible).
  const body = tree.root.find(node => node.props.className === 'tool-text');
  const rendered = body.findAll(() => true).flatMap(child => child.children.filter(item => typeof item === 'string')).join('');
  assert.match(rendered, /build 001: ok\nbuild 002: ok/);
});
