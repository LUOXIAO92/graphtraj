#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 518 Main-run steps. Run one step at a time:  zsh <this file> <STEP>
#   0  preflight: claude --version, quiet host, read-only census of production's records (sizes only), scratch venv
#      BEFORE (81dde17e + production graftling + the prof518 sampler), isolated project under /private/tmp/cpu-518,
#      probe Task ready, one-line claude -p answer (model and login source name)
#   S  BEFORE at production scale, profiled: a fresh BEFORE project gets a synthetic Worldline of production's
#      event count (~4.9 KB each) and a sanitized copy of production's Runner Session records and agents records
#      (paths rewritten into the project, pids 99999, markers blanked, no tool-process records); then verify-501's
#      probe: a Runner-dispatched Claude member
#      creates an agents child (six sleeps ~2.5 min), waits, reads it back, retires it. Worker ps every ~10 s;
#      CPU per phase (start / 30 s before the child's creation / 30 s after / child running / after its end), the
#      busiest functions per phase and the counted whole-record reads (<12 min)
#   T  the same at AFTER (VERIFY518_AFTER, default the Worktree HEAD), then S vs T (<12 min)
#   G  GraphTraj full suite of the Worktree HEAD (background), graftling wheel from <Harness>/graftling
#   R  results of the newest G
#   U  USER, only if S or T reports a folder-trust or login refusal (waits for the user)
# Dialog: none in every Main step. No production install: .venv-runtime is only read (graftling, click, yaml,
# websockets copied out); production records are only read (census: stat and line counts; S/T: copied, then
# rewritten in the copy). Venvs and sources under <Harness>/tmp/518; projects under /private/tmp/cpu-518.
# No step signals a process it did not start.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY518_T:-$H/tmp/518}               # the overrides are for the Engineer's sandbox rehearsal only
PR=${VERIFY518_PR:-/private/tmp/cpu-518}
OUT=${VERIFY518_OUT:-$H/.graphtraj/core/state/tasks/518-worker-cpu-after-child-create/realhost}
G=$H/graftling
SD=${0:A:h}
SD501=${SD:h}/verify-501
THIS=${0:A}
BEFORE_COMMIT=81dde17e
AFTER_COMMIT=${VERIFY518_AFTER:-$(git -C $WT rev-parse --short HEAD)}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
MODEL=claude-opus-5-5
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP LANG=${LANG:-en_US.UTF-8} "$@"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: $PYTEST_TMP (outside the Harness)"
}
quiet() {  # measurements and suites run on a quiet host, one Main step at a time
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS $STEP"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
venv() { print -r -- $T/venv-$1; }
project() { print -r -- $PR/project-$1; }
probe() { local L=$1; shift; (cd $(project $L) && clean $(venv $L)/bin/python -I $SD501/probe.py "$@") }
probe518() { local L=$1; shift; (cd $(project $L) && clean $(venv $L)/bin/python -I $SD/probe518.py "$@") }
claude_version() { print -r -- "claude --version: $(claude --version 2>&1 | head -1) ($(command -v claude || print none))"; }

build() {  # $1 label, $2 commit: scratch venv (graftling copied from production) + isolated project
  local S=$T/src-$1 V=$(venv $1) P=$(project $1)
  say "$1: scratch venv from $2 + graftling from $RT/graftling + prof518 (writes $T/prof-$1)"
  git -C $WT cat-file -e $2^{commit} || { print "STOP: $2 is not in $WT"; return 1; }
  rm -rf $S $V $T/prof-$1; mkdir -p $S; git -C $WT archive $2 | tar -x -C $S || return 1
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/graftling $RT/graftling-*.dist-info(N) $D/ || return 1
  copy_deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S 2>&1 | grep -vi cache
  sed "s|@OUT@|$T/prof-$1|" $SD/prof518.py > $D/prof518.py && print 'import prof518' > $D/prof518.pth || return 1
  (cd $PYTEST_TMP && $V/bin/python -I $SD501/probe.py imports $S - | sed 's/prof501: not installed/prof501: not used (518 uses prof518)/') \
      || { print "STOP: the $1 venv does not import $S"; return 1; }
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import importlib.util; s = importlib.util.find_spec("prof518"); print("profiler hook prof518:", s.origin if s else "NOT INSTALLED")')
  say "$1: isolated project $P (own git, own .graphtraj; Claude settings without the Harness instruction files)"
  case ${P:A}/ in ${H:A}/*) print "STOP: $P is inside the Harness"; return 1 ;; esac
  rm -rf $P; mkdir -p $P
  $V/bin/python -I -c 'import json, sys
from pathlib import Path
harness = sys.argv[1]
for path in map(Path, sys.argv[2:]):
    settings = json.loads(path.read_text()) if path.is_file() else {}
    settings["claudeMdExcludes"] = sorted({*settings.get("claudeMdExcludes", []), harness + "/CLAUDE.md",
        harness + "/CLAUDE.local.md", harness + "/.claude/CLAUDE.md", harness + "/**/CLAUDE.md", harness + "/**/CLAUDE.local.md",
        harness + "/AGENTS.md", harness + "/**/AGENTS.md"})
    settings["enabledPlugins"] = {**settings.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")' $H $P/.claude/settings.json $P/.claude/settings.local.json || return 1
  (cd $P && git init -q -b main && print -r -- "# 518 probe" > README.md && git add README.md .claude/settings.json \
      && git -c user.name=518 -c user.email=518@invalid commit -qm "Initial source with Claude settings") || return 1
  (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  probe $1 prepare $P $MODEL || { print "STOP: the $1 probe Task is not ready (above)"; return 1; }
  probe $1 isolation $P - || { print "STOP: the $1 project is not isolated"; return 1; }
}

scale() {  # $1 label: production-sized Worldline and Runner Sessions in the isolated project
  local P=$(project $1)
  local events=$(cat $H/.graphtraj/core/state/worldline/*.jsonl | wc -l | tr -d ' ')
  say "$1: seeding $events synthetic Worldline events (production has $events) and production's Runner Session and agents records"
  probe $1 seed $P $events || { print -r -- "STOP: seeding the Worldline failed (above)"; return 1; }
  probe518 $1 clone $P $H || { print -r -- "STOP: copying the Runner Session records failed (above)"; return 1; }
  (cd $P && clean $(venv $1)/bin/graphtraj task graph > /dev/null) && print "task graph after seeding: rc=0" \
      || { print "STOP: task graph fails after seeding"; return 1; }
}

member() {  # $1 label
  local F=$OUT/$1-facts.json
  mkdir -p $OUT
  $(venv $1)/bin/python -I -c 'import json, sys; json.dump({"label": sys.argv[2], "out": sys.argv[3], "prof": sys.argv[4]}, open(sys.argv[1], "w"))' \
      $F ${(U)1} $OUT/$1.json $T/prof-$1 || return 1
  probe $1 run $(project $1) $F
  local rc=$?
  [[ -f $OUT/$1.json ]] && probe518 $1 phases $OUT/$1.json $(project $1)
  return $rc
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT $PR
case $STEP in
0)
  { say "[0] preflight. Dialog: none. Output also in $OUT/0.txt"
  claude_version; print "zsh: $ZSH_VERSION ($THIS)"
  print "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | BEFORE $BEFORE_COMMIT | AFTER $AFTER_COMMIT"
  check_tmp && quiet || return 1
  say "production census (read only: stat and line counts)"
  (cd $PYTEST_TMP && clean $H/.venv-runtime/bin/python -I $SD/probe518.py census $H -) || return 1
  build before $BEFORE_COMMIT || return 1
  say "host answers one line with $MODEL in the BEFORE project (model and login source name from the init record)"
  (cd $(project before) && clean claude -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config \
      --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' \
      > $OUT/0-model.jsonl 2> $OUT/0-model-stderr.txt)
  print "claude -p rc=$?"
  probe before init $OUT/0-model.jsonl $H || { print "STOP: no MODEL OK or no init record (above). stderr:"
      head -c 300 $OUT/0-model-stderr.txt; print "\nIf it names a login or folder trust: USER step: zsh $THIS U"; return 1; }
  print "Success: census lines (Worldline, Runner Sessions, agents records, archives), 'under ...: True',"
  print "'graftling: ... 0.6.0', 'profiler hook prof518: ...', 'roles OK', 'probe Task ready: YES', 'isolation: OK',"
  print "'init: ... model $MODEL | apiKeySource <name>', 'result: MODEL OK | MEMORY: NONE'."
  print -r -- "next: zsh $THIS S 2>&1 | tee $OUT/S.txt"
  } 2>&1 | tee $OUT/0.txt
  ;;
S|T)
  local L=before C=$BEFORE_COMMIT
  [[ $STEP == T ]] && { L=after; C=$AFTER_COMMIT; }
  say "[$STEP] $L ($C + production graftling) at production scale, profiled. Dialog: none (U if refused). <12 min."
  check_tmp && quiet || return 1
  [[ $STEP == T && ! -f $OUT/before.json ]] && { print -r -- "STOP: run S first"; return 1; }
  claude_version
  build $L $C || return 1
  scale $L || return 1
  member $L; local rc=$?
  (( rc == 2 )) && { print -r -- "rerun this step for a fresh project"; return $rc; }
  [[ $STEP == T ]] && probe518 after compare $OUT/before.json $OUT/after.json
  print "Success: 'seeded N synthetic events ... one read_worldline', 'cloned ... Runner Session directories', raw ps"
  print "lines, '== ${(U)L} phases' with start/pre30/post30/child/after, and per phase the busiest functions and reads."
  [[ $STEP == S ]] && print -r -- "next: report $OUT/S.txt to the Leader (T follows once the Leader names AFTER)" \
                   || print -r -- "next: zsh $THIS G (full suite), then R"
  ;;
M)
  say "[M] read only, <2 min: one archive-header lookup over production's Session archives. Dialog: none. Output also in $OUT/M.txt"
  { check_tmp || return 1
  print -r -- "load average: $(sysctl -n vm.loadavg) (another run on the host only slows the wall times)"
  (cd $PYTEST_TMP && clean $H/.venv-runtime/bin/python -I $SD/probe518.py archives $H -)
  print "Success: 'Session archives: N, ... GB; first lines ... GB', two 'fresh SessionArchive(root).native_header' lines"
  print "(each a full scan) and one 'reading only each header' line. Nothing is written."
  print -r -- "next: report $OUT/M.txt to the Leader"
  } 2>&1 | tee $OUT/M.txt
  ;;
X)
  say "[X] rehearsal without the host: build BEFORE and scale it; dispatches nothing. Dialog: none."
  check_tmp || return 1
  build before $BEFORE_COMMIT && scale before || return 1
  print -r -- "rehearsal OK: $(project before)"
  ;;
G)
  say "[G] GraphTraj full suite of the Worktree HEAD, graftling as a wheel from $G (6 shards, --timeout 1500, -rA, background). Dialog: none. Returns at once."
  check_tmp && quiet || return 1
  [[ -d $G/src/graftling ]] || { print "STOP: $G/src/graftling missing"; return 1; }
  print "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  git -C $WT diff --quiet HEAD -- || { print "STOP: tracked changes in $WT are uncommitted"; return 1; }
  local C=$(git -C $WT rev-parse --short HEAD)
  local V=$T/venv-gt-$C N=$T/wheels-gt-$C R=$OUT/G-$C-$(date +%H%M%S)
  if [[ -x $V/bin/python ]]; then
    print "reusing $V (made for $C)"
  else
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $G/src/graftling >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      $N/graftling-*.whl -e $WT 2>&1 | grep -vi cache
  fi
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $R
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print -r -- "next, when it ends: zsh $THIS R"
  ;;
R)
  say "[R] results. Dialog: none."
  local g=($OUT/G-*(N/om[1]))
  (( $#g )) || { print -r -- "no G result under $OUT yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- $g"
  [[ -f $g/suite.txt ]] || { print -r -- "(no suite.txt yet)"; return 0; }
  tail -8 $g/suite.txt
  print "failed/error lines:"
  grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sort -u || print "(none)"
  print -r -- "next: report $g to the Leader"
  ;;
U)
  say "[U] USER, only if S or T reported a folder-trust or login refusal. Plain macOS Terminal:"
  claude_version
  print -r -- "  cd $(project before) && claude      (for T: $(project after))"
  print "Dialog: 'Do you trust the files in this folder?' naming that project: choose 'Yes, proceed', then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message."
  print -r -- "next (Main): the refused step again (zsh $THIS S or T)"
  ;;
*) print -r -- "usage: zsh $THIS 0|S|T|G|R|U" ; return 2 ;;
esac
