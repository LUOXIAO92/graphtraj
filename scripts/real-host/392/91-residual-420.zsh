#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 91-residual-420. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/91-residual-420.zsh
# 420: one real DSH member round under the Runner, with the venv bin off the host PATH: what the host lacked at 417, EMFILE, the agent-runner fallback.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 91-residual-420 15 none 'read the PASS, FAIL and CANNOT lines: 420: one real DSH member round under the Runner, with the venv bin off the host PATH: what the host lacked at 417, EMFILE, the agent-runner fallback.'
prepare_checks
run_scratch r420
step_end
