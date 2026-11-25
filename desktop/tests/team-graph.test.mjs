import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const desktop = fileURLToPath(new URL('..', import.meta.url));

// Controlled component regression, not screenshot-driven installed-App acceptance.
// Use the shipped React Flow and browser selectors/events; no callback shell.
test('real TeamGraph handles connect, reconnect and disconnect encoded occurrences', async t => {
  const directory = await fs.mkdtemp(path.join(desktop, 'node_modules/.team-graph-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const initial = {
    'studio.lead': { 'studio.worker': {} }, 'studio.leaf': {},
    'other.lead': { 'studio.worker': { 'other.child': {} } },
  };
  await build({ stdin: { contents: `
    import React, {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {TeamGraph} from './src/TeamGraph';
    const initial = ${JSON.stringify(initial)};
    function Fixture() {
      const [tree,setTree] = useState(initial), [selected,setSelected] = useState(''), [error,setError] = useState('');
      return <><TeamGraph tree={tree} references={['studio.lead','studio.worker','studio.leaf']}
        roles={{}} renames={{}} selected={selected} busy={false} onSelect={setSelected}
        onChange={next => {setTree(next);setError('');}} onError={setError} modelLabel={() => 'Controlled model'}/>
        <output id="selected">{selected}</output><output id="error">{error}</output><pre id="tree">{JSON.stringify(tree)}</pre></>;
    }
    createRoot(document.getElementById('root')).render(<Fixture/>);
  `, resolveDir: desktop, loader: 'tsx' }, outfile: path.join(directory, 'fixture.js'),
    bundle: true, platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } });
  await fs.writeFile(path.join(directory, 'index.html'), `<!doctype html><link rel="stylesheet" href="fixture.css">
    <style>.d-team-flow{height:650px;width:1100px}.d-org-node{width:160px;height:100px;border:1px solid;display:flex;flex-direction:column;background:white}.react-flow__handle{width:14px;height:14px}</style>
    <div id="root"></div><script src="fixture.js"></script>`);
  const browser = await chromium.launch({ headless: true,
    ...(process.env.GRAPHTRAJ_CHROMIUM ? { executablePath: process.env.GRAPHTRAJ_CHROMIUM } : {}) });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(path.join(directory, 'index.html')).href);
  // React Flow 12 gives a focusable node wrapper role 'group' with the node's ariaLabel
  // (TeamGraph.tsx `Configure agent <team.name>`); edges are groups named 'Edge from …', so no clash.
  const node = (name, index = 0) => page.getByRole('group', { name: `Configure agent studio.${name}`, exact: true }).nth(index);
  const handle = (name, type, index = 0) => node(name, index).locator(`.react-flow__handle.${type}`);
  await handle('leaf', 'target').waitFor({ state: 'visible' });
  // Card contents and handle names (Task 627 V8): name, 'Runtime · model', tags; handle names unchanged.
  const card = (name, index = 0) => node(name, index).locator('.d-org-node').evaluate(element => ({
    name: element.querySelector(':scope > strong')?.textContent, model: element.querySelector(':scope > small')?.textContent,
    tags: [...element.querySelectorAll('.d-org-tags > *')].map(tag => tag.textContent) }));
  assert.deepEqual(await card('leaf'), { name: 'leaf', model: 'Controlled model', tags: ['Default effort'] });
  assert.deepEqual(await card('worker', 1), { name: 'worker', model: 'Controlled model', tags: ['Default effort', 'Cross-team parent · preserved'] });
  assert.equal(await handle('leaf', 'target').getAttribute('aria-label'), 'Parent connection');
  assert.equal(await handle('leaf', 'source').getAttribute('aria-label'), 'Connect a child');
  /** Each tree change remounts the flow (TeamGraph keys it by occurrence IDs) and fits the view again,
   * so wait until both endpoints are measured and stay put for a frame before dragging. */
  async function settled(locator) {
    await locator.waitFor({ state: 'visible' });
    let previous = null;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const box = await locator.boundingBox();
      if (box && previous && JSON.stringify(box) === JSON.stringify(previous)) return box;
      previous = box;
    }
    assert.fail('graph position did not settle');
  }
  async function drag(from, to) {
    await settled(from); await settled(to);
    const a = await from.boundingBox(), b = await to.boundingBox();
    assert.ok(a && b);
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 });
    await page.mouse.up();
  }
  async function expectTree(expected) {
    await page.waitForFunction(expected => {
      const ordered = tree => Object.fromEntries(Object.entries(tree).sort().map(([key, children]) => [key, ordered(children)]));
      return JSON.stringify(ordered(JSON.parse(document.querySelector('#tree').textContent))) === JSON.stringify(ordered(expected));
    }, expected, { timeout: 3000 });
    assert.deepEqual(JSON.parse(await page.locator('#tree').textContent()), expected);
    assert.deepEqual(errors, []);
  }
  const edgeById = id => page.locator('.react-flow__edge').locator(`xpath=self::*[@data-id='${id}']`);
  const disconnect = page.getByRole('button', { name: 'Disconnect parent · make root', exact: true });
  /** Click the edge's own path at its midpoint, as a user would. A straight edge's path has a zero-width
   * box, which Playwright treats as invisible, but its 20 px interaction stroke is clickable; so the point
   * is taken on the path (getPointAtLength at half length, mapped by getScreenCTM) once it stops moving.
   * Selection is proven by TeamGraph's Disconnect control appearing enabled for that edge. */
  async function selectEdge(id) {
    const path = edgeById(id).locator('.react-flow__edge-interaction');
    await path.waitFor({ state: 'attached' });
    const midpoint = () => path.evaluate(element => {
      const point = element.getPointAtLength(element.getTotalLength() / 2), matrix = element.getScreenCTM();
      return { x: matrix.a * point.x + matrix.c * point.y + matrix.e, y: matrix.b * point.x + matrix.d * point.y + matrix.f };
    });
    let previous = null, point = null;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      point = await midpoint();
      if (previous && point.x === previous.x && point.y === previous.y) break;
      previous = point;
    }
    assert.ok(point && previous && point.x === previous.x && point.y === previous.y, 'edge position did not settle');
    await page.mouse.click(point.x, point.y);
    await disconnect.waitFor({ state: 'visible' });
    assert.equal(await disconnect.isEnabled(), true, 'selecting the edge offers an enabled Disconnect');
  }
  await drag(handle('lead', 'source'), handle('leaf', 'target'));
  await expectTree({ 'studio.lead': { 'studio.worker': {}, 'studio.leaf': {} }, 'other.lead': initial['other.lead'] });
  await node('leaf').click();
  assert.equal(await page.locator('#selected').textContent(), 'studio.leaf');
  // Select the incoming leaf edge, then drag its source endpoint to worker.
  // Distinguish the leaf edge by its target data ID, read from the real node.
  const leafId = await node('leaf').getAttribute('data-id');
  const leafEdge = edgeById(leafId);
  await selectEdge(leafId);
  await drag(leafEdge.locator('.react-flow__edgeupdater-source'), handle('worker', 'source'));
  await expectTree({ 'studio.lead': { 'studio.worker': { 'studio.leaf': {} } }, 'other.lead': initial['other.lead'] });
  const movedId = await node('leaf').getAttribute('data-id');
  await selectEdge(movedId);
  await disconnect.click();
  await expectTree(initial);
  // Actual handle lookup must also reach, and preserve state on, cycle validation.
  await drag(handle('worker', 'source'), handle('lead', 'target'));
  await page.waitForFunction(() => document.querySelector('#error').textContent.includes('descendants'));
  await expectTree(initial);
});
