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
# Patterns from scripts/verify-490 (venv, isolated project, launch, decide). The steps never signal a process they
# did not start. pytest temp: ${TMPDIR:-/tmp}, refused if inside the Harness. Outputs: $OUT/<step>.txt via tee.
set -u
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
investigator() { ls $P/.graphtraj/runner/sessions 2>/dev/null | grep "^1-" | grep -m1 "investigator"; }

step_P() {
  say "[P] preflight via /bin/zsh. Dialog: none. Waits: install <= 2 min, claude <= 120 s."
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} (launched by: $(ps -o comm= -p $$ 2>/dev/null))"
  print "candidate $CAND (uncommitted paths in $SRC: $(git -C $SRC status --porcelain | wc -l | tr -d ' ')); BASE=$BASE"
  check_tmp || return 1
  say "candidate venv $V: commit archived to $BASE/candidate and installed editable from there"
  if [[ $(cat $V/.candidate 2>/dev/null) != $CAND ]]; then
    rm -rf $BASE/candidate && mkdir -p $BASE/candidate && git -C $SRC archive $CAND | tar -x -C $BASE/candidate || return 1
    link_deps
    rm -rf $V && $(base_python) -m venv --system-site-packages $V || return 1
    local site=$($PY -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
    for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
    clean $PY -m pip install -q --no-deps --no-build-isolation --no-index -e $BASE/candidate 2>&1 | grep -vi cache
    print -r -- $CAND > $V/.candidate
  else print "venv already holds $CAND: install skipped (rerun)"; fi
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

case $STEP in
  P|A) step_$STEP ;;
  D) step_D ${2:-} ;;
  *) print "usage: zsh $THIS P|A|D [alias]   (order P -> A -> D)"; exit 2 ;;
esac
