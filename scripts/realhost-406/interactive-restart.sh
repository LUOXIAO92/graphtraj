#!/bin/zsh
# Task 406 real-host check, interactive part: a plain interactive start, then `claude --continue`,
# each over a dead host's channel.json. It finishes step 6 of stale-channel.sh, whose --continue
# stopped with `No conversation found to continue` before any host started.
#
# Run in a plain macOS Terminal, outside any sandbox (about 3 minutes):
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/406-stale-host-channel-after-crash/scripts/realhost-406/interactive-restart.sh
#
# Dialogs: none expected. Any dialog: press Esc and tell Main its title.
# You type: /exit, twice. Each time Claude Code starts, type nothing until it prints DONE, then
# type /exit and press Enter.
#
#   A  no dialog  the leftover channel.json is there and its host is dead
#   B  no dialog  plain interactive start over that file: replaced line, no host-busy, agents call ok
#   C  no dialog  a hold is killed abnormally, then claude --continue: the same three checks
#
# Observables: host.log, channel.json and process ids. Results go to results-interactive.txt in the
# evidence directory, apart from results.txt.
#
# Not run with Claude Code before hand-off: written in the team's sandbox, which cannot run it.
# Reuses /Users/luoxiao/agents-406-realhost as it is: nothing there is moved, deleted or recreated.
# No credential is read or printed. Nothing is installed. Main's host and its .graphtraj/claude-host
# are not touched; every process killed here is a claude this script started, or that claude's host.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/406-stale-host-channel-after-crash
# The code under test; later commits may change only this script's directory.
COMMIT=401df0576f1c66549f3c839c2be9247eafdd22e6
P=/Users/luoxiao/agents-406-realhost
MODEL=claude-opus-5-5
WORK=$P/project
EVIDENCE=$P/evidence
VENV=$P/venv
CHECK=$WT/scripts/realhost-406/check_stream.py
RESULTS=$EVIDENCE/results-interactive.txt
FIFO=$P/hold-stdin-interactive.fifo
HOSTDIR=$WORK/.graphtraj/claude-host
CONFIG=$HOSTDIR/config.json
LOG=$HOSTDIR/host.log
CHANNEL=$HOSTDIR/live/channel.json
REPLACED='agents host replaced a stale channel of a dead host'
DISCOVER='{"action":"discover"}'
PROMPT="Call mcp__agents__agents once with $DISCOVER and print one line DONE."

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }
# One PASS, FAIL or observed line: shown now and kept for the summary.
result() { print -r -- "$*" | tee -a $RESULTS; }
# Use as: check && passed <part> <statement> || failed <part> <statement>. Never stops the script.
typeset -U FAILED
FAILED=()
passed() { result "PASS $1: $2"; }
failed() { result "FAIL $1: $2"; FAILED+=($1); }

say "preflight (native dialog: none; nothing to type)"
[[ -n ${ZSH_VERSION:-} ]] || fail "run this script with zsh, as shown at its top"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-406' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-406' || fail "the Worktree has uncommitted code changes"
for needed in $VENV/bin/python $WORK $EVIDENCE $CONFIG $WORK/.mcp.json $LOG; do
  [[ -e $needed ]] || fail "$needed is missing; this script reuses the project stale-channel.sh built and does not recreate it"
done
# The CLI the host verifies as its parent.
CLAUDE=$($VENV/bin/python -c 'import json, sys; print(json.load(open(sys.argv[1]))["claude"])' $CONFIG)
[[ -x $CLAUDE ]] || fail "claude is not at $CLAUDE, the path in $CONFIG"
print -r -- "claude: $CLAUDE ($($CLAUDE --version))"
USER_MESSAGE=$($VENV/bin/python -c 'import json, sys; print(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": sys.argv[1]}]}}))' \
  "Call mcp__agents__agents once with $DISCOVER. Print one line DONE and stop.")
result "--- run at $(date +%T), code $COMMIT"

HOLD_OPEN=0
offset() { wc -c < $LOG | tr -d ' '; }
log_since() { tail -c +$(($1 + 1)) $LOG; }
# Value of one field of the channel file, or nothing when it cannot be read.
channel_field() { $VENV/bin/python -c 'import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' $CHANNEL $1 2>/dev/null || true; }
alive() { kill -0 $1 2>/dev/null; }
start_hold() {  # part, stream-json file: leaves a claude -p running; CLAUDE_PID is empty if it never got ready
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
    && result "$step: observed: the hold received real agents discover output" \
    || result "$step: observed: the hold did NOT receive real agents discover output; see $stream"
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
kill_abnormally() {  # part: SIGKILL the host, then its Claude, so nothing can clean up
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
restart_checks() {  # part, log offset, slice file: what the log gained since this start
  log_since $2 > $3
  grep -E " agents-call |$REPLACED|host-busy" $3 || true
  grep -qF "$REPLACED" $3 \
    && passed $1 "host.log gained the line: $REPLACED" || failed $1 "host.log gained the line: $REPLACED"
  grep -qF 'host-busy' $3 \
    && failed $1 "host.log gained no host-busy line" || passed $1 "host.log gained no host-busy line"
  grep -q 'agents-call finished .*tool=agents.*outcome=ok' $3 \
    && passed $1 "host.log shows an agents call finished with outcome=ok" \
    || failed $1 "host.log shows an agents call finished with outcome=ok"
}
wait_channel_gone() { for i in {1..50}; do [[ -e $CHANNEL ]] || break; sleep 0.1; done; }
interactive_lines() {
  print -r -- "Claude Code now starts in $WORK with this prompt already sent:"
  print -r -- "  $PROMPT"
  print -r -- "Type nothing until it prints DONE, then type /exit and press Enter."
  print -r -- "Expected dialogs: none. Any dialog: press Esc and tell Main its title."
}

say "A: the leftover channel.json (native dialog: none; nothing to type)"
[[ -e $CHANNEL ]] || fail "$CHANNEL does not exist, so there is no stale file to start over; tell Main"
print -r -- "channel.json: $(cat $CHANNEL)"
LOCK=$($VENV/bin/python -c 'import json, sys
from agent_swarm.connection import host_alive
print(host_alive(json.load(open(sys.argv[1]))["address"]))' $CHANNEL 2>/dev/null || print -r -- unreadable)
PARENT=$(channel_field parent)
if [[ -n $PARENT ]] && alive $PARENT; then PARENT_STATE=alive; else PARENT_STATE="not alive"; fi
result "A: observed: its parent ${PARENT:-(none)} is $PARENT_STATE; host_alive of its address: $LOCK"
[[ $LOCK == True ]] && fail "the host of $CHANNEL is alive, so the file is not stale; close that Claude Code and tell Main"
passed A "channel.json is there and its host is dead"

say "B: plain interactive start over that file (expected native dialog: none; about 1 minute)"
print -r -- "Observable: host.log gains the replaced line, no host-busy line, and an agents call with outcome=ok."
interactive_lines
START=$(offset)
# The prompt comes first: --mcp-config and --allowedTools take several values and would swallow it.
(cd $WORK && $CLAUDE "$PROMPT" --model $MODEL --mcp-config $WORK/.mcp.json --strict-mcp-config \
  --allowedTools mcp__agents__agents) || print -r -- "(claude exit $?; continuing to collect evidence)"
restart_checks B $START $EVIDENCE/interactive-B-log.txt
wait_channel_gone

say "C: the incident's path, claude --continue after an abnormal exit (expected native dialog: none; about 2 minutes)"
print -r -- "Observable: as in B. First a hold is killed abnormally; nothing to type for that."
start_hold C $EVIDENCE/interactive-C-before.jsonl
kill_abnormally C
interactive_lines
print -r -- "This one is 'claude --continue': it continues the interactive session from B."
START=$(offset)
CONTINUE_STATUS=0
# Stderr is kept, then shown, to name the client's message if it refuses.
(cd $WORK && $CLAUDE --continue "$PROMPT" --model $MODEL --mcp-config $WORK/.mcp.json --strict-mcp-config \
  --allowedTools mcp__agents__agents) 2> $EVIDENCE/interactive-C-stderr.txt || CONTINUE_STATUS=$?
cat $EVIDENCE/interactive-C-stderr.txt
print -r -- "(claude --continue exit $CONTINUE_STATUS)"
NOT_SHOWN=0
log_since $START > $EVIDENCE/interactive-C-log.txt
if [[ ! -s $EVIDENCE/interactive-C-log.txt ]]; then
  # A host that starts over the stale file always logs; an empty slice means none started.
  NOT_SHOWN=1
  MESSAGE=$(tr -s '\n' ' ' < $EVIDENCE/interactive-C-stderr.txt 2>/dev/null || true)
  result "C: observed: claude --continue exited $CONTINUE_STATUS without starting a host; the client said: ${MESSAGE:-(nothing on stderr; see the terminal above)}"
  result "C: --continue NOT SHOWN by this client; the replaced and outcome=ok checks do not count as product failures"
else
  restart_checks C $START $EVIDENCE/interactive-C-log.txt
fi

say "summary and evidence"
print -r -- "Results ($RESULTS):"
cat $RESULTS
print -r -- "Follow-up commands (copy as needed):"
print -r -- "grep -F '$REPLACED' $EVIDENCE/interactive-B-log.txt $EVIDENCE/interactive-C-log.txt"
print -r -- "grep -F 'host-busy' $EVIDENCE/interactive-B-log.txt $EVIDENCE/interactive-C-log.txt"
print -r -- "grep -E 'agents-call finished .*tool=agents' $EVIDENCE/interactive-B-log.txt $EVIDENCE/interactive-C-log.txt"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."
if (( ${#FAILED} )); then
  result "CRITERION NOT SHOWN: ${(j:, :)FAILED}"
elif (( NOT_SHOWN )); then
  result "CRITERION PASS for interactive restart; --continue NOT SHOWN"
else
  result "CRITERION PASS"
fi
