#!/bin/zsh
# Task 383 real-host check A: the agents DSH host (inside DSH, DeepSeek model)
# starts a non-DSH child (Claude Code, claude-sonnet-5-5), does a message round
# trip, then resumes its own Session and the same child.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host/scripts/realhost-383/dsh-host-claude-child.sh
#
# Steps (each says which native review dialog may appear and what to choose):
#   0 preflight: versions, login state, one-line answers from dsh (DeepSeek) and claude
#   1 put the agents-dsh bundle into the test profile: `dsh plugin add` through
#     pnpm with --offline (no registry access), else the same plugin per run
#     with --patch; the route used and the composed agents-host row are printed
#   2 the DSH parent (headless) creates a Claude child, waits for PONG-1, sends a
#     second message, waits for PONG-2, then ends its task
#   3 the parent resumes its own Session (`--session-id`), resumes the same child
#     (PONG-3), waits, reads the child's status, and ends
#   4 the script checks the public agents results and the DSH Session log and
#     prints PASS/FAIL per criterion
#
# DSH runs with its own home $P/dsh-home (DSH_HOME), as agent_swarm.dsh.execution
# isolates its children; the user's ~/.dsh is neither read nor changed. The key
# reaches DSH by name only (llm-deepseek apiKeyEnv: DEEPSEEK_API_KEY); its value
# is never written or printed, only whether it is set. DSH starts with
# DEEPSEEK_BASE_URL unset (Task 338) and keeps its default permission preset and
# approval policy: nothing is loosened. Headless DSH has no live approval
# channel, so no native dialog appears; a refused tool call shows in the step's
# retained events. Every check reads public agents results (the tool results the
# parent received) or the native DSH Session log, never agents' internal records.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=236a3a1ef369bdf68f662543732e0c28acf2c729
P=/Users/luoxiao/agents-383-realhost/a
PY=/Users/luoxiao/miniconda3/bin/python3.13
CHILD_MODEL=claude-sonnet-5-5
PROFILE=agents-383a
WORK=$P/project
ROOT=$P/data
EVIDENCE=$P/evidence
VENV=$P/venv

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "commit check"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-383' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-383' || fail "the Worktree has uncommitted code changes"

[[ -e $P ]] && fail "$P exists from an earlier run; move it away (for example: mv $P $P.old) and run again"
mkdir -p $WORK $ROOT $EVIDENCE $P/dsh-home
export DSH_HOME=$P/dsh-home
print -r -- "DSH_HOME=$DSH_HOME (isolated; ~/.dsh is not used)"

say "venv (isolated; Conda and system Python are not modified; agents only, no GraphTraj)"
$PY -m venv --system-site-packages $VENV
$VENV/bin/pip install -q --no-index --no-deps --no-build-isolation -e $WT/src/agent_swarm
if ! $VENV/bin/python -c 'import websockets' 2>/dev/null; then
  # One fixed source: the Harness's persistent runtime venv (websockets 16.1.1 when written).
  SRC=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
  DIST=($SRC/websockets-*.dist-info(N/))
  [[ -d $SRC/websockets && ${#DIST} -eq 1 ]] \
    || fail "websockets is missing; install it into the venv yourself: $VENV/bin/pip install websockets==16.1.1"
  cp -R $SRC/websockets $DIST[1] $VENV/lib/python3.13/site-packages/
  print -r -- "copied websockets ${${${DIST[1]:t}#websockets-}%.dist-info} from $SRC"
fi
$VENV/bin/python -c 'import agent_swarm, websockets; print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__)'
AGENTS_DSH=$($VENV/bin/python -c 'import agent_swarm.dsh, pathlib; print(pathlib.Path(agent_swarm.dsh.__file__).parent)')
print -r -- "agents DSH bundle: $AGENTS_DSH"

# Retain each headless --json event in full; print a short summary and the
# Session id and final reason as SESSION=/FINAL= lines.
cat > $P/stream.py <<'EOF'
import json, sys
session, final = None, ''
with open(sys.argv[1], 'w') as retained:
    for line in sys.stdin:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        retained.write(json.dumps(event, ensure_ascii=False) + '\n')
        kind = event.get('type')
        if kind == 'session':
            session = event.get('sessionId')
        elif kind in ('tool_call', 'tool_result', 'error'):
            print(kind, json.dumps({k: v for k, v in event.items() if k != 'type'}, ensure_ascii=False)[:300])
        elif kind == 'status' and (event.get('reason') or {}).get('kind') == 'error':
            print('DSH ERROR', json.dumps(event['reason'].get('error'), ensure_ascii=False)[:300])
        elif kind == 'final':
            session = event.get('sessionId') or session
            final = (event.get('reason') or {}).get('kind') or ''
            print('final reason:', json.dumps(event.get('reason')), '| text:', (event.get('text') or '')[:400])
print('SESSION=' + (session or ''))
print('FINAL=' + final)
EOF

# The public agents result documents ({"action", "agent", "session", "result"})
# the parent received, found in the retained tool_result events.
cat > $P/public.py <<'EOF'
import json, sys

def documents(value):
    """Yield agents result documents inside one event, parsing JSON text."""
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

found = []
for line in open(sys.argv[1]):
    event = json.loads(line)
    if event.get('type') == 'tool_result':
        for document in documents(event):
            if document not in found:
                found.append(document)
with open(sys.argv[2], 'w') as output:
    for document in found:
        output.write(json.dumps(document, ensure_ascii=False) + '\n')
for document in found:
    print(document['action'], document.get('agent'), json.dumps(document.get('error') or {
        key: (document.get('result') or {}).get(key) for key in ('runtime', 'model', 'state', 'session')}))
EOF

say "step 0: preflight (native review dialog: none; nothing to type)"
if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
  source ~/.zshrc >/dev/null 2>&1 || true
fi
print -r -- "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
[[ -n ${DEEPSEEK_API_KEY:-} ]] || fail "DEEPSEEK_API_KEY is unset; export it (or add it to ~/.zshrc) and run again"
print -r -- "DEEPSEEK_BASE_URL in this shell: ${${DEEPSEEK_BASE_URL:+set}:-unset} (DSH starts with it unset)"
GT_VARS=(${(k)parameters[(I)GRAPHTRAJ_*]})
print -r -- "GRAPHTRAJ_* variables removed for DSH: ${GT_VARS:-none}"
UNSET=(-u DEEPSEEK_BASE_URL -u AGENT_SWARM_CONNECTION -u DSH_AGENT_PACKAGE)
for name in $GT_VARS; do UNSET+=(-u $name); done
# The fresh home's provider takes the key by its variable name, as the agents
# DSH driver's own profile patch does; the value stays in the environment.
print -rl -- '- id: llm-deepseek' '  config:' '    apiKeyEnv: DEEPSEEK_API_KEY' > $P/deepseek-key.patch.yml
KEY=(--patch $P/deepseek-key.patch.yml)

DSH=$(command -v dsh) || fail "dsh is not on PATH"
DSH_VERSION=$($VENV/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' ${DSH:A:h:h}/package.json)
print -r -- "dsh: $DSH -> ${DSH:A} (installed version $DSH_VERSION; dsh --version: $($DSH --version))"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p --model $CHILD_MODEL) | tail -1
print -r -- "dsh: creates profile $PROFILE in $DSH_HOME from the shipped headless template and answers once"
(cd $WORK && env $UNSET $DSH --profile $PROFILE --from-default-profile headless $KEY --json \
  "In one line: name the model you are running as, and confirm you are logged in. Do not use any tool." \
  2>$EVIDENCE/step0.stderr.txt) | $VENV/bin/python $P/stream.py $EVIDENCE/step0-events.jsonl | tee $EVIDENCE/step0.txt \
  || print -r -- "(dsh exit $?)"
grep -qx 'FINAL=completed' $EVIDENCE/step0.txt \
  || fail "DSH did not answer in the isolated home; see $EVIDENCE/step0.txt and step0.stderr.txt"

say "step 1: put the agents-dsh bundle into profile $PROFILE (native review dialog: none)"
PATCH=()
if command -v pnpm >/dev/null && env npm_config_offline=true $DSH plugin --profile $PROFILE add --offline $AGENTS_DSH \
    > $EVIDENCE/step1-plugin-add.txt 2>&1; then
  ROUTE="dsh plugin add through pnpm --offline (npm_config_offline=true; no registry access)"
else
  print -r -- "dsh plugin add was not used (pnpm missing, or it failed offline; see step1-plugin-add.txt)" \
    >> $EVIDENCE/step1-plugin-add.txt
  print -rl -- '- insert:' '    - id: agents-host' "      name: $AGENTS_DSH/plugin.mjs" > $P/agents-host.patch.yml
  PATCH=(--patch $P/agents-host.patch.yml)
  ROUTE="--patch $P/agents-host.patch.yml on each run (dsh plugin add not used)"
fi
print -r -- "route: $ROUTE" | tee -a $EVIDENCE/step1-plugin-add.txt
cat $EVIDENCE/step1-plugin-add.txt
env $UNSET $DSH --profile $PROFILE $KEY $PATCH --dump-config 2>/dev/null > $EVIDENCE/step1-dump-config.txt || true
grep -n -B1 -A3 'agents-host' $EVIDENCE/step1-dump-config.txt \
  || fail "the composed profile has no agents-host row; see $EVIDENCE/step1-dump-config.txt"

cat > $P/dsh-host.json <<EOF
{"root": "$ROOT", "claude": {"executable": "$CLAUDE"}}
EOF
# The declared model list avoids native discovery; no home: the native Claude login.
cat > $ROOT/config.yml <<EOF
connections:
  local-claude:
    runtime: claude
    models:
      - $CHILD_MODEL
EOF
cp $P/dsh-host.json $ROOT/config.yml $EVIDENCE/
HOSTENV=(AGENT_SWARM_PYTHON=$VENV/bin/python AGENT_SWARM_DSH_CONFIG=$P/dsh-host.json)
call() { $VENV/bin/python -c 'import json,sys; print(json.dumps({"action":"execute","feature":sys.argv[1],"arguments":json.loads(sys.argv[2])}))' "$@"; }

say "step 2: the DSH parent creates a Claude child, two answers (native review dialog: none)"
ASK2="Use only the agents tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call create "{\"runtime\":\"claude\",\"model\":\"$CHILD_MODEL\",\"instruction\":\"Reply with exactly: PONG-1\"}")
2. {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<agent from 1>\",\"timeout_seconds\":240}}
3. {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<agent from 1>\",\"message\":\"Reply with exactly: PONG-2\"}}
4. the same wait as 2.
A child's answer may also arrive as an agents notice message; that counts as its answer.
Then reply with one line: AGENT=<agent> and the two answers, and stop."
(cd $WORK && env $UNSET $HOSTENV $DSH --profile $PROFILE $KEY $PATCH --json "$ASK2" 2>$EVIDENCE/step2.stderr.txt) \
  | $VENV/bin/python $P/stream.py $EVIDENCE/step2-events.jsonl | tee $EVIDENCE/step2.txt \
  || print -r -- "(dsh exit $?; continuing to collect evidence)"
$VENV/bin/python $P/public.py $EVIDENCE/step2-events.jsonl $EVIDENCE/step2-agents.jsonl
SID=$(sed -n 's/^SESSION=//p' $EVIDENCE/step2.txt | tail -1)
[[ -n $SID ]] || fail "step 2 reported no DSH Session; see $EVIDENCE/step2.txt and step2.stderr.txt"
AGENT=$($VENV/bin/python -c 'import json,sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d["action"] == "create" and d.get("agent"): print(d["agent"]); break' $EVIDENCE/step2-agents.jsonl)
[[ -n $AGENT ]] || fail "no public create result named a child; see $EVIDENCE/step2-events.jsonl and step2.stderr.txt"
print -r -- "DSH parent Session: $SID; child agent (from the create result): $AGENT"

say "step 3: the DSH parent resumes its Session, then the same child (native review dialog: none)"
ASK3="Use only the agents tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call resume "{\"agent\":\"$AGENT\",\"message\":\"Reply with exactly: PONG-3, then the two replies you gave before.\"}")
2. $(call wait "{\"agent\":\"$AGENT\",\"timeout_seconds\":240}")
3. $(call status "{\"agent\":\"$AGENT\"}")
A child's answer may also arrive as an agents notice message; that counts as its answer.
Then reply with the child's answer in one line and stop."
(cd $WORK && env $UNSET $HOSTENV $DSH --profile $PROFILE $KEY $PATCH --session-id $SID --json "$ASK3" \
  2>$EVIDENCE/step3.stderr.txt) | $VENV/bin/python $P/stream.py $EVIDENCE/step3-events.jsonl | tee $EVIDENCE/step3.txt \
  || print -r -- "(dsh exit $?; continuing to collect evidence)"
$VENV/bin/python $P/public.py $EVIDENCE/step3-events.jsonl $EVIDENCE/step3-agents.jsonl

# The relay messages are native DSH Session records in the isolated home.
$VENV/bin/python - $DSH_HOME $EVIDENCE/relay-messages.jsonl <<'EOF'
import json, pathlib, sys

def walk(value):
    """Yield every native user/message event carrying an agents notice relay."""
    if isinstance(value, dict):
        source = (value.get('data') or {}).get('source') if value.get('type') == 'user/message' else None
        if isinstance(source, dict) and str(source.get('communicationId', '')).startswith('agents-notice:'):
            yield value
            return
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)

with open(sys.argv[2], 'w') as output:
    for path in sorted(pathlib.Path(sys.argv[1]).rglob('*.jsonl')):
        for line in path.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for event in walk(record):
                data = event['data']
                output.write(json.dumps({'log': str(path), 'seq': event.get('seq'),
                    'communicationId': data['source']['communicationId'],
                    'text': ''.join(part.get('text', '') for part in data.get('content') or [])},
                    ensure_ascii=False) + '\n')
EOF

say "step 4: public results and the native relay"
$VENV/bin/python - $EVIDENCE/step2-agents.jsonl $EVIDENCE/step3-agents.jsonl $EVIDENCE/relay-messages.jsonl \
    $CHILD_MODEL $SID $AGENT <<'EOF'
import json, sys
read = lambda path: [json.loads(line) for line in open(path) if line.strip()]
two, three, relays = read(sys.argv[1]), read(sys.argv[2]), read(sys.argv[3])
model, session, agent = sys.argv[4:7]
mine = lambda documents, action: [d for d in documents if d['action'] == action and d.get('agent') == agent
                                  and 'error' not in d]
create = (mine(two, 'create') or [{}])[0].get('result') or {}
status = (mine(three, 'status') or [{}])[-1].get('result') or {}
waits2 = [d['result'] for d in mine(two, 'wait')]
waits3 = [d['result'] for d in mine(three, 'wait')]
relayed = {}
for relay in relays:
    relayed.setdefault(relay['communicationId'], []).append(relay['text'])
answer = lambda wait: ((wait.get('last_result') or {}).get('last_message') or ''.join(
    relayed.get(f"agents-notice:{(wait.get('last_result') or {}).get('id')}:completed", [])))
said2, said3 = ' | '.join(map(answer, waits2)), ' | '.join(map(answer, waits3))
delivered = [(w.get('last_result') or {}).get('id') for w in waits2 + waits3
             if (w.get('last_result') or {}).get('notification') == 'delivered']
native = {w.get('session') for w in waits2 + waits3 if w.get('session')}
checks = [
    ('create result: runtime == claude (a non-DSH child of the DSH host)', create.get('runtime') == 'claude'),
    (f'create result: model == {model} (chosen at create)', create.get('model') == model),
    ('create result: parent == null and creator.session == the DSH parent Session',
     create.get('parent') is None and (create.get('creator') or {}).get('session') == session),
    ('step 2 wait results or relays: PONG-1 then PONG-2 (round trip)', 'PONG-1' in said2 and 'PONG-2' in said2),
    ('relay-messages.jsonl: each end the host pushed (notification delivered) is in the DSH Session once',
     bool(delivered) and all(len(relayed.get(f'agents-notice:{e}:completed', [])) == 1 for e in delivered)),
    ('step 3 wait result or relay: PONG-3 (child resumed)', 'PONG-3' in said3),
    ('step 3 status result: same native Claude Session as the waits, standby, creator.session unchanged',
     len(native) == 1 and status.get('session') in native and status.get('state') == 'standby'
     and (status.get('creator') or {}).get('session') == session),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('answers step 2:', json.dumps(said2, ensure_ascii=False))
print('answers step 3:', json.dumps(said3, ensure_ascii=False))
print('pushed ends:', json.dumps(delivered), '| relay ids:', json.dumps(sorted(relayed)))
print('status:', json.dumps({k: status.get(k) for k in ('runtime', 'model', 'state', 'session', 'parent')}))
EOF

say "follow-up commands (copy as needed)"
print -r -- "cd $WORK && env DSH_HOME=$DSH_HOME $UNSET ${HOSTENV[*]} $DSH --profile $PROFILE ${KEY[*]} ${PATCH[*]} --session-id $SID --json '$(call status "{\"agent\":\"$AGENT\"}") — call the agents tool once with exactly this and print the raw result.'"
print -r -- "less $EVIDENCE/step2-agents.jsonl $EVIDENCE/step3-agents.jsonl $EVIDENCE/relay-messages.jsonl"
print -r -- "less $EVIDENCE/step2-events.jsonl $EVIDENCE/step3-events.jsonl $EVIDENCE/step2.stderr.txt $EVIDENCE/step3.stderr.txt"
print -r -- "cat $EVIDENCE/step1-plugin-add.txt $EVIDENCE/step1-dump-config.txt"
print -r -- "All DSH state of this run is in $DSH_HOME; remove $P when done."
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
