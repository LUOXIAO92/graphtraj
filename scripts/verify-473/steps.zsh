#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 473 Main checks: a Codex child ends with its own outcome after its owner's main thread has returned.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/473-codex-child-interpreter-shutdown/scripts/verify-473/steps.zsh <0|1|2|3>
# 0  preflight: claude --version, the commit under test and the expected HEAD, scratch and output directories.
# 1  suite venv (about 1 min); reused when it already exists.
# 2  focused acceptance: the 473, 462 and approved-recovery tests (about 4 min).
# 3  full suite in the background (about 20 min).
# No Runtime host or model is used: the tests run a fake Codex peer, so no login prompt is needed.
# Harness tmp/473 holds only the suite venv; all pytest temp is under ${TMPDIR:-/tmp}/verify-473.
# Never changes production .venv-runtime (only copies click, yaml and websockets out of it, read only), deletes
# nothing, and signals no process it did not start.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/473-codex-child-interpreter-shutdown
THIS=${0:A}
COMMIT=$(git -C $WT rev-parse HEAD)
B=$H/tmp/473
# pytest temp stays outside the Harness: a test that walks up from its temp directory
# must never reach the real Harness (482).
T=${TMPDIR:-/tmp}/verify-473
SV=$B/suite-venv
O=$H/.graphtraj/core/state/tasks/473-codex-child-interpreter-shutdown/realhost
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
EXPECT_CLAUDE=2.1.325
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $1"; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME PATH=$SV/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$T "$@"; }
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/
}

step_0() {
  say "[0] Main. preflight. Dialog: none."
  local V=$(claude --version 2>&1 | head -1)
  print -r -- "claude --version: $V | expected $EXPECT_CLAUDE: $([[ $V == $EXPECT_CLAUDE* ]] && print yes || print NO)"
  print -r -- "launched via zsh: ${ZSH_VERSION:+yes ($ZSH_VERSION)} | script: $THIS"
  print -r -- "commit under test: $COMMIT"
  # A file cannot name its own commit: the expected HEAD is the commit that last changed this script.
  local EXPECT=$(git -C $WT log -1 --format=%H -- scripts/verify-473/steps.zsh)
  print -r -- "expected HEAD (last commit of this script): $EXPECT | HEAD equals it: $([[ $COMMIT == $EXPECT ]] && print yes || print NO)"
  [[ $COMMIT == $EXPECT ]] || { print "STOP: HEAD is not the commit that adds this script; report to the Leader"; return 1; }
  mkdir -p $T $O || return 1
  [[ ${T:A} != $H && ${T:A} != $H/* ]] || { print "STOP: pytest temp $T is inside the Harness"; return 1; }
  print -r -- "pytest temp (outside the Harness): ${T:A}"
  print -r -- "suite venv: $SV | output: $O"
  print "No Runtime host or model is used (fake Codex peer); no login prompt is needed."
  next "zsh $THIS 1"
}

step_1() {
  say "[1] Main. suite venv $SV (about 1 min). Dialog: none."
  if [[ -x $SV/bin/python ]]; then
    print "venv exists: reused (no rebuild)"
  else
    $CONDA -m venv --system-site-packages $SV || return 1
    $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
        -e $WT/src/graftling -e $WT || return 1
    copy_deps $SV || return 1
  fi
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj, graftling, websockets; print(graphtraj.__file__, graftling.__file__)')
  print -r -- "Observable: both paths under $WT/src/ (graphtraj/ and graftling/)"
  next "zsh $THIS 2"
}

step_2() {
  say "[2] Main. focused acceptance (about 4 min). Dialog: none."
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  (cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q --basetemp=$T/bt-focused \
      tests/test_codex_child_interpreter_shutdown_473.py tests/test_codex_tool_reclaim_462.py \
      tests/test_approved_recovery.py tests/test_graphtraj_public_agents_api.py 2>&1 \
      | tee $O/02-focused.txt | tail -n 3)
  print "Observable: no failures. test_child_ends_completed_after_the_owner_main_thread_returns passes (outcome completed);"
  print "tests/test_approved_recovery.py covers the recovery-notice site the team could not run in its sandbox;"
  print "test_graphtraj_public_agents_api.py::test_graphtraj_uses_only_published_agents_names passes (published in_thread)."
  print -r -- "Output: $O/02-focused.txt"
  next "zsh $THIS 3"
}

step_3() {
  say "[3] Main. full suite at $COMMIT in the background (about 20 min). Dialog: none."
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  (cd $WT && nohup env -i HOME=$HOME PATH=$SV/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$T \
      $SV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/suite-shards \
      > $O/03-suite.txt 2>&1 &)
  print "started at $(date +%T)."
  print -r -- "Status (any time): tail -n 25 $O/03-suite.txt"
  print -r -- "Failing IDs: $O/suite-shards/failures.txt"
  print "Observable: no failure beyond the dev baseline (latest known: 461 at c4cb357d, 2 failed:"
  print "test_srt_gone_before_launch_is_refused (470) and test_run_test_shards::test_hanging_shard_is_stopped_and_reported (472))."
  print "A failure in any test file with codex, approval, review, recovery, 462 or 473 in its name is new and blocks acceptance."
  print "The leftover line must show remaining=0."
  next "tail -n 25 $O/03-suite.txt"
}

case $STEP in
  0) step_0 ;;
  1) step_1 ;;
  2) step_2 ;;
  3) step_3 ;;
  *) print "usage: zsh ${0:A} <0|1|2|3>" ;;
esac
