/** One real, owned Electron window. Run only after the native host adopts self activity. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const worktree = path.dirname(desktop);
const tool = process.env.GRAPHTRAJ_TOOL;
const project = process.env.GRAPHTRAJ_LIVE_PROJECT;
const ticket = process.env.GRAPHTRAJ_LIVE_TICKET;

function selfQuery() {
  return new Promise((resolve, reject) => {
    const child = execFile(tool, ['--allowed-features', 'desktop_activity'],
      { cwd: worktree, timeout: 15000, maxBuffer: 1024 * 1024 }, (error, stdout) => {
        if (error) return reject(error);
        try {
          const reply = JSON.parse(stdout);
          assert.equal(reply.failed, false, 'Native host must adopt authenticated self activity before launch');
          assert.equal(reply.result.scope, 'self');
          assert.equal(reply.result.agents.length, 1);
          resolve(reply.result.agents[0]);
        } catch (failure) { reject(failure); }
      });
    child.stdin.on('error', reject);
    child.stdin.end(JSON.stringify({ action: 'execute', feature: 'desktop_activity', arguments: { ticket_id: ticket } }) + '\n');
  });
}

test('one native window observes its real executing Agent', { timeout: 240000, skip: !project || !ticket || !tool }, async () => {
  // Authentication is native and inherited. No identity fields, detached host,
  // fake activity backend, fixture Trace or replacement directory dialog.
  const member = await selfQuery();
  const evidence = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-activity-live-'));
  const token = randomUUID();
  const liveMarker = '262-live-' + token;
  const pausedMarker = '262-paused-' + token;
  let app;
  let exit = null;
  let stderr = '';
  const facts = { project, ticket, alias: member.alias, launches: 0, steps: [] };
  try {
    app = await electron.launch({ executablePath: electronExecutable,
      args: [...(process.env.GRAPHTRAJ_LIVE_NO_SANDBOX === '1' ? ['--no-sandbox'] : []),
        desktop, `--project=${project}`, `--user-data-dir=${path.join(evidence, 'profile')}`], timeout: 20000,
      env: { ...process.env, GRAPHTRAJ_TOOL: tool, MAC_CHROMIUM_TMPDIR: evidence } });
    facts.launches += 1;
    app.process().stderr?.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-32768); });
    app.process().on('exit', (code, signal) => { exit = { code, signal }; });
    const page = await app.firstWindow();
    page.setDefaultTimeout(15000);
    await page.getByRole('searchbox').fill(ticket);
    await page.getByRole('button', { name: new RegExp('^#' + ticket + ' ') }).click();
    await page.getByRole('button', { name: member.alias, exact: true }).click();
    await page.getByText('This Agent connection shows only its own Session.').waitFor();
    facts.steps.push('real native self connection visible');
    console.log(JSON.stringify({ phase: 'READY', token, evidence, alias: member.alias }));
    const liveCard = page.locator('.activity-event').filter({ hasText: liveMarker }).filter({ hasText: '· result' }).first();
    await liveCard.waitFor({ timeout: 90000 });
    await liveCard.locator('summary').click();
    await liveCard.getByRole('button', { name: 'Copy', exact: true }).click();
    await liveCard.getByRole('button', { name: 'Copied', exact: true }).waitFor();
    const copied = await app.evaluate(({ clipboard }) => clipboard.readText());
    assert.ok(copied.includes(liveMarker) && copied.includes('diagnostic'));
    facts.steps.push('actual new native tool event expanded and copied');
    await page.getByRole('button', { name: 'Pause following', exact: true }).click();
    const history = page.locator('.activity-history');
    await history.evaluate(node => { node.scrollTop = 0; });
    const before = await history.evaluate(node => ({ top: node.scrollTop, text: node.innerText }));
    console.log(JSON.stringify({ phase: 'PAUSED', token }));
    await page.getByRole('button', { name: /Follow new messages \([1-9]/ }).waitFor({ timeout: 60000 });
    const after = await history.evaluate(node => ({ top: node.scrollTop, text: node.innerText }));
    assert.equal(after.top, before.top);
    assert.equal(after.text, before.text);
    await page.getByRole('button', { name: /Follow new messages/ }).click();
    await page.locator('.activity-event').filter({ hasText: pausedMarker }).first().waitFor({ timeout: 60000 });
    facts.steps.push('paused older view stable; follow reached actual next event');
    await page.screenshot({ path: path.join(evidence, 'activity.png') });
    facts.passed = true;
  } catch (error) {
    facts.failure = String(error);
    throw error;
  } finally {
    if (app) await app.close();
    facts.exit = exit;
    await fs.writeFile(path.join(evidence, 'stderr.log'), stderr);
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
    console.log(JSON.stringify({ phase: 'CLOSED', evidence, exit, passed: facts.passed === true }));
  }
});
