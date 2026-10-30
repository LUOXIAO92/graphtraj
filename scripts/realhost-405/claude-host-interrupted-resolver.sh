#!/bin/zsh
# Task 405 real-host check: Main on the GraphTraj Claude Code host interrupts a merge resolver
# that has a Session, the integration escalates, and the merge still completes through the public
# operations: step 1 resumes the same Session, step 2 dispatches a new resolver.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/405-interrupted-resolver-recovery/scripts/realhost-405/claude-host-interrupted-resolver.sh
#
# Steps (each states which native dialog appears and what to choose):
#   0 preflight: shell, versions, Claude flags, a one-line model/login answer, scratch project,
#     probe Tasks ready, folder trust (one dialog: the folder trust question), host configuration
#   1 resume: conflict, resolver launched and interrupted, task_integrate gives escalated,
#     approved_recovery with restore_active resumes the same Session, integrated (no dialog)
#   2 re-dispatch: the same up to escalated, then task_integrate with resolve_conflict and another
#     role launches a new Session, integrated (no dialog)
#
# Not verified before hand-off: this script was written in the team's sandbox, which can run
# neither Claude Code nor this host. Each operation and its argument names were checked against
# this commit's schema (tasks: task_integrate, approved_recovery, session_reports, decide_result;
# agents: wait, requests, reply, interrupt, status, send). Each Claude Main is a print-mode
# Session in this script, so its resolver's permission requests and notices are read and answered
# by that Main through requests and reply; nothing routes to another Main.
# No credential is read, copied or printed.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/405-interrupted-resolver-recovery
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=28caab3e16f36a763988bf9fc32ed9806d4e21d7
P=/Users/luoxiao/agents-405-realhost
PY=/Users/luoxiao/miniconda3/bin/python3.13
# The Claude adapter accepts only claude-opus-5-5 unless the role names an explicit model connection.
MODEL=claude-opus-5-5
WORK=$P/project
DEV=$WORK/.graphtraj/.agent-worktrees/dev
EVIDENCE=$P/evidence
VENV=$P/venv
GT=$VENV/bin/graphtraj
RUNNER=$VENV/bin/agent-runner
VALIDATOR=$P/validate.py

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "commit check"
[[ $COMMIT == REPLACE_WITH_CODE_COMMIT ]] && fail "set COMMIT in this script to the code commit under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-405' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-405' || fail "the Worktree has uncommitted code changes"

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

say "step 0: preflight (native dialog: only the folder trust question at the end of this step)"
[[ -n ${ZSH_VERSION:-} ]] || fail "start this script with zsh, as shown at its top"
print -r -- "shell: zsh $ZSH_VERSION"
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
HELP=$($CLAUDE --help)
for flag in --print --session-id --mcp-config --strict-mcp-config --allowedTools --output-format --verbose; do
  print -r -- $HELP | grep -q -- $flag && print -r -- "claude --help lists $flag" || fail "claude --help does not list $flag"
done
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p) | tail -1

git -C $WORK init -q --initial-branch=main
print -r -- "# 405 scratch project" > $WORK/README.md
git -C $WORK add README.md && git -C $WORK commit -qm "Initial source"
(cd $WORK && print -r -- y | $GT setup) | tee $EVIDENCE/setup.txt
[[ -d $DEV ]] || fail "setup did not create the dev Worktree at $DEV; compare $EVIDENCE/setup.txt with this script's layout"
cat > $WORK/.graphtraj/roles.yml <<EOF
roles:
  writer:
    runtime: claude
    model: $MODEL
    claude: {permission_mode: auto}
  merge_resolver:
    runtime: claude
    model: $MODEL
    # Its Edit and its Bash git command each ask its parent (Main), which answers with reply.
    claude: {permission_mode: default}
  merge_resolver_b:
    runtime: claude
    model: $MODEL
    claude: {permission_mode: default}
role_tree:
  writer: {}
  merge_resolver: {}
  merge_resolver_b: {}
EOF
cat > $VALIDATOR <<'EOF'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
assert 'WRITER LINE' in text and 'DEV LINE' in text and '<<<<<<<' not in text
EOF
print -r -- "Main validated readiness for the 405 real-host check." > $WORK/delivery-evidence.md
for N in 1 2; do
  cat > $P/task$N.yml <<EOF
task_id: '$N'
task_name: article$N
source: realhost-405
title: Article $N line
body: |
  Create article$N.md containing exactly the single line \`WRITER LINE\`, then commit it with
  one Bash command: git add article$N.md && git commit -m "Add writer line". Then submit
  the result with the GraphTraj tasks tool feature submit_result: commit = the new HEAD,
  result_refs = [article$N.md], completion = "Writer line committed". Do nothing else.
dependencies: []
schema_version: 2
parent_id: null
disposition: active
replaced_by: []
retirement_reason: null
EOF
  (cd $WORK && $GT task register --task-file $P/task$N.yml)
  cat > $P/ready$N.yml <<EOF
task_id: '$N'
status: ready
active_team_ordinal: null
worktree: null
branch: null
current_candidate: null
caused_by_event_ids: []
evidence_refs: [delivery-evidence.md]
EOF
  (cd $WORK && $GT task update --state-file $P/ready$N.yml)
  STATUS=$($VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["status"])' \
    $WORK/.graphtraj/state/tasks/$N-article$N/task.yml)
  print -r -- "Probe Task $N status: $STATUS"
  [[ $STATUS == ready ]] || fail "Task $N is $STATUS, not ready; see $WORK/.graphtraj/state/tasks/$N-article$N/task.yml"
done

# Trust comes first: no .mcp.json or .claude/ exists yet, so only the trust dialog can appear.
print -r -- "Claude Code now starts once in $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
(cd $WORK && $CLAUDE)
print -r -- "Writing the GraphTraj Claude host configuration (no dialog)."
(cd $WORK && $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $WORK --claude $CLAUDE --write)

# Deliver and accept Task N's writer result, then retain a conflict with a dev commit.
prepare_conflict() {
  local N=$1 STEP=step$1
  print -r -- "tasks: [{task_id: '$N', task_name: article$N, role: writer}]" > $P/batch$N.yml
  (cd $WORK && $RUNNER --swarm-input $P/batch$N.yml) | tee $EVIDENCE/$STEP-swarm.yml
  local WRITER=$($VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["tasks"][0]["alias"])' $EVIDENCE/$STEP-swarm.yml)
  print -r -- "writer: $WRITER"
  local i
  for i in {1..180}; do
    (cd $WORK && $RUNNER reports $WRITER) > $EVIDENCE/$STEP-reports.yml
    $VENV/bin/python -c 'import sys, yaml; sys.exit(0 if (yaml.safe_load(open(sys.argv[1])) or {}).get("submissions") else 1)' \
      $EVIDENCE/$STEP-reports.yml && break
    sleep 5
  done
  # decide-result needs at least one evidence ref; the writer's submission may carry none.
  # The decision file (untracked, Harness-relative) records the script's own check.
  $VENV/bin/python - $EVIDENCE/$STEP-reports.yml $EVIDENCE/$STEP-swarm.yml $WORK/writer-decision$N.md article$N.md > $P/decide$N.args <<'EOF'
import subprocess, sys, yaml
from pathlib import Path
reports, swarm, decision, article = sys.argv[1:5]
submissions = (yaml.safe_load(open(reports)) or {}).get('submissions') or []
if not submissions:
    sys.exit('the writer submitted nothing within 15 minutes; see the writer Trace')
latest = submissions[-1]
worktree = yaml.safe_load(open(swarm))['tasks'][0]['worktree_path']
shown = subprocess.run(['git', '-C', worktree, 'show', f"{latest['candidate']}:{article}"], capture_output=True, text=True)
exact = shown.returncode == 0 and shown.stdout.strip() == 'WRITER LINE'
open(decision, 'w').write(f"Submission {latest['event_id']} candidate {latest['candidate']}: "
                          f"{article} is exactly 'WRITER LINE': {'yes' if exact else 'no'}\n")
if not exact:
    sys.exit(f'{article} at {latest["candidate"]} is not exactly WRITER LINE; see {decision}')
print('--submission-id', latest['event_id'], '--commit', latest['candidate'], '--evidence-ref', Path(decision).name)
for ref in latest.get('evidence_refs') or []:
    print('--evidence-ref', ref)
EOF
  (cd $WORK && $RUNNER decide-result ${(z)"$(<$P/decide$N.args)"} --decision accepted --reason "Writer line committed") \
    | tee $EVIDENCE/$STEP-decision.yml
  print -r -- "DEV LINE" > $DEV/article$N.md
  git -C $DEV add article$N.md && git -C $DEV commit -qm "Conflicting dev line $N"
  (cd $WORK && $GT task integrate --task-id $N -- $VENV/bin/python $VALIDATOR article$N.md) | tee $EVIDENCE/$STEP-first-integrate.yml \
    || print -r -- "(expected non-zero exit: the merge conflicts)"
  print -r -- "Main decision evidence for the 405 real-host resolver check" > $WORK/resolver-decision$N.md
}

# Run one Claude Main prompt and retain its stream, then the records the check reads.
run_main() {
  local N=$1 ASK=$2 U=$(uuidgen | tr A-Z a-z)
  print -r -- "Claude Main Session: $U"
  print -r -- $U > $EVIDENCE/step$N-main-session.txt
  (cd $WORK && print -r -- "$ASK" | $CLAUDE -p --session-id $U --output-format stream-json --verbose \
     --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) \
    > $EVIDENCE/step$N.jsonl || print -r -- "(claude exit $?; continuing to collect evidence)"
  cp $WORK/.graphtraj/claude-host/host.log $EVIDENCE/step$N-host.log 2>/dev/null || true
  cp $WORK/.graphtraj/state/tasks/$N-article$N/task.yml $EVIDENCE/step$N-task.yml
  rm -rf $EVIDENCE/worldline
  cp -R $WORK/.graphtraj/state/worldline $EVIDENCE/worldline
  git -C $DEV log --oneline -8 > $EVIDENCE/step$N-dev-log.txt
  cp $DEV/article$N.md $EVIDENCE/step$N-dev-article.md 2>/dev/null || true
  local CANDIDATE=$($VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["current_candidate"])' $EVIDENCE/step$N-task.yml)
  git -C $DEV merge-base --is-ancestor $CANDIDATE dev && print -r -- yes > $EVIDENCE/step$N-candidate-in-dev.txt \
    || print -r -- no > $EVIDENCE/step$N-candidate-in-dev.txt
}

common_start() {
  local N=$1 VJSON=$2
  print -r -- "Use only the MCP tools mcp__agents__tasks and mcp__agents__agents. Make these calls in order and
print each raw result text verbatim right after it returns. A refused call named below is expected; carry on.
1. tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"$N\",\"validation_command\":$VJSON,\"resolve_conflict\":\"article$N.md conflicts: keep both lines, WRITER LINE first, then DEV LINE. Finish the merge with one Bash command: git add article$N.md && git commit --no-edit. Then submit_result with that commit, result_refs [article$N.md].\",\"role\":\"merge_resolver\"}}
2. agents: {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<resolution.alias from 1>\",\"timeout_seconds\":120}}
3. agents: {\"action\":\"execute\",\"feature\":\"requests\",\"arguments\":{\"agent\":\"<same alias>\"}}
   Repeat 2 and 3 until 3 lists a pending request, at most 5 times. Do NOT answer that request.
4. agents: {\"action\":\"execute\",\"feature\":\"interrupt\",\"arguments\":{\"agent\":\"<same alias>\"}}
5. agents: {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"<same alias>\"}} Repeat after 10 seconds until it shows the Agent idle, at most 6 times.
6. tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"$N\",\"validation_command\":$VJSON}} Its result must show status escalated; keep its event_id as ESCALATED."
}

common_finish() {
  local N=$1 VJSON=$2 ALIAS_NAME=$3 FIRST=$4 NEXT=$(( $4 + 1 ))
  print -r -- "$FIRST. Loop: agents wait on $ALIAS_NAME with timeout_seconds 120, then agents requests on it; answer each pending
   request once with agents {\"action\":\"execute\",\"feature\":\"reply\",\"arguments\":{\"agent\":\"<$ALIAS_NAME>\",\"request\":<that request document>,\"response\":{\"behavior\":\"allow\"}}}.
   Stop looping when wait shows the Agent idle and requests lists nothing pending.
$NEXT. tasks: {\"action\":\"execute\",\"feature\":\"session_reports\",\"arguments\":{\"alias\":\"<$ALIAS_NAME>\"}}
$(( NEXT + 1 )). tasks: {\"action\":\"execute\",\"feature\":\"decide_result\",\"arguments\":{\"submission_id\":\"<last submissions[].event_id>\",\"commit\":\"<its candidate>\",\"decision\":\"accepted\",\"reason\":\"Both lines kept\",\"evidence_refs\":<its evidence_refs plus \"resolver-decision$N.md\"; never an empty list>}}
$(( NEXT + 2 )). tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"$N\",\"validation_command\":$VJSON}}"
}

check_step() {
  # Prints PASS/FAIL per criterion and ready-to-paste commands; exits non-zero on any FAIL.
  $VENV/bin/python - $1 $EVIDENCE $WORK $RUNNER $GT $CLAUDE <<'EOF'
import json, sys, yaml
from pathlib import Path
step, evidence, work, runner, product, claude = sys.argv[1:7]
evidence, work = Path(evidence), Path(work)
results, order, calls = {}, [], {}
for line in (evidence / f'step{step}.jsonl').read_text().splitlines():
    try:
        message = json.loads(line)
    except ValueError:
        continue
    for item in (message.get('message') or {}).get('content') or []:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'tool_use':
            calls[item['id']] = (item.get('input') or {}).get('feature')
        elif item.get('type') == 'tool_result':
            text = item.get('content')
            text = ''.join(part.get('text', '') for part in text) if isinstance(text, list) else str(text)
            results[item['tool_use_id']] = (bool(item.get('is_error')), text)
            order.append((calls.get(item['tool_use_id']), bool(item.get('is_error')), text))
def parsed(text):
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
integrates = [parsed(text) | {'failed': error} for feature, error, text in order if feature == 'task_integrate']
recoveries = [(error, text) for feature, error, text in order if feature == 'approved_recovery']
sends = [(error, text) for feature, error, text in order if feature == 'send']
replies = [error for feature, error, _ in order if feature == 'reply']
events = [json.loads(line) for path in sorted((evidence / 'worldline').glob('*.jsonl'))
          for line in path.read_text().splitlines() if line.strip()]
own = [event for event in events if event.get('task_id') == step]
integration = [event['event'] for event in own if event['event'].startswith('task-integration-')]
first = (integrates[0].get('resolution') or {}) if integrates else {}
old = first.get('alias')
sessions = work / '.graphtraj/runner/sessions'
def session_of(alias):
    path = sessions / str(alias) / 'mapping.yml'
    return yaml.safe_load(path.read_text())['session'] if path.is_file() else None
task = yaml.safe_load((evidence / f'step{step}-task.yml').read_text())
article_file = evidence / f'step{step}-dev-article.md'
article = article_file.read_text() if article_file.exists() else ''
applied = [event for event in own if event['event'] == 'recovery-applied']
resumed = [event for event in own if event['event'] == 'recovery-resumed']
started = [event for event in own if event['event'] == 'task-integration-conflict-started']
checks = [
    ('step jsonl: the first task_integrate launched a resolver and returned resolving-integration',
     first.get('launch_status') == 'launched' and integrates[0].get('status') == 'resolving-integration'),
    ('step jsonl: the task_integrate after the interrupt returned status escalated',
     len(integrates) > 1 and integrates[1].get('status') == 'escalated'),
    ('worldline: an escalated event follows the dispatch', 'task-integration-escalated' in integration),
    ('step jsonl: a reply result came back without error', bool(replies) and not any(replies)),
    ('worldline: the final task-integration event is task-integration-conflict-resolved',
     bool(integration) and integration[-1] == 'task-integration-conflict-resolved'),
    ('task.yml: status == integrated', task.get('status') == 'integrated'),
    ('candidate-in-dev == yes and the dev article keeps both lines without conflict markers',
     (evidence / f'step{step}-candidate-in-dev.txt').read_text().strip() == 'yes'
     and 'WRITER LINE' in article and 'DEV LINE' in article and '<<<<<<<' not in article),
]
new = None
if step == '1':
    stop = sessions / str(old) / 'stop.yml'
    checks += [
        ('step jsonl: approved_recovery without restore_active was refused, naming restore_active',
         bool(recoveries) and recoveries[0][0] and 'restore_active' in recoveries[0][1]),
        ('worldline: exactly one recovery-applied, from the restore_active call', len(applied) == 1
         and applied[0]['proposal']['request'].get('restore_active') is True),
        ('worldline: recovery-resumed names the resolver and the same native Session as its launch',
         len(resumed) == 1 and resumed[0]['alias'] == old and resumed[0]['session'] == first.get('session') == session_of(old)),
        ('stop.yml of the resolver is retained with resumed true',
         stop.is_file() and yaml.safe_load(stop.read_text()).get('resumed') is True),
    ]
    print('native Session at launch:', first.get('session'), '; at resumption:', resumed[0]['session'] if resumed else None)
else:
    redispatch = (integrates[2].get('resolution') or {}) if len(integrates) > 2 else {}
    new = redispatch.get('alias')
    stop = sessions / str(old) / 'stop.yml'
    checks += [
        ('step jsonl: task_integrate with the other role launched a new resolver',
         redispatch.get('launch_status') == 'launched' and bool(new) and new != old),
        ('worldline: the latest conflict-started records superseded_resolvers == [the old resolver] and the new role',
         bool(started) and started[-1].get('superseded_resolvers') == [old]
         and started[-1].get('role_reference') == 'merge_resolver_b'),
        ('sessions: the new resolver has a different native Session; the old one keeps its own',
         bool(session_of(new)) and session_of(new) != session_of(old) == first.get('session')),
        ('stop.yml of the old resolver is retained', stop.is_file()),
        ('step jsonl: send to the old resolver was refused with active conflict assignment',
         bool(sends) and sends[-1][0] and 'active conflict assignment' in sends[-1][1]),
    ]
    print('native Session of the old resolver:', session_of(old), '; of the new resolver:', session_of(new))
failed = False
for name, ok in checks:
    failed = failed or not ok
    print(('PASS ' if ok else 'FAIL ') + name)
print('tool order:', json.dumps([[feature, error] for feature, error, _ in order]))
print(f'Task {step} integration events:', json.dumps(integration))
print('ready-to-paste follow-ups:')
for alias in filter(None, (old, new)):
    print(f'  cd {work} && {runner} reports {alias}')
print(f'  cd {work} && {product} task graph')
print(f"  less {evidence / f'step{step}.jsonl'} {evidence / f'step{step}-host.log'} {evidence / f'step{step}-dev-log.txt'}")
if not old:
    print('  (no resolver alias was launched; read the jsonl above first)')
sys.exit(1 if failed else 0)
EOF
}

say "step 1: resume the same Session (native dialog: none; nothing to choose)"
print -r -- "Print mode; the agents and tasks tools are pre-allowed and Main answers the resolver's"
print -r -- "permission requests with reply. A dialog here is unexpected: press Esc (dialogs time out"
print -r -- "after 300 s) and tell Main its title."
prepare_conflict 1
VJSON1=$($VENV/bin/python -c 'import json, sys; print(json.dumps(sys.argv[1:]))' $VENV/bin/python $VALIDATOR article1.md)
ASK1="$(common_start 1 $VJSON1)
7. tasks: {\"action\":\"execute\",\"feature\":\"approved_recovery\",\"arguments\":{\"alias\":\"<same alias>\",\"reason\":\"The resolver was interrupted before committing\",\"instruction\":\"Finish the conflict resolution you were given\",\"allowed_scope\":\"The retained conflict in article1.md\",\"forbidden_scope\":\"Any other file or Task\",\"caused_by_event_ids\":[\"<ESCALATED>\"]}} This one must be refused and name restore_active.
8. tasks: the same approved_recovery call with \"restore_active\":true added. Its recovery_status must be resumed.
$(common_finish 1 $VJSON1 'the same alias' 9)
Then print one line ALIAS=<alias> and stop."
run_main 1 "$ASK1"
if ! check_step 1 | tee $EVIDENCE/step1-check.txt; then
  fail "step 1 did not pass; Task 2 cannot integrate while Task 1 is unfinished. Send $EVIDENCE to Main."
fi

say "step 2: dispatch a new resolver (native dialog: none; nothing to choose)"
print -r -- "Print mode, as step 1. A dialog here is unexpected: press Esc and tell Main its title."
prepare_conflict 2
VJSON2=$($VENV/bin/python -c 'import json, sys; print(json.dumps(sys.argv[1:]))' $VENV/bin/python $VALIDATOR article2.md)
ASK2="$(common_start 2 $VJSON2)
7. tasks: {\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"2\",\"validation_command\":$VJSON2,\"resolve_conflict\":\"article2.md still conflicts after the first resolver stopped: keep both lines, WRITER LINE first, then DEV LINE. Finish the merge with one Bash command: git add article2.md && git commit --no-edit. Then submit_result with that commit, result_refs [article2.md].\",\"role\":\"merge_resolver_b\"}} Keep its resolution.alias as NEW.
8. agents: {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<the alias from call 1>\",\"message\":\"Continue\"}} This one must be refused and name active conflict assignment.
$(common_finish 2 $VJSON2 'NEW' 9)
Then print one line ALIAS=<NEW> and stop."
run_main 2 "$ASK2"
check_step 2 | tee $EVIDENCE/step2-check.txt || print -r -- "step 2 has FAIL lines above"

say "done"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
