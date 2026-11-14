#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 470 real-host check: the Pi fixture records only launches, so test_srt_gone_before_launch_is_refused
# passes with and without a credential-named variable in the test environment.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/470-pi-srt-test-credential-env/scripts/verify-470/steps.zsh <1|2|3>
# 1  Main. suite venv from this Worktree (editable; click/yaml/websockets copied read-only from production).
# 2  Main. the single test twice: without, and with DEEPSEEK_API_KEY=placeholder-not-a-key (a placeholder, no key).
# 3  Main. full suite in the background (self-stopping after 25 min in its own process group).
# Never changes production .venv-runtime. No key value is read or printed. No standalone sleep.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/470-pi-srt-test-credential-env
B=$H/tmp/470
SV=$B/suite-venv
O=$H/.graphtraj/core/state/tasks/470-pi-srt-test-credential-env/realhost
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
THIS=${0:A}
STEP=${1:-help}
T=tests/test_pi_runtime.py::test_srt_gone_before_launch_is_refused
mkdir -p $B/t $O
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
head_line() { print -r -- "HEAD: $(git -C $WT rev-parse HEAD)"; print -r -- "Dialog: none"; }
clean_tree() { [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes in src, tests or scripts"; return 1; }; }
# click, yaml and websockets from production, copied (never changed there) into the venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($SV/lib/python*/site-packages(N))
  [[ -n ${S[1]:-} && -n ${D[1]:-} ]] || { print "STOP: site-packages not found"; return 1; }
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
}

step_1() {
  say "[1] Main. suite venv $SV from the Worktree. Output also in $O/1.txt"
  head_line
  clean_tree || return 1
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps || return 1
  (cd /tmp && $SV/bin/python -I -c 'import importlib.metadata as m, graphtraj, websockets
print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))
print("websockets imported:", websockets.__file__)
print("graphtraj.__file__ =", graphtraj.__file__)') || return 1
  print "Success: graphtraj.__file__ under $WT/src/graphtraj/ and 'websockets imported'."
  next "zsh $THIS 2"
}

step_2() {
  say "[2] Main. $T without and with a placeholder credential-named variable. Output also in $O/2.txt"
  head_line
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  local label
  for label in without with; do
    local extra=()
    [[ $label == with ]] && extra=(DEEPSEEK_API_KEY=placeholder-not-a-key)
    rm -rf $B/bt-$label
    (cd $WT && env -i HOME=$HOME PATH=$SV/bin:/usr/bin:/bin TMPDIR=$B/t $extra \
        $SV/bin/python -m pytest -p no:cacheprovider -q --basetemp=$B/bt-$label $T > $O/2-$label.log 2>&1)
    print -r -- "-- $label (rc=$?)"
    tail -n 3 $O/2-$label.log
  done
  print "Success: '1 passed' under both."
  next "zsh $THIS 3"
}

step_3() {
  say "[3] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. <= 25 min. Output also in $O/3.txt"
  head_line
  [[ -x $SV/bin/python ]] || { print "STOP: run 1 first"; return 1; }
  clean_tree || return 1
  rm -rf $O/suite-shards
  print "== suite venv: $(cd /tmp && $SV/bin/python -I -c 'import graphtraj; print(graphtraj.__file__)')" > $O/suite.txt
  (cd $WT && nohup zsh $THIS _3run >> $O/suite.txt 2>&1 &)
  print "started at $(date +%T). Done when it shows '== totals:'; failing IDs in $O/suite-shards/failures.txt."
  print "Baseline 461@c4cb357d: 2 failed: tests/test_pi_runtime.py::test_srt_gone_before_launch_is_refused (must now pass)"
  print "and tests/test_run_test_shards.py::test_hanging_shard_is_stopped_and_reported (separate known defect)."
  next "tail -n 25 $O/suite.txt"
}

step__3run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit.
  env -i HOME=$HOME PATH=$SV/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$B/t $SV/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $O/suite-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $O/suite.txt | tail -1)"
  print "== baseline 461@c4cb357d: 2 failed (test_srt_gone_before_launch_is_refused must now pass; test_hanging_shard_is_stopped_and_reported known)"
  print "== failures:"; cat $O/suite-shards/failures.txt 2>/dev/null
}

case $STEP in
  1) step_1 2>&1 | tee $O/1.txt ;;
  2) step_2 2>&1 | tee $O/2.txt ;;
  3) step_3 2>&1 | tee $O/3.txt ;;
  _3run) step__3run ;;
  *) print "usage: zsh ${0:A} <1|2|3>" ;;
esac
