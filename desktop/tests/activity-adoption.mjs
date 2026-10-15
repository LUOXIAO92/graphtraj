/** Focused #292 installed macOS activity acceptance, only on disposable CI. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Controlled records require disposable CI');
assert.equal(process.platform, 'darwin', 'This entry exercises installed macOS only');
const require = createRequire(import.meta.url);
const evidence = path.resolve(process.env.GRAPHTRAJ_ACTIVITY_EVIDENCE || 'dist-package/adoption-evidence/activity');
const work = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-292-activity-'));
const executablePath = '/Applications/GraphTraj.app/Contents/MacOS/GraphTraj';
const alias = 'sanitized292-handover0-engineer@engineer';
const otherAlias = 'sanitizedother-handover0-engineer@engineer';
const time = new Date().toISOString();
const facts = { source: process.env.GITHUB_SHA, platform: process.platform, node: process.version,
  data: 'Handwritten sanitized native-shape records, not original #282 records; no model execution.',
  executablePath, launches: 0, passed: false, steps: [], screenshots: [], pageErrors: [] };
await fs.mkdir(evidence, { recursive: true });
const step = text => { facts.steps.push(text); console.log(text); };
const item = (type, payload = {}) => ({ timestamp: time, type: 'response_item', payload: { type, ...payload } });
const context = { timestamp: time, type: 'turn_context', payload: { model: 'gpt-5.3-codex', turn_id: 'sanitized-turn' } };
const usage = total => ({ timestamp: time, type: 'event_msg', payload: { type: 'token_count', info: {
  last_token_usage: { input_tokens: 10, output_tokens: 2 },
  total_token_usage: { input_tokens: total, output_tokens: total / 5 },
} } });
const message = text => item('message', { role: 'assistant', content: [{ type: 'output_text', text }] });
const records = [context,
  item('function_call', { call_id: 'sanitized-call-1', name: 'exec_command', arguments: '{"cmd":"rg sanitized-test tests"}' }),
  item('function_call_output', { call_id: 'sanitized-result-first', output: 'Sanitized result recorded before its call' }),
  item('reasoning', { summary: [], content: [{ type: 'reasoning_text', text: 'Sanitized plaintext reasoning with an empty summary.' }] }),
  item('reasoning', { summary: [] }),
  item('reasoning', { summary: [], encrypted_content: 'sanitized-opaque-never-display' }),
  { timestamp: time, type: 'event_msg', payload: { type: 'task_started', turn_id: 'sanitized-turn' } },
];
// Native page size is 200 records. Context records pad without obscuring the UI.
while (records.length < 200) records.push(context);
records.push(
  item('function_call_output', { call_id: 'sanitized-call-1', output: 'Sanitized explicit response-format test: hook decision allow. Not a Stop activation.' }),
  item('function_call', { call_id: 'sanitized-result-first', name: 'read_file', arguments: '{"path":"sanitized.txt"}' }),
  item('function_call_output', { call_id: 'sanitized-missing-name', output: 'Sanitized tool name was not recorded' }),
  message('Sanitized response in the recorded turn.'), usage(10), usage(20), usage(20),
);
let app;
let page;
try {
  const project = await fs.realpath(await fixtures.makeProject(path.join(work, 'sanitized-292'), 'activity-adoption'));
  // Reuse the existing disposable fixture seam; never edit an actual Session.
  const trace = await fixtures.recordActivity(project, { taskId: '1', taskName: 'activity-adoption', alias, records,
    additionalMembers: [{ alias: otherAlias, historical: false,
      records: [message('Sanitized other Agent; usage must not be attached here.')] }] });
  // Exercise the exact desktop bridge/public observer before opening a window.
  // A bad fixture must report its native projection, not a downstream UI timeout.
  const { ActivityReader } = require('../dist-electron/activity.js');
  const reader = new ActivityReader();
  facts.preflight = { agents: [], pages: [] };
  try {
    const members = await reader.read(project, { task_id: '1' });
    facts.preflight.agents = members.agents;
    assert.deepEqual(members.agents.map(agent => agent.alias).sort(), [alias, otherAlias].sort());
    for (const agent of members.agents) {
      assert.equal(agent.runtime, 'codex', `Native fixture member ${agent.alias}: ${JSON.stringify(agent)}`);
      assert.equal(agent.model, 'recorded-model');
      assert.equal(agent.historical, agent.alias === alias);
      assert.notEqual(agent.state, 'unavailable', `Native fixture member ${agent.alias}: ${JSON.stringify(agent)}`);
    }
    const otherPage = await reader.read(project, { task_id: '1', alias: otherAlias });
    facts.preflight.other = { availability: otherPage.availability, count: otherPage.events?.length };
    assert.equal(otherPage.availability, 'available');
    assert.ok(otherPage.events.some(event => event.kind === 'message' && event.agent === otherAlias));
    const events = [];
    let cursor;
    let more;
    do {
      const page = await reader.read(project, { task_id: '1', alias, ...(cursor ? { cursor } : {}) });
      facts.preflight.pages.push({ availability: page.availability, count: page.events?.length,
        has_more: page.has_more, reason: page.reason });
      assert.equal(page.availability, 'available', JSON.stringify(facts.preflight));
      assert.equal(page.waiting_for_record, false, 'Fixture must contain complete native records');
      events.push(...page.events);
      cursor = page.cursor;
      more = page.has_more;
    } while (more);
    assert.equal(facts.preflight.pages.length, 2, 'Fixture must cross the native page boundary');
    assert.ok(events.some(event => event.kind === 'tool' && event.phase === 'result' && event.name === 'exec_command'));
    assert.ok(events.some(event => event.role === 'reasoning' && event.text === 'Sanitized plaintext reasoning with an empty summary.'));
    const observations = events.filter(event => event.kind === 'usage');
    assert.equal(observations.length, 3);
    assert.equal(new Set(observations.map(event => event.usage.identity)).size, 2);
    step('Public native preflight resolves both fixture members and projects cross-page tools, plaintext and usage before launch.');
  } finally {
    reader.close();
  }
  const loader = path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/server/electron/loader.js');
  facts.launches += 1;
  app = await electron.launch({ executablePath,
    args: ['-r', loader, `--user-data-dir=${path.join(work, 'preferences')}`, `--project=${project}`], timeout: 30000 });
  page = await app.firstWindow();
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => facts.pageErrors.push(String(error)));
  facts.installed = await app.evaluate(({ app, BrowserWindow }) => ({ packaged: app.isPackaged,
    appPath: app.getAppPath(), sandbox: BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences().sandbox }));
  assert.equal(facts.installed.packaged, true);
  assert.equal(facts.installed.sandbox, true);
  const monitor = page.locator('.monitor-page:visible');
  await monitor.locator('.react-flow__node[data-id="1"]').click();
  await monitor.getByRole('button', { name: 'Expand chat', exact: true }).click();
  const column = monitor.locator(`[data-agent-id="${alias}"]`);
  const other = monitor.locator(`[data-agent-id="${otherAlias}"]`);
  const result = column.locator('.tool-card').filter({ has: page.locator('.tool-result', { hasText: /^result/ }) });
  const execResult = result.filter({ has: page.locator('summary strong', { hasText: 'Tool · exec_command' }) });
  await execResult.waitFor();
  assert.equal(await execResult.count(), 1);
  await execResult.locator('summary').click();
  await execResult.getByText('sanitized-call-1', { exact: true }).waitFor();
  await execResult.getByText('Sanitized explicit response-format test: hook decision allow. Not a Stop activation.', { exact: true }).waitFor();
  assert.equal(await result.filter({ has: page.locator('summary strong', { hasText: 'Tool · read_file' }) }).count(), 1);
  assert.equal(await result.filter({ has: page.locator('summary strong', { hasText: 'Tool · Name not recorded' }) }).count(), 1);
  assert.ok(!(await column.locator('.tool-card summary').allTextContents()).some(text => /sanitized-call-1|sanitized-result-first|sanitized-missing-name/.test(text)));
  step('Installed native reader resolves names across its 200-record page boundary and result-first order; IDs stay in details and missing names remain explicit.');

  await column.getByText('Sanitized plaintext reasoning with an empty summary.', { exact: true }).waitFor();
  assert.equal(await column.locator('.message-heading strong', { hasText: /^Reasoning$/ }).count(), 3);
  await column.getByText('No reasoning text was recorded.', { exact: true }).waitFor();
  await column.getByText('Reasoning is inaccessible; only encrypted content is recorded.', { exact: true }).waitFor();
  assert.equal(await column.getByText('sanitized-opaque-never-display', { exact: true }).count(), 0);
  await column.locator('summary strong', { hasText: /^Execution event$/ }).waitFor();
  step('Recorded plaintext is Reasoning; missing/inaccessible text and execution events are distinct.');

  const supplement = column.locator('footer.usage-supplement');
  await supplement.waitFor();
  assert.equal(await supplement.count(), 1);
  assert.equal(await supplement.getAttribute('aria-label'), `Usage for ${alias}`);
  assert.match(await supplement.locator('summary').innerText(), /Recorded turn.*codex.*Latest response observation/);
  assert.equal(await other.locator('.usage-supplement').count(), 0);
  assert.equal(await column.locator('.activity-event').filter({ hasText: /^Usage/ }).count(), 0);
  await supplement.locator('summary').click();
  assert.equal(await supplement.locator('.usage-observation').count(), 2);
  assert.equal(await supplement.getByText('Latest response (last_token_usage)', { exact: true }).count(), 2);
  assert.equal(await supplement.getByText('Cumulative native Session counter (total_token_usage; not this turn)', { exact: true }).count(), 2);
  const parents = await supplement.evaluate(node => ({ tag: node.tagName, preceding: node.previousElementSibling?.className }));
  assert.equal(parents.tag, 'FOOTER');
  assert.match(parents.preceding, /activity-event/);
  step('Usage supplements the recorded turn for the actual Agent; two distinct observations survive and the repeated counter does not add a third.');

  // Append only this disposable fixture Trace. The unchanged native reader and
  // three-second renderer polling must discover the addition without reload.
  await fs.appendFile(trace, [message('Sanitized appended response discovered by native refresh.'), usage(30)]
    .map(record => JSON.stringify(record)).join('\n') + '\n');
  await column.getByText('Sanitized appended response discovered by native refresh.', { exact: true }).waitFor();
  await page.waitForFunction(alias => document.querySelector(`[data-agent-id="${alias}"]`)
    ?.querySelectorAll('.usage-observation').length === 3, alias);
  step('Actual file append reaches the installed native observer and existing UI polling without window reload or task completion.');

  const dimensions = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, devicePixelRatio }));
  const shot = 'activity-d.png';
  const bytes = await page.screenshot({ path: path.join(evidence, shot), scale: 'css', fullPage: true });
  facts.screenshots.push({ file: shot, ...dimensions, sha256: createHash('sha256').update(bytes).digest('hex') });
  assert.deepEqual(facts.pageErrors, []);
  await app.close(); app = null;
  assert.equal(fixtures.operate(project, 'task_graph').tasks.length, 2);
  step('D activity screenshot retained; native graph remains available after closing the optional window.');
  facts.passed = true;
} catch (error) {
  facts.error = String(error.stack || error);
  if (page) await page.screenshot({ path: path.join(evidence, 'failure.png') }).catch(() => {});
  throw error;
} finally {
  if (app) await app.close().catch(error => { facts.cleanupError = String(error); });
  await fs.writeFile(path.join(evidence, 'activity-adoption.json'), JSON.stringify(facts, null, 2) + '\n');
}
