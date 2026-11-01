#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 93-leftovers. Run in a plain macOS Terminal, outside any sandbox, BEFORE anything
# stops those processes:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/93-leftovers.zsh [pid ...]
# Read-only and sends no signal. It records the processes the run left, samples them twice 30 s apart, and copies
# what step 91's member left. The DeepSeek value is loaded only so that the save scan leaves out any file holding it.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 93-leftovers 2 none 'summary.txt states the last activity of the member of step 91, whether a native approval is pending there, the EMFILE count, and what each leftover process is doing'
GIVEN_PIDS=("$@")
(( ${#GIVEN_PIDS} )) || GIVEN_PIDS=(13673 13674 13677 11287)
load_key
env -u DEEPSEEK_API_KEY $PY -I $HERE/leftovers.py $AG $OUT $GIVEN_PIDS || check FAIL "leftovers.py stopped with exit $?; see the terminal transcript"
KILL_LINE=
[[ -f $OUT/kill-line.txt ]] && KILL_LINE=$(<$OUT/kill-line.txt)
if [[ -n $KILL_LINE ]]; then
  step_end "$KILL_LINE"
fi
step_end
