#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 97-locate-89. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/97-locate-89.zsh
# Read-only: says where the DeepSeek value sits in the four session files step 94 flagged in rerun 89, masked:
# inside a model-produced tool result, or in a record agents wrote. It prints and saves no copy of the value.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 97-locate-89 2 none 'summary.txt says, per flagged file, how many masked locations are in a model-produced tool result and how many in a record agents wrote'
load_key
$PY -I $HERE/locate97.py $AG/runs $OUT > $OUT/answer.txt 2>&1 || print -r -- "FAIL locate97.py stopped with exit $?" >> $OUT/answer.txt
grep -E '^(PASS|FAIL|CANNOT) ' $OUT/answer.txt >> $OUT/summary.txt || print -r -- "FAIL locate97.py gave no answer; see answer.txt" >> $OUT/summary.txt
step_end "none; tell Main step 97 has finished"
