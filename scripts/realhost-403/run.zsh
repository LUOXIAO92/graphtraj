#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 403 real-host check: the one entry to run, in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay/scripts/realhost-403/run.zsh
#
# Preflight first (a short one-line answer from each host, with its configured model and login;
# the commit under test against HEAD), then claude.zsh, codex.zsh and pi.zsh in this directory.
# Each step states its own native review dialog and the choice to make. A failed step does not
# stop the others. Everything is kept under one new directory, printed at the end with one
# PASS/FAIL line per criterion. No credential is read beyond DEEPSEEK_API_KEY for the Pi step,
# which stays in that step's own process and is reported only as set or unset.
setopt err_exit pipe_fail no_unset

HERE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay/scripts/realhost-403
WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=REPLACE_WITH_CODE_COMMIT
path=(/opt/homebrew/bin $HOME/.local/bin $path)
# Outside $TMPDIR and /tmp, so a child's sandbox treats it as outside (385).
export AGENTS_403_RUN=/Users/luoxiao/agents-403-realhost/run-$(date +%Y%m%dT%H%M%S)
STEPS=(claude codex pi)

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "preflight: shell and commit (native review dialog: none)"
print -r -- "shell: zsh $ZSH_VERSION, started as $0"
[[ $COMMIT == REPLACE_WITH_CODE_COMMIT ]] && fail "set COMMIT in this script to the code commit under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-403' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-403' || fail "the Worktree has uncommitted code changes"
for step in $STEPS; do
  [[ -f $HERE/$step.zsh ]] || fail "$HERE/$step.zsh is missing"
done
mkdir -p $AGENTS_403_RUN/logs
print -r -- "this run keeps everything in: $AGENTS_403_RUN"

say "preflight: one line from each host (native review dialog: none; nothing to type)"
PROBE='In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.'
CLAUDE=$(command -v claude) || fail "claude is not on PATH"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
print -r -- $PROBE | (cd $AGENTS_403_RUN && $CLAUDE -p --model claude-sonnet-5-5) | tail -1
CODEX=$(command -v codex) || fail "codex is not on PATH"
print -r -- "codex: $CODEX ($($CODEX --version))"
$CODEX login status || fail "codex is not logged in"
print -r -- $PROBE | (cd $AGENTS_403_RUN && $CODEX exec --skip-git-repo-check --ephemeral -s read-only -) | tail -1
/bin/zsh $HERE/pi.zsh preflight

for step in $STEPS; do
  say "$step step"
  # A step's own STOP or failed check is reported below; the next step still runs.
  # script(1) keeps the terminal for a native dialog, which a pipe to tee would take away.
  /usr/bin/script -q $AGENTS_403_RUN/logs/$step.log /bin/zsh $HERE/$step.zsh || print -r -- "($step.zsh exit $?)"
done

say "results"
OVERALL=0
for step in $STEPS; do
  FOUND=(${(f)"$(tr -d '\r' < $AGENTS_403_RUN/logs/$step.log | grep -E '^(PASS|FAIL) ' || true)"})
  if [[ ${#FOUND} -eq 0 ]]; then
    print -r -- "FAIL $step: stopped before its checks; see $AGENTS_403_RUN/logs/$step.log"
    OVERALL=1
    continue
  fi
  print -rl -- $FOUND
  [[ ${#${(M)FOUND:#FAIL *}} -eq 0 ]] || OVERALL=1
done
print -r -- ""
print -r -- "Retained evidence (no secret in it): $AGENTS_403_RUN"
print -r -- "Send that path back to Main."
exit $OVERALL
