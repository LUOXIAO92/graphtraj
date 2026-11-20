#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: fake Harness root, stub `claude` on PATH, real builds from the real
# candidate commits, real pytest through G's entry (limited test lists). Never touches production or ~/.claude.
#   zsh rehearse.zsh <empty or absent directory>
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
FH=$F/H; mkdir -p $FH/tmp $FH/graphtraj $FH/.graphtraj $F/stub $F/projects/-x-vproject-533 $F/w
export VERIFY533_H=$FH VERIFY533_BASE=$F/base VERIFY533_W=$F/w VERIFY533_VPROJECT=$FH/tmp/vproject-533 \
  VERIFY533_PROJECTS=$F/projects VERIFY533_RT=$REALH/.venv-runtime VERIFY533_WT=${SD:h:h}
export PATH=$F/stub:$PATH
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "2.1.325 (stub Claude Code)" ;;
  plugin) print "✔ Validation passed (stub)" ;;
  -p) in=$(cat); tag=$(print -r -- "$in" | sed -n 's/.*Line 1: \([A-Z0-9-]*\) followed.*/\1/p')
      print -r -- '{"type":"system","subtype":"init","plugins":[]}'
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
S() { zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
check() { local name=$1; shift; if "$@"; then print "REHEARSAL PASS $name"; ((pass++)); else print "REHEARSAL FAIL $name"; ((fail++)); fi; }
print "== rehearsal in $F (stub claude; real candidate commits)"
S 00 > $F/00.out 2>&1; check "00: version gate, isolation OK, answer check OK" sh -c "grep -q 'Claude Code >= 2.1.314: yes' $F/00.out && grep -q 'isolation: OK' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out"
tail -3 $F/00.out
S B > $F/B.out 2>&1; check "B: wheels + venv; candidate mod has ui.place and UserMessage; notice_text" sh -c "grep -q 'ui.place / UserMessage render: True True' $F/B.out && grep -q 'notice_text: True' $F/B.out && grep -q 'scratch venv pip check rc=0' $F/B.out"
grep -E 'candidates:|product diff|graftling f67|^graftling |^graphtraj ' $F/B.out
# V resolves the child role through ~/.graphtraj/connections.yml; the rehearsal gives V a HOME with a minimal catalog
# naming the same reference (the real one is the user's, unreadable here). The resolution itself runs for real.
mkdir -p $F/home/.graphtraj
cat > $F/home/.graphtraj/connections.yml <<'EOF'
version: 1
runtimes:
  claude:
    runtime: claude
    providers:
      anthropic:
        models:
          opus-5_5: {id: claude-opus-5-5, source: native}
EOF
HOME=$F/home S V > $F/V.out 2>&1; check "V: MCP enabled, child role resolves (no model launched), written mod is 533's, USER command and prompt printed" sh -c "grep -q 'CHECK 533 graphtraj MCP server enabled in project settings: PASS' $F/V.out && grep -q 'CHECK 533 child role resolves: PASS (runtime claude, model claude-opus-5-5' $F/V.out && grep -q 'UserMessage render in the written mod: yes' $F/V.out && grep -q 'claude --allowedTools mcp__graphtraj__agents' $F/V.out && grep -q 'Pass NO model' $F/V.out && ! grep -q haiku $F/V.out"
grep -E 'CHECK 533|roles file written' $F/V.out
# A broken connection reference STOPs V before the USER part.
sed -i '' 's/opus-5_5:/other-model:/' $F/home/.graphtraj/connections.yml
HOME=$F/home S V > $F/V-bad.out 2>&1; check "V with an unresolvable connection: STOP before the USER part" sh -c "grep -q 'CHECK 533 child role resolves: FAIL' $F/V-bad.out && grep -q 'STOP: the child role does not resolve' $F/V-bad.out && ! grep -q '粘贴下面整段提示' $F/V-bad.out"
# Vr on the REAL path: GraphTraj's queue_notice (as notify_direct_parent queues a Main notice) -> the candidate
# host's NativeCalls.notices claim (the push) -> the mod V wrote submits it (node, stubbed $) -> transcript record.
PY=$F/base/venv/bin/python
MOD=$FH/tmp/vproject-533/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs
$PY -I - $F/claim-root $F/claimed.json <<'PYEOF'
import json, sys
from pathlib import Path
from uuid import uuid4
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution.main_continuity import queue_notice
from graphtraj.runtimes.claude.host import NativeCalls
root = Path(sys.argv[1]); (root / '.graphtraj').mkdir(parents=True)
runner, session = runner_directory(root), str(uuid4())
end = {'session': 's', 'execution_id': 'e1', 'outcome': 'completed', 'terminal_confirmed': True, 'session_id': 's',
       'permissions': {'requested': 'auto'}, 'last_agent_message': '## Reply from n533\n\n- one `agents`\n- two\n\n> quoted'}
queue_notice(runner, {'runtime': 'claude', 'session': session}, {'source': 'graphtraj', 'alias': 'n533', 'event': 'completed',
             'message': 'Session execution ended:\n' + json.dumps(end), 'execution': 'e1'})
claimed = NativeCalls(lambda *a: None, root, runner).notices({'operation': 'notices', 'session': session})
Path(sys.argv[2]).write_text(json.dumps(claimed))
print('claimed through the candidate host:', [sorted(n) for n in claimed['notices']])
PYEOF
node --input-type=module -e '
import {readFileSync, writeFileSync} from "node:fs";
const [mod, claimedFile, out] = process.argv.slice(1);
const {register} = await import(mod);
const handlers = new Map();
register((name, matcher, fn) => { handlers.set(fn ? name + ":" + (matcher.tool ?? matcher.component) : name, fn ?? matcher); return {catch() {}}; });
const claimed = readFileSync(claimedFile, "utf8"), timers = [], submitted = [];
const $ = {session: {id: async () => "00000000-0000-4000-8000-000000000000", cwd: async () => "/p"}, command: {register: async () => {}},
  env: {get: async () => "/x"}, clock: {setTimeout: (fn) => timers.push(fn)}, prompt: {submit: async (v) => submitted.push(v.text)},
  process: {run: async (argv, o) => ({exitCode: 0, stderr: "", stdout: JSON.parse(o.stdin).operation === "notices" ? claimed : "{}"})},
  ui: {log: async () => {}}};
await handlers.get("session.start")($, {}, async () => {});
await timers[0]();
const rows = ["create", "send"].map((f) => ({type: "assistant", message: {content: [{type: "tool_use", name: "mcp__graphtraj__agents", input: {action: "execute", feature: f}}]}}));
rows.push({type: "user", message: {role: "user", content: submitted[0]}});
writeFileSync(out, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
console.log("mod submitted", submitted.length, "prompt(s)");
' $MOD $F/claimed.json $F/projects/-x-vproject-533/new.jsonl
S Vr > $F/Vr-new.out 2>&1; check "Vr on the notice from GraphTraj's real claim path and the written mod: PASS" grep -q '^Vr533: PASS' $F/Vr-new.out
rm $F/projects/-x-vproject-533/new.jsonl
$PY -I - $F/projects/-x-vproject-533/old.jsonl old <<'PYEOF'
import json, sys
end = 'Session execution ended:\n' + json.dumps({'session': 's', 'execution_id': 'e1', 'permissions': {}, 'last_agent_message': '## x\n- y'})
rows = [{'type': 'user', 'message': {'role': 'user', 'content': '[Graftling notice from n533 · completed · execution e1]\n' + end}}]
open(sys.argv[1], 'w').write('\n'.join(json.dumps(r) for r in rows) + '\n')
PYEOF
S Vr > $F/Vr-old.out 2>&1; check "Vr on the old JSON notice: FAIL (the check can fail)" grep -q '^Vr533: FAIL' $F/Vr-old.out
# G's entry with real tests (GraphTraj tests using repository fixtures; graftling's new tests).
VERIFY533_TESTS="tests/test_claude_host_context.py tests/test_notice_delivery_372.py tests/test_claude_main_notice_text_533.py" \
VERIFY533_GLTESTS="tests/test_notice_text.py tests/test_claude_main_display.py" S G > $F/G.out 2>&1
S GR > $F/GR.out 2>&1
check "G: TMPDIR outside the Harness printed; both limited runs exit=0" sh -c "grep -q 'TMPDIR of the runs (outside the Harness)' $F/G.out && [ \$(grep -c '^exit=0' $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt | awk -F: '{s+=\$2} END {print s}') -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
