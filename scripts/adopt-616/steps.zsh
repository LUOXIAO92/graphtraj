#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 616 Main-run steps: adopt GraphTraj dev 4ef36426 (Task 614: subagents `models` served by GraphTraj as the
# project roles create can select, grouped by catalog provider) into production. graftling stays 0.10.0 (612's wheel,
# untouched). User decision (Worldline): 20261125T112834.635492+0900 ("614 换到生产").
# Run one step at a time:  zsh <this file> <STEP>     ONE ordered list:
#   00 -> B -> GR614 -> V -> Mpre -> [Main tells the USER; 616's Leader and Engineer have ended their turns]
#   USER /exit Main -> I (USER, Terminal) -> USER `cd <Harness> && claude --continue` -> M -> Mr -> N -> Nr -> P -> Pr -> done.
#   Rollback: R (Main asks the USER first; the USER /exits Main), run from the backup's own copy.
#   A failed I that R rolled back: I0 -> Mpre -> USER /exit + I -> claude --continue -> M -> ... -> done (README.md).
# I installs ONLY the graphtraj wheel (git archive TARGET) with pip --force-reinstall --no-deps --no-index; graphtraj's
# version stays 0.1.0, hence --force-reinstall. graftling 0.10.0 (612's wheels-0.10.0) is not reinstalled and I checks
# that its files and dist-info equal the backup's.
# GR614 replaces a new full suite: it re-judges Task 614's retained G record of this same commit with the 0.10.0 wheel.
# Login: the Claude login the user approved (603/604/612) for 00's probe and N; Main's own running Session carries M
# and P. P's `models` reads files only (P checks this in the installed code and STOPs otherwise). No other login or key.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer; Main leaves all of these unset): ADOPT616_H, ADOPT616_WT, ADOPT616_STUB, ADOPT616_PROJECTS,
# ADOPT616_VPROJECT, ADOPT616_VHOME, ADOPT616_OUT, ADOPT616_SCRATCH, ADOPT616_G, ADOPT616_R614, ADOPT616_NOSNAP,
# ADOPT616_CATALOG_HOME, ADOPT616_CLEAN_EXTRA.
# No zsh special parameter name is used as a variable (path is used only as zsh's PATH array, as 593/600/604/612).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
TASKDIR=616-graphtraj-614-production-adoption
TASK_ID=616
H=${ADOPT616_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}   # the Harness (production)
WT=${ADOPT616_WT:-$H/.graphtraj/core/worktrees/$TASKDIR}                           # this Task Worktree
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused by path: adopt_tree.py, pkgdiff532.py, onegraft.py, ...
STEP=${1:-}
DECISION=20261125T112834.635492+0900                # the user's adoption decision
LOGIN_NOTE="the Claude login the user approved (603/604/612), named in Task 616's definition (acceptance)"
path=($HOME/.local/bin /opt/homebrew/bin $path)     # claude and node, as 593/600/604/612 (the USER's usual installs)
[[ -n ${ADOPT616_STUB:-} ]] && path=($ADOPT616_STUB $path)   # rehearsal only: stub claude/ps first
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; builds the wheel, runs the helpers with -I
# ---- versions ----
TARGET=4ef36426ab6fa5a4769a23557aecf2aa2e2b3759     # GraphTraj dev with 614; production graphtraj after I
OLD=78f929eed956714ba2d6e83fb2ace953f8a56bcb        # production graphtraj now (612's wheel); TARGET's ancestor
PRODUCT_DIFF="src/graphtraj/execution/agent_driver.py src/graphtraj/interfaces/agents.py tests/test_provider_selection.py tests/test_role_models_614.py"
GTVERSION=0.1.0
GLVERSION=0.10.0                                    # production graftling, unchanged
GTAG=v0.10.0
GCOMMIT=6f4aeb8fe9f47b71d81b9771486167b123308066    # graftling v0.10.0 (612)
GSHA=6ae3e26efd9023e04e0b8a4fccf7eab65d7088bc5cae50eebd3482dd9b384a51   # 612's graftling-0.10.0 wheel
G=${ADOPT616_G:-$H/graftling}                       # read only: B compares 612's wheel with git archive v0.10.0
GUARDED=(src tests plugins manuals pyproject.toml)
STATE=$H/.graphtraj/core/state
T612=612-graftling-provider-release-and-production-adoption
T614=614-graphtraj-subagents-models-discovery
W612=$STATE/tasks/$T612/adoption
NG=$W612/wheels-$GLVERSION                          # production's graftling wheel (612), reused, never rebuilt
W78=$W612/wheels-${OLD[1,8]}                        # production's graphtraj wheel now (612)
AD=$STATE/tasks/$TASKDIR/adoption
NT=$AD/wheels-${TARGET[1,8]}                        # the graphtraj wheel I installs (B writes it)
R614=${ADOPT616_R614:-$STATE/tasks/$T614/realhost/G-20261125T030159}   # Task 614's retained full-suite record
D516=$STATE/tasks/516-low-priority-flaky-tests      # known flaky tests: 516's CURRENT definition via its task.yml
KNOWN_EXTRA=("tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]")   # 611/614: fails on base too
SCR=${ADOPT616_SCRATCH:-$H/tmp/616}
TSRC=$SCR/tsrc                                      # git archive TARGET
GSRC=$SCR/gsrc                                      # git archive v0.10.0 (B's comparison only)
WHL=$SCR/wheel
BK=$SCR/backup
BK612=$H/tmp/612/backup                             # the current rollback (612); only read
VV=$SCR/vvenv
R=${ADOPT616_OUT:-$STATE/tasks/$TASKDIR/realhost/main-raw}
RT=$H/.venv-runtime
VPROJ=${ADOPT616_VPROJECT:-/private/tmp/vproject-616}   # isolated project for the real MCP entries (graphtraj setup)
VHOME=${ADOPT616_VHOME:-/private/tmp/vhome-616}         # V's scratch HOME for the scratch catalog
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
SESS=$H/.graphtraj/swarm/sessions
AGENTREC=$H/.graphtraj/swarm/control/agents
RUNNERSESS=$H/.graphtraj/core/runner/sessions
PROJECTS=${ADOPT616_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
MODEL=claude-opus-5-5
CHILD=n616
DONEWORD=DONE-616
SUITEIDS=$WT/scripts/verify-581/suiteids.py
MAIN=$(cat $SCR/main.session 2>/dev/null)

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT616_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean git "$@"; }                            # every git call: allowlist environment
ck() { [[ $1 == 0 ]] && print -r -- "CHECK 616 $2: PASS${3:+ ($3)}" || print -r -- "CHECK 616 $2: FAIL${3:+ ($3)}"; }   # $1 = 0 for pass
helper() { [[ -f $SD/$1 ]] && print -r -- $SD/$1 || print -r -- $S593/$1; }   # R runs from $BK/tools with its own copies
tree() { clean $CONDA -I $(helper adopt_tree.py) "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
cv() { local C=$(claude_bin); print -r -- "claude: $C -> ${C:A} | version: $(clean $C --version 2>&1 | head -1) | recorded at 00: $(cat $SCR/cc.version 2>/dev/null || print none)"; }
need_main() { [[ -n $MAIN ]] || { print "STOP: no $SCR/main.session (Main's Session id): run 00 first"; exit 1; }; }
yml() { local f=$1 k=$2; print -r -- ${${${(M)${(f)"$(cat $f 2>/dev/null)"}:#${k}: *}#${k}: }//[\'\"]/}; }   # one top-level scalar
cdef_of() { local d=$1 c; c=$(yml $d/task.yml current_definition); print -r -- ${c:+$d/$c}; }   # current definition file
KNOWN516=$(cdef_of $D516)
check_tmp() {
  case ${${TMPDIR:-/tmp}:A}/ in ${H:A}/*) print "STOP: TMPDIR ${TMPDIR:-/tmp} is inside the Harness"; return 1 ;; esac
  print -r -- "TMPDIR=${TMPDIR:-/tmp} (outside the Harness)"
}
prod_versions() { clean $RT/bin/python -I -c 'import importlib.metadata as m; print(m.version("graphtraj"), m.version("graftling"))' 2>&1; }
direct_urls() {  # sets DGT and DGL from production's dist-info
  local sp=$(site); DGT=$(cat $sp/graphtraj-$GTVERSION.dist-info/direct_url.json 2>/dev/null); DGL=$(cat $sp/graftling-$GLVERSION.dist-info/direct_url.json 2>/dev/null)
  print -r -- "graphtraj direct_url: ${DGT:-none}"; print -r -- "graftling direct_url: ${DGL:-none}"
}
product_guard() {  # HEAD contains TARGET and differs from it only under scripts/adopt-616; OLD..TARGET = 614's 4 files
  local head names other range dirty
  head=$(gg -C $WT rev-parse HEAD)
  names=$(gg -C $WT diff --name-only $TARGET HEAD -- $GUARDED 2>&1); other=$(gg -C $WT diff --name-only $TARGET HEAD 2>&1 | grep -v '^scripts/adopt-616/')
  range=$(gg -C $WT diff --name-only $OLD $TARGET -- $GUARDED 2>&1 | tr '\n' ' ')
  dirty=$(gg -C $WT status --porcelain -- . ':!scripts/adopt-616/rehearsal' 2>&1)
  print -r -- "product guard: HEAD $head | git diff ${TARGET[1,8]} HEAD -- ${GUARDED[*]}: ${${names//$'\n'/ }:-empty} | other changes since ${TARGET[1,8]} outside scripts/adopt-616: ${${other//$'\n'/ }:-none} | git diff ${OLD[1,8]} ${TARGET[1,8]} -- product: ${range:-empty} | uncommitted (rehearsal outputs excepted): ${${dirty//$'\n'/ }:-none}"
  gg -C $WT merge-base --is-ancestor $TARGET HEAD && gg -C $WT merge-base --is-ancestor $OLD $TARGET \
    && [[ -z $names && -z $other && $range == "$PRODUCT_DIFF " && -z $dirty ]]
}
# 593/600/604/612's guard: BLOCKING = a live process naming $RT/, Main's host config or Main's Session id; budget timers
# and zombies are listed, never blocking; nothing is ever signalled. Return 2 when ps cannot list.
guard() {
  local listing line words hits=() timers=() zombies=0
  listing=$(ps -axww -o pid=,stat=,etime=,command= 2>&1) || { print "guard: ps cannot list processes; run this step in a normal Terminal"; return 2; }
  for line in ${(f)listing}; do
    words=(${=line}); [[ ${words[1]} == $$ ]] && continue
    [[ ${words[2]} == *Z* ]] && { zombies=$(( zombies + 1 )); continue; }
    [[ $line == *"-m graphtraj.execution.budget_idle_timer"* ]] && { timers+=("${line[1,200]}"); continue; }
    [[ $line == *"$RT/"* || $line == *"$HOSTCFG"* || ( -n $MAIN && $line == *"$MAIN"* ) ]] && hits+=("${line[1,200]}")
  done
  print "guard: budget_idle_timer processes (NON-BLOCKING, never signalled): ${#timers}"; (( ${#timers} )) && print -l -- "  "$timers
  print "guard: zombies (information): $zombies"
  (( ${#hits} == 0 )) && { print "guard: BLOCKING 0 (no process uses $RT)"; return 0; }
  print "guard: BLOCKING ${#hits} (processes using $RT or Main ${MAIN:-?}; wait for them, never kill):"; print -l -- "  "$hits
  return 1
}
detect_main() {  # the Claude Main: parent of the host serving $HOSTCFG (argv --resume/--session-id), else the newest transcript
  local hit words pp cmd id="" t
  hit=$(ps -axww -o pid=,ppid=,command= 2>/dev/null | grep -F -- "$HOSTCFG" | grep -F -- ' serve ' | head -1)
  words=(${=hit}); pp=${words[2]:-}
  if [[ -n $pp ]]; then
    cmd=$(ps -ww -o command= -p $pp 2>/dev/null); print -r -- "host pid ${words[1]}, parent $pp: ${cmd[1,160]}" >&2
    id=$(print -r -- "$cmd" | grep -oE -- '--(resume|session-id)[ =][0-9a-f-]{36}' | grep -oE '[0-9a-f-]{36}$' | head -1)
  else print -r -- "no host serving $HOSTCFG found by ps" >&2; fi
  if [[ -z $id ]]; then t=($PROJECTS/*.jsonl(N.om[1])); [[ -n ${t[1]:-} ]] && { id=${t[1]:t:r}; print -r -- "source: newest transcript ${t[1]:t}" >&2; }; fi
  print -r -- $id
}
members_idle() {  # $1 = phase. STOP while a member Worker or swarm batch runs; after Mpre also guard's BLOCKING 0
  local listing; listing=$(ps -axww -o pid=,etime=,command= 2>&1) || { print "STOP: ps cannot list processes"; return 2; }
  local -a workers=(${${(f)"$(print -r -- $listing | grep -E -- '-m graphtraj\.execution\.runner_worker|-m graphtraj\.teams\.team_round' | grep -v -- 'grep -E')"}:#})
  print -r -- "members_idle [$1]: Task $TASK_ID's Leader and Engineer must have ended their turns; member Workers and swarm batches running now: ${#workers}"
  (( ${#workers} )) && { print -l -- "  "${^workers[1,12]}; return 1; }
  if [[ $1 != Mpre && $1 != 00 ]]; then guard || return 1; fi
  print -r -- "members_idle [$1]: no member execution is active: PASS"
}
vproject_init() {  # $1 = graphtraj command: an isolated project with its own git and .graphtraj (setup), never the Harness
  mkdir -p $VPROJ
  [[ -d $VPROJ/.git ]] || gg -C $VPROJ init -q --initial-branch=main || return 1
  if ! gg -C $VPROJ rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 616 scratch project" > $VPROJ/README.md
    gg -C $VPROJ add README.md && gg -C $VPROJ -c user.name=616 -c user.email=616@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJ/.graphtraj/core/config.yml || -e $VPROJ/.graphtraj/config.yml ]] && gg -C $VPROJ rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJ && print -r -- y | clean $1 setup) > /dev/null || return 1
  fi
}
mcp_probe() {  # $1 = label, $2 = venv: graphtraj-mcp tools/list exactly subagents, tasks and 'agents' unknown (593's mcp593.py)
  (cd ${TMPDIR:-/tmp} && clean $2/bin/python -I $(helper mcp593.py) $1 $VPROJ $2/bin/graphtraj-mcp); ck $? "$1 graphtraj-mcp tools/list is exactly subagents, tasks and 'agents' is unknown (mcp593.py above)"
}
codex_hook_check() {  # $1 = venv: the Codex hooks entry names this venv's python and answers a neutral event with {} (no login)
  local P=$1/bin/python out cmd
  out=$(cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook --configuration 2>&1)
  cmd=$(print -r -- "$out" | clean $CONDA -I -c 'import json,sys; d=json.load(sys.stdin); print(sorted({h["command"] for e in d["hooks"].values() for g in e for h in g["hooks"]}), sorted(d["hooks"]))' 2>&1)
  print -r -- "Codex hooks entry configuration: $cmd"
  [[ $cmd == *"'$P -m graphtraj.runtimes.codex.stop_hook'"*"'SessionEnd', 'SessionStart', 'Stop'"* ]]; ck $? "Codex hooks entry of $1 names its python for SessionStart/Stop/SessionEnd"
  out=$(print -r -- '{"hook_event_name":"Probe616","session_id":"probe-616","cwd":"'$VPROJ'"}' | (cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
  [[ $out == '{}' ]]; ck $? "Codex hooks entry of $1 runs (neutral event answers {})" "${out[1,200]}"
}
manuals_check() {  # $1 = label, $2 = installed manuals tree: == the archive's, EXACTLY the .claude/.cc-writes marker tolerated (612)
  local d m=$2/.claude line
  local -a inside
  d=$(diff -r $TSRC/manuals $2 2>&1)
  if [[ -d $m && ! -L $m && -d $m/.cc-writes && ! -L $m/.cc-writes ]]; then
    inside=(${(f)"$(cd $m && find . -mindepth 1 2>&1)"})
    if [[ ${(j: :)inside} == ./.cc-writes ]]; then
      line="Only in $2: .claude"
      d=$(print -r -- "$d" | grep -vxF -- "$line")
      print -r -- "INFO 616 $1 tolerated in $2: .claude/.cc-writes (empty), the Claude Code sandbox write marker (inferred, 612; not a product file, in no RECORD); .claude $(stat -f '%Sm' -t '%F %T' $m) | .cc-writes $(stat -f '%Sm' -t '%F %T' $m/.cc-writes)"
    fi
  fi
  print -r -- "diff -r archive manuals vs $2 (the marker excepted): ${${d//$'\n'/ | }[1,300]:-none}"
  [[ -z $d ]]; ck $? "$1 share/graphtraj/manuals equals git archive ${TARGET[1,8]}'s manuals ($(find $2 -type f ! -path "$2/.claude/*" 2>/dev/null | wc -l | tr -d ' ') product files)"
}
record_counts() {  # Agent records, Session archives and member Sessions now (P's "nothing created" observable)
  print -r -- "agents $(print -l $AGENTREC/*.json(N) | grep -c .) sessions $(print -l $SESS/*(N/) | grep -c .) members $(print -l $RUNNERSESS/*(N/) | grep -c .)"
}
sr_classify() {  # $1 = suite record. Sets SR_NEW, SR_ANY, SR_IDS (every FAILED/ERROR id and ABNORMAL line read)
  local rec=$1 line t id timeouts=0; SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): $KNOWN516"
  [[ -f $KNOWN516 ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  print -r -- "shard logs read: ${#logs} (${logs:t})"
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if (( ${KNOWN_EXTRA[(Ie)$id]} )); then print -r -- "  known (611/614, fails on base too): $id"
    elif grep -qF -- "${t##*::}" $KNOWN516; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print "  (no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL ' $rec/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *'timed out after '*) print -r -- "  ABNORMAL shard TIMED OUT (NEW): $line"; SR_NEW=1; timeouts=$(( timeouts + 1 )) ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -r -- "  ABNORMAL lines: $(grep -c '^ABNORMAL ' $rec/suite.txt) | shard timeouts: $timeouts"
}
nr_read() {  # 593's nr_read (its Python, read from adopt-593/steps.zsh and run as is, with the child's done word)
  clean $CONDA -I -c 'import sys
src = open(sys.argv[1]).read()
body = src.split("<<" + chr(39) + "PY2" + chr(39) + "\n", 1)[1].split("\nPY2\n", 1)[0].replace("DONE-593", sys.argv[2])
sys.argv = ["nr_read"] + sys.argv[3:]
exec(compile(body, "adopt-593 nr_read", "exec"))' $S593/steps.zsh $DONEWORD $H $SESS $TASKDIR $R $CHILD
}
main_transcripts() {  # $1 = epoch file: Main's transcript plus any transcript written after it
  local -a found=($PROJECTS/$MAIN.jsonl(N) ${(f)"$(find $PROJECTS -maxdepth 1 -name '*.jsonl' -newer $1 2>/dev/null)"})
  print -l -- ${(u)found:#}
}

mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only, apart from creating $SCR (main.session, cc.version, the probe's stream). Login: yes, one claude -p probe with $LOGIN_NOTE; no Codex, Pi or DSH. Network: Claude only. Dialog: none."
  { mkdir -p $SCR || exit 1
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    check_tmp; ck $? "00 TMPDIR outside the Harness"
    say "production $RT (read only)"
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"
    direct_urls
    [[ $pv == "$GTVERSION $GLVERSION" && $DGT == *"$W78/graphtraj-$GTVERSION-"*.whl* && $DGL == *"$NG/graftling-$GLVERSION-"*.whl* ]]
    ck $? "00 production is graphtraj $GTVERSION (612's wheels-${OLD[1,8]}) + graftling $GLVERSION (612's wheels-$GLVERSION)"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "00 production pip check" "${pc[1,120]}"
    print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp,graphtraj-mcp,agent-runner}(N:t) | tr '\n' ' ')"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && ! -e $RT/bin/agents ]]; ck $? "00 production bin has subagents, subagents-mcp, graphtraj-mcp (and no agents)"
    say "backups"
    print -r -- "612's backup $BK612 (the current rollback, information; never written): $([[ -e $BK612/COMPLETE ]] && print COMPLETE || print 'not complete or absent')"
    [[ ! -e $BK ]]; ck $? "00 backup $BK absent"
    say "this Worktree $WT (the GraphTraj product I installs)"
    product_guard; ck $? "00 HEAD contains TARGET ${TARGET[1,8]}, a descendant of ${OLD[1,8]} by exactly 614's 4 product files, and differs from it only under scripts/adopt-616; clean"
    print -r -- "GraphTraj dev now (information): $(gg -C $WT rev-parse -q --verify refs/heads/dev)"
    print -r -- "Task 614's suite record (GR614 judges it): $R614 $([[ -f $R614/suite.txt ]] && print present || print MISSING)"
    cdef=$(cdef_of $STATE/tasks/$TASKDIR); [[ -n $cdef && -f $cdef ]]; ck $? "00 Task $TASK_ID ready (current_definition ${cdef:t} exists)"
    print -r -- "plugin and entry files (hashes; V and I require them unchanged):"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json $ENTRIES 2>&1 | sed 's/^/  /'
    say "Claude: version and one claude -p probe ($LOGIN_NOTE)"
    C=$(claude_bin); [[ -s $SCR/cc.version ]] || clean $C --version 2>&1 | head -1 > $SCR/cc.version; cv
    P=$(mktemp -d ${TMPDIR:-/tmp}/probe-616.XXXXXX)
    (cd $P && print -r -- "Reply with one line: READY-616 and your model id." | clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose > $SCR/00-probe.jsonl 2>&1)
    ans=$(clean $CONDA -I -c 'import json, sys
init, result = {}, ""
for line in open(sys.argv[1], errors="replace"):
    try: r = json.loads(line)
    except ValueError: continue
    if r.get("type") == "system" and r.get("subtype") == "init": init = r
    if r.get("type") == "result": result = str(r.get("result", ""))
print("model %s | apiKeySource %s | answer %r" % (init.get("model"), init.get("apiKeySource"), result[:120]))' $SCR/00-probe.jsonl 2>&1)
    print -r -- "claude -p probe: $ans (stream: $SCR/00-probe.jsonl)"
    [[ $ans == *"model $MODEL"* && $ans == *"apiKeySource none"* && $ans == *READY-616* ]]
    ck $? "00 claude -p answers READY-616 on $MODEL through the Claude login (apiKeySource none: no API key)"
    say "Main's Session (I, M, Mr, P need it)"
    id=$(detect_main); [[ -n $id ]] && print -r -- $id > $SCR/main.session
    print -r -- "MAIN=${id:-NOT FOUND} (saved to $SCR/main.session)"; [[ -n $id ]]; ck $? "00 Main's Session id found"
    members_idle 00 | head -14 || print "(information at 00: members may run now; Mpre and I wait for them)"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above). Nothing was changed. Hand $R/00.txt to the Team."; exit 1; }
  summary 00 "$(grep -E '^(CHECK|TMPDIR|production|612|claude|MAIN=|members_idle|graph|graft)' $R/00.txt)"
  print "Success: every 'CHECK 616 00 ...: PASS'."
  next "zsh $THIS B" ;;

B) print "[B] Main. Builds the graphtraj wheel from git archive ${TARGET[1,8]} with $CONDA (--no-index --no-deps --no-build-isolation) -> $NT. graftling: 612's wheels-$GLVERSION is reused by sha256 (no rebuild) and compared with git archive $GTAG. No network, no login. Dialog: none."
  { product_guard || { print "STOP: product guard (above)"; exit 1; }
    rm -rf $TSRC $GSRC $WHL $SCR/twheelview; mkdir -p $TSRC $GSRC $WHL $SCR/twheelview || exit 1
    sv=$(clean $CONDA -I -c 'import setuptools, pip; print("setuptools", setuptools.__version__, "| pip", pip.__version__)' 2>&1); ck $? "B setuptools importable offline in $CONDA" "$sv"
    say "graftling: 612's wheel $NG (production's, reused)"
    gw=($NG/graftling-$GLVERSION-*.whl(N)); print -r -- "wheel: ${gw[*]:t} | COMMIT: $(cat $NG/COMMIT 2>/dev/null)"
    (cd $NG && shasum -a 256 -c SHA256SUMS) && [[ $#gw == 1 && $(shasum -a 256 $gw[1] | cut -d' ' -f1) == $GSHA ]]
    ck $? "B 612's graftling wheel verifies (SHA256SUMS) and its sha256 is $GSHA"
    [[ $(cat $NG/COMMIT 2>/dev/null) == "$GTAG $GCOMMIT" ]]; ck $? "B 612's wheels-$GLVERSION COMMIT is $GTAG $GCOMMIT"
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}"); [[ $gt == $GCOMMIT ]]; ck $? "B $G's $GTAG peels to $GCOMMIT" "${gt:-absent}"
    gg -C $G archive $GTAG | tar -x -C $GSRC && clean $CONDA -I $S593/pkgdiff532.py graftling $gw[1] archive:$GSRC/src "616 B 612's graftling wheel equals git archive $GTAG" -
    ck $? "B 612's graftling wheel's files equal git archive $GTAG (built from the same commit as Task 614's suite wheel)"
    say "graphtraj: git archive $TARGET -> $TSRC"
    gg -C $WT archive $TARGET | tar -x -C $TSRC || exit 1
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL $TSRC) || { print "STOP: the graphtraj wheel build failed"; exit 1; }
    twhl=($WHL/graphtraj-$GTVERSION-*.whl(N)); all=($WHL/*.whl(N)); print -r -- "graphtraj wheel: ${all[*]:t}"
    (( $#twhl == 1 && $#all == 1 )) || { print "STOP: expected exactly one graphtraj-$GTVERSION wheel"; exit 1; }
    twhl=$twhl[1]; old=($W78/graphtraj-$GTVERSION-*.whl(N)); (cd $SCR/twheelview && unzip -qo $twhl) || exit 1
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $twhl archive:$TSRC/src "616 B graphtraj wheel equals git archive ${TARGET[1,8]}" -
    ck $? "B the graphtraj wheel's graphtraj/ files equal git archive ${TARGET[1,8]}"
    clean $CONDA -I -c 'import sys, tomllib, zipfile
from pathlib import Path
from packaging.requirements import Requirement
whl, src, old, cur = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
spec = tomllib.load(open(src / "pyproject.toml", "rb"))["tool"]["setuptools"]["data-files"]
want = {f"{d}/{Path(f).name}": src / f for d, fs in spec.items() for f in fs}
z, zo = zipfile.ZipFile(whl), zipfile.ZipFile(old)
def data(zf):
    return {n.split(".data/data/", 1)[1]: n for n in zf.namelist() if ".data/data/" in n}
got, gold = data(z), data(zo)
bad = sorted(set(want) ^ set(got)) + sorted(k for k in set(want) & set(got) if z.read(got[k]) != want[k].read_bytes())
print(f"data files in the pyproject: {len(want)} | in the wheel: {len(got)} | differing or missing: {bad or 0}")
print("data files changed since 612s wheels-78f929ee (information; expected none):", sorted(k for k in got if k not in gold or z.read(got[k]) != zo.read(gold[k])))
def meta(zf, name):
    return [n for n in zf.namelist() if n.endswith(".dist-info/" + name)][0]
ep = z.read(meta(z, "entry_points.txt")) == zo.read(meta(zo, "entry_points.txt"))
rq = lambda zf: sorted(l.split(":", 1)[1].strip() for l in zf.read(meta(zf, "METADATA")).decode().splitlines() if l.startswith("Requires-Dist:"))
print("Requires-Dist:", rq(z), "| 612 wheel:", rq(zo))
g = [Requirement(r) for r in rq(z) if Requirement(r).name == "graftling"]
inc = len(g) == 1 and g[0].specifier.contains(cur) and not g[0].specifier.contains("0.11.0")
print(f"CHECK 616 B graphtraj data files equal the archive manuals ({len(want)} files): {"PASS" if not bad and want else "FAIL"}")
print(f"CHECK 616 B graphtraj entry_points.txt identical to 612s wheels-78f929ee: {"PASS" if ep else "FAIL"}")
print(f"CHECK 616 B graphtraj Requires-Dist identical to 612s wheels-78f929ee: {"PASS" if rq(z) == rq(zo) else "FAIL"}")
print(f"CHECK 616 B graphtraj requires graftling {g[0] if g else None}: includes production {cur}, excludes 0.11.0: {"PASS" if inc else "FAIL"}")
' $twhl $TSRC ${old[1]:-$W78/missing.whl} $GLVERSION 2>&1 || ck 1 "B graphtraj data files and metadata read"
    t1=$(grep -c 'def role_models' $SCR/twheelview/graphtraj/execution/agent_driver.py 2>/dev/null) t2=$(grep -c 'role_models(self.root' $SCR/twheelview/graphtraj/interfaces/agents.py 2>/dev/null)
    print -r -- "  614 markers: agent_driver.py 'def role_models' x${t1:-0} | agents.py 'role_models(self.root' x${t2:-0}"
    (( ${t1:-0} > 0 && ${t2:-0} > 0 )); ck $? "B 614's markers are in the graphtraj wheel"
    leaked=$(unzip -Z1 $twhl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "graphtraj wheel build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the graphtraj wheel"
    say "the wheel V and I install: $NT"
    rm -rf $NT && mkdir -p $NT && cp -p $twhl $NT/ && (cd $NT && shasum -a 256 *.whl > SHA256SUMS) && print -r -- $TARGET > $NT/COMMIT || exit 1
    (cd $NT && shasum -a 256 -c SHA256SUMS); ck $? "B $NT holds the wheel with SHA256SUMS and COMMIT"
    print -r -- "wheel sha256: $(cat $NT/SHA256SUMS) | graftling (reused): $(cat $NG/SHA256SUMS)"
  } 2>&1 | tee $R/B.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/B.txt || { print "\nB STOP (see above). Hand $R/B.txt to the Team."; exit 1; }
  summary B "$(grep -E '^(CHECK|wheel|data files|Requires-Dist)' $R/B.txt)"
  print "Success: every 'CHECK 616 B ...: PASS'."
  next "zsh $THIS GR614" ;;

GR614) print "[GR614] Main. Read only: re-judges Task 614's retained full-suite record $R614 (requirement 1; no new suite). Its candidate must be TARGET, its graftling wheel built from $GTAG ($GCOMMIT, the commit of production's 612 wheel), pytest temp outside the Harness, a clean launch environment, no ABNORMAL shard, and every FAILED/ERROR id known: Task 516's CURRENT definition (516's task.yml current_definition) or ${KNOWN_EXTRA[1]}. No login. Dialog: none."
  { print -r -- "record: $R614"
    product_guard; ck $? "GR614 product guard (HEAD's product = TARGET ${TARGET[1,8]})"
    [[ -f $R614/run.txt && -f $R614/suite.txt ]] || { print "STOP: the record is missing"; exit 1; }
    sed 's/^/  run.txt: /' $R614/run.txt; print -r -- "  wait.txt: $(tr '\n' ';' < $R614/wait.txt 2>/dev/null)"
    cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $R614/run.txt | head -1) gl=$(grep -oE 'git archive [0-9a-f]{40}' $R614/run.txt | head -1 | awk '{print $3}')
    [[ $cand == $TARGET ]]; ck $? "GR614 the record's candidate is TARGET $TARGET" "${cand:-none}"
    [[ $gl == $GCOMMIT && $(cat $NG/COMMIT 2>/dev/null) == "$GTAG $GCOMMIT" ]]; ck $? "GR614 the record's graftling wheel is from $GTAG $GCOMMIT, the commit of production's wheels-$GLVERSION (612)" "${gl:-none}"
    grep -q "graftling $GLVERSION" $R614/run.txt; ck $? "GR614 test interpreter graftling = $GLVERSION"
    tmp=$(sed -n 's/^pytest temp root: \([^ ]*\).*/\1/p' $R614/run.txt | head -1)
    [[ -n $tmp && ${tmp:A}/ != ${H:A}/* ]]; ck $? "GR614 pytest temp root is outside the Harness" "${tmp:-none}"
    le=$(grep -m1 '^launch environment: ' $R614/run.txt); names=(${(o)${=${${le#launch environment: }%% only*}}})
    [[ ${(j: :)names} == "HOME LANG PATH TERM TMPDIR USER" && $le == *' only'* ]]; ck $? "GR614 launch environment is exactly HOME USER PATH TERM TMPDIR LANG (no provider credential)" "${le:-none}"
    tot=$(grep -E '^[0-9]+ (failed|errors|passed)|^=*.* (passed|failed)' $R614/suite.txt | tail -1); ex=$(sed -n 's/^exit=//p' $R614/suite.txt | tail -1)
    print -r -- "totals: ${tot:-NOT FOUND} | exit: ${ex:-NOT FOUND}"
    grep -q '^exit=' $R614/suite.txt; ck $? "GR614 the suite ended (exit= line)"
    sr_classify $R614
    print -r -- "614's new-ids.txt: $(grep -c . $R614/new-ids.txt 2>/dev/null) lines"
    (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && $SR_ANY == 1 ) ]]; ck $? "GR614 no new failure and no ABNORMAL shard" "$( (( $#SR_IDS )) && print "$#SR_IDS NEW ids: ${SR_IDS[*]}")"
  } 2>&1 | tee $R/GR614.txt; rc=${pipestatus[1]}
  verdict=PASS; (( rc == 0 )) && ! grep -q ': FAIL' $R/GR614.txt || verdict=FAIL
  summary GR614 "$(grep -E '^(record|totals|CHECK|  NEW|  known|  ABNORMAL|STOP)' $R/GR614.txt)"
  kn=$(grep -c '^  known ' $R/GR614.txt) nw=$(grep -c '^  NEW: ' $R/GR614.txt) ab=$(grep -c '^  ABNORMAL shard' $R/GR614.txt)
  print ""; print -r -- "RESULT 616 GR614: $verdict | ${$(sed -n 's/^totals: //p' $R/GR614.txt | tail -1):-no totals} | known non-blocking ids: $kn | NEW ids: $nw | ABNORMAL shards: $ab"
  if [[ $verdict == PASS ]]; then next "zsh $THIS V"
  else print "\nGR614 STOP: Main names Task 616's Leader and hands $R/GR614.txt over. No new full suite runs unless the Leader decides so."; exit 1; fi ;;

V) print "[V] Main. Before the install, outside production: a scratch venv ($VV) with the new graphtraj wheel + production's graftling $GLVERSION wheel + production's click, yaml and websockets; the real MCP entries in an isolated project ($VPROJ) and a scratch HOME ($VHOME); the hook copy regenerated by the product into a scratch copy must be byte-identical to production's. No login. Dialog: none. ~1 min."
  { rm -f $R/V.ok
    [[ -f $NT/SHA256SUMS && $(<$NT/COMMIT) == $TARGET ]] && (cd $NT && shasum -a 256 -c SHA256SUMS) && (cd $NG && shasum -a 256 -c SHA256SUMS) \
      || { print "STOP: no checked wheels in $NT and $NG: run B first"; exit 1; }
    product_guard; ck $? "V product guard"
    print -r -- "changes since production ${OLD[1,8]} under src/graphtraj/runtimes/claude, plugins, manuals, pyproject.toml (information; expected none): $(gg -C $WT diff --name-only $OLD $TARGET -- src/graphtraj/runtimes/claude plugins manuals pyproject.toml | tr '\n' ' ')"
    gt=($NT/graphtraj-$GTVERSION-*.whl(N)) gw=($NG/graftling-$GLVERSION-*.whl(N))
    rm -rf $VV; clean $CONDA -m venv $VV || exit 1
    clean $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gt[1] $gw[1] || exit 1
    sp=$(site) D=($VV/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pc=$(clean $VV/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "V scratch venv pip check" "${pc[1,120]}"
    clean $VV/bin/python -I $S593/onegraft.py $VV $GLVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "V one graftling $GLVERSION from the wheel in the scratch venv (onegraft.py)"
    [[ -x $VV/bin/subagents && -x $VV/bin/subagents-mcp && -x $VV/bin/graphtraj-mcp ]]; ck $? "V scratch venv bin has subagents, subagents-mcp, graphtraj-mcp"
    say "the hook copy: regenerated by the product (adopt_plugin.py regen) into a scratch copy of production's; prediction: byte-identical"
    VPL=$AD/vplug; VP=$VPL/graphtraj-claude-host; rm -rf $VPL; mkdir -p $VPL; cp -Rp $PDIR $VPL/ || exit 1
    clean $VV/bin/python -I $S593/adopt_plugin.py regen $H $(claude_bin) $VP || { ck 1 "V regenerate the hook copy"; exit 1; }
    diff -r $PDIR $VP > $R/V-plugin.diff 2>&1; drc=$?
    print -r -- "diff -r production copy vs regenerated: $(wc -l < $R/V-plugin.diff | tr -d ' ') lines ($R/V-plugin.diff)"
    ck $drc "V the regenerated hook copy is byte-identical to production's (no regeneration in I, no plugin/hooks trust dialog at claude --continue)" \
      "$( (( drc )) && print "STOP: hand $R/V-plugin.diff to the Leader; do not plan a regeneration")"
    say "real entries of the scratch venv in the isolated project $VPROJ"
    vproject_init $VV/bin/graphtraj; ck $? "V isolated project $VPROJ (own git, graphtraj setup)"
    mcp_probe V-scratch $VV
    (cd ${TMPDIR:-/tmp} && clean $VV/bin/python -I $SD/v616.py mcp V-scratch $VPROJ $VV/bin/graphtraj-mcp); ck $? "V v616.py mcp: subagents discover lists models; describe models takes {runtime, provider?}"
    say "execute models through the native host's binding (scratch catalog in $VHOME, scratch roles in $VPROJ)"
    rm -rf $VHOME; mkdir -p $VHOME || exit 1
    (cd ${TMPDIR:-/tmp} && clean HOME=$VHOME $VV/bin/python -I $SD/v616.py bound V-scratch $VPROJ); ck $? "V v616.py bound: execute models answers grouped by provider with key names only"
    codex_hook_check $VV
    mkdir -p $AD && shasum -a 256 $ENTRIES | tee $AD/entries.sha256
  } 2>&1 | tee $R/V.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/V.txt || { print "\nV STOP (see above). Nothing in production changed. Hand $R/V.txt to the Team."; exit 1; }
  touch $R/V.ok
  summary V "$(grep -E '^(CHECK|diff -r|product guard)' $R/V.txt)"
  print "Success: every 'CHECK 616 V ...: PASS' (incl. the hook copy byte-identical, tools/list subagents and tasks, models listed and executing grouped)."
  next "zsh $THIS Mpre" ;;

I0) need_main; print "[I0] Main, before Mpre and a rerun of I. Read only, apart from two MOVES (nothing is deleted): when the backup $BK belongs to an I whose install began and R rolled it back, and production equals that backup, it moves $BK to $SCR/backup-run<N>-<time> and that run's I/R records into $R/run<N>/. Otherwise STOP, changing nothing. $BK612 is not touched. No login. Dialog: none."
  { if [[ ! -e $BK ]]; then print -r -- "no backup $BK: nothing to set aside; I may run (it still STOPs when a backup exists)"; exit 0; fi
    nrun=1; while [[ -e $R/run$nrun || -n $(print -l $SCR/backup-run$nrun-*(N)) ]]; do nrun=$(( nrun + 1 )); done
    print -r -- "the failed run being set aside: run$nrun | backup $BK (I start $(sed -n 's/^I start //p' $R/I.txt 2>/dev/null | tail -1))"
    [[ -e $BK/COMPLETE && -e $BK/INSTALL-STARTED ]]; ck $? "I0 $BK has COMPLETE and INSTALL-STARTED (an I whose install began)"
    nr=$(grep -c '^CHECK 616 R ' $R/R.txt 2>/dev/null) nf=$(grep -c '^CHECK 616 R .*: FAIL' $R/R.txt 2>/dev/null)
    [[ -s $R/R.txt && ${nr:-0} -ge 5 && ${nf:-0} == 0 ]]; ck $? "I0 R's record $R/R.txt exists and every CHECK in it passed" "${nr:-0} CHECK lines, ${nf:-0} FAIL"
    say "production equals that backup, in R's terms"
    tree compare $BK/venv.manifest $RT > $SCR/I0-venv-compare.txt 2>&1; vrc=$?; tail -2 $SCR/I0-venv-compare.txt
    ck $vrc "I0 production venv equals the backup (adopt_tree.py compare, as R)"
    tree compare $BK/plugin.manifest $PDIR > /dev/null 2>&1; ck $? "I0 hook copy equals the backup"
    shasum -a 256 -c $BK/entries.sha256 > /dev/null 2>&1; ck $? "I0 .mcp.json, settings.local.json and config.json equal the backup"
    direct_urls; [[ $DGT == *"wheels-${OLD[1,8]}/graphtraj-$GTVERSION-"* && $DGL == *"wheels-$GLVERSION/graftling-$GLVERSION-"* ]]; ck $? "I0 graphtraj from wheels-${OLD[1,8]} and graftling $GLVERSION from 612's wheel"
    pc=$(clean $RT/bin/python -B -m pip check --disable-pip-version-check 2>&1); ck $? "I0 production pip check" "${pc[1,120]}"
  } 2>&1 | tee $R/I0.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || exit $rc
  [[ -e $BK ]] || { next "zsh $THIS Mpre"; exit 0; }
  grep -q '^CHECK 616 I0 .*: FAIL' $R/I0.txt && { print "\nI0 STOP (see above). Nothing was moved. Hand $R/I0.txt to the Team."; exit 1; }
  { nrun=1; while [[ -e $R/run$nrun || -n $(print -l $SCR/backup-run$nrun-*(N)) ]]; do nrun=$(( nrun + 1 )); done
    NB=$SCR/backup-run$nrun-$(date +%Y%m%dT%H%M%S)
    mv $BK $NB || { print "STOP: moving $BK failed"; exit 1; }
    print -r -- "MOVED $BK -> $NB (after-install snapshots inside: $(print -l $NB/after-install-*(N/:t) | tr '\n' ' '))"
    mkdir -p $R/run$nrun || exit 1
    files=($R/I.txt(N) $R/I.ok(N) $R/I-*(N) $R/R.txt(N) $R/R-*(N))
    (( $#files )) && mv $files $R/run$nrun/ || exit 1
    print -r -- "MOVED to $R/run$nrun/: ${files:t}"
    print -r -- "I failed after the install began; R restored production; I0 set its backup ($NB) and records aside" > $R/run$nrun/SUPERSEDED
    [[ ! -e $BK && -e $NB/COMPLETE && ! -e $R/I.txt && ! -e $R/R.txt ]]; ck $? "I0 backup and run$nrun records set aside; $BK and the current I/R records are absent"
    print -r -- "$BK612 (untouched): $([[ -e $BK612/COMPLETE ]] && print COMPLETE || print 'not complete or absent')"
  } 2>&1 | tee -a $R/I0.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q '^CHECK 616 I0 .*: FAIL' $R/I0.txt || { print "\nI0 STOP (see above). Hand $R/I0.txt to the Team."; exit 1; }
  print "Success: every 'CHECK 616 I0 ...: PASS'. I may run again (Mpre right before it)."
  next "zsh $THIS Mpre" ;;

Mpre) need_main; print "[Mpre] Main, right before the USER exits Main (GR614 and V passed). Adoption only with no member running: 616's Leader and Engineer have ended their turns and no other member runs; else STOP (never signals). No login. Dialog: none."
  { grep -q '^CHECK 616 GR614 no new failure .*: PASS' $R/GR614.txt 2>/dev/null; ck $? "Mpre GR614 passed"
    [[ -e $R/V.ok ]]; ck $? "Mpre V passed"
    members_idle Mpre; ck $? "Mpre no member Worker or swarm batch runs"
  } 2>&1 | tee $R/Mpre.txt
  grep -q ': FAIL' $R/Mpre.txt && { print "\nMpre STOP (see above). Wait for members to end (never kill them), then rerun Mpre."; exit 1; }
  print "\nWhy Main exits: Main's subagents/tasks calls run in its host process, which keeps the graphtraj modules it loaded; I replaces graphtraj. So Main exits before I and resumes after it."
  print "Main tells the USER, then the USER /exits Main and runs I in a Terminal:"
  next "(USER, normal Terminal, after /exit in Main) zsh $THIS I" ;;

I) need_main
  print "[I] USER (Main tells the USER first; the USER /exits Main, then runs this in a normal Terminal). Waits for members, backs up to $BK, installs ONLY the graphtraj wheel of ${TARGET[1,8]} into $RT (graphtraj ${OLD[1,8]} -> ${TARGET[1,8]}; graftling $GLVERSION untouched) with pip --force-reinstall --no-deps --no-index, checks the real entries. No login. Dialog: none (one Enter to confirm). ~3 min plus waiting."
  [[ -e $BK ]] && { print "STOP: $BK exists; I never overwrites a backup. Tell Main. (After a failed I that R rolled back, Main runs: zsh $THIS I0)"; exit 1; }
  [[ -e $R/V.ok ]] && grep -q '^CHECK 616 GR614 no new failure .*: PASS' $R/GR614.txt 2>/dev/null || { print "STOP: V or GR614 has not passed. Nothing changed."; exit 1; }
  product_guard || { print "STOP: product guard. Nothing changed."; exit 1; }
  print "Confirm that you typed /exit in the Claude Code Main. Enter to continue, Ctrl-C to stop."; read -r answer
  { members_idle I || { print "STOP: a member or host still runs (above). Nothing changed; wait, then rerun I (never kill them)."; exit 1; }
    date '+I start %F %T'
    say "backup: venv (manifest + cp -Rp), hook copy, entry files (mode 600), the tools R needs; COMPLETE marker"
    mkdir -p $BK/tools $BK/entries && chmod 700 $BK || exit 1
    cp -p $THIS $S593/adopt_tree.py $S593/pkgdiff532.py $BK/tools/ && print -r -- $MAIN > $BK/tools/main.session && cp -p $SCR/main.session $BK/main.session || exit 1
    tree manifest $RT $BK/venv.manifest && cp -Rp $RT $BK/venv && tree compare $BK/venv.manifest $BK/venv || { print "STOP: venv backup failed; production unchanged"; exit 1; }
    tree manifest $PDIR $BK/plugin.manifest && cp -Rp $PDIR $BK/plugin || exit 1
    for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || exit 1; done; chmod 600 $BK/entries/*(D) || exit 1
    shasum -a 256 $ENTRIES > $BK/entries.sha256; touch $BK/COMPLETE; print "backup COMPLETE: $BK"
    shasum -a 256 -c $AD/entries.sha256 > /dev/null; ck $? "I entry files unchanged since V"
    members_idle I-before-pip || { print "STOP: a member started; backup done, production unchanged. Main runs I0 before a rerun."; exit 1; }
    touch $BK/INSTALL-STARTED; date +%s > $R/I-install-start.epoch
    gt=($NT/graphtraj-$GTVERSION-*.whl(N)); (cd $NT && shasum -a 256 -c SHA256SUMS) || exit 1
    say "pip install --force-reinstall --no-deps --no-index ${gt:t} (same version $GTVERSION, so --force-reinstall; graftling not reinstalled)"
    clean $RT/bin/python -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall --no-deps --no-index $gt[1]; ck $? "I pip install of the ${TARGET[1,8]} graphtraj wheel"
    date +%s > $R/I-install-end.epoch
    sp=$(site); bs=($BK/venv/lib/python*/site-packages(N/))
    clean $CONDA -I $S593/pkgdiff532.py graftling $sp ${bs[1]:-$BK/venv/missing} "616 I graftling unchanged (installed vs backup, package and dist-info)" - | tail -1; ck ${pipestatus[1]} "I graftling $GLVERSION package and dist-info unchanged vs the backup"
    direct_urls
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"*.whl* ]]; ck $? "I graphtraj direct_url is wheels-${TARGET[1,8]}"
    [[ $DGL == *"$NG/graftling-$GLVERSION-"*.whl* ]]; ck $? "I graftling direct_url is still 612's wheels-$GLVERSION"
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $gt[1] $sp "616 I installed graphtraj equals the ${TARGET[1,8]} wheel" - | tail -1; ck ${pipestatus[1]} "I installed graphtraj files equal the wheel"
    [[ -d $TSRC/manuals ]] || { mkdir -p $TSRC && gg -C $WT archive $TARGET | tar -x -C $TSRC; }   # B's archive of TARGET
    manuals_check I $RT/share/graphtraj/manuals
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "I production pip check" "${pc[1,120]}"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && $(head -1 $RT/bin/graphtraj-mcp) == "#!$RT/bin/python"* ]]
    ck $? "I production bin subagents, subagents-mcp, graphtraj-mcp (this venv's python)"
    clean $RT/bin/python -I $S593/onegraft.py $RT $GLVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "I one graftling $GLVERSION in production (onegraft.py)"
    say "real entries of production (run in the isolated $VPROJ) and the files that must not change"
    mcp_probe I-production $RT
    (cd ${TMPDIR:-/tmp} && clean $RT/bin/python -I $SD/v616.py mcp I-production $VPROJ $RT/bin/graphtraj-mcp); ck $? "I production graphtraj-mcp: subagents discover lists models (v616.py mcp)"
    codex_hook_check $RT
    diff -r $BK/plugin $PDIR > /dev/null; ck $? "I hook copy byte-identical to the backup (no configuration --write: V proved no change)"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__}; ck $? "I ${f#$H/} byte-identical to the backup"; done
    guard > /dev/null; ck $? "I no process started on $RT during the install"
  } 2>&1 | tee -a $R/I.txt; rc=${pipestatus[1]}
  if (( rc != 0 )) || grep -q '^CHECK 616 I .*: FAIL' $R/I.txt; then
    [[ -e $BK/INSTALL-STARTED ]] && print "\nI FAILED after the install began. Do not resume Main. Run the rollback now:\n  zsh $BK/tools/steps.zsh R" || print "\nI STOP before the install (production unchanged). Tell Main."
    exit 1
  fi
  touch $R/I.ok
  summary I "$(grep -E '^(I start|backup COMPLETE|graphtraj direct_url|graftling direct_url|CHECK|INFO)' $R/I.txt)"
  print "Success: every 'CHECK 616 I ...: PASS'. Rollback, if ever needed (Main asks the USER first): zsh $BK/tools/steps.zsh R"
  print "\nNext (USER, normal Terminal): resume Main (same Session):\n  cd $H && claude --continue"
  print "Expected dialog: none (the hook copy and .mcp.json are unchanged). If a plugin/hooks trust dialog or any other dialog appears anyway: Esc and tell Main (unexpected). If --continue opens another conversation: /exit, then cd $H && claude --resume $MAIN"
  next "Main (resumed): zsh $THIS M" ;;

M) need_main; cv; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main (resumed with claude --continue, Session $MAIN). Paste one at a time; Main saves each raw answer as $R/M-<letter>.txt. Login: none beyond the running Main. Dialog: none expected (if a tool permission dialog appears: 'Yes' once, not always, and tell the Team).
Every tool call below passes its arguments INLINE in the "arguments" field; never use arguments_file. Claude Code may first load a tool's schema with ToolSearch (select:mcp__graphtraj__subagents or select:mcp__graphtraj__tasks); that is allowed (614) and Mr lists it.

[a] Using no tools: list exactly every tool in your current tool list whose name starts with mcp__graphtraj__, mcp__graftling__ or mcp__agents__, and list every GraphTraj/Graftling notice delivered to you since this resume, saying for each whether you had seen it before the resume.
  Success: only mcp__graphtraj__subagents and mcp__graphtraj__tasks; no notice seen before the resume appears again.

[b] Using only mcp__graphtraj__subagents: execute status with arguments {} given inline (no agent, no arguments_file). Print the raw result and whether it was an error. Then using only mcp__graphtraj__tasks: execute task_graph with arguments {"view":"current","details":["$TASK_ID"]} given inline (no arguments_file) and print only whether an error was returned and Task $TASK_ID's current definition path.
  Success: subagents status answers without error; task_graph without error, Task $TASK_ID's current definition definitions/<time>.md.
EOF2
  next "zsh $THIS Mr" ;;

Mr) need_main; print "[Mr] Main, after M[b]. Read only: Main's own transcript after I's install end must hold mcp__graphtraj__subagents and mcp__graphtraj__tasks calls answered without error (593's rec593.py); Claude Code's ToolSearch select: of the same mcp__graphtraj tool is allowed and listed (614). No login. Dialog: none."
  { split=$(cat $R/I-install-end.epoch 2>/dev/null); [[ -n $split ]] || { print "STOP: I has not finished (no I-install-end.epoch)"; exit 1; }
    files=(${(f)"$(main_transcripts $R/I-install-end.epoch)"})
    print -r -- "Main transcripts read: $files"
    clean $CONDA -I $S593/rec593.py calls "Main $MAIN" --after $split --need subagents,tasks --old-info $files
    ck $? "Mr Main called mcp__graphtraj__subagents and mcp__graphtraj__tasks after I without error (rec593.py above)"
    clean $CONDA -I $SD/p616.py calls Mr $split - $files
  } 2>&1 | tee $R/Mr.txt
  grep -q ': FAIL' $R/Mr.txt && { print "\nMr FAIL (see above): did Main do M[b] with inline arguments? Hand $R/Mr.txt to the Team."; exit 1; }
  print "Success: 'CHECK 616 Mr ...: PASS'."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. One real dispatch: an advisor member on Task $TASK_ID creates the Claude child $CHILD (model $MODEL) through mcp__graphtraj__subagents WITHOUT tools; the child runs Bash and replies $DONEWORD; the member waits, reads and retires it. Login: $LOGIN_NOTE; Main does not ask again. Dialog: none expected (a tool permission dialog: 'Yes' once and tell the Team). 616's Leader and Engineer have ended their turns. ~3-5 min. Paste in the Claude Main (arguments INLINE, never arguments_file):
Using only mcp__graphtraj__tasks: execute swarm with these arguments given inline in the "arguments" field (no arguments_file) {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"This is a production check. Do NOT call submit_result or submit_report. Pass every tool's arguments inline in the arguments field; never use arguments_file. (a) Using the subagents tool (mcp__graphtraj__subagents), create ONE claude child named $CHILD with configuration opus_coding_team.advisor, WITHOUT a tools argument (do not pass tools or disallowed_tools), and this message: <<This is a scripted probe. Call Bash once with exactly: echo $CHILD-tool && sleep 20 ; then reply with exactly: $DONEWORD>>. Quote the raw create result (agent id, session, execution id). If the child asks you to approve a Bash command, approve exactly that command. (b) Call subagents wait on that agent id with timeout_seconds 300, repeating until the execution has ended; quote the final wait result's last_message. Then call subagents status with arguments {agent: <agent id>} and quote its configuration, model and last_message. (c) Retire the child by its agent id and quote the raw result. End your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main saves the raw swarm result as $R/N.txt (it must hold "agent"), every notice of this member as $R/N-main-notice.txt (one line per notice, exactly as received: '[Graftling notice from <alias> · completed · execution <hex>] <its text>' or '[GraphTraj notice from ...] <its text>', header and text on the SAME line), and the member's final reply as $R/N-reply.txt.
  After the member's completed notice, before retiring the member, Main's Bash: zsh $THIS Nr
EOF2
  next "zsh $THIS Nr" ;;

Nr) print "[Nr] Main. Read only: the child $CHILD's and the member's records, one notice, the member's subagents calls (593's nr_read with $DONEWORD, rec593.py, notices499.py). No login. Dialog: none."
  { nr_read; nrc=$?
    ck $nrc "Nr 593's record checks ran (their CHECK lines above)"
  } 2>&1 | tee $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1)
  { if [[ -s $R/N-main-notice.txt ]]; then nc=$(clean $CONDA -I $S593/notices499.py $R/N-main-notice.txt "$MEMBER"); [[ $nc == 1 ]]; ck $? "Nr Main got exactly one completed notice of the member" "$nc"
    else print "CHECK 616 Nr Main got exactly one completed notice of the member: PENDING (save it to $R/N-main-notice.txt)"; fi
    SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1); bare=${SID#*:}
    if [[ -n $MEMBER && -n $bare ]]; then   # the member's records by its Session id (593's rs_session_files): archive header, Claude transcript
      mf=(); for f in $SESS/*/session.jsonl(N); do head -1 $f | grep -qF -- $bare && mf+=$f; done; mf+=(${PROJECTS:h}/*/$bare.jsonl(N))
      print -r -- "member $MEMBER (Session $SID) record files: ${#mf}"
      clean $CONDA -I $S593/rec593.py calls "member $MEMBER" --need subagents $mf; ck $? "Nr member called mcp__graphtraj__subagents without error (rec593.py above)"
    else ck 1 "Nr member alias and Session found" "member ${MEMBER:-none}, session ${SID:-none}"; fi
    grep -qF -- $MODEL $R/N-reply.txt 2>/dev/null; ck $? "Nr the member's reply quotes the child's model $MODEL"
    sa=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
    [[ -n $sa ]]; ck $? "Nr swarm result has agent" "${sa:-none}"
    [[ -n $sa ]] && print -r -- "SWARM_AGENT $sa"
  } 2>&1 | tee -a $R/Nr.txt
  grep -qE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)' $R/Nr.txt && { print "\nNr not passed (see above). PENDING: save the files and rerun Nr. FAIL: hand $R/Nr.txt to the Team."; exit 1; }
  sa=$(sed -n 's/^SWARM_AGENT //p' $R/Nr.txt | tail -1)
  [[ -n $sa ]] && print "\nRetire the member (Main pastes): Using only mcp__graphtraj__subagents: retire with arguments {\"agent\":\"$sa\"} given inline (no arguments_file) and print the raw result."
  print "Success: every CHECK line PASS (child completed with $DONEWORD, created without tools, one execution, notice delivered; member's subagents calls; one notice; model; swarm agent)."
  next "zsh $THIS P" ;;

P) need_main; print "[P] Main. Read only: with production's own (installed) graphtraj and graftling it checks the models contract and that models reads only project roles and the user catalog (no login, no key, no process), prints the user catalog by NAMES only, computes the expected answer (role_models on $H, runtime claude), records the Agent/Session counts, and prints ONE prompt for Main's MCP call: mcp__graphtraj__subagents execute models. The step itself calls nothing. No login. Dialog: none."
  { rm -f $R/P.txt $R/P-expect.json
    [[ -e $R/I.ok ]] || { print "STOP: I has not passed (no $R/I.ok)"; exit 1; }
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"; direct_urls
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"*.whl* ]]; ck $? "P production graphtraj is wheels-${TARGET[1,8]} (installed by I)"
    (cd ${TMPDIR:-/tmp} && clean ${ADOPT616_CATALOG_HOME:+HOME=$ADOPT616_CATALOG_HOME} $RT/bin/python -I $SD/p616.py expect $H $R/P-expect.json); ck $? "P p616.py expect (contract, code, catalog names, expected groups)"
    print -r -- "COUNTS $(record_counts)"
    date +%s > $R/P.epoch
  } 2>&1 | tee $R/P-pre.txt; rc=${pipestatus[1]}
  if grep -q '^LOGIN-OR-KEY STOP' $R/P-pre.txt; then print "\nP STOP: the installed models code may use a login or key other than Claude's. Nothing was called. Main asks the USER before any models call and tells the Team."; exit 1; fi
  (( rc == 0 )) && ! grep -q ': FAIL' $R/P-pre.txt || { print "\nP STOP (see above). Nothing was called. Hand $R/P-pre.txt to the Team."; exit 1; }
  args=$(sed -n 's/^ARGS //p' $R/P-pre.txt | tail -1)
  cat <<EOF2 | tee $R/P-prompt.txt

[P] Paste in the Claude Main (ONE call; arguments INLINE, never arguments_file). It lists the project roles create can select for the Claude Runtime, grouped by catalog provider: files only, no native query, no child, no key (Claude Code may first load the tool's schema with ToolSearch select:mcp__graphtraj__subagents; that is allowed).
Using only mcp__graphtraj__subagents: execute models with arguments $args given inline in the "arguments" field (no arguments_file). Print the raw result exactly and whether it was an error. Then, with Bash, save that raw result exactly (the whole document) as $R/P.txt.
  Success: no error; result.runtime claude, status available, and result.groups [{provider, models: [...]}] as P printed above (expected groups), every api_key_env a variable name or null.
EOF2
  next "zsh $THIS Pr    (after Main saved $R/P.txt)" ;;

Pr) need_main; print "[Pr] Main. Read only: Main's raw models result ($R/P.txt) against P's expectation and counts, and Main's transcript (the mcp__graphtraj__subagents execute models call after P, answered without error; ToolSearch select: allowed). No login. Dialog: none."
  { [[ -s $R/P-pre.txt && -s $R/P-expect.json && -s $R/P.epoch ]] || { print "STOP: no $R/P-pre.txt or P-expect.json: run P first"; exit 1; }
    [[ -s $R/P.txt ]] || { print "STOP: no $R/P.txt: Main has not saved the raw models result yet (P's prompt)"; exit 1; }
    before=$(sed -n 's/^COUNTS //p' $R/P-pre.txt | tail -1)
    clean $CONDA -I $SD/p616.py judge $R/P.txt $R/P-expect.json "$before" "$(record_counts)"
    ck $? "Pr checks above (grouped by provider, key names only, no credential-like value, nothing created)"
    files=(${(f)"$(main_transcripts $R/P.epoch)"}); print -r -- "Main transcripts read: $files"
    clean $CONDA -I $SD/p616.py calls Pr $(<$R/P.epoch) models $files
  } 2>&1 | tee $R/Pr.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/Pr.txt || { print "\nPr STOP or FAIL (see above). Hand $R/Pr.txt and $R/P.txt to the Team."; exit 1; }
  summary Pr "$(grep -E '^(result|CHECK|INFO)' $R/Pr.txt)"
  print "Success: every 'CHECK 616 Pr ...: PASS'."
  next "zsh $THIS done" ;;

R) need_main; print "[R] USER (Main asks the USER first; after agreeing the USER /exits Main and runs this in a normal Terminal). Restores the whole venv (graphtraj ${OLD[1,8]} + graftling $GLVERSION), the hook copy and the entry files from $BK; the current ones are kept in $BK/after-install-*. No login. Dialog: none (one Enter). Enter to continue, Ctrl-C to stop."; read -r answer
  [[ -e $BK/COMPLETE ]] || { print "STOP: no complete backup in $BK (the install starts only after it): production was not changed by I. Tell Main."; exit 1; }
  { members_idle R || { print "STOP: a member or host runs (above). Nothing restored."; exit 1; }
    KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S); mkdir -p $KEEP/entries
    mv $RT $KEEP/venv && cp -Rp $BK/venv $RT || exit 1
    tree compare $BK/venv.manifest $RT; ck $? "R venv equals the pre-install bytes"
    [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; cp -Rp $BK/plugin $PDIR || exit 1
    tree compare $BK/plugin.manifest $PDIR; ck $? "R hook copy restored"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__} || { cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $BK/entries/${${f#$H/}//\//__} $f; }; done
    shasum -a 256 -c $BK/entries.sha256; ck $? "R entry files restored"
    direct_urls; [[ $DGT == *"wheels-${OLD[1,8]}/graphtraj-$GTVERSION-"* && $DGL == *"wheels-$GLVERSION/graftling-$GLVERSION-"* ]]; ck $? "R graphtraj from wheels-${OLD[1,8]} and graftling $GLVERSION from 612's wheel again"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "R pip check" "${pc[1,120]}"
    CH=$H/.graphtraj/claude-host/live/channel.json; [[ -e $CH ]] && mv $CH $KEEP/channel.json && print "moved out a stale $CH"
  } 2>&1 | tee -a $R/R.txt
  grep -q '^CHECK 616 R .*: FAIL' $R/R.txt && { print "\nR left a difference (above). Do not resume Main; hand $R/R.txt to Main. R can be rerun."; exit 1; }
  print "Success: every 'CHECK 616 R ...: PASS'. Then (USER): cd $H && claude --continue" ;;

done) print "[done] Main. Read only: every CHECK line of every step's raw file, and production now. No login. Dialog: none."
  { miss=""
    steps=(00 B GR614 V Mpre I Mr Nr P-pre Pr)
    runs=($R/run<->(N/))
    (( $#runs )) && steps+=(I0)   # a failed I was set aside: I0 must have passed
    for d in $runs; do   # set-aside runs are listed, never counted (only the current I and R records count)
      print -r -- "SUPERSEDED ${d:t}: $(cat $d/SUPERSEDED 2>/dev/null || print 'set aside by I0') | files: $(print -l $d/*(N:t) | tr '\n' ' ')| its CHECK FAIL lines (not counted): $(cat $d/*.txt(N) | grep -c '^CHECK .*: FAIL')"
    done
    for s in $steps; do [[ -s $R/$s.txt ]] || miss="$miss $s"; done
    grep -h '^CHECK ' $R/${^steps}.txt(N)
    np=$(cat $R/${^steps}.txt(N) | grep -c '^CHECK .*: PASS') nf=$(cat $R/${^steps}.txt(N) | grep -cE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)')
    say "production now"
    print -r -- "graphtraj graftling: $(prod_versions)"; direct_urls
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"* && $DGL == *"$NG/graftling-$GLVERSION-"* ]]
    ck $? "done production graphtraj from wheels-${TARGET[1,8]}, graftling $GLVERSION from 612's wheels-$GLVERSION"
    print -r -- "steps without a raw file:${miss:- none} | CHECK PASS $np | CHECK not passed $nf"
    [[ -z $miss && $nf == 0 ]]; ck $? "done every step ran and every CHECK passed"
  } 2>&1 | tee $R/done.txt
  grep -q '^CHECK 616 done every step ran and every CHECK passed: PASS' $R/done.txt && ! grep -qE '^CHECK .*: FAIL' $R/done.txt || { print "\ndone: FAIL (see above). Hand $R/done.txt to the Team."; exit 1; }
  print "Success: both 'CHECK 616 done ...: PASS' (production graphtraj ${TARGET[1,8]} + graftling $GLVERSION; every step's CHECK passed)."
  next "Main: hand $R to the Team; Task 616 steps complete. Rollback stays available (Main asks the USER first): zsh $BK/tools/steps.zsh R" ;;

*) print "usage: zsh $THIS 00|B|GR614|V|I0|Mpre|I|M|Mr|N|Nr|P|Pr|done|R"; exit 2 ;;
esac
