#!/bin/zsh
# Dry run only: a step that stops with a nonzero exit, so the runner must go on and retry it next time.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 98-stops 1 none 'stops with a nonzero exit'
fail 'this dry step stops on purpose'
