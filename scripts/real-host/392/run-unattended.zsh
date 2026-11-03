#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392: run the unattended steps one at a time, in the fixed order, in a plain macOS Terminal
# outside any sandbox, after the attended steps:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/run-unattended.zsh
#
# Running the same command again continues: a step already finished at this commit is skipped.
# `--from <step>` starts at that step and runs it even if it is finished.
# `--despite-dsh`, alone or before `--from <step>`, starts even if step 00's only FAIL lines start `FAIL dsh answers`.
# `--rerun`, alone or after `--despite-dsh`, runs the fixed rerun list below instead, even where a result
# is finished; running it again continues, and `--rerun --restart` starts over. Its summary is realhost/run-rerun/.
# native review dialog: none from this command; each step prints its own line, and all of them say none.
# Nothing to type. Keep the Mac on power with its lid open: caffeinate stops idle sleep, not a closed lid.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh

commit_check

# Stop unless this step ended with a result for this code and no FAIL line.
need_clean() {
  local saved=$REALHOST/$1
  [[ -f $saved/summary.txt ]] || fail "realhost/$1 has no result; run first: zsh $HERE/$1.zsh"
  grep -q "code $COMMIT " $saved/run.txt 2>/dev/null || fail "realhost/$1 is for other code; run again: zsh $HERE/$1.zsh"
  local failing=$(grep '^FAIL ' $saved/summary.txt || true)
  if [[ $1 == 00-preflight && -n $DESPITE_DSH ]]; then
    failing=${(F)${${(f)failing}:#FAIL dsh answers*}}
  fi
  if [[ -n $failing ]]; then
    fail "realhost/$1/summary.txt has a FAIL line; tell Main, or fix it and run again: zsh $HERE/$1.zsh"
  fi
}
DESPITE_DSH=
if [[ ${1:-} == --despite-dsh ]]; then
  DESPITE_DSH=1
  shift
  print -r -- "--despite-dsh: a FAIL dsh answers line in step 00 is ignored; DSH-host steps are expected to FAIL."
fi
need_claude_project
load_key

if [[ ${1:-} == --rerun ]]; then
  shift
  # Main's list for the rerun after 441 and the COMMIT move. 00 and 01 run inside it, and a FAIL in either stops
  # the run (00's key-name probe included).
  UNATTENDED=(00-preflight 01-install 88-graphtraj-venv 13-matrix-dsh 22-launch-failed 42-hold-dsh 45-pi-parent 50-stuck-dsh
              65-walk-dsh 82-residual-387-hosts 91-residual-420 89-residual-416 70-suite 71-flaky 72-metadata)
  export AGENTS_392_RERUN=1
  if [[ ${1:-} == --restart ]]; then
    shift
    export AGENTS_392_RESTART=1
  fi
  (( $# == 0 )) || fail "--rerun takes only --restart, got: $*"
fi
# The plain run needs 00 and 01 done and clean first; the rerun runs them itself and stops on their FAIL.
if [[ -z ${AGENTS_392_RERUN:-} ]]; then
  need_clean 00-preflight
  need_clean 01-install
fi
export AGENTS_392_DESPITE_DSH=$DESPITE_DSH
if [[ -n ${AGENTS_392_DRY_STEPS:-} ]]; then UNATTENDED=(${=AGENTS_392_DRY_STEPS}); fi
if [[ ${1:-} == --from ]]; then
  (( ${UNATTENDED[(Ie)${2:-none}]} )) || fail "--from names no unattended step: ${2:-nothing}"
  export AGENTS_392_FROM=$2
fi

export AGENTS_392_UNDER_RUNNER=1 AGENTS_392_AG=$AG AGENTS_392_REALHOST=$REALHOST AGENTS_392_COMMIT=$COMMIT
exec /usr/bin/caffeinate -i $PY -I $HERE/run_unattended.py $HERE $UNATTENDED
