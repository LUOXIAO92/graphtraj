#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 592 Main-run steps: GraphTraj follows graftling 0.9.0's rename. Its MCP server and Claude host offer the tools
# `subagents` and `tasks` (the model sees mcp__graphtraj__subagents and mcp__graphtraj__tasks); the gateway feature
# `agents` is now `subagents`; no old name stays. GraphTraj candidate GCOMMIT + graftling candidate 49f97004 (591),
# both installed as WHEELS.
# ACCEPTANCE ENTRY: a real GraphTraj Main through the entry users use: a Pi Main on DeepSeek in a project set up with
# `graphtraj setup` and the GraphTraj Pi extension (`pi install -l`), and optionally a Claude Code Main with the
# project's `configuration --write` material. The model itself makes five calls (judge.py probes):
#   1 mcp__graphtraj__subagents discover              -> answers with its features (the acceptance call, new name)
#   2 mcp__graphtraj__subagents execute status {}     -> GraphTraj routes the subagents feature (no routing error)
#   3 mcp__graphtraj__tasks discover                  -> lists neither the feature subagents nor agents
#   4 mcp__graphtraj__tasks execute feature subagents -> refused: 'Feature does not belong to this MCP entry.'
#   5 mcp__graphtraj__tasks execute feature agents    -> refused: 'Unknown feature: agents' (the old feature is gone)
# Verdicts read the hosts' own records: the Pi Session file (tool declarations toolsAdded/toolsRemoved, calls,
# results by toolCallId, providers) and the Claude stream-json (init tool list and servers, tool_use/tool_result).
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre          Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions (zsh,
#                node, pi, git); GCOMMIT resolvable in this repository and graftling 49f97004 in <Harness>/graftling;
#                DEEPSEEK_API_KEY set (never printed); the allowlisted environment's variable NAMES (STOP if another
#                provider credential is left); 'before' state of ~/.pi/agent (names + sha256 prefixes), ~/.dsh and
#                ~/.codex (listings); the deepseek flash id from `pi --list-models deepseek`, pinned in the isolated
#                PI_CODING_AGENT_DIR=ROOT/pi-agent; a ONE-LINE Pi prompt naming its model and provider. No probe Task
#                is needed by any step. Dialog: none. Network: api.deepseek.com. ~1 min.
#                Observable: 'PASS: Pi answered as deepseek/<id>'.
#   install      Main. ROOT/venv: GraphTraj GCOMMIT and graftling 49f97004 as WHEELS (offline: click, PyYAML and
#                websockets copied from <Harness>/.venv-runtime, read only); the metadata (graphtraj's graftling
#                requirement, graftling's version); console scripts; ROOT/proj: own git, `graphtraj setup` (its dev-
#                branch question answered y), `graphtraj doctor`, and `pi install -l <the wheel's extension.mjs>`
#                (project-local .pi/settings.json). Dialog: none. No network. ~1 min.
#                Observable: 'PASS: ROOT/proj/.pi/settings.json names ...extension.mjs'.
#   cli          Main. No model, no network, no login: the installed graphtraj-mcp over stdio in ROOT/proj lists
#                exactly [subagents, tasks], refuses tools/call agents as 'Unknown tool: agents', and answers the five
#                probes as above (status here has no native Main: a refusal that is not a routing error passes, with
#                a NOTE); the hosted `subagents` CLI in ROOT/proj routes status through GraphTraj (no routing error);
#                the installed role_definitions name the `subagents` tool and not the `agents` tool. <15 s.
#   pi-main      Main. A real GraphTraj Pi Main (deepseek flash, --approve to trust the project-local extension) in
#                ROOT/proj makes the five calls. Verdicts (judge.py pi): the tools Pi declared to the model include
#                mcp__graphtraj__subagents and mcp__graphtraj__tasks, and no Session message ever offered agents or
#                mcp__*__agents; deepseek is the only provider; each probe's result as listed above; no 'Extension
#                error'. Dialog: none. Model calls: DeepSeek only. ~1-3 min.
#   claude-pre   Main, OPTIONAL, VERIFY592_CLAUDE_USER_LOGIN=1 (Main asks the user first: it uses the user's own Claude
#                Code login). A one-line `claude -p --model claude-haiku-5-5` in ROOT/claude-pre with the Mains' flags
#                and environment, judged by verify-common/claude_isolation.py check (model id, login, no Harness
#                instruction file loaded). Dialog: none. Network: Anthropic. ~30 s.
#   claude-main  Main, OPTIONAL, VERIFY592_CLAUDE_USER_LOGIN=1. ROOT/proj-claude: own git, `graphtraj setup`, then
#                `python -m graphtraj.runtimes.claude.host configuration --project ... --claude ... --write` from
#                ROOT/venv (the regenerated graphtraj-claude-host hook) and claude_isolation settings. The written
#                hook must say const TOOL = "subagents"; and const TOOLS = [TOOL, "tasks"];. A real Claude Code Main
#                (`claude -p --setting-sources project,local --strict-mcp-config --mcp-config <proj>/.mcp.json
#                --plugin-dir <written plugin> --model claude-haiku-5-5 --allowedTools mcp__graphtraj__subagents,
#                mcp__graphtraj__tasks --output-format stream-json --verbose`) makes the five calls. Verdicts (judge.py
#                claude): the init tool list of every server has the two new names and no old name; graphtraj is
#                connected; the written plugin is loaded; the five probe results. Dialog: none (print mode; the MCP
#                server and plugin are given on the command line, so no folder-trust or server-approval prompt).
#                Network: Anthropic. ~1-2 min.
#   post         Main. ~/.pi/agent, ~/.dsh and ~/.codex vs pre (any difference FAILs). <5 s.
#   suite        Main, OPTIONAL: A ran the full suite (c9d68f31: 3 failed, 3696 passed, 60 skipped; see validation report).
#                This is Main's own confirmation. First STOPs, writing
#                nothing, unless T=<Harness>/tmp/592 can be created and written (suite-base too). GraphTraj's full suite of
#                GCOMMIT (a clean clone in T, not this Worktree: uncommitted edits cannot leak in) with graftling
#                49f97004 as a WHEEL and GraphTraj editable from that clone; scripts/run_test_shards.py, 6 shards,
#                --timeout 1500, -rA, in the BACKGROUND (~25 min). pytest's temp root is a fresh directory under
#                TMPDIR=${TMPDIR:-/tmp}, outside the Harness (checked and printed). Dialog: none. No login.
#   SR           Read only: the newest suite's FAILED/ERROR node ids (whole ids, scripts/verify-581/suiteids.py), each
#                marked 'listed in 516' (Task 516's CURRENT definition, read through its task.yml current_definition)
#                or 'not in 516'; ALL of them go to failed-ids.txt and to the ready-to-paste suite-base command (each id
#                a separate shell-quoted argument). test_runtime_distribution::test_wheels_have_separate_owners gets a
#                NOTE: candidate version label 0.8.0; resolved by 593. Dialog: none. (optional: A ran the full suite)
#   suite-base   Main, optional (A ran the full suite), only if SR lists failures: the ids on base GraphTraj bfed0c4c with graftling 542a81df (0.8.0)
#                as a WHEEL, then on GCOMMIT with graftling 49f97004; per id: fails on both (also fails on base) |
#                candidate-only (NEW unless listed in 516) | ... Dialog: none. No login.
# Order: pre, install, cli, pi-main, [claude-pre, claude-main], post. suite, SR (suite-base) are optional (A ran the
# full suite) and need no ROOT, no key, no login. No push step: the backup to LUOXIAO92/graphtraj is the Leader's/Main's integration step.
# Preflight: every host answers a one-line prompt naming its configured model and login before it is used: Pi in pre,
# Claude in claude-pre. No probe Task is needed (tasks discover and the two refusals need none).
# Credentials: every pi process runs in an ALLOWLISTED environment (launch: HOME USER LOGNAME SHELL TERM LANG LC_ALL
# LC_CTYPE TMPDIR PATH, PI_CODING_AGENT_DIR, the step's own VAR=value, and DEEPSEEK_API_KEY for pi only); a guard
# STOPs (exit 97, names only) if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* other than DEEPSEEK_API_KEY is left.
# The key is never printed and never an argument. The Claude Mains run in their own allowlist (callow: PATH, HOME
# (yours: the login needs it), USER, LOGNAME, SHELL, TMPDIR, LANG); DEEPSEEK_API_KEY does not reach them.
# The user's Claude login (claude-* only; STOP without VERIFY592_CLAUDE_USER_LOGIN=1): Claude Code reads the macOS
# keychain login and ~/.claude.json, and may itself write Session transcripts under
# ~/.claude/projects/-private-tmp-graphtraj-592-*/, entries under ~/.claude/sessions and ~/.claude.json. These
# steps' own commands write nothing under ~/.claude, ~/.codex, ~/.pi, ~/.dsh or to dotfiles.
# Writes: ROOT (real-host steps), T (suite venvs, clones, outputs), OUT (copies of every step's output) and pytest's
# temp roots under TMPDIR. VERIFY592_ROOT / _OUT / _T / _BIN (rehearsal stubs first on PATH) / _USERHOME / _GCOMMIT /
# _PIMODEL / _PYTEST_ARGS / _NO_PS are for the Engineer's rehearsal only; a run with any of them set is a rehearsal,
# not acceptance evidence.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY592_ROOT:-/private/tmp/graphtraj-592}
T=${VERIFY592_T:-$H/tmp/592}                        # suite venvs, clones and outputs
OUT=${VERIFY592_OUT:-$H/.graphtraj/core/state/tasks/592-graphtraj-rename-agents-to-subagents/realhost}
GREPO=$H/graftling                                  # the local graftling repository (read only)
LCAND=49f97004a86cc245ad32515b9dd056d7092b08f7      # graftling candidate (591, accepted; dev), version string 0.8.0
LBASE=542a81df0c941f5b1a425d9807681b2a38daa87c      # graftling v0.8.0, the base's graftling
GTBASE=bfed0c4c                                     # GraphTraj dev, this Task's base (expanded below)
GCOMMIT=${VERIFY592_GCOMMIT:-c9d68f31ea1bf5a23ada6157d084f6edaf7ed60c}  # GraphTraj candidate (A final; code as 3f8207b6)
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: click, PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
JUDGE=${0:A:h}/judge.py
ISO=$WT/scripts/verify-common/claude_isolation.py
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
UH=${VERIFY592_USERHOME:-$HOME}                     # your home: its .pi/agent, .dsh and .codex are only read
PIAGENT=$ROOT/pi-agent                              # isolated Pi agent directory of every pi command here
PIMODELF=$ROOT/pi-model.txt                         # the deepseek flash id (pre)
V=$ROOT/venv                                        # GraphTraj GCOMMIT + graftling LCAND, wheels
P=$ROOT/proj                                        # the Pi Main's project
PC=$ROOT/proj-claude                                # the Claude Main's project
EXT=$V/lib/python3.13/site-packages/graphtraj/runtimes/pi/extension.mjs
MMODEL=claude-haiku-5-5                             # the Claude Main's model (as 591)
THIS=${0:A}
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
PIPATH=${VERIFY592_BIN:+$VERIFY592_BIN:}/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
path=(${VERIFY592_BIN:+$VERIFY592_BIN} /opt/homebrew/bin $path)
CLAUDE=''
GTBASE=$(git -C $WT rev-parse --verify -q "$GTBASE^{commit}" || print -r -- $GTBASE)

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
gcommit() {
  [[ -n $GCOMMIT ]] || { print -r -- "STOP: GCOMMIT is not set yet in this script (the GraphTraj candidate is not final)"; return 1; }
  git -C $WT cat-file -e "$GCOMMIT^{commit}" 2>/dev/null || { print -r -- "STOP: GraphTraj $GCOMMIT is not in $WT"; return 1; }
}
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set (every Pi run here uses it). Fix:"
  print -r -- "  export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"; return 1
}
# ALLOWLIST launch (as verify-583): in a subshell every exported name outside ALLOW is unset, then
# PI_CODING_AGENT_DIR and the step's own VAR=value are exported (DEEPSEEK_API_KEY only with --key, and only from your
# environment). A guard STOPs (exit 97, names only) if another provider-credential-like name is left.
ALLOW=(HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE TMPDIR PATH)
launch() {  # [--key | --plain] [VAR=value...] -- command...   (--plain: the suite's: your PATH, no Pi agent dir)
  local key=0 plain=0; [[ ${1:-} == --key ]] && { key=1; shift; }; [[ ${1:-} == --plain ]] && { plain=1; shift; }
  local -a add=(); while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done
  (( $# )) && shift
  (
    local n
    for n in ${(k)parameters[(R)*export*]}; do
      (( ${ALLOW[(Ie)$n]} )) && continue
      [[ $n == DEEPSEEK_API_KEY ]] && (( key )) && continue
      unset $n 2>/dev/null
    done
    (( plain )) || export PATH=$PIPATH PI_CODING_AGENT_DIR=$PIAGENT
    for n in $add; do export "$n"; done
    local -a bad=(${(M)${(k)parameters[(R)*export*]}:#(*_API_KEY|*_TOKEN|*_BASE_URL|*_AUTH*)})
    bad=(${bad:#DEEPSEEK_API_KEY})
    (( $#bad )) && { print -u2 -r -- "STOP: provider credential names in the launch environment: $bad"; exit 97; }
    exec "$@"
  )
}
# A Claude Code Main's allowlisted environment (as verify-591): your HOME (the login), no graftling/GraphTraj markers.
callow() {
  local -a add=()
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k u=$HOME us=${USER:-$(id -un)} sh=${SHELL:-/bin/zsh} t=$PYTEST_TMP
    for k in ${(k)parameters[(R)*export*]}; do unset $k 2>/dev/null; done
    export PATH=${CLAUDE:h}:$PIPATH HOME=$u USER=$us LOGNAME=$us SHELL=$sh TMPDIR=$t LANG=en_US.UTF-8
    (( $#add )) && export "${add[@]}"
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,USER,LOGNAME,SHELL,TMPDIR,LANG${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# Your locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh and ~/.codex), never contents.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  ls -laT $UH/.codex 2>&1 | awk 'NF >= 10 && $10 != ".." {print "codex", $6, $7, $8, $9, $10}'
}
pi_flags() {
  [[ -s $PIMODELF ]] || { print -r -- "STOP: $PIMODELF missing; run: rm -rf $ROOT && zsh $THIS pre" >&2; return 1; }
  PIFLAGS=(--provider deepseek --model $(<$PIMODELF))
}
copy_deps() {  # click, yaml, websockets from <Harness>/.venv-runtime into venv $1 when it lacks them (read only)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $1/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
# ROOT/venv: GraphTraj GCOMMIT and graftling LCAND, both WHEELS built offline from git archives (as uv tool install).
build_venv() {
  local S=$ROOT/venv-src
  [[ -f $V/installed && $(<$V/installed) == "$GCOMMIT $LCAND"* ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf $V $S && mkdir -p $S/graphtraj $S/graftling $S/wheels || return 1
  git -C $WT archive $GCOMMIT | tar -x -C $S/graphtraj || { print -r -- "STOP: GraphTraj $GCOMMIT not found"; return 1; }
  git -C $GREPO archive $LCAND | tar -x -C $S/graftling || { print -r -- "STOP: graftling $LCAND not found"; return 1; }
  $CONDA -m venv $V && copy_deps $V || return 1
  $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling $S/graphtraj > $S/wheel.txt 2>&1 || { tail -5 $S/wheel.txt; return 1; }
  # graftling 49f97004 still reports 0.8.0 (593 sets 0.9.0), so GraphTraj's graftling>=0.9.0,<0.10 cannot resolve:
  # both wheels are installed side by side with --no-deps (no resolver, no override file).
  print -r -- "pip install --no-deps --no-index $(print -l -- $S/wheels/*.whl(:t) | tr '\n' ' ')(both wheels side by side; no resolver)"
  $V/bin/python -m pip install $PIP $S/wheels/*.whl || return 1
  local got; got=$(cd / && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__, "| graftling", graftling.__file__)') \
    || { print -r -- "STOP: $V cannot import graphtraj and graftling"; return 1; }
  [[ $got == *"$V/"*"$V/"* ]] || { print -r -- "STOP: not both imported from $V: $got"; return 1; }
  [[ -f $EXT ]] || { print -r -- "STOP: $EXT missing"; return 1; }
  print -r -- "$GCOMMIT $LCAND | wheels: $(print -l -- $S/wheels/*.whl(:t) | tr '\n' ' ')| $got" > $V/installed
  print -r -- "$V: $(<$V/installed)"
}
# A git project set up through GraphTraj's public entry (`graphtraj setup`, its dev question answered y).
mkproject() {  # dir
  local d=$1
  rm -rf $d && mkdir -p $d && git -C $d init -q -b main && print -r -- "# verify-592 ${d:t}" > $d/README.md \
    && git -C $d add README.md && git -C $d -c user.name=verify-592 -c user.email=verify-592@example.invalid commit -q -m init \
    || return 1
  say "graphtraj setup in $d (its question 'Create dev from ...? [y/N]' is answered y on stdin)"
  (cd $d && print y | launch PATH=$V/bin:$PIPATH -- $V/bin/graphtraj setup 2>&1 | tail -4)
  [[ -f $d/.graphtraj/config.yml && -d $d/.graphtraj/runner ]] && pass "$d has GraphTraj Config and runner" \
    || { fail "graphtraj setup did not create $d/.graphtraj/config.yml"; return 1; }
  (cd $d && launch PATH=$V/bin:$PIPATH -- $V/bin/graphtraj doctor 2>&1 | tail -3)
  return 0
}
prompt() {
  print -r -- 'Use only the MCP tools mcp__graphtraj__subagents and mcp__graphtraj__tasks. Make exactly these five calls, in this order, each exactly once, with exactly the input given (JSON). Some calls are expected to return an error: do not retry, do not change any input and do not make any other call.'
  local n=1 line; for line in ${(f)"$(python3 -I $JUDGE probes)"}; do print -r -- "$n. $line"; (( n++ )); done
  print -r -- 'Then reply with one line per call: CALL <n>: ok, or the first line of its error. Then one line TOOLS: the names of all your tools whose names start with mcp__, comma separated.'
}
# --- Claude Code (as verify-591) ---
login_gate() {
  [[ -n ${VERIFY592_CLAUDE_USER_LOGIN:-} ]] || {
    print -r -- "STOP: this step uses the user's own Claude login; Main asks the user first, then runs:"
    print -r -- "  VERIFY592_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"
    return 1 }
  CLAUDE=$(command -v claude)
  [[ -n $CLAUDE ]] || { print "STOP: no claude on PATH"; return 1; }
  print -r -- "claude: $CLAUDE $($CLAUDE --version 2>&1 | head -1)"
  print -r -- "VERIFY592_CLAUDE_USER_LOGIN=1: Claude Code uses the user's own login. It reads the keychain and ~/.claude.json."
  print -r -- "Claude Code itself may write Session transcripts under ~/.claude/projects/-private-tmp-graphtraj-592-*/,"
  print -r -- "entries under ~/.claude/sessions, and ~/.claude.json. This step's own commands write nothing under ~/.claude."
}
claude_outside() {  # names only
  print -r -- "~/.claude/projects directories naming ${ROOT:t}: $(print -l -- $HOME/.claude/projects/*${ROOT:t}*(N/:t) | tr '\n' ' ')"
  python3 -I -c 'import json, sys
p = json.load(open(sys.argv[1])).get("projects") or {}
print("~/.claude.json project keys under", sys.argv[2] + ":", [k for k in p if k.startswith(sys.argv[2])])' \
    $HOME/.claude.json ${ROOT:A} 2>&1
}
# --- suite (as verify-586, but from clean clones at fixed commits) ---
others() {
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1); then
    [[ ${VERIFY592_NO_PS:-} == 1 ]] && { print -u2 -r -- "NOTE: ps cannot list processes here; check skipped (VERIFY592_NO_PS=1, rehearsal)"; return 0; }
    print -r -- "ps cannot list processes here ($listed); run this script in your own terminal"; return 0
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -v grep || true
}
outside() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
t_ready() {  # STOP unless T exists or can be created, and accepts a file
  local probe=$T/.write-check-$$
  if mkdir -p $T 2>/dev/null && : > $probe 2>/dev/null; then rm -f $probe; print -r -- "T=$T is writable"; return 0; fi
  print -r -- "STOP: $T is not writable here (the suite's venvs, clones and outputs go there). Run this step where"
  print -r -- "  $T can be created and written (your own terminal), or report this line; nothing was written."
  return 1
}
run_root() {  # label; sets RUNTMP: a fresh pytest temp root under TMPDIR, outside the Harness, no Harness marker above
  outside || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-592-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
}
clone_at() {  # dir commit: a clean clone of this repository at commit (never this Worktree's files)
  local B=$1 c=$2
  if [[ ! -d $B/.git || $(git -C $B rev-parse HEAD 2>/dev/null) != $c || -n $(git -C $B status --porcelain 2>/dev/null) ]]; then
    rm -rf -- $B && git clone -q --template= --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $c || { print -r -- "STOP: cannot check out $c in $B"; return 1; }
  fi
  print -r -- "checkout: $B at $(git -C $B log --oneline -1) (clean: $([[ -z $(git -C $B status --porcelain) ]] && print yes || print NO))"
}
suite_venv() {  # venv graphtraj-checkout graftling-commit: graftling as a WHEEL, GraphTraj editable from the clone
  local SV=$1 gt=$2 lc=$3 S=$1-src
  [[ -x $SV/bin/python && -f $SV/installed && $(<$SV/installed) == "$lc $gt"* ]] && { print -r -- "reusing $SV ($(<$SV/installed))"; return 0; }
  rm -rf -- $SV $S && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $lc | tar -x -C $S/graftling || { print -r -- "STOP: graftling $lc not found"; return 1; }
  $CONDA -m venv --system-site-packages $SV && copy_deps $SV || return 1
  $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null || return 1
  $SV/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && $SV/bin/python -m pip install $PIP -e $gt || return 1
  print -r -- "$lc $gt (graftling wheel + graphtraj editable)" > $SV/installed; print -r -- "$SV: $(<$SV/installed)"
}
versions() {  # venv: what it imports, from the pytest temp root
  # Both graftling commits say 0.8.0; TOOL_NAME tells them apart (542a81df: agents, 49f97004: subagents).
  (cd $RUNTMP && $1/bin/python -I -c 'import graphtraj, graftling, graftling.tool as t, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, "TOOL_NAME", t.TOOL_NAME, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))')
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. Network: api.deepseek.com. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  gcommit && key_ready || return 1
  mkdir -p $PIAGENT $ROOT/out $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  local t; for t in node pi git; do print -r -- "$t: $(command -v $t) $(launch -- $t --version < /dev/null 2>&1 | head -1)"; done
  print -r -- "GraphTraj candidate $GCOMMIT: $(git -C $WT log --format=%s -1 $GCOMMIT | cut -c1-90)"
  print -r -- "GraphTraj base $GTBASE: $(git -C $WT log --format=%s -1 $GTBASE | cut -c1-90)"
  # The wheels are built from GCOMMIT (git archive); this shows the checkout Main runs from equals it outside verify-592.
  say "git diff --stat $GCOMMIT HEAD (this Worktree, $(git -C $WT rev-parse HEAD)):"
  git -C $WT diff --stat $GCOMMIT HEAD
  local -a other=(${(f)"$( { git -C $WT diff --name-only $GCOMMIT HEAD; git -C $WT diff --name-only HEAD; } | grep -v '^scripts/verify-592/' | sort -u)"})
  if [[ -n ${VERIFY592_NO_DIFF_CHECK:-} ]]; then
    print -r -- "REHEARSAL: diff check skipped (VERIFY592_NO_DIFF_CHECK); differing paths outside scripts/verify-592: ${#other}"
  elif (( $#other )); then
    print -r -- "FAIL: the Worktree differs from GCOMMIT outside scripts/verify-592 (committed or not): $other"
    print -r -- "STOP: the installed candidate would not equal this checkout; report this to the Leader."; return 1
  else pass "the Worktree equals GCOMMIT outside scripts/verify-592 (committed and uncommitted)"; fi
  git -C $GREPO cat-file -e "$LCAND^{commit}" 2>/dev/null || { print -r -- "STOP: graftling $LCAND not in $GREPO"; return 1; }
  print -r -- "graftling candidate $LCAND: $(git -C $GREPO log --format=%s -1 $LCAND | cut -c1-90)"
  [[ -d $RTSP/websockets && -d $RTSP/yaml && -d $RTSP/click ]] || { print -r -- "STOP: $RTSP lacks click, websockets or yaml"; return 1; }
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  say "names in a Pi launch environment (values never printed)"
  launch --key EXAMPLE_STEP_VAR=1 -- /usr/bin/env | cut -d= -f1 | sort | tr '\n' ' '; print
  local leaked=$(launch --key -- /usr/bin/env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | grep -vx DEEPSEEK_API_KEY)
  [[ -z $leaked ]] && pass "no provider credential other than DEEPSEEK_API_KEY reaches Pi" || { print -r -- "STOP: leaked names: $leaked"; return 1; }
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "the Pi model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$PIAGENT)"
  local listed; listed=$(cd $ROOT && launch --key -- perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  if [[ -n ${VERIFY592_PIMODEL:-} ]]; then print -r -- $VERIFY592_PIMODEL > $PIMODELF
  else print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $PIMODELF; fi
  [[ -s $PIMODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pi_flags || return 1
  # Pin the isolated agent dir to DeepSeek flash, so a Session that names no model cannot pick another provider.
  print -r -- "{\"defaultProvider\": \"deepseek\", \"defaultModel\": \"$(<$PIMODELF)\", \"enabledModels\": [\"deepseek/$(<$PIMODELF)\"]}" > $PIAGENT/settings.json
  print -r -- "pinned $PIAGENT/settings.json: $(<$PIAGENT/settings.json)"
  say "one-line Pi prompt: pi -p $PIFLAGS --no-session --no-extensions --no-tools (in $ROOT)"
  (cd $ROOT && launch --key -- perl -e 'alarm shift; exec @ARGV' 120 pi -p $PIFLAGS --no-session --no-extensions --no-tools \
     "Reply in one line: the exact model id and the provider you are running as, nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc (login: DEEPSEEK_API_KEY from the allowlisted environment)"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer with $PIFLAGS; check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "Pi answered as deepseek/$(<$PIMODELF)"
  print -r -- "probe Tasks: none needed by any step"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. $V (GraphTraj $GCOMMIT + graftling $LCAND, wheels), $P (graphtraj setup, pi install -l). Dialog: none. No network."
  gcommit && need $PIMODELF pre || return 1
  OK=1
  build_venv || return 1
  (cd / && $V/bin/python -I -c 'import importlib.metadata as m
print("graphtraj", m.version("graphtraj"), "requires:", [r for r in m.requires("graphtraj") or [] if r.startswith("graftling")])
print("graftling", m.version("graftling"), "(591 candidate; its version string is not bumped until 593 releases 0.9.0)")
print("graftling console_scripts:", sorted(e.name for e in m.distribution("graftling").entry_points if e.group == "console_scripts"))
print("graphtraj graftling.hosts entry:", sorted(f"{e.name}={e.value}" for e in m.distribution("graphtraj").entry_points if e.group == "graftling.hosts"))
low = [r.split(">=")[1].split(",")[0] for r in m.requires("graphtraj") or [] if r.startswith("graftling") and ">=" in r]
if low and tuple(map(int, m.version("graftling").split(".")[:2])) < tuple(map(int, low[0].split(".")[:2])):
    print("NOTE: installed with --no-deps; a resolver would refuse graftling", m.version("graftling"), "here until its release carries", low[0], "(593)")')
  local -a have=($V/bin/(subagents|subagents-mcp|agents|agents-mcp|graphtraj-mcp)(N:t))
  print -r -- "console scripts present: $have"
  (( ${have[(Ie)subagents]} && ${have[(Ie)subagents-mcp]} && ${have[(Ie)graphtraj-mcp]} )) && pass "subagents, subagents-mcp and graphtraj-mcp are installed" || fail "a new console script is missing"
  (( ! ${have[(Ie)agents]} && ! ${have[(Ie)agents-mcp]} )) && pass "agents and agents-mcp are not installed" || fail "an old console script is installed"
  mkproject $P || return 1
  (cd $P && launch -- pi install -l $EXT < /dev/null 2>&1 | tail -1)
  [[ $(cat $P/.pi/settings.json 2>/dev/null) == *graphtraj/runtimes/pi/extension.mjs* ]] \
    && pass "$P/.pi/settings.json names $EXT" || fail "$P/.pi/settings.json does not name the extension"
  (( OK )) && print -r -- "next: zsh $THIS cli" || print -r -- "next: fix the FAIL above, then: zsh $THIS install"
  (( OK ))
  ;;
cli)
  say "[cli] Main. The installed graphtraj-mcp and hosted subagents CLI in $P. Dialog: none. No network, no login."
  gcommit && need $V/installed install && need $P/.graphtraj/config.yml install || return 1
  [[ $(<$V/installed) == "$GCOMMIT $LCAND"* ]] || { print -r -- "STOP: $V is not $GCOMMIT + $LCAND; rerun: zsh $THIS install"; return 1; }
  OK=1
  launch PATH=$V/bin:$PIPATH -- python3 -I $JUDGE mcp $V $P || OK=0
  say "hosted CLI: $V/bin/subagents '{\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{}}' in $P"
  local cli; cli=$(cd $P && launch PATH=$V/bin:$PIPATH -- $V/bin/subagents '{"action":"execute","feature":"status","arguments":{}}' < /dev/null 2>&1)
  print -r -- "exit=$? | ${cli[1,400]}"
  [[ $cli != *(#i)unknown\ feature* && $cli != *'does not belong'* ]] && pass "the hosted subagents CLI is routed through GraphTraj with no routing error" \
    || fail "the hosted subagents CLI hit a routing error"
  # Whole words: the new form 'subagents needs a verified caller' contains the old one as a substring.
  [[ $cli != (*[^[:alnum:]_-]|)'agents needs a verified caller'* && $cli != *'read-only agents access'* ]] \
    && pass "the hosted CLI's answer has neither old form ('agents needs a verified caller', 'read-only agents access')" \
    || fail "the hosted CLI's answer still says an old form (Leader decision: FAIL)"
  local rd=$V/lib/python3.13/site-packages/graphtraj/configuration/role_definitions.py
  local roles=$(grep -n -E '`(sub)?agents` tool' $rd)
  print -r -- "installed role_definitions lines naming a tool: ${roles//$'\n'/ | }"
  [[ $roles == *'`subagents` tool'* && $roles != *'`agents` tool'* ]] && pass "every child role's system text names the \`subagents\` tool, not \`agents\`" \
    || fail "role_definitions does not name only the \`subagents\` tool"
  (( OK )) && print -r -- "next: zsh $THIS pi-main" || print -r -- "next: inspect the FAIL lines above; rerun: zsh $THIS cli"
  (( OK ))
  ;;
pi-main)
  say "[pi-main] Main. A real GraphTraj Pi Main (DeepSeek) in $P makes the five calls. Dialog: none. ~1-3 min."
  key_ready && pi_flags && need $P/.pi/settings.json install || return 1
  local SD=$ROOT/sessions/pi-main SOUT=$ROOT/out/pi-main.txt
  rm -rf $SD $SOUT; mkdir -p $SD ${SOUT:h}
  prompt > $ROOT/out/pi-main-prompt.txt
  print -r -- "prompt ($ROOT/out/pi-main-prompt.txt):"; cat $ROOT/out/pi-main-prompt.txt
  say "pi -p $PIFLAGS --session-dir $SD --approve '<prompt>'  (in $P; PI_CODING_AGENT_DIR=$PIAGENT; PATH starts $V/bin)"
  (cd $P && launch --key PATH=$V/bin:$PIPATH -- perl -e 'alarm shift; exec @ARGV' 300 \
     pi -p $PIFLAGS --session-dir $SD --approve "$(<$ROOT/out/pi-main-prompt.txt)" < /dev/null) > $SOUT 2>&1
  local src=$?
  tail -12 $SOUT; print -r -- "pi exit=$src (full output: $SOUT)"
  local -a sf=($SD/**/*.jsonl(N.))
  cp $SOUT $OUT/ 2>/dev/null; (( $#sf )) && cp $sf[1] $OUT/pi-main.session.jsonl 2>/dev/null
  say "verdict (computed from the Pi Session file)"
  OK=1
  (( src == 0 )) && pass "the Pi Main exited 0" || fail "the Pi Main exited $src"
  python3 -I $JUDGE pi $SD $SOUT || OK=0
  print -r -- "follow-up (paste): python3 -I $JUDGE pi $SD $SOUT"
  if (( OK )); then
    print -r -- "SUCCESS: a real GraphTraj Pi Main was offered mcp__graphtraj__subagents and mcp__graphtraj__tasks, no old name, and called the new name"
    print -r -- "next: VERIFY592_CLAUDE_USER_LOGIN=1 zsh $THIS claude-pre   (optional; Main asks the user first)   or: zsh $THIS post"
  else print -r -- "next: inspect $SOUT and $SD; then rerun: zsh $THIS pi-main"; fi
  (( OK ))
  ;;
claude-pre)
  say "[claude-pre] Main, optional. One-line claude -p with the Mains' flags and environment. Dialog: none expected. ~30 s."
  need $V/installed install || return 1
  login_gate || return 1
  mkdir -p $ROOT/claude-pre $ROOT/out && python3 -I $ISO settings $H $ROOT/claude-pre || return 1
  [[ $($CLAUDE --help 2>&1) == *--plugin-dir* ]] && pass "claude --help offers --plugin-dir" || { print "STOP: claude --help offers no --plugin-dir"; return 1; }
  local pr=$ROOT/out/claude-pre-prompt.txt out=$ROOT/out/claude-pre.jsonl
  python3 -I $ISO prompt V592 > $pr
  say "claude -p --setting-sources project,local --strict-mcp-config --model $MMODEL --output-format stream-json --verbose < $pr (in $ROOT/claude-pre)"
  (cd $ROOT/claude-pre && callow -- $CLAUDE -p --setting-sources project,local --strict-mcp-config --model $MMODEL \
     --output-format stream-json --verbose < $pr > $out 2> $out.err)
  local crc=$?; print -r -- "exit=$crc"; cp $out $out.err $OUT/ 2>/dev/null
  python3 -I $ISO check $out V592 $H $ROOT/claude-pre $pr; local ic=$?
  claude_outside
  (( crc == 0 && ic == 0 )) || { print -r -- "STOP: Claude Code did not answer cleanly (above); check its login, then rerun: VERIFY592_CLAUDE_USER_LOGIN=1 zsh $THIS claude-pre"; return 1; }
  print -r -- "next: VERIFY592_CLAUDE_USER_LOGIN=1 zsh $THIS claude-main"
  ;;
claude-main)
  say "[claude-main] Main, optional. configuration --write in $PC; a real Claude Code GraphTraj Main makes the five calls. Dialog: none expected. ~1-2 min."
  gcommit && need $V/installed install || return 1
  [[ -e $ROOT/out/claude-pre.jsonl ]] || { print -r -- "STOP: claude-pre has not run in $ROOT; run: VERIFY592_CLAUDE_USER_LOGIN=1 zsh $THIS claude-pre"; return 1; }
  login_gate || return 1
  OK=1
  mkproject $PC && python3 -I $ISO settings $H $PC || return 1
  (cd $PC && launch PATH=$V/bin:$PIPATH -- $V/bin/python -I -m graphtraj.runtimes.claude.host configuration --project $PC --claude $CLAUDE --write > /dev/null) \
    || { print "STOP: configuration --write failed"; return 1; }
  python3 -I $ISO settings $H $PC || return 1
  local pd=$PC/.claude/skills/graphtraj-claude-host
  [[ -f $pd/.claude-plugin/plugin.json ]] || { print -r -- "STOP: no written host plugin at $pd"; return 1; }
  print -r -- "written: $(cd $PC && print -l -- .mcp.json(N) .claude/**/*(N.D) .graphtraj/claude-host/config.json(N) | tr '\n' ' ')"
  print -r -- ".mcp.json servers: $(python3 -I -c 'import json, sys; s = json.load(open(sys.argv[1]))["mcpServers"]; print({k: v.get("args") for k, v in s.items()})' $PC/.mcp.json)"
  python3 -I $JUDGE hook $pd || OK=0
  local out=$ROOT/out/claude-main-$(date +%H%M%S).jsonl
  prompt > $ROOT/out/claude-main-prompt.txt
  local -a LAUNCH=(-p --setting-sources project,local --strict-mcp-config --mcp-config $PC/.mcp.json --plugin-dir $pd
                   --model $MMODEL --allowedTools mcp__graphtraj__subagents,mcp__graphtraj__tasks --output-format stream-json --verbose)
  say "claude ${LAUNCH[*]} < $ROOT/out/claude-main-prompt.txt   (in $PC; environment names: PATH HOME USER LOGNAME SHELL TMPDIR LANG)"
  (cd $PC && callow -- perl -e 'alarm shift; exec @ARGV' 300 $CLAUDE $LAUNCH < $ROOT/out/claude-main-prompt.txt > $out 2> $out.err)
  local mrc=$?
  print -r -- "Main exit=$mrc (stream: $out; stderr: $out.err, $(wc -l < $out.err | tr -d ' ') lines)"
  cp $out $out.err $OUT/ 2>/dev/null
  say "verdict (computed from the stream-json)"
  (( mrc == 0 )) && pass "the Claude Main exited 0" || fail "the Claude Main exited $mrc"
  python3 -I $JUDGE claude $out || OK=0
  print -r -- "host log (last lines): $(tail -3 $PC/.graphtraj/claude-host/host.log 2>/dev/null | tr '\n' ' ')"
  claude_outside
  print -r -- "follow-up (paste): python3 -I $JUDGE claude $out"
  (( OK )) && print -r -- "SUCCESS: a real Claude Code GraphTraj Main was offered the two new names, no old name, and called the new name"
  print -r -- "next: zsh $THIS post"
  (( OK ))
  ;;
post)
  say "[post] Main. Your ~/.pi/agent, ~/.dsh and ~/.codex vs pre (any difference FAILs). <5 s. Dialog: none."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh and ~/.codex unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT/out, $ROOT/sessions (copied to $OUT). To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
suite)
  setopt local_options no_bg_nice
  gcommit || return 1
  say "[suite] Main, optional: A ran the full suite. GraphTraj full suite of $GCOMMIT (clean clone) + graftling $LCAND (wheel); 6 shards, --timeout 1500, -rA, background ~25 min. Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg 2>/dev/null || print unavailable)"
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $o; return 1; }
  t_ready && run_root suite || return 1
  local C=$T/graphtraj-cand SV=$T/venv-cand
  clone_at $C $GCOMMIT || return 1
  suite_venv $SV $C $LCAND || return 1
  versions $SV || return 1
  local R=$T/suite-${GCOMMIT[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness) | GraphTraj $GCOMMIT (clean clone $C) | graftling $LCAND (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY592_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${(j: :)${(@qq)extra}}" >> $R/run.txt
  cat $R/run.txt
  # The background run writes only its own files; it holds no descriptor of this step's output (tee would wait).
  (cd $C && launch --plain TMPDIR=$RUNTMP -- $SV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) < /dev/null > /dev/null 2>&1 &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "writes: $T ($C, $SV, $R) and $RUNTMP only. dialog: none."
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: the newest suite; FAILED/ERROR node ids, each marked against 516's current definition. Dialog: none."
  local cur=${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  local K=$D516/$cur
  print -r -- "516 current definition (task.yml current_definition): $K"
  [[ -n $cur && -f $K ]] || { print -r -- "STOP: cannot read 516's current definition '$K'"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet); next: zsh $THIS SR (later)"; return 1; }
  local -a logs=($g/shards/*.log(N.)); (( $#logs )) || logs=($g/suite.txt)
  local id t line bad=0; local -a ids=()
  for id in ${(f)"$(python3 -I $SUITEIDS ids $logs)"}; do
    [[ -n $id ]] || continue
    t=${id%%\[*}; ids+=$id; bad=1
    if grep -qF -- "${t##*::}" $K; then print -r -- "listed in 516: $id"; else print -r -- "not in 516: $id"; fi
    [[ $t == *test_runtime_distribution.py::test_wheels_have_separate_owners ]] \
      && print -r -- "NOTE: $id: candidate version label 0.8.0; resolved by 593 (A showed it passes with a 0.9.0-labelled wheel)"
  done
  print -l -- $ids > $g/failed-ids.txt
  (( $#ids )) || print -r -- "(no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; bad=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; bad=1 ;;
    esac
  done
  grep -hE '^(=+ )?[0-9]+ (passed|failed)' $g/shards/*(N.) | sed -E 's/^=+ //; s/ =+$//'
  mkdir -p $OUT 2>/dev/null && cp $g/run.txt $g/failed-ids.txt $OUT/ 2>/dev/null && cp $g/suite.txt $OUT/suite-${g:t}.txt 2>/dev/null
  print -r -- "SR verdict: $( (( bad == 0 )) && print 'PASS (no FAILED/ERROR line, no ABNORMAL shard)' || print "FAILURES ($#ids ids; classify with suite-base)")$(grep -q '^REHEARSAL' $g/run.txt && print ' — FILTERED rehearsal run')"
  print -r -- "failing node ids ($#ids, one per line): $g/failed-ids.txt"
  if (( $#ids )); then
    # Each id its own single-quoted word ((@qq) quotes element by element).
    print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)ids}"
    print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)g}/failed-ids.txt"
  else
    print -r -- "next: none; report the SR verdict"
  fi
  return $bad
  ;;
suite-base)
  setopt local_options no_bg_nice
  gcommit || return 1
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then
    [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file '${IDS[2]:-}'; SR writes it (failed-ids.txt)"; return 2; }
    ids=(${(f)"$(<${IDS[2]})"})
  else ids=("${(@)IDS}"); fi
  ids=(${ids:#})
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>...   (SR prints both)"; return 2; }
  say "[suite-base] Main, optional: A ran the full suite. $#ids node ids: base (GraphTraj $GTBASE + graftling $LBASE), then candidate (GraphTraj $GCOMMIT + graftling $LCAND). Dialog: none. No login."
  print -l -- "  id: "${^ids}
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun this command later"; print -r -- $o; return 1; }
  t_ready || return 1
  local B=$T/graphtraj-base C=$T/graphtraj-cand VB=$T/venv-base VC=$T/venv-cand
  clone_at $B $GTBASE && clone_at $C $GCOMMIT || return 1
  suite_venv $VB $B $LBASE && suite_venv $VC $C $LCAND || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R || return 1
  print -l -- $ids > $R/ids.txt
  local side dir SV rc
  for side dir SV in base $B $VB candidate $C $VC; do
    run_root $side || return 1
    say "$side: pytest in $dir; $(versions $SV)"
    (cd $dir && launch --plain TMPDIR=$RUNTMP -- $SV/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $R/$side-collected.txt 2>&1)
    python3 -I $SUITEIDS present $R/$side-collected.txt $R/ids.txt > $R/$side-ids.txt 2> $R/$side-missing.txt
    [[ -s $R/$side-missing.txt ]] && print -r -- "not on $side (not run there): $(tr '\n' ' ' < $R/$side-missing.txt)"
    local -a run=(${(f)"$(<$R/$side-ids.txt)"})
    if (( $#run )); then
      (cd $dir && launch --plain TMPDIR=$RUNTMP -- $SV/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $R/$side.txt 2>&1); rc=$?
    else print -r -- "(no id present on $side)" > $R/$side.txt; rc=5; fi
    print -r -- "$side: pytest exit=$rc, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $R/$side.txt | tail -1) (output: $R/$side.txt)"
    python3 -I $SUITEIDS errors $R/$side.txt > $R/$side-errors.txt
  done
  say "classification (each id: base, then candidate); a candidate-only id is NEW unless SR marked it 'listed in 516'"
  python3 -I $SUITEIDS classify $R/ids.txt $R/base.txt $R/candidate.txt | tee $R/classification.txt; local fails=${pipestatus[1]}
  mkdir -p $OUT 2>/dev/null && cp -R $R $OUT/ 2>/dev/null
  print -r -- "first E line + raise location per failing test: $R/base-errors.txt and $R/candidate-errors.txt"
  print -r -- "writes: $T ($B, $C, venvs, $R), a copy in $OUT/${R:t} and pytest temp roots under $PYTEST_TMP only. dialog: none."
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|install|cli|pi-main|claude-pre|claude-main|post|suite|SR|suite-base --from <file>|<ids>..."; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY592_OUT:-} ]] || { print "STOP: $H is not the Harness root"; exit 1; }
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
PIFLAGS=()
mkdir -p $OUT 2>/dev/null
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
{ run_step; print -r -- "STEP-END $STEP rc=$?"; } 2>&1 | tee $OUT/$STEP.txt
rc=$?
grep -q "^STEP-END $STEP rc=0\$" $OUT/$STEP.txt || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT/$STEP.txt; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
exit $rc
