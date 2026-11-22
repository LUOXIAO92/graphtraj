#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 567 Main-run steps (modelled on verify-563 and verify-531 G/GR). Run one step at a time:  zsh <this file> <STEP>
#   pre  Main. Preflight: shell, paths, graftling v0.6.3 commit, TMPDIR outside the Harness, clean candidate.
#        Dialog: none. <10 s.
#   P    Main. Preview record on a COPY at <Harness>/tmp/567/p/h (production is only read): Worldline, task index,
#        every Task's task.yml, task.md and definitions/ as verify-563 copied them; the renames production already
#        applied are undone in the copy (defs567.py retire) so the migration has work again; Task 418's
#        teams/1/rounds/{1,2}/realhost are copied in and set to 0444 as found in production on 2026-11-22.
#        Runs the candidate's `graphtraj migrate-task-definitions --preview`, then without --preview: both must
#        exit 1 naming both directories and the remedy, with nothing changed. Then u+x on the copies and the
#        preview again: it must proceed (exit 0). Dialog: none. ~1 min (first venv build ~1 min more).
#   F    Main. Focused tests: tests/test_task_definition_migration.py and tests/test_task_migration.py (the other
#        caller) in the G venv, new pytest temp root under TMPDIR. Dialog: none. ~3 min.
#   G    Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a venv with the
#        graftling wheel built from git archive ROOT of <Harness>/graftling at v0.6.3 (= production, 560); new
#        pytest temp root under TMPDIR=${TMPDIR:-/tmp}, outside the Harness. Main's suite queue is serial: G stops
#        if another pytest run is going. VERIFY567_PYTEST_ARGS='<args>' only appends pytest args after `-- -rA`.
#   GR   Main. Read only: newest G; every FAILED/ERROR line classed known (516's CURRENT definition read through
#        516's task.yml current_definition), seen in 560's accepted-base G record, or NEW. <10 s.
# No step raises a native review dialog. Production state is only read. Venvs and the copy are under
# <Harness>/tmp/567; step output under OUT. VERIFY567_T / VERIFY567_OUT are for the Engineer's rehearsal only
# (Harness tmp/ is not writable from the Engineer's sandbox).
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY567_T:-$H/tmp/567}
OUT=${VERIFY567_OUT:-$H/.graphtraj/core/state/tasks/567-definition-migration-unreadable-directory-error/realhost}
PROD=$H/.graphtraj/core/state
G=$H/graftling
GCOMMIT=ef7c37db15f4e6318fd5b6bf5bd79321b876eac5   # graftling v0.6.3 (560) = production; wheel builds from the archive root
SD=${0:A:h}
THIS=${0:A}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN560=$WT/scripts/adopt-560/G-record/failures.txt   # 560's G at 8949caff + graftling v0.6.3 (this base's parent line)
# 516's CURRENT definition, read through its task.yml (works before and after migrate-task-definitions).
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN516=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
E418=$PROD/tasks/418-agents-claude-code-marketplace-package/teams/1/rounds
DEMO=$T/p/h                                         # the copy's Harness root
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
g_venv() {  # sets V: venv with the graftling wheel built at GCOMMIT (archive root) and this Worktree editable
  local GS=${GCOMMIT[1,8]}
  local SRC=$T/graftling-$GS N=$T/wheels-gl-$GS
  V=$T/venv-g-gl-$GS
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V (graftling $GS; this Worktree editable)"
  else
    rm -rf $SRC $N $V && mkdir -p $SRC && git -C $G archive $GCOMMIT | tar -x -C $SRC || { print "STOP: cannot extract graftling"; return 1; }
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $SRC >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT 2>&1 | grep -vi cache
    print -r -- $GCOMMIT > $V/installed
  fi
}
# A new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-567-$1-$(date +%Y%m%dT%H%M%S)
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
classify() {  # FAILED/ERROR lines of files $@: known (516 current definition), seen in 560's G record, or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    elif grep -qF -- "$t" $KNOWN560 2>/dev/null; then print -r -- "seen in 560's G record (not in 516; Leader judges): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}
graphtraj_demo() { (cd $DEMO && clean $V/bin/graphtraj "$@") }
refused() {  # $1 label, $2 output file, $3 rc: exit 1, both directories, remedy, no Errno
  local ok=0 d
  (( $3 == 1 )) && print "PASS: $1 exit 1" || { print "FAIL: $1 exit $3 (expected 1)"; ok=1; }
  for d in 1 2; do
    grep -qF ".graphtraj/core/state/tasks/418-agents-claude-code-marketplace-package/teams/1/rounds/$d/realhost" $2 \
      && print "PASS: $1 names rounds/$d/realhost" || { print "FAIL: $1 does not name rounds/$d/realhost"; ok=1; }
  done
  grep -qF 'chmod u+rx' $2 && grep -qF 'Nothing was changed' $2 && print "PASS: $1 states the remedy and that nothing changed" \
    || { print "FAIL: $1 lacks the remedy"; ok=1; }
  grep -q 'Errno' $2 && { print "FAIL: $1 still shows Errno"; ok=1; } || print "PASS: $1 shows no Errno"
  return $ok
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight. Dialog: none. <10 s."
  print "zsh: $ZSH_VERSION ($THIS)"
  print -r -- "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | T=$T | OUT=$OUT | PROD=$PROD (read only)"
  check_tmp || return 1
  case ${T:A}/ in ${H:A}/tmp/*|${PYTEST_TMP:A}/*) ;; *) print "STOP: T $T is neither under <Harness>/tmp nor TMPDIR"; return 1 ;; esac
  [[ -d $PROD/tasks && -d $PROD/worldline ]] || { print -r -- "STOP: $PROD has no tasks/ or worldline/"; return 1; }
  print -r -- "production Task directories: $(print -l $PROD/tasks/[^.]*(N/) | wc -l | tr -d ' ') (read only)"
  print -r -- "Task 418 evidence directories (P copies them): $(print -l $E418/{1,2}/realhost(N/) | wc -l | tr -d ' ') of 2"
  print -r -- "516 current definition (from task.yml): $KNOWN516"; [[ -f $KNOWN516 ]] || { print "STOP: 516 current definition missing"; return 1; }
  print -r -- "560 G record (seen-before list): $KNOWN560"; [[ -f $KNOWN560 ]] || { print "STOP: 560 G record missing"; return 1; }
  git -C $G cat-file -e $GCOMMIT^{commit} && print -r -- "graftling $GCOMMIT (v0.6.3) present in $G" || { print "STOP: graftling commit missing"; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins scripts)
  print "uncommitted in src/tests/plugins/scripts: ${dirty:-none}"
  print "Success: 'pytest temp: ... outside the Harness', '2 of 2', the 516 path ends in definitions/<time>.md, 'uncommitted ...: none'."
  print -r -- "next: zsh $THIS P"
  ;;
P)
  say "[P] Main. Preview on a copy with unreadable directories; then with u+x. Dialog: none. ~1 min."
  check_tmp || return 1
  local V; g_venv || return 1
  local S=$DEMO/.graphtraj/core/state d rc ok=0
  [[ -e $T/p ]] && chmod -R u+rwx $T/p          # an earlier copy keeps read-only modes
  rm -rf $T/p && mkdir -p $S/tasks || return 1
  say "copying from $PROD (read only) to $S: Worldline, task index, every Task's task.yml, task.md, definitions/"
  cp -Rp $PROD/worldline $S/ && cp -p $PROD/task-index.json(N) $S/ || { print "STOP: copy failed"; return 1; }
  cp -p $PROD/tasks/.lock $S/tasks/ || { print "STOP: copy of the empty Task-state lock file failed"; return 1; }  # every locked run creates it
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
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs567.py retire $DEMO $S) || return 1
  local C418=$S/tasks/418-agents-claude-code-marketplace-package/teams/1/rounds
  for d in 1 2; do mkdir -p $C418/$d && cp -Rp $E418/$d/realhost $C418/$d/ || { print "STOP: copy of 418 rounds/$d/realhost failed"; return 1; }; done
  print -r -- "copy: $(print -l $S/tasks/[^.]*(N/) | wc -l | tr -d ' ') Task directories, $(print -l $S/tasks/*/task.md(N) | wc -l | tr -d ' ') task.md, 418 realhost entries: $(ls -A $C418/1/realhost | wc -l | tr -d ' ') + $(ls -A $C418/2/realhost | wc -l | tr -d ' ')"
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs567.py tree $S $T/p/before.json) || return 1
  chmod 0444 $C418/1/realhost $C418/2/realhost
  print -r -- "copy modes now: $(stat -f '%Sp %N' $C418/1/realhost $C418/2/realhost | sed "s|$S/||" | tr '\n' ' ')"
  say "preview (public entry) with the two directories at r--r--r--"
  graphtraj_demo migrate-task-definitions --preview > $T/p/refused-preview.out 2>&1; rc=$?
  print "rc=$rc"; cat $T/p/refused-preview.out
  refused preview $T/p/refused-preview.out $rc || ok=1
  say "migration without --preview, same directories"
  graphtraj_demo migrate-task-definitions > $T/p/refused-migrate.out 2>&1; rc=$?
  print "rc=$rc"; refused migrate $T/p/refused-migrate.out $rc || ok=1
  chmod u+x $C418/1/realhost $C418/2/realhost
  print -r -- "after u+x: $(stat -f '%Sp %N' $C418/1/realhost $C418/2/realhost | sed "s|$S/||" | tr '\n' ' ')"
  (cd $PYTEST_TMP && clean $V/bin/python -I $SD/defs567.py tree $S $T/p/after.json) || return 1
  cmp -s $T/p/before.json $T/p/after.json && print "PASS: nothing under the copy's state changed (every file and link)" \
    || { print "FAIL: the copy's state changed"; ok=1; }
  [[ -e $DEMO/.graphtraj/backups ]] && { print "FAIL: a backup directory was created"; ok=1; } || print "PASS: no backup directory"
  say "preview again after u+x (must proceed)"
  graphtraj_demo migrate-task-definitions --preview > $T/p/preview.yml 2>&1; rc=$?
  print "rc=$rc"; grep -E '^(tasks|unchanged|preview|links):' $T/p/preview.yml
  local n=$(grep -c '^- task_id:' $T/p/preview.yml)
  print -r -- "planned renames: $n"
  (( rc == 0 && n > 0 )) && print "PASS: preview proceeds after u+x" || { print "FAIL: preview after u+x"; cat $T/p/preview.yml; ok=1; }
  print -r -- "kept: $T/p/{refused-preview.out,refused-migrate.out,before.json,after.json,preview.yml}"
  (( ok == 0 )) && print "RESULT 567 P: PASS" || print "RESULT 567 P: FAIL"
  print "Success: every line PASS and 'RESULT 567 P: PASS'."
  print -r -- "next: zsh $THIS F"
  return $ok
  ;;
F)
  say "[F] Main. Focused tests (definition migration and its Ticket-conversion caller). Dialog: none. ~3 min."
  local V RUNTMP; g_common F || return 1
  local extra=(${(Q)${(z)${VERIFY567_PYTEST_ARGS:-}}})
  print -r -- "pytest -p no:cacheprovider -q -rfE tests/test_task_definition_migration.py tests/test_task_migration.py $extra"
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE \
    tests/test_task_definition_migration.py tests/test_task_migration.py $extra); local rc=$?
  print "exit=$rc"
  print "Success: 'exit=0' with every test passed (none skipped unless run as root)."
  print -r -- "next: zsh $THIS G  (background ~25 min; then zsh $THIS GR)"
  return $rc
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V RUNTMP; g_common G || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling $GCOMMIT (v0.6.3)"; } > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY567_PYTEST_ARGS:-}}})   # shell words, so a quoted -k expression stays one arg
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra (same shard entry; whole suite collected)" | tee -a $R/run.txt
  # `&!` disowns the run and all output is redirected; nohup is not used (without a console it exits 127).
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.3 ...' built from $GCOMMIT, 'started in the background'."
  print -r -- "next (after G ends, i.e. $R/suite.txt ends with 'exit='): zsh $THIS GR"
  ;;
GR)
  say "[GR] Main. Read only. Newest G; FAILED/ERROR lines classed known (516), seen in 560's G record, or NEW. <10 s."
  print -r -- "516 current definition: $KNOWN516"
  local g=$(cat $OUT/G-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  print "Success: G 'exit=0' or only 'known (516)' lines; a 'seen in 560' line goes to the Leader; no 'NEW' line."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|P|F|G|GR" ; return 2 ;;
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
