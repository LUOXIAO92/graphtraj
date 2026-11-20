// Task 538 (from 537's ui537.mjs at 6317b20d): drive a DSH web page with a headless browser and save screenshots +
// page text. Run by steps.zsh (node from /opt/homebrew/bin, playwright-core from $BASE/node/node_modules):
//   node ui538.mjs <json-config-file>
// Config: {url, workspace, prompt, out, browser, noticeMarker, sendMarker, failMarker, turnTimeoutS, noticeTimeoutS,
//          settleS, viewportHeight, playwright}
// 538 changes: a tall viewport (the conversation is virtualized; a tall page renders all of it, so full-page shots
// hold every row); agents Tool rows are expanded by their DSH root div[data-tool$="__agents"] until IN shows (537
// clicked header and inner span, toggling twice); a notice answered inside the first turn ends that turn (no
// misjudged wait); after the notice the driver waits for the page to stay idle (settleS) so later notices show;
// (a) = each agents send card, (b) = each incoming-notice block (graftling's section[data-agent-incoming] or DSH's
// section[data-turn-trigger]), expanded, as element shots and text; observables go to summary.json.
// Locale is en-US so DSH shows its English labels. Every wait is bounded; on a miss the driver saves a debug
// screenshot, the page text and the visible buttons, and continues to the end screenshots when that is still useful.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

const cfg = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const require = createRequire(join(cfg.playwright, 'package.json'));
const { chromium } = require('playwright-core');
mkdirSync(cfg.out, { recursive: true });
const t0 = Date.now();
const timings = [];
const notes = [];
let phaseStart = Date.now();
const sec = (ms) => Math.round(ms / 100) / 10;
const log = (s) => { const line = `[${sec(Date.now() - t0)}s] ${s}`; console.log(line); notes.push(line); };
const phase = (name, ok, extra = '') => {
  timings.push({ phase: name, seconds: sec(Date.now() - phaseStart), ok, extra });
  log(`phase ${name}: ${ok ? 'ok' : 'MISSED'} in ${sec(Date.now() - phaseStart)} s ${extra}`);
  phaseStart = Date.now();
};
const retries = {};
const bump = (k) => { retries[k] = (retries[k] ?? 0) + 1; };

const browser = await chromium.launch({
  executablePath: cfg.browser, headless: true,
  args: ['--disable-crash-reporter', '--disable-breakpad', '--no-first-run', '--no-default-browser-check',
    `--crash-dumps-dir=${process.env.TMPDIR}/crash`],
});
writeFileSync(join(cfg.out, 'browser.txt'), `${cfg.browser}\nversion ${browser.version()}\n`);
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1400, height: cfg.viewportHeight ?? 2600 }, deviceScaleFactor: 1 });
const page = await context.newPage();
page.setDefaultTimeout(15000);

async function dump(name) {
  try {
    await page.screenshot({ path: join(cfg.out, `${name}.png`), fullPage: true });
    writeFileSync(join(cfg.out, `${name}.txt`), await page.locator('body').innerText());
    const buttons = await page.evaluate(() => [...document.querySelectorAll('button,[role=button],[role=menuitem],[role=option],textarea,input,[contenteditable=true]')]
      .filter((e) => e.getClientRects().length)
      .map((e) => `${e.tagName.toLowerCase()} role=${e.getAttribute('role') ?? ''} aria-label=${e.getAttribute('aria-label') ?? ''} expanded=${e.getAttribute('aria-expanded') ?? ''} text=${(e.innerText ?? e.value ?? '').replace(/\s+/g, ' ').slice(0, 80)}`));
    writeFileSync(join(cfg.out, `${name}-controls.txt`), buttons.join('\n') + '\n');
  } catch (e) { log(`dump ${name} failed: ${e.message}`); }
}
async function firstVisible(locators, timeoutMs, key) {
  const end = Date.now() + timeoutMs;
  let round = 0;
  while (Date.now() < end) {
    for (const l of locators) {
      const n = await l.count().catch(() => 0);
      for (let i = 0; i < n; i++) {
        const c = l.nth(i);
        if (await c.isVisible().catch(() => false)) return c;
      }
    }
    if (round++ > 0) bump(key);
    await page.waitForTimeout(500);
  }
  return null;
}
async function approveIfAsked() {
  const b = await firstVisible([page.getByRole('button', { name: 'Allow once', exact: true }),
    page.getByRole('button', { name: 'Allow', exact: true })], 300, 'approve');
  if (b) { await b.click().catch(() => {}); log('approved a tool call in the page (Allow once/Allow)'); return 1; }
  return 0;
}
async function bodyText() { return page.locator('body').innerText().catch(() => ''); }
const PROMPT_HEAD = cfg.prompt.split('\n')[0].slice(0, 60);   // identifies the user's own message bubble
// A marker counts only as a leaf element whose whole text is the marker. The prompt spells markers as words (steps.zsh
// STOPs if it holds one literally), so the user's bubble never matches; prose quoting a marker is not a whole leaf.
async function markerLine(marker) {
  return page.evaluate((m) => [...document.querySelectorAll('body *')].some((e) => !e.children.length
    && !e.closest('nav, aside, form, [role=dialog]') && (e.innerText ?? '').trim() === m), marker).catch(() => false);
}
// First-run modals that DSH 0.2.2-alpha.2 can show in a plain web page before the composer. Each is body-portaled and
// sets #root inert (OnboardingModal / SignInDialog). Labels are the exact English strings from the installed source:
//   dsh-client-ui-settings-models  welcomeTitle 'Preview Notice'                  -> welcomeContinue 'Continue'
//                                  onboardingTitle 'Add an API key to get started' -> onboardingLater 'Configure later'
//   dsh-client-ui-settings-account loginTitle 'Get started' (sign-in dialog)       -> close 'Close' (aria-label)
// (The account package's desktop onboarding needs globalThis.dshDesktop, i.e. the desktop app, never a web page.)
const MODALS = [['Preview Notice', 'Continue'], ['Add an API key to get started', 'Configure later'], ['Get started', 'Close']];
async function blockingState() {
  return page.evaluate(() => {
    const root = document.getElementById('root');
    const vis = (e) => e.getClientRects().length > 0;
    const modals = [...document.querySelectorAll('[role=dialog], dialog[open], [aria-modal=true]')].filter((e) => vis(e) && !e.closest('[inert]'));
    return { inert: !!root?.inert, text: modals.map((e) => (e.innerText ?? '').replace(/\s+/g, ' ').slice(0, 120)) };
  }).catch(() => ({ inert: false, text: [] }));
}
async function dismissBlocking(settleMs) {
  // settleMs: how long to watch for a modal that renders a moment after the page (the notice loads its state first)
  const watchEnd = Date.now() + settleMs;
  let st = await blockingState();
  while (!st.inert && !st.text.length && Date.now() < watchEnd) { await page.waitForTimeout(500); st = await blockingState(); }
  for (let round = 0; round < 6 && (st.inert || st.text.length); round++) {
    // the dismiss button: exact label, visible, not inside an inert subtree (the greyed page behind the modal)
    const hit = await page.evaluate((known) => {
      for (const e of document.querySelectorAll('[data-ui538-dismiss]')) e.removeAttribute('data-ui538-dismiss');
      const body = document.body.innerText ?? '';
      for (const [title, label] of known) {
        if (!body.includes(title)) continue;
        for (const b of document.querySelectorAll('button')) {
          if (!b.getClientRects().length || b.closest('[inert]') || b.disabled) continue;
          const name = ((b.getAttribute('aria-label') || b.innerText) ?? '').trim();
          if (name === label) { b.setAttribute('data-ui538-dismiss', '1'); return [title, label]; }
        }
      }
      return null;
    }, MODALS);
    if (!hit) {
      await dump('debug-modal');
      throw new Error(`a blocking modal without a known dismiss button: ${JSON.stringify(st.text)} (root inert ${st.inert})`);
    }
    await page.locator('[data-ui538-dismiss="1"]').click({ timeout: 10000 });
    log(`dismissed the "${hit[0]}" modal with "${hit[1]}"`);
    reached.push(`dismissed:${hit[0]}`);
    // the next onboarding step, if any, renders right after; otherwise the page stops being inert
    await page.waitForFunction(() => !document.getElementById('root')?.inert, null, { timeout: 15000 }).catch(() => bump('inert-after-dismiss'));
    await page.waitForTimeout(800);
    st = await blockingState();
  }
  if (st.inert) { await dump('debug-modal'); throw new Error('the page stayed inert after dismissing the first-run modals'); }
}
const count = (s, re) => (s.match(new RegExp(re, 'g')) ?? []).length;
async function busy() {  // DSH shows a 'Stop generating' button while a turn runs
  return page.getByRole('button', { name: 'Stop generating' }).isVisible().catch(() => false);
}
async function expandAll(scopeName) {
  // Expand the tool group ('Called tools'/…) rows and the agents Tool cards: every collapsed control in the
  // conversation (not the sidebar, composer or dialogs), then any header that names an agents tool.
  let clicked = 0;
  for (let round = 0; round < 4; round++) {
    const handles = await page.evaluate(() => {
      const out = [];
      const skip = (e) => e.closest('nav, aside, form, [role=dialog], [role=menu], [data-queue-dock], [data-testid=todo-panel]');
      for (const e of document.querySelectorAll('[aria-expanded="false"]')) {
        if (!e.getClientRects().length || skip(e)) continue;
        const label = (e.getAttribute('aria-label') ?? '') + ' ' + (e.innerText ?? '');
        if (e.getAttribute('aria-haspopup')) continue;  // menus and pickers, not content
        if (/Choose workspace|View options|Group by|Order by|Filter/i.test(label)) continue;
        e.setAttribute('data-ui538-expand', String(out.length));
        out.push(label.replace(/\s+/g, ' ').slice(0, 80));
      }
      return out;
    });
    if (!handles.length) break;
    for (let i = 0; i < handles.length; i++) {
      await page.locator(`[data-ui538-expand="${i}"]`).first().click({ timeout: 3000 }).then(() => { clicked++; }).catch(() => {});
      await page.evaluate((k) => document.querySelector(`[data-ui538-expand="${k}"]`)?.removeAttribute('data-ui538-expand'), String(i));
    }
    await page.waitForTimeout(600);
  }
  // 538: agents Tool rows. DSH's ToolRow root is div[data-tool=<tool name>] holding a DisclosureRow that expands on a
  // row click (dsh-client-ui-tool lib/client.js ToolRow: "data-tool": toolName, expandOnRowClick: true). A row is
  // open when its text holds the IN label; each closed row gets one click on its own disclosure, re-checked after.
  const rows = await page.evaluate(() => {
    let k = 0;
    for (const e of document.querySelectorAll('[data-tool$="__agents"]')) e.setAttribute('data-ui538-tool', String(k++));
    return k;
  });
  let opened = 0;
  for (let i = 0; i < rows; i++) {
    const row = page.locator(`[data-ui538-tool="${i}"]`);
    for (let attempt = 0; attempt < 3; attempt++) {
      const text = await row.innerText().catch(() => '');
      if (/(^|\n)IN(\n|$)/.test(text)) { opened++; break; }
      const target = await row.evaluate((root, n) => {
        for (const e of root.querySelectorAll('[data-ui538-click]')) e.removeAttribute('data-ui538-click');
        const tries = [root.querySelector('[aria-expanded="false"]'), root.querySelector('button'),
          [...root.querySelectorAll('*')].find((e) => e.getClientRects().length && !e.children.length && /__agents/.test(e.textContent ?? ''))];
        const pick = tries.filter(Boolean)[Math.min(n, tries.filter(Boolean).length - 1)];
        if (!pick) return false;
        pick.setAttribute('data-ui538-click', '1');
        return true;
      }, attempt).catch(() => false);
      if (!target) break;
      await row.locator('[data-ui538-click="1"]').first().click({ timeout: 3000 }).then(() => { clicked++; }).catch(() => bump('tool-click'));
      await page.waitForTimeout(600);
    }
  }
  log(`${scopeName}: clicked ${clicked} collapsed control(s); agents Tool rows ${rows}, open with IN ${opened}`);
  return clicked;
}

let reached = [];
try {
  // 1. open the served page
  await page.goto(cfg.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const trigger = await firstVisible([page.getByRole('button', { name: 'Choose workspace' }), page.getByLabel('Choose workspace')], 60000, 'open');
  phase('open', !!trigger);
  if (!trigger) { await dump('debug-open'); throw new Error('the page did not show "Choose workspace"'); }
  reached.push('open');
  await dismissBlocking(4000);   // conditional: a later run on the same DSH_HOME may show no notice

  // 2. add the workspace through DSH's in-page browse dialog and select it (a rerun on the same DSH_HOME finds the
  //    workspace already listed and selects it instead; recorded as 'workspace-existing')
  const wsName = cfg.workspace.split('/').filter(Boolean).pop();
  // exact workspace name (other workspaces, e.g. 'dsh-ui-537' from step 0, are listed too and must not match)
  const wsRe = new RegExp(`^${wsName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\s|$)`);
  const triggerText = async () => (await page.getByRole('button', { name: 'Choose workspace' }).first().innerText().catch(() => '')).trim();
  // round 2: no 'New session' click before the workspace is chosen (S try showed the prompt leaving the new session);
  // order is now: choose/add workspace -> new session in it -> check the chip -> fill -> send -> confirm the bubble
  await trigger.click();
  const existing = await firstVisible([page.getByRole('menuitem', { name: wsRe }), page.getByRole('option', { name: wsRe })], 2000, 'existing');
  if (existing) { await existing.click(); reached.push('workspace-existing'); }
  let add = existing ? null : await firstVisible([page.getByRole('menuitem', { name: /Add workspace/ }), page.getByRole('option', { name: /Add workspace/ }),
    page.getByRole('button', { name: /Add workspace/ }), page.getByText(/Add workspace/)], 10000, 'add');
  if (!existing && !add) { await dump('debug-add'); throw new Error('no "Add workspace…" entry after "Choose workspace"'); }
  if (add) {
  await add.click();
  const dialog = page.getByRole('dialog', { name: /Select Workspace Directory/ });
  const dlg = await firstVisible([dialog, page.getByRole('dialog')], 15000, 'browse-dialog');
  if (!dlg) { await dump('debug-browse'); throw new Error('the in-page "Select Workspace Directory" dialog did not appear (native chooser?)'); }
  const edit = await firstVisible([dlg.getByRole('button', { name: 'Edit path' })], 10000, 'edit-path');
  if (edit) await edit.click();
  const input = await firstVisible([dlg.getByRole('textbox', { name: 'Edit path' }), dlg.locator('input')], 10000, 'path-input');
  if (!input) { await dump('debug-path'); throw new Error('no "Edit path" field in the browse dialog'); }
  await input.fill(cfg.workspace);
  await input.press('Enter');
  await page.waitForTimeout(1500);
  const open = await firstVisible([dlg.getByRole('button', { name: 'Open', exact: true })], 10000, 'open-button');
  if (!open) { await dump('debug-open-button'); throw new Error('no "Open" button in the browse dialog'); }
  await page.waitForFunction((b) => b && !b.disabled, await open.elementHandle(), { timeout: 15000 }).catch(() => bump('open-enabled'));
  await open.click();
  await dialog.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => bump('dialog-close'));
  }
  // DSH selects the added workspace: the composer's 'Choose workspace' trigger then shows its name as its text (the
  // accessible name stays 'Choose workspace'). If it shows another name, pick ours from the menu by exact name.
  let shownWs = '';
  const ensureWs = async () => {   // the chip shows our workspace, else pick it from the chip's menu by exact name
    for (let i = 0; i < 10 && (shownWs = await triggerText()) !== wsName; i++) await page.waitForTimeout(500);
    if (shownWs === wsName) return;
    bump('ws-reselect');
    const t2 = await firstVisible([page.getByRole('button', { name: 'Choose workspace' })], 5000, 'ws-trigger2');
    if (!t2) return;
    await t2.click();
    const item = await firstVisible([page.getByRole('menuitem', { name: wsRe }), page.getByRole('option', { name: wsRe })], 8000, 'ws-item');
    if (item) await item.click();
    for (let i = 0; i < 10 && (shownWs = await triggerText()) !== wsName; i++) await page.waitForTimeout(500);
  };
  await ensureWs();
  // then a new session IN that workspace: the sidebar's 'New session in <name>' (dsh-client-ui-workspace
  // actions.newSession.aria) when visible, else the global 'New session'; the chip is checked again afterwards
  const wsNew = await firstVisible([page.getByRole('button', { name: `New session in ${wsName}`, exact: true })], 1500, 'ws-new-session');
  if (wsNew) { await wsNew.click().catch(() => bump('ws-new-session-click')); log(`clicked "New session in ${wsName}"`); }
  else { await page.getByRole('button', { name: 'New session', exact: true }).first().click({ timeout: 3000 }).catch(() => {}); log('clicked "New session"'); }
  await page.waitForTimeout(800);
  await ensureWs();
  phase('workspace', shownWs === wsName, `(composer workspace "${shownWs}", expected "${wsName}" = ${cfg.workspace})`);
  if (shownWs !== wsName) { await dump('debug-workspace'); throw new Error(`the composer shows workspace "${shownWs}", not "${wsName}"`); }
  await page.screenshot({ path: join(cfg.out, '01-workspace.png') });
  reached.push('workspace');

  // 3. new conversation = the hero composer of the selected workspace; send the prompt
  const composer = await firstVisible([page.getByRole('textbox', { name: /Describe what you want|Message or run a task/ }),
    page.locator('textarea'), page.locator('[contenteditable=true]')], 15000, 'composer');
  if (!composer) { await dump('debug-composer'); throw new Error('no composer'); }
  await composer.click();
  await composer.fill(cfg.prompt);
  // round 2: 'sent' only when a user bubble starting with the prompt's first line is in the conversation (not the
  // composer); one retry (Send button, else Enter); otherwise STOP with debug-send.*
  const bubbleShown = () => page.evaluate((head) => [...document.querySelectorAll('body *')].some((e) =>
    !e.closest('nav, aside, form, textarea, [contenteditable=true], [role=dialog]') && e.getClientRects().length
    && (e.innerText ?? '').trim().startsWith(head)), PROMPT_HEAD).catch(() => false);
  const waitBubble = async (ms) => { const until = Date.now() + ms; while (Date.now() < until) { if (await bubbleShown()) return true; await page.waitForTimeout(500); } return false; };
  const clickSend = async (attempt) => {
    const send = await firstVisible([page.getByRole('button', { name: 'Send message', exact: true })], 5000, `send-${attempt}`);
    if (send && await send.isEnabled().catch(() => false)) await send.click().catch(() => composer.press('Enter'));
    else await composer.press('Enter');
  };
  await clickSend(1);
  let sent = await waitBubble(20000);
  if (!sent) {
    bump('send-retry'); log('no user bubble with the prompt within 20 s; retrying the send once');
    if (!(await composer.inputValue().catch(() => composer.innerText().catch(() => ''))).trim()) await composer.fill(cfg.prompt).catch(() => {});
    await clickSend(2);
    sent = await waitBubble(20000);
  }
  phase('send-prompt', sent, `(user bubble starting with "${PROMPT_HEAD.slice(0, 40)}…" ${sent ? 'shown' : 'NOT shown'}; composer workspace "${await triggerText()}")`);
  if (!sent) { await dump('debug-send'); throw new Error('the prompt did not appear as a user message in the conversation'); }
  reached.push('prompt-sent');

  // 4. first turn: approve when asked; it ends, with no turn running, on the send marker, the fail marker or (538)
  //    the notice marker: a notice that arrives before the turn ends is answered in that same turn (537 S), and
  //    that turn may never print the send marker.
  let approvals = 0;
  let end = Date.now() + cfg.turnTimeoutS * 1000;
  let doneTurn = false; let failed = false; let inTurnNotice = false;
  while (Date.now() < end) {
    approvals += await approveIfAsked();
    const b = await busy();
    // markers count only as a whole line of the model's text, outside the user's own message (537 c4)
    if (!b && await markerLine(cfg.failMarker)) { failed = true; break; }
    if (!b && await markerLine(cfg.sendMarker)) { doneTurn = true; break; }
    if (!b && await markerLine(cfg.noticeMarker)) { doneTurn = true; inTurnNotice = true; break; }
    await page.waitForTimeout(1000);
  }
  phase('first-turn', doneTurn, `(approvals ${approvals}; ${failed ? `the model ended with ${cfg.failMarker}: create or send failed` : inTurnNotice ? `the notice was answered inside the first turn (${cfg.noticeMarker} before any ${cfg.sendMarker} wait)` : `reply line ${cfg.sendMarker} ${doneTurn ? 'seen' : 'not seen'}`})`);
  await page.screenshot({ path: join(cfg.out, '02-first-turn.png'), fullPage: true });
  if (doneTurn) reached.push('first-turn');
  if (inTurnNotice) reached.push('notice-in-first-turn');
  if (failed) reached.push('model-reported-FAILED');

  // 5. the member's end notice: the notice marker reply the prompt asks for (bounded); none when the first turn
  //    failed. Then the page must stay idle for settleS seconds (a second notice, e.g. the send's end after the
  //    create's, starts another turn), bounded by noticeTimeoutS overall.
  const noticeEnd = doneTurn ? Date.now() + cfg.noticeTimeoutS * 1000 : 0;
  let notice = inTurnNotice;
  while (!notice && Date.now() < noticeEnd) {
    approvals += await approveIfAsked();
    if (!(await busy()) && await markerLine(cfg.noticeMarker)) { notice = true; break; }
    await page.waitForTimeout(1500);
  }
  let quiet = 0;
  const settleEnd = Math.min(noticeEnd, Date.now() + (cfg.settleS + 60) * 1000);
  while (notice && quiet < cfg.settleS && Date.now() < settleEnd) {
    approvals += await approveIfAsked();
    quiet = (await busy()) ? 0 : quiet + 1;
    await page.waitForTimeout(1000);
  }
  phase('notice', notice, `(marker ${cfg.noticeMarker} ${notice ? (inTurnNotice ? 'seen in the first turn' : 'seen') : doneTurn ? 'NOT seen within ' + cfg.noticeTimeoutS + ' s' : 'not awaited: the first turn failed or did not end'}; idle ${quiet} s after it)`);
  if (notice) reached.push('notice');
  writeFileSync(join(cfg.out, '03-before-expand.txt'), await bodyText());
  await page.screenshot({ path: join(cfg.out, '03-before-expand.png'), fullPage: true });

  // 6. expand every collapsed conversation control and the agents Tool rows, then the shots
  await expandAll('expand');
  await page.waitForTimeout(800);
  await expandAll('expand-again');   // rows rendered by the first expansion (e.g. inside 'Called tools')
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(cfg.out, '04-expanded-full.png'), fullPage: true });
  writeFileSync(join(cfg.out, '04-expanded-full.txt'), await bodyText());
  // (a) every agents Tool row (div[data-tool$="__agents"]); a-send-card = the first whose IN holds the send feature
  const tools = await page.evaluate(() => [...document.querySelectorAll('[data-tool$="__agents"]')].map((e, i) => {
    e.setAttribute('data-ui538-shot', `tool-${i}`);
    const t = e.innerText ?? '';
    return { i, tool: e.getAttribute('data-tool'), open: /(^|\n)IN(\n|$)/.test(t), send: /"feature":\s*"send"/.test(t), text: t };
  }));
  const observed = { tools: [], notices: [] };
  let sendShot = false;
  for (const x of tools) {
    const loc = page.locator(`[data-ui538-shot="tool-${x.i}"]`);
    const name = x.send && !sendShot ? 'a-send-card' : `a-tool-${x.i + 1}`;
    if (name === 'a-send-card') sendShot = true;
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.screenshot({ path: join(cfg.out, `${name}.png`) }).catch((e) => log(`${name} shot: ${e.message}`));
    writeFileSync(join(cfg.out, `${name}.txt`), x.text);
    observed.tools.push({ file: name, tool: x.tool, inShown: x.open, send: x.send,
      markdownInIn: x.send ? /## Report 538/.test(x.text) && /- first item/.test(x.text) : null });
  }
  if (sendShot) reached.push('send-card'); else log('no agents Tool row whose IN holds "feature": "send"; a-send-card not written (see 04-expanded-full.*)');
  // (b) each incoming-notice block: graftling-dsh's attribution section (it wraps DSH's trigger), else DSH's own
  //     trigger section; text + element shot each. b-notice.* = the first; none in S when the notice came in-turn.
  const blocks = await page.evaluate(() => {
    const all = [...document.querySelectorAll('section[data-agent-incoming], section[data-turn-trigger]')]
      .filter((e) => !e.parentElement?.closest('section[data-agent-incoming]'));
    return all.map((e, i) => { e.setAttribute('data-ui538-shot', `notice-${i}`); return { i, text: e.innerText ?? '', graftling: e.matches('[data-agent-incoming]') }; });
  });
  for (const x of blocks) {
    const name = x.i === 0 ? 'b-notice' : `b-notice-${x.i + 1}`;
    const loc = page.locator(`[data-ui538-shot="notice-${x.i}"]`);
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.screenshot({ path: join(cfg.out, `${name}.png`) }).catch((e) => log(`${name} shot: ${e.message}`));
    writeFileSync(join(cfg.out, `${name}.txt`), x.text);
    const lines = x.text.split('\n').map((l) => l.trim()).filter(Boolean);
    const repeated = lines.filter((l, k) => k > 0 && l === lines[k - 1] && l.length > 3);
    observed.notices.push({ file: name, graftlingSection: x.graftling, showsGraphtrajAsSender: /^graphtraj$/m.test(x.text),
      adjacentRepeatedLines: repeated, markdownSource: /(^|\n)(## |- |```)/.test(x.text) });
  }
  if (blocks.length) reached.push('notice-shot');
  else {
    // no block: the notice reached the model inside a running turn (S); shot = the region around the marker reply
    const box = await page.evaluate((m) => {
      let best = null;
      for (const e of document.querySelectorAll('body *')) {
        if (e.closest('nav, aside, form, [role=dialog]')) continue;
        const t = e.innerText ?? '';
        if (!t.includes(m) || e.getBoundingClientRect().width < 200) continue;
        if (!best || t.length < (best.innerText ?? '').length) best = e;
      }
      if (!best) return false;
      // 538 r1: up until the region also holds where the notice shows (the Think that mentions it), bounded
      let e = best;
      for (let i = 0; i < 12 && e.parentElement; i++) {
        if (/notice/i.test((e.innerText ?? '').replace(m, '')) || (e.parentElement.innerText ?? '').length > 20000) break;
        e = e.parentElement;
      }
      e.setAttribute('data-ui538-shot', 'notice-region');
      return true;
    }, cfg.noticeMarker);
    if (box) {
      const loc = page.locator('[data-ui538-shot="notice-region"]');
      await loc.screenshot({ path: join(cfg.out, 'b-notice-region.png') }).catch((e) => log(`notice region shot: ${e.message}`));
      writeFileSync(join(cfg.out, 'b-notice-region.txt'), await loc.innerText().catch(() => ''));
      reached.push('notice-region-shot');
    }
    log('no incoming-notice block (section[data-agent-incoming] / section[data-turn-trigger]) on the page');
  }
  // 538 r1: where a notice's text is in the DOM at all (S: a relay claimed inside a running turn is a DSH 'context'
  // node, ContextInjectionRow): every element whose own text starts with a notice title or a relay-sender line,
  // with whether it is rendered visibly; plus the relay/trigger markers DSH and graftling-dsh put on the page.
  observed.dom = await page.evaluate(() => {
    const hits = [];
    for (const e of document.querySelectorAll('body *')) {
      const own = [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim();
      if (!/^\[(Graftling|GraphTraj) notice from |^From session /.test(own)) continue;
      const box = e.getBoundingClientRect();
      hits.push({ tag: e.tagName.toLowerCase(), visible: !!e.getClientRects().length && box.height > 0,
        text: own.slice(0, 120), inThink: !!e.closest('[data-reasoning], [data-process]') });
    }
    return { hits, relaySender: document.querySelectorAll('[data-context-relay-sender]').length,
      turnTrigger: document.querySelectorAll('[data-turn-trigger]').length,
      agentIncoming: document.querySelectorAll('[data-agent-incoming]').length,
      contextText: document.querySelectorAll('[data-context-text]').length };
  }).catch((e) => ({ error: e.message }));
  writeFileSync(join(cfg.out, 'observed.json'), JSON.stringify(observed, null, 2));
  log(`observed: ${JSON.stringify({ tools: observed.tools.map((t) => [t.file, t.inShown, t.send]), notices: observed.notices.map((n) => [n.file, n.graftlingSection, n.showsGraphtrajAsSender, n.adjacentRepeatedLines.length]) })}`);
  phase('shots', true);
} catch (e) {
  log(`STOP: ${e.message}`);
  await dump('debug-stop');
} finally {
  writeFileSync(join(cfg.out, 'summary.json'), JSON.stringify({ reached, timings, retries, totalSeconds: sec(Date.now() - t0), notes }, null, 2));
  await browser.close().catch(() => {});
  log(`browser closed; reached: ${reached.join(', ')}`);
}
