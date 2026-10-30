#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 403 real-host check, Codex step: a notice held while the parent is stopped.
#
# Started by run.zsh in this directory, in a plain macOS Terminal outside any sandbox. Alone:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay/scripts/realhost-403/codex.zsh
#
# Steps:
#   1 a Codex parent creates a Codex child with a long task and ends its turn; the closing host
#     interrupts the child, so that end is recorded while the parent is stopped
#   2 the parent resumes (--resume); the host sends the held notice into the resumed turn, and the
#     parent's one call is discover, which does not show the end
#   3 the parent resumes again: nothing more is sent, and public status says delivered
#   4 the script reads the --output documents and prints PASS/FAIL per criterion
#
# Observables, none of them agents' internal records: `deliveries` and `operations` in each
# --output document, and public `status` `notification`.
#
# Flags are those of realhost-381 (codex-cli 0.164.0). No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay
PY=/Users/luoxiao/miniconda3/bin/python3.13
path=(/opt/homebrew/bin $HOME/.local/bin $path)
# Outside $TMPDIR and /tmp, so a child's sandbox treats it as outside (385).
RUN=${AGENTS_403_RUN:-/Users/luoxiao/agents-403-realhost/codex-$(date +%Y%m%dT%H%M%S)}
P=$RUN/codex
WORK=$P/work
STATE=$P/state
EVIDENCE=$P/evidence
VENV=$P/venv

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

CODEX=$(command -v codex) || fail "codex is not on PATH"
[[ -e $P ]] && fail "$P exists from an earlier run; choose another AGENTS_403_RUN"
mkdir -p $WORK $STATE $EVIDENCE

say "venv (isolated; Conda and system Python are not modified; agents only)"
$PY -m venv --system-site-packages $VENV
$VENV/bin/pip install -q --no-index --no-deps --no-build-isolation -e $WT/src/agent_swarm 2>&1 | grep -v 'WARNING: The directory' || true
if ! $VENV/bin/python -c 'import websockets' 2>/dev/null; then
  # One fixed source, read only: the Harness's persistent runtime venv (websockets 16.1.1 when written).
  SRC=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
  DIST=($SRC/websockets-*.dist-info(N/))
  [[ -d $SRC/websockets && ${#DIST} -eq 1 ]] \
    || fail "websockets is missing; install it into the venv yourself: $VENV/bin/pip install websockets==16.1.1"
  cp -R $SRC/websockets $DIST[1] $VENV/lib/python3.13/site-packages/
fi
$VENV/bin/python -c 'import agent_swarm, websockets; print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__)'
MODEL=$(sed -n 's/^model *= *"\(.*\)"/\1/p' $HOME/.codex/config.toml 2>/dev/null | head -1)
[[ -n $MODEL ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
print -r -- "parent and child Codex model (from ~/.codex/config.toml): $MODEL"

cat > $P/settings.json <<JSON
{
  "adapter_request": {
    "arguments": ["$CODEX"],
    "worktree_path": "$WORK",
    "session_parameters": {
      "cwd": "$WORK",
      "model": "$MODEL",
      "developerInstructions": "",
      "config": {
        "default_permissions": "work",
        "permissions": {"work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}}
      }
    }
  }
}
JSON
cp $P/settings.json $EVIDENCE/
host() {  # host <output> <stderr log> [--resume] <instruction>; a failed run still leaves its evidence
  local output=$1 log=$2; shift 2
  $VENV/bin/python -m agent_swarm.codex.host --settings $P/settings.json --directory $STATE \
    --output $output "$@" 2> >(tee $log >&2) || print -r -- "(host exit $?; continuing to collect evidence)"
}
DIALOG='Native review dialog: none expected (approvals go to Codex auto_review). If a line {"native_request": ...} appears on stderr, type ONE line and press Enter:
  method mcpServer/elicitation/request whose params name the agents tool: {"action":"accept","content":{}}
  any other method: {"decision":"decline"}'

cat > $P/created.py <<'PY'
"""Name the child the first run created, from its public create result."""
import json, sys

document = json.load(open(sys.argv[1]))
created = next(o['result'] for o in document['operations'] if o['action'] == 'create' and not o['failed'])
print(created['agent'], created['execution'])
PY
cat > $P/check.py <<'PY'
"""Read the host's --output documents; never agents' internal records."""
import json, sys

first, second, third = (json.load(open(path)) for path in sys.argv[1:4])
agent, execution = sys.argv[4:6]
ids = lambda document: [delivery.get('id') for delivery in document['deliveries']]
own = [item for item in ids(second) if (item or '').startswith(execution + ':')]
statuses = [o['result']['result'] for o in third['operations']
            if o['action'] == 'status' and not o['failed'] and o['result'].get('agent') == agent]
last = statuses[-1].get('last_result', {}) if statuses else {}
checks = [
    ('Codex stopped: the first run delivered nothing for its child, which ended only after its turn',
     not [item for item in ids(first) if (item or '').startswith(execution + ':')], f'{ids(first)}'),
    ('Codex resume: the notice arrives exactly once', len(own) == 1, f'{ids(second)}'),
    ('Codex end: it names the child\'s stop', bool(own) and own[0].split(':')[1] in ('interrupted', 'failed'), f'{own}'),
    ('Codex no status read: the resumed parent did not read the end through status or wait',
     not [o for o in second['operations'] if o['action'] in ('status', 'wait')],
     f"{[o['action'] for o in second['operations']]}"),
    ('Codex further resume: nothing more is sent', ids(third) == [], f'{ids(third)}'),
    ('Codex status: public status says delivered, and repeats no body',
     last.get('notification') == 'delivered' and last.get('last_message') is None, f'{last}'),
]
failed = False
for name, passed, detail in checks:
    print(('PASS ' if passed else 'FAIL ') + name)
    print('     ' + str(detail))
    failed = failed or not passed
sys.exit(1 if failed else 0)
PY

say "step 1: Codex parent creates a long Codex child and ends its turn"
print -r -- $DIALOG
host $EVIDENCE/step1.json $EVIDENCE/step1.stderr.log "Use only the agents MCP tool, no shell commands.
Call it once with {\"action\":\"execute\",\"feature\":\"create\",\"arguments\":{\"runtime\":\"codex\",\"model\":\"$MODEL\",\"reasoning_effort\":\"low\",\"instruction\":\"Run the shell command /bin/sleep 600, then reply with exactly: SLEPT\"}}.
Do not wait for the child and do not call any other feature. End your turn with one line."
CREATED=($($VENV/bin/python $P/created.py $EVIDENCE/step1.json)) \
  || fail "step 1 created no child; see $EVIDENCE/step1.json and $EVIDENCE/step1.stderr.log"
AGENT=$CREATED[1]; EXECUTION=$CREATED[2]
print -r -- "child agent $AGENT, execution $EXECUTION; the host has exited, so the child's end is recorded now"

say "step 2: the parent resumes; the host sends the held notice into the turn"
print -r -- $DIALOG
host $EVIDENCE/step2.json $EVIDENCE/step2.stderr.log --resume 'Use only the agents MCP tool, no shell commands.
Call it once with {"action":"discover"}. Do not call status or wait, even if a notice arrives. End your turn with one line.'

say "step 3: a further resume sends nothing; public status reads delivered"
print -r -- $DIALOG
ASK3="Use only the agents MCP tool, no shell commands.
Call it once with {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"$AGENT\"}}. End your turn with one line."
host $EVIDENCE/step3.json $EVIDENCE/step3.stderr.log --resume "$ASK3"

say "step 4: checks (no model calls)"
RESULT=0
$VENV/bin/python $P/check.py $EVIDENCE/step1.json $EVIDENCE/step2.json $EVIDENCE/step3.json $AGENT $EXECUTION \
  | tee $EVIDENCE/checks.txt || RESULT=1

say "follow-up commands (copy as needed)"
print -r -- "cd ${(q)WORK} && ${(q)VENV}/bin/python -m agent_swarm.codex.host --settings ${(q)P}/settings.json --directory ${(q)STATE} --output ${(q)EVIDENCE}/again.json --resume ${(qq)ASK3}"
print -r -- "${(q)VENV}/bin/python -m json.tool ${(q)EVIDENCE}/step2.json | grep -n ${EXECUTION}:"
print -r -- "less ${(q)EVIDENCE}/step1.json ${(q)EVIDENCE}/step2.json ${(q)EVIDENCE}/step3.json ${(q)EVIDENCE}/step2.stderr.log"
print -r -- "Evidence kept in $EVIDENCE; no secret is in it. Remove $RUN when done."
exit $RESULT
