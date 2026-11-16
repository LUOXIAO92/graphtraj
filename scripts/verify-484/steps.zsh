#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 484: 401 for an INTERACTIVE Codex Main started on Codex's shared background server, in a FRESH isolated
# project under the Harness tmp/484, with the candidate installed into an isolated venv under tmp/484.
# Production .venv-runtime is only read (its dependencies are linked, never changed); production Main is never yielded.
#   zsh <this file> <00|I1|I2|S|F>
# Order: 00 -> I1 (the only USER step: interactive Codex, one pasted prompt) -> I2 (judge, Codex still open) -> S -> F.
# 00 needs no project trust and no Main claim; the first trust happens in I1.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY484_BASE:-$H/tmp/484}
P=$BASE/project
V=$BASE/venv
VT=$BASE/venv-test
DEPS=$BASE/deps
OUT=${VERIFY484_OUT:-$H/.graphtraj/core/state/tasks/484-codex-main-root-agent-end-delivery/realhost}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
PY=$V/bin/python
MODEL=claude-opus-5-5
CODEX_MODEL=gpt-6-luna
CODEX_HOME_USED=${CODEX_HOME:-$HOME/.codex}
STEP=${1:-help}
path=($V/bin /opt/homebrew/bin $HOME/.local/bin ${path:#$RT/bin})
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY484_CLAUDE:-} ]] && { print -r -- $VERIFY484_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
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
  print -r -- $DEPS > $($dir/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/484-deps.pth
  clean $dir/bin/python -m pip install -q --no-deps --no-build-isolation --no-index "$@" 2>&1 | grep -vi cache
  return ${pipestatus[1]}
}
CREATE="{\"action\":\"execute\",\"feature\":\"create\",\"arguments\":{\"runtime\":\"claude\",\"configuration\":\"advisor\",\"name\":\"h484\",\"instruction\":\"Reply with exactly one line: PONG-h484. Use no tools.\"}}"
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
  [[ -s $OUT/00-production-main.txt || -n ${VERIFY484_NO_MODEL:-} ]] || { print "STOP: production continuity record unreadable; F could not compare"; return 1; }
  say "isolated candidate venv $V (commit $commit; dependencies linked read-only from $RTSP)"
  if [[ $(cat $V/.candidate 2>/dev/null) != $commit ]]; then
    rm -rf $BASE/candidate && mkdir -p $BASE/candidate && git -C $SRC archive $commit | tar -x -C $BASE/candidate || return 1
    make_venv $V $BASE/candidate/src/graftling $BASE/candidate || { print "STOP: candidate install failed (text above)"; return 1; }
    print -r -- $commit > $V/.candidate
  else print "venv already holds $commit: install skipped (rerun)"; fi
  clean $PY -I -c 'import sys, graphtraj, graftling
from importlib.metadata import entry_points
ok = all(m.__file__.startswith(sys.argv[1]) for m in (graphtraj, graftling))
print("candidate imports:", graphtraj.__file__, graftling.__file__, "| under venv:", ok)
print("graftling.hosts:", [e.value for e in entry_points(group="graftling.hosts")]); sys.exit(0 if ok else 1)' $V \
    || { print "STOP: the venv does not import the candidate"; return 1; }
  print "graphtraj-mcp: $(ls $V/bin/graphtraj-mcp 2>&1)"
  say "fresh isolated project $P (own git repo, so Codex reads no Harness AGENTS.md)"
  if [[ -d $P/.git ]]; then print "existing project $P: git init and graphtraj setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 484 probe README first line" > README.md && git add README.md \
      && git -c user.name=484 -c user.email=484@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  probe prepare $P; local prc=$?
  [[ $prc == 0 ]] || { print "STOP: probe.py prepare rc=$prc (2 register/update, 3 roles, 4 Task 1 not ready; text above)"; return 1; }
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  say "Claude host configuration for the advisor member; Harness AGENTS.md/CLAUDE.md excluded"
  (cd $P && clean $PY -m graphtraj.runtimes.claude.host configuration --project $P --claude $(claude_bin) --write) || return 1
  $PY -I -c 'import json, sys
from pathlib import Path
h, path = sys.argv[1], Path(sys.argv[2])
s = json.loads(path.read_text()) if path.is_file() else {}
s["claudeMdExcludes"] = sorted({*s.get("claudeMdExcludes", []), *(h + x for x in ("/CLAUDE.md", "/CLAUDE.local.md",
    "/.claude/CLAUDE.md", "/**/CLAUDE.md", "/**/CLAUDE.local.md", "/AGENTS.md", "/**/AGENTS.md"))})
s["enabledPlugins"] = {**s.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(s, indent=2) + "\n")
print("claudeMdExcludes set in", path)' $H $P/.claude/settings.local.json || return 1
  say "Codex project files in $P/.codex: hooks (graphtraj.runtimes.codex.finalize.hook) and the graphtraj MCP server in config.toml"
  print "(no -c on the interactive command: Codex runs a Session with -c/--enable/--disable/--search without the shared background server)"
  mkdir -p $P/.codex
  (cd $P && clean $PY -I -c 'import json
from pathlib import Path
from graphtraj.runtimes.codex.finalize import hook
Path(".codex/hooks.json").write_text(json.dumps(hook(Path("."), {}), indent=2) + "\n"); print("wrote .codex/hooks.json")') || return 1
  print -r -- "[mcp_servers.graphtraj]
command = \"$V/bin/graphtraj-mcp\"
args = []
cwd = \"$P\"
default_tools_approval_mode = \"approve\"" > $P/.codex/config.toml
  print "wrote $P/.codex/config.toml:"; sed 's/^/    /' $P/.codex/config.toml
  say "(b) the GraphTraj MCP entry the interactive Main uses: the server exactly as $P/.codex/config.toml names it (initialize, tools/list, tasks task_graph; no model, limit 60 s)"
  (cd $P && clean /usr/bin/perl -e 'alarm 60; exec @ARGV' $PY -I $SD/probe.py mcp $P/.codex/config.toml) \
    || { print "STOP: the graphtraj MCP entry does not serve (text above)"; return 1; }
  [[ -n ${VERIFY484_NO_MODEL:-} ]] && { print "VERIFY484_NO_MODEL set: stopping before any model or host call (rehearsal)."; return 0; }

  local ASK='Reply with exactly three lines. Line 1: MODEL OK. Line 2: MODEL: your model name. Line 3: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'
  print -r -- "$ASK" > $OUT/00-ask.txt
  say "(a) codex login; codex exec $CODEX_MODEL one-line answer (limit 300 s); claude -p (the advisor's host; limit 300 s). Neither shows a dialog."
  if clean codex login status 2>&1 | grep -q 'Logged in'; then print "codex logged in: YES"; else print "codex logged in: NO"; fi
  (cd $P && limit 300 codex exec -m $CODEX_MODEL --sandbox read-only - < $OUT/00-ask.txt > $OUT/00-codex.txt 2>&1)
  (cd $P && limit 300 $(claude_bin) -p --model $MODEL --output-format json --mcp-config $P/.mcp.json --strict-mcp-config < $OUT/00-ask.txt > $OUT/00-claude.txt 2>&1)
  for host in codex claude; do
    local f=$OUT/00-$host.txt ok=BLOCKED leak=""
    grep -q 'MODEL OK' $f && ok=OK
    grep -oE "$H/[^ \"]*(AGENTS|CLAUDE)\.md" $f | grep -v "^$P/" | head -1 | read leak
    print "$host answer: $ok | model line: $(grep -oE 'MODEL: [^\"\\]*' $f | head -1) | Harness instruction file loaded: ${leak:-none}"
    [[ $ok == OK ]] || { print "raw $host error (tail):"; tail -5 $f; }
  done
  say "(c) codex app-server proxy (send_event's channel): one read-only thread/loaded/list, CODEX_HOME $CODEX_HOME_USED (limit 60 s)"
  probe daemon $CODEX_HOME_USED \
    || print "note: a connect failure here can mean the shared background server is not running yet; I1's interactive codex starts it, I2 asks again"
  print "Success: 'under venv: True', roles OK, task 1 ready, 'project own: True', 'MCP initialize: OK', 'tools agents and tasks served: YES',"
  print "'task_graph shows probe Task 1: YES', 'codex logged in: YES', both 'answer: OK' with 'loaded: none', and the proxy line (YES, or NO with the note)."
  next "USER step: zsh $THIS I1   (prints what the user runs and pastes)"
}

step_I1() {
  $PY -I -c 'import time; print(time.time())' > $OUT/I1.start
  print -r -- "Using only the graphtraj agents tool: call it once with exactly $CREATE; print one line H484-CREATE <agent id>. Do not call wait or status for it, and end your turn. When a GraphTraj notice about it arrives later, quote its alias, event and execution on one line starting with H484-NOTICE and stop." > $OUT/I1-prompt.txt
  say "[I1] the only USER step, in your own macOS Terminal. Dialog: Codex's first-launch trust for this fresh project, shown together at the first start (the one unavoidable exception):"
  print "     first 'Do you trust the contents of this directory?' for $P -> 'Yes'; then the hook review for $P/.codex/hooks.json -> approve."
  print "     No other dialog should appear (the graphtraj tools are pre-approved in $P/.codex/config.toml)."
  print "  1. cd $P && codex -m $CODEX_MODEL"
  print "     (exactly this: no -c or other options. If Codex prints 'Running without the shared background server: ...', copy that line to Main.)"
  print "     If after trusting, the startup does not show 'GraphTraj Main Session associated' or the graphtraj tool is missing: /exit and run the same command once more."
  print "  2. paste this one prompt (also in $OUT/I1-prompt.txt):"
  print -r -- "$(cat $OUT/I1-prompt.txt)"
  print "  3. wait until a new turn starts by itself and prints H484-NOTICE, or 3 minutes; wait one more minute (a second delivery would show)."
  print "  4. keep Codex OPEN and tell Main 'I1 done' (I2 asks the shared server whether this Session is loaded); /exit after Main's I2 has printed."
  next "zsh $THIS I2 2>&1 | tee $OUT/I2.txt"
}

step_I2() {
  say "[I2] read only (the user's Codex still open): 401 by event identity, the push's recorded result and failure reason, and whether the Main Session is on the shared background server. Dialog: none."
  local start=$(cat $OUT/I1.start 2>/dev/null || print 0)
  local claim=$($PY -I -c 'import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / ".graphtraj/runner/main-sessions/continuity.jsonl"
c = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []
c = [x for x in c if x.get("runtime") == "codex" and float(x.get("at", 0)) >= float(sys.argv[2])]
print(c[-1]["session"], (c[-1].get("connection") or {}).get("codex_home", "")) if c else print("")' $P $start)
  local thread=${claim%% *} home=${claim#* }
  print "interactive Codex Main thread (codex claim after I1): ${thread:-NONE} | its CODEX_HOME: ${home:-NONE}"
  [[ -n $thread ]] || { print "FAIL I entry: no codex continuity claim since I1 (hooks not trusted, or I1 not run)"; probe claims $P; return 1; }
  probe daemon ${home:-$CODEX_HOME_USED} $thread
  probe agent $P h484
  probe rollout $P h484 $thread ${home:-$CODEX_HOME_USED}
  print ""
  print "USER: you may now /exit the Codex Session."
  next "zsh $THIS S 2>&1 | tee $OUT/S.txt"
}

step_S() {
  say "[S] full suite of the candidate checkout $SRC ($(git -C $SRC rev-parse HEAD)) in its own test venv $VT. Dialog: none. Limit 1800 s."
  make_venv $VT -e $SRC/src/graftling -e $SRC || { print "STOP: test venv install failed (text above)"; return 1; }
  local tmp=${TMPDIR:-/tmp}
  print "pytest temp base: ${tmp:A} | outside the Harness $H: $([[ ${tmp:A} != $H* ]] && print YES || print NO)"
  [[ ${tmp:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
  local cmd=(env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$VT/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$tmp LANG=${LANG:-en_US.UTF-8}
             /usr/bin/perl -e 'alarm 1800; exec @ARGV' $VT/bin/python -m pytest -p no:cacheprovider -q)
  print "command (in $SRC): ${(q)cmd[@]}"
  [[ -n ${VERIFY484_NO_MODEL:-} ]] && { print "VERIFY484_NO_MODEL set: test venv ready, suite not run (rehearsal)."; return 0; }
  (cd $SRC && $cmd | tail -40; print "pytest exit: ${pipestatus[1]}")
  next "zsh $THIS F 2>&1 | tee $OUT/F.txt"
}

step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $SD/probe.py main $H ${rt:-none} ${sess:-none})
  if [[ "$(runtime_records)" == "$(cat $OUT/00-production-runtime.txt)" ]]; then print "PASS F production .venv-runtime unchanged: $(runtime_records | tr '\n' ' ')"
  else print "FAIL F production .venv-runtime changed: now $(runtime_records | tr '\n' ' ') / at 00 $(tr '\n' ' ' < $OUT/00-production-runtime.txt)"; fi
  local pids=($OUT/*.pid(N))
  (( ${#pids} )) || print "pids: this script starts no background process (every host call is foreground with a limit)"
  for f in $pids; do
    local pid=$(cat $f)
    if kill -0 $pid 2>/dev/null; then print "STILL RUNNING: ${f:t:r} pid $pid; stop it with: kill $pid"; else print "ended: ${f:t:r} pid $pid"; fi
  done
  print "PASS/FAIL summary:"; grep -hE '^(PASS|FAIL)' $OUT/*.txt(N) | sort | uniq
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt; return ${pipestatus[1]} ;;
  I1|I2|S|F) step_$STEP ;;
  *) print "usage: zsh $THIS <00|I1|I2|S|F>" ;;
esac
}
dispatch; exit $?
