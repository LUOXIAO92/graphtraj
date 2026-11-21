// Task 545: read a DSH_HOME's session logs (session[.vN].jsonl[.zstd]) for the sessions of one workspace and say,
// per user/message, in which turn and step it entered the model:
//   node sessions545.mjs <DSH_HOME> <workspace cwd> [<since ms> <until ms>]
// With since/until (epoch ms), only sessions whose directory was created in that window count (545 c1: G and GI
// share one project, so each case keeps only the session its own run created).
// DSH appends user/message inside step() after step/start (dsh-agent-loop: turn/start -> step/start -> the claimed
// messages). So an agent-message relay in step 1 opened (triggered) its turn; one in step > 1 was claimed by a later
// step of a turn that was already running (538's in-turn case, rendered as a 'context' node with no notice block).
// Read only. Prints one JSON object per session, then a one-line verdict per relay.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { zstdDecompressSync } from 'node:zlib';

const [home, cwd, since = '0', until = 'Infinity'] = process.argv.slice(2);
const born = (f) => statSync(join(f, '..')).birthtimeMs;
const files = [];
const walk = (d, depth) => {
  if (depth > 8) return;
  let entries = [];
  try { entries = readdirSync(d, { withFileTypes: true }); } catch { return; }
  for (const e of entries) {
    const p = join(d, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules' && e.name !== 'profiles') walk(p, depth + 1); }
    else if (/^session(\.v\d+)?\.jsonl(\.zstd)?$/.test(e.name)) files.push(p);
  }
};
walk(home, 0);
// 545 c1: DSH appends one zstd frame per write (G in B: 18 frames); zstdDecompressSync returns only the first
// frame (the header line). Split on the frame magic 28 B5 2F FD and decompress each frame; a magic that falls
// inside compressed data makes that slice fail, so it is joined with the next slice and tried again.
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const frames = (buf) => {
  const starts = [];
  for (let i = buf.indexOf(MAGIC); i >= 0; i = buf.indexOf(MAGIC, i + 1)) starts.push(i);
  if (starts[0] !== 0) throw new Error('not a zstd stream');
  const out = [];
  let from = 0;
  for (let k = 1; k <= starts.length; k++) {
    const to = k < starts.length ? starts[k] : buf.length;
    try { out.push(zstdDecompressSync(buf.subarray(from, to))); from = to; }
    catch (e) { if (to === buf.length) throw e; }
  }
  return Buffer.concat(out);
};
const lines = (p) => {
  let buf = readFileSync(p);
  if (p.endsWith('.zstd')) buf = frames(buf);
  return buf.toString('utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
};
const text = (m) => JSON.stringify(m?.content ?? m ?? '').slice(0, 100);
let shown = 0;
for (const f of files.sort((a, b) => statSync(a).mtimeMs - statSync(b).mtimeMs)) {
  if (born(f) < Number(since) || born(f) > Number(until)) continue;
  let ev;
  try { ev = lines(f); } catch (e) { console.log(JSON.stringify({ file: f, error: e.message })); continue; }
  if (!JSON.stringify(ev[0] ?? {}).includes(cwd)) continue;   // header names the session's cwd
  const out = { file: f.slice(home.length), subagent: f.includes('/subagents/'), turns: 0, messages: [] };
  let turn = 0; let step = 0;
  for (const e of ev.slice(1)) {
    const type = e.type ?? e.t; const data = e.data ?? e.d ?? {};
    if (type === 'turn/start') { turn = data.turn ?? turn + 1; step = 0; out.turns++; }
    else if (type === 'step/start') step = data.step ?? step + 1;
    else if (type === 'user/message') {
      const src = data.source ?? {};
      out.messages.push({ turn, step, kind: src.kind ?? '?', form: src.form, sender: src.senderAgentId,
        id: src.communicationId, entered: step <= 1 ? 'opened its turn' : 'inside a running turn', text: text(data) });
    }
  }
  if (!out.turns) { console.log(`skipped ${out.file}: ${ev.length} event(s), no turn (header-only session)`); continue; }
  console.log(JSON.stringify(out));
  if (out.subagent) continue;
  shown++;
  const users = out.messages.filter((m) => m.kind === 'user').length;
  console.log(`session ${out.file}: turns ${out.turns}, user inputs ${users}`);
  const relays = out.messages.filter((m) => m.kind === 'agent-message');
  const ids = relays.map((m) => m.id);
  for (const m of relays) console.log(`  relay ${m.id} from ${m.sender}: turn ${m.turn} step ${m.step} -> ${m.entered}`);
  const dup = ids.filter((x, i) => ids.indexOf(x) !== i);
  console.log(`  relays ${relays.length}, opened a turn ${relays.filter((m) => m.step <= 1).length}, inside a running turn ${relays.filter((m) => m.step > 1).length}, duplicate ids ${JSON.stringify(dup)}`);
}
if (!shown) console.log(`no Main session for ${cwd} under ${home} (session files seen: ${files.length})`);
