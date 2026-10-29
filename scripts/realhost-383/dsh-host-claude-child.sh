#!/bin/zsh
# Task 383 real-host check A: the agents DSH host (inside the user's own DSH,
# DeepSeek model) starts a non-DSH child (Claude Code, claude-sonnet-5-5), does a
# message round trip, then resumes its own Session and the same child.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host/scripts/realhost-383/dsh-host-claude-child.sh
#
# Steps (each says which native review dialog may appear and what to choose):
#   0 preflight: versions, login state, one-line answers from dsh (DeepSeek) and claude
#   1 install the agents-dsh bundle into a new DSH profile `agents-383a` with
#     `dsh plugin` (DSH's own plugin management; needs pnpm). Without pnpm the
#     script loads the same plugin for each run with `--patch` instead and says so.
#   2 the DSH parent (`--profile agents-383a`, headless) creates a Claude child,
#     waits for PONG-1, sends a second message, waits for PONG-2, then ends its task
#   3 the parent resumes its own Session (`--session-id`), resumes the same child
#     (PONG-3), waits, and ends
#   4 the script checks the retained records and prints PASS/FAIL per criterion
#
# The parent DSH starts with DEEPSEEK_BASE_URL unset (Task 338) and keeps its
# default permission preset and approval policy: nothing is loosened. Headless
# DSH has no live approval channel, so no native dialog appears; a refused tool
# call shows in the step's JSON stream. Only whether DEEPSEEK_API_KEY is set is
# printed; no credential is read, copied or printed.
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
mkdir -p $WORK $ROOT $EVIDENCE

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

DSH=$(command -v dsh) || fail "dsh is not on PATH"
DSH_VERSION=$($VENV/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' ${DSH:A:h:h}/package.json)
print -r -- "dsh: $DSH -> ${DSH:A} (installed version $DSH_VERSION; dsh --version: $($DSH --version))"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p --model $CHILD_MODEL) | tail -1

# Read one headless --json stream: session id, tool calls/results, final text.
cat > $P/stream.py <<'EOF'
import json, sys
session = None
for line in sys.stdin:
    try:
        event = json.loads(line)
    except ValueError:
        continue
    kind = event.get('type')
    if kind == 'session':
        session = event.get('sessionId')
    elif kind in ('tool_call', 'tool_result', 'error'):
        print(kind, json.dumps({k: v for k, v in event.items() if k != 'type'}, ensure_ascii=False)[:600])
    elif kind == 'status' and (event.get('reason') or {}).get('kind') == 'error':
        print('DSH ERROR', json.dumps(event['reason'].get('error'), ensure_ascii=False)[:300])
    elif kind == 'final':
        session = event.get('sessionId') or session
        print('final reason:', json.dumps(event.get('reason')), '| text:', (event.get('text') or '')[:400])
print('SESSION=' + (session or ''))
EOF

say "step 1: install the agents-dsh bundle into a new DSH profile (native review dialog: none)"
print -r -- "Creates \$DSH_HOME/profiles/$PROFILE from the shipped headless template; other profiles are unchanged."
(cd $WORK && env $UNSET $DSH --profile $PROFILE --from-default-profile headless --json \
  "In one line: name the model you are running as, and confirm you are logged in. Do not use any tool." 2>/dev/null) \
  | $VENV/bin/python $P/stream.py | grep -v '^SESSION=' | tee $EVIDENCE/step0-dsh.txt
PATCH=()
if command -v pnpm >/dev/null; then
  $DSH plugin --profile $PROFILE add $AGENTS_DSH 2>&1 | tee $EVIDENCE/step1-plugin-add.txt
  print -r -- "installed through dsh plugin; profile manifest:"
  $DSH --profile $PROFILE --dump-config 2>/dev/null | grep -n -A2 'agents-host' | tee -a $EVIDENCE/step1-plugin-add.txt \
    || fail "the profile does not compose the agents-host row after dsh plugin add"
else
  print -r -- "pnpm is not on PATH: dsh plugin cannot install; loading the same plugin per run with --patch instead" \
    | tee $EVIDENCE/step1-plugin-add.txt
  print -rl -- '- insert:' '    - id: agents-host' "      name: $AGENTS_DSH/plugin.mjs" > $P/agents-host.patch.yml
  PATCH=(--patch $P/agents-host.patch.yml)
fi

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
touch $P/started

say "step 2: the DSH parent creates a Claude child, two answers (native review dialog: none)"
ASK2="Use only the agents tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call create "{\"runtime\":\"claude\",\"model\":\"$CHILD_MODEL\",\"instruction\":\"Reply with exactly: PONG-1\"}")
2. {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<agent from 1>\",\"timeout_seconds\":240}}
3. {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<agent from 1>\",\"message\":\"Reply with exactly: PONG-2\"}}
4. the same wait as 2.
A child's answer may also arrive as an agents notice message; that counts as its answer.
Then reply with one line: AGENT=<agent> and the two answers, and stop."
(cd $WORK && env $UNSET $HOSTENV $DSH --profile $PROFILE $PATCH --json "$ASK2" 2>$EVIDENCE/step2.stderr.txt) \
  | $VENV/bin/python $P/stream.py | tee $EVIDENCE/step2.txt || print -r -- "(dsh exit $?; continuing to collect evidence)"
SID=$(sed -n 's/^SESSION=//p' $EVIDENCE/step2.txt | tail -1)
[[ -n $SID ]] || fail "step 2 reported no DSH Session; see $EVIDENCE/step2.txt and step2.stderr.txt"
AGENT=$(ls $ROOT/control/agents 2>/dev/null | sed -n 's/\.json$//p' | head -1)
[[ -n $AGENT ]] || fail "step 2 created no child; see $EVIDENCE/step2.txt and step2.stderr.txt"
print -r -- "DSH parent Session: $SID; child agent: $AGENT"
cp $ROOT/control/agents/$AGENT.json $EVIDENCE/agent-after-step2.json

say "step 3: the DSH parent resumes its Session, then resumes the same child (native review dialog: none)"
ASK3="Use only the agents tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call resume "{\"agent\":\"$AGENT\",\"message\":\"Reply with exactly: PONG-3, then the two replies you gave before.\"}")
2. $(call wait "{\"agent\":\"$AGENT\",\"timeout_seconds\":240}")
Then reply with the child's answer in one line and stop."
(cd $WORK && env $UNSET $HOSTENV $DSH --profile $PROFILE $PATCH --session-id $SID --json "$ASK3" \
  2>$EVIDENCE/step3.stderr.txt) | $VENV/bin/python $P/stream.py | tee $EVIDENCE/step3.txt \
  || print -r -- "(dsh exit $?; continuing to collect evidence)"
cp $ROOT/control/agents/$AGENT.json $EVIDENCE/agent-after-step3.json
# The relay message lands in the DSH Session log; find it by its communication id.
DSH_LOGS=${DSH_HOME:-$HOME/.dsh}
find $DSH_LOGS -name '*.jsonl' -newer $P/started -print0 2>/dev/null \
  | xargs -0 grep -l "agents-notice:" 2>/dev/null > $EVIDENCE/relay-logs.txt || true
for log in $(cat $EVIDENCE/relay-logs.txt); do
  grep -o '"communicationId":"agents-notice:[^"]*"' $log; done | sort -u > $EVIDENCE/relay-ids.txt || true

say "step 4: retained evidence"
$VENV/bin/python - $EVIDENCE/agent-after-step2.json $EVIDENCE/agent-after-step3.json $EVIDENCE/relay-ids.txt \
    $CHILD_MODEL $SID <<'EOF'
import json, sys
two, three = (json.load(open(path)) for path in sys.argv[1:3])
relays = [line.strip() for line in open(sys.argv[3]) if line.strip()]
model, session = sys.argv[4:6]
ended = lambda record: [e for e in record['executions'] if e['state'] == 'ended']
answers = lambda record: [(e.get('last_message') or '').strip() for e in ended(record)]
first_two = [e['id'] for e in ended(two)][:2]
checks = [
    ('agent-after-step2.json runtime == claude (a non-DSH child of the DSH host)', two['runtime'] == 'claude'),
    (f'agent-after-step2.json model == {model} (chosen at create)', two['model'] == model),
    ('agent-after-step2.json parent == null and creator.session == the DSH parent Session',
     two['parent'] is None and two['creator']['session'] == session),
    ('agent-after-step2.json two ended executions, completed (round trip)',
     [e['outcome'] for e in ended(two)][:2] == ['completed', 'completed']),
    ('relay-ids.txt: the DSH Session log holds an agents-notice relay for each of the two ends (once each)',
     all(sum(f'agents-notice:{execution}:completed' in line for line in relays) == 1 for execution in first_two)),
    ('agent-after-step3.json a later execution answers PONG-3 (child resumed)',
     any(answer.startswith('PONG-3') for answer in answers(three)[2:])),
    ('agent-after-step3.json sessions has one native Claude Session (same Session continued)',
     len(three['sessions']) == 1),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('answers:', json.dumps(answers(three), ensure_ascii=False))
print('notifications:', json.dumps([e.get('notification') for e in ended(three)]))
print('relay ids:', json.dumps(relays))
EOF

say "follow-up commands (copy as needed)"
print -r -- "cd $WORK && env $UNSET ${HOSTENV[*]} $DSH --profile $PROFILE ${PATCH[*]} --session-id $SID --json 'Use the agents tool once: $(call status "{\"agent\":\"$AGENT\"}"); print the raw result.'"
print -r -- "less $EVIDENCE/step2.txt $EVIDENCE/step3.txt $EVIDENCE/step2.stderr.txt $EVIDENCE/step3.stderr.txt $EVIDENCE/agent-after-step3.json"
print -r -- "cat $EVIDENCE/relay-logs.txt $EVIDENCE/relay-ids.txt"
print -r -- "Remove the test profile afterwards if wanted: rm -r ${DSH_HOME:-$HOME/.dsh}/profiles/$PROFILE"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
