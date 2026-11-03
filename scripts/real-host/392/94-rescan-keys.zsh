#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 94-rescan-keys. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/94-rescan-keys.zsh
# Read-only. Rescans this Task's realhost/ and ~/agents-392/runs for the values of every key ~/.zshrc gives,
# plainly or interactively, and the DeepSeek key. It prints the variable name and the file, never a value.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 94-rescan-keys 5 none 'no saved file in realhost/ or ~/agents-392/runs holds a key value; any that does is named with its variable'
load_key
$PY -I $HERE/rescan_keys.py $RUN $REALHOST $AG/runs > $OUT/rescan.txt 2>&1 || check FAIL "rescan_keys.py stopped with exit $?; see rescan.txt"
while IFS= read -r line; do
  case $line in
    'FAIL '*) check FAIL "${line#FAIL }" ;;
    'CANNOT '*) check CANNOT "${line#CANNOT }" ;;
    'PASS '*) check PASS "${line#PASS }" ;;
    *) note "$line" ;;
  esac
done < $OUT/rescan.txt
step_end
