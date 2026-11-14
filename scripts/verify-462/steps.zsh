#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 462 real-host check: a member's agents-tool Codex child (gpt-6-luna) runs `sleep 462` in its shell tool (own
# session, below the Codex app-server); its owner Worker and the app-server's group are SIGKILLed; one reconciling
# read must stop the escaped tool processes through the recorded descendants (tool_descendants), and nothing else.
# Adapted from scripts/verify-459/steps.zsh (the Main and the member stay Claude, as there).
# The child's model comes from the project's only Codex preset, codex_child (gpt-6-luna; probe.py prepare): the
# create names no model, since GraphTraj's agents driver refuses a selected model (invalid-config).
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/462-codex-child-tool-process-reclaim/scripts/verify-462/steps.zsh <00|00u|01|02|03>
# 00  Main. preflight: scratch venv from COMMIT, isolated project, Codex login state (yes/no only) and a one-line
#     gpt-6-luna (the codex_child preset's model) answer, the Claude Main's one-line answer, probe Task ready, and a line proving the fix is in the venv.
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust.
# 01  Main. background `claude -p` Main: swarm -> member creates a Codex child whose shell runs exactly `sleep 462`
#     (no model in the create: the codex_child preset gives gpt-6-luna)
#     and ends its turn; Main polls until CHILD-RUNNING and stops.
# 02  Main. waits (<= 9 min) for 01's Main; refuses unless the child's descendants record lists a `sleep 462`;
#     starts three bystanders, SIGKILLs ONLY the child's app-server process group (start time checked, own group,
#     carries the child's marker); the owner stays alive. CHECK A residue alive, B owner-side reclaim (or, after
#     30 s, one reconciling read) stopped it, C nothing left, D bystanders alive. Nothing to act on fails.
# 03  Main. full suite at HEAD in the background (self-terminating after 25 min).
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
# Rehearsal without a model: VERIFY462_NO_MODEL=1 (00 stops before Codex and Claude Code; 02 runs on a stub from 'probe.py stub').
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/462-codex-child-tool-process-reclaim
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY462_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY462_BASE:-$H/tmp/462/verify}
OUT=${VERIFY462_OUT:-$H/.graphtraj/core/state/tasks/462-codex-child-tool-process-reclaim/realhost/reopen}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
CODEX_MODEL=gpt-6-luna
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
PID01=$OUT/01-main.pid
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY462_CLAUDE:-} ]] && { print -r -- $VERIFY462_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
# click 8.5.0, yaml and websockets from production, copied (never changed there) into a venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
  [[ $(cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print(m.version("click"))') == 8.5.0 ]] \
    || { print "STOP: click in $1 is not production's 8.5.0"; return 1; }
}
# Wait (<= 9 min) for a background claude -p started by this script; never a standalone sleep.
main_wait() {
  $VV/bin/python -I -c 'import os, sys, time
try:
    pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError):
    print("STOP: no pid file", sys.argv[1] + "; run the previous step first"); sys.exit(2)
deadline = time.time() + 540
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("Main claude -p", pid, "ended"); sys.exit(0)
    time.sleep(5)
print("Main claude -p", pid, "still running after 9 min"); sys.exit(1)' $1
}
# PROBE_OUT lets the probe find 01's Main stream (which member 01 created).
probe() { (cd $P && clean PROBE_OUT=$OUT VERIFY462_STUB_TOOL_GONE=${VERIFY462_STUB_TOOL_GONE:-} $VV/bin/python -I $SD/probe.py "$@") }
# STOP, changing nothing, while an earlier run's Main or a 'sleep 462' still lives. Signals nothing.
guard() { clean $CONDA -I $SD/probe.py idle $OUT - }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  guard || return 1
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import inspect, graftling.control as c, graphtraj.execution.agent_driver as d
import graftling.codex.managed_session as m
print("control:", c.__file__)
print("462 fix: reconcile reads tool_descendants:", "read_sidecar" in inspect.getsource(c._stop_escaped),
      "| Codex owner samples:", "DescendantSampler" in inspect.getsource(m.CodexManagedExecution.__init__),
      "| Codex owner reclaims:", "stop_tool_processes" in inspect.getsource(m.CodexManagedExecution._reclaim_tools),
      "| agents driver records Codex:", "\"codex\"" in inspect.getsource(d.AdapterDriver.start).replace(chr(39), chr(34)).split("member_marker", 1)[1].split("\n", 1)[0])') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 462 probe" > README.md && git add README.md \
      && git -c user.name=462 -c user.email=462@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  probe prepare $P $MODEL || { print "STOP: probe Task is not ready (text above)"; return 1; }
  say "isolation: GraphTraj resolves the project's own .graphtraj, not the Harness's"
  (cd $P && clean $VV/bin/python -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve()
own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own)
sys.exit(0 if found == own else 1)') || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  print "claude --version: $(clean $(claude_bin) --version 2>&1 | tail -1)   (expected 2.1.323)"
  print "codex --version: $(clean $(command -v codex) --version 2>&1 | tail -1)"
  [[ -n ${VERIFY462_NO_MODEL:-} ]] && { print "VERIFY462_NO_MODEL set: stopping before Codex and Claude Code (rehearsal)."; return 0; }
  say "Codex: version, login state (yes/no only; no account or key text) and one line from $CODEX_MODEL"
  local X=$(command -v codex)
  [[ -n $X ]] || { print "STOP: no codex on PATH"; return 1; }
  print "codex: $X $(clean $X --version 2>/dev/null | tail -1)"
  if clean $X login status 2>&1 | grep -q 'Logged in'; then print "codex logged in: YES"; else
    print "codex logged in: NO"; print "STOP: USER logs in with 'codex login' in Terminal, then Main reruns 00."; return 1; fi
  (cd $P && clean $X exec -m $CODEX_MODEL --skip-git-repo-check --sandbox read-only --json 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: AGENTS: then the absolute directory of every AGENTS.md whose instructions you were given, separated by spaces, or NONE. Use no tool.' \
      < /dev/null > $OUT/00-codex-stream.jsonl 2> $OUT/00-codex-stderr.txt)
  print "codex exec rc=$? model requested: $CODEX_MODEL"
  $VV/bin/python -I -c 'import json,sys
texts, models = [], set()
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    item = d.get("item") or {}
    if item.get("type") == "agent_message": texts.append(item.get("text"))
    if isinstance(d.get("model"), str): models.add(d["model"])
print("codex result:", texts[-1] if texts else None, "| models seen in stream:", sorted(models) or "(not reported)")
harness, project = sys.argv[2], sys.argv[3]
leaked = [w for w in (texts[-1] if texts else "").split() if w.startswith(harness) and not w.startswith(project)]
print("codex AGENTS.md from the Harness:", leaked or "none")
sys.exit(0 if texts and "MODEL OK" in texts[-1] and not leaked else 1)' $OUT/00-codex-stream.jsonl $H $P \
      || { print "STOP: Codex gave no MODEL OK. stderr (last 300 chars):"; tail -c 300 $OUT/00-codex-stderr.txt; return 1; }
  local C=$(claude_bin)
  [[ -f $BASE/settings.local.json.keep ]] && mkdir -p $P/.claude && cp -p $BASE/settings.local.json.keep $P/.claude/settings.local.json
  (cd $P && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write) || return 1
  # Claude Code also loads CLAUDE.md files from every parent directory; exclude the Harness's (claudeMdExcludes).
  # The builtin plugin cc-plugin-agents-md loaded the Harness AGENTS.md (reopen 00, run 1): disable it for this
  # project only. The probe Main and member run in this project and read this same file.
  $VV/bin/python -I -c 'import json, sys
from pathlib import Path
harness, path = sys.argv[1], Path(sys.argv[2])
settings = json.loads(path.read_text()) if path.is_file() else {}
settings["claudeMdExcludes"] = sorted({*settings.get("claudeMdExcludes", []), harness + "/CLAUDE.md",
    harness + "/CLAUDE.local.md", harness + "/.claude/CLAUDE.md", harness + "/**/CLAUDE.md", harness + "/**/CLAUDE.local.md",
    harness + "/AGENTS.md", harness + "/**/AGENTS.md"})
settings["enabledPlugins"] = {**settings.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + "\n")
print("claudeMdExcludes in", path, ":", settings["claudeMdExcludes"])
print("enabledPlugins in", path, ":", settings["enabledPlugins"])' $H $P/.claude/settings.local.json || return 1
  say "host answers one line with $MODEL (login check; no tool)"
  (cd $P && clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' > $OUT/00-model-stream.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  $VV/bin/python -I -c 'import json,sys
agents_md = False
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d.get("type") == "system" and d.get("subtype") == "init":
        names = [p.get("name") if isinstance(p, dict) else p for p in d.get("plugins", [])]
        agents_md = any("cc-plugin-agents-md" in str(name) for name in names)
        print("plugins loaded:", names)
        print("cc-plugin-agents-md loaded:", "YES" if agents_md else "NO")
    if d.get("type") == "result":
        text = d.get("result") or ""
        print("result:", text, "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))
        leaked = [w for w in text.split() if w.startswith(sys.argv[2]) and not w.startswith(sys.argv[3])]
        print("claude memory from the Harness:", leaked or "none")
        if not leaked and agents_md:
            print("NOTE: cc-plugin-agents-md is still listed, but no Harness file was reported; going on.")
        sys.exit(1 if leaked or "MODEL OK" not in text else 0)
sys.exit(1)' $OUT/00-model-stream.jsonl $H $P \
      || { print "STOP: claude -p gave no MODEL OK, or loaded a Harness CLAUDE.md/AGENTS.md (above). stderr:"; head -c 300 $OUT/00-model-stderr.txt; print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "plugin check: the init record must list graphtraj-claude-host"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"
    return 1
  fi
  print "Success: '462 fix: reconcile reads tool_descendants: True | Codex owner samples: True | Codex owner reclaims: True |"
  print "agents driver records Codex: True', deps click 8.5.0, 'roles OK', 'task 1 ready', 'codex logged in: YES',"
  print "'codex result: MODEL OK', 'codex AGENTS.md from the Harness: none', 'claude memory from the Harness: none',"
  print "'graphtraj runner directory: ... | project own: True', result 'MODEL OK' with $MODEL, 'graphtraj-claude-host loaded: YES'."
  next "zsh $THIS 01"
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: folder trust is recorded only through this dialog; claude -p never asks, and Main must not edit ~/.claude.json."
  next "Main: zsh $THIS 00"
}

step_01() {
  say "[01] Main. starts the probe Main in the background. Dialog: none. Returns at once; then run 02."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  guard || return 1
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  local C=$(claude_bin) S=$OUT/01-main-stream.jsonl
  rm -f $PID01 $S  # 471: a fresh stream; its creation time is this dispatch's time (probe.py member)
  local member='Use only the agents tool (mcp__agents__agents). Execute feature create with arguments {"runtime": "codex", "instruction": "Use your shell tool once to run exactly: sleep 462 . Wait for it. Then reply DONE-462."}. Reply with the one line CREATE <agent> <execution> from its result and end your turn at once. Do not call wait or status. Read no files and run no shell command yourself.'
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  print -r -- "$swarm" > $OUT/01-swarm-arguments.json
  local W="env PROBE_OUT=$OUT $VV/bin/python $SD/probe.py child $P 100"
  print -r -- "1. Call mcp__agents__tasks once with exactly these arguments: $swarm
Print its raw result text on one line starting with SWARM-RESULT.
2. Send nothing to the member. Run this exact Bash command, one call after another, until one prints CHILD-RUNNING (the member's turn ended and its child's sleep 462 runs), at most 5 times: $W
3. Print CHILD-RUNNING (or CHILD-NOT-RUNNING after 5 calls) and stop. Do not retire, interrupt or message anything." > $OUT/01-main-prompt.txt
  print "dispatch at $(date +%T); prompt: $OUT/01-main-prompt.txt"
  (cd $P && clean nohup $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      --allowedTools "mcp__agents__tasks,Bash($W)" < $OUT/01-main-prompt.txt > $S 2> $OUT/01-main-stderr.txt &
   print $! > $PID01)
  print "Main claude -p pid $(cat $PID01) (in $PID01), stream $S"
  print "The child's 'sleep 462' ends by itself about 7.7 min after it starts: run 02 right after 01's Main ends."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. waits for 01's Main (<= 9 min); kills ONLY the child's app-server group, waits <= 30 s for the owner's reclaim, CHECK A-D. Dialog: none."
  if [[ -n ${VERIFY462_NO_MODEL:-} ]]; then
    print "VERIFY462_NO_MODEL set: stub member and child instead of 01 (rehearsal)."
    probe stub $P - || return 1
  else
    main_wait $PID01
    case $? in
      0) ;;
      1) print "STOP: rerun 02 later (01's Main still runs)"; return 1 ;;
      *) return 1 ;;
    esac
    grep -o 'CHILD-RUNNING\|CHILD-NOT-RUNNING\|SWARM-RESULT[^"]*' $OUT/01-main-stream.jsonl | sort | uniq -c
  fi
  probe child $P 1
  probe kill $P $OUT/02-kill.json
  local rc=$?
  print ""
  print "Success: 'summary: ALL PASS'. A a recorded 'sleep 462' alive right after the app-server is gone; B the owner's"
  print "codex-termination record (or the reconcile path, labelled) lists it, same pid, in stopped, remaining [], no error;"
  print "C no recorded descendant and no 'sleep 462' alive; D the three bystanders alive. Nothing to act on is a FAIL."
  print "A STOP line means nothing was signalled."
  next "zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV > $OUT/03-suite.txt 2>&1 || { cat $OUT/03-suite.txt; return 1; }
  cat $OUT/03-suite.txt
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee -a $OUT/03-suite.txt
  rm -rf $OUT/03-shards
  (cd $WT && nohup zsh $THIS _03run >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time): tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows '== totals:'; failing IDs are in $OUT/03-shards/failures.txt."
}

step__03run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit.
  clean $SV/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $OUT/03-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $OUT/03-suite.txt | tail -1)"
  print "== baseline: compare with the dev full-suite run Main last used (462 base b3d522ad)"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
