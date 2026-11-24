#!/bin/zsh
# Engineer rehearsal of steps.zsh through the same entry Main uses (zsh steps.zsh <step>), without the user's login.
# Every run sets VERIFY614_* variables, so each step prints REHEARSAL and is not acceptance evidence.
# usage: zsh rehearse.zsh <step>...   (console output: rehearsal/<step>.txt)
emulate -L zsh
setopt pipe_fail
SD=${0:A:h}
SCRATCH=${TMPDIR:-/tmp}/614
export VERIFY614_ROOT=$SCRATCH/root VERIFY614_T=$SCRATCH/T VERIFY614_OUT=$SD/rehearsal/out VERIFY614_USERHOME=$SCRATCH/userhome
export VERIFY614_DEPS="$SCRATCH/venv/lib/python3.13/site-packages /Users/luoxiao/miniconda3/lib/python3.13/site-packages"
export VERIFY614_NO_PROMPT=1 VERIFY614_NO_PS=1 VERIFY614_GWAIT=5VERIFY614_CLAUDE=/usr/bin/true   # stand-in: no Claude CLI in the sandbox
export VERIFY614_PYTEST_ARGS=${VERIFY614_PYTEST_ARGS:-"-k 'test_role_models_614 or test_agents_discovery_intents'"}
mkdir -p $SD/rehearsal $VERIFY614_USERHOME/.graphtraj
local step; for step in "$@"; do
  print -r -- "\$ zsh steps.zsh $step   (rehearsal $(date +%FT%T))" > $SD/rehearsal/$step.txt
  zsh $SD/steps.zsh $step 2>&1 | tee -a $SD/rehearsal/$step.txt
done
