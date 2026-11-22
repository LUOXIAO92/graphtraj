#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 575 Main-run steps: a real Claude Code Main calls mcp__graphtraj__tasks/agents with arguments_file.
#   zsh scripts/verify-575/steps.zsh <STEP>      (Main, from this Task's Worktree; one step at a time)
# Order: pre -> Tu (USER) -> repro -> after -> foreign -> suite -> SR.
#   pre      Versions; isolated project /private/tmp/argsfile-575/project (own git and .graphtraj, project-only
#            isolation settings, probe Task 1 ready); the candidate (this Worktree's HEAD, built as a wheel) with
#            graftling v0.7.0 (production) in /private/tmp/argsfile-575/venv-<commit>; a one-line claude -p in the
#            project judged by claude_isolation.py check; the host plugin gate (NOT PASSED before Tu is expected).
#            Dialog: none. ~3 min.
#   Tu       USER, plain Terminal: trust the project folder once (Claude Code's own dialog), then /exit.
#   repro    Production installation (<Harness>/.venv-runtime, read only) as the project's adopted graphtraj host. A
#            real Claude Main calls tasks task_graph inline (control) and with arguments_file, and agents status with
#            arguments_file. Verdict REPRODUCED only when the inline call succeeds and the file call is refused with
#            authority-denied (read from the Session's own tool results). Dialog: none. ~2 min.
#   after    Candidate installation as the adopted host. A real Claude Main makes one write (tasks worldline_append)
#            and one read (tasks task_graph) with arguments_file, and agents status with arguments_file. PASS only when
#            all succeed, the read shows probe Task 1, and the write's unique event name is in the project's
#            .graphtraj state; FAIL on any authority-denied or a missing effect. Dialog: none. ~2 min.
#   foreign  Candidate. Real Claude Main A holds the project's host (it runs `sleep 150` through Bash); meanwhile a
#            second real Claude Session B in the same project calls tasks worldline_append with arguments_file.
#            PASS only when B's call is refused, B's event name is absent from the project state, and A ended normally.
#            Dialog: none. ~3 min.
#            LIMIT (stated for the report): NativeCalls' own refusal of another Session's association inside ONE host
#            (the 'already pending' / 'No matching' branches) cannot be operated through the real entry: one Claude
#            Code process launches its own host and serves one Session at a time, so a real second Session always
#            reaches the project through a second Claude process, which this step shows is refused. The in-host
#            branch has unit tests only (tests/test_claude_arguments_file_575.py), which are not acceptance evidence.
#   suite    GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a venv under <Harness>/tmp/575
#            with graftling built from v0.7.0; pytest temp root under TMPDIR=${TMPDIR:-/tmp} (outside the Harness).
#            Dialog: none. VERIFY575_PYTEST_ARGS='<args>' only appends pytest args after `-- -rA` (rehearsal).
#   SR       Read only: newest suite; FAILED/ERROR lines classed known (516's CURRENT definition via its task.yml) or NEW.
# User login: repro, after, foreign and pre's one-line check run Claude Code with the user's own login and run only
# with VERIFY575_CLAUDE_USER_LOGIN=1. Claude Code then reads the keychain and ~/.claude.json and writes Session
# transcripts under ~/.claude/projects/-private-tmp-argsfile-575-project/ and the project's entry in ~/.claude.json
# (Tu's trust answer lands there too). Nothing else under ~/.claude, no dotfile and no host installation is written.
# Writes: /private/tmp/argsfile-575/ and step output under <Harness>/tmp/575/<step>-<time>/. Production is only read.
# VERIFY575_* other than VERIFY575_CLAUDE_USER_LOGIN and VERIFY575_PYTEST_ARGS are for the Engineer's stub rehearsal.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)
H=${VERIFY575_H:-${WT:h:h:h:h}}                         # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
BASE=${VERIFY575_BASE:-/private/tmp/argsfile-575}       # outside the Harness: no parent .mcp.json/instructions/.graphtraj
P=$BASE/project
OUTBASE=${VERIFY575_OUT:-$H/tmp/575}
T=${VERIFY575_T:-$H/tmp/575}                            # the suite venv
PROD=$H/.venv-runtime/bin/python                         # production GraphTraj + graftling 0.7.0, read only
G=$H/graftling
GCOMMIT=6a1f18be7e3f6cdf9587d98cb1c541832bcbd9ca          # graftling v0.7.0 (571) = production
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
ISO=$WT/scripts/verify-common/claude_isolation.py
JUDGE=$SD/judge575.py
PREP=$SD/prep575.py
MODEL=claude-opus-5-5
HEAD=$(git -C $WT rev-parse HEAD)
CAND=$BASE/venv-${HEAD[1,8]}
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY575_STUB:-} ]] && path=($VERIFY575_STUB $path)   # rehearsal only: stub claude first

BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP \
  LANG=${LANG:-en_US.UTF-8} PYTHONDONTWRITEBYTECODE=1 ${VERIFY575_STUB_MODE:+VERIFY575_STUB_MODE=$VERIFY575_STUB_MODE} "$@"; }
out_dir() { D=$OUTBASE/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D && print -r -- "output: $D"; }
next() { print -r -- "next (paste): $*"; }
judge() { clean $CONDA -I $JUDGE "$@"; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
need_login() {
  [[ -n ${VERIFY575_CLAUDE_USER_LOGIN:-} ]] && {
    print -r -- "VERIFY575_CLAUDE_USER_LOGIN=1: Claude Code uses the user's own login. It reads the keychain and ~/.claude.json"
    print -r -- "and writes only Session transcripts under $HOME/.claude/projects/${${P:A}//[\/.]/-}/ and the project entry for ${P:A}"
    print -r -- "in ~/.claude.json. No settings, plugins or skills under ~/.claude, no dotfile, no host installation is written."
    return 0; }
  print -r -- "STOP: this step runs Claude Code with the user's own login. Ask the user first; it reads the keychain and"
  print -r -- "~/.claude.json and writes $HOME/.claude/projects/${${P:A}//[\/.]/-}/ (transcripts) and ~/.claude.json (project entry)."
  print -r -- "When the user agrees:  VERIFY575_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"
  return 1
}
versions() {
  local C=$(claude_bin)
  print -r -- "zsh $ZSH_VERSION | git $(git --version | cut -d' ' -f3) | claude: $C -> ${C:A} | $($C --version 2>&1 | head -1)"
  print -r -- "worktree $WT HEAD $HEAD | uncommitted: $(git -C $WT status --porcelain | wc -l | tr -d ' ') file(s)"
  print -r -- "production (read only): $(clean $PROD -I -B -c 'import importlib.metadata as m; print("graftling", m.version("graftling"), "graphtraj", m.version("graphtraj"))' 2>&1)"
}
isolation() {  # graphtraj root and git top level are the project; nothing of the Harness above it
  clean $PROD -I -B - $P <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('CLAUDE.md', 'CLAUDE.local.md') if (p / n).exists()]
leaks = [str(p / n) for p in project.parents for n in ('.mcp.json', 'AGENTS.md', '.graphtraj') if (p / n).exists()]
print(f'graphtraj project root: {root} | git top level: {top}')
print(f'CLAUDE.md at or above: {upward or "none"} | .mcp.json/AGENTS.md/.graphtraj above: {leaks or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward and not leaks
print('isolation:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
}
project_init() {
  mkdir -p $P
  [[ -d $P/.git ]] || git -C $P init -q --initial-branch=main || return 1
  if ! git -C $P rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 575 arguments_file probe" > $P/README.md
    git -C $P add README.md && git -C $P -c user.name=575 -c user.email=575@invalid commit -qm "Initial source" || return 1
  fi
  [[ -e $P/.graphtraj/config.yml || -e $P/.graphtraj/core/config.yml ]] \
    || (cd $P && print -r -- y | clean ${PROD:h}/graphtraj setup | tail -2) || return 1
  (cd $P && clean $PROD -I -B $PREP task $P)
}
copy_deps() {  # production's click, yaml, websockets into venv $1 when its base Python lacks them (read only)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $1/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RT/$m $RT/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
# $1 venv, $2 'editable' (this Worktree, for tests) or 'wheel' (HEAD's git archive, the installed candidate).
build_venv() {
  local V=$1 S=${1}-src
  if [[ -x $V/bin/python && -f $V/installed ]]; then print -r -- "reusing $V ($(<$V/installed))"; return 0; fi
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  rm -rf $V $S && mkdir -p $S/graftling $S/graphtraj $S/wheels || return 1
  git -C $G archive $GCOMMIT | tar -x -C $S/graftling || return 1
  $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  if [[ $2 == wheel ]]; then
    git -C $WT archive $HEAD | tar -x -C $S/graphtraj || return 1
    $CONDA -m pip wheel $pip -w $S/wheels $S/graphtraj > /dev/null || return 1
    $V/bin/python -m pip install $pip $S/wheels/*.whl || return 1
  else
    $V/bin/python -m pip install $pip $S/wheels/graftling-*.whl && $V/bin/python -m pip install $pip -e $WT || return 1
  fi
  print -r -- "graftling $GCOMMIT + graphtraj $HEAD ($2)" > $V/installed
}
configure() {  # $1 python of the installation the project adopts; then 489's project-only isolation settings
  (cd $P && clean $1 -B -m graphtraj.runtimes.claude.host configuration --project $P --claude $(claude_bin) --write) >/dev/null \
    || { print "STOP: configuration --write failed with $1"; return 1; }
  clean $CONDA -I $ISO settings $H $P
  print -r -- "adopted host: $(clean $CONDA -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["mcpServers"]; print(list(s), s["graphtraj"]["command"])' $P/.mcp.json 2>&1)"
  print -r -- "host installation: $(clean $1 -I -B -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__)' 2>&1)"
}
gate() {  # plugin gate (verify-514/519): init lists graphtraj and its tools, the host plugin, no untrusted warning
  (cd $P && clean $BOUND 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json \
     --strict-mcp-config <<< 'Reply with one line: READY-575 and your exact model name. Use no tool.' > $D/gate.jsonl 2> $D/gate.err) \
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
ok = [n for n, _ in servers] == ["graphtraj"] and "untrusted" not in warnings and {"mcp__graphtraj__agents", "mcp__graphtraj__tasks"} <= set(tools) \
     and any("graphtraj-claude-host" in str(p) for p in plugins)
print("plugin gate:", "PASS" if ok else "NOT PASSED")
sys.exit(0 if ok else 1)' $D/gate.jsonl
}
main_run() {  # $1 name, $2 prompt file, $3 bound seconds, $4 extra allowed tool. One real Claude Main in the project.
  local name=$1 prompt=$2 bound=$3 allowed=mcp__graphtraj__agents,mcp__graphtraj__tasks${4:+,$4}
  (cd $P && clean $BOUND $bound $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
     --mcp-config $P/.mcp.json --strict-mcp-config --allowedTools $allowed \
     < $prompt > $D/$name.jsonl 2> $D/$name.err) || { local rc=$?; print "claude $name rc=$rc (142 = timeout)"; return $rc; }
}
in_state() { grep -rlF -- $1 $P/.graphtraj 2>/dev/null | grep -v '/claude-host/' | head -3; }
CALLS='Use only the tools named below, exactly once each, in this order, with exactly the input given (JSON). Do not retry, do not
read or write any file yourself, and do not change the inputs. After the calls print one line per call: CALL <n> followed by
the raw tool result on one line. Then stop.'

run_step() {
case $STEP in
pre) out_dir pre
  print "[pre] preflight. Dialog: none. ~3 min."
  versions
  local rc=0
  project_init || { print "STOP: the project or probe Task 1 is not ready"; return 1; }
  build_venv $CAND wheel || { print "STOP: candidate venv failed"; return 1; }
  print -r -- "candidate (outside the Harness): $(clean $CAND/bin/python -I -B -c 'import graphtraj, graftling, importlib.metadata as m; print(graphtraj.__file__, "| graftling", m.version("graftling"))' 2>&1)"
  configure $PROD || return 1
  isolation || rc=1
  need_login || return 1
  print -r -- "-- one-line claude -p (model and login), judged by claude_isolation.py check"
  clean $CONDA -I $ISO prompt PROBE-575 > $D/model-prompt.txt
  (cd $P && clean $BOUND 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json \
     --strict-mcp-config < $D/model-prompt.txt > $D/model.jsonl 2> $D/model.err) || print "claude rc=$? (142 = 120 s timeout)"
  clean $CONDA -I $ISO check $D/model.jsonl PROBE-575 $H $P $D/model-prompt.txt || rc=1
  print -r -- "-- plugin gate (information; repro/after/foreign require PASS, which needs Tu first)"
  gate || print "(NOT PASSED is expected before Tu: Claude Code loads the project plugin only in a trusted folder)"
  print "Observable: 'probe Task 1 ready', candidate graphtraj under $CAND, 'isolation: OK', the check's OK line with $MODEL."
  print "pre verdict: $( (( rc == 0 )) && print PASS || print FAIL )"
  (( rc == 0 )) && next "Tu (USER, plain Terminal): cd $P && claude" || print "fix the NOT OK lines, then: zsh $THIS pre"
  return $rc ;;

Tu)
  print "[Tu] USER in a plain Terminal. Dialog: one: Claude Code's 'Do you trust the files in this folder?' naming $P ->"
  print "choose 'Yes, proceed'. Should an MCP server approval for 'graphtraj' appear, approve it for this project. Then /exit."
  print "This writes the project's entry in ~/.claude.json (the user's own login)."
  print "  cd $P && claude"
  next "VERIFY575_CLAUDE_USER_LOGIN=1 zsh $THIS repro" ;;

repro) out_dir repro
  print "[repro] production host (.venv-runtime, read only); real Claude Main. Dialog: none. ~2 min."
  need_login || return 1
  configure $PROD || return 1
  gate || { print "STOP: plugin gate not passed; trust the folder first: zsh $THIS Tu"; return 1; }
  clean $PROD -I -B $PREP files $P argsfile-575-repro-$(date +%H%M%S) || return 1
  print -r -- "$CALLS
1. mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"task_graph\", \"arguments\": {\"view\": \"current\"}}
2. mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"task_graph\", \"arguments_file\": \"args575/graph.json\"}
3. mcp__graphtraj__agents {\"action\": \"execute\", \"feature\": \"status\", \"arguments_file\": \"args575/status.json\"}" > $D/prompt.txt
  main_run main $D/prompt.txt 600
  judge calls $D/main.jsonl
  print -r -- "-- verdict from the Session's own tool results"
  local rc=0
  judge expect $D/main.jsonl control=tasks:task_graph:inline:ok tasks-file=tasks:task_graph:file:denied || rc=1
  judge expect $D/main.jsonl agents-file=agents:status:file:denied || print "(agents with arguments_file was not refused as above; recorded, not part of the verdict)"
  print "repro verdict: $( (( rc == 0 )) && print 'REPRODUCED (PASS): inline succeeds, arguments_file is authority-denied' || print 'NOT REPRODUCED (FAIL): see the lines above')"
  next "VERIFY575_CLAUDE_USER_LOGIN=1 zsh $THIS after"
  return $rc ;;

after) out_dir after
  print "[after] candidate host $CAND; real Claude Main: one write, one read, agents status, all with arguments_file. Dialog: none. ~2 min."
  need_login || return 1
  [[ -f $CAND/installed ]] || { print "STOP: $CAND missing; run: zsh $THIS pre"; return 1; }
  configure $CAND/bin/python || return 1
  gate || { print "STOP: plugin gate not passed; trust the folder first: zsh $THIS Tu"; return 1; }
  local tag=argsfile-575-after-$(date +%H%M%S)
  print -r -- "write's event name: $tag | already in the project state: ${$(in_state $tag):-no}"
  clean $CAND/bin/python -I -B $PREP files $P $tag || return 1
  print -r -- "$CALLS
1. mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"worldline_append\", \"arguments_file\": \"args575/append.json\"}
2. mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"task_graph\", \"arguments_file\": \"args575/graph.json\"}
3. mcp__graphtraj__agents {\"action\": \"execute\", \"feature\": \"status\", \"arguments_file\": \"args575/status.json\"}" > $D/prompt.txt
  main_run main $D/prompt.txt 600
  judge calls $D/main.jsonl
  print -r -- "-- verdict from the Session's own tool results and the project state"
  local rc=0
  judge expect $D/main.jsonl write=tasks:worldline_append:file:ok read=tasks:task_graph:file:ok \
    agents=agents:status:file:ok || rc=1
  judge has $D/main.jsonl tasks task_graph argsfile-probe || rc=1
  local found=$(in_state $tag)
  print -r -- "write effect: event $tag in $P/.graphtraj: ${found:-ABSENT}"; [[ -n $found ]] || rc=1
  grep -q 'authority-denied' $D/main.jsonl && { print "authority-denied appears in the Session -> FAIL"; rc=1; }
  print "after verdict: $( (( rc == 0 )) && print PASS || print FAIL )"
  next "VERIFY575_CLAUDE_USER_LOGIN=1 zsh $THIS foreign"
  return $rc ;;

foreign) out_dir foreign
  print "[foreign] candidate host; real Main A holds the host (Bash sleep 150); a second real Session B calls tasks with"
  print "arguments_file meanwhile. Dialog: none. ~3 min. See LIMIT in this script's header."
  need_login || return 1
  [[ -f $CAND/installed ]] || { print "STOP: $CAND missing; run: zsh $THIS pre"; return 1; }
  configure $CAND/bin/python || return 1
  gate || { print "STOP: plugin gate not passed; trust the folder first: zsh $THIS Tu"; return 1; }
  local tag=argsfile-575-foreign-$(date +%H%M%S) channel=$P/.graphtraj/claude-host/live/channel.json
  clean $CAND/bin/python -I -B $PREP files $P $tag || return 1
  print -r -- "Run the Bash command  sleep ${VERIFY575_SLEEP:-150}  once (no other tool), then reply with one line DONE-A." > $D/a-prompt.txt
  main_run a $D/a-prompt.txt 400 'Bash(sleep:*)' &
  local apid=$! waited=0
  until grep -q '"name":"Bash"' $D/a.jsonl 2>/dev/null && [[ -f $channel ]]; do
    (( waited++ >= 120 )) && { print "STOP: A did not start its Bash call with a live host within 120 s"; wait $apid; return 1; }
    sleep 1
  done
  print -r -- "A holds the host: channel $(<$channel | tr -d '\n' | cut -c1-160)"
  print -r -- "$CALLS
1. mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"worldline_append\", \"arguments_file\": \"args575/append.json\"}" > $D/b-prompt.txt
  main_run b $D/b-prompt.txt 300
  local brc=$?
  wait $apid; local arc=$?
  print -r -- "A rc=$arc | B rc=$brc"
  judge calls $D/b.jsonl
  print -r -- "-- verdict"
  local rc=0
  judge expect $D/b.jsonl b-write=tasks:worldline_append:file:refused || rc=1
  local found=$(in_state $tag)
  print -r -- "B's event $tag in $P/.graphtraj: ${found:-ABSENT}"; [[ -z $found ]] || rc=1
  (( arc == 0 )) && grep -q 'DONE-A' $D/a.jsonl || { print "A did not end normally -> FAIL"; rc=1; }
  print "foreign verdict: $( (( rc == 0 )) && print PASS || print FAIL ) (a second real Session's arguments_file call is refused)"
  next "zsh $THIS suite"
  return $rc ;;

suite)
  setopt local_options no_bg_nice
  print "[suite] GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none."
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $others; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  local RUNTMP=${PYTEST_TMP:A}/verify-575-suite-$(date +%Y%m%dT%H%M%S) d
  d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  build_venv $V editable || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__)') || return 1
  local R=$OUTBASE/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP | candidate $HEAD | graftling $GCOMMIT (v0.7.0)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY575_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $OUTBASE/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  next "zsh $THIS SR    (after $R/suite.txt ends with exit=)" ;;

SR)
  print "[SR] read only: newest suite; FAILED/ERROR lines classed against 516's current definition. Dialog: none."
  local K=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- "516 current definition: $K"; [[ -f $K ]] || { print "STOP: cannot read $K"; return 1; }
  local g=$(cat $OUTBASE/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print "suite still running (no exit= line yet)"; return 1; }
  local line t new=0 any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; new=1; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
  # A shard ending other than by test failures (exit 1) is a failure of the run itself; exit 5 (nothing collected)
  # is only expected when a rehearsal filter was given.
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; new=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; new=1 ;;
    esac
  done
  print "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  return $new ;;

*) print -r -- "usage: zsh $THIS pre|Tu|repro|after|foreign|suite|SR"; return 2 ;;
esac
}

[[ -x $PROD ]] || { print "STOP: $PROD (production) is missing"; exit 1; }
mkdir -p $OUTBASE
D=$OUTBASE
run_step 2>&1 | tee $OUTBASE/$STEP-$(date +%Y%m%dT%H%M%S).txt
exit ${pipestatus[1]}
