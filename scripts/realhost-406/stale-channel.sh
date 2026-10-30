#!/bin/zsh
# Task 406 real-host check: on the user's Claude Code, a host and its Claude are killed so that
# channel.json stays behind; the next normal start serves without anyone deleting the file, and a
# host that is really alive still keeps the project.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/406-stale-host-channel-after-crash/scripts/realhost-406/stale-channel.sh
#
# Every PASS, FAIL and observed line also goes to the evidence directory's results.txt.
#
# A "hold" keeps one claude -p running without any long tool or model cooperation: its stdin is a
# FIFO this script keeps open, with the same stream-json input flags as the project's own driver
# (src/agent_swarm/claude/execution.py). It answers one discover message and then waits for input.
#
#   step  dialog                what it shows
#   0     none                  zsh, versions, flags used, a one-line model and login answer
#   1     ONE (folder trust)    scratch project; trust once; host configuration --write
#   2     none                  baseline: claude -p calls agents discover
#   3     none                  abnormal exit: a hold, then SIGKILL its host and Claude; channel.json stays
#   4     none                  restart: claude -p serves; host.log says the stale channel was replaced
#   5     none                  live occupant: a hold; a second claude -p is refused with the first's pid
#   6     none expected         the incident's path: claude --continue after an abnormal exit
#   7     none                  results.txt, follow-up commands, last line CRITERION PASS or NOT SHOWN
#
# Observables: host.log in the scratch project, the channel file, process ids, and the
# stream-json of each claude -p run. Step 6 is interactive, so it uses host.log only.
#
# Not run before hand-off: written in the team's sandbox, which cannot run Claude Code. No credential
# is read, copied or printed. Nothing is installed into production: .venv-runtime is only read for one
# fixed websockets copy, as in 402 and 404. Main's host and its .graphtraj/claude-host are not touched;
# every process killed here is a claude this script started, or that claude's host.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/406-stale-host-channel-after-crash
# The code under test; later commits may change only this script's directory.
COMMIT=401df0576f1c66549f3c839c2be9247eafdd22e6
P=/Users/luoxiao/agents-406-realhost
PY=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
WORK=$P/project
EVIDENCE=$P/evidence
VENV=$P/venv
GT=$VENV/bin/graphtraj
CHECK=$WT/scripts/realhost-406/check_stream.py
RESULTS=$EVIDENCE/results.txt
FIFO=$P/hold-stdin.fifo
REPLACED='agents host replaced a stale channel of a dead host'

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }
# One PASS, FAIL or observed line: shown now and kept for the summary.
result() { print -r -- "$*" | tee -a $RESULTS; }
# Use as: check && passed <step> <statement> || failed <step> <statement>. Never stops the script.
passed() { result "PASS step $1: $2"; }
failed() { result "FAIL step $1: $2"; FAILED+=" $1"; }
FAILED=""

say "step 0: preflight (native dialog: none; nothing to type)"
[[ -n ${ZSH_VERSION:-} ]] || fail "run this script with zsh, as shown at its top"
print -r -- "shell: zsh $ZSH_VERSION"
[[ $COMMIT == REPLACE_WITH_CODE_COMMIT ]] && fail "set COMMIT in this script to the code commit under test"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-406' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-406' || fail "the Worktree has uncommitted code changes"
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
$VENV/bin/python -c 'import graphtraj, agent_swarm.connection as c, websockets; print("graphtraj", graphtraj.__file__); print("agent_swarm.connection", c.__file__); c.host_alive'

CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
[[ -x $CLAUDE ]] || fail "claude is not installed"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
HELP=$($CLAUDE --help)
for flag in --print --continue --session-id --mcp-config --strict-mcp-config --allowedTools --input-format --output-format --verbose --model '\[prompt\]'; do
  print -r -- $HELP | grep -q -- $flag && print -r -- "claude --help lists $flag" || fail "claude --help does not list $flag"
done
print -r -- 'In one line: name the model you are running as, and confirm you are logged in. Do not use any tool.' \
  | (cd $P && $CLAUDE -p --model $MODEL) | tail -1

say "step 1: scratch project and folder trust (ONE native dialog)"
git -C $WORK init -q --initial-branch=main
print -r -- "# 406 scratch project" > $WORK/README.md
git -C $WORK add README.md && git -C $WORK commit -qm "Initial source"
(cd $WORK && print -r -- y | $GT setup) | tee $EVIDENCE/setup.txt
HOSTDIR=$WORK/.graphtraj/claude-host
LOG=$HOSTDIR/host.log
CHANNEL=$HOSTDIR/live/channel.json
print -r -- "Claude Code now starts once in $WORK."
print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
(cd $WORK && $CLAUDE)
print -r -- "Writing the GraphTraj Claude host configuration (no dialog)."
(cd $WORK && $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $WORK --claude $CLAUDE --write)
touch $LOG

DISCOVER='{"action":"discover"}'
USER_MESSAGE=$($VENV/bin/python -c 'import json, sys; print(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": sys.argv[1]}]}}))' \
  "Call mcp__agents__agents once with $DISCOVER. Print one line DONE and stop.")
# The same way of giving claude -p the tools as 404's script; the mod comes from the written project plugin.
claude_print() {  # reads the prompt from stdin
  (cd $WORK && $CLAUDE -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) --output-format stream-json \
     --verbose --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__agents)
}
HOLD_OPEN=0
offset() { wc -c < $LOG | tr -d ' '; }
log_since() { tail -c +$(($1 + 1)) $LOG; }
# Value of one field of the channel file, or nothing when it cannot be read.
channel_field() { $VENV/bin/python -c 'import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' $CHANNEL $1 2>/dev/null || true; }
alive() { kill -0 $1 2>/dev/null; }
start_hold() {  # step, stream-json file: leaves a claude -p running; CLAUDE_PID is empty if it never got ready
  local step=$1 stream=$2
  rm -f $FIFO
  mkfifo $FIFO
  # Held by this script: claude -p sees no end of input until close_hold.
  exec 3<>$FIFO
  HOLD_OPEN=1
  (cd $WORK && exec $CLAUDE -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) --input-format stream-json \
     --output-format stream-json --verbose --mcp-config $WORK/.mcp.json --strict-mcp-config \
     --allowedTools mcp__agents__agents) < $FIFO > $stream 3>&- &
  HOLD_JOB=$!
  print -r -u3 -- $USER_MESSAGE
  CLAUDE_PID=""
  for i in {1..120}; do
    if [[ -s $CHANNEL ]] && grep -q '"type":"result"' $stream 2>/dev/null; then
      CLAUDE_PID=$(channel_field parent)
      if [[ -n $CLAUDE_PID ]] && alive $CLAUDE_PID; then break; fi
      CLAUDE_PID=""
    fi
    alive $HOLD_JOB || break  # Ended early: no reason to keep waiting.
    sleep 1
  done
  $VENV/bin/python $CHECK $stream --discover | tee $stream.check.txt \
    && result "step $step: observed: the hold received real agents discover output" \
    || result "step $step: observed: the hold did NOT receive real agents discover output; see $stream"
  if [[ -z $CLAUDE_PID ]]; then
    close_hold
    for i in {1..150}; do alive $HOLD_JOB || break; sleep 0.1; done
    kill -TERM $HOLD_JOB 2>/dev/null || true
    wait $HOLD_JOB 2>/dev/null || true
  fi
}
close_hold() {  # Ends the hold's input; after a kill this is only cleanup.
  if (( HOLD_OPEN )); then
    exec 3>&-
    HOLD_OPEN=0
  fi
  rm -f $FIFO
}
kill_abnormally() {  # step: SIGKILL the host, then its Claude, so nothing can clean up
  local step=$1 host
  if [[ -z $CLAUDE_PID ]]; then
    failed $step "the hold got a result, channel.json and a live parent within 2 minutes; see the stream-json"
    return 0
  fi
  host=$(pgrep -P $CLAUDE_PID -f 'claude.host serve' | head -1 || true)
  print -r -- "channel.json before the kill: $(<$CHANNEL)"
  print -r -- "Claude Code pid: $CLAUDE_PID; host pid: ${host:-none found}"
  if [[ -z $host ]]; then
    failed $step "the host was found as a direct child of Claude Code pid $CLAUDE_PID"
    kill -KILL $CLAUDE_PID 2>/dev/null || true
    wait $HOLD_JOB 2>/dev/null || true
    close_hold
    return 0
  fi
  kill -KILL $host 2>/dev/null || true
  kill -KILL $CLAUDE_PID 2>/dev/null || true
  wait $HOLD_JOB 2>/dev/null || true
  # Only now: closing the input earlier would let Claude end normally and clean up.
  close_hold
  for i in {1..50}; do alive $host || alive $CLAUDE_PID || break; sleep 0.1; done
  ! alive $host && ! alive $CLAUDE_PID && [[ -s $CHANNEL ]] \
    && passed $step "channel.json remains and both pids ($host, $CLAUDE_PID) are gone" \
    || failed $step "channel.json remains and both pids ($host, $CLAUDE_PID) are gone"
  print -r -- "channel.json after the kill: $(cat $CHANNEL 2>/dev/null || print -r -- '(missing)')"
}
replaced_and_not_busy() {  # step, log offset
  local since
  since=$(log_since $2)
  print -r -- $since | grep -F "$REPLACED" || true
  print -r -- $since | grep -qF "$REPLACED" \
    && passed $1 "host.log gained the line: $REPLACED" || failed $1 "host.log gained the line: $REPLACED"
  print -r -- $since | grep -qF 'host-busy' \
    && failed $1 "host.log gained no host-busy line" || passed $1 "host.log gained no host-busy line"
}

say "step 2: baseline (native dialog: none; about 1 minute)"
print -r -- "Observable: the stream-json result of agents discover is real output, not a refusal."
print -r -- "Call mcp__agents__agents once with $DISCOVER. Print one line DONE and stop." \
  | claude_print > $EVIDENCE/step2.jsonl || print -r -- "(claude exit $?; continuing to collect evidence)"
$VENV/bin/python $CHECK $EVIDENCE/step2.jsonl --discover | tee $EVIDENCE/step2-result.txt \
  && passed 2 "claude -p received real agents discover output" \
  || failed 2 "claude -p received real agents discover output"
for i in {1..50}; do [[ -e $CHANNEL ]] || break; sleep 0.1; done
[[ ! -e $CHANNEL ]] && result "step 2: observed: a normal exit removed channel.json" \
  || result "step 2: observed: channel.json still there 5 s after a normal exit: $(<$CHANNEL)"

say "step 3: abnormal exit (native dialog: none; about 1 minute)"
print -r -- "Observable: channel.json stays and both process ids are gone after SIGKILL."
start_hold 3 $EVIDENCE/step3.jsonl
kill_abnormally 3

say "step 4: restart after the abnormal exit (native dialog: none; about 1 minute)"
print -r -- "Observable: real discover output in stream-json; host.log gains the replaced line and no host-busy line."
START=$(offset)
print -r -- "Call mcp__agents__agents once with $DISCOVER. Print one line DONE and stop." \
  | claude_print > $EVIDENCE/step4.jsonl || print -r -- "(claude exit $?; continuing to collect evidence)"
$VENV/bin/python $CHECK $EVIDENCE/step4.jsonl --discover | tee $EVIDENCE/step4-result.txt \
  && passed 4 "claude -p received real agents discover output without anyone deleting the file" \
  || failed 4 "claude -p received real agents discover output without anyone deleting the file"
replaced_and_not_busy 4 $START
for i in {1..50}; do [[ -e $CHANNEL ]] || break; sleep 0.1; done

say "step 5: live occupant (native dialog: none; about 2 minutes)"
print -r -- "Observable: host.log gains host-busy naming the first pid; the second's call shows it; the file is unchanged."
start_hold 5 $EVIDENCE/step5-first.jsonl
if [[ -z $CLAUDE_PID ]]; then
  failed 5 "the hold got a result, channel.json and a live parent within 2 minutes; see the stream-json"
else
  FIRST=$CLAUDE_PID
  BEFORE=$(<$CHANNEL)
  print -r -- "first Claude Code pid: $FIRST; channel.json: $BEFORE"
  START=$(offset)
  print -r -- "Call mcp__agents__agents once with $DISCOVER. If it fails, print its error text. Print one line DONE and stop." \
    | claude_print > $EVIDENCE/step5-second.jsonl || print -r -- "(claude exit $?; continuing to collect evidence)"
  log_since $START | grep -F 'host-busy' | tee $EVIDENCE/step5-log.txt || true
  grep -q "host-busy.*Claude Code pid $FIRST" $EVIDENCE/step5-log.txt \
    && passed 5 "host.log gained host-busy naming Claude Code pid $FIRST" \
    || failed 5 "host.log gained host-busy naming Claude Code pid $FIRST"
  $VENV/bin/python $CHECK $EVIDENCE/step5-second.jsonl --refused "Claude Code pid $FIRST" | tee $EVIDENCE/step5-result.txt \
    && passed 5 "the second call shows that reason, not a CLI version mismatch" \
    || failed 5 "the second call shows that reason, not a CLI version mismatch"
  [[ $(cat $CHANNEL 2>/dev/null || true) == $BEFORE ]] \
    && passed 5 "the first host's channel.json is unchanged" || failed 5 "the first host's channel.json is unchanged"
  alive $FIRST && passed 5 "the first Claude Code is still running" || failed 5 "the first Claude Code is still running"
  print -r -- "Ending the first Claude Code with SIGINT at $(date +%T)."
  kill -INT $FIRST 2>/dev/null || true
  for i in {1..150}; do alive $FIRST || break; sleep 0.1; done
  if alive $FIRST; then
    result "step 5: observed: Claude Code still runs 15 s after SIGINT; sending SIGTERM"
    kill -TERM $FIRST 2>/dev/null || true
  fi
  # Closed before waiting, so a Claude ignoring both signals still ends at the end of its input.
  close_hold
  wait $HOLD_JOB 2>/dev/null || true
  for i in {1..50}; do [[ -e $CHANNEL ]] || break; sleep 0.1; done
  [[ ! -e $CHANNEL ]] && result "step 5: observed: channel.json removed after the first Claude Code ended" \
    || result "step 5: observed: channel.json still there 5 s after the first Claude Code ended: $(<$CHANNEL)"
fi

say "step 6: interactive restart, the incident's own path (expected native dialog: none; about 2 minutes)"
print -r -- "Observable: host.log gains the replaced line, no host-busy line, and agents-call finished tool=agents outcome=ok."
start_hold 6 $EVIDENCE/step6-before.jsonl
kill_abnormally 6
START=$(offset)
print -r -- "Claude Code now continues the last session in $WORK with this prompt already sent:"
print -r -- "  Call mcp__agents__agents once with $DISCOVER and print one line DONE."
print -r -- "It is 'claude --continue' plus the same --mcp-config and --allowedTools as above, because this"
print -r -- "scratch project has no approval for its .mcp.json and a second dialog would change the step."
print -r -- "Type nothing while it works. When it prints DONE, type /exit and press Enter."
print -r -- "Any dialog: press Esc and tell Main its title."
# The prompt comes first: --mcp-config and --allowedTools take several values and would swallow it.
(cd $WORK && $CLAUDE --continue "Call mcp__agents__agents once with $DISCOVER and print one line DONE." \
  --model $MODEL --mcp-config $WORK/.mcp.json --strict-mcp-config --allowedTools mcp__agents__agents) \
  || print -r -- "(claude exit $?; continuing to collect evidence)"
log_since $START | tee $EVIDENCE/step6-log.txt | grep ' agents-call ' || true
replaced_and_not_busy 6 $START
grep -q 'agents-call finished .*tool=agents.*outcome=ok' $EVIDENCE/step6-log.txt \
  && passed 6 "host.log shows an agents call finished with outcome=ok" \
  || failed 6 "host.log shows an agents call finished with outcome=ok"

say "step 7: summary and evidence"
cp $LOG $EVIDENCE/host.log
print -r -- "Results ($RESULTS):"
cat $RESULTS
print -r -- "Follow-up commands (copy as needed):"
print -r -- "grep -F '$REPLACED' $EVIDENCE/host.log"
print -r -- "grep -F 'host-busy' $EVIDENCE/host.log"
print -r -- "$VENV/bin/python $CHECK $EVIDENCE/step4.jsonl --discover"
print -r -- "$VENV/bin/python $CHECK $EVIDENCE/step5-second.jsonl --refused 'host-busy'"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
if [[ -z $FAILED ]]; then
  result "CRITERION PASS: abnormal exit, restart without cleanup, live occupant and interactive restart all passed"
else
  result "CRITERION NOT SHOWN: failed in step(s)$FAILED"
fi
