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
S V > $F/V.out 2>&1; check "V: written mod is 533's; USER command and prompt printed" sh -c "grep -q 'UserMessage render in the written mod: yes' $F/V.out && grep -q 'claude --allowedTools mcp__graphtraj__agents' $F/V.out && grep -q 'Task 533 display check' $F/V.out"
# Vr against synthetic transcripts: the new notice text passes, the old JSON body fails.
PY=$F/base/venv/bin/python
$PY -I - $F/projects/-x-vproject-533/new.jsonl new <<'PYEOF'
import json, sys
from graftling import notice_text
end = 'Session execution ended:\n' + json.dumps({'session': 's', 'execution_id': 'e1', 'outcome': 'completed', 'terminal_confirmed': True,
       'session_id': 's', 'permissions': {'requested': 'auto'}, 'last_agent_message': '## Reply from n533\n\n- one `agents`\n- two\n\n> quoted'})
old = '[Graftling notice from n533 · completed · execution e1]\n' + end
text = notice_text({'alias': 'n533', 'event': 'completed', 'execution': 'e1', 'message': end}) if sys.argv[2] == 'new' else old
rows = [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'mcp__graphtraj__agents', 'input': {'action': 'execute', 'feature': f}}]}} for f in ('create', 'send')]
rows.append({'type': 'user', 'message': {'role': 'user', 'content': text}, 'origin': {'kind': 'plugin'}})
open(sys.argv[1], 'w').write('\n'.join(json.dumps(r) for r in rows) + '\n')
PYEOF
S Vr > $F/Vr-new.out 2>&1; check "Vr on the new notice text: PASS" grep -q '^Vr533: PASS' $F/Vr-new.out
rm $F/projects/-x-vproject-533/new.jsonl
$PY -I - $F/projects/-x-vproject-533/old.jsonl old <<'PYEOF'
import json, sys
end = 'Session execution ended:\n' + json.dumps({'session': 's', 'execution_id': 'e1', 'permissions': {}, 'last_agent_message': '## x\n- y'})
rows = [{'type': 'user', 'message': {'role': 'user', 'content': '[Graftling notice from n533 · completed · execution e1]\n' + end}}]
open(sys.argv[1], 'w').write('\n'.join(json.dumps(r) for r in rows) + '\n')
PYEOF
S Vr > $F/Vr-old.out 2>&1; check "Vr on the old JSON notice: FAIL (the check can fail)" grep -q '^Vr533: FAIL' $F/Vr-old.out
# G's entry with real tests (GraphTraj tests using repository fixtures; graftling's new tests).
VERIFY533_TESTS="tests/test_claude_host_context.py tests/test_notice_delivery_372.py" \
VERIFY533_GLTESTS="tests/test_notice_text.py tests/test_claude_main_display.py" S G > $F/G.out 2>&1
S GR > $F/GR.out 2>&1
check "G: TMPDIR outside the Harness printed; both limited runs exit=0" sh -c "grep -q 'TMPDIR of the runs (outside the Harness)' $F/G.out && [ \$(grep -c '^exit=0' $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt | awk -F: '{s+=\$2} END {print s}') -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
