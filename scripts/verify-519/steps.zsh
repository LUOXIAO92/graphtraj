#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 519 Main-run steps: when does a standby Claude member's last turn reach its graftling archive, its Claude
# transcript and session_read?   zsh scripts/verify-519/steps.zsh <STEP>   (Main, from this Task's Worktree)
# Order: P -> Tu (USER, plain Terminal, one dialog) -> A -> B -> C.   S: rehearsal-only simulation (no model).
#   P   preflight: production install (read only), isolated project /private/tmp/standby-519/project (own git and
#       .graphtraj, project-only isolation settings, roles, probe Task 1), a one-line claude -p (model and login)
#   Tu  USER: trust the new project folder once (Claude Code's own dialog), then /exit
#   A   a Claude Main dispatches one Claude member; its one turn ends with marker M1; the Main calls session_read at once;
#       then this step observes both record files (right after the turn ended)
#   B   the member is standby (no process); after a fixed wait (60 s) the same observation, compared with A
#   C   a new Claude Main resumes the member with marker M2, waits, calls session_read; the observation, compared with
#       A and B (rewrite: inode, first bytes, metadata line; marker offset shift; size never shrinks)
# Uses the production .venv-runtime read only (python -I -B; PYTHONDONTWRITEBYTECODE=1 for every child), never writes
# the Harness .mcp.json, CONTEXT.md, docs/ or the venv. Each step writes only under <Harness>/tmp/519/<step>-<time>/
# (and the isolated project under /private/tmp/standby-519/). No step signals a process it did not start.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=${SD:h:h}                                            # this Task Worktree (scripts/verify-519/..)
# VERIFY519_* are set only by a rehearsal (scratch BASE/OUT, a stub claude first on PATH); the defaults are real.
H=${VERIFY519_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${VERIFY519_BASE:-/private/tmp/standby-519}        # outside the Harness: no parent .mcp.json/instructions/.graphtraj
P=$BASE/project
OUTBASE=${VERIFY519_OUT:-$H/tmp/519}
RTPY=${VERIFY519_PY:-$H/.venv-runtime/bin/python}       # production graftling 0.6.0 + GraphTraj, read only
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
ISO=$WT/scripts/verify-common/claude_isolation.py
OBS=$SD/obs519.py
STATE=$OUTBASE/state.env                                # member, session, transcript, markers, A/B observation files
MODEL=claude-opus-5-5
WAIT=${VERIFY519_WAIT:-60}
PROJECTS=${VERIFY519_PROJECTS:-$HOME/.claude/projects}
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY519_STUB:-} ]] && path=($VERIFY519_STUB $path)   # rehearsal only: stub claude first

BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} PYTHONDONTWRITEBYTECODE=1 "$@"; }
out_dir() { D=$OUTBASE/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D && print -r -- "output: $D"; }
next() { print -r -- "next (paste): zsh $THIS $*"; }
obs() { clean $RTPY -I -B $OBS "$@"; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
cv() { local C=$(claude_bin); print -r -- "claude: $C -> ${C:A} | version: $($C --version 2>&1 | head -1)"; }
isolation() {  # verify-465 / adopt-515: graphtraj root, git top level, no CLAUDE.md at or above the project
  clean $RTPY -I -B - $P <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('CLAUDE.md', 'CLAUDE.local.md') if (p / n).exists()]
leaks = [str(p / n) for p in project.parents for n in ('.mcp.json', 'AGENTS.md', '.graphtraj') if (p / n).exists()]
print(f'graphtraj project root: {root} | isolated: {root == project}')
print(f'git top level: {top} | isolated: {Path(top).resolve() == project if top else False}')
print(f'CLAUDE.md/CLAUDE.local.md at or above the project: {upward or "none"}')
print(f'.mcp.json/AGENTS.md/.graphtraj above the project: {leaks or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward and not leaks
print('isolation:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
}
project_init() {
  mkdir -p $P
  [[ -d $P/.git ]] || git -C $P init -q --initial-branch=main || return 1
  if ! git -C $P rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 519 standby probe" > $P/README.md
    git -C $P add README.md && git -C $P -c user.name=519 -c user.email=519@invalid commit -qm "Initial source" || return 1
  fi
  [[ -e $P/.graphtraj/core/config.yml || -e $P/.graphtraj/config.yml ]] || (cd $P && print -r -- y | clean ${RTPY:h}/graphtraj setup | tail -2) || return 1
  (cd $P && clean $RTPY -I -B $SD/prep519.py $P) || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
}
configure() {  # configuration --write (only the graphtraj entry), then 489's project-only isolation settings
  (cd $P && clean $RTPY -B -m graphtraj.runtimes.claude.host configuration --project $P --claude $(claude_bin) --write) >/dev/null \
    || { print "STOP: configuration --write failed"; return 1; }
  clean $CONDA -I $ISO settings $H $P
  print "isolated .mcp.json servers: $(clean $CONDA -I -c 'import json,sys; print(list(json.load(open(sys.argv[1]))["mcpServers"]))' $P/.mcp.json 2>&1) (expected ['graphtraj'])"
}
# The plugin gate before a paid step (verify-514 gate): init lists exactly graphtraj, mcp__graphtraj__agents, no
# untrusted-plugin warning. Before Tu the plugin is skipped (untrusted folder): NOT PASSED is then expected.
gate() {
  (cd $P && clean $BOUND 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json \
     --strict-mcp-config <<< 'Reply with one line: READY-519 and your exact model name. Use no tool.' > $D/gate.jsonl 2> $D/gate.err) \
     || print "claude rc=$? (142 = 120 s timeout)"
  clean $CONDA -I -c 'import json, sys
lines = []
for l in open(sys.argv[1], errors="replace"):
    try: lines.append(json.loads(l))
    except ValueError: pass
init = next((l for l in lines if l.get("subtype") == "init"), {}); res = next((l for l in lines if l.get("type") == "result"), {})
servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers", [])]
warnings = json.dumps(init.get("plugin_warnings", []))
tools = [t for t in init.get("tools", []) if t.startswith("mcp__")]
plugins = [p.get("name") if isinstance(p, dict) else p for p in init.get("plugins") or []]
print("claude model:", init.get("model"), "| answer:", str(res.get("result", ""))[:120].replace("\n", " "))
print("init mcp_servers:", servers, "| mcp tools:", tools, "| plugins:", plugins, "| plugin_warnings:", warnings[:300])
ok = [n for n, _ in servers] == ["graphtraj"] and "untrusted" not in warnings and "mcp__graphtraj__agents" in tools \
     and any("graphtraj-claude-host" in str(p) for p in plugins)
print("plugin gate:", "PASS" if ok else "NOT PASSED")
sys.exit(0 if ok else 1)' $D/gate.jsonl
}
main_run() {  # $1 prompt file: one bounded claude -p Main of the GraphTraj host plugin in the isolated project
  local S=$(uuidgen | tr A-Z a-z); print -r -- $S > $D/main-session.txt
  (cd $P && clean $BOUND 1200 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
     --mcp-config $P/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__agents,mcp__graphtraj__tasks \
     --session-id $S < $1 > $D/stream.jsonl 2> $D/stderr.txt) || print "claude rc=$? (142 = 20 min timeout)"
  date -u +%Y-%m-%dT%H:%M:%SZ > $D/main-ended.txt
}
result_lines() {  # lines of the Main's last result record starting with one of the given words
  clean $CONDA -I -c 'import json, sys
text = ""
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    if d.get("type") == "result": text = str(d.get("result", ""))
words = tuple(sys.argv[2:])
hits = [l.strip() for l in text.splitlines() if l.strip().startswith(words)]
print("\n".join(hits) if hits else "(none; the result text ends: " + text[-800:].replace("\n", " | ") + ")")' $D/stream.jsonl "$@"
}
transcript_of() { local f=($PROJECTS/*standby-519*/$1.jsonl(N)); print -r -- ${f[1]:-$PROJECTS/-private-tmp-standby-519-project/$1.jsonl}; }
member_ps() {  # read only: live processes naming the member session (standby: none expected); never signals
  local lines=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -F -- $1 | grep -v grep || true)
  print -r -- "processes naming session $1: ${lines:-none}"
}
need_state() { [[ -r $STATE ]] || { print "STOP: $STATE is missing; run A first"; exit 1; }; source $STATE; }
PREDICT='Predictions (code, see the report): graftling collects the turn while it runs and once more after Claude exits,
  before the execution reports completed (graftling claude/execution.py:1119-1146, outcome at 1157); every archive write
  replaces the whole file (sessions/archive.py:94-103, 336-349) and its line 1 holds pending drafts and accumulating
  observations (archive.py:364-366, 494-499). Hence:
  H2 (code):  A archive has M1 and session_read finds it; B identical to A (same inode, size, mtime);
              C archive inode CHANGED, line 1 grew by d bytes, M1 line number unchanged, M1 offset shifted by exactly +d;
              transcript inode same, first bytes same, M1 offset unchanged (append only); session_read finds M1 and M2.
  H1 (latency, the 515 inference) would show: A and B archive M1 ABSENT and session_read 0 hits; C present.
  H3 (Claude rewrites its transcript on --resume) would show: C transcript inode changed or first bytes CHANGED or SHRANK.'

case $STEP in
P) out_dir P; {
  print "[P] preflight. Dialog: none (no tool use; before Tu the folder is untrusted and the plugin is skipped). About 2 min."
  cv; print "zsh $ZSH_VERSION | worktree $WT $(git -C $WT rev-parse --short HEAD 2>&1) dirty files: $(git -C $WT status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  print "production install (read only): $(clean $RTPY -I -B -c 'import graftling, importlib.metadata as m; print("graftling", m.version("graftling"), "graphtraj", m.version("graphtraj"), "from", graftling.__file__.rsplit("/lib/", 1)[0])' 2>&1)"
  print "expected: graftling 0.6.0 (the code read for 519; its archive/collection files are identical to <Harness>/graftling main)"
  rc=0
  project_init || exit 1
  configure || exit 1
  isolation || rc=1
  print -r -- "-- one-line claude -p (model and login), judged by claude_isolation.py check (no Harness instruction file loaded)"
  clean $CONDA -I $ISO prompt PROBE-519 > $D/model-prompt.txt
  (cd $P && clean $BOUND 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json \
     --strict-mcp-config < $D/model-prompt.txt > $D/model.jsonl 2> $D/model.err) || print "claude rc=$? (142 = 120 s timeout)"
  clean $CONDA -I $ISO check $D/model.jsonl PROBE-519 $H $P $D/model-prompt.txt || rc=1
  print -r -- "-- plugin gate (information before Tu; A and C require PASS)"
  gate || print "(expected NOT PASSED before Tu: Claude Code loads the project plugin only in a trusted folder)"
  print "expected: 'roles OK', 'probe Task 1 ready', servers ['graphtraj'], 'isolation: OK', answer check OK with model $MODEL and logged in."
  print "P rc=$rc"
  (( rc == 0 )) && next "Tu    (USER, plain Terminal)" || print "fix the NOT OK lines above, then rerun P"
  exit $rc
} 2>&1 | tee $D/P.txt; exit ${pipestatus[1]} ;;

Tu)
  print "[Tu] USER in a plain Terminal (Main cannot answer dialogs). Dialog: one: Claude Code's 'Do you trust the files in this folder?' naming $P -> choose 'Yes, proceed'. Then type /exit (send no message). Should an MCP server approval for 'graphtraj' appear, approve it for this project. Any other dialog: press Esc and tell Main its title."
  print "  cd $P && claude"
  print "then Main: zsh $THIS A" ;;

A) out_dir A; {
  print "[A] Claude Main dispatches one Claude member; its one turn ends with M1; the Main calls session_read right after. Dialog: none. At most 20 min."
  cv
  (cd $P && clean $RTPY -I -B $SD/prep519.py $P) || exit 1
  configure || exit 1
  gate || { print "STOP: plugin gate not passed (above); no member was dispatched. Trust the folder: zsh $THIS Tu"; exit 1; }
  # The member composes the marker: its instruction holds the base and the suffix apart, so only its reply holds M1.
  BASEMARK=STANDBY519-$(date +%H%M%S); M1=$BASEMARK-R1; print -r -- $M1 > $D/marker.txt
  print -r -- "Use only the MCP tools mcp__graphtraj__tasks and mcp__graphtraj__agents. 1. With mcp__graphtraj__tasks execute swarm with arguments {\"tasks\":[{\"task_id\":\"1\",\"role\":\"claude_member\",\"instruction\":\"This is a scripted probe. Use no tool at all. Reply with exactly one line: the word $BASEMARK immediately followed by the three characters -R1 (no space between), then a space and turn-one-done. No quotes.\"}]} and print the raw result on one line starting with SWARM-RESULT. 2. Call mcp__graphtraj__agents with {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": <the member's agent id from step 1>, \"timeout_seconds\": 300}}, repeating until its execution has ended. 3. Immediately after that, call mcp__graphtraj__agents with {\"action\": \"execute\", \"feature\": \"session_read\", \"arguments\": {\"agent\": <the same agent id>, \"search\": \"$M1\"}} and print its raw result on one line starting with SESSION-READ-A. 4. Print one line MEMBER <the member's agent id> <its alias> <its session>. Stop." > $D/prompt.txt
  main_run $D/prompt.txt
  T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  print "Main ended $(<$D/main-ended.txt); observation starts $T0"
  print -r -- "-- Main's lines"; result_lines $D/stream.jsonl SWARM-RESULT SESSION-READ-A MEMBER REPLY | cut -c1-1500 | tee $D/main-lines.txt
  agent=$(awk '$1=="MEMBER"{print $2}' $D/main-lines.txt | tail -1); session=$(awk '$1=="MEMBER"{print $4}' $D/main-lines.txt | tail -1)
  if [[ -z $session || $session == *'<'* ]]; then
    print "MEMBER line incomplete; using the project's Claude agent records (newest last):"; obs member $P/.graphtraj/swarm | tee $D/members.txt
    agent=$(tail -1 $D/members.txt | cut -d' ' -f1); session=$(tail -1 $D/members.txt | cut -d' ' -f3)
  fi
  [[ -n $session && $session != None ]] || { print "STOP: no member session found (above)"; exit 1; }
  TR=$(transcript_of $session)
  print -r -- "member agent $agent | session $session | transcript $TR"
  obs snap A $P/.graphtraj/swarm $session $TR $M1 $D/A.json
  member_ps $session
  { print -r -- "agent=${(q)agent}"; print -r -- "session=${(q)session}"; print -r -- "TR=${(q)TR}"; print -r -- "M1=${(q)M1}"
    print -r -- "AJSON=${(q)D}/A.json"; } > $STATE
  print -r -- "state: $STATE"
  print -r -- $PREDICT
  print "Observable for A: 'archive: ... marker $M1: PRESENT' with an event line (not only the metadata line), 'search $M1 content text: hits >= 1', and SESSION-READ-A above with a hit. ABSENT / 0 hits supports H1."
  next "B      (waits ${WAIT} s; member $agent session $session)"
} 2>&1 | tee $D/A.txt; exit ${pipestatus[1]} ;;

B) out_dir B; {
  print "[B] standby: wait ${WAIT} s, then the same observation, compared with A. Dialog: none. No model. About $(( WAIT + 5 )) s."
  need_state
  print -r -- "member agent $agent | session $session | waiting ${WAIT} s from $(date -u +%H:%M:%SZ)"; sleep $WAIT
  obs snap B $P/.graphtraj/swarm $session $TR $M1 $D/B.json
  member_ps $session
  obs compare $AJSON $D/B.json
  print -r -- "BJSON=${(q)D}/B.json" >> $STATE
  print "expected (H2 and H1 alike, nothing writes while standby): archive and transcript inode same, size same, first bytes same, line 1 +0; marker lines unchanged; no process naming the session."
  print "Observable for H1 only: B archive marker ABSENT and 0 session_read hits, like A."
  next "C      (resumes member $agent, session $session)"
} 2>&1 | tee $D/B.txt; exit ${pipestatus[1]} ;;

C) out_dir C; {
  print "[C] a new Claude Main resumes the standby member with M2, waits, calls session_read; then the observation. Dialog: none. At most 20 min."
  need_state; cv
  configure || exit 1
  gate || { print "STOP: plugin gate not passed (above); the member was not resumed. Trust the folder: zsh $THIS Tu"; exit 1; }
  BASEMARK=${M1%-R1}; M2=$BASEMARK-R2; print -r -- $M2 > $D/marker.txt
  print -r -- "Use only the MCP tools mcp__graphtraj__agents and mcp__graphtraj__tasks. 1. Call mcp__graphtraj__agents with {\"action\": \"execute\", \"feature\": \"resume\", \"arguments\": {\"agent\": \"$agent\", \"message\": \"This is a scripted probe after standby. Use no tool at all. Reply with exactly one line: the word $BASEMARK immediately followed by the three characters -R2 (no space between), then a space and turn-two-done. No quotes.\"}} and print the raw result on one line starting with RESUME-RESULT. If resume is refused, describe resume with schema true, retry once with the documented arguments, and print both raw results. 2. Wait for it with mcp__graphtraj__agents wait (agent $agent, timeout_seconds 300), repeating until its execution has ended. 3. Immediately after that call mcp__graphtraj__agents session_read twice, {\"agent\": \"$agent\", \"search\": \"$M1\"} and {\"agent\": \"$agent\", \"search\": \"$M2\"}, and print each raw result on one line starting with SESSION-READ-C1 and SESSION-READ-C2. Stop." > $D/prompt.txt
  main_run $D/prompt.txt
  print "Main ended $(<$D/main-ended.txt)"
  print -r -- "-- Main's lines"; result_lines $D/stream.jsonl RESUME-RESULT SESSION-READ-C1 SESSION-READ-C2 REPLY | cut -c1-1500 | tee $D/main-lines.txt
  obs snap C $P/.graphtraj/swarm $session $TR $M1,$M2 $D/C.json
  member_ps $session
  print "\n-- A -> C (the 515 situation: sizes recorded at A, records read after the resume)"; obs compare $AJSON $D/C.json
  [[ -n ${BJSON:-} ]] && { print "\n-- B -> C"; obs compare $BJSON $D/C.json; }
  print -r -- $PREDICT
  print "Decide: H2 when the A->C archive line says 'inode CHANGED' and 'shift +d' equals the line-1 growth with the line number unchanged; the 515 symptom is reproduced when it also says 'beyond A's size ... YES'."
  print "        H1 when A/B said ABSENT and C PRESENT.  H3 when the transcript line says inode CHANGED, first bytes CHANGED or SHRANK."
  print "Done. Hand $OUTBASE/{A,B,C}-* to the Engineer/Leader."
} 2>&1 | tee $D/C.txt; exit ${pipestatus[1]} ;;

S) out_dir S; {
  print "[S] rehearsal simulation (no model, no process): graftling's own ClaudeJsonlCollector over a synthetic transcript; the A/B/C observation and comparison code on its files. Dialog: none."
  W=$D/sim; M=SIM519-M1
  obs sim $W first && obs snap A $W/swarm s $W/native.jsonl $M $D/A.json || exit 1
  obs snap B $W/swarm s $W/native.jsonl $M $D/B.json && obs compare $D/A.json $D/B.json
  obs sim $W resume && obs snap C $W/swarm s $W/native.jsonl $M,SIM519-M2 $D/C.json && obs compare $D/A.json $D/C.json
  print "expected: A present + 1 hit; A->B all same; A->C archive inode CHANGED, shift equal to line-1 growth, beyond A's size YES; transcript append only; H1 NO, H2 YES, H3 NO."
} 2>&1 | tee $D/S.txt; exit ${pipestatus[1]} ;;

*) print -r -- "usage: zsh $THIS P|Tu|A|B|C   (Main; Tu is USER)   S: rehearsal simulation"; exit 2 ;;
esac
