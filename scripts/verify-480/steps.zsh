#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 480: a sandboxed Pi member writes its assigned report (.state symlink into the private state).
# ISOLATED projects under the Harness tmp/480 (own git, own .graphtraj; Harness AGENTS.md is not an ancestor
# instruction: projects live under tmp/480 and Pi members get only their Worktree's instruction files).
#   zsh <this file> <00|R|V|T>      order: 00 -> R (production, reproduce) -> V (candidate) -> T (full suite)
# Wait limits: 00 <= 9 min (installs + one pi call), R <= 9 min, V <= 9 min, T <= 30 min; sum <= 57 min.
# Every step: Dialog: none; signals only the processes it started; never prints the DEEPSEEK_API_KEY value.
# Rehearsal without a model: VERIFY480_NO_MODEL=1 zsh <this file> 00
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
REPO=${SD:h:h}
BASE=${VERIFY480_BASE:-$H/tmp/480}
OUT=${VERIFY480_OUT:-$H/.graphtraj/core/state/tasks/480-pi-member-report-path-sandbox/realhost}
RT=${VERIFY480_RT:-$H/.venv-runtime}
PYTHON=${VERIFY480_PYTHON:-/Users/luoxiao/miniconda3/bin/python3.13}
COMMIT=$(git -C $REPO rev-parse HEAD)
SRC=$BASE/src-${COMMIT[1,12]}
# VERIFY480_CAND only for a model-less rehearsal with an existing installation; Main never sets it.
CAND=${VERIFY480_CAND:-$BASE/candidate-${COMMIT[1,12]}}
TESTENV=$BASE/testenv-${COMMIT[1,12]}
STEP=${1:-help}
path=($RT/bin /opt/homebrew/bin $HOME/.local/bin $path)
LIMIT9=(/usr/bin/perl -e 'alarm 540; exec @ARGV')
LIMIT30=(/usr/bin/perl -e 'alarm 1800; exec @ARGV')
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Hosts run without this shell's GraphTraj Session variables; DEEPSEEK_API_KEY passes by name, never printed.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
# probe <venv> <project> <args...>: the probe under the installation being tested, in that project.
probe() { local venv=$1 proj=$2; shift 2; (cd $proj && clean $LIMIT9 $venv/bin/python -I $SD/probe.py "$@") | redact
  return ${pipestatus[1]}; }
installed() { $1/bin/python -I -c 'import graphtraj; print(graphtraj.__file__)' 2>&1; }

project() {  # project <venv> <dir>: git init, graphtraj setup, roles and Task 1 with that installation
  local venv=$1 proj=$2
  if [[ -d $proj/.git ]]; then print "existing project $proj: git init and setup skipped (rerun)"; else
    mkdir -p $proj && (cd $proj && git init -q -b main && print -r -- "# 480 probe" > README.md && git add README.md \
      && git -c user.name=480 -c user.email=480@invalid commit -qm "Initial source") || return 1
    (cd $proj && print y | clean $venv/bin/graphtraj setup 2>&1 | tail -2) || return 1
  fi
  probe $venv $proj prepare $proj || { print "STOP: prepare failed in $proj (2 register, 3 roles, 4 not ready)"; return 1; }
}

step_00() {
  say "[00] preflight. Dialog: none. Wait limit: 9 min per host call. Output also in $OUT/00.txt"
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} (launched via /bin/zsh)"
  print "candidate commit: $COMMIT (from $REPO)"
  [[ -z $(git -C $REPO status --porcelain --untracked-files=no) ]] || print "NOTE: $REPO has uncommitted tracked changes; the candidate is the commit above."
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset"
  print "production installation ($RT): $(installed $RT)"
  say "candidate installation $CAND from git archive $COMMIT"
  if [[ -x $CAND/bin/agent-runner ]]; then print "existing candidate kept (same commit)"; else
    rm -rf $SRC && mkdir -p $SRC && git -C $REPO archive $COMMIT | tar -x -C $SRC || return 1
    $LIMIT9 $PYTHON -m venv $CAND || return 1
    $LIMIT9 $CAND/bin/python -m pip install -q $SRC/src/graftling $SRC 2>&1 | tail -3
  fi
  print "candidate installation ($CAND): $(installed $CAND)"
  grep -q "'write_paths': list(request\['reports'\])" \
    "$($CAND/bin/python -I -c 'import graphtraj.runtimes.pi.pi_adapter as m; print(m.__file__)')" \
    && print "candidate has the 480 report write grant: YES" || { print "STOP: candidate lacks the 480 change"; return 1; }
  say "Pi sandbox (roles.yml pi_member = production pi_dsh_trial.team_leader pi values)"
  if ! probe $RT $BASE pisandbox -; then
    [[ -n ${VERIFY480_NO_MODEL:-} ]] && print "(rehearsal: continuing without the Pi sandbox)" \
      || { print "STOP: Pi sandbox incomplete (above)"; return 1; }
  fi
  say "isolated projects: R (production) $BASE/project-R ; V (candidate) $BASE/project-V"
  project $RT $BASE/project-R || return 1
  project $CAND $BASE/project-V || return 1
  [[ -n ${VERIFY480_NO_MODEL:-} ]] && { print "VERIFY480_NO_MODEL set: stopping before any model (rehearsal)."; return 0; }
  say "pi answers one line (the one read-only model call; no tools)"
  (cd $BASE/project-R && clean $LIMIT9 pi --print --no-tools --provider deepseek --model deepseek-flash \
    'Reply with exactly one line: MODEL: your model name. Use no tool.' < /dev/null 2>&1 | redact > $OUT/00-pi.txt)
  print "pi reply: $(tail -1 $OUT/00-pi.txt)"
  grep -q 'MODEL:' $OUT/00-pi.txt && print "PASS pi-answers: MODEL line present" || { print "FAIL pi-answers (see $OUT/00-pi.txt)"; return 1; }
  next "zsh $THIS R 2>&1 | tee $OUT/R.txt"
}

member() {  # member <label> <venv> <project>
  local label=$1 venv=$2 proj=$3
  say "[$label] $(installed $venv) dispatches pi_member on Task 1 in $proj via agent-runner --swarm-input (public CLI; no model Main). Dialog: none. Wait limit: 8 min (dispatch) + 1 min (judge)."
  [[ -f $OUT/$label-dispatch.yml ]] && print "existing $OUT/$label-dispatch.yml: dispatch skipped (rerun judges only)" \
    || probe $venv $proj dispatch $proj $OUT $label
  probe $venv $proj judge $proj $OUT $label; local rc=$?
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
  say "[T] full suite on candidate $COMMIT (editable test venv $TESTENV from $SRC). Dialog: none. Wait limit: 30 min."
  [[ -d $SRC ]] || { print "STOP: run 00 first ($SRC missing)"; return 1; }
  if [[ ! -x $TESTENV/bin/pytest ]]; then
    $LIMIT9 $PYTHON -m venv $TESTENV || return 1
    $LIMIT9 $TESTENV/bin/python -m pip install -q -e $SRC/src/graftling -e $SRC pytest 2>&1 | tail -3
  fi
  local tmp=${TMPDIR:-/tmp}
  [[ ${tmp:A} == $H* ]] && { print "STOP: TMPDIR $tmp is inside the Harness"; return 1; }
  print "TMPDIR=$tmp (outside the Harness); graphtraj: $(installed $TESTENV)"
  (cd $SRC && TMPDIR=$tmp $LIMIT30 $TESTENV/bin/python -m pytest -p no:cacheprovider -q 2>&1 | redact | tail -40)
  local rc=${pipestatus[1]}
  print "[T] pytest rc=$rc"
  next "report $OUT/{00,R,V,T}.txt to the Task 480 Leader"
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt; exit ${pipestatus[1]} ;;
  R|V|T) step_$STEP ;;
  *) print "usage: zsh $THIS <00|R|V|T>" ;;
esac
