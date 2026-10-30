#!/bin/zsh
# Task 383: re-evaluate a retained run of real-host script A with no model calls.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host/scripts/realhost-383/recheck-a.sh
# Script A's step 4 runs it the same way with the run directory as argument.
#
# Reads $P/evidence and the DSH Session logs in $P/dsh-home, read only. DSH
# writes those logs zstd-compressed (*.jsonl.zstd) by default; Node's built-in
# zlib decodes them (Python cannot). Writes only the new directory $P/recheck.
# Starts no DSH, Claude or agents process. No native review dialog.
#
# Checks (PASS/FAIL each): the public create result (runtime, model, parent,
# creator); the child's answers PONG-1/PONG-2 (step 2) and PONG-3 (step 3) from
# the wait results or, for an end the host pushed, from its relay message;
# each pushed end relayed exactly once into the DSH Session as a native
# user/message with communicationId agents-notice:<execution>:completed; the
# step-3 status result (same native Session, standby, creator unchanged).
setopt err_exit pipe_fail no_unset

P=${1:-/Users/luoxiao/agents-383-realhost/a}
CHILD_MODEL=claude-sonnet-5-5
EVIDENCE=$P/evidence
R=$P/recheck

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

[[ -f $EVIDENCE/step2-agents.jsonl && -f $EVIDENCE/step3-agents.jsonl && -f $EVIDENCE/step2.txt ]] \
  || fail "$EVIDENCE does not hold a script A run (step2-agents.jsonl, step3-agents.jsonl, step2.txt)"
[[ -d $P/dsh-home ]] || fail "$P/dsh-home is missing"
[[ -e $R ]] && fail "$R exists from an earlier recheck; move it away (for example: mv $R $R.old) and run again"
mkdir $R
PYTHON=$P/venv/bin/python
[[ -x $PYTHON ]] || PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
NODE=$(command -v node) || fail "node is not on PATH"
print -r -- "run: $P; writing only $R"
print -r -- "node: $NODE $($NODE --version); python: $PYTHON (-I -B, no bytecode written)"

say "step 1 record: how the agents-dsh bundle was loaded (step1-plugin-add.txt, verbatim)"
cat $EVIDENCE/step1-plugin-add.txt 2>/dev/null || print -r -- "(no step1-plugin-add.txt)"

# Decode every native Session log (plain or zstd) and keep each agents notice
# relay message with its exact file, line, event type and sequence number.
cat > $R/relay.mjs <<'EOF'
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import zlib from 'node:zlib';

const [root, output] = process.argv.slice(2);
const zstd = typeof zlib.zstdDecompressSync === 'function';
console.log(`node ${process.version}: zlib zstd ${zstd ? 'available' : 'UNAVAILABLE'}`);
const files = [];
const visit = directory => {
  for (const name of readdirSync(directory).sort()) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) visit(path);
    else if (name.endsWith('.jsonl') || name.endsWith('.jsonl.zstd')) files.push(path);
  }
};
visit(root);

/**
 * Decode every zstd frame of one appended log. zstdDecompressSync stops after
 * the first frame, so continue from the bytes it consumed; skippable frames
 * (magic 0x184D2A50-5F) are passed over by their declared size.
 */
function decodeZstd(raw) {
  const parts = [];
  let offset = 0;
  while (offset < raw.length) {
    const rest = raw.subarray(offset);
    if (rest.length >= 8 && (rest.readUInt32LE(0) & 0xfffffff0) === 0x184d2a50) {
      offset += 8 + rest.readUInt32LE(4);
      continue;
    }
    const { buffer, engine } = zlib.zstdDecompressSync(rest, { info: true });
    if (!engine.bytesWritten) throw new Error(`no progress at byte ${offset}`);
    parts.push(buffer);
    offset += engine.bytesWritten;
  }
  return Buffer.concat(parts).toString('utf8');
}

/** Yield each object carrying an agents notice relay source, with its event's type and seq. */
function* relays(value, event = {}) {
  if (Array.isArray(value)) { for (const item of value) yield* relays(item, event); return; }
  if (!value || typeof value !== 'object') return;
  const here = { type: typeof value.type === 'string' && value.type.includes('/') ? value.type : event.type,
                 seq: value.seq ?? event.seq };
  const id = value.source?.communicationId;
  if (typeof id === 'string' && id.startsWith('agents-notice:')) {
    yield { ...here, communicationId: id, kind: value.source.kind,
            text: (value.content || []).map(part => part?.text || '').join('') };
    return;
  }
  for (const item of Object.values(value)) yield* relays(item, here);
}

const found = [];
for (const path of files) {
  let text;
  try {
    const raw = readFileSync(path);
    text = path.endsWith('.zstd') ? (zstd ? decodeZstd(raw) : null)
                                  : raw.toString('utf8');
  } catch (error) {
    console.log(`DECODE FAILED ${path}: ${error.message}`);
    continue;
  }
  if (text === null) { console.log(`NOT DECODED (no zstd in this Node) ${path}`); continue; }
  const lines = text.split('\n');
  console.log(`decoded ${path}: ${lines.filter(Boolean).length} lines`);
  lines.forEach((line, index) => {
    let record;
    try { record = JSON.parse(line); } catch { return; }
    for (const relay of relays(record)) found.push({ log: path, line: index + 1, ...relay });
  });
}
writeFileSync(output, found.map(item => JSON.stringify(item)).join('\n') + (found.length ? '\n' : ''));
for (const item of found) {
  console.log(`relay ${item.log}:${item.line} ${item.type} seq=${item.seq} ${item.communicationId} ` +
              JSON.stringify(item.text.slice(0, 160)));
}
console.log(`relay messages found: ${found.length}`);
EOF

say "decode the native DSH Session logs (read only)"
$NODE $R/relay.mjs $P/dsh-home $R/relay-messages.jsonl

SID=$(sed -n 's/^SESSION=//p' $EVIDENCE/step2.txt | tail -1)
AGENT=$($PYTHON -I -B -c 'import json,sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d["action"] == "create" and d.get("agent"): print(d["agent"]); break' $EVIDENCE/step2-agents.jsonl)
print -r -- "DSH parent Session (step2.txt): ${SID:-none}; child (public create result): ${AGENT:-none}"

say "checks: public agents results and the native relay"
$PYTHON -I -B - $EVIDENCE/step2-agents.jsonl $EVIDENCE/step3-agents.jsonl $R/relay-messages.jsonl \
    $CHILD_MODEL "$SID" "$AGENT" <<'EOF' | tee $R/checks.txt
import json, sys
read = lambda path: [json.loads(line) for line in open(path) if line.strip()]
two, three, relays = read(sys.argv[1]), read(sys.argv[2]), read(sys.argv[3])
model, session, agent = sys.argv[4:7]
mine = lambda documents, action: [d for d in documents if d['action'] == action and d.get('agent') == agent
                                  and 'error' not in d]
create = (mine(two, 'create') or [{}])[0].get('result') or {}
status = (mine(three, 'status') or [{}])[-1].get('result') or {}
waits2 = [d['result'] for d in mine(two, 'wait')]
waits3 = [d['result'] for d in mine(three, 'wait')]
# Only the native user/message entering the Session counts as the delivery.
messages = {}
for relay in relays:
    if relay.get('type') == 'user/message':
        messages.setdefault(relay['communicationId'], []).append(relay)
last = lambda wait: wait.get('last_result') or {}
relay_id = lambda wait: f"agents-notice:{last(wait).get('id')}:completed"
def answer(wait):
    """The wait result's body, else the body of that end's relay message."""
    return last(wait).get('last_message') or ''.join(m['text'] for m in messages.get(relay_id(wait), []))
said2, said3 = ' | '.join(map(answer, waits2)), ' | '.join(map(answer, waits3))
pushed = [w for w in waits2 + waits3 if last(w).get('notification') == 'delivered']
native = {w.get('session') for w in waits2 + waits3 if w.get('session')}
checks = [
    ('create result: runtime == claude (a non-DSH child of the DSH host)', create.get('runtime') == 'claude'),
    (f'create result: model == {model} (chosen at create)', create.get('model') == model),
    ('create result: parent == null and creator.session == the DSH parent Session',
     create.get('parent') is None and (create.get('creator') or {}).get('session') == session),
    ('step 2 answers (wait results or relays): PONG-1 then PONG-2 (round trip)',
     'PONG-1' in said2 and 'PONG-2' in said2 and said2.index('PONG-1') < said2.index('PONG-2')),
    ('each pushed end (notification delivered) is one native user/message agents-notice:<execution>:completed',
     bool(pushed) and all(len(messages.get(relay_id(w), [])) == 1 for w in pushed)),
    ('step 3 answer (wait result or relay): PONG-3 (child resumed)', 'PONG-3' in said3),
    ('step 3 status result: same native Claude Session as the waits, standby, creator.session unchanged',
     len(native) == 1 and status.get('session') in native and status.get('state') == 'standby'
     and (status.get('creator') or {}).get('session') == session),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print()
for step, waits in (('step 2', waits2), ('step 3', waits3)):
    for wait in waits:
        rows = messages.get(relay_id(wait), [])
        print(f"{step} wait: execution {last(wait).get('id')} outcome {last(wait).get('outcome')} "
              f"notification {last(wait).get('notification')} body {json.dumps(last(wait).get('last_message'))}")
        for row in rows:
            print(f"  relayed at {row['log']}:{row['line']} seq={row['seq']}: {json.dumps(row['text'], ensure_ascii=False)}")
other = sorted({r['communicationId'] + ' (' + str(r.get('type')) + ')' for r in relays if r.get('type') != 'user/message'})
print('relay copies outside user/message (not counted):', json.dumps(other))
print('answers step 2:', json.dumps(said2, ensure_ascii=False))
print('answers step 3:', json.dumps(said3, ensure_ascii=False))
print('create:', json.dumps({k: create.get(k) for k in ('runtime', 'model', 'parent', 'creator', 'state')}))
print('status:', json.dumps({k: status.get(k) for k in ('runtime', 'model', 'state', 'session', 'parent', 'creator')}))
EOF

say "recheck written to $R (relay.mjs, relay-messages.jsonl, checks.txt); send that path back to Main"
