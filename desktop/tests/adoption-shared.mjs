import assert from 'node:assert/strict';
import { defaultDates } from '../src/usage.ts';

/** Check D navigation and parallel readers against supplied native memberships. */
export async function parallelChat({ page, members, shot }) {
  const button = name => page.getByRole('button', { name, exact: true });
  await button('Expand chat').click();
  const monitor = page.locator('.monitor-page:visible');
  const columns = monitor.locator('.agent-column');
  await columns.last().waitFor();
  assert.equal(await columns.count(), members.length);
  for (const member of members) {
    const column = monitor.getByRole('article', { name: member.alias, exact: true });
    await column.getByText(`${member.historical ? 'Historical' : 'Current'} · ${member.state}`, { exact: true }).waitFor();
    await column.locator('.activity-event').first().waitFor();
  }
  await columns.first().getByRole('button', { name: 'Pause following', exact: true }).click();
  assert.equal(await columns.nth(1).getByRole('button', { name: 'Pause following', exact: true }).count(), 1);
  const selected = await monitor.locator('.react-flow__node.selected').getAttribute('data-id');
  await button('Teams & roles').click();
  await button('Monitor').click();
  assert.equal(await monitor.locator('.react-flow__node.selected').getAttribute('data-id'), selected);
  await columns.first().getByRole('button', { name: /Follow new messages/ }).waitFor();
  const global = page.getByRole('button', { name: /^GLOBAL/ });
  const projects = page.getByRole('button', { name: /^PROJECTS/ });
  await global.click();
  assert.equal(await button('Settings').isVisible(), false);
  assert.equal(await page.locator('.project-button.current').isVisible(), true);
  await global.click();
  await projects.click();
  assert.equal(await page.locator('.project-button.current').isVisible(), false);
  assert.equal(await button('Monitor').isVisible(), true);
  await projects.click();
  await button('Hide sidebar').click();
  assert.equal(await page.getByRole('navigation', { name: 'Projects', exact: true }).count(), 0);
  await shot('d-parallel-chat');
  await button('Show sidebar').click();
}

/** Verify combined global/project date routing using an actual retained usage row. */
export async function datedUsage({ page, first, second, agent, date, input = 1000, shot }) {
  const button = name => page.getByRole('button', { name, exact: true });
  const table = name => page.getByRole('table', { name, exact: true });
  const model = table('Model breakdown').getByRole('row').filter({ hasText: 'gpt-5.3-codex' });
  const dates = async (from, to) => {
    await page.getByLabel('Start date', { exact: true }).fill(from);
    await page.getByLabel('End date', { exact: true }).fill(to);
  };
  await button('Project usage').click();
  await button('Last 7 days').click();
  assert.equal(await page.getByLabel('Start date').inputValue(), defaultDates().from);
  assert.equal(await page.getByLabel('End date').inputValue(), defaultDates().to);
  await dates(date, date);
  await model.waitFor();
  const filters = page.locator('.usage-filters');
  await filters.getByLabel('Ticket', { exact: true }).selectOption('1');
  await filters.getByLabel('Agent', { exact: true }).selectOption(agent);
  await filters.getByLabel('Model', { exact: true }).selectOption('gpt-5.3-codex');
  assert.equal(await model.locator('td').nth(1).evaluate(cell => cell.firstChild.textContent.replaceAll(',', '')), String(input));
  await dates('2099-01-01', '2099-01-01');
  assert.equal(await table('Model breakdown').locator('tbody tr').count(), 0);
  await dates('2099-01-02', '2099-01-01');
  await page.locator('.usage-dashboard').getByRole('alert').waitFor();
  await dates(date, date);
  await shot('dated-project-usage');
  await button('Global usage').click();
  await dates(date, date);
  // Collection is asynchronous: wait for this project's actual quantity, not
  // just a row that is also present while its history is still loading.
  await page.waitForFunction(({ first, input }) => {
    const table = [...document.querySelectorAll('table')].find(table => table.caption?.textContent === 'Project comparison');
    const row = [...(table?.tBodies[0]?.rows ?? [])].find(row => row.cells[0].textContent === first);
    return row?.cells[2]?.firstChild.textContent.replaceAll(',', '') === String(input);
  }, { first, input });
  assert.equal(await table('Project comparison').locator('tbody tr').count(), 2);
  assert.match(await table('Project comparison').getByRole('row').filter({ hasText: second }).locator('td').nth(1).innerText(), /^Unknown/);
  assert.equal(await filters.locator('select').count(), 0);
  assert.equal(await table('Model breakdown').count(), 0);
  assert.ok(!(await page.locator('.usage-dashboard').innerText()).includes(agent));
  await shot('dated-global-usage');
}
