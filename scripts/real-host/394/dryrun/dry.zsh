#!/bin/zsh
# Run the 394 steps' fixed logic against stub_host.py, in $TMPDIR, inside any sandbox. Never a real check.
#   zsh dry.zsh [step ...]        with AGENTS_394_DRY_BAD=1, the stubs answer so that criteria must fail
# The Worktree is read from a fresh clone of its head ($D/wt), so work in progress there does not stop
# commit_check; Python imports the Worktree's src/graftling as it is on disk. Each step's evidence goes
# to $TMPDIR/rh394-dry/realhost/<step>/.
HERE=${0:A:h:h}
SRC=${HERE:h:h:h}/src
D=$TMPDIR/rh394-dry
mkdir -p $D/bin $D/home/.codex $D/sandbox $D/ag/claude-project
for name in claude codex pi dsh pnpm codex-host; do ln -sf $HERE/dryrun/stub_host.py $D/bin/$name; done
print -r -- 'model = "stub-codex-model"' > $D/home/.codex/config.toml
print -rl -- "sandbox_python=$(command -v python3.13)" "sandbox_path=/usr/bin:/bin" > $D/sandbox/pi-sandbox.env
# A fresh clone of the branch head each time, and a COMMIT frozen from it unless the caller keeps one.
rm -rf $D/wt
git clone -q --no-hardlinks ${SRC:h} $D/wt
[[ -n ${AGENTS_394_DRY_KEEP_COMMIT:-} ]] || rm -f $D/ag/COMMIT
if [[ ! -x $D/ag/venv/bin/python ]]; then
  # graftling only: a directory holding just a graftling link, as 392's dry run did for agent_swarm.
  python3.13 -m venv --system-site-packages $D/ag/venv
  mkdir -p $D/graftling-only
  ln -sfn $SRC/graftling $D/graftling-only/graftling
  print -r -- $D/graftling-only > $D/ag/venv/lib/python3.13/site-packages/graftling-only.pth
fi
# The dry sandbox reaches no package index. A module of that name lets `import graftling.dsh` succeed;
# nothing in a dry run opens a connection with it.
if ! $D/ag/venv/bin/python -c 'import websockets.sync.client' 2>/dev/null; then
  mkdir -p $D/graftling-only/websockets/sync
  print -r -- '# dry-run stand-in, never a real websockets' > $D/graftling-only/websockets/__init__.py
  print -r -- '' > $D/graftling-only/websockets/sync/__init__.py
  print -rl -- 'def connect(*arguments, **options):' '    raise OSError("dry-run stand-in for websockets")' > $D/graftling-only/websockets/sync/client.py
fi
export HOME=$D/home AGENTS_394_DRY_ROOT=$D/ag AGENTS_394_DRY_SANDBOX=$D/sandbox AGENTS_394_DRY_REALHOST=$D/realhost
export AGENTS_394_DRY_SHORT=$D/short AGENTS_394_DRY_WT=$D/wt AGENTS_394_DRY_BIN=$D/bin AGENTS_394_DRY_NO_SCRIPT=1 RH_DRY_CODEX_HOST=$D/bin/codex-host
export DEEPSEEK_API_KEY=${AGENTS_394_DRY_KEY:-dry-run-not-a-key-394}
steps=($@)
(( ${#steps} )) || steps=($HERE/[0-9][0-9]-*.zsh(N:t:r))
for step in $steps; do
  print -r -- "===== $step"
  # Step 00 freezes COMMIT; the venv stands for step 01's and is marked as built from it.
  [[ $step == 00-preflight || ! -f $D/ag/COMMIT ]] || print -r -- $(<$D/ag/COMMIT) > $D/ag/venv/installed-commit
  zsh $HERE/$step.zsh </dev/null 2>&1 | tail -${AGENTS_394_DRY_TAIL:-6}
done
