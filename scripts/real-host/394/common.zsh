# Task 394 real-host steps: what every step shares. Sourced, never run. Taken from 392's common.zsh
# (accepted 20261104T210805) with the renamed package graftling and a COMMIT frozen by step 00.
#
# A step, in a file named <step>.zsh in this directory, starts:
#   #!/bin/zsh
#   [ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
#   source /abs/path/scripts/real-host/394/common.zsh
#   step_begin <step> <expected minutes> <dialog text, or "none"> <what success looks like>
# and ends with `step_end`, which scans, saves, prints the summary and the next step's command.
#
# Layout (fixed; AGENTS_394_DRY_* only exist for the dry run against stub hosts):
#   HARNESS, WT     the Harness root and this Worktree
#   AG              /Users/luoxiao/agents-394: the isolated project, outside the Harness, $TMPDIR and /tmp
#   COMMIT          the code under test: step 00 freezes the branch head into $AG/COMMIT once; every
#                   later step reads that file and stops unless the Worktree's code is still that commit
#   VENV            $AG/venv: the graftling-only venv step 01 builds, with $VENV/installed-commit
#   RUN             $AG/runs/<step>-<time>: this run's scratch; WORK under it is free to use
#   OUT             $RUN/out: this run's evidence; only this directory is ever saved
#   REALHOST        the Harness directory that receives $OUT, as real-host/<step>/
#
# Output is written to $OUT first and reaches the Harness only after the DeepSeek value, and the
# values of the other credentials ~/.zshrc sets, have been looked for in it (save_step.py).
#
# Lines in summary.txt: PASS|FAIL|CANNOT <criterion>: <observable>. Use check/note below.

setopt err_exit pipe_fail no_unset

# Only the DeepSeek key may reach a host or a model. The rest go first, and every child inherits their
# absence. Names only are printed.
() {
  local name removed=()
  for name in ${(k)parameters[(R)*export*]}; do
    if [[ ${name:l} == *(key|token|secret|password|credential)* && $name != DEEPSEEK_API_KEY ]]; then
      unset $name || true
      removed+=($name)
      [[ $name != GIT_CONFIG_KEY_* ]] || unset GIT_CONFIG_COUNT
    fi
  done
  if (( ${#removed} )); then
    print -r -- "removed from this run's environment (names only): $removed"
    export AGENTS_394_REMOVED_NAMES="$removed"
  fi
}

HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
HERE=$HARNESS/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394
# The dry run reads a clone of the branch head, so that work in progress in the Worktree does not stop it.
WT=${AGENTS_394_DRY_WT:-$HARNESS/.graphtraj/core/worktrees/394-agents-rename-after-naming}
# The base the suite's failures are compared with: dev when 394 began (392 accepted, 424 integrated).
BASE=$(git -C $WT rev-parse --verify 'cb29c3a4^{commit}')
PY=/Users/luoxiao/miniconda3/bin/python3.13
# Keys ~/.zshrc gives only to an interactive shell, or under names the pattern misses, are dropped too.
() {
  local name extra=($($PY -I $HERE/shell_keys.py names))
  for name in $extra; do unset $name || true; done
  if (( ${#extra} )); then
    print -r -- "removed from this run's environment (names only): $extra"
    export AGENTS_394_REMOVED_NAMES="${AGENTS_394_REMOVED_NAMES:-} $extra"
  fi
}
AG=${AGENTS_394_DRY_ROOT:-/Users/luoxiao/agents-394}
mkdir -p $AG/zdotdir
# Every zsh a host or child starts reads these empty files instead of the user's (392's isolation).
for _rc in .zshenv .zprofile .zshrc .zlogin; do
  [[ -f $AG/zdotdir/$_rc ]] || print -r -- '# Empty on purpose: task 394 keeps the user startup files and their keys out of the run.' > $AG/zdotdir/$_rc
done
unset _rc
export ZDOTDIR=$AG/zdotdir
VENV=$AG/venv
GT=$AG/venv-graphtraj
PI_SANDBOX=${AGENTS_394_DRY_SANDBOX:-$HOME/agents-pi-sandbox}
REALHOST=${AGENTS_394_DRY_REALHOST:-$HARNESS/.graphtraj/core/state/tasks/394-agents-rename-after-naming/real-host}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
if [[ -n ${AGENTS_394_DRY_BIN:-} ]]; then path=($AGENTS_394_DRY_BIN $path); fi
# 392's test models. Children and hosts use the small ones; the Codex one is the user's own.
CLAUDE_MODEL=claude-sonnet-5-5
DEEPSEEK_MODEL=deepseek-flash
PI_PROVIDER=deepseek
PI_MODEL=deepseek-flash
# The renamed package as Task 394 fixes it.
DIST=graftling
DIST_VERSION=0.5.0
# The run's COMMIT; step 00 sets it, every other step reads the frozen file.
COMMIT=
if [[ -f $AG/COMMIT ]]; then COMMIT=$(<$AG/COMMIT); fi

say() { print -r -- ""; print -r -- "== $*"; }
info() { print -r -- "$*"; }

check() {
  local state=$1; shift
  print -r -- "$state $*"
  print -r -- "$state $*" >> $OUT/summary.txt
}

note() {
  print -r -- "note: $*"
  print -r -- "note: $*" >> $OUT/summary.txt
}

judge() {
  if [[ $1 == 0 ]]; then check PASS "$2"; else check FAIL "$2"; fi
}

# Show what to type in its own window, where Claude Code's screen cannot cover it; wait for Enter.
what_to_type() {
  local file=$OUT/what-to-type.txt answer
  print -rl -- "$@" "" "This file stays open while you work. Return to the Terminal to type: Claude Code runs there." > $file
  print -r -- ""
  cat $file
  [[ -z ${AGENTS_394_DRY_BIN:-} ]] || return 0
  /usr/bin/open -e $file || note "what-to-type: the window did not open; read the lines above, or $file"
  print -n -- "Press Enter to start Claude Code "
  read -r answer || true
}

fail() {
  print -r -- "STOP: $*" >&2
  [[ -n ${OUT:-} && -d ${OUT:-/nonexistent} ]] || exit 1
  print -r -- "FAIL step stopped: $*" >> $OUT/summary.txt
  step_save
  step_close "Run this step again once the line above is dealt with: zsh $HERE/$STEP.zsh"
}

bounded() {
  local seconds=$1; shift
  /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' $seconds "$@"
}

# Stop unless COMMIT is frozen and this Worktree's code is exactly COMMIT. Later commits may change only
# this directory.
commit_check() {
  [[ -n $COMMIT ]] || fail "no frozen COMMIT in $AG/COMMIT; run: zsh $HERE/00-preflight.zsh"
  local head_now
  head_now=$(git -C $WT rev-parse HEAD)
  info "HEAD=$head_now expected code=$COMMIT"
  [[ $head_now == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $head_now -- . ':!scripts/real-host/394' \
    || fail "the Worktree's code differs from the frozen commit $COMMIT; to test the new head, run: mv $AG/COMMIT $AG/COMMIT.$STAMP && zsh $HERE/00-preflight.zsh"
  git -C $WT diff --quiet HEAD -- . ':!scripts/real-host/394' || fail "the Worktree has uncommitted code changes; the test needs committed code"
  git -C $WT diff --cached --quiet HEAD -- . ':!scripts/real-host/394' || fail "the Worktree has staged code changes; the test needs committed code"
}

# Stop unless the venv exists, was built from COMMIT, and holds graftling without GraphTraj.
venv_check() {
  [[ -x $VENV/bin/python ]] || fail "$VENV is missing; run: zsh $HERE/01-install.zsh"
  [[ -f $VENV/installed-commit ]] || fail "$VENV/installed-commit is missing; run: zsh $HERE/01-install.zsh"
  [[ $(<$VENV/installed-commit) == $COMMIT ]] \
    || fail "$VENV was built from $(<$VENV/installed-commit), not $COMMIT; run: zsh $HERE/01-install.zsh"
  (cd $RUN && $VENV/bin/python -I -c 'import importlib.util as u, sys
import graftling
print("graftling", graftling.__version__, graftling.__file__)
sys.exit(u.find_spec("graphtraj") is not None or u.find_spec("agent_swarm") is not None)') \
    || fail "graphtraj or agent_swarm is importable in $VENV; these steps need a graftling-only venv"
}

find_hosts() {
  CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
  [[ -x $CLAUDE ]] || fail "claude is not installed"
  CODEX=$(command -v codex) || fail "codex is not on PATH"
  PI_BIN=$(command -v pi) || fail "pi is not on PATH"
  DSH=$(command -v dsh) || fail "dsh is not on PATH"
}

codex_model() {
  sed -n 's/^model *= *"\(.*\)"/\1/p' ${AGENTS_394_DRY_CODEX_CONFIG:-$HOME/.codex/config.toml} 2>/dev/null | head -1
}

# Load the DeepSeek key into this process's environment only. The value is never printed or written.
load_key() {
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  info "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || fail "DEEPSEEK_API_KEY is unset; export it (or add it to ~/.zshrc) and run again"
}

read_sandbox() {
  local env_file=$PI_SANDBOX/pi-sandbox.env
  [[ -f $env_file ]] || fail "$env_file is missing; run: /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh"
  SANDBOX_PYTHON=$(sed -n 's/^sandbox_python=//p' $env_file)
  SANDBOX_PATH=$(sed -n 's/^sandbox_path=//p' $env_file)
  [[ -n $SANDBOX_PYTHON && -n $SANDBOX_PATH ]] || fail "$env_file lacks sandbox_python or sandbox_path"
}

# Begin a step. It runs again under script(1), so the terminal stays with a native dialog and a
# transcript is kept, then makes the run's directories and prints what to expect.
SCRIPT_ARGS=("$@")
step_begin() {
  STEP=$1 STEP_MINUTES=$2 STEP_DIALOG=$3 STEP_SUCCESS=$4
  [[ $STEP == *[!a-z0-9-]* ]] && { print -r -- "STOP: bad step name $STEP" >&2; exit 2; }
  STAMP=${AGENTS_394_STAMP:-$(date +%Y%m%dT%H%M%S)}
  RUN=$AG/runs/$STEP-$STAMP
  OUT=$RUN/out
  WORK=$RUN/work
  mkdir -p $OUT $WORK
  if [[ -z ${AGENTS_394_STAMP:-} && -z ${AGENTS_394_DRY_NO_SCRIPT:-} ]]; then
    export AGENTS_394_STAMP=$STAMP
    exec /usr/bin/script -q $OUT/terminal.log /bin/zsh $ZSH_ARGZERO "${SCRIPT_ARGS[@]}"
  fi
  unset AGENTS_394_STAMP
  say "$STEP (expect about $STEP_MINUTES minutes)"
  info "shell: zsh $ZSH_VERSION, script: $ZSH_ARGZERO"
  info "scratch: $RUN"
  info "saved to: $REALHOST/$STEP"
  if [[ $STEP_DIALOG == none ]]; then
    info "native dialog: none"
  else
    info "native dialog: $STEP_DIALOG"
  fi
  info "success: $STEP_SUCCESS"
  if [[ -n ${AGENTS_394_REMOVED_NAMES:-} ]]; then
    note "removed from this run's environment (names only): $AGENTS_394_REMOVED_NAMES"
  fi
  # Step 00 freezes COMMIT itself before it calls commit_check.
  if [[ $STEP != 00-preflight ]]; then
    print -r -- "step $STEP code $COMMIT started $STAMP" > $OUT/run.txt
    commit_check
  fi
}

# Prepare the variables rh394.py reads. Stops when a host or the Codex model is missing.
prepare_checks() {
  venv_check
  find_hosts
  load_key
  read_sandbox
  local model=$(codex_model)
  [[ -n $model ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
  export RH_RUN=$RUN RH_OUT=$OUT RH_AG=$AG RH_PYTHON=$VENV/bin/python RH_CLAUDE=$CLAUDE RH_CODEX=$CODEX RH_PI=$PI_BIN \
    RH_DSH=$DSH RH_CLAUDE_MODEL=$CLAUDE_MODEL RH_CODEX_MODEL=$model RH_DEEPSEEK_MODEL=$DEEPSEEK_MODEL \
    RH_PI_PROVIDER=$PI_PROVIDER RH_SANDBOX_PYTHON=$SANDBOX_PYTHON RH_SANDBOX_PATH=$SANDBOX_PATH
  info "models: Claude $CLAUDE_MODEL, Codex $model (from ~/.codex/config.toml), Pi and DSH $DEEPSEEK_MODEL"
}

need_claude_project() {
  [[ -f $AG/claude-project/.trust-394-done ]] || fail "the Claude project is not trusted yet; run: zsh $HERE/02-claude-trust.zsh"
}

run_checks() {
  setopt local_options no_err_exit
  (cd $RUN && $VENV/bin/python -E -s $HERE/checks.py "$@")
  local code=$?
  (( code == 0 )) || check FAIL "checks.py $* stopped with exit $code; see the terminal transcript"
}

# Look for key values in $OUT and copy the rest to the Harness. Runs once (392's step_save).
step_save() {
  (( ZSH_SUBSHELL == 0 )) || return 0
  [[ -z ${SCAN_DONE:-} && -n ${OUT:-} && -d ${OUT:-/nonexistent} ]] || return 0
  SCAN_DONE=1
  setopt local_options no_err_exit
  local saved=$REALHOST/$STEP
  $PY -I $HERE/save_step.py $OUT $saved $RUN/saved.txt
  if [[ -f $RUN/saved.txt ]]; then
    cat $RUN/saved.txt
  else
    print -r -- "NOT SAVED: the scan did not finish. Evidence stays in $OUT."
  fi
}

SCAN_DONE=
trap 'step_save' EXIT

# The fixed order; each step prints the next one's command.
ORDER=(00-preflight 01-install 02-claude-trust 10-matrix-claude 11-matrix-codex 12-matrix-pi 13-matrix-dsh
       20-dsh-plugin 30-suite)

# End a step: mark it finished, save, show the summary, a one-line PASS/FAIL and the next command.
step_end() {
  print -r -- "finished $(date +%Y%m%dT%H%M%S)" > $OUT/finished.txt
  step_save
  step_close
}

# The step's last lines: its criteria, the next command (or the given line), and `STEP <name> PASS|FAIL`.
step_close() {
  local index=${ORDER[(ie)$STEP]} next verdict=PASS counts
  next=${ORDER[index+1]:-}
  grep -q -E '^(FAIL|CANNOT) ' $OUT/summary.txt 2>/dev/null && verdict=FAIL
  counts="$(grep -c '^PASS ' $OUT/summary.txt 2>/dev/null || true) PASS, $(grep -c '^FAIL ' $OUT/summary.txt 2>/dev/null || true) FAIL, $(grep -c '^CANNOT ' $OUT/summary.txt 2>/dev/null || true) CANNOT"
  print -r -- ""
  print -r -- "== $STEP criteria ($REALHOST/$STEP/summary.txt)"
  grep -v '^note: ' $OUT/summary.txt 2>/dev/null || print -r -- "(no criterion lines)"
  print -r -- ""
  print -r -- "If a line above says FAIL or CANNOT, go on anyway: Main reads the saved output."
  [[ -z ${1:-} ]] || print -r -- "$1"
  if [[ -n $next ]]; then
    print -r -- "Next command:"
    print -r -- "  zsh $HERE/$next.zsh"
  else
    print -r -- "Last step: nothing more to run."
  fi
  print -r -- "STEP $STEP $verdict ($counts) code $COMMIT"
  [[ $verdict == PASS ]] && exit 0 || exit 1
}

# PASS when the venv was built from COMMIT and holds graftling at the version that commit declares.
installed_versions() {
  local venv=$1 expected got
  expected=$(git -C $WT show ${COMMIT}:src/graftling/__init__.py | sed -n 's/^__version__ = "\(.*\)"$/\1/p')
  got=$($venv/bin/python -I -c 'import importlib.metadata as m
names = ["graftling", "agent-swarm", "graphtraj"]
print(" ".join(f"{n}={m.version(n)}" for n in names if any(d.metadata["Name"] == n for d in m.distributions())))' 2>&1 || true)
  if [[ -f $venv/installed-commit && $(<$venv/installed-commit) == $COMMIT && " $got " == *" graftling=$expected "* \
        && $expected == $DIST_VERSION && " $got " != *" agent-swarm="* ]]; then
    check PASS "installed in $venv from $COMMIT: $got"
  else
    check FAIL "$venv: expected graftling=$DIST_VERSION (the commit declares $expected) and no agent-swarm, from $COMMIT; found: $got (built from $(cat $venv/installed-commit 2>/dev/null || print nothing))"
  fi
}

# 394's acceptance in this step's host output: none of the old names the renamed code used to emit.
# GRAPHTRAJ_* is left out: the user's own GraphTraj install may print it through their Claude or Codex
# hooks, which these steps do not control. old-names.txt keeps every matching line.
OLD_NAMES='GraphTraj notice|graphtraj:agent-communication|agent_swarm|agent-swarm|AGENT_SWARM_'
old_names() {
  setopt local_options no_err_exit
  grep -rIn -E $OLD_NAMES $OUT --exclude=summary.txt --exclude='*.prompt.txt' --exclude=terminal.log \
    --exclude=old-names.txt > $OUT/old-names.txt 2>/dev/null
  local hits=$(cut -d: -f1 $OUT/old-names.txt | sort -u | sed "s|^$OUT/||" | tr '\n' ' ')
  [[ -z ${hits// /} ]] && check PASS "no old name ($OLD_NAMES) in this step's host output" \
    || check FAIL "an old name in: $hits; the lines are in old-names.txt"
}
