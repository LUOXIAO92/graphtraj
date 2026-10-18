/** Task 336: screenshot-driven real-window check of member scope, lifecycle display and archive settings.
 *
 * Launches this Worktree's built Electron App on a real project and operates it only with
 * page.mouse / page.keyboard. The App never stops or continues an Agent: when
 * GRAPHTRAJ_SCOPE_ALIAS is set, the operator stops and then continues that member through
 * native operations while this script waits and captures each visible state.
 *
 * Env: GRAPHTRAJ_TOOL (candidate graphtraj-tool), GRAPHTRAJ_SCOPE_PROJECT (project root),
 * GRAPHTRAJ_SCOPE_SUMMARY (historical summary Task ID), optional GRAPHTRAJ_SCOPE_ALIAS,
 * optional GRAPHTRAJ_SCOPE_EVIDENCE (default dist-package/adoption-evidence/336-<commit>).
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const project = process.env.GRAPHTRAJ_SCOPE_PROJECT;
const summary = process.env.GRAPHTRAJ_SCOPE_SUMMARY;
const alias = process.env.GRAPHTRAJ_SCOPE_ALIAS;
assert.ok(process.env.GRAPHTRAJ_TOOL && project && summary, 'Set GRAPHTRAJ_TOOL, GRAPHTRAJ_SCOPE_PROJECT and GRAPHTRAJ_SCOPE_SUMMARY');
const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: desktop, encoding: 'utf8' }).trim();
const dirty = execFileSync('git', ['status', '--porcelain', '--', '.'], { cwd: desktop, encoding: 'utf8' }).trim();
const evidence = path.resolve(process.env.GRAPHTRAJ_SCOPE_EVIDENCE || path.join(desktop, 'dist-package', 'adoption-evidence', `336-${commit.slice(0, 12)}`));
const config = path.join(project, '.graphtraj', 'swarm', 'config.yml');
const facts = { commit, dirty: Boolean(dirty), project, summary, alias: alias ?? null, electron: electronExecutable,
  launches: 0, steps: [], screenshots: [], passed: false };
await fs.mkdir(evidence, { recursive: true });

let app;
let page;
const step = text => { facts.steps.push({ at: new Date().toISOString(), text }); console.log(text); };
const shot = async name => { const file = path.join(evidence, name); await page.screenshot({ path: file }); facts.screenshots.push(file); };
/** Click the visible centre of a control with the real mouse. */
const click = async locator => {
  await locator.waitFor({ state: 'visible' });
  const box = await locator.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
};
/** Choose a select option with mouse focus and keyboard type-ahead only. */
const choose = async (locator, label) => {
  await click(locator);
  await page.keyboard.press('Escape');
  await page.keyboard.type(label);
  await page.keyboard.press('Enter');
};
const rows = () => page.locator('.member-tree-rows > button').allInnerTexts();
const row = name => page.locator('.member-tree-rows > button', { hasText: name });

try {
  app = await electron.launch({ executablePath: electronExecutable, timeout: 20000,
    args: [desktop, `--project=${project}`, `--user-data-dir=${path.join(evidence, 'profile')}`],
    env: { ...process.env, MAC_CHROMIUM_TMPDIR: evidence } });
  facts.launches += 1;
  page = await app.firstWindow();
  page.setDefaultTimeout(20000);

  // Current summaries are the default scope.
  await click(page.getByRole('button', { name: 'Members', exact: true }));
  // A project without members shows the empty state; rows are listed otherwise.
  const listed = () => page.locator('.member-tree-rows > button, .member-tree p[role="status"]:has-text("No members in this scope.")').first().waitFor();
  await page.getByText('Members of current summaries', { exact: false }).waitFor();
  await listed();
  facts.currentNotice = await page.locator('.member-tree .native-notice').first().innerText();
  const current = await rows();
  facts.current = current;
  assert.ok(current.every(text => !text.includes('Retired')), 'Retired members never appear in the current list');
  step(`current scope lists ${current.length} members`);
  await shot('01-members-current.png');

  // One historical summary, then back: reading must leave current members unchanged.
  await choose(page.getByLabel('Member scope'), `History · #${summary}`);
  await page.getByText('History of one summary', { exact: false }).waitFor();
  await listed();
  facts.historyNotice = await page.locator('.member-tree .native-notice').first().innerText();
  facts.history = await rows();
  step(`history of #${summary} lists ${facts.history.length} members`);
  await shot('02-members-history.png');
  await choose(page.getByLabel('Member scope'), 'Current summaries');
  await page.getByText('Members of current summaries', { exact: false }).waitFor();
  await page.waitForTimeout(3500);
  const again = await rows();
  // Parents and states come from native records; switching scope must not change them.
  assert.deepEqual(again.filter(text => !alias || !text.includes(alias)), current.filter(text => !alias || !text.includes(alias)));
  step('switching scope left current members, parents and states unchanged');
  await shot('03-members-current-again.png');

  if (alias) {
    // The operator performs stop and continue natively; the App only observes.
    for (const [state, name] of [['Active', '04-lifecycle-active.png'], ['Standby', '05-lifecycle-standby.png'], ['Active', '06-lifecycle-active-again.png']]) {
      console.log(JSON.stringify({ phase: 'WAITING', alias, state }));
      await row(alias).filter({ hasText: `${state}` }).first().waitFor({ timeout: 600000 });
      step(`${alias} shows ${state}`);
      await shot(name);
    }
    // Messages of the same member are readable with their direction.
    await click(row(alias).first());
    await page.locator(`[data-agent-id="${alias}"] .activity-event`).first().waitFor();
    await page.locator(`[data-agent-id="${alias}"]`).getByText(/Message (to|from) /).first().waitFor();
    step('member conversation shows readable messages with direction');
    await shot('07-member-conversation.png');
    await click(page.getByRole('button', { name: 'Collapse chat', exact: true }));
  }

  // Archive switches: edit, confirm the tool's own file, reload, restore.
  const before = await fs.readFile(config, 'utf8').catch(() => null);
  facts.configBefore = before;
  await click(page.getByRole('button', { name: 'Teams & roles', exact: true }));
  const backfill = page.getByLabel('Backfill history of associated Sessions');
  await backfill.waitFor();
  const original = await backfill.isChecked();
  await click(backfill);
  await page.getByText('Saved Session archive settings.').waitFor();
  const written = await fs.readFile(config, 'utf8');
  assert.ok(written.includes(`backfill_history: ${!original}`), written);
  await click(page.getByRole('button', { name: 'Reload', exact: true }));
  await page.getByText('Loaded current configuration.').waitFor();
  assert.equal(await backfill.isChecked(), !original);
  step(`backfill_history saved as ${!original} in swarm/config.yml and reloaded`);
  await shot('08-settings-archive-edited.png');
  await click(backfill);
  await page.getByText('Saved Session archive settings.').waitFor();
  facts.configAfter = await fs.readFile(config, 'utf8');
  assert.ok(facts.configAfter.includes(`backfill_history: ${original}`));
  step('backfill_history restored to its original value');
  await shot('09-settings-archive-restored.png');
  facts.passed = true;
} catch (error) {
  facts.failure = String(error);
  if (page) await shot('failure.png').catch(() => {});
  process.exitCode = 1;
} finally {
  if (app) await app.close().catch(() => { facts.closeError = 'Owned app close rejected'; });
  await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
  console.log(JSON.stringify({ phase: 'CLOSED', evidence, passed: facts.passed }));
}
