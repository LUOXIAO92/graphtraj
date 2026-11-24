#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 600 Main-run steps: release graftling 0.9.1 (compatible: 597's install command with uv's own managed Python,
# 599's PUBLIC_API note on Retired Agents). One commit e8c2e802 "graftling 0.9.1 (600)" on graftling dev 2b4a33ae, in
# graftling-0.9.1.bundle next to this file. User's release (and push) decision: Worldline user-decision
# 20261124T114043.053104+0900.
# Run one step at a time:  zsh <this file> <STEP>     ONE ordered list (release, then production adoption):
#   00 -> rel -> B -> G (background) -> rp -> gh -> C5 -> GR (after G; -> SR -> suite-base only if NEW) -> V -> Mpre
#   -> [Main tells the USER; 600's Leader and Engineer have ended their turns] USER /exit Main -> I (USER, Terminal)
#   -> USER `cd <Harness> && claude --continue` -> M -> Mr -> N -> Nr -> done.   Rollback: R (Main asks the USER first).
# Adoption: production .venv-runtime gets ONLY the graftling 0.9.1 wheel (graphtraj stays 593's 6fe8c8d9 wheel; this
# Worktree's product equals it). V regenerates the hook copy through the product into a scratch copy and requires it
# byte-identical (prediction: no regeneration, no trust dialog). G/GR/SR/suite-base, V, Mpre, I, M, Mr, N, Nr, R and
# done follow adopt-593 (README: what was trimmed and why). Login: the USER pre-approved their Claude login for 00's
# probe and N (Worldline user-decision 20261124T115605.289456+0900).
#   00    Main. Read only (creates <Harness>/tmp/600 and a scratch clone there to read the bundle). No host, no login:
#         Task 600 calls no Claude, Codex, Pi or DSH. Network: github.com (git ls-remote). Dialog: none.
#   rel   Main. graftling repository: fetch the bundle branch, fast-forward dev (graftling-dev Worktree) and main
#         (<Harness>/graftling) to the release commit, annotated tag v0.9.1 (noreply tagger). STOPs, changing nothing,
#         when dev is no longer 2b4a33ae or main no longer 7b5f4e6b. Idempotent. No network. Dialog: none.
#   B     Main, before the push. git archive v0.9.1 -> <Harness>/tmp/600/gsrc, wheel from the archive root (Miniconda
#         python3.13, --no-index --no-deps --no-build-isolation); version strings, CHANGELOG, console scripts, wheel ==
#         archive, content markers, GraphTraj's range. No network. Dialog: none.
#   rp    Main. Push dev, main and v0.9.1 to origin (GitHub), fast-forward only, atomic, no force. Needs
#         ADOPT600_PUSH_CONFIRMED=yes (the user's release decision is the push decision). Network: github.com (the
#         user's usual git credentials). Dialog: none.
#   gh    Main. Read only: GitHub main and v0.9.1 resolve to the release commit; the tag object is the local one.
#   C5    Main. README's command `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git@v0.9.1"`
#         with uv's tool, bin, cache and Python directories under /private/tmp/uvtool-600 only; version 0.9.1, uv-managed
#         base interpreter, installed commit, `subagents --help`. Network: github.com, PyPI, uv's Python download. No
#         login. Dialog: none. ~2-3 min.
#   done  Main. Read only: every CHECK line of the raw files; nonzero on any FAIL.
# Nothing here writes ~/.local, the USER's uv tool directory, dotfiles or conda; .venv-runtime is not touched.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer; Main leaves all of these unset): ADOPT600_G, ADOPT600_GDEV (scratch graftling clone and its
# dev worktree), ADOPT600_GURL (scratch bare repository standing in for GitHub), ADOPT600_OUT, ADOPT600_SCRATCH,
# ADOPT600_UVT, ADOPT600_NOSNAP=1 (a sandbox cannot read $HOME), ADOPT600_SOURCE (C5's source instead of GitHub; the
# sandbox proxy refuses git to GitHub), ADOPT600_CLEAN_EXTRA (the sandbox's proxy variables for clean()).
# No zsh special parameter name is used as a variable (593 correction 4).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
TASKDIR=600-graftling-0-9-1-release
TASK_ID=600
H=${ADOPT600_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}   # the Harness (production)
WT=${ADOPT600_WT:-$H/.graphtraj/core/worktrees/$TASKDIR}                           # this Task Worktree
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused by path: homesnap593.py, pkgdiff532.py, adopt_tree.py, ...
STEP=${1:-}
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
DECISION=20261124T114043.053104+0900                # the user's release decision = the push decision
LOGIN_DECISION=20261124T115605.289456+0900          # the USER pre-approved their Claude login for 600's steps (00, N)
path=($HOME/.local/bin /opt/homebrew/bin $path)     # claude and node, as 593 (the USER's usual installs)
[[ -n ${ADOPT600_STUB:-} ]] && path=($ADOPT600_STUB $path)   # rehearsal only: stub claude/codex first
G=${ADOPT600_G:-$H/graftling}                       # main is checked out here
GDEV=${ADOPT600_GDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # dev is checked out here
GURL=${ADOPT600_GURL:-https://github.com/LUOXIAO92/graftling.git}   # origin of $G (GitHub)
GBASE=2b4a33aef93dc45b953bd412e4d5dd61347c38ea      # graftling dev at dispatch (597 + 599)
GMAIN0=7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9     # graftling main = v0.9.0 (593)
GCOMMIT=e8c2e80241dff1151f2122e8957fca5598ec987b    # graftling 0.9.1 (600), parent $GBASE
GBRANCH=agent/600-graftling-0.9.1
BUNDLE=$SD/graftling-0.9.1.bundle
BSHA=b5c6d530ef5f3f5324438a4f3ba6d47d0ef8bee271e4b7f53f34f2f2fe66ee12
GFILES="CHANGELOG.md src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json"
GTAG=v0.9.1
GVERSION=0.9.1
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
RELMSG="graftling 0.9.1 (compatible): the install command lets uv use its own managed Python (uv tool install --managed-python, 597) and PUBLIC_API documents Retired Agents (599); no public name, result, archive format or behavior changes"
SRCURL="git+https://github.com/LUOXIAO92/graftling.git@$GTAG"
INSTALL=(uv tool install --managed-python $SRCURL)  # the README's command with <tag-or-commit> = v0.9.1
[[ -n ${ADOPT600_SOURCE:-} ]] && INSTALL=(uv tool install --managed-python $ADOPT600_SOURCE)   # rehearsal only
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; builds the wheel, runs the helpers with -I
CROOT=${CONDA:h:h}
SCR=${ADOPT600_SCRATCH:-$H/tmp/600}
GSRC=$SCR/gsrc                                      # git archive v0.9.1
WHL=$SCR/wheel
UVT=${ADOPT600_UVT:-/private/tmp/uvtool-600}
R=${ADOPT600_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost/main-raw}
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT600_NOSNAP:-}
# Production adoption (requirement 4). GraphTraj product unchanged: production graphtraj is 593's wheel of 6fe8c8d9 and
# this Worktree's src/tests/plugins/pyproject.toml equal 6fe8c8d9, so I installs ONLY the graftling 0.9.1 wheel.
RT=$H/.venv-runtime
TARGET=6fe8c8d97b5eedaf3fae898cd3f3f86a66a7acf7     # production graphtraj (593) = the GraphTraj product here
GUARDED=(src tests plugins pyproject.toml)
W593=$H/.graphtraj/core/state/tasks/593-graftling-0-9-0-release-and-production-adoption/adoption/wheels-${TARGET[1,8]}
AD=$H/.graphtraj/core/state/tasks/$TASKDIR/adoption   # wheels-0.9.1/ (B), G records, V copies
N=$AD/wheels-$GVERSION                              # the graftling 0.9.1 wheel G and I install
GOLDVERSION=0.9.0
BK=$SCR/backup
VV=$SCR/vvenv
VPROJ=${ADOPT600_VPROJECT:-/private/tmp/vproject-600}   # isolated project for the real MCP entries (graphtraj setup)
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
STATE=$H/.graphtraj/core/state
SESS=$H/.graphtraj/swarm/sessions
PROJECTS=${ADOPT600_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
MODEL=claude-opus-5-5
CHILD=n600
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$STATE/tasks/516-low-priority-flaky-tests      # known flaky tests: 516's CURRENT definition via its task.yml
KNOWN516=$D516/${${${(M)${(f)"$(cat $D516/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
MAIN=$(cat $SCR/main.session 2>/dev/null)

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT600_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean git "$@"; }                            # every git call: allowlist environment
ck() { [[ $1 == 0 ]] && print -r -- "CHECK 600 $2: PASS${3:+ ($3)}" || print -r -- "CHECK 600 $2: FAIL${3:+ ($3)}"; }   # $1 = 0 for pass
U=$(clean /usr/bin/which uv 2>/dev/null)            # the uv on the clean PATH; every uv call uses this one file
[[ -n $U ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
rel_wt() {  # the worktree that has branch $1 checked out in $G, if any
  gg -C $G worktree list --porcelain | awk -v b="branch refs/heads/$1" '/^worktree /{w=substr($0,10)} $0==b{print w}'
}
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT600_NOSNAP, rehearsal only)"; return 0; }
  clean $CONDA -I $S593/homesnap593.py snap $1 local=$HOME/.local uvtools=$(clean $U tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) \
    pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT
}
remote_of() {  # $1 = ls-remote output, $2 = ref
  print -r -- $1 | awk -v r="$2" '$2==r{print $1}'
}
# ---- adoption helpers (from adopt-593, adapted; helpers reused by path) ----
helper() { [[ -f $SD/$1 ]] && print -r -- $SD/$1 || print -r -- $S593/$1; }   # R runs from $BK/tools with its own copies
tree() { clean $CONDA -I $(helper adopt_tree.py) "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
cv() { local C=$(claude_bin); print -r -- "claude: $C -> ${C:A} | version: $(clean $C --version 2>&1 | head -1) | recorded at 00: $(cat $SCR/cc.version 2>/dev/null || print none)"; }
need_main() { [[ -n $MAIN ]] || { print "STOP: no $SCR/main.session (Main's Session id): run 00 first"; exit 1; }; }
check_tmp() {
  case ${${TMPDIR:-/tmp}:A}/ in ${H:A}/*) print "STOP: TMPDIR ${TMPDIR:-/tmp} is inside the Harness"; return 1 ;; esac
  print -r -- "TMPDIR=${TMPDIR:-/tmp} (outside the Harness)"
}
product_guard() {  # this Worktree's src/tests/plugins/pyproject.toml = $TARGET (production graphtraj), nothing uncommitted there
  local names dirty
  names=$(gg -C $WT diff --name-only $TARGET HEAD -- $GUARDED 2>&1); dirty=$(gg -C $WT status --porcelain -- $GUARDED 2>&1)
  print -r -- "product guard: HEAD $(gg -C $WT rev-parse HEAD) | git diff ${TARGET[1,8]} HEAD -- ${GUARDED[*]}: ${${names//$'\n'/ }:-empty} | uncommitted there: ${${dirty//$'\n'/ }:-none}"
  [[ -z $names && -z $dirty ]]
}
other_suites() {  # test runs of anyone; exit 2 when ps cannot list (never read as "no other suite")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then print -r -- "ps cannot list processes (${listed[1,160]})"; return 2; fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E|other_suites'
  return 0
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
# 593's guard, simplified: BLOCKING = a live process naming $RT/, Main's host config or Main's Session id; budget timers
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
members_idle() {  # $1 = phase. STOP while a member Worker or swarm batch runs; after Mpre also guard's BLOCKING 0
  local listing; listing=$(ps -axww -o pid=,etime=,command= 2>&1) || { print "STOP: ps cannot list processes"; return 2; }
  local -a workers=(${${(f)"$(print -r -- $listing | grep -E -- '-m graphtraj\.execution\.runner_worker|-m graphtraj\.teams\.team_round' | grep -v -- 'grep -E')"}:#})
  print -r -- "members_idle [$1]: Task $TASK_ID's Leader and Engineer must have ended their turns; member Workers and swarm batches running now: ${#workers}"
  (( ${#workers} )) && { print -l -- "  "${^workers[1,12]}; return 1; }
  if [[ $1 != Mpre ]]; then guard || return 1; fi
  print -r -- "members_idle [$1]: no member execution is active: PASS"
}
vproject_init() {  # $1 = graphtraj command: an isolated project with its own git and .graphtraj (setup), never the Harness
  mkdir -p $VPROJ
  [[ -d $VPROJ/.git ]] || gg -C $VPROJ init -q --initial-branch=main || return 1
  if ! gg -C $VPROJ rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 600 scratch project" > $VPROJ/README.md
    gg -C $VPROJ add README.md && gg -C $VPROJ -c user.name=600 -c user.email=600@invalid commit -qm "Initial source" || return 1
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
  out=$(print -r -- '{"hook_event_name":"Probe600","session_id":"probe-600","cwd":"'$VPROJ'"}' | (cd $VPROJ && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
  [[ $out == '{}' ]]; ck $? "Codex hooks entry of $1 runs (neutral event answers {})" "${out[1,200]}"
}
sr_classify() {  # $1 = G record. Sets SR_NEW, SR_ANY, SR_IDS; writes <record>/new-ids.txt (593's, every ABNORMAL line read)
  local rec=$1 line t id timeouts=0; SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): $KNOWN516"
  [[ -f $KNOWN516 ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516; then print -r -- "  known (516): $id"; else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
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
grec() { print -r -- ${ADOPT600_GREC:-${$(print -l $AD/G-*(N/om[1])):-$AD/G-none}}; }   # newest G record
nr_read() {  # 593's nr_read (its Python, read from adopt-593/steps.zsh and run as is, with the child's done word DONE-600)
  clean $CONDA -I -c 'import sys
src = open(sys.argv[1]).read()
body = src.split("<<" + chr(39) + "PY2" + chr(39) + "\n", 1)[1].split("\nPY2\n", 1)[0].replace("DONE-593", "DONE-600")
sys.argv = ["nr_read"] + sys.argv[2:]
exec(compile(body, "adopt-593 nr_read", "exec"))' $S593/steps.zsh $H $SESS $TASKDIR $R $CHILD
}

mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only, apart from creating $SCR (main.session, cc.version, a scratch clone g00.git to read the bundle). Login: yes, one claude -p probe with the USER's Claude login, pre-approved (Worldline user-decision $LOGIN_DECISION); no Codex, Pi or DSH. Network: github.com (git ls-remote). Dialog: none."
  { mkdir -p $SCR || exit 1
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python' ; ck $? "00 this uv's 'uv tool install --help' lists --managed-python" "$(clean $U tool install --help 2>&1 | grep -- '--managed-python ' | head -1 | sed 's/^ *//')"
    print -r -- "uv user config: $(for f in $HOME/.config/uv/uv.toml /etc/uv/uv.toml; do [[ -e $f ]] && print -n "$f present; " || print -n "$f absent; "; done)"
    print -r -- "TMPDIR: ${TMPDIR:-unset}"
    [[ ! -e $UVT ]]; ck $? "00 $UVT absent" "$([[ -e $UVT ]] && print "move it aside first: mv $UVT $UVT.old-\$(date +%s)")"
    say "graftling repository $G (read only)"
    gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "dev: ${gd:-NOT FOUND} in ${dw:-no worktree} | main: ${gm:-NOT FOUND} in ${mw:-no worktree}"
    [[ $gd == $GBASE ]]; ck $? "00 graftling dev = $GBASE"
    [[ $gm == $GMAIN0 ]]; ck $? "00 graftling main = $GMAIN0 (v0.9.0)"
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]]; ck $? "00 dev is checked out in $GDEV and main in $G"
    dirty=""; for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || dirty="$dirty $w"; done
    [[ -z $dirty ]]; ck $? "00 both worktrees clean (git status --porcelain empty)" "${dirty# }"
    lt=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG)
    [[ -z $lt ]]; ck $? "00 $GTAG absent locally" "${lt}"
    say "GitHub $GURL (git ls-remote, read only)"
    if rem=$(gg ls-remote $GURL refs/heads/main refs/heads/dev refs/tags/$GTAG 2>&1); then
      rm0=$(remote_of $rem refs/heads/main) rd0=$(remote_of $rem refs/heads/dev) rt0=$(remote_of $rem refs/tags/$GTAG)
      print -r -- "GitHub main: ${rm0:-absent} | dev: ${rd0:-absent} | $GTAG: ${rt0:-absent}"
      [[ $rm0 == $GMAIN0 ]]; ck $? "00 GitHub main = $GMAIN0"
      [[ -z $rt0 ]]; ck $? "00 GitHub $GTAG absent"
      [[ -n $rd0 ]] && gg -C $G merge-base --is-ancestor $rd0 $GBASE 2>/dev/null; ck $? "00 GitHub dev (${rd0:-absent}) is an ancestor of $GBASE, so rp fast-forwards it"
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
    want="uv tool install --managed-python \"git+https://github.com/LUOXIAO92/graftling.git@<tag-or-commit>\""
    run="uv tool install --managed-python \"$SRCURL\""
    print -r -- "README install line: $line"
    print -r -- "C5 runs:             $run"
    [[ $line == $want && ${line/<tag-or-commit>/$GTAG} == $run ]]; ck $? "00 README install line at $GCOMMIT with @$GTAG equals C5's command"
    say "adoption preflight: production $RT (read only)"
    check_tmp; ck $? "00 TMPDIR outside the Harness"
    pv=$(clean $RT/bin/python -I -c 'import importlib.metadata as m; print(m.version("graphtraj"), m.version("graftling"))' 2>&1); print -r -- "production graphtraj graftling: $pv"
    sp=$(site); dgt=$(cat $sp/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null) dgl=$(cat $sp/graftling-$GOLDVERSION.dist-info/direct_url.json 2>/dev/null)
    print -r -- "graphtraj direct_url: ${dgt:-none}"; print -r -- "graftling direct_url: ${dgl:-none}"
    [[ $pv == "0.1.0 $GOLDVERSION" && $dgt == *"wheels-${TARGET[1,8]}/graphtraj-0.1.0-"*.whl* && $dgl == *"wheels-${TARGET[1,8]}/graftling-$GOLDVERSION-"*.whl* ]]
    ck $? "00 production is graphtraj 0.1.0 + graftling $GOLDVERSION, both from 593's wheels-${TARGET[1,8]}"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "00 production pip check" "${pc[1,120]}"
    print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && ! -e $RT/bin/agents ]]; ck $? "00 production bin has subagents, subagents-mcp (and no agents)"
    w593=($W593/graphtraj-0.1.0-*.whl(N) $W593/graftling-$GOLDVERSION-*.whl(N)); print -r -- "593 wheels: ${w593[*]:t}"
    (( $#w593 == 2 )); ck $? "00 593's graphtraj and graftling $GOLDVERSION wheels are in $W593 (suite-base's base side, V's graphtraj)"
    [[ ! -e $BK ]]; ck $? "00 backup $BK absent"
    product_guard; ck $? "00 this Worktree's ${GUARDED[*]} equal production graphtraj ${TARGET[1,8]} (I installs only the graftling wheel)"
    gdev=$(gg -C $WT rev-parse -q --verify refs/heads/dev); print -r -- "GraphTraj dev: ${gdev:-none} | git diff ${TARGET[1,8]} dev -- src plugins pyproject.toml tests: $(gg -C $WT diff --name-only $TARGET ${gdev:-HEAD} -- src plugins pyproject.toml tests | tr '\n' ' ')(information)"
    cdef=${${${(M)${(f)"$(cat $STATE/tasks/$TASKDIR/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
    [[ -n $cdef && -f $STATE/tasks/$TASKDIR/$cdef ]]; ck $? "00 probe Task $TASK_ID ready (current_definition ${cdef:-none} exists)"
    print -r -- ".mcp.json servers: $(clean $CONDA -I -c 'import json,sys; print(sorted((json.load(open(sys.argv[1])).get("mcpServers") or {})))' $H/.mcp.json 2>&1)"
    print -r -- "plugin and entry files (hashes; I requires them unchanged):"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json $ENTRIES 2>&1 | sed 's/^/  /'
    say "Claude: version and one claude -p probe (the USER pre-approved their Claude login for Task 600: Worldline user-decision $LOGIN_DECISION)"
    C=$(claude_bin); [[ -s $SCR/cc.version ]] || clean $C --version 2>&1 | head -1 > $SCR/cc.version; cv
    P=$(mktemp -d ${TMPDIR:-/tmp}/probe-600.XXXXXX)
    ans=$(cd $P && print -r -- "Reply with one line: READY-600, your model id, and LOGGED-IN if you answer through a login." | clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL 2>&1 | head -3)
    print -r -- "claude answered: $ans"; [[ $ans == *READY-600* ]]; ck $? "00 claude -p answers READY-600 (model and login above)"
    say "Main's Session (I, M, Mr need it)"
    id=$(detect_main); [[ -n $id ]] && print -r -- $id > $SCR/main.session
    print -r -- "MAIN=${id:-NOT FOUND} (saved to $SCR/main.session)"; [[ -n $id ]]; ck $? "00 Main's Session id found"
    members_idle 00 | head -14 || print "(information at 00: members may run now; Mpre and I wait for them)"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above). Nothing was changed. Hand $R/00.txt to the Team."; exit 1; }
  summary 00 "$(grep -E '^(uv|CHECK|TMPDIR|dev|GitHub|sha256|list-heads|README|C5 runs|production|claude|MAIN=|members_idle)' $R/00.txt)"
  print "Success: every 'CHECK 600 00 ...: PASS'."
  next "zsh $THIS rel" ;;

rel) print "[rel] Main. graftling repository $G: fetch $GBRANCH from the bundle, fast-forward dev ($GDEV) and main ($G) to $GCOMMIT, annotated tag $GTAG ($RELNAME <$RELMAIL>). No network, no login. Dialog: none."
  rel_verify() {
    local gt gd gm
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    print -r -- "$GTAG -> ${gt:-absent} | dev $gd | main $gm | type $(gg -C $G cat-file -t refs/tags/$GTAG 2>&1) | tagger $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG)"
    [[ $gt == $GCOMMIT ]]; ck $? "rel $GTAG peels to $GCOMMIT"
    [[ $gm == $GCOMMIT && $gd == $GCOMMIT ]]; ck $? "rel graftling main == dev == $GTAG^{} == $GCOMMIT"
    [[ $(gg -C $G cat-file -t refs/tags/$GTAG 2>/dev/null) == tag && $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG) == "$RELNAME <$RELMAIL>" ]]
    ck $? "rel $GTAG is an annotated tag with the noreply tagger"
    local tm; tm=$(gg -C $G cat-file tag refs/tags/$GTAG 2>/dev/null | sed '1,/^$/d')
    [[ $tm == *597* && $tm == *599* && $tm == *compatible* ]]; ck $? "rel $GTAG message names 597, 599 and compatible"
    local v; v=$(gg -C $G show ${GTAG}:src/graftling/__init__.py 2>/dev/null | grep -E '^__version__')
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
    [[ $gm == $GMAIN0 || $gm == $GCOMMIT ]] || { print -r -- "STOP: graftling main is $gm, no longer $GMAIN0 (v0.9.0). Nothing changed. Main tells the Leader."; exit 1; }
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
  print "Success: every 'CHECK 600 rel ...: PASS' (or 'already released')."
  next "zsh $THIS B" ;;

B) print "[B] Main, before the push. git archive $GTAG -> $GSRC; wheel from the archive root with $CONDA (--no-index --no-deps --no-build-isolation) -> $WHL. No network, no login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}")
    [[ $gt == $GCOMMIT ]] || { print -r -- "STOP: $GTAG^{commit} is ${gt:-absent}, not $GCOMMIT: run rel first."; exit 1; }
    rm -rf $GSRC $WHL $SCR/wheelview; mkdir -p $GSRC $WHL $SCR/wheelview || exit 1
    gg -C $G archive $GTAG | tar -x -C $GSRC || exit 1
    print -r -- "git archive $GTAG ($GCOMMIT) -> $GSRC"
    say "version strings in the archive"
    vbad=0; for vf in src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $GSRC/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B archive version strings (__init__.py and the 3 json) all $GVERSION"
    hd=$(grep -m1 '^## ' $GSRC/CHANGELOG.md); print -r -- "CHANGELOG first heading: $hd"
    [[ $hd == "## $GVERSION (compatible)" ]] && ! grep -q '^## Unreleased' $GSRC/CHANGELOG.md; ck $? "B CHANGELOG heading '## $GVERSION (compatible)' and no '## Unreleased'"
    say "build ($(clean $CONDA -c 'import setuptools, pip; print("setuptools", setuptools.__version__, "| pip", pip.__version__)'))"
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL $GSRC) || { print "STOP: the wheel build failed"; exit 1; }
    whl=($WHL/graftling-$GVERSION-*.whl(N)); all=($WHL/*.whl(N))
    print -r -- "wheel: ${all[*]:t}"
    (( $#whl == 1 && $#all == 1 )) || { print "STOP: expected exactly one graftling-$GVERSION wheel in $WHL"; exit 1; }
    whl=$whl[1]
    (cd $SCR/wheelview && unzip -qo $whl) || exit 1
    say "version strings in the wheel"
    mv_=$(sed -n 's/^Version: //p' $SCR/wheelview/graftling-$GVERSION.dist-info/METADATA 2>/dev/null); print -r -- "  METADATA Version: ${mv_:-MISSING}"
    vbad=0; [[ $mv_ == $GVERSION ]] || vbad=1
    for vf in graftling/__init__.py graftling/claude-plugin/.claude-plugin/plugin.json graftling/dsh/package.json graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $SCR/wheelview/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B wheel version strings (METADATA, __init__.py, the 3 json) all $GVERSION"
    say "console scripts"
    cs=$(sed -n '/^\[console_scripts\]/,/^\[/p' $SCR/wheelview/graftling-$GVERSION.dist-info/entry_points.txt | grep -oE '^[A-Za-z0-9_.-]+ *=' | tr -d ' =' | sort | tr '\n' ' ')
    print -r -- "  [console_scripts]: ${cs:-none}"
    [[ $cs == "subagents subagents-mcp " ]]; ck $? "B wheel console scripts are exactly subagents, subagents-mcp"
    say "wheel == git archive $GTAG, file by file (593's pkgdiff532.py)"
    clean $CONDA -I $S593/pkgdiff532.py graftling $whl archive:$GSRC/src "600 B graftling wheel equals git archive $GTAG" -
    ck $? "B the wheel's graftling/ files equal git archive $GTAG"
    say "content markers in the wheel"
    mk=0
    for f in graftling/claude-plugin/bin/graftling-host graftling/dsh/plugin.mjs; do
      n=$(grep -c 'uv tool install --managed-python' $SCR/wheelview/$f 2>/dev/null); print -r -- "  $f: 'uv tool install --managed-python' x${n:-0}"; (( ${n:-0} > 0 )) || mk=1
    done
    n=$(grep -c '^\*\*Retired Agents\.\*\*' $SCR/wheelview/graftling/PUBLIC_API.md 2>/dev/null); print -r -- "  graftling/PUBLIC_API.md: '**Retired Agents.**' x${n:-0}"; (( ${n:-0} > 0 )) || mk=1
    ck $mk "B 597's and 599's markers are in the wheel"
    leaked=$(unzip -Z1 $whl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "leaked build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the wheel"
    say "GraphTraj's graftling requirement ($WT/pyproject.toml; information: no change needed)"
    clean $CONDA -I -c 'import sys, tomllib
from packaging.requirements import Requirement
deps = tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]
reqs = [Requirement(d) for d in deps if Requirement(d).name == "graftling"]
ok = len(reqs) == 1 and reqs[0].specifier.contains(sys.argv[2])
verdict = "yes, no change needed" if ok else "NO"
print(f"REPORT 600 B GraphTraj Requires-Dist {reqs[0] if reqs else None} includes {sys.argv[2]}: {verdict}")
sys.exit(0 if ok else 1)' $WT/pyproject.toml $GVERSION; ck $? "B GraphTraj's graftling range includes $GVERSION"
    print -r -- "wheel sha256: $(shasum -a 256 $whl)"
    say "the wheel G and I install: $N"
    rm -rf $N && mkdir -p $N && cp -p $whl $N/ && (cd $N && shasum -a 256 *.whl > SHA256SUMS) && print -r -- "$GTAG $GCOMMIT" > $N/GRAFTLING || exit 1
    (cd $N && shasum -a 256 -c SHA256SUMS) ; ck $? "B $N holds the $GTAG wheel with SHA256SUMS"
  } 2>&1 | tee $R/B.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/B.txt || { print "\nB STOP (see above). Do not push. Hand $R/B.txt to the Team."; exit 1; }
  summary B "$(grep -E '^(CHECK|REPORT|wheel)' $R/B.txt)"
  print "Success: every 'CHECK 600 B ...: PASS'."
  next "zsh $THIS G    (it starts the full suite in the background and returns; then: ADOPT600_PUSH_CONFIRMED=yes zsh $THIS rp)" ;;

rp) print "[rp] Main. Outward-facing: push graftling dev, main and refs/tags/$GTAG to origin ($GURL), fast-forward only, atomic, no force. The user's release decision is the push decision (Worldline user-decision $DECISION). Network: github.com with the user's usual git credentials (osxkeychain); no other login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]] || { print -r -- "STOP: rel is not complete (dev $gd, main $gm, $GTAG ${gt:-absent}; need all $GCOMMIT)."; exit 1; }
    ou=$(gg -C $G remote get-url origin 2>&1); print -r -- "origin: $ou"
    [[ $ou == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL"; exit 1; }
    before=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main refs/tags/$GTAG 2>&1) || { print -r -- "STOP: ls-remote failed: ${before[1,200]}"; exit 1; }
    print -r -- "remote before: ${before//$'\n'/ | }"
    print -r -- "will push: dev $gd, main $gm, refs/tags/$GTAG ($(gg -C $G rev-parse refs/tags/$GTAG)) (fast-forward only, --atomic, no force)"
    [[ ${ADOPT600_PUSH_CONFIRMED:-} == yes ]] || { print -r -- "STOP: the push is outward-facing. It is the user's decision $DECISION; run: ADOPT600_PUSH_CONFIRMED=yes zsh $THIS rp"; exit 1; }
    gg -C $G push --atomic origin refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/$GTAG || { print "STOP: the push was refused (atomic: nothing changed on the remote)"; exit 1; }
    now=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" 2>&1)
    print -r -- "remote now: ${now//$'\n'/ | }"
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT && $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "rp remote main == $GTAG^{} == $GCOMMIT"
    [[ $(remote_of $now refs/heads/dev) == $gd ]]; ck $? "rp remote dev == local dev ($gd)"
  } 2>&1 | tee $R/rp.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rp.txt || { print "\nrp STOP (see above). Hand $R/rp.txt to the Team."; exit 1; }
  summary rp "$(grep -E '^(remote|CHECK)' $R/rp.txt)"
  print "Success: both 'CHECK 600 rp ...: PASS'."
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
  print "Success: three 'CHECK 600 gh ...: PASS'."
  next "zsh $THIS C5" ;;

C5) print "[C5] Main. README's install command for GitHub $GTAG in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local, uv tool directory, dotfiles and conda are not touched. Network: github.com, PyPI, uv's Python download. No login. Dialog: none. ~2-3 min."
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier C5). Move it aside: mv $UVT $UVT.old-\$(date +%s)"; exit 1; }
    mkdir -p $UVT || exit 1
    say "before: USER directories and conda (read only)"
    snap $R/C5-home-before.json || exit 1
    say "README line 1: the install, uv directories isolated under $UVT"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1) | environment: ${UVENV[*]}"
    print -r -- "command: ${INSTALL[*]}   (uv = $U)"
    (cd $UVT && clean $UVENV $U ${INSTALL[2,-1]}) > $R/C5-uv.txt 2>&1; urc=$?
    tail -5 $R/C5-uv.txt
    print "uv tool install rc=$urc (full output: $R/C5-uv.txt)"; ck $urc "C5 uv tool install rc 0"
    (( urc == 0 )) || exit 1
    say "README line 2: AGENTS_PYTHON=\"\$(uv tool dir)/graftling/bin/python\" (isolated environment)"
    td=$(cd $UVT && clean $UVENV $U tool dir 2>&1); py=$td/graftling/bin/python
    print -r -- "uv tool dir: $td"; [[ $td == $UVT/tools ]]; ck $? "C5 uv tool dir is $UVT/tools"
    out=$(cd $UVT && clean $py -I -c 'import sys, json, importlib.metadata as m, graftling
d = m.distribution("graftling")
print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix)
print(graftling.__version__); print(m.version("graftling"))
print(json.loads(d.read_text("direct_url.json") or "{}").get("vcs_info", {}).get("commit_id", "none"))' 2>&1) || { ck 1 "C5 the tool Python runs" "${out[1,200]}"; exit 1; }
    prefix=${${(f)out}[1]} base=${${(f)out}[2]} gv=${${(f)out}[3]} mdv=${${(f)out}[4]} cid=${${(f)out}[5]}
    print -r -- "tool python: $py -> ${py:A} | sys.prefix: $prefix | base: $base -> ${base:A} | graftling.__version__ $gv | metadata $mdv | direct_url commit_id $cid"
    [[ $gv == $GVERSION && $mdv == $GVERSION ]]; ck $? "C5 graftling.__version__ and importlib.metadata version are $GVERSION"
    [[ ${prefix:A} == ${UVT:A}/tools/graftling ]]; ck $? "C5 sys.prefix is $UVT/tools/graftling"
    class=other
    case ${base:A}/ in ${CROOT:A}/*) class=conda ;; /usr/*|/System/*|/Library/*|/opt/homebrew/*) class=system ;; esac
    [[ ${base:A}/ == ${UVT:A}/python/* && ${py:A}/ == ${UVT:A}/python/* ]] && class=uv-managed
    print -r -- "REPORT 600 C5 base interpreter: $base ($class) | uv-managed Pythons: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    [[ $class == uv-managed ]]; ck $? "C5 tool environment base interpreter is uv-managed (under $UVT/python)" "$class"
    [[ $cid == $GCOMMIT ]]; ck $? "C5 installed dist-info direct_url.json vcs commit_id is $GCOMMIT" "$cid"
    say "README line 3: \"\$(uv tool dir --bin)/subagents\" --help (isolated environment)"
    bd=$(cd $UVT && clean $UVENV $U tool dir --bin 2>&1); print -r -- "uv tool dir --bin: $bd"
    [[ $bd == $UVT/bin ]]; ck $? "C5 uv tool dir --bin is $UVT/bin"
    hl=$(cd $UVT && clean "$bd/subagents" --help 2>&1); hrc=$?
    print -r -- "subagents --help (rc $hrc): ${${(f)hl}[1]:-}"
    ck $hrc "C5 $UVT/bin/subagents --help rc 0"
    [[ -x $UVT/bin/subagents-mcp ]]; ck $? "C5 $UVT/bin/subagents-mcp exists" "$(head -1 $UVT/bin/subagents-mcp 2>/dev/null)"
    say "after: USER directories and conda"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT600_NOSNAP, rehearsal only)"
    else
      snap $R/C5-home-after.json > /dev/null
      clean $CONDA -I $S593/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json; ck $? "C5 USER directories (~/.local, uv tools, ~/.pi, ~/.dsh, ~/.codex) and conda unchanged"
    fi
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/C5.txt || { print "\nC5 STOP (see above). Hand $R/C5.txt to the Team."; exit 1; }
  summary C5 "$(grep -E '^(uv|command|uv tool install|tool python|subagents --help|CHECK|REPORT)' $R/C5.txt)"
  print "Success: every 'CHECK 600 C5 ...: PASS' (rc 0; version $GVERSION; base interpreter under $UVT/python; commit $GCOMMIT; subagents --help rc 0; USER directories and conda unchanged)."
  next "zsh $THIS GR    (after G has ended: the last line of $(grec)/suite.txt is exit=N)" ;;

G) print "[G] Main. Full GraphTraj suite: this Worktree's HEAD (editable; product = production ${TARGET[1,8]}) + the $GTAG wheel from B, 6 shards in the background (~25-30 min once started); pytest temp under TMPDIR=${TMPDIR:-/tmp}. Main's suite queue is serial: while another suite runs G waits (it says so in wait.txt) and starts by itself. No login, no network. Dialog: none. Returns at once."
  { check_tmp || exit 1
    product_guard || { print "STOP: product guard (above)"; exit 1; }
    whl=($N/graftling-$GVERSION-*.whl(N)); (( $#whl == 1 )) || { print "STOP: no $GTAG wheel in $N: run B first"; exit 1; }
    pscheck=$(other_suites) || { print -r -- "STOP: $pscheck (nothing was built or started)"; exit 1; }
    GV=${SCR:A}/gvenv-600 O=$AD/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-600-G-$(date +%Y%m%dT%H%M%S)
    rm -rf $GV; clean $CONDA -m venv --system-site-packages $GV || exit 1
    sp=$(site); D=($GV/lib/python*/site-packages(N))   # production's click 8.5.0, PyYAML, websockets shadow the base Python's (564)
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    clean $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $whl || exit 1
    clean $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
    mkdir -p $O $RUNTMP
    { print -r -- "pytest temp root: $RUNTMP (TMPDIR=${TMPDIR:-/tmp}, outside the Harness)"
      print -r -- "launch environment: HOME USER PATH TERM TMPDIR LANG only (clean(); no provider credential variable reaches the suite)"
      print -r -- "candidate: $(gg -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT ($GTAG, ${whl:t})"; print -r -- "python: $GV/bin/python"
      (cd ${TMPDIR:-/tmp} && clean $GV/bin/python -I -c 'import importlib.metadata as m; print("test interpreter dependencies:", " | ".join(f"{n} {m.version(n)}" for n in ("click", "PyYAML", "websockets", "pytest", "graftling")))'); } > $O/run.txt
    extra=(${(Q)${(z)${ADOPT600_PYTEST_ARGS:-}}})
    (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" >> $O/run.txt
    : > $O/suite.txt
    busy=$(other_suites)
    ( while true; do
        busy=$(other_suites) || { print "$(date +%T) STOP: ps failed; G did not start" >> $O/wait.txt; print "exit=ps-failed (G did not start)" >> $O/suite.txt; exit 1; }
        [[ -z $busy ]] && break
        print -r -- "$(date +%T) waiting for another suite: $(print -r -- $busy | awk '{print $1}' | tr '\n' ' ')" >> $O/wait.txt; sleep ${ADOPT600_GWAIT:-60}
      done
      print -r -- "$(date +%T) started" >> $O/wait.txt
      cd $WT && clean env TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra > $O/suite.txt 2>&1
      print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended" >> $O/wait.txt
      clean $CONDA -I $S593/fails593.py $O/failures.txt $O/suite.txt $O/shards/*(N.) > /dev/null
    ) < /dev/null > /dev/null 2>&1 &!
    cat $O/run.txt
    print -r -- "G $([[ -n $busy ]] && print 'queued behind another suite' || print started) in the background at $(date +%T): record $O (suite.txt ends with exit=N)"
  } 2>&1 | tee $R/G.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nG STOP (see above). Hand $R/G.txt to the Team."; exit 1; }
  print "Success: 'G started' (or 'queued'); run.txt names the candidate, the $GTAG wheel and a pytest temp root outside the Harness."
  next "ADOPT600_PUSH_CONFIRMED=yes zsh $THIS rp    (G keeps running; GR after it ends)" ;;

GR) print "[GR] Main, after G has ended. Read only: G's record, totals, and every FAILED/ERROR id and ABNORMAL shard classed against 516's current definition (a shard 'timed out after' is NEW). No login. Dialog: none."
  { rec=$(grec); ok=0; print -r -- "G record: $rec"
    product_guard || ok=1
    [[ -f $rec/run.txt && -f $rec/suite.txt ]] || { print "STOP: no G record: run G first"; exit 1; }
    grep -q '^exit=' $rec/suite.txt || { print -r -- "G has not finished ($rec/suite.txt has no exit= line; queue: $(tail -1 $rec/wait.txt 2>/dev/null)). Rerun GR later."; exit 1; }
    sed 's/^/  run.txt: /' $rec/run.txt
    cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $rec/run.txt | head -1) gl=$(grep -oE 'git archive [0-9a-f]{40}' $rec/run.txt | head -1 | awk '{print $3}')
    cdiff=$(gg -C $WT diff --name-only ${cand:-missing} $TARGET -- $GUARDED 2>&1)
    [[ -n $cand && -z $cdiff ]]; ck $? "GR the record's candidate ${cand[1,8]} has the product of ${TARGET[1,8]}" "${cdiff//$'\n'/ }"
    [[ $gl == $GCOMMIT ]]; ck $? "GR the record's graftling wheel is $GTAG ($GCOMMIT)" "${gl:-none}"
    grep -q 'outside the Harness' $rec/run.txt && grep -q '^launch environment: HOME USER PATH TERM TMPDIR LANG only' $rec/run.txt; ck $? "GR pytest temp outside the Harness and clean launch environment recorded"
    grep -q 'click 8.5.0' $rec/run.txt; ck $? "GR test interpreter click = production's 8.5.0"
    tot=$(grep -E '^=*.* (passed|failed)|^[0-9]+ (failed|errors|passed)' $rec/suite.txt | tail -1); ex=$(sed -n 's/^exit=//p' $rec/suite.txt | tail -1)
    print -r -- "totals: ${tot:-NOT FOUND} | exit: ${ex:-NOT FOUND}"
    sr_classify $rec
    rf=0; grep -q '^REHEARSAL' $rec/run.txt && rf=1   # a rehearsal -k filter leaves shards with nothing collected (exit 5)
    (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && ( $SR_ANY == 1 || $rf == 1 ) ) ]]; ck $? "GR G record ($GTAG wheel) has no new failure" "$( (( $#SR_IDS )) && print "$#SR_IDS NEW ids: run SR")"
  } 2>&1 | tee $R/GR.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/GR.txt || { print "\nGR STOP or FAIL (see above). If it names NEW ids or an ABNORMAL shard: zsh $THIS SR"; exit 1; }
  summary GR "$(grep -E '^(G record|totals|CHECK|  NEW|  known|  ABNORMAL)' $R/GR.txt)"
  print "Success: every 'CHECK 600 GR ...: PASS'."
  next "zsh $THIS V" ;;

SR) print "[SR] Main, read only. The newest G record's FAILED/ERROR ids and ABNORMAL shards, classed against 516; prints the suite-base command for NEW ids. Dialog: none."
  rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no finished G record ($rec)"; exit 1; }
  { tail -6 $rec/suite.txt; sr_classify $rec; print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"; } 2>&1 | tee $R/SR.txt
  SR_IDS=(${(f)"$(<$rec/new-ids.txt)"}); SR_IDS=(${SR_IDS:#}); SR_NEW=0; grep -q '^SR verdict: PASS' $R/SR.txt || SR_NEW=1   # the block above ran in a subshell
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)SR_IDS}"; print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else next "none for suite-base (no NEW id). A NEW ABNORMAL shard: hand $rec/suite.txt and its shard log to the Team. Otherwise: zsh $THIS V"; fi
  exit $SR_NEW ;;

suite-base) print "[suite-base] Main, only for SR's NEW ids. Reruns them on GraphTraj ${TARGET[1,8]} + production's graftling $GOLDVERSION wheel (593's) and on the candidate (G's venv, $GTAG wheel); clean environment, pytest temp under TMPDIR. Dialog: none."
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print "STOP: no id file"; exit 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; exit 2; }
  check_tmp || exit 1
  o=$(other_suites) || { print -r -- "STOP: $o"; exit 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; exit 1; }
  B0=${SCR:A}/graphtraj-base VB=${SCR:A}/sbvenv-${TARGET[1,8]} VC=${SCR:A}/gvenv-600 sp=$(site)
  [[ -x $VC/bin/python ]] || { print "STOP: no G venv $VC; run G first"; exit 1; }
  if [[ ! -d $B0/.git ]]; then rm -rf -- $B0 && gg clone -q --no-checkout $(gg -C $WT rev-parse --path-format=absolute --git-common-dir) $B0 && gg -C $B0 -c advice.detachedHead=false checkout -q $TARGET || exit 1; fi
  if [[ ! -f $VB/installed ]]; then
    rm -rf -- $VB && clean $CONDA -m venv --system-site-packages $VB || exit 1; D=($VB/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pipq=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
    clean $VB/bin/python -m pip install $pipq $W593/graftling-$GOLDVERSION-*.whl && clean $VB/bin/python -m pip install $pipq -e $B0 > /dev/null || exit 1
    print -r -- "graftling $GOLDVERSION (593's wheel) + graphtraj ${TARGET[1,8]} (editable)" > $VB/installed
  fi
  O=$AD/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $O; print -l -- $ids > $O/ids.txt
  for side dir V in base $B0 $VB candidate $WT $VC; do
    RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-600-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $dir with $V ($([[ $side == base ]] && cat $VB/installed || print "graftling $GTAG wheel")) | temp $RUNTMP | launch environment: HOME USER PATH TERM TMPDIR LANG only"
    (cd $dir && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $O/$side-collected.txt 2>&1)
    clean $CONDA -I $SUITEIDS present $O/$side-collected.txt $O/ids.txt > $O/$side-ids.txt 2> $O/$side-missing.txt
    run=(${(f)"$(<$O/$side-ids.txt)"})
    if (( $#run )); then (cd $dir && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $O/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $O/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $O/$side.txt | tail -1) ($O/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $O/ids.txt $O/base.txt $O/candidate.txt | tee $O/classification.txt; fails=${pipestatus[1]}
  print -r -- "next: hand $O/classification.txt to the Team; a candidate-only id is a regression of this release (no adoption)"; exit $fails ;;

V) print "[V] Main. Before the install, outside production: a scratch venv ($VV) with 593's graphtraj wheel (${TARGET[1,8]}) + the $GTAG wheel; the real MCP entry in an isolated project ($VPROJ); the hook copy regenerated by the product into a scratch copy must be byte-identical to production's. No login. Dialog: none. ~1 min."
  { rm -f $R/V.ok
    [[ -f $N/SHA256SUMS ]] && (cd $N && shasum -a 256 -c SHA256SUMS) || { print "STOP: no checked wheel in $N: run B first"; exit 1; }
    product_guard; ck $? "V product guard (Worktree = production graphtraj ${TARGET[1,8]})"
    gt=($W593/graphtraj-0.1.0-*.whl(N)) gw=($N/graftling-$GVERSION-*.whl(N))
    rm -rf $VV; clean $CONDA -m venv $VV || exit 1
    clean $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gt[1] $gw[1] || exit 1
    sp=$(site) D=($VV/lib/python*/site-packages(N))
    cp -Rp $sp/click $sp/click-*.dist-info(N) $sp/yaml $sp/_yaml(N) $sp/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $sp/websockets $sp/websockets-*.dist-info(N) $D[1]/ || exit 1
    pc=$(clean $VV/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "V scratch venv pip check" "${pc[1,120]}"
    clean $VV/bin/python -I $S593/onegraft.py $VV $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "V one graftling $GVERSION from the wheel in the scratch venv (onegraft.py)"
    [[ -x $VV/bin/subagents && -x $VV/bin/subagents-mcp ]]; ck $? "V scratch venv bin has subagents, subagents-mcp"
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
    shasum -a 256 $ENTRIES | tee $AD/entries.sha256
  } 2>&1 | tee $R/V.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/V.txt || { print "\nV STOP (see above). Nothing in production changed. Hand $R/V.txt to the Team."; exit 1; }
  touch $R/V.ok
  summary V "$(grep -E '^(CHECK|diff -r|product guard)' $R/V.txt)"
  print "Success: every 'CHECK 600 V ...: PASS' (incl. the hook copy byte-identical and graphtraj-mcp tools/list subagents, tasks)."
  next "zsh $THIS Mpre" ;;

Mpre) need_main; print "[Mpre] Main, right before the USER exits Main (GR and V passed). Adoption only with no member running: 600's Leader and Engineer have ended their turns and no other member runs; else STOP (never signals). No login. Dialog: none."
  { grep -q '^CHECK 600 GR G record .*: PASS' $R/GR.txt 2>/dev/null; ck $? "Mpre GR passed"
    [[ -e $R/V.ok ]]; ck $? "Mpre V passed"
    members_idle Mpre; ck $? "Mpre no member Worker or swarm batch runs"
  } 2>&1 | tee $R/Mpre.txt
  grep -q ': FAIL' $R/Mpre.txt && { print "\nMpre STOP (see above). Wait for members to end (never kill them), then rerun Mpre."; exit 1; }
  print "\nWhy Main exits: Main's subagents/tasks calls run in its host process, which keeps the graftling $GOLDVERSION modules it loaded; I replaces them. So Main exits before I and resumes after it."
  print "Main tells the USER, then the USER /exits Main and runs I in a Terminal:"
  next "(USER, normal Terminal, after /exit in Main) zsh $THIS I" ;;

I) need_main
  print "[I] USER (Main tells the USER first; the USER /exits Main, then runs this in a normal Terminal). Waits for members, backs up, installs ONLY the graftling $GTAG wheel into $RT (graphtraj unchanged), checks the real entries. No login. Dialog: none (one Enter to confirm). ~3 min plus waiting."
  [[ -e $BK ]] && { print "STOP: $BK exists; I never overwrites a backup. Tell Main."; exit 1; }
  [[ -e $R/V.ok ]] && grep -q '^CHECK 600 GR G record .*: PASS' $R/GR.txt 2>/dev/null || { print "STOP: V or GR has not passed. Nothing changed."; exit 1; }
  product_guard || { print "STOP: product guard. Nothing changed."; exit 1; }
  print "Confirm that you typed /exit in the Claude Code Main. Enter to continue, Ctrl-C to stop."; read -r answer
  { members_idle I || { print "STOP: a member or host still runs (above). Nothing changed; wait, then rerun I (never kill them)."; exit 1; }
    date '+I start %F %T'
    say "backup: venv (manifest + cp -Rp), hook copy, entry files (mode 600), the tools R needs; COMPLETE marker"
    mkdir -p $BK/tools $BK/entries && chmod 700 $BK || exit 1
    cp -p $THIS $S593/adopt_tree.py $S593/pkgdiff532.py $BK/tools/ && print -r -- $MAIN > $BK/tools/main.session || exit 1
    tree manifest $RT $BK/venv.manifest && cp -Rp $RT $BK/venv && tree compare $BK/venv.manifest $BK/venv || { print "STOP: venv backup failed; production unchanged"; exit 1; }
    tree manifest $PDIR $BK/plugin.manifest && cp -Rp $PDIR $BK/plugin || exit 1
    for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || exit 1; done; chmod 600 $BK/entries/*(D) || exit 1
    shasum -a 256 $ENTRIES > $BK/entries.sha256; touch $BK/COMPLETE; print "backup COMPLETE: $BK"
    shasum -a 256 -c $AD/entries.sha256 > /dev/null; ck $? "I entry files unchanged since V"
    members_idle I-before-pip || { print "STOP: a member started; backup done, production unchanged. Main moves $BK aside before a rerun."; exit 1; }
    touch $BK/INSTALL-STARTED; date +%s > $R/I-install-start.epoch
    whl=($N/graftling-$GVERSION-*.whl(N)); (cd $N && shasum -a 256 -c SHA256SUMS) || exit 1
    say "pip install --no-deps --no-index ${whl:t} (graftling $GOLDVERSION -> $GVERSION; graphtraj not reinstalled)"
    clean $RT/bin/python -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index $whl; ck $? "I pip install of the $GTAG wheel"
    date +%s > $R/I-install-end.epoch
    sp=$(site); bs=($BK/venv/lib/python*/site-packages(N/))
    gv=$(clean $RT/bin/python -I -c 'import graftling; print(graftling.__version__)' 2>&1); dgl=$(cat $sp/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null)
    print -r -- "graftling $gv | direct_url: ${dgl:-none}"
    [[ $gv == $GVERSION && $dgl == *"$N/graftling-$GVERSION-"*.whl* ]]; ck $? "I graftling $GVERSION from the 600 wheel"
    (( $(print -l $sp/graftling-$GOLDVERSION.dist-info(N) | grep -c .) == 0 )); ck $? "I graftling $GOLDVERSION dist-info gone"
    clean $CONDA -I $S593/pkgdiff532.py graftling $whl $sp "600 I installed graftling equals the $GTAG wheel" - | tail -1; ck ${pipestatus[1]} "I installed graftling files equal the wheel"
    dgt=$(cat $sp/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null); print -r -- "graphtraj direct_url: ${dgt:-none}"
    [[ $dgt == *"wheels-${TARGET[1,8]}/graphtraj-0.1.0-"*.whl* ]]; ck $? "I graphtraj direct_url is still 593's ${TARGET[1,8]} wheel"
    clean $CONDA -I $S593/pkgdiff532.py graphtraj $sp ${bs[1]:-$BK/venv/missing} "600 I graphtraj unchanged (installed vs backup)" - | tail -1; ck ${pipestatus[1]} "I graphtraj package unchanged vs the backup"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "I production pip check" "${pc[1,120]}"
    [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && $(head -1 $RT/bin/subagents) == "#!$RT/bin/python"* ]]; ck $? "I production bin subagents, subagents-mcp (this venv's python)"
    clean $RT/bin/python -I $S593/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'; ck ${pipestatus[1]} "I one graftling $GVERSION in production (onegraft.py)"
    say "real entries of production (run in the isolated $VPROJ) and the files that must not change"
    mcp_probe I-production $RT
    codex_hook_check $RT
    diff -r $BK/plugin $PDIR > /dev/null; ck $? "I hook copy byte-identical to the backup (no configuration --write: V proved no change)"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__}; ck $? "I ${f#$H/} byte-identical to the backup"; done
    guard > /dev/null; ck $? "I no process started on $RT during the install"
  } 2>&1 | tee -a $R/I.txt; rc=${pipestatus[1]}
  if (( rc != 0 )) || grep -q '^CHECK 600 I .*: FAIL' $R/I.txt; then
    [[ -e $BK/INSTALL-STARTED ]] && print "\nI FAILED after the install began. Do not resume Main. Run the rollback now:\n  zsh $BK/tools/steps.zsh R" || print "\nI STOP before the install (production unchanged). Tell Main."
    exit 1
  fi
  touch $R/I.ok
  summary I "$(grep -E '^(I start|backup COMPLETE|graftling 0|graphtraj direct_url|CHECK)' $R/I.txt)"
  print "Success: every 'CHECK 600 I ...: PASS'. Rollback, if ever needed (Main asks the USER first): zsh $BK/tools/steps.zsh R"
  print "\nNext (USER, normal Terminal): resume Main (same Session):\n  cd $H && claude --continue"
  print "Expected dialog: none (the hook copy and .mcp.json are unchanged). If a plugin/hooks trust dialog appears anyway: Esc and tell Main (unexpected). If --continue opens another conversation: /exit, then cd $H && claude --resume $MAIN"
  next "Main (resumed): zsh $THIS M" ;;

M) need_main; cv; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main (resumed with claude --continue, Session $MAIN). Paste one at a time; Main saves each raw answer as $R/M-<letter>.txt. Login: none beyond the running Main. Dialog: none expected (if a tool permission dialog appears: 'Yes' once, not always, and tell the Team).

[a] Using no tools: list exactly every tool in your current tool list whose name starts with mcp__graphtraj__, mcp__graftling__ or mcp__agents__, and list every GraphTraj/Graftling notice delivered to you since this resume, saying for each whether you had seen it before the resume.
  Success: only mcp__graphtraj__subagents and mcp__graphtraj__tasks; no notice seen before the resume appears again.

[b] Using only mcp__graphtraj__subagents: execute status with arguments {} (no agent). Print the raw result and whether it was an error. Then using only mcp__graphtraj__tasks: execute task_graph with arguments {"view":"current","details":["$TASK_ID"]} and print only whether an error was returned and Task $TASK_ID's current definition path.
  Success: subagents status answers without error; task_graph without error, Task $TASK_ID's current definition definitions/<time>.md.
EOF2
  next "zsh $THIS Mr" ;;

Mr) need_main; print "[Mr] Main, after M[b]. Read only: Main's own transcript after I's install end must hold mcp__graphtraj__subagents and mcp__graphtraj__tasks calls answered without error (593's rec593.py). No login. Dialog: none."
  { split=$(cat $R/I-install-end.epoch 2>/dev/null); [[ -n $split ]] || { print "STOP: I has not finished (no I-install-end.epoch)"; exit 1; }
    files=($PROJECTS/$MAIN.jsonl(N) ${(f)"$(find $PROJECTS -maxdepth 1 -name '*.jsonl' -newer $R/I-install-end.epoch 2>/dev/null)"})
    print -r -- "Main transcripts read: ${(u)files}"
    clean $CONDA -I $S593/rec593.py calls "Main $MAIN" --after $split --need subagents,tasks --old-info ${(u)files}
    ck $? "Mr Main called mcp__graphtraj__subagents and mcp__graphtraj__tasks after I without error (rec593.py above)"
  } 2>&1 | tee $R/Mr.txt
  grep -q ': FAIL' $R/Mr.txt && { print "\nMr FAIL (see above): did Main do M[b]? Hand $R/Mr.txt to the Team."; exit 1; }
  print "Success: 'CHECK 600 Mr ...: PASS'."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. One real dispatch: an advisor member on Task $TASK_ID creates the Claude child $CHILD through mcp__graphtraj__subagents WITHOUT tools; the child runs Bash and replies DONE-600; the member waits, reads and retires it. Login: the USER's Claude login, pre-approved (Worldline user-decision $LOGIN_DECISION); Main does not ask again. Dialog: none expected (a tool permission dialog: 'Yes' once and tell the Team). 600's Leader and Engineer have ended their turns. ~3-5 min. Paste in the Claude Main:
Using only mcp__graphtraj__tasks: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"This is a production check. Do NOT call submit_result or submit_report. (a) Using the subagents tool (mcp__graphtraj__subagents), create ONE claude child named $CHILD with configuration opus_coding_team.advisor, WITHOUT a tools argument (do not pass tools or disallowed_tools), and this message: <<This is a scripted probe. Call Bash once with exactly: echo $CHILD-tool && sleep 20 ; then reply with exactly: DONE-600>>. Quote the raw create result (agent id, session, execution id). If the child asks you to approve a Bash command, approve exactly that command. (b) Call subagents wait on that agent id with timeout_seconds 300, repeating until the execution has ended; quote the final wait result's last_message. Then call subagents status with arguments {agent: <agent id>} and quote its configuration, model and last_message. (c) Retire the child by its agent id and quote the raw result. End your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main saves the raw swarm result as $R/N.txt (it must hold "agent"), every notice of this member (one per line, starting '[Graftling notice from <alias> · ...' or '[GraphTraj notice from ...') as $R/N-main-notice.txt, and the member's final reply as $R/N-reply.txt.
  After the member's completed notice, before retiring the member, Main's Bash: zsh $THIS Nr
EOF2
  next "zsh $THIS Nr" ;;

Nr) print "[Nr] Main. Read only: the child $CHILD's and the member's records, one notice, the member's subagents calls (593's nr_read, rec593.py, notices499.py). No login. Dialog: none."
  { nr_read; nrc=$?
    MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt 2>/dev/null | tail -1)
    ck $nrc "Nr 593's record checks ran (their CHECK lines above)"
  } 2>&1 | tee $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1)
  { if [[ -s $R/N-main-notice.txt ]]; then nc=$(clean $CONDA -I $S593/notices499.py $R/N-main-notice.txt "$MEMBER"); [[ $nc == 1 ]]; ck $? "Nr Main got exactly one completed notice of the member" "$nc"
    else print "CHECK 600 Nr Main got exactly one completed notice of the member: PENDING (save it to $R/N-main-notice.txt)"; fi
    SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1); bare=${SID#*:}
    if [[ -n $MEMBER && -n $bare ]]; then   # the member's records by its Session id (593's rs_session_files): archive header, Claude transcript
      mf=(); for f in $SESS/*/session.jsonl(N); do head -1 $f | grep -qF -- $bare && mf+=$f; done; mf+=(${PROJECTS:h}/*/$bare.jsonl(N))
      print -r -- "member $MEMBER (Session $SID) record files: ${#mf}"
      clean $CONDA -I $S593/rec593.py calls "member $MEMBER" --need subagents $mf; ck $? "Nr member called mcp__graphtraj__subagents without error (rec593.py above)"
    else ck 1 "Nr member alias and Session found" "member ${MEMBER:-none}, session ${SID:-none}"; fi
    sa=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
    [[ -n $sa ]]; ck $? "Nr swarm result has agent" "${sa:-none}"
  } 2>&1 | tee -a $R/Nr.txt
  grep -qE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)' $R/Nr.txt && { print "\nNr not passed (see above). PENDING: save the files and rerun Nr. FAIL: hand $R/Nr.txt to the Team."; exit 1; }
  [[ -n ${sa:-} ]] && print "\nRetire the member (Main pastes): Using only mcp__graphtraj__subagents: retire with {\"agent\":\"$sa\"} and print the raw result."
  print "Success: every CHECK line PASS (child completed with DONE-600, created without tools, one execution, notice delivered; member's subagents calls; one notice; swarm agent)."
  next "zsh $THIS done" ;;

R) need_main; print "[R] USER (Main asks the USER first; after agreeing the USER /exits Main and runs this in a normal Terminal). Restores the whole venv (graftling $GOLDVERSION), the hook copy and the entry files from $BK; the current ones are kept in $BK/after-install-*. No login. Dialog: none (one Enter). Enter to continue, Ctrl-C to stop."; read -r answer
  [[ -e $BK/COMPLETE ]] || { print "STOP: no complete backup in $BK (the install starts only after it): production was not changed by I. Tell Main."; exit 1; }
  { members_idle R || { print "STOP: a member or host runs (above). Nothing restored."; exit 1; }
    KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S); mkdir -p $KEEP/entries
    mv $RT $KEEP/venv && cp -Rp $BK/venv $RT || exit 1
    tree compare $BK/venv.manifest $RT; ck $? "R venv equals the pre-install bytes"
    [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; cp -Rp $BK/plugin $PDIR || exit 1
    tree compare $BK/plugin.manifest $PDIR; ck $? "R hook copy restored"
    for f in $ENTRIES; do cmp -s $f $BK/entries/${${f#$H/}//\//__} || { cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $BK/entries/${${f#$H/}//\//__} $f; }; done
    shasum -a 256 -c $BK/entries.sha256; ck $? "R entry files restored"
    gv=$(clean $RT/bin/python -I -c 'import graftling; print(graftling.__version__)' 2>&1); [[ $gv == $GOLDVERSION ]]; ck $? "R graftling is $GOLDVERSION again" "$gv"
    pc=$(clean $RT/bin/python -m pip check --disable-pip-version-check 2>&1); ck $? "R pip check" "${pc[1,120]}"
    CH=$H/.graphtraj/claude-host/live/channel.json; [[ -e $CH ]] && mv $CH $KEEP/channel.json && print "moved out a stale $CH"
  } 2>&1 | tee -a $R/R.txt
  grep -q '^CHECK 600 R .*: FAIL' $R/R.txt && { print "\nR left a difference (above). Do not resume Main; hand $R/R.txt to Main. R can be rerun."; exit 1; }
  print "Success: every 'CHECK 600 R ...: PASS'. Then (USER): cd $H && claude --continue" ;;

done) print "[done] Main. Read only: every CHECK line of every step's raw file, and production now. No login. Dialog: none."
  { miss=""
    steps=(00 rel B G rp gh C5 GR V Mpre I Mr Nr)
    for s in $steps; do [[ -s $R/$s.txt ]] || miss="$miss $s"; done
    grep -h '^CHECK ' $R/${^steps}.txt(N)
    grep -h '^REPORT 600 ' $R/{B,C5}.txt(N)
    np=$(cat $R/${^steps}.txt(N) | grep -c '^CHECK .*: PASS') nf=$(cat $R/${^steps}.txt(N) | grep -cE '^CHECK .*: (FAIL|PENDING|NOT OBSERVED|CHECK BY HAND)')
    say "production now"
    sp=$(site); print -r -- "graphtraj graftling: $(clean $RT/bin/python -I -c 'import importlib.metadata as m; print(m.version("graphtraj"), m.version("graftling"))' 2>&1)"
    print -r -- "graftling direct_url: $(cat $sp/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null || print none)"
    print -r -- "graphtraj direct_url: $(cat $sp/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null || print none)"
    [[ $(cat $sp/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null) == *"$N/graftling-$GVERSION-"* && $(cat $sp/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null) == *"wheels-${TARGET[1,8]}/graphtraj-0.1.0-"* ]]
    ck $? "done production graftling $GVERSION from the 600 wheel, graphtraj unchanged (593's ${TARGET[1,8]} wheel)"
    print -r -- "steps without a raw file:${miss:- none} | CHECK PASS $np | CHECK not passed $nf"
    [[ -z $miss && $nf == 0 ]]; ck $? "done every step ran and every CHECK passed"
  } 2>&1 | tee $R/done.txt
  grep -q '^CHECK 600 done every step ran and every CHECK passed: PASS' $R/done.txt && ! grep -qE '^CHECK .*: FAIL' $R/done.txt || { print "\ndone: FAIL (see above). Hand $R/done.txt to the Team."; exit 1; }
  print "Success: both 'CHECK 600 done ...: PASS' (production graftling $GVERSION, graphtraj unchanged; every step's CHECK passed)."
  next "Main: hand $R to the Team; Task 600 steps complete. Rollback stays available (Main asks the USER first): zsh $BK/tools/steps.zsh R" ;;

*) print "usage: zsh $THIS 00|rel|B|G|rp|gh|C5|GR|SR|suite-base|V|Mpre|I|M|Mr|N|Nr|done|R"; exit 2 ;;
esac
