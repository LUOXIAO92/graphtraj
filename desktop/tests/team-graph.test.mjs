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
  const node = (name, index = 0) => page.getByRole('button', { name: `Configure agent studio.${name}`, exact: true }).nth(index);
  const handle = (name, type) => node(name).locator(`.react-flow__handle.${type}`);
  await handle('leaf', 'target').waitFor({ state: 'visible' });
  async function drag(from, to) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
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
  await drag(handle('lead', 'source'), handle('leaf', 'target'));
  await expectTree({ 'studio.lead': { 'studio.worker': {}, 'studio.leaf': {} }, 'other.lead': initial['other.lead'] });
  await node('leaf').click();
  assert.equal(await page.locator('#selected').textContent(), 'studio.leaf');
  // Select the incoming leaf edge, then drag its source endpoint to worker.
  // Distinguish the leaf edge by its target data ID, read from the real node.
  const leafId = await node('leaf').getAttribute('data-id');
  const edge = page.locator('.react-flow__edge').filter({ has: page.locator('.react-flow__edgeupdater-source') });
  const leafEdge = edge.locator(`xpath=self::*[@data-id='${leafId}']`);
  await leafEdge.locator('.react-flow__edge-interaction').click();
  await drag(leafEdge.locator('.react-flow__edgeupdater-source'), handle('worker', 'source'));
  await expectTree({ 'studio.lead': { 'studio.worker': { 'studio.leaf': {} } }, 'other.lead': initial['other.lead'] });
  const movedId = await node('leaf').getAttribute('data-id');
  await page.locator('.react-flow__edge').locator(`xpath=self::*[@data-id='${movedId}']`).locator('.react-flow__edge-interaction').click();
  await page.getByRole('button', { name: 'Disconnect parent · make root' }).click();
  await expectTree(initial);
  // Actual handle lookup must also reach, and preserve state on, cycle validation.
  await drag(handle('worker', 'source'), handle('lead', 'target'));
  await page.waitForFunction(() => document.querySelector('#error').textContent.includes('descendants'));
  await expectTree(initial);
});
