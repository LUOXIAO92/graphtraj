#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 531 Main-run steps (modelled on verify-518 and adopt-528). Run one step at a time:  zsh <this file> <STEP>
#   0   Main. Preflight + fresh read-only census of every per-project store (stat and line counts only), then the
#       BEFORE scratch venv (c917f5fc + production graftling + prof531) and its isolated project under
#       /private/tmp/cpu-531, one-line claude -p answer. Dialog: none. ~2 min.
#   S   Main. BEFORE at production scale, profiled: production's Worldline event count (synthetic, verify-501 seed)
#       and a sanitized copy of production's Runner Session and agents records (verify-518 clone); a Runner-dispatched
#       Claude member creates an agents child (verify-501 probe). Per phase start/pre30/post30/child/after the Worker
#       CPU (ps) and prof531's per-call table (own-thread CPU of named readers, by caller). Dialog: none. <12 min.
#   T   Main. The same at AFTER (VERIFY531_AFTER, default this Worktree's HEAD), then BEFORE vs AFTER. <12 min.
#   X   rehearsal without the host: build BEFORE and scale it; dispatches nothing.
#   G   Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min), graftling wheel built
#       from git archive of <Harness>/graftling at v0.6.2 (production's graftling); new pytest temp root outside the
#       Harness. VERIFY531_TESTS=<files> runs plain pytest on those files instead (rehearsal of the entry).
#   Gt  Main. The focused 531 tests and the 459/495/496/498/501 guarantee tests through G's venv, foreground (~3 min).
#   GR  Main. Read only: newest G and Gt; every FAILED/ERROR line classed known (528's accepted G, 516) or NEW.
#   U   USER, only if S or T reports a folder-trust or login refusal.
# No production install: .venv-runtime is only read (graftling, click, yaml, websockets copied out); production
# records are only read (census: stat; S/T: copied, then rewritten in the copy). Venvs under <Harness>/tmp/531,
# projects under /private/tmp/cpu-531. No step signals a process it did not start.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY531_T:-$H/tmp/531}               # the VERIFY531_T/PR/OUT overrides are for the Engineer's rehearsal only
PR=${VERIFY531_PR:-/private/tmp/cpu-531}
OUT=${VERIFY531_OUT:-$H/.graphtraj/core/state/tasks/531-child-create-runner-record-walk/realhost}
G=$H/graftling
GCOMMIT=4a002129f8b97f32980afd59e5a1a64c428fe684   # graftling v0.6.2 = production's (528)
SD=${0:A:h}
SD501=${SD:h}/verify-501
SD518=${SD:h}/verify-518
THIS=${0:A}
BEFORE_COMMIT=c917f5fc
AFTER_COMMIT=${VERIFY531_AFTER:-$(git -C $WT rev-parse --short HEAD)}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
MODEL=claude-opus-5-5
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN528=$H/.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/G-8267f9e5-20261119T235550/suite.txt
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
FOCUSED=(tests/test_claude_resource_grants_531.py)
GUARANTEES=(${(f)"$(cd $WT && print -l tests/*459*.py(N) tests/*495*.py(N) tests/*496*.py(N) tests/*498*.py(N) tests/*501*.py(N))"})
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP LANG=${LANG:-en_US.UTF-8} "$@"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
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
probe518() { local L=$1; shift; (cd $(project $L) && clean $(venv $L)/bin/python -I $SD518/probe518.py "$@") }
probe531() { local L=$1; shift; (cd $PYTEST_TMP && clean $(venv $L)/bin/python -I $SD/probe531.py "$@") }
claude_version() { print -r -- "claude --version: $(claude --version 2>&1 | head -1) ($(command -v claude || print none))"; }

build() {  # $1 label, $2 commit: scratch venv (graftling copied from production) + isolated project
  local S=$T/src-$1 V=$(venv $1) P=$(project $1)
  say "$1: scratch venv from $2 + graftling from $RT/graftling + prof531 (writes $T/prof-$1)"
  git -C $WT cat-file -e $2^{commit} || { print "STOP: $2 is not in $WT"; return 1; }
  rm -rf $S $V $T/prof-$1; mkdir -p $S; git -C $WT archive $2 | tar -x -C $S || return 1
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/graftling $RT/graftling-*.dist-info(N) $D/ || return 1
  copy_deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S 2>&1 | grep -vi cache
  sed "s|@OUT@|$T/prof-$1|" $SD/prof531.py > $D/prof531.py && print 'import prof531' > $D/prof531.pth || return 1
  (cd $PYTEST_TMP && $V/bin/python -I $SD501/probe.py imports $S - | sed 's/prof501: not installed/prof501: not used (531 uses prof531)/') \
      || { print "STOP: the $1 venv does not import $S"; return 1; }
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import importlib.util; s = importlib.util.find_spec("prof531"); print("profiler hook prof531:", s.origin if s else "NOT INSTALLED")')
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
  (cd $P && git init -q -b main && print -r -- "# 531 probe" > README.md && git add README.md .claude/settings.json \
      && git -c user.name=531 -c user.email=531@invalid commit -qm "Initial source with Claude settings") || return 1
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
  [[ -f $OUT/$1.json ]] && probe531 $1 phases $OUT/$1.json $(project $1)
  return $rc
}

# G's venv (also Gt's): conda --system-site-packages + production's click/yaml/websockets + graftling wheel built
# from git archive $GCOMMIT (never the working tree) + this Worktree editable. Sets V.
g_venv() {
  local GS=${GCOMMIT[1,8]}
  local SRC=$T/graftling-$GS N=$T/wheels-gl-$GS
  V=$T/venv-g-gl-$GS
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V (graftling $GS; this Worktree editable)"
  else
    rm -rf $SRC $N $V && mkdir -p $SRC && git -C $G archive $GCOMMIT | tar -x -C $SRC || { print "STOP: cannot extract graftling"; return 1; }
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $SRC/src/graftling >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT 2>&1 | grep -vi cache
    print -r -- $GCOMMIT > $V/installed
  fi
}
# A new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-531-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
g_common() {  # guard + venv + imports
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  print "uncommitted in src/tests/plugins: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  new_runtmp $1 || return 1
  g_venv || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT"
}
classify() {  # FAILED/ERROR lines of files $@ as known (528's accepted G, 516) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $KNOWN528 2>/dev/null; then print -r -- "known (528 accepted G; 529 fixed it in this base): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

run_step() {
case $STEP in
0)
  say "[0] Main. Preflight + census. Dialog: none. ~2 min."
  claude_version; print "zsh: $ZSH_VERSION ($THIS)"
  print "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | BEFORE $BEFORE_COMMIT | AFTER $AFTER_COMMIT"
  print -r -- "production graftling: $(grep -m1 '^Version' $RT/graftling-*.dist-info/METADATA) ($RT/graftling)"
  check_tmp && quiet || return 1
  say "production census (read only: stat and line counts)"
  (cd $PYTEST_TMP && clean $H/.venv-runtime/bin/python -I $SD/probe531.py census $H -) || return 1
  build before $BEFORE_COMMIT || return 1
  say "host answers one line with $MODEL in the BEFORE project (model and login source name from the init record)"
  (cd $(project before) && clean claude -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config \
      --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' \
      > $OUT/0-model.jsonl 2> $OUT/0-model-stderr.txt)
  print "claude -p rc=$?"
  probe before init $OUT/0-model.jsonl $H || { print "STOP: no MODEL OK or no init record (above). stderr:"
      head -c 300 $OUT/0-model-stderr.txt; print "\nIf it names a login or folder trust: USER step: zsh $THIS U"; return 1; }
  print "Success: census lines (Worldline, Runner Sessions by kind, agents records, archives, every store under"
  print ".graphtraj/core/runner, core/state, swarm, swarm/control), 'under ...: True', 'graftling: ... 0.6.2',"
  print "'profiler hook prof531: ...', 'roles OK', 'probe Task ready: YES', 'isolation: OK', 'result: MODEL OK | MEMORY: NONE'."
  print -r -- "next: zsh $THIS S"
  ;;
S|T)
  local L=before C=$BEFORE_COMMIT
  [[ $STEP == T ]] && { L=after; C=$AFTER_COMMIT; }
  say "[$STEP] Main. $L ($C + production graftling) at production scale, profiled. Dialog: none (U if refused). <12 min."
  check_tmp && quiet || return 1
  [[ $STEP == T && ! -f $OUT/before.json ]] && { print -r -- "STOP: run S first"; return 1; }
  claude_version
  build $L $C || return 1
  scale $L || return 1
  member $L; local rc=$?
  (( rc == 2 )) && { print -r -- "rerun this step for a fresh project"; return $rc; }
  [[ $STEP == T ]] && probe531 after compare $OUT/before.json $OUT/after.json
  print "Success: 'seeded N synthetic events', 'cloned ... Runner Session directories', raw ps lines, '== ${(U)L} phases'"
  print "with start/pre30/post30/child/after, and '== ${(U)L} per-call table' with a function table per phase."
  [[ $STEP == S ]] && print -r -- "next: report $OUT/S.txt to the Leader (then, once the Leader names AFTER: zsh $THIS T)" \
                   || print -r -- "next: zsh $THIS G  (background ~25 min; then zsh $THIS Gt and zsh $THIS GR)"
  ;;
X)
  say "[X] rehearsal without the host: build BEFORE and scale it; dispatches nothing. Dialog: none."
  check_tmp || return 1
  build before $BEFORE_COMMIT && scale before || return 1
  print -r -- "rehearsal OK: $(project before)"
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V RUNTMP; g_common G || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY531_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY531_TESTS (plain pytest, same venv, temp root and exit file)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY531_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  else
    (cd $WT && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  fi
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.2 ...', 'started in the background'."
  print -r -- "next: zsh $THIS Gt  (after G ends: zsh $THIS GR)"
  ;;
Gt)
  say "[Gt] Main. Focused 531 tests + the 459/495/496/498/501 guarantee tests via G's venv, foreground. Dialog: none. ~3 min."
  local V RUNTMP; g_common Gt || return 1
  local R=$OUT/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED $GUARANTEES" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt $FOCUSED $GUARANTEES > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  tail -3 $R/suite.txt; classify $R/suite.txt
  print -r -- $R > $OUT/Gt-latest
  print "Success: 'N passed' with exit=0 and '(no FAILED/ERROR lines)'."
  print -r -- "next: zsh $THIS GR  (when G's suite.txt ends with exit=)"
  ;;
GR)
  say "[GR] Main. Read only. Newest G and Gt; FAILED/ERROR lines classed known (528 accepted G, 516) or NEW. <10 s."
  local g=$(cat $OUT/G-latest 2>/dev/null) t=$(cat $OUT/Gt-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify $t/suite.txt; }
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line in G or Gt."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
U)
  say "[U] USER, only if S or T reported a folder-trust or login refusal. Plain macOS Terminal:"
  claude_version
  print -r -- "  cd $(project before) && claude      (for T: $(project after))"
  print "Dialog: 'Do you trust the files in this folder?' naming that project: choose 'Yes, proceed', then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message."
  print -r -- "next (Main): the refused step again (zsh $THIS S or T)"
  ;;
*) print -r -- "usage: zsh $THIS 0|S|T|X|G|Gt|GR|U" ; return 2 ;;
esac
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT $PR
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
