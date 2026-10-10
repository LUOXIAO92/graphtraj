import assert from 'node:assert/strict';

/** Exercise Settings through the installed window and its real native bridge. */
export async function settingsAdoption({ page, decide, firstId, secondId, runtimeHome, shot, step }) {
  const button = name => page.getByRole('button', { name, exact: true });
  const input = name => page.getByLabel(name, { exact: true });
  async function expectDisclosure(summary, open) {
    // Keyboard activation may finish after the input protocol reply. Await the
    // observable native state, without replaying input or prescribing a delay.
    await summary.locator(open ? 'xpath=parent::details[@open]' : 'xpath=parent::details[not(@open)]').waitFor({ state: 'attached' });
    assert.equal(await summary.locator('..').getAttribute('open'), open ? '' : null);
  }
  async function globalPage() {
    if (!await button('Agents & models').isVisible()) await button('Settings').click();
    await button('Agents & models').click();
    await button('Reload connections').waitFor();
  }
  async function saveConnections() {
    await button('Preview connections').click();
    await button('Save connections').click();
    await page.getByRole('status').getByText('Connections saved.', { exact: true }).waitFor();
  }
  async function saveRoles() {
    await button('Save changes').click();
    await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  }
  const originalSecond = await page.evaluate(id => window.graphtraj.settings(id), secondId);
  const originalFirst = await page.evaluate(id => window.graphtraj.settings(id), firstId);
  await decide(1);
  await globalPage();
  await input('Runtime entry name').fill('shared');
  await button('Add Runtime').click();
  await input('Shared Runtime Home').fill(runtimeHome);
  await saveConnections();
  const summary = page.locator('summary').filter({ hasText: /^shared · codex$/ });
  await summary.click();
  await expectDisclosure(summary, true);
  await summary.click();
  await expectDisclosure(summary, false);
  await summary.click();
  await expectDisclosure(summary, true);
  await summary.press('Enter');
  await expectDisclosure(summary, false);
  await summary.evaluate(element => {
    // Observe after document listeners, including any mounted graph shortcuts.
    window.addEventListener('keydown', event => {
      element.spaceInput = { key: event.key, code: event.code,
        defaultPrevented: event.defaultPrevented, targetIsSummary: event.target === element };
    }, { once: true });
  });
  await summary.press('Space');
  const spaceInput = await summary.evaluate(element => element.spaceInput);
  step(`Summary Space input after document handlers: ${JSON.stringify(spaceInput)}`);
  assert.deepEqual(spaceInput, { key: ' ', code: 'Space', defaultPrevented: false, targetIsSummary: true });
  await expectDisclosure(summary, true);
  step('Runtime disclosure repeat-click, Enter and Space reached their expected native states.');
  await button('Refresh native models').click();
  await page.getByText(/account access: unknown/).waitFor();
  const discoveryText = await page.getByText(/account access: unknown/).innerText();
  assert.match(discoveryText, /^(available|unknown)/);
  step(`Native discovery display: ${discoveryText}. No login or model run.`);

  const discoveredModel = page.getByRole('button', { name: /^Use / }).first();
  const canUseDiscoveredModel = await discoveredModel.count() > 0;
  if (canUseDiscoveredModel) await discoveredModel.click();

  await input('Provider name').fill('custom');
  await button('Add Provider').click();
  await input('Provider Base URL').fill('https://provider.invalid/v1');
  await input('Provider api_key_env name').fill('GRAPHTRAJ_ADOPTION_SECRET');
  if (canUseDiscoveredModel) {
    // Keep the discovered identifier unchanged: changing it would independently
    // reset metadata and conceal the destination-change regression.
    await input('Model entry name').fill('moved-discovery');
    await button('Add Model').click();
  }
  await input('Model entry name').fill('model');
  await input('Model identifier').fill('custom-model');
  await input('Model alias').fill('Manual model');
  await button('Add Model').click();
  const before = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId);
  await decide(0);
  await button('Preview connections').click();
  await button('Save connections').click();
  await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
  assert.deepEqual((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId)).catalog, before.catalog);
  await decide(1);
  await button('Save connections').click();
  await page.getByRole('status').getByText('Connections saved.', { exact: true }).waitFor();
  const saved = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId);
  assert.equal(saved.catalog.runtimes.shared.providers.custom.models.model.alias, 'Manual model');
  if (canUseDiscoveredModel) {
    const moved = saved.catalog.runtimes.shared.providers.custom.models['moved-discovery'];
    assert.equal(moved.source, 'manual');
    assert.equal(moved.supported_efforts, undefined);
    step('Real discovered model moved to a custom Provider saved as manual with no unverified efforts.');
  } else {
    step('Discovery returned no usable model; destination-change regression remains covered by focused component tests, not this installed run.');
  }
  assert.equal(saved.catalog.runtimes.shared.home, runtimeHome);
  assert.equal((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), secondId)).revision, saved.revision);
  await shot('09-global-connections.png');

  await input('Provider name').fill('cancelled');
  await button('Add Provider').click();
  await button('Cancel connections draft').click();
  assert.equal((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId)).revision, saved.revision);
  await input('Provider name').fill('stale');
  await button('Add Provider').click();
  await button('Preview connections').click();
  // Concurrent change goes through the same public native save, never file writes.
  await page.evaluate(async id => {
    const current = await window.graphtraj.connections(id, { action: 'read' });
    current.catalog.runtimes.shared.providers.custom.models.model.alias = 'Externally updated';
    await window.graphtraj.connections(id, { action: 'save', catalog: current.catalog, expected_revision: current.revision });
  }, firstId);
  await button('Save connections').click();
  await page.getByRole('alert').filter({ hasText: 'Connections changed' }).waitFor();
  await button('Reload connections').click();
  await page.getByRole('status').getByText('Connections reloaded.', { exact: true }).waitFor();
  step('Global manual provider/model/alias saved natively; cancel, refusal and external revision conflict kept the catalog intact across two projects.');

  await button('Teams & roles').click();
  await input('Team name for new team').fill('research');
  await input('New Agent name').fill('root');
  await input('New Agent model').fill('initial-model');
  await button('Add team with root').click();
  await input('Global connection').selectOption('shared/custom/model');
  await input('System prompt').fill('Keep the selected role instructions.');
  await input('Instruction file reference').fill('seed.txt');
  await page.locator('summary').filter({ hasText: /^Runtime parameters$/ }).click();
  await input('Reasoning effort').fill('low');
  await page.locator('summary').filter({ hasText: /^Codex approval route$/ }).click();
  await input('Codex approval model').fill('approval-model');
  await input('Codex approval Base URL').fill('https://review.invalid/v1');
  await input('Codex approval api_key_env name').fill('GRAPHTRAJ_APPROVAL_KEY');
  await input('New team name').fill('delivery');
  await button('Rename team').click();
  await input('New Agent name').fill('middle');
  await button('Add child Agent').click();
  await input('New Agent name').fill('leaf');
  await button('Add child Agent').click();
  await input('Agent parent').selectOption('research.root');
  await input('Agent parent').selectOption('research.middle');
  await saveRoles();
  const created = await page.evaluate(id => window.graphtraj.settings(id), firstId);
  assert.equal(created.roles['delivery.root'].connection, 'shared/custom/model');
  assert.equal(created.roles['delivery.root'].reasoning_effort, 'low');
  assert.equal(created.roles['delivery.root'].instructions, 'seed.txt');
  assert.equal(created.roles['delivery.root'].system_prompt, 'Keep the selected role instructions.');
  assert.deepEqual(created.role_tree['delivery.root'], { 'delivery.middle': { 'delivery.leaf': {} } });
  assert.deepEqual(created.roles['custom_group.observer'], originalFirst.roles['custom_group.observer']);
  await input('Team').selectOption('delivery');
  const roles = page.getByRole('navigation', { name: 'Configured roles' });
  await roles.getByRole('button', { name: 'delivery.root', exact: true }).click();
  const treeSummary = page.locator('summary').filter({ hasText: /^delivery.root$/ });
  const referenceBefore = await input('Role reference').inputValue();
  await treeSummary.click();
  await treeSummary.click();
  assert.equal(await treeSummary.locator('..').getAttribute('open'), null);
  assert.equal(await input('Role reference').inputValue(), referenceBefore);
  await roles.getByRole('button', { name: 'delivery.middle', exact: true }).click();
  await button('Delete Agent, reconnect children').click();
  await saveRoles();
  const reconnected = await page.evaluate(id => window.graphtraj.settings(id), firstId);
  assert.deepEqual(reconnected.role_tree['delivery.root'], { 'delivery.leaf': {} });
  assert.ok(!Object.hasOwn(reconnected.roles, 'delivery.middle'));
  await input('Team').selectOption('delivery');
  await roles.getByRole('button', { name: 'delivery.leaf', exact: true }).click();
  await button('Delete Agent and branch').click();
  await button('Cancel draft').click();
  assert.ok((await page.evaluate(id => window.graphtraj.settings(id), firstId)).roles['delivery.leaf']);
  await roles.getByRole('button', { name: 'delivery.leaf', exact: true }).click();
  await button('Delete Agent and branch').click();
  await saveRoles();
  assert.ok(!(await page.evaluate(id => window.graphtraj.settings(id), firstId)).roles['delivery.leaf']);
  await roles.getByRole('button', { name: 'delivery.root', exact: true }).click();
  await input('New Agent name').fill('branch');
  await button('Add child Agent').click();
  await input('New Agent name').fill('leaf');
  await button('Add child Agent').click();
  await saveRoles();
  await roles.getByRole('button', { name: 'delivery.root', exact: true }).click();
  await button('Delete Agent and branch').click();
  await decide(0);
  await button('Save changes').click();
  await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
  assert.ok((await page.evaluate(id => window.graphtraj.settings(id), firstId)).roles['delivery.root']);
  await decide(1);
  await saveRoles();
  assert.ok(!(await page.evaluate(id => window.graphtraj.settings(id), firstId)).roles['delivery.root']);
  await page.getByText('Empty organization. Add a root Agent to recover.', { exact: true }).waitFor();

  // Keep one final globally referenced team for restart/native resolution checks.
  await input('Team name for new team').fill('final');
  await input('New Agent name').fill('root');
  await button('Add team with root').click();
  await input('Global connection').selectOption('shared/custom/model');
  const parameters = page.locator('summary').filter({ hasText: /^Runtime parameters$/ });
  if (await parameters.locator('..').getAttribute('open') === null) await parameters.click();
  const approval = page.locator('summary').filter({ hasText: /^Codex approval route$/ });
  if (await approval.locator('..').getAttribute('open') === null) await approval.click();
  await input('Codex approval model').fill('approval-model');
  await input('Codex approval Base URL').fill('https://review.invalid/v1');
  await input('Codex approval api_key_env name').fill('GRAPHTRAJ_APPROVAL_KEY');
  await saveRoles();
  await input('Team name for new team').fill('temporary');
  await input('New Agent name').fill('root');
  await button('Add team with root').click();
  await saveRoles();
  await input('Team').selectOption('temporary');
  await button('Delete team').click();
  await saveRoles();
  await input('Team').selectOption('final');
  await input('System prompt').fill('stale UI draft');
  await page.evaluate(async id => {
    const current = await window.graphtraj.settings(id);
    await window.graphtraj.saveSettings(id, { revision: current.revision, edits: { 'final.root': { reasoning_effort: 'low' } }, renames: {}, add_edges: [], remove_edges: [] });
  }, firstId);
  await button('Save changes').click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  await button('Reload and discard draft').click();
  await page.getByRole('status').getByText('Loaded current configuration. Draft discarded.', { exact: true }).waitFor();
  const final = await page.evaluate(id => window.graphtraj.settings(id), firstId);
  assert.ok(!Object.keys(final.roles).some(ref => ref.startsWith('temporary.')));
  assert.ok(final.roles['final.root']);
  assert.deepEqual(await page.evaluate(id => window.graphtraj.settings(id), secondId), originalSecond);
  await shot('10-teams-and-global-reference.png');
  step('Created and renamed teams; added/reparented Agents; reconnected children, deleted leaf/branch/team, rejected and cancelled drafts; second project stayed identical. Final connection passed native role/Runtime validation without launching an Agent.');
  return { global: await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId), roles: final, discoveryDisplay: discoveryText };
}
