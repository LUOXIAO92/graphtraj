#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 22: 421's public code, on GraphTraj's Runner in a scratch project.
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/22-launch-failed.zsh
#
# launch-failed is GraphTraj's code (src/graphtraj/execution/runner_models.py), so this one step needs
# a separate venv, $AG/venv-graphtraj, with GraphTraj beside agents, built from this commit. The
# agents-only venv is not touched. The Runner runs under sandbox-exec with TCP binding denied, the
# refusal 421 saw, so the real DSH member cannot start; no model answers and no Main is involved.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 22-launch-failed 6 none "the Runner's task error has code launch-failed and its message names EPERM"

prepare_checks
GT_VENV=$AG/venv-graphtraj
if [[ ! -f $GT_VENV/installed-commit || $(cat $GT_VENV/installed-commit 2>/dev/null) != $COMMIT ]]; then
  say "build $GT_VENV from commit $COMMIT (dependencies from PyPI)"
  if [[ -e $GT_VENV ]]; then mv $GT_VENV $GT_VENV.$STAMP; note "an earlier venv was moved to $GT_VENV.$STAMP"; fi
  $PY -m venv $GT_VENV
  WHEELS=$RUN/wheels
  mkdir -p $WHEELS
  git -C $WT archive $COMMIT | (mkdir -p $RUN/source && tar -x -C $RUN/source)
  $GT_VENV/bin/python -m pip install --quiet --disable-pip-version-check $RUN/source/src/agent_swarm $RUN/source > $OUT/install.txt 2>&1 \
    || fail "installing GraphTraj into $GT_VENV failed; see install.txt"
  print -r -- $COMMIT > $GT_VENV/installed-commit
fi
$GT_VENV/bin/python -c 'import agent_swarm, graphtraj; print("agent_swarm", agent_swarm.__version__, "graphtraj", graphtraj.__file__)' | tee $OUT/versions.txt
(cd $RUN && $GT_VENV/bin/python -E -s $HERE/checks.py launch_failed) || check FAIL "checks.py launch_failed stopped with exit $?"
step_end
