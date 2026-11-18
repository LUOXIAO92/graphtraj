#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 521: a read-only investigator submits its own submit_report report as result_refs; its parent accepts it.
#   zsh <this file> <P|A|D>      order: P -> A -> D (Main, from any directory)
#   P  preflight: zsh, pytest temp, candidate commit archived and installed into a venv, isolated project
#      /private/tmp/verify-521/project (own git and .graphtraj, outside the Harness), roles + Task 1 ready,
#      one-line answer from claude -p (model and login), the new tests collected (--collect-only)
#   A  one read-only investigator (claude, Sonnet, worktree_access read) on Task 1: submit_report investigation.md,
#      then submit_result with result_refs [.state/teams/1/rounds/1/investigation.md]; observed from the records
#   D  Main's decide-result accepts that submission (CLI in the project, as verify-490 decide)
#   F  [rerun]  full suite of PRODUCT (bf92a981, installed by P) from $BASE/candidate, single process, nohup in the
#      background: $OUT/F-pytest.txt, F-junit.xml, F.pid, F.start, F.exit (exit code, written when pytest ends)
#   R  the F result: running (elapsed, last log line) or finished (summary, exit code, failed ids from junit)
#   B  only F's failed ids rerun on the baseline 81dde17e (archived, own venv): new failures -> PASS (none new) or FAIL
# Patterns from scripts/verify-490 (venv, isolated project, launch, decide). The steps never signal a process they
# did not start. pytest temp: ${TMPDIR:-/tmp}, refused if inside the Harness. Outputs: $OUT/<step>.txt via tee.
set -u
setopt no_bg_nice   # F's background suite keeps normal priority (and a sandbox refuses nice)
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
# VERIFY521_* are set only by a rehearsal (empty scratch directory, stub claude); the defaults are the real paths.
BASE=${VERIFY521_BASE:-/private/tmp/verify-521}
P=$BASE/project
V=$BASE/venv
PY=$V/bin/python
DEPS=$BASE/deps
OUT=${VERIFY521_OUT:-$BASE/out}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
CAND=${VERIFY521_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
MODEL=claude-sonnet-5-5
STEP=${1:-help}
TMPB=${TMPDIR:-/tmp}
path=(${VERIFY521_STUB_BIN:+$VERIFY521_STUB_BIN} /opt/homebrew/bin $HOME/.local/bin /usr/bin /bin /usr/sbin /sbin)
mkdir -p $OUT
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
# No GraphTraj/Graftling Session variables of Main leak in.
# VERIFY521_HOME (rehearsal only) is a scratch HOME whose catalog names the same connection; the real steps use HOME.
clean() { env -i HOME=${VERIFY521_HOME:-$HOME} USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$TMPB \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
x521() { local command=$1; shift; (cd $P && clean $PY -I $SD/x521.py $command $P "$@"); }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
check_tmp() {
  print "pytest temp base: ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != $H* ]] && print YES || print NO)"
  [[ ${TMPB:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}
link_deps() {  # production dependencies, graftling included; graphtraj comes from the candidate only
  [[ -d $DEPS ]] || { mkdir -p $DEPS; for x in $RTSP/*(N); do case ${x:t} in
      graphtraj*|__editable__*|*.pth|pip|pip-*|_distutils_hack|__pycache__) ;; *) ln -s $x $DEPS/ ;; esac; done; }
}
# install_commit <commit> <tree> <venv>: archive the commit into <tree>, install it editable into <venv> (P and B).
install_commit() {
  local commit=$1 tree=$2 venv=$3
  if [[ $(cat $venv/.candidate 2>/dev/null) == $commit ]]; then print "venv $venv already holds $commit: install skipped (rerun)"; return 0; fi
  rm -rf $tree && mkdir -p $tree && git -C $SRC archive $commit | tar -x -C $tree || return 1
  link_deps
  rm -rf $venv && $(base_python) -m venv --system-site-packages $venv || return 1
  local site=$($venv/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  clean $venv/bin/python -m pip install -q --no-deps --no-build-isolation --no-index -e $tree 2>&1 | grep -vi cache
  print -r -- $commit > $venv/.candidate
}
investigator() { ls$P/.graphtraj/runner/sessions 2>/dev/null | grep "^1-" | grep -m1 "investigator"; }

step_P() {
  say "[P] preflight via /bin/zsh. Dialog: none. Waits: install <= 2 min, claude <= 120 s."
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} (launched by: $(ps -o comm= -p $$ 2>/dev/null))"
  print "candidate $CAND (uncommitted paths in $SRC: $(git -C $SRC status --porcelain | wc -l | tr -d ' ')); BASE=$BASE"
  check_tmp || return 1
  say "candidate venv $V: commit archived to $BASE/candidate and installed editable from there"
  install_commit $CAND $BASE/candidate $V || return 1
  clean $PY -I -c 'import sys, graphtraj, graftling
from pathlib import Path
ok = Path(graphtraj.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
print("graphtraj:", graphtraj.__file__, "| from the archived commit:", ok, "| graftling:", graftling.__file__)
sys.exit(0 if ok else 1)' $BASE/candidate || { print "STOP: the venv does not import the candidate"; return 1; }
  say "isolated project $P (own git and .graphtraj; outside the Harness, so no Harness instruction file applies)"
  if [[ -d $P/.git ]]; then print "existing project: git init and setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 521 probe: read-only report as result" > README.md \
      && git add README.md && git -c user.name=521 -c user.email=521@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  x521 prepare || { print "STOP: roles or Task 1 not ready (text above)"; return 1; }
  say "the new tests of this commit, collected only (pytest temp ${TMPB:A}, outside the Harness)"
  (cd $BASE/candidate && clean $PY -I -c 'import pytest' 2>/dev/null) \
    && (cd $BASE/candidate && clean $PY -m pytest --collect-only -q -p no:cacheprovider tests/test_result_submission.py \
        -k "read_only or retained_once or foreign_unassigned" 2>&1 | grep -E "::|collected|selected|error" | head -5) \
    || print "pytest is not in this venv: collection skipped (the Engineer's validation.md has the runs)"
  say "the host A uses, one call: claude -p --model $MODEL (limit 120 s)"
  (cd $P && clean /usr/bin/perl -e 'alarm 120; exec @ARGV' claude -p --model $MODEL \
     "Reply with exactly one line: READY-521, then your model name, then whether you are logged in. Use no tool." > $OUT/P-claude.txt 2>&1)
  local line=$(grep -v '^\s*$' $OUT/P-claude.txt | tail -1)
  [[ $line == *READY-521* ]] && print "claude answer: OK | $line" || { print "STOP P: claude did not answer: ${line:-none}"; return 1; }
  next "zsh $THIS A 2>&1 | tee $OUT/A.txt"
}

step_A() {
  say "[A] one read-only investigator on Task 1 (claude, $MODEL): submit_report then submit_result naming its own report. Dialog: expected none (its one Bash git rev-parse runs sandboxed under permission_mode auto, and submit_report/submit_result are its own tasks tool calls); if a native permission request for that Bash command or a tasks tool call appears, the user approves it (Allow once). Waits: execution <= 600 s, submission <= 120 s."
  [[ -x $PY ]] || { print "STOP: run P first"; return 1; }
  local existing=$(investigator)
  [[ -z $existing ]] || { print "STOP: Task 1 already has $existing; to observe it again run: zsh $THIS D $existing"; return 1; }
  local batch=$P/.graphtraj/probe-521/batch.yml
  clean $PY -I -c 'import sys, yaml
print(yaml.safe_dump({"tasks": [{"task_id": "1", "task_name": "read-only-report-result", "role": "investigator",
                                  "instruction": sys.argv[1]}]}, sort_keys=False, width=100000), end="")' \
    "$(x521 instruction)" > $batch
  (cd $P && clean $V/bin/agent-runner --swarm-input $batch) > $OUT/A-launch.yml 2>&1
  local alias=$(grep -m1 "alias:" $OUT/A-launch.yml | awk '{print $NF}')
  [[ -n $alias ]] || { print "STOP: launch failed:"; cat $OUT/A-launch.yml; return 1; }
  print "investigator alias: $alias"
  x521 ended $alias 600 || { print "STOP: $alias did not end"; return 1; }
  say "standards 1 and 3 from the records (launch.yml, agent-runner reports, the retained copy)"
  x521 submitted $alias 120; local rc=$?
  (( rc == 0 )) && print "PASS A" || print "FAIL A (an NO line above)"
  next "zsh $THIS D $alias 2>&1 | tee $OUT/D.txt"
  return $rc
}

step_D() {
  local alias=${1:-$(investigator)}
  say "[D] Main's decide-result accepts the investigator's submission. Dialog: none (Main's own CLI in the isolated project)."
  [[ -n $alias ]] || { print "STOP: no investigator Session of Task 1; run A first"; return 1; }
  print "investigator: $alias"
  x521 decide $alias; local rc=$?
  (( rc == 0 )) && print "PASS D" || print "FAIL D (above)"
  print "records: $P/.graphtraj/state (Worldline), $P/.graphtraj/state/tasks/1-read-only-report-result/teams/1/traces/$alias/"
  return $rc
}

# Full suite of the product commit (F/R/B). PRODUCT is the commit Main's P/A/D passed on; BASELINE is the branch base.
PRODUCT=bf92a9810333cbb96e9445b5b459160942606884
BASELINE=81dde17ec099e8bb7d70f25eb2f320f61cc41ffb
VB=$BASE/venv-baseline
# VERIFY521_COLLECT=1 (rehearsal only) runs pytest --collect-only through the same background and exit-file path.
PYTEST_ARGS=(-p no:cacheprovider -p no:xdist -q -rfE)
# F counts as running while F.exit is absent and its pid is visible, or (a sandbox hides other processes from ps)
# its log or start record changed within 10 minutes. It never signals the process.
pid_visible() { [[ -f $OUT/F.pid ]] && ps -p $(<$OUT/F.pid) >/dev/null 2>&1; }
running_f() {
  [[ -f $OUT/F.start && ! -f $OUT/F.exit ]] || return 1
  pid_visible && return 0
  local newest=$OUT/F.start; [[ -f $OUT/F-pytest.txt ]] && newest=$OUT/F-pytest.txt
  (( $(date +%s) - $(stat -f %m $newest) < 600 ))
}

step_F() {
  local mode=${1:-}
  say "[F] full suite of $PRODUCT in the background, single process (no xdist). Dialog: none. Returns at once; the suite takes about 75 min."
  check_tmp || return 1
  print "pytest temp: TMPDIR=${TMPB:A}, --basetemp ${TMPB:A}/verify-521-F (outside the Harness)"
  [[ $(cat $V/.candidate 2>/dev/null) == $PRODUCT ]] || {
    print "STOP: $V holds $(cat $V/.candidate 2>/dev/null || print nothing), not $PRODUCT. Install it with:"
    print -r -- "  VERIFY521_CANDIDATE=$PRODUCT zsh $THIS P"; return 1; }
  if running_f; then print "STOP: an earlier F is still running (pid $(<$OUT/F.pid)); read it with: zsh $THIS R"; return 1; fi
  if [[ -e $OUT/F.pid || -e $OUT/F.exit || -e $OUT/F-pytest.txt ]]; then
    if [[ $mode != rerun ]]; then
      print "STOP: results of an earlier F exist in $OUT (F.pid/F.exit/F-pytest.txt). Read them: zsh $THIS R"
      print "      or start again, moving them aside: zsh $THIS F rerun"; return 1
    fi
    local aside=$OUT/F-earlier-$(date +%Y%m%dT%H%M%S); mkdir -p $aside
    mv $OUT/F.pid $OUT/F.exit $OUT/F.start $OUT/F-pytest.txt $OUT/F-junit.xml $aside/ 2>/dev/null; print "earlier F results moved to $aside"
  fi
  local args=(tests $PYTEST_ARGS --junitxml=$OUT/F-junit.xml --basetemp=$TMPB/verify-521-F)
  [[ -n ${VERIFY521_COLLECT:-} ]] && { args=(--collect-only $args); print "REHEARSAL: --collect-only"; }
  print -r -- "$(date +%s) $(date '+%Y-%m-%d %H:%M:%S %Z')" > $OUT/F.start
  print -r -- "command (in $BASE/candidate): $PY -m pytest ${args[*]}"
  # The wrapper records its own pid, ignores HUP, runs pytest as its child, then writes F.exit atomically.
  # nohup is used where it works (a host terminal); a sandbox refuses its detach, so the trap alone then holds.
  local hup=(nohup)
  nohup /usr/bin/true < /dev/null > /dev/null 2>&1 || hup=()
  print "detached with: ${${hup:+nohup + trap HUP}:-trap HUP (nohup refused here)} and &!"
  clean $hup /bin/zsh -fc 'trap "" HUP; print $$ > $3.pid; cd $1 || { print 127 > $3.exit; exit 1 }
    log=$2 p=$3; shift 3; "$@" > $log 2>&1; print $? > $p.exit.tmp && mv $p.exit.tmp $p.exit' \
    F-run $BASE/candidate $OUT/F-pytest.txt $OUT/F $PY -m pytest $args < /dev/null > /dev/null 2>&1 &!
  local i=0; while [[ ! -f $OUT/F.pid ]] && (( i++ < 10 )); do sleep 0.5; done
  [[ -f $OUT/F.pid ]] || { rm -f $OUT/F.start; print "STOP: the background run did not start (no $OUT/F.pid within 5 s)"; return 1; }
  print "started $(cut -d' ' -f2- $OUT/F.start) pid $(<$OUT/F.pid)"
  print "files: $OUT/F-pytest.txt, F-junit.xml, F.pid, F.start, F.exit (written when pytest ends)"
  next "zsh $THIS R"
}

step_R() {
  say "[R] the F result. Dialog: none."
  [[ -f $OUT/F.start ]] || { print "no F has started in $OUT; start it: zsh $THIS F"; return 1; }
  local elapsed=$(( $(date +%s) - $(cut -d' ' -f1 $OUT/F.start) ))
  if [[ ! -f $OUT/F.exit ]]; then
    if running_f; then
      print "running: pid $(cat $OUT/F.pid 2>/dev/null) ($(pid_visible && print visible || print 'not visible to ps here; judged by a log change within 10 min')), started $(cut -d' ' -f2- $OUT/F.start), elapsed $(( elapsed / 60 )) min $(( elapsed % 60 )) s"
      print -r -- "last log line: $(grep -v '^\s*$' $OUT/F-pytest.txt 2>/dev/null | tail -1 | cut -c1-200)"
      next "zsh $THIS R"; return 0
    fi
    print "STOP: no F.exit, pid $(cat $OUT/F.pid 2>/dev/null) not visible and no log change for 10 min: the run died; log tail:"
    tail -5 $OUT/F-pytest.txt 2>/dev/null; print "start again: zsh $THIS F rerun"; return 1
  fi
  local rc=$(<$OUT/F.exit)
  print "finished: exit code $rc (started $(cut -d' ' -f2- $OUT/F.start); $(( elapsed / 60 )) min since)"
  print -r -- "summary: $(grep -E '(passed|failed|error|no tests ran|collected|tests? collected)' $OUT/F-pytest.txt | tail -1)"
  [[ -f $OUT/F-junit.xml ]] || { print "STOP: no $OUT/F-junit.xml"; return 1; }
  $PY -I $SD/x521.py failed-ids $OUT/F-junit.xml $BASE/candidate > $OUT/F-failed.txt
  print "failed/errored test ids (junit): $(wc -l < $OUT/F-failed.txt | tr -d ' ') -> $OUT/F-failed.txt"
  sed 's/^/  /' $OUT/F-failed.txt
  if [[ -s $OUT/F-failed.txt ]]; then next "zsh $THIS B 2>&1 | tee $OUT/B.txt"
  elif [[ $rc == 0 ]]; then print "no failures: no new failures (B not needed)"
  else print "exit $rc without failed ids in junit: read $OUT/F-pytest.txt (collection or session error)"; fi
}

step_B() {
  say "[B] the F failures rerun on the baseline $BASELINE, single process. Dialog: none. Install about 1 min; then only those tests."
  check_tmp || return 1
  print "pytest temp: TMPDIR=${TMPB:A}, --basetemp ${TMPB:A}/verify-521-B (outside the Harness)"
  [[ -s $OUT/F-failed.txt ]] || { print "STOP: no failed ids in $OUT/F-failed.txt; run: zsh $THIS R"; return 1; }
  say "baseline venv $VB: $BASELINE archived to $BASE/baseline and installed editable from there"
  install_commit $BASELINE $BASE/baseline $VB || return 1
  # Collect the failed files on the baseline: an id absent there would stop pytest (not found), so only present ids run.
  local files=(${(u)${(f)"$(cut -d: -f1 $OUT/F-failed.txt)"}})
  (cd $BASE/baseline && local present=(${^files}(N)) && (( $#present )) && clean $VB/bin/python -m pytest --collect-only -q \
     -p no:cacheprovider -p no:xdist $present 2>/dev/null) | grep '::' > $OUT/B-collected.txt
  local ids=(${(f)"$(grep -Fxf $OUT/B-collected.txt $OUT/F-failed.txt)"})
  print "candidate failures: $(wc -l < $OUT/F-failed.txt | tr -d ' '); present on the baseline: ${#ids}"
  rm -f $OUT/B-junit.xml
  if (( ${#ids} )); then
    (cd $BASE/baseline && clean $VB/bin/python -m pytest $PYTEST_ARGS --junitxml=$OUT/B-junit.xml \
       --basetemp=$TMPB/verify-521-B $ids > $OUT/B-pytest.txt 2>&1)
    print -r -- "baseline run: $(grep -E '(passed|failed|error)' $OUT/B-pytest.txt | tail -1) (log $OUT/B-pytest.txt)"
  fi
  say "per test: candidate / baseline"
  $PY -I $SD/x521.py compare $OUT/F-failed.txt $OUT/B-junit.xml $OUT/B-collected.txt $BASE/baseline
}

case $STEP in
  P|A|R|B) step_$STEP ;;
  D) step_D ${2:-} ;;
  F) step_F ${2:-} ;;
  *) print "usage: zsh $THIS P|A|D [alias]|F [rerun]|R|B   (order P -> A -> D; then F -> R -> B when R lists failures)"; exit 2 ;;
esac
