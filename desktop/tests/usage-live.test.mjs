/** Opt-in, deadline-bound native check; never changes the executing Agent's identity. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';
import { ActivityReader } from '../dist-electron/activity.js';
import { collect, records, groups, metrics } from '../src/usage.ts';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const project = process.env.GRAPHTRAJ_LIVE_PROJECT;
const ticket = process.env.GRAPHTRAJ_LIVE_TICKET;
const tool = process.env.GRAPHTRAJ_TOOL;
const executable = process.env.GRAPHTRAJ_ELECTRON_EXECUTABLE || electronExecutable;
// The caller may opt in only after this execution's native/host approval.
const noSandbox = process.env.GRAPHTRAJ_LIVE_NO_SANDBOX === '1';
const deadlineText = process.env.GRAPHTRAJ_LIVE_DEADLINE;
const deadline = typeof deadlineText === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(deadlineText)
  ? Date.parse(deadlineText) : NaN;

/** Match datetime-local's minute precision without changing the selected timezone. */
function localMinute(time) {
  const date = new Date(time);
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

test('owned Electron Dashboard matches native quantities, filters and replay', {
  timeout: Number.isFinite(deadline) ? Math.max(1, deadline - Date.now()) : 1000,
  skip: !project || !ticket || !tool,
}, async () => {
  assert.ok(Number.isFinite(deadline) && deadline > Date.now() + 10000,
    'Provide GRAPHTRAJ_LIVE_DEADLINE as a future absolute ISO time with timezone; no deadline is inferred.');
  const reader = new ActivityReader(tool);
  const artifactRoot = process.env.GRAPHTRAJ_LIVE_ARTIFACTS || os.tmpdir();
  assert.ok(path.isAbsolute(artifactRoot) && path.isAbsolute(executable), 'Resource paths must be absolute');
  await fs.mkdir(artifactRoot, { recursive: true });
  const evidence = await fs.mkdtemp(path.join(artifactRoot, 'graphtraj-usage-live-'));
  const cutoff = localMinute(Math.floor(Date.now() / 60000) * 60000);
  const facts = { project, ticket, executable, noSandbox, deadline: deadlineText, cutoff, steps: [], passed: false };
  let launch;
  let app;
  let stopping = false;
  let rejectStop;
  const interrupted = new Promise((_, reject) => { rejectStop = reject; });
  const stop = reason => {
    stopping = true;
    reader.close();
    rejectStop(new Error(reason));
    if (app) void app.close().catch(() => {});
  };
  const onTerm = () => stop('Native execution received SIGTERM');
  const onInt = () => stop('Native execution received SIGINT');
  process.once('SIGTERM', onTerm);
  process.once('SIGINT', onInt);
  // Begin shutdown before the absolute boundary; this does not extend Runner time.
  const deadlineTimer = setTimeout(() => stop('Caller deadline reached (shutdown reserve)'), deadline - Date.now() - 3000);
  const hardStop = setTimeout(() => { app?.process().kill('SIGKILL'); }, deadline - Date.now());
  function check() {
    if (stopping || Date.now() >= deadline - 3000) throw new Error('Execution stopped or deadline reached');
  }
  async function run() {
    const own = await reader.read(project, { ticket_id: ticket });
    assert.equal(own.scope, 'self');
    assert.equal(own.agents.length, 1);
    const alias = own.agents[0].alias;
    const calls = new Map();
    let cursor;
    do {
      check();
      const page = await reader.read(project, { ticket_id: ticket, alias, cursor });
      assert.equal(page.availability, 'available');
      collect(calls, project, page.events ?? []);
      cursor = page.has_more ? page.cursor : undefined;
    } while (cursor);
    const selected = records(calls, { ticket, agent: alias, to: cutoff });
    const expected = groups(selected, 'model');
    assert.ok(expected.some(row => row.tokens.input.value > 0), 'Requires real usage before the fixed time boundary');
    facts.expected = expected;
    facts.cacheWriteMissing = selected.filter(row => row.tokens.cache_write === undefined).length;
    facts.steps.push('Captured native self quantities through fixed minute; old-host missing cache-write fields remain unknown');
    check();
    launch = electron.launch({ executablePath: executable,
      args: [...(noSandbox ? ['--no-sandbox'] : []), desktop, `--project=${project}`, `--user-data-dir=${path.join(evidence, 'profile')}`],
      env: { ...process.env, TMPDIR: artifactRoot, MAC_CHROMIUM_TMPDIR: artifactRoot, CLAUDE_TMPDIR: artifactRoot }, timeout: Math.min(20000, deadline - Date.now() - 3000) });
    app = await launch;
    if (stopping) { await app.close(); return; }
    const page = await app.firstWindow();
    page.setDefaultTimeout(Math.min(30000, deadline - Date.now() - 3000));
    await page.getByRole('button', { name: 'Usage', exact: true }).click();
    // Wrapping select labels include option text; scope to the filter label prefix.
    await page.locator('.usage-filters > label').filter({ hasText: /^Ticket/ }).locator('select').selectOption(ticket);
    await page.getByLabel('Through (local time)').fill(cutoff);
    await page.getByText('This Agent connection shows only its own Session. Other Agents are not covered.', { exact: true }).waitFor();
    await page.locator('.usage-filters > label').filter({ hasText: /^Agent/ }).locator('select').selectOption(alias);

    async function matchQuantities() {
      check();
      await page.locator('.usage-dashboard > [role="status"]').filter({ hasText: 'Observation active' }).waitFor();
      const table = page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Model breakdown' }) });
      assert.equal(await table.locator('tbody tr').count(), expected.length);
      for (const expectedRow of expected) {
        const row = table.locator('tbody tr').filter({ has: page.getByRole('rowheader', { name: expectedRow.name, exact: true }) });
        const values = await row.locator('td').evaluateAll(cells => cells.map(cell => cell.firstChild?.textContent));
        const numbers = await page.evaluate(row => {
          const format = value => value.toLocaleString(undefined, { maximumFractionDigits: 6 });
          return [String(row.count), ...['input', 'output', 'cache_read', 'cache_write'].map(metric =>
            row.tokens[metric].known ? format(row.tokens[metric].value) : 'Unknown'),
          row.cacheRate === null ? 'Unknown' : format(row.cacheRate * 100) + '%',
          row.priced ? '$' + row.amount.toFixed(6) : 'Unknown', String(row.unpriced)];
        }, expectedRow);
        assert.deepEqual(values, numbers, `Native/rendered quantities for ${expectedRow.name}`);
      }
      const daily = groups(selected, 'day');
      const trend = page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Daily trend (UTC)' }) });
      assert.equal(await trend.locator('tbody tr').count(), daily.length);
      for (const day of daily) {
        const row = trend.locator('tbody tr').filter({ has: page.getByRole('rowheader', { name: day.name, exact: true }) });
        for (const [index, metric] of metrics.entries()) {
          const actual = await row.locator('td').nth(index + 1).evaluate(cell => cell.firstChild?.textContent);
          const expectedText = await page.evaluate(value => value === null ? 'Unknown' : value.toLocaleString(undefined, { maximumFractionDigits: 6 }),
            day.tokens[metric].known ? day.tokens[metric].value : null);
          assert.equal(actual, expectedText, `${day.name} ${metric}`);
        }
      }
    }
    await matchQuantities();
    facts.steps.push('Model and daily rendered input/output/cache quantities, rate, cost and unpriced counts match actual native records');
    await page.getByLabel('From (local time)').fill('2099-01-01T00:00');
    await page.getByText('No usage records match this view.', { exact: true }).waitFor();
    await page.getByLabel('From (local time)').fill('');
    const beforeReplay = await page.locator('.usage-dashboard > [role="status"]').textContent();
    await page.getByRole('button', { name: 'Reconnect usage', exact: true }).click();
    await page.waitForFunction(before => {
      const status = document.querySelector('.usage-dashboard > [role="status"]')?.textContent;
      return status !== before && status?.includes('Observation active');
    }, beforeReplay);
    await matchQuantities();
    facts.steps.push('Time filter excludes native usage; replay restores the same bounded quantities');
    // DOM values alone do not prove that flex/overflow layout lets a human read them.
    async function readable(locator, label) {
      check();
      await locator.scrollIntoViewIfNeeded();
      const box = await locator.evaluate(element => {
        const rect = element.getBoundingClientRect();
        let top = 0, bottom = window.innerHeight;
        let shown = true;
        for (let parent = element; parent; parent = parent.parentElement) {
          const style = getComputedStyle(parent);
          shown &&= style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0;
          if (parent !== element && /auto|scroll|hidden|clip/.test(style.overflowY)) {
            const bounds = parent.getBoundingClientRect();
            top = Math.max(top, bounds.top + parent.clientTop);
            bottom = Math.min(bottom, bounds.top + parent.clientTop + parent.clientHeight);
          }
        }
        return { shown, height: rect.height, width: rect.width, top: rect.top, bottom: rect.bottom,
          visibleTop: top, visibleBottom: bottom };
      });
      assert.ok(box.shown && box.height > 0 && box.width > 0 &&
        box.top >= box.visibleTop - 1 && box.bottom <= box.visibleBottom + 1,
      `${label} must be readable after scrolling: ${JSON.stringify(box)}`);
    }
    const dashboard = page.locator('.usage-dashboard');
    const coverageCard = dashboard.locator(':scope > .card');
    assert.equal(await coverageCard.count(), 1);
    const coverageSize = await coverageCard.evaluate(card => ({ height: card.clientHeight, content: card.scrollHeight }));
    assert.ok(coverageSize.height > 0 && coverageSize.content <= coverageSize.height + 1,
      'Data coverage card must contain its full body without internal clipping');
    await readable(coverageCard.locator('.card__title'), 'Data coverage title');
    const paragraphs = coverageCard.locator('.card__content > p');
    assert.ok(await paragraphs.count() > 0, 'Coverage body is present');
    for (const paragraph of await paragraphs.all()) await readable(paragraph, 'Data coverage body paragraph');
    await page.screenshot({ path: path.join(evidence, 'coverage.png') });
    for (const caption of ['Model breakdown', 'Daily trend (UTC)']) {
      const table = page.getByRole('table').filter({ has: page.locator('caption', { hasText: caption }) });
      await readable(table.locator('caption'), caption);
      assert.ok(await table.locator('tbody tr').count() > 0, `${caption} has actual rows`);
      for (const row of await table.locator('tbody tr').all()) await readable(row, `${caption} row`);
      await page.screenshot({ path: path.join(evidence, caption === 'Model breakdown' ? 'models.png' : 'trend.png') });
    }
    const scroll = await dashboard.evaluate(element => ({ top: element.scrollTop, height: element.clientHeight, content: element.scrollHeight }));
    assert.ok(scroll.height > 0 && scroll.content > scroll.height && scroll.top > 0,
      'Dashboard must scroll to its lower tables instead of shrinking their content');
    facts.steps.push('Coverage body and model/daily captions and rows are unclipped after scrolling; dashboard scroll confirmed');
    await page.screenshot({ path: path.join(evidence, 'usage.png') });
    facts.passed = true;
  }
  try { await Promise.race([run(), interrupted]); }
  catch (error) { facts.failure = String(error); throw error; }
  finally {
    stopping = true;
    reader.close();
    if (launch && !app) app = await launch.catch(() => undefined);
    if (app) {
      const child = app.process();
      const kill = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, Math.max(0, Math.min(2000, deadline - Date.now())));
      try { await app.close(); } catch { if (child.exitCode === null) child.kill('SIGKILL'); }
      finally { clearTimeout(kill); }
    }
    clearTimeout(deadlineTimer); clearTimeout(hardStop);
    process.removeListener('SIGTERM', onTerm); process.removeListener('SIGINT', onInt);
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
    console.log(JSON.stringify({ evidence, ...facts }));
  }
});
