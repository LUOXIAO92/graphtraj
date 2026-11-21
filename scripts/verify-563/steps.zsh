#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 563 Main-run steps (modelled on verify-531 G/GR). Run one step at a time:  zsh <this file> <STEP>
#   pre   Main. Preflight: shell, paths, graftling commit, TMPDIR outside the Harness, clean candidate. Dialog: none. <10 s.
#   demo  Main. Copies production Task state (read only: Worldline, task index, every Task's task.yml, task.md and
#         definitions/; not Team reports or Traces) to <Harness>/tmp/563/demo/h/.graphtraj/core/state
#         with a minimal config.yml, hashes every Task's versions, runs the candidate's public
#         `graphtraj migrate-task-definitions --preview`, then the migration, then the same command again
#         (must report nothing left), hashes again and compares: PASS/FAIL per check. Dialog: none. ~3 min.
#   G     Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a venv with the
#         graftling wheel built from git archive of <Harness>/graftling v0.6.2 (production's graftling); new pytest
#         temp root under TMPDIR=${TMPDIR:-/tmp}, outside the Harness. VERIFY563_TESTS=<files> runs plain pytest on
#         those files instead (rehearsal of the entry).
#   GR    Main. Read only: newest G; every FAILED/ERROR line classed known (528's accepted G, or 516's CURRENT
#         definition read through 516's task.yml current_definition) or NEW. <10 s.
# No step raises a native review dialog. Production is only read (demo copies it). Venvs and the demo copy are
# under <Harness>/tmp/563; step output under OUT. VERIFY563_T / VERIFY563_OUT / VERIFY563_PROD are for the
# Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY563_T:-$H/tmp/563}
OUT=${VERIFY563_OUT:-$H/.graphtraj/core/state/tasks/563-versioned-task-definition-files/realhost}
PROD=${VERIFY563_PROD:-$H/.graphtraj/core/state}
G=$H/graftling
GCOMMIT=4a002129f8b97f32980afd59e5a1a64c428fe684   # graftling v0.6.2 = production's (528)
SD=${0:A:h}
THIS=${0:A}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN528=$H/.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/G-8267f9e5-20261119T235550/suite.txt
# 516's CURRENT definition, read through its task.yml (works before and after migrate-task-definitions).
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN516=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
DEMO=$T/demo/h                                      # the demo Harness root (copy)
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP LANG=${LANG:-en_US.UTF-8} "$@"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
quiet() {  # suites run on a quiet host, one Main step at a time
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS $STEP"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 when the base Python lacks them (read only)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $1/bin/python -I -c "import $m" 2>/dev/null && continue
    print -r -- "$m: copied read only from $RT"
    case $m in
      yaml) cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RT/$m $RT/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
g_venv() {  # sets V: venv with the graftling v0.6.2 wheel and this Worktree editable
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
  RUNTMP=${PYTEST_TMP:A}/verify-563-$1-$(date +%Y%m%dT%H%M%S)
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
classify() {  # FAILED/ERROR lines of files $@ as known (528's accepted G, 516's current definition) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $KNOWN528 2>/dev/null; then print -r -- "known (528 accepted G; 529 fixed it in this base): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}
graphtraj_demo() { (cd $DEMO && clean $V/bin/graphtraj "$@") }

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight. Dialog: none. <10 s."
  print "zsh: $ZSH_VERSION ($THIS)"
  print -r -- "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | T=$T | OUT=$OUT | PROD=$PROD"
  check_tmp || return 1
  case ${T:A}/ in ${H:A}/tmp/*|${PYTEST_TMP:A}/*) ;; *) print "STOP: T $T is neither under <Harness>/tmp nor TMPDIR"; return 1 ;; esac
  [[ -d $PROD/tasks && -d $PROD/worldline ]] || { print -r -- "STOP: $PROD has no tasks/ or worldline/"; return 1; }
  print -r -- "production Task directories: $(print -l $PROD/tasks/[^.]*(N/) | wc -l | tr -d ' ') (read only)"
  print -r -- "516 current definition (from task.yml): $KNOWN516"; [[ -f $KNOWN516 ]] || { print "STOP: 516 current definition missing"; return 1; }
  git -C $G cat-file -e $GCOMMIT^{commit} && print -r -- "graftling $GCOMMIT present in $G" || { print "STOP: graftling commit missing"; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins scripts)
  print "uncommitted in src/tests/plugins/scripts: ${dirty:-none}"
  print "Success: 'pytest temp: ... outside the Harness', the 516 path ends in definitions/<time>.md, 'uncommitted ...: none'."
  print -r -- "next: zsh $THIS demo"
  ;;
demo)
  say "[demo] Main. Copy production state, preview, migrate, migrate again, compare hashes. Dialog: none. ~3 min."
  check_tmp || return 1
  local V; g_venv || return 1
  local S=$DEMO/.graphtraj/core/state d
  [[ -e $T/demo ]] && chmod -R u+w $T/demo      # an earlier demo copy keeps read-only modes
  rm -rf $T/demo && mkdir -p $S/tasks || return 1
  # The migration reads and writes only these files; Team reports and Traces are not copied (~2 GB). A link
  # elsewhere that reads a task.md would be retargeted, so production is checked for one first (read only).
  say "links in production Task state that read a task.md: $(find $PROD/tasks -type l -exec readlink {} \; 2>/dev/null | grep -c 'task\.md$')"
  say "copying from $PROD (read only) to $S: Worldline, task index, and every Task's task.yml, task.md, definitions/"
  cp -Rp $PROD/worldline $S/ && cp -p $PROD/task-index.json(N) $S/ || { print "STOP: copy failed"; return 1; }
  for d in $PROD/tasks/[^.]*(N/); do
    mkdir $S/tasks/$d:t && cp -p $d/task.yml $d/task.md(N) $S/tasks/$d:t/ || { print -r -- "STOP: copy of $d failed"; return 1; }
    [[ -d $d/definitions ]] && { cp -Rp $d/definitions $S/tasks/$d:t/ || { print -r -- "STOP: copy of $d failed"; return 1; } }
  done
  print -r -- 'version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/core/worktrees
  state: .graphtraj/core/state
agent_runner:
  max_concurrency: 1' > $DEMO/.graphtraj/core/config.yml
  print -r -- "copy: $(print -l $S/tasks/[^.]*(N/) | wc -l | tr -d ' ') Task directories, $(print -l $S/tasks/*/task.md(N) | wc -l | tr -d ' ') task.md, $(print -l $S/tasks/*/definitions/*.md(N) | wc -l | tr -d ' ') definitions/*.md"
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs563.py hashes $S $T/demo/before.json) || return 1
  say "preview (public entry; writes nothing)"
  graphtraj_demo migrate-task-definitions --preview > $T/demo/preview.yml; local rc=$?
  print "preview rc=$rc"; (( rc == 0 )) || { cat $T/demo/preview.yml; return 1; }
  grep -E '^(tasks|unchanged|preview):' $T/demo/preview.yml; print -r -- "planned renames: $(grep -c '^- task_id:' $T/demo/preview.yml)"
  sed -n '/^renamed:/,/^links:/p' $T/demo/preview.yml | head -9
  say "migrate"
  graphtraj_demo migrate-task-definitions > $T/demo/migrate.yml; rc=$?
  print "migrate rc=$rc"; (( rc == 0 )) || { cat $T/demo/migrate.yml; return 1; }
  grep -E '^(tasks|unchanged|backup|event_id):' $T/demo/migrate.yml; print -r -- "renamed: $(grep -c '^- task_id:' $T/demo/migrate.yml)"
  say "migrate again (must change nothing)"
  graphtraj_demo migrate-task-definitions > $T/demo/again.yml; rc=$?
  print "again rc=$rc"; cat $T/demo/again.yml
  grep -q '^renamed: \[\]' $T/demo/again.yml && print "PASS: second run renames nothing" || print "FAIL: second run renamed something"
  say "an earlier event's task.md reference resolves through the rename event (516's registration)"
  (cd $PYTEST_TMP && clean $V/bin/python -I -c '
import sys, pathlib
from graphtraj.graph.delivery_worldline import read_worldline
state = pathlib.Path(sys.argv[1])
events = read_worldline(state)
renamed = [e for e in events if e["event"] == "task-definitions-renamed"]
old = next(r for e in events if e["event"] == "task-registered" and e.get("task_id") == "516" for r in e["evidence_refs"])
print("events task-definitions-renamed:", len(renamed), "| mappings:", len(renamed[-1]["renamed_definitions"]))
print("516 registered with", old, "->", renamed[-1]["renamed_definitions"].get(old))
' $S) || return 1
  say "compare"
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs563.py hashes $S $T/demo/after.json) || return 1
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs563.py compare $T/demo/before.json $T/demo/after.json $S); rc=$?
  print -r -- "kept: $T/demo/{before,after}.json, preview.yml, migrate.yml, again.yml"
  print "Success: 'migrate rc=0', 'PASS: second run renames nothing', every check PASS and 'RESULT: PASS'."
  print -r -- "next: zsh $THIS G  (background ~25 min; then zsh $THIS GR)"
  return $rc
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V RUNTMP; g_common G || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY563_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY563_TESTS (plain pytest, same venv, temp root and exit file)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY563_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  else
    (cd $WT && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  fi
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.2 ...', 'started in the background'."
  print -r -- "next (after G ends): zsh $THIS GR"
  ;;
GR)
  say "[GR] Main. Read only. Newest G; FAILED/ERROR lines classed known (528 accepted G, 516 current definition) or NEW. <10 s."
  print -r -- "516 current definition: $KNOWN516"
  local g=$(cat $OUT/G-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|demo|G|GR" ; return 2 ;;
esac
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
