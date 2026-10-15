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
const roleFlow = process.env.D_ADOPTION_SCOPE === 'roles-291';
assert.ok(['all', 'roles-291'].includes(process.env.D_ADOPTION_SCOPE || 'all'));
const require = createRequire(import.meta.url);
const evidence = path.resolve(process.env.D_ADOPTION_EVIDENCE || 'test-results/d-adoption');
const work = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-d-adoption-'));
const executablePath = process.platform === 'win32' ? process.env.GRAPHTRAJ_WIN_EXE
  : process.platform === 'darwin' ? '/Applications/GraphTraj.app/Contents/MacOS/GraphTraj'
  : '/opt/graphtraj-desktop/graphtraj-desktop-bin';
assert.ok(executablePath);
const facts = { source: process.env.GITHUB_SHA, platform: process.platform, arch: process.arch,
  scope: roleFlow ? 'roles-291' : 'all', command: 'node tests/d-adoption.mjs', startedAt: new Date().toISOString(),
  node: process.version, os: os.release(), executablePath, passed: false, steps: [], screenshots: [],
  data: 'Controlled retained records through the installed native desktop APIs; no model execution. System picker and review responses are controlled; prior native-dialog/platform evidence is reused.',
  pageErrors: [] };
await fs.mkdir(evidence, { recursive: true });
const step = message => { facts.steps.push(message); console.log(message); };
let app;
let page;
let approvals = [];
try {
const first = await fs.realpath(await fixtures.makeProject(path.join(work, 'delivery-project'), 'connect-provider'));
const second = await fs.realpath(await fixtures.makeProject(path.join(work, 'documentation-project'), 'documentation'));
if (!roleFlow) {
for (const [id, name, dependencies] of [['3','usage-accounting',['1']], ['4','agent-timeline',['1']], ['5','desktop-integration',['2','3','4']], ['6','retained-experiment',[]]]) {
  fixtures.operate(first, 'task_register', fixtures.task(id, name, dependencies));
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
await fixtures.recordActivity(first, { taskId: '1', taskName: 'connect-provider', alias: 'previous-handover0-engineer@engineer', records: records('previous'),
  additionalMembers: ['lead','engineer','reviewer'].map(name => ({ alias: `current-handover0-${name}@${name}`, records: records(name), historical: false })) });
await fixtures.recordActivity(second, { taskId: '1', taskName: 'documentation', alias: 'docs-handover0-writer@writer', records: records('docs') });
}
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
  async function launch() {
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
  }
  await launch();
  const button = name => page.getByRole('button', { name, exact: true });
  const field = name => page.getByLabel(name, { exact: true }).filter({visible:true});
  const dialogButton = name => page.getByRole('dialog').getByRole('button', { name, exact: true });
  const monitor = page.locator('.monitor-page:visible');
  async function selectProject(name) {
    const project = page.locator('.project-button').filter({ hasText: name });
    await project.click();
    // Native index selection is asynchronous; observe its committed UI state
    // before reading the preserved monitor or issuing another selection.
    await project.and(page.locator('[aria-current="true"]:enabled')).waitFor();
  }
  async function size(width, height) {
    await app.evaluate(({ BrowserWindow }, dimensions) => { const window=BrowserWindow.getAllWindows()[0]; window.setPosition(0,0); window.setContentSize(...dimensions); }, [width,height]);
    await page.waitForFunction(({ width,height }) => innerWidth === width && innerHeight === height, {width,height});
    const layout = page.getByRole('button',{name:'Auto layout',exact:true}); if(await layout.isVisible()) { await layout.click(); await page.waitForTimeout(250); }
  }
  async function shot(name) {
    if (name.startsWith('expanded-chat') || name.startsWith('chat-sidebar-hidden')) {
      const paintedNodes = await page.locator('.react-flow__node').evaluateAll(nodes =>
        nodes.filter(node => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })).map(node => node.textContent));
      assert.deepEqual(paintedNodes, [], 'Expanded chat must not paint graph cards from any mounted project');
    }
    const dimensions = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, devicePixelRatio }));
    const file = `${name}-${dimensions.width}.png`;
    const bytes = await page.screenshot({ path: path.join(evidence,file), scale: 'css' });
    assert.equal(bytes.readUInt32BE(16), dimensions.width);
    assert.equal(bytes.readUInt32BE(20), dimensions.height);
    facts.screenshots.push({file,...dimensions,sha256:createHash('sha256').update(bytes).digest('hex')});
  }
  async function decide(response) {
    await app.evaluate(({ dialog }, value) => { globalThis.__dApprovals ??= []; dialog.showMessageBox = async (_window, proposal) => { globalThis.__dApprovals.push({ title: proposal.title, message: proposal.message, detail: proposal.detail, response: value }); return { response: value, checkboxChecked: false }; }; }, response);
  }
  async function reviewSave(name) { await button('Review changes').click(); await dialogButton(name).click(); }
  /** Use real installed controls and native saves; only native review responses are controlled. */
  async function roleCreationAdoption() {
    await monitor.locator('.react-flow__node[data-id="1"]').waitFor();
    const prefs = await page.evaluate(() => window.graphtraj.projects());
    const projectId = prefs.projects.find(item => item.root === first)?.id;
    assert.ok(projectId);
    const read = () => page.evaluate(id => window.graphtraj.settings(id), projectId);
    const original = await read();
    const originalBytes = await fs.readFile(rolesFile);
    const legacyRoles = fixtures.operate(first,'role_organization').roles.delivery;
    const connection = 'shared/custom/model';
    const newRefs = ['research.root', 'research.child', 'research.independent'];
    facts.originalRoles = original.roles;
    await size(1440,1000);
    await button('Settings').click(); await button('Agents & models').click();
    await page.locator('.d-library-tree').waitFor();
    await button('Add Runtime').click(); await field('Runtime entry name').fill('shared');
    await field('Runtime type').selectOption('codex'); await dialogButton('Add runtime').click();
    await field('Runtime Home').fill(path.join(work,'runtime-home'));
    await page.locator('.d-library-detail-heading').getByRole('button',{name:'Add provider',exact:true}).click();
    await field('Provider name').fill('custom'); await dialogButton('Add provider').click();
    await field('Base URL').fill('https://provider.invalid/v1');
    await field('API key environment variable').fill('D_ADOPTION_MODEL_KEY');
    await page.locator('.d-library-detail-heading').getByRole('button',{name:'Add model',exact:true}).click();
    await field('Model entry name').fill('model'); await field('Model identifier').fill('configured-model');
    await field('Model alias').fill('Configured model'); await dialogButton('Add model').click();
    await decide(1); await reviewSave('Save connections');
    await page.getByRole('status').filter({hasText:'Connections saved.'}).waitFor();
    const catalog = await page.evaluate(id => window.graphtraj.connections(id,{action:'read'}),projectId);
    assert.equal(catalog.catalog.runtimes.shared.runtime,'codex');
    assert.equal(catalog.catalog.runtimes.shared.providers.custom.models.model.id,'configured-model');
    facts.catalog = catalog.catalog;
    await shot('291-global-model');
    await button('Teams & roles').click();
    await page.getByRole('button',{name:'Configure agent delivery.lead',exact:true}).waitFor();

    async function addAgent(action, name) {
      await button(action).click();
      if (action === 'Add team') await field('Team name for new team').fill('research');
      await field('New Agent name').fill(name);
      await field('New Agent Runtime').selectOption('shared');
      assert.match(await field('New Agent Runtime').locator('option:checked').innerText(), /Codex/);
      await field('New Agent provider').selectOption('custom');
      await field('New Agent model').selectOption(connection);
      await dialogButton(action === 'Add team' ? 'Add team with root' : 'Add Agent').click();
      assert.equal(await field('Agent model').inputValue(),connection);
      assert.deepEqual(await field("This agent's effort").locator('option').evaluateAll(options => options.map(option => option.value)), ['']);
      // Existing custom Codex routes require an explicit approval route, not an auth fallback.
      const approval = page.locator('.d-agent-properties details').filter({has:page.locator('summary').filter({hasText:'Codex approval route'})});
      if (!await approval.evaluate(element => element.open)) await approval.locator('summary').click();
      await field('Codex approval model').fill('approval-model');
      await field('Codex approval Base URL').fill('https://review.invalid/v1');
      await field('Codex approval api_key_env name').fill('D_ADOPTION_APPROVAL_KEY');
    }

    /** Measure computed connector segments against every card's actual interior. */
    async function geometry(name, expectedRoots, expectedEdges) {
      for (const [width,height] of [[1440,1000],[1024,820]]) {
        await size(width,height);
        const result = await page.locator('.d-org-tree:visible').evaluate(tree => {
          const rect = element => { const r=element.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
          const cards = [...tree.querySelectorAll('[data-config-agent]')].map(card => ({ref:card.dataset.configAgent,...rect(card)}));
          const lists = [...tree.querySelectorAll('li')];
          const roots = [...tree.querySelectorAll(':scope > ul > li')].map(li => ({
            ref:li.querySelector(':scope > button').dataset.configAgent,
            pseudos:['::before','::after'].map(pseudo => { const style=getComputedStyle(li,pseudo); return {content:style.content,display:style.display}; }),
          }));
          const edges = lists.flatMap(li => { const parent=li.parentElement.closest('li'); return parent ? [[parent.querySelector(':scope > button').dataset.configAgent,li.querySelector(':scope > button').dataset.configAgent]] : []; });
          const segments = [];
          for (const element of tree.querySelectorAll('ul, li')) for (const pseudo of ['::before','::after']) {
            const style=getComputedStyle(element,pseudo);
            if (style.display === 'none' || ['none','normal'].includes(style.content)) continue;
            const base=rect(element), w=parseFloat(style.width), h=parseFloat(style.height);
            const offset=(value,extent)=>value.endsWith('%') ? parseFloat(value)*extent/100 : parseFloat(value);
            const x=base.x+(style.left !== 'auto' ? offset(style.left,base.width) : base.width-offset(style.right,base.width)-w);
            const y=base.y+offset(style.top,base.height);
            const add=(side,x,y,width,height) => segments.push({tag:element.tagName,pseudo,side,x,y,width,height});
            if (element.tagName === 'UL') add('trunk',x,y,w,h);
            for (const side of ['Top','Left','Right']) {
              const thickness=parseFloat(style[`border${side}Width`]);
              if (!thickness || style[`border${side}Style`] === 'none') continue;
              if(side === 'Top') add(side,x,y,w,thickness);
              else add(side,side === 'Left' ? x : x+w-thickness,y,thickness,h);
            }
          }
          return {width:innerWidth,height:innerHeight,roots,edges,cards,segments};
        });
        facts.geometry ??= []; facts.geometry.push({name,...result});
        await shot(`291-${name}`);
        assert.deepEqual(result.roots.map(root=>root.ref).sort(),expectedRoots.slice().sort());
        assert.deepEqual(result.edges.map(edge=>edge.join(' -> ')).sort(),expectedEdges.map(edge=>edge.join(' -> ')).sort());
        for (const root of result.roots) for (const pseudo of root.pseudos) {
          assert.ok(pseudo.display === 'none' || ['none','normal'].includes(pseudo.content), `Independent root ${root.ref} must have no sibling connector`);
        }
        assert.ok(result.segments.length > 0, 'A parent-child tree must have actual painted connectors');
        for(const [,child] of result.edges) {
          const card=result.cards.find(item=>item.ref === child);
          assert.ok(result.segments.some(line=>line.width <= 1 && Math.abs(line.y+line.height-card.y) <= 1
            && Math.abs(line.x-(card.x+card.width/2)) <= 1), `Connector must reach ${child}'s top border`);
        }
        for(const segment of result.segments) {
          assert.ok([segment.x,segment.y,segment.width,segment.height].every(Number.isFinite),'Measure every connector');
          for(const card of result.cards) {
            // One CSS pixel excludes the card border, not its content.
            const overlap=segment.x < card.x+card.width-1 && segment.x+segment.width > card.x+1
              && segment.y < card.y+card.height-1 && segment.y+segment.height > card.y+1;
            assert.equal(overlap,false,`${name}/${width}: connector enters ${card.ref}`);
          }
        }
      }
    }

    await addAgent('Add team','root');
    await addAgent('Add child agent','child');
    assert.equal(await field('Agent parent').inputValue(),'research.root');
    await geometry('single-root',['research.root'],[['research.root','research.child']]);
    await addAgent('Add root agent','independent');
    assert.equal(await field('Agent parent').inputValue(),'');
    await geometry('multiple-roots',['research.root','research.independent'],[['research.root','research.child']]);
    await decide(0); await reviewSave('Save changes');
    await page.getByRole('dialog').getByRole('alert').filter({hasText:'did not approve'}).waitFor();
    assert.deepEqual(await fs.readFile(rolesFile),originalBytes);
    assert.deepEqual((await read()).roles,original.roles);
    await dialogButton('Keep editing').click();
    for(const ref of newRefs) assert.equal(await page.getByRole('button',{name:`Configure agent ${ref}`,exact:true}).count(),1);
    assert.equal(await field('Agent model').inputValue(),connection);
    await shot('291-denied-draft');
    await decide(1); await reviewSave('Save changes');
    await page.getByRole('status').filter({hasText:'Settings saved.'}).waitFor();
    const saved = await read();
    for(const ref of newRefs) {
      assert.equal(saved.roles[ref].connection,connection);
      for(const key of ['runtime','model','base_url','api_key_env']) assert.equal(saved.roles[ref][key] ?? null,null);
    }
    for(const [ref,value] of Object.entries(original.roles)) assert.deepEqual(saved.roles[ref],value);
    assert.deepEqual(saved.role_tree['research.root'],{'research.child':{}});
    assert.deepEqual(saved.role_tree['research.independent'],{});
    assert.deepEqual(fixtures.operate(first,'role_organization').roles.delivery,legacyRoles);
    facts.savedRoles=saved;
    await fs.copyFile(rolesFile,path.join(evidence,'291-saved-roles.yml'));
    step('#291 catalog, root, child and independent root creation saved selected references; denial kept bytes and draft.');

    const savedBytes=await fs.readFile(rolesFile);
    approvals.push(...await app.evaluate(()=>globalThis.__dApprovals));
    await app.close(); app=null;
    await launch(); await decide(1);
    const reopenedPrefs=await page.evaluate(()=>window.graphtraj.projects());
    assert.ok(reopenedPrefs.projects.some(item=>item.id === projectId && item.root === first));
    await button('Teams & roles').click();
    await page.locator('.d-team-tabs button').filter({hasText:'research'}).click();
    await page.getByRole('button',{name:'Configure agent research.child',exact:true}).click();
    assert.equal(await field('Agent model').inputValue(),connection);
    assert.deepEqual((await read()).roles,saved.roles);
    assert.deepEqual((await read()).role_tree,saved.role_tree);
    assert.deepEqual(await fs.readFile(rolesFile),savedBytes);
    await shot('291-reopened');

    await field('Responsibility / system instructions').fill('Retain stale draft after concurrent save.');
    await page.evaluate(async id=>{
      const current=await window.graphtraj.settings(id);
      await window.graphtraj.saveSettings(id,{revision:current.revision,edits:{'research.child':{system_prompt:'Concurrent native change.'}},renames:{},add_edges:[],remove_edges:[]});
    },projectId);
    const concurrentBytes=await fs.readFile(rolesFile);
    await reviewSave('Save changes');
    await page.getByRole('dialog').getByRole('alert').filter({hasText:'changed while editing'}).waitFor();
    assert.deepEqual(await fs.readFile(rolesFile),concurrentBytes);
    assert.equal((await read()).roles['research.child'].system_prompt,'Concurrent native change.');
    await dialogButton('Keep editing').click();
    assert.equal(await field('Responsibility / system instructions').inputValue(),'Retain stale draft after concurrent save.');
    await shot('291-conflict-draft'); await button('Reload').click();
    await page.getByRole('status').filter({hasText:'Loaded current configuration.'}).waitFor();

    // Cross-team organization is established by the same real reviewed native save.
    await page.evaluate(async id=>{
      const current=await window.graphtraj.settings(id);
      const tree=structuredClone(current.role_tree);
      delete tree['research.root'];
      tree['delivery.lead']['research.root']={'research.child':{}};
      await window.graphtraj.saveSettings(id,{revision:current.revision,edits:{},renames:{},add_edges:[],remove_edges:[],role_tree:tree});
    },projectId);
    await button('Reload').click();
    await page.getByRole('button',{name:'Configure agent delivery.lead',exact:true}).waitFor();
    await geometry('cross-team',['delivery.lead','research.independent'],[
      ['delivery.lead','delivery.engineer'],['delivery.engineer','delivery.writer'],['delivery.lead','delivery.reviewer'],
      ['delivery.lead','research.root'],['research.root','research.child'],
    ]);
    const final=await read();
    for(const [ref,value] of Object.entries(original.roles)) assert.deepEqual(final.roles[ref],value);
    assert.deepEqual(final.role_tree['delivery.lead']['research.root'],{'research.child':{}});
    assert.deepEqual(fixtures.operate(first,'role_organization').roles.delivery,legacyRoles);
    facts.finalRoles=final;
    await fs.copyFile(rolesFile,path.join(evidence,'291-final-roles.yml'));
    step('#291 actual app reopen, legacy preservation, native conflict and single/multiple/cross-team connector clearance passed.');
  }
  if (roleFlow) {
    await roleCreationAdoption();
  } else {
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
  const members = await page.evaluate(id => window.graphtraj.activity(id,{task_id:'1'}),firstId);
  assert.equal(members.agents.length,4);
  assert.equal(members.agents.filter(agent => agent.historical).length,1);
  for (const agent of members.agents) {
    assert.equal(agent.runtime,'codex'); assert.equal(agent.model,'recorded-model');
    assert.notEqual(agent.state,'unavailable');
    const activity = await page.evaluate(({id,alias}) => window.graphtraj.activity(id,{task_id:'1',alias}),{id:firstId,alias:agent.alias});
    assert.ok(activity.events.some(event => event.kind === 'message'), `${agent.alias} must expose its recorded messages`);
  }
  facts.members=members.agents;
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
  await page.getByRole('button',{name:/^All project usage\b/}).click();
  await page.locator('.d-project-usage-table tbody tr').nth(1).waitFor();
  assert.equal(await page.locator('.usage-filters select').count(),0);
  assert.ok(!(await page.locator('.usage-dashboard').innerText()).includes('current-handover0-engineer@engineer'));
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
  for (const expanded of [false,true,false,true]) { const toggle=page.getByRole('button',{name:/^(Expand|Collapse) shared Runtime$/}); await toggle.click(); assert.equal(await toggle.getAttribute('aria-expanded'), String(expanded)); }
  const providerToggle=page.getByRole('button',{name:/^(Expand|Collapse) shared \/ custom provider$/});
  if(await providerToggle.getAttribute('aria-expanded') !== 'true') await providerToggle.click();
  await page.locator('.library-models').getByRole('button',{name:'Configured model',exact:true}).click();
  await field('Model alias').fill('Updated model alias');
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('model-edit'); }
  await button('Cancel changes').click();
  await button('Teams & roles').click(); await page.locator('.d-org-node').nth(3).waitFor();
  await page.getByRole('button',{name:'Configure agent delivery.engineer',exact:true}).click();
  await field('Agent Runtime').selectOption('shared');
  assert.deepEqual(await field("This agent's effort").locator('option').evaluateAll(options => options.map(option => option.value)), ['']);
  await page.locator('summary').filter({hasText:'Prompt layers'}).click();
  await field('Responsibility / system instructions').fill('Report recorded evidence to the parent.');
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('teams-edit'); }
  await size(1440,1000); await page.locator('summary').filter({hasText:'Codex approval route'}).click();
  await field('Codex approval model').fill('approval-model'); await field('Codex approval Base URL').fill('https://review.invalid/v1'); await field('Codex approval api_key_env name').fill('D_ADOPTION_APPROVAL_KEY');
  await decide(1); await reviewSave('Save changes'); await page.getByRole('status').filter({hasText:'Settings saved.'}).waitFor();
  const savedRoles = await page.evaluate(id=>window.graphtraj.settings(id),firstId);
  assert.equal(savedRoles.roles['delivery.engineer'].connection,'shared/custom/model');
  assert.equal(savedRoles.roles['delivery.engineer'].reasoning_effort ?? null, null);
  assert.match(await fs.readFile(rolesFile,'utf8'),/report.md/);
  const secondRoles = await page.evaluate(id=>window.graphtraj.settings(id),secondId);
  assert.ok(!secondRoles.roles['delivery.engineer']);
  // A real concurrent native save must invalidate the UI revision without discarding the draft.
  await field('Responsibility / system instructions').fill('Retain this draft after a conflict.');
  await page.evaluate(async id => { const current=await window.graphtraj.settings(id); await window.graphtraj.saveSettings(id,{revision:current.revision,edits:{'delivery.engineer':{system_prompt:'Concurrent native instruction edit.'}},renames:{},add_edges:[],remove_edges:[]}); },firstId);
  await reviewSave('Save changes'); await page.getByRole('dialog').getByRole('alert').waitFor();
  assert.equal((await page.evaluate(id=>window.graphtraj.settings(id),firstId)).roles['delivery.engineer'].system_prompt,'Concurrent native instruction edit.');
  await dialogButton('Keep editing').click(); assert.equal(await field('Responsibility / system instructions').inputValue(),'Retain this draft after a conflict.'); await button('Reload').click();
  step('Installed global and team D editing reaches native preview/save; denial retains the draft, approval saves and revision conflict refuses overwrite.');
  await button('Add or manage projects').click();
  for (const [width,height] of [[1440,1000],[1024,820]]) { await size(width,height); await shot('project-index'); }
  }
  approvals.push(...await app.evaluate(()=>globalThis.__dApprovals ?? []));
  facts.approvalCount=approvals.length;
  facts.approvalResponses=approvals.map(item=>item.response);
  assert.deepEqual(facts.pageErrors,[]);
  await app.close(); app=null;
  assert.equal(fixtures.operate(first,'task_graph').tasks.length,roleFlow ? 2 : 6);
  facts.passed=true;
  step('Closing the optional desktop leaves the native graph available. Unchanged live-Runner optionality and real system-dialog/platform evidence are reused from prior delivery.');
} catch(error) {
  facts.error=String(error.stack || error);
  if(page) { await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{}); }
  throw error;
} finally {
  if(app) await app.close().catch(error=>{facts.cleanupError=String(error);});
  facts.finishedAt = new Date().toISOString();
  await fs.writeFile(path.join(evidence,'d-adoption.json'),JSON.stringify(facts,null,2)+'\n');
}
