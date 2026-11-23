#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 581 Main-run steps: graftling is installed ONCE, with uv from GitHub, and DSH, Pi and Claude Code all attach to
# that one install (graftling-dsh, the Pi extension and Claude Code's generated plugin come from it; no second
# graftling, no $DSH_HOME/graftling-python, no GRAFTLING_PYTHON anywhere).
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre      Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions (uv, dsh,
#            pi, node, pnpm, claude, python3, git); the bundle verifies and its head is GCOMMIT; DEEPSEEK_API_KEY set
#            (STOP with the fix if not; never printed); `python3` on PATH does NOT import graftling (so any graftling
#            that runs later can only be the uv install); the 'before' state of your locations (below); one-line
#            prompts naming the model: DSH (DSH_HOME=ROOT/dsh-home), Pi (PI_CODING_AGENT_DIR=ROOT/pi-agent) and
#            Claude Code (CLAUDE_CONFIG_DIR=ROOT/claude-home, DeepSeek's Anthropic endpoint, judged by
#            scripts/verify-common/claude_isolation.py check). Dialog: none. ~1-2 min.
#   push     Main, ONLY after the user agreed. Pushes the candidate branch from the bundle to LUOXIAO92/graftling
#            (every author/committer must be the noreply identity, else STOP). Dialog: none expected; git uses
#            your usual GitHub login. ~30 s.
#   install  Main. Needs push (checks `git ls-remote`; STOP with the push command otherwise). THE ONLY graftling
#            install: uv tool install "git+https://github.com/LUOXIAO92/graftling.git@GCOMMIT" with UV_TOOL_DIR,
#            UV_TOOL_BIN_DIR, UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR under ROOT; prints the install's Python and
#            package directory; graftling's DSH model discovery with that Python. Then attaches each host as the
#            candidate's docs/install/*.md say: `dsh plugin --profile headless add "$DSH_PACKAGE"` (DSH_HOME=ROOT/
#            dsh-home, in ROOT/proj-dsh), `pi install -l "$PI_PACKAGE"` (in ROOT/proj-pi), and
#            `"$AGENTS_PYTHON" -m graftling.claude.host configuration --project ROOT/proj-claude --claude ... --write`
#            (+ claude_isolation settings, the project MCP server approval and folder trust that the documented
#            prompts would record, written into ROOT only, and a runtimes.dsh entry so the Claude Main can create a
#            dsh child). Dialog: none. ~1-3 min (uv downloads PyYAML and websockets from PyPI).
#   dsh      Main. DSH Main in ROOT/proj-dsh creates one dsh child, waits, reads status. Dialog: none. ~1-3 min.
#   pi       Main. Pi Main in ROOT/proj-pi, the same. Dialog: none. ~1-3 min.
#   claude   Main. Claude Code Main (`claude -p`, isolated, see below) in ROOT/proj-claude, the same. Dialog: none
#            (print mode shows no dialog). ~1-3 min.
#            Each of dsh / pi / claude, computed: the Main exited 0; association (one new record under the
#            project's .agents-control created by <host>-native, no authority-denied: the call-ownership check of
#            the host's hooks, the observable Task 570 used to show the hooks are required); child outcome
#            (completed with 'ready'); visibility (the LISTED ids are the host's own); completion notice (the
#            record's last execution notification is 'delivered' and the STATUS line says delivered); and every
#            Python process that ran graftling under the Session started from the uv install (process table).
#   single   Main. Read only: the single-source observables (no $DSH_HOME/graftling-python, nor any graftling-python
#            under ROOT; graftling-dsh in the DSH profile resolves into the uv install; Pi's settings name the uv
#            install's graftling/pi; Claude Code's .mcp.json / settings.local.json name the uv install's Python and
#            its plugin files equal the install's; exactly one installed graftling under ROOT; no GRAFTLING_PYTHON
#            in any host configuration). Dialog: none. <5 s.
#   post     Main. Your locations vs pre (any difference FAILs). Dialog: none. <5 s.
#   suite    Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a fresh venv under
#            <Harness>/tmp/581 with graftling built as a WHEEL from the candidate bundle (GCOMMIT) and GraphTraj
#            editable. pytest's temp root is under TMPDIR=${TMPDIR:-/tmp}, outside the Harness (checked, with the
#            Harness-marker guard). Dialog: none. No login. VERIFY581_PYTEST_ARGS='<args>' only appends pytest args
#            after `-- -rA` (rehearsal).
#   SR       Read only: the newest suite's FAILED/ERROR lines classed 'known (581 definition)' (the two
#            test_extension_in_a_worktree_never_spawns_the_collector ids), 'known (516)' (Task 516's CURRENT
#            definition, via its task.yml) or NEW; prints the ready-to-paste suite-base command. Dialog: none.
#   suite-base  Main, only if SR reports NEW: `zsh <this file> suite-base <node id>...` reruns exactly those node ids
#            on GraphTraj dev 24674e30 (a local git clone under <Harness>/tmp/581) with graftling built as a wheel
#            from dev a4f008f; per node id 'also fails on base' or 'candidate-only'. Dialog: none. No login.
# Order: pre, push (after the user agrees), install, dsh, pi, claude, single, post. suite, SR (and suite-base) may run
# before or after; they need no ROOT and no key and write only <Harness>/tmp/581/ and pytest's temp root.
# Third host: Claude Code, not Codex. Claude Code runs fully isolated in CLAUDE_CONFIG_DIR=ROOT/claude-home with
# DeepSeek's Anthropic-compatible endpoint (ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic, token from
# DEEPSEEK_API_KEY, exported inside the step's subshell, never on a command line): no Claude login, no keychain
# login, nothing under ~/.claude or ~/.claude.json. The Codex host has no isolated login with this key: it would use
# ~/.codex (CODEX_HOME) and your Codex login, and write Session files there.
# Login and credentials: only DEEPSEEK_API_KEY (never printed), for the DSH, Pi and Claude Code Mains and every dsh
# child (user decision: DeepSeek is the only provider). clean() removes EVERY exported variable whose name matches
# procs.py's CRED pattern (API_KEY, _KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL, _BASE_URL, provider prefixes...),
# known or not, except DEEPSEEK_API_KEY (and for Claude Code the ANTHROPIC_AUTH_TOKEN derived from it). `push` does
# not use clean(): git keeps your usual GitHub login. Each host step also checks, names only, never values:
#   observable 1  the credential-like names in the exact environment the Main gets ({DEEPSEEK_API_KEY}; Claude Code
#                 also ANTHROPIC_AUTH_TOKEN and its endpoint ANTHROPIC_BASE_URL, host printed); pre checks the same
#                 for its one-liners and install's model discovery; a failure STOPs before anything starts;
#   observable 2  every process under the Session (ps -E): FAIL if one holds another name from your environment or
#                 any provider-credential name; a token-like name a host set itself is printed as NOTE;
#   observable 3  provider/model/endpoint of the Main (DSH: files under DSH_HOME; Pi: --provider/--model and its
#                 Session files; Claude Code: ANTHROPIC_BASE_URL host and the init model) and of the child (its
#                 record's resolved_model and the files under <data root>/native): FAIL unless DeepSeek.
# Your locations, only read: ~/.pi/agent (names + sha256 prefixes), ~/.dsh (listing), ~/.claude/projects and
# ~/.claude.json project keys naming ROOT, ~/.local/share/uv/tools and ~/.local/bin/agents* (names), ~/.codex
# (files written since pre that name ROOT). `dsh plugin add` runs pnpm, which may add files to pnpm's own content
# store (pre prints `pnpm store path`). OUT keeps every Session output.
# VERIFY581_ROOT / _OUT / _BIN (rehearsal stubs) / _USERHOME / _DMODEL / _URL (a git+file repository instead of
# GitHub) / _GCOMMIT / _BUNDLE / _T / _PYTEST_ARGS / _UV_ARGS are for the Engineer's rehearsal only (stub/ holds
# stand-ins for dsh, pi, claude and ps). VERIFY581_CLAUDE_MODEL (pre) is Main's fallback if DeepSeek's Anthropic
# endpoint refuses the Pi flash id for Claude Code; pre says when to use it.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY581_ROOT:-/private/tmp/graftling-581}
OUT=${VERIFY581_OUT:-$H/.graphtraj/core/state/tasks/581-graftling-single-source-uv-install/realhost}
URL=${VERIFY581_URL:-https://github.com/LUOXIAO92/graftling.git}
BASE=a4f008f3712614cbdcae714ae46cad07c1f8de6e       # graftling dev before 581 (577 + 578)
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/581-graftling-single-source-uv-install
PINNED=e919de2e790433fea7ed25c07e61474f94ca1b3b    # the graftling candidate the Leader named (base: dev a4f008f)
BUNDLE=${VERIFY581_BUNDLE:-$WT/.scratch/581/graftling-581.bundle}
GCOMMIT=${VERIFY581_GCOMMIT:-$PINNED}
NOREPLY='89069722+LUOXIAO92@users.noreply.github.com'
JUDGE=$WT/scripts/verify-570/judge.py               # records on disk + the answer's lines (Task 570, unchanged)
PROCS=${0:A:h}/procs.py                             # which Python ran graftling under a Session (process table)
PROVIDERS=${0:A:h}/providers.py                     # provider, model and endpoint of each Main and child (files)
CREDRE=$(python3 -I $PROCS pattern)                 # credential-like names (one definition, in procs.py)
CSTREAM=${0:A:h}/claude_stream.py                   # a claude -p stream-json run -> summary + text for the judge
ISO=$WT/scripts/verify-common/claude_isolation.py   # Task 489 rule for Claude hosts in isolated projects
RTPY=$H/.venv-runtime/bin/python                    # read only: runs claude_isolation.py (no graftling use)
UH=${VERIFY581_USERHOME:-$HOME}                     # your home: the locations above are only read
DH=$ROOT/dsh-home                                   # isolated DSH home of every dsh command here
PIAGENT=$ROOT/pi-agent                              # isolated Pi agent directory of every pi command here
CH=$ROOT/claude-home                                # isolated CLAUDE_CONFIG_DIR of every claude command here
UVT=$ROOT/uv-tools UVB=$ROOT/uv-bin UVC=$ROOT/uv-cache UVP=$ROOT/uv-python   # the uv install, all inside ROOT
AGENTS_PYTHON=$UVT/graftling/bin/python             # = "$(uv tool dir)/graftling/bin/python" (docs)
PD=$ROOT/proj-dsh PP=$ROOT/proj-pi PC=$ROOT/proj-claude   # one project per host
MODELF=$ROOT/dsh-model.txt                          # the dsh child's model for the Pi and Claude Mains (install)
PIMODELF=$ROOT/pi-model.txt                         # the Pi Main's deepseek model id (pre)
CMODELF=$ROOT/claude-model.txt                      # the Claude Code Main's model id (pre)
DSURL=https://api.deepseek.com/anthropic            # DeepSeek's Anthropic-compatible endpoint (Claude Code Main)
THIS=${0:A}
STEP=${1:-}
# suite / SR / suite-base (modelled on verify-577).
T=${VERIFY581_T:-$H/tmp/581}                        # suite venvs, sources and outputs
GTREPO=$H/graphtraj                                 # the GraphTraj repository (read only): holds GTBASE
GTBASE=24674e308d9747f05bdaacded00ffabf83183857     # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN581=(tests/test_pi_attachment_private_paths.py::test_extension_in_a_worktree_never_spawns_the_collector'[plugin-child]'
          tests/test_pi_attachment_private_paths.py::test_extension_in_a_worktree_never_spawns_the_collector'[runner]')
# uv's tool bin is on PATH, as `uv tool install` asks; nothing else of ROOT is.
path=(${VERIFY581_BIN:+$VERIFY581_BIN} $UVB /opt/homebrew/bin ${path:#$ROOT/*} /Users/luoxiao/miniconda3/bin)
typeset -U path

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
# No inherited agents channel, explicit Python, host settings, Session markers or other logins; every host and uv
# confined to ROOT. KEEP_TOKEN=1 (claude_run only) keeps the ANTHROPIC_AUTH_TOKEN exported just before.
# Pure zsh (a subshell that unsets, exports NAME=value arguments and execs), not /usr/bin/env: uv started through
# env panicked in the Engineer's sandbox (macOS proxy lookup), and this keeps the rehearsal on Main's code path.
clean() {
  ( unset GRAFTLING_PYTHON GRAFTLING_CONNECTION GRAFTLING_DATA_ROOT GRAFTLING_DSH_CONFIG GRAFTLING_CLAUDE_HOST_CONFIG \
      GRAFTLING_CLAUDE_HOST_CHANNEL GRAFTLING_CLAUDE_HOST_PYTHON DSH_AGENT_PACKAGE DSH_SESSION_ID DSH_AGENT_SOURCE \
      GRAFTLING_NATIVE_RUNTIME CLAUDECODE CLAUDE_CODE_ENTRYPOINT PI_SUBAGENT_CHILD DEEPSEEK_BASE_URL ANTHROPIC_API_KEY \
      ANTHROPIC_BASE_URL CLAUDE_CODE_OAUTH_TOKEN CODEX_HOME VIRTUAL_ENV PYTHONPATH
    # DeepSeek is the only provider (user decision, Worldline 20261123T172123.471127+0900): every exported variable
    # whose upper-cased name matches procs.py's CRED goes, known or not, except DEEPSEEK_API_KEY and, for claude_run
    # (KEEP_TOKEN=1), the ANTHROPIC_AUTH_TOKEN derived from it. Endpoints claude_run sets are exported after this.
    # (KEEP_TOKEN itself matches TOKEN: read it before the loop can unset it.)
    local n keep=${KEEP_TOKEN:-}; unset KEEP_TOKEN
    for n in ${(k)parameters[(R)*export*]}; do
      [[ ${(U)n} =~ $CREDRE ]] || continue
      [[ $n == DEEPSEEK_API_KEY || ( $n == ANTHROPIC_AUTH_TOKEN && $keep == 1 ) ]] && continue
      unset $n
    done
    [[ $keep == 1 ]] || unset ANTHROPIC_AUTH_TOKEN
    export DSH_HOME=$DH PI_CODING_AGENT_DIR=$PIAGENT CLAUDE_CONFIG_DIR=$CH UV_TOOL_DIR=$UVT UV_TOOL_BIN_DIR=$UVB \
      UV_CACHE_DIR=$UVC UV_PYTHON_INSTALL_DIR=$UVP
    while [[ ${1:-} == [A-Za-z_][A-Za-z0-9_]#=* ]]; do export "$1"; shift; done
    exec "$@" )
}
# Claude Code on DeepSeek's Anthropic endpoint. Call it only inside a subshell that has run
# `export ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY` (so the key is never an argument and leaves with the subshell).
claude_run() {
  KEEP_TOKEN=1 clean ANTHROPIC_BASE_URL=$DSURL ANTHROPIC_MODEL=$(<$CMODELF) ANTHROPIC_SMALL_FAST_MODEL=$(<$CMODELF) \
    ANTHROPIC_DEFAULT_HAIKU_MODEL=$(<$CMODELF) CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 "$@"
}
# Your locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh), never contents or values.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  # ~/.dsh and its profiles, without '..' (that is the parent's own entry, which other programs change).
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  print -r -- "claude projects naming ${ROOT:t}: $(print -l -- $UH/.claude/projects/*${ROOT:t}*(N:t) | tr '\n' ' ')"
  python3 -I -c 'import json, sys
try: p = json.load(open(sys.argv[1])).get("projects") or {}
except (OSError, ValueError) as e: p = {}; print("~/.claude.json:", type(e).__name__)
print("~/.claude.json project keys naming", sys.argv[2] + ":", sorted(k for k in p if sys.argv[2] in k))' $UH/.claude.json ${ROOT:t}
  print -r -- "uv tools in ~/.local/share/uv/tools: $(print -l -- $UH/.local/share/uv/tools/*(N:t) | tr '\n' ' ')"
  print -r -- "~/.local/bin/agents*: $(print -l -- $UH/.local/bin/agents*(N:t) | tr '\n' ' ')"
}
count() { print -l -- $1/control/agents/*.json(N) | grep -c . }
dmodel() { [[ -n ${VERIFY581_DMODEL:-} ]] && print -r -- $VERIFY581_DMODEL || print -r -- "$(<$MODELF)"; }
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set (DSH, Pi and Claude Code Mains and dsh children use it). Fix:"
  print -r -- "  export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"; return 1
}
gcommit_ready() {  # the candidate: the bundle's head, equal to the pinned commit
  [[ $GCOMMIT == PENDING* ]] && { print -r -- "STOP: the candidate commit is not pinned yet (PINNED=$PINNED in $THIS)"; return 1; }
  [[ -f $BUNDLE ]] || { print -r -- "STOP: $BUNDLE missing"; return 1; }
  local head=$(git bundle list-heads $BUNDLE 2>/dev/null | awk -v b="refs/heads/$BRANCH" '$2 == b {print $1}')
  [[ $head == $GCOMMIT ]] || { print -r -- "STOP: the bundle's $BRANCH is '${head:-absent}', not the pinned $GCOMMIT"; return 1; }
}
PIFLAGS=()
pi_ready() {  # sets PIFLAGS from pre's model
  [[ -s $PIMODELF ]] || { print -r -- "STOP: $PIMODELF missing; run: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  PIFLAGS=(--provider deepseek --model $(<$PIMODELF))
}
pkgdir() {  # module: the installed package directory of graftling.<module>, from the one install's Python
  (cd / && clean $AGENTS_PYTHON -I -c 'import importlib, pathlib, sys; print(pathlib.Path(importlib.import_module(sys.argv[1]).__file__).parent)' $1)
}
create_prompt() {  # runtime-model-json-fragment
  print -r -- 'Use the tool mcp__graftling__agents, not your own subagents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"dsh"'$1',"instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
4) {"action":"execute","feature":"status","arguments":{}}
Then report exactly four lines: AGENT: the agent id; ANSWER: the child'"'"'s answer; STATUS: the state and last_result.notification from call 3; LISTED: every agent id that call 4 lists. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
}
# The credential-like names a Main of this kind may hold (DeepSeek only). claude: the token derived from
# DEEPSEEK_API_KEY and DeepSeek's endpoint ANTHROPIC_BASE_URL (its host is printed and checked).
allowed() { [[ $1 == claude ]] && print -r -- DEEPSEEK_API_KEY,ANTHROPIC_AUTH_TOKEN,ANTHROPIC_BASE_URL || print -r -- DEEPSEEK_API_KEY; }
# Observable 1: the credential-like NAMES in the exact environment a Main of this kind gets (the same clean(), run
# with `env`; values never leave the pipe). Also keeps your shell's own names in ROOT/<kind>-user-creds.txt.
launch_env() {  # kind dir
  local kind=$1 dir=$2
  env | python3 -I $PROCS names > $ROOT/$kind-user-creds.txt
  local -a got
  if [[ $kind == claude ]]; then
    got=(${(f)"$(cd $dir && export ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY && claude_run env | python3 -I $PROCS names)"})
  else
    got=(${(f)"$(cd $dir && clean env | python3 -I $PROCS names)"})
  fi
  local want=(${(s:,:)"$(allowed $kind)"})
  print -r -- "your shell's credential-like names (not passed on unless allowed): $(tr '\n' ' ' < $ROOT/$kind-user-creds.txt)"
  [[ $kind == claude ]] && print -r -- "ANTHROPIC_BASE_URL host for Claude Code: ${${DSURL#*://}%%/*}"
  [[ ${(j:,:)${(o)got}} == ${(j:,:)${(o)want}} ]] \
    && pass "the $kind Main's environment holds exactly these credential-like names: ${(j:, :)${(o)got}}" \
    || fail "the $kind Main's environment holds credential-like names ${(j:, :)${(o)got}:-none}; allowed only ${(j:, :)${(o)want}}"
}
# One real Main Session of kind dsh|pi|claude in dir; sets SRC and SOUT (the text the judge reads), PROCF
# (graftling command lines of the Session's descendants; PROCF.env: their credential-like names) and CJSONL.
session() {
  local kind=$1 dir=$2 prompt=$3 stamp=$(date +%H%M%S)
  SOUT=$ROOT/$kind-$stamp.txt PROCF=$ROOT/$kind-$stamp-procs.txt CJSONL=$ROOT/claude-$stamp.jsonl
  : > $PROCF; : > $PROCF.env
  say "$kind Main in $dir (no GRAFTLING_PYTHON; the agents tool comes from the uv install's attachment)"
  if [[ $kind == dsh ]]; then
    (cd $dir && clean perl -e 'alarm shift; exec @ARGV' 600 dsh --profile headless "$prompt" < /dev/null) > $SOUT 2>&1 &
  elif [[ $kind == pi ]]; then
    (cd $dir && clean perl -e 'alarm shift; exec @ARGV' 600 \
       pi -p $PIFLAGS --session-dir $ROOT/pi-sessions --approve "$prompt" < /dev/null) > $SOUT 2>&1 &
  else
    (cd $dir && export ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY && claude_run perl -e 'alarm shift; exec @ARGV' 600 claude -p --model $(<$CMODELF) \
       --output-format stream-json --verbose --allowedTools mcp__graftling__agents -- "$prompt" < /dev/null) \
       > $ROOT/claude-$stamp.jsonl 2> $ROOT/claude-$stamp.err &
  fi
  local pid=$!
  python3 -I $PROCS watch $pid $PROCF &
  local wpid=$!
  wait $pid; SRC=$?
  wait $wpid 2>/dev/null
  if [[ $kind == claude ]]; then
    python3 -I $CSTREAM $ROOT/claude-$stamp.jsonl $SOUT
    print -r -- "claude stderr tail: $(tail -3 $ROOT/claude-$stamp.err)"
  fi
  tail -25 $SOUT; print -r -- "exit=$SRC (full output: $SOUT)"
  mkdir -p $OUT 2>/dev/null && cp $SOUT $PROCF $PROCF.env ${ROOT}/claude-$stamp.jsonl(N) $OUT/ 2>/dev/null
}
# One host step: its Main creates one dsh child in the project's own .agents-control; computed verdicts.
host_step() {  # kind dir
  local kind=$1 dir=$2 root=$2/.agents-control
  local snap=$ROOT/$kind-before.ids model=''
  python3 -I $JUDGE snap $root > $snap
  [[ $kind == pi ]] && model=',"model":"'$(dmodel)'"'
  OK=1
  say "observable 1: credential-like names in the $kind Main's environment (names only)"
  launch_env $kind $dir
  (( OK )) || { print -r -- "STOP: the $kind Main would start with another credential; nothing was started. Report it."; return 1; }
  session $kind $dir "$(create_prompt "$model")"
  say "verdict (computed from the records, the output and the process table)"
  (( SRC == 0 )) && pass "the $kind Main exited 0" || fail "the $kind Main exited $SRC"
  grep -q 'Extension error' $SOUT && fail "Pi printed an extension error: $(grep -m1 'Extension error' $SOUT)"
  python3 -I $JUDGE pair $SOUT $root $snap $kind-native ready; local bits=$?
  local group bit
  for group bit in association 1 'child outcome' 2 visibility 4; do (( bits & bit )) && OK=0; done
  local agent=$(python3 -I $JUDGE snap $root | grep -v -x -F -f $snap | head -1)
  local note=$(python3 -I -c 'import json, sys; r = json.load(open(sys.argv[1])); print((r.get("executions") or [{}])[-1].get("notification"))' $root/control/agents/$agent.json 2>/dev/null)
  [[ $note == delivered ]] && pass "completion notice: the record's last execution notification is 'delivered' ($agent)" \
    || fail "completion notice: the record's last execution notification is '${note:-no record}'"
  local st=$(grep -h '^ *STATUS:' $SOUT | tail -1)
  [[ $st == *delivered* ]] && pass "completion notice reached the Main: $st" || fail "the Main's STATUS line does not say delivered: '${st:-none}'"
  python3 -I $PROCS judge $PROCF $UVT/graftling/ "$kind host" || OK=0
  [[ ! -e $DH/graftling-python ]] && pass "$DH/graftling-python does not exist" || fail "$DH/graftling-python exists"
  say "observable 2: credential-like names of every process under the Session (names only; from ps -E)"
  python3 -I $PROCS creds $PROCF.env $ROOT/$kind-user-creds.txt $(allowed $kind) "$kind Session" $kind || OK=0
  say "observable 3: provider, model and endpoint of the Main and of the child (DeepSeek only)"
  case $kind in
    dsh) python3 -I $PROVIDERS scan "dsh Main (files under DSH_HOME $DH)" $DH || OK=0 ;;
    pi)  print -r -- "pi Main configured: $PIFLAGS"
         [[ $PIFLAGS[2] == deepseek ]] && pass "pi Main configured provider deepseek, model $PIFLAGS[4]" || fail "pi Main provider is $PIFLAGS[2]"
         python3 -I $PROVIDERS scan "pi Main (its Session files in $ROOT/pi-sessions)" $ROOT/pi-sessions || OK=0 ;;
    claude)
         local cm=$(python3 -I -c 'import json, sys
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    if isinstance(d, dict) and d.get("type") == "system" and d.get("subtype") == "init": print(d.get("model")); break' $CJSONL 2>/dev/null)
         local host=${${DSURL#*://}%%/*}
         print -r -- "claude Main: endpoint ANTHROPIC_BASE_URL host $host, configured model $(<$CMODELF), init model ${cm:-none}"
         [[ $host == api.deepseek.com && $cm == *deepseek* ]] && pass "claude Main: provider deepseek (endpoint $host), model $cm" \
           || fail "claude Main: endpoint $host / model ${cm:-none} is not DeepSeek" ;;
  esac
  if [[ -n $agent ]]; then python3 -I $PROVIDERS child $root $agent || OK=0
  else fail "child: no new record to read its provider from"; fi
  if (( OK )); then
    print -r -- "SUCCESS. follow-ups (paste as needed):"
    print -r -- "  python3 -m json.tool $root/control/agents/$agent.json"
    print -r -- "  cat $PROCF"
  else
    print -r -- "next: inspect $SOUT, $PROCF and $root/control/agents/, then rerun: zsh $THIS $STEP"
  fi
  return $(( 1 - OK ))
}
# The single-source observables (read only).
single_source() {
  OK=1
  local real_uv=${UVT:A}/graftling/
  local dshp=$(pkgdir graftling.dsh) pip=$(pkgdir graftling.pi) clp=$(pkgdir graftling.claude)
  print -r -- "the uv install: $AGENTS_PYTHON; graftling/dsh $dshp; graftling/pi $pip"
  say "no second graftling"
  local gp=(${(f)"$(find $ROOT -name graftling-python -prune -print 2>/dev/null)"})
  (( ${#${gp:#}} == 0 )) && pass "no graftling-python directory anywhere under $ROOT (incl. $DH)" || fail "graftling-python under $ROOT: $gp"
  local -a inits=(${(f)"$(find $ROOT -path $UVC -prune -o -path '*/graftling/__init__.py' -print 2>/dev/null)"})
  local -a dists=(${(f)"$(find $ROOT -path $UVC -prune -o -name 'graftling-*.dist-info' -print 2>/dev/null)"})
  inits=(${inits:#}) dists=(${dists:#})   # drop empty lines; count elements (a nested ${#...} of one counts characters)
  print -r -- "graftling/__init__.py under $ROOT (outside uv's cache): ${inits:-none}"
  print -r -- "graftling-*.dist-info under $ROOT (outside uv's cache): ${dists:-none}"
  (( ${#inits} == 1 )) && [[ ${inits[1]:A} == ${real_uv}* ]] && (( ${#dists} == 1 )) && [[ ${dists[1]:A} == ${real_uv}* ]] \
    && pass "exactly one installed graftling under $ROOT, in the uv tool environment $UVT/graftling" \
    || fail "installed graftling under $ROOT is not exactly the uv one"
  print -r -- "uv cache $UVC (not an install; not importable): $(find $UVC -path '*/graftling/__init__.py' 2>/dev/null | grep -c .) source/archive copies"
  local direct=$(cd / && clean $AGENTS_PYTHON -I -c 'import json, importlib.metadata as m; d = json.loads(m.distribution("graftling").read_text("direct_url.json") or "{}"); print(d.get("url"), (d.get("vcs_info") or {}).get("commit_id"))' 2>&1)
  print -r -- "the install's direct_url: $direct"
  [[ $direct == *$GCOMMIT* ]] && pass "the uv install is graftling $GCOMMIT from ${URL}" || fail "the uv install is not $GCOMMIT"
  local others=$(cd / && clean python3 -I -c 'import graftling; print(graftling.__file__)' 2>&1 | tail -1)
  [[ $others == *ModuleNotFoundError* ]] && pass "python3 on PATH ($(command -v python3)) does not import graftling" \
    || fail "python3 on PATH imports a graftling: $others"
  say "DSH: graftling-dsh in profile headless of $DH"
  local link=$DH/profiles/headless/node_modules/graftling-dsh
  print -r -- "package.json: $(grep -h graftling-dsh $DH/profiles/headless/package.json 2>/dev/null | tr -s ' ')"
  print -r -- "$link -> $(readlink $link 2>/dev/null || print 'not a link') ; real path ${link:A}"
  [[ -e $link && ${link:A} == ${dshp:A} ]] && pass "the DSH profile's graftling-dsh is the uv install's graftling/dsh" \
    || fail "the DSH profile's graftling-dsh (${link:A}) is not $dshp"
  say "Pi: $PP/.pi/settings.json"
  local pis=$(python3 -I -c 'import json, sys; print("\n".join(str(p if isinstance(p, str) else p.get("source")) for p in json.load(open(sys.argv[1])).get("packages") or []))' $PP/.pi/settings.json 2>&1)
  print -r -- "packages: ${pis//$'\n'/ }"
  local p q ok=0; for p in ${(f)pis}; do  # a relative entry is read against .pi/ and the project
    for q in $p $PP/.pi/$p $PP/$p; do [[ $q == /* && -e $q && ${q:A} == ${pip:A} ]] && ok=1; done; done
  (( ok )) && pass "Pi's settings name the uv install's graftling/pi" || fail "Pi's settings do not name $pip"
  local copies=(${(f)"$(find $PP/.pi $PIAGENT -name extension.mjs 2>/dev/null)"})
  (( ${#${copies:#}} == 0 )) && pass "no copy of the Pi extension under $PP/.pi or $PIAGENT" || print -r -- "note: extension files under Pi's directories: $copies"
  say "Claude Code: $PC"
  local cmd=$(python3 -I -c 'import json, sys; s = json.load(open(sys.argv[1]))["mcpServers"]["graftling"]; print(s["command"])' $PC/.mcp.json 2>&1)
  local cpy=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1])).get("env", {}).get("GRAFTLING_CLAUDE_HOST_PYTHON"))' $PC/.claude/settings.local.json 2>&1)
  print -r -- ".mcp.json graftling command: $cmd | settings.local.json GRAFTLING_CLAUDE_HOST_PYTHON: $cpy"
  [[ $cmd == $UVT/graftling/bin/* && $cpy == $UVT/graftling/bin/* ]] && pass "Claude Code's MCP server and plugin use the uv install's Python" \
    || fail "Claude Code's configuration names another Python"
  local f d=0 n=0; for f in $PC/.claude/skills/agents-claude-host/**/*.mjs(N.); do
    n=$(( n + 1 )); cmp -s $f $clp/${f:t} || { d=1; print -r -- "differs from the install: $f"; }; done
  (( n > 0 && d == 0 )) && pass "Claude Code's plugin modules ($n) are identical to the uv install's graftling/claude" \
    || fail "Claude Code's plugin modules: $n found, identical: $(( d == 0 ))"
  say "no GRAFTLING_PYTHON in any host configuration"
  # Configuration files only (the plugins' own code names the variable it honours); not node_modules or records.
  local gpy=(${(f)"$(grep -rl --include='*.json' --include='*.yml' --include='*.yaml' --include='*.toml' \
      --exclude-dir=node_modules --exclude-dir=control --exclude-dir=sessions --exclude-dir=native \
      GRAFTLING_PYTHON $PD $PP $PC $DH/profiles $PIAGENT $CH/settings.json(N) 2>/dev/null)"})
  (( ${#${gpy:#}} == 0 )) && pass "no host configuration file under $ROOT names GRAFTLING_PYTHON" || fail "GRAFTLING_PYTHON named in: $gpy"
  (( OK ))
}
# A venv with graftling installed as a WHEEL built from commit $2 (the bundle supplies the candidate) and GraphTraj
# editable from checkout $3; no network (click, PyYAML and websockets are copied from .venv-runtime).
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only
suite_venv() {  # venv graftling-commit graphtraj-checkout
  local V=$1 c=$2 gt=$3 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf $V $S && mkdir -p $S/graftling $S/wheels || return 1
  git clone -q --no-checkout $GREPO $S/repo && git -C $S/repo fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $S/repo archive $c | tar -x -C $S/graftling || { print -r -- "STOP: graftling $c not found"; return 1; }
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $V/bin/python -m pip install $pip $S/wheels/graftling-*.whl && $V/bin/python -m pip install $pip -e $gt || return 1
  print -r -- "graftling $c (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
# A fresh pytest temp root under TMPDIR, outside the Harness, with no Harness marker above it; sets RUNTMP.
run_root() {  # label
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/verify-581-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1-2 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  key_ready || return 1
  print -r -- "zsh $ZSH_VERSION ($THIS, run by $(ps -o comm= -p $$))"
  local t; for t in uv dsh pi node pnpm claude python3 git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  local missing=(${(f)"$(for t in uv dsh pi node pnpm claude python3 git; do command -v $t >/dev/null || print $t; done)"})
  (( ${#${missing:#}} == 0 )) || { print -r -- "STOP: not on PATH: $missing"; return 1; }
  [[ -x $RTPY ]] || { print -r -- "STOP: $RTPY missing (it runs claude_isolation.py)"; return 1; }
  gcommit_ready || return 1
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies; its head is $GCOMMIT" \
    || { print -r -- "STOP: $BUNDLE does not verify against $GREPO"; return 1; }
  mkdir -p $PD $PP $PC $DH $PIAGENT $CH $ROOT/pi-sessions $OUT || return 1
  touch $ROOT/pre-marker
  print -r -- "pnpm store path (dsh plugin add may add the package there): $(pnpm store path 2>&1 | tail -1)"
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  local g=$(cd / && clean python3 -I -c 'import graftling; print(graftling.__file__)' 2>&1 | tail -1)
  [[ $g == *ModuleNotFoundError* ]] && pass "python3 on PATH ($(command -v python3)) does not import graftling" \
    || { print -r -- "STOP: python3 on PATH imports a graftling ($g); a host could use it instead of the uv install"; return 1; }
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/ 2>/dev/null
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "observable 1 for pre's one-liners and install's model discovery (the same clean()): credential-like names"
  launch_env dsh $PD; launch_env pi $PP
  (( OK )) || { print -r -- "STOP: a Main would start with another credential (above); nothing was started. Report it."; return 1; }
  say "one-line DSH prompt, DSH_HOME=$DH (login: DEEPSEEK_API_KEY)"
  (cd $PD && clean perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless \
     "Reply in one line with the name of the model you are and nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: DSH could not answer; check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  say "the Pi Main's model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$PIAGENT)"
  local listed; listed=$(cd $ROOT && clean perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $PIMODELF
  [[ -s $PIMODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pi_ready || return 1
  say "one-line Pi prompt: pi -p $PIFLAGS --no-session --no-extensions --no-tools"
  (cd $PP && clean perl -e 'alarm shift; exec @ARGV' 120 pi -p $PIFLAGS --no-session --no-extensions --no-tools \
     "Reply in one line: the exact model id and the provider you are running as, nothing else." < /dev/null) 2>&1 | tail -5
  rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer with $PIFLAGS; then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print -r -- ${VERIFY581_CLAUDE_MODEL:-$(<$PIMODELF)} > $CMODELF
  launch_env claude $PC
  (( OK )) || { print -r -- "STOP: Claude Code would start with another credential (above); nothing was started. Report it."; return 1; }
  say "one-line Claude Code prompt: CLAUDE_CONFIG_DIR=$CH, ANTHROPIC_BASE_URL=$DSURL, model $(<$CMODELF), token from DEEPSEEK_API_KEY"
  $RTPY -I $ISO settings $H $PC || return 1
  $RTPY -I $ISO prompt R581 > $ROOT/claude-pre-prompt.txt
  (cd $PC && export ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY && claude_run perl -e 'alarm shift; exec @ARGV' 180 claude -p --model $(<$CMODELF) --output-format stream-json \
     --verbose < $ROOT/claude-pre-prompt.txt > $ROOT/claude-pre.jsonl 2> $ROOT/claude-pre.err); rc=$?
  print -r -- "exit=$rc; stderr tail: $(tail -3 $ROOT/claude-pre.err)"
  python3 -I $CSTREAM $ROOT/claude-pre.jsonl $ROOT/claude-pre.txt; head -3 $ROOT/claude-pre.txt
  $RTPY -I $ISO check $ROOT/claude-pre.jsonl R581 $H $PC $ROOT/claude-pre-prompt.txt \
    || { print -r -- "STOP: Claude Code on DeepSeek did not answer cleanly (above). If DeepSeek refused the model id, retry with"
         print -r -- "  rm -rf $ROOT && VERIFY581_CLAUDE_MODEL=<a DeepSeek model id> zsh $THIS pre"
         print -r -- "else report it (the Leader decides on another third host)."; return 1; }
  pass "DSH, Pi (deepseek/$(<$PIMODELF)) and Claude Code ($(<$CMODELF) via DeepSeek) answered in $ROOT"
  print -r -- "next: zsh $THIS push   (ONLY after the user agreed; skip if 'git ls-remote $URL refs/heads/$BRANCH' already shows $GCOMMIT)"
  print -r -- "then: zsh $THIS install"
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $GCOMMIT -> $URL $BRANCH. Dialog: none expected."
  gcommit_ready || return 1
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { pass "already there: $BRANCH = $GCOMMIT"; return 0; }
  local tmp=${ROOT}-push.git; rm -rf $tmp; git clone -q --bare $GREPO $tmp || return 1
  git -C $tmp fetch -q $BUNDLE "${BRANCH}:refs/heads/${BRANCH}" || return 1
  [[ $(git -C $tmp rev-parse $BRANCH) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head differs"; return 1; }
  local ids=(${(f)"$(git -C $tmp log --format='%an <%ae>%n%cn <%ce>' $BASE..$BRANCH | sort -u)"})
  print -r -- "authors and committers $BASE..$BRANCH: $ids"
  local bad=(${ids:#*<$NOREPLY>})
  (( ${#bad} == 0 )) || { print -r -- "STOP: not the noreply identity: $bad"; rm -rf $tmp; return 1; }
  git -C $tmp push $URL "${GCOMMIT}:refs/heads/${BRANCH}" 2>&1 | tail -3
  rm -rf $tmp
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && pass "$URL $BRANCH = $GCOMMIT" || { fail "$URL $BRANCH is not $GCOMMIT"; return 1; }
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. The ONLY graftling install (uv, from $URL at $GCOMMIT), then each host attaches to it. Dialog: none."
  need $ROOT/user-before.txt pre && key_ready && gcommit_ready || return 1
  [[ $(git ls-remote $URL refs/heads/$BRANCH 2>/dev/null | cut -f1) == $GCOMMIT ]] \
    || { print -r -- "STOP: $URL $BRANCH is not $GCOMMIT. After the user agrees: zsh $THIS push; then: zsh $THIS install"; return 1; }
  [[ -e $UVT || -e $UVB ]] && { print -r -- "STOP: $UVT or $UVB exists (install runs once). Start over: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  OK=1
  local spec="git+${URL}@${GCOMMIT}" extra=(${(Q)${(z)${VERIFY581_UV_ARGS:-}}})
  say "uv tool install \"$spec\" ${extra:-}  (UV_TOOL_DIR=$UVT UV_TOOL_BIN_DIR=$UVB UV_CACHE_DIR=$UVC UV_PYTHON_INSTALL_DIR=$UVP)"
  (cd $ROOT && clean uv tool install $extra "$spec" < /dev/null) > $ROOT/install-uv.txt 2>&1; local rc=$?
  tail -8 $ROOT/install-uv.txt; print -r -- "exit=$rc (full output: $ROOT/install-uv.txt)"
  (( rc == 0 )) || { print -r -- "STOP: uv tool install failed (above). Start over after fixing: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print -r -- "uv tool dir: $(clean uv tool dir 2>&1) | uv tool dir --bin: $(clean uv tool dir --bin 2>&1)"
  print -r -- "uv tool list: $(clean uv tool list 2>&1 | tr '\n' ' ')"
  [[ $(clean uv tool dir 2>&1) == $UVT ]] && pass "uv tool dir is $UVT (inside ROOT)" || fail "uv tool dir is not $UVT"
  local info=$(cd / && clean $AGENTS_PYTHON -I -c 'import sys, graftling; print(sys.version.split()[0], sys.prefix, graftling.__version__, graftling.__file__)' 2>&1)
  print -r -- "AGENTS_PYTHON=$AGENTS_PYTHON -> Python, prefix, graftling version, file: $info"
  [[ $info == *$UVT/graftling/* ]] && pass "the install's Python imports graftling from $UVT/graftling" || { fail "the install's Python does not import its own graftling"; return 1; }
  print -r -- "$UVB: $(for f in $UVB/*(N); do print -n -- "${f:t} -> $(readlink $f) "; done)"
  say "README: \"\$(uv tool dir --bin)/agents\" --help"
  (cd / && clean "$(clean uv tool dir --bin)/agents" --help < /dev/null) > $ROOT/install-agents-help.txt 2>&1 \
    && pass "agents --help from uv's tool bin: $(head -1 $ROOT/install-agents-help.txt)" || fail "agents --help failed: $(tail -2 $ROOT/install-agents-help.txt)"
  local DSH_PACKAGE=$(pkgdir graftling.dsh) PI_PACKAGE=$(pkgdir graftling.pi)
  print -r -- "DSH_PACKAGE=$DSH_PACKAGE"; print -r -- "PI_PACKAGE=$PI_PACKAGE"
  if [[ -n ${VERIFY581_DMODEL:-} ]]; then print -r -- $VERIFY581_DMODEL > $MODELF; else
    say "graftling's DSH model discovery (with the uv install's Python) for the Pi and Claude Mains' dsh children"
    (cd $ROOT && clean perl -e 'alarm shift; exec @ARGV' 180 $AGENTS_PYTHON -I -c '
import sys
from graftling.models import discover_models
found = discover_models({"runtime": "dsh"})
models = found.get("models") or []
print("status", found.get("status"), "|", found.get("message") or "")
for m in models: print("  model", m["id"], "| alias", m.get("alias"))
flash = [m["id"] for m in models if "flash" in (m["id"] + " " + str(m.get("alias"))).lower()]
if flash: open(sys.argv[1], "w").write(flash[0]); print("chosen", flash[0])
' $MODELF) 2>&1 | tail -12
  fi
  [[ -s $MODELF ]] && pass "dsh child model: $(<$MODELF)" || { fail "no flash DSH model (above)"; return 1; }
  say "DSH (docs/install/dsh.md): DSH_HOME=$DH dsh plugin --profile headless add \"\$DSH_PACKAGE\"  (in $PD)"
  (cd $PD && clean dsh plugin --profile headless add "$DSH_PACKAGE" < /dev/null) > $ROOT/install-dsh.txt 2>&1; rc=$?
  tail -6 $ROOT/install-dsh.txt; print -r -- "exit=$rc (full output: $ROOT/install-dsh.txt)"
  [[ $(cat $DH/profiles/headless/package.json 2>/dev/null) == *graftling-dsh* ]] && pass "profile headless of $DH has graftling-dsh" \
    || fail "graftling-dsh is not in $DH/profiles/headless/package.json"
  say "Pi (docs/install/pi.md): PI_CODING_AGENT_DIR=$PIAGENT pi install -l \"\$PI_PACKAGE\"  (in $PP)"
  (cd $PP && clean pi install -l "$PI_PACKAGE" < /dev/null 2>&1 | tail -2)
  [[ $(cat $PP/.pi/settings.json 2>/dev/null) == *graftling/pi* ]] && pass "$PP/.pi/settings.json declares the package" \
    || fail "$PP/.pi/settings.json does not declare the package"
  local CLAUDE=$(command -v claude)
  say "Claude Code (docs/install/claude-code.md): \"\$AGENTS_PYTHON\" -m graftling.claude.host configuration --project $PC --claude $CLAUDE --write"
  (cd $PC && clean $AGENTS_PYTHON -m graftling.claude.host configuration --project $PC --claude $CLAUDE --write < /dev/null) 2>&1 | tail -8
  [[ -f $PC/.mcp.json && -f $PC/.agents-control/claude-host.json ]] && pass "configuration --write wrote $PC/.mcp.json and .agents-control/claude-host.json" \
    || { fail "configuration --write did not write its files"; return 1; }
  $RTPY -I $ISO settings $H $PC || return 1
  # What the documented prompts would record, in ROOT only: the project MCP server approval (print mode shows no
  # prompt; Claude Code keeps the answer in the project) and the folder trust (an untrusted folder suppresses the
  # project plugin, Task 576), in the isolated CLAUDE_CONFIG_DIR's .claude.json. And the dsh child's settings
  # (docs/install/claude-code.md "Children on other Runtimes").
  python3 -I -c 'import json, sys, pathlib
pc, ch, model = sys.argv[1:4]
f = pathlib.Path(pc, ".claude", "settings.local.json"); d = json.loads(f.read_text())
d["enabledMcpjsonServers"] = sorted(set(d.get("enabledMcpjsonServers", [])) | {"graftling"}); f.write_text(json.dumps(d, indent=2) + "\n")
f = pathlib.Path(ch, ".claude.json"); d = json.loads(f.read_text()) if f.is_file() else {}
d["hasCompletedOnboarding"] = True
for key in {pc, str(pathlib.Path(pc).resolve())}:
    d.setdefault("projects", {}).setdefault(key, {}).update(hasTrustDialogAccepted=True, hasCompletedProjectOnboarding=True)
f.write_text(json.dumps(d, indent=2) + "\n")
f = pathlib.Path(pc, ".agents-control", "claude-host.json"); d = json.loads(f.read_text())
d.setdefault("runtimes", {})["dsh"] = {"model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}
f.write_text(json.dumps(d, indent=2) + "\n")
print("settings.local.json enabledMcpjsonServers + graftling; claude-home/.claude.json trust for", pc, "; claude-host.json runtimes.dsh model", model)' $PC $CH $(dmodel) || return 1
  print -r -- "written in $PC: $(cd $PC && print -l -- .mcp.json .claude/**/*(N.D) .agents-control/claude-host.json(N) | tr '\n' ' ')"
  (( OK )) || return 1; print -r -- "next: zsh $THIS dsh"
  ;;
dsh)
  key_ready && need $DH/profiles/headless/package.json install || return 1
  say "[dsh] Main. DSH Main in $PD creates one dsh child; record expected in $PD/.agents-control. Dialog: none. ~1-3 min."
  host_step dsh $PD || return 1
  print -r -- "next: zsh $THIS pi"
  ;;
pi)
  key_ready && pi_ready && need $PP/.pi/settings.json install || return 1
  say "[pi] Main. Pi Main in $PP creates one dsh child ($(dmodel)); record expected in $PP/.agents-control. Dialog: none. ~1-3 min."
  host_step pi $PP || return 1
  print -r -- "next: zsh $THIS claude"
  ;;
claude)
  key_ready && need $PC/.mcp.json install || return 1
  say "[claude] Main. Claude Code Main ($(<$CMODELF) via DeepSeek, CLAUDE_CONFIG_DIR=$CH) in $PC creates one dsh child; record expected in $PC/.agents-control. Dialog: none (print mode). ~1-3 min."
  host_step claude $PC || return 1
  print -r -- "next: zsh $THIS single"
  ;;
single)
  say "[single] read only: one graftling, every host attached to it. Dialog: none. <5 s."
  need $AGENTS_PYTHON install || return 1
  single_source || return 1
  print -r -- "next: zsh $THIS post"
  ;;
post)
  say "[post] Main. Your locations vs pre (any difference FAILs). Dialog: none. <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh, ~/.claude/projects, ~/.claude.json projects, uv tools unchanged" || fail "a location changed (diff above)"
  local codex=(${(f)"$(find $UH/.codex -newer $ROOT/pre-marker -type f 2>/dev/null | xargs grep -l -F $ROOT 2>/dev/null)"})
  (( ${#${codex:#}} == 0 )) && pass "no ~/.codex file written since pre names $ROOT" || fail "~/.codex files naming $ROOT: $codex"
  print -r -- "Sessions of these runs: $ROOT/pi-sessions, the DSH Sessions under $DH, Claude Code's under $CH."
  print -r -- "To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
suite)
  setopt local_options no_bg_nice
  say "[suite] GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  gcommit_ready || return 1
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $others; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 || { print -r -- "STOP: $BUNDLE does not verify"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $GCOMMIT $WT || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))') || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY581_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: newest suite; FAILED/ERROR lines classed against 581's two known ids and 516's current definition. Dialog: none."
  local K=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- "516 current definition: $K"; [[ -f $K ]] || { print -r -- "STOP: cannot read $K"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet)"; return 1; }
  local line t id new=0 any=0; local -a ids=()
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; id=${line#* }; t=${id%%\[*}
    if (( ${KNOWN581[(Ie)$id]} )); then print -r -- "known (581 definition): $line"
    elif grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; new=1; ids+=$id; fi
  done
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
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
  print -r -- "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  (( $#ids )) && print -r -- "next (paste): zsh $THIS suite-base ${(j: :)${(q)ids}}"
  return $new
  ;;
suite-base)
  setopt local_options no_bg_nice
  local -a ids=("${(@)IDS}")
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base <node id>...   (SR prints the command with its NEW node ids)"; return 2; }
  say "[suite-base] the NEW node ids on GraphTraj $GTBASE with graftling $BASE (wheel). Dialog: none. No login."
  run_root base || return 1
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf $B && git clone -q --no-checkout $GTREPO $B && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  print -r -- "base checkout: $B (a git clone; $(git -C $B log --oneline -1))"
  local V=$T/venv-base-${BASE[1,8]}
  suite_venv $V $BASE $B || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  (cd $B && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${ids[@]}" > $R/base.txt 2>&1); local rc=$?
  tail -4 $R/base.txt; print -r -- "pytest exit=$rc (output: $R/base.txt)"
  local id fails=0
  for id in $ids; do
    if grep -qE "^(FAILED|ERROR) ${(b)id}( |\$)" $R/base.txt; then print -r -- "also fails on base: $id"
    elif grep -qE "^PASSED ${(b)id}\$" $R/base.txt; then print -r -- "candidate-only: $id"; fails=1
    else print -r -- "NOT RUN on base (missing there?): $id"; fails=1; fi
  done
  print -r -- "writes: $T ($B, $V, $R) and $RUNTMP only"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|push|install|dsh|pi|claude|single|post|suite|SR|suite-base <ids>"; return 2 ;;
esac
}
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
