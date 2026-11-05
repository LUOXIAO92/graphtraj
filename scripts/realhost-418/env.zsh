# Shared variables of the 418 real-host steps; each step sources this.
# Everything derives from this checkout and its HEAD; nothing touches ~/.claude,
# ~/.codex, dotfiles or a production venv.
emulate -L zsh
set -u
STEPS=${${(%):-%x}:A:h}
REPO=$(git -C "$STEPS" rev-parse --show-toplevel)
COMMIT=$(git -C "$REPO" rev-parse HEAD)
SHORT=${COMMIT[1,10]}
OUT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/418-agents-claude-code-marketplace-package/teams/1/rounds/1/realhost
SCRATCH=/private/tmp/graftling-418-$SHORT
CHECKOUT=$SCRATCH/checkout
VENV=$SCRATCH/venv
PROJECT=$SCRATCH/project
BOTH=$SCRATCH/both
export CLAUDE_CONFIG_DIR=$SCRATCH/claude-config
CLAUDE=$(command -v claude || true)
TOOL=mcp__plugin_graftling_agents__agents
mkdir -p "$OUT" "$SCRATCH" "$CLAUDE_CONFIG_DIR" "$PROJECT" "$BOTH"
if [[ -n $(git -C "$REPO" status --porcelain --untracked-files=no) ]]; then
  print -u2 "418: $REPO has uncommitted changes; the steps run only on a clean commit."; exit 2
fi
if [[ -f $SCRATCH/commit && $(<$SCRATCH/commit) != $COMMIT ]]; then
  print -u2 "418: $SCRATCH was prepared for $(<$SCRATCH/commit), not $COMMIT. Run step 00 again."; exit 2
fi
if [[ -z $CLAUDE ]]; then print -u2 '418: no claude on PATH.'; exit 2; fi
print "418 commit $COMMIT · claude $CLAUDE · CLAUDE_CONFIG_DIR $CLAUDE_CONFIG_DIR · output $OUT"
