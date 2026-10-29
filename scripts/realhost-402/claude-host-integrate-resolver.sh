#!/bin/zsh
# Task 402 real-host check: Main on the GraphTraj Claude Code host runs task_integrate with
# resolve_conflict; the merge resolver needs one native permission that Main answers with reply.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/402-integrate-resolver-approval-deadlock/scripts/realhost-402/claude-host-integrate-resolver.sh
#
# Steps (each states which native dialog appears and what to choose):
#   0 preflight: versions, Claude flags, a one-line model/login answer (no dialog)
#   1 scratch project: git repository, graphtraj setup, roles, Task 1 (no dialog)
#   2 the writer role delivers article.md; the script decides its submission (no dialog)
#   3 a conflicting dev commit and a failed first integration retain the conflict (no dialog)
#   4 folder trust: one interactive Claude Code start, then /exit (one dialog)
#   5 Claude Main (print mode) calls task_integrate with resolve_conflict, answers the
#     resolver's permission request with reply, decides its submission and integrates (no dialog)
#   6 the script checks the retained records and prints PASS/FAIL per criterion
#
# Not verified before hand-off: this script was written in the team's sandbox, which can
# run neither Claude Code nor this host. The flags (-p, --session-id, --mcp-config,
# --strict-mcp-config, --allowedTools, --output-format stream-json, --verbose) are checked
# in step 0. Step 2 dispatches the writer from this shell (CLI root, no host), so a
# permission request from the writer would have no parent to answer it: the writer uses
# permission_mode auto and the step stops after 15 minutes if it does not submit.
# No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/402-integrate-resolver-approval-deadlock
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=REPLACE_WITH_CODE_COMMIT
P=/Users/luoxiao/agents-402-realhost
PY=/Users/luoxiao/miniconda3/bin/python3.13
# Both Claude roles use this model; change it here if your login offers another.
MODEL=claude-sonnet-5-5
WORK=$P/project
DEV=$WORK/.graphtraj/.agent-worktrees/dev
EVIDENCE=$P/evidence
VENV=$P/venv
GT=$VENV/bin/graphtraj
RUNNER=$VENV/bin/agent-runner
VALIDATE=($VENV/bin/python -c "from pathlib import Path; text = Path('article.md').read_text(); assert 'WRITER LINE' in text and 'DEV LINE' in text and '<<<<<<<' not in text")

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "commit check"
[[ $COMMIT == REPLACE_WITH_CODE_COMMIT ]] && fail "set COMMIT in this script to the code commit under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-402' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-402' || fail "the Worktree has uncommitted code changes"

[[ -e $P ]] && fail "$P exists from an earlier run; move it away (for example: mv $P $P.old) and run again"
mkdir -p $WORK $EVIDENCE

say "venv (isolated; Conda, system Python and .venv-runtime are not modified)"
$PY -m venv --system-site-packages $VENV
$VENV/bin/pip install -q --no-index --no-deps --no-build-isolation -e $WT -e $WT/src/agent_swarm
if ! $VENV/bin/python -c 'import websockets' 2>/dev/null; then
  # One fixed source, read only: the Harness's persistent runtime venv (websockets 16.1.1 when written).
  SRC=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
  DIST=($SRC/websockets-*.dist-info(N/))
  [[ -d $SRC/websockets && ${#DIST} -eq 1 ]] \
    || fail "websockets is missing; install it into the venv yourself: $VENV/bin/pip install websockets==16.1.1"
  cp -R $SRC/websockets $DIST[1] $VENV/lib/python3.13/site-packages/
fi
$VENV/bin/python -c 'import graphtraj, agent_swarm, websockets; print("graphtraj", graphtraj.__file__); print("agent_swarm", agent_swarm.__file__)'

say "step 0: preflight (native dialog: none; nothing to type)"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
HELP=$($CLAUDE --help)
for flag in --print --session-id --mcp-config --strict-mcp-config --allowedTools --output-format --verbose; do
  print -r -- $HELP | grep -q -- $flag && print -r -- "claude --help lists $flag" || fail "claude --help does not list $flag"
done
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p) | tail -1

say "step 1: scratch project (native dialog: none)"
git -C $WORK init -q --initial-branch=main
print -r -- "# 402 scratch project" > $WORK/README.md
git -C $WORK add README.md && git -C $WORK commit -qm "Initial source"
(cd $WORK && print -r -- y | $GT setup) | tee $EVIDENCE/setup.txt
cat > $WORK/.graphtraj/roles.yml <<EOF
roles:
  writer:
    runtime: claude
    model: $MODEL
    claude: {permission_mode: auto}
  merge_resolver:
    runtime: claude
    model: $MODEL
    # File edits in its Worktree are accepted; its Bash git command asks its parent (Main).
    claude: {permission_mode: acceptEdits}
role_tree:
  writer: {}
  merge_resolver: {}
EOF
cat > $P/task.yml <<'EOF'
task_id: '1'
task_name: article
source: realhost-402
title: Article line
body: |
  Create article.md containing exactly the single line `WRITER LINE`, then commit it with
  one Bash command: git add article.md && git commit -m "Add writer line". Then submit
  the result with the GraphTraj tasks tool feature submit_result: commit = the new HEAD,
  result_refs = [article.md], completion = "Writer line committed". Do nothing else.
dependencies: []
schema_version: 2
parent_id: null
disposition: active
replaced_by: []
retirement_reason: null
EOF
(cd $WORK && $GT task register --task-file $P/task.yml)
print -r -- "Main validated readiness for the 402 real-host check." > $WORK/delivery-evidence.md
cat > $P/ready.yml <<'EOF'
task_id: '1'
status: ready
active_team_ordinal: null
worktree: null
branch: null
current_candidate: null
caused_by_event_ids: []
evidence_refs: [delivery-evidence.md]
EOF
(cd $WORK && $GT task update --state-file $P/ready.yml)

say "step 2: the writer delivers article.md (native dialog: none)"
print -r -- "tasks: [{task_id: '1', task_name: article, role: writer}]" > $P/batch.yml
(cd $WORK && $RUNNER --swarm-input $P/batch.yml) | tee $EVIDENCE/step2-swarm.yml
WRITER=$($VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["tasks"][0]["alias"])' $EVIDENCE/step2-swarm.yml)
print -r -- "writer: $WRITER"
for i in {1..180}; do
  (cd $WORK && $RUNNER reports $WRITER) > $EVIDENCE/step2-reports.yml
  $VENV/bin/python -c 'import sys, yaml; sys.exit(0 if (yaml.safe_load(open(sys.argv[1])) or {}).get("submissions") else 1)' \
    $EVIDENCE/step2-reports.yml && break
  sleep 5
done
$VENV/bin/python - $EVIDENCE/step2-reports.yml > $P/decide.args <<'EOF'
import sys, yaml
submissions = (yaml.safe_load(open(sys.argv[1])) or {}).get('submissions') or []
if not submissions:
    sys.exit('the writer submitted nothing within 15 minutes; see the writer Trace')
latest = submissions[-1]
print('--submission-id', latest['event_id'], '--commit', latest['candidate'])
for ref in latest['evidence_refs']:
    print('--evidence-ref', ref)
EOF
(cd $WORK && $RUNNER decide-result ${(z)"$(<$P/decide.args)"} --decision accepted --reason "Writer line committed") \
  | tee $EVIDENCE/step2-decision.yml

say "step 3: a conflicting dev commit; the first integration retains the conflict (native dialog: none)"
print -r -- "DEV LINE" > $DEV/article.md
git -C $DEV add article.md && git -C $DEV commit -qm "Conflicting dev line"
(cd $WORK && $GT task integrate --task-id 1 -- $VALIDATE) | tee $EVIDENCE/step3-integrate.yml \
  || print -r -- "(expected non-zero exit: the merge conflicts)"
grep -q 'status: integrating\|task-integration-failed\|status: escalated' $EVIDENCE/step3-integrate.yml \
  || print -r -- "note: check $EVIDENCE/step3-integrate.yml for the retained conflict"

say "step 4: folder trust (one dialog)"
print -r -- "Writing the GraphTraj Claude host configuration (no dialog)."
(cd $WORK && $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $WORK --claude $CLAUDE --write)
print -r -- "Claude Code now starts once in $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog (for example the"
print -r -- "project MCP server question): press Esc and tell Main its title; step 5 passes the"
print -r -- "server explicitly, so it does not need that approval."
(cd $WORK && $CLAUDE)

say "step 5: Claude Main integrates through the resolver (native dialog: none)"
print -r -- "Print mode; the agents and tasks tools are pre-allowed. The resolver's Bash permission"
print -r -- "request goes to Main, which answers it with reply; you do not see a dialog for it."
U=$(uuidgen | tr A-Z a-z)
print -r -- "Claude Main Session: $U"
VJSON=$($VENV/bin/python -c 'import json, sys; print(json.dumps(sys.argv[1:]))' $VALIDATE)
ASK5="Use only the MCP tools mcp__agents__tasks and mcp__agents__agents. Make these calls in order and
print each raw result text verbatim right after it returns:
1. tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"1\",\"validation_command\":$VJSON,\"resolve_conflict\":\"article.md conflicts: keep both lines, WRITER LINE first, then DEV LINE. Finish the merge with one Bash command: git add article.md && git commit --no-edit. Then submit_result with that commit, result_refs [article.md].\",\"role\":\"merge_resolver\"}}
2. agents: {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<resolution.alias from 1>\",\"timeout_seconds\":300}}
3. agents: {\"action\":\"execute\",\"feature\":\"requests\",\"arguments\":{\"agent\":\"<same alias>\"}}
4. For each request from 3: agents {\"action\":\"execute\",\"feature\":\"reply\",\"arguments\":{\"agent\":\"<same alias>\",\"request\":<that request document>,\"response\":{\"behavior\":\"allow\"}}}
   If 3 has no request, repeat 2 and 3 once more first.
5. Repeat 2 until the result shows the Agent idle; answer any further request as in 4.
6. tasks: {\"action\":\"execute\",\"feature\":\"session_reports\",\"arguments\":{\"alias\":\"<same alias>\"}}
7. tasks: {\"action\":\"execute\",\"feature\":\"decide_result\",\"arguments\":{\"submission_id\":\"<last submissions[].event_id>\",\"commit\":\"<its candidate>\",\"decision\":\"accepted\",\"reason\":\"Both lines kept\",\"evidence_refs\":<its evidence_refs>}}
8. tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"1\",\"validation_command\":$VJSON}}
Then print one line ALIAS=<alias> and stop."
(cd $WORK && print -r -- "$ASK5" | $CLAUDE -p --session-id $U --output-format stream-json --verbose \
   --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) \
  > $EVIDENCE/step5.jsonl || print -r -- "(claude exit $?; continuing to collect evidence)"
cp $WORK/.graphtraj/claude-host/host.log $EVIDENCE/host.log 2>/dev/null || true
cp $WORK/.graphtraj/state/tasks/1-article/task.yml $EVIDENCE/task.yml
cp -R $WORK/.graphtraj/state/worldline $EVIDENCE/worldline
git -C $DEV log --oneline -5 > $EVIDENCE/dev-log.txt
cp $DEV/article.md $EVIDENCE/dev-article.md 2>/dev/null || true

say "step 6: retained evidence"
CANDIDATE=$($VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["current_candidate"])' $EVIDENCE/task.yml)
git -C $DEV merge-base --is-ancestor $CANDIDATE dev && print -r -- yes > $EVIDENCE/candidate-in-dev.txt || print -r -- no > $EVIDENCE/candidate-in-dev.txt
$VENV/bin/python - $EVIDENCE <<'EOF'
import json, sys, yaml
from pathlib import Path
evidence = Path(sys.argv[1])
calls, results, order = {}, {}, []
for line in (evidence / 'step5.jsonl').read_text().splitlines():
    try:
        message = json.loads(line)
    except ValueError:
        continue
    for item in (message.get('message') or {}).get('content') or []:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'tool_use':
            feature = (item.get('input') or {}).get('feature')
            calls[item['id']] = feature
            order.append(('call', feature, item['id']))
        elif item.get('type') == 'tool_result':
            text = item.get('content')
            text = ''.join(part.get('text', '') for part in text) if isinstance(text, list) else str(text)
            results[item['tool_use_id']] = (bool(item.get('is_error')), text)
            order.append(('result', calls.get(item['tool_use_id']), item['tool_use_id']))
def first(kind, feature):
    return next((index for index, entry in enumerate(order) if entry[:2] == (kind, feature)), None)
integrate_returned = first('result', 'task_integrate')
reply_sent = first('call', 'reply')
dispatch = results.get(next((entry[2] for entry in order if entry[:2] == ('result', 'task_integrate')), None))
replies = [results[entry[2]] for entry in order if entry[:2] == ('result', 'reply') and entry[2] in results]
task = yaml.safe_load((evidence / 'task.yml').read_text())
article = (evidence / 'dev-article.md').read_text() if (evidence / 'dev-article.md').exists() else ''
checks = [
    ('step5.jsonl: the first task_integrate result (resolving-integration, launched) came back before the first reply call',
     integrate_returned is not None and reply_sent is not None and integrate_returned < reply_sent
     and dispatch is not None and 'resolving-integration' in dispatch[1] and 'launched' in dispatch[1]),
    ('step5.jsonl: a reply result came back without error', bool(replies) and not any(error for error, _ in replies)),
    ('task.yml: status == integrated', task.get('status') == 'integrated'),
    ('candidate-in-dev.txt == yes and dev-article.md keeps both lines without conflict markers',
     (evidence / 'candidate-in-dev.txt').read_text().strip() == 'yes'
     and 'WRITER LINE' in article and 'DEV LINE' in article and '<<<<<<<' not in article),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('tool order:', json.dumps([entry[:2] for entry in order]))
EOF

say "follow-up commands (copy as needed)"
ALIAS=$(grep -o 'ALIAS=[^"\\ ]*' $EVIDENCE/step5.jsonl | tail -1 | cut -d= -f2 || true)
print -r -- "cd $WORK && $RUNNER reports ${ALIAS:-<resolver alias>}"
print -r -- "cd $WORK && $GT task graph"
print -r -- "cd $WORK && print -r -- 'Use the agents MCP tool once: {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"${ALIAS:-<resolver alias>}\"}}; print the raw result.' | $CLAUDE -p --resume $U --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__agents"
print -r -- "less $EVIDENCE/step5.jsonl $EVIDENCE/host.log $EVIDENCE/dev-log.txt"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
