#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 88-graphtraj-venv. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/88-graphtraj-venv.zsh
# A dedicated venv holding wheels of GraphTraj and agents from this commit, for steps 89 to 91. Not .venv-runtime, Conda or the system.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 88-graphtraj-venv 5 none 'graphtraj, agent-runner and graphtraj-session exist beside the venv Python, built from this commit'
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi
GT=$AG/venv-graphtraj
if [[ -f $GT/installed-commit && $(<$GT/installed-commit) == $COMMIT ]]; then
  note "already built from $COMMIT"
else
  [[ -e $GT ]] && mv $GT $GT.$STAMP
  git clone -q --no-hardlinks $WT $RUN/checkout
  git -C $RUN/checkout checkout -q --detach $COMMIT
  $PY -m venv $GT
  (cd $RUN/checkout && WHEELS=$RUN/wheels && $GT/bin/python -m pip wheel -q --no-deps -w $WHEELS ./src/agent_swarm . && $GT/bin/python -m pip install -q $WHEELS/*.whl) 2>&1 | tee $OUT/install.txt | tail -3
  print -r -- $COMMIT > $GT/installed-commit
fi
$GT/bin/python -m pip list --disable-pip-version-check 2>/dev/null > $OUT/pip-list.txt
for tool in graphtraj agent-runner graphtraj-session; do
  [[ -x $GT/bin/$tool ]] && check PASS "$tool beside the venv Python" || check FAIL "$tool missing from $GT/bin"
done
step_end
