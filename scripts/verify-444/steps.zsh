#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 444: unattended Main-swap checks on real hosts, in an ISOLATED project under the Harness tmp/444.
# The production Claude Main is never yielded, exited or reconfigured; every probe Main runs in $P.
#   zsh <this file> <00|00u|B1|B2|C1|C2|C3|P1|P2|E1|E2|D1|D2|D3|F>
# Order: 00 -> (00u, USER, only if 00 says so) -> B1 B2 (Claude Main queues h397) -> C1 C2 C3 (Codex Main:
# 397, 373, 401) -> P1 P2 (Pi Main: 373) -> E1 E2 (Pi member: 425) -> D1 D2 D3 (headless DSH Main: 398, 373) -> F.
# Every step: no native dialog (headless hosts; requests are answered by the probe Main through the tasks tool),
# returns within 10 minutes or starts its host in the background, signals only processes it started.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
BASE=${VERIFY444_BASE:-$H/tmp/444}
P=$BASE/project
OUT=${VERIFY444_OUT:-$H/.graphtraj/core/state/tasks/444-unattended-main-swap-checks/realhost}
RT=${VERIFY444_RT:-$H/.venv-runtime}
PY=$RT/bin/python
MODEL=claude-opus-5-5
CODEX_MODEL=gpt-6-luna
STEP=${1:-help}
path=($RT/bin /opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY444_CLAUDE:-} ]] && { print -r -- $VERIFY444_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Hosts run without this shell's GraphTraj Session variables (Main's own would leak in). DEEPSEEK_API_KEY is
# passed through by name only for Pi and DSH, which need it; its value is never printed.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
probe() { (cd $P && clean $PY -I $SD/probe.py "$@") | redact; return ${pipestatus[1]}; }
# Wait (<= 9 min) for a background host started by this script; never a standalone sleep.
wait_pid() { $PY -I -c 'import os, sys, time
try: pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError): print("STOP: no pid file", sys.argv[1], "- run the previous step first"); sys.exit(2)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("host pid", pid, "ended"); sys.exit(0)
    time.sleep(5)
print("host pid", pid, "still running; rerun this step later"); sys.exit(1)' $1 ${2:-540}; }
pause() { $PY -I -c 'import sys, time; time.sleep(float(sys.argv[1]))' $1; }
bg() { local name=$1; shift; (cd $P && clean nohup "$@" < $OUT/$name-prompt.txt > $OUT/$name-main-stream.jsonl 2> $OUT/$name-stderr.txt & print $! > $OUT/$name.pid); print "$name host pid $(cat $OUT/$name.pid); stream $OUT/$name-main-stream.jsonl"; }
CLAUDE_MAIN=(-p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config --allowedTools "mcp__agents__agents,mcp__agents__tasks")
CODEX_MAIN=(exec -m $CODEX_MODEL --skip-git-repo-check --json -c "mcp_servers.graphtraj.command=\"$RT/bin/graphtraj-mcp\"" -c "mcp_servers.graphtraj.cwd=\"$P\"" -c 'approval_policy="never"')
SITE() { print -r -- $($PY -I -c 'import graphtraj, os; print(os.path.dirname(os.path.dirname(graphtraj.__file__)))'); }
PI_MAIN() { print -r -- pi --print --extension $(SITE)/graphtraj/runtimes/pi/extension.mjs --provider deepseek --model deepseek-flash; }
# The 373 trigger, shared by C1, P1 and D2: an asker (Claude, permission_mode default) makes two shell calls.
ASK373() { print -r -- "{\"action\":\"execute\",\"feature\":\"swarm\",\"arguments\":{\"tasks\":[{\"task_id\":\"1\",\"role\":\"asker\",\"instruction\":\"Run these two shell commands, one Bash call each, in this order: touch $BASE/373-$1-a and touch $BASE/373-$1-b. Each needs approval; wait for each answer. Then reply with one line saying which were allowed or denied.\"}]}}"; }
DENY='Then repeat, at most 12 rounds, until the asker execution has ended: using the agents tool, action requests with agent set to the asker alias from SWARM-RESULT; for EVERY pending native request call the agents tool action reply with that agent, request set to the request object exactly as returned, and response {"behavior": "deny", "message": "444 probe denies"}; print one line DENIED <request id> per reply. Between rounds use the agents tool action wait with that agent and timeout_seconds 15 (never a shell command). Finally print the asker final reply on one line starting with ASKER-RESULT and stop. Never allow a request.'

step_00() {
  say "[00] preflight. Dialog: none. Output also in $OUT/00.txt"
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} (launched via /bin/zsh)"
  print "claude --version: $(clean $(claude_bin) --version 2>&1 | tail -1)   (expected 2.1.325)"
  print "production graphtraj: $($PY -I -c 'import graphtraj; print(graphtraj.__file__)' 2>&1)"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset"
  say "production current Main (read only; F compares)"
  (cd $H && clean $PY -I -c 'import json,sys
from pathlib import Path
p = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-1] if p.is_file() else {}
print(last.get("runtime", "none"), last.get("session", "none"))') > $OUT/00-production-main.txt
  print "production Main: $(cat $OUT/00-production-main.txt)"
  say "isolated project $P"
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 444 probe README first line" > README.md && git add README.md \
      && git -c user.name=444 -c user.email=444@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $RT/bin/graphtraj setup | tail -2) || return 1
  fi
  probe prepare $P || { print "STOP: probe Task is not ready (text above)"; return 1; }
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  say "Claude host configuration and isolation (project .claude/settings.local.json only)"
  (cd $P && clean $PY -m graphtraj.runtimes.claude.host configuration --project $P --claude $(claude_bin) --write) || return 1
  $PY -I -c 'import json, sys
from pathlib import Path
h, path = sys.argv[1], Path(sys.argv[2])
s = json.loads(path.read_text()) if path.is_file() else {}
s["claudeMdExcludes"] = sorted({*s.get("claudeMdExcludes", []), *(h + x for x in ("/CLAUDE.md", "/CLAUDE.local.md",
    "/.claude/CLAUDE.md", "/**/CLAUDE.md", "/**/CLAUDE.local.md", "/AGENTS.md", "/**/AGENTS.md"))})
s["enabledPlugins"] = {**s.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(s, indent=2) + "\n")
print("claudeMdExcludes set; cc-plugin-agents-md@builtin disabled in", path)' $H $P/.claude/settings.local.json || return 1
  say "Codex project hooks (SessionStart/Stop/SessionEnd from graphtraj.runtimes.codex.finalize.hook) in $P/.codex"
  mkdir -p $P/.codex
  (cd $P && clean $PY -I -c 'import json, sys
from pathlib import Path
from graphtraj.runtimes.codex.finalize import hook
Path(".codex/hooks.json").write_text(json.dumps(hook(Path("."), {}), indent=2) + "\n"); print("wrote .codex/hooks.json")') || return 1
  say "Pi sandbox (roles.yml pi_member = production pi_dsh_trial.team_leader values)"
  probe pisandbox - ; print "pi sandbox rc=$? (non-zero: E is NOT OBSERVED; Pi as Main does not use it: extension.mjs has no sandbox)"
  say "DSH headless profile plugins (D needs the GraphTraj DSH plugin there)"
  clean dsh plugin --profile headless list 2>&1 | redact | head -20 | tee $OUT/00-dsh-plugins.txt
  grep -qiE 'graphtraj|graftling' $OUT/00-dsh-plugins.txt && print "dsh GraphTraj plugin: YES" || print "dsh GraphTraj plugin: NO (D is NOT OBSERVED; installing it is the user's decision)"
  [[ -n ${VERIFY444_NO_MODEL:-} ]] && { print "VERIFY444_NO_MODEL set: stopping before any model (rehearsal)."; return 0; }
  local ASK='Reply with exactly three lines. Line 1: MODEL OK. Line 2: MODEL: your model name. Line 3: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'
  print -r -- "$ASK" > $OUT/00-ask.txt
  say "hosts answer one line in $P (YES/NO only; Harness instruction files must be NONE)"
  (cd $P && clean $(claude_bin) -p --model $MODEL --output-format json --mcp-config $P/.mcp.json --strict-mcp-config < $OUT/00-ask.txt > $OUT/00-claude.txt 2>&1)
  if clean codex login status 2>&1 | grep -q 'Logged in'; then print "codex logged in: YES"; else print "codex logged in: NO"; fi
  (cd $P && clean codex exec -m $CODEX_MODEL --skip-git-repo-check --sandbox read-only - < $OUT/00-ask.txt > $OUT/00-codex.txt 2>&1)
  (cd $P && clean $(PI_MAIN) --no-tools "$ASK" < /dev/null > $OUT/00-pi.txt 2>&1)
  (cd $P && clean env -u DEEPSEEK_BASE_URL dsh --profile headless --permission-mode read-only "$ASK" < /dev/null > $OUT/00-dsh.txt 2>&1)
  for host in claude codex pi dsh; do
    local f=$OUT/00-$host.txt
    redact < $f > $f.r && mv $f.r $f
    local ok=NO leak=none; grep -q 'MODEL OK' $f && ok=YES
    grep -oE "$H/[^ \"]*(AGENTS|CLAUDE)\.md" $f | grep -v "^$P/" | head -1 | read leak
    print "$host answered: $ok | model line: $(grep -oE 'MODEL: [^\"\\]*' $f | head -1) | Harness instruction file loaded: ${leak:-none}"
  done
  grep -q 'graphtraj-claude-host' <(cd $P && clean $(claude_bin) -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config <<< 'Reply OK. Use no tool.' 2>&1) \
    && print "graphtraj-claude-host loaded: YES" || { print "graphtraj-claude-host loaded: NO"; next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"; return 1; }
  print "Success: four 'answered: YES', every 'Harness instruction file loaded: none', 'codex logged in: YES', roles OK, task 1 ready,"
  print "'project own: True', 'graphtraj-claude-host loaded: YES', 'pi sandbox missing: nothing', 'dsh GraphTraj plugin: YES'."
  next "zsh $THIS B1"
}

step_00u() {
  say "[00u] USER, once, only when 00 says so (Main cannot: these are native trust dialogs). Plain macOS Terminal:"
  print "  cd $P && claude          -> 'Do you trust the files in this folder?' choose 'Yes, proceed'; approve the project MCP 'agents'; /exit"
  print "  cd $P && codex -m $CODEX_MODEL   -> trust this folder and approve the project hooks ($P/.codex/hooks.json) if asked; /exit"
  print "  cd $P && $(PI_MAIN | sed 's/--print //')   -> trust the folder if Pi asks; Ctrl-C"
  print "Send no message. Any other dialog: Esc and tell Main its title. Nothing here touches the production Main."
  next "Main: zsh $THIS 00"
}

# ---- B: Claude Main queues a notice before the swap (397) ------------------------------------------------
step_B1() {
  say "[B1] background Claude Main in $P creates root agent h397 (90 s) and ends at once. Dialog: none."
  print -r -- 'Using only the agents tool: execute feature create with arguments {"runtime": "claude", "configuration": "advisor", "alias": "h397", "instruction": "Run the shell command sleep 90 once, then reply with exactly one line: PONG-397."}. Print the raw result on one line starting with CREATE and end your turn at once. Do not wait, do not call status.' > $OUT/B1-prompt.txt
  bg B1 $(claude_bin) $CLAUDE_MAIN
  next "zsh $THIS B2 2>&1 | tee $OUT/B2.txt"
}
step_B2() {
  say "[B2] waits for B1's Claude Main, then <= 3 min for h397's end notice in the (now host-less) Claude Main queue. Dialog: none."
  wait_pid $OUT/B1.pid || return 1
  grep -o 'CREATE[^"]*' $OUT/B1-main-stream.jsonl | head -2
  probe queued $P claude h397 180; local rc=$?
  probe inbox $P | tee $OUT/B2-inbox.txt
  print $([[ $rc == 0 ]] && print PASS || print FAIL) "397 precondition: an undelivered h397 end notice is queued for the exited Claude Main (QUEUED line)"
  next "zsh $THIS C1"
}

# ---- C: Codex Main (397, 373, 401) ----------------------------------------------------------------------
step_C1() {
  say "[C1] background Codex Main ($CODEX_MODEL, codex exec) in $P. Dialog: none (exec has no UI; approval_policy never)."
  print -r -- "First, before any tool: quote every GraphTraj notice you were given at session start (alias, event, first message line) and print one line H397-COUNT <n> with how many times h397 appears.
Second, using only the graphtraj agents tool: create a root agent with arguments {\"runtime\": \"claude\", \"configuration\": \"advisor\", \"alias\": \"h401\", \"instruction\": \"Reply with exactly one line: PONG-401. Use no tools.\"}; print one line H401-CREATE <agent id>. Do not wait for it.
Third, using only the graphtraj tasks tool: call it once with exactly $(ASK373 codex) and print its raw result on one line starting with SWARM-RESULT.
$DENY" > $OUT/C1-prompt.txt
  bg C1 codex $CODEX_MAIN -
  next "zsh $THIS C2 2>&1 | tee $OUT/C2.txt"
}
step_C2() {
  say "[C2] waits (<= 9 min) for C1; judges 397 and 373 on Codex; starts the Codex resume turn for 401. Dialog: none."
  wait_pid $OUT/C1.pid || return 1
  probe inbox $P | tee $OUT/C2-inbox.txt
  local thread=$($PY -I -c 'import json,sys
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    if d.get("type") == "thread.started": print(d.get("thread_id")); break' $OUT/C1-main-stream.jsonl)
  print "Codex Main thread: ${thread:-NONE}"; print -r -- "$thread" > $OUT/C1.thread
  probe count $OUT/C1-main-stream.jsonl PONG-397 H397-COUNT H401-CREATE SWARM-RESULT DENIED ASKER-RESULT
  local n=$(grep -oE 'H397-COUNT [0-9]+' $OUT/C1-main-stream.jsonl | tail -1 | awk '{print $2}')
  local claimed=$(grep -c '"runtime": *"codex"' $P/.graphtraj/runner/main-sessions/continuity.jsonl 2>/dev/null)
  print $([[ $claimed -ge 1 ]] && print PASS || print FAIL) "C entry: continuity.jsonl has a codex claim ($claimed) - Codex SessionStart hook ran (else: hooks not trusted, see 00u)"
  probe delivered $P h397; local rec=$?
  print $([[ $n == 1 && $rec == 0 ]] && print PASS || print FAIL) "397: h397's end notice id delivered exactly once in the records (397 record line above) AND H397-COUNT ${n:-none} == 1 in the Codex Main's session-start notices"
  probe requests $P $OUT C1 codex
  [[ -n $thread ]] || { print "STOP: no Codex thread id; 401 cannot be resumed"; return 1; }
  pause 60
  print -r -- "Before any tool: quote every GraphTraj notice or host event you were given since your previous turn (alias, event, first message line), and print one line H401-COUNT <n> with how many times h401 or PONG-401 appears. Then, using only the graphtraj agents tool, status for agent h401 and print its notification field on one line starting with H401-NOTIFICATION. Stop." > $OUT/C3-prompt.txt
  bg C3 codex exec resume $thread -m $CODEX_MODEL --skip-git-repo-check --json -c "mcp_servers.graphtraj.command=\"$RT/bin/graphtraj-mcp\"" -c "mcp_servers.graphtraj.cwd=\"$P\"" -c 'approval_policy="never"' -
  next "zsh $THIS C3 2>&1 | tee $OUT/C3.txt"
}
step_C3() {
  say "[C3] waits for the Codex resume turn; judges 401. Dialog: none."
  wait_pid $OUT/C3.pid || return 1
  probe count $OUT/C3-main-stream.jsonl PONG-401 H401-COUNT H401-NOTIFICATION
  probe count $OUT/C1-main-stream.jsonl PONG-401
  print "supporting only: H401-COUNT $(grep -oE 'H401-COUNT [0-9]+' $OUT/C3-main-stream.jsonl | tail -1 | awk '{print $2}') (model self-report), H401-NOTIFICATION above"
  probe ends $P $OUT h401 C1-main-stream.jsonl C3-main-stream.jsonl
  print "Judged by 'PASS/FAIL 401 delivered once' above: deliveries of h401's end event to the Codex Main, by event identity."
  probe inbox $P | tee $OUT/C3-inbox.txt
  next "zsh $THIS P1"
}

# ---- P: Pi Main (373) -----------------------------------------------------------------------------------
step_P1() {
  say "[P1] background Pi Main (pi --print with GraphTraj's Pi extension) in $P. Dialog: none."
  print -r -- "Using only the GraphTraj tasks tool: call it once with exactly $(ASK373 pi) and print its raw result on one line starting with SWARM-RESULT.
$DENY" > $OUT/P1-prompt.txt
  (cd $P && clean GRAFTLING_PYTHON=$PY nohup ${=$(PI_MAIN)} "$(cat $OUT/P1-prompt.txt)" < /dev/null > $OUT/P1-main-stream.jsonl 2> $OUT/P1-stderr.txt & print $! > $OUT/P1.pid)
  print "P1 host pid $(cat $OUT/P1.pid)"
  next "zsh $THIS P2 2>&1 | tee $OUT/P2.txt"
}
step_P2() {
  say "[P2] waits for the Pi Main; judges 373 on Pi. Dialog: none."
  wait_pid $OUT/P1.pid || return 1
  redact < $OUT/P1-main-stream.jsonl | tail -20
  local claimed=$(grep -c '"runtime": *"pi"' $P/.graphtraj/runner/main-sessions/continuity.jsonl 2>/dev/null)
  print $([[ $claimed -ge 1 ]] && print PASS || print FAIL) "P entry: continuity.jsonl has a pi claim ($claimed) - the Pi extension's session_start continued Main"
  probe requests $P $OUT P1 pi
  probe inbox $P | tee $OUT/P2-inbox.txt
  next "zsh $THIS E1"
}

# ---- E: real Pi member reads a file in its own Worktree (425) ---------------------------------------------
step_E1() {
  say "[E1] background Claude Main dispatches a Pi member that reads README.md in its Worktree, then session_read. Dialog: none."
  print -r -- 'Use only the tasks and agents tools. 1. With the tasks tool execute swarm with arguments {"tasks":[{"task_id":"1","role":"pi_member","instruction":"Use your read tool on README.md in your working directory, then reply with exactly one line: PONG-425: followed by that file first line."}]} and print the raw result on one line starting with SWARM-RESULT. 2. Wait for that member with the agents tool action wait (agent: its alias, timeout_seconds 240). 3. With the tasks tool, session_read for the member session (the session_id from the swarm result) with limit 20 and print one line E-MISSING <yes|no> <path named, or none> saying whether any attachment or read result is marked missing, and one line E-REPLY <its final reply>. Stop.' > $OUT/E1-prompt.txt
  bg E1 $(claude_bin) $CLAUDE_MAIN
  next "zsh $THIS E2 2>&1 | tee $OUT/E2.txt"
}
step_E2() {
  say "[E2] waits; judges 425. Dialog: none."
  wait_pid $OUT/E1.pid || return 1
  grep -oE 'E-MISSING[^"\\]*|E-REPLY[^"\\]*|SWARM-RESULT.{0,200}' $OUT/E1-main-stream.jsonl | redact | head -5
  local s=$(probe session $P pi_member)
  print "Pi member session: $s"
  local miss=$( [[ -d $s ]] && grep -rliE '"missing"|missing: *true' $s 2>/dev/null | head -3)
  grep -q 'PONG-425: # 444 probe README first line' $OUT/E1-main-stream.jsonl && local ok=1 || local ok=0
  print $([[ $ok == 1 && -z $miss ]] && print PASS || print FAIL) "425: the Pi member's reply carries README.md's first line, and its session records mark nothing missing (${miss:-no missing marker})"
  next "zsh $THIS D1 2>&1 | tee $OUT/D1.txt"
}

# ---- D: headless DSH Main (398, 373) -----------------------------------------------------------------------
dsh_turn() { (cd $P && clean env -u DEEPSEEK_BASE_URL nohup dsh --profile headless --json "$@" < /dev/null > $OUT/$STEP-main-stream.jsonl 2> $OUT/$STEP-stderr.txt & print $! > $OUT/$STEP.pid); wait_pid $OUT/$STEP.pid 420; }
step_D1() {
  say "[D1] headless DSH Main: create g398 (60 s) and exit. Then waits 100 s and checks the notice stays queued (398). Dialog: none."
  dsh_turn "Using only the agents tool: create a root agent with arguments {\"runtime\": \"claude\", \"configuration\": \"advisor\", \"alias\": \"g398\", \"instruction\": \"Run the shell command sleep 60 once, then reply with exactly one line: PONG-398.\"}. Do not wait. Print CREATE and the agent id, then stop." || return 1
  $PY -I -c 'import json,sys
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    s = d.get("session") or d.get("sessionId") or d.get("session_id")
    s = s.get("id") if isinstance(s, dict) else s
    if isinstance(s, str) and s: print(s); break' $OUT/D1-main-stream.jsonl > $OUT/D.session
  print "DSH Main session: $(cat $OUT/D.session)"
  pause 100
  probe queued $P dsh g398 60; local rc=$?
  print $([[ $rc == 0 ]] && print PASS || print FAIL) "398 part 1: after the headless DSH Main exited, g398's end stays queued, undelivered (QUEUED line)"
  next "zsh $THIS D2 2>&1 | tee $OUT/D2.txt"
}
step_D2() {
  say "[D2] resume the DSH Main (--session-id): g398 delivered once; dispatch the asker; exit. Dialog: none."
  [[ -s $OUT/D.session ]] || { print "STOP: no DSH session id; run D1"; return 1; }
  dsh_turn --session-id $(cat $OUT/D.session) "Quote every GraphTraj notice you received at the start of this turn (alias, event) and print one line G398-COUNT <n> with how many times g398 appears. Then using only the tasks tool call it once with exactly $(ASK373 dsh) and print its raw result on one line starting with SWARM-RESULT. Stop; do not wait." || return 1
  local n=$(grep -oE 'G398-COUNT [0-9]+' $OUT/D2-main-stream.jsonl | tail -1 | awk '{print $2}')
  print $([[ $n == 1 ]] && print PASS || print FAIL) "398 part 2: the resumed headless DSH Main received g398 exactly once (G398-COUNT ${n:-none})"
  probe inbox $P | tee $OUT/D2-inbox.txt
  print "D3 starts by waiting 120 s so the asker's two requests are queued while the DSH Main is exited."
  next "zsh $THIS D3 2>&1 | tee $OUT/D3.txt"
}
step_D3() {
  say "[D3] after 120 s, resume the DSH Main: the asker's queued requests arrive; it denies each. Dialog: none."
  pause 120
  dsh_turn --session-id $(cat $OUT/D.session) "Quote every GraphTraj notice you received at the start of this turn (alias, event, request id). $DENY" || return 1
  cat $OUT/D2-main-stream.jsonl $OUT/D3-main-stream.jsonl > $OUT/D3x-main-stream.jsonl 2>/dev/null  # asker alias is in D2's
  probe requests $P $OUT D3x dsh
  probe inbox $P | tee $OUT/D3-inbox.txt
  next "zsh $THIS F 2>&1 | tee $OUT/F.txt"
}

# ---- F: production Main unchanged; nothing left running ----------------------------------------------------
step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $SD/probe.py main $H $rt $sess) | redact
  for f in $OUT/*.pid(N); do
    local pid=$(cat $f)
    if kill -0 $pid 2>/dev/null; then print "STILL RUNNING: ${f:t:r} pid $pid (started by this script); stop it with: kill $pid"; else print "ended: ${f:t:r} pid $pid"; fi
  done
  print "PASS/FAIL summary:"; grep -h '^\(PASS\|FAIL\)' $OUT/*.txt(N) | sort | uniq
}

case $STEP in
  00) step_00 2>&1 | redact | tee $OUT/00.txt ;;
  00u) step_00u ;;
  B1|B2|C1|C2|C3|P1|P2|E1|E2|D1|D2|D3|F) step_$STEP ;;
  *) print "usage: zsh ${0:A} <00|00u|B1|B2|C1|C2|C3|P1|P2|E1|E2|D1|D2|D3|F>" ;;
esac
