#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 486: a headless DSH Main's root Agent stops with the DSH Main (user decision, option A); its interrupted end
# is recorded and queued for that Main, and the resumed DSH Main receives it exactly once by event id.
# ISOLATED project under the Harness tmp/486 (own git and .graphtraj), candidate commit installed into tmp/486/venv.
# Production .venv-runtime is only read (dependencies linked); the production Main is never yielded.
#   zsh <this file> <00|D1|D2|X|SUITE|SUITEB|F>   order: 00 -> D1 -> D2 -> X -> SUITE -> SUITEB -> F
# Reuses verify-481's DSH turn form (README "DSH as Main": dsh --profile headless --patch <file>) and verify-444/probe.py.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY486_BASE:-$H/tmp/486}
P=$BASE/project
V=$BASE/venv
DEPS=$BASE/deps
OUT=${VERIFY486_OUT:-$H/.graphtraj/core/state/tasks/486-dsh-main-root-agent-end-after-exit/realhost}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
PY=$V/bin/python
PATCH=$BASE/dsh-main.patch.yml
PROBE=$SRC/scripts/verify-444/probe.py
DEV=5a451267
MODEL=claude-opus-5-5
TURN_LIMIT=300
STEP=${1:-help}
# The candidate venv is deliberately NOT on PATH: the patch names its python (README "DSH as Main").
# VERIFY486_STUB_BIN (rehearsal only) puts stub dsh/claude first.
path=(${VERIFY486_STUB_BIN:+$VERIFY486_STUB_BIN} /opt/homebrew/bin $HOME/.local/bin /usr/bin /bin /usr/sbin /sbin)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): zsh $THIS $1 2>&1 | tee $OUT/$1.txt"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# No GraphTraj/Graftling Session variables of Main leak in; GRAFTLING_DSH_CONFIG is never set.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
probe() { (cd $P && clean $PY -I $PROBE "$@") | redact; return ${pipestatus[1]}; }
iso() { clean $RT/bin/python -I $SRC/scripts/verify-common/claude_isolation.py "$@"; }
x486() { (cd $P && clean $PY -I $SD/x486.py $P g398 "$@"); }
limit() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
runtime_records() { for d in $RTSP/graphtraj-*.dist-info $RTSP/graftling-*.dist-info; do print -r -- "${d:t} $(shasum -a 256 $d/RECORD | cut -c1-16)"; done; }
wait_pid() { $(base_python) -I -c 'import os, sys, time
try: pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError): print("STOP: no pid file", sys.argv[1]); sys.exit(2)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("host pid", pid, "ended"); sys.exit(0)
    time.sleep(2)
print("host pid", pid, "still running after", sys.argv[2], "s; F reports it"); sys.exit(1)' $1 $2; }
claims() { $(base_python) -I -c 'import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / ".graphtraj/runner/main-sessions/continuity.jsonl"
for r in ([json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []):
    if r.get("runtime") == "dsh": print(r.get("entry"), r.get("session"))' $P; }
# One venv: base Python, dependencies linked read-only from production (never graphtraj/graftling).
make_venv() {
  local dir=$1; shift
  [[ -d $DEPS ]] || { mkdir -p $DEPS; for x in $RTSP/*(N); do case ${x:t} in
      graphtraj*|graftling*|__editable__*|*.pth|pip|pip-*|_distutils_hack|__pycache__) ;; *) ln -s $x $DEPS/ ;; esac; done; }
  rm -rf $dir && $(base_python) -m venv --system-site-packages $dir || return 1
  print -r -- $DEPS > $($dir/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/486-deps.pth
  clean $dir/bin/python -m pip install -q --no-deps --no-build-isolation --no-index "$@" 2>&1 | grep -vi cache
  return ${pipestatus[1]}
}
# One headless DSH turn of the documented form, from the project; --patch precedes the app flags (481).
dsh_turn() {
  (cd $P && clean nohup dsh --profile headless --patch $PATCH --json "$@" < /dev/null \
    > $OUT/$STEP-main-stream.jsonl 2> $OUT/$STEP-stderr.txt & print $! > $OUT/$STEP.pid)
  wait_pid $OUT/$STEP.pid $TURN_LIMIT
}
# A one-line answer that is not the prompt echoed: the LAST line must start with the tag and name no placeholder.
answer() { local f=$1 tag=$2 line; line=$(grep -v '^\s*$' $f | tail -1)
  if [[ $line == $tag* && $line != *'<'* ]]; then print "$tag answer: OK | line: $line"; return 0; fi
  print "$tag answer: NO | last line: ${line:-none}"; return 1; }

step_00() {
  say "[00] preflight via /bin/zsh. Dialog: none. Waits: claude <= 120 s, dsh <= 120 s, DSH entry turn <= ${TURN_LIMIT} s."
  local commit=$(git -C $SRC rev-parse HEAD)
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; candidate $SRC commit $commit (uncommitted paths: $(git -C $SRC status --porcelain | wc -l | tr -d ' ')); BASE=$BASE"
  say "production (read only; F compares)"
  (cd $H && clean $RT/bin/python -I -c 'import json
from pathlib import Path
p = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-1] if p.is_file() else {}
print(last.get("runtime", "none"), last.get("session", "none"))') > $OUT/00-production-main.txt
  runtime_records > $OUT/00-production-runtime.txt
  print "production Main: $(cat $OUT/00-production-main.txt) | production .venv-runtime: $(tr '\n' ' ' < $OUT/00-production-runtime.txt)"
  say "candidate venv $V: commit $commit archived to $BASE/candidate, installed editable from there"
  if [[ $(cat $V/.candidate 2>/dev/null) != $commit ]]; then
    rm -rf $BASE/candidate && mkdir -p $BASE/candidate && git -C $SRC archive $commit | tar -x -C $BASE/candidate || return 1
    make_venv $V -e $BASE/candidate/src/graftling -e $BASE/candidate || { print "STOP: candidate install failed (text above)"; return 1; }
    print -r -- $commit > $V/.candidate
  else print "venv already holds $commit: install skipped (rerun)"; fi
  clean $PY -I -c 'import sys, graphtraj, graftling
from pathlib import Path
ok = all(Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()) for m in (graphtraj, graftling))
print("candidate imports:", graphtraj.__file__, "| from the archived commit:", ok); sys.exit(0 if ok else 1)' $BASE/candidate \
    || { print "STOP: the venv does not import the candidate"; return 1; }
  say "isolated project $P (own git and .graphtraj; GraphTraj must not resolve the Harness .graphtraj)"
  if [[ -d $P/.git ]]; then print "existing project: git init and setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 486 probe" > README.md && git add README.md \
      && git -c user.name=486 -c user.email=486@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  # Task 489: the project's OWN .claude/settings.local.json disables cc-plugin-agents-md and excludes the Harness
  # CLAUDE.md/AGENTS.md (rerun after any `configuration --write`); claude -p below is judged by `check`.
  iso settings $H $P || { print "STOP 00: project isolation settings refused or failed (text above)"; return 1; }
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  probe prepare $P || { print "STOP: probe prepare failed (text above): roles or Task 1 not ready"; return 1; }
  say "the documented patch, written by the candidate installation"
  clean $PY -m graphtraj.runtimes.dsh.main_entry patch --write $PATCH && cat $PATCH
  clean dsh --profile headless --patch $PATCH --dump-config > $OUT/00-dump-config.txt 2>&1
  grep -q graphtraj-main $OUT/00-dump-config.txt && print "composed headless tree has the graphtraj-main row: YES" \
    || { print "STOP 00: no graphtraj-main row in the composed headless tree (no model turn started)"; head -20 $OUT/00-dump-config.txt | redact; return 1; }
  [[ -n ${VERIFY486_NO_MODEL:-} ]] && { print "VERIFY486_NO_MODEL set: stopping before any model or host call (rehearsal)."; return 0; }

  local ASK='Reply with exactly two lines. Line 1: TAG <your model id>. Line 2: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'
  say "hosts the steps use, one real read-only call each: claude -p (g398's Runtime; limit 120 s), dsh headless (limit 120 s)"
  # claude: the shared prompt as stream-json, judged from its records (Task 489): STOP when a Harness file is loaded.
  iso prompt CLAUDE-OK > $OUT/00-claude-prompt.txt || return 1
  (cd $P && limit 120 claude -p --model $MODEL --output-format stream-json --verbose \
    < $OUT/00-claude-prompt.txt > $OUT/00-claude.jsonl 2> $OUT/00-claude.err)
  (cd $P && limit 120 dsh --profile headless --permission-mode read-only "${ASK//TAG/DSH-OK}" < /dev/null 2>&1 | redact > $OUT/00-dsh.txt)
  local ok=0
  iso check $OUT/00-claude.jsonl CLAUDE-OK $H $P $OUT/00-claude-prompt.txt --expect clean \
    || { ok=1; print "claude -p did not answer cleanly or loaded a Harness instruction file; $OUT/00-claude.err (head):"; head -5 $OUT/00-claude.err | redact; }
  # dsh: the FILES line is last; the answer line is the one before it.
  local f=$OUT/00-dsh.txt
  grep -v '^\s*$' $f | grep -v '^FILES:' > $f.answer
  answer $f.answer DSH-OK || { ok=1; print "raw dsh (tail):"; tail -4 $f | redact; }
  print "dsh instruction files loaded: $(grep -m1 '^FILES:' $f | cut -c8- || print '(no FILES line)')"
  print "login: claude $([[ $ok == 0 ]] && print 'answered (logged in)' || print 'see above'); dsh DEEPSEEK_API_KEY $([[ -n ${DEEPSEEK_API_KEY:-} ]] && print set || print 'not set here (dsh profile credentials)')"
  [[ $ok == 0 ]] || { print "STOP 00: a host did not answer, or claude -p loaded a Harness instruction file (text above)"; return 1; }
  say "ONE real read-only call through the patched headless DSH Main entry: tasks discover (judged from records)"
  local before=$(claims | grep -c .)
  STEP=00e dsh_turn "Call your GraphTraj tasks tool exactly once with the arguments {\"action\": \"discover\"}. Then print one line DISCOVERED and stop. Use no other tool." || return 1
  local after=$(claims | grep -c .)
  # DSH --json tool results are YAML text inside the JSON line ("result": "action: ...").
  local calls=$(grep -c 'mcp__graphtraj__tasks' $OUT/00e-main-stream.jsonl) results=$(grep '"tool_result"' $OUT/00e-main-stream.jsonl | grep -c 'task_graph')
  print "dsh claims before $before after $after; stream lines naming mcp__graphtraj__tasks: $calls; tool results holding task_graph: $results"
  if [[ $after -gt $before && $calls -gt 0 && $results -gt 0 ]]; then
    print "PASS 00: claude and dsh answered; the patched headless DSH claimed Main and its tasks tool answered"
    next D1
  else print "FAIL 00: see $OUT/00e-main-stream.jsonl and $OUT/00e-stderr.txt; D1/D2 would not be meaningful"; next F; fi
}

step_D1() {
  say "[D1] headless DSH Main creates root Agent g398 (sleep 60) and exits at once; at that exit g398 is stopped: end recorded interrupted, queued undelivered for that Main. Dialog: none. Waits <= $TURN_LIMIT + 60 s."
  [[ -z $(x486 dump 2>/dev/null | grep '^g398 = ') ]] || { print "STOP: g398 already exists in $P (D1 ran before); judge it with X, or remove $BASE to start over"; return 1; }
  dsh_turn "Using only the agents tool: create a root agent with arguments {\"runtime\": \"claude\", \"configuration\": \"advisor\", \"name\": \"g398\", \"instruction\": \"Run the shell command sleep 60 once, then reply with exactly one line: PONG-398.\"}. Do not wait. Print CREATE and the agent id, then stop." || return 1
  claims | tail -1 | awk '{print $2}' > $OUT/D.session
  local session=$(cat $OUT/D.session)
  print "DSH Main session (from its continuity claim): ${session:-NONE}"
  if [[ -z $session ]]; then
    print "FAIL 486 queued: no DSH continuity claim, so the turn did not become Main (see $OUT/D1-stderr.txt)"
    x486 dump; next X; return 1
  fi
  grep '"tool_result"' $OUT/D1-main-stream.jsonl | grep -o 'agent: agent-[0-9a-f]*' | head -1 | sed 's/^/created (YAML tool result): /'
  x486 queued $session 60
  probe queued $P dsh g398 5
  next D2
}

step_D2() {
  say "[D2] resume the DSH Main (--session-id): it receives g398's end exactly once by event id. Dialog: none. Waits <= $TURN_LIMIT s."
  [[ -s $OUT/D.session ]] || { print "STOP: no DSH session id; run D1"; return 1; }
  local session=$(cat $OUT/D.session)
  dsh_turn --session-id $session "Quote every GraphTraj notice you received at the start of this turn (alias, event, execution) on lines starting with NOTICE, then print one line G398-COUNT <n> with how many of them are about g398 or its agent id. Use no tool. Stop." || return 1
  claims | tail -1
  print "model's own count (diagnostic; the verdicts below are from records): $(grep -o 'G398-COUNT [0-9]*' $OUT/D2-main-stream.jsonl | tail -1)"
  x486 delivered $session
  probe delivered $P g398
  probe inbox $P
  next X
}

step_X() {
  say "[X] read only: g398's record and every Main notice of its execution; the Main queues. No model, no host, nothing signalled. Dialog: none. Waits: none."
  x486 dump
  probe inbox $P
  next SUITE
}

# Full suite of one commit, from its own git checkout (a shared clone of this repository under $BASE) and test venv.
suite() {
  local name=$1 commit=$2 C=$BASE/checkout-$1 VT=$BASE/venv-test-$1 L=$OUT/$1-shards
  say "[$STEP] full suite of $name = $commit from the git checkout $C, test venv $VT, 6 shards. Dialog: none. Wait limit 1500 s (stops the whole process group)."
  if [[ $(git -C $C rev-parse HEAD 2>/dev/null) != $(git -C $SRC rev-parse $commit) ]]; then
    rm -rf $C && git clone -q --shared --no-checkout $SRC $C && git -C $C checkout -q --detach $commit || { print "STOP: checkout failed"; return 1; }
  fi
  print "checkout $C at $(git -C $C rev-parse HEAD)"
  make_venv $VT -e $C/src/graftling -e $C || { print "STOP: test venv install failed (text above)"; return 1; }
  # The suite's nested venv (tests/conftest.py) reads only $VT's own purelib: put the dependencies there, not behind a .pth.
  local site=$($VT/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  rm -f $site/486-deps.pth
  local nest=$BASE/nested-check
  rm -rf $nest && $VT/bin/python -m venv --system-site-packages $nest \
    && print -r -- $site > $($nest/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/graphtraj_test_dependencies.pth \
    && clean $nest/bin/python -I -c 'import websockets, click, yaml' \
    && print "nested venv imports: OK (websockets, click, yaml via $site)" \
    || { print "STOP: nested venv imports failed (error above)"; return 1; }
  rm -rf $nest
  clean $VT/bin/python -I -c 'import sys, graphtraj, graftling
from pathlib import Path
ok = all(Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()) for m in (graphtraj, graftling))
print("test venv imports the checkout:", "OK" if ok else "NO", graphtraj.__file__); sys.exit(0 if ok else 1)' $C/src \
    || { print "STOP: the test venv does not import the checkout"; return 1; }
  local tmp=${TMPDIR:-/tmp}
  print "pytest temp base TMPDIR=\${TMPDIR:-/tmp} = ${tmp:A} | outside the Harness $H: $([[ ${tmp:A} != $H* ]] && print YES || print NO)"
  [[ ${tmp:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
  local cmd=(env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$VT/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$tmp LANG=${LANG:-en_US.UTF-8}
             $VT/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 1500 s limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $VT/bin/python $C/scripts/run_test_shards.py --shards 6 --log-dir $L)
  print "command (in $C): ${(q)cmd[@]}"
  [[ -n ${VERIFY486_NO_MODEL:-} ]] && { print "VERIFY486_NO_MODEL set: checkout and test venv ready, suite not run (rehearsal)."; return 0; }
  rm -rf $L; mkdir -p $L
  print "== start $(date +%T)"
  (cd $C && $cmd) > $OUT/$1-suite.txt 2>&1
  local rc=$?
  print "== shards exit $rc at $(date +%T); output $OUT/$1-suite.txt, shard logs $L/"
  tail -n 3 $OUT/$1-suite.txt; grep -h '^leftover processes' $OUT/$1-suite.txt | tail -1
  touch $L/failures.txt
  print "== $name failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  print "== $name totals: $(grep -E '[0-9]+ (passed|failed)' $OUT/$1-suite.txt | tail -1)"
  return $rc
}
compare() {
  local cand=$OUT/SUITE-shards/failures.txt base=$OUT/SUITEB-shards/failures.txt
  [[ -f $cand && -f $base ]] || { print "comparison waits for both SUITE and SUITEB results"; return 0; }
  local new=$(comm -23 <(sort -u $cand) <(sort -u $base))
  print "candidate $(grep -E '[0-9]+ (passed|failed)' $OUT/SUITE-suite.txt | tail -1) | dev $DEV $(grep -E '[0-9]+ (passed|failed)' $OUT/SUITEB-suite.txt | tail -1)"
  [[ -z $new ]] && print "PASS SUITE no new failures against dev $DEV" || { print "FAIL SUITE new failures against dev $DEV:"; print -r -- $new | sed 's/^/  /'; }
}
step_SUITE() { suite SUITE $(git -C $SRC rev-parse HEAD); compare; next SUITEB; }
step_SUITEB() { suite SUITEB $DEV; compare; next F; }

step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $PROBE main $H ${rt:-none} ${sess:-none})
  if [[ "$(runtime_records)" == "$(cat $OUT/00-production-runtime.txt)" ]]; then print "PASS F production .venv-runtime unchanged: $(runtime_records | tr '\n' ' ')"
  else print "FAIL F production .venv-runtime changed: now $(runtime_records | tr '\n' ' ') / at 00 $(tr '\n' ' ' < $OUT/00-production-runtime.txt)"; fi
  for f in $OUT/*.pid(N); do
    local pid=$(cat $f)
    if kill -0 $pid 2>/dev/null; then print "STILL RUNNING: ${f:t:r} pid $pid (started by this script); stop it with: kill $pid"; else print "ended: ${f:t:r} pid $pid"; fi
  done
  print "PASS/FAIL summary:"; grep -hE '^(PASS|FAIL)' $OUT/*.txt(N) | sort | uniq
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00|D1|D2|X|SUITE|SUITEB|F) step_$STEP 2>&1 | redact; return ${pipestatus[1]} ;;
  *) print "usage: zsh $THIS <00|D1|D2|X|SUITE|SUITEB|F>" ;;
esac
}
dispatch; exit $?
