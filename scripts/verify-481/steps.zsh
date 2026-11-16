#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 481: a user-started headless DSH becomes GraphTraj Main through the documented patch (README "DSH as Main"),
# in an ISOLATED project under the Harness tmp/481, with the candidate installed in tmp/481/venv.
# Production .venv-runtime (read only: dependency copies) and the production Main are never changed.
#   zsh <this file> <00|D1|D2|D3|SUITE|F>       order: 00 -> D1 -> D2 -> D3 -> SUITE -> F
# Every step: no native dialog (headless hosts; the DSH Main answers requests through its tools), bounded waits,
# signals only processes it started. Reuses verify-444/probe.py (same commit) for the 398/373 judgements.
set -u
SD=${0:A:h}; THIS=${0:A}; WT=${SD:h:h}; H=${WT:h:h:h:h}
BASE=${VERIFY481_BASE:-$H/tmp/481}
P=$BASE/project
OUT=${VERIFY481_OUT:-$H/.graphtraj/core/state/tasks/481-dsh-user-started-main-docs/realhost}
RT=$H/.venv-runtime
CONDA=${VERIFY481_PYTHON:-/Users/luoxiao/miniconda3/bin/python3.13}
V=$BASE/venv; PY=$V/bin/python
PATCH=$BASE/dsh-main.patch.yml
PROBE=$WT/scripts/verify-444/probe.py
MODEL=claude-opus-5-5
TURN_LIMIT=300
STEP=${1:-help}
# The candidate venv is deliberately NOT on PATH: the patch must work without it (README).
path=(/opt/homebrew/bin $HOME/.local/bin /usr/bin /bin /usr/sbin /sbin)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): zsh $THIS $1 2>&1 | tee $OUT/$1.txt"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# No GraphTraj/Graftling Session variables of Main leak in; GRAFTLING_DSH_CONFIG is never set (the plugin refuses it).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
probe() { (cd $P && clean $PY -I $PROBE "$@") | redact; return ${pipestatus[1]}; }
pause() { $CONDA -I -c 'import sys, time; time.sleep(float(sys.argv[1]))' $1; }
wait_pid() { $CONDA -I -c 'import os, sys, time
try: pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError): print("STOP: no pid file", sys.argv[1]); sys.exit(2)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("host pid", pid, "ended"); sys.exit(0)
    time.sleep(3)
print("host pid", pid, "still running after", sys.argv[2], "s; F reports it"); sys.exit(1)' $1 $2; }
claims() { $CONDA -I -c 'import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / ".graphtraj/runner/main-sessions/continuity.jsonl"
rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []
for r in rows:
    if r.get("runtime") == "dsh" or (r.get("connection") or {}).get("runtime") == "dsh":
        print(r.get("entry"), (r.get("connection") or {}).get("session") or r.get("session"))' $P; }
# One headless DSH turn of the documented form: dsh --profile headless --patch <file>, from the project directory.
dsh_turn() { (cd $P && clean nohup dsh --profile headless --json --patch $PATCH "$@" < /dev/null \
  > $OUT/$STEP-main-stream.jsonl 2> $OUT/$STEP-stderr.txt & print $! > $OUT/$STEP.pid); wait_pid $OUT/$STEP.pid $TURN_LIMIT; }
ASK373() { print -r -- "{\"action\":\"execute\",\"feature\":\"swarm\",\"arguments\":{\"tasks\":[{\"task_id\":\"1\",\"role\":\"asker\",\"instruction\":\"Run these two shell commands, one Bash call each, in this order: touch $BASE/373-$1-a and touch $BASE/373-$1-b. Each needs approval; wait for each answer. Then reply with one line saying which were allowed or denied.\"}]}}"; }
DENY='Then repeat, at most 12 rounds, until the asker execution has ended: using the agents tool, action requests with agent set to the asker alias from SWARM-RESULT; for EVERY pending native request call the agents tool action reply with that agent, request set to the request object exactly as returned, and response {"behavior": "deny", "message": "481 probe denies"}; print one line DENIED <request id> per reply. Between rounds use the agents tool action wait with that agent and timeout_seconds 15 (never a shell command). Finally print the asker final reply on one line starting with ASKER-RESULT and stop. Never allow a request.'

step_00() {
  say "[00] preflight via /bin/zsh. Dialog: none. Waits: dsh entry turn <= ${TURN_LIMIT} s, host lines <= 120 s each."
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; candidate commit $(git -C $WT rev-parse --short HEAD); BASE=$BASE"
  say "production current Main (read only; F compares)"
  (cd $H && $CONDA -I -c 'import json
from pathlib import Path
p = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-1] if p.is_file() else {}
print(last.get("runtime", "none"), last.get("session", "none"))') > $OUT/00-production-main.txt
  print "production Main: $(cat $OUT/00-production-main.txt)"
  say "candidate venv $V (editable from this Worktree; dependencies copied from production, which is only read)"
  if [[ ! -x $PY ]]; then
    $CONDA -m venv --system-site-packages $V || return 1
    $PY -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
    local S=($RT/lib/python*/site-packages(N)) D=($V/lib/python*/site-packages(N))
    cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  fi
  (cd /tmp && $PY -I -c 'import graphtraj; print("candidate imports", graphtraj.__file__)') || return 1
  say "isolated project $P (outside the Harness AGENTS.md/.graphtraj influence: its own git and .graphtraj)"
  if [[ -d $P/.git ]]; then print "existing project: git init and setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 481 probe" > README.md && git add README.md \
      && git -c user.name=481 -c user.email=481@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  probe prepare $P || { print "STOP: probe prepare failed (text above): roles or Task 1 not ready"; return 1; }
  say "hosts the later steps use: one real line each (model and login)"
  (cd $BASE && clean claude -p --model $MODEL "Reply with exactly one line: CLAUDE-OK <your model id>." 2>&1 | tail -1) | tee $OUT/00-claude.txt
  (cd $BASE && clean dsh --profile headless --permission-mode read-only "Reply with exactly one line: DSH-OK <your model id>. Use no tool." < /dev/null 2>&1 | redact | tail -1) | tee $OUT/00-dsh.txt
  grep -q CLAUDE-OK $OUT/00-claude.txt || { print "STOP: claude did not answer (login?)"; return 1; }
  grep -q DSH-OK $OUT/00-dsh.txt || { print "STOP: dsh did not answer (login/DEEPSEEK_API_KEY?)"; return 1; }
  say "graftling-dsh in the headless profile (read only; never installed or removed here)"
  clean dsh plugin --profile headless list --depth 0 2>&1 | redact | head -20 > $OUT/00-dsh-plugins.txt
  cat $OUT/00-dsh-plugins.txt
  local coexist=NO; grep -q graftling-dsh $OUT/00-dsh-plugins.txt && coexist=YES
  print "graftling-dsh installed in headless: $coexist"
  say "the documented patch, written by the candidate installation"
  clean $PY -m graphtraj.runtimes.dsh.main_entry patch --write $PATCH && cat $PATCH
  say "ONE real read-only call through the new entry (judged from records, not model text)"
  local before=$(claims | grep -c .)
  STEP=00e dsh_turn "Call your GraphTraj tasks tool exactly once with the arguments {\"action\": \"discover\"}. Then print one line DISCOVERED and stop. Use no other tool."
  claims | tail -3
  local after=$(claims | grep -c .)
  $CONDA -I -c 'import json, sys
calls = results = 0
for line in open(sys.argv[1], errors="replace"):
    if "mcp__graphtraj__tasks" in line and "discover" in line: calls += 1; print("call record:", line.strip()[:300])
    if "task_graph" in line: results += 1; print("result record:", line.strip()[:300])
print(f"records naming mcp__graphtraj__tasks with discover: {calls}; records holding the discover result (task_graph): {results}")
sys.exit(0 if calls and results else 1)' $OUT/00e-main-stream.jsonl; local rec=$?
  local claimed=NO; [[ ${after:-0} -gt ${before:-0} ]] && claims | tail -1 | grep -q '^dsh:agent/created:startup ' && claimed=YES
  print "dsh claim after agent/created: $claimed (dsh claims before ${before:-0}, after ${after:-0})"
  print "dsh tasks tool call and result in records: $([[ $rec == 0 ]] && print YES || print NO)"
  if [[ $claimed == YES && $rec == 0 ]]; then
    print "PASS 00: the patched headless DSH claimed Main at agent/created and called its tasks tool (graftling-dsh installed in headless: $coexist)"
    [[ $coexist == YES ]] || print "note: graftling-dsh is not installed in headless, so coexistence is unobserved in this run"
    next D1
  else
    print "FAIL 00: see $OUT/00e-main-stream.jsonl and $OUT/00e-stderr.txt; D1-D3 would not be meaningful. Next: F."
    next F
  fi
}
step_D1() {
  say "[D1] headless DSH Main: create g398 (60 s) and exit; after 100 s its end stays queued (398). Dialog: none. Waits <= $((TURN_LIMIT + 100)) s."
  dsh_turn "Using only the agents tool: create a root agent with arguments {\"runtime\": \"claude\", \"configuration\": \"advisor\", \"name\": \"g398\", \"instruction\": \"Run the shell command sleep 60 once, then reply with exactly one line: PONG-398.\"}. Do not wait. Print CREATE and the agent id, then stop." || return 1
  claims | tail -1 | awk '{print $2}' > $OUT/D.session
  print "DSH Main session (from the continuity claim): $(cat $OUT/D.session)"
  pause 100
  probe queued $P dsh g398 60; local rc=$?
  print $([[ $rc == 0 ]] && print PASS || print FAIL) "398 part 1: after the headless DSH Main exited, g398's end stays queued, undelivered (QUEUED line)"
  next D2
}
step_D2() {
  say "[D2] resume the DSH Main (--session-id): g398 delivered once; dispatch the asker; exit. Dialog: none. Waits <= $TURN_LIMIT s."
  [[ -s $OUT/D.session ]] || { print "STOP: no DSH session id; run D1"; return 1; }
  dsh_turn --session-id $(cat $OUT/D.session) "Quote every GraphTraj notice you received at the start of this turn (alias, event) and print one line G398-COUNT <n> with how many times g398 appears. Then using only the tasks tool call it once with exactly $(ASK373 dsh) and print its raw result on one line starting with SWARM-RESULT. Stop; do not wait." || return 1
  claims | tail -1
  probe delivered $P g398; local rc=$?
  print $([[ $rc == 0 ]] && print PASS || print FAIL) "398 part 2: the resumed headless DSH Main received g398 exactly once (probe delivered, from records)"
  probe inbox $P | tee $OUT/D2-inbox.txt
  print "D3 starts by waiting 120 s so the asker's two requests are queued while the DSH Main is exited."
  next D3
}
step_D3() {
  say "[D3] after 120 s, resume the DSH Main: the asker's queued requests arrive; it denies each (373-DSH). Dialog: none. Waits <= $((TURN_LIMIT + 120)) s."
  pause 120
  dsh_turn --session-id $(cat $OUT/D.session) "Quote every GraphTraj notice you received at the start of this turn (alias, event, request id). $DENY" || return 1
  cat $OUT/D2-main-stream.jsonl $OUT/D3-main-stream.jsonl > $OUT/D3x-main-stream.jsonl 2>/dev/null  # asker alias is in D2's
  probe requests $P $OUT D3x dsh
  for f in $BASE/373-dsh-a $BASE/373-dsh-b; do [[ -e $f ]] && print "FAIL 373-DSH target exists: $f" || print "PASS 373-DSH target absent: $f"; done
  probe inbox $P | tee $OUT/D3-inbox.txt
  next SUITE
}
step_SUITE() {
  local T=${TMPDIR:-/tmp} R=$OUT/SUITE
  say "[SUITE] full pytest of the candidate with TMPDIR=$T (\${TMPDIR:-/tmp}; outside the Harness, Task 482). Dialog: none. Waits <= 1500 s."
  case $T in $H|$H/*) print "STOP: TMPDIR $T lies inside the Harness"; return 1 ;; esac
  rm -rf $R-shards; mkdir -p $R-shards
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) TMPDIR=$T shards=8"
  (cd $WT && clean $PY -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try: child.wait(timeout=10)
    except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $PY $WT/scripts/run_test_shards.py --shards 8 --log-dir $R-shards) > $R-suite.txt 2>&1
  print "== shards exit $? at $(date +%T); output $R-suite.txt"; tail -n 4 $R-suite.txt
  touch $R-shards/failures.txt
  print "== failures ($(wc -l < $R-shards/failures.txt | tr -d ' ')):"; cat $R-shards/failures.txt
  print "== NEW failures (not in baseline $WT/scripts/verify-482/baseline-failures.txt):"
  local new=$(comm -23 <(sort -u $R-shards/failures.txt) <(grep -v '^#' $WT/scripts/verify-482/baseline-failures.txt | sort -u))
  [[ -z $new ]] && print "PASS SUITE: no new failures" || { print -r -- $new | sed 's/^/  /'; print "FAIL SUITE: new failures above"; }
  next F
}
step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $PROBE main $H $rt $sess) | redact
  for f in $OUT/*.pid(N); do
    local pid=$(cat $f)
    if kill -0 $pid 2>/dev/null; then print "STILL RUNNING: ${f:t:r} pid $pid (started by this script); stop it with: kill $pid"; else print "ended: ${f:t:r} pid $pid"; fi
  done
  print "PASS/FAIL summary:"; grep -h '^\(PASS\|FAIL\)' $OUT/*.txt(N) | sort | uniq
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00|D1|D2|D3|SUITE|F) step_$STEP 2>&1 | redact ;;
  *) print "usage: zsh $THIS <00|D1|D2|D3|SUITE|F>" ;;
esac
}; dispatch; exit
