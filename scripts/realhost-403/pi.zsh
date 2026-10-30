#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 403 real-host check, Pi step: one permission-request notice on a Pi host.
#
# Started by run.zsh in this directory, in a plain macOS Terminal outside any sandbox. Alone:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay/scripts/realhost-403/pi.zsh
# `pi.zsh preflight` only answers run.zsh's one-line question.
#
# Steps:
#   1 a Pi parent on DeepSeek creates a Claude child whose one Bash command Claude asks about,
#     sees the request, answers it through `reply`, and receives the child's answer
#   2 a new Pi host process for the same Session delivers nothing more
#   3 the script reads the Pi Session file and prints PASS/FAIL per criterion
#
# Why this reaches a request, read at this commit: `pi -e extension.mjs --agents-config` starts
# the host (pi/extension.mjs registerAgents, 1.6). Its "claude" section reaches the Claude driver
# with permission_mode default (pi/host.py runtime_drivers, claude/settings.py). Claude then runs
# with --permission-prompt-tool stdio and autoAllowBashIfSandboxed false, and a Bash command it
# does not classify as read-only arrives as can_use_tool (claude/execution.py _prepare, _permission).
# The driver reports it through ExecutionEvents.request (claude/driver.py), and the core calls this
# host's receiver once. The child's Bash runs arbitrary perl, which Claude always asks about.
#
# Why a Claude child and not a Pi one: a Pi child needs agent-sandbox and srt, not installed here.
# The Pi Home is $P/pi-home, so ~/.pi is neither read nor changed. The key reaches Pi by name
# (DEEPSEEK_API_KEY, Pi's own lookup); its value is never written or printed, only set or unset.
# Print-mode Pi has no approval of its own and agents loosens nothing. Checks read the Pi Session
# file and the public agents results in it, never agents' internal records.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/403-host-notice-holding-and-relay
PY=/Users/luoxiao/miniconda3/bin/python3.13
PI_MODEL=deepseek/deepseek-flash
CHILD_MODEL=claude-sonnet-5-5
path=(/opt/homebrew/bin $HOME/.local/bin $path)
# Outside $TMPDIR and /tmp, so a child's sandbox treats it as outside (385).
RUN=${AGENTS_403_RUN:-/Users/luoxiao/agents-403-realhost/pi-$(date +%Y%m%dT%H%M%S)}
P=$RUN/pi
WORK=$P/project
EVIDENCE=$P/evidence
VENV=$P/venv
SID=realhost-403-${RUN:t}

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }
# A hung run must not hold the terminal for ever: the alarm survives exec.
BOUNDED=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' 600)

# A failing line of the user's ~/.zshrc must not stop this script, and only the key leaves it.
load_key() {
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null)
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print -r -- "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || fail "DEEPSEEK_API_KEY is unset; export it (or add it to ~/.zshrc) and run again"
}

PI_BIN=$(command -v pi) || fail "pi is not on PATH"
GT_VARS=(${(k)parameters[(I)GRAPHTRAJ_*]})
UNSET=(-u AGENT_SWARM_CONNECTION -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u DSH_AGENT_PACKAGE)
for name in $GT_VARS; do UNSET+=(-u $name); done

if [[ ${1:-} == preflight ]]; then
  load_key
  print -r -- "pi: $PI_BIN ($($PI_BIN --version 2>&1 | tail -1))"
  mkdir -p $RUN/pi-preflight/pi-home
  (cd $RUN/pi-preflight && env $UNSET PI_CODING_AGENT_DIR=$RUN/pi-preflight/pi-home $BOUNDED $PI_BIN --no-session --model $PI_MODEL -p \
    'In one line: name the model you are running as, and confirm you can answer. Do not use any tool.' </dev/null) | tail -1
  exit 0
fi

CLAUDE=$(command -v claude) || fail "claude is not on PATH"
[[ -e $P ]] && fail "$P exists from an earlier run; choose another AGENTS_403_RUN"
mkdir -p $WORK $EVIDENCE $P/data $P/sessions $P/pi-home
cd $WORK

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
EXTENSION=$($VENV/bin/python -c 'import agent_swarm.pi, pathlib; print(pathlib.Path(agent_swarm.pi.__file__).parent / "extension.mjs")')
print -r -- "Pi extension: $EXTENSION"

load_key
cat > $P/pi-host.json <<JSON
{"root": "$P/data", "claude": {"executable": "$CLAUDE", "permission_mode": "default"}}
JSON
# The declared model list avoids native discovery; no home: the native Claude login.
cat > $P/data/config.yml <<YAML
connections:
  local-claude:
    runtime: claude
    models:
      - $CHILD_MODEL
YAML
cp $P/pi-host.json $P/data/config.yml $EVIDENCE/
HOSTENV=(AGENT_SWARM_PYTHON=$VENV/bin/python PI_CODING_AGENT_DIR=$P/pi-home)
PI_ARGS=(--mode json --session-dir $P/sessions --session-id $SID --model $PI_MODEL -e $EXTENSION --agents-config $P/pi-host.json)
call() { $VENV/bin/python -c 'import json,sys; print(json.dumps({"action":"execute","feature":sys.argv[1],"arguments":json.loads(sys.argv[2])}))' "$@"; }
INSTRUCTION=$($VENV/bin/python -c 'import json,sys; print(json.dumps(sys.argv[1]))' \
  "Use the Bash tool to run exactly this command: /usr/bin/perl -e 'print 40300+3'. Then reply with exactly: ANSWER=<its output>")

# Keep each Pi event; show the tool calls so the run can be followed.
cat > $P/stream.py <<'PY'
import json, sys
with open(sys.argv[1], 'w') as retained:
    for line in sys.stdin:
        retained.write(line)
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('type')
        if kind == 'tool_execution_start':
            print('tool', json.dumps(event.get('args'), ensure_ascii=False)[:200], flush=True)
        elif kind == 'message_end' and (event.get('message') or {}).get('role') == 'custom':
            print('notice', json.dumps((event['message'].get('details') or {}).get('fact')), flush=True)
PY

say "step 1: the Pi parent, a Claude child, one permission request (native review dialog: none)"
print -r -- "Nothing to type. The parent answers the child's request with reply. A dialog here is"
print -r -- "unexpected: press Esc (dialogs time out after 300 s) and tell Main its title."
ASK1="Use only the agents tool. Call it with exactly these arguments, in order, one call at a time:
1. $(call create "{\"runtime\":\"claude\",\"model\":\"$CHILD_MODEL\",\"instruction\":$INSTRUCTION}")
2. {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<agent from 1>\",\"timeout_seconds\":180}}
3. {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"<agent from 1>\"}}
4. {\"action\":\"execute\",\"feature\":\"requests\",\"arguments\":{\"agent\":\"<agent from 1>\"}}
5. {\"action\":\"execute\",\"feature\":\"reply\",\"arguments\":{\"agent\":\"<agent from 1>\",\"request\":<the first request document from 4, unchanged>,\"response\":{\"behavior\":\"allow\"}}}
6. the same wait as 2.
A message starting with [agents notice from ...] may arrive: it is expected. A permission-request notice needs nothing beyond the calls above, and a child's answer may arrive this way; that counts as its answer.
Then reply with one line: AGENT=<agent> and the child's answer, and stop."
(cd $WORK && env $UNSET $HOSTENV $BOUNDED $PI_BIN $PI_ARGS "$ASK1" 2>$EVIDENCE/step1.stderr.txt </dev/null) \
  | $VENV/bin/python $P/stream.py $EVIDENCE/step1-events.jsonl \
  || print -r -- "(pi exit $?; continuing to collect evidence)"

SESSION_FILES=($P/sessions/*_$SID.jsonl(N))
[[ ${#SESSION_FILES} -eq 1 ]] || fail "expected one Pi Session file for $SID in $P/sessions; see $EVIDENCE/step1.stderr.txt"
SESSION_FILE=$SESSION_FILES[1]
print -r -- "Pi Session file: $SESSION_FILE"
cat > $P/check.py <<'PY'
import json, sys

session_file, stage, snapshot = sys.argv[1:4]
entries = [json.loads(line) for line in open(session_file) if line.strip()]
facts = [(entry.get('details') or {}).get('fact') for entry in entries
         if entry.get('type') == 'custom_message' and entry.get('customType') == 'graphtraj:agent-communication']
notices = [(entry.get('details') or {}) for entry in entries if entry.get('type') == 'custom_message']


def documents(value):
    """Yield public agents result documents inside one value, parsing JSON text."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, dict):
        if isinstance(value.get('action'), str) and ('result' in value or 'error' in value):
            yield value
            return
        for item in value.values():
            yield from documents(item)
    elif isinstance(value, list):
        for item in value:
            yield from documents(item)


def results(count=None):
    found = []
    for entry in entries[:count]:
        if entry.get('type') == 'message' and (entry.get('message') or {}).get('role') == 'toolResult':
            for document in documents(entry['message']):
                if document not in found:
                    found.append(document)
    return found


if stage == 'snapshot':
    json.dump({'facts': facts, 'entries': len(entries)}, open(snapshot, 'w'))
    sys.exit(0)

before = json.load(open(snapshot))
found = results()
agent = next((document.get('agent') for document in found if document['action'] == 'create' and document.get('agent')), '')
print('AGENT=' + (agent or ''))
requests = next((document['result'].get('requests') for document in found
                 if document['action'] == 'requests' and (document.get('result') or {}).get('requests')), None) or []
request = requests[0] if requests else {}
expected = f"notice:{request.get('execution') or request.get('execution_id')}:request:{request.get('request_token')}"
statuses = [(document.get('result') or {}).get('pending_requests') for document in found if document['action'] == 'status']
replies = [document for document in found if document['action'] == 'reply']
bodies = [(document.get('result') or {}).get('last_result') or {} for document in found]
answered = (any('40303' in (last.get('last_message') or '') for last in bodies)
            or any('40303' in (notice.get('body') or '') for notice in notices))
later = [document for document in results() if document not in results(before['entries'])]
checks = [
    ('Pi notice: exactly one custom message with the request fact', bool(request) and facts.count(expected) == 1
     and sum(':request:' in (fact or '') for fact in facts) == 1, f'expected {expected}; request facts '
     f'{[fact for fact in facts if ":request:" in (fact or "")]}'),
    ('Pi status: public status showed pending_requests', any((value or 0) >= 1 for value in statuses), f'{statuses}'),
    ('Pi reply: the request was answered through reply and the child went on to answer',
     bool(replies) and not any(document.get('error') for document in replies) and answered,
     f'{len(replies)} replies; answer 40303 seen: {answered}'),
    ('Pi restart: a new host process for the Session delivered nothing more',
     bool(later) and facts == before['facts'], f'{len(later)} results in the new process; facts {len(before["facts"])} -> {len(facts)}'),
    ('Pi once: no notice fact appears twice in the Session', len(facts) == len(set(facts)), f'{facts}'),
]
failed = False
for name, passed, detail in checks:
    print(('PASS ' if passed else 'FAIL ') + name)
    print('     ' + detail)
    failed = failed or not passed
sys.exit(1 if failed else 0)
PY
$VENV/bin/python $P/check.py $SESSION_FILE snapshot $EVIDENCE/after-step1.json

say "step 2: a new Pi host process for the same Session (native review dialog: none)"
print -r -- "Nothing to type; the same note as step 1 applies to a dialog."
AGENT=$($VENV/bin/python $P/check.py $SESSION_FILE check $EVIDENCE/after-step1.json | sed -n 's/^AGENT=//p' || true)
[[ -n $AGENT ]] || fail "no public create result named a child; see $EVIDENCE/step1-events.jsonl"
print -r -- "child agent (from the create result): $AGENT"
ASK2="Use only the agents tool. Call it once with exactly these arguments: $(call status "{\"agent\":\"$AGENT\"}")
Then reply with one line: the child's state, and stop."
(cd $WORK && env $UNSET $HOSTENV $BOUNDED $PI_BIN $PI_ARGS "$ASK2" 2>$EVIDENCE/step2.stderr.txt </dev/null) \
  | $VENV/bin/python $P/stream.py $EVIDENCE/step2-events.jsonl \
  || print -r -- "(pi exit $?; continuing to collect evidence)"

say "step 3: checks (no model calls)"
RESULT=0
$VENV/bin/python $P/check.py $SESSION_FILE check $EVIDENCE/after-step1.json | tee $EVIDENCE/checks.txt || RESULT=1

say "follow-up commands (copy as needed)"
print -r -- "grep -n 'notice:' ${(q)SESSION_FILE}"
print -r -- "# With DEEPSEEK_API_KEY set in that shell, a further Pi host process for this Session:"
print -r -- "cd ${(q)WORK} && env PI_CODING_AGENT_DIR=${(q)P}/pi-home AGENT_SWARM_PYTHON=${(q)VENV}/bin/python ${(q)PI_BIN} --mode json --session-dir ${(q)P}/sessions --session-id $SID --model $PI_MODEL -e ${(q)EXTENSION} --agents-config ${(q)P}/pi-host.json ${(qq)ASK2}"
print -r -- "less ${(q)EVIDENCE}/step1-events.jsonl ${(q)EVIDENCE}/step2-events.jsonl ${(q)EVIDENCE}/step1.stderr.txt ${(q)EVIDENCE}/step2.stderr.txt"
print -r -- "Evidence kept in $EVIDENCE; no secret is in it. Remove $RUN when done."
exit $RESULT
