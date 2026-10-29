#!/bin/zsh
# Task 381 real-host check: the independent Claude Code host (Main) runs a Codex child.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/381-claude-codex-hosts-cross-runtime/scripts/realhost-381/claude-host-codex-child.sh
#
# Steps (each states which native dialog appears and what to choose):
#   0 preflight: versions, Claude flags, login status, one-line model answers from claude and codex
#   1 folder trust: one interactive Claude Code start in the empty project, then /exit
#   2 Claude Main (print mode) creates a Codex child with an explicit model and effort,
#     waits for its answer, sends a second message and waits again
#   3 Claude Main resumes its own Session (--resume) and resumes the same Codex child
#   4 the script checks the retained records and prints PASS/FAIL per criterion
#
# Flags: `claude -p` with the prompt on stdin, --session-id, --resume, --mcp-config,
# --strict-mcp-config and --allowedTools follow Tasks 369/370's real runs; Claude Code
# cannot run inside the team's sandbox, so step 0 checks each flag in `claude --help`
# and stops if one is missing. Codex flags (exec, --skip-git-repo-check, --ephemeral,
# -s, login status) are the ones the sibling script checked against codex-cli 0.164.0.
# No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/381-claude-codex-hosts-cross-runtime
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=c76734cc540230e4586b679acc49333b69b0ca59
P=/Users/luoxiao/agents-381-realhost/claude-host
PY=/Users/luoxiao/miniconda3/bin/python3.13
CHILD_EFFORT=low
WORK=$P/project
ROOT=$WORK/.agents-control
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
mkdir -p $WORK $EVIDENCE

say "venv (isolated; Conda and system Python are not modified)"
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
$VENV/bin/python -c 'import websockets; print("websockets", websockets.__version__, websockets.__file__)' \
  || fail "websockets does not import in $VENV"
$VENV/bin/python -c 'import agent_swarm, websockets; print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__)'

say "step 0: preflight (native dialog: none; nothing to type)"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
CODEX=$(command -v codex) || fail "codex is not on PATH"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
HELP=$($CLAUDE --help)
for flag in --print --session-id --resume --mcp-config --strict-mcp-config --allowedTools; do
  print -r -- $HELP | grep -q -- $flag && print -r -- "claude --help lists $flag" || fail "claude --help does not list $flag"
done
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p) | tail -1
print -r -- "codex: $CODEX ($($CODEX --version))"
$CODEX login status || fail "codex is not logged in"
print -r -- 'In one line: name the model you are running as. Do not run any command.' \
  | $CODEX exec --skip-git-repo-check --ephemeral -s read-only - | tail -1
CHILD_MODEL=$(sed -n 's/^model *= *"\(.*\)"/\1/p' $HOME/.codex/config.toml 2>/dev/null | head -1)
[[ -n $CHILD_MODEL ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
print -r -- "Codex child model, chosen explicitly at create (from ~/.codex/config.toml): $CHILD_MODEL"

say "step 1: folder trust (one dialog)"
print -r -- "Claude Code now starts once in the empty project $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
(cd $WORK && $CLAUDE)

say "write the host configuration (native dialog: none)"
(cd $WORK && $VENV/bin/python -m agent_swarm.claude.host configuration --project $WORK --claude $CLAUDE --write)
$VENV/bin/python - $ROOT/claude-host.json $CODEX $WORK $CHILD_MODEL <<'EOF'
import json, sys
path, codex, work, model = sys.argv[1:5]
document = json.load(open(path))
document['runtimes'] = {'codex': {'adapter_request': {
    'arguments': [codex], 'worktree_path': work,
    'session_parameters': {'cwd': work, 'model': model, 'developerInstructions': '',
        'config': {'default_permissions': 'work', 'permissions': {
            'work': {'extends': ':workspace', 'filesystem': {':workspace_roots': {'.': 'write'}}}}}}}}}
json.dump(document, open(path, 'w'), indent=2)
EOF
# The declared model list avoids native discovery; no home: the native Codex login.
# The host checks this connection at start (installed, logged in).
cat > $ROOT/config.yml <<EOF
connections:
  local-codex:
    runtime: codex
    models:
      - $CHILD_MODEL
EOF
cp $ROOT/claude-host.json $ROOT/config.yml $EVIDENCE/
U=$(uuidgen | tr A-Z a-z)
print -r -- "Claude Main Session: $U"
TOOLS=(--allowedTools mcp__agents__agents)
MCP=(--mcp-config $WORK/.mcp.json --strict-mcp-config)
call() { $VENV/bin/python -c 'import json,sys; print(json.dumps({"action":"execute","feature":sys.argv[1],"arguments":json.loads(sys.argv[2])}))' "$@"; }

say "step 2: Claude Main creates a Codex child, two answers"
print -r -- "Native dialog: none (print mode; the agents tool is pre-allowed; the child's approvals go to Codex auto_review)."
ASK2="Use only the agents MCP tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call create "{\"runtime\":\"codex\",\"model\":\"$CHILD_MODEL\",\"reasoning_effort\":\"$CHILD_EFFORT\",\"instruction\":\"Reply with exactly: PONG-1\"}")
2. {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<agent from 1>\",\"timeout_seconds\":240}}
3. {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<agent from 1>\",\"message\":\"Reply with exactly: PONG-2\"}}
4. the same wait as 2.
Then print each raw result text verbatim, then one line: AGENT=<agent>, and stop."
(cd $WORK && print -r -- "$ASK2" | $CLAUDE -p --session-id $U $MCP $TOOLS) | tee $EVIDENCE/step2.txt \
  || print -r -- "(claude exit $?; continuing to collect evidence)"
AGENT=$(ls $ROOT/control/agents 2>/dev/null | sed -n 's/\.json$//p' | head -1)
[[ -n $AGENT ]] || fail "step 2 created no child; see $EVIDENCE/step2.txt and $ROOT/host.log"
print -r -- "child agent: $AGENT"
cp $ROOT/control/agents/$AGENT.json $EVIDENCE/agent-after-step2.json

say "step 3: Claude Main resumes its Session, then resumes the same Codex child"
print -r -- "Native dialog: none."
ASK3="Use only the agents MCP tool (mcp__agents__agents). Call it with exactly these arguments, in order:
1. $(call resume "{\"agent\":\"$AGENT\",\"message\":\"Reply with exactly: PONG-3, then the two replies you gave before.\"}")
2. $(call wait "{\"agent\":\"$AGENT\",\"timeout_seconds\":240}")
Then print each raw result text verbatim and stop."
(cd $WORK && print -r -- "$ASK3" | $CLAUDE -p --resume $U $MCP $TOOLS) | tee $EVIDENCE/step3.txt \
  || print -r -- "(claude exit $?; continuing to collect evidence)"
cp $ROOT/control/agents/$AGENT.json $EVIDENCE/agent-after-step3.json
cp $ROOT/host.log $EVIDENCE/host.log 2>/dev/null || true
find $ROOT -name trace.jsonl -print > $EVIDENCE/traces.txt

say "step 4: retained evidence"
$VENV/bin/python - $EVIDENCE/agent-after-step2.json $EVIDENCE/agent-after-step3.json $EVIDENCE/traces.txt \
    $CHILD_MODEL $CHILD_EFFORT $U <<'EOF'
import json, sys
two, three = (json.load(open(path)) for path in sys.argv[1:3])
traces = [line.strip() for line in open(sys.argv[3]) if line.strip()]
model, effort, main = sys.argv[4:7]
ends = lambda record: [e.get('last_message') or '' for e in record['executions'] if e['state'] == 'ended']
observed = any(f'"model": "{model}"' in open(path).read() or f'"model":"{model}"' in open(path).read()
               for path in traces)
checks = [
    ('agent-after-step2.json runtime == codex', two['runtime'] == 'codex'),
    (f'agent-after-step2.json model == {model} (chosen at create)', two['model'] == model),
    (f'agent-after-step2.json reasoning_effort == {effort}', two['reasoning_effort'] == effort),
    ('agent-after-step2.json parent == null and creator.session == the Claude Main Session',
     two['parent'] is None and two['creator']['session'] == main),
    ('agent-after-step2.json executions answer PONG-1 then PONG-2 (round trip)',
     [m.strip() for m in ends(two)][:2] == ['PONG-1', 'PONG-2']),
    (f'a child trace.jsonl (traces.txt) shows the Codex service running model {model}', observed),
    ('agent-after-step3.json a later execution answers PONG-3 (child resumed)',
     any(m.startswith('PONG-3') for m in ends(three)[2:])),
    ('agent-after-step3.json sessions has one native Codex thread (same Session continued)',
     len(three['sessions']) == 1),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('ends:', json.dumps([(e['outcome'], e.get('last_message'), (e.get('error') or {}).get('message'))
                           for e in three['executions'] if e['state'] == 'ended'], ensure_ascii=False))
EOF

say "follow-up commands (copy as needed)"
print -r -- "cd $WORK && print -r -- 'Use the agents MCP tool once: {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"$AGENT\"}}; print the raw result.' | $CLAUDE -p --resume $U --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__agents"
print -r -- "less $EVIDENCE/step2.txt $EVIDENCE/step3.txt $EVIDENCE/agent-after-step3.json $EVIDENCE/host.log"
print -r -- "cat $EVIDENCE/traces.txt"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
