#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 461 real-host check (round 2): a member's agents-tool Pi child leaves `sleep 1461` as a background job of one
# bash call, then runs a second, still-running bash call (`sleep 1200`); its owner Worker and Runtime group are
# SIGKILLed; the orphan must still be alive then (CHECK 0, else NOT OBSERVED); one reconciling read must stop it
# through the recorded descendants (tool_descendants), and nothing else.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/461-pi-child-tool-process-reclaim/scripts/verify-461/steps.zsh <00|00u|01|02|03>
# Timeline (t0 = 01's dispatch): the orphan starts about t0+2 min and lives 24 min (to >= t0+26); the second call
# starts about t0+3 min and runs 20 min (to >= t0+23); 01's Main ends by about t0+10; 02 waits <= 9 min for it and
# kills at once (<= t0+9, or <= t0+18 when 02 is rerun once after 'still running'). Both are alive at the kill.
# 00  Main. preflight: claude/pi versions, scratch venv from COMMIT, the fix is in it, isolated project (isolation
#     and Pi context-file facts) with a 'pi' role on the user's Pi connection and settings (values printed, never a
#     key), srt/sandbox available, one-line answers from the Claude host and from Pi (scratch agent dir; skipped when
#     DEEPSEEK_API_KEY is unset; the user's ~/.pi is never written), probe Task ready, plugin loaded YES/NO.
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust.
# 01  Main. records the dispatch, starts a background `claude -p` Main: swarm -> Claude member creates the Pi child
#     and ends its turn; Main polls `probe child` (member of this dispatch only) until CHILD-RUNNING. Returns at once.
# 02  Main. waits (<= 9 min) for 01's Main; refuses unless the dispatch's member's child record lists a live
#     `sleep 1461`; SIGKILLs only that child's recorded owner Worker and Runtime group (start times unchanged);
#     CHECK 0; three bystanders; one reconciling read; CHECK 1-4; stops the bystanders.
# 03  Main. full suite at HEAD in the background (self-terminating after 25 min), no key variable in its environment.
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# ~/.claude, ~/.codex, ~/.pi or dotfiles. No key value is printed. Signals only processes named above.
# Rehearsal without a model: VERIFY461_NO_MODEL=1 (00 stops before Claude Code and Pi; 02 runs on a 'probe.py stub').
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/461-pi-child-tool-process-reclaim
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY461_COMMIT:-$(git -C $WT rev-parse HEAD)}
# Harness tmp (AGENTS.md rule), never the home directory; round 1's realhost/ output is left untouched.
BASE=${VERIFY461_BASE:-$H/tmp/461}
OUT=${VERIFY461_OUT:-$H/.graphtraj/core/state/tasks/461-pi-child-tool-process-reclaim/realhost/r2}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
AGENT_DIR=${VERIFY461_AGENT_DIR:-$HOME/.pi/agent}
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
PID01=$OUT/01-main.pid
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY461_CLAUDE:-} ]] && { print -r -- $VERIFY461_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
# Credential variables kept for the Pi child (names only are ever printed): DeepSeek's, plus any the connection names
# (00 prints them; set VERIFY461_KEEP_ENV="NAME ..." to add more).
KEEP=(DEEPSEEK_API_KEY ${=VERIFY461_KEEP_ENV:-})
kept() { local n; for n in $KEEP; do [[ -n ${(P)n:-} ]] && print -r -- "$n=${(P)n}"; done }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
# clean0: no key variable at all (setup, probe, suite); clean: plus the kept key variables (claude -p, the Pi line).
clean0() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
clean() { clean0 ${(f)"$(kept)"} "$@"; }
# click 8.5.0, yaml and websockets from production, copied (never changed there) into a venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
  [[ $(cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print(m.version("click"))') == 8.5.0 ]] \
    || { print "STOP: click in $1 is not production's 8.5.0"; return 1; }
}
# One bounded (120 s) answer line, or the last failure line; never fatal; never a standalone sleep.
one_line() {
  local label=$1 rc=0 o=$BASE/scratch/out.$$ e=$BASE/scratch/err.$$; shift
  (cd $BASE/scratch && /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' 120 "$@" < /dev/null > $o 2> $e) || rc=$?
  if (( rc == 0 )); then print -r -- "$label OK: $(tail -1 $o)"
  else print -r -- "$label FAILED rc=$rc (142 = 120 s limit): $(tail -1 $e | cut -c1-200) $(tail -1 $o | cut -c1-200)"; fi
  rm -f $o $e
}
# Wait (<= 9 min) for a background claude -p started by this script; never a standalone sleep.
main_wait() {
  $VV/bin/python -I -c 'import os, sys, time
try:
    pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError):
    print("STOP: no pid file", sys.argv[1] + "; run the previous step first"); sys.exit(2)
deadline = time.time() + 540
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("Main claude -p", pid, "ended"); sys.exit(0)
    time.sleep(5)
print("Main claude -p", pid, "still running after 9 min"); sys.exit(1)' $1
}
probe() { (cd $P && clean0 VERIFY461_NO_MODEL=${VERIFY461_NO_MODEL:-} VERIFY461_AGENT_DIR=$AGENT_DIR \
    ${VERIFY461_SANDBOX_PYTHON:+VERIFY461_SANDBOX_PYTHON=$VERIFY461_SANDBOX_PYTHON} \
    ${VERIFY461_SANDBOX_PATH:+VERIFY461_SANDBOX_PATH=$VERIFY461_SANDBOX_PATH} $VV/bin/python -I $SD/probe.py "$@") }
# STOP, changing nothing, while an earlier run's Main or a 'sleep 1461' still lives. Signals nothing.
guard() { clean0 $CONDA -I $SD/probe.py idle $OUT - }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  guard || return 1
  print "claude --version: $($(claude_bin) --version 2>&1 | head -1)   (expected 2.1.323)"
  print "pi --version: $($(command -v pi || print pi) --version 2>&1 | head -1)   (expected 1.4.0)"
  print "BASE $BASE | OUT $OUT"
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC $BASE/scratch; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import inspect, graftling.pi.execution as e, graftling.pi.driver as p
import graphtraj.execution.agent_driver as d, graphtraj.runtimes.pi.managed_session as m
print("pi execution:", e.__file__)
print("461 fix: Pi owner samples:", "DescendantSampler" in inspect.getsource(e.PiExecution.__init__),
      "| Pi owner stops recorded:", "stop_tool_processes" in inspect.getsource(e.PiExecution.run),
      "| PiDriver records it:", "tool_descendants" in inspect.getsource(p.PiDriver.start),
      "| agents driver records it for pi:", "\"pi\") else None" in inspect.getsource(d.AdapterDriver.start).replace(chr(39), chr(34)),
      "| GraphTraj Pi owner inherits:", issubclass(m.PiManagedExecution, e.PiExecution))') || return 1
  say "isolated project $P (git, graphtraj setup, a 'pi' role on the user's Pi connection, Claude host configuration)"
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  # .claude/settings.json is in the initial commit, so dev (setup) and every member worktree carry it.
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 461 probe" > README.md \
      && $VV/bin/python -I $SD/probe.py claude_settings $P - && git add README.md .claude/settings.json \
      && git -c user.name=461 -c user.email=461@invalid commit -qm "Initial source" \
      && print "committed: $(git ls-files .claude)") || return 1
  (cd $P && print y | clean0 $VV/bin/graphtraj setup | tail -2) || return 1
  say "Pi values the child uses (read only; key variables by name and set/unset only)"
  probe prepare $P $MODEL || { print "STOP: the Pi values, the sandbox or the probe Task are not ready (text above)"; return 1; }
  say "isolation: the project is its own root; context files a Pi child would load (probe-only deny_read)"
  probe isolation $P - || { print "STOP: the project or the Pi child's context is not isolated (text above)"; return 1; }
  print "key variables passed to the probe's processes (names only): ${(j: :)${(@)${(f)$(kept)}%%=*}:-none}"
  [[ -n ${VERIFY461_NO_MODEL:-} ]] && { print "VERIFY461_NO_MODEL set: stopping before Claude Code and Pi (rehearsal)."; return 0; }
  local C=$(claude_bin)
  [[ -f $BASE/settings.local.json.keep ]] && mkdir -p $P/.claude && cp -p $BASE/settings.local.json.keep $P/.claude/settings.local.json
  (cd $P && clean0 $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write) || return 1
  say "host answers MODEL OK and lists its instruction files with $MODEL (login and Claude context check; no tool)"
  (cd $P && clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      <<< "$($VV/bin/python -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import probe; print(probe.CLAUDE_CHECK_PROMPT)' $SD)" \
      > $OUT/00-model-stream.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  $VV/bin/python -I $SD/probe.py claude_check $OUT/00-model-stream.jsonl $P \
      || { print "STOP: no MODEL OK, $P's settings did not turn cc-plugin-agents-md off, or Claude was given a CLAUDE.md/AGENTS.md outside the project (above). stderr:"; head -c 300 $OUT/00-model-stderr.txt; print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "Pi answers one line with deepseek/deepseek-flash (scratch agent dir, key from the environment; the user's ~/.pi is never written)"
  # Pi's startup migrations write settings.json and auth.json in its agent dir, so never point it at ~/.pi here.
  mkdir -p $BASE/scratch/pi-home
  local PIB=$(command -v pi); print "pi: $PIB ($($PIB --version 2>&1 | head -1))"
  if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then
    # one_line execs an executable (perl), never a shell function such as clean: run this script's _pi1 step.
    one_line "pi deepseek-flash" /bin/zsh $THIS _pi1
  else
    print "pi check SKIPPED: DEEPSEEK_API_KEY not set in Main's shell; the child's own login is proven by 01"
  fi
  say "plugin check: the init record must list graphtraj-claude-host"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"
    return 1
  fi
  print "Success: claude 2.1.323, pi 1.4.0, the '461 fix:' line all True, deps click 8.5.0, connection resolved, srt listed,"
  print "'sandbox available: YES', 'roles OK', 'task 1 ready', 'isolation: OK', 'Pi child context isolated: YES',"
  print "'claude memory from the Harness: none', 'Claude context isolated: YES', 'pi deepseek-flash OK: PI OK' (or 'pi check SKIPPED'), 'graphtraj-claude-host loaded: YES'."
  next "zsh $THIS 01"
}

# Private: 00's one Pi line (scratch agent dir, key from the environment), run through one_line.
step__pi1() {
  clean PI_CODING_AGENT_DIR=$BASE/scratch/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
      $(command -v pi) --print --no-tools --no-session --provider deepseek --model deepseek-flash 'Reply with exactly: PI OK'
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: folder trust is recorded only through this dialog; claude -p never asks, and Main must not edit ~/.claude.json."
  next "Main: zsh $THIS 00"
}

step_01() {
  say "[01] Main. starts the probe Main in the background. Dialog: none. Returns at once; then run 02."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  guard || return 1
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  local C=$(claude_bin) S=$OUT/01-main-stream.jsonl
  rm -f $PID01
  # Call 1 leaves the orphan in the background and ends (3 s let the 1 s sampler record it); call 2 still runs at
  # the kill. Pi's own abort on shutdown stops only the running call's group, never the orphan (round 1, 02b).
  # No nohup: Pi SIGKILLs groups (utils/shell.js:189-213), and macOS nohup fails without a console.
  local child='Use the bash tool to run exactly: sleep 1461 >/dev/null 2>&1 & sleep 3 . Then use the bash tool again to run exactly: sleep 1200 . Then reply DONE-461.'
  print -r -- "child instruction: $child"
  local member="Use only the agents tool (mcp__agents__agents). Execute feature create with arguments {\"runtime\": \"pi\", \"instruction\": \"$child\"}. Reply with the one line CREATE <agent> <execution> from its result and end your turn at once. Do not call wait or status. Read no files and run no shell command yourself."
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  print -r -- "$swarm" > $OUT/01-swarm-arguments.json
  local W="$VV/bin/python $SD/probe.py child $P 100"
  print -r -- "1. Call mcp__agents__tasks once with exactly these arguments: $swarm
Print its raw result text on one line starting with SWARM-RESULT.
2. Send nothing to the member. Run this exact Bash command, one call after another, until one prints CHILD-RUNNING (the member created by this dispatch ended its turn, its Pi child runs and the child's background sleep 1461 lives), at most 5 times: $W
3. Print CHILD-RUNNING (or CHILD-NOT-RUNNING after 5 calls) and stop. Do not retire, interrupt or message anything." > $OUT/01-main-prompt.txt
  # The dispatch record (time; the stream holding the swarm result's alias) selects the member in 'probe child/kill'.
  probe dispatch $P $S | tee $OUT/01-dispatch.txt || return 1
  print "prompt: $OUT/01-main-prompt.txt"
  (cd $P && clean nohup $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      --allowedTools "mcp__agents__tasks,Bash($W)" < $OUT/01-main-prompt.txt > $S 2> $OUT/01-main-stderr.txt &
   print $! > $PID01)
  print "Main claude -p pid $(cat $PID01) (in $PID01), stream $S"
  print "Timeline: orphan 'sleep 1461' lives about t0+2..t0+26 min, running 'sleep 1200' about t0+3..t0+23 min (t0 = now)."
  print "Run 02 now: it waits (<= 9 min) for this Main and kills at once; if it says 'still running', rerun 02 once."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. waits for 01's Main (<= 9 min); prints the recorded chain, kills the child's owner and Runtime, CHECK 0, one reconciling read, CHECK 1-4. Dialog: none."
  if [[ -n ${VERIFY461_NO_MODEL:-} ]]; then
    print "VERIFY461_NO_MODEL set: stub member and child instead of 01 (rehearsal)."
    probe stub $P ${VERIFY461_STUB_CASE:--} || return 1
  else
    main_wait $PID01
    case $? in
      0) ;;
      1) print "STOP: rerun 02 later (01's Main still runs)"; return 1 ;;
      *) return 1 ;;
    esac
    grep -o 'CHILD-RUNNING\|CHILD-NOT-RUNNING' $OUT/01-main-stream.jsonl | sort | uniq -c
  fi
  probe child $P 1
  say "Claude context facts (read only): 01 Main's and the member's init plugins; settings.json in the member's cwd"
  probe claude_facts $P $OUT
  probe kill $P $OUT/02-kill.json
  local rc=$?
  print ""
  print "Success: 'summary: ALL PASS' (5 checks). 0 after the owner kill and before the read the recorded 'sleep 1461'"
  print "is alive outside the Runtime group ('NOT OBSERVED' otherwise: the path was not exercised, not a pass);"
  print "1 child failed/owner-exited; 2 escaped_processes lists 'sleep 1461' and every recorded process alive after the"
  print "kill as stopped, remaining []; 3 none of the recorded descendants and no 'sleep 1461' alive; 4 the three"
  print "bystanders alive (then stopped by the probe). A STOP line means nothing was signalled; the 'member:' line"
  print "says which member was selected and why."
  next "zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV > $OUT/03-suite.txt 2>&1 || { cat $OUT/03-suite.txt; return 1; }
  cat $OUT/03-suite.txt
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee -a $OUT/03-suite.txt
  rm -rf $OUT/03-shards
  (cd $WT && nohup zsh $THIS _03run >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time): tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows '== totals:'; failing IDs are in $OUT/03-shards/failures.txt."
}

step__03run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit.
  clean0 $SV/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $OUT/03-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $OUT/03-suite.txt | tail -1)"
  print "== baseline: compare with the dev full-suite run Main last used (461 base b3d522ad)"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  _pi1) step__pi1 ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
