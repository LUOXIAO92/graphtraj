#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 480: a sandboxed Pi member writes its assigned report (.state symlink into the private state).
# ISOLATED projects under the Harness tmp/480 (own git, own .graphtraj; Harness AGENTS.md is not an ancestor
# instruction: projects live under tmp/480 and Pi members get only their Worktree's instruction files).
#   zsh <this file> <00|R|V|T>      order: 00 -> R (production, reproduce) -> V (candidate) -> T (full suite)
# Wait limits (each enforced by alarms/self-stops in the step):
#   00 <= 10 min  offline venv builds (3 x <= 2 min) + one pi call (<= 4 min)
#   R  <= 10 min  dispatch (<= 9 min, the member's turn <= 8 min) + judge (<= 1 min)
#   V  <= 10 min  same as R with the candidate
#   T  <= 35 min  8-shard suite (self-stops at 25 min) + reruns of its failures on the base (<= 10 min)
#   Sum Main should plan for: 65 min.
# Every step: Dialog: none; signals only the processes it started; never prints the DEEPSEEK_API_KEY value.
# Venvs are built offline (no PyPI), as verify-482 build(). Rehearsal without a model: VERIFY480_NO_MODEL=1 ... 00
# Rehearsal of T on a subset only: VERIFY480_T_ARGS='tests/<file>.py' (Main never sets it).
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
REPO=${SD:h:h}
BASE=${VERIFY480_BASE:-$H/tmp/480}
OUT=${VERIFY480_OUT:-$H/.graphtraj/core/state/tasks/480-pi-member-report-path-sandbox/realhost}
RT=${VERIFY480_RT:-$H/.venv-runtime}
CONDA=${VERIFY480_PYTHON:-/Users/luoxiao/miniconda3/bin/python3.13}
COMMIT=$(git -C $REPO rev-parse HEAD)
BASE_COMMIT=6160ed7a
SRC=$BASE/src-${COMMIT[1,12]}
BSRC=$BASE/src-base-$BASE_COMMIT
# VERIFY480_CAND only for a model-less rehearsal with an existing installation; Main never sets it.
CAND=${VERIFY480_CAND:-$BASE/candidate-${COMMIT[1,12]}}
TESTENV=$BASE/testenv-${COMMIT[1,12]}
BASEENV=$BASE/testenv-base-$BASE_COMMIT
SHARDS=8
STEP=${1:-help}
path=($RT/bin /opt/homebrew/bin $HOME/.local/bin $path)
LIMIT2=(/usr/bin/perl -e 'alarm 120; exec @ARGV')
LIMIT4=(/usr/bin/perl -e 'alarm 240; exec @ARGV')
LIMIT9=(/usr/bin/perl -e 'alarm 540; exec @ARGV')
LIMIT1=(/usr/bin/perl -e 'alarm 60; exec @ARGV')
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Hosts run without this shell's GraphTraj Session variables; DEEPSEEK_API_KEY passes by name, never printed.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
# probe <limit-array-name> <venv> <project> <args...>: the probe under the installation being tested.
probe() { local lim=$1 venv=$2 proj=$3; shift 3
  (cd $proj && clean ${(P)lim} $venv/bin/python -I $SD/probe.py "$@") | redact; return ${pipestatus[1]}; }
installed() { (cd / && $1/bin/python -I -c 'import graphtraj; print(graphtraj.__file__)' 2>&1); }
# group <seconds> <cmd...>: run (clean env, this TMPDIR) in its own process group; on the limit, TERM then KILL
# that group only; exit 124. Otherwise the command's real exit status.
group() { clean $CONDA -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[2:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=float(sys.argv[1])))
except subprocess.TimeoutExpired:
    print(f"== {sys.argv[1]} s limit reached: stopping this process group", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' "$@"; }

archive() {  # archive <commit> <dir>: the exact commit's tree (git archive)
  [[ -f $2/pyproject.toml ]] && { print "existing archive $2 kept"; return 0; }
  rm -rf $2 && mkdir -p $2 && git -C $REPO archive $1 | tar -x -C $2
}
build() {  # build <venv> <source> <editable|installed>: offline, as verify-482 build()
  local V=$1 S=($RT/lib/python*/site-packages(N)) D
  [[ -x $V/bin/python && -f $V/.built-480 ]] && { print "existing venv $V kept"; return 0; }
  rm -rf $V; $LIMIT2 $CONDA -m venv --system-site-packages $V || return 1
  local e=(); [[ $3 == editable ]] && e=(-e)
  $LIMIT2 $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps \
      --no-build-isolation $e $2/src/graftling $e $2 2>&1 | grep -vi cache
  D=($V/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  touch $V/.built-480
}

project() {  # project <venv> <dir>: git init, graphtraj setup, roles and Task 1 with that installation
  local venv=$1 proj=$2
  if [[ -d $proj/.git ]]; then print "existing project $proj: git init and setup skipped (rerun)"; else
    mkdir -p $proj && (cd $proj && git init -q -b main && print -r -- "# 480 probe" > README.md && git add README.md \
      && git -c user.name=480 -c user.email=480@invalid commit -qm "Initial source") || return 1
    (cd $proj && print y | clean $LIMIT1 $venv/bin/graphtraj setup 2>&1 | tail -2) || return 1
  fi
  probe LIMIT1 $venv $proj prepare $proj || { print "STOP: prepare failed in $proj (2 register, 3 roles, 4 not ready)"
    [[ -n ${VERIFY480_NO_MODEL:-} ]] && print "(rehearsal: continuing)" || return 1; }
}

step_00() {
  say "[00] preflight. Dialog: none. Wait limit: 10 min (3 offline venv builds <= 2 min each, pi call <= 4 min). Output also in $OUT/00.txt"
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} (launched via /bin/zsh)"
  print "candidate commit: $COMMIT (from $REPO); base commit for failure reruns: $BASE_COMMIT"
  [[ -z $(git -C $REPO status --porcelain --untracked-files=no) ]] || print "NOTE: $REPO has uncommitted tracked changes; the candidate is the commit above."
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset"
  print "production installation ($RT): $(installed $RT)"
  say "offline venvs (conda --system-site-packages, pip --no-index --no-deps; click/yaml/websockets from $RT)"
  archive $COMMIT $SRC || return 1
  archive $BASE_COMMIT $BSRC || return 1
  if [[ -z ${VERIFY480_CAND:-} ]]; then build $CAND $SRC installed || return 1; fi
  build $TESTENV $SRC editable || return 1
  build $BASEENV $BSRC editable || return 1
  print "candidate runtime ($CAND): $(installed $CAND)"
  local mod=$(cd / && $CAND/bin/python -I -c 'import graphtraj.runtimes.pi.pi_adapter as m; print(m.__file__)')
  cmp -s $mod $SRC/src/graphtraj/runtimes/pi/pi_adapter.py \
    && print "candidate runtime imports the archived exact commit $COMMIT: YES ($mod identical to $SRC copy)" \
    || { print "STOP: candidate runtime pi_adapter.py differs from git archive $COMMIT"; return 1; }
  grep -q "'write_paths': list(request\['reports'\])" $mod \
    && print "candidate has the 480 report write grant: YES" || { print "STOP: candidate lacks the 480 change"; return 1; }
  print "candidate test venv ($TESTENV): $(installed $TESTENV)"
  print "base test venv ($BASEENV): $(installed $BASEENV)"
  say "Pi sandbox (roles.yml pi_member = production pi_dsh_trial.team_leader pi values)"
  if ! probe LIMIT1 $RT $BASE pisandbox -; then
    [[ -n ${VERIFY480_NO_MODEL:-} ]] && print "(rehearsal: continuing without the Pi sandbox)" \
      || { print "STOP: Pi sandbox incomplete (above)"; return 1; }
  fi
  say "isolated projects: R (production) $BASE/project-R ; V (candidate) $BASE/project-V"
  project $RT $BASE/project-R || return 1
  project $CAND $BASE/project-V || return 1
  [[ -n ${VERIFY480_NO_MODEL:-} ]] && { print "VERIFY480_NO_MODEL set: stopping before any model (rehearsal)."; return 0; }
  say "pi answers one line (the one read-only model call; no tools; <= 4 min)"
  (cd $BASE/project-R && clean $LIMIT4 pi --print --no-tools --provider deepseek --model deepseek-flash \
    'Reply with exactly one line: MODEL: your model name. Use no tool.' < /dev/null 2>&1 | redact > $OUT/00-pi.txt)
  print "pi reply: $(tail -1 $OUT/00-pi.txt)"
  grep -q 'MODEL:' $OUT/00-pi.txt && print "PASS pi-answers: MODEL line present" || { print "FAIL pi-answers (see $OUT/00-pi.txt)"; return 1; }
  next "zsh $THIS R 2>&1 | tee $OUT/R.txt"
}

member() {  # member <label> <venv> <project>
  local label=$1 venv=$2 proj=$3
  say "[$label] $(installed $venv) dispatches pi_member on Task 1 in $proj via agent-runner --swarm-input (public CLI; no model Main). Dialog: none. Wait limit: 10 min (dispatch <= 9 min, judge <= 1 min)."
  [[ -f $OUT/$label-dispatch.yml ]] && print "existing $OUT/$label-dispatch.yml: dispatch skipped (rerun judges only)" \
    || probe LIMIT9 $venv $proj dispatch $proj $OUT $label
  probe LIMIT1 $venv $proj judge $proj $OUT $label; local rc=$?
  print "[$label] overall: $([[ $rc == 0 ]] && print PASS || print FAIL) (rc=$rc)"
  return $rc
}

step_R() {
  member R $RT $BASE/project-R
  print "Expected before the fix: FAIL report-written/report-listed (reproduction), PASS extra-absent/roles-unchanged."
  next "zsh $THIS V 2>&1 | tee $OUT/V.txt"
}
step_V() {
  print "candidate commit: $COMMIT"
  member V $CAND $BASE/project-V; local rc=$?
  next "zsh $THIS T 2>&1 | tee $OUT/T.txt"
  return $rc
}

step_T() {
  say "[T] full suite on candidate $COMMIT, $SHARDS shards. Dialog: none. Wait limit: 35 min (suite self-stops at 25 min; base reruns <= 10 min)."
  [[ -d $SRC && -x $TESTENV/bin/python && -x $BASEENV/bin/python ]] || { print "STOP: run 00 first"; return 1; }
  local T=${TMPDIR:-/tmp} enc
  enc=$(cd / && $TESTENV/bin/python -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from harness_isolation import enclosing_harness as e; print(e(sys.argv[2]) or "")' $SRC/tests $T)
  if [[ -n $enc || ${T:A} == $H || ${T:A} == $H/* ]]; then print "STOP: TMPDIR $T lies inside a Harness (${enc:-$H})"; return 1; fi
  print "TMPDIR=$T: pytest's temp directory is outside the Harness (enclosing Harness: none)"
  print "candidate source $SRC; test venv graphtraj: $(installed $TESTENV)"
  local R=$OUT/T; rm -rf $R-shards; mkdir -p $R-shards
  print "== start $(date +%T)"
  (cd $SRC && group 1500 $TESTENV/bin/python $SRC/scripts/run_test_shards.py --shards $SHARDS --log-dir $R-shards \
    ${=VERIFY480_T_ARGS:-}) > $R-suite.txt 2>&1
  local rc=$?
  print "== suite exit status $rc at $(date +%T) (124 = 25 min self-stop); output $R-suite.txt, shard logs $R-shards/"
  tail -n 4 $R-suite.txt
  touch $R-shards/failures.txt
  print "== failures ($(wc -l < $R-shards/failures.txt | tr -d ' ')):"; cat $R-shards/failures.txt
  say "rerun each failing test id on base $BASE_COMMIT ($BSRC, $BASEENV), same TMPDIR; <= 10 min in total"
  local ids=$R-base-ids.txt; awk '{print $2}' $R-shards/failures.txt | sort -u > $ids
  (cd $BSRC && group 600 $BASEENV/bin/python -I -c 'import subprocess, sys
new = []
for node in open(sys.argv[1]).read().split():
    try:
        rc = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", node],
                            capture_output=True, text=True, timeout=120).returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    verdict = {0: "passes on base -> NEW", 1: "fails on base too", 4: "absent on base -> NEW",
               5: "absent on base -> NEW"}.get(rc, f"base rc={rc} (unclassified)")
    print(f"  {node}: {verdict}", flush=True)
    if "NEW" in verdict:
        new.append(node)
print("== NEW failures (fail on the candidate, pass or are absent on the base): %d" % len(new))
for node in new:
    print("  NEW", node)
print("== end of new failures")' $ids) 2>&1 | redact
  next "report $OUT/{00,R,V,T}.txt to the Task 480 Leader"
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt; exit ${pipestatus[1]} ;;
  R|V|T) step_$STEP ;;
  *) print "usage: zsh $THIS <00|R|V|T>" ;;
esac
