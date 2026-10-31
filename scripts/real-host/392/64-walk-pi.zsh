#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 64-walk-pi. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/64-walk-pi.zsh
# install/pi.md: pi install of the installed package into a scratch Pi home, -l, over an earlier install, and a real Session.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# PI_CODING_AGENT_DIR points at this run: ~/.pi is neither read nor changed. The key reaches Pi by name.
step_begin 64-walk-pi 8 none 'pi install succeeds, again over itself, and with -l; a Session with no -e has the agents tool and a Claude child answers with one notice'
prepare_checks
AGENTS_VENV=$VENV
export PI_CODING_AGENT_DIR=$WORK/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0
mkdir -p $PI_CODING_AGENT_DIR $WORK/project $WORK/data $WORK/sessions
cd $WORK/project
git init -q .
PI_PACKAGE="$("$AGENTS_VENV/bin/python" -c 'import agent_swarm.pi, pathlib; print(pathlib.Path(agent_swarm.pi.__file__).parent)')"
for form in first over-earlier; do
  CODE=0
  pi install "$PI_PACKAGE" > $OUT/pi-install-$form.txt 2>&1 || CODE=$?
  judge $CODE "pi.md: pi install, $form: exit $CODE; $(tail -1 $OUT/pi-install-$form.txt | cut -c1-200)"
done
CODE=0
pi install "$PI_PACKAGE" -l > $OUT/pi-install-local.txt 2>&1 || CODE=$?
judge $CODE "pi.md: pi install -l: exit $CODE; $(tail -1 $OUT/pi-install-local.txt | cut -c1-200)"
pi list > $OUT/pi-list.txt 2>&1 || true
cp $PI_CODING_AGENT_DIR/settings.json $OUT/settings.json 2>/dev/null || true
print -r -- "{\"root\": \"$WORK/data\", \"claude\": {\"model\": \"$CLAUDE_MODEL\"}}" > $WORK/pi-host.json
say "start it, with no -e: AGENT_SWARM_PYTHON=... pi --agents-config ..."
PROMPT="Use the agents tool to create a Claude child that answers one word, with model $CLAUDE_MODEL, then wait for it with timeout_seconds 240, then read its status. Reply with one line."
CODE=0
bounded 420 env AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" pi --agents-config $WORK/pi-host.json --mode json \
  --session-dir $WORK/sessions --model $PI_PROVIDER/$PI_MODEL -p $PROMPT </dev/null > $OUT/pi-session-stdout.jsonl 2> $OUT/pi-session.stderr || CODE=$?
judge $CODE "pi.md: a Session with the installed extension ran: exit $CODE"
SESSION=($WORK/sessions/*.jsonl(Nom[1]))
if (( ${#SESSION} )); then
  cp $SESSION $OUT/pi-session.jsonl
  NOTICES=$(grep -c 'agents notice from' $OUT/pi-session.jsonl || true)
  grep -q 'graphtraj:agent-communication' $OUT/pi-session.jsonl && check PASS "pi.md: a notice message appears in the Session ($NOTICES lines naming it); status below" \
    || check FAIL "pi.md: no agents notice in the Session; read pi-session.jsonl"
  grep -q '"notification":"delivered"\|notification\\":\\"delivered' $OUT/pi-session.jsonl \
    && check PASS "pi.md: status shows notification delivered" || check FAIL "pi.md: status did not show notification delivered"
else
  check FAIL "pi.md: no Session file in $WORK/sessions"
fi
step_end
