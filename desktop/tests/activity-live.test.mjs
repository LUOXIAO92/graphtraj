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
  let page;
  let exit = null;
  let stderr = '';
  let stopping = false;
  const stopOwned = () => { stopping = true; if (app) void app.close().catch(() => {}); };
  process.once('SIGTERM', stopOwned);
  const facts = { project, ticket, alias: member.alias, launches: 0, steps: [] };
  try {
    app = await electron.launch({ executablePath: electronExecutable,
      args: [...(process.env.GRAPHTRAJ_LIVE_NO_SANDBOX === '1' ? ['--no-sandbox'] : []),
        desktop, `--project=${project}`, `--user-data-dir=${path.join(evidence, 'profile')}`], timeout: 20000,
      env: { ...process.env, GRAPHTRAJ_TOOL: tool, MAC_CHROMIUM_TMPDIR: evidence } });
    if (stopping) throw new Error('Owned live test stopped.');
    facts.launches += 1;
    app.process().stderr?.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-32768); });
    app.process().on('exit', (code, signal) => { exit = { code, signal }; });
    page = await app.firstWindow();
    page.setDefaultTimeout(15000);
    // Observe the real reader without changing requests, promises, or responses.
    // Inspector-evaluated functions have no dynamic-import callback or CJS scope.
    try {
    await app.evaluate(({ app }, { alias, markers }) => {
      const { createRequire } = process.getBuiltinModule('module');
      const require = createRequire(app.getAppPath() + '/package.json');
      const { createHash } = require('node:crypto');
      const { ActivityReader } = require('./dist-electron/activity.js');
      const original = ActivityReader.prototype.read;
      const entries = [];
      const hash = value => value == null ? null : createHash('sha256').update(String(value)).digest('hex').slice(0, 16);
      const record = value => { entries.push({ at: new Date().toISOString(), ...value }); if (entries.length > 500) entries.shift(); };
      globalThis.activityLiveDiagnostics = entries;
      // Observe only this feature-restricted child's existing stdout/lifecycle.
      // Do not consume stderr or change stdin, response bytes, or process options.
      const childProcess = require('node:child_process');
      const { createInterface } = require('node:readline');
      const spawn = childProcess.spawn;
      const safeError = value => String(value || '').slice(0, 2000)
        .replace(/(authorization|api[_-]?key|token|password|secret)\s*[:=]\s*\S+/gi, '$1=[redacted]')
        .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
        .replace(/[A-Za-z0-9_+\/-]{20,}/g, '[identifier]')
        .replace(/(?:\/[^\s'"<>]+)+/g, '[path]').slice(0, 400);
      childProcess.spawn = function(executable, args, options) {
        const child = spawn.call(this, executable, args, options);
        if (args?.includes('--desktop-observer') && args?.includes('desktop_activity')) {
          const pid = child.pid;
          record({ stage: 'child-start', pid });
          child.on('error', error => record({ stage: 'child-error', pid, code: safeError(error.code), name: safeError(error.name) }));
          child.on('exit', (code, signal) => record({ stage: 'child-exit', pid, code, signal }));
          child.stdin.on('error', error => record({ stage: 'stdin-error', pid, code: safeError(error.code) }));
          createInterface({ input: child.stdout }).on('line', line => {
            try {
              const reply = JSON.parse(line);
              if (reply.failed) record({ stage: 'wire-rejected', pid,
                error: safeError(reply.error || reply.result?.error),
                featureActivity: reply.result?.feature === 'desktop_activity' });
            } catch (error) { record({ stage: 'wire-parse-error', pid, name: safeError(error.name), bytes: Buffer.byteLength(line) }); }
          });
        }
        return child;
      };
      ActivityReader.prototype.read = function(root, request) {
        const id = entries.length + ':' + Date.now();
        record({ stage: 'request', id, ownAlias: request.alias === alias, hasAlias: Boolean(request.alias), cursor: hash(request.cursor) });
        const promise = original.call(this, root, request);
        void promise.then(value => {
          const events = value.events || [];
          record({ stage: 'response', id, scopeSelf: value.scope === 'self', cursor: hash(value.cursor),
            hasMore: value.has_more, waiting: value.waiting_for_record,
            availability: ['available', 'cursor-expired', 'trace-changed', 'unavailable'].includes(value.availability) ? value.availability : 'other',
            count: events.length, ids: events.map(event => hash(event.id)),
            markers: markers.map(marker => ({ marker, matches: events.filter(event => JSON.stringify(event).includes(marker)).map(event => ({
              id: hash(event.id), result: event.phase === 'result', call: event.phase === 'call', tool: event.kind === 'tool',
            })) })) });
        }, error => record({ stage: 'error', id, name: safeError(error.name), error: safeError(error.message) }));
        return promise;
      };
    }, { alias: member.alias, markers: [liveMarker, pausedMarker] });
    facts.observerInstalled = true;
    } catch (error) {
      facts.observerInstalled = false;
      facts.observerInstallError = 'Activity reader instrumentation installation failed';
      throw error;
    }
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
    // Capture both success and failure before owned close. Never dump event text.
    const diagnostics = { at: new Date().toISOString(), markers: [liveMarker, pausedMarker],
      observerInstalled: facts.observerInstalled === true, observerInstallError: facts.observerInstallError };
    try {
      if (app) diagnostics.reads = await app.evaluate(() => globalThis.activityLiveDiagnostics || []);
    } catch { diagnostics.readError = 'Reader diagnostics unavailable'; }
    try {
      if (page) diagnostics.dom = await page.evaluate(markers => {
        const cards = [...document.querySelectorAll('.activity-event')];
        const text = node => node.textContent || '';
        const activity = document.querySelector('.activity');
        return {
          at: new Date().toISOString(), cardCount: cards.length,
          follow: [...document.querySelectorAll('.activity-controls button')].map(text).filter(value => /^(Pause following|Follow new messages)/.test(value)),
          pageCount: (activity?.textContent || '').match(/\d+ events loaded/)?.[0] || null,
          errors: [...(activity?.querySelectorAll('[role="alert"]') || [])].map(node => ({
            disconnected: /disconnected|access refused/i.test(text(node)), replay: /replaying/i.test(text(node)),
            length: text(node).length,
          })),
          markers: markers.map(marker => ({ marker, anywhere: document.body.textContent.includes(marker),
            cards: cards.filter(node => text(node).includes(marker)).map(node => ({
              visible: Boolean(node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden',
              result: text(node).includes('· result'), call: text(node).includes('· call'),
              diagnostic: text(node).includes('diagnostic'), expanded: Boolean(node.querySelector('details[open]')),
              markerOccurrences: text(node).split(marker).length - 1,
            })),
          })),
        };
      }, [liveMarker, pausedMarker]);
    } catch { diagnostics.domError = 'DOM diagnostics unavailable'; }
    try { await fs.writeFile(path.join(evidence, 'diagnostics.json'), JSON.stringify(diagnostics, null, 2)); }
    catch { console.error('DIAGNOSTICS_WRITE_FAILED'); }
    try { if (app) await app.close(); }
    catch { facts.closeError = 'Owned app close rejected'; }
    process.removeListener('SIGTERM', stopOwned);
    facts.exit = exit;
    await fs.writeFile(path.join(evidence, 'stderr.log'), stderr);
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
    console.log(JSON.stringify({ phase: 'CLOSED', evidence, exit, passed: facts.passed === true }));
  }
});
