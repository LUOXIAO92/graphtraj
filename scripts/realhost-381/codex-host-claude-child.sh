#!/bin/zsh
# Task 381 real-host check: a Codex host parent runs a Claude child.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/381-claude-codex-hosts-cross-runtime/scripts/realhost-381/codex-host-claude-child.sh
#
# Steps (each prints which native review dialog may appear and what to type):
#   0 preflight: versions, login status, one-line model answers from codex and claude
#   1 the Codex parent creates a Claude child with an explicit model and effort,
#     receives its answer as a host event, sends a second message, then ends its turn
#   2 the parent resumes its own Session (--resume) and resumes the same Claude child
#   3 the script checks the retained JSON and prints PASS/FAIL per criterion
#
# Flags used were checked against `codex --help`, `codex exec --help` and
# `codex login --help` (codex-cli 0.164.0). `claude -p` with the prompt on stdin
# and `claude --version` follow the pattern verified in Task 369's real run;
# Claude Code could not be executed inside the team's sandbox.
# No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/381-claude-codex-hosts-cross-runtime
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=f3af2bea8cb8c9a431de201b87428556b9092b91
P=/Users/luoxiao/agents-381-realhost/codex-host
PY=/Users/luoxiao/miniconda3/bin/python3.13
CHILD_MODEL=claude-sonnet-5-5
CHILD_EFFORT=high
WORK=$P/work
STATE=$P/state
EVIDENCE=$P/evidence
VENV=$P/venv

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "commit check"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-381' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-381' || fail "the Worktree has uncommitted code changes"

[[ -e $P ]] && fail "$P exists from an earlier run; move it away (for example: mv $P $P.old) and run again"
mkdir -p $WORK $STATE $EVIDENCE

say "venv (isolated; Conda and system Python are not modified)"
$PY -m venv --system-site-packages $VENV
$VENV/bin/pip install -q --no-index --no-deps --no-build-isolation -e $WT/src/agent_swarm
if ! $VENV/bin/python -c 'import websockets' 2>/dev/null; then
  COPY=$(print -l /private/tmp/claude-501/*/lib/python3.13/site-packages/websockets(N/) | head -1)
  [[ -n $COPY ]] || fail "websockets is missing; install it into the venv yourself: $VENV/bin/pip install websockets==16.1.1"
  cp -R $COPY ${COPY%/websockets}/websockets-*.dist-info(N) $VENV/lib/python3.13/site-packages/
fi
$VENV/bin/python -c 'import agent_swarm, websockets; print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__)'

say "step 0: preflight (native review dialog: none; nothing to type)"
CODEX=$(command -v codex) || fail "codex is not on PATH"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "codex: $CODEX ($($CODEX --version))"
$CODEX login status || fail "codex is not logged in"
print -r -- 'In one line: name the model you are running as. Do not run any command.' \
  | $CODEX exec --skip-git-repo-check --ephemeral -s read-only - | tail -1
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | $CLAUDE -p | tail -1
PARENT_MODEL=$(sed -n 's/^model *= *"\(.*\)"/\1/p' $HOME/.codex/config.toml 2>/dev/null | head -1)
[[ -n $PARENT_MODEL ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
print -r -- "parent Codex model (from ~/.codex/config.toml): $PARENT_MODEL"

cat > $P/settings.json <<EOF
{
  "adapter_request": {
    "arguments": ["$CODEX"],
    "worktree_path": "$WORK",
    "session_parameters": {
      "cwd": "$WORK",
      "model": "$PARENT_MODEL",
      "developerInstructions": "",
      "config": {
        "default_permissions": "work",
        "permissions": {"work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}}
      }
    }
  },
  "runtimes": {"claude": {"executable": "$CLAUDE"}}
}
EOF
# The declared model list avoids native discovery; no home: the native login.
cat > $STATE/config.yml <<EOF
connections:
  local-claude:
    runtime: claude
    models:
      - $CHILD_MODEL
EOF

host() {  # host <output> <stderr log> [--resume] <instruction>
  local output=$1 log=$2; shift 2
  $VENV/bin/python -m agent_swarm.codex.host --settings $P/settings.json --directory $STATE \
    --output $output "$@" 2> >(tee $log >&2)
}

say "step 1: Codex parent creates a Claude child"
print -r -- "Native review dialog: none expected (the parent's approvals go to Codex auto_review)."
print -r -- "If a line {\"native_request\": ...} appears on stderr, type ONE line and press Enter:"
print -r -- "  method mcpServer/elicitation/request whose params name the agents tool: {\"action\":\"accept\",\"content\":{}}"
print -r -- "  method ending in requestApproval for a command you do not expect:      {\"decision\":\"decline\"}"
host $EVIDENCE/step1.json $EVIDENCE/step1.stderr.log "Use only the agents MCP tool, no shell commands.
1. Call it with {\"action\":\"execute\",\"feature\":\"create\",\"arguments\":{\"runtime\":\"claude\",\"model\":\"$CHILD_MODEL\",\"reasoning_effort\":\"$CHILD_EFFORT\",\"instruction\":\"Reply with exactly: PONG-1\"}}.
2. Call it with {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<the agent from step 1>\",\"timeout_seconds\":240}}. The child's answer may also arrive as a host event.
3. Call it with {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<the same agent>\",\"message\":\"Reply with exactly: PONG-2\"}}, then wait for it as in step 2.
4. End your turn with one line: the agent and the two answers you received." || print -r -- "(host exit $?; continuing to collect evidence)"

AGENT=$($VENV/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(next(o["result"]["agent"] for o in d["operations"] if o["action"]=="create" and not o["failed"]))' $EVIDENCE/step1.json) \
  || fail "step 1 created no child; see $EVIDENCE/step1.json and $EVIDENCE/step1.stderr.log"
print -r -- "child agent: $AGENT"

say "step 2: parent --resume, then resume the same Claude child"
print -r -- "Native review dialog: same as step 1 (none expected; same replies if one appears)."
host $EVIDENCE/step2.json $EVIDENCE/step2.stderr.log --resume "Use only the agents MCP tool, no shell commands.
1. Call it with {\"action\":\"execute\",\"feature\":\"resume\",\"arguments\":{\"agent\":\"$AGENT\",\"message\":\"Reply with exactly: PONG-3, then the two replies you gave before.\"}}.
2. Wait for it with {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"$AGENT\",\"timeout_seconds\":240}}.
3. End your turn with one line: the child's answer." || print -r -- "(host exit $?; continuing to collect evidence)"

say "step 3: retained evidence"
cp $STATE/host/trace.jsonl $EVIDENCE/parent-trace.jsonl 2>/dev/null || print -r -- "no parent trace at $STATE/host/trace.jsonl"
find $STATE -name trace.jsonl -newer $P/settings.json -print > $EVIDENCE/traces.txt
$VENV/bin/python - $EVIDENCE/step1.json $EVIDENCE/step2.json $CHILD_MODEL $CHILD_EFFORT <<'EOF'
import json, sys
one, two = (json.load(open(path)) for path in sys.argv[1:3])
model, effort = sys.argv[3:5]
ops = lambda doc, action: [o for o in doc['operations'] if o['action'] == action and not o['failed']]
create = ops(one, 'create')[0]['result']
agent, session = create['agent'], create['session']
checks = [
    ('step1.json operations[create].result.result.runtime == claude', create['result']['runtime'] == 'claude'),
    (f'step1.json operations[create].result.result.model == {model}', create['result']['model'] == model),
    (f'step1.json operations[create].result.result.reasoning_effort == {effort}',
     create['result']['reasoning_effort'] == effort),
    ('step1.json operations[create].result.result.parent == null (root child of the Codex parent)',
     create['result']['parent'] is None),
    ('step1.json deliveries[] has the child answer as a host event (agent == child, accepted)',
     any(d['agent'] == agent and d['accepted'] for d in one['deliveries'])),
    ('step1.json operations[send] for the child succeeded', any(o['result']['agent'] == agent for o in ops(one, 'send'))),
    ('step2.json parent_session == step1.json parent_session (parent resumed)', two['parent_session'] == one['parent_session']),
    ('step2.json operations[resume].result.session == step1 child session (child resumed)',
     any(o['result']['agent'] == agent and o['result']['session'] == session for o in ops(two, 'resume'))),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('deliveries step1:', json.dumps([{k: d[k] for k in ('agent', 'body')} for d in one['deliveries']], ensure_ascii=False))
print('deliveries step2:', json.dumps([{k: d[k] for k in ('agent', 'body')} for d in two['deliveries']], ensure_ascii=False))
EOF

say "follow-up commands (copy as needed)"
print -r -- "zsh -c 'cd $WORK && $VENV/bin/python -m agent_swarm.codex.host --settings $P/settings.json --directory $STATE --output $EVIDENCE/step3.json --resume \"Use the agents MCP tool: status for agent $AGENT, then end your turn with its state.\"'"
print -r -- "less $EVIDENCE/step1.json $EVIDENCE/step2.json $EVIDENCE/step1.stderr.log $EVIDENCE/step2.stderr.log"
print -r -- "cat $EVIDENCE/traces.txt"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
