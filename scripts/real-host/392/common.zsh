# Task 392 real-host steps: what every step shares. Sourced, never run.
#
# A step starts:
#   #!/bin/zsh
#   [ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
#   source /abs/path/scripts/real-host/392/common.zsh
#   step_begin <step> <expected minutes> <dialog text, or "none"> <what success looks like>
# and ends with `step_end <exact next command>`, which scans, saves and exits.
#
# Layout (fixed; AGENTS_392_DRY_* only exist for the dry run against stub hosts):
#   HARNESS, WT     the Harness root and this Worktree
#   COMMIT          the code under test, from scripts/real-host/392/COMMIT
#   AG              /Users/luoxiao/agents-392: scratch, outside the Harness, $TMPDIR and /tmp
#   VENV            $AG/venv: the agents-only venv. The install step (Engineer 2) builds it and
#                   writes the commit it built from to $VENV/installed-commit
#   RUN             $AG/runs/<step>-<time>: this run's scratch; WORK under it is free to use
#   OUT             $RUN/out: this run's evidence; only this directory is ever saved
#   SAVED           the Harness directory that receives $OUT, as realhost/<step>/
#
# Output is written to $OUT first and reaches the Harness only after the DeepSeek value has been
# looked for in it. A file holding that value is not copied, and the summary says so.
#
# Lines in summary.txt: PASS|FAIL|CANNOT <criterion>: <observable>. Use check/note below.

setopt err_exit pipe_fail no_unset

HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$HARNESS/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance
HERE=$WT/scripts/real-host/392
COMMIT=$(<$HERE/COMMIT)
# Used only to read the scan and for small fixed logic before the venv exists; nothing imports agents.
PY=/Users/luoxiao/miniconda3/bin/python3.13
AG=${AGENTS_392_DRY_ROOT:-/Users/luoxiao/agents-392}
VENV=$AG/venv
PI_SANDBOX=${AGENTS_392_DRY_SANDBOX:-$HOME/agents-pi-sandbox}
REALHOST=${AGENTS_392_DRY_REALHOST:-$HARNESS/.graphtraj/core/state/tasks/392-agents-standalone-combined-acceptance/realhost}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
# The test Runtimes' models. Children and hosts use the small ones; the Codex one is the user's own.
CLAUDE_MODEL=claude-sonnet-5-5
DEEPSEEK_MODEL=deepseek-flash
PI_PROVIDER=deepseek
PI_MODEL=deepseek-flash

say() { print -r -- ""; print -r -- "== $*"; }
info() { print -r -- "$*"; }

# One criterion line: `check PASS|FAIL|CANNOT "<criterion>: <observable>"`, shown and kept.
check() {
  local state=$1; shift
  print -r -- "$state $*"
  print -r -- "$state $*" >> $OUT/summary.txt
}

# Keep an observation in the terminal and the summary without judging it.
note() {
  print -r -- "note: $*"
  print -r -- "note: $*" >> $OUT/summary.txt
}

# `judge <0|nonzero status> <criterion>`: PASS on 0, FAIL otherwise.
judge() {
  if [[ $1 == 0 ]]; then check PASS "$2"; else check FAIL "$2"; fi
}

# Stop this step: the reason goes to the summary, the evidence so far is saved.
fail() {
  print -r -- "STOP: $*" >&2
  [[ -n ${OUT:-} && -d ${OUT:-/nonexistent} ]] && print -r -- "FAIL step stopped: $*" >> $OUT/summary.txt
  step_save
  exit 1
}

# A hung run must not hold the terminal for ever: the alarm survives exec. `bounded <seconds> cmd...`
bounded() {
  local seconds=$1; shift
  /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' $seconds "$@"
}

# Stop unless this Worktree's code is exactly COMMIT. Later commits may change only this directory.
commit_check() {
  local head_now
  head_now=$(git -C $WT rev-parse HEAD)
  info "HEAD=$head_now expected code=$COMMIT"
  [[ $head_now == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $head_now -- . ':!scripts/real-host/392' \
    || fail "the Worktree's code differs from commit $COMMIT"
  git -C $WT diff --quiet HEAD -- . ':!scripts/real-host/392' || fail "the Worktree has uncommitted code changes"
  git -C $WT diff --cached --quiet HEAD -- . ':!scripts/real-host/392' || fail "the Worktree has staged code changes"
}

# Stop unless the venv exists, was built from COMMIT, and holds agents without GraphTraj.
venv_check() {
  [[ -x $VENV/bin/python ]] || fail "$VENV is missing; run the install step first"
  [[ -f $VENV/installed-commit ]] || fail "$VENV/installed-commit is missing; run the install step first"
  [[ $(<$VENV/installed-commit) == $COMMIT ]] \
    || fail "$VENV was built from $(<$VENV/installed-commit), not $COMMIT; run the install step again"
  (cd $RUN && $VENV/bin/python -I -c 'import importlib.util as u, sys
import agent_swarm
print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__)
sys.exit(u.find_spec("graphtraj") is not None)') \
    || fail "graphtraj is importable in $VENV; these steps need an agents-only venv"
}

# Name each Runtime's executable. Sets CLAUDE, CODEX, PI_BIN, DSH; stops on a missing one.
find_hosts() {
  CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
  [[ -x $CLAUDE ]] || fail "claude is not installed"
  CODEX=$(command -v codex) || fail "codex is not on PATH"
  PI_BIN=$(command -v pi) || fail "pi is not on PATH"
  DSH=$(command -v dsh) || fail "dsh is not on PATH"
}

# The user's configured Codex model. Prints it, or nothing.
codex_model() {
  sed -n 's/^model *= *"\(.*\)"/\1/p' ${AGENTS_392_DRY_CODEX_CONFIG:-$HOME/.codex/config.toml} 2>/dev/null | head -1
}

# Load the DeepSeek key into this process's environment only. A failing line of ~/.zshrc must not
# stop the script, and only the key leaves that shell. The value is never printed or written.
load_key() {
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  info "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || fail "DEEPSEEK_API_KEY is unset; export it (or add it to ~/.zshrc) and run again"
}

# Read the installer's result into SANDBOX_PYTHON and SANDBOX_PATH. Only the installer writes the file.
read_sandbox() {
  local env_file=$PI_SANDBOX/pi-sandbox.env
  [[ -f $env_file ]] || fail "$env_file is missing; run: /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh"
  SANDBOX_PYTHON=$(sed -n 's/^sandbox_python=//p' $env_file)
  SANDBOX_PATH=$(sed -n 's/^sandbox_path=//p' $env_file)
  [[ -n $SANDBOX_PYTHON && -n $SANDBOX_PATH ]] || fail "$env_file lacks sandbox_python or sandbox_path"
}

# Begin a step: re-run under script(1) so the terminal stays with a native dialog and a transcript
# is kept (403's form), make the run's directories and print what to expect.
step_begin() {
  STEP=$1 STEP_MINUTES=$2 STEP_DIALOG=$3 STEP_SUCCESS=$4
  STAMP=$(date +%Y%m%dT%H%M%S)
  RUN=$AG/runs/$STEP-$STAMP
  OUT=$RUN/out
  WORK=$RUN/work
  [[ $STEP == *[!a-z0-9-]* ]] && { print -r -- "STOP: bad step name $STEP" >&2; exit 2; }
  mkdir -p $OUT $WORK
  SCAN_DONE=
  trap 'step_save' EXIT
  say "$STEP (expect about $STEP_MINUTES minutes)"
  info "shell: zsh $ZSH_VERSION, script: ${ZSH_ARGZERO:-$0}"
  info "scratch: $RUN"
  info "saved to: $REALHOST/$STEP"
  if [[ $STEP_DIALOG == none ]]; then
    info "native review dialog: none"
  else
    info "native review dialog: $STEP_DIALOG"
  fi
  info "success: $STEP_SUCCESS"
  print -r -- "step $STEP code $COMMIT started $STAMP" > $OUT/run.txt
  commit_check
}

# Look for the key's value in $OUT and copy the rest to the Harness. Runs once. The scan is a Python
# program reading the value from its environment, so the value is on no command line, and its answer
# is a file: inside an EXIT trap zsh can lose a command's status (403), and no file means no copy.
step_save() {
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

# End a step: save, show the summary and print the exact next command.
step_end() {
  step_save
  print -r -- ""
  print -r -- "== $STEP summary ($REALHOST/$STEP/summary.txt)"
  cat $OUT/summary.txt 2>/dev/null || print -r -- "(no criterion lines)"
  print -r -- ""
  print -r -- "Next command:"
  print -r -- "  $*"
  local failed=0
  grep -q '^FAIL ' $OUT/summary.txt 2>/dev/null && failed=1
  exit $failed
}
