import assert from 'node:assert/strict';
import { defaultDates } from '../src/usage.ts';

/** Column state wording, restated from desktop/src/Activity.tsx visibleState. */
export const visibleState = state => state === 'retired' ? 'retired'
  : state === 'running' || state === 'unreachable' || state === 'active' ? 'active' : 'standby';

/** A task card on the X6 monitor canvas; its title button carries the accessible name. */
export const taskCard = (scope, id) => scope.locator(`.native-task-card[data-task-id="${id}"]`);
/** Select a task by its title button (TaskCanvas.tsx card). */
export const openTask = (scope, id) => taskCard(scope, id).locator('.native-task-title').click();
/** The selected task id: the card whose title button is pressed. */
export const selectedTask = scope => scope.locator('.native-task-card')
  .filter({ has: scope.page().getByRole('button', { pressed: true }) }).getAttribute('data-task-id');

/** Open the Projects view, the only place for Add/Check/Relocate/Remove (main.tsx ProjectIndexEditor). */
export async function projectsView(page) {
  const add = page.getByRole('button', { name: 'Add project', exact: true });
  if (await add.isVisible()) return;
  const manage = page.getByRole('button', { name: 'Add or manage projects', exact: true });
  if (await manage.isVisible()) await manage.click();
  else await page.getByRole('button', { name: 'Manage projects', exact: true }).click();
  await add.waitFor();
}

/** Remove one index entry through the D confirmation dialog. */
export async function removeIndexEntry(page, root) {
  await projectsView(page);
  await page.getByRole('button', { name: `Remove ${root}`, exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove index entry', exact: true }).click();
}

/**
 * Count Electron message boxes: D saves directly, so any approval dialog is a
 * regression. The stub throws, failing that save visibly (settings-window.test.mjs).
 */
export async function guardApprovals(app) {
  await app.evaluate(({ dialog }) => {
    globalThis.adoptionApprovalDialogs = 0;
    dialog.showMessageBox = async () => { globalThis.adoptionApprovalDialogs++; throw new Error('Unexpected approval dialog'); };
    dialog.showMessageBoxSync = () => { globalThis.adoptionApprovalDialogs++; throw new Error('Unexpected approval dialog'); };
  });
}
export const approvalDialogs = app => app.evaluate(() => globalThis.adoptionApprovalDialogs);

/** Check D navigation and parallel readers against supplied native memberships. */
export async function parallelChat({ page, members, shot }) {
  assert.ok(members.some(member => member.historical) && members.some(member => !member.historical),
    'Parallel adoption needs both historical and current native memberships');
  const button = name => page.getByRole('button', { name, exact: true });
  await button('Expand chat').click();
  const monitor = page.locator('.monitor-page:visible');
  const columns = monitor.locator('.agent-column');
  await columns.last().waitFor();
  assert.equal(await columns.count(), members.length);
  for (const member of members) {
    const column = monitor.getByRole('article', { name: member.alias, exact: true });
    await column.getByText(`${member.historical ? 'Historical' : 'Current'} · ${visibleState(member.state)}`, { exact: true }).waitFor();
    await column.locator('.activity-event').first().waitFor();
  }
  await columns.first().getByRole('button', { name: 'Pause following', exact: true }).click();
  assert.equal(await columns.nth(1).getByRole('button', { name: 'Pause following', exact: true }).count(), 1);
  const selected = await selectedTask(monitor);
  await button('Teams & roles').click();
  await button('Monitor').click();
  assert.equal(await selectedTask(monitor), selected);
  await columns.first().getByRole('button', { name: /Follow new messages/ }).waitFor();
  const global = page.getByRole('button', { name: /^GLOBAL/ });
  const projects = page.getByRole('button', { name: /^PROJECTS/ });
  const current = page.locator('.project-button[aria-current="true"]');
  await global.click();
  assert.equal(await button('Settings').isVisible(), false);
  assert.equal(await current.isVisible(), true);
  await global.click();
  await projects.click();
  assert.equal(await current.isVisible(), false);
  assert.equal(await button('Monitor').isVisible(), true);
  await projects.click();
  await button('Hide sidebar').click();
  assert.equal(await page.getByRole('complementary', { name: 'Projects', exact: true }).count(), 0);
  await shot('d-parallel-chat');
  await button('Show sidebar').click();
}

/** Verify combined global/project date routing using an actual retained usage row. */
export async function datedUsage({ page, first, second, agent, date, input = 1000, shot }) {
  const button = name => page.getByRole('button', { name, exact: true });
  const dashboard = page.getByRole('region', { name: 'Usage dashboard', exact: true });
  // D lists models as buttons (UsageDashboard.tsx d-model-list); it has no breakdown table.
  const model = dashboard.getByRole('button', { name: /^gpt-5\.3-codex\b/ });
  const modelList = dashboard.getByText('MODELS IN THIS PROJECT', { exact: true });
  // The dated chart's tooltip keeps the exact reported input (UsageDashboard.tsx DHistoryTrend).
  const exactInput = async () => dashboard.getByRole('img', { name: /^Reported input by date/ }).locator('title')
    .evaluateAll(titles => titles.map(title => title.textContent));
  const dates = async (from, to) => {
    await dashboard.getByLabel('Start date', { exact: true }).fill(from);
    await dashboard.getByLabel('End date', { exact: true }).fill(to);
  };
  await button('Project usage').click();
  await button('Last 7 days').click();
  assert.equal(await dashboard.getByLabel('Start date').inputValue(), defaultDates().from);
  assert.equal(await dashboard.getByLabel('End date').inputValue(), defaultDates().to);
  await dates(date, date);
  await model.waitFor();
  await dashboard.getByLabel('Task', { exact: false }).selectOption('1');
  await dashboard.getByLabel('Agent', { exact: false }).selectOption(agent);
  await model.click();
  assert.equal(await model.getAttribute('aria-pressed'), 'true');
  const quantity = (await page.evaluate(value => value.toLocaleString(), input));
  assert.deepEqual(await exactInput(), [`${date}: ${quantity} input tokens`]);
  await dates('2099-01-01', '2099-01-01');
  await dashboard.getByRole('heading', { name: 'No dated usage in this view', exact: true }).waitFor();
  assert.equal(await dashboard.locator('.d-dated-records > div').count(), 0);
  await dates('2099-01-02', '2099-01-01');
  await dashboard.getByRole('alert').waitFor();
  await dates(date, date);
  await shot('dated-project-usage');
  await button('All project usage').click();
  await dates(date, date);
  // Collection is asynchronous: wait for this project's actual quantity, not
  // just a row that is also present while its history is still loading.
  const comparison = dashboard.getByRole('table', { name: 'Project comparison', exact: true });
  const row = root => comparison.getByRole('row').filter({ has: page.locator(`span[title="${root}"]`) });
  await page.waitForFunction(({ date, quantity }) => [...document.querySelectorAll('.usage-dashboard svg title')]
    .some(title => title.textContent === `${date}: ${quantity} input tokens`), { date, quantity });
  await row(first).getByRole('cell').first().filter({ hasNotText: /^Unknown/ }).waitFor();
  assert.equal(await comparison.locator('tbody tr').count(), 2);
  assert.match(await row(second).getByRole('cell').first().innerText(), /^Unknown/);
  assert.equal(await dashboard.getByRole('combobox').count(), 0);
  assert.equal(await modelList.count(), 0);
  assert.ok(!(await dashboard.innerText()).includes(agent));
  await shot('dated-global-usage');
}
