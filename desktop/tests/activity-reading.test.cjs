const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

test('following survives programmatic scroll and content resize; upward reading pauses only its own column', async t => {
  const folder = await fs.mkdtemp(path.join(__dirname, '../node_modules/.reading-check-'));
  t.after(() => fs.rm(folder, { recursive: true, force: true }));
  const output = path.join(folder, 'view.cjs');
  await build({ entryPoints: [path.join(__dirname, '../src/Activity.tsx')], outfile: output,
    bundle: true, platform: 'node', format: 'cjs', external: ['react'],
    plugins: [{ name: 'ui-shell', setup(builder) {
      builder.onResolve({ filter: /^@heroui\/react$/ }, () => ({ path: 'shell', namespace: 'ui-shell' }));
      builder.onLoad({ filter: /.*/, namespace: 'ui-shell' }, () => ({ contents: `
        import React from 'react';
        export const Button = ({onPress, children, ...props}) => React.createElement('button', {...props, onClick:onPress}, children);
        export const TextField = props => React.createElement('div', props);
        export const Input = props => React.createElement('input', props);
        export const Label = props => React.createElement('label', props);
        export const Description = props => React.createElement('span', props);
      `, resolveDir: path.join(__dirname, '..') }));
    }}] });
  const observers = new Set();
  const previousWindow = globalThis.window, previousObserver = globalThis.ResizeObserver;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.add(this); }
    observe() {}
    disconnect() { observers.delete(this); }
  };
  let version = 1, failed = false;
  globalThis.window = { graphtraj: { activity: async (_project, request) => {
    if (failed) throw new Error('Controlled connection failure');
    return { agents: ['alpha', 'beta'].map(alias => ({ alias, kind: 'main', state: 'running', runtime: 'codex' })),
      updated_at: new Date().toISOString(), availability: 'available', cursor: String(version),
      events: !request.alias || request.cursor === String(version) ? [] : [{ id: `${request.alias}:${version}`,
        kind: 'message', role: 'assistant', text: `Message ${version}`, time: null, source: { runtime: 'codex', offset: version } }] };
  } } };
  const histories = new Map();
  let tree;
  t.after(async () => {
    if (tree) await act(async () => tree.unmount());
    globalThis.window = previousWindow; globalThis.ResizeObserver = previousObserver;
  });
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { ActivityView } = require(output);
  await act(async () => {
    tree = create(React.createElement(ActivityView, { projectId: 'project' }), { createNodeMock(element) {
      if (element.props.className === 'transcript activity-history') {
        const key = element.props['aria-label'];
        if (!histories.has(key)) histories.set(key, { scrollTop: 0, scrollHeight: 1000, clientHeight: 200 });
        return histories.get(key);
      }
      return { scrollLeft: 0, scrollWidth: 900, clientWidth: 900, querySelectorAll: () => [] };
    } });
  });
  const transcript = alias => tree.root.findAllByProps({ 'aria-label': `${alias} messages` })[0];
  const column = alias => tree.root.findByProps({ 'data-agent-id': alias });
  const following = alias => column(alias).findAllByType('button').some(button => button.children.includes('Pause following'));
  const first = histories.get('alpha messages'), second = histories.get('beta messages');
  assert.equal(first.scrollTop, 1000);
  await act(async () => {
    first.scrollHeight = 1400;
    transcript('alpha').props.onScroll({ currentTarget: first });
    for (const observer of observers) observer.callback();
  });
  assert.ok(following('alpha'));
  assert.equal(first.scrollTop, 1400);
  await act(async () => {
    transcript('alpha').props.onWheel({ deltaY: -100 });
    first.scrollTop = 300;
    transcript('alpha').props.onScroll({ currentTarget: first });
  });
  version++;
  await act(async () => { t.mock.timers.tick(3000); });
  assert.equal(first.scrollTop, 300);
  assert.equal(following('alpha'), false);
  assert.ok(following('beta'));
  assert.equal(second.scrollTop, 1000);
  await act(async () => column('alpha').findAllByType('button').find(button => button.children.some(child => typeof child === 'string' && child.startsWith('Follow new messages'))).props.onClick());
  for (let index = 0; index < 3; index++) {
    version++;
    await act(async () => { t.mock.timers.tick(3000); });
    await act(async () => {
      first.scrollHeight += 500;
      transcript('alpha').props.onScroll({ currentTarget: first });
      for (const observer of observers) observer.callback();
    });
    assert.ok(following('alpha'));
    assert.equal(first.scrollTop, first.scrollHeight);
  }
  // Failure feedback has an action and does not pretend that initial loading continues.
  failed = true;
  await act(async () => { t.mock.timers.tick(3000); });
  assert.ok(tree.root.findAllByType('button').some(button => button.children.includes('Retry now')));
  assert.equal(tree.root.findAllByType('p').some(node => node.children.some(child => typeof child === 'string' && child.startsWith('Loading Main'))), false);
});
