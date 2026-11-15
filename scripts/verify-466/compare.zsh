#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 466: base d5b9797f vs candidate 11bd4f94 on every test that failed in a 466 full-suite run.
#   zsh <this> prep    Main, foreground (< 5 min): both trees (git archive -> own git repo) and venvs under Harness tmp/466/compare.
#   zsh <this> check   Main, foreground (< 3 min): one test per side, full output shown; must say '1 passed' (or a real failure).
#   zsh <this> run     Main: starts the alternating rounds in the background; stops itself after 40 min.
#   zsh <this> tally   Main, any time: per-test failures per side; done at '== compare done'.
# pytest temp and cwd live under $TMPDIR, which must be outside the Harness (Task 482). Trees and venvs are in
# Harness tmp/466/compare; logs in the Task's realhost/compare. Signals only its own process group.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/466-session-read-in-agents
THIS=${0:A}
BASE_C=d5b9797f
CAND_C=11bd4f94
REPS=${VERIFY466_REPS:-5}
W=$H/tmp/466/compare
OUT=$H/.graphtraj/core/state/tasks/466-session-read-in-agents/realhost/compare
PT=${TMPDIR:-/tmp}/graphtraj-466-compare
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
TESTS=(
  tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations
  tests/test_child_env_own_key.py::test_codex_declared_ordinary_name_needs_no_set
  tests/test_claude_runner.py::test_child_registration_follows_its_owning_execution
  tests/test_claude_runtime.py::test_claude_later_prompt_hook_is_answered_during_one_slow_collection
  tests/test_claude_termination.py::test_current_group_requires_original_leader
  tests/test_execution_budgets.py::test_installed_runner_delivers_sampled_stop_to_leader_before_engineer_stops
  tests/test_hosted_cli.py::test_cli_host_returns_a_slow_read_result_instead_of_a_timeout
  tests/test_hosted_cli.py::test_cli_host_returns_a_slow_write_receipt_instead_of_a_timeout
  tests/test_resume_after_owner_exit.py::test_unconfirmed_termination_keeps_the_session_stopped
  tests/test_team_replacement.py::test_replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session
)
mkdir -p $W $OUT $PT
if [[ ${PT:A}/ == $H/* ]]; then print "STOP: pytest temp $PT is inside the Harness; set TMPDIR outside $H"; exit 1; fi
path=(/opt/homebrew/bin $HOME/.local/bin $path)
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} COLUMNS=250 TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

# One pytest run of tests ($3...) for side $1 with basetemp label $2; cwd and temp outside the Harness.
side_pytest() {
  local side=$1 label=$2; shift 2
  local S=$W/$side/src
  mkdir -p $PT/cwd
  (cd $PT/cwd && clean $W/$side/venv/bin/python -m pytest -q -rfE --tb=short -p no:warnings -p no:cacheprovider \
      --rootdir=$S -c $S/pyproject.toml --basetemp=$PT/bt/$label ${@/#/$S/})
}

prep() {
  print "claude --version: $(claude --version 2>&1 | head -1)"
  print "load: $(sysctl -n vm.loadavg)"
  print "pytest temp and cwd: ${PT:A} (outside the Harness: yes)"
  local side commit S D
  for side commit in base $BASE_C cand $CAND_C; do
    print "### $side $(git -C $WT rev-parse $commit)"
    rm -rf $W/$side; mkdir -p $W/$side/src
    git -C $WT archive $commit | tar -x -C $W/$side/src || return 1
    # The installed-environment fixtures run 'git ls-files', so each tree is its own repository.
    (cd $W/$side/src && git init -q && git add -A && git -c user.name=466 -c user.email=466@invalid commit -qm "$commit") || return 1
    $CONDA -m venv --system-site-packages $W/$side/venv || return 1
    $W/$side/venv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps \
        --no-build-isolation -e $W/$side/src/src/graftling -e $W/$side/src 2>&1 | grep -vi cache
    S=($RT/lib/python*/site-packages(N)); D=($W/$side/venv/lib/python*/site-packages(N))
    cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/pyyaml-*.dist-info(N) \
        $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
    (cd $PT && $W/$side/venv/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m
print("imports:", graftling.__file__, graphtraj.__file__, "| click", m.version("click"), "| websockets", m.version("websockets"))')
  done
  print "== prep done. Next (Main): zsh $THIS check"
}

check() {
  print "claude --version: $(claude --version 2>&1 | head -1)"
  print "pytest temp and cwd: ${PT:A}"
  local side
  for side in base cand; do
    print "### check $side: one case, full output"
    side_pytest $side check-$side 'tests/test_claude_termination.py::test_current_group_requires_original_leader[orphan]' 2>&1 | tail -40
  done
  print "== check done. If both say '1 passed', next (Main): zsh $THIS run"
}

run() {
  [[ -x $W/base/venv/bin/python && -x $W/cand/venv/bin/python ]] || { print "STOP: run prep first"; return 1; }
  rm -f $OUT/compare.txt $OUT/round-*.log
  (cd $PT && nohup zsh $THIS _run >> $OUT/compare.txt 2>&1 &)
  print "started $(date +%T); $REPS rounds x (base, cand), <= 40 min. Status: zsh $THIS tally"
}

_run() {
  print "== compare start $(date +%T) reps $REPS load $(sysctl -n vm.loadavg) pytest temp ${PT:A}"
  clean $W/cand/venv/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=2400))
except subprocess.TimeoutExpired:
    print("== 40 min limit reached: stopping", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' zsh $THIS _rounds
  print "== compare done $(date +%T) exit $? load $(sysctl -n vm.loadavg)"
}

_rounds() {
  local rep side log
  for rep in {1..$REPS}; do
    for side in base cand; do
      log=$OUT/round-$rep-$side.log
      print "=== round $rep $side $(git -C $W/$side/src log -1 --format=%s) $(date +%T) load $(sysctl -n vm.loadavg)"
      side_pytest $side $side-$rep $TESTS > $log 2>&1
      grep -E '^(FAILED|ERROR) |^E  |[0-9]+ (passed|failed|error)' $log | cut -c1-300 | head -60
    done
  done
}

tally() {
  [[ -f $OUT/compare.txt ]] || { print "no $OUT/compare.txt yet"; return 1; }
  grep -E '^(==|===) |[0-9]+ (passed|failed|error)' $OUT/compare.txt
  print "== per test: base failures / cand failures (rounds counted: base $(grep -c '^=== round .* base' $OUT/compare.txt), cand $(grep -c '^=== round .* cand' $OUT/compare.txt))"
  local t b c
  for t in $TESTS; do
    b=$(awk -v t="${t##*::}" '/^=== round/{s=$4} ($1=="FAILED"||$1=="ERROR") && index($2,t) && s=="base"{n++} END{print n+0}' $OUT/compare.txt)
    c=$(awk -v t="${t##*::}" '/^=== round/{s=$4} ($1=="FAILED"||$1=="ERROR") && index($2,t) && s=="cand"{n++} END{print n+0}' $OUT/compare.txt)
    print "$b / $c  ${t##*/}"
  done
}

case ${1:-} in
  prep) prep 2>&1 | tee $OUT/prep.txt ;;
  check) check 2>&1 | tee $OUT/check.txt ;;
  run) run ;;
  _run) _run ;;
  _rounds) _rounds ;;
  tally) tally ;;
  *) print "usage: zsh $THIS <prep|check|run|tally>" ;;
esac
