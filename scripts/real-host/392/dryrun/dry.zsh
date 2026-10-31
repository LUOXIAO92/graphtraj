#!/bin/zsh
# Run the 392 steps' fixed logic against stub_host.py, in $TMPDIR, inside any sandbox. Never a real check.
#   zsh dry.zsh [step ...]        with AGENTS_392_DRY_BAD=1, the stubs answer so that criteria must fail
# Each step's summary goes to $TMPDIR/rh392-dry/realhost/<step>/summary.txt.
HERE=${0:A:h:h}
D=$TMPDIR/rh392-dry
mkdir -p $D/bin $D/home/.codex $D/sandbox $D/ag/claude-project
for name in claude codex pi dsh codex-host; do ln -sf $HERE/dryrun/stub_host.py $D/bin/$name; done
print -r -- 'model = "stub-codex-model"' > $D/home/.codex/config.toml
print -rl -- "sandbox_python=$(command -v python3.13)" "sandbox_path=/usr/bin:/bin" > $D/sandbox/pi-sandbox.env
touch $D/ag/claude-project/.trust-392-done
if [[ ! -x $D/ag/venv/bin/python ]]; then
  # Agents only: a directory holding just an agent_swarm link, as 383's script did.
  python3.13 -m venv --system-site-packages $D/ag/venv
  mkdir -p $D/agents-only
  ln -sf ${HERE:h:h:h}/src/agent_swarm $D/agents-only/agent_swarm
  print -r -- $D/agents-only > $D/ag/venv/lib/python3.13/site-packages/agents-only.pth
fi
print -r -- $(<$HERE/COMMIT) > $D/ag/venv/installed-commit
export HOME=$D/home AGENTS_392_DRY_ROOT=$D/ag AGENTS_392_DRY_SANDBOX=$D/sandbox AGENTS_392_DRY_REALHOST=$D/realhost
export AGENTS_392_DRY_BIN=$D/bin AGENTS_392_DRY_NO_SCRIPT=1 RH_DRY_CODEX_HOST=$D/bin/codex-host
export DEEPSEEK_API_KEY=${AGENTS_392_DRY_KEY:-dry-run-not-a-key-392}
# `dry.zsh runner [--from <step>]` runs run-unattended.zsh instead, with AGENTS_392_DRY_STEPS and
# AGENTS_392_DRY_LIMIT_SECONDS as the caller set them.
if [[ ${1:-} == runner ]]; then shift; exec zsh $HERE/run-unattended.zsh "$@" </dev/null; fi
steps=($@)
(( ${#steps} )) || steps=($HERE/[0-9][0-9]-*.zsh(N:t:r))
for step in $steps; do
  print -r -- "===== $step"
  zsh $HERE/$step.zsh </dev/null 2>&1 | tail -${AGENTS_392_DRY_TAIL:-4}
done
