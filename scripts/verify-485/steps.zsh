#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 485: an interactive Codex Main's Stop completion check fails with Codex's
# 'failed to load workspace requirements: invalid input parameter'. Fresh isolated projects under the Harness tmp/485,
# the candidate in an isolated venv there. Production .venv-runtime is only read; production Main is never yielded.
#   zsh <this file> <00|E|R|I1|I2|S|F>
# Order: 00 -> E -> R (reproduce/discriminate, no user) -> I1 (the only USER step) -> I2 -> (R again, optional) -> S -> F.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY485_BASE:-$H/tmp/485}
P=$BASE/project
P2=$BASE/project2
P484=${VERIFY485_P484:-$H/tmp/484/project}
V=$BASE/venv
VT=$BASE/venv-test
DEPS=$BASE/deps
OUT=${VERIFY485_OUT:-$H/.graphtraj/core/state/tasks/485-codex-main-completion-check-workspace-requirements/realhost}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
PY=$V/bin/python
CODEX_MODEL=gpt-6-luna
CODEX_HOME_USED=${CODEX_HOME:-$HOME/.codex}
STEP=${1:-help}
path=($V/bin /opt/homebrew/bin $HOME/.local/bin ${path:#$RT/bin})
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
# Hosts run without this shell's GraphTraj Session variables (Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
probe() { (cd $P && clean $PY -I $SD/probe.py "$@"); }
# A foreground call with a hard limit (seconds) via perl alarm.
limit() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
runtime_records() { for d in $RTSP/graphtraj-*.dist-info $RTSP/graftling-*.dist-info; do print -r -- "${d:t} $(shasum -a 256 $d/RECORD | cut -c1-16)"; done; }
# One venv: base Python + setuptools from it, dependencies linked read-only from production (never graphtraj/graftling).
make_venv() {
  local dir=$1; shift
  [[ -d $DEPS ]] || { mkdir -p $DEPS; for x in $RTSP/*(N); do case ${x:t} in
      graphtraj*|graftling*|__editable__*|*.pth|pip|pip-*|_distutils_hack|__pycache__) ;; *) ln -s $x $DEPS/ ;; esac; done; }
  rm -rf $dir && $(base_python) -m venv --system-site-packages $dir || return 1
  print -r -- $DEPS > $($dir/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/485-deps.pth
  clean $dir/bin/python -m pip install -q --no-deps --no-build-isolation --no-index "$@" 2>&1 | grep -vi cache
  return ${pipestatus[1]}
}
# A fresh isolated project: own git repo (no Harness AGENTS.md), graphtraj setup, Codex hooks + graphtraj MCP entry.
make_project() {
  local p=$1
  if [[ -d $p/.git ]]; then print "existing project $p: git init and graphtraj setup skipped (rerun)"; else
    mkdir -p $p; (cd $p && git init -q -b main && print -r -- "# 485 probe README first line" > README.md && git add README.md \
      && git -c user.name=485 -c user.email=485@invalid commit -qm "Initial source") || return 1
    (cd $p && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $p && clean $PY -I $SD/probe.py prepare $p) \
    || { print "STOP: probe.py prepare $p failed (2 register/update, 3 roles, 4 Task 1 not ready; text above)"; return 1; }
  (cd $p && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve $p's own .graphtraj"; return 1; }
  mkdir -p $p/.codex
  (cd $p && clean $PY -I -c 'import json
from pathlib import Path
from graphtraj.runtimes.codex.finalize import hook
Path(".codex/hooks.json").write_text(json.dumps(hook(Path("."), {}), indent=2) + "\n"); print("wrote .codex/hooks.json")') || return 1
  print -r -- "[mcp_servers.graphtraj]
command = \"$V/bin/graphtraj-mcp\"
args = []
cwd = \"$p\"
default_tools_approval_mode = \"approve\"" > $p/.codex/config.toml
  print "wrote $p/.codex/config.toml:"; sed 's/^/    /' $p/.codex/config.toml
}

step_00() {
  say "[00] preflight. Dialog: none. Output also in $OUT/00.txt"
  local commit=$(git -C $SRC rev-parse HEAD) dirty=$(git -C $SRC status --porcelain | wc -l | tr -d ' ')
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; candidate $SRC commit $commit (uncommitted paths: $dirty; installed is the commit)"
  say "production (read only; F compares)"
  (cd $H && clean $RT/bin/python -I -c 'import json
from pathlib import Path
p = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-1] if p.is_file() else {}
print(last.get("runtime", "none"), last.get("session", "none"))') > $OUT/00-production-main.txt
  runtime_records > $OUT/00-production-runtime.txt
  print "production Main: $(cat $OUT/00-production-main.txt) | production .venv-runtime: $(tr '\n' ' ' < $OUT/00-production-runtime.txt)"
  [[ -s $OUT/00-production-main.txt || -n ${VERIFY485_NO_MODEL:-} ]] || { print "STOP: production continuity record unreadable; F could not compare"; return 1; }
  say "isolated candidate venv $V (commit $commit; dependencies linked read-only from $RTSP)"
  if [[ $(cat $V/.candidate 2>/dev/null) != $commit ]]; then
    rm -rf $BASE/candidate && mkdir -p $BASE/candidate && git -C $SRC archive $commit | tar -x -C $BASE/candidate || return 1
    make_venv $V $BASE/candidate/src/graftling $BASE/candidate || { print "STOP: candidate install failed (text above)"; return 1; }
    print -r -- $commit > $V/.candidate
  else print "venv already holds $commit: install skipped (rerun)"; fi
  clean $PY -I -c 'import sys, graphtraj, graftling
ok = all(m.__file__.startswith(sys.argv[1]) for m in (graphtraj, graftling))
print("candidate imports:", graphtraj.__file__, graftling.__file__, "| under venv:", ok); sys.exit(0 if ok else 1)' $V \
    || { print "STOP: the venv does not import the candidate"; return 1; }
  say "fresh isolated projects $P (I1, R1/R2) and $P2 (R3); each its own git repo, so Codex reads no Harness AGENTS.md"
  print "(no -c on the interactive command: Codex runs a Session with -c/--enable/--disable/--search without the shared background server)"
  make_project $P || return 1
  make_project $P2 || return 1
  say "the GraphTraj MCP entry the interactive Main uses: the server exactly as $P/.codex/config.toml names it (initialize, tools/list, tasks task_graph; no model, limit 60 s)"
  (cd $P && clean /usr/bin/perl -e 'alarm 60; exec @ARGV' $PY -I $SD/probe.py mcp $P/.codex/config.toml) \
    || { print "STOP: the graphtraj MCP entry does not serve (text above)"; return 1; }
  [[ -n ${VERIFY485_NO_MODEL:-} ]] && { print "VERIFY485_NO_MODEL set: stopping before any model or host call (rehearsal)."; return 0; }

  local ASK='Reply with exactly three lines. Line 1: MODEL OK. Line 2: MODEL: your model name. Line 3: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'
  print -r -- "$ASK" > $OUT/00-ask.txt
  say "codex login; one read-only codex exec $CODEX_MODEL answer (limit 300 s). No dialog."
  print "codex version: $(clean codex --version 2>&1 | tail -1)"
  if clean codex login status 2>&1 | grep -q 'Logged in'; then print "codex logged in: YES"; else print "codex logged in: NO"; fi
  (cd $P && limit 300 codex exec -m $CODEX_MODEL --sandbox read-only - < $OUT/00-ask.txt > $OUT/00-codex.txt 2>&1)
  local f=$OUT/00-codex.txt ok=BLOCKED leak="" answer
  # The answer is the last 'MODEL:' line (Codex echoes the prompt first); an echo still contains 'your model name'.
  answer=$(grep -oE 'MODEL: [^\"\\]*' $f | tail -1)
  [[ -n $answer && $answer != *"your model name"* ]] && grep -q 'MODEL OK' $f && ok=OK
  grep -oE "$H/[^ \"]*(AGENTS|CLAUDE)\.md" $f | grep -v "^$P/" | head -1 | read leak
  print "codex answer: $ok | model line: ${answer:-none} | header model: $(grep -m1 -E '^model: ' $f | cut -c8- || true) | Harness instruction file loaded: ${leak:-none}"
  [[ $ok == OK ]] || { print "raw codex output (tail):"; tail -8 $f; }
  say "codex app-server proxy: one read-only thread/loaded/list, CODEX_HOME $CODEX_HOME_USED (limit 60 s)"
  probe daemon $CODEX_HOME_USED \
    || print "note: a connect failure here can mean the shared background server is not running; R uses the same channel and says so"
  print "Success: 'under venv: True', roles OK, task 1 ready, both 'project own: True', 'MCP initialize: OK', 'tools agents and tasks served: YES',"
  print "'task_graph shows probe Task 1: YES', 'codex logged in: YES', 'codex answer: OK' (model line not the prompt) with 'loaded: none',"
  print "and 'app-server proxy thread/loaded/list: YES' (NO with the note is allowed)."
  next "zsh $THIS E 2>&1 | tee $OUT/E.txt"
}

step_E() {
  say "[E] read only: 484's retained completion checks in $P484 (paths per main_finalize.session_binding/bind_checker) and Codex log lines naming 'requirements'. Dialog: none."
  [[ -d $P484 ]] || { print "no 484 project at $P484"; return 1; }
  (cd $P484 && clean $PY -I $SD/probe.py evidence $P484 $CODEX_HOME_USED)
  print "Observable: the failed check's outcome/error, the fork's configuration vs parent_configuration and authorized_difference"
  print "(permission profile, unix socket, network access) and any Codex log line around the failure."
  next "zsh $THIS R 2>&1 | tee $OUT/R.txt"
}

step_R() {
  say "[R] reproduce/discriminate through the checker's own channel (codex app-server proxy on the shared server, CODEX_HOME $CODEX_HOME_USED). Dialog: none. No user."
  print "Per project: a Main-like thread (model $CODEX_MODEL, cwd only), one trivial turn (a base); R1 = fork exactly as finalize.check"
  print "(graphtraj_checker profile + control socket) + one checker turn; R2 = fork without the network profile/socket + one turn;"
  print "R1b = R1 while a base turn is still in progress (as at Stop). Each turn limit 180 s, each project 900 s; the base thread is archived, forks are ephemeral."
  print "Projects: $P (R in the I1 project), $P2 (R3: a second fresh isolated project), $P484 (R4: 484's project where the failure was seen; trusted there)."
  print "Rerun after I1 (then $P is trusted by the user's first launch) to separate project trust."
  [[ -n ${VERIFY485_NO_MODEL:-} ]] && { print "VERIFY485_NO_MODEL set: no model or host call (rehearsal)."; return 0; }
  local label proj
  for label proj in R $P R3 $P2 R4 $P484; do
    [[ -d $proj ]] || { print "[$label] $proj absent: skipped"; continue; }
    (cd $proj && limit 960 $PY -I $SD/probe.py repro $label $proj $CODEX_HOME_USED $CODEX_MODEL) || print "[$label] probe rc=$? (960 s limit is rc 142)"
  done
  print ""
  print "Observable: each '<label> <case>: <status> <error>' line; a case containing 'workspace requirements' is marked <= SYMPTOM,"
  print "and '[<label>] REPRODUCED (<cases>)' or '[<label>] NOT reproduced'. Fork request/response permission fields are printed as -> / <- lines."
  next "USER step: zsh $THIS I1   (prints what the user runs and pastes)"
}

step_R5() {
  local proj=${1:-$P}
  say "[R5] which part of the checker's permission override fails, on ONE project ($proj), through the checker's channel. Dialog: none. No user."
  print "Two base threads (thread/start permissions ':read-only' and ':workspace'), each one trivial turn; per base 5 forks:"
  print "plain (Main's profile), net+sock (today's override), net (no socket), net+lit (literal symlink socket path), sock (socket, network not enabled)."
  print "Each fork's turn runs one command connecting to the control socket: 'socket REACHED' = the checker keeps its access."
  print "Each turn limit 180 s; whole run 1560 s. Base threads archived; forks ephemeral. Best after I1 (then $P is trusted)."
  [[ -n ${VERIFY485_NO_MODEL:-} ]] && { print "VERIFY485_NO_MODEL set: no model or host call (rehearsal)."; return 0; }
  [[ -d $proj ]] || { print "$proj absent"; return 1; }
  (cd $proj && limit 1560 $PY -I $SD/probe.py variants R5 $proj $CODEX_HOME_USED $CODEX_MODEL) || print "[R5] probe rc=$? (1560 s limit is rc 142)"
  print ""
  print "Observable: 'R5 <base> <variant>: <outcome> | socket REACHED/NOT reached | <message>', '<= SYMPTOM' on 'workspace requirements'."
  next "zsh $THIS F 2>&1 | tee $OUT/F.txt   (or the step the Leader names)"
}

step_I1() {
  $PY -I -c 'import time; print(time.time())' > $OUT/I1.start
  print -r -- "Reply with exactly one line: H485-DONE. Use no tool." > $OUT/I1-prompt.txt
  say "[I1] the only USER step, in your own macOS Terminal. Dialog: Codex's first-launch trust for this fresh project, shown together at the first start:"
  print "     first 'Do you trust the contents of this directory?' for $P -> 'Yes'; then the hook review for $P/.codex/hooks.json -> approve."
  print "     No other dialog should appear."
  print "  1. cd $P && codex -m $CODEX_MODEL"
  print "     (exactly this: no -c or other options. If Codex prints 'Running without the shared background server: ...', copy that line to Main.)"
  print "     If after trusting, the startup does not show 'GraphTraj Main Session associated': /exit and run the same command once more."
  print "  2. paste this one prompt (also in $OUT/I1-prompt.txt):"
  print -r -- "$(cat $OUT/I1-prompt.txt)"
  print "  3. wait until the reply H485-DONE and the Stop hook's 'Completion Check · ...' lines appear (up to 10 minutes);"
  print "     copy those Completion Check lines to Main."
  print "  4. keep Codex OPEN and tell Main 'I1 done'; /exit after Main's I2 has printed."
  print "PASS observable: the Completion Check status is completed/waiting/actionable, not 'error' with 'Completion check failed: ... workspace requirements'."
  next "zsh $THIS I2 2>&1 | tee $OUT/I2.txt"
}

step_I2() {
  say "[I2] read only (the user's Codex still open): the completion check retained for I1's Stop, and whether the Main thread is on the shared server. Dialog: none."
  local start=$(cat $OUT/I1.start 2>/dev/null || print 0)
  local claim=$($PY -I -c 'import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / ".graphtraj/runner/main-sessions/continuity.jsonl"
c = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []
c = [x for x in c if x.get("runtime") == "codex" and float(x.get("at", 0)) >= float(sys.argv[2])]
print(c[-1]["session"], (c[-1].get("connection") or {}).get("codex_home", "")) if c else print("")' $P $start)
  local thread=${claim%% *} home=${claim#* }
  print "interactive Codex Main thread (codex claim after I1): ${thread:-NONE} | its CODEX_HOME: ${home:-NONE}"
  [[ -n $thread ]] || print "FAIL I entry: no codex continuity claim since I1 (hooks not trusted, or I1 not run)"
  [[ -n $thread ]] && probe daemon ${home:-$CODEX_HOME_USED} $thread
  probe evidence $P ${home:-$CODEX_HOME_USED} $start
  print ""
  print "USER: you may now /exit the Codex Session."
  next "zsh $THIS S 2>&1 | tee $OUT/S.txt"
}

step_S() {
  say "[S] full suite of the candidate checkout $SRC ($(git -C $SRC rev-parse HEAD)) in its own test venv $VT, 6 shards (scripts/run_test_shards.py). Dialog: none. Limit 1500 s (stops the whole process group)."
  make_venv $VT -e $SRC/src/graftling -e $SRC || { print "STOP: test venv install failed (text above)"; return 1; }
  # The suite's installed-environment tests make a nested venv whose .pth names only $VT's own purelib
  # (tests/conftest.py _install_commands); a .pth inside a .pth-added directory is not read, so the
  # dependencies must be in $VT's purelib itself, not behind 485-deps.pth.
  local site=$($VT/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  rm -f $site/485-deps.pth
  local nest=$BASE/nested-check
  rm -rf $nest && $VT/bin/python -m venv --system-site-packages $nest \
    && print -r -- $site > $($nest/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/graphtraj_test_dependencies.pth \
    && clean $nest/bin/python -I -c 'import websockets, click, yaml' \
    && print "nested venv imports: OK (websockets, click, yaml via $site; conftest installs the graphtraj/graftling wheels there itself)" \
    || { print "STOP: nested venv imports failed (error above)"; return 1; }
  clean $VT/bin/python -I -c 'import sys, graphtraj, graftling
ok = all(m.__file__.startswith(sys.argv[1]) for m in (graphtraj, graftling))
print("test venv imports the checkout:", "OK" if ok else "NO", graphtraj.__file__, graftling.__file__); sys.exit(0 if ok else 1)' $SRC/src \
    || { print "STOP: the test venv does not import the checkout"; return 1; }
  rm -rf $nest
  local tmp=${TMPDIR:-/tmp} L=$OUT/S-shards
  print "pytest temp base: ${tmp:A} | outside the Harness $H: $([[ ${tmp:A} != $H* ]] && print YES || print NO)"
  [[ ${tmp:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
  # A 1500 s self-limit that stops the shard runner's whole process group (verify-482 suite()).
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
    sys.exit(124)' $VT/bin/python $SRC/scripts/run_test_shards.py --shards 6 --log-dir $L)
  print "command (in $SRC): ${(q)cmd[@]}"
  [[ -n ${VERIFY485_NO_MODEL:-} ]] && { print "VERIFY485_NO_MODEL set: test venv ready, suite not run (rehearsal)."; return 0; }
  rm -rf $L; mkdir -p $L
  print "== start $(date +%T) commit $(git -C $SRC rev-parse HEAD)"
  (cd $SRC && $cmd) > $OUT/S-suite.txt 2>&1
  local rc=$?
  print "== shards exit $rc at $(date +%T); output $OUT/S-suite.txt, shard logs $L/"
  tail -n 4 $OUT/S-suite.txt
  grep -h "^leftover processes" $OUT/S-suite.txt
  touch $L/failures.txt
  print "== failures.txt ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  print "== baseline: dev 5a451267 = 484 accepted 2eea5ed3 (484 realhost/S.txt, S-suite.txt): 0 failed / 4130 passed / 69 skipped."
  print "   Candidate totals: $(grep -E '[0-9]+ (passed|failed)' $OUT/S-suite.txt | tail -1)"
  if [[ $rc == 0 && ! -s $L/failures.txt ]]; then print "PASS S no new failures (baseline had none)"
  else print "FAIL S (shards exit $rc); new failures (the baseline had none):"; sed 's/^/  /' $L/failures.txt; fi
  next "zsh $THIS F 2>&1 | tee $OUT/F.txt"
}

step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $SD/probe.py main $H ${rt:-none} ${sess:-none})
  if [[ "$(runtime_records)" == "$(cat $OUT/00-production-runtime.txt)" ]]; then print "PASS F production .venv-runtime unchanged: $(runtime_records | tr '\n' ' ')"
  else print "FAIL F production .venv-runtime changed: now $(runtime_records | tr '\n' ' ') / at 00 $(tr '\n' ' ' < $OUT/00-production-runtime.txt)"; fi
  print "pids: this script starts no background process (every host call is foreground with a limit)"
  print "PASS/FAIL summary:"; grep -hE '^(PASS|FAIL)' $OUT/*.txt(N) | sort | uniq
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt; return ${pipestatus[1]} ;;
  E|R|I1|I2|S|F) step_$STEP ;;
  R5) step_R5 ${2:-} ;;
  *) print "usage: zsh $THIS <00|E|R|R5 [project]|I1|I2|S|F>" ;;
esac
}
dispatch "$@"; exit $?
