/** Installed D presentation adoption. Reuses the established platform packaging and native fixture seams. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Controlled native records belong only on disposable CI hosts');
const require = createRequire(import.meta.url);
const evidence = path.resolve(process.env.D_ADOPTION_EVIDENCE || 'test-results/d-adoption');
const work = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-d-adoption-'));
const executablePath = process.platform === 'win32' ? process.env.GRAPHTRAJ_WIN_EXE
  : process.platform === 'darwin' ? '/Applications/GraphTraj.app/Contents/MacOS/GraphTraj'
  : '/opt/graphtraj-desktop/graphtraj-desktop-bin';
assert.ok(executablePath);
const facts = { source: process.env.GITHUB_SHA, platform: process.platform, arch: process.arch,
  node: process.version, os: os.release(), executablePath, passed: false, steps: [], screenshots: [],
  data: 'Controlled retained records through the installed native desktop APIs; no model execution. System picker and review responses are controlled; prior native-dialog/platform evidence is reused.',
  pageErrors: [] };
await fs.mkdir(evidence, { recursive: true });
const step = message => { facts.steps.push(message); console.log(message); };
const first = await fixtures.makeProject(path.join(work, 'delivery-project'), 'connect-provider');
const second = await fixtures.makeProject(path.join(work, 'documentation-project'), 'documentation');
for (const [id, name, dependencies] of [['3','usage-accounting',['1']], ['4','agent-timeline',['1']], ['5','desktop-integration',['2','3','4']], ['6','retained-experiment',[]]]) {
  fixtures.operate(first, 'ticket_register', fixtures.ticket(id, name, dependencies));
}
const time = new Date().toISOString();
const tokens = { input_tokens: 100000, cached_input_tokens: 60000, output_tokens: 8000 };
const records = name => [
  { timestamp: time, type: 'turn_context', payload: { model: 'gpt-5.3-codex', turn_id: `${name}-turn` } },
  ...Array.from({ length: 72 }, (_, i) => ({ timestamp: time, type: 'response_item', payload: {
    type: 'message', role: 'assistant', content: [{ type: 'output_text', text: `Controlled retained ${name} message ${i}.\n\nThis record checks independent reading and long output. ` + 'Recorded text stays available while changing pages. '.repeat(15) }],
  } })),
  { timestamp: time, type: 'response_item', payload: { type: 'function_call', call_id: `${name}-read`, name: 'read_file', arguments: JSON.stringify({ path: 'controlled-example.ts' }) } },
  { timestamp: time, type: 'response_item', payload: { type: 'function_call_output', call_id: `${name}-read`, output: 'Controlled retained tool output\n' + 'line of recorded output\n'.repeat(50) } },
  { timestamp: time, type: 'event_msg', payload: { type: 'token_count', info: { last_token_usage: tokens, total_token_usage: tokens } } },
];
await fixtures.recordActivity(first, { ticketId: '1', ticketName: 'connect-provider', alias: 'previous@engineer', records: records('previous'),
  additionalMembers: ['lead','engineer','reviewer'].map(name => ({ alias: `current@${name}`, records: records(name), historical: false })) });
await fixtures.recordActivity(second, { ticketId: '1', ticketName: 'documentation', alias: 'docs@writer', records: records('docs') });
const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
await fs.writeFile(rolesFile, `roles:
  delivery:
    lead: {runtime: codex, model: gpt-5.3-codex, instructions: seed.txt}
    engineer: {runtime: codex, model: gpt-5.3-codex, reports: [report.md]}
    reviewer: {runtime: pi, model: openai/gpt-5.3-codex}
    writer: {runtime: codex, model: gpt-5.3-codex}
role_tree:
  delivery.lead:
    delivery.engineer:
      delivery.writer: {}
    delivery.reviewer: {}
`);
let app;
let page;
let approvals = [];
try {
  const loader = path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/server/electron/loader.js');
  app = await electron.launch({ executablePath, args: [
    ...(process.platform === 'darwin' ? ['-r', loader] : []),
    ...(process.platform === 'linux' ? ['--ozone-platform=x11'] : []),
    `--user-data-dir=${path.join(work,'preferences')}`, `--project=${first}`,
  ], timeout: 30000 });
  page = await app.firstWindow(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => facts.pageErrors.push(String(error)));
  facts.installed = await app.evaluate(({ app, BrowserWindow }) => ({ packaged: app.isPackaged, appPath: app.getAppPath(), sandbox: BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences().sandbox }));
  assert.equal(facts.installed.packaged, true); assert.equal(facts.installed.sandbox, true);
  const button = name => page.getByRole('button', { name, exact: true });
  const field = name => page.getByLabel(name, { exact: true });
  const dialogButton = name => page.getByRole('dialog').getByRole('button', { name, exact: true });
  const monitor = page.locator('.monitor-page:visible');
  const selectProject = name => page.locator('.project-button').filter({ hasText: name }).click();
  async function size(width, height) {
    await app.evaluate(({ BrowserWindow }, dimensions) => { const window=BrowserWindow.getAllWindows()[0]; window.setPosition(0,0); window.setContentSize(...dimensions); }, [width,height]);
    await page.waitForFunction(({ width,height }) => innerWidth === width && innerHeight === height, {width,height});
    const layout = page.getByRole('button',{name:'Auto layout',exact:true}); if(await layout.isVisible()) await layout.click();
  }
  async function shot(name) {
    const dimensions = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
    const file = `${name}-${dimensions.width}.png`;
    const bytes = await page.screenshot({ path: path.join(evidence,file) });
    assert.equal(bytes.readUInt32BE(16), dimensions.width);
    assert.equal(bytes.readUInt32BE(20), dimensions.height);
    facts.screenshots.push({file,...dimensions,sha256:createHash('sha256').update(bytes).digest('hex')});
  }
  async function decide(response) {
    await app.evaluate(({ dialog }, value) => { globalThis.__dApprovals ??= []; dialog.showMessageBox = async (_window, proposal) => { globalThis.__dApprovals.push({ title: proposal.title, message: proposal.message, detail: proposal.detail, response: value }); return { response: value, checkboxChecked: false }; }; }, response);
  }
  async function reviewSave(name) { await button('Review changes').click(); await dialogButton(name).click(); }
  await monitor.locator('.react-flow__node[data-id="1"]').waitFor();
  await size(1440,1000);
  // Picker API response is controlled, while the production native add/index path executes unchanged.
  await app.evaluate(({ dialog }, directory) => { dialog.showOpenDialog = async () => ({ canceled:false, filePaths:[directory] }); }, second);
  await button('Add or manage projects').click(); await button('Add project').click();
  await page.locator('.d-project-index-table').getByText('documentation-project', {exact:true}).waitFor();
  await selectProject('delivery-project');
  const prefs = await page.evaluate(() => window.graphtraj.projects());
  const firstId = prefs.projects.find(item => item.root === first).id;
  const secondId = prefs.projects.find(item => item.root === second).id;
  assert.ok(firstId && secondId);
  await monitor.locator('.react-flow__node[data-id="1"]').click();
  await monitor.locator('.d-task-shelf .member-pills button').nth(3).waitFor();
  const members = await page.evaluate(id => window.graphtraj.activity(id,{ticket_id:'1'}),firstId);
  assert.equal(members.agents.length,4);
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('monitor-details'); }
  await size(1440,1000); await button('Expand chat').click();
  const columns = monitor.locator('.agent-column');
  await columns.nth(3).locator('.activity-event').first().waitFor();
  assert.equal(await columns.count(),4);
  await columns.first().getByRole('button',{name:'Pause following',exact:true}).click();
  await columns.nth(1).getByRole('button',{name:'Pause following',exact:true}).click();
  const positions = await monitor.evaluate(element => {
    const histories = element.querySelectorAll('.activity-history'); histories[0].scrollTop=220; histories[1].scrollTop=470;
    const horizontal = element.querySelector('.agent-columns'); horizontal.scrollLeft=150;
    return [histories[0].scrollTop,histories[1].scrollTop,horizontal.scrollLeft];
  });
  assert.ok(positions.every(value=>value>0));
  await button('Teams & roles').click(); await button('Monitor').click();
  assert.deepEqual(await monitor.evaluate(element => [element.querySelectorAll('.activity-history')[0].scrollTop,element.querySelectorAll('.activity-history')[1].scrollTop,element.querySelector('.agent-columns').scrollLeft]),positions);
  await selectProject('documentation-project'); await selectProject('delivery-project');
  assert.deepEqual(await monitor.evaluate(element => [element.querySelectorAll('.activity-history')[0].scrollTop,element.querySelectorAll('.activity-history')[1].scrollTop,element.querySelector('.agent-columns').scrollLeft]),positions);
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await monitor.locator('.agent-columns').evaluate(element=>element.scrollLeft=0); await shot('expanded-chat'); const slider = field('Agent columns horizontal scrollbar'); const box = await slider.boundingBox(); const thumb = await slider.evaluate(element => parseFloat(getComputedStyle(element).getPropertyValue('--scroll-thumb-width'))); await page.mouse.move(box.x + thumb / 2 + 8, box.y + box.height / 2); await page.mouse.down(); await page.mouse.move(box.x + box.width - thumb / 2 - 8, box.y + box.height / 2, {steps:10}); await page.mouse.up(); assert.ok(Number(await slider.inputValue()) > 0); await shot('expanded-chat-last'); }
  await size(1440,1000); await monitor.locator('.agent-columns').evaluate(element=>element.scrollLeft=0);
  await columns.first().getByRole('button',{name:/Follow new messages/}).click();
  const tool = columns.first().locator('.tool-card').first();
  await tool.waitFor();
  for (const open of [true,false,true,false]) { await tool.locator('summary').click(); assert.equal(await tool.evaluate(element=>element.open),open); }
  await button('Hide sidebar').click(); await shot('chat-sidebar-hidden'); await button('Show sidebar').click();
  step('Installed D graph, details, current/history columns, independent scroll, repeated tools, draggable reading and cross-project retention passed.');
  await button('Project usage').click();
  await page.locator('.d-dated-records > div').first().waitFor();
  const date = new Date().toLocaleDateString('en-CA');
  await field('Start date').fill(date); await field('End date').fill(date);
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('project-usage'); }
  await field('Start date').fill('2099-01-02'); await field('End date').fill('2099-01-01');
  await page.locator('.d-usage-date-note[role="alert"]').waitFor();
  assert.equal(await page.locator('[data-usage-cost]').innerText(),'—');
  await button('All project usage').click();
  await page.locator('.d-project-usage-table tbody tr').nth(1).waitFor();
  assert.equal(await page.locator('.usage-filters select').count(),0);
  assert.ok(!(await page.locator('.usage-dashboard').innerText()).includes('current@engineer'));
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('global-usage'); }
  step('Installed dated project/global history, invalid dates, missing-field and project-only global scope passed.');
  await size(1440,1000); await button('Settings').click(); await button('Agents & models').click();
  await page.locator('.d-library-tree').waitFor();
  await button('Add Runtime').click(); await field('Runtime entry name').fill('shared'); await dialogButton('Add runtime').click();
  await field('Runtime Home').fill(path.join(work,'runtime-home'));
  await page.locator('.d-library-detail-heading').getByRole('button',{name:'Add provider',exact:true}).click();
  await field('Provider name').fill('custom'); await dialogButton('Add provider').click();
  await field('Base URL').fill('https://provider.invalid/v1'); await field('API key environment variable').fill('D_ADOPTION_MODEL_KEY');
  await page.locator('.d-library-detail-heading').getByRole('button',{name:'Add model',exact:true}).click();
  await field('Model entry name').fill('model'); await field('Model identifier').fill('configured-model'); await field('Model alias').fill('Configured model'); await dialogButton('Add model').click();
  const originalCatalog = await page.evaluate(id=>window.graphtraj.connections(id,{action:'read'}), firstId);
  await decide(0); await reviewSave('Save connections');
  await page.getByRole('dialog').getByRole('alert').waitFor();
  assert.deepEqual((await page.evaluate(id=>window.graphtraj.connections(id,{action:'read'}),firstId)).catalog,originalCatalog.catalog);
  await decide(1); await dialogButton('Save connections').click(); await page.getByRole('status').filter({hasText:'Connections saved.'}).waitFor();
  await page.locator('.library-select').filter({hasText:'shared'}).click();
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('agents-models'); }
  await page.getByRole('button',{name:'Expand shared / custom provider',exact:true}).click();
  await page.locator('.library-models').getByRole('button',{name:'Configured model',exact:true}).click();
  await field('Model alias').fill('Updated model alias');
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('model-edit'); }
  await button('Cancel changes').click();
  await button('Teams & roles').click(); await page.locator('.d-org-node').nth(3).waitFor();
  await page.getByRole('button',{name:'Configure agent delivery.engineer',exact:true}).click();
  await field('Agent Runtime').selectOption('shared'); await field('Reasoning effort').fill('high');
  await page.locator('summary').filter({hasText:'Prompt layers'}).click();
  await field('System prompt').fill('Report recorded evidence to the parent.');
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('teams-edit'); }
  await size(1440,1000); await page.locator('summary').filter({hasText:'Codex approval route'}).click();
  await field('Codex approval model').fill('approval-model'); await field('Codex approval Base URL').fill('https://review.invalid/v1'); await field('Codex approval api_key_env name').fill('D_ADOPTION_APPROVAL_KEY');
  await decide(1); await reviewSave('Save changes'); await page.getByRole('status').filter({hasText:'Settings saved.'}).waitFor();
  const savedRoles = await page.evaluate(id=>window.graphtraj.settings(id),firstId);
  assert.equal(savedRoles.roles['delivery.engineer'].connection,'shared/custom/model');
  assert.equal(savedRoles.roles['delivery.engineer'].reasoning_effort,'high');
  assert.match(await fs.readFile(rolesFile,'utf8'),/report.md/);
  const secondRoles = await page.evaluate(id=>window.graphtraj.settings(id),secondId);
  assert.ok(!secondRoles.roles['delivery.engineer']);
  // A real concurrent native save must invalidate the UI revision without discarding the draft.
  await field('Reasoning effort').fill('low');
  await page.evaluate(async id => { const current=await window.graphtraj.settings(id); await window.graphtraj.saveSettings(id,{revision:current.revision,edits:{'delivery.engineer':{reasoning_effort:'medium'}},renames:{},add_edges:[],remove_edges:[]}); },firstId);
  await reviewSave('Save changes'); await page.getByRole('dialog').getByRole('alert').waitFor();
  assert.equal((await page.evaluate(id=>window.graphtraj.settings(id),firstId)).roles['delivery.engineer'].reasoning_effort,'medium');
  await dialogButton('Keep editing').click(); assert.equal(await field('Reasoning effort').inputValue(),'low'); await button('Reload').click();
  step('Installed global and team D editing reaches native preview/save; denial retains the draft, approval saves and revision conflict refuses overwrite.');
  await button('Add or manage projects').click();
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('project-index'); }
  approvals = await app.evaluate(()=>globalThis.__dApprovals);
  facts.approvalCount=approvals.length;
  facts.approvalResponses=approvals.map(item=>item.response);
  assert.deepEqual(facts.pageErrors,[]);
  await app.close(); app=null;
  assert.equal(fixtures.operate(first,'ticket_graph').tickets.length,6);
  facts.passed=true;
  step('Closing the optional desktop leaves the native graph available. Unchanged live-Runner optionality and real system-dialog/platform evidence are reused from prior delivery.');
} catch(error) {
  facts.error=String(error.stack || error);
  if(page) { await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{}); }
  throw error;
} finally {
  if(app) await app.close().catch(error=>{facts.cleanupError=String(error);});
  await fs.writeFile(path.join(evidence,'d-adoption.json'),JSON.stringify(facts,null,2)+'\n');
}
