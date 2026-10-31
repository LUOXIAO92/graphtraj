#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 60-readme-sandbox. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/60-readme-sandbox.zsh
# README's Pi sandbox commands, as written, in a directory of their own; then a real Pi child uses that install.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# Downloads agent-sandbox from GitHub and srt from npm, into $AG/doc-pi-sandbox only (the user's 20261031 approval, 387's pins).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 60-readme-sandbox 8 none "README's pip and npm lines succeed, and a real Pi child runs with sandbox_python and sandbox_path written as README says"
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi
prepare_checks
PI_DOC=$AG/doc-pi-sandbox
[[ -e $PI_DOC ]] && mv $PI_DOC $PI_DOC.$STAMP
say "README's commands"
CODE=0
# README's variable is PI_SANDBOX; common.zsh uses that name for the installer's location.
{
  PI_SANDBOX_DOC=$PI_DOC
  python3 -m venv "$PI_SANDBOX_DOC/venv" \
  && "$PI_SANDBOX_DOC/venv/bin/python" -m pip install \
    "git+https://github.com/anonx3247/agent-sandbox.git@705d8801356e758819dfbbe4fba7022fe96475f8" \
  && npm --prefix "$PI_SANDBOX_DOC/srt" install --ignore-scripts --save-exact \
    @anthropic-ai/sandbox-runtime@0.0.49
} > $OUT/readme-sandbox.txt 2>&1 || CODE=$?
tail -5 $OUT/readme-sandbox.txt
judge $CODE "README's Pi sandbox commands exit $CODE"
NODE_DIR=$(dirname $(command -v node))
RG=$(command -v rg || print -r -- $PI_SANDBOX/bin/rg)
if [[ -x $RG ]]; then
  export RH_SANDBOX_PYTHON=$PI_DOC/venv/bin/python
  export RH_SANDBOX_PATH=$PI_DOC/srt/node_modules/.bin:$NODE_DIR:$(dirname $RG):/usr/bin:/bin:/usr/sbin:/sbin
  note "sandbox_path as README says: $RH_SANDBOX_PATH"
  note "README installs no rg; this run took it from $RG"
  run_residual readme_sandbox $PI_DOC
else
  check CANNOT "README's sandbox with a real Pi child: no rg on PATH or at $PI_SANDBOX/bin/rg"
fi
step_end
