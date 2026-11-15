#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 483: 373 and 401 with Codex as Main, in a FRESH isolated project under the Harness tmp/483 (never tmp/444).
# Trimmed from scripts/verify-444 (Codex-Main checks only). The production Claude Main is never yielded or changed.
#   zsh <this file> <00|00u|A1|A2|A3|I1|I2|F>
# Order: 00 -> (00u, USER, only if 00 says so) -> A1 A2 A3 (codex exec Main: 373, 401-exec) -> I1 (USER, interactive
# Codex) -> I2 (401-interactive) -> F. Each wait has a limit (README); steps signal only processes they started.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
BASE=${VERIFY483_BASE:-$H/tmp/483}
P=$BASE/project
OUT=${VERIFY483_OUT:-$H/.graphtraj/core/state/tasks/483-codex-main-373-401-recheck/realhost}
RT=${VERIFY483_RT:-$H/.venv-runtime}
PY=$RT/bin/python
MODEL=claude-opus-5-5
CODEX_MODEL=gpt-6-luna
STEP=${1:-help}
path=($RT/bin /opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY483_CLAUDE:-} ]] && { print -r -- $VERIFY483_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
# Hosts run without this shell's GraphTraj Session variables (Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
probe() { (cd $P && clean $PY -I $SD/probe.py "$@"); }
# A foreground host call with a hard limit (seconds) via perl alarm.
limit() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
wait_pid() { $PY -I -c 'import os, sys, time
try: pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError): print("STOP: no pid file", sys.argv[1], "- run the previous step first"); sys.exit(2)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("host pid", pid, "ended"); sys.exit(0)
    time.sleep(5)
print("host pid", pid, "still running after", sys.argv[2], "s; rerun this step (same limit)"); sys.exit(1)' $1 $2; }
pause() { $PY -I -c 'import sys, time; time.sleep(float(sys.argv[1]))' $1; }
bg() { local name=$1; shift; (cd $P && clean nohup "$@" < $OUT/$name-prompt.txt > $OUT/$name-main-stream.jsonl 2> $OUT/$name-stderr.txt & print $! > $OUT/$name.pid); print "$name host pid $(cat $OUT/$name.pid); stream $OUT/$name-main-stream.jsonl"; }
MCP=(-c "mcp_servers.graphtraj.command=\"$RT/bin/graphtraj-mcp\"" -c "mcp_servers.graphtraj.cwd=\"$P\"" -c 'mcp_servers.graphtraj.default_tools_approval_mode="approve"')
CODEX_MAIN=(exec -m $CODEX_MODEL --skip-git-repo-check --json $MCP -c 'approval_policy="never"')
thread_of() { $PY -I -c 'import json,sys
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    if d.get("type") == "thread.started": print(d.get("thread_id")); break' $1 2>/dev/null; }
# Every completed mcp_tool_call in a codex --json stream: OK/BLOCKED with the raw error or result head.
mcp_calls() { $PY -I -c 'import json,sys
n = 0
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    it = d.get("item") or {}
    if it.get("type") == "mcp_tool_call" and d.get("type") == "item.completed":
        n += 1; res = it.get("result"); err = it.get("error") or (it.get("status") if it.get("status") not in ("completed", None) else None)
        text = "".join(c.get("text", "") for c in ((res or {}).get("content") or []) if isinstance(c, dict))
        ok = res is not None and not err and "error:" not in text[:400]
        print("MCP", json.dumps(it.get("arguments"))[:120], "->", "OK" if ok else "BLOCKED", (json.dumps(err) if err else text)[:600].replace("\n", " | "))
print("mcp calls completed:", n)' $1; }
ASK373="{\"action\":\"execute\",\"feature\":\"swarm\",\"arguments\":{\"tasks\":[{\"task_id\":\"1\",\"role\":\"asker\",\"instruction\":\"Run these two shell commands, one Bash call each, in this order: touch $BASE/373-codex-a and touch $BASE/373-codex-b. Each needs approval; wait for each answer. Then reply with one line saying which were allowed or denied.\"}]}}"
DENY='Then repeat, at most 12 rounds, until the asker execution has ended: using the agents tool, action requests with agent set to the asker alias from SWARM-RESULT; for EVERY pending native request call the agents tool action reply with that agent, request set to the request object exactly as returned, and response {"behavior": "deny", "message": "483 probe denies"}; print one line DENIED <request id> per reply. Between rounds use the agents tool action wait with that agent and timeout_seconds 15 (never a shell command). Finally print the asker final reply on one line starting with ASKER-RESULT and stop. Never allow a request.'
CREATE() { print -r -- "{\"action\":\"execute\",\"feature\":\"create\",\"arguments\":{\"runtime\":\"claude\",\"configuration\":\"advisor\",\"name\":\"$1\",\"instruction\":\"Reply with exactly one line: PONG-$1. Use no tools.\"}}"; }

step_00() {
  say "[00] preflight. Dialog: none. Output also in $OUT/00.txt"
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; production graphtraj: $($PY -I -c 'import graphtraj; print(graphtraj.__file__)' 2>&1)"
  print "claude --version: $(clean $(claude_bin) --version 2>&1 | tail -1) | codex --version: $(clean codex --version 2>&1 | tail -1)"
  say "production current Main (read only; F compares)"
  (cd $H && clean $PY -I -c 'import json
from pathlib import Path
p = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-1] if p.is_file() else {}
print(last.get("runtime", "none"), last.get("session", "none"))') > $OUT/00-production-main.txt
  print "production Main: $(cat $OUT/00-production-main.txt)"
  [[ -s $OUT/00-production-main.txt || -n ${VERIFY483_NO_MODEL:-} ]] || { print "STOP: production continuity record unreadable; F could not compare"; return 1; }
  say "fresh isolated project $P (own git repo; never tmp/444)"
  if [[ -d $P/.git ]]; then print "existing project $P: git init and graphtraj setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 483 probe README first line" > README.md && git add README.md \
      && git -c user.name=483 -c user.email=483@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $RT/bin/graphtraj setup | tail -2) || return 1
  fi
  probe prepare $P; local prc=$?
  case $prc in
    0) ;;
    2) print "STOP: graphtraj task register/update failed (text above)"; return 1 ;;
    3) print "STOP: roles invalid: graphtraj doctor did not report 'roles: OK' (text above)"; return 1 ;;
    4) print "STOP: Task 1 is not ready in the task graph (text above)"; return 1 ;;
    *) print "STOP: probe.py prepare failed rc=$prc (text above)"; return 1 ;;
  esac
  print "probe Task 1 readiness (graphtraj task graph, raw):"
  (cd $P && clean $RT/bin/graphtraj task graph 2>&1 | grep -E "task_id|status|budget" | head -8)
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  say "Claude host configuration for the asker/advisor members; Harness AGENTS.md/CLAUDE.md excluded (project .claude/settings.local.json only)"
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
  (cd $P && clean $PY -I -c 'import json
from pathlib import Path
from graphtraj.runtimes.codex.finalize import hook
Path(".codex/hooks.json").write_text(json.dumps(hook(Path("."), {}), indent=2) + "\n"); print("wrote .codex/hooks.json")') || return 1
  probe claims $P | tail -1
  [[ -n ${VERIFY483_NO_MODEL:-} ]] && { print "VERIFY483_NO_MODEL set: stopping before any model or host call (rehearsal)."; return 0; }

  local ASK='Reply with exactly three lines. Line 1: MODEL OK. Line 2: MODEL: your model name. Line 3: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'
  print -r -- "$ASK" > $OUT/00-ask.txt
  say "(a) codex exec $CODEX_MODEL one-line answer (limit 300 s); login; Harness instruction files must be none"
  if clean codex login status 2>&1 | grep -q 'Logged in'; then print "codex logged in: YES"; else print "codex logged in: NO"; fi
  (cd $P && limit 300 codex exec -m $CODEX_MODEL --skip-git-repo-check --sandbox read-only - < $OUT/00-ask.txt > $OUT/00-codex.txt 2>&1)
  say "(a') claude -p one-line answer (the asker/advisor member host; limit 300 s)"
  (cd $P && limit 300 $(claude_bin) -p --model $MODEL --output-format json --mcp-config $P/.mcp.json --strict-mcp-config < $OUT/00-ask.txt > $OUT/00-claude.txt 2>&1)
  for host in codex claude; do
    local f=$OUT/00-$host.txt ok=BLOCKED leak=""
    grep -q 'MODEL OK' $f && ok=OK
    grep -oE "$H/[^ \"]*(AGENTS|CLAUDE)\.md" $f | grep -v "^$P/" | head -1 | read leak
    print "$host answer: $ok | model line: $(grep -oE 'MODEL: [^\"\\]*' $f | head -1) | Harness instruction file loaded: ${leak:-none}"
    [[ $ok == OK ]] || { print "raw $host error (tail):"; tail -5 $f; }
  done
  say "(b) codex exec GraphTraj MCP (limit 300 s): agents describe create schema:true; tasks task_graph"
  print -r -- 'Call tools exactly twice, nothing else. 1. The graphtraj agents tool with {"action": "describe", "feature": "create", "schema": true}. 2. The graphtraj tasks tool with {"action": "execute", "feature": "task_graph", "arguments": {}}. Then reply with one line: MCP-DONE.' > $OUT/00-mcp-prompt.txt
  (cd $P && limit 300 codex $CODEX_MAIN - < $OUT/00-mcp-prompt.txt > $OUT/00-mcp-stream.jsonl 2> $OUT/00-mcp-stderr.txt)
  mcp_calls $OUT/00-mcp-stream.jsonl
  for key in runtime configuration name instruction; do
    grep -q "\\\\\"$key\\\\\"\|\"$key\"" <(grep '"describe"' $OUT/00-mcp-stream.jsonl | grep item.completed) && print "create schema key $key: YES" || print "create schema key $key: NO"
  done
  grep 'task_graph' $OUT/00-mcp-stream.jsonl | grep -q 'item.completed' && grep 'task_graph' $OUT/00-mcp-stream.jsonl | grep item.completed | grep -qE "main-swap-probe.{0,400}ready|ready.{0,400}main-swap-probe" \
    && print "task_graph shows probe Task 1 ready: YES" || print "task_graph shows probe Task 1 ready: NO (raw in 00-mcp-stream.jsonl)"
  say "(c) interactive Codex form for 401 (I1): host entries checkable without the user"
  clean codex --help 2>&1 | grep -qiE '^\s*app-server' && print "codex app-server subcommand: YES" || print "codex app-server subcommand: NO"
  clean codex app-server --help 2>&1 | grep -qi 'proxy' && print "codex app-server proxy (send_event's channel): YES" || print "codex app-server proxy: NO (raw: $(clean codex app-server --help 2>&1 | head -3 | tr '\n' ' '))"
  print "not checkable without the user: the interactive Codex folder/hook trust dialogs for $P (I1 header names them)"
  say "continuity claims after 00's probes (444 lesson: did the preflight claim Main in the project?)"
  probe claims $P
  grep -q '"runtime": *"codex"' $P/.graphtraj/runner/main-sessions/continuity.jsonl 2>/dev/null \
    && print "00's codex exec probes claimed Main in $P: YES (Codex SessionStart hook ran; A1 re-claims with its own thread)" \
    || { print "00's codex exec probes claimed Main in $P: NO -> the project hooks are not trusted; without a codex claim a root Agent's end is not routed (agents.py:290-292)"; next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"; return 1; }
  print "Success: 'codex logged in: YES', both 'answer: OK' with 'Harness instruction file loaded: none', roles OK, task 1 ready, 'project own: True',"
  print "two MCP lines OK, four 'create schema key … YES', 'task_graph shows probe Task 1 ready: YES', 'app-server proxy … YES', claimed Main: YES."
  next "zsh $THIS A1"
}

step_00u() {
  say "[00u] USER, once, only when 00 says so. Dialog: native trust dialogs (Codex: trust this folder -> 'Yes'; approve the project hooks $P/.codex/hooks.json; Claude: 'Yes, proceed' and approve the project MCP). Plain macOS Terminal:"
  print "  cd $P && codex -m $CODEX_MODEL     -> trust the folder, approve the hooks if asked; then /exit"
  print "  cd $P && claude                    -> 'Yes, proceed'; approve the project MCP 'agents' if asked; then /exit"
  next "zsh $THIS 00"
}

# ---- A: codex exec Main: 373 (two requests denied) and 401 (exec form) ------------------------------------
step_A1() {
  say "[A1] background Codex Main ($CODEX_MODEL, codex exec) in $P. Dialog: none (exec has no UI; approval_policy never; only mcp_servers.graphtraj approved for this run). Returns at once."
  print -r -- "First, using only the graphtraj agents tool: call it once with exactly $(CREATE h401); print one line H401-CREATE <agent id>. Do not wait for it and never call status or wait for it.
Second, using only the graphtraj tasks tool: call it once with exactly $ASK373 and print its raw result on one line starting with SWARM-RESULT.
$DENY" > $OUT/A1-prompt.txt
  bg A1 codex $CODEX_MAIN -
  next "zsh $THIS A2 2>&1 | tee $OUT/A2.txt"
}
step_A2() {
  say "[A2] waits (<= 540 s) for A1; judges 373; records h401's push outcome; starts the exec resume turn. Dialog: none."
  wait_pid $OUT/A1.pid 540 || return 1
  local thread=$(thread_of $OUT/A1-main-stream.jsonl); print -r -- "$thread" > $OUT/A1.thread
  print "Codex Main thread: ${thread:-NONE}"
  probe count $OUT/A1-main-stream.jsonl H401-CREATE SWARM-RESULT DENIED ASKER-RESULT
  probe current $P codex ${thread:-none} >/dev/null && print "PASS A entry: A1's Codex thread $thread is the current Main of $P" || { print "FAIL A entry: A1's thread ${thread:-NONE} is not the current Main:"; probe current $P codex ${thread:-none}; }
  probe requests $P $OUT A1 codex
  say "401 (exec): h401's control record before any pull (notification = outcome of the push to the codex exec Main)"
  probe agent $P h401 | tee $OUT/A2-h401.txt
  probe ends $P $OUT h401 A1-main-stream.jsonl
  probe inbox $P > $OUT/A2-inbox.txt; print "inbox: $OUT/A2-inbox.txt"
  [[ -n $thread ]] || { print "STOP: no Codex thread id; 401 resume cannot run"; return 1; }
  local id=$(grep -oE 'AGENT h401 id [^ ]+' $OUT/A2-h401.txt | head -1 | awk '{print $4}')
  print "h401 agent id: ${id:-NONE}"
  print -r -- "Before any tool: quote every GraphTraj notice or host event you were given since your previous turn (alias, event, first message line), and print one line H401-COUNT <n> with how many name agent ${id:-h401} or PONG-h401. Then, using only the graphtraj agents tool, action status with agent ${id:-h401} (the agent id, not the name) and print its notification field on one line starting with H401-NOTIFICATION. Stop." > $OUT/A3-prompt.txt
  bg A3 codex exec resume $thread -m $CODEX_MODEL --skip-git-repo-check --json $MCP -c 'approval_policy="never"' -
  next "zsh $THIS A3 2>&1 | tee $OUT/A3.txt"
}
step_A3() {
  say "[A3] waits (<= 300 s) for the exec resume turn; judges 401 for the codex exec form. Dialog: none."
  wait_pid $OUT/A3.pid 300 || return 1
  probe count $OUT/A3-main-stream.jsonl PONG-h401 H401-COUNT H401-NOTIFICATION
  mcp_calls $OUT/A3-main-stream.jsonl
  probe ends $P $OUT h401 A1-main-stream.jsonl A3-main-stream.jsonl; local ends_rc=$?
  local note=$(grep -oE 'NOTIFICATION [^ ]+ [a-z]+' $OUT/A2-h401.txt | head -1 | awk '{print $3}')
  print "h401 notification recorded at A2 (before the resume's status pull): ${note:-none}"
  case "$ends_rc:${note:-none}" in
    0:*) print "401-EXEC: delivered once to the codex exec Main (stream, by event identity)" ;;
    *:unconfirmed|*:unavailable|*:held) print "401-EXEC: EXEC-NO-CHANNEL: the push was attempted and failed (notification ${note}); Codex is a push host with no queue (main_continuity.py:241-246), so nothing retries; resume shows it only through a status pull. Use I1/I2 (interactive Codex)." ;;
    *:delivered) print "401-EXEC: POSSIBLE LOSS: Codex accepted the host event (send_host_event returned, notification delivered) but no Main stream shows it. Raw evidence: $OUT/A2-h401.txt, A1/A3 streams. Main registers it; no fix here." ;;
    *) print "401-EXEC: NOT SETTLED: notification ${note:-none} (push not taken/attempted, or no record); raw $OUT/A2-h401.txt" ;;
  esac
  probe agent $P h401
  next "USER step: zsh $THIS I1   (prints what the user runs and pastes)"
}

# ---- I: interactive Codex Main (user's terminal) for 401 ------------------------------------------------
step_I1() {
  $PY -I -c 'import time; print(time.time())' > $OUT/I1.start
  print -r -- "Using only the graphtraj agents tool: call it once with exactly $(CREATE h401i); print one line H401I-CREATE <agent id>. Do not call wait or status for it, and end your turn. When a GraphTraj notice about it arrives later, quote its alias, event and execution on one line starting with H401I-NOTICE and stop." > $OUT/I1-prompt.txt
  say "[I1] USER, in your own macOS Terminal. Dialog: Codex folder trust for $P -> choose 'Yes' (only if asked) and hook approval for $P/.codex/hooks.json -> approve (only if asked); nothing else."
  print "  1. cd $P && codex -m $CODEX_MODEL ${(qq)MCP[@]}"
  print "  2. paste this one prompt (also in $OUT/I1-prompt.txt):"
  print -r -- "$(cat $OUT/I1-prompt.txt)"
  print "  3. wait until a new turn starts by itself and prints H401I-NOTICE, or 3 minutes; wait one more minute (a second delivery would show); then /exit."
  next "zsh $THIS I2 2>&1 | tee $OUT/I2.txt"
}
step_I2() {
  say "[I2] read only: judges 401 for the interactive Codex Main by event identity (records + its rollout). Dialog: none."
  local start=$(cat $OUT/I1.start 2>/dev/null || print 0)
  local thread=$($PY -I -c 'import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / ".graphtraj/runner/main-sessions/continuity.jsonl"
c = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []
c = [x for x in c if x.get("runtime") == "codex" and float(x.get("at", 0)) >= float(sys.argv[2])]
print(c[-1]["session"] if c else "")' $P $start)
  print "interactive Codex Main thread (codex claim after I1): ${thread:-NONE}"
  [[ -n $thread ]] || { print "FAIL I entry: no codex continuity claim since I1 (hooks not trusted, or I1 not run)"; probe claims $P; return 1; }
  probe agent $P h401i
  probe rollout $P h401i $thread
  probe inbox $P > $OUT/I2-inbox.txt; print "inbox: $OUT/I2-inbox.txt"
  next "zsh $THIS F 2>&1 | tee $OUT/F.txt"
}

step_F() {
  say "[F] read only. Dialog: none."
  local rt sess; read rt sess < $OUT/00-production-main.txt
  (cd $H && clean $PY -I $SD/probe.py main $H $rt $sess)
  for f in $OUT/*.pid(N); do
    local pid=$(cat $f)
    if kill -0 $pid 2>/dev/null; then print "STILL RUNNING: ${f:t:r} pid $pid (started by this script); stop it with: kill $pid"; else print "ended: ${f:t:r} pid $pid"; fi
  done
  print "PASS/FAIL and 401 classification summary:"; grep -hE '^(PASS|FAIL|401-EXEC)' $OUT/*.txt(N) | sort | uniq
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt; return ${pipestatus[1]} ;;
  00u|A1|A2|A3|I1|I2|F) step_$STEP ;;
  *) print "usage: zsh $THIS <00|00u|A1|A2|A3|I1|I2|F>" ;;
esac
}
dispatch; exit $?
