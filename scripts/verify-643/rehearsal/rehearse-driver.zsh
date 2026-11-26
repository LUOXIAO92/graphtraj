#!/bin/zsh
# Task 643 rehearsal (Engineer) of the VM-side driver vm/drive643.py on macOS (POSIX branches; the Win32 facts read
# NOT-WINDOWS):
#   - the rollout parser on the REAL Task 640 rollouts (every exec_command -> -1073741502);
#   - graftling cloned from a bundle of <Harness>/graftling dev, the candidate checked out (as provision.ps1 does);
#   - R0 with a fake `codex`; case A with a fake `codex exec` giving TOOL-RAN, TOOL-FAILED -1073741502 (a rollout shaped
#     like 640's real one) and NO-TOOL-CALL, and no key (STOP);
#   - case C-ssh through graftling with graftling's stand-in Codex peer (tests/codex_stdio_peer.py): its tool writes
#     the marker (TOOL-RAN); a tool that does nothing with an injected 640-like rollout (TOOL-FAILED -1073741502); an
#     injected rollout without a call (NO-TOOL-CALL);
#   - schedule B (off Windows the task body runs as a plain subprocess): the done-file wait and the printed console;
#     schedule with no console session (STOP); the session parser on sample `query user` output; verdict;
#   - scan: the key, and the autologon password, planted in the evidence fail the scan without printing it.
# Settings values, the key and the password are RANDOM per run. Consoles: rehearsal/<round>/drv-NN-*.txt.
emulate -L zsh
setopt pipe_fail no_unset
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
OUT=$HERE/rehearsal/${1:-c1}
mkdir -p $OUT
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
PY=$HARNESS/.venv-runtime/bin/python   # has PyYAML and websockets (graftling's runtime needs); graftling from PYTHONPATH
CANDIDATE=2ee706eb749355afc3f73f03a1b0de4cd48da1f2
REAL640=$HARNESS/.graphtraj/core/state/tasks/640-graftling-windows-codex-real/realhost/evidence-live
TAG=$(openssl rand -hex 4)
H=$(mktemp -d $TMPDIR/v643drv.XXXXXX)
mkdir -p $H/bin $H/codex-home
KEYENV=K${(U)TAG}_API_KEY
KEYVAL=sk-dummy-$TAG-$(openssl rand -hex 16)
PASSWD=Pw-$(openssl rand -hex 12)
MODEL=model-$TAG-flash PROV=prov$TAG URL=https://api.h$TAG.invalid/v7/
git -C $HARNESS/graftling bundle create -q $H/graftling.bundle refs/heads/dev
git clone -q --template= --no-checkout $H/graftling.bundle $H/graftling && git -C $H/graftling checkout -q --detach $CANDIDATE
$PY -I -c 'import json, sys
t, model, prov, url, keyenv, cand = sys.argv[2:8]
pairs = [["<PROJECT>", f"p-{t}-proj"], ["<ZONE>", f"z{t}-east9-q"], ["<VM_NAME>", f"vm-{t}-x"], ["<MACHINE_TYPE>", f"mt-{t}-std2"],
         ["<PROVIDER_ID>", prov], ["<PROVIDER_NAME>", f"Prov{t} Name"], ["<BASE_URL>", url], ["<BASE_URL>", url.rstrip("/")],
         ["<BASE_URL_HOST>", url.split("/")[2]], ["<MODEL>", model], ["<KEY_ENV>", keyenv]]
json.dump({"provider": {"id": prov, "name": f"Prov{t} Name", "base_url": url, "wire_api": "responses", "model": model, "key_env": keyenv},
           "codex_version": "0.172.0", "candidate": cand, "scrub": pairs}, open(sys.argv[1], "w"))' \
  $H/settings.json $TAG $MODEL $PROV $URL $KEYENV $CANDIDATE
# A fake codex: --version; exec (R0's one-line answer, or a case by FAKE_CODEX_CASE = ran | failed | nocall); sandbox.
# Rollout records follow the shape of Task 640's REAL Codex 0.172 rollouts (function_call exec_command with
# arguments {"cmd": ...}; function_call_output "Chunk ID ...\nProcess exited with code N\n...").
cat > $H/bin/codex <<PYEOF
#!$PY -I
import json, os, sys, time, tomllib, pathlib
argv = sys.argv[1:]
if argv[:1] == ['--version']:
    print('codex-cli 0.172.0 (stand-in)'); sys.exit(0)
if argv[:1] == ['sandbox']:
    if argv[1:2] == ['--help']:
        print('Run commands within a Codex-provided sandbox\n\nCommands:\n  macos\n  linux\n  windows  (stand-in)'); sys.exit(0)
    if argv[1:3] == ['windows', '--help']:
        print('Usage: codex sandbox windows [OPTIONS] [COMMAND]...\n  --full-auto (stand-in)'); sys.exit(0)
    print('stand-in: no Windows sandbox on this machine', file=sys.stderr); sys.exit(1)
home = pathlib.Path(os.environ['CODEX_HOME'])
config = tomllib.loads((home / 'config.toml').read_text())
day = home / 'sessions' / '2026' / '11' / '27'; day.mkdir(parents=True, exist_ok=True)
thread = f'01a2{time.time_ns() % 10**12:012d}'
work = pathlib.Path(argv[argv.index('-C') + 1])
case = os.environ.get('FAKE_CODEX_CASE', 'answer')
records = [{'type': 'session_meta', 'payload': {'id': thread, 'model_provider': config['model_provider']}},
           {'type': 'turn_context', 'payload': {'model': config['model'], 'cwd': str(work)}}]
call = {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command',
        'arguments': json.dumps({'cmd': 'Set-Content -Path marker-643.txt -Value tool-ran', 'yield_time_ms': 10000}), 'call_id': 'call_00_x'}}
if case == 'ran':
    (work / 'marker-643.txt').write_text('tool-ran\n')
    records += [call, {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'call_00_x',
                'output': 'Chunk ID: a1\nWall time: 0.4 seconds\nProcess exited with code 0\nOriginal token count: 0\nOutput:\n'}}]
elif case == 'failed':
    records += [call, {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'call_00_x',
                'output': 'Chunk ID: a0e20a\nWall time: 0.0001 seconds\nProcess exited with code -1073741502\nOriginal token count: 0\nOutput:\n'}}]
records.append({'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'CASE-DONE' if case != 'answer' else 'PONG643'}]}})
(day / f'rollout-2026-11-27T00-00-00-{thread}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
for event in ({'type': 'thread.started', 'thread_id': thread},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'CASE-DONE' if case != 'answer' else 'PONG643'}},
              {'type': 'turn.completed'}):
    print(json.dumps(event))
PYEOF
chmod +x $H/bin/codex
# Injected rollouts for the graftling stand-in peer: 640-like failure, and no call.
mkdir -p $H/fake-rollouts
print -r -- '{"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\": \"Set-Content -Path marker-643.txt -Value tool-ran\"}", "call_id": "c1"}}
{"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "Chunk ID: f80e91\nWall time: 0.0001 seconds\nProcess exited with code -1073741502\nOriginal token count: 0\nOutput:\n"}}' > $H/fake-rollouts/rollout-failed.jsonl
print -r -- '{"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "CASE-DONE"}]}}' > $H/fake-rollouts/rollout-no-call.jsonl
# Sample query user outputs (the user name is the current one, as on the VM; never printed by the driver).
ME=${USER}
print -r -- " USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
>$ME                 console             1  Active      none   11/27/2026 1:00 AM" > $H/quser-active.txt
print -r -- " USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
 $ME                                      2  Disc        none   11/27/2026 1:00 AM" > $H/quser-disc.txt
BASEENV=(HOME=$HOME USER=$ME PATH=$H/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$TMPDIR LANG=en_US.UTF-8
         PYTHONPATH=$H/graftling/src V643_HOME=$H CODEX_HOME=$H/codex-home PYTHONDONTWRITEBYTECODE=1)
N=0
typeset -a SUMMARY CHECK
LAST=
drv() {  # drv <name> <expect-regex> <extra env...> -- <driver args...>
  local name=$1 expect=$2; shift 2
  local -a extra=()
  while [[ $1 != -- ]]; do extra+=$1; shift; done; shift
  (( N++ ))
  local file=$OUT/drv-$(printf %02d $N)-$name.txt
  print -r -- "\$ <venv python> scripts/verify-643/vm/drive643.py $*   (env names: ${(j: :)${${${extra%%=*}/$KEYENV/<KEY_ENV>}}})" > $file
  /usr/bin/env -i $BASEENV $extra $PY $HERE/vm/drive643.py "$@" >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^(RESULT |SCAN |SCRUB |SESSION (ACTIVE|NONE)|VERDICT-OF )' $file | tail -1) ok=no
  [[ $got =~ $expect ]] && ok=yes
  SUMMARY+="drv-$(printf %02d $N) $name: expected /$expect/, got '${got:-none}' -> $ok"
  LAST=$file
}
rm -f $OUT/drv-[0-9][0-9]-*.txt(N)
# The parser on the real 640 rollouts.
(( N++ ))
PF=$OUT/drv-$(printf %02d $N)-parser-real-640-rollouts.txt
print -r -- "\$ python3 -I rehearsal/check_parser643.py vm ../verify-640/vm <640 realhost evidence-live>/R-unelevated/rollouts <...>/R-unelevated-prev-*/rollouts" > $PF
/usr/bin/env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 $PY -I $HERE/rehearsal/check_parser643.py $HERE/vm $WT/scripts/verify-640/vm \
  $REAL640/R-unelevated/rollouts $REAL640/R-unelevated-prev-*/rollouts(N) >> $PF 2>&1
print -r -- "(exit $?)" >> $PF
SUMMARY+="drv-$(printf %02d $N) parser-real-640-rollouts: expected /PARSER PASS/, got '$(grep '^PARSER' $PF)' -> $(grep -q '^PARSER PASS' $PF && print yes || print no)"
drv r0-no-key 'RESULT R0 STOP' -- r0
drv r0-pass 'RESULT R0 PASS' $KEYENV=$KEYVAL -- r0
drv A-no-key 'RESULT A STOP the key variable is not set' -- case A
drv A-tool-ran 'RESULT A TOOL-RAN' $KEYENV=$KEYVAL FAKE_CODEX_CASE=ran -- case A
CHECK+="A TOOL-RAN: marker line $(grep -c "^CASE A marker file: present, content 'tool-ran'" $LAST), call line with exit 0 $(grep -c '^CASE A call 1: exec_command .* -> exit 0' $LAST), rollout kept $(ls $H/out/A/rollouts | grep -c rollout-), sandbox runner OBSERVED line $(grep -c '^CASE A codex sandbox runner (OBSERVED, never blocks): codex sandbox windows --full-auto -- powershell' $LAST)"
drv A-tool-failed 'RESULT A TOOL-FAILED -1073741502' $KEYENV=$KEYVAL FAKE_CODEX_CASE=failed -- case A
CHECK+="A TOOL-FAILED: call line with exit -1073741502 $(grep -c '^CASE A call 1: exec_command .* -> exit -1073741502' $LAST), marker absent $(grep -c '^CASE A marker file: absent' $LAST), config.toml has [windows] sandbox = unelevated $(grep -c 'sandbox = "unelevated"' $H/out/A/config.toml)"
drv A-no-tool-call 'RESULT A NO-TOOL-CALL' $KEYENV=$KEYVAL FAKE_CODEX_CASE=nocall -- case A
CHECK+="every case prints the launcher lines (pid, parent chain, Win32 facts NOT-WINDOWS here): $(grep -c -E '^CASE A launcher (pid|parent_chain|windows):' $LAST) of 3; the verdict is the last line: $(tail -2 $LAST | head -1 | grep -c '^RESULT A ')"
drv C-ssh-tool-ran 'RESULT C-ssh TOOL-RAN' $KEYENV=$KEYVAL V643_STANDIN=$H/graftling/tests -- case C-ssh
CHECK+="C-ssh through graftling: outcome line $(grep -c '^CASE C-ssh outcome: completed' $LAST), runtime_job line $(grep -c '^CASE C-ssh runtime job:' $LAST), graftling records kept $(find $H/out/C-ssh/agents -type f 2> /dev/null | wc -l | tr -d ' ') file(s)"
drv C-ssh-tool-failed 'RESULT C-ssh TOOL-FAILED -1073741502' $KEYENV=$KEYVAL V643_STANDIN=$H/graftling/tests V643_PEER_TOOL=true V643_STANDIN_ROLLOUT=$H/fake-rollouts/rollout-failed.jsonl -- case C-ssh
drv C-ssh-no-tool-call 'RESULT C-ssh NO-TOOL-CALL' $KEYENV=$KEYVAL V643_STANDIN=$H/graftling/tests V643_PEER_TOOL=true V643_STANDIN_ROLLOUT=$H/fake-rollouts/rollout-no-call.jsonl -- case C-ssh
drv session-none 'SESSION NONE' -- session
drv session-disconnected 'SESSION NONE' V643_QUSER_FILE=$H/quser-disc.txt -- session
drv session-active 'SESSION ACTIVE 1 console' V643_QUSER_FILE=$H/quser-active.txt -- session
CHECK+="session lines never show the user name: $(grep -c -F -- "$ME" $OUT/drv-*-session-*.txt | awk -F: '{s+=$2} END {print s}') hit(s)"
drv B-schedule-no-session 'RESULT B STOP the VM user has no Active console session' $KEYENV=$KEYVAL -- schedule B 60
drv B-schedule-tool-failed 'RESULT B TOOL-FAILED -1073741502' $KEYENV=$KEYVAL FAKE_CODEX_CASE=failed V643_QUSER_FILE=$H/quser-active.txt -- schedule B 120
CHECK+="B through the task body: done.json $([[ -f $H/out/B/done.json ]] && print present || print absent), task-output.txt $([[ -f $H/out/B/task-output.txt ]] && print present || print absent), case lines printed by schedule $(grep -c '^CASE B ' $LAST)"
drv verdict-B 'VERDICT-OF B TOOL-FAILED -1073741502' -- verdict B
drv B-schedule-tool-ran 'RESULT B TOOL-RAN' $KEYENV=$KEYVAL FAKE_CODEX_CASE=ran V643_QUSER_FILE=$H/quser-active.txt -- schedule B 120
drv verdict-B-after-rerun 'VERDICT-OF B TOOL-RAN' -- verdict B
drv verdict-C-interactive-absent 'VERDICT-OF C-interactive none' -- verdict C-interactive
drv C-interactive-schedule 'RESULT C-interactive TOOL-RAN' $KEYENV=$KEYVAL V643_STANDIN=$H/graftling/tests V643_QUSER_FILE=$H/quser-active.txt -- schedule C-interactive 180
drv scan-A 'SCAN PASS' $KEYENV=$KEYVAL V643_PASSWORD=$PASSWD -- scan A
print -r -- "planted $KEYVAL" > $H/out/A/planted.txt
drv scan-finds-planted-key 'SCAN FAIL' $KEYENV=$KEYVAL V643_PASSWORD=$PASSWD -- scan A
rm -f $H/out/A/planted.txt
print -r -- "planted $PASSWD" > $H/out/I-planted.txt; mkdir -p $H/out/I; mv $H/out/I-planted.txt $H/out/I/planted.txt
drv scan-finds-planted-password 'SCAN FAIL' $KEYENV=$KEYVAL V643_PASSWORD=$PASSWD -- scan I
# Leftover stand-in tool sleeps (graftling's peer starts /bin/sleep 303 for 462's tests) are this run's own.
pkill -f '/bin/sleep 303' 2> /dev/null
k=$(grep -r -l -F -e $KEYVAL -e $PASSWD $OUT 2> /dev/null | wc -l | tr -d ' ')
hits=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e $TAG -e $KEYVAL -e $PASSWD -- .)
v=$(print -rn -- $hits | grep -c .)
[[ -n $hits ]] && CHECK+="files with a hit (names only): ${(f)hits}"
left=$(grep -r -i -l -F -e $MODEL -e api.h$TAG.invalid $H/out | wc -l | tr -d ' ')
CHECK+="consoles holding the key or the password: $k; committed-or-committable files holding a random value, the key or the password: $v"
CHECK+="VM-side evidence (out/) files still holding the model or base-URL host after the scans: $left (only A and I were scanned here)"
{
  print -r -- "Task 643 driver rehearsal on macOS (POSIX branches; graftling ${CANDIDATE[1,12]} cloned from a bundle of dev)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/drv-00-summary.txt
rm -rf $H
