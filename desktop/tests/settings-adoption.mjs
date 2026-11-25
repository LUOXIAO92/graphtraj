import assert from 'node:assert/strict';

/**
 * Exercise Settings through the installed window and its real native bridge.
 *
 * The D desktop saves directly: Save writes through the shared native writer and
 * Cancel discards the draft (user decision recorded in docs/specs/optional-desktop-gui-mvp.md,
 * 「用户确认的配置、活动与统计修正」). There is no approval dialog. `checkSave(label)` is the
 * caller's platform check after every Save: zero native message boxes and no
 * credential value in the window or its logs.
 */
export async function settingsAdoption({ page, firstId, secondId, runtimeHome, shot, step, checkSave,
  legacyRole = 'custom_group.observer' }) {
  // Concealed pages stay mounted (visibility: hidden); keep only visible matches.
  const button = name => page.getByRole('button', { name, exact: true }).filter({ visible: true });
  const input = name => page.getByLabel(name, { exact: true }).filter({ visible: true });
  const allSaved = () => page.getByText('All changes saved', { exact: true }).filter({ visible: true }).waitFor();
  const dialog = page.getByRole('dialog');
  const dialogButton = name => dialog.getByRole('button', { name, exact: true });
  const readCatalog = id => page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), id);
  const readRoles = id => page.evaluate(id => window.graphtraj.settings(id), id);
  // The detail heading's add button acts on the selected Runtime or provider.
  const headingButton = name => page.locator('.d-library-detail-heading').getByRole('button', { name, exact: true });
  const tree = page.getByRole('navigation', { name: 'Runtime provider model hierarchy', exact: true });
  // React Flow 12 gives a focusable node role 'group' (node.ariaRole ?? (isFocusable ? 'group' : undefined));
  // the name is TeamGraph.tsx:50/61 `Configure agent ${roleName(renames, ref)}`, the pending team rename included.
  const agent = reference => page.getByRole('group', { name: `Configure agent ${reference}`, exact: true });
  const teamTab = name => page.getByRole('navigation', { name: 'Project teams', exact: true }).getByRole('button', { name: new RegExp(`^${name}\\b`) });
  async function globalPage() {
    // Sidebar-scoped: an open Teams & roles page has its own 'Agents & models' shortcut (Settings.tsx).
    const sidebar = page.getByRole('complementary', { name: 'Projects', exact: true });
    const entry = sidebar.getByRole('button', { name: 'Agents & models', exact: true });
    if (!await entry.isVisible()) await sidebar.getByRole('button', { name: 'Settings', exact: true }).click();
    await entry.click();
    await tree.waitFor();
  }
  async function saved(message) {
    // The confirmation is a role=status toast cleared after 4.5 s; the footer state stays.
    await button('Save').click();
    await page.getByRole('status').filter({ hasText: message }).waitFor();
    await allSaved();
  }
  async function saveConnections(label) { await saved('Connections saved.'); await checkSave(label); }
  async function saveRoles(label) { await saved('Settings saved.'); await checkSave(label); }
  async function addEntry(kind, fields) {
    for (const [label, value] of Object.entries(fields)) await dialog.getByLabel(label, { exact: true }).fill(value);
    await dialogButton(`Add ${kind}`).click();
    await dialog.waitFor({ state: 'detached' });
  }
  async function addAgent({ team, name }) {
    // D creates every Agent with a global model (Settings.tsx addNode).
    if (team) await input('Team name for new team').fill(team);
    await input('New Agent name').fill(name);
    // Model stays disabled until a Runtime is chosen (Settings.tsx modelFields).
    await input('New Agent Runtime').selectOption('shared');
    await input('New Agent provider').selectOption('custom');
    await input('New Agent model').selectOption('shared/custom/model');
    await dialogButton(team ? 'Add team with root' : 'Add Agent').click();
    await dialog.waitFor({ state: 'detached' });
  }
  async function removeSelected(mode) {
    await button('Delete selected agent configuration').click();
    if (mode) await dialog.getByRole('radio', { name: mode }).check();
    await dialogButton('Remove configuration').click();
    await dialog.waitFor({ state: 'detached' });
  }
  async function openApproval() {
    const summary = page.locator('summary').filter({ hasText: /^Codex approval model$/ }).filter({ visible: true });
    if (await summary.locator('..').getAttribute('open') === null) await summary.click();
  }
  async function expectExpanded(toggle, expanded) {
    // Keyboard activation may finish after the input protocol reply. Await the
    // observable native state, without replaying input or prescribing a delay.
    await page.getByRole('button', { name: `${expanded ? 'Collapse' : 'Expand'} shared Runtime`, exact: true }).waitFor();
    assert.equal(await toggle().getAttribute('aria-expanded'), String(expanded));
  }
  const originalSecond = await readRoles(secondId);
  const originalFirst = await readRoles(firstId);
  await globalPage();
  await button('Add Runtime').click();
  await addEntry('runtime', { 'Runtime entry name': 'shared' });
  await input('Runtime Home').fill(runtimeHome);
  await saveConnections('runtime');
  const toggle = () => tree.getByRole('button', { name: /^(Expand|Collapse) shared Runtime$/ });
  await expectExpanded(toggle, true);
  await toggle().click();
  await expectExpanded(toggle, false);
  await toggle().click();
  await expectExpanded(toggle, true);
  await toggle().click();
  await expectExpanded(toggle, false);
  await toggle().press('Enter');
  await expectExpanded(toggle, true);
  await toggle().evaluate(element => {
    // Observe after document listeners, including any mounted graph shortcuts.
    window.addEventListener('keydown', event => {
      element.spaceInput = { key: event.key, code: event.code,
        defaultPrevented: event.defaultPrevented, targetIsToggle: event.target === element };
    }, { once: true });
  });
  await toggle().press('Space');
  const spaceInput = await toggle().evaluate(element => element.spaceInput);
  step(`Runtime disclosure Space input after document handlers: ${JSON.stringify(spaceInput)}`);
  assert.deepEqual(spaceInput, { key: ' ', code: 'Space', defaultPrevented: false, targetIsToggle: true });
  await expectExpanded(toggle, false);
  await toggle().click();
  await expectExpanded(toggle, true);
  step('Runtime disclosure repeat-click, Enter and Space reached their expected native states.');
  await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
  await button('Refresh native models').click();
  const discovery = page.locator('.d-discovery-state');
  await discovery.locator('strong').filter({ hasNotText: /^Runtime discovery$/ }).waitFor();
  const discoveryStatus = (await discovery.locator('strong').textContent()).trim();
  const discoveryText = `${discoveryStatus} · ${(await page.getByText(/^Account access: /).filter({ visible: true }).textContent()).trim()}`;
  assert.match(discoveryText, /^(available|unknown)/);
  assert.match(discoveryText, /account access: unknown$/i);
  step(`Native discovery display: ${discoveryText}. No login or model run.`);

  const discoveredModel = page.getByRole('button', { name: /^Use / }).first();
  const canUseDiscoveredModel = await discoveredModel.count() > 0;
  async function draftCustom() {
    await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
    await headingButton('Add provider').click();
    await addEntry('provider', { 'Provider name': 'custom' });
    await input('Base URL').fill('https://provider.invalid/v1');
    await input('API key environment variable').fill('GRAPHTRAJ_ADOPTION_SECRET');
    if (canUseDiscoveredModel) {
      // Keep the discovered identifier unchanged: changing it would independently
      // reset metadata and conceal the destination-change regression. In D the
      // discovered entry is added under its own provider, then that provider is
      // routed to a custom endpoint (Connections.tsx Base URL), the destination change.
      await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
      await button('Refresh native models').click();
      await discoveredModel.click();
      await dialog.getByLabel('Model entry name', { exact: true }).fill('moved-discovery');
      await dialogButton('Add model').click();
      await dialog.waitFor({ state: 'detached' });
      await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
      await page.locator('.library-select').filter({ hasText: 'custom' }).click();
    }
    await headingButton('Add model').click();
    await addEntry('model', { 'Model entry name': 'model', 'Model identifier': 'custom-model', 'Model alias': 'Manual model' });
  }
  const before = await readCatalog(firstId);
  await draftCustom();
  // Declining is Cancel in D: the draft is discarded and nothing is written.
  await button('Cancel').click();
  await allSaved();
  assert.deepEqual((await readCatalog(firstId)).catalog, before.catalog);
  await draftCustom();
  await saveConnections('connections');
  const savedCatalog = await readCatalog(firstId);
  assert.equal(savedCatalog.catalog.runtimes.shared.providers.custom.models.model.alias, 'Manual model');
  if (canUseDiscoveredModel) {
    const moved = Object.values(savedCatalog.catalog.runtimes.shared.providers)
      .map(provider => provider.models['moved-discovery']).find(Boolean);
    assert.equal(moved.source, 'manual');
    assert.equal(moved.supported_efforts, undefined);
    step('Real discovered model moved to a custom Provider saved as manual with no unverified efforts.');
  } else {
    step('Discovery returned no usable model; destination-change regression remains covered by focused component tests, not this installed run.');
  }
  assert.equal(savedCatalog.catalog.runtimes.shared.home, runtimeHome);
  assert.equal((await readCatalog(secondId)).revision, savedCatalog.revision);
  await shot('09-global-connections.png');

  await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
  await headingButton('Add provider').click();
  await addEntry('provider', { 'Provider name': 'cancelled' });
  await button('Cancel').click();
  assert.equal((await readCatalog(firstId)).revision, savedCatalog.revision);
  await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
  await headingButton('Add provider').click();
  await addEntry('provider', { 'Provider name': 'stale' });
  // Concurrent change goes through the same public native save, never file writes.
  await page.evaluate(async id => {
    const current = await window.graphtraj.connections(id, { action: 'read' });
    current.catalog.runtimes.shared.providers.custom.models.model.alias = 'Externally updated';
    await window.graphtraj.connections(id, { action: 'save', catalog: current.catalog, expected_revision: current.revision });
  }, firstId);
  await button('Save').click();
  await page.getByRole('alert').filter({ hasText: 'Connections changed' }).waitFor();
  assert.ok(!Object.hasOwn((await readCatalog(firstId)).catalog.runtimes.shared.providers, 'stale'));
  await button('Reload').click();
  await allSaved();
  // The model button sits in a collapsed (hidden) provider branch; include hidden nodes.
  await tree.getByRole('button', { name: 'Externally updated', exact: true, includeHidden: true }).waitFor({ state: 'attached' });
  step('Global manual provider/model/alias saved natively; cancel, refusal and external revision conflict kept the catalog intact across two projects.');

  await button('Teams & roles').click();
  await button('Add team').click();
  await addAgent({ team: 'research', name: 'root' });
  await input('System prompt').fill('Keep the selected role instructions.');
  await input('Developer prompt file').fill('seed.txt');
  await input("This agent's effort").selectOption('low');
  await openApproval();
  await input('Codex approval model').selectOption('shared/custom/model');
  await input('Team name').fill('delivery');
  await button('Add child agent').click();
  await addAgent({ name: 'middle' });
  await agent('delivery.root').click();
  await button('Add child agent').click();
  await addAgent({ name: 'leaf' });
  // Reparent leaf from root to middle with the organization tree's own handles.
  await dragHandle(page, agent('delivery.middle').getByLabel('Connect a child', { exact: true }),
    agent('delivery.leaf').getByLabel('Parent connection', { exact: true }));
  await saveRoles('team created');
  const created = await readRoles(firstId);
  assert.equal(created.roles['delivery.root'].connection, 'shared/custom/model');
  assert.equal(created.roles['delivery.root'].reasoning_effort, 'low');
  assert.equal(created.roles['delivery.root'].instructions, 'seed.txt');
  assert.equal(created.roles['delivery.root'].system_prompt, 'Keep the selected role instructions.');
  assert.deepEqual(created.role_tree['delivery.root'], { 'delivery.middle': { 'delivery.leaf': {} } });
  assert.deepEqual(created.roles[legacyRole], originalFirst.roles[legacyRole]);
  await teamTab('delivery').click();
  // Re-selecting the selected agent keeps the same role in the properties panel.
  await agent('delivery.root').click();
  const referenceBefore = await input('Agent name').inputValue();
  await agent('delivery.root').click();
  await agent('delivery.root').click();
  assert.equal(await input('Agent name').inputValue(), referenceBefore);
  await agent('delivery.middle').click();
  await removeSelected('Keep descendants');
  await saveRoles('reconnected');
  const reconnected = await readRoles(firstId);
  assert.deepEqual(reconnected.role_tree['delivery.root'], { 'delivery.leaf': {} });
  assert.ok(!Object.hasOwn(reconnected.roles, 'delivery.middle'));
  await teamTab('delivery').click();
  await agent('delivery.leaf').click();
  await removeSelected();
  await button('Cancel').click();
  assert.ok((await readRoles(firstId)).roles['delivery.leaf']);
  await agent('delivery.leaf').click();
  await removeSelected();
  await saveRoles('leaf removed');
  assert.ok(!(await readRoles(firstId)).roles['delivery.leaf']);
  await agent('delivery.root').click();
  await button('Add child agent').click();
  await addAgent({ name: 'branch' });
  await agent('delivery.root').click();
  await button('Add child agent').click();
  await addAgent({ name: 'leaf' });
  await saveRoles('branch added');
  await agent('delivery.root').click();
  await removeSelected('Delete the entire branch');
  // Declining is Cancel: the whole-branch deletion is discarded, nothing written.
  await button('Cancel').click();
  await allSaved();
  assert.ok((await readRoles(firstId)).roles['delivery.root']);
  await agent('delivery.root').click();
  await removeSelected('Delete the entire branch');
  await saveRoles('branch removed');
  assert.ok(!(await readRoles(firstId)).roles['delivery.root']);
  // D derives teams from roles: an emptied team leaves no tab (Settings.tsx teams).
  assert.equal(await teamTab('delivery').count(), 0);

  // Keep one final globally referenced team for restart/native resolution checks.
  await button('Add team').click();
  await addAgent({ team: 'final', name: 'root' });
  await openApproval();
  await input('Codex approval model').selectOption('shared/custom/model');
  await saveRoles('final team');
  await button('Add team').click();
  await addAgent({ team: 'temporary', name: 'root' });
  await saveRoles('temporary team');
  await teamTab('temporary').click();
  await button('Delete team').click();
  await dialogButton('Remove configuration').click();
  await saveRoles('temporary removed');
  await teamTab('final').click();
  await input('System prompt').fill('stale UI draft');
  await page.evaluate(async id => {
    const current = await window.graphtraj.settings(id);
    await window.graphtraj.saveSettings(id, { revision: current.revision, edits: { 'final.root': { reasoning_effort: 'low' } }, renames: {}, add_edges: [], remove_edges: [] });
  }, firstId);
  await button('Save').click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  await button('Reload').click();
  await page.getByRole('status').filter({ hasText: 'Loaded current configuration.' }).waitFor();
  await agent('final.root').click();
  assert.notEqual(await input('System prompt').inputValue(), 'stale UI draft', 'Reload discards the draft');
  const final = await readRoles(firstId);
  assert.ok(!Object.keys(final.roles).some(ref => ref.startsWith('temporary.')));
  assert.ok(final.roles['final.root']);
  assert.equal(final.roles['final.root'].reasoning_effort, 'low');
  assert.deepEqual(await readRoles(secondId), originalSecond);
  await shot('10-teams-and-global-reference.png');
  step('Created and renamed teams; added/reparented Agents; reconnected children, deleted leaf/branch/team, rejected and cancelled drafts; second project stayed identical. Final connection passed native role/Runtime validation without launching an Agent.');
  return { global: await readCatalog(firstId), roles: final, discoveryDisplay: discoveryText };
}

/** Drag between two React Flow handles with real pointer input (as team-graph.test.mjs). */
export async function dragHandle(page, from, to) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const a = await from.boundingBox(), b = await to.boundingBox();
  assert.ok(a && b, 'organization tree handles must be visible');
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 });
  await page.mouse.up();
}
