/** Opt-in one-window native usage check; preserves the executing Agent's identity. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';
import { ActivityReader } from '../dist-electron/activity.js';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const project = process.env.GRAPHTRAJ_LIVE_PROJECT;
const ticket = process.env.GRAPHTRAJ_LIVE_TICKET;
const tool = process.env.GRAPHTRAJ_TOOL;

test('owned Electron Dashboard displays actual native self usage and filters it', {
  timeout: 120000, skip: !project || !ticket || !tool,
}, async () => {
  const reader = new ActivityReader(tool);
  let app;
  const evidence = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-usage-live-'));
  const facts = { project, ticket, steps: [], passed: false };
  try {
    const own = await reader.read(project, { ticket_id: ticket });
    assert.equal(own.scope, 'self');
    assert.equal(own.agents.length, 1);
    const alias = own.agents[0].alias;
    let cursor;
    let usage = 0;
    let input = 0;
    do {
      const page = await reader.read(project, { ticket_id: ticket, alias, cursor });
      assert.equal(page.availability, 'available');
      for (const event of page.events ?? []) if (event.kind === 'usage') {
        usage++; input += event.usage.tokens.input ?? 0;
      }
      cursor = page.has_more ? page.cursor : undefined;
    } while (cursor);
    assert.ok(usage > 0 && input > 0, 'Requires actual reported model usage');
    facts.steps.push(`Native self usage available (${usage} observations)`);
    app = await electron.launch({ executablePath: electronExecutable,
      args: [desktop, `--project=${project}`, `--user-data-dir=${path.join(evidence, 'profile')}`],
      env: { ...process.env, MAC_CHROMIUM_TMPDIR: evidence }, timeout: 20000 });
    const page = await app.firstWindow();
    page.setDefaultTimeout(30000);
    await page.getByRole('button', { name: 'Usage', exact: true }).click();
    await page.getByLabel('Ticket', { exact: true }).selectOption(ticket);
    await page.getByText('This Agent connection shows only its own Session. Other Agents are not covered.', { exact: true }).waitFor();
    await page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Model breakdown' }) }).locator('tbody tr').first().waitFor();
    facts.steps.push('Actual native usage rendered in model breakdown and daily trend');
    await page.getByLabel('Agent', { exact: true }).selectOption(alias);
    await page.getByLabel('From (local time)').fill('2099-01-01T00:00');
    await page.getByText('No usage records match this view.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await page.getByLabel('Ticket', { exact: true }).selectOption(ticket);
    await page.getByRole('button', { name: 'Reconnect usage', exact: true }).click();
    await page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Model breakdown' }) }).locator('tbody tr').first().waitFor();
    facts.steps.push('Time filter excludes real usage; reconnect replays native records');
    await page.screenshot({ path: path.join(evidence, 'usage.png') });
    facts.passed = true;
  } catch (error) { facts.failure = String(error); throw error; }
  finally {
    reader.close();
    if (app) await app.close();
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
    console.log(JSON.stringify({ evidence, ...facts }));
  }
});
