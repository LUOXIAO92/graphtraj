// Task 626 step S driver: light/dark screenshots of the built desktop app over a disposable fixture.
// argv: <desktop dir (built export)> <out dir>. Run only through steps.zsh S (allowlisted env, isolated HOME).
// The theme is forced inside the app (Electron nativeTheme.themeSource); the system appearance is never touched.
// No Save is pressed and no native picker is opened: the project is passed with --project.
// Any failure is recorded in facts.json (with the stage it happened in); facts.json is always written and the
// app is always closed (then killed if it does not close), so no window is left open.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const [desktop, out] = process.argv.slice(2);
const require = createRequire(path.join(desktop, 'package.json'));
const facts = { desktop, out, started: new Date().toISOString(), steps: [], themes: {}, pageErrors: [], problems: [] };
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
async function selectTaskOne() {
  await page.getByRole('button', { name: 'Monitor', exact: true }).click();
  await page.locator('.native-task-card[data-task-id="1"] .native-task-title').click();
  await page.getByRole('complementary', { name: 'Task details' }).waitFor();
  await page.waitForTimeout(800);
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
  ] });
  facts.fixtureTasks = fixtures.operate(project, 'task_graph', { view: 'full' }).tasks
    .map(task => ({ id: task.task_id, status: task.status, disposition: task.disposition }));
  note(`fixture project ${project}: ${JSON.stringify(facts.fixtureTasks)}`);
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
    stage = `${theme}: task graph`;
    await selectTaskOne();
    facts.themes[theme].machine = await machine();
    await shot('task-graph');
    stage = `${theme}: expanded chat`;
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    await page.locator('.agent-columns .agent-column, .agent-columns article').first().waitFor();
    await shot('chat');
    await page.getByRole('button', { name: 'Collapse chat', exact: true }).click();
    stage = `${theme}: teams and roles`;
    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await page.getByRole('region', { name: 'Team organization tree' }).waitFor().catch(error => {
      throw new Error(`Teams & roles did not render the "Team organization tree" region (fixture team ${JSON.stringify(facts.fixtureTeam)}): ${error.message.split('\n')[0]}`);
    });
    await shot('teams-roles');
    stage = `${theme}: project usage`;
    await page.getByRole('button', { name: 'Project usage', exact: true }).click();
    await page.locator('.usage-dashboard').first().waitFor();
    await shot('project-usage');
    stage = `${theme}: narrow task graph (1000x760)`;
    await resize(1000, 760);
    await selectTaskOne();
    await shot('narrow-task-graph');
    await resize(1440, 900);
  }
  theme = null;
  stage = 'machine checks';
  const light = facts.themes.light.machine, dark = facts.themes.dark.machine;
  const expectBg = { light: '#f6f7f9', dark: '#14171c' };
  for (const m of [light, dark]) {
    if (m.darkMatches !== (m.theme === 'dark')) problem(`${m.theme}: prefers-color-scheme dark=${m.darkMatches}`);
    if (m.token['--bg'] !== expectBg[m.theme]) problem(`${m.theme}: --bg is ${m.token['--bg']}, expected ${expectBg[m.theme]}`);
    const allowed = [m.token['--edge-dep'], m.token['--edge-repl'], m.token['--edge-accept'], m.token['--accent-ui']];
    if (!m.edgeStrokes.length) problem(`${m.theme}: no X6 edge stroke found`);
    for (const stroke of m.edgeStrokes) if (!allowed.includes(stroke)) problem(`${m.theme}: X6 edge stroke ${stroke} is not an edge/accent token value`);
    if (m.projectFrameFill !== m.token['--surface']) problem(`${m.theme}: X6 project frame fill ${m.projectFrameFill} != --surface ${m.token['--surface']}`);
  }
  if (light.token['--edge-dep'] === dark.token['--edge-dep'] || !light.edgeStrokes.includes(light.token['--edge-dep'])
    || !dark.edgeStrokes.includes(dark.token['--edge-dep'])) problem('X6 dependency edge colour does not follow the theme');
  if (light.projectFrameFill === dark.projectFrameFill) problem('X6 project frame fill is the same in both themes');
  stage = 'done';
} catch (error) {
  problem(`stage "${stage}" failed: ${error?.message ?? error}`);
  facts.failure = { stage, theme, message: String(error?.message ?? error), stack: String(error?.stack ?? '') };
  if (page && !page.isClosed()) {
    const file = path.join(out, `${theme ?? 'app'}-failure.png`);
    await withTimeout(page.screenshot({ path: file }), 10000, 'failure screenshot')
      .then(() => { facts.failure.screenshot = file; note(`failure screenshot: ${file}`); })
      .catch(shotError => note(`failure screenshot not taken: ${shotError.message}`));
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
