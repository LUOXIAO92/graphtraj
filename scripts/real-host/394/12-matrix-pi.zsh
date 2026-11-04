#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 12-matrix-pi: 392's matrix row for the pi host, with the renamed package. Run in a plain macOS Terminal:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/12-matrix-pi.zsh
# Pi host x all four; the Pi x Pi cell is 382's Task-free Pi child. Notices arrive as custom messages graftling:agent-communication.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 12-matrix-pi 25 none 'matrix.txt shows PASS (9 of 9) for each of the 4 cells of the pi row, and no old name in the host output'
prepare_checks
need_claude_project
run_checks matrix pi
# Item 6 of the rename, seen from the Pi parent: a notice injected as graftling:agent-communication.
FOUND=$({ grep -l '"customType": *"graftling:agent-communication"' $OUT/*.pi-session.jsonl(N) /dev/null 2>/dev/null || true; } | wc -l | tr -d ' ')
(( FOUND > 0 )) && check PASS "Pi Sessions holding a graftling:agent-communication notice: $FOUND" \
  || note "no Pi Session of this row holds a graftling:agent-communication notice (answers may have come in results only)"
old_names
step_end
