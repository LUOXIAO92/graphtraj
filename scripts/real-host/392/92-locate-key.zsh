#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 92-locate-key. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/92-locate-key.zsh
# Read-only: says where the DeepSeek value sits in the saved Pi sessions of steps 64 and 89, and counts
# other *.jsonl files holding it. It prints and saves no copy of the value or of those files, and changes none.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 92-locate-key 2 none 'locations.txt says where the value sits, masked, and summary.txt has the counts'
load_key
$PY -I $HERE/locate_key.py $AG/runs $OUT > $OUT/answer.txt 2>&1 || print -r -- "FAIL locate_key.py stopped with exit $?" >> $OUT/answer.txt
grep -E '^(PASS|FAIL|CANNOT) ' $OUT/answer.txt >> $OUT/summary.txt || print -r -- "FAIL locate_key.py gave no answer; see answer.txt" >> $OUT/summary.txt
step_end "none; tell Main step 92 has finished"
