#!/bin/zsh
# Task 644 rehearsal (Engineer) of the VM-side driver vm/drive644.py on macOS (POSIX branches; the Win32 facts read
# NOT-WINDOWS; job APIs and the scheduled task cannot run here):
#   - the rollout parser on the REAL Task 640 and 643 rollouts (exit codes from function_call_output; the cwd);
#   - graftling cloned from a bundle of <Harness>/graftling dev, the candidate checked out (as provision.ps1 does);
#   - each case through graftling with graftling's stand-in Codex peer (tests/codex_stdio_peer.py): tool and nonascii
#     with a rollout shaped like the real ones (exit 0, the cwd) -> PASS; a real 643 rollout with exit -1073741502 and a
#     tool that does nothing -> FAIL; a rollout without a call -> NO-TOOL-CALL; nonascii with a real 640 rollout whose
#     cwd is another dir -> the cwd item FAILs; stop, takeover (owner killed hard, a new owner process) and caller (the
#     Codex parent host, a create through MCP);
#   - schedule (off Windows the task body runs as a plain subprocess) with and without a console session; no key
#     (STOP); a driver error (STOP driver error); cleanup of a planted leftover; jobopen off Windows;
#   - scan: the key, and the autologon password, planted in the evidence fail the scan without printing it; VM_USER
#     in a VM path is replaced.
# Settings values, the key and the password are RANDOM per run. Consoles: rehearsal/<round>/drv-NN-*.txt.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
HERE=${0:A:h:h}
OUT=$HERE/rehearsal/${1:-c1}
mkdir -p $OUT
rm -f $OUT/drv-*.txt(N)
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
PY=$HARNESS/.venv-runtime/bin/python   # has PyYAML and websockets (graftling's runtime needs); graftling from PYTHONPATH
CANDIDATE=2ee706eb749355afc3f73f03a1b0de4cd48da1f2
STATE=$HARNESS/.graphtraj/core/state/tasks
REAL640=$STATE/640-graftling-windows-codex-real/realhost/evidence-live/R-unelevated/rollouts
REAL643=$STATE/643-codex-windows-dll-init-attribution/realhost/evidence-live-run2
TAG=$(openssl rand -hex 4)
H=$(mktemp -d $TMPDIR/v644drv.XXXXXX)
mkdir -p $H/home $H/codex-home $H/fixtures
KEYENV=K${(U)TAG}_API_KEY
KEYVAL=sk-dummy-$TAG-$(openssl rand -hex 16)
PASSWD=Pw-$(openssl rand -hex 12)
VMUSER=u$TAG
git -C $HARNESS/graftling bundle create -q $H/graftling.bundle refs/heads/dev
git clone -q --template= --no-checkout $H/graftling.bundle $H/graftling && git -C $H/graftling checkout -q --detach $CANDIDATE
$PY -I -c 'import json, sys
t, keyenv, user, cand = sys.argv[2:6]
pairs = [["<PROJECT>", f"p-{t}-proj"], ["<MODEL>", f"model-{t}-flash"], ["<PROVIDER_ID>", f"prov{t}"], ["<KEY_ENV>", keyenv],
         ["<VM_USER>", user]]
json.dump({"provider": {"id": f"prov{t}", "name": f"Prov{t} Name", "base_url": f"https://api.h{t}.invalid/v7/", "wire_api": "responses",
           "model": f"model-{t}-flash", "key_env": keyenv}, "codex_version": "0.172.0", "candidate": cand, "scrub": pairs},
          open(sys.argv[1], "w"))' $H/home/settings.json $TAG $KEYENV $VMUSER $CANDIDATE
# Rollouts shaped like Codex 0.172's real ones (function_call exec_command {"cmd": ...}; function_call_output
# "Chunk ID ...\nProcess exited with code N\n..."; turn_context cwd).
mkfix() {  # mkfix <file> <cwd> <with call: 1|0>
  $PY -I -c 'import json, sys
out, cwd, call = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
rows = [{"type": "session_meta", "payload": {"id": "s", "cwd": cwd, "model_provider": "x"}},
        {"type": "turn_context", "payload": {"cwd": cwd, "model": "x"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Set-Content -Path marker-644.txt -Value tool-ran-644"}]}}]
if call:
    rows += [{"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
              "arguments": json.dumps({"cmd": "Set-Content -Path marker-644.txt -Value tool-ran-644"})}},
             {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
              "output": "Chunk ID: 1a2b3c\nWall time: 0.4 seconds\nProcess exited with code 0\nOriginal token count: 0\nOutput:\n"}}]
open(out, "w").write("\n".join(json.dumps(r) for r in rows) + "\n")' $1 $2 $3
}
# The cwd as the driver resolves HOME (on macOS $TMPDIR may sit behind the /tmp symbolic link).
mkfix $H/fixtures/tool-exit0.jsonl ${H:A}/home/work/tool 1
mkfix $H/fixtures/nonascii-exit0.jsonl "${H:A}/home/work/工作ü-644" 1
mkfix $H/fixtures/no-call.jsonl ${H:A}/home/work/tool 0
BASE=(env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$H/graftling/src V644_HOME=$H/home CODEX_HOME=$H/codex-home V644_PASSWORD=$PASSWD $KEYENV=$KEYVAL USER=${USER:-} PYTHONUTF8=1)
SA=(V644_STANDIN=$H/graftling/tests)
DRV=$HERE/vm/drive644.py
N=0
typeset -a SUMMARY
run() {  # run <name> <expect substring> <env/command...>
  local name=$1 expect=$2; shift 2
  (( N++ ))
  local file=$OUT/drv-$(printf %02d $N)-$name.txt
  print -r -- "\$ ${(j: :)${@:#*=*}}" | sed "s|$DRV|vm/drive644.py|g; s|$PY|<python>|g; s|${H:A}|<tmp>|g; s|$H|<tmp>|g;
    s|$HERE|scripts/verify-644|g; s|$STATE|<state>/tasks|g; s|$VMUSER|<VM_USER>|g" > $file
  "$@" 2>&1 | sed "s|${H:A}|<tmp>|g; s|$H|<tmp>|g" >> $file   # scratch paths shown as <tmp>
  print -r -- "(exit ${pipestatus[1]})" >> $file
  local ok=no; grep -q -F -- "$expect" $file && ok=yes
  SUMMARY+="drv-$(printf %02d $N) $name: expects '$expect' -> $ok"
}
FX=(640-R1=$REAL640/rollout-2026-11-26T15-19-50-01a21871-06af-74b3-b923-a1165b563348.jsonl
    640-R2=$REAL640/rollout-2026-11-26T15-28-29-01a21878-f40f-7900-b46a-a496237b0b9f.jsonl
    640-R3=$REAL640/rollout-2026-11-26T15-28-29-01a21878-f4b5-7ff0-a279-a1d8382742a1.jsonl
    640-R4=$REAL640/rollout-2026-11-26T15-28-52-01a21879-4b51-7652-91ea-a7d209ed920c.jsonl
    643-A=$REAL643/A/rollouts/rollout-2026-11-26T16-52-58-01a218c6-4d6d-7862-818e-05e72a903679.jsonl
    643-B=$REAL643/B/rollouts/rollout-2026-11-26T16-55-18-01a218c8-6f6f-78d3-aa4c-dbb47280f360.jsonl
    643-C-interactive=$REAL643/C-interactive/rollouts/rollout-2026-11-26T16-56-13-01a218c9-4662-76c1-9d67-c6881a017ef4.jsonl
    643-C-ssh=$REAL643/C-ssh/rollouts/rollout-2026-11-26T16-56-50-01a218c9-d5bc-7a73-aec4-34216995d347.jsonl)
run parser-real-640-643-rollouts "643-C-interactive" $BASE $PY -I $HERE/rehearsal/check_parser644.py $DRV $FX
run cwd-compare-real-640 "same: True True False" $BASE $PY -I -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("d", sys.argv[1]); d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
cwd = d.reported_cwd(d.read_records(__import__("pathlib").Path(sys.argv[2])))
print("same:", d.same_dir(cwd[0], "C:\\v640\\work\\工作ü-640"), d.same_dir("\\\\?\\" + cwd[0].upper(), "C:\\v640\\work\\工作ü-640"), d.same_dir(cwd[0], "C:\\v644\\work\\工作ü-644"))' $DRV ${FX[1]#*=}
run tool-pass "RESULT tool PASS" $BASE $SA V644_STANDIN_ROLLOUT=$H/fixtures/tool-exit0.jsonl $PY $DRV case tool
run tool-fail-real-643-ssh-rollout "RESULT tool FAIL (tool call exit, marker)" $BASE $SA V644_PEER_TOOL=true V644_STANDIN_ROLLOUT=${FX[8]#*=} $PY $DRV case tool
run tool-no-tool-call "RESULT tool NO-TOOL-CALL" $BASE $SA V644_PEER_TOOL=true V644_STANDIN_ROLLOUT=$H/fixtures/no-call.jsonl $PY $DRV case tool
run nonascii-pass "RESULT nonascii PASS" $BASE $SA V644_STANDIN_ROLLOUT=$H/fixtures/nonascii-exit0.jsonl $PY $DRV case nonascii
run nonascii-cwd-differs-real-640 "RESULT nonascii FAIL (tool call exit, cwd Codex reports)" $BASE $SA V644_STANDIN_ROLLOUT=${FX[1]#*=} $PY $DRV case nonascii
run stop "RESULT stop PASS" $BASE $SA $PY $DRV case stop
run takeover "RESULT takeover PASS" $BASE $SA $PY $DRV case takeover
run caller "RESULT caller PASS" $BASE $SA $PY $DRV case caller
print -r -- " USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
>${USER:-x}               console             1  Active      none   11/27/2026 9:00 AM" > $H/quser.txt
run schedule-tool "RESULT tool PASS" $BASE $SA V644_QUSER_FILE=$H/quser.txt V644_STANDIN_ROLLOUT=$H/fixtures/tool-exit0.jsonl $PY $DRV schedule tool 120
run schedule-no-session "RESULT tool STOP the VM user has no Active console session" $BASE $SA $PY $DRV schedule tool 120
run no-key "RESULT tool STOP the key variable is not set" env PYTHONPATH=$H/graftling/src V644_HOME=$H/home CODEX_HOME=$H/codex-home $PY $DRV case tool
run driver-error "RESULT stop STOP driver error" $BASE V644_STANDIN=$H/no-such-tests $PY $DRV case stop
/bin/sleep 6441 &
run cleanup-planted-leftover "CLEANUP stop: 1 leftover" $BASE $SA $PY $DRV cleanup stop
run jobopen-off-windows "NOT-WINDOWS" $BASE $PY $DRV jobopen graftling-x $H/jobopen.json 1 2
mkdir -p $H/home/out/tool/agents
print -r -- "work dir C:\\Users\\$VMUSER\\AppData\\Roaming\\npm\\codex.CMD" > $H/home/out/tool/agents/path.txt
run scan-clean-vm-user-replaced "SCAN PASS" $BASE $PY $DRV scan tool
run scan-no-vm-user-left "count 0" $BASE /usr/bin/python3 -I -c 'import sys, pathlib; print("count", sum(sys.argv[2].lower() in p.read_text(errors="replace").lower() for p in pathlib.Path(sys.argv[1]).rglob("*") if p.is_file()))' $H/home/out/tool $VMUSER
print -r -- "leaked $KEYVAL" > $H/home/out/tool/agents/leak.txt
run scan-finds-planted-key "SCAN FAIL the key or the autologon password is in 1 file(s)" $BASE $PY $DRV scan tool
rm -f $H/home/out/tool/agents/leak.txt
print -r -- "leaked $PASSWD" > $H/home/out/tool/agents/leak.txt
run scan-finds-planted-password "SCAN FAIL the key or the autologon password is in 1 file(s)" $BASE $PY $DRV scan tool
rm -f $H/home/out/tool/agents/leak.txt
leaks=$(grep -l -F -e $KEYVAL -e $PASSWD -e $VMUSER -e $TAG $OUT/drv-*.txt 2> /dev/null | wc -l | tr -d ' ')
home=$(grep -l -e '/Users/' $OUT/drv-*.txt 2> /dev/null | wc -l | tr -d ' ')
{
  print -r -- "Task 644 driver rehearsal (macOS, stand-in Codex peer; random dummy settings, key and password; consoles drv-01-$(printf %02d $N) in ${OUT:t}/)"
  print -lr -- $SUMMARY
  print -r -- "consoles holding the dummy key, password, VM user or settings tag: $leaks; consoles holding a /Users/ path: $home"
} | tee $OUT/drv-00-summary.txt
pkill -f 'sleep 6441' 2> /dev/null
rm -rf $H
