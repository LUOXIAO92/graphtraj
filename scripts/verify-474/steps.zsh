#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 474 Main checks: interrupt returns once the member's terminal record is readable (or marks it pending).
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/474-interrupt-before-execution-record/scripts/verify-474/steps.zsh <0|1|2|3>
# 0  preflight: claude --version, the commit under test, scratch and output directories.
# 1  suite venv (about 1 min); reused when it already exists.
# 2  focused acceptance: tests/test_team_replacement.py (about 1 min).
# 3  full suite in the background (about 20 min).
# No Runtime host or model is used: the tests run fake Runtimes, so no login prompt is needed.
# pytest temp stays under ${TMPDIR:-/tmp}, outside the Harness (a temp inside it let a test reach the real Harness,
# 482); only the suite venv lives in $H/tmp/474.
# Never changes production .venv-runtime (only copies click, yaml and websockets out of it, read only), deletes
# nothing, and signals no process it did not start.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/474-interrupt-before-execution-record
THIS=${0:A}
COMMIT=$(git -C $WT rev-parse HEAD)
B=$H/tmp/474
SV=$B/suite-venv
O=$H/.graphtraj/core/state/tasks/474-interrupt-before-execution-record/realhost
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
EXPECT_CLAUDE=2.1.325
STEP=${1:-help}
PT=${TMPDIR:-/tmp}
if [[ ${PT:A} == $H || ${PT:A} == $H/* ]]; then
  print -r -- "STOP: pytest temp $PT is inside the Harness"
  exit 1
fi
path=(/opt/homebrew/bin $HOME/.local/bin $path)
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $1"; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME PATH=$SV/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$PT "$@"; }
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
  mkdir -p $O || return 1
  print -r -- "output: $O"
  print -r -- "pytest temp: ${PT:A} (outside the Harness: yes)"
  print "No Runtime host or model is used (fake Runtimes); no login prompt is needed."
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
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj, websockets; print(graphtraj.__file__)')
  print -r -- "Observable: a path under $WT/src/graphtraj/"
  next "zsh $THIS 2"
}

step_2() {
  say "[2] Main. focused acceptance (about 1 min). Dialog: none."
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  (cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q --basetemp=$PT/474-bt-focused tests/test_team_replacement.py 2>&1 \
      | tee $O/02-focused.txt | tail -n 3)
  print "Observable: '3 passed', including test_interrupt_returns_after_slow_terminal_record. Output: $O/02-focused.txt"
  next "zsh $THIS 3"
}

step_3() {
  say "[3] Main. full suite at $COMMIT in the background (about 20 min). Dialog: none."
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  (cd $WT && nohup env -i HOME=$HOME PATH=$SV/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$PT \
      $SV/bin/python scripts/run_test_shards.py --shards 6 --log-dir $O/suite-shards > $O/03-suite.txt 2>&1 &)
  print "started at $(date +%T)."
  print -r -- "Status (any time): tail -n 25 $O/03-suite.txt"
  print -r -- "Failing IDs: $O/suite-shards/failures.txt"
  print "Observable: no failure beyond the dev baseline (latest known: 461 at c4cb357d, 2 failed:"
  print "test_srt_gone_before_launch_is_refused (470) and test_run_test_shards::test_hanging_shard_is_stopped_and_reported (472))."
  print "A failure in tests/test_team_replacement.py or in any interrupt test is new and blocks acceptance."
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
