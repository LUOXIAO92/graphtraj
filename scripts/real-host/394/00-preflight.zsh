#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 00: the preflight. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/00-preflight.zsh
#
# Freezes the code under test once (the branch head, written to /Users/luoxiao/agents-394/COMMIT), then:
# each host answers one line with its configured model and login, the shell is zsh, pnpm and dsh are
# present, and the Pi sandbox is complete. 392's step 00 without its key-name and bind probes.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 00-preflight 5 none 'every line says PASS: COMMIT frozen and holding src/graftling, shell zsh, four hosts answer, pnpm and dsh found, Pi sandbox verified'

say "the code under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
BRANCH=$(git -C $WT branch --show-current)
if [[ -n $COMMIT ]] && git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/real-host/394'; then
  note "COMMIT was frozen by an earlier run of this step: $COMMIT (the head $HEAD_NOW has the same code)"
elif [[ -n $COMMIT ]]; then
  fail "the head $HEAD_NOW has other code than the frozen $COMMIT. To test the head, run: mv $AG/COMMIT $AG/COMMIT.$STAMP && zsh $HERE/00-preflight.zsh"
else
  COMMIT=$HEAD_NOW
  print -r -- $COMMIT > $AG/COMMIT
  check PASS "COMMIT frozen from the head of $BRANCH: $COMMIT, written to $AG/COMMIT"
fi
print -r -- "step $STEP code $COMMIT started $STAMP" > $OUT/run.txt
commit_check
check PASS "the Worktree's code is $COMMIT, committed, nothing staged"
[[ $BRANCH == agent/394-agents-rename-after-naming ]] && check PASS "branch: $BRANCH" || check FAIL "branch: $BRANCH, not agent/394-agents-rename-after-naming"
VERSION=$(git -C $WT show ${COMMIT}:src/graftling/__init__.py 2>/dev/null | sed -n 's/^__version__ = "\(.*\)"$/\1/p' || true)
[[ $VERSION == $DIST_VERSION ]] && check PASS "$COMMIT holds src/graftling at version $VERSION" \
  || check FAIL "$COMMIT: src/graftling/__init__.py version is '${VERSION:-missing}', not $DIST_VERSION"
git -C $WT cat-file -e ${COMMIT}:src/agent_swarm/__init__.py 2>/dev/null \
  && check FAIL "$COMMIT still has src/agent_swarm" || check PASS "$COMMIT has no src/agent_swarm"
git -C $WT merge-base --is-ancestor $BASE $COMMIT && check PASS "the base $BASE is an ancestor of $COMMIT" \
  || check FAIL "the base $BASE is not an ancestor of $COMMIT"

say "the shell and the tools"
[[ -n ${ZSH_VERSION:-} && ${ZSH_ARGZERO:t} == 00-preflight.zsh ]] && check PASS "shell: zsh $ZSH_VERSION at $(command -v zsh) runs $ZSH_ARGZERO" \
  || check FAIL "shell: this script runs as ${ZSH_ARGZERO:-?} under ${ZSH_VERSION:+zsh }${ZSH_VERSION:-another shell}"
find_hosts
for tool in claude codex pi dsh; do
  case $tool in claude) BIN=$CLAUDE ;; codex) BIN=$CODEX ;; pi) BIN=$PI_BIN ;; dsh) BIN=$DSH ;; esac
  info "$tool: $BIN ($($BIN --version 2>&1 | tail -1))"
  print -r -- "$tool $BIN $($BIN --version 2>&1 | tail -1)" >> $OUT/versions.txt
done
check PASS "dsh: $DSH $($DSH --version 2>&1 | tail -1)"
if PNPM=$(command -v pnpm); then
  PNPM_VERSION=$(pnpm --version 2>&1 | tail -1) && check PASS "pnpm: $PNPM $PNPM_VERSION" || check FAIL "pnpm: $PNPM --version says: $PNPM_VERSION"
  print -r -- "pnpm $PNPM $PNPM_VERSION" >> $OUT/versions.txt
else
  check FAIL "pnpm: not on PATH ($PATH); step 20 needs it for dsh plugin add"
fi
NODE=$(command -v node) && check PASS "node: $NODE $(node --version)" || check FAIL "node: not on PATH; DSH and Pi need it"

say "each host answers one line with its configured model and login"
ASK='In one line: name the model you are running as, and confirm you can answer. Do not use any tool or print any key.'
PROBE_DIR=$RUN/probe
mkdir -p $PROBE_DIR $PROBE_DIR/pi-home $PROBE_DIR/dsh-home
print -r -- $ASK > $PROBE_DIR/ask.txt
print -n > $PROBE_DIR/empty.txt
print -rl -- '- id: llm-deepseek' '  config:' '    apiKeyEnv: DEEPSEEK_API_KEY' '    baseURL: https://api.deepseek.com/anthropic' > $PROBE_DIR/dsh.patch.yml
load_key
MODEL=$(codex_model)
[[ -n $MODEL ]] && check PASS "codex model from ~/.codex/config.toml: $MODEL" \
  || check FAIL "codex model: no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run this again"
LOGIN=$($CODEX login status 2>&1 | tail -1) && check PASS "codex login: $LOGIN" || check FAIL "codex login: $LOGIN"

# `answers <label> <stdin file> <command...>`: bounded; the answer is kept and judged by its exit.
answers() {
  setopt local_options no_err_exit
  local label=$1 input=$2 code=0; shift 2
  (cd $PROBE_DIR && bounded 180 "$@" < $input > $OUT/$label.answer.txt 2> $OUT/$label.stderr.txt) || code=$?
  if (( code == 0 )) && [[ -s $OUT/$label.answer.txt ]]; then
    check PASS "$label answers: $(tail -1 $OUT/$label.answer.txt | cut -c1-200)"
  else
    check FAIL "$label answers: exit $code (142 is the 180 s limit); $(tail -1 $OUT/$label.stderr.txt | cut -c1-300)"
  fi
}
answers claude $PROBE_DIR/ask.txt $CLAUDE -p --model $CLAUDE_MODEL
answers codex $PROBE_DIR/ask.txt $CODEX exec --skip-git-repo-check --ephemeral -s read-only -
answers pi $PROBE_DIR/empty.txt env PI_CODING_AGENT_DIR=$PROBE_DIR/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
  $PI_BIN --no-session --no-tools --model $PI_PROVIDER/$PI_MODEL -p $ASK
answers dsh $PROBE_DIR/empty.txt env DSH_HOME=$PROBE_DIR/dsh-home \
  $DSH --profile probe --from-default-profile headless --patch $PROBE_DIR/dsh.patch.yml $ASK

say "the Pi sandbox the Pi cells use (nothing is downloaded when it is already complete)"
if [[ -n ${AGENTS_394_DRY_BIN:-} ]]; then
  note 'dry run: install-pi-sandbox.sh not run; the dry layout has its own pi-sandbox.env'
elif /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh ${AGENTS_394_DRY_SANDBOX:+$AGENTS_394_DRY_SANDBOX} > $OUT/install-pi-sandbox.txt 2>&1 \
    && [[ -f $PI_SANDBOX/pi-sandbox.env ]]; then
  check PASS "install-pi-sandbox.sh: $(tail -1 $OUT/install-pi-sandbox.txt)"
else
  check FAIL "install-pi-sandbox.sh: NOT VERIFIED; last line: $(tail -1 $OUT/install-pi-sandbox.txt); see install-pi-sandbox.txt"
fi
step_end
