#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 625 Main-run steps: release graftling 0.10.2 (compatible: 619, `import graftling` works on Windows; on Windows
# process listing raises a clear OSError and the Codex parent host refuses with the existing code authority-denied,
# where both failed at import; POSIX unchanged) and adopt it into production.
# GraphTraj stays 4ef36426 (616's wheel, reused, never rebuilt); its range graftling>=0.10.0,<0.11 includes 0.10.2.
# One release commit 57bca736 "graftling 0.10.2 (625)" on graftling dev 6166718, in graftling-0.10.2.bundle next to
# this file. User decision (Worldline): release, push and adoption 20261125T154402.789038+0900 ("发布 0.10.2 并换到生产").
# Run one step at a time:  zsh <this file> <STEP>     ONE ordered list:
#   00 -> rel -> B -> G (Main starts it as a background command; G itself waits for its shards and ends with GR's
#   verdict; -> SR -> suite-base only if NEW) -> [G ended PASS] -> rp -> gh -> C5 -> V -> Mpre
#   -> [Main tells the USER; 625's Leader and Engineer have ended their turns] USER /exit Main -> I (USER, Terminal)
#   -> USER `cd <Harness> && claude --continue` -> M -> Mr -> N -> Nr -> done.
#   rp needs GR passed: the definition requires the paired GraphTraj suite BEFORE the push. B, V meanwhile are fine.
#   Rollback: R (Main asks the USER first; the USER /exits Main), run from the backup's own copy.
#   A failed I that R rolled back: I0 -> Mpre -> USER /exit + I -> claude --continue -> M -> ... -> done (README.md).
# No production-visible 0.10.2 observable exists on macOS (619 changes Windows only), so 617's Q/Qr are dropped; B, C5,
# V and I check 619's marker in the installed code instead (marker619) and GR requires graftling 0.10.2 in the suite.
# I installs ONLY the graftling 0.10.2 wheel (git archive v0.10.2) with pip --force-reinstall --no-deps --no-index;
# graphtraj is not reinstalled, and I checks its files and dist-info equal the backup's and its direct_url is 616's.
# Login: the Claude login the user approved (603/604/612/616/617) for 00's probe and N; Main's own running Session
# carries M. Network: github.com for 00, rp, gh, C5 (the user's usual git credentials for rp); PyPI and uv's Python
# download for C5. No other login or key.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer; Main leaves all of these unset): ADOPT625_H, ADOPT625_WT, ADOPT625_STUB, ADOPT625_PROJECTS,
# ADOPT625_VPROJECT, ADOPT625_OUT, ADOPT625_SCRATCH, ADOPT625_UVT, ADOPT625_G, ADOPT625_GDEV, ADOPT625_GURL,
# ADOPT625_SOURCE, ADOPT625_NOSNAP, ADOPT625_GWAIT, ADOPT625_PYTEST_ARGS, ADOPT625_CLEAN_EXTRA.
# No zsh special parameter name is used as a variable (path is used only as zsh's PATH array, as 593/600/604/612/616/617).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
TASKDIR=625-graftling-0-10-2-release-and-production-adoption
TASK_ID=625
H=${ADOPT625_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}   # the Harness (production)
WT=${ADOPT625_WT:-$H/.graphtraj/core/worktrees/$TASKDIR}                           # this Task Worktree
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused by path: adopt_tree.py, pkgdiff532.py, onegraft.py, ...
S616=$WT/scripts/adopt-616                          # reused by path: p616.py (Mr's ToolSearch INFO lines)
S617=$WT/scripts/adopt-617                          # reused by path: q617.py mcp (discover 'start an agent' = [create])
STEP=${1:-}
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
DECISION=20261125T154402.789038+0900                # the user's release, push and adoption decision
LOGIN_NOTE="the Claude login the user approved (603/604/612/616/617), named in Task 625's definition (acceptance)"
path=($HOME/.local/bin /opt/homebrew/bin $path)     # claude and node, as 593/600/604/612/616/617 (the USER's usual installs)
[[ -n ${ADOPT625_STUB:-} ]] && path=($ADOPT625_STUB $path)   # rehearsal only: stub claude/ps first
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; builds the wheel, runs the helpers with -I
CROOT=${CONDA:h:h}
# ---- graftling release ----
G=${ADOPT625_G:-$H/graftling}                       # main is checked out here
GDEV=${ADOPT625_GDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # dev is checked out here
GURL=${ADOPT625_GURL:-https://github.com/LUOXIAO92/graftling.git}   # origin of $G (GitHub)
GBASE=616671870fb2dd9679ea18fdfdbd2f094b1ae0a9      # graftling dev at dispatch (6166718, 619)
GMAIN0=82e9d12b7c4a76e4074d405fbd135f3c38f1103a     # graftling main = v0.10.1 (617)
GCOMMIT=57bca73657d3135a4504904fcc3f1898c2419766    # graftling 0.10.2 (625), parent $GBASE
GBRANCH=agent/625-graftling-0.10.2
BUNDLE=$SD/graftling-0.10.2.bundle
BSHA=3253fbfabea6775caa7293bdf3d3347b883cdb52bf7bbefc1ba67b625f5ea9a8
GFILES="CHANGELOG.md src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json"
GTAG=v0.10.2
GVERSION=0.10.2
GOLDVERSION=0.10.1
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
RELMSG="graftling 0.10.2 (compatible): 619, import graftling works on Windows; on Windows process listing raises a clear OSError and the Codex parent host refuses with the existing error code authority-denied, where both used to fail at import; POSIX behaviour is unchanged; no public name, argument, result field, error code or result shape changes and nothing that used to succeed is refused (PUBLIC_API section 7)."
SRCURL="git+https://github.com/LUOXIAO92/graftling.git"   # the README's TAGLESS command: the default branch main
INSTALL=(uv tool install --managed-python $SRCURL)
[[ -n ${ADOPT625_SOURCE:-} ]] && INSTALL=(uv tool install --managed-python $ADOPT625_SOURCE)   # rehearsal only
UVT=${ADOPT625_UVT:-/private/tmp/uvtool-625}
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT625_NOSNAP:-}
# ---- GraphTraj (unchanged) and production ----
TARGET=4ef36426ab6fa5a4769a23557aecf2aa2e2b3759     # production graphtraj now and after I (616's wheel)
TSHA=ac805ac9b3fb88f328a932a52ecd807a369ff25500f15d67d94489a1508bf473   # 616's graphtraj wheel
GOLDSHA=764d010b822cbe5a94767de0e215841cb49fbc8be7e5b271817521e9c36063f1 # 617's graftling 0.10.1 wheel (production now; R's target)
GTVERSION=0.1.0
DEV0=4b71012cc36b15063576c86038cf36c383d5989b       # GraphTraj dev at dispatch (this Worktree's base); its product = TARGET's
GUARDED=(src desktop/src pyproject.toml manuals skills plugins)   # the product: must equal TARGET (tests and workflows differ: 618/620/622/619)
STATE=$H/.graphtraj/core/state
T616=616-graphtraj-614-production-adoption
T617=617-graftling-0-10-1-release-and-production-adoption
W617=$STATE/tasks/$T617/adoption/wheels-$GOLDVERSION   # production's graftling 0.10.1 wheel now (617)
NT=$STATE/tasks/$T616/adoption/wheels-${TARGET[1,8]}   # production's graphtraj wheel (616), reused, never rebuilt
AD=$STATE/tasks/$TASKDIR/adoption
NG=$AD/wheels-$GVERSION                             # the graftling wheel G, V and I install (B writes it)
D516=$STATE/tasks/516-low-priority-flaky-tests      # known flaky tests: 516's CURRENT definition via its task.yml
SCR=${ADOPT625_SCRATCH:-$H/tmp/625}
GSRC=$SCR/gsrc                                      # git archive v0.10.2
TSRC=$SCR/tsrc                                      # git archive TARGET (B's comparison; I's manuals)
WHL=$SCR/wheel
BK=$SCR/backup
BK617=$H/tmp/617/backup                             # the current rollback (617); only read
OLDBK=($H/tmp/{600,604,612,616,617}/backup)         # older rollbacks the user keeps: never written, reported by 00 and I
VV=$SCR/vvenv
R=${ADOPT625_OUT:-$STATE/tasks/$TASKDIR/realhost/main-raw}
RT=$H/.venv-runtime
VPROJ=${ADOPT625_VPROJECT:-/private/tmp/vproject-625}   # isolated project for the real MCP entries (graphtraj setup)
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
SESS=$H/.graphtraj/swarm/sessions
RUNNERSESS=$H/.graphtraj/core/runner/sessions
PROJECTS=${ADOPT625_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
MODEL=claude-opus-5-5
CHILD=n625
DONEWORD=DONE-625
SUITEIDS=$WT/scripts/verify-581/suiteids.py
MAIN=$(cat $SCR/main.session 2>/dev/null)

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT625_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean git "$@"; }                            # every git call: allowlist environment
ck() { [[ $1 == 0 ]] && print -r -- "CHECK 625 $2: PASS${3:+ ($3)}" || print -r -- "CHECK 625 $2: FAIL${3:+ ($3)}"; }   # $1 = 0 for pass
U=$(clean /usr/bin/which uv 2>/dev/null)            # the uv on the clean PATH; every uv call uses this one file
rel_wt() {  # the worktree that has branch $1 checked out in $G, if any
  gg -C $G worktree list --porcelain | awk -v b="branch refs/heads/$1" '/^worktree /{w=substr($0,10)} $0==b{print w}'
}
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT625_NOSNAP, rehearsal only)"; return 0; }
  clean $CONDA -I $S593/homesnap593.py snap $1 local=$HOME/.local uvtools=$(clean $U tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) \
    pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT
}
remote_of() { print -r -- $1 | awk -v r="$2" '$2==r{print $1}'; }   # $1 = ls-remote output, $2 = ref
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
direct_urls() {  # $1 = graftling version whose dist-info is read; sets DGT and DGL from production's dist-info
  local sp=$(site); DGT=$(cat $sp/graphtraj-$GTVERSION.dist-info/direct_url.json 2>/dev/null); DGL=$(cat $sp/graftling-$1.dist-info/direct_url.json 2>/dev/null)
  print -r -- "graphtraj direct_url: ${DGT:-none}"; print -r -- "graftling $1 direct_url: ${DGL:-none}"
}
product_guard() {  # HEAD's product (GUARDED) == TARGET (production's graphtraj); HEAD differs from DEV0 only under scripts/adopt-625/; clean
  local head names other dirty range
  head=$(gg -C $WT rev-parse HEAD)
  names=$(gg -C $WT diff --name-only $TARGET HEAD -- $GUARDED 2>&1); other=$(gg -C $WT diff --name-only $DEV0 HEAD 2>&1 | grep -v '^scripts/adopt-625/')
  dirty=$(gg -C $WT status --porcelain -- . ':!scripts/adopt-625/rehearsal' 2>&1)
  range=$(gg -C $WT show ${TARGET}:pyproject.toml 2>/dev/null | grep -m1 '"graftling')
  print -r -- "product guard: HEAD $head | git diff ${TARGET[1,8]} HEAD -- ${GUARDED[*]}: ${${names//$'\n'/ }:-empty} | changes since GraphTraj dev ${DEV0[1,8]} outside scripts/adopt-625/: ${${other//$'\n'/ }:-none} | uncommitted (rehearsal outputs excepted): ${${dirty//$'\n'/ }:-none} | graftling range at ${TARGET[1,8]}: ${range//[[:space:]]/}"
  gg -C $WT merge-base --is-ancestor $TARGET $DEV0 && gg -C $WT merge-base --is-ancestor $DEV0 HEAD \
    && [[ -z $names && -z $other && -z $dirty && ${range//[[:space:]]/} == '"graftling>=0.10.0,<0.11",' ]]
}
marker619() {  # $1 = label, $2 = an installed or unpacked graftling package dir: 619's fix is in that code
  local a=$2/sessions/archive.py f i e w c
  f=$(grep -cE '^[[:space:]]*import fcntl' $a 2>/dev/null) i=$(grep -c '^from graftling.locks import exclusive, ignore_in_git$' $a 2>/dev/null)
  e=$(grep -c 'with exclusive(' $a 2>/dev/null)
  w=$(grep -cF "raise OSError('Listing marked processes is not supported on Windows.')" $2/member_processes.py 2>/dev/null)
  c=$(grep -cF "raise AgentsError('authority-denied', 'Windows does not support the Codex parent host.')" $2/codex/host.py 2>/dev/null)
  print -r -- "  619 marker in $2: sessions/archive.py 'import fcntl' x${f:-0}, 'from graftling.locks import exclusive, ignore_in_git' x${i:-0}, 'with exclusive(' x${e:-0} | member_processes.py Windows OSError x${w:-0} | codex/host.py Windows authority-denied x${c:-0}"
  (( ${f:-0} == 0 && ${i:-0} == 1 && ${e:-0} == 2 && ${w:-0} == 1 && ${c:-0} == 1 ))
  ck $? "$1 619's fix is in $2 (archive.py: no 'import fcntl', locks.exclusive x2; Windows errors in member_processes.py and codex/host.py)"
}
oldbk_report() {  # $1 = label: the older rollbacks the user keeps (never written); prints one fingerprint line each
  local b
  for b in $OLDBK; do
    if [[ -e $b ]]; then print -r -- "  $1 kept backup $b: $([[ -e $b/COMPLETE ]] && print COMPLETE || print 'no COMPLETE') | top-level mtime $(stat -f '%m' $b) | entries $(find $b -maxdepth 2 2>/dev/null | wc -l | tr -d ' ')"
    else print -r -- "  $1 kept backup $b: absent"; fi
  done
}
other_suites() {  # test runs of anyone; exit 2 when ps cannot list (never read as "no other suite")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then print -r -- "ps cannot list processes (${listed[1,160]})"; return 2; fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E|other_suites'
  return 0
}
# 593/600/604/612/616's guard: BLOCKING = a live process naming $RT/, Main's host config or Main's Session id; budget
# timers and zombies are listed, never blocking; nothing is ever signalled. Return 2 when ps cannot list.
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
    print -r -- "# 625 scratch project" > $VPROJ/README.md
    gg -C $VPROJ add README.md && gg -C $VPROJ -c user.name=625 -c user.email=625@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJ/.graphtraj/core/config.yml || -e $VPROJ/.graphtraj/config.yml ]] && gg -C $VPROJ rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJ && print -r -- y | clean $1 setup) > /dev/null || return 1
  fi
}
mcp_probe() {  # $1 = label, $2 = venv: tools/list exactly subagents, tasks; 'agents' unknown (mcp593.py); discover intent (617's q617.py)
  (cd ${TMPDIR:-/tmp} && clean $2/bin/python -I $(helper mcp593.py) $1 $VPROJ $2/bin/graphtraj-mcp); ck $? "$1 graphtraj-mcp tools/list is exactly subagents, tasks and 'agents' is unknown (mcp593.py above)"
  (cd ${TMPDIR:-/tmp} && clean $2/bin/python -I $S617/q617.py mcp $1 $VPROJ $2/bin/graphtraj-mcp); ck $? "$1 617's q617.py mcp (still holds on $GVERSION): discover 'start an agent' = [create], 'list models' finds models"
}
codex_hook_check() {  # $1 = venv: the Codex hooks entry names this venv's python and answers a neutral event with {} (no login)
  local P=$1/bin/python out cmd
  out=$(cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook --configuration 2>&1)
  cmd=$(print -r -- "$out" | clean $CONDA -I -c 'import json,sys; d=json.load(sys.stdin); print(sorted({h["command"] for e in d["hooks"].values() for g in e for h in g["hooks"]}), sorted(d["hooks"]))' 2>&1)
  print -r -- "Codex hooks entry configuration: $cmd"
  [[ $cmd == *"'$P -m graphtraj.runtimes.codex.stop_hook'"*"'SessionEnd', 'SessionStart', 'Stop'"* ]]; ck $? "Codex hooks entry of $1 names its python for SessionStart/Stop/SessionEnd"
  out=$(print -r -- '{"hook_event_name":"Probe625","session_id":"probe-625","cwd":"'$VPROJ'"}' | (cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
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
      print -r -- "INFO 625 $1 tolerated in $2: .claude/.cc-writes (empty), the Claude Code sandbox write marker (inferred, 612; not a product file, in no RECORD); .claude $(stat -f '%Sm' -t '%F %T' $m) | .cc-writes $(stat -f '%Sm' -t '%F %T' $m/.cc-writes)"
    fi
  fi
  print -r -- "diff -r archive manuals vs $2 (the marker excepted): ${${d//$'\n'/ | }[1,300]:-none}"
  [[ -z $d ]]; ck $? "$1 share/graphtraj/manuals equals git archive ${TARGET[1,8]}'s manuals ($(find $2 -type f ! -path "$2/.claude/*" 2>/dev/null | wc -l | tr -d ' ') product files)"
}
sr_classify() {  # $1 = G record. Sets SR_NEW, SR_ANY, SR_IDS; writes <record>/new-ids.txt (every ABNORMAL line read)
  local rec=$1 line t id timeouts=0; SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): $KNOWN516"
  print -r -- "known non-blocking ids: ONLY those in 516's current definition"
  [[ -f $KNOWN516 ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print "  (no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL ' $rec/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *': exit 5') grep -q '^REHEARSAL' $rec/run.txt && print -r -- "  rehearsal filter, nothing collected: $line" || { print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1; } ;;
      *'timed out after '*) print -r -- "  ABNORMAL shard TIMED OUT (NEW): $line"; SR_NEW=1; timeouts=$(( timeouts + 1 )) ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -r -- "  shard timeouts ('timed out after' lines): $timeouts"
  print -l -- $SR_IDS > $rec/new-ids.txt
}
tig_of() {  # $1 = G record: the graftling version the test interpreter imported (run.txt's 'test interpreter graftling' line)
  sed -n 's/^test interpreter graftling: \([^ ]*\) .*/\1/p' $1/run.txt 2>/dev/null | head -1
}
grec() { print -r -- ${$(print -l $AD/G-*(N/om[1])):-$AD/G-none}; }   # newest G record
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
gr_passed() { [[ -e $R/GR.ok ]] && grep -q "^RESULT 625 G/GR: PASS" $R/GR.txt 2>/dev/null; }

mkdir -p $R || exit 1
cred_guard
[[ -n $U || $STEP == R ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
case $STEP in
00) print "[00] Main. Read only, apart from creating $SCR (main.session, cc.version, the probe's stream, a scratch clone g00.git to read the bundle). Login: yes, one claude -p probe with $LOGIN_NOTE; no Codex, Pi or DSH. Network: github.com (git ls-remote) and Claude. Dialog: none."
  { mkdir -p $SCR || exit 1
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python'; ck $? "00 this uv's 'uv tool install --help' lists --managed-python"
    check_tmp; ck $? "00 TMPDIR outside the Harness"
    [[ ! -e $UVT ]]; ck $? "00 $UVT absent" "$([[ -e $UVT ]] && print "move it aside first: mv $UVT $UVT.old-\$(date +%s)")"
    say "graftling repository $G (read only)"
    gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "dev: ${gd:-NOT FOUND} in ${dw:-no worktree} | main: ${gm:-NOT FOUND} in ${mw:-no worktree}"
    [[ $gd == $GBASE ]]; ck $? "00 graftling dev = $GBASE"
    [[ $gm == $GMAIN0 ]]; ck $? "00 graftling main = $GMAIN0 (v$GOLDVERSION)"
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]]; ck $? "00 dev is checked out in $GDEV and main in $G"
    dirty=""; for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || dirty="$dirty $w"; done
    [[ -z $dirty ]]; ck $? "00 both worktrees clean (git status --porcelain empty)" "${dirty# }"
    lt=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG); [[ -z $lt ]]; ck $? "00 $GTAG absent locally" "$lt"
    say "GitHub $GURL (git ls-remote, read only)"
    if rem=$(gg ls-remote $GURL refs/heads/main refs/heads/dev refs/tags/$GTAG 2>&1); then
      rm0=$(remote_of $rem refs/heads/main) rd0=$(remote_of $rem refs/heads/dev) rt0=$(remote_of $rem refs/tags/$GTAG)
      print -r -- "GitHub main: ${rm0:-absent} | dev: ${rd0:-absent} | $GTAG: ${rt0:-absent}"
      [[ $rm0 == $GMAIN0 ]]; ck $? "00 GitHub main = $GMAIN0"
      [[ -z $rt0 ]]; ck $? "00 GitHub $GTAG absent"
      [[ -n $rd0 ]] && gg -C $G merge-base --is-ancestor $rd0 $GBASE 2>/dev/null; ck $? "00 GitHub dev (${rd0:-absent}) is $GBASE or its ancestor, so rp fast-forwards it"
    else ck 1 "00 git ls-remote $GURL" "${rem[1,200]}"; fi
    say "bundle $BUNDLE"
    bs=$(shasum -a 256 $BUNDLE | cut -d' ' -f1); print -r -- "sha256: $bs"
    [[ $bs == $BSHA ]]; ck $? "00 bundle sha256 = $BSHA"
    gg -C $G bundle verify -q $BUNDLE > /dev/null 2>&1; ck $? "00 bundle verifies against $G (its prerequisite $GBASE is there)"
    heads=$(gg bundle list-heads $BUNDLE); print -r -- "list-heads: $heads"
    [[ $heads == "$GCOMMIT refs/heads/$GBRANCH" ]]; ck $? "00 bundle head = $GCOMMIT ($GBRANCH)"
    say "the release commit, read from a scratch clone $SCR/g00.git (objects shared from $G, which is not written)"
    rm -rf $SCR/g00.git && gg clone -q --bare --shared $G $SCR/g00.git && gg -C $SCR/g00.git fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" \
      || { ck 1 "00 read the bundle into $SCR/g00.git"; exit 1; }
    X=(gg -C $SCR/g00.git)
    print -r -- "$GCOMMIT: $($X log -1 --format='%s | author %an <%ae> | committer %cn <%ce> | parent %P' $GCOMMIT)"
    [[ $($X log -1 --format=%P $GCOMMIT) == $GBASE ]]; ck $? "00 $GCOMMIT is one commit on $GBASE"
    [[ $($X log -1 --format='%ae %ce' $GCOMMIT) == "$RELMAIL $RELMAIL" ]]; ck $? "00 release commit author and committer are $RELMAIL"
    changed=$($X diff --name-only $GBASE $GCOMMIT | sort | tr '\n' ' '); print -r -- "changed files: $changed"
    [[ $changed == $(print -l ${=GFILES} | sort | tr '\n' ' ') ]]; ck $? "00 the release commit changes exactly the 5 version/CHANGELOG files"
    print -r -- "version at $GCOMMIT: $($X show ${GCOMMIT}:src/graftling/__init__.py | grep -E '^__version__')"
    line=$($X show ${GCOMMIT}:README.md | grep -m1 '^uv tool install ')
    print -r -- "README install line: $line"; print -r -- "C5 runs:             uv tool install --managed-python \"$SRCURL\""
    [[ $line == "uv tool install --managed-python \"$SRCURL\"" ]]; ck $? "00 README's first install line at $GCOMMIT is C5's tagless command"
    say "production $RT (read only)"
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"
    direct_urls $GOLDVERSION
    [[ $pv == "$GTVERSION $GOLDVERSION" && $DGT == *"$NT/graphtraj-$GTVERSION-"*.whl* && $DGL == *"$W617/graftling-$GOLDVERSION-"*.whl* ]]
    ck $? "00 production is graphtraj $GTVERSION (616's wheels-${TARGET[1,8]}) + graftling $GOLDVERSION (617's wheels-$GOLDVERSION)"
    (cd $W617 && shasum -a 256 -c SHA256SUMS > /dev/null 2>&1) && [[ $(shasum -a 256 $W617/graftling-$GOLDVERSION-*.whl(N) | cut -d' ' -f1) == $GOLDSHA ]]
    ck $? "00 617's wheels-$GOLDVERSION (R's graftling) verifies, sha256 ${GOLDSHA[1,16]}..."
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "00 production pip check" "${pc[1,120]}"
    print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp,graphtraj-mcp,agent-runner}(N:t) | tr '\n' ' ')"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && ! -e $RT/bin/agents ]]; ck $? "00 production bin has subagents, subagents-mcp, graphtraj-mcp (and no agents)"
    say "backups"
    print -r -- "617's backup $BK617 (the current rollback, information; never written): $([[ -e $BK617/COMPLETE ]] && print COMPLETE || print 'not complete or absent')"
    print -r -- "older rollbacks the user keeps (information; never written; I reports them again):"; oldbk_report 00 | tee $SCR/oldbk-00.txt
    [[ ! -e $BK ]]; ck $? "00 backup $BK absent"
    say "this Worktree $WT (GraphTraj, unchanged: its product is production's ${TARGET[1,8]}; G tests it)"
    product_guard; ck $? "00 HEAD's product (${GUARDED[*]}) = ${TARGET[1,8]}, HEAD differs from GraphTraj dev ${DEV0[1,8]} only under scripts/adopt-625/, clean"
    cdef=$(cdef_of $STATE/tasks/$TASKDIR); [[ -n $cdef && -f $cdef ]]; ck $? "00 Task $TASK_ID ready (current_definition ${cdef:t} exists)"
    print -r -- "plugin and entry files (hashes; V and I require them unchanged):"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json $ENTRIES 2>&1 | sed 's/^/  /'
    say "Claude: version and one claude -p probe ($LOGIN_NOTE)"
    C=$(claude_bin); [[ -s $SCR/cc.version ]] || clean $C --version 2>&1 | head -1 > $SCR/cc.version; cv
    P=$(mktemp -d ${TMPDIR:-/tmp}/probe-625.XXXXXX)
    (cd $P && print -r -- "Reply with one line: READY-625 and your model id." | clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose > $SCR/00-probe.jsonl 2>&1)
    ans=$(clean $CONDA -I -c 'import json, sys
init, result = {}, ""
for line in open(sys.argv[1], errors="replace"):
    try: r = json.loads(line)
    except ValueError: continue
    if r.get("type") == "system" and r.get("subtype") == "init": init = r
    if r.get("type") == "result": result = str(r.get("result", ""))
print("model %s | apiKeySource %s | answer %r" % (init.get("model"), init.get("apiKeySource"), result[:120]))' $SCR/00-probe.jsonl 2>&1)
    print -r -- "claude -p probe: $ans (stream: $SCR/00-probe.jsonl)"
    [[ $ans == *"model $MODEL"* && $ans == *"apiKeySource none"* && $ans == *READY-625* ]]
    ck $? "00 claude -p answers READY-625 on $MODEL through the Claude login (apiKeySource none: no API key)"
    say "Main's Session (I, M, Mr need it)"
    id=$(detect_main); [[ -n $id ]] && print -r -- $id > $SCR/main.session
    print -r -- "MAIN=${id:-NOT FOUND} (saved to $SCR/main.session)"; [[ -n $id ]]; ck $? "00 Main's Session id found"
    members_idle 00 | head -14 || print "(information at 00: members may run now; Mpre and I wait for them)"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above). Nothing was changed. Hand $R/00.txt to the Team."; exit 1; }
  summary 00 "$(grep -E '^(uv|CHECK|TMPDIR|dev|GitHub|sha256|list-heads|README|C5 runs|production|617|older|  00 kept|claude|MAIN=|members_idle|graph|graft)' $R/00.txt)"
  print "Success: every 'CHECK 625 00 ...: PASS'."
  next "zsh $THIS rel" ;;

rel) print "[rel] Main. graftling repository $G: fetch $GBRANCH from the bundle, fast-forward dev ($GDEV) and main ($G) to $GCOMMIT, annotated tag $GTAG ($RELNAME <$RELMAIL>). No network, no login. Dialog: none."
  rel_verify() {
    local gt gd gm tm v
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    print -r -- "$GTAG -> ${gt:-absent} | dev $gd | main $gm | type $(gg -C $G cat-file -t refs/tags/$GTAG 2>&1) | tagger $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG)"
    [[ $gt == $GCOMMIT ]]; ck $? "rel $GTAG peels to $GCOMMIT"
    [[ $gm == $GCOMMIT && $gd == $GCOMMIT ]]; ck $? "rel graftling main == dev == $GTAG^{} == $GCOMMIT"
    [[ $(gg -C $G cat-file -t refs/tags/$GTAG 2>/dev/null) == tag && $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG) == "$RELNAME <$RELMAIL>" ]]
    ck $? "rel $GTAG is an annotated tag with the noreply tagger"
    tm=$(gg -C $G cat-file tag refs/tags/$GTAG 2>/dev/null | sed '1,/^$/d')
    [[ $tm == *619* && $tm == *compatible* ]]; ck $? "rel $GTAG message names 619 and compatible"
    v=$(gg -C $G show ${GTAG}:src/graftling/__init__.py 2>/dev/null | grep -E '^__version__')
    [[ $v == "__version__ = \"$GVERSION\"" ]]; ck $? "rel version at $GTAG is $GVERSION" "$v"
  }
  { gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}" 2>/dev/null)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "before: dev ${gd:-NOT FOUND} (in ${dw:-no worktree}) | main ${gm:-NOT FOUND} (in ${mw:-no worktree}) | $GTAG ${gt:-absent}"
    if [[ -n $gt ]]; then
      if [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]]; then print "already released: $GTAG = main = dev = $GCOMMIT (nothing to do)"; rel_verify; exit 0; fi
      print "STOP: $GTAG exists at $gt, but not with main = dev = $GCOMMIT. Nothing changed. Main tells the Leader."; exit 1
    fi
    [[ $gd == $GBASE || $gd == $GCOMMIT ]] || { print -r -- "STOP: graftling dev is $gd, no longer $GBASE (moved since dispatch: $(gg -C $G log --oneline $GBASE..$gd 2>/dev/null | head -5 | tr '\n' ';')). Requirement 2 needs dev AND main at the release commit, so rel does not merge. Nothing changed. Main tells the Leader."; exit 1; }
    [[ $gm == $GMAIN0 || $gm == $GCOMMIT ]] || { print -r -- "STOP: graftling main is $gm, no longer $GMAIN0 (v$GOLDVERSION). Nothing changed. Main tells the Leader."; exit 1; }
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]] || { print -r -- "STOP: dev must be checked out in $GDEV and main in $G (found ${dw:-none} and ${mw:-none}). Nothing changed."; exit 1; }
    for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || { print -r -- "STOP: the worktree $w is not clean (git status --porcelain). Nothing changed."; exit 1; }; done
    say "bundle (sha256 $(shasum -a 256 $BUNDLE | cut -c1-16)...): verify, fetch $GBRANCH, check it is $GCOMMIT on $GBASE"
    [[ $(shasum -a 256 $BUNDLE | cut -d' ' -f1) == $BSHA ]] || { print "STOP: the bundle's sha256 is not $BSHA. Nothing changed."; exit 1; }
    gg -C $G bundle verify -q $BUNDLE > /dev/null || { print "STOP: the bundle does not verify against $G. Nothing changed."; exit 1; }
    gg -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" || { print "STOP: fetching $GBRANCH from the bundle failed. Nothing else changed."; exit 1; }
    [[ $(gg -C $G rev-parse refs/heads/$GBRANCH) == $GCOMMIT && $(gg -C $G rev-parse $GCOMMIT~1) == $GBASE ]] \
      && print -r -- "$GBRANCH = $GCOMMIT (parent $GBASE) | author / committer: $(gg -C $G log -1 --format='%an <%ae> / %cn <%ce>' $GCOMMIT)" \
      || { print "STOP: $GBRANCH is not $GCOMMIT on $GBASE. dev, main and the tag are unchanged."; exit 1; }
    say "dev: fast-forward $gd -> $GCOMMIT in $dw"
    gg -C $dw merge --ff-only -q $GCOMMIT || { print "STOP: dev did not fast-forward; main and the tag are unchanged."; exit 1; }
    say "main: fast-forward $gm -> $GCOMMIT in $mw"
    gg -C $mw merge --ff-only -q $GCOMMIT || { print "STOP: main did not fast-forward; dev is at $GCOMMIT, the tag is not made. Rerun rel after fixing."; exit 1; }
    say "annotated tag $GTAG at $GCOMMIT, tagger $RELNAME <$RELMAIL>"
    clean GIT_COMMITTER_NAME=$RELNAME GIT_COMMITTER_EMAIL=$RELMAIL git -C $G tag -a $GTAG $GCOMMIT -m "$RELMSG" || exit 1
    rel_verify
  } 2>&1 | tee $R/rel.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rel.txt || { print "\nrel STOP (see above). Hand $R/rel.txt to the Team; do not run B or rp."; exit 1; }
  summary rel "$(grep -E '^(before|already|CHECK|STOP)' $R/rel.txt)"
  print "Success: every 'CHECK 625 rel ...: PASS' (or 'already released')."
  next "zsh $THIS B" ;;

B) print "[B] Main, before the push. Builds the graftling wheel with $CONDA (--no-index --no-deps --no-build-isolation) from git archive $GTAG -> $NG. graphtraj: 616's wheels-${TARGET[1,8]} is REUSED by sha256 (never rebuilt) and compared with git archive ${TARGET[1,8]}. No network, no login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}")
    [[ $gt == $GCOMMIT ]] || { print -r -- "STOP: $GTAG^{commit} is ${gt:-absent}, not $GCOMMIT: run rel first."; exit 1; }
    product_guard || { print "STOP: product guard (above)"; exit 1; }
    rm -rf $GSRC $TSRC $WHL $SCR/wheelview; mkdir -p $GSRC $TSRC $WHL $SCR/wheelview || exit 1
    sv=$(clean $CONDA -I -c 'import setuptools, pip; print("setuptools", setuptools.__version__, "| pip", pip.__version__)' 2>&1); ck $? "B setuptools importable offline in $CONDA" "$sv"
    say "graftling: git archive $GTAG ($GCOMMIT) -> $GSRC"
    gg -C $G archive $GTAG | tar -x -C $GSRC || exit 1
    vbad=0; for vf in src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $GSRC/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B archive version strings (__init__.py and the 3 json) all $GVERSION"
    hd=$(grep -m1 '^## ' $GSRC/CHANGELOG.md); print -r -- "CHANGELOG first heading: $hd"
    [[ $hd == "## $GVERSION (compatible)" ]] && ! grep -q '^## Unreleased' $GSRC/CHANGELOG.md; ck $? "B CHANGELOG heading '## $GVERSION (compatible)' and no '## Unreleased'"
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL $GSRC) || { print "STOP: the graftling wheel build failed"; exit 1; }
    whl=($WHL/graftling-$GVERSION-*.whl(N)); all=($WHL/*.whl(N)); print -r -- "graftling wheel: ${all[*]:t}"
    (( $#whl == 1 && $#all == 1 )) || { print "STOP: expected exactly one graftling-$GVERSION wheel"; exit 1; }
    whl=$whl[1]; (cd $SCR/wheelview && unzip -qo $whl) || exit 1
    mv_=$(sed -n 's/^Version: //p' $SCR/wheelview/graftling-$GVERSION.dist-info/METADATA 2>/dev/null); print -r -- "  METADATA Version: ${mv_:-MISSING}"
    vbad=0; [[ $mv_ == $GVERSION ]] || vbad=1
    for vf in graftling/__init__.py graftling/claude-plugin/.claude-plugin/plugin.json graftling/dsh/package.json graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $SCR/wheelview/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B graftling wheel reports $GVERSION (METADATA, __init__.py, the 3 json)"
    cs=$(sed -n '/^\[console_scripts\]/,/^\[/p' $SCR/wheelview/graftling-$GVERSION.dist-info/entry_points.txt | grep -oE '^[A-Za-z0-9_.-]+ *=' | tr -d ' =' | sort | tr '\n' ' ')
    print -r -- "  [console_scripts]: ${cs:-none}"; [[ $cs == "subagents subagents-mcp " ]]; ck $? "B graftling console scripts are exactly subagents, subagents-mcp"
    clean $CONDA -I $S593/pkgdiff532.py graftling $whl archive:$GSRC/src "625 B graftling wheel equals git archive $GTAG" -
    ck $? "B the graftling wheel's files equal git archive $GTAG"
    marker619 "B wheel" $SCR/wheelview/graftling
    leaked=$(unzip -Z1 $whl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "graftling wheel build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the graftling wheel"
    say "graphtraj: 616's wheel $NT (production's, reused; never rebuilt)"
    tw=($NT/graphtraj-$GTVERSION-*.whl(N)); print -r -- "wheel: ${tw[*]:t} | COMMIT: $(cat $NT/COMMIT 2>/dev/null)"
    (cd $NT && shasum -a 256 -c SHA256SUMS) && [[ $#tw == 1 && $(shasum -a 256 $tw[1] | cut -d' ' -f1) == $TSHA ]]
    ck $? "B 616's graphtraj wheel verifies (SHA256SUMS) and its sha256 is $TSHA"
    [[ $(cat $NT/COMMIT 2>/dev/null) == $TARGET ]]; ck $? "B 616's wheels-${TARGET[1,8]} COMMIT is $TARGET"
    gg -C $WT archive $TARGET | tar -x -C $TSRC && clean $CONDA -I $S593/pkgdiff532.py graphtraj $tw[1] archive:$TSRC/src "625 B 616's graphtraj wheel equals git archive ${TARGET[1,8]}" -
    ck $? "B 616's graphtraj wheel's graphtraj/ files equal git archive ${TARGET[1,8]} (G tests this Worktree's HEAD, whose product is ${TARGET[1,8]})"
    clean $CONDA -I -c 'import sys, zipfile
from packaging.requirements import Requirement
z = zipfile.ZipFile(sys.argv[1]); new = sys.argv[2]
meta = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")][0]
rq = [l.split(":", 1)[1].strip() for l in z.read(meta).decode().splitlines() if l.startswith("Requires-Dist:")]
g = [Requirement(r) for r in rq if Requirement(r).name == "graftling"]
inc = len(g) == 1 and g[0].specifier.contains(new) and not g[0].specifier.contains("0.11.0")
print("Requires-Dist:", rq)
print(f"CHECK 625 B graphtraj requires graftling {g[0] if g else None}: includes {new}, excludes 0.11.0: {"PASS" if inc else "FAIL"}")
' ${tw[1]:-$NT/missing.whl} $GVERSION 2>&1 || ck 1 "B graphtraj metadata read"
    say "the graftling wheel G, V and I install: $NG"
    rm -rf $NG && mkdir -p $NG && cp -p $whl $NG/ || exit 1
    (cd $NG && shasum -a 256 *.whl > SHA256SUMS) && print -r -- "$GTAG $GCOMMIT" > $NG/COMMIT || exit 1
    (cd $NG && shasum -a 256 -c SHA256SUMS); ck $? "B $NG holds the wheel with SHA256SUMS and COMMIT"
    print -r -- "wheel sha256: $(cat $NG/SHA256SUMS) | graphtraj (reused): $(cat $NT/SHA256SUMS)"
  } 2>&1 | tee $R/B.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/B.txt || { print "\nB STOP (see above). Do not push. Hand $R/B.txt to the Team."; exit 1; }
  summary B "$(grep -E '^(CHECK|wheel|Requires-Dist)' $R/B.txt)"
  print "Success: every 'CHECK 625 B ...: PASS'."
  next "zsh $THIS G    (Main starts it as a BACKGROUND command; it runs ~25-30 min and ends with its verdict, then: ADOPT625_PUSH_CONFIRMED=yes zsh $THIS rp. Meanwhile V may run: zsh $THIS V)" ;;

G) print "[G] Main STARTS THIS STEP IN THE BACKGROUND ITSELF (Runtime background command); the Runtime tells Main when it exits. Full GraphTraj suite: this Worktree's HEAD (editable; product = production's ${TARGET[1,8]}) + the $GTAG wheel from B, 6 parallel shards through scripts/run_test_shards.py with -rA (each test's own outcome is recorded); pytest temp under TMPDIR=${TMPDIR:-/tmp} (outside the Harness; checked below). Main's suite queue is serial: while another suite runs, G waits for it first. This process waits for the shards, then judges the record (GR) and exits; its LAST lines are the verdict (RESULT 625 G/GR), the counts, the test interpreter's graftling and the next command. Duration: ~25-30 min once the shards start, plus any wait behind another suite. No login, no network. Dialog: none."
  { check_tmp || exit 1
    product_guard || { print "STOP: product guard (above)"; exit 1; }
    whl=($NG/graftling-$GVERSION-*.whl(N)); (( $#whl == 1 )) && (cd $NG && shasum -a 256 -c SHA256SUMS > /dev/null) || { print "STOP: no checked $GTAG wheel in $NG: run B first"; exit 1; }
    pscheck=$(other_suites) || { print -r -- "STOP: $pscheck (nothing was built or started)"; exit 1; }
    GV=${SCR:A}/gvenv-625 O=$AD/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-625-G-$(date +%Y%m%dT%H%M%S)
    rm -rf $GV; clean $CONDA -m venv --system-site-packages $GV || exit 1
    sp=$(site); D=($GV/lib/python*/site-packages(N))   # production's click, PyYAML, websockets shadow the base Python's (564)
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    clean $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $whl || exit 1
    clean $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
    mkdir -p $O $RUNTMP
    { print -r -- "pytest temp root: $RUNTMP (TMPDIR=${TMPDIR:-/tmp}, outside the Harness)"
      print -r -- "launch environment: HOME USER PATH TERM TMPDIR LANG only (clean(); no provider credential variable reaches the suite)"
      print -r -- "candidate: $(gg -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT ($GTAG, ${whl:t})"; print -r -- "python: $GV/bin/python"
      (cd ${TMPDIR:-/tmp} && clean $GV/bin/python -I -c 'import importlib.metadata as m; print("test interpreter dependencies:", " | ".join(f"{n} {m.version(n)}" for n in ("click", "PyYAML", "websockets", "pytest", "graftling", "graphtraj")))')
      (cd ${TMPDIR:-/tmp} && clean $GV/bin/python -I -c 'import os, graftling; print("test interpreter graftling:", graftling.__version__, os.path.dirname(graftling.__file__))'); } > $O/run.txt
    extra=(${(Q)${(z)${ADOPT625_PYTEST_ARGS:-}}})
    (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" >> $O/run.txt
    : > $O/suite.txt
    cat $O/run.txt; print -r -- "record: $O"
    # The serial queue: wait (in this process) while another suite runs.
    while true; do
      busy=$(other_suites) || { print -r -- "$(date +%T) STOP: ps failed; G did not start" | tee -a $O/wait.txt; print "exit=ps-failed (G did not start)" >> $O/suite.txt; exit 1; }
      [[ -z $busy ]] && break
      print -r -- "$(date +%T) waiting for another suite: $(print -r -- $busy | awk '{print $1}' | tr '\n' ' ')" | tee -a $O/wait.txt; sleep ${ADOPT625_GWAIT:-60}
    done
    # The 6 shards run in parallel inside run_test_shards.py; this process waits for it to end.
    print -r -- "$(date +%T) started (6 shards; this step waits for them)" | tee -a $O/wait.txt
    (cd $WT && clean env TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra > $O/suite.txt 2>&1 < /dev/null)
    print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended (all shards ended: $(tail -1 $O/suite.txt))" | tee -a $O/wait.txt
    clean $CONDA -I $S593/fails593.py $O/failures.txt $O/suite.txt $O/shards/*(N.) > /dev/null
  } 2>&1 | tee $R/G.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nG STOP (see above). Hand $R/G.txt to the Team."; exit 1; }
  print "\n### G: the suite has ended; GR judges its record (the same checks as the GR step)"
  zsh $THIS GR; exit $? ;;

GR) print "[GR] G runs this at its end; Main may rerun it alone to re-judge an ended G record. Read only: G's record, totals, every FAILED/ERROR id and ABNORMAL shard, classed against 516's CURRENT definition ONLY (a shard 'timed out after' is NEW), and the graftling the test interpreter imported (it must be $GVERSION with 619's fix). No login. Dialog: none."
  rm -f $R/GR.ok
  { rec=$(grec); print -r -- "G record: $rec"
    product_guard
    [[ -f $rec/run.txt && -f $rec/suite.txt ]] || { print "STOP: no G record: run G first"; exit 1; }
    grep -q '^exit=' $rec/suite.txt || { print -r -- "G has not finished ($rec/suite.txt has no exit= line; queue: $(tail -1 $rec/wait.txt 2>/dev/null)). Rerun GR later."; exit 1; }
    sed 's/^/  run.txt: /' $rec/run.txt
    cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $rec/run.txt | head -1) gl=$(grep -oE 'git archive [0-9a-f]{40}' $rec/run.txt | head -1 | awk '{print $3}')
    cdiff=$(gg -C $WT diff --name-only ${cand:-missing} $TARGET -- $GUARDED 2>&1)
    [[ -n $cand && -z $cdiff ]]; ck $? "GR the record's candidate ${cand[1,8]} has the product of ${TARGET[1,8]} (production's GraphTraj)" "${cdiff//$'\n'/ }"
    [[ $gl == $GCOMMIT ]] && grep -q "($GTAG, graftling-$GVERSION-" $rec/run.txt; ck $? "GR the record's graftling wheel is $GTAG ($GCOMMIT)" "${gl:-none}"
    tig=$(tig_of $rec) tigdir=$(sed -n 's/^test interpreter graftling: [^ ]* //p' $rec/run.txt | head -1)
    print -r -- "test interpreter graftling: ${tig:-NOT RECORDED} | dependencies line: $(grep -oE '\| graftling [^ ]+ \|' $rec/run.txt | head -1)"
    [[ $tig == $GVERSION ]] && grep -q "| graftling $GVERSION |" $rec/run.txt; ck $? "GR test interpreter imports graftling $GVERSION (graftling.__version__ and metadata)" "${tig:-none}"
    marker619 "GR test interpreter's graftling" ${tigdir:-$rec/no-graftling-dir}
    tmp=$(sed -n 's/^pytest temp root: \([^ ]*\).*/\1/p' $rec/run.txt | head -1)
    [[ -n $tmp && ${tmp:A}/ != ${H:A}/* ]] && grep -q 'outside the Harness' $rec/run.txt; ck $? "GR pytest temp root is outside the Harness" "${tmp:-none}"
    grep -q '^launch environment: HOME USER PATH TERM TMPDIR LANG only' $rec/run.txt; ck $? "GR clean launch environment recorded (HOME USER PATH TERM TMPDIR LANG only)"
    tot=$(grep -E '^=*.* (passed|failed)|^[0-9]+ (failed|errors|passed)' $rec/suite.txt | tail -1); ex=$(sed -n 's/^exit=//p' $rec/suite.txt | tail -1)
    print -r -- "totals: ${tot:-NOT FOUND} | exit: ${ex:-NOT FOUND}"
    sr_classify $rec
    rf=0; grep -q '^REHEARSAL' $rec/run.txt && rf=1   # a rehearsal -k filter leaves shards with nothing collected (exit 5)
    (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && ( $SR_ANY == 1 || $rf == 1 ) ) ]]; ck $? "GR G record ($GTAG wheel) has no new failure and no ABNORMAL shard" "$( (( $#SR_IDS )) && print "$#SR_IDS NEW ids: run SR")"
  } 2>&1 | tee $R/GR.txt; rc=${pipestatus[1]}
  verdict=PASS; (( rc == 0 )) && ! grep -q ': FAIL' $R/GR.txt || verdict=FAIL
  summary GR "$(grep -E '^(G record|totals|CHECK|  NEW|  known|  ABNORMAL|test interpreter|STOP)' $R/GR.txt)"
  kn=$(grep -c '^  known ' $R/GR.txt) nw=$(grep -c '^  NEW: ' $R/GR.txt) ab=$(grep -c '^  ABNORMAL shard' $R/GR.txt)
  tig=$(sed -n 's/^test interpreter graftling: \([^ ]*\) |.*/\1/p' $R/GR.txt | tail -1)
  print -r -- "RESULT 625 G/GR: $verdict | ${$(sed -n 's/^totals: //p' $R/GR.txt | tail -1):-no totals (the record has not ended or is missing)} | known non-blocking ids: $kn | NEW ids: $nw | ABNORMAL shards: $ab | test interpreter graftling: ${tig:-not judged}" | tee -a $R/GR.txt
  [[ $verdict == PASS ]] && touch $R/GR.ok
  if [[ $verdict == PASS ]]; then next "ADOPT625_PUSH_CONFIRMED=yes zsh $THIS rp"
  else next "zsh $THIS SR    (NEW ids or an ABNORMAL shard: SR prints the suite-base command; a STOP line above: hand $R/GR.txt to the Team; do not push)"; exit 1; fi ;;

SR) print "[SR] Main, read only. The newest G record's FAILED/ERROR ids and ABNORMAL shards, classed against 516 only; prints the suite-base command for NEW ids. Dialog: none."
  rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no finished G record ($rec)"; exit 1; }
  { tail -6 $rec/suite.txt; sr_classify $rec; print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"; } 2>&1 | tee $R/SR.txt
  SR_IDS=(${(f)"$(<$rec/new-ids.txt)"}); SR_IDS=(${SR_IDS:#}); SR_NEW=0; grep -q '^SR verdict: PASS' $R/SR.txt || SR_NEW=1   # the block above ran in a subshell
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)SR_IDS}"; print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else next "none for suite-base (no NEW id). A NEW ABNORMAL shard: hand $rec/suite.txt and its shard log to the Team. Do not push."; fi
  exit $SR_NEW ;;

suite-base) print "[suite-base] Main, only for SR's NEW ids. Reruns them on base (this Worktree, product ${TARGET[1,8]}, + graftling $GOLDVERSION from 617's wheel: production now) and on the candidate (G's venv: the same product + $GTAG); clean environment, pytest temp under TMPDIR. Dialog: none."
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print "STOP: no id file"; exit 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; exit 2; }
  check_tmp || exit 1
  o=$(other_suites) || { print -r -- "STOP: $o"; exit 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; exit 1; }
  VB=${SCR:A}/sbvenv-$GOLDVERSION VC=${SCR:A}/gvenv-625 sp=$(site)
  [[ -x $VC/bin/python ]] || { print "STOP: no G venv $VC; run G first"; exit 1; }
  if [[ ! -f $VB/installed ]]; then
    rm -rf -- $VB && clean $CONDA -m venv --system-site-packages $VB || exit 1; D=($VB/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pipq=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
    clean $VB/bin/python -m pip install $pipq $W617/graftling-$GOLDVERSION-*.whl && clean $VB/bin/python -m pip install $pipq -e $WT > /dev/null || exit 1
    print -r -- "graftling $GOLDVERSION (617's wheel) + graphtraj (this Worktree, editable; product ${TARGET[1,8]})" > $VB/installed
  fi
  O=$AD/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $O; print -l -- $ids > $O/ids.txt
  for side V in base $VB candidate $VC; do
    RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-625-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $WT with $V ($([[ $side == base ]] && cat $VB/installed || print "graftling $GTAG wheel")) | temp $RUNTMP | launch environment: HOME USER PATH TERM TMPDIR LANG only"
    (cd $WT && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $O/$side-collected.txt 2>&1)
    clean $CONDA -I $SUITEIDS present $O/$side-collected.txt $O/ids.txt > $O/$side-ids.txt 2> $O/$side-missing.txt
    run=(${(f)"$(<$O/$side-ids.txt)"})
    if (( $#run )); then (cd $WT && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $O/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $O/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $O/$side.txt | tail -1) ($O/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $O/ids.txt $O/base.txt $O/candidate.txt | tee $O/classification.txt; fails=${pipestatus[1]}
  print ""; print -r -- "RESULT 625 suite-base: $( (( fails == 0 )) && print 'PASS (no candidate-only failure)' || print 'FAIL (classification above)') | ids: $#ids | record: $O"
  print -r -- "next: hand $O/classification.txt to the Team; a candidate-only id is a regression of this release (no push, no adoption)."; exit $fails ;;

rp) print "[rp] Main. Outward-facing: push graftling dev, main and refs/tags/$GTAG to origin ($GURL), fast-forward only, atomic, no force. Only after rel and after G/GR PASSED (the definition requires the paired GraphTraj suite before the push). The user's release decision is the push decision (Worldline user-decision $DECISION). Network: github.com with the user's usual git credentials (osxkeychain); no other login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]] || { print -r -- "STOP: rel is not complete (dev $gd, main $gm, $GTAG ${gt:-absent}; need all $GCOMMIT). Nothing pushed."; exit 1; }
    gr_passed || { print -r -- "STOP: G/GR has not passed ($R/GR.ok absent or $R/GR.txt has no 'RESULT 625 G/GR: PASS'): the paired GraphTraj suite with the $GTAG wheel must pass before the push. Nothing pushed."; exit 1; }
    print -r -- "G/GR: $(grep '^RESULT 625 G/GR: ' $R/GR.txt | tail -1)"
    ou=$(gg -C $G remote get-url origin 2>&1); print -r -- "origin: $ou"
    [[ $ou == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL"; exit 1; }
    before=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main refs/tags/$GTAG 2>&1) || { print -r -- "STOP: ls-remote failed: ${before[1,200]}"; exit 1; }
    print -r -- "remote before: ${before//$'\n'/ | }"
    print -r -- "will push: dev $gd, main $gm, refs/tags/$GTAG ($(gg -C $G rev-parse refs/tags/$GTAG)) (fast-forward only, --atomic, no force)"
    [[ ${ADOPT625_PUSH_CONFIRMED:-} == yes ]] || { print -r -- "STOP: the push is outward-facing. It is the user's decision $DECISION; run: ADOPT625_PUSH_CONFIRMED=yes zsh $THIS rp"; exit 1; }
    gg -C $G push --atomic origin refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/$GTAG || { print "STOP: the push was refused (atomic: nothing changed on the remote)"; exit 1; }
    now=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" 2>&1)
    print -r -- "remote now: ${now//$'\n'/ | }"
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT && $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "rp remote main == $GTAG^{} == $GCOMMIT"
    [[ $(remote_of $now refs/heads/dev) == $gd ]]; ck $? "rp remote dev == local dev ($gd)"
  } 2>&1 | tee $R/rp.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rp.txt || { print "\nrp STOP (see above). Hand $R/rp.txt to the Team."; exit 1; }
  summary rp "$(grep -E '^(G/GR|remote|CHECK)' $R/rp.txt)"
  print "Success: both 'CHECK 625 rp ...: PASS'."
  next "zsh $THIS gh" ;;

gh) print "[gh] Main. Read only: git ls-remote $GURL. Network: github.com. No login. Dialog: none."
  { now=$(gg ls-remote $GURL refs/heads/main refs/tags/$GTAG "refs/tags/$GTAG^{}" 2>&1) || { print -r -- "STOP: git ls-remote $GURL failed: ${now[1,200]}"; exit 1; }
    print -r -- "GitHub: ${now//$'\n'/ | }"
    rto=$(remote_of $now refs/tags/$GTAG) lto=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG)
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT ]]; ck $? "gh GitHub main = $GCOMMIT"
    [[ $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "gh GitHub $GTAG^{} = $GCOMMIT"
    [[ -n $rto && $rto != $GCOMMIT && $rto == $lto ]]; ck $? "gh GitHub $GTAG is the local annotated tag object" "remote ${rto:-absent}, local ${lto:-absent}"
  } 2>&1 | tee $R/gh.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/gh.txt || { print "\ngh STOP (see above). Hand $R/gh.txt to the Team."; exit 1; }
  summary gh "$(grep -E '^(GitHub|CHECK)' $R/gh.txt)"
  print "Success: three 'CHECK 625 gh ...: PASS'."
  next "zsh $THIS C5" ;;

C5) print "[C5] Main, as a FOREGROUND command (612's background run lost uv's network). The README's TAGLESS install command (605) from GitHub, in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local, uv tool directory, dotfiles and conda are not touched. Network: github.com, PyPI, uv's Python download. No login. Dialog: none. ~2-3 min."
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier C5). Move it aside: mv $UVT $UVT.old-\$(date +%s)"; exit 1; }
    mkdir -p $UVT || exit 1
    say "before: USER directories and conda (read only, where readable)"
    snap $R/C5-home-before.json || exit 1
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1) | environment: ${UVENV[*]}"
    print -r -- "command: ${INSTALL[*]}   (uv = $U; no tag: the default branch main)"
    (cd $UVT && clean $UVENV $U ${INSTALL[2,-1]}) > $R/C5-uv.txt 2>&1; urc=$?
    tail -5 $R/C5-uv.txt
    print "uv tool install rc=$urc (full output: $R/C5-uv.txt)"; ck $urc "C5 uv tool install rc 0"
    (( urc == 0 )) || exit 1
    td=$(cd $UVT && clean $UVENV $U tool dir 2>&1); py=$td/graftling/bin/python
    print -r -- "uv tool dir: $td"; [[ $td == $UVT/tools ]]; ck $? "C5 uv tool dir is $UVT/tools"
    out=$(cd $UVT && clean $py -I -c 'import sys, json, importlib.metadata as m, graftling
d = m.distribution("graftling")
print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix)
print(graftling.__version__); print(m.version("graftling"))
v = json.loads(d.read_text("direct_url.json") or "{}").get("vcs_info", {})
print(v.get("commit_id", "none")); print(v.get("requested_revision", "-"))' 2>&1) || { ck 1 "C5 the tool Python runs" "${out[1,200]}"; exit 1; }
    prefix=${${(f)out}[1]} base=${${(f)out}[2]} gv=${${(f)out}[3]} mdv=${${(f)out}[4]} cid=${${(f)out}[5]} rrev=${${(f)out}[6]}
    print -r -- "tool python: $py -> ${py:A} | sys.prefix: $prefix | base: $base -> ${base:A} | graftling.__version__ $gv | metadata $mdv | direct_url commit_id $cid | requested_revision $rrev"
    [[ $gv == $GVERSION && $mdv == $GVERSION ]]; ck $? "C5 graftling.__version__ and importlib.metadata version are $GVERSION"
    [[ ${prefix:A} == ${UVT:A}/tools/graftling ]]; ck $? "C5 sys.prefix is $UVT/tools/graftling"
    class=other
    case ${base:A}/ in ${CROOT:A}/*) class=conda ;; /usr/*|/System/*|/Library/*|/opt/homebrew/*) class=system ;; esac
    [[ ${base:A}/ == ${UVT:A}/python/* && ${py:A}/ == ${UVT:A}/python/* ]] && class=uv-managed
    print -r -- "REPORT 625 C5 base interpreter: $base ($class) | uv-managed Pythons: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    [[ $class == uv-managed ]]; ck $? "C5 tool environment base interpreter is uv-managed (under $UVT/python)" "$class"
    [[ $cid == $GCOMMIT ]]; ck $? "C5 installed commit (direct_url commit_id) is the release commit $GCOMMIT (GitHub main)" "$cid"
    bd=$(cd $UVT && clean $UVENV $U tool dir --bin 2>&1); print -r -- "uv tool dir --bin: $bd"
    hl=$(cd $UVT && clean "$bd/subagents" --help 2>&1); hrc=$?
    print -r -- "subagents --help (rc $hrc): ${${(f)hl}[1]:-}"; ck $hrc "C5 $UVT/bin/subagents --help rc 0"
    [[ -x $UVT/bin/subagents-mcp ]]; ck $? "C5 $UVT/bin/subagents-mcp exists" "$(head -1 $UVT/bin/subagents-mcp 2>/dev/null)"
    gpd=$(cd $UVT && clean $py -I -c 'import os, graftling; print(os.path.dirname(graftling.__file__))' 2>&1)
    marker619 "C5 installed" $gpd
    say "after: USER directories and conda"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT625_NOSNAP, rehearsal only)"
    else
      snap $R/C5-home-after.json > /dev/null
      clean $CONDA -I $S593/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json; ck $? "C5 USER directories (~/.local, uv tools, ~/.pi, ~/.dsh, ~/.codex) and conda unchanged"
    fi
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/C5.txt || { print "\nC5 STOP (see above). Hand $R/C5.txt to the Team."; exit 1; }
  summary C5 "$(grep -E '^(uv|command|uv tool install|tool python|subagents --help|CHECK|REPORT)' $R/C5.txt)"
  print "Success: every 'CHECK 625 C5 ...: PASS' (rc 0; version $GVERSION; commit $GCOMMIT; subagents --help rc 0; subagents-mcp; USER directories and conda unchanged)."
  next "zsh $THIS V    (if V already passed: zsh $THIS Mpre)" ;;

V) print "[V] Main. Before the install, outside production: a scratch venv ($VV) with 616's graphtraj wheel + the $GTAG wheel + production's click, yaml and websockets; the real MCP entries in an isolated project ($VPROJ); the hook copy regenerated by the product into a scratch copy must be byte-identical to production's. No login. Dialog: none. ~1 min."
  { rm -f $R/V.ok
    [[ -f $NG/SHA256SUMS && $(<$NG/COMMIT) == "$GTAG $GCOMMIT" && $(<$NT/COMMIT) == $TARGET ]] && (cd $NG && shasum -a 256 -c SHA256SUMS) && (cd $NT && shasum -a 256 -c SHA256SUMS) \
      || { print "STOP: no checked wheels in $NG and $NT: run B first"; exit 1; }
    product_guard; ck $? "V product guard"
    print -r -- "graftling changes since $GOLDVERSION in the files the hook copy is written from (information; expected none): $(gg -C $G diff --name-only $GMAIN0 $GCOMMIT -- src/graftling/claude/plugin.py src/graftling/claude/host_context.mjs 2>/dev/null | tr '\n' ' ')"
    gt=($NT/graphtraj-$GTVERSION-*.whl(N)) gw=($NG/graftling-$GVERSION-*.whl(N))
    rm -rf $VV; clean $CONDA -m venv $VV || exit 1
    clean $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gt[1] $gw[1] || exit 1
    sp=$(site) D=($VV/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pc=$(clean $VV/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "V scratch venv pip check" "${pc[1,120]}"
    clean $VV/bin/python -I $S593/onegraft.py $VV $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "V one graftling $GVERSION from the wheel in the scratch venv (onegraft.py)"
    marker619 "V scratch venv" $VV/lib/python3.13/site-packages/graftling
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
    codex_hook_check $VV
    mkdir -p $AD && shasum -a 256 $ENTRIES | tee $AD/entries.sha256
  } 2>&1 | tee $R/V.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/V.txt || { print "\nV STOP (see above). Nothing in production changed. Hand $R/V.txt to the Team."; exit 1; }
  touch $R/V.ok
  summary V "$(grep -E '^(CHECK|diff -r|product guard)' $R/V.txt)"
  print "Success: every 'CHECK 625 V ...: PASS' (incl. 619's marker, the hook copy byte-identical, tools/list subagents and tasks, discover 'start an agent' = [create])."
  next "zsh $THIS Mpre    (after G/GR, rp, gh and C5 have passed)" ;;

I0) need_main; print "[I0] Main, before Mpre and a rerun of I. Read only, apart from two MOVES (nothing is deleted): when the backup $BK belongs to an I whose install began and R rolled it back, and production equals that backup, it moves $BK to $SCR/backup-run<N>-<time> and that run's I/R records into $R/run<N>/. Otherwise STOP, changing nothing. The older rollbacks (tmp/600, 604, 612, 616, 617 backups) are not touched. No login. Dialog: none."
  { if [[ ! -e $BK ]]; then print -r -- "no backup $BK: nothing to set aside; I may run (it still STOPs when a backup exists)"; exit 0; fi
    nrun=1; while [[ -e $R/run$nrun || -n $(print -l $SCR/backup-run$nrun-*(N)) ]]; do nrun=$(( nrun + 1 )); done
    print -r -- "the failed run being set aside: run$nrun | backup $BK (I start $(sed -n 's/^I start //p' $R/I.txt 2>/dev/null | tail -1))"
    [[ -e $BK/COMPLETE && -e $BK/INSTALL-STARTED ]]; ck $? "I0 $BK has COMPLETE and INSTALL-STARTED (an I whose install began)"
    nr=$(grep -c '^CHECK 625 R ' $R/R.txt 2>/dev/null) nf=$(grep -c '^CHECK 625 R .*: FAIL' $R/R.txt 2>/dev/null)
    [[ -s $R/R.txt && ${nr:-0} -ge 5 && ${nf:-0} == 0 ]]; ck $? "I0 R's record $R/R.txt exists and every CHECK in it passed" "${nr:-0} CHECK lines, ${nf:-0} FAIL"
    say "production equals that backup, in R's terms"
    tree compare $BK/venv.manifest $RT > $SCR/I0-venv-compare.txt 2>&1; vrc=$?; tail -2 $SCR/I0-venv-compare.txt
    ck $vrc "I0 production venv equals the backup (adopt_tree.py compare, as R)"
    tree compare $BK/plugin.manifest $PDIR > /dev/null 2>&1; ck $? "I0 hook copy equals the backup"
    shasum -a 256 -c $BK/entries.sha256 > /dev/null 2>&1; ck $? "I0 .mcp.json, settings.local.json and config.json equal the backup"
    direct_urls $GOLDVERSION; [[ $DGT == *"$NT/graphtraj-$GTVERSION-"* && $DGL == *"$W617/graftling-$GOLDVERSION-"* ]]; ck $? "I0 graphtraj from 616's wheels-${TARGET[1,8]} and graftling $GOLDVERSION from 617's wheel"
    pc=$(clean $RT/bin/python -B -m pip check --disable-pip-version-check 2>&1); ck $? "I0 production pip check" "${pc[1,120]}"
  } 2>&1 | tee $R/I0.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || exit $rc
  [[ -e $BK ]] || { next "zsh $THIS Mpre"; exit 0; }
  grep -q '^CHECK 625 I0 .*: FAIL' $R/I0.txt && { print "\nI0 STOP (see above). Nothing was moved. Hand $R/I0.txt to the Team."; exit 1; }
  { nrun=1; while [[ -e $R/run$nrun || -n $(print -l $SCR/backup-run$nrun-*(N)) ]]; do nrun=$(( nrun + 1 )); done
    NB=$SCR/backup-run$nrun-$(date +%Y%m%dT%H%M%S)
    mv $BK $NB || { print "STOP: moving $BK failed"; exit 1; }
    print -r -- "MOVED $BK -> $NB (after-install snapshots inside: $(print -l $NB/after-install-*(N/:t) | tr '\n' ' '))"
    mkdir -p $R/run$nrun || exit 1
    files=($R/I.txt(N) $R/I.ok(N) $R/I-*(N) $R/R.txt(N) $R/R-*(N))
    (( $#files )) && mv $files $R/run$nrun/ || exit 1
    moved=(${files:t}); print -r -- "MOVED to $R/run$nrun/: $moved"
    print -r -- "I failed after the install began; R restored production; I0 set its backup ($NB) and records aside" > $R/run$nrun/SUPERSEDED
    [[ ! -e $BK && -e $NB/COMPLETE && ! -e $R/I.txt && ! -e $R/R.txt ]]; ck $? "I0 backup and run$nrun records set aside; $BK and the current I/R records are absent"
    oldbk_report I0
  } 2>&1 | tee -a $R/I0.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q '^CHECK 625 I0 .*: FAIL' $R/I0.txt || { print "\nI0 STOP (see above). Hand $R/I0.txt to the Team."; exit 1; }
  print "Success: every 'CHECK 625 I0 ...: PASS'. I may run again (Mpre right before it)."
  next "zsh $THIS Mpre" ;;

Mpre) need_main; print "[Mpre] Main, right before the USER exits Main (G/GR, V, rp, gh and C5 passed). Adoption only with no member running: 625's Leader and Engineer have ended their turns and no other member runs; else STOP (never signals). No login. Dialog: none."
  { gr_passed; ck $? "Mpre G/GR passed ($(grep '^RESULT 625 G/GR: ' $R/GR.txt 2>/dev/null | tail -1))"
    [[ -e $R/V.ok ]]; ck $? "Mpre V passed"
    for s in rp gh C5; do [[ -s $R/$s.txt ]] && grep -q "^CHECK 625 $s " $R/$s.txt && ! grep -q "^CHECK 625 $s .*: FAIL" $R/$s.txt; ck $? "Mpre $s passed"; done
    members_idle Mpre; ck $? "Mpre no member Worker or swarm batch runs"
  } 2>&1 | tee $R/Mpre.txt
  grep -q ': FAIL' $R/Mpre.txt && { print "\nMpre STOP (see above). A step not passed: run it first. A member running: wait for it to end (never kill it), then rerun Mpre."; exit 1; }
  print "\nWhy Main exits: Main's subagents/tasks calls run in its host process, which keeps the graftling modules it loaded; I replaces graftling. So Main exits before I and resumes after it."
  print "Main tells the USER, then the USER /exits Main and runs I in a Terminal:"
  next "(USER, normal Terminal, after /exit in Main) zsh $THIS I" ;;

I) need_main
  print "[I] USER (Main tells the USER first; the USER /exits Main, then runs this in a normal Terminal). Waits for members, backs up to $BK, installs ONLY the graftling $GVERSION wheel into $RT (graftling $GOLDVERSION -> $GVERSION; graphtraj ${TARGET[1,8]} untouched) with pip --force-reinstall --no-deps --no-index, checks the real entries. No login. Dialog: none (one Enter to confirm). ~3 min plus waiting."
  [[ -e $BK ]] && { print "STOP: $BK exists; I never overwrites a backup. Tell Main. (After a failed I that R rolled back, Main runs: zsh $THIS I0)"; exit 1; }
  [[ -e $R/V.ok ]] && gr_passed || { print "STOP: V or G/GR has not passed. Nothing changed."; exit 1; }
  product_guard || { print "STOP: product guard. Nothing changed."; exit 1; }
  print "Confirm that you typed /exit in the Claude Code Main. Enter to continue, Ctrl-C to stop."; read -r answer
  { members_idle I || { print "STOP: a member or host still runs (above). Nothing changed; wait, then rerun I (never kill them)."; exit 1; }
    date '+I start %F %T'
    oldbk_report I > $SCR/oldbk-I-before.txt; print "older rollbacks before the install (never written):"; cat $SCR/oldbk-I-before.txt
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
    gw=($NG/graftling-$GVERSION-*.whl(N)); (cd $NG && shasum -a 256 -c SHA256SUMS) || exit 1
    say "pip install --force-reinstall --no-deps --no-index ${gw:t} (graftling only; graphtraj not reinstalled)"
    clean $RT/bin/python -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall --no-deps --no-index $gw[1]; ck $? "I pip install of the $GTAG graftling wheel"
    date +%s > $R/I-install-end.epoch
    sp=$(site); bs=($BK/venv/lib/python*/site-packages(N/))
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $sp ${bs[1]:-$BK/venv/missing} "625 I graphtraj unchanged (installed vs backup, package and dist-info)" - | tail -1; ck ${pipestatus[1]} "I graphtraj package and dist-info unchanged vs the backup"
    direct_urls $GVERSION
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"*.whl* ]]; ck $? "I graphtraj direct_url is still 616's wheels-${TARGET[1,8]}"
    [[ $DGL == *"$NG/graftling-$GVERSION-"*.whl* ]]; ck $? "I graftling direct_url is wheels-$GVERSION"
    (( $(print -l $sp/graftling-$GOLDVERSION.dist-info(N) | grep -c .) == 0 )); ck $? "I graftling $GOLDVERSION dist-info gone"
    clean $CONDA -I $S593/pkgdiff532.py graftling $gw[1] $sp "625 I installed graftling equals the $GTAG wheel" - | tail -1; ck ${pipestatus[1]} "I installed graftling files equal the wheel"
    [[ -d $TSRC/manuals ]] || { mkdir -p $TSRC && gg -C $WT archive $TARGET | tar -x -C $TSRC; }   # B's archive of TARGET
    manuals_check I $RT/share/graphtraj/manuals
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "I production pip check" "${pc[1,120]}"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && $(head -1 $RT/bin/subagents) == "#!$RT/bin/python"* && $(head -1 $RT/bin/graphtraj-mcp) == "#!$RT/bin/python"* ]]
    ck $? "I production bin subagents, subagents-mcp, graphtraj-mcp (this venv's python)"
    clean $RT/bin/python -I $S593/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "I one graftling $GVERSION in production (onegraft.py)"
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"; [[ $pv == "$GTVERSION $GVERSION" ]]; ck $? "I production reports graphtraj $GTVERSION and graftling $GVERSION"
    marker619 "I production" $sp/graftling
    say "real entries of production (run in the isolated $VPROJ) and the files that must not change"
    mcp_probe I-production $RT
    codex_hook_check $RT
    diff -r $BK/plugin $PDIR > /dev/null; ck $? "I hook copy byte-identical to the backup (no configuration --write: V proved no change)"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__}; ck $? "I ${f#$H/} byte-identical to the backup"; done
    guard > /dev/null; ck $? "I no process started on $RT during the install"
    oldbk_report I > $SCR/oldbk-I-after.txt; print "older rollbacks after the install:"; cat $SCR/oldbk-I-after.txt
    cmp -s $SCR/oldbk-I-before.txt $SCR/oldbk-I-after.txt; ck $? "I older rollbacks (tmp/600, 604, 612, 616, 617 backups) untouched: same presence, COMPLETE, mtime and entry count before and after"
  } 2>&1 | tee -a $R/I.txt; rc=${pipestatus[1]}
  if (( rc != 0 )) || grep -q '^CHECK 625 I .*: FAIL' $R/I.txt; then
    [[ -e $BK/INSTALL-STARTED ]] && print "\nI FAILED after the install began. Do not resume Main. Run the rollback now:\n  zsh $BK/tools/steps.zsh R" || print "\nI STOP before the install (production unchanged). Tell Main."
    exit 1
  fi
  touch $R/I.ok
  summary I "$(grep -E '^(I start|backup COMPLETE|graphtraj direct_url|graftling .*direct_url|CHECK|INFO)' $R/I.txt)"
  print "Success: every 'CHECK 625 I ...: PASS'. Rollback, if ever needed (Main asks the USER first): zsh $BK/tools/steps.zsh R"
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
    clean $CONDA -I $S616/p616.py calls Mr $split - $files
  } 2>&1 | tee $R/Mr.txt
  grep -q ': FAIL' $R/Mr.txt && { print "\nMr FAIL (see above): did Main do M[b] with inline arguments? Hand $R/Mr.txt to the Team."; exit 1; }
  print "Success: 'CHECK 625 Mr ...: PASS'."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. One real dispatch: an advisor member on Task $TASK_ID creates the Claude child $CHILD (model $MODEL) through mcp__graphtraj__subagents WITHOUT tools; the child runs Bash and replies $DONEWORD; the member waits, reads and retires it. Login: $LOGIN_NOTE; Main does not ask again. Dialog: none expected (a tool permission dialog: 'Yes' once and tell the Team). 625's Leader and Engineer have ended their turns. ~3-5 min. Paste in the Claude Main (arguments INLINE, never arguments_file):
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
    else print "CHECK 625 Nr Main got exactly one completed notice of the member: PENDING (save it to $R/N-main-notice.txt)"; fi
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
  next "zsh $THIS done    (after retiring the member)" ;;

R) need_main; print "[R] USER (Main asks the USER first; after agreeing the USER /exits Main and runs this in a normal Terminal). Restores the whole venv (graphtraj ${TARGET[1,8]} + graftling $GOLDVERSION), the hook copy and the entry files from $BK; the current ones are kept in $BK/after-install-*. No login. Dialog: none (one Enter). Enter to continue, Ctrl-C to stop."; read -r answer
  [[ -e $BK/COMPLETE ]] || { print "STOP: no complete backup in $BK (the install starts only after it): production was not changed by I. Tell Main."; exit 1; }
  { members_idle R || { print "STOP: a member or host runs (above). Nothing restored."; exit 1; }
    KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S); mkdir -p $KEEP/entries
    mv $RT $KEEP/venv && cp -Rp $BK/venv $RT || exit 1
    tree compare $BK/venv.manifest $RT; ck $? "R venv equals the pre-install bytes"
    [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; cp -Rp $BK/plugin $PDIR || exit 1
    tree compare $BK/plugin.manifest $PDIR; ck $? "R hook copy restored"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__} || { cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $BK/entries/${${f#$H/}//\//__} $f; }; done
    shasum -a 256 -c $BK/entries.sha256; ck $? "R entry files restored"
    direct_urls $GOLDVERSION; [[ $DGT == *"wheels-${TARGET[1,8]}/graphtraj-$GTVERSION-"* && $DGL == *"$T617/adoption/wheels-$GOLDVERSION/graftling-$GOLDVERSION-"* && $DGL == *$GOLDSHA* ]]; ck $? "R graphtraj from 616's wheels-${TARGET[1,8]} and graftling $GOLDVERSION from 617's wheel (sha256 ${GOLDSHA[1,16]}...) again"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "R pip check" "${pc[1,120]}"
    CH=$H/.graphtraj/claude-host/live/channel.json; [[ -e $CH ]] && mv $CH $KEEP/channel.json && print "moved out a stale $CH"
  } 2>&1 | tee -a $R/R.txt
  grep -q '^CHECK 625 R .*: FAIL' $R/R.txt && { print "\nR left a difference (above). Do not resume Main; hand $R/R.txt to Main. R can be rerun."; exit 1; }
  print "Success: every 'CHECK 625 R ...: PASS'. Then (USER): cd $H && claude --continue" ;;

done) print "[done] Main. Read only: every CHECK line of every step's raw file, and production now. No login. Dialog: none."
  { miss=""
    steps=(00 rel B GR rp gh C5 V Mpre I Mr Nr)
    runs=($R/run<->(N/))
    (( $#runs )) && steps+=(I0)   # a failed I was set aside: I0 must have passed
    for d in $runs; do   # set-aside runs are listed, never counted (only the current I and R records count)
      print -r -- "SUPERSEDED ${d:t}: $(cat $d/SUPERSEDED 2>/dev/null || print 'set aside by I0') | files: $(print -l $d/*(N:t) | tr '\n' ' ')| its CHECK FAIL lines (not counted): $(cat $d/*.txt(N) | grep -c '^CHECK .*: FAIL')"
    done
    for s in $steps; do [[ -s $R/$s.txt ]] || miss="$miss $s"; done
    grep -h '^CHECK ' $R/${^steps}.txt(N)
    grep -h '^REPORT 625 ' $R/C5.txt(N); grep -h '^RESULT 625 G/GR: ' $R/GR.txt(N) | tail -1
    np=$(cat $R/${^steps}.txt(N) | grep -c '^CHECK .*: PASS') nf=$(cat $R/${^steps}.txt(N) | grep -cE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)')
    say "production now"
    print -r -- "graphtraj graftling: $(prod_versions)"; direct_urls $GVERSION
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"* && $DGL == *"$NG/graftling-$GVERSION-"* ]]
    ck $? "done production graphtraj from 616's wheels-${TARGET[1,8]}, graftling $GVERSION from wheels-$GVERSION"
    print -r -- "steps without a raw file:${miss:- none} | CHECK PASS $np | CHECK not passed $nf"
    [[ -z $miss && $nf == 0 ]]; ck $? "done every step ran and every CHECK passed"
  } 2>&1 | tee $R/done.txt
  grep -q '^CHECK 625 done every step ran and every CHECK passed: PASS' $R/done.txt && ! grep -qE '^CHECK .*: FAIL' $R/done.txt || { print "\ndone: FAIL (see above). Hand $R/done.txt to the Team."; exit 1; }
  print "Success: both 'CHECK 625 done ...: PASS' (production graphtraj ${TARGET[1,8]} + graftling $GVERSION; every step's CHECK passed)."
  next "Main: hand $R to the Team; Task 625 steps complete. Rollback stays available (Main asks the USER first): zsh $BK/tools/steps.zsh R" ;;

*) print "usage: zsh $THIS 00|rel|B|G|GR|SR|suite-base|rp|gh|C5|V|I0|Mpre|I|M|Mr|N|Nr|done|R"; exit 2 ;;
esac
