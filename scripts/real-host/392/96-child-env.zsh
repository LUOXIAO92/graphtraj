#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 96-child-env. Run in a plain macOS Terminal, outside any sandbox, after step 43:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/96-child-env.zsh
# 433's items 1 to 6 and 439's item 1: which credential NAMES real shells and children see. Names only, ever:
# every command pipes `env` and `ps -E` through `cut -d= -f1` before printing. Only fake markers are set.
# The user's dotfiles and Runtime configuration are not changed: the dotfile markers come from a scratch
# ZDOTDIR, so HOME and every login stay as they are.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 96-child-env 10 none 'no child on any Runtime sees a credential name but its own key; the Codex host keeps FAKE439_TOKEN and its child does not; what each shell reloads from dotfiles is named'
prepare_checks

# Fake dotfiles: each exports one fake name. Nothing real is read from them.
FAKE_Z=$RUN/zdotdir
mkdir -p $FAKE_Z
for file in zshenv zprofile zlogin zshrc; do
  print -r -- "export FAKE_${file:u}_API_KEY=fake-433-$file-not-a-key" > $FAKE_Z/.$file
done
# The markers come from printf, so a copy of the command text is never read as its output.
NAMES_CMD="printf '%s-%s\\n' NAMES BEGIN; env | cut -d= -f1 | grep -E 'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|^FAKE' | sort | tr '\n' ' '; echo; echo FLAGS=\$-; printf '%s-%s\\n' NAMES END"

# `seen <file>`: the names between the markers of the LAST block in a host's answer, one line.
seen() {
  awk '/NAMES-BEGIN/{n="";f=1;next} /NAMES-END/{last=n;f=0} f&&!/^FLAGS=/{n=n" "$0} END{print last}' $1 \
    | tr ' ' '\n' | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' | sort -u | tr '\n' ' ' || true
}
# `judge_names <label> <file>`: FAIL for a real credential name; the fake markers are only noted.
judge_names() {
  local names=$(seen $2)
  if ! grep -q NAMES-END $2; then check CANNOT "$1: the model did not run the names command; see ${2:t}"; return 0; fi
  local real=$(print -r -- $names | tr ' ' '\n' | grep -v -x -e DEEPSEEK_API_KEY -e '' | grep -v '^FAKE' | tr '\n' ' ' || true)
  note "$1 sees: $names; $(grep -m1 -o 'FLAGS=[A-Za-z0-9]*' $2 || true)"
  [[ -z ${real// /} ]] && check PASS "$1: no real credential name but DEEPSEEK_API_KEY" || check FAIL "$1: real credential names: $real"
}

say "433 items 2 and 3: Codex with the fake dotfiles and a declared fake marker; the tool path, first and later command"
touch $RUN/codex-start
CODEX_HOME_DIR=${CODEX_HOME:-$HOME/.codex}
CODE=0
print -r -- "Using your shell tool, run this command, then run pwd, then run the same command again. Reply with the two outputs only. Do not print environment values. Command: $NAMES_CMD" \
  | (cd $RUN && bounded 300 env ZDOTDIR=$FAKE_Z FAKE433_DECLARED=FAKE433MARKER-declared-not-a-key \
      $CODEX exec --skip-git-repo-check --ephemeral -s read-only - > $OUT/codex-dotfiles.txt 2> $OUT/codex-dotfiles.stderr.txt) || CODE=$?
judge_names "433 item 3: Codex tool shell (exit $CODE)" $OUT/codex-dotfiles.txt
print -r -- "433 item 3: Codex blocks $(grep -c NAMES-END $OUT/codex-dotfiles.txt || true); the last one is judged above" >> $OUT/summary.txt
HELD=($(find $CODEX_HOME_DIR/sessions $CODEX_HOME_DIR/shell_snapshots -type f -newer $RUN/codex-start 2>/dev/null \
  | xargs grep -l FAKE433MARKER 2>/dev/null || true))
if (( ${#HELD} )); then
  check FAIL "433 item 2: the declared fake marker landed in ${#HELD} Codex files: ${HELD:t}"
else
  check PASS "433 item 2: no Codex rollout or shell snapshot written in this step holds FAKE433MARKER"
fi

say "433 item 5: Claude's Bash tool, with the fake dotfiles (one -p call, no dialog)"
CODE=0
# The prompt goes on stdin: --allowedTools takes every later word, so a prompt argument after it was lost.
print -r -- "Run exactly this one command with your Bash tool, once, and reply with only its output: $NAMES_CMD" \
  > $RUN/claude-dotfiles-prompt.txt
(cd $RUN && bounded 240 env ZDOTDIR=$FAKE_Z $CLAUDE -p --model $CLAUDE_MODEL --allowedTools Bash \
  < $RUN/claude-dotfiles-prompt.txt > $OUT/claude-dotfiles.txt 2> $OUT/claude-dotfiles.stderr.txt) || CODE=$?
judge_names "433 item 5: Claude Bash tool after dotfile reload (exit $CODE)" $OUT/claude-dotfiles.txt

say "433 items 1 and 6, 439 item 1: a host on each Runtime and its child of the same Runtime"
export FAKE439_TOKEN=fake-439-not-a-token
run_child_env() {
  setopt local_options no_err_exit
  (cd $RUN && $VENV/bin/python -E -s $HERE/child_env.py "$@")
  local code=$?
  (( code == 0 )) || check FAIL "child_env.py $* stopped with exit $code; see the terminal transcript"
}
run_child_env claude codex pi dsh
unset FAKE439_TOKEN

note "433 item 4: a real model call with a resolved key ran in each host and child above, and in step 00's answers lines; Pi's request used DEEPSEEK_API_KEY"
step_end
