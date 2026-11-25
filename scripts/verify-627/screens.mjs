// Task 627 step S driver (extends verify-626/screens.mjs): light/dark screenshots of the built desktop app over a
// disposable fixture, with machine checks for the Task 627 structure (overlap = bounding-box intersection).
// argv: <desktop dir (built export)> <out dir> [--fixture-only]. Run only through steps.zsh S (allowlisted env,
// isolated HOME). --fixture-only builds and reads back the fixture without starting Electron (rehearsal).
// The theme is forced inside the app (Electron nativeTheme.themeSource); the system appearance is never touched.
// No Save is pressed and no native picker is opened: the project is passed with --project.
// Any failure is recorded in facts.json (with the stage it happened in); facts.json is always written and the
// app is always closed (then killed if it does not close), so no window is left open.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const [desktop, out, mode] = process.argv.slice(2);
const fixtureOnly = mode === '--fixture-only';
const require = createRequire(path.join(desktop, 'package.json'));
const facts = { desktop, out, mode: fixtureOnly ? 'fixture-only' : 'screens', started: new Date().toISOString(), steps: [],
  themes: {}, overlaps: [], overlapNotes: [], pageErrors: [], problems: [] };
// The screens S must produce per theme (1440x900 unless named narrow-*, which are 1000x760).
const SCREENS = ['task-graph', 'search', 'members', 'chat', 'teams-roles', 'agents-models', 'project-usage',
  'narrow-task-graph', 'narrow-task-graph-selected'];
const note = text => { facts.steps.push(text); console.log(`-- ${text}`); };
const problem = text => { facts.problems.push(text); console.log(`!! ${text}`); };
const withTimeout = (promise, ms, what) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what} timed out after ${ms} ms`)), ms);
  })]).finally(() => clearTimeout(timer));
};
let stage = 'setup';
let theme = null;
let app = null;
let page = null;
// Playwright can reject an internal promise (e.g. "Process failed to launch!") outside the awaited call; record it
// instead of letting Node exit before facts.json is written. The awaited call is bounded by withTimeout below.
let unhandled = null;
const onUnhandled = kind => error => {
  unhandled ??= error;
  problem(`${kind} during "${stage}": ${error?.message ?? error}`);
};
process.on('unhandledRejection', onUnhandled('unhandled rejection'));
process.on('uncaughtException', onUnhandled('uncaught exception'));

async function shot(name) {
  const file = path.join(out, `${theme}-${name}.png`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: file });
  const size = (await fs.stat(file)).size;
  facts.themes[theme].screens[name] = { file, size };
  if (size < 10000) problem(`${theme} ${name} screenshot is only ${size} bytes`);
  note(`${theme} ${name}: ${file} (${size} bytes)`);
}
async function resize(width, height) {
  await app.evaluate(({ BrowserWindow }, [w, h]) => { const win = BrowserWindow.getAllWindows()[0]; win.setContentSize(w, h); win.center(); }, [width, height]);
  await page.waitForTimeout(400);
}
const monitor = () => page.locator('.monitor-page:not(.concealed)');
/** Back to the visible project's task graph: sidebar 'Monitor', then the top bar's 'Task graph' segment (V4). */
async function toGraph() {
  await page.getByRole('button', { name: 'Monitor', exact: true }).click();
  await monitor().getByRole('group', { name: 'Monitor view' }).getByRole('button', { name: 'Task graph', exact: true }).click();
  await page.waitForTimeout(300);
}
async function selectTaskOne() {
  await toGraph();
  await monitor().locator('[aria-label="Native task canvas"] .native-task-card[data-task-id="1"] .native-task-title').click();
  await page.getByRole('complementary', { name: 'Task details' }).waitFor();
  await page.waitForTimeout(800);
}
async function closeDetails() {
  const close = monitor().getByRole('button', { name: 'Close details', exact: true });
  if (await close.isVisible()) await close.click();
  await page.waitForTimeout(500);
}
/**
 * Overlap machine check (Task 627): bounding boxes of the visible task cards, clipped to the main canvas, against the
 * canvas overlays. A card under the minimap, or the 'Search results' panel over the canvas or a card, is a problem
 * (626 leftover at 1000 px; 621 interim 23). Legend and zoom intersections are recorded as notes. `inspector` asks
 * for the U2 position of Task details: 'right' (wide) or 'bottom' (below ~1100 px).
 */
async function layout(name, { inspector = null, search = false } = {}) {
  const boxes = await page.evaluate(() => {
    const scope = document.querySelector('.monitor-page:not(.concealed)');
    const box = element => {
      if (!element) return null;
      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') return null;
      const r = element.getBoundingClientRect();
      return r.width && r.height ? { x: r.left, y: r.top, right: r.right, bottom: r.bottom } : null;
    };
    const canvas = box(scope.querySelector('[aria-label="Native task canvas"]'));
    const clip = r => canvas && r ? { x: Math.max(r.x, canvas.x), y: Math.max(r.y, canvas.y),
      right: Math.min(r.right, canvas.right), bottom: Math.min(r.bottom, canvas.bottom) } : null;
    const cards = [...scope.querySelectorAll('[aria-label="Native task canvas"] .native-task-card')]
      .map(card => ({ id: card.dataset.taskId, box: clip(box(card)) }))
      .filter(card => card.box && card.box.right > card.box.x && card.box.bottom > card.box.y);
    return { canvas, cards, minimap: box(scope.querySelector('.native-minimap')),
      legend: box(scope.querySelector('.native-relation-legend')), zoom: box(scope.querySelector('.native-task-zoom')),
      search: box(scope.querySelector('.map-search-results')), inspector: box(scope.querySelector('aside[aria-label="Task details"]')),
      window: { width: innerWidth, height: innerHeight } };
  });
  const hit = (a, b) => !!a && !!b && a.x < b.right - .5 && b.x < a.right - .5 && a.y < b.bottom - .5 && b.y < a.bottom - .5;
  const label = `${theme} ${name}`;
  const record = { screen: label, ...boxes, intersections: [] };
  if (!boxes.canvas) problem(`${label}: no visible task canvas`);
  if (!boxes.cards.length) problem(`${label}: no task card visible in the canvas`);
  for (const card of boxes.cards) {
    for (const [overlay, failing] of [['minimap', true], ['search', true], ['legend', false], ['zoom', false]]) {
      if (!hit(card.box, boxes[overlay])) continue;
      record.intersections.push(`#${card.id} x ${overlay}`);
      if (failing) problem(`${label}: card #${card.id} intersects the ${overlay} overlay`);
      else facts.overlapNotes.push(`${label}: card #${card.id} intersects the ${overlay} (not a failing criterion)`);
    }
  }
  if (search) {
    if (!boxes.search) problem(`${label}: 'Search results' panel not visible`);
    else if (hit(boxes.search, boxes.canvas)) problem(`${label}: 'Search results' panel intersects the task canvas`);
  }
  if (inspector === 'right' && !(boxes.inspector && boxes.canvas && boxes.inspector.x >= boxes.canvas.right - 1))
    problem(`${label}: Task details is not a right-side inspector (U2): ${JSON.stringify({ inspector: boxes.inspector, canvas: boxes.canvas })}`);
  if (inspector === 'bottom' && !(boxes.inspector && boxes.canvas && boxes.inspector.y >= boxes.canvas.bottom - 1))
    problem(`${label}: Task details is not the bottom shelf below 1100 px (U2): ${JSON.stringify({ inspector: boxes.inspector, canvas: boxes.canvas })}`);
  facts.overlaps.push(record);
  note(`${label}: ${boxes.cards.length} cards visible; intersections ${record.intersections.join(', ') || 'none'}`);
}
/** U2/V4/V11 structure facts read from the DOM (names and roles the adoption scripts rely on). */
async function structure() {
  return page.evaluate(() => {
    const scope = document.querySelector('.monitor-page:not(.concealed)');
    const sidebar = document.querySelector('#d-project-sidebar');
    const order = [...sidebar.children].map(node => node.getAttribute('aria-label')
      || node.querySelector('.d-sidebar-group-toggle')?.textContent.trim() || node.tagName.toLowerCase());
    const group = scope.querySelector('[role="group"][aria-label="Monitor view"]');
    return { sidebarOrder: order,
      viewSwitch: group ? [...group.querySelectorAll('button')].map(button => `${button.textContent}:${button.getAttribute('aria-pressed')}`) : null,
      projectSubtitles: [...sidebar.querySelectorAll('.project-button')].map(button => ({ title: button.title, subtitle: button.querySelector('small')?.textContent })),
      detailWidth: !!scope.querySelector('input[type="range"][aria-label="Detail width"]'),
      canvasHeading: scope.querySelector('.d-map-workspace h1')?.className ?? null,
      mapCaption: !!scope.querySelector('.map-caption'),
      legend: [...scope.querySelectorAll('.native-relation-legend > span')].map(node => `${node.textContent}:${node.querySelector('svg') ? 'svg' : 'text'}`),
      cardTopRows: [...scope.querySelectorAll('[aria-label="Native task canvas"] .native-task-card .native-task-top')].map(node => node.textContent) };
  });
}
// Computed colours of visible elements against a token resolved through a probe in .desktop-d (as rgb()).
// Any mismatch is a problem; in dark, pure white is a problem too (third-party light defaults).
async function colours(name, checks) {
  const result = await page.evaluate(checks => {
    const root = document.querySelector('.desktop-d');
    const probe = document.createElement('span');
    root.append(probe);
    const rgb = token => { probe.style.color = `var(${token})`; return getComputedStyle(probe).color; };
    const rows = checks.map(([selector, prop, token]) => {
      const element = [...document.querySelectorAll(selector)].find(node => node.getClientRects().length);
      return { selector, prop, token, expected: rgb(token), actual: element ? getComputedStyle(element)[prop] : null };
    });
    probe.remove();
    return rows;
  }, checks);
  facts.themes[theme].colours ??= {};
  facts.themes[theme].colours[name] = result;
  for (const row of result) {
    if (row.actual === null) problem(`${theme} ${name}: no visible ${row.selector}`);
    else if (row.actual !== row.expected) problem(`${theme} ${name}: ${row.selector} ${row.prop} ${row.actual} != ${row.token} ${row.expected}`);
    if (theme === 'dark' && row.actual === 'rgb(255, 255, 255)') problem(`dark ${name}: ${row.selector} ${row.prop} is white`);
  }
}
const tokens = ['--bg', '--surface', '--ink', '--edge-dep', '--edge-repl', '--edge-accept', '--accent-ui'];
async function machine() {
  return page.evaluate(({ theme, tokens }) => {
    const root = document.querySelector('.desktop-d');
    const style = getComputedStyle(root);
    const token = Object.fromEntries(tokens.map(name => [name, style.getPropertyValue(name).trim()]));
    const edgeStrokes = [...new Set([...document.querySelectorAll('.monitor-page:not([hidden]) .x6-edge path[stroke]')]
      .map(node => node.getAttribute('stroke')).filter(value => value && value !== 'none' && value !== 'transparent'))];
    const frame = document.querySelector('.monitor-page:not([hidden]) [data-cell-id="project-frame"] rect');
    return { theme, darkMatches: matchMedia('(prefers-color-scheme: dark)').matches, token,
      background: style.backgroundColor, edgeStrokes, projectFrameFill: frame?.getAttribute('fill') ?? null,
      cardStatusChips: [...document.querySelectorAll('.native-task-card .native-task-meta .status')].map(node => node.className + ' :: ' + node.textContent),
      cardMeta: [...document.querySelectorAll('.native-task-card .native-task-meta')].map(node => node.textContent) };
  }, { theme, tokens });
}

try {
  // ---- disposable fixture: several statuses, two agents with activity and usage, default team configuration ----
  stage = 'fixture';
  const fixtures = require(path.join(desktop, 'tests', 'fixtures.cjs'));
  const project = path.join(out, 'fixture', 'ui-fixture');
  await fs.mkdir(path.dirname(project), { recursive: true });
  await fixtures.makeProject(project, 'ui-fixture');
  const now = new Date();
  const message = (role, text) => ({ timestamp: now.toISOString(), type: 'response_item', payload: {
    type: 'message', role, content: [{ type: role === 'user' ? 'input_text' : 'output_text', text }] } });
  const count = (input, cache, output) => ({ timestamp: now.toISOString(), type: 'event_msg', payload: { type: 'token_count', info: {
    last_token_usage: { input_tokens: input, cached_input_tokens: cache, output_tokens: output, reasoning_output_tokens: 20 },
    total_token_usage: { input_tokens: input, output_tokens: output } } } });
  const records = who => [
    { type: 'turn_context', payload: { model: 'gpt-5.3-codex' } },
    message('user', `Controlled fixture request for ${who}. No model execution.`),
    message('assistant', `## Plan\nControlled retained **${who}** message.\n\n- read the task\n- report back\n\n\`inline code\` sample.`),
    { timestamp: now.toISOString(), type: 'response_item', payload: { type: 'function_call', name: 'shell', call_id: `call-${who}`,
      arguments: JSON.stringify({ command: ['ls', '-la'] }) } },
    { timestamp: now.toISOString(), type: 'response_item', payload: { type: 'function_call_output', call_id: `call-${who}`,
      output: 'total 8\nseed.txt' } },
    count(12000, 8000, 640),
    message('assistant', `Controlled retained ${who} summary. `.repeat(12)),
    count(3000, 1000, 240),
  ];
  await fixtures.recordActivity(project, { taskId: '1', taskName: 'ui-fixture', alias: 'engineer@x1', records: records('engineer'),
    additionalMembers: [{ alias: 'leader@x2', historical: false, records: records('leader') }] });
  const definition = fixtures.operate(project, 'task_graph', { view: 'full' }).tasks.find(task => task.task_id === '2').current_definition;
  fixtures.operate(project, 'task_revise', { product_preserving: true, caused_by_event_ids: [], evidence_refs: ['evidence.md'], tasks: [
    { ...fixtures.task('2', 'dependent', ['1']), disposition: 'superseded', replaced_by: ['3'], retirement_reason: 'Replaced by successor.',
      current_definition: definition },
    { ...fixtures.task('3', 'successor', ['1']), current_definition: null },
    { ...fixtures.task('4', 'follow-up', ['3']), current_definition: null },
    // Task 627: a summary (#5) with a child (#6) whose members fill the Members tree table (V7); the tree's default
    // scope is "current summaries and their child tasks".
    { ...fixtures.task('5', 'review-summary'), current_definition: null },
    { ...fixtures.task('6', 'review-work'), parent_id: '5', current_definition: null },
  ] });
  await fixtures.recordActivity(project, { taskId: '6', taskName: 'review-work', alias: 'reviewer-old@x3', records: records('reviewer-old'),
    additionalMembers: [{ alias: 'reviewer@x4', historical: false, records: records('reviewer') }] });
  facts.fixtureTasks = fixtures.operate(project, 'task_graph', { view: 'full' }).tasks
    .map(task => ({ id: task.task_id, status: task.status, disposition: task.disposition, parent: task.parent_id ?? null }));
  note(`fixture project ${project}: ${JSON.stringify(facts.fixtureTasks)}`);
  if (!facts.fixtureTasks.some(task => task.id === '6' && task.parent === '5')) throw new Error('fixture summary #5 with child #6 was not registered');
  // A configured team (root + children), written only into the disposable project as tests/d-adoption.mjs does,
  // so Teams & roles renders its organization tree instead of the "No teams configured" empty state.
  stage = 'fixture team';
  await fs.writeFile(path.join(project, '.graphtraj', 'roles.yml'), `roles:
  delivery:
    lead: {runtime: codex, model: gpt-5.3-codex}
    engineer: {runtime: codex, model: gpt-5.3-codex, reports: [report.md]}
    reviewer: {runtime: codex, model: gpt-5.3-codex}
role_tree:
  delivery.lead:
    delivery.engineer: {}
    delivery.reviewer: {}
`);
  // Read it back through the built app's own native settings reader (no Save, no review), with this step's HOME.
  const { SettingsClient } = require(path.join(desktop, 'dist-electron', 'settings.js'));
  const settings = new SettingsClient();
  try {
    const read = await withTimeout(settings.request(project), 30000, 'native settings read');
    facts.fixtureTeam = { roles: Object.keys(read.roles ?? {}), edges: read.edges ?? [] };
  } finally { settings.close(); }
  note(`fixture team config (native read): ${JSON.stringify(facts.fixtureTeam)}`);
  if (!facts.fixtureTeam.roles.includes('delivery.lead')
    || !facts.fixtureTeam.edges.some(edge => edge.includes('delivery.lead')
      && edge.some(end => end !== 'delivery.lead' && end.startsWith('delivery.'))))
    throw new Error('fixture team (root delivery.lead with a child) is not visible through the native settings reader');
  if (fixtureOnly) { stage = 'done'; throw Object.assign(new Error('fixture-only'), { fixtureOnly: true }); }

  // ---- launch the built app ----
  stage = 'launch';
  const { _electron: electron } = require('playwright');
  facts.executable = require('electron');
  // colorScheme: null = Playwright "no-override". Its default ('light') sends CDP Emulation.setEmulatedMedia
  // prefers-color-scheme=light, which would mask nativeTheme.themeSource (host run at 43ea0bf5).
  const launching = electron.launch({ executablePath: facts.executable, colorScheme: null,
    args: [desktop, `--project=${project}`, `--user-data-dir=${path.join(out, 'profile')}`], env: process.env, timeout: 60000 });
  // Stop waiting as soon as an unhandled launch error was seen, else after 75 s.
  const failed = new Promise((_, reject) => { const poll = setInterval(() => {
    if (unhandled) { clearInterval(poll); reject(unhandled); } }, 200); launching.finally(() => clearInterval(poll)).catch(() => {}); });
  // A launch that completes after we gave up is closed at once, never left open.
  let gaveUp = false;
  launching.then(late => { if (gaveUp) return late.close().catch(() => late.process().kill('SIGKILL')); }).catch(() => {});
  try { app = await withTimeout(Promise.race([launching, failed]), 75000, 'electron.launch'); }
  catch (error) { gaveUp = true; throw error; }
  page = await app.firstWindow();
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => facts.pageErrors.push(String(error)));
  await resize(1440, 900);
  await page.locator('.native-task-card[data-task-id="1"] .native-task-title').waitFor();
  note('app window open with the fixture project');

  for (theme of ['light', 'dark']) {
    stage = `${theme}: force theme`;
    facts.themes[theme] = { screens: {} };
    // Force only through Electron's nativeTheme; no page.emulateMedia fallback. If the renderer does not follow,
    // fail and record both sides so the mismatch is attributable.
    const native = () => app.evaluate(({ nativeTheme }) => ({ themeSource: nativeTheme.themeSource, shouldUseDarkColors: nativeTheme.shouldUseDarkColors }));
    await app.evaluate(({ nativeTheme }, value) => { nativeTheme.themeSource = value; }, theme);
    facts.themes[theme].nativeTheme = await native();
    try {
      await page.waitForFunction(dark => matchMedia('(prefers-color-scheme: dark)').matches === dark, theme === 'dark', { timeout: 15000 });
    } catch {
      const darkMatches = await page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches);
      facts.themes[theme].themeMismatch = { ...(await native()), darkMatches };
      throw new Error(`nativeTheme.themeSource=${theme} did not reach the renderer: ${JSON.stringify(facts.themes[theme].themeMismatch)}`);
    }
    facts.themes[theme].nativeThemeAfter = await native();
    // Unselected first: with #1 selected its related dependency edges are drawn in --accent-ui (by design),
    // so the plain --edge-dep stroke is only observable without a selection.
    stage = `${theme}: task graph unselected`;
    await toGraph();
    await closeDetails();
    await monitor().getByRole('button', { name: 'Fit graph', exact: true }).click();
    await page.waitForTimeout(600);
    facts.themes[theme].machineUnselected = await machine();
    // 626 leftovers: the Electron window background follows the theme; HeroUI shadows resolve to our --shadow-*.
    facts.themes[theme].windowBackground = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getBackgroundColor());
    facts.themes[theme].shadows = await page.evaluate(() => {
      const style = getComputedStyle(document.querySelector('.desktop-d'));
      return Object.fromEntries(['--surface-shadow', '--overlay-shadow', '--field-shadow', '--shadow-sm', '--shadow-md']
        .map(name => [name, style.getPropertyValue(name).trim()]));
    });
    await colours('minimap', [['.native-minimap .x6-widget-minimap', 'backgroundColor', '--surface'],
      ['.native-minimap .x6-widget-minimap-viewport', 'borderTopColor', '--accent-ui']]);
    await layout('task-graph-unselected');
    stage = `${theme}: task graph`;
    await selectTaskOne();
    facts.themes[theme].machine = await machine();
    facts.themes[theme].structure = await structure();
    await layout('task-graph', { inspector: 'right' });
    await shot('task-graph');
    stage = `${theme}: search`;
    // 621 interim 23: with a query the 'Search results' panel and the zoomed-in top-left cards are both visible.
    await closeDetails();
    const search = monitor().getByRole('searchbox', { name: 'Search tasks', exact: true });
    await search.fill('fixture');
    await search.press('Enter');
    for (let index = 0; index < 2; index++) await monitor().getByRole('button', { name: 'Zoom in', exact: true }).click();
    await page.waitForTimeout(600);
    await layout('search', { search: true });
    await shot('search');
    // Selecting through the panel (as adoption.mjs:931 does) opens Task details for that task.
    await monitor().getByLabel('Search results', { exact: true }).getByRole('button', { name: '#1 ui fixture', exact: true }).click();
    await page.getByRole('complementary', { name: 'Task details' }).getByText('#1', { exact: true }).waitFor();
    await search.fill('');
    await closeDetails();
    stage = `${theme}: members`;
    await monitor().getByRole('group', { name: 'Monitor view' }).getByRole('button', { name: 'Members', exact: true }).click();
    const members = page.getByRole('region', { name: 'Agent members', exact: true });
    // V7 rows carry the full alias in data-alias (the visible name may be shortened).
    await members.locator('tr[data-alias="reviewer@x4"]').waitFor();
    await shot('members');
    stage = `${theme}: expanded chat`;
    await selectTaskOne();
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    const reader = page.getByRole('region', { name: 'Expanded agent conversations', exact: true });
    await reader.locator('.agent-column').first().waitFor();
    // A tool call, a usage line and the historical member's column (engineer@x1 is retained history).
    await reader.locator('details.tool-card').first().waitFor();
    await reader.locator('.usage-supplement').first().waitFor();
    await reader.getByRole('article', { name: 'engineer@x1', exact: true }).waitFor();
    await shot('chat');
    await page.getByRole('button', { name: 'Collapse chat', exact: true }).click();
    stage = `${theme}: teams and roles`;
    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await page.getByRole('region', { name: 'Team organization tree' }).waitFor().catch(error => {
      throw new Error(`Teams & roles did not render the "Team organization tree" region (fixture team ${JSON.stringify(facts.fixtureTeam)}): ${error.message.split('\n')[0]}`);
    });
    await colours('org tree', [['.d-team-flow .d-org-node:not(.selected)', 'backgroundColor', '--surface'],
      ['.d-team-flow .d-org-node:not(.selected)', 'color', '--ink'],
      ['.d-team-flow .react-flow__controls-button', 'backgroundColor', '--surface']]);
    // A selected agent shows its properties (V8); the other org cards stay unselected for the colour check above.
    await page.locator('.d-team-flow .react-flow__node').first().click();
    await page.getByLabel('Agent name', { exact: true }).filter({ visible: true }).waitFor();
    await page.waitForTimeout(400);
    await shot('teams-roles');
    stage = `${theme}: agents and models`;
    const settings = page.getByRole('button', { name: 'Settings', exact: true });
    if (await settings.getAttribute('aria-expanded') !== 'true') await settings.click();
    await page.getByRole('button', { name: 'Agents & models', exact: true }).click();
    await page.getByRole('heading', { name: 'Agents & models', exact: true }).waitFor();
    await shot('agents-models');
    stage = `${theme}: project usage`;
    await page.getByRole('button', { name: 'Project usage', exact: true }).click();
    await page.locator('.usage-dashboard:visible').first().waitFor();
    // The fixture's token counts are dated today, inside the default range: the records table has rows (V9).
    await page.locator('.d-dated-records tbody tr').filter({ visible: true }).first().waitFor();
    await shot('project-usage');
    stage = `${theme}: narrow task graph (1000x760)`;
    await resize(1000, 760);
    await toGraph();
    await closeDetails();
    await monitor().getByRole('button', { name: 'Fit graph', exact: true }).click();
    await page.waitForTimeout(600);
    await layout('narrow-task-graph');
    await shot('narrow-task-graph');
    stage = `${theme}: narrow task graph selected (1000x760)`;
    await selectTaskOne();
    await layout('narrow-task-graph-selected', { inspector: 'bottom' });
    await shot('narrow-task-graph-selected');
    await resize(1440, 900);
  }
  theme = null;
  stage = 'machine checks';
  // 626 leftovers and Task 627 structure.
  const expectWindow = { light: '#f6f7f9', dark: '#14171c' };
  for (const name of ['light', 'dark']) {
    const facts627 = facts.themes[name];
    const missing = SCREENS.filter(screen => !facts627.screens[screen]);
    if (missing.length) problem(`${name}: missing screens ${missing.join(', ')}`);
    if (!String(facts627.windowBackground).toLowerCase().startsWith(expectWindow[name]))
      problem(`${name}: Electron window backgroundColor ${facts627.windowBackground} != ${expectWindow[name]}`);
    const shadow = facts627.shadows;
    if (shadow['--surface-shadow'] !== shadow['--shadow-sm'] || shadow['--overlay-shadow'] !== shadow['--shadow-md'])
      problem(`${name}: HeroUI shadows do not resolve to --shadow-*: ${JSON.stringify(shadow)}`);
    const layoutFacts = facts627.structure;
    const order = layoutFacts.sidebarOrder.join(' > ');
    if (order !== 'header > Current project > PROJECTS > GLOBAL > footer') problem(`${name}: sidebar order is ${order} (U1)`);
    if (!layoutFacts.detailWidth) problem(`${name}: no 'Detail width' slider (U2)`);
    if (JSON.stringify(layoutFacts.viewSwitch) !== JSON.stringify(['Task graph:true', 'Members:false', 'Main sessions:false']))
      problem(`${name}: view switch ${JSON.stringify(layoutFacts.viewSwitch)} (V4)`);
    if (layoutFacts.mapCaption) problem(`${name}: .map-caption still present (V5)`);
    if (!layoutFacts.legend.some(item => item === 'Crossing:svg') || layoutFacts.legend.some(item => item.endsWith(':text')))
      problem(`${name}: legend is not one set of SVG line types incl. Crossing: ${JSON.stringify(layoutFacts.legend)} (V5)`);
  }
  if (JSON.stringify(facts.themes.light.windowBackground) === JSON.stringify(facts.themes.dark.windowBackground))
    problem('Electron window backgroundColor is the same in both themes');
  const expectBg = { light: '#f6f7f9', dark: '#14171c' };
  for (const name of ['light', 'dark']) {
    const plain = facts.themes[name].machineUnselected, chosen = facts.themes[name].machine;
    for (const [label, m, withAccent] of [['unselected', plain, false], ['#1 selected', chosen, true]]) {
      if (m.darkMatches !== (name === 'dark')) problem(`${name} ${label}: prefers-color-scheme dark=${m.darkMatches}`);
      if (m.token['--bg'] !== expectBg[name]) problem(`${name} ${label}: --bg is ${m.token['--bg']}, expected ${expectBg[name]}`);
      const allowed = [m.token['--edge-dep'], m.token['--edge-repl'], m.token['--edge-accept'], ...(withAccent ? [m.token['--accent-ui']] : [])];
      if (!m.edgeStrokes.length) problem(`${name} ${label}: no X6 edge stroke found`);
      for (const stroke of m.edgeStrokes) if (!allowed.includes(stroke)) problem(`${name} ${label}: X6 edge stroke ${stroke} is not one of this theme's edge tokens ${allowed.join(' ')}`);
      if (m.projectFrameFill !== m.token['--surface']) problem(`${name} ${label}: X6 project frame fill ${m.projectFrameFill} != --surface ${m.token['--surface']}`);
    }
    if (!plain.edgeStrokes.includes(plain.token['--edge-dep'])) problem(`${name} unselected: no plain dependency edge in --edge-dep ${plain.token['--edge-dep']} (strokes ${plain.edgeStrokes.join(' ')})`);
  }
  const lightPlain = facts.themes.light.machineUnselected, darkPlain = facts.themes.dark.machineUnselected;
  if (lightPlain.token['--edge-dep'] === darkPlain.token['--edge-dep']
    || lightPlain.edgeStrokes.some(stroke => darkPlain.edgeStrokes.includes(stroke))) problem('X6 edge strokes do not differ between themes');
  if (lightPlain.projectFrameFill === darkPlain.projectFrameFill) problem('X6 project frame fill is the same in both themes');
  stage = 'done';
} catch (error) {
  if (error?.fixtureOnly) note('fixture-only: fixture built and read back; Electron not started');
  else {
  problem(`stage "${stage}" failed: ${error?.message ?? error}`);
  facts.failure = { stage, theme, message: String(error?.message ?? error), stack: String(error?.stack ?? '') };
  if (page && !page.isClosed()) {
    const file = path.join(out, `${theme ?? 'app'}-failure.png`);
    await withTimeout(page.screenshot({ path: file }), 10000, 'failure screenshot')
      .then(() => { facts.failure.screenshot = file; note(`failure screenshot: ${file}`); })
      .catch(shotError => note(`failure screenshot not taken: ${shotError.message}`));
  }
  }
} finally {
  if (facts.pageErrors.length) problem(`page errors: ${facts.pageErrors.length}`);
  if (app) {
    await withTimeout(app.close(), 10000, 'app.close').then(() => note('app closed'))
      .catch(closeError => {
        note(`app.close failed (${closeError.message}); killing the Electron process`);
        try { app.process().kill('SIGKILL'); note('Electron process killed'); } catch (killError) { problem(`could not kill Electron: ${killError.message}`); }
      });
  }
  facts.verdict = facts.problems.length ? 'FAIL' : 'PASS';
  facts.finished = new Date().toISOString();
  await fs.mkdir(out, { recursive: true });
  await fs.writeFile(path.join(out, 'facts.json'), JSON.stringify(facts, null, 2) + '\n');
  console.log(`DRIVER ${facts.verdict} problems=${facts.problems.length} facts=${path.join(out, 'facts.json')}`);
  // Exit now: the app is closed or killed, and no pending Playwright handle may keep the step waiting.
  process.exit(facts.problems.length ? 1 : 0);
}
