#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 403 real-host check, Claude Code step: a notice held while the parent is stopped.
#
# Started by run.zsh in this directory, in a plain macOS Terminal outside any sandbox. Alone:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay/scripts/realhost-403/claude.zsh
#
# Steps:
#   1 folder trust: one interactive Claude Code start in the empty project, then /exit
#   2 a Claude Main creates a Codex child with a long task and ends; Claude Code ending the
#     Session stops the host, which interrupts the child, so that end is recorded while stopped
#   3 the Main resumes (--resume) and makes one call that does not itself show the end:
#     discover, not status. Print mode has no prompt push, so the notice comes as main_notices
#   4 the Main resumes again: discover shows no notice, and public status says delivered
#   5 the script reads the Claude output and the host log and prints PASS/FAIL per criterion
#
# Observables, none of them agents' internal records: the notice id `<execution>:<event>` in the
# tool results of each `claude -p --output-format stream-json` run and in the native transcript,
# public `status` `notification`, and two lines of host.log. The child's end is `interrupted` when
# the host finishes stopping it, or `failed` (owner-exited) when Claude Code kills the host first;
# either must arrive exactly once. Claude Code follows SIGINT with another signal soon after
# (src/agent_swarm/mcp.py INTERRUPT_SECONDS, Task 404), so the check prints whether host.log shows
# the host finished. Its absence with a `failed` notice is that kill, not a failure of holding.
#
# Flags are those of realhost-381 and realhost-404. No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay
PY=/Users/luoxiao/miniconda3/bin/python3.13
path=(/opt/homebrew/bin $HOME/.local/bin $path)
# Outside $TMPDIR and /tmp, so a child's sandbox treats it as outside (385).
RUN=${AGENTS_403_RUN:-/Users/luoxiao/agents-403-realhost/claude-$(date +%Y%m%dT%H%M%S)}
P=$RUN/claude
WORK=$P/project
ROOT=$WORK/.agents-control
EVIDENCE=$P/evidence
VENV=$P/venv

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }
# A hung run must not hold the terminal for ever: the alarm survives exec.
BOUNDED=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' 600)

CLAUDE=$(command -v claude) || fail "claude is not on PATH"
CODEX=$(command -v codex) || fail "codex is not on PATH"
[[ -e $P ]] && fail "$P exists from an earlier run; choose another AGENTS_403_RUN"
mkdir -p $WORK $EVIDENCE

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
CHILD_MODEL=$(sed -n 's/^model *= *"\(.*\)"/\1/p' $HOME/.codex/config.toml 2>/dev/null | head -1)
[[ -n $CHILD_MODEL ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
print -r -- "Codex child model, chosen explicitly at create (from ~/.codex/config.toml): $CHILD_MODEL"

say "step 1: folder trust (one dialog)"
print -r -- "Claude Code now starts once in the empty project $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
(cd $WORK && $CLAUDE)

say "write the host configuration (native review dialog: none)"
(cd $WORK && $VENV/bin/python -m agent_swarm.claude.host configuration --project $WORK --claude $CLAUDE --write) >/dev/null
$VENV/bin/python - $ROOT/claude-host.json $CODEX $WORK $CHILD_MODEL <<'PY'
import json, sys
path, codex, work, model = sys.argv[1:5]
document = json.load(open(path))
document['runtimes'] = {'codex': {'adapter_request': {
    'arguments': [codex], 'worktree_path': work,
    'session_parameters': {'cwd': work, 'model': model, 'developerInstructions': '',
        'config': {'default_permissions': 'work', 'permissions': {
            'work': {'extends': ':workspace', 'filesystem': {':workspace_roots': {'.': 'write'}}}}}}}}}
json.dump(document, open(path, 'w'), indent=2)
PY
# The declared model list avoids native discovery; no home: the native Codex login.
cat > $ROOT/config.yml <<YAML
connections:
  local-codex:
    runtime: codex
    models:
      - $CHILD_MODEL
YAML
cp $ROOT/claude-host.json $ROOT/config.yml $EVIDENCE/
U=$(uuidgen | tr A-Z a-z)
print -r -- "Claude Main Session: $U"
CLAUDE_ARGS=(-p --output-format stream-json --verbose --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__agents)
call() { $VENV/bin/python -c 'import json,sys; print(json.dumps({"action":"execute","feature":sys.argv[1],"arguments":json.loads(sys.argv[2])}))' "$@"; }
main() {  # main <stream file> <claude session flag> <prompt>; a failed run still leaves its evidence
  print -r -- "$3" | (cd $WORK && $BOUNDED $CLAUDE $CLAUDE_ARGS ${=2} $U) >$1 2>$1.stderr \
    || print -r -- "(claude exit $?; continuing to collect evidence)"
}

cat > $P/check.py <<'PY'
"""Read one Claude stream's tool results; never agents' internal records."""
import json, sys
from pathlib import Path


def documents(path):
    """Yield each tool result in one stream-json file as its JSON document."""
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get('message') if isinstance(record, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict) or item.get('type') != 'tool_result':
                continue
            text = item.get('content')
            if isinstance(text, list):
                text = ''.join(part.get('text', '') for part in text if isinstance(part, dict))
            try:
                document = json.loads(text)
            except (TypeError, ValueError):
                continue
            if isinstance(document, dict):
                yield document


def notices(path):
    return [notice['id'] for document in documents(path) for notice in document.get('main_notices', [])]


def prompted(path, agent):
    """Count the pushed form too, should this Claude Code push in print mode."""
    return Path(path).read_text(errors='replace').count(f'[GraphTraj notice from {agent}')


if sys.argv[1] == 'created':
    created = next((document for document in documents(sys.argv[2])
                    if document.get('agent') and document.get('execution')), {})
    print(created.get('agent', ''), created.get('execution', ''))
    sys.exit()

create, resumed, later, transcript, log, agent, execution, session = sys.argv[1:9]
seen = notices(resumed)
ids = [item for item in seen if item.startswith(execution + ':')]
pushed = prompted(resumed, agent)
statuses = [document['result'] for document in documents(later)
            if isinstance(document.get('result'), dict) and document['result'].get('agent') == agent]
last = statuses[-1].get('last_result', {}) if statuses else {}
native = Path(transcript).read_text(errors='replace').count(f'{execution}:') if Path(transcript).is_file() else None
text = Path(log).read_text(errors='replace') if Path(log).is_file() else ''
print(f'host.log Claude Code ended the session by SIGINT: {"Claude Code ended the session" in text}')
print(f'host.log host finished recording its stopped children: {"recorded its children stopped" in text}')
print(f'native transcript mentions of {execution}: {native} (the resumed Session; a count, for reading by eye)')
checks = [
    ('Claude stopped: the first run shows no notice for its child, which ended only after it',
     not [item for item in notices(create) if item.startswith(execution + ':')], ''),
    ('Claude resume: the notice arrives exactly once', len(ids) + pushed == 1,
     f'main_notices {ids}, pushed {pushed} (a push is acceptable, one way only)'),
    ('Claude end: it names the child\'s stop', any(item.split(':')[1] in ('interrupted', 'failed') for item in ids) or pushed == 1,
     f'{ids}'),
    ('Claude further resume: no notice', notices(later) == [] and prompted(later, agent) == 0, f'{notices(later)}'),
    ('Claude status: public status says delivered, and repeats no body',
     last.get('notification') == 'delivered' and last.get('last_message') is None, f'{last}'),
]
failed = False
for name, passed, detail in checks:
    print(('PASS ' if passed else 'FAIL ') + name)
    print('     ' + str(detail))
    failed = failed or not passed
sys.exit(1 if failed else 0)
PY

say "step 2: Claude Main creates a long Codex child and ends"
print -r -- "Native review dialog: none (print mode; the agents tool is pre-allowed; the child's approvals go to Codex auto_review)."
LONG=$(call create "{\"runtime\":\"codex\",\"model\":\"$CHILD_MODEL\",\"reasoning_effort\":\"low\",\"instruction\":\"Run the shell command /bin/sleep 600, then reply with exactly: SLEPT\"}")
main $EVIDENCE/step2.jsonl --session-id "Use only the agents MCP tool (mcp__agents__agents). Call it once with exactly these arguments: $LONG
Do not wait for the child and do not call any other feature. Then reply with one line and stop."
CREATED=($($VENV/bin/python $P/check.py created $EVIDENCE/step2.jsonl))
[[ ${#CREATED} -eq 2 ]] || fail "step 2 created no child; see $EVIDENCE/step2.jsonl and $ROOT/host.log"
AGENT=$CREATED[1]; EXECUTION=$CREATED[2]
print -r -- "child agent $AGENT, execution $EXECUTION; Claude Code has exited."
# If Claude Code's next signal killed the host first, the child's end is only recorded once its
# Runtime is gone too, which the next host finds. Give that Runtime time to see its input close.
print -r -- "Waiting 15 s for a Runtime that outlived a killed host to exit (nothing to type)."
sleep 15

say "step 3: the Main resumes and calls discover, which does not show the end"
print -r -- "Native review dialog: none."
DISCOVER='{"action":"discover"}'
ASK_DISCOVER="Use only the agents MCP tool (mcp__agents__agents). Call it once with exactly these arguments: $DISCOVER
Do nothing else, even if the result carries a notice. Reply with one line and stop."
main $EVIDENCE/step3.jsonl --resume "$ASK_DISCOVER"

say "step 4: a further resume finds no notice; public status reads delivered"
print -r -- "Native review dialog: none."
STATUS=$(call status "{\"agent\":\"$AGENT\"}")
ASK_STATUS="Use only the agents MCP tool (mcp__agents__agents). Call it twice, in order, with exactly these arguments:
1. $DISCOVER
2. $STATUS
Do nothing else. Reply with one line and stop."
main $EVIDENCE/step4.jsonl --resume "$ASK_STATUS"

say "step 5: checks (no model calls)"
cp $ROOT/host.log $EVIDENCE/host.log 2>/dev/null || print -r -- "no host.log at $ROOT/host.log"
TRANSCRIPT=$(find $HOME/.claude/projects -name "$U.jsonl" -print 2>/dev/null | head -1 || true)
print -r -- "native transcript: ${TRANSCRIPT:-not found}"
RESULT=0
$VENV/bin/python $P/check.py $EVIDENCE/step2.jsonl $EVIDENCE/step3.jsonl $EVIDENCE/step4.jsonl "${TRANSCRIPT:-/nonexistent}" \
  $EVIDENCE/host.log $AGENT $EXECUTION $U | tee $EVIDENCE/checks.txt || RESULT=1

say "follow-up commands (copy as needed)"
print -r -- "cd ${(q)WORK} && print -r -- ${(qq)ASK_STATUS} | ${(q)CLAUDE} ${(q)CLAUDE_ARGS} --resume $U"
print -r -- "grep -n ${EXECUTION}: ${(q)${TRANSCRIPT:-$EVIDENCE/step3.jsonl}}"
print -r -- "less ${(q)EVIDENCE}/step2.jsonl ${(q)EVIDENCE}/step3.jsonl ${(q)EVIDENCE}/step4.jsonl ${(q)EVIDENCE}/host.log"
print -r -- "Evidence kept in $EVIDENCE; no secret is in it. Remove $RUN when done."
exit $RESULT
