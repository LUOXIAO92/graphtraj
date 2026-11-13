#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 463 real-host check: a DSH child, created through GraphTraj's agents control by a probe owner, runs one Bash
# tool whose /usr/bin/perl setsid's a /bin/sleep 4632 (out of every group DSH knows); the owner alone is SIGKILLed;
# the residue is printed; one reconciling read must stop it through the recorded descendants, and nothing else.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/463-dsh-child-tool-process-reclaim/scripts/verify-463/steps.zsh <00|01|02|03>
# 00  Main. preflight: scratch venv from COMMIT, the fix-present line, isolated project with the user's dsh role
#     (copied from this project's roles.yml; connection and model unchanged), the DSH version/model/key-name line.
# 01  Main. starts the probe owner in the background (it creates the DSH child) and returns.
# 02  Main. waits (<= 8 min) until the child's record lists a live setsid'd sleep 4632; SIGKILLs only the owner;
#     prints the residue; three bystanders; one reconciling read; CHECK 1-4; stops the bystanders.
# 03  Main. full suite at HEAD in the background (self-terminating after 25 min).
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only), the user's
# dotfiles, ~/.dsh, ~/.claude or ~/.codex. No key value is printed: only the key variable's name passes through.
# Rehearsal without a model: VERIFY463_NO_MODEL=1 (00 uses a stand-in role and stops before DSH; 02 runs on a stub);
# VERIFY463_DEPS names a site-packages directory added to the rehearsal venv instead of production's deps.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/463-dsh-child-tool-process-reclaim
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY463_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY463_BASE:-$HOME/graphtraj-verify-463}
OUT=${VERIFY463_OUT:-$H/.graphtraj/core/state/tasks/463-dsh-child-tool-process-reclaim/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
PID01=$OUT/01-owner.pid
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
# Child commands run without this shell's GraphTraj Session variables. Only the dsh role's key variable passes,
# by name; its value is never printed.
clean() {
  local K=$(cat $P/.graphtraj/probe-463/keyvar 2>/dev/null) pass=()
  [[ -n $K && -n ${(P)K:-} ]] && pass=("$K=${(P)K}")
  env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
      LANG=${LANG:-en_US.UTF-8} $pass "$@"
}
# click 8.5.0, yaml and websockets from production, copied (never changed there) into a venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
  [[ $(cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print(m.version("click"))') == 8.5.0 ]] \
    || { print "STOP: click in $1 is not production's 8.5.0"; return 1; }
}
probe() { (cd $P && clean $VV/bin/python -I $SD/probe.py "$@") }
# STOP, changing nothing, while an earlier owner or a probe sleep still lives. Signals nothing.
guard() { $CONDA -I $SD/probe.py idle $OUT - }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  guard || return 1
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  if [[ -n ${VERIFY463_NO_MODEL:-} ]]; then
    print "VERIFY463_NO_MODEL set: no production deps copied (rehearsal); VERIFY463_DEPS=${VERIFY463_DEPS:-unset} on the path."
    [[ -n ${VERIFY463_DEPS:-} ]] && print -r -- $VERIFY463_DEPS > $VV/lib/python3.13/site-packages/rehearsal-deps.pth
  else
    copy_deps $VV || return 1
  fi
  (cd /tmp && $VV/bin/python -I -c 'import inspect, graftling.dsh.execution as e, graftling.dsh.driver as d
import graphtraj.execution.agent_driver as a
print("dsh execution:", e.__file__)
print("463 fix: dsh owner samples:", "DescendantSampler" in inspect.getsource(e.DshExecution.__init__),
      "| sets the marker:", "MEMBER_RUN_ENV" in inspect.getsource(e.DshExecution.prepare_launch),
      "| dsh driver records it:", "tool_descendants" in inspect.getsource(d.DshDriver.start),
      "| agents driver records dsh:", "(\x27claude\x27, \x27dsh\x27)" in inspect.getsource(a.AdapterDriver.start))') || return 1
  say "isolated project $P (git, graphtraj setup, the dsh role)"
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 463 probe" > README.md && git add README.md \
      && git -c user.name=463 -c user.email=463@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  local roles=$H/.graphtraj/roles.yml
  [[ -n ${VERIFY463_NO_MODEL:-} ]] && roles=-
  (cd $P && clean $VV/bin/python -I $SD/probe.py prepare $P $roles) || { print "STOP: the dsh role is not usable (text above)"; return 1; }
  [[ -n ${VERIFY463_NO_MODEL:-} ]] && { print "VERIFY463_NO_MODEL set: stopping before DSH (rehearsal)."; return 0; }
  say "DSH: version and the key variable (name only)"
  print "dsh: $(command -v dsh) $(clean dsh --version 2>&1 | head -1)"
  local K=$(cat $P/.graphtraj/probe-463/keyvar)
  print "key variable ${K:-none (DSH login)} set in this shell: $([[ -n $K && -n ${(P)K:-} ]] && print yes || print no)"
  if [[ -n $K && -z ${(P)K:-} ]]; then
    print "STOP: the dsh role's key variable $K is not set in this shell. Main: run 00 from a shell that has it."
    return 1
  fi
  print "Success: '463 fix: dsh owner samples: True | sets the marker: True | dsh driver records it: True | agents driver records dsh: True',"
  print "deps click 8.5.0, a 'dsh role' line with your model and connection, 'roles OK', and a DSH version."
  print "The model itself first answers in 01 (its log shows CREATED and, if DSH asks, the owner's approval)."
  next "zsh $THIS 01"
}

step_01() {
  say "[01] Main. starts the probe owner in the background; it creates the DSH child. Dialog: none. Returns at once."
  [[ -x $VV/bin/graphtraj && -f $P/.graphtraj/roles.yml ]] || { print "STOP: run 00 first"; return 1; }
  guard || return 1
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  rm -f $PID01 $P/.graphtraj/probe-463/owner.json
  (cd $P && clean nohup $VV/bin/python -I $SD/probe.py owner $P $P/.graphtraj/probe-463/owner.json \
      > $OUT/01-owner.log 2>&1 & print $! > $PID01)
  print "owner pid $(cat $PID01) (in $PID01), log $OUT/01-owner.log"
  print "The owner answers only an approval for the exact command; no native dialog appears (dsh web runs headless)."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. waits (<= 8 min) for the child's setsid'd sleep; kills only the owner; residue; one read; CHECK 1-4. Dialog: none."
  if [[ -n ${VERIFY463_NO_MODEL:-} ]]; then
    print "VERIFY463_NO_MODEL set: stub owner and child instead of 01 (rehearsal)."
    probe stub $P - || return 1
  else
    [[ -f $PID01 ]] || { print "STOP: run 01 first"; return 1; }
  fi
  probe ready $P 480 || { print "STOP: not ready; nothing was signalled. Owner log tail:"; tail -n 15 $OUT/01-owner.log 2>/dev/null; return 1; }
  probe kill $P $OUT/02-kill.json
  local rc=$?
  print ""
  print "Success: a 'RESIDUE ... still alive' line naming /bin/sleep $(print 4632), then 'summary: ALL PASS': 1 owner-exited;"
  print "2 escaped_processes stopped the survivors, remaining [], no error; 3 no recorded identity alive; 4 bystanders alive."
  print "A STOP line means nothing was signalled."
  next "zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV > $OUT/03-suite.txt 2>&1 || { cat $OUT/03-suite.txt; return 1; }
  cat $OUT/03-suite.txt
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee -a $OUT/03-suite.txt
  rm -rf $OUT/03-shards
  (cd $WT && nohup zsh $THIS _03run >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time): tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows '== totals:'; failing IDs are in $OUT/03-shards/failures.txt."
}

step__03run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit.
  env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
      LANG=${LANG:-en_US.UTF-8} $SV/bin/python -I -c 'import os, signal, subprocess, sys
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
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $OUT/03-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $OUT/03-suite.txt | tail -1)"
  print "== baseline: compare with the dev full-suite run Main last used (463 base b3d522ad)"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|01|02|03>" ;;
esac
