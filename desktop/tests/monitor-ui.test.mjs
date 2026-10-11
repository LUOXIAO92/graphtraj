import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// A renderer behavior check with an explicit API double; never native acceptance.
test('D navigation preserves separate project graphs and independent column reading positions', async t => {
  const browser = await chromium.launch({ headless: true, args: ['--allow-file-access-from-files'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => {
    const projects = [{ id: 'first', root: '/projects/first' }, { id: 'second', root: '/projects/second' }];
    let selected = 'first';
    window.graphtraj = {
      projects: async () => ({ projects, selected }),
      selectProject: async id => ({ projects, selected: selected = id }),
      graph: async projectId => ({ projectId, updatedAt: new Date().toISOString(), graph: { tickets: [
        { ticket_id: '1', ticket_name: 'current', title: `${projectId} current`, status: 'implementing', active: true, dependencies: [], replaced_by: [] },
        { ticket_id: '2', ticket_name: 'previous', title: `${projectId} previous`, status: 'integrated', active: false, dependencies: ['1'], replaced_by: ['1'] },
      ] } }),
      activity: async (projectId, request) => {
        const agents = ['alpha', 'beta', 'historical', 'delta'].map(alias => ({ alias,
          historical: alias === 'historical', state: alias === 'historical' ? 'retired' : 'running', runtime: 'codex' }));
        return { ticket_id: request.ticket_id, agents, updated_at: new Date().toISOString(),
          availability: 'available', cursor: '80', has_more: false,
          events: !request.alias || request.cursor ? [] : Array.from({ length: 80 }, (_, i) => ({
            id: `${projectId}:${request.alias}:${i}`, kind: i === 79 ? 'tool' : 'message',
            phase: i === 79 ? 'result' : undefined, name: i === 79 ? 'read file' : undefined,
            text: `${projectId} ${request.alias} record ${i}\n` + 'Long readable record. '.repeat(50),
            time: null, source: { runtime: 'codex', offset: i },
          })),
        };
      },
      settings: async () => ({ revision: '1', roles: {'delivery.root':{runtime:'codex',model:'recorded-model'}}, edges: [], role_tree: {'delivery.root':{}}, effect: 'No changes' }),
      connections: async () => ({revision:'1',catalog:{version:1,runtimes:{}},capabilities:{model_discovery:{},custom_api:{}},account_access:'unknown'}),
      copyText: async () => {},
    };
  });
  await page.goto(new URL('../dist/index.html', import.meta.url).href);
  const monitor = page.locator('.monitor-page:visible');
  const visibleGraphTitles = () => page.locator('.react-flow__node').evaluateAll(nodes =>
    nodes.filter(node => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }))
      .map(node => node.querySelector('.node-title')?.textContent));
  await page.getByRole('button', { name: 'Settings', exact: true }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'GLOBAL', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Settings', exact: true }).isVisible(), false);
  await page.getByRole('button', { name: 'PROJECTS', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Monitor', exact: true }).isVisible(), true);
  await page.getByRole('button', { name: 'GLOBAL', exact: true }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Agents & models', exact: true }).isVisible(), true);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Agents & models', exact: true }).isVisible(), false);
  await monitor.getByRole('searchbox').fill('first current');
  await monitor.getByRole('searchbox').press('Enter');
  await monitor.getByRole('button', { name: 'Expand chat', exact: true }).click();
  const columns = monitor.locator('.agent-column');
  await columns.first().locator('.tool-card').last().waitFor();
  assert.deepEqual(await visibleGraphTitles(), [], 'Expanded chat hides its mounted graph');
  assert.equal(await columns.count(), 4);
  await columns.nth(2).getByText('Historical · retired', { exact: true }).waitFor();
  for (const index of [0, 1]) {
    await columns.nth(index).getByRole('button', { name: 'Pause following', exact: true }).click();
  }
  const positions = await monitor.evaluate(element => {
    const histories = element.querySelectorAll('.activity-history');
    histories[0].scrollTop = 210; histories[1].scrollTop = 475;
    const horizontal = element.querySelector('.agent-columns');
    horizontal.scrollLeft = 155;
    return { first: histories[0].scrollTop, second: histories[1].scrollTop, horizontal: horizontal.scrollLeft };
  });
  assert.ok(positions.first > 0 && positions.second > positions.first && positions.horizontal > 0);
  await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
  await page.getByLabel('Agent name', {exact:true}).fill('edited');
  await page.getByRole('button', { name: 'Monitor', exact: true }).click();
  const restored = await monitor.evaluate(element => ({ first: element.querySelectorAll('.activity-history')[0].scrollTop,
    second: element.querySelectorAll('.activity-history')[1].scrollTop, horizontal: element.querySelector('.agent-columns').scrollLeft }));
  assert.deepEqual(restored, positions);
  await page.getByRole('button', { name: 'PROJECTS', exact: true }).click();
  await page.locator('.project-button').filter({ hasText: '/projects/second' }).click();
  await monitor.getByRole('searchbox').fill('second current');
  await monitor.locator('.react-flow__node[data-id="1"] .node-title').waitFor();
  assert.deepEqual(await visibleGraphTitles(), ['second current', 'second previous'], 'Only the selected project paints graph cards');
  await monitor.getByRole('searchbox').press('Enter');
  await monitor.getByRole('button', { name: 'Expand chat', exact: true }).click();
  await monitor.locator('.agent-column').first().locator('.tool-card').last().waitFor();
  assert.deepEqual(await visibleGraphTitles(), [], 'Neither mounted project may paint over expanded chat');
  assert.equal(await monitor.getByText('first alpha record 79', { exact: false }).count(), 0);
  await page.locator('.project-button').filter({ hasText: '/projects/first' }).click();
  assert.equal(await monitor.locator('input[aria-label="Search tasks"]').inputValue(), 'first current');
  assert.deepEqual(await visibleGraphTitles(), [], 'Returning to preserved chat keeps other project graphs invisible');
  const again = await monitor.evaluate(element => ({ first: element.querySelectorAll('.activity-history')[0].scrollTop,
    second: element.querySelectorAll('.activity-history')[1].scrollTop, horizontal: element.querySelector('.agent-columns').scrollLeft }));
  assert.deepEqual(again, positions);
  await monitor.locator('.agent-columns').evaluate(element => { element.scrollLeft = 0; });
  await columns.first().getByRole('button', { name: 'Follow new messages', exact: false }).click();
  const tool = columns.first().locator('details').last();
  for (const open of [true, false, true, false]) {
    await tool.locator('summary').click();
    assert.equal(await tool.evaluate(element => element.open), open);
  }
  await monitor.getByRole('button', { name: 'Collapse chat', exact: true }).click();
  const viewport = await monitor.locator('.react-flow__viewport').getAttribute('style');
  await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
  await page.getByRole('button', { name: 'Monitor', exact: true }).click();
  assert.equal(await monitor.locator('.react-flow__viewport').getAttribute('style'), viewport);
  await page.getByRole('button', { name: 'Hide sidebar', exact: true }).click();
  assert.equal(await page.locator('#d-project-sidebar').isVisible(), false);
  await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Monitor', exact: true }).isVisible(), true);
  assert.equal(await page.getByRole('textbox').count(), 0, 'monitor has no message input');
  await page.getByRole('button', {name:'Teams & roles',exact:true}).click();
  assert.equal(await page.getByLabel('Agent name',{exact:true}).inputValue(),'edited');

});
