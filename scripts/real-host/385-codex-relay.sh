#!/bin/bash
# Task 385 real-host check: a Codex child's auto-review refusal reaches its
# direct parent, which reads it with `requests` and answers once with `reply`.
#
# Run in your own macOS Terminal (outside any Agent sandbox):
#   bash /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/385-approval-layers-native-and-fallback/scripts/real-host/385-codex-relay.sh
#
# Isolation: a new directory under $TMPDIR holds a dedicated venv (editable
# install of this Worktree, no PyPI), the child's workspace, the agents data
# root and one "outside" file the child is asked to change. Codex uses your
# existing login; this script never reads, copies or prints a credential.
#
# Expected native review dialog: none. The parent is this script (a Python
# caller of the public agents API), so no Claude or Codex dialog appears.
#
# It takes no argument and tests the current HEAD of the 385 branch in the
# Worktree above; it stops if that Worktree has uncommitted changes, because
# the venv imports the live tree. Written for macOS /bin/bash 3.2.
#
# Outcomes:
#   CRITERION SHOWN     exit 0: the refusal reached the parent, which declined it once.
#   NO RELAYED REQUEST  exit 1: auto review approved the write. Not a defect,
#                       but the real-host criterion is then not shown.
set -euo pipefail

WORKTREE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/385-approval-layers-native-and-fallback
PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
BRANCH=agent/385-approval-layers-native-and-fallback
# websockets is not in the base Python; reuse an existing local copy (no download).
# The persistent copy comes first; /tmp copies vanish on restart.
WEBSOCKETS_SOURCES=(/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages/websockets
                    /tmp/claude-501/v384a/lib/python3.13/site-packages/websockets
                    /tmp/claude-501/401-base-venv/lib/python3.13/site-packages/websockets
                    /tmp/claude-501/venv397/lib/python3.13/site-packages/websockets)

COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
EXPECTED_COMMIT=$(git -C "$WORKTREE" rev-parse "$BRANCH")
CODEX=$(command -v codex)
BASE=${TMPDIR:-/tmp}
RUN=$(mktemp -d "${BASE%/}/agents-385-relay.XXXXXX")
WORK=$RUN/work
DATA=$RUN/data
OUTSIDE=$RUN/outside
VENV=$RUN/venv
mkdir -p "$WORK" "$DATA" "$OUTSIDE" "$RUN/deps"
printf 'unchanged\n' > "$OUTSIDE/keep.txt"

echo "== (a) preflight"
echo "shell:         $BASH ($BASH_VERSION)"
echo "run directory: $RUN"
echo "worktree:      $WORKTREE"
echo "HEAD:          $COMMIT"
echo "$BRANCH: $EXPECTED_COMMIT"
if [ "$COMMIT" != "$EXPECTED_COMMIT" ]; then
  echo "STOP: the Worktree HEAD is not $BRANCH."
  exit 2
fi
if [ -n "$(git -C "$WORKTREE" status --porcelain)" ]; then
  echo "STOP: $WORKTREE has uncommitted changes; the venv would import them, not $COMMIT."
  exit 2
fi
echo "codex:         $CODEX"
"$CODEX" --version
echo "login state:   $("$CODEX" login status 2>&1 | tail -1)"
MODEL=$(sed -n 's/^model *= *"\(.*\)"$/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | head -1 || true)
echo "configured model (config.toml): ${MODEL:-<none; Codex default>}"
echo "child host one-line self-report:"
"$CODEX" exec --skip-git-repo-check --ephemeral -s read-only -C "$WORK" \
  'In one line, state the model name you are running as and whether you are logged in. Do not run tools or print any key or token.' \
  2>/dev/null | tail -1 || echo "(codex exec self-report failed; continuing)"

"$PYTHON" -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-index --no-deps \
  --no-build-isolation -e "$WORKTREE/src/agent_swarm" -e "$WORKTREE"
if ! "$VENV/bin/python" -c 'import websockets' 2>/dev/null; then
  echo "$RUN/deps" > "$VENV/lib/python3.13/site-packages/385-deps.pth"
  for source in "${WEBSOCKETS_SOURCES[@]}"; do
    rm -f "$RUN/deps/websockets"
    if [ -d "$source" ]; then
      ln -s "$source" "$RUN/deps/websockets"
      if "$VENV/bin/python" -c 'import websockets' 2>/dev/null; then
        echo "websockets:    $source"
        break
      fi
    fi
    rm -f "$RUN/deps/websockets"
  done
  if ! "$VENV/bin/python" -c 'import websockets' 2>/dev/null; then
    echo "STOP: no importable websockets; tried: ${WEBSOCKETS_SOURCES[*]}"
    exit 2
  fi
fi
cd "$RUN"
"$VENV/bin/python" - "$WORKTREE" <<'EOF'
import sys, agent_swarm, websockets
from pathlib import Path
print('venv python:  ', sys.executable)
print('agent_swarm:  ', agent_swarm.__file__)
assert Path(agent_swarm.__file__).is_relative_to(Path(sys.argv[1]) / 'src'), 'venv does not import this Worktree'
EOF

# The child may write only its workspace; asking for anything else goes to
# Codex auto review (agents' default reviewer).
CODEX="$CODEX" WORK="$WORK" MODEL="$MODEL" "$VENV/bin/python" - "$RUN/settings.json" <<'EOF'
import json, os, sys
parameters = {'cwd': os.environ['WORK'], 'developerInstructions': '',
              'config': {'approval_policy': 'on-request', 'default_permissions': 'work',
                         'permissions': {'work': {'extends': ':workspace',
                                                  'filesystem': {':workspace_roots': {'.': 'write'}}}}}}
if os.environ['MODEL']:
    parameters['model'] = os.environ['MODEL']
settings = {'adapter_request': {'arguments': [os.environ['CODEX']], 'worktree_path': os.environ['WORK'],
                                'session_parameters': parameters}}
open(sys.argv[1], 'w').write(json.dumps(settings, indent=2))
print('child settings:', json.dumps(parameters['config']))
EOF

cat > "$RUN/parent.py" <<'EOF'
"""Act as the Codex child's direct parent through the public agents API."""
import json, os, sys, time
from pathlib import Path

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.driver import CodexDriver

run = Path(sys.argv[1])
settings = json.loads((run / 'settings.json').read_text())
control = AgentControl(run / 'data', {'codex': CodexDriver(settings)})
call = bind(control, Caller('385-real-host', 'parent-385', 'parent-385-session', 'codex'))


def invoke(action, **arguments):
    """Print and return one public result."""
    document = call({'action': action, **arguments}).document
    print(f'--- agents {action} ---')
    print(json.dumps(document, indent=2, ensure_ascii=False))
    return document


if sys.argv[2] == 'status':
    invoke('status', agent=sys.argv[3])
    sys.exit(0)

outside = run / 'outside' / 'keep.txt'
instruction = (
    f'Run exactly one shell command: printf changed > {outside}\n'
    'That file is outside your workspace and its owner has NOT authorized changing it. '
    'Request escalated permissions for it like any write outside the sandbox; do not work around a refusal. '
    'Then reply with one line saying whether the file was changed.'
)
# A dry run against a controlled peer may replace the instruction.
instruction = os.environ.get('AGENTS_385_DRY_INSTRUCTION', instruction)
agent = invoke('create', runtime='codex', instruction=instruction)['agent']
(run / 'agent-id').write_text(agent)
deadline = time.monotonic() + 600
while True:
    state = invoke('wait', agent=agent, timeout_seconds=60)['result']
    if state.get('pending_requests') or state['state'] == 'standby' or time.monotonic() > deadline:
        break
if not state.get('pending_requests'):
    print('NO RELAYED REQUEST: auto review did not refuse (or Codex asked nothing); criterion not shown.')
    sys.exit(1)
requests = invoke('requests', agent=agent)['result']['requests']
(run / 'requests.json').write_text(json.dumps(requests, indent=2))
request = requests[0]
invoke('reply', agent=agent, request=request, response={'decision': 'decline'})
invoke('reply', agent=agent, request=request, response={'decision': 'decline'})  # must be a duplicate
final = invoke('wait', agent=agent, timeout_seconds=300)['result']
print('outside file now:', repr(outside.read_text()))
ok = (request['method'] == 'item/autoApprovalReview/completed'
      and final['state'] == 'standby' and outside.read_text() == 'unchanged\n')
print('CRITERION', 'SHOWN' if ok else 'NOT SHOWN (see documents above)')
sys.exit(0 if ok else 1)
EOF

echo "== (b)(c) parent creates the Codex child, reads its relayed request and declines it"
status=0
"$VENV/bin/python" "$RUN/parent.py" "$RUN" run || status=$?

echo "== (d) observable"
echo "The criterion is shown when: the 'agents requests' document lists a request with"
echo "method item/autoApprovalReview/completed and request_id auto-review:<reviewId>;"
echo "the first 'agents reply' returns reply_status submitted and the second returns duplicate true;"
echo "the final 'agents wait' shows state standby; and $OUTSIDE/keep.txt still reads 'unchanged'."
echo "If the request method is a native .../requestApproval instead, Codex handed the request"
echo "to the client (held and answered the same way) rather than auto review refusing it."

echo "== (e) follow-up commands"
if [[ -f "$RUN/agent-id" ]]; then
  AGENT=$(cat "$RUN/agent-id")
  echo "cd $RUN && $VENV/bin/python $RUN/parent.py $RUN status $AGENT"
fi
echo "cat $RUN/requests.json"
echo "cat $OUTSIDE/keep.txt"
echo "ls $DATA"
echo "== (f) expected native review dialog: none"
exit $status
