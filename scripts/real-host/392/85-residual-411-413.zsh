#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 85-residual-411-413. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/85-residual-411-413.zsh
# 411, 413: DSH child with DEEPSEEK_BASE_URL set and kept; where the key goes; search; session/modelCatalog; dsh web; !command on listing.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 85-residual-411-413 15 none 'read the PASS, FAIL and CANNOT lines: 411, 413: DSH child with DEEPSEEK_BASE_URL set and kept; where the key goes; search; session/modelCatalog; dsh web; !command on listing.'
prepare_checks

run_residual r411_413
step_end
