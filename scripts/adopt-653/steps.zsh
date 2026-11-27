#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 653 Main-run steps: release graftling 0.11.0 (native Windows support, 632-652; compatible by PUBLIC_API section 7,
# minor version by the user's decision of 2026-11-28) and adopt it into production together with GraphTraj's adoption
# commit TARGET (GraphTraj dev 5a17543e with the graftling range widened to graftling>=0.10.0,<0.12).
# One release commit 67b0fe9a "graftling 0.11.0 (653)" on graftling dev 9650361e, in graftling-0.11.0.bundle next to
# this file. User decisions (Worldline): release, push of dev/main/tag and adoption 20261128T030617.779906+0900
# ("发版并采用到生产"); pushing agent branches and running the Windows workflow 20261127T190418.319112+0900 (long-term).
# Run one step at a time:  zsh <this file> <STEP>     ONE ordered list:
#   00 -> P (push the release branch, dispatch windows.yml on it, wait, judge; W/X observe or re-run failed jobs)
#   -> rel -> B -> G (Main starts it as a background command; G itself waits for its shards and ends with GR's
#   verdict; -> SR -> suite-base only if NEW) -> rp -> gh -> C5 -> V -> Mpre
#   -> [Main tells the USER; 653's Leader and Engineer have ended their turns] USER /exit Main -> I (USER, Terminal)
#   -> USER `cd <Harness> && claude --continue` (expected: the plugin/hooks trust dialog; trust) -> M -> Mr -> N -> Nr
#   -> done.   rp needs P (Windows) and G/GR passed. B and V may run while P or G run.
#   Rollback: R (Main asks the USER first; the USER /exits Main), run from the backup's own copy.
#   A failed I that R rolled back: I0 -> Mpre -> USER /exit + I -> claude --continue -> M -> ... -> done (README.md).
# I installs BOTH wheels (graftling from git archive v0.11.0, graphtraj from git archive TARGET) in ONE
# pip --force-reinstall --no-deps --no-index call, then regenerates the hook copy ONLY through the product
# (graphtraj.runtimes.claude.host configuration --write); V predicts that copy and the entries first.
# Login: the Claude login the user approved, named in Task 653's definition (production adoption), for 00's probe and N;
# Main's own running Session carries M. Network: github.com for 00, P, W, X, rp, gh, C5 (the user's usual git
# credentials for the pushes, gh's stored login for the Actions API); PyPI and uv's Python download for C5.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer; Main leaves all of these unset): ADOPT653_H, ADOPT653_WT, ADOPT653_STUB, ADOPT653_PROJECTS,
# ADOPT653_VPROJECT, ADOPT653_OUT, ADOPT653_SCRATCH, ADOPT653_UVT, ADOPT653_G, ADOPT653_GDEV, ADOPT653_GURL,
# ADOPT653_SOURCE, ADOPT653_NOSNAP, ADOPT653_GWAIT, ADOPT653_PYTEST_ARGS, ADOPT653_CLEAN_EXTRA, ADOPT653_GH,
# ADOPT653_APPEAR_S, ADOPT653_DONE_S, ADOPT653_POLL_S.
# No zsh special parameter name is used as a variable (path is used only as zsh's PATH array, as 593-625).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
TASKDIR=653-graftling-0-11-0-release-and-production-adoption
TASK_ID=653
THIS=${0:A}
SD=${0:A:h}
# The Harness and this Worktree: from the Worktree's location (<Harness>/.graphtraj/core/worktrees/<name>), or, for R
# run from the backup's own copy, from the HARNESS and WORKTREE files I writes beside it.
if [[ -f $SD/HARNESS && -f $SD/WORKTREE ]]; then H0=$(<$SD/HARNESS) WT0=$(<$SD/WORKTREE)
else WT0=$(/usr/bin/env -i PATH=/usr/bin:/bin git -C $SD rev-parse --show-toplevel 2>/dev/null); H0=${WT0:h:h:h:h}; fi
H=${ADOPT653_H:-$H0}                                # the Harness (production)
WT=${ADOPT653_WT:-$WT0}                             # this Task Worktree
S593=$WT/scripts/adopt-593                          # reused by path: adopt_tree.py, pkgdiff532.py, onegraft.py, adopt_plugin.py, ...
S616=$WT/scripts/adopt-616                          # reused by path: p616.py (Mr's ToolSearch INFO lines)
S617=$WT/scripts/adopt-617                          # reused by path: q617.py mcp (discover 'start an agent' = [create])
S632=$WT/scripts/verify-632                         # reused by path: wincheck.py, windows-expected.txt
S652=$WT/scripts/verify-652                         # reused by path: wincheck652.py, new-tests.txt
STEP=${1:-}
IDS=("${(@)argv[2,-1]}")                            # suite-base: node ids; W/X: a run id or sha
DECISION=20261128T030617.779906+0900                # the user's release, push and adoption decision
WINDECISION=20261127T190418.319112+0900             # the user's long-term authority: agent branches and the Windows workflow
LOGIN_NOTE="the Claude login the user approved, named in Task 653's definition (production adoption)"
path=($HOME/.local/bin /opt/homebrew/bin $path)     # claude, node and gh (the USER's usual installs)
[[ -n ${ADOPT653_STUB:-} ]] && path=($ADOPT653_STUB $path)   # rehearsal only: stub claude/ps first
CONDA=$HOME/miniconda3/bin/python3.13               # read only; builds the wheels, runs the helpers with -I
CROOT=${CONDA:h:h}
# ---- graftling release ----
G=${ADOPT653_G:-$H/graftling}                       # main is checked out here
GDEV=${ADOPT653_GDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # dev is checked out here
GURL=${ADOPT653_GURL:-https://github.com/LUOXIAO92/graftling.git}   # origin of $G (GitHub)
REPO=LUOXIAO92/graftling                            # the Actions API's repository
GBASE=9650361e13d6ef9981c753038469ff3b9e44cfa6      # graftling dev at dispatch (652)
GMAIN0=57bca73657d3135a4504904fcc3f1898c2419766     # graftling main = v0.10.2 (625)
GCOMMIT=67b0fe9aacc868c9c6b5a2818adc8449514221c4    # graftling 0.11.0 (653), parent $GBASE
GBRANCH=agent/653-graftling-0.11.0
BUNDLE=$SD/graftling-0.11.0.bundle
BSHA=660b394a384a1e645805bf4bc62f6411abcb46a0eb8ec59049e81ba51bcfb30e
GFILES="CHANGELOG.md PUBLIC_API.md src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json"
GTAG=v0.11.0
GVERSION=0.11.0
GOLDTAG=v0.10.2
GOLDVERSION=0.10.2
GHEADING="## 0.11.0 (compatible; minor release by the user's decision of 2026-11-28)"
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
RELMSG="graftling 0.11.0 (compatible; minor version by the user's decision of 2026-11-28): native Windows support (632-652). Claude Code, Codex, Pi and DSH work as hosts on Windows, Codex and DSH also as children; Claude and Pi children and the marketplace plugin are refused there. On POSIX only two Claude Code host refusal messages change (652); error codes are unchanged. Compatible by PUBLIC_API section 7; GraphTraj's range becomes graftling>=0.10.0,<0.12."
SRCURL="git+https://github.com/LUOXIAO92/graftling.git"   # the README's TAGLESS command: the default branch main
INSTALL=(uv tool install --managed-python $SRCURL)
[[ -n ${ADOPT653_SOURCE:-} ]] && INSTALL=(uv tool install --managed-python $ADOPT653_SOURCE)   # rehearsal only
UVT=${ADOPT653_UVT:-/private/tmp/uvtool-653}
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT653_NOSNAP:-}
# ---- the Windows workflow (P, W, X; judged as 652) ----
GH=${ADOPT653_GH:-$(whence -p gh || print -r -- gh)}
WORKFLOW=.github/workflows/windows.yml
APPEAR_S=${ADOPT653_APPEAR_S:-300}
DONE_S=${ADOPT653_DONE_S:-6000}
POLL_S=${ADOPT653_POLL_S:-30}
JOB=windows-tests
DSHJOB=dsh-windows-tests
REALJOB=claude-real-entry
SETUP=("Keep symbolic links on this runner" "Check out the commit under test" "Fail unless the linked package documents are symbolic links"
       "Set up Node 22.18.0 x64" "Set up Python 3.13.7 x64" "Install graftling and pinned test tools" "Show runner, Python and pytest versions")
SUITE="Run the graftling test suite"
UPLOAD="Retain JUnit results"
WINCHECK=$S632/wincheck.py
EXPECTED=$S632/windows-expected.txt
NEWTESTS=$S652/new-tests.txt
# ---- GraphTraj and production ----
TARGET=afaaca41e5c148048e0ce8bb0d1d7c352505a9f3     # GraphTraj adoption commit: DEV0 + the widened range; production after I
DEV0=5a17543e9cdaa927b136a2c14e6b8b82320a873e       # GraphTraj dev at dispatch, TARGET's parent
RANGE='"graftling>=0.10.0,<0.12",'                   # pyproject's dependency line at TARGET
OLDT=4ef36426ab6fa5a4769a23557aecf2aa2e2b3759       # production graphtraj now (616's wheel)
TOLDSHA=ac805ac9b3fb88f328a932a52ecd807a369ff25500f15d67d94489a1508bf473  # 616's graphtraj wheel (R's graphtraj)
GOLDSHA=300559ab2221d4d257ceeac10678e2a1de8abc40e0ce495abeb9acf072b9f1ee  # 625's graftling 0.10.2 wheel (R's graftling)
GTVERSION=0.1.0
STATE=$H/.graphtraj/core/state
T616=616-graphtraj-614-production-adoption
T625=625-graftling-0-10-2-release-and-production-adoption
W616=$STATE/tasks/$T616/adoption/wheels-${OLDT[1,8]}   # production's graphtraj wheel now (616)
W625=$STATE/tasks/$T625/adoption/wheels-$GOLDVERSION   # production's graftling wheel now (625)
AD=$STATE/tasks/$TASKDIR/adoption
NG=$AD/wheels-$GVERSION                             # the graftling wheel G, V and I install (B writes it)
NT=$AD/wheels-${TARGET[1,8]}                        # the graphtraj wheel V and I install (B writes it)
D516=$STATE/tasks/516-low-priority-flaky-tests      # known flaky tests: 516's CURRENT definition via its task.yml
SCR=${ADOPT653_SCRATCH:-$H/tmp/653}
GSRC=$SCR/gsrc                                      # git archive v0.11.0
TSRC=$SCR/tsrc                                      # git archive TARGET (B's comparison; I's manuals)
WHL=$SCR/wheel
BK=$SCR/backup
VV=$SCR/vvenv
R=${ADOPT653_OUT:-$STATE/tasks/$TASKDIR/realhost/main-raw}
WEV=$R/windows                                      # P, W, X: the run's jobs, logs, artifacts and judgement
RT=$H/.venv-runtime
VPROJ=${ADOPT653_VPROJECT:-/private/tmp/vproject-653}   # isolated project for the real MCP entries (graphtraj setup)
PDIR=$H/.claude/skills/graphtraj-claude-host
VPL=$AD/vplug; VP=$VPL/graphtraj-claude-host       # V's product-regenerated hook copy; I's copy must equal it
HOSTCFG=$H/.graphtraj/claude-host/config.json
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
SESS=$H/.graphtraj/swarm/sessions
PROJECTS=${ADOPT653_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
MODEL=claude-opus-5-5
CHILD=n653
DONEWORD=DONE-653
SUITEIDS=$WT/scripts/verify-581/suiteids.py
MAIN=$(cat $SCR/main.session 2>/dev/null)

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT653_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean git "$@"; }                            # every git call: allowlist environment
gpush() { clean GIT_TERMINAL_PROMPT=0 git "$@"; }   # pushes: a credential helper that needs a dialog fails instead
ghc() {  # gh with the allowlist environment (its stored login; no prompt)
  local -a extra=(); [[ -n ${GH_CONFIG_DIR:-} ]] && extra+=GH_CONFIG_DIR=$GH_CONFIG_DIR; [[ -n ${XDG_CONFIG_HOME:-} ]] && extra+=XDG_CONFIG_HOME=$XDG_CONFIG_HOME
  clean GH_PROMPT_DISABLED=1 GIT_TERMINAL_PROMPT=0 $extra $GH "$@"
}
ck() { [[ $1 == 0 ]] && print -r -- "CHECK 653 $2: PASS${3:+ ($3)}" || print -r -- "CHECK 653 $2: FAIL${3:+ ($3)}"; }   # $1 = 0 for pass
U=$(clean /usr/bin/which uv 2>/dev/null)            # the uv on the clean PATH; every uv call uses this one file
rel_wt() {  # the worktree that has branch $1 checked out in $G, if any
  gg -C $G worktree list --porcelain | awk -v b="branch refs/heads/$1" '/^worktree /{w=substr($0,10)} $0==b{print w}'
}
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT653_NOSNAP, rehearsal only)"; return 0; }
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
product_guard() {  # TARGET = DEV0 + pyproject.toml (range <0.12); HEAD differs from TARGET only under scripts/adopt-653/; clean
  local head tdiff other dirty range parent
  head=$(gg -C $WT rev-parse HEAD) parent=$(gg -C $WT rev-parse -q --verify "$TARGET^" 2>/dev/null)
  tdiff=$(gg -C $WT diff --name-only $DEV0 $TARGET 2>&1); other=$(gg -C $WT diff --name-only $TARGET HEAD 2>&1 | grep -v '^scripts/adopt-653/')
  dirty=$(gg -C $WT status --porcelain -- . ':!scripts/adopt-653/rehearsal' 2>&1)
  range=$(gg -C $WT show ${TARGET}:pyproject.toml 2>/dev/null | grep -m1 '"graftling')
  print -r -- "product guard: HEAD $head | TARGET ${TARGET[1,8]}'s parent ${parent[1,8]:-none} (DEV0 ${DEV0[1,8]}) | git diff ${DEV0[1,8]} ${TARGET[1,8]}: ${${tdiff//$'\n'/ }:-empty} | changes since ${TARGET[1,8]} outside scripts/adopt-653/: ${${other//$'\n'/ }:-none} | uncommitted (rehearsal outputs excepted): ${${dirty//$'\n'/ }:-none} | graftling range at ${TARGET[1,8]}: ${range//[[:space:]]/}"
  [[ $parent == $DEV0 ]] && gg -C $WT merge-base --is-ancestor $TARGET HEAD \
    && [[ $tdiff == pyproject.toml && -z $other && -z $dirty && ${range//[[:space:]]/} == $RANGE ]]
}
marker653() {  # $1 = label, $2 = an installed or unpacked graftling package dir: 0.11.0's code (647, 652) is in it
  local m=$2/claude/host_context.mjs w b n t v
  w=$(grep -c '^const WINDOWS_UNSUPPORTED = ' $m 2>/dev/null) b=$(grep -c '^const BOOT = ' $m 2>/dev/null)
  n=$(grep -c '^def native_claude() -> Path:' $2/claude/settings.py 2>/dev/null)
  t=$(grep -cF 'so Claude Code has not loaded it' $2/claude/native_host.py 2>/dev/null)
  v=$(grep -c "^__version__ = \"$GVERSION\"" $2/__init__.py 2>/dev/null)
  print -r -- "  0.11.0 marker in $2: __init__.py version $GVERSION x${v:-0} | claude/host_context.mjs WINDOWS_UNSUPPORTED x${w:-0}, BOOT x${b:-0} | claude/settings.py native_claude x${n:-0} | claude/native_host.py 'so Claude Code has not loaded it' x${t:-0}"
  (( ${v:-0} == 1 && ${w:-0} == 1 && ${b:-0} == 1 && ${n:-0} == 1 && ${t:-0} >= 1 ))
  ck $? "$1 0.11.0's code is in $2 (version; 647's BOOT and 652's WINDOWS_UNSUPPORTED in host_context.mjs; native_claude; 652's unloaded-plugin message)"
}
oldbks() { local b; for b in $H/tmp/*/backup(N/); do [[ ${b:A} == ${BK:A} ]] || print -r -- $b; done; }   # rollbacks the user keeps
oldbk_report() {  # $1 = label: every <Harness>/tmp/*/backup other than 653's (never written); one fingerprint line each
  local b; local -a l=(${(f)"$(oldbks)"})
  (( $#l )) || { print -r -- "  $1 other backups under $H/tmp: none"; return 0; }
  for b in $l; do print -r -- "  $1 kept backup $b: $([[ -e $b/COMPLETE ]] && print COMPLETE || print 'no COMPLETE') | top-level mtime $(stat -f '%m' $b) | entries $(find $b -maxdepth 2 2>/dev/null | wc -l | tr -d ' ')"; done
}
other_suites() {  # test runs of anyone; exit 2 when ps cannot list (never read as "no other suite")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then print -r -- "ps cannot list processes (${listed[1,160]})"; return 2; fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E|other_suites'
  return 0
}
# 593-625's guard: BLOCKING = a live process naming $RT/, Main's host config or Main's Session id; budget timers and
# zombies are listed, never blocking; nothing is ever signalled. Return 2 when ps cannot list.
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
    print -r -- "# 653 scratch project" > $VPROJ/README.md
    gg -C $VPROJ add README.md && gg -C $VPROJ -c user.name=653 -c user.email=653@invalid commit -qm "Initial source" || return 1
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
  out=$(print -r -- '{"hook_event_name":"Probe653","session_id":"probe-653","cwd":"'$VPROJ'"}' | (cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
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
      print -r -- "INFO 653 $1 tolerated in $2: .claude/.cc-writes (empty), the Claude Code sandbox write marker (inferred, 612; not a product file, in no RECORD)"
    fi
  fi
  print -r -- "diff -r archive manuals vs $2 (the marker excepted): ${${d//$'\n'/ | }[1,300]:-none}"
  [[ -z $d ]]; ck $? "$1 share/graphtraj/manuals equals git archive ${TARGET[1,8]}'s manuals ($(find $2 -type f ! -path "$2/.claude/*" 2>/dev/null | wc -l | tr -d ' ') product files)"
}
templates() {  # graftling's host_context.mjs at v0.10.2 and v0.11.0 (read from $G), the inputs of plugin653.py
  mkdir -p $AD && gg -C $G show $GOLDTAG:src/graftling/claude/host_context.mjs > $AD/host_context-$GOLDVERSION.mjs \
    && gg -C $G show $GTAG:src/graftling/claude/host_context.mjs > $AD/host_context-$GVERSION.mjs
}
plugin_check() {  # $1 = production copy, $2 = candidate copy: exactly the template change (plugin653.py)
  clean $CONDA -I $SD/plugin653.py $1 $2 $AD/host_context-$GOLDVERSION.mjs $AD/host_context-$GVERSION.mjs
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
tig_of() { sed -n 's/^test interpreter graftling: \([^ ]*\) .*/\1/p' $1/run.txt 2>/dev/null | head -1; }
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
gr_passed() { [[ -e $R/GR.ok ]] && grep -q "^RESULT 653 G/GR: PASS" $R/GR.txt 2>/dev/null; }
win_passed() { [[ -e $R/WIN.ok ]] && grep -q "^CHECK 653 win .*: PASS" $R/WIN.txt 2>/dev/null; }
passed() { [[ -s $R/$1.txt ]] && grep -q "^CHECK 653 $1 " $R/$1.txt && ! grep -q "^CHECK 653 $1 .*: FAIL" $R/$1.txt; }

# ---- the Windows workflow: Actions API, waiting and judging (652's judge, with 653's paths and label) ----
wc_() { clean $CONDA -I $WINCHECK "$@"; }
w652_() { clean $CONDA -I $S652/wincheck652.py "$@"; }
api() {  # $1 = output file, $2 = endpoint: save a gh api response; on failure print the error and return 1
  ghc api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}
judge() {  # $1 = completed run's json, $2 = label: jobs, logs, artifacts, judgement; ends with the VERDICT line
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res files newt djob rjob real jname tlist=
  rid=$(wc_ get $runfile id); sha=$(wc_ get $runfile head_sha); attempt=$(wc_ get $runfile run_attempt)
  concl=$(wc_ get $runfile conclusion); url=$(wc_ get $runfile html_url); event=$(wc_ get $runfile event)
  dir=$WEV/run-$rid-a${attempt:-1}; mkdir -p $dir
  print -r -- "--- run $rid | attempt $attempt | $event | conclusion $concl (information only) | head $sha | $url"
  [[ $sha == $GCOMMIT ]] || print -r -- "NOTE: run head $sha is not the release commit $GCOMMIT (the VERDICT requires it)"
  clean $CONDA -I -c 'import json, sys; print(json.dumps({"job": sys.argv[1], "setup": sys.argv[2:-2], "suite": sys.argv[-2], "upload": sys.argv[-1]}))' \
    $JOB $SETUP $SUITE $UPLOAD > $WORK/config.json
  if api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/attempts/${attempt:-1}/jobs?per_page=100"; then
    cp $WORK/jobs.json $dir/jobs.json
    wc_ jobs $WORK/jobs.json $WORK/config.json > $WORK/jobs.txt 2>&1
    w652_ jobstate $WORK/jobs.json $DSHJOB > $WORK/dshjob.txt 2>&1
    w652_ jobstate $WORK/jobs.json $REALJOB > $WORK/realjob.txt 2>&1
  else
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/dshjob.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/realjob.txt
  fi
  cat $WORK/jobs.txt $WORK/dshjob.txt $WORK/realjob.txt > $dir/jobs.txt
  grep -v '^JUDGE \|^JOB ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  grep -v '^JOBSTATE ' $WORK/dshjob.txt | head -3
  djob=$(grep '^JOBSTATE ' $WORK/dshjob.txt | tail -1); [[ -n $djob ]] || djob="JOBSTATE FAIL $DSHJOB judgement failed"
  grep -v '^JOBSTATE ' $WORK/realjob.txt
  rjob=$(grep '^JOBSTATE ' $WORK/realjob.txt | tail -1); [[ -n $rjob ]] || rjob="JOBSTATE FAIL $REALJOB judgement failed"
  for jname in $JOB $REALJOB; do   # each job's log (ANSI colour codes need --allow-escape-sequences, 619)
    jid=$(clean $CONDA -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == sys.argv[2]), ""))' $WORK/jobs.json $jname 2> /dev/null)
    if [[ -n $jid ]] && ghc api --allow-escape-sequences "repos/$REPO/actions/jobs/$jid/logs" > $dir/$jname.log 2> $WORK/err; then print -r -- "--- job log saved: $dir/$jname.log"
    else print -r -- "$jname job log unavailable: $(<$WORK/err 2> /dev/null)"; fi
  done
  [[ -f $dir/$JOB.log ]] && grep -E '(### HUNG|run_test_files exit code:|INTERNALERROR|has timed out)' $dir/$JOB.log | tail -n 12 | cut -c1-240 | sed 's/^/  /'
  local name=graftling-windows-junit-$sha-${attempt:-1} rname=graftling-claude-real-entry-$sha-${attempt:-1}
  if [[ -f $dir/junit/environment.json ]]; then print -r -- "already present, not downloaded again: $dir/junit"
  else print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dir/junit"; ghc run download $rid --repo $REPO -n $name -D $dir/junit 2>&1 | sed 's/^/  /'; fi
  # The commit's test files (the bundle's commit is in $G after P).
  if gg -C $G cat-file -e "$sha^{commit}" 2> /dev/null; then
    gg -C $G ls-tree --name-only $sha tests/ | grep -E '^tests/test_[^/]*\.py$' > $WORK/testfiles.txt; tlist=$WORK/testfiles.txt
    print -r -- "test files in $sha: $(grep -c . $tlist)"
  else print -r -- "NOTE: $sha is not in $G; per-file records are not compared with its test files"; fi
  if [[ -f $dir/junit/environment.json ]]; then
    print -r -- "--- per-file records and results against $EXPECTED"
    wc_ junit $dir/junit $EXPECTED $dir/observed-expected.txt $tlist > $dir/judgement.txt 2>&1
    grep -v '^JUDGE \|^FILES ' $dir/judgement.txt
    files=$(grep '^FILES ' $dir/judgement.txt | tail -1); [[ -n $files ]] || files="FILES FAIL per-file judgement failed: $(tail -2 $dir/judgement.txt)"
    res=$(grep '^JUDGE ' $dir/judgement.txt | tail -1); [[ -n $res ]] || res="JUDGE FAIL JUnit judgement failed: $(tail -2 $dir/judgement.txt)"
    w652_ newtests $dir/junit $NEWTESTS > $dir/652-tests.txt 2>&1
    newt=$(grep '^NEWTESTS ' $dir/652-tests.txt | tail -1); [[ -n $newt ]] || newt="NEWTESTS FAIL check failed: $(tail -2 $dir/652-tests.txt)"
  else
    files="FILES FAIL no artifact downloaded ($name)"; res="JUDGE FAIL no JUnit files"; newt="NEWTESTS FAIL no JUnit files"
    print -r -- "NEWTESTS FAIL no JUnit files" > $dir/652-tests.txt
  fi
  if [[ $files == "FILES FAIL"* ]]; then [[ $mech == "JUDGE PASS"* ]] && mech="JUDGE FAIL ${files#FILES FAIL }" || mech="$mech; ${files#FILES FAIL }"
  else mech="$mech; ${files#FILES PASS }"; fi
  grep -v '^NEWTESTS ' $dir/652-tests.txt
  if [[ -f $dir/real-entry/results.json ]]; then print -r -- "already present, not downloaded again: $dir/real-entry"
  else print -r -- "\$ gh run download $rid --repo $REPO -n $rname -D $dir/real-entry"; ghc run download $rid --repo $REPO -n $rname -D $dir/real-entry 2>&1 | sed 's/^/  /'; fi
  w652_ realentry $dir/real-entry > $dir/real-entry-judgement.txt 2>&1
  grep -v '^REALENTRY ' $dir/real-entry-judgement.txt
  real=$(grep '^REALENTRY ' $dir/real-entry-judgement.txt | tail -1); [[ -n $real ]] || real="REALENTRY FAIL judgement failed: $(tail -2 $dir/real-entry-judgement.txt)"
  print -r -- "evidence: $dir"
  print -r -- "RUNID $rid"
  if [[ $sha == $GCOMMIT && $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* && $newt == "NEWTESTS PASS"* && $djob == "JOBSTATE PASS"* \
        && $rjob == "JOBSTATE PASS"* && $real == "REALENTRY PASS"* ]]; then
    print -r -- "VERDICT 653 $label: PASS (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; 652 tests: ${newt#NEWTESTS PASS }; ${djob#JOBSTATE PASS }; ${rjob#JOBSTATE PASS }; real Claude Code: ${real#REALENTRY PASS }; $url)"
    return 0
  fi
  print -r -- "VERDICT 653 $label: FAIL (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE }; results: ${res#JUDGE }; 652 tests: ${newt#NEWTESTS }; ${djob#JOBSTATE }; ${rjob#JOBSTATE }; real Claude Code: ${real#REALENTRY }; $url)"
  return 1
}
wait_run() {  # $1 = run id, $2 = label: wait for completion (bounded), then judge
  local rid=$1 label=$2 start=$SECONDS rstate= prev= line
  print -r -- "waiting in this process for run $rid (completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    api $WORK/run.json repos/$REPO/actions/runs/$rid && rstate=$(wc_ get $WORK/run.json status)
    line="${rstate:-unknown} $(wc_ get $WORK/run.json conclusion 2> /dev/null)"
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] run $rid: $line"; prev=$line
    [[ $rstate == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "RUNID $rid"; print -r -- "completion timeout after $((SECONDS - start))s (run still ${rstate:-unknown})"
      print -r -- "VERDICT 653 $label: FAIL (run $rid not completed within ${DONE_S}s)"; return 1
    fi
    sleep $POLL_S
  done
  judge $WORK/run.json $label
}
dispatch_ids() {  # $1 = runs json: the windows.yml workflow_dispatch run ids in it, space separated
  clean $CONDA -I -c 'import json, sys; print(" ".join(str(r["id"]) for r in json.load(open(sys.argv[1])).get("workflow_runs", []) if r.get("path") == sys.argv[2] and r.get("event") == "workflow_dispatch"))' $1 $WORKFLOW
}
win_after() {  # $1 = the step (P, W, X): record the verdict; WIN.ok and WIN.txt on PASS; the next command last
  local v rid; v=$(grep '^VERDICT 653 ' $R/$1.txt | tail -1); rid=$(sed -n 's/^RUNID //p' $R/$1.txt | tail -1)
  if [[ $v == "VERDICT 653 $1: PASS"* ]]; then
    ck 0 "win Windows workflow on the release commit $GCOMMIT ($1)" "${v#VERDICT 653 $1: PASS }" > $R/WIN.txt; touch $R/WIN.ok
    summary $1 "$(grep -E '^(CHECK|VERDICT|PASS:|remote|dispatch|run )' $R/$1.txt)"
    print "Success: VERDICT 653 $1: PASS (windows-tests against windows-expected.txt, 652's tests, dsh-windows-tests, claude-real-entry)."
    next "zsh $THIS rel"; return 0
  fi
  rm -f $R/WIN.ok
  print -r -- "\n$1 not passed (see above; ${v:-no VERDICT}). Evidence under $WEV. A test result failing: hand $R/$1.txt to the Team; do not push dev/main/tag."
  if [[ -n $rid ]]; then next "zsh $THIS W $rid    (observe again; no push, no re-run)   or, only for a transient runner/download fault: zsh $THIS X $rid"
  else next "zsh $THIS W    (observe the newest dispatch run of $GCOMMIT)"; fi
  return 1
}

mkdir -p $R || exit 1
cred_guard
[[ -n $U || $STEP == R ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
case $STEP in
00) print "[00] Main. Read only, apart from creating $SCR (main.session, cc.version, the probe's stream, a scratch clone g00.git to read the bundle). Login: yes, one claude -p probe with $LOGIN_NOTE; gh's stored login (gh auth status, account only); no Codex, Pi or DSH. Network: github.com (git ls-remote, gh) and Claude. Dialog: none."
  { mkdir -p $SCR || exit 1
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python'; ck $? "00 this uv's 'uv tool install --help' lists --managed-python"
    check_tmp; ck $? "00 TMPDIR outside the Harness"
    [[ ! -e $UVT ]]; ck $? "00 $UVT absent" "$([[ -e $UVT ]] && print "move it aside first: mv $UVT $UVT.old-\$(date +%s)")"
    au=$(ghc auth status 2>&1); arc=$?; print -r -- "gh: $GH | $(ghc --version 2>&1 | head -1) | auth status: $(print -r -- $au | grep -iE 'logged in|account' | head -2 | tr '\n' ' ')"
    ck $arc "00 gh auth status rc 0 (gh's stored login; P, W, X read and dispatch the Actions run with it)"
    say "graftling repository $G (read only)"
    gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "dev: ${gd:-NOT FOUND} in ${dw:-no worktree} | main: ${gm:-NOT FOUND} in ${mw:-no worktree} | origin: $(gg -C $G remote get-url origin 2>&1)"
    [[ $gd == $GBASE ]]; ck $? "00 graftling dev = $GBASE"
    [[ $gm == $GMAIN0 ]]; ck $? "00 graftling main = $GMAIN0 ($GOLDTAG)"
    [[ $(gg -C $G remote get-url origin 2>&1) == $GURL ]]; ck $? "00 origin of $G is $GURL"
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]]; ck $? "00 dev is checked out in $GDEV and main in $G"
    dirty=""; for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || dirty="$dirty $w"; done
    [[ -z $dirty ]]; ck $? "00 both worktrees clean (git status --porcelain empty)" "${dirty# }"
    lt=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG); [[ -z $lt ]]; ck $? "00 $GTAG absent locally" "$lt"
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH); [[ -z $lb || $lb == $GCOMMIT ]]; ck $? "00 local $GBRANCH absent or the release commit" "${lb:-absent}"
    say "GitHub $GURL (git ls-remote, read only)"
    if rem=$(gg ls-remote $GURL refs/heads/main refs/heads/dev refs/tags/$GTAG refs/heads/$GBRANCH 2>&1); then
      rm0=$(remote_of $rem refs/heads/main) rd0=$(remote_of $rem refs/heads/dev) rt0=$(remote_of $rem refs/tags/$GTAG) rb0=$(remote_of $rem refs/heads/$GBRANCH)
      print -r -- "GitHub main: ${rm0:-absent} | dev: ${rd0:-absent} | $GTAG: ${rt0:-absent} | $GBRANCH: ${rb0:-absent}"
      [[ $rm0 == $GMAIN0 ]]; ck $? "00 GitHub main = $GMAIN0"
      [[ -z $rt0 ]]; ck $? "00 GitHub $GTAG absent"
      [[ -n $rd0 ]] && gg -C $G merge-base --is-ancestor $rd0 $GBASE 2>/dev/null; ck $? "00 GitHub dev (${rd0:-absent}) is $GBASE or its ancestor, so rp fast-forwards it"
      [[ -z $rb0 || $rb0 == $GCOMMIT ]]; ck $? "00 GitHub $GBRANCH absent or the release commit (P pushes it, fast-forward only)" "${rb0:-absent}"
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
    [[ $changed == $(print -l ${=GFILES} | sort | tr '\n' ' ') ]]; ck $? "00 the release commit changes exactly the 4 version files, CHANGELOG.md and PUBLIC_API.md (so windows.yml and the tests are 652's)"
    print -r -- "version at $GCOMMIT: $($X show ${GCOMMIT}:src/graftling/__init__.py | grep -E '^__version__')"
    hd=$($X show ${GCOMMIT}:CHANGELOG.md | grep -m1 '^## '); print -r -- "CHANGELOG first heading: $hd"
    [[ $hd == $GHEADING ]] && ! $X show ${GCOMMIT}:CHANGELOG.md | grep -q '^## Unreleased'; ck $? "00 CHANGELOG at $GCOMMIT starts '$GHEADING' and has no '## Unreleased'"
    line=$($X show ${GCOMMIT}:README.md | grep -m1 '^uv tool install ')
    print -r -- "README install line: $line"; print -r -- "C5 runs:             uv tool install --managed-python \"$SRCURL\""
    [[ $line == "uv tool install --managed-python \"$SRCURL\"" ]]; ck $? "00 README's first install line at $GCOMMIT is C5's tagless command"
    say "the Windows judgement's inputs (read only)"
    wc_ expected $EXPECTED | tail -2; ck ${pipestatus[1]} "00 windows-expected.txt parses ($EXPECTED)"
    [[ $(grep -vc '^#' $NEWTESTS) -ge 1 ]]; ck $? "00 652's new-tests.txt is readable ($(grep -vc '^#' $NEWTESTS) node ids; each must PASS on Windows)"
    say "production $RT (read only)"
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"
    direct_urls $GOLDVERSION
    [[ $pv == "$GTVERSION $GOLDVERSION" && $DGT == *"$W616/graphtraj-$GTVERSION-"*.whl* && $DGL == *"$W625/graftling-$GOLDVERSION-"*.whl* ]]
    ck $? "00 production is graphtraj $GTVERSION (616's wheels-${OLDT[1,8]}) + graftling $GOLDVERSION (625's wheels-$GOLDVERSION)"
    (cd $W616 && shasum -a 256 -c SHA256SUMS > /dev/null 2>&1) && [[ $(shasum -a 256 $W616/graphtraj-$GTVERSION-*.whl(N) | cut -d' ' -f1) == $TOLDSHA ]]
    ck $? "00 616's wheels-${OLDT[1,8]} (R's graphtraj) verifies, sha256 ${TOLDSHA[1,16]}..."
    (cd $W625 && shasum -a 256 -c SHA256SUMS > /dev/null 2>&1) && [[ $(shasum -a 256 $W625/graftling-$GOLDVERSION-*.whl(N) | cut -d' ' -f1) == $GOLDSHA ]]
    ck $? "00 625's wheels-$GOLDVERSION (R's graftling) verifies, sha256 ${GOLDSHA[1,16]}..."
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "00 production pip check" "${pc[1,120]}"
    print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp,graphtraj-mcp,agent-runner}(N:t) | tr '\n' ' ')"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && ! -e $RT/bin/agents ]]; ck $? "00 production bin has subagents, subagents-mcp, graphtraj-mcp (and no agents)"
    say "backups under $H/tmp (information; none is required; never written)"
    oldbk_report 00 | tee $SCR/oldbk-00.txt
    [[ ! -e $BK ]]; ck $? "00 backup $BK absent"
    say "this Worktree $WT (GraphTraj adoption commit ${TARGET[1,8]} + scripts/adopt-653/)"
    product_guard; ck $? "00 TARGET ${TARGET[1,8]} = GraphTraj dev ${DEV0[1,8]} + pyproject.toml (range $RANGE); HEAD differs from TARGET only under scripts/adopt-653/; clean"
    print -r -- "graphtraj product changes ${OLDT[1,8]} (production) .. ${TARGET[1,8]} (information): $(gg -C $WT diff --name-only $OLDT $TARGET -- src manuals pyproject.toml plugins skills | tr '\n' ' ')| desktop/src files changed: $(gg -C $WT diff --name-only $OLDT $TARGET -- desktop/src | grep -c .) (not in the graphtraj wheel; B checks)"
    cdef=$(cdef_of $STATE/tasks/$TASKDIR); [[ -n $cdef && -f $cdef ]]; ck $? "00 Task $TASK_ID ready (current_definition ${cdef:t} exists)"
    print -r -- "hook copy and entry files (hashes; V and I compare against them):"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json $ENTRIES 2>&1 | sed 's/^/  /'
    say "Claude: version and one claude -p probe ($LOGIN_NOTE)"
    C=$(claude_bin); [[ -s $SCR/cc.version ]] || clean $C --version 2>&1 | head -1 > $SCR/cc.version; cv
    P=$(mktemp -d ${TMPDIR:-/tmp}/probe-653.XXXXXX)
    (cd $P && print -r -- "Reply with one line: READY-653 and your model id." | clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose > $SCR/00-probe.jsonl 2>&1)
    ans=$(clean $CONDA -I -c 'import json, sys
init, result = {}, ""
for line in open(sys.argv[1], errors="replace"):
    try: r = json.loads(line)
    except ValueError: continue
    if r.get("type") == "system" and r.get("subtype") == "init": init = r
    if r.get("type") == "result": result = str(r.get("result", ""))
print("model %s | apiKeySource %s | answer %r" % (init.get("model"), init.get("apiKeySource"), result[:120]))' $SCR/00-probe.jsonl 2>&1)
    print -r -- "claude -p probe: $ans (stream: $SCR/00-probe.jsonl)"
    [[ $ans == *"model $MODEL"* && $ans == *"apiKeySource none"* && $ans == *READY-653* ]]
    ck $? "00 claude -p answers READY-653 on $MODEL through the Claude login (apiKeySource none: no API key)"
    say "Main's Session (I, M, Mr need it)"
    id=$(detect_main); [[ -n $id ]] && print -r -- $id > $SCR/main.session
    print -r -- "MAIN=${id:-NOT FOUND} (saved to $SCR/main.session)"; [[ -n $id ]]; ck $? "00 Main's Session id found"
    members_idle 00 | head -14 || print "(information at 00: members may run now; Mpre and I wait for them)"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above). Nothing was changed. Hand $R/00.txt to the Team."; exit 1; }
  summary 00 "$(grep -E '^(uv|gh|CHECK|TMPDIR|dev|GitHub|sha256|list-heads|README|C5 runs|production|  00 |claude|MAIN=|members_idle)' $R/00.txt)"
  print "Success: every 'CHECK 653 00 ...: PASS'."
  next "zsh $THIS P    (pushes $GBRANCH, dispatches the Windows workflow on it and waits for it, up to ~100 min; meanwhile rel and B may run)" ;;

P) print "[P] Main. OUTWARD-FACING under the user's long-term authority $WINDECISION (agent branches and the Windows workflow): (1) fetch $GBRANCH from the bundle into $G (only if absent); (2) push it to origin ($GURL), fast-forward only, never forced; (3) dispatch $WORKFLOW on it (workflow_dispatch, which also runs claude-real-entry), unless a dispatch run of $GCOMMIT exists, which is then observed; (4) wait in this process (appearance ${APPEAR_S}s, completion ${DONE_S}s); (5) judge as 652: windows-tests against $EXPECTED, 652's tests, dsh-windows-tests, claude-real-entry. dev, main and the tag are not pushed here. Login: git credential helper (push), gh's stored login. Network: GitHub. Dialog: none. Up to ~100 min."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/adopt653-P.XXXXXX); trap 'rm -rf $WORK' EXIT
    [[ $(shasum -a 256 $BUNDLE | cut -d' ' -f1) == $BSHA ]] && gg -C $G bundle verify -q $BUNDLE > /dev/null 2>&1 \
      && [[ $(gg bundle list-heads $BUNDLE) == "$GCOMMIT refs/heads/$GBRANCH" ]] || { print "STOP: the bundle (sha256 $BSHA, head $GCOMMIT) does not verify against $G. Nothing pushed."; exit 1; }
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH)
    if [[ -z $lb ]]; then gg -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" || { print "STOP: fetching $GBRANCH from the bundle failed. Nothing pushed."; exit 1; }
    elif [[ $lb != $GCOMMIT ]]; then print -r -- "STOP: $G has local $GBRANCH at $lb, not $GCOMMIT; never overwritten. Nothing pushed."; exit 1; fi
    [[ $(gg -C $G rev-parse refs/heads/$GBRANCH) == $GCOMMIT ]]; ck $? "P local $GBRANCH = $GCOMMIT"
    [[ $(gg -C $G remote get-url origin 2>&1) == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL. Nothing pushed."; exit 1; }
    rb=$(gg -C $G ls-remote origin refs/heads/$GBRANCH 2>&1) || { print -r -- "STOP: git ls-remote failed (nothing pushed): ${rb[1,200]}"; exit 1; }
    rb=${rb%%$'\t'*}
    if [[ -z $rb ]]; then
      print -r -- "remote $GBRANCH: absent; pushing (fast-forward only, no force)"
      gpush -C $G push origin refs/heads/${GBRANCH}:refs/heads/$GBRANCH || { print "STOP: the push was refused. Nothing else changed."; exit 1; }
    elif [[ $rb == $GCOMMIT ]]; then print -r -- "remote $GBRANCH: already $GCOMMIT (not pushed again)"
    else print -r -- "STOP: origin has $GBRANCH at $rb, not $GCOMMIT; never forced. Nothing pushed."; exit 1; fi
    now=$(gg -C $G ls-remote origin refs/heads/$GBRANCH 2>&1); [[ ${now%%$'\t'*} == $GCOMMIT ]]; ck $? "P remote $GBRANCH = $GCOMMIT" "${now%%$'\t'*}"
    api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" || { print "STOP: the Actions API is not readable (gh login?). The branch is pushed; rerun P (it will not push again)."; exit 1; }
    old=($(dispatch_ids $WORK/runs.json))
    if (( $#old )); then
      print -r -- "dispatch: a workflow_dispatch run of $GCOMMIT exists (${old[*]}); P does not dispatch again and observes the newest"
      row=$(wc_ runs $WORK/runs.json $WORKFLOW workflow_dispatch | grep '^RUN' | head -1)
    else
      print -r -- "dispatch: \$ gh workflow run windows.yml --repo $REPO --ref $GBRANCH"
      ghc workflow run windows.yml --repo $REPO --ref $GBRANCH 2>&1 | sed 's/^/  /'; (( ${pipestatus[1]} == 0 )) || { print "STOP: the dispatch failed (above). The branch is pushed; rerun P."; exit 1; }
      start=$SECONDS row=
      while true; do
        sleep $POLL_S
        api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" && row=$(wc_ newrun $WORK/runs.json $WORKFLOW workflow_dispatch $old | grep '^RUN' | head -1)
        [[ -n $row ]] && break
        (( SECONDS - start >= APPEAR_S )) && { print -r -- "VERDICT 653 P: FAIL (the dispatched $WORKFLOW run of $GCOMMIT did not appear within ${APPEAR_S}s)"; exit 1; }
      done
    fi
    f=("${(@ps:\t:)row}"); print -r -- "run ${f[3]}: ${f[7]} | ${f[6]}"
    wait_run ${f[3]} P
  } 2>&1 | tee $R/P.txt
  win_after P || exit 1 ;;

W) print "[W] Main. Observe only (no push, no dispatch, no re-run): 'W <run-id>' that run; 'W' the newest workflow_dispatch run of $GCOMMIT. Waits and judges as P. Login: gh's stored login. Network: GitHub. Dialog: none."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/adopt653-W.XXXXXX); trap 'rm -rf $WORK' EXIT
    rid=${IDS[1]:-}
    if [[ -z $rid ]]; then
      api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" || exit 1
      row=$(wc_ runs $WORK/runs.json $WORKFLOW workflow_dispatch | grep '^RUN' | head -1); f=("${(@ps:\t:)row}"); rid=${f[3]:-}
      [[ -n $rid ]] || { print -r -- "VERDICT 653 W: FAIL (no workflow_dispatch run of $GCOMMIT: run P)"; exit 1; }
    fi
    [[ $rid =~ '^[0-9]+$' ]] || { print -r -- "VERDICT 653 W: FAIL (not a run id: $rid)"; exit 1; }
    wait_run $rid W
  } 2>&1 | tee $R/W.txt
  win_after W || exit 1 ;;

X) print "[X] Main. OUTWARD-FACING (the user's long-term authority $WINDECISION): 'X <run-id>' re-runs the FAILED jobs of one completed windows.yml run of $GCOMMIT (gh run rerun --failed), for a transient runner or download fault only, never for a test result. Waits for the new attempt and judges it as P. Login: gh's stored login. Network: GitHub. Dialog: none."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/adopt653-X.XXXXXX); trap 'rm -rf $WORK' EXIT
    rid=${IDS[1]:-}; [[ $rid =~ '^[0-9]+$' ]] || { print -r -- "usage: zsh $THIS X <run-id>"; exit 2; }
    api $WORK/run.json repos/$REPO/actions/runs/$rid || exit 1
    a0=$(wc_ get $WORK/run.json run_attempt) st=$(wc_ get $WORK/run.json status) sh=$(wc_ get $WORK/run.json head_sha) cn=$(wc_ get $WORK/run.json conclusion)
    [[ $st == completed && $cn != success && $sh == $GCOMMIT ]] || { print -r -- "STOP: run $rid is $st/$cn on $sh; X re-runs only a completed, failed run of $GCOMMIT. Nothing re-run."; exit 1; }
    print -r -- "\$ gh run rerun $rid --failed --repo $REPO   (attempt $a0 -> $((a0 + 1)))"
    ghc run rerun $rid --failed --repo $REPO 2>&1 | sed 's/^/  /'; (( ${pipestatus[1]} == 0 )) || { print "STOP: the re-run was refused (above)."; exit 1; }
    start=$SECONDS
    while true; do
      sleep $POLL_S
      api $WORK/run.json repos/$REPO/actions/runs/$rid && [[ $(wc_ get $WORK/run.json run_attempt) -gt $a0 ]] && break
      (( SECONDS - start >= APPEAR_S )) && { print -r -- "VERDICT 653 X: FAIL (attempt $((a0 + 1)) of run $rid did not appear within ${APPEAR_S}s)"; exit 1; }
    done
    wait_run $rid X
  } 2>&1 | tee $R/X.txt
  win_after X || exit 1 ;;

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
    [[ $tm == *Windows* && $tm == *compatible* && $tm == *2026-11-28* ]]; ck $? "rel $GTAG message names Windows, compatible and the user's decision of 2026-11-28"
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
    [[ $gm == $GMAIN0 || $gm == $GCOMMIT ]] || { print -r -- "STOP: graftling main is $gm, no longer $GMAIN0 ($GOLDTAG). Nothing changed. Main tells the Leader."; exit 1; }
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]] || { print -r -- "STOP: dev must be checked out in $GDEV and main in $G (found ${dw:-none} and ${mw:-none}). Nothing changed."; exit 1; }
    for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || { print -r -- "STOP: the worktree $w is not clean (git status --porcelain). Nothing changed."; exit 1; }; done
    say "bundle (sha256 $(shasum -a 256 $BUNDLE | cut -c1-16)...): verify, fetch $GBRANCH, check it is $GCOMMIT on $GBASE"
    [[ $(shasum -a 256 $BUNDLE | cut -d' ' -f1) == $BSHA ]] || { print "STOP: the bundle's sha256 is not $BSHA. Nothing changed."; exit 1; }
    gg -C $G bundle verify -q $BUNDLE > /dev/null || { print "STOP: the bundle does not verify against $G. Nothing changed."; exit 1; }
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH)
    [[ -z $lb || $lb == $GCOMMIT ]] || { print -r -- "STOP: local $GBRANCH is $lb, not $GCOMMIT. Nothing changed."; exit 1; }
    [[ -n $lb ]] || gg -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" || { print "STOP: fetching $GBRANCH from the bundle failed. Nothing else changed."; exit 1; }
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
  print "Success: every 'CHECK 653 rel ...: PASS' (or 'already released')."
  next "zsh $THIS B" ;;

B) print "[B] Main, before the push. Builds both wheels with $CONDA (--no-index --no-deps --no-build-isolation): graftling from git archive $GTAG -> $NG; graphtraj from git archive TARGET ${TARGET[1,8]} -> $NT. No network, no login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}")
    [[ $gt == $GCOMMIT ]] || { print -r -- "STOP: $GTAG^{commit} is ${gt:-absent}, not $GCOMMIT: run rel first."; exit 1; }
    product_guard || { print "STOP: product guard (above)"; exit 1; }
    rm -rf $GSRC $TSRC $WHL $SCR/wheelview $SCR/twheelview; mkdir -p $GSRC $TSRC $WHL/g $WHL/t $SCR/wheelview $SCR/twheelview || exit 1
    sv=$(clean $CONDA -I -c 'import setuptools, pip; print("setuptools", setuptools.__version__, "| pip", pip.__version__)' 2>&1); ck $? "B setuptools importable offline in $CONDA" "$sv"
    say "graftling: git archive $GTAG ($GCOMMIT) -> $GSRC"
    gg -C $G archive $GTAG | tar -x -C $GSRC || exit 1
    vbad=0; for vf in src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $GSRC/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B archive version strings (__init__.py and the 3 json) all $GVERSION"
    hd=$(grep -m1 '^## ' $GSRC/CHANGELOG.md); print -r -- "CHANGELOG first heading: $hd"
    [[ $hd == $GHEADING ]] && ! grep -q '^## Unreleased' $GSRC/CHANGELOG.md; ck $? "B CHANGELOG heading '$GHEADING' and no '## Unreleased'"
    grep -q '^- 0.11.0 is compatible and raises the minor version by the user' $GSRC/PUBLIC_API.md; ck $? "B PUBLIC_API records the 0.11.0 classification"
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL/g $GSRC) || { print "STOP: the graftling wheel build failed"; exit 1; }
    whl=($WHL/g/graftling-$GVERSION-*.whl(N)); all=($WHL/g/*.whl(N)); print -r -- "graftling wheel: ${all[*]:t}"
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
    clean $CONDA -I $S593/pkgdiff532.py graftling $whl archive:$GSRC/src "653 B graftling wheel equals git archive $GTAG" -
    ck $? "B the graftling wheel's files equal git archive $GTAG"
    marker653 "B graftling wheel" $SCR/wheelview/graftling
    leaked=$(unzip -Z1 $whl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "graftling wheel build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the graftling wheel"
    say "graphtraj: git archive $TARGET -> $TSRC"
    gg -C $WT archive $TARGET | tar -x -C $TSRC || exit 1
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL/t $TSRC) || { print "STOP: the graphtraj wheel build failed"; exit 1; }
    twhl=($WHL/t/graphtraj-$GTVERSION-*.whl(N)); all=($WHL/t/*.whl(N)); print -r -- "graphtraj wheel: ${all[*]:t}"
    (( $#twhl == 1 && $#all == 1 )) || { print "STOP: expected exactly one graphtraj-$GTVERSION wheel"; exit 1; }
    twhl=$twhl[1]; old=($W616/graphtraj-$GTVERSION-*.whl(N)); (cd $SCR/twheelview && unzip -qo $twhl) || exit 1
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $twhl archive:$TSRC/src "653 B graphtraj wheel equals git archive ${TARGET[1,8]}" -
    ck $? "B the graphtraj wheel's graphtraj/ files equal git archive ${TARGET[1,8]}"
    dsk=$(unzip -Z1 $twhl | grep -cE '(^|/)desktop/|\.tsx$|\.css$'); print -r -- "graphtraj wheel entries from desktop/ (.tsx, .css): $dsk"
    [[ $dsk == 0 ]]; ck $? "B the graphtraj wheel ships nothing from desktop/src (626/627 change only the desktop app, outside the wheel)"
    clean $CONDA -I -c 'import sys, tomllib, zipfile
from pathlib import Path
from packaging.requirements import Requirement
whl, src, old, new = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
spec = tomllib.load(open(src / "pyproject.toml", "rb"))["tool"]["setuptools"]["data-files"]
want = {f"{d}/{Path(f).name}": src / f for d, fs in spec.items() for f in fs}
z, zo = zipfile.ZipFile(whl), zipfile.ZipFile(old)
def data(zf):
    return {n.split(".data/data/", 1)[1]: n for n in zf.namelist() if ".data/data/" in n}
got, gold = data(z), data(zo)
bad = sorted(set(want) ^ set(got)) + sorted(k for k in set(want) & set(got) if z.read(got[k]) != want[k].read_bytes())
print(f"data files in the pyproject: {len(want)} | in the wheel: {len(got)} | differing or missing: {bad or 0}")
print("data files changed since production (616s wheels-4ef36426; information, 641/642: command-inputs.md):", sorted(k for k in got if k not in gold or z.read(got[k]) != zo.read(gold[k])))
def meta(zf, name):
    return [n for n in zf.namelist() if n.endswith(".dist-info/" + name)][0]
ep = z.read(meta(z, "entry_points.txt")) == zo.read(meta(zo, "entry_points.txt"))
rq = lambda zf: sorted(l.split(":", 1)[1].strip() for l in zf.read(meta(zf, "METADATA")).decode().splitlines() if l.startswith("Requires-Dist:"))
print("Requires-Dist:", rq(z), "| 616 wheel:", rq(zo))
g = [Requirement(r) for r in rq(z) if Requirement(r).name == "graftling"]
others = lambda zf: [r for r in rq(zf) if Requirement(r).name != "graftling"]
inc = len(g) == 1 and g[0].specifier.contains(new) and g[0].specifier.contains("0.10.2") and not g[0].specifier.contains("0.12.0")
print(f"CHECK 653 B graphtraj data files equal the archive manuals ({len(want)} files): {"PASS" if not bad and want else "FAIL"}")
print(f"CHECK 653 B graphtraj entry_points.txt identical to 616s wheels-4ef36426: {"PASS" if ep else "FAIL"}")
print(f"CHECK 653 B graphtraj Requires-Dist other than graftling identical to 616s wheels-4ef36426: {"PASS" if others(z) == others(zo) else "FAIL"}")
print(f"CHECK 653 B graphtraj requires graftling {g[0] if g else None}: includes {new} and 0.10.2, excludes 0.12.0: {"PASS" if inc else "FAIL"}")
' $twhl $TSRC ${old[1]:-$W616/missing.whl} $GVERSION 2>&1 || ck 1 "B graphtraj data files and metadata read"
    leaked=$(unzip -Z1 $twhl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "graphtraj wheel build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the graphtraj wheel"
    say "the wheels G, V and I install: $NG and $NT"
    rm -rf $NG $NT && mkdir -p $NG $NT && cp -p $whl $NG/ && cp -p $twhl $NT/ || exit 1
    (cd $NG && shasum -a 256 *.whl > SHA256SUMS) && print -r -- "$GTAG $GCOMMIT" > $NG/COMMIT || exit 1
    (cd $NT && shasum -a 256 *.whl > SHA256SUMS) && print -r -- $TARGET > $NT/COMMIT || exit 1
    (cd $NG && shasum -a 256 -c SHA256SUMS) && (cd $NT && shasum -a 256 -c SHA256SUMS); ck $? "B $NG and $NT hold the wheels with SHA256SUMS and COMMIT"
    print -r -- "wheel sha256: graftling $(cat $NG/SHA256SUMS) | graphtraj $(cat $NT/SHA256SUMS)"
  } 2>&1 | tee $R/B.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/B.txt || { print "\nB STOP (see above). Do not push. Hand $R/B.txt to the Team."; exit 1; }
  summary B "$(grep -E '^(CHECK|wheel|Requires-Dist|data files)' $R/B.txt)"
  print "Success: every 'CHECK 653 B ...: PASS'."
  next "zsh $THIS G    (Main starts it as a BACKGROUND command; it runs ~25-30 min and ends with its verdict. Meanwhile V may run: zsh $THIS V)" ;;

G) print "[G] Main STARTS THIS STEP IN THE BACKGROUND ITSELF (Runtime background command); the Runtime tells Main when it exits. Full GraphTraj suite of the adoption commit: this Worktree's HEAD (editable; = TARGET ${TARGET[1,8]} outside scripts/adopt-653/) + the $GTAG wheel from B, 6 parallel shards through scripts/run_test_shards.py with -rA; pytest temp under TMPDIR=${TMPDIR:-/tmp} (outside the Harness; checked below). Main's suite queue is serial: while another suite runs, G waits for it first. This process waits for the shards, then judges the record (GR) and exits; its LAST lines are the verdict (RESULT 653 G/GR), the counts, the test interpreter's graftling and the next command. Duration: ~25-30 min once the shards start, plus any wait. No login, no network. Dialog: none."
  { check_tmp || exit 1
    product_guard || { print "STOP: product guard (above)"; exit 1; }
    whl=($NG/graftling-$GVERSION-*.whl(N)); (( $#whl == 1 )) && (cd $NG && shasum -a 256 -c SHA256SUMS > /dev/null) || { print "STOP: no checked $GTAG wheel in $NG: run B first"; exit 1; }
    pscheck=$(other_suites) || { print -r -- "STOP: $pscheck (nothing was built or started)"; exit 1; }
    GV=${SCR:A}/gvenv-653 O=$AD/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-653-G-$(date +%Y%m%dT%H%M%S)
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
    extra=(${(Q)${(z)${ADOPT653_PYTEST_ARGS:-}}})
    (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" >> $O/run.txt
    : > $O/suite.txt
    cat $O/run.txt; print -r -- "record: $O"
    while true; do   # the serial queue: wait (in this process) while another suite runs
      busy=$(other_suites) || { print -r -- "$(date +%T) STOP: ps failed; G did not start" | tee -a $O/wait.txt; print "exit=ps-failed (G did not start)" >> $O/suite.txt; exit 1; }
      [[ -z $busy ]] && break
      print -r -- "$(date +%T) waiting for another suite: $(print -r -- $busy | awk '{print $1}' | tr '\n' ' ')" | tee -a $O/wait.txt; sleep ${ADOPT653_GWAIT:-60}
    done
    print -r -- "$(date +%T) started (6 shards; this step waits for them)" | tee -a $O/wait.txt
    (cd $WT && clean env TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra > $O/suite.txt 2>&1 < /dev/null)
    print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended (all shards ended: $(tail -1 $O/suite.txt))" | tee -a $O/wait.txt
    clean $CONDA -I $S593/fails593.py $O/failures.txt $O/suite.txt $O/shards/*(N.) > /dev/null
  } 2>&1 | tee $R/G.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nG STOP (see above). Hand $R/G.txt to the Team."; exit 1; }
  print "\n### G: the suite has ended; GR judges its record (the same checks as the GR step)"
  zsh $THIS GR; exit $? ;;

GR) print "[GR] G runs this at its end; Main may rerun it alone to re-judge an ended G record. Read only: G's record, totals, every FAILED/ERROR id and ABNORMAL shard, classed against 516's CURRENT definition ONLY (a shard 'timed out after' is NEW), and the graftling the test interpreter imported (it must be $GVERSION with 0.11.0's code). No login. Dialog: none."
  rm -f $R/GR.ok
  { rec=$(grec); print -r -- "G record: $rec"
    product_guard
    [[ -f $rec/run.txt && -f $rec/suite.txt ]] || { print "STOP: no G record: run G first"; exit 1; }
    grep -q '^exit=' $rec/suite.txt || { print -r -- "G has not finished ($rec/suite.txt has no exit= line; queue: $(tail -1 $rec/wait.txt 2>/dev/null)). Rerun GR later."; exit 1; }
    sed 's/^/  run.txt: /' $rec/run.txt
    cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $rec/run.txt | head -1) gl=$(grep -oE 'git archive [0-9a-f]{40}' $rec/run.txt | head -1 | awk '{print $3}')
    cdiff=$(gg -C $WT diff --name-only ${cand:-missing} $TARGET 2>&1 | grep -v '^scripts/adopt-653/')
    [[ -n $cand && -z $cdiff ]] && gg -C $WT merge-base --is-ancestor $TARGET $cand; ck $? "GR the record's candidate ${cand[1,8]} is the adoption commit ${TARGET[1,8]} (only scripts/adopt-653/ differs)" "${cdiff//$'\n'/ }"
    [[ $gl == $GCOMMIT ]] && grep -q "($GTAG, graftling-$GVERSION-" $rec/run.txt; ck $? "GR the record's graftling wheel is $GTAG ($GCOMMIT)" "${gl:-none}"
    tig=$(tig_of $rec) tigdir=$(sed -n 's/^test interpreter graftling: [^ ]* //p' $rec/run.txt | head -1)
    print -r -- "test interpreter graftling: ${tig:-NOT RECORDED} | dependencies line: $(grep -oE '\| graftling [^ ]+ \|' $rec/run.txt | head -1)"
    [[ $tig == $GVERSION ]] && grep -q "| graftling $GVERSION |" $rec/run.txt; ck $? "GR test interpreter imports graftling $GVERSION (graftling.__version__ and metadata)" "${tig:-none}"
    marker653 "GR test interpreter's graftling" ${tigdir:-$rec/no-graftling-dir}
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
  print -r -- "RESULT 653 G/GR: $verdict | ${$(sed -n 's/^totals: //p' $R/GR.txt | tail -1):-no totals (the record has not ended or is missing)} | known non-blocking ids: $kn | NEW ids: $nw | ABNORMAL shards: $ab | test interpreter graftling: ${tig:-not judged}" | tee -a $R/GR.txt
  [[ $verdict == PASS ]] && touch $R/GR.ok
  if [[ $verdict == PASS ]]; then
    win_passed && next "ADOPT653_PUSH_CONFIRMED=yes zsh $THIS rp" || next "zsh $THIS W    (rp also needs the Windows verdict; P/W/X has not passed yet)"
  else next "zsh $THIS SR    (NEW ids or an ABNORMAL shard: SR prints the suite-base command; a STOP line above: hand $R/GR.txt to the Team; do not push)"; exit 1; fi ;;

SR) print "[SR] Main, read only. The newest G record's FAILED/ERROR ids and ABNORMAL shards, classed against 516 only; prints the suite-base command for NEW ids. Dialog: none."
  rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no finished G record ($rec)"; exit 1; }
  { tail -6 $rec/suite.txt; sr_classify $rec; print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"; } 2>&1 | tee $R/SR.txt
  SR_IDS=(${(f)"$(<$rec/new-ids.txt)"}); SR_IDS=(${SR_IDS:#}); SR_NEW=0; grep -q '^SR verdict: PASS' $R/SR.txt || SR_NEW=1   # the block above ran in a subshell
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)SR_IDS}"; print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else next "none for suite-base (no NEW id). A NEW ABNORMAL shard: hand $rec/suite.txt and its shard log to the Team. Do not push."; fi
  exit $SR_NEW ;;

suite-base) print "[suite-base] Main, only for SR's NEW ids. Reruns them on base (this Worktree + graftling $GOLDVERSION from 625's wheel: production's graftling now) and on the candidate (G's venv: the same Worktree + $GTAG); clean environment, pytest temp under TMPDIR. Dialog: none."
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print "STOP: no id file"; exit 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; exit 2; }
  check_tmp || exit 1
  o=$(other_suites) || { print -r -- "STOP: $o"; exit 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; exit 1; }
  VB=${SCR:A}/sbvenv-$GOLDVERSION VC=${SCR:A}/gvenv-653 sp=$(site)
  [[ -x $VC/bin/python ]] || { print "STOP: no G venv $VC; run G first"; exit 1; }
  if [[ ! -f $VB/installed ]]; then
    rm -rf -- $VB && clean $CONDA -m venv --system-site-packages $VB || exit 1; D=($VB/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pipq=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
    clean $VB/bin/python -m pip install $pipq $W625/graftling-$GOLDVERSION-*.whl && clean $VB/bin/python -m pip install $pipq -e $WT > /dev/null || exit 1
    print -r -- "graftling $GOLDVERSION (625's wheel) + graphtraj (this Worktree, editable)" > $VB/installed
  fi
  O=$AD/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $O; print -l -- $ids > $O/ids.txt
  for side V in base $VB candidate $VC; do
    RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-653-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $WT with $V ($([[ $side == base ]] && cat $VB/installed || print "graftling $GTAG wheel")) | temp $RUNTMP | launch environment: HOME USER PATH TERM TMPDIR LANG only"
    (cd $WT && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $O/$side-collected.txt 2>&1)
    clean $CONDA -I $SUITEIDS present $O/$side-collected.txt $O/ids.txt > $O/$side-ids.txt 2> $O/$side-missing.txt
    run=(${(f)"$(<$O/$side-ids.txt)"})
    if (( $#run )); then (cd $WT && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $O/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $O/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $O/$side.txt | tail -1) ($O/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $O/ids.txt $O/base.txt $O/candidate.txt | tee $O/classification.txt; fails=${pipestatus[1]}
  print ""; print -r -- "RESULT 653 suite-base: $( (( fails == 0 )) && print 'PASS (no candidate-only failure)' || print 'FAIL (classification above)') | ids: $#ids | record: $O"
  print -r -- "next: hand $O/classification.txt to the Team; a candidate-only id is a regression of this release (no push, no adoption)."; exit $fails ;;

rp) print "[rp] Main. Outward-facing: push graftling dev, main and refs/tags/$GTAG to origin ($GURL), fast-forward only, atomic, no force. Only after rel, after the Windows workflow passed (P/W/X) and after G/GR PASSED. The user's release decision is the push decision (Worldline user-decision $DECISION). Network: github.com with the user's usual git credentials (osxkeychain); no other login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]] || { print -r -- "STOP: rel is not complete (dev $gd, main $gm, $GTAG ${gt:-absent}; need all $GCOMMIT). Nothing pushed."; exit 1; }
    win_passed || { print -r -- "STOP: the Windows workflow has not passed ($R/WIN.ok absent): run P (or W/X). Nothing pushed."; exit 1; }
    print -r -- "Windows: $(cat $R/WIN.txt)"
    gr_passed || { print -r -- "STOP: G/GR has not passed ($R/GR.ok absent or $R/GR.txt has no 'RESULT 653 G/GR: PASS'): the paired GraphTraj suite with the $GTAG wheel must pass before the push. Nothing pushed."; exit 1; }
    print -r -- "G/GR: $(grep '^RESULT 653 G/GR: ' $R/GR.txt | tail -1)"
    ou=$(gg -C $G remote get-url origin 2>&1); print -r -- "origin: $ou"
    [[ $ou == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL"; exit 1; }
    before=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main refs/tags/$GTAG 2>&1) || { print -r -- "STOP: ls-remote failed: ${before[1,200]}"; exit 1; }
    print -r -- "remote before: ${before//$'\n'/ | }"
    print -r -- "will push: dev $gd, main $gm, refs/tags/$GTAG ($(gg -C $G rev-parse refs/tags/$GTAG)) (fast-forward only, --atomic, no force)"
    [[ ${ADOPT653_PUSH_CONFIRMED:-} == yes ]] || { print -r -- "STOP: the push is outward-facing. It is the user's decision $DECISION; run: ADOPT653_PUSH_CONFIRMED=yes zsh $THIS rp"; exit 1; }
    gpush -C $G push --atomic origin refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/$GTAG || { print "STOP: the push was refused (atomic: nothing changed on the remote)"; exit 1; }
    now=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" 2>&1)
    print -r -- "remote now: ${now//$'\n'/ | }"
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT && $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "rp remote main == $GTAG^{} == $GCOMMIT"
    [[ $(remote_of $now refs/heads/dev) == $gd ]]; ck $? "rp remote dev == local dev ($gd)"
  } 2>&1 | tee $R/rp.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rp.txt || { print "\nrp STOP (see above). Hand $R/rp.txt to the Team."; exit 1; }
  summary rp "$(grep -E '^(Windows|G/GR|remote|CHECK)' $R/rp.txt)"
  print "Success: both 'CHECK 653 rp ...: PASS'. (GitHub now also runs windows.yml for the push of dev; information only.)"
  next "zsh $THIS gh" ;;

gh) print "[gh] Main. Read only: git ls-remote $GURL. Network: github.com. No login. Dialog: none."
  { now=$(gg ls-remote $GURL refs/heads/main refs/heads/dev refs/tags/$GTAG "refs/tags/$GTAG^{}" 2>&1) || { print -r -- "STOP: git ls-remote $GURL failed: ${now[1,200]}"; exit 1; }
    print -r -- "GitHub: ${now//$'\n'/ | }"
    rto=$(remote_of $now refs/tags/$GTAG) lto=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG)
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT ]]; ck $? "gh GitHub main = $GCOMMIT"
    [[ $(remote_of $now refs/heads/dev) == $GCOMMIT ]]; ck $? "gh GitHub dev = $GCOMMIT"
    [[ $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "gh GitHub $GTAG^{} = $GCOMMIT"
    [[ -n $rto && $rto != $GCOMMIT && $rto == $lto ]]; ck $? "gh GitHub $GTAG is the local annotated tag object" "remote ${rto:-absent}, local ${lto:-absent}"
  } 2>&1 | tee $R/gh.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/gh.txt || { print "\ngh STOP (see above). Hand $R/gh.txt to the Team."; exit 1; }
  summary gh "$(grep -E '^(GitHub|CHECK)' $R/gh.txt)"
  print "Success: four 'CHECK 653 gh ...: PASS'."
  next "zsh $THIS C5    (FOREGROUND)" ;;

C5) print "[C5] Main, as a FOREGROUND command (612's background run lost uv's network). The README's TAGLESS install command from GitHub, in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local, uv tool directory, dotfiles and conda are not touched. Network: github.com, PyPI, uv's Python download. No login. Dialog: none. ~2-3 min."
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
    print -r -- "REPORT 653 C5 base interpreter: $base ($class) | uv-managed Pythons: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    [[ $class == uv-managed ]]; ck $? "C5 tool environment base interpreter is uv-managed (under $UVT/python)" "$class"
    [[ $cid == $GCOMMIT ]]; ck $? "C5 installed commit (direct_url commit_id) is the release commit $GCOMMIT (GitHub main)" "$cid"
    bd=$(cd $UVT && clean $UVENV $U tool dir --bin 2>&1); print -r -- "uv tool dir --bin: $bd"
    hl=$(cd $UVT && clean "$bd/subagents" --help 2>&1); hrc=$?
    print -r -- "subagents --help (rc $hrc): ${${(f)hl}[1]:-}"; ck $hrc "C5 $UVT/bin/subagents --help rc 0"
    [[ -x $UVT/bin/subagents-mcp ]]; ck $? "C5 $UVT/bin/subagents-mcp exists" "$(head -1 $UVT/bin/subagents-mcp 2>/dev/null)"
    gpd=$(cd $UVT && clean $py -I -c 'import os, graftling; print(os.path.dirname(graftling.__file__))' 2>&1)
    marker653 "C5 installed" $gpd
    say "after: USER directories and conda"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT653_NOSNAP, rehearsal only)"
    else
      snap $R/C5-home-after.json > /dev/null
      clean $CONDA -I $S593/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json; ck $? "C5 USER directories (~/.local, uv tools, ~/.pi, ~/.dsh, ~/.codex) and conda unchanged"
    fi
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/C5.txt || { print "\nC5 STOP (see above). Hand $R/C5.txt to the Team."; exit 1; }
  summary C5 "$(grep -E '^(uv|command|uv tool install|tool python|subagents --help|CHECK|REPORT)' $R/C5.txt)"
  print "Success: every 'CHECK 653 C5 ...: PASS' (rc 0; version $GVERSION; commit $GCOMMIT; subagents --help rc 0; subagents-mcp; USER directories and conda unchanged)."
  next "zsh $THIS V    (if V already passed: zsh $THIS Mpre)" ;;

V) print "[V] Main. Before the install, outside production: a scratch venv ($VV) with BOTH new wheels + production's click, yaml and websockets; the hook copy regenerated by the product into a scratch copy, which must differ from production's EXACTLY by graftling's v0.10.2..v0.11.0 host_context.mjs change; the product's prediction of the 3 entry files (must be unchanged); the real MCP entries in an isolated project ($VPROJ). No login. Dialog: none. ~1 min."
  { rm -f $R/V.ok
    [[ $(<$NG/COMMIT) == "$GTAG $GCOMMIT" && $(<$NT/COMMIT) == $TARGET ]] && (cd $NG && shasum -a 256 -c SHA256SUMS) && (cd $NT && shasum -a 256 -c SHA256SUMS) \
      || { print "STOP: no checked wheels in $NG and $NT: run B first"; exit 1; }
    product_guard; ck $? "V product guard"
    print -r -- "graftling $GOLDTAG..$GTAG in the files the hook copy is written from (information; expected: host_context.mjs only): $(gg -C $G diff --name-only $GOLDTAG $GTAG -- src/graftling/claude/plugin.py src/graftling/claude/host_context.mjs 2>/dev/null | tr '\n' ' ')"
    print -r -- "graphtraj ${OLDT[1,8]}..${TARGET[1,8]} under src/graphtraj/runtimes/claude and plugins (information; expected none): $(gg -C $WT diff --name-only $OLDT $TARGET -- src/graphtraj/runtimes/claude plugins 2>/dev/null | tr '\n' ' ')"
    gt=($NT/graphtraj-$GTVERSION-*.whl(N)) gw=($NG/graftling-$GVERSION-*.whl(N))
    rm -rf $VV; clean $CONDA -m venv $VV || exit 1
    clean $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gt[1] $gw[1] || exit 1
    sp=$(site) D=($VV/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pc=$(clean $VV/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "V scratch venv pip check (graphtraj's range accepts $GVERSION)" "${pc[1,120]}"
    clean $VV/bin/python -I $S593/onegraft.py $VV $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "V one graftling $GVERSION from the wheel in the scratch venv (onegraft.py)"
    marker653 "V scratch venv" $D[1]/graftling
    [[ -x $VV/bin/subagents && -x $VV/bin/subagents-mcp && -x $VV/bin/graphtraj-mcp ]]; ck $? "V scratch venv bin has subagents, subagents-mcp, graphtraj-mcp"
    say "the hook copy: regenerated by the product (adopt_plugin.py regen: adoption_material + write_adoption) into a scratch copy of production's"
    rm -rf $VPL; mkdir -p $VPL; cp -Rp $PDIR $VPL/ || exit 1
    clean $VV/bin/python -I $S593/adopt_plugin.py regen $H $(claude_bin) $VP || { ck 1 "V regenerate the hook copy"; exit 1; }
    templates || { ck 1 "V read host_context.mjs at $GOLDTAG and $GTAG from $G"; exit 1; }
    diff -r $PDIR $VP > $R/V-plugin.diff 2>&1
    print -r -- "diff -r production copy vs regenerated: $(wc -l < $R/V-plugin.diff | tr -d ' ') lines ($R/V-plugin.diff)"
    plugin_check $PDIR $VP; prc=$?
    ck $prc "V the regenerated hook copy differs from production's EXACTLY by graftling's $GOLDTAG..$GTAG host_context.mjs change (plugin.json and hooks.json byte-identical; plugin653.py above)" \
      "$( (( prc )) && print "STOP: hand $R/V-plugin.diff to the Leader; do not install")"
    grep -q '^const SERVER = "graphtraj";' $VP/hooks/host_context.mjs && grep -q '^const TOOL = "subagents";' $VP/hooks/host_context.mjs \
      && grep -q '^const TOOLS = \[TOOL, "tasks"\];' $VP/hooks/host_context.mjs && grep -q '^const PLUGIN = null;' $VP/hooks/host_context.mjs
    ck $? "V the regenerated host_context.mjs names SERVER graphtraj, TOOL subagents, TOOLS [TOOL, \"tasks\"] and PLUGIN null (the marketplace-only Windows refusal stays inert here)"
    (( prc == 0 )) && print "plugin dialog expected at claude --continue: yes (one: the plugin/hooks trust dialog for graphtraj-claude-host, because hooks/host_context.mjs changes; the USER chooses trust)" > $R/V-dialog.txt
    say "the 3 entry files: the product's prediction of configuration --write (adopt_plugin.py entries; writes nothing in $H)"
    rm -rf $AD/ventries; clean $VV/bin/python -I $S593/adopt_plugin.py entries $H $(claude_bin) $RT/bin/python $AD/ventries | tee $R/V-entries.txt; erc=${pipestatus[1]}
    (( erc == 0 )) && [[ $(grep -c '^SAME    ' $R/V-entries.txt) == 3 && $(grep -c '^CHANGES ' $R/V-entries.txt) == 0 ]]
    ck $? "V configuration --write keeps .mcp.json, settings.local.json and config.json unchanged (3 SAME)"
    say "real entries of the scratch venv in the isolated project $VPROJ"
    vproject_init $VV/bin/graphtraj; ck $? "V isolated project $VPROJ (own git, graphtraj setup)"
    mcp_probe V-scratch $VV
    codex_hook_check $VV
    mkdir -p $AD && shasum -a 256 $ENTRIES | tee $AD/entries.sha256
  } 2>&1 | tee $R/V.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/V.txt || { print "\nV STOP (see above). Nothing in production changed. Hand $R/V.txt to the Team."; exit 1; }
  touch $R/V.ok
  summary V "$(grep -E '^(CHECK|diff -r|product guard|SAME|CHANGED|RESULT plugin653|plugin dialog)' $R/V.txt $R/V-dialog.txt | sed 's/^[^:]*://')"
  print "Success: every 'CHECK 653 V ...: PASS' (both wheels; the hook copy changes exactly as predicted; entries unchanged; tools/list subagents and tasks)."
  next "zsh $THIS Mpre    (after P/W, G/GR, rp, gh and C5 have passed)" ;;

I0) need_main; print "[I0] Main, before Mpre and a rerun of I. Read only, apart from two MOVES (nothing is deleted): when the backup $BK belongs to an I whose install began and R rolled it back, and production equals that backup, it moves $BK to $SCR/backup-run<N>-<time> and that run's I/R records into $R/run<N>/. Otherwise STOP, changing nothing. Other backups under $H/tmp are not touched. No login. Dialog: none."
  { if [[ ! -e $BK ]]; then print -r -- "no backup $BK: nothing to set aside; I may run (it still STOPs when a backup exists)"; exit 0; fi
    nrun=1; while [[ -e $R/run$nrun || -n $(print -l $SCR/backup-run$nrun-*(N)) ]]; do nrun=$(( nrun + 1 )); done
    print -r -- "the failed run being set aside: run$nrun | backup $BK (I start $(sed -n 's/^I start //p' $R/I.txt 2>/dev/null | tail -1))"
    [[ -e $BK/COMPLETE && -e $BK/INSTALL-STARTED ]]; ck $? "I0 $BK has COMPLETE and INSTALL-STARTED (an I whose install began)"
    nr=$(grep -c '^CHECK 653 R ' $R/R.txt 2>/dev/null) nf=$(grep -c '^CHECK 653 R .*: FAIL' $R/R.txt 2>/dev/null)
    [[ -s $R/R.txt && ${nr:-0} -ge 5 && ${nf:-0} == 0 ]]; ck $? "I0 R's record $R/R.txt exists and every CHECK in it passed" "${nr:-0} CHECK lines, ${nf:-0} FAIL"
    say "production equals that backup, in R's terms"
    tree compare $BK/venv.manifest $RT > $SCR/I0-venv-compare.txt 2>&1; vrc=$?; tail -2 $SCR/I0-venv-compare.txt
    ck $vrc "I0 production venv equals the backup (adopt_tree.py compare, as R)"
    tree compare $BK/plugin.manifest $PDIR > /dev/null 2>&1; ck $? "I0 hook copy equals the backup"
    shasum -a 256 -c $BK/entries.sha256 > /dev/null 2>&1; ck $? "I0 .mcp.json, settings.local.json and config.json equal the backup"
    direct_urls $GOLDVERSION; [[ $DGT == *"$W616/graphtraj-$GTVERSION-"* && $DGL == *"$W625/graftling-$GOLDVERSION-"* ]]; ck $? "I0 graphtraj from 616's wheels-${OLDT[1,8]} and graftling $GOLDVERSION from 625's wheel"
    pc=$(clean $RT/bin/python -B -m pip check --disable-pip-version-check 2>&1); ck $? "I0 production pip check" "${pc[1,120]}"
  } 2>&1 | tee $R/I0.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || exit $rc
  [[ -e $BK ]] || { next "zsh $THIS Mpre"; exit 0; }
  grep -q '^CHECK 653 I0 .*: FAIL' $R/I0.txt && { print "\nI0 STOP (see above). Nothing was moved. Hand $R/I0.txt to the Team."; exit 1; }
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
  (( rc == 0 )) && ! grep -q '^CHECK 653 I0 .*: FAIL' $R/I0.txt || { print "\nI0 STOP (see above). Hand $R/I0.txt to the Team."; exit 1; }
  print "Success: every 'CHECK 653 I0 ...: PASS'. I may run again (Mpre right before it)."
  next "zsh $THIS Mpre" ;;

Mpre) need_main; print "[Mpre] Main, right before the USER exits Main (P/W, G/GR, V, rp, gh and C5 passed). Adoption only with no member running: 653's Leader and Engineer have ended their turns and no other member runs; else STOP (never signals). No login. Dialog: none."
  { win_passed; ck $? "Mpre the Windows workflow passed ($(cat $R/WIN.txt 2>/dev/null | cut -c1-160))"
    gr_passed; ck $? "Mpre G/GR passed ($(grep '^RESULT 653 G/GR: ' $R/GR.txt 2>/dev/null | tail -1))"
    [[ -e $R/V.ok ]]; ck $? "Mpre V passed"
    for s in rp gh C5; do passed $s; ck $? "Mpre $s passed"; done
    members_idle Mpre; ck $? "Mpre no member Worker or swarm batch runs"
  } 2>&1 | tee $R/Mpre.txt
  grep -q ': FAIL' $R/Mpre.txt && { print "\nMpre STOP (see above). A step not passed: run it first. A member running: wait for it to end (never kill it), then rerun Mpre."; exit 1; }
  print "\nWhy Main exits: Main's subagents/tasks calls run in its host process, which keeps the graftling and graphtraj modules it loaded; I replaces both. So Main exits before I and resumes after it."
  print "Main tells the USER, then the USER /exits Main and runs I in a Terminal:"
  next "(USER, normal Terminal, after /exit in Main) zsh $THIS I" ;;

I) need_main
  print "[I] USER (Main tells the USER first; the USER /exits Main, then runs this in a normal Terminal). Waits for members, backs up to $BK, installs BOTH wheels into $RT in ONE pip --force-reinstall --no-deps --no-index call (graphtraj ${OLDT[1,8]} -> ${TARGET[1,8]}, graftling $GOLDVERSION -> $GVERSION), regenerates the hook copy through the product (configuration --write), checks everything. No login. Dialog: none (one Enter to confirm). ~3 min plus waiting."
  [[ -e $BK ]] && { print "STOP: $BK exists; I never overwrites a backup. Tell Main. (After a failed I that R rolled back, Main runs: zsh $THIS I0)"; exit 1; }
  [[ -e $R/V.ok ]] && gr_passed && win_passed || { print "STOP: V, G/GR or the Windows workflow has not passed. Nothing changed."; exit 1; }
  product_guard || { print "STOP: product guard. Nothing changed."; exit 1; }
  print "Confirm that you typed /exit in the Claude Code Main. Enter to continue, Ctrl-C to stop."; read -r answer
  { members_idle I || { print "STOP: a member or host still runs (above). Nothing changed; wait, then rerun I (never kill them)."; exit 1; }
    date '+I start %F %T'
    oldbk_report I > $SCR/oldbk-I-before.txt; print "other backups before the install (never written):"; cat $SCR/oldbk-I-before.txt
    say "backup: venv (manifest + cp -Rp), hook copy, entry files (mode 600), the tools R needs; COMPLETE marker"
    mkdir -p $BK/tools $BK/entries && chmod 700 $BK || exit 1
    cp -p $THIS $S593/adopt_tree.py $S593/pkgdiff532.py $BK/tools/ && print -r -- $H > $BK/tools/HARNESS && print -r -- $WT > $BK/tools/WORKTREE \
      && print -r -- $MAIN > $BK/tools/main.session && cp -p $SCR/main.session $BK/main.session || exit 1
    tree manifest $RT $BK/venv.manifest && cp -Rp $RT $BK/venv && tree compare $BK/venv.manifest $BK/venv || { print "STOP: venv backup failed; production unchanged"; exit 1; }
    tree manifest $PDIR $BK/plugin.manifest && cp -Rp $PDIR $BK/plugin || exit 1
    for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || exit 1; done; chmod 600 $BK/entries/*(D) || exit 1
    shasum -a 256 $ENTRIES > $BK/entries.sha256; touch $BK/COMPLETE; print "backup COMPLETE: $BK"
    shasum -a 256 -c $AD/entries.sha256 > /dev/null; ck $? "I entry files unchanged since V"
    members_idle I-before-pip || { print "STOP: a member started; backup done, production unchanged. Main runs I0 before a rerun."; exit 1; }
    touch $BK/INSTALL-STARTED; date +%s > $R/I-install-start.epoch
    gt=($NT/graphtraj-$GTVERSION-*.whl(N)) gw=($NG/graftling-$GVERSION-*.whl(N)); (cd $NT && shasum -a 256 -c SHA256SUMS) && (cd $NG && shasum -a 256 -c SHA256SUMS) || exit 1
    say "ONE pip install --force-reinstall --no-deps --no-index ${gt:t} ${gw:t}"
    clean $RT/bin/python -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall --no-deps --no-index $gt[1] $gw[1]; ck $? "I one pip install of both wheels (graphtraj ${TARGET[1,8]}, graftling $GTAG)"
    date +%s > $R/I-install-end.epoch
    sp=$(site)
    direct_urls $GVERSION
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"*.whl* ]]; ck $? "I graphtraj direct_url is wheels-${TARGET[1,8]}"
    [[ $DGL == *"$NG/graftling-$GVERSION-"*.whl* ]]; ck $? "I graftling direct_url is wheels-$GVERSION"
    (( $(print -l $sp/graftling-$GOLDVERSION.dist-info(N) | grep -c .) == 0 )); ck $? "I graftling $GOLDVERSION dist-info gone"
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $gt[1] $sp "653 I installed graphtraj equals the ${TARGET[1,8]} wheel" - | tail -1; ck ${pipestatus[1]} "I installed graphtraj files equal the wheel"
    clean $CONDA -I $S593/pkgdiff532.py graftling $gw[1] $sp "653 I installed graftling equals the $GTAG wheel" - | tail -1; ck ${pipestatus[1]} "I installed graftling files equal the wheel"
    [[ -d $TSRC/manuals ]] || { mkdir -p $TSRC && gg -C $WT archive $TARGET | tar -x -C $TSRC; }   # B's archive of TARGET
    manuals_check I $RT/share/graphtraj/manuals
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "I production pip check" "${pc[1,120]}"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && -x $RT/bin/graphtraj-mcp && $(head -1 $RT/bin/subagents) == "#!$RT/bin/python"* && $(head -1 $RT/bin/graphtraj-mcp) == "#!$RT/bin/python"* ]]
    ck $? "I production bin subagents, subagents-mcp, graphtraj-mcp (this venv's python)"
    clean $RT/bin/python -I $S593/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "I one graftling $GVERSION in production (onegraft.py)"
    pv=$(prod_versions); print -r -- "production graphtraj graftling: $pv"; [[ $pv == "$GTVERSION $GVERSION" ]]; ck $? "I production reports graphtraj $GTVERSION and graftling $GVERSION"
    marker653 "I production" $sp/graftling
    say "the hook copy: regenerated ONLY through the product (configuration --write from the installed code; never edited by hand)"
    (cd $H && clean $RT/bin/python -m graphtraj.runtimes.claude.host configuration --write --project $H --claude $(claude_bin)) > $R/I-configuration.txt 2>&1
    crc=$?; print -r -- "configuration --write rc=$crc (output: $R/I-configuration.txt)"; ck $crc "I configuration --write rc 0"
    diff -r $VP $PDIR > $R/I-plugin-vs-V.diff 2>&1; ck $? "I the hook copy equals V's validated regeneration ($VP)"
    plugin_check $BK/plugin $PDIR; ck $? "I the hook copy changed from the backup EXACTLY by graftling's $GOLDTAG..$GTAG host_context.mjs change (plugin653.py above; at claude --continue the plugin/hooks trust dialog: trust)"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__}; ck $? "I ${f#$H/} byte-identical to the backup (V predicted SAME)"; done
    say "real entries of production (run in the isolated $VPROJ)"
    mcp_probe I-production $RT
    codex_hook_check $RT
    guard > /dev/null; ck $? "I no process started on $RT during the install"
    oldbk_report I > $SCR/oldbk-I-after.txt; print "other backups after the install:"; cat $SCR/oldbk-I-after.txt
    cmp -s $SCR/oldbk-I-before.txt $SCR/oldbk-I-after.txt; ck $? "I other backups under $H/tmp untouched: same presence, COMPLETE, mtime and entry count before and after"
  } 2>&1 | tee -a $R/I.txt; rc=${pipestatus[1]}
  if (( rc != 0 )) || grep -q '^CHECK 653 I .*: FAIL' $R/I.txt; then
    [[ -e $BK/INSTALL-STARTED ]] && print "\nI FAILED after the install began. Do not resume Main. Run the rollback now:\n  zsh $BK/tools/steps.zsh R" || print "\nI STOP before the install (production unchanged). Tell Main."
    exit 1
  fi
  touch $R/I.ok
  summary I "$(grep -E '^(I start|backup COMPLETE|graphtraj direct_url|graftling .*direct_url|CHECK|INFO|configuration)' $R/I.txt)"
  print "Success: every 'CHECK 653 I ...: PASS'. Rollback, if ever needed (Main asks the USER first): zsh $BK/tools/steps.zsh R"
  print "\nNext (USER, normal Terminal): resume Main (same Session):\n  cd $H && claude --continue"
  print "Expected dialog: ONE, the plugin/hooks trust dialog for graphtraj-claude-host (its hooks/host_context.mjs changed): choose trust. Any OTHER dialog: Esc and tell Main its title. If --continue opens another conversation: /exit, then cd $H && claude --resume $MAIN"
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
  print "Success: 'CHECK 653 Mr ...: PASS'."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. One real dispatch: an advisor member on Task $TASK_ID creates the Claude child $CHILD (model $MODEL) through mcp__graphtraj__subagents WITHOUT tools; the child runs Bash and replies $DONEWORD; the member waits, reads and retires it. Login: $LOGIN_NOTE; Main does not ask again. Dialog: none expected (a tool permission dialog: 'Yes' once and tell the Team). 653's Leader and Engineer have ended their turns. ~3-5 min. Paste in the Claude Main (arguments INLINE, never arguments_file):
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
    else print "CHECK 653 Nr Main got exactly one completed notice of the member: PENDING (save it to $R/N-main-notice.txt)"; fi
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

R) need_main; print "[R] USER (Main asks the USER first; after agreeing the USER /exits Main and runs this in a normal Terminal). Restores the whole venv (graphtraj ${OLDT[1,8]} from 616's wheel + graftling $GOLDVERSION from 625's wheel), the hook copy and the entry files from $BK; the current ones are kept in $BK/after-install-*. No login. Dialog: none at R (one Enter); at the next claude --continue the plugin/hooks trust dialog may show again (the restored host_context.mjs): trust. Enter to continue, Ctrl-C to stop."; read -r answer
  [[ -e $BK/COMPLETE ]] || { print "STOP: no complete backup in $BK (the install starts only after it): production was not changed by I. Tell Main."; exit 1; }
  { members_idle R || { print "STOP: a member or host runs (above). Nothing restored."; exit 1; }
    KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S); mkdir -p $KEEP/entries
    mv $RT $KEEP/venv && cp -Rp $BK/venv $RT || exit 1
    tree compare $BK/venv.manifest $RT; ck $? "R venv equals the pre-install bytes"
    [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; cp -Rp $BK/plugin $PDIR || exit 1
    tree compare $BK/plugin.manifest $PDIR; ck $? "R hook copy restored"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__} || { cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $BK/entries/${${f#$H/}//\//__} $f; }; done
    shasum -a 256 -c $BK/entries.sha256; ck $? "R entry files restored"
    direct_urls $GOLDVERSION
    [[ $DGT == *"$T616/adoption/wheels-${OLDT[1,8]}/graphtraj-$GTVERSION-"* && $DGT == *$TOLDSHA* ]]; ck $? "R graphtraj from 616's wheels-${OLDT[1,8]} again (sha256 ${TOLDSHA[1,16]}... in direct_url)"
    [[ $DGL == *"$T625/adoption/wheels-$GOLDVERSION/graftling-$GOLDVERSION-"* && $DGL == *$GOLDSHA* ]]; ck $? "R graftling $GOLDVERSION from 625's wheel again (sha256 ${GOLDSHA[1,16]}... in direct_url)"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "R pip check" "${pc[1,120]}"
    CH=$H/.graphtraj/claude-host/live/channel.json; [[ -e $CH ]] && mv $CH $KEEP/channel.json && print "moved out a stale $CH"
  } 2>&1 | tee -a $R/R.txt
  grep -q '^CHECK 653 R .*: FAIL' $R/R.txt && { print "\nR left a difference (above). Do not resume Main; hand $R/R.txt to Main. R can be rerun."; exit 1; }
  print "Success: every 'CHECK 653 R ...: PASS'. Then (USER): cd $H && claude --continue (the plugin/hooks trust dialog may show: trust; any other dialog: Esc, tell Main)" ;;

done) print "[done] Main. Read only: every CHECK line of every step's raw file, and production now. No login. Dialog: none."
  { miss=""
    steps=(00 WIN rel B GR rp gh C5 V Mpre I Mr Nr)
    runs=($R/run<->(N/))
    (( $#runs )) && steps+=(I0)   # a failed I was set aside: I0 must have passed
    for d in $runs; do   # set-aside runs are listed, never counted (only the current I and R records count)
      print -r -- "SUPERSEDED ${d:t}: $(cat $d/SUPERSEDED 2>/dev/null || print 'set aside by I0') | files: $(print -l $d/*(N:t) | tr '\n' ' ')| its CHECK FAIL lines (not counted): $(cat $d/*.txt(N) | grep -c '^CHECK .*: FAIL')"
    done
    for s in $steps; do [[ -s $R/$s.txt ]] || miss="$miss $s"; done
    grep -h '^CHECK ' $R/${^steps}.txt(N)
    grep -h '^REPORT 653 ' $R/C5.txt(N); grep -h '^RESULT 653 G/GR: ' $R/GR.txt(N) | tail -1
    np=$(cat $R/${^steps}.txt(N) | grep -c '^CHECK .*: PASS') nf=$(cat $R/${^steps}.txt(N) | grep -cE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)')
    say "production now"
    print -r -- "graphtraj graftling: $(prod_versions)"; direct_urls $GVERSION
    [[ $DGT == *"$NT/graphtraj-$GTVERSION-"* && $DGL == *"$NG/graftling-$GVERSION-"* ]]
    ck $? "done production graphtraj from wheels-${TARGET[1,8]}, graftling $GVERSION from wheels-$GVERSION"
    print -r -- "steps without a raw file:${miss:- none} | CHECK PASS $np | CHECK not passed $nf"
    [[ -z $miss && $nf == 0 ]]; ck $? "done every step ran and every CHECK passed"
  } 2>&1 | tee $R/done.txt
  grep -q '^CHECK 653 done every step ran and every CHECK passed: PASS' $R/done.txt && ! grep -qE '^CHECK .*: FAIL' $R/done.txt || { print "\ndone: FAIL (see above). Hand $R/done.txt to the Team."; exit 1; }
  print "Success: both 'CHECK 653 done ...: PASS' (production graphtraj ${TARGET[1,8]} + graftling $GVERSION; every step's CHECK passed)."
  next "Main: hand $R to the Team; Task 653 steps complete. The backup $BK stays until the user releases it. Rollback (Main asks the USER first): zsh $BK/tools/steps.zsh R" ;;

*) print "usage: zsh $THIS 00|P|W [run-id]|X <run-id>|rel|B|G|GR|SR|suite-base|rp|gh|C5|V|I0|Mpre|I|M|Mr|N|Nr|done|R"; exit 2 ;;
esac
