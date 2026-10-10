const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { useKeyPress } = require('@xyflow/react');

// Exercise the actual graph dependency's document-level listener without a
// browser double claiming native summary activation or installed acceptance.
test('hidden graph releases Space default action and restores panning on return', async t => {
  const previousWindow = globalThis.window;
  globalThis.window = new EventTarget();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const document = new EventTarget();
  function GraphShortcut({ active }) {
    useKeyPress(active ? 'Space' : null, { target: document });
    return null;
  }
  let tree;
  t.after(async () => {
    if (tree) await act(async () => tree.unmount());
    globalThis.window = previousWindow;
  });
  async function space() {
    const summary = { nodeType: 1, nodeName: 'SUMMARY', hasAttribute: () => false, closest: () => null };
    const down = new Event('keydown', { cancelable: true });
    const up = new Event('keyup', { cancelable: true });
    for (const event of [down, up]) {
      Object.defineProperties(event, { key: { value: ' ' }, code: { value: 'Space' },
        composedPath: { value: () => [summary, document] } });
    }
    await act(async () => { document.dispatchEvent(down); document.dispatchEvent(up); });
    return down.defaultPrevented;
  }
  await act(async () => { tree = create(React.createElement(GraphShortcut, { active: true })); });
  assert.equal(await space(), true, 'mounted graph cancels native summary Space activation');
  await act(async () => tree.update(React.createElement(GraphShortcut, { active: false })));
  assert.equal(await space(), false, 'hidden graph must release the document shortcut');
  await act(async () => tree.update(React.createElement(GraphShortcut, { active: true })));
  assert.equal(await space(), true, 'returning monitor retains its Space-pan behavior');
});
