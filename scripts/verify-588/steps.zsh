#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 588 Main-run steps: submit_report accepts the assigned path form and lists the assigned names when it refuses.
# Candidate = this Worktree's HEAD (GraphTraj base 350b8e19 + the 588 fix); graftling v0.8.0 (542a81df), the version
# this HEAD declares (graftling>=0.8.0,<0.9). Production (.venv-runtime, 579) is only read, never changed.
# Run one step at a time:  zsh <this file> <STEP>
#   pre         Main. Read only, except one claude -p call in a fresh empty directory under ${TMPDIR:-/tmp}. Checks:
#               ROOT=/private/tmp/graphtraj-588 does not exist (STOP with the exact rm command if it does); zsh;
#               candidate HEAD, base 350b8e19 and graftling 542a81df resolvable; TMPDIR outside the Harness;
#               click/PyYAML/websockets in <Harness>/.venv-runtime; claude --version; no other pytest; one-line
#               `claude -p --model claude-opus-5-5` answer naming its model and login state.
#               Dialog: none. LOGIN: the claude -p call uses the user's Claude login (Main asks the user first). ~30 s.
#               Observable: "PASS claude answered: READY-588 ..." and every other line PASS.
#   install     Main. Builds venv $T/venv-root-<head8> for the isolated project, offline: a wheel of this Worktree's
#               HEAD (git archive) and a wheel of graftling 542a81df (v0.8.0); click/PyYAML/websockets copied from
#               <Harness>/.venv-runtime (read only). Dialog: none. No login. ~1 min.
#               Observable: "PASS venv imports graphtraj <HEAD> (wheel) and graftling 0.8.0" lines.
#   realhost    Main, after the user agreed to use the Claude login. In ROOT (own git; .graphtraj through the public
#               `graphtraj setup` entry; roles: opus_coding_team.engineer on runtime claude, connection
#               claude/anthropic/opus-5_5, reports engineer.md and validation.md) registers probe Task 1 and dispatches
#               ONE real Engineer with `agent-runner --swarm-input` from the install venv. It calls tasks submit_report
#               with name engineer.md, name .state/teams/1/rounds/1/validation.md and name engineer-budget, and
#               replies with the raw results. Then reads back through session_reports (`agent-runner reports`).
#               ROOT is outside the Harness, so no Harness AGENTS.md/CLAUDE.md is found by walk-up: the
#               verify-common/claude_isolation.py settings are not needed (and it refuses projects outside
#               <Harness>/tmp). Dialog: expected none (submit_report is the Engineer's own tasks tool call under
#               permission_mode auto); if a native permission request for a tasks tool call appears, the user allows
#               it once. LOGIN: the user's Claude login. ~3-6 min (execution limit 600 s).
#               Observable: five "PASS" lines from x588.py check: engineer.md holds 'probe bare' (bare name);
#               validation.md holds 'probe path' (path form); the engineer-budget refusal is authority-denied and
#               lists "Assigned reports: engineer.md, validation.md"; Round 1 holds only those two files; nothing was
#               written elsewhere. Verdict line "realhost: PASS".
#   suite       Main. GraphTraj full suite of HEAD (scripts/run_test_shards.py, 6 shards, --timeout 1500, -rA,
#               background ~25 min) in a venv under $T with graftling 542a81df as a WHEEL and GraphTraj editable.
#               pytest's temp root is a fresh directory under TMPDIR=${TMPDIR:-/tmp}, outside the Harness (checked;
#               the step prints it). Dialog: none. No login.
#   SR          Read only: the newest suite's FAILED/ERROR node ids (whole, via scripts/verify-581/suiteids.py) classed
#               'known (516)' (Task 516's CURRENT definition, read through its task.yml current_definition) or NEW;
#               writes new-ids.txt and prints the ready-to-paste suite-base command, each id a separate shell-quoted
#               argument, and the --from form. Dialog: none. No login.
#   suite-base  Main, only if SR reports NEW: `zsh <this file> suite-base <id>...` or `... suite-base --from <file>`
#               reruns exactly those ids on base GraphTraj 350b8e19 (a local clone under $T), then on the candidate,
#               both with the graftling 542a81df wheel. Dialog: none. No login.
#   push        Main, ONLY after the user agreed. Pushes HEAD to LUOXIAO92/graphtraj as this Task's branch. Dialog:
#               none expected; git uses your usual GitHub login.
# Order: pre, install, realhost (after the user agrees to the Claude login), suite, SR (suite-base only if SR names NEW
# ids); push separately after the user agrees.
# Credentials: pytest starts from an ALLOWLIST (launch(): HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE TMPDIR PATH
# and the step's own VAR=value); a guard STOPs (exit 97, names only) if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH*
# name is left. claude and the Engineer start from the same allowlist. Writes: T (venvs, sources, outputs), ROOT
# (realhost only), OUT (copies of results) and temp roots under TMPDIR only; never .venv-runtime, ~/.claude or dotfiles.
# Rehearsal only (Engineer): VERIFY588_T, VERIFY588_OUT, VERIFY588_ROOT, VERIFY588_PYTEST_ARGS (pytest args after
# `-- -rA`), VERIFY588_SUITE_ENV (extra VAR=value for the suite's launch), VERIFY588_NO_PS=1 (no ps in a sandbox),
# VERIFY588_HOME (a scratch HOME holding a connection catalog), VERIFY588_DRY=1 (realhost stops before the dispatch).
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
STEP=${1:-}
URL=https://github.com/LUOXIAO92/graphtraj.git
BRANCH=agent/588-submit-report-name-forms-and-error
TASKDIR=588-submit-report-name-forms-and-error
GREPO=$H/graftling                                  # the local graftling repository (read only)
GCOMMIT=542a81df0c941f5b1a425d9807681b2a38daa87c   # graftling v0.8.0 (pyproject: graftling>=0.8.0,<0.9)
GTBASE=350b8e19a60cdc49093e5633f05881e0b4415b83     # GraphTraj dev, this Task's base (unfixed)
HEAD=$(git -C $WT rev-parse HEAD)                   # the candidate
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: click, PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
T=${VERIFY588_T:-$H/tmp/588}                        # venvs, sources and outputs
OUT=${VERIFY588_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost}
ROOT=${VERIFY588_ROOT:-/private/tmp/graphtraj-588}  # the isolated project (outside the Harness)
VROOT=$T/venv-root-${HEAD[1,8]}                     # install: the isolated project's GraphTraj
MODEL=claude-opus-5-5
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
SUITEIDS=$WT/scripts/verify-581/suiteids.py        # whole node ids, classification, error origins (Task 581)
X588=$SD/x588.py
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
ALLOW=(HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE TMPDIR PATH)
launch() {  # [VAR=value...] -- command...
  local -a add=(); while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done
  (( $# )) && shift
  (
    local n
    for n in ${(k)parameters[(R)*export*]}; do
      (( ${ALLOW[(Ie)$n]} )) || unset $n 2>/dev/null
    done
    for n in $add; do export "$n"; done
    local -a bad=(${(M)${(k)parameters[(R)*export*]}:#(*_API_KEY|*_TOKEN|*_BASE_URL|*_AUTH*)})
    (( $#bad )) && { print -u2 -r -- "STOP: provider credential names in the launch environment: $bad"; exit 97; }
    exec "$@"
  )
}
others() {
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1); then
    [[ ${VERIFY588_NO_PS:-} == 1 ]] && { print -u2 -r -- "NOTE: ps cannot list processes here; check skipped (VERIFY588_NO_PS=1, rehearsal)"; return 0; }
    print -r -- "ps cannot list processes here ($listed); run this script in your own terminal"; return 0
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -v grep || true
}
outside() {  # STOP unless TMPDIR is outside the Harness
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
copy_deps() {  # venv: click, PyYAML, websockets from production (read only) when the venv lacks them
  local V=$1 D m
  D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
graftling_wheel() {  # wheel directory: graftling GCOMMIT built offline from a git archive
  local S=$1
  rm -rf -- $S/graftling && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null
}
# venv with graftling GCOMMIT as a WHEEL and GraphTraj editable (suite, suite-base).
suite_venv() {  # venv graphtraj-checkout
  local V=$1 gt=$2 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf -- $V $S && mkdir -p $S || return 1
  graftling_wheel $S || return 1
  $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  $V/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && $V/bin/python -m pip install $PIP -e $gt || return 1
  print -r -- "graftling $GCOMMIT (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
run_root() {  # label; a fresh pytest temp root under TMPDIR, outside the Harness, no Harness marker above; sets RUNTMP
  outside || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-588-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
}
versions() {  # venv: which graphtraj and graftling it imports (from the temp root, not the checkout)
  (cd $RUNTMP && $1/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))')
}
# The isolated project's commands: allowlisted environment, HOME from VERIFY588_HOME in a rehearsal only.
inroot() { (cd $ROOT && launch HOME=${VERIFY588_HOME:-$HOME} TMPDIR=$PYTEST_TMP -- "$@"); }

run_step() {
case $STEP in
pre)
  say "[pre] Main. Read-only preflight plus one claude -p call. Dialog: none. LOGIN: the user's Claude login (claude -p). ~30 s."
  OK=1
  if [[ -e $ROOT ]]; then
    print -r -- "STOP: $ROOT exists (an earlier run). Look at it, then remove it with:  rm -rf ${(qq)ROOT}  and rerun: zsh $THIS pre"
    return 1
  fi
  pass "$ROOT does not exist"
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT cat-file -e "$GTBASE^{commit}" 2>/dev/null && pass "base GraphTraj $GTBASE resolvable ($(git -C $WT log --format=%s -1 $GTBASE | cut -c1-70))" || fail "base GraphTraj $GTBASE not in $WT"
  git -C $GREPO cat-file -e "$GCOMMIT^{commit}" 2>/dev/null && pass "graftling $GCOMMIT resolvable in $GREPO ($(git -C $GREPO describe --tags $GCOMMIT 2>/dev/null))" || fail "graftling $GCOMMIT not in $GREPO"
  local declared=$(git -C $WT show HEAD:pyproject.toml | grep -o '"graftling[<>=][^"]*"')
  [[ $declared == '"graftling>=0.8.0,<0.9"' ]] && pass "HEAD declares $declared" || fail "HEAD declares $declared (expected graftling>=0.8.0,<0.9)"
  local dirty=$(git -C $WT status --porcelain -- src tests scripts)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, scripts" || fail "uncommitted changes in $WT: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m; for m in click yaml websockets; do [[ -d $RTSP/$m ]] && pass "$m present in $RTSP" || fail "$m missing in $RTSP"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  local o=$(others); [[ -z $o ]] && pass "no other pytest running" || { fail "another test run is running:"; print -r -- $o; }
  local C=$(command -v claude || print -r -- $HOME/.local/bin/claude)
  [[ -x $C ]] && pass "claude $C: $(launch HOME=$HOME -- $C --version 2>&1 | head -1)" || fail "claude not found by 'command -v claude' or at $HOME/.local/bin/claude; run this step in your own terminal where claude works"
  if [[ -x $C ]]; then
    local P=$(mktemp -d ${PYTEST_TMP:A}/verify-588-pre-XXXXXX) || return 1
    print -r -- "claude -p runs in $P (empty, outside the Harness; limit 120 s)"
    (cd $P && launch HOME=$HOME -- /usr/bin/perl -e 'alarm 120; exec @ARGV' $C -p --model $MODEL \
      "Reply with exactly one line: READY-588, then your model name, then whether you are logged in. Use no tool." \
      > $P/answer.txt 2>&1); local rc=$?
    local line=$(grep -v '^\s*$' $P/answer.txt | tail -1)
    [[ $line == *READY-588* ]] && pass "claude answered: $line" || fail "claude -p rc=$rc (142 = timeout): ${line:-no answer}"
  fi
  print -r -- "writes: one empty temp directory and its answer.txt under $PYTEST_TMP only. dialog: none."
  (( OK )) && print -r -- "next (paste): zsh $THIS install" || print -r -- "next: fix the FAIL lines above, then: zsh $THIS pre"
  (( OK ))
  ;;
install)
  say "[install] Main. venv $VROOT: wheels of GraphTraj $HEAD and graftling $GCOMMIT, offline. Dialog: none. No login. ~1 min."
  OK=1
  local S=$VROOT-src
  if [[ -x $VROOT/bin/python && $(cat $VROOT/installed 2>/dev/null) == $HEAD ]]; then
    print -r -- "reusing $VROOT (graphtraj $HEAD)"
  else
    rm -rf -- $VROOT $S && mkdir -p $S/graphtraj || return 1
    git -C $WT archive $HEAD | tar -x -C $S/graphtraj || return 1
    graftling_wheel $S || return 1
    $CONDA -m pip wheel $PIP -w $S/wheels $S/graphtraj > /dev/null || { print -r -- "STOP: GraphTraj wheel build failed"; return 1; }
    $CONDA -m venv $VROOT && copy_deps $VROOT || return 1
    $VROOT/bin/python -m pip install $PIP $S/wheels/graftling-*.whl $S/wheels/graphtraj-*.whl || return 1
    print -r -- $HEAD > $VROOT/installed
  fi
  run_root install || return 1
  (cd $RUNTMP && $VROOT/bin/python -I -c 'import sys, graphtraj, graftling, importlib.metadata as m
from pathlib import Path
d = m.distribution("graphtraj"); url = d.read_text("direct_url.json") or ""
site = Path(sys.argv[1]).resolve()
ok = Path(graphtraj.__file__).resolve().is_relative_to(site) and "editable" not in url
print("graphtraj", graphtraj.__file__, "| wheel:", ok, "| graftling", graftling.__version__, graftling.__file__)
sys.exit(0 if ok and graftling.__version__ == "0.8.0" else 1)' $VROOT) \
    && pass "venv imports graphtraj $HEAD (wheel) and graftling 0.8.0" || fail "venv does not import the candidate wheel and graftling 0.8.0"
  # The fix is in the installed code: the refusal lists the assigned names.
  grep -q 'Assigned reports:' $VROOT/lib/python3.13/site-packages/graphtraj/execution/runner_control.py \
    && pass "installed runner_control.py holds the 588 refusal text" || fail "installed runner_control.py lacks the 588 change"
  for m in graphtraj agent-runner; do [[ -x $VROOT/bin/$m ]] && pass "$VROOT/bin/$m" || fail "$VROOT/bin/$m missing"; done
  print -r -- "writes: $VROOT, $S and $RUNTMP only. dialog: none."
  (( OK )) && print -r -- "next: ask the user to agree to the Claude login, then (paste): zsh $THIS realhost" \
           || print -r -- "next: fix the FAIL lines above, then: zsh $THIS install"
  (( OK ))
  ;;
realhost)
  say "[realhost] Main. ONE real opus_coding_team Engineer in $ROOT. Dialog: expected none. LOGIN: the user's Claude login. ~3-6 min."
  [[ $(cat $VROOT/installed 2>/dev/null) == $HEAD ]] || { print -r -- "STOP: run first: zsh $THIS install"; return 1; }
  mkdir -p $OUT
  local PY=$VROOT/bin/python
  if [[ -d $ROOT/.git ]]; then print -r -- "existing project $ROOT: git init and setup skipped (rerun)"
  else
    mkdir -p $ROOT && (cd $ROOT && git init -q -b main && print -r -- "# 588 probe: submit_report name forms" > README.md \
      && git add README.md && git -c user.name=588 -c user.email=588@invalid commit -qm "Initial source") || return 1
    print y | inroot $VROOT/bin/graphtraj setup 2>&1 | tail -3 || return 1
  fi
  inroot $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); root = Path.cwd().resolve()
print("runner directory:", found, "| inside the project:", found.is_relative_to(root)); sys.exit(0 if found.is_relative_to(root) else 1)' \
    || { print -r -- "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  print -r -- "$ROOT is outside the Harness $H: no Harness AGENTS.md/CLAUDE.md lies above it"
  inroot $PY -I $X588 prepare $ROOT || { print -r -- "STOP: roles or Task 1 not ready (text above)"; return 1; }
  local existing=(${ROOT}/.graphtraj/**/sessions/1-*engineer*(N/))
  (( $#existing )) && { print -r -- "STOP: Task 1 already has ${existing:t}; to check it again: zsh $THIS check ${existing[1]:t}"; return 1; }
  local batch=$ROOT/.graphtraj/probe-588/batch.yml
  inroot $PY -I -c 'import sys, yaml
print(yaml.safe_dump({"tasks": [{"task_id": "1", "task_name": "submit-report-name-probe",
                                  "role": "opus_coding_team.engineer", "instruction": sys.argv[1]}]},
                     sort_keys=False, width=100000), end="")' "$(inroot $PY -I $X588 instruction $ROOT)" > $batch
  print -r -- "batch: $batch"; cat $batch
  [[ ${VERIFY588_DRY:-} == 1 ]] && { print -r -- "DRY (rehearsal): stopped before agent-runner --swarm-input"; return 0; }
  inroot $VROOT/bin/agent-runner --swarm-input $batch > $OUT/realhost-launch.yml 2>&1
  local alias=$(grep -m1 "alias:" $OUT/realhost-launch.yml | awk '{print $NF}')
  [[ -n $alias ]] || { print -r -- "STOP: launch failed:"; cat $OUT/realhost-launch.yml; return 1; }
  print -r -- "Engineer alias: $alias"
  inroot $PY -I $X588 ended $ROOT $alias 600 || { print -r -- "STOP: $alias did not end; later: zsh $THIS check $alias"; return 1; }
  IDS=($alias); STEP=check; run_step
  ;;
check)
  local alias=${IDS[1]:-}
  [[ -n $alias ]] || { print -r -- "usage: zsh $THIS check <Engineer alias>"; return 2; }
  say "[check] read only: $alias's reports through session_reports, its reply and its own transcript. Dialog: none."
  mkdir -p $OUT
  inroot $VROOT/bin/python -I $X588 check $ROOT $alias 2>&1 | tee $OUT/realhost-check.txt; local rc=${pipestatus[1]}
  print -r -- "realhost: $( (( rc == 0 )) && print PASS || print FAIL) (copy: $OUT/realhost-check.txt)"
  print -r -- "writes: $OUT/realhost-check.txt only (ROOT is left as it is for inspection). dialog: none."
  print -r -- "next (paste): zsh $THIS suite"
  return $rc
  ;;
suite)
  setopt local_options no_bg_nice
  say "[suite] Main. GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg 2>/dev/null || print unavailable)"
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $o; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $WT || return 1
  versions $V || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP (TMPDIR, outside the Harness) | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY588_PYTEST_ARGS:-}}}) senv=(${(Q)${(z)${VERIFY588_SUITE_ENV:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${(j: :)${(@qq)extra}}" >> $R/run.txt
  (( $#senv )) && print -r -- "REHEARSAL: extra launch environment: $senv" >> $R/run.txt
  cat $R/run.txt
  (cd $WT && launch TMPDIR=$RUNTMP $senv -- $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only. dialog: none."
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: newest suite; FAILED/ERROR node ids classed against 516's current definition. Dialog: none."
  local cur=${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  local K=$D516/$cur
  print -r -- "516 current definition (task.yml current_definition): $K"
  [[ -n $cur && -f $K ]] || { print -r -- "STOP: cannot read 516's current definition '$K'"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet); next: zsh $THIS SR (later)"; return 1; }
  local -a logs=($g/shards/*.log(N.)); (( $#logs )) || logs=($g/suite.txt)
  local line t id new=0 any=0; local -a ids=()
  for id in ${(f)"$(python3 -I $SUITEIDS ids $logs)"}; do
    any=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $id"
    else print -r -- "NEW: $id"; new=1; ids+=$id; fi
  done
  print -l -- $ids > $g/new-ids.txt
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; new=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; new=1 ;;
    esac
  done
  grep -E '^(=+ )?[0-9]+ (passed|failed)|^[0-9]+ (passed|failed)' $g/shards/*(N.) | sed "s#^$g/shards/##"
  mkdir -p $OUT 2>/dev/null && cp $g/run.txt $g/new-ids.txt $OUT/ 2>/dev/null && cp $g/suite.txt $OUT/suite-${g:t}.txt 2>/dev/null
  print -r -- "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  print -r -- "NEW node ids ($#ids, one per line): $g/new-ids.txt"
  print -r -- "writes: $g/new-ids.txt and copies in $OUT only. dialog: none."
  if (( $#ids )); then
    print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)ids}"
    print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)g}/new-ids.txt"
  else
    print -r -- "next: none (no NEW id); report the SR verdict"
  fi
  return $new
  ;;
suite-base)
  setopt local_options no_bg_nice
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then
    [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file '${IDS[2]:-}'; SR writes it (new-ids.txt)"; return 2; }
    ids=(${(f)"$(<${IDS[2]})"})
  else ids=("${(@)IDS}"); fi
  ids=(${ids:#})
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>...   (SR prints both)"; return 2; }
  say "[suite-base] Main. $#ids node ids: base (GraphTraj $GTBASE), then candidate (HEAD $HEAD), both with graftling $GCOMMIT (wheel). Dialog: none. No login."
  print -l -- "  id: "${^ids}
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun this command later"; print -r -- $o; return 1; }
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  print -r -- "base checkout: $B ($(git -C $B log --oneline -1)); candidate checkout: $WT ($(git -C $WT log --oneline -1))"
  local VB=$T/venv-base-${GTBASE[1,8]} VC=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $VB $B && suite_venv $VC $WT || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R || return 1
  print -l -- $ids > $R/ids.txt
  local side dir V rc
  for side dir V in base $B $VB candidate $WT $VC; do
    run_root $side || return 1
    say "$side: pytest in $dir; $(versions $V)"
    (cd $dir && launch TMPDIR=$RUNTMP -- $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $R/$side-collected.txt 2>&1)
    python3 -I $SUITEIDS present $R/$side-collected.txt $R/ids.txt > $R/$side-ids.txt 2> $R/$side-missing.txt
    [[ -s $R/$side-missing.txt ]] && print -r -- "not on $side (not run there): $(tr '\n' ' ' < $R/$side-missing.txt)"
    local -a run=(${(f)"$(<$R/$side-ids.txt)"})
    if (( $#run )); then
      (cd $dir && launch TMPDIR=$RUNTMP -- $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $R/$side.txt 2>&1); rc=$?
    else print -r -- "(no id present on $side)" > $R/$side.txt; rc=5; fi
    print -r -- "$side: pytest exit=$rc, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $R/$side.txt | tail -1) (output: $R/$side.txt)"
    python3 -I $SUITEIDS errors $R/$side.txt > $R/$side-errors.txt
  done
  say "classification (each id: base, then candidate)"
  python3 -I $SUITEIDS classify $R/ids.txt $R/base.txt $R/candidate.txt | tee $R/classification.txt; local fails=${pipestatus[1]}
  mkdir -p $OUT 2>/dev/null && cp -R $R $OUT/ 2>/dev/null
  print -r -- "first E line + raise location per failing test: $R/base-errors.txt and $R/candidate-errors.txt"
  print -r -- "writes: $T (venvs, $B, $R), a copy in $OUT/${R:t} and the pytest temp roots under $PYTEST_TMP only. dialog: none."
  print -r -- "next: report the classification ($R/classification.txt); a candidate-only id is a regression of this Task"
  return $fails
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $HEAD -> $URL $BRANCH. Dialog: none expected (your usual GitHub login)."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && { pass "already on GitHub"; print -r -- "next: none"; return 0; }
  print -r -- "authors and committers since base: $(git -C $WT log --format='%an <%ae> | %cn <%ce>' $GTBASE..$HEAD | sort -u)"
  git -C $WT push $URL "${HEAD}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && pass "GitHub $BRANCH = $HEAD" || { fail "GitHub $BRANCH is not $HEAD"; return 1; }
  print -r -- "writes: the GitHub branch $BRANCH only. dialog: none. next: none"
  ;;
*) print -r -- "usage: zsh $THIS pre|install|realhost|check <alias>|suite|SR|suite-base --from <file>|<ids>...|push"; return 2 ;;
esac
}
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: node ids; check: the Engineer alias
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
