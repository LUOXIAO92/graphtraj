#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: fake Harness root, stub `pi` on PATH for 00/V0/V1, real builds from
# the real commits, Vr on Session entries made from GraphTraj's real notice path, real pytest through G's entry
# (limited test lists, real `pi` and node). Never touches production, ~/.pi or dotfiles.
#   zsh rehearse.zsh <empty or absent directory>
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
FH=$F/H; mkdir -p $FH/tmp $FH/.graphtraj $F/stub $F/w
export VERIFY536_H=$FH VERIFY536_BASE=$F/base VERIFY536_W=$F/w VERIFY536_VPROJECT=$FH/tmp/vproject-536 \
  VERIFY536_RT=$REALH/.venv-runtime VERIFY536_WT=${SD:h:h} DEEPSEEK_API_KEY=rehearsal-key
cat > $F/stub/pi <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "1.4.0 (stub pi)" ;;
  --print) [[ -e ${0:A:h}/pi-fail ]] && { print "Error: no API key (stub)"; exit 1; }; print "READY-536 deepseek-flash" ;;
  *) print "stub pi: $*" ;;
esac
EOF
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "2.1.325 (stub Claude Code)" ;;
  -p) in=$(cat); tag=$(print -r -- "$in" | sed -n 's/.*Line 1: \([A-Z0-9-]*\) followed.*/\1/p')
      print -r -- '{"type":"system","subtype":"init","plugins":[]}'
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/pi $F/stub/claude
S() { zsh $SD/steps.zsh "$@"; }
SP() { PATH=$F/stub:$PATH zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
check() { local name=$1; shift; if "$@"; then print "REHEARSAL PASS $name"; ((pass++)); else print "REHEARSAL FAIL $name"; ((fail++)); fi; }
print "== rehearsal in $F (stub pi for 00/V0/V1; real commits)"
SP 00 > $F/00.out 2>&1; check "00: isolation OK, pi answer line, claude answer check, next command; no 'No such file'" sh -c "grep -q 'isolation: OK' $F/00.out && grep -q '^READY-536 deepseek-flash' $F/00.out && grep -q 'CHECK 536 Pi answer line (READY-536 + model): PASS' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out && grep -q 'steps.zsh B' $F/00.out && ! grep -q 'No such file' $F/00.out"
grep -E 'rc=|READY-536 |CHECK 536|answer check|isolation:' $F/00.out
# A Pi without an answer STOPs 00 before the Claude check and the next command (marker file: 00 runs pi under env -i).
touch $F/stub/pi-fail; SP 00 > $F/00-bad.out 2>&1; rm $F/stub/pi-fail; check "00 with no Pi answer: STOP, no next command" sh -c "grep -q 'STOP: no .READY-536 <model>. answer from pi' $F/00-bad.out && ! grep -q 'steps.zsh B' $F/00-bad.out && ! grep -q 'claude -p rc=' $F/00-bad.out"
grep -E 'pi --print rc=|STOP' $F/00-bad.out
S B > $F/B.out 2>&1; check "B: exact diff; baseline without, candidate with the notice renderer; pip check rc=0 twice" sh -c "grep -q 'CHECK 536 GraphTraj product diff is exactly the three 536 files: PASS' $F/B.out && grep -q 'baseline: notice renderer in the extension: 0' $F/B.out && grep -q 'candidate: notice renderer in the extension: [1-9]' $F/B.out && [ \$(grep -c 'venv pip check rc=0' $F/B.out) -eq 2 ]"
grep -E 'CHECK|^baseline:|^candidate:|graftling candidate' $F/B.out
# V resolves the child role through ~/.graphtraj/connections.yml; the rehearsal HOME has a minimal catalog naming the same reference.
mkdir -p $F/home/.graphtraj
cat > $F/home/.graphtraj/connections.yml <<'EOF'
version: 1
runtimes:
  claude:
    runtime: claude
    providers:
      anthropic:
        models:
          opus-5_5: {id: claude-opus-5-5, source: native, supported_efforts: [high, max]}
EOF
for v in V0 V1; do
  HOME=$F/home SP $v > $F/$v.out 2>&1
  check "$v: child role resolves (no model), USER pi command with --session-dir and --extension, prompt printed" sh -c "grep -q 'child role resolves: PASS (runtime claude, model claude-opus-5-5' $F/$v.out && grep -q -- '--session-dir $F/w/pi-$v --extension' $F/$v.out && grep -q 'Pass NO model' $F/$v.out"
  grep -E 'notice renderer in it|   cd ' $F/$v.out
done
# Vr: Session entries made from GraphTraj's real queue (queue_notice, as notify_direct_parent queues a member end)
# through each venv's real notices native entry (main_notices), mapped as each extension's deliverNotices maps it.
for v in V0:baseline V1:candidate; do
  tag=${v%%:*}; venv=${v##*:}
  $F/base/venv-$venv/bin/python -I - $F/claim-$tag $F/w/pi-$tag/session.jsonl <<'PYEOF'
import json, sys
from pathlib import Path
from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution.main_continuity import queue_notice
from graphtraj.runtimes.native_entry import main_notices
root = Path(sys.argv[1]); (root / '.graphtraj').mkdir(parents=True)
runner, connection = runner_directory(root), {'runtime': 'pi', 'session': 'pi-main'}
end = {'session': 's', 'execution_id': 'e1', 'outcome': 'completed', 'terminal_confirmed': True, 'session_id': 's',
       'permissions': {'requested': 'auto'}, 'last_agent_message': '## Reply from n536\n\n- one `agents`\n- two\n\n> quoted'}
queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'n536', 'event': 'completed',
             'message': 'Session execution ended:\n' + json.dumps(end), 'execution': 'e1'})
pending = main_notices({'event': 'notices'}, runner, connection)
messages = ([{'content': item['text'], 'details': {**{k: item[k] for k in ('sender', 'event', 'body')}, 'source': 'graphtraj'}}
             for item in pending['items']] if 'items' in pending else [{'content': pending['text']}])
rows = [{'type': 'custom_message', 'customType': 'graphtraj:main-notice', 'display': True, **message} for message in messages]
Path(sys.argv[2]).write_text(''.join(json.dumps(row) + '\n' for row in rows))
print(sys.argv[2], 'notice rows:', len(rows))
PYEOF
done
S Vr > $F/Vr.out 2>&1
check "Vr: V0 (BASELINE) FAIL, V1 (CANDIDATE) PASS" sh -c "[ \"\$(grep '^Vr536:' $F/Vr.out | tr '\n' ' ')\" = 'Vr536: FAIL Vr536: PASS ' ]"
grep -E 'PASS|FAIL|notice \[|Session file' $F/Vr.out
# G's entry with real tests: GraphTraj tests using repository fixtures and the real pi/node; graftling's new and changed tests.
VERIFY536_TESTS="tests/test_pi_main_notice_display_536.py tests/test_pi_dsh_main_continuity.py tests/test_claude_main_notice_text_533.py" \
VERIFY536_GLTESTS="tests/test_pi_notice_display_536.py tests/test_notice_text.py" S G > $F/G.out 2>&1
S GR > $F/GR.out 2>&1
check "G: TMPDIR outside the Harness printed; both limited runs exit=0" sh -c "grep -q 'TMPDIR of the runs (outside the Harness)' $F/G.out && [ \$(grep -c '^exit=0' $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt | awk -F: '{s+=\$2} END {print s}') -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
