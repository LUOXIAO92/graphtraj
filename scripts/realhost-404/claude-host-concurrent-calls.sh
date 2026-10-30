#!/bin/zsh
# Task 404 real-host check: on the user's Claude Code, one long agents/tasks call is in
# progress and another call finishes first; a cancellation stops the long call's work.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/404-claude-host-concurrent-calls/scripts/realhost-404/claude-host-concurrent-calls.sh
#
# The long call is task_integrate with a sleeping validation command. It needs no dialog and
# no Agent, and its duration does not depend on a model. A failing validation keeps the Task
# integrating, so the same Task serves steps 4 to 6; step 7 integrates it.
#
#   0 preflight: zsh, versions, Claude flags, a one-line model/login answer (no dialog)
#   1 scratch project, Task 1, proved ready (no dialog)
#   2 the writer role delivers article.md; the script decides its submission (no dialog)
#   3 folder trust: one interactive Claude Code start, then /exit (ONE dialog);
#     then the host configuration, which copies the new mod (no dialog)
#   4 two calls asked for in one response: a 40 s task_integrate and task_graph (no dialog)
#   5 a 170 s task_integrate, past the client's 120 s foreground limit, then task_graph (no dialog)
#   6 cancellation: SIGINT to claude -p while a 300 s task_integrate runs (no dialog)
#   7 task_integrate with a passing validation reaches integrated (no dialog)
#   8 summary of every PASS/FAIL, follow-up commands
#
# Steps 4 and 5 report whether the client overlapped the calls. Whether this client sends two
# non-read-only MCP calls in parallel is unproven; a FAIL that says the host received the
# second call only after the first finished is a client observation. The tool annotations
# stay unchanged. Step 6 reports whether the client sent notifications/cancelled or only
# ended the host; a client that does neither there cannot trigger a cancel non-interactively.
#
# Not verified before hand-off: written in the team's sandbox, which can run neither Claude
# Code nor this host. No credential is read, copied or printed. Production .venv-runtime is
# only read for one fixed websockets copy, as in 402; nothing is installed into it.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/404-claude-host-concurrent-calls
# The code under test; later commits may change only this script's directory.
COMMIT=120f2734f1bb9e6e90074bb4033bc699dea58d94
P=/Users/luoxiao/agents-404-realhost
PY=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
WORK=$P/project
EVIDENCE=$P/evidence
VENV=$P/venv
GT=$VENV/bin/graphtraj
RUNNER=$VENV/bin/agent-runner
CHECK=$WT/scripts/realhost-404/check_host_log.py

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "step 0: preflight (native dialog: none; nothing to type)"
[[ -n ${ZSH_VERSION:-} ]] || fail "run this script with zsh, as shown at its top"
print -r -- "shell: zsh $ZSH_VERSION"
[[ $COMMIT == REPLACE_WITH_CODE_COMMIT ]] && fail "set COMMIT in this script to the code commit under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-404' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-404' || fail "the Worktree has uncommitted code changes"
[[ -e $P ]] && fail "$P exists from an earlier run; move it away (for example: mv $P $P.old) and run again"
mkdir -p $WORK $EVIDENCE

$PY -m venv --system-site-packages $VENV
$VENV/bin/pip install -q --no-index --no-deps --no-build-isolation -e $WT -e $WT/src/agent_swarm
if ! $VENV/bin/python -c 'import websockets' 2>/dev/null; then
  # One fixed source, read only: the Harness's persistent runtime venv.
  SRC=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
  DIST=($SRC/websockets-*.dist-info(N/))
  [[ -d $SRC/websockets && ${#DIST} -eq 1 ]] \
    || fail "websockets is missing; install it into the venv yourself: $VENV/bin/pip install websockets==16.1.1"
  cp -R $SRC/websockets $DIST[1] $VENV/lib/python3.13/site-packages/
fi
$VENV/bin/python -c 'import graphtraj, agent_swarm.calls, websockets; print("graphtraj", graphtraj.__file__); print("agent_swarm.calls", agent_swarm.calls.__file__)'

CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
HELP=$($CLAUDE --help)
for flag in --print --session-id --mcp-config --strict-mcp-config --allowedTools --output-format --verbose --model; do
  print -r -- $HELP | grep -q -- $flag && print -r -- "claude --help lists $flag" || fail "claude --help does not list $flag"
done
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p --model $MODEL) | tail -1

say "step 1: scratch project (native dialog: none)"
git -C $WORK init -q --initial-branch=main
print -r -- "# 404 scratch project" > $WORK/README.md
git -C $WORK add README.md && git -C $WORK commit -qm "Initial source"
(cd $WORK && print -r -- y | $GT setup) | tee $EVIDENCE/setup.txt
# Paths come from the configuration this installation just wrote, not from assumptions.
eval "$($VENV/bin/python - $WORK <<'EOF'
import shlex, sys
from pathlib import Path
from graphtraj.configuration.project_configuration import load_project_configuration
loaded = load_project_configuration(Path(sys.argv[1]))
print(f'STATE={shlex.quote(str(loaded.state))}\nDEV={shlex.quote(str(loaded.integration_worktree))}')
EOF
)"
print -r -- "state: $STATE"; print -r -- "dev: $DEV"
HOSTDIR=$WORK/.graphtraj/claude-host
LOG=$HOSTDIR/host.log
CHANNEL=$HOSTDIR/live/channel.json
cat > $WORK/.graphtraj/roles.yml <<EOF
roles:
  writer:
    runtime: claude
    model: $MODEL
    claude: {permission_mode: auto}
role_tree:
  writer: {}
EOF
cat > $P/task.yml <<'EOF'
task_id: '1'
task_name: article
source: realhost-404
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
print -r -- "Main validated readiness for the 404 real-host check." > $WORK/delivery-evidence.md
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
task_status() { $VENV/bin/python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["status"])' $STATE/tasks/1-article/task.yml; }
print -r -- "Task 1 status: $(task_status)"
[[ $(task_status) == ready ]] || fail "Task 1 is not ready; see $STATE/tasks/1-article/task.yml"

say "step 2: the writer delivers article.md (native dialog: none; about 2 minutes)"
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
$VENV/bin/python - $EVIDENCE/step2-reports.yml $WORK/writer-decision.md > $P/decide.args <<'EOF'
import sys, yaml
reports, decision = sys.argv[1:3]
submissions = (yaml.safe_load(open(reports)) or {}).get('submissions') or []
if not submissions:
    sys.exit('the writer submitted nothing within 15 minutes; see the writer Trace')
latest = submissions[-1]
open(decision, 'w').write(f"Submission {latest['event_id']} candidate {latest['candidate']} taken as the 404 probe.\n")
print('--submission-id', latest['event_id'], '--commit', latest['candidate'], '--evidence-ref', 'writer-decision.md')
EOF
(cd $WORK && $RUNNER decide-result ${(z)"$(<$P/decide.args)"} --decision accepted --reason "Writer line committed") \
  | tee $EVIDENCE/step2-decision.yml
print -r -- "Task 1 status: $(task_status)"

say "step 3: folder trust (ONE dialog), then the host configuration (no dialog)"
print -r -- "Claude Code now starts once in $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
(cd $WORK && $CLAUDE)
print -r -- "Writing the GraphTraj Claude host configuration (no dialog)."
(cd $WORK && $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $WORK --claude $CLAUDE --write)
touch $LOG

# A validation that writes its pid, sleeps, then exits with the given code.
cat > $P/sleeper.py <<'EOF'
import os, sys, time
open(sys.argv[1], 'w').write(str(os.getpid()))
time.sleep(float(sys.argv[2]))
raise SystemExit(int(sys.argv[3]))
EOF
sleeper() { print -r -- "[\"$VENV/bin/python\",\"$P/sleeper.py\",\"$1\",\"$2\",\"$3\"]"; }
integrate_call() { print -r -- "{\"action\":\"execute\",\"feature\":\"task_integrate\",\"arguments\":{\"task_id\":\"1\",\"validation_command\":$1}}"; }
GRAPH_CALL='{"action":"execute","feature":"task_graph","arguments":{}}'
run_main() {  # prompt, stream-json output file
  (cd $WORK && print -r -- "$1" | $CLAUDE -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) \
     --output-format stream-json --verbose --mcp-config $WORK/.mcp.json --strict-mcp-config \
     --allowedTools mcp__agents__tasks,mcp__agents__agents) > $2 || print -r -- "(claude exit $?; continuing to collect evidence)"
}
channel_check() {  # What this run left behind; a stale file would refuse the next host.
  if [[ -e $CHANNEL ]]; then
    print -r -- "FAIL $1: $CHANNEL is still there after Claude Code exited (separate Task on stale channels);"
    print -r -- "     its content: $(<$CHANNEL). Removed so the next step's host can start."
    rm -f $CHANNEL
  else
    print -r -- "PASS $1: no channel file left behind"
  fi
}
offset() { wc -c < $LOG | tr -d ' '; }

say "step 4: two calls asked for in one response (native dialog: none; about 1 minute)"
print -r -- "Observable: host.log order. PASS if task_graph finishes between task_integrate's received and finished."
VJSON=$(sleeper $P/step4.pid 40 1)
START=$(offset)
run_main "Use only the MCP tool mcp__agents__tasks. In ONE single response, emit these two tool calls together as parallel tool calls, in this order, without waiting between them:
1. $(integrate_call $VJSON)
2. $GRAPH_CALL
The first takes about 40 seconds and reports a failed validation; that is expected. Print one line DONE after both results and stop." $EVIDENCE/step4.jsonl
$VENV/bin/python $CHECK $LOG $EVIDENCE/step4.jsonl --offset $START | tee $EVIDENCE/step4-result.txt
channel_check "step 4"

say "step 5: a call past the client's foreground limit (native dialog: none; about 4 minutes)"
print -r -- "Observable: as in step 4. A FAIL that says the host received task_graph afterwards is a client observation."
VJSON=$(sleeper $P/step5.pid 170 1)
START=$(offset)
run_main "Use only the MCP tool mcp__agents__tasks. Make this call:
1. $(integrate_call $VJSON)
It takes about 170 seconds and reports a failed validation; that is expected. As soon as you regain control, whether its result arrived or it was moved to the background, make this call:
2. $GRAPH_CALL
Do not end your turn until the result of call 1 is available; check for it if it runs in the background. Then print one line DONE and stop." $EVIDENCE/step5.jsonl
$VENV/bin/python $CHECK $LOG $EVIDENCE/step5.jsonl --offset $START | tee $EVIDENCE/step5-result.txt
channel_check "step 5"

say "step 6: cancellation by SIGINT to claude -p (native dialog: none; about 1 minute)"
print -r -- "Observable: host.log cancelled or finished lines, the validation process gone, the Task still integrating."
VJSON=$(sleeper $P/step6.pid 300 1)
START=$(offset)
(cd $WORK && print -r -- "Use only the MCP tool mcp__agents__tasks. Make this call once and wait for it: $(integrate_call $VJSON)" \
  | $CLAUDE -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) --output-format stream-json --verbose \
      --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) \
  > $EVIDENCE/step6.jsonl &
MAIN_PID=$!
for i in {1..120}; do [[ -s $P/step6.pid ]] && break; sleep 1; done
[[ -s $P/step6.pid ]] || print -r -- "FAIL step 6: the long validation never started; see $EVIDENCE/step6.jsonl"
VALIDATION=$(cat $P/step6.pid 2>/dev/null || print -r -- 0)
print -r -- "validation pid: $VALIDATION; sending SIGINT to claude -p (shell job $MAIN_PID) at $(date +%T)"
pkill -INT -P $MAIN_PID 2>/dev/null || true
kill -INT $MAIN_PID 2>/dev/null || true
sleep 15
if ps -p $MAIN_PID > /dev/null; then
  print -r -- "observed: claude -p still runs 15 s after SIGINT; sending SIGTERM"
  pkill -TERM -P $MAIN_PID 2>/dev/null || true
  kill -TERM $MAIN_PID 2>/dev/null || true
fi
wait $MAIN_PID 2>/dev/null || print -r -- "(claude exit $?)"
tail -c +$((START + 1)) $LOG | grep ' agents-call ' | tee $EVIDENCE/step6-lines.txt || true
grep -q ' agents-call cancelled ' $EVIDENCE/step6-lines.txt \
  && print -r -- "observed: the client sent notifications/cancelled for the running call" \
  || print -r -- "observed: no notifications/cancelled reached the host; SIGINT or input EOF ended it"
if [[ $VALIDATION != 0 ]] && ps -p $VALIDATION > /dev/null; then
  print -r -- "FAIL step 6: validation pid $VALIDATION is still running; stopping it now"; kill $VALIDATION || true
else
  print -r -- "PASS step 6: the long validation process is gone"
fi
print -r -- "Task 1 status: $(task_status)"
[[ $(task_status) == integrating ]] && print -r -- "PASS step 6: the Task stays integrating" || print -r -- "FAIL step 6: the Task left integrating"
channel_check "step 6"

say "step 7: a passing validation integrates the same Task (native dialog: none)"
VJSON=$(sleeper $P/step7.pid 1 0)
START=$(offset)
run_main "Use only the MCP tool mcp__agents__tasks. Make this call once: $(integrate_call $VJSON)
Print one line DONE and stop." $EVIDENCE/step7.jsonl
print -r -- "Task 1 status: $(task_status)"
[[ $(task_status) == integrated ]] && print -r -- "PASS step 7: Task 1 integrated after the cancellation" || print -r -- "FAIL step 7: Task 1 is not integrated"
channel_check "step 7"

say "step 8: summary and evidence"
cp $LOG $EVIDENCE/host.log
cp -R $STATE/worldline $EVIDENCE/worldline
grep -h '^PASS\|^FAIL\|^observed' $EVIDENCE/step4-result.txt $EVIDENCE/step5-result.txt || true
print -r -- "Follow-up commands (copy as needed):"
print -r -- "grep ' agents-call ' $EVIDENCE/host.log"
print -r -- "$VENV/bin/python $CHECK $EVIDENCE/host.log $EVIDENCE/step5.jsonl"
print -r -- "cd $WORK && $RUNNER reports $WRITER"
print -r -- "cd $WORK && $GT task graph"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
