#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 65-walk-dsh. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/65-walk-dsh.zsh
# install/dsh.md: dsh plugin add into a scratch DSH home, over an earlier add, --patch, the start lines as written, --session-id.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# DSH_HOME points at this run, so the user's profile is neither read nor changed. pnpm is not installed by this script.
step_begin 65-walk-dsh 10 none 'dsh plugin add works (or is CANNOT with pnpm named), the start line reaches a model and a Claude child answers with one relay notice'
prepare_checks
AGENTS_VENV=$VENV
export DSH_HOME=$WORK/dsh-home
mkdir -p $DSH_HOME $WORK/project $WORK/data
cd $WORK/project
git init -q .
DSH_PACKAGE="$("$AGENTS_VENV/bin/python" -c 'import agent_swarm.dsh, pathlib; print(pathlib.Path(agent_swarm.dsh.__file__).parent)')"
ADDED=
if command -v pnpm >/dev/null; then
  note "pnpm: $(command -v pnpm) $(pnpm --version)"
  CODE=0
  dsh plugin --profile headless add "$DSH_PACKAGE" > $OUT/plugin-add.txt 2>&1 || CODE=$?
  judge $CODE "dsh.md: dsh plugin --profile headless add: exit $CODE; $(tail -1 $OUT/plugin-add.txt | cut -c1-200)"
  (( CODE == 0 )) && ADDED=1
  CODE=0
  dsh plugin --profile headless add "$DSH_PACKAGE" > $OUT/plugin-add-again.txt 2>&1 || CODE=$?
  judge $CODE "dsh.md: dsh plugin add over an earlier add: exit $CODE; $(tail -1 $OUT/plugin-add-again.txt | cut -c1-200)"
else
  check CANNOT "dsh.md: dsh plugin add: pnpm is not on PATH, and this step installs nothing beyond the approved tools. The note's prerequisite says the same"
fi
print -r -- "{\"root\": \"$WORK/data\", \"claude\": {\"model\": \"$CLAUDE_MODEL\"}}" > $WORK/dsh-host.json
PATCH_FILE=$WORK/agents-host.patch.yml
cat > $PATCH_FILE <<PATCH
- insert:
    - id: agents-host
      name: $DSH_PACKAGE/plugin.mjs
PATCH
PROMPT="Use the agents tool to create a Claude child with model $CLAUDE_MODEL that answers one word, and wait for it with timeout_seconds 240 before ending the task. Then read its status. Reply with one line."
ROUTE=(); [[ -n $ADDED ]] || ROUTE=(--patch $PATCH_FILE)
say "the start line as written, on an empty DSH home with the key only in the environment"
CODE=0
bounded 420 env -u DEEPSEEK_BASE_URL AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" AGENT_SWARM_DSH_CONFIG=$WORK/dsh-host.json \
  dsh --profile headless $ROUTE --json "$PROMPT" </dev/null > $OUT/start-as-written.jsonl 2> $OUT/start-as-written.stderr || CODE=$?
FINAL=$($VENV/bin/python -I -c 'import json,sys
for line in open(sys.argv[1]):
    try: e=json.loads(line)
    except ValueError: continue
    if e.get("type")=="final": print((e.get("reason") or {}).get("kind"), e.get("sessionId"))' $OUT/start-as-written.jsonl | tail -1 || true)
note "start as written: exit $CODE, final: $FINAL"
if [[ $FINAL != completed* ]]; then
  note "dsh.md finding to read: the note's start line on a home with no login did not complete; next, the key named in a patch, as the earlier real runs did"
  print -rl -- '- id: llm-deepseek' '  config:' '    apiKeyEnv: DEEPSEEK_API_KEY' > $WORK/key.patch.yml
  ROUTE+=(--patch $WORK/key.patch.yml)
  CODE=0
  bounded 420 env -u DEEPSEEK_BASE_URL AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" AGENT_SWARM_DSH_CONFIG=$WORK/dsh-host.json \
    dsh --profile headless $ROUTE --json "$PROMPT" </dev/null > $OUT/start-with-key.jsonl 2> $OUT/start-with-key.stderr || CODE=$?
  cp $OUT/start-with-key.jsonl $OUT/start.jsonl
else
  cp $OUT/start-as-written.jsonl $OUT/start.jsonl
fi
SESSION=$($VENV/bin/python -I -c 'import json,sys
for line in open(sys.argv[1]):
    try: e=json.loads(line)
    except ValueError: continue
    if e.get("sessionId"): s=e["sessionId"]
print(s)' $OUT/start.jsonl 2>/dev/null || true)
judge $CODE "dsh.md: a Session ran: exit $CODE, session $SESSION"
grep -q '"agents"\|agents__agents\|mcp__agents' $OUT/start.jsonl && check PASS "dsh.md: the agents tool was called" || check FAIL "dsh.md: no agents tool call in the Session; read start.jsonl"
grep -q 'standby' $OUT/start.jsonl && check PASS "dsh.md: status shows standby" || check FAIL "dsh.md: status did not show standby"
if [[ -n $SESSION ]]; then
  CODE=0
  bounded 300 env -u DEEPSEEK_BASE_URL AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" AGENT_SWARM_DSH_CONFIG=$WORK/dsh-host.json \
    dsh --profile headless $ROUTE --session-id "$SESSION" --json "Reply with one word: next." </dev/null > $OUT/continue.jsonl 2> $OUT/continue.stderr || CODE=$?
  judge $CODE "dsh.md: --session-id continues the Session: exit $CODE"
fi
step_end
