#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 591 Main-run steps: graftling's MCP tool `agents` is renamed `subagents`, the console scripts agents/agents-mcp
# are renamed subagents/subagents-mcp, and the standalone Claude Code plugin's server key is `subagents`. No old name
# stays. graftling only, no GraphTraj.
# ACCEPTANCE ENTRY (user rule 2026-11-23): every judged step goes through the entry users use: a real Claude Code Main
# (`claude -p`, the user's own login) and a real Pi Main (DeepSeek), each with the candidate installed as a wheel, the
# model itself calling the subagents tool, and a real DSH child on DeepSeek. Verdicts read the hosts' own records (the
# Claude stream-json init tool list and tool results; the Pi Session file's tool declarations, calls and results) and
# the child record under <project>/.agents-control. No stub, no direct call of a host's server instead of the host.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre            Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions (zsh,
#                  node, pi, dsh, git); the bundle verifies and its head is GCOMMIT; DEEPSEEK_API_KEY set (never
#                  printed); the allowlisted environment's variable NAMES; 'before' state of ~/.pi/agent (names +
#                  sha256 prefixes), ~/.dsh and ~/.codex (listings); the deepseek flash id from `pi --list-models
#                  deepseek`; a ONE-LINE Pi prompt naming its model and provider. Dialog: none. Network:
#                  api.deepseek.com. ~1 min.
#   install        Main. ROOT/venv-cand: the candidate from the bundle as a WHEEL, graftling only (graphtraj must not
#                  import; no network: PyYAML and websockets copied from <Harness>/.venv-runtime); graftling's DSH model
#                  discovery picks the dsh child's model; a ONE-LINE DSH PROMPT with that model (DSH_HOME=ROOT/dsh-home,
#                  allowlisted env, DEEPSEEK_API_KEY the only credential) printing the configured model, DSH's answer
#                  and its login source; STOP if DSH cannot answer. Then PI_CODING_AGENT_DIR=ROOT/agent-cand:
#                  `pi install <venv-cand's graftling/pi>` (a local directory) with Pi's default provider deepseek.
#                  No `dsh plugin add`, no marketplace add. Dialog: none. Network: api.deepseek.com. ~1-2 min.
#   cli            Main. The installed candidate's console scripts: subagents and subagents-mcp exist, agents and
#                  agents-mcp do not; the metadata declares exactly the two new names; `subagents --help` runs;
#                  `subagents '{"action":"discover"}'` without a host refuses with JSON authority-denied;
#                  `subagents-mcp` over stdio names itself subagents, lists exactly the tool subagents and refuses a
#                  call of `agents` as unknown. Dialog: none. No network, no login. <10 s.
#   pi-main        Main. A real Pi Main (DeepSeek) with the candidate in a fresh git project ROOT/proj-pi creates ONE
#                  dsh child through mcp__graftling__subagents and waits for its completed answer. Verdicts: the tool
#                  set Pi declared to the model, replayed from the Session file's system messages (toolsAdded,
#                  toolsRemoved), has mcp__graftling__subagents and no agents/mcp__*__agents; the Main's tool calls
#                  and results; the one new record (host pi-native, outcome completed, 'ready'). Dialog: none.
#                  Model calls: DeepSeek only. ~2-4 min.
#   claude-pre     Main, VERIFY591_CLAUDE_USER_LOGIN=1. A one-line `claude -p` in ROOT/claude-pre with the Mains'
#                  flags and environment, judged by verify-common/claude_isolation.py check (model id, login, no
#                  Harness instruction file loaded). Dialog: none. Network: Anthropic. ~30 s.
#   claude-plugin  Main, VERIFY591_CLAUDE_USER_LOGIN=1. The STANDALONE PLUGIN form: `claude -p --plugin-dir <venv-cand's
#                  graftling/claude-plugin>` with GRAFTLING_PYTHON=venv-cand's python, in ROOT/proj-claude-plugin. The
#                  model creates ONE dsh child (DeepSeek) through mcp__plugin_graftling_subagents__subagents and waits
#                  for it. Verdicts: the stream-json init tool list has that name and no agents/mcp__*__agents; the
#                  plugin's MCP server plugin:graftling:subagents is connected; calls, results; the one new record
#                  (host claude-native, completed, 'ready'). Dialog: none. Network: Anthropic, api.deepseek.com.
#                  ~2-4 min. If the init record shows the plugin's server missing (for example because
#                  --strict-mcp-config also drops plugin servers), report it and run claude-config.
#   claude-config  Main, VERIFY591_CLAUDE_USER_LOGIN=1. The `configuration --write` form in ROOT/proj-claude-config
#                  (--mcp-config <project>/.mcp.json + --plugin-dir of the written host plugin): the same create and
#                  wait through mcp__graftling__subagents, the same verdicts. The fallback for claude-plugin, or extra
#                  coverage if Main wants both forms. Dialog: none. ~2-4 min.
#   post           Main. ~/.pi/agent, ~/.dsh and ~/.codex vs pre (any difference FAILs). <5 s.
#   suite          Main. graftling's full suite on GCOMMIT: a clean clone from the bundle in SROOT (not ROOT), a venv
#                  with conda's pytest and graftling editable (no network), TMPDIR=${TMPDIR:-/tmp} outside the
#                  Harness (checked and printed). Foreground. Dialog: none. No login. ~5-15 min.
#                  VERIFY591_PYTEST_ARGS='<args>' appends pytest arguments (rehearsal only).
#   SR             Read only: the newest suite log's summary and FAILED/ERROR node ids; for any, the ready-to-paste
#                  suite-base command. Dialog: none.
#   suite-base     Main, only if SR lists failures: reruns exactly those node ids on graftling dev BASE (542a81df) in
#                  SROOT; per id 'also fails on base' (not new) or 'candidate-only' (NEW). Dialog: none. No login.
#   push           Main, ONLY after asking the user. Pushes the candidate branch to LUOXIAO92/graftling from the
#                  bundle. Dialog: none expected; git uses your usual GitHub login (github.com). ~30 s.
# Order: pre, install, cli, pi-main, claude-pre, claude-plugin, [claude-config], post. suite and SR (suite-base) need
# no ROOT, no key and no login; push separately after asking.
# Preflight: every host answers a one-line prompt with its configured model and login before it is used: Pi in pre,
# DSH (the children's host) in install, Claude in claude-pre.
# Credentials: every pi and dsh process started by pre/install/pi-main runs in an ALLOWLISTED environment: PATH,
# HOME=ROOT/home, TMPDIR, LANG, PI_CODING_AGENT_DIR, DEEPSEEK_API_KEY and the step's own variables (shown by name).
# The Claude Mains run in an allowlisted environment too: PATH, HOME (yours: Claude Code's login needs it), USER,
# LOGNAME, SHELL, TMPDIR, LANG, DEEPSEEK_API_KEY, DSH_HOME=ROOT/dsh-home (and GRAFTLING_PYTHON for the plugin), so the
# dsh child they create has DEEPSEEK_API_KEY as its only credential. The key is never printed and never an argument.
# The user's Claude login (VERIFY591_CLAUDE_USER_LOGIN=1, required by claude-*; STOP without it): Claude Code reads the
# macOS keychain login and ~/.claude.json. Claude Code itself may write Session transcripts under
# ~/.claude/projects/-private-tmp-graftling-591-*/, entries under ~/.claude/sessions, its plugin store cache
# ~/.claude/plugins/store, and ~/.claude.json. These steps' own commands write nothing under ~/.claude, ~/.codex,
# ~/.pi, ~/.dsh or to dotfiles (no marketplace add, no plugin install, no dsh plugin add). The Mains run with
# --setting-sources project,local --strict-mcp-config, so no user settings or MCP servers load. Each claude step
# reports, by name only, what it can attribute under ~/.claude and ~/.claude/plugins/store before/after.
# Writes outside ROOT and SROOT: none expected apart from Claude Code's own files named above.
# VERIFY591_ROOT / _OUT / _BIN / _USERHOME / _BUNDLE / _GCOMMIT / _DMODEL / _PIMODEL / _SUITE_ROOT / _PYTEST_ARGS are for
# the Engineer's rehearsal only; a run with any of them set (or with stubs) is a rehearsal, not acceptance evidence.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY591_ROOT:-/private/tmp/graftling-591}
SROOT=${VERIFY591_SUITE_ROOT:-/private/tmp/graftling-591-suite}
OUT=${VERIFY591_OUT:-$H/.graphtraj/core/state/tasks/591-graftling-rename-agents-to-subagents/realhost}
URL=https://github.com/LUOXIAO92/graftling.git
BASE=542a81df0c941f5b1a425d9807681b2a38daa87c       # graftling dev v0.8.0, this Task's base
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/591-graftling-rename-agents-to-subagents
GCOMMIT=${VERIFY591_GCOMMIT:-2440d75d37838327217c3f8e9eba04ef0165051a}  # the graftling candidate (parent e952fc62, base dev 542a81df)
BUNDLE=${VERIFY591_BUNDLE:-$WT/.scratch/591/graftling-591.bundle}
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
JUDGE=${0:A:h}/judge.py
ISO=$WT/scripts/verify-common/claude_isolation.py
UH=${VERIFY591_USERHOME:-$HOME}                     # your home: its .pi/agent, .dsh and .codex are only read
DH=$ROOT/dsh-home                                   # isolated DSH home of the dsh children and model discovery
MODELF=$ROOT/pi-model.txt                           # the Pi Main's deepseek model id (pre)
DMODELF=$ROOT/dsh-model.txt                         # the dsh child's model (install)
MMODEL=${VERIFY591_CLAUDE_MODEL:-claude-haiku-5-5}  # the Claude Mains' model (as 574)
PTOOL=mcp__graftling__subagents                     # the Pi Main's and the configuration --write tool name
CTOOL=mcp__plugin_graftling_subagents__subagents    # the standalone plugin's tool name
THIS=${0:A}
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
PIPATH=${VERIFY591_BIN:+$VERIFY591_BIN:}/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
path=(${VERIFY591_BIN:+$VERIFY591_BIN} /opt/homebrew/bin $path)
CLAUDE=''

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
gcommit() { [[ -n $GCOMMIT ]] || { print -r -- "STOP: GCOMMIT is not set yet in this script (the candidate is not final)"; return 1; } }
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set. Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"
  return 1
}
# Run "$@" with ONLY the allowlisted variables (as verify-585). Usage: allow <agent dir> [NAME=value...] -- command...
allow() {
  local a=$1; shift; local -a add=()
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k
    for k in ${(k)parameters[(R)*export*]}; do [[ $k == DEEPSEEK_API_KEY ]] || unset $k 2>/dev/null; done
    export PATH=$PIPATH HOME=$ROOT/home TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8 PI_CODING_AGENT_DIR=$a
    (( $#add )) && export "${add[@]}"
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,TMPDIR,LANG,PI_CODING_AGENT_DIR,DEEPSEEK_API_KEY${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# A Claude Code Main's allowlisted environment: your HOME (the login), no graftling or Claude Code session markers.
callow() {
  local -a add=()
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k u=$HOME us=${USER:-$(id -un)} sh=${SHELL:-/bin/zsh} t=$PYTEST_TMP
    for k in ${(k)parameters[(R)*export*]}; do [[ $k == DEEPSEEK_API_KEY ]] || unset $k 2>/dev/null; done
    export PATH=${CLAUDE:h}:$PIPATH HOME=$u USER=$us LOGNAME=$us SHELL=$sh TMPDIR=$t LANG=en_US.UTF-8 DSH_HOME=$DH
    (( $#add )) && export "${add[@]}"
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,USER,LOGNAME,SHELL,TMPDIR,LANG,DSH_HOME,DEEPSEEK_API_KEY${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# Your locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh and ~/.codex), never contents.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  ls -laT $UH/.codex 2>&1 | awk 'NF >= 10 && $10 != ".." {print "codex", $6, $7, $8, $9, $10}'
}
pimodel() { [[ -s $MODELF ]] && print -r -- "$(<$MODELF)" || { print -r -- "STOP: $MODELF missing; run: rm -rf $ROOT && zsh $THIS pre" >&2; return 1; } }
venv() { print -r -- $ROOT/venv-$1; }
site() { print -r -- $(venv $1)/lib/python3.13/site-packages/graftling; }
mkproj() { rm -rf $1 && mkdir -p $1 && git -C $1 init -q; }
# Builds a venv with graftling installed as a WHEEL from commit $2 of the bundle; graftling only (as verify-585).
build_venv() {  # dir commit
  local v=$1 c=$2 S=$1-src
  [[ -f $v/installed && $(<$v/installed) == $c* ]] && { print -r -- "reusing $v ($(<$v/installed))"; return 0; }
  rm -rf $v $S && mkdir -p $S/graftling $S/wheels || return 1
  git clone -q --no-checkout $GREPO $S/repo && git -C $S/repo fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $S/repo archive $c | tar -x -C $S/graftling || { print -r -- "STOP: graftling $c not found"; return 1; }
  $CONDA -m venv $v || return 1
  local D=$($v/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ || return 1
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $v/bin/python -m pip install $pip $S/wheels/graftling-*.whl || return 1
  local got; got=$(cd / && $v/bin/python -I -c 'import graftling, yaml, websockets, importlib.util as u; print(graftling.__version__, graftling.__file__, "| graphtraj importable:", u.find_spec("graphtraj") is not None)') \
    || { print -r -- "STOP: $v cannot import graftling with its dependencies"; return 1; }
  [[ $got == *'graphtraj importable: False' ]] || { print -r -- "STOP: graphtraj is importable in $v: $got"; return 1; }
  print -r -- "$c $got" > $v/installed; print -r -- "$v: $(<$v/installed)"
}
defaults() {  # agent dir, model: Pi's default provider/model there
  python3 -I -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "settings.json"; s = json.loads(p.read_text()) if p.exists() else {}
s.update(defaultProvider="deepseek", defaultModel=sys.argv[2]); p.write_text(json.dumps(s, indent=2))
print("settings.json: packages", s.get("packages"), "| default", s["defaultProvider"], s["defaultModel"])' $1 $2
}
# One-line DSH prompt (as verify-585 install) with the dsh child's model, before any graftling step.
dsh_preflight() {  # model
  local m=$1 patch=$ROOT/dsh-preflight.patch.yml log=$ROOT/dsh-preflight.txt rc
  print -r -- "- id: llm-deepseek
  config:
    models:
      - id: $m" > $patch
  say "one-line DSH prompt: dsh --profile headless --patch $patch (DSH_HOME=$DH; allowlisted env)"
  local dumped; dumped=$(cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- dsh --profile headless --patch $patch --dump-config < /dev/null 2>&1)
  print -r -- "configured models of llm-deepseek (from --dump-config): $(print -r -- $dumped | awk '/^- id: llm-deepseek$/ {f=1; next} f && /^- id:/ {exit} f && /- id:/ {print $3}' | xargs)"
  print -r -- "login: DEEPSEEK_API_KEY from the allowlisted environment (set, ${#DEEPSEEK_API_KEY} characters, not printed); DEEPSEEK_BASE_URL absent; $DH/.credentials.yaml $([[ -e $DH/.credentials.yaml ]] && print PRESENT || print absent), $DH/.env $([[ -e $DH/.env ]] && print PRESENT || print absent)"
  (cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless --patch $patch \
     "Reply in one line with the exact model id you are running as, nothing else." < /dev/null) > $log 2>&1; rc=$?
  tail -5 $log; print -r -- "exit=$rc (full output: $log)"
  if (( rc != 0 )); then
    print -r -- "STOP: DSH could not answer with model $m (output above). Check DEEPSEEK_API_KEY (export DEEPSEEK_API_KEY=<your DeepSeek API key>),"
    print -r -- "  the network to api.deepseek.com and that '$m' is listed by the discovery above; then rerun exactly: zsh $THIS install"
    return 1
  fi
  pass "DSH answered as configured model $m (login: DEEPSEEK_API_KEY)"
}
create_prompt() {  # tool, dsh model
  print -r -- 'Use the MCP tool '$1' (not any built-in Task or Agent tool of yours). Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"dsh","model":"'$2'","instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
Do not retry or change any argument. Then report exactly two lines: AGENT: the agent id; ANSWER: the child'"'"'s answer. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
}
# --- Claude Code (as verify-574) ---
login_gate() {
  [[ -n ${VERIFY591_CLAUDE_USER_LOGIN:-} ]] || {
    print -r -- "STOP: this step uses the user's own Claude login; Main asks the user first, then runs:"
    print -r -- "  VERIFY591_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"
    return 1 }
  CLAUDE=$(command -v claude)
  [[ -n $CLAUDE ]] || { print "STOP: no claude on PATH"; return 1; }
  print -r -- "claude: $CLAUDE $($CLAUDE --version 2>&1 | head -1)"
  print -r -- "VERIFY591_CLAUDE_USER_LOGIN=1: Claude Code uses the user's own login. It reads the keychain and ~/.claude.json."
  print -r -- "Claude Code itself may write Session transcripts under ~/.claude/projects/-private-tmp-graftling-591-*/,"
  print -r -- "entries under ~/.claude/sessions, its plugin store cache ~/.claude/plugins/store, and ~/.claude.json."
  print -r -- "This step's own commands write nothing under ~/.claude or to ~/.claude.json."
  : > $ROOT/.claude-marker-$STEP
  store > $ROOT/.plugins-store-before-$STEP
}
store() { ls -lT $HOME/.claude/plugins/store 2>&1 | awk 'NR > 1 { print $6, $7, $8, $9, $10 }' }  # mtime + name
claude_outside() {  # names only: what this step can attribute under ~/.claude, and what it cannot
  say "outside $ROOT during this step (names only; no values printed)"
  local ids=$ROOT/.session-ids-$STEP f
  {
    for f in $ROOT/*.jsonl(N); do [[ $f -nt $ROOT/.claude-marker-$STEP ]] && python3 -I -c 'import json, sys
for raw in open(sys.argv[1], errors="replace"):
    try: e = json.loads(raw)
    except ValueError: continue
    if isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "init" and e.get("session_id"): print(e["session_id"]); break' $f; done
    for f in $ROOT/proj-*/.agents-control/control/agents/*.json(N); do
      python3 -I -c 'import json, sys; r = json.load(open(sys.argv[1])); print("\n".join(s for s in [r.get("session"), *(r.get("sessions") or [])] if isinstance(s, str)))' $f
    done
    print -r -- ${ROOT:A}
  } | sort -u | grep . > $ids
  print -r -- "this step's Session ids and ROOT ($(wc -l < $ids | tr -d ' ') strings) are matched below"
  local -a mine=(${(f)"$(find $HOME/.claude/sessions -type f -newer $ROOT/.claude-marker-$STEP 2>/dev/null | xargs grep -l -F -f $ids 2>/dev/null)"})
  print -r -- "~/.claude/sessions entries changed in this step whose content names its Sessions or ROOT: ${(j: :)${mine[@]:t}}"
  print -r -- "~/.claude/projects directories naming ${ROOT:t}: $(print -l -- $HOME/.claude/projects/*${ROOT:t}*(N/:t) | tr '\n' ' ')"
  store > $ROOT/.plugins-store-after-$STEP
  if cmp -s $ROOT/.plugins-store-before-$STEP $ROOT/.plugins-store-after-$STEP; then
    print -r -- "~/.claude/plugins/store: unchanged during this step"
  else
    print -r -- "~/.claude/plugins/store changed during this step (names and mtimes, before -> after); this cannot be"
    print -r -- "attributed to this step: other Claude processes run concurrently."
    diff $ROOT/.plugins-store-before-$STEP $ROOT/.plugins-store-after-$STEP | grep '^[<>]'
  fi
  python3 -I -c 'import json, sys
p = json.load(open(sys.argv[1])).get("projects") or {}
print("~/.claude.json project keys under", sys.argv[2] + ":", [k for k in p if k.startswith(sys.argv[2])])' \
    $HOME/.claude.json ${ROOT:A} 2>&1
}
# One real Claude Main in project $1 with launch flags $LAUNCH and extra env $CENV; judged for tool $2.
claude_case() {  # project tool
  local P=$1 tool=$2 out=$ROOT/${1:t}-$(date +%H%M%S).jsonl snap=$ROOT/${1:t}-before.ids model
  model=$(<$DMODELF)
  python3 -I $JUDGE snap $P/.agents-control > $snap
  say "Main in $P: claude ${LAUNCH[*]} '<create+wait+status prompt for $tool, dsh child model $model>'"
  print -r -- "Main environment (names; values not printed): PATH HOME USER LOGNAME SHELL TMPDIR LANG DSH_HOME DEEPSEEK_API_KEY ${CENV%%=*}"
  (cd $P && callow $CENV -- $CLAUDE $LAUNCH "$(create_prompt $tool $model)" < /dev/null > $out 2> $out.err)
  local mrc=$?
  print -r -- "Main exit=$mrc (stream: $out; stderr: $out.err, $(wc -l < $out.err | tr -d ' ') lines)"
  cp $out $out.err $OUT/ 2>/dev/null
  say "verdict (computed)"
  (( mrc == 0 )) && pass "the Main exited 0" || fail "the Main exited $mrc"
  python3 -I $JUDGE claude $out $P/.agents-control $snap $tool claude-native ready || OK=0
  print -r -- "host log (last lines): $(tail -3 $P/.agents-control/host.log 2>/dev/null | tr '\n' ' ')"
  print -r -- "processes still naming $P (expect none): $(pgrep -fl -- $P 2>/dev/null | head -3 | tr '\n' ' ')"
  print -r -- "follow-up (paste): python3 -I $JUDGE claude $out $P/.agents-control $snap $tool claude-native ready"
}

# A fresh pytest temp root under TMPDIR, outside the Harness, with no Harness marker above it; sets RUNTMP.
run_root() {  # label
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/verify-591-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
}
# A clean checkout of commit $2 in $1/src and a venv $1/venv: conda's pytest (system site), graftling editable.
suite_tree() {  # dir commit
  local S=$1 c=$2
  if [[ ! -d $S/src/.git || $(git -C $S/src rev-parse HEAD 2>/dev/null) != $c || -n $(git -C $S/src status --porcelain 2>/dev/null) ]]; then
    rm -rf $S && mkdir -p $S || return 1
    git clone -q --no-checkout $GREPO $S/src && git -C $S/src fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" \
      && git -C $S/src -c advice.detachedHead=false checkout -q $c || { print -r -- "STOP: cannot check out $c"; return 1; }
  fi
  print -r -- "suite source: $S/src at $(git -C $S/src rev-parse HEAD) (clean: $([[ -z $(git -C $S/src status --porcelain) ]] && print yes || print NO))"
  if [[ ! -f $S/venv/installed ]]; then
    $CONDA -m venv --system-site-packages $S/venv || return 1
    local D=$($S/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
    for m in yaml websockets; do
      $S/venv/bin/python -I -c "import $m" 2>/dev/null && continue
      case $m in
        yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
        *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
      esac || return 1
    done
    $S/venv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S/src > $S/pip.txt 2>&1 || { tail -5 $S/pip.txt; print -r -- "STOP: editable install failed ($S/pip.txt)"; return 1; }
    print -r -- $c > $S/venv/installed
  fi
  (cd / && $S/venv/bin/python -I -c 'import graftling, pytest, importlib.util as u; print("imports graftling", graftling.__version__, "from", graftling.__file__, "| pytest", pytest.__version__, "| graphtraj importable:", u.find_spec("graphtraj") is not None)')
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  gcommit && key_ready || return 1
  mkdir -p $ROOT/home $ROOT/agent-probe $DH $OUT || return 1
  print -r -- "zsh $ZSH_VERSION ($THIS)"
  local t; for t in node git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  for t in pi dsh; do print -r -- "$t: $(command -v $t) $(cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- $t --version < /dev/null 2>&1 | head -1)"; done
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { print -r -- "STOP: bundle does not verify"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | cut -d' ' -f1) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head is not $GCOMMIT"; return 1; }
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed)."
  print -r -- "allowlisted environment of every pi/dsh process (names only): $(allow $ROOT/agent-probe EXAMPLE_STEP_VAR=1 -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "the Pi Main's model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$ROOT/agent-probe)"
  local listed; listed=$(cd $ROOT && allow $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  if [[ -n ${VERIFY591_PIMODEL:-} ]]; then print -r -- $VERIFY591_PIMODEL > $MODELF
  else print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $MODELF; fi
  [[ -s $MODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  say "one-line Pi prompt: pi -p --provider deepseek --model $(<$MODELF) --no-session --no-extensions --no-tools"
  (cd $ROOT && allow $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi -p --provider deepseek --model $(<$MODELF) \
     --no-session --no-extensions --no-tools "Reply in one line: the exact model id and the provider you are running as, nothing else." \
     < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc (login: DEEPSEEK_API_KEY from the allowlisted environment)"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer; check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "Pi Main model: deepseek/$(<$MODELF)"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. venv-cand ($GCOMMIT), DSH model discovery, one-line DSH prompt, agent-cand. Dialog: none."
  gcommit && need $MODELF pre && key_ready || return 1
  build_venv $(venv cand) $GCOMMIT || return 1
  if [[ -n ${VERIFY591_DMODEL:-} ]]; then print -r -- $VERIFY591_DMODEL > $DMODELF; else
    say "graftling's DSH model discovery for the dsh children ($(venv cand)/bin/python; DSH_HOME=$DH)"
    (cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 180 $(venv cand)/bin/python -I -c '
import sys
from graftling.models import discover_models
found = discover_models({"runtime": "dsh"})
models = found.get("models") or []
print("status", found.get("status"), "|", found.get("message") or "")
for m in models: print("  model", m["id"], "| alias", m.get("alias"))
flash = [m["id"] for m in models if "flash" in (m["id"] + " " + str(m.get("alias"))).lower()]
if flash: open(sys.argv[1], "w").write(flash[0]); print("chosen", flash[0])
' $DMODELF) 2>&1 | tail -12
  fi
  [[ -s $DMODELF ]] || { print -r -- "STOP: no flash DSH model; see above. Then: zsh $THIS install"; return 1; }
  dsh_preflight $(<$DMODELF) || return 1
  local a=$ROOT/agent-cand model; model=$(pimodel) || return 1
  rm -rf $a && mkdir -p $a || return 1
  say "PI_CODING_AGENT_DIR=$a pi install $(site cand)/pi"
  allow $a -- pi install $(site cand)/pi < /dev/null 2>&1 | tail -3
  defaults $a $model
  allow $a -- pi list < /dev/null 2>&1 | head -6
  print -r -- "candidate plugin.json mcpServers keys: $(python3 -I -c 'import json, sys; print(list(json.load(open(sys.argv[1]))["mcpServers"]))' $(site cand)/claude-plugin/.claude-plugin/plugin.json)"
  pass "installed; dsh child model: $(<$DMODELF) (DSH answered with it above)"
  print -r -- "next: zsh $THIS cli"
  ;;
cli)
  say "[cli] Main. The candidate's console scripts in $(venv cand)/bin. Dialog: none. No network, no login."
  gcommit && need $(venv cand)/installed install || return 1
  [[ $(<$(venv cand)/installed) == $GCOMMIT* ]] || { print -r -- "STOP: $(venv cand) is not $GCOMMIT; rerun: zsh $THIS install"; return 1; }
  mkdir -p $ROOT/cli-cwd && (cd $ROOT/cli-cwd && env -u GRAFTLING_CONNECTION -u GRAFTLING_DATA_ROOT python3 -I $JUDGE cli $(venv cand))
  local rc=$?; (( rc == 0 )) || { print -r -- "next: inspect the FAIL lines above; rerun: zsh $THIS cli"; return 1; }
  print -r -- "next: zsh $THIS pi-main"
  ;;
pi-main)
  key_ready && need $ROOT/agent-cand/settings.json install && need $DMODELF install || return 1
  local P=$ROOT/proj-pi root=$ROOT/proj-pi/.agents-control snap=$ROOT/pi-main-before.ids SD=$ROOT/sessions-pi-main
  local SOUT=$ROOT/pi-main.txt model dmodel; model=$(pimodel) || return 1; dmodel=$(<$DMODELF)
  say "[pi-main] Main. Plain Pi Main (deepseek/$model) with the candidate creates ONE dsh child ($dmodel) through $PTOOL in $P. Dialog: none."
  mkproj $P; : > $snap; rm -rf $SD; mkdir -p $SD
  say "pi -p --provider deepseek --model $model --approve --session-dir $SD '<create+wait+status prompt>'; PI_CODING_AGENT_DIR=$ROOT/agent-cand; allowlisted env + DSH_HOME"
  ( cd $P && allow $ROOT/agent-cand DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 600 pi -p --provider deepseek --model $model \
      --approve --session-dir $SD "$(create_prompt $PTOOL $dmodel)" ) < /dev/null > $SOUT 2>&1
  local src=$?
  tail -8 $SOUT; print -r -- "exit=$src (full output: $SOUT)"; cp $SOUT $OUT/ 2>/dev/null
  print -r -- "$root: $(print -l -- $root/*(N:t) | tr '\n' ' '); live: $(print -l -- $root/live/*(N:t) | tr '\n' ' ')"
  say "verdict (computed)"
  OK=1
  (( src == 0 )) && pass "the Pi Main exited 0" || fail "the Pi Main exited $src"
  python3 -I $JUDGE pi $SD $SOUT $root $snap $PTOOL pi-native ready || OK=0
  print -r -- "follow-up (paste): python3 -I $JUDGE pi $SD $SOUT $root $snap $PTOOL pi-native ready"
  (( OK )) || { print -r -- "next: inspect $SOUT and $SD"; return 1; }
  print -r -- "next: VERIFY591_CLAUDE_USER_LOGIN=1 zsh $THIS claude-pre   (Main asks the user first)"
  ;;
claude-pre)
  say "[claude-pre] Main. One-line claude -p with the Mains' flags and environment. Dialog: none expected. ~30 s."
  need $DMODELF install || return 1
  login_gate || return 1
  mkdir -p $ROOT/claude-pre && python3 -I $ISO settings $H $ROOT/claude-pre || return 1
  [[ $($CLAUDE --help 2>&1) == *--plugin-dir* ]] && pass "claude --help offers --plugin-dir" || { print "STOP: claude --help offers no --plugin-dir"; return 1; }
  local pr=$ROOT/claude-pre-prompt.txt out=$ROOT/claude-pre.jsonl
  python3 -I $ISO prompt V591 > $pr
  say "claude -p --setting-sources project,local --strict-mcp-config --model $MMODEL --output-format stream-json --verbose < $pr (in $ROOT/claude-pre)"
  (cd $ROOT/claude-pre && callow -- $CLAUDE -p --setting-sources project,local --strict-mcp-config --model $MMODEL \
     --output-format stream-json --verbose < $pr > $out 2> $out.err)
  local crc=$?; print -r -- "exit=$crc"
  python3 -I $ISO check $out V591 $H $ROOT/claude-pre $pr; local ic=$?
  claude_outside
  (( crc == 0 && ic == 0 )) || { print -r -- "STOP: Claude Code did not answer cleanly (above); check its login, then rerun: VERIFY591_CLAUDE_USER_LOGIN=1 zsh $THIS claude-pre"; return 1; }
  print -r -- "next: VERIFY591_CLAUDE_USER_LOGIN=1 zsh $THIS claude-plugin"
  ;;
claude-plugin)
  key_ready && need $DMODELF install && need $ROOT/claude-pre.jsonl claude-pre || return 1
  local P=$ROOT/proj-claude-plugin PD=$(site cand)/claude-plugin
  say "[claude-plugin] Main. Standalone plugin form (--plugin-dir $PD, GRAFTLING_PYTHON=$(venv cand)/bin/python); tool $CTOOL. Dialog: none expected. ~2-4 min."
  login_gate || return 1
  local keys; keys=$(python3 -I -c 'import json, sys; print(" ".join(json.load(open(sys.argv[1]))["mcpServers"]))' $PD/.claude-plugin/plugin.json)
  [[ $keys == subagents ]] && pass "the candidate plugin's only MCP server key is subagents" || fail "plugin mcpServers keys: $keys"
  mkproj $P && python3 -I $ISO settings $H $P || return 1
  OK=1
  typeset -ga LAUNCH=(-p --setting-sources project,local --strict-mcp-config --plugin-dir $PD --model $MMODEL
                      --allowedTools $CTOOL --output-format stream-json --verbose)
  CENV=GRAFTLING_PYTHON=$(venv cand)/bin/python
  claude_case $P $CTOOL
  claude_outside
  (( OK )) && print -r -- "SUCCESS: the standalone plugin's Main created and waited for a child through $CTOOL" \
    || { print -r -- "NOT ACCEPTED (FAIL lines above). If the init record lacks plugin:graftling:subagents, run instead:"
         print -r -- "  VERIFY591_CLAUDE_USER_LOGIN=1 zsh $THIS claude-config"; return 1; }
  print -r -- "next: zsh $THIS post   (claude-config is optional extra coverage)"
  ;;
claude-config)
  key_ready && need $DMODELF install && need $ROOT/claude-pre.jsonl claude-pre || return 1
  local P=$ROOT/proj-claude-config
  say "[claude-config] Main. configuration --write form; tool $PTOOL. Dialog: none expected. ~2-4 min."
  login_gate || return 1
  mkproj $P && python3 -I $ISO settings $H $P || return 1
  (cd $P && env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u GRAFTLING_DATA_ROOT -u GRAFTLING_CLAUDE_HOST_CONFIG \
     $(venv cand)/bin/python -I -m graftling.claude.host configuration --project $P --claude $CLAUDE --write) \
    || { print "STOP: configuration --write failed"; return 1; }
  python3 -I $ISO settings $H $P || return 1
  local -a pd=($P/.claude/skills/*/.claude-plugin/plugin.json(N:h:h))
  print -r -- "written: $(cd $P && print -l -- .mcp.json(N) .claude/**/*(N.D) .agents-control/claude-host.json(N) | tr '\n' ' ')"
  (( $#pd == 1 )) || { print -r -- "STOP: expected one written host plugin under $P/.claude/skills: $pd"; return 1; }
  OK=1
  print -r -- ".mcp.json servers: $(python3 -I -c 'import json, sys; print(list(json.load(open(sys.argv[1]))["mcpServers"]))' $P/.mcp.json)"
  local tl=$(grep -hE '^const TOOLS? = ' $pd[1]/hooks/*.mjs(N))
  print -r -- "written hook TOOL/TOOLS lines: ${tl//$'\n'/ | }"
  [[ $tl == *'"subagents"'* && $tl != *'"agents"'* ]] && pass "the written hook names the tool subagents and not \"agents\"" \
    || fail "the written hook's TOOL/TOOLS lines do not name subagents only"
  typeset -ga LAUNCH=(-p --setting-sources project,local --strict-mcp-config --mcp-config $P/.mcp.json --plugin-dir $pd[1]
                      --model $MMODEL --allowedTools $PTOOL --output-format stream-json --verbose)
  CENV=VERIFY591_FORM=config
  claude_case $P $PTOOL
  claude_outside
  (( OK )) && print -r -- "SUCCESS: the configuration --write Main created and waited for a child through $PTOOL" || return 1
  print -r -- "next: zsh $THIS post"
  ;;
post)
  say "[post] Main. Your ~/.pi/agent, ~/.dsh and ~/.codex vs pre (any difference FAILs). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh and ~/.codex unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT/*.txt, $ROOT/*.jsonl (copied to $OUT). To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
suite)
  gcommit || return 1
  say "[suite] Main. graftling full suite on $GCOMMIT (clean clone from the bundle in $SROOT/cand). TMPDIR=$PYTEST_TMP. Dialog: none. No login. ~5-15 min."
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 || { print -r -- "STOP: $BUNDLE does not verify"; return 1; }
  run_root suite || return 1
  suite_tree $SROOT/cand $GCOMMIT || return 1
  local extra=(${(Q)${(z)${VERIFY591_PYTEST_ARGS:-}}}) log=$SROOT/suite-$(date +%Y%m%dT%H%M%S).txt
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args: $extra (a filtered run is not the full suite)"
  print -r -- "pytest: cd $SROOT/cand/src && TMPDIR=$RUNTMP $SROOT/cand/venv/bin/python -m pytest -q -p no:cacheprovider -rfE $extra"
  { print -r -- "candidate $GCOMMIT | TMPDIR $RUNTMP | extra: $extra"
    (cd $SROOT/cand/src && TMPDIR=$RUNTMP $SROOT/cand/venv/bin/python -m pytest -q -p no:cacheprovider -rfE $extra 2>&1)
    print -r -- "exit=$?"; } > $log
  print -r -- $log > $SROOT/suite-latest; cp $log $OUT/ 2>/dev/null
  tail -25 $log; print -r -- "(full output: $log)"
  local prc=${$(tail -1 $log)#exit=}
  (( prc == 0 )) && ! grep -qE '[0-9] passed' $log && { print -r -- "FAIL: pytest exited 0 but no test passed"; prc=1; }
  (( prc == 0 )) && print -r -- "SUCCESS: graftling suite passed on $GCOMMIT$( (( $#extra )) && print ' (FILTERED rehearsal run)')" \
    || print -r -- "FAIL: pytest exit $prc; classify with: zsh $THIS SR"
  print -r -- "next (paste): zsh $THIS SR"
  return $prc
  ;;
SR)
  say "[SR] read only: the newest suite log. Dialog: none."
  local g=$(cat $SROOT/suite-latest 2>/dev/null)
  [[ -n $g && -f $g ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  print -r -- "log: $g"; head -1 $g; tail -3 $g
  local -a summary=(${(M)${(f)"$(<$g)"}:#*[0-9] (passed|failed|skipped|error)*})
  [[ $summary == *[0-9]\ passed* ]] || { print -r -- "SR verdict: FAIL (no test passed: '${summary[-1]:-no summary}')"; return 1; }
  local -a ids=(${(f)"$(grep -E '^(FAILED|ERROR) ' $g | sed -E 's/^(FAILED|ERROR) //; s/ - .*//' | sort -u)"})
  if (( $#ids )); then
    print -l -- "FAILED/ERROR: "${^ids}
    print -r -- "SR verdict: $#ids failing node id(s); compare with base (paste):"
    print -r -- "  zsh $THIS suite-base ${(j: :)${(q)ids}}"
    return 1
  fi
  grep -q '^exit=0$' $g && { print -r -- "SR verdict: PASS (no FAILED/ERROR line, exit 0)$(head -1 $g | grep -q 'extra: .' && print ' — FILTERED rehearsal run')"; return 0; }
  print -r -- "SR verdict: FAIL (no FAILED line but pytest did not exit 0; see $g)"; return 1
  ;;
suite-base)
  local -a ids=("${(@)IDS}")
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base <node id>...   (SR prints the command with its node ids)"; return 2; }
  say "[suite-base] the failing node ids on graftling dev $BASE (clean clone in $SROOT/base). Dialog: none. No login."
  run_root base || return 1
  suite_tree $SROOT/base $BASE || return 1
  local log=$SROOT/suite-base-$(date +%Y%m%dT%H%M%S).txt
  (cd $SROOT/base/src && TMPDIR=$RUNTMP $SROOT/base/venv/bin/python -m pytest -q -p no:cacheprovider -rA "${ids[@]}" > $log 2>&1); local rc=$?
  tail -4 $log; print -r -- "pytest exit=$rc (output: $log)"; cp $log $OUT/ 2>/dev/null
  local id new=0
  for id in $ids; do
    if grep -qE "^(FAILED|ERROR) ${(b)id}( |\$)" $log; then print -r -- "also fails on base (not new): $id"
    elif grep -qE "^PASSED ${(b)id}\$" $log; then print -r -- "candidate-only (NEW): $id"; new=1
    else print -r -- "NOT RUN on base (a new or renamed test; NEW unless explained): $id"; new=1; fi
  done
  return $new
  ;;
push)
  gcommit || return 1
  say "[push] Main, ONLY after the user agreed. $GCOMMIT -> $URL $BRANCH. Dialog: none expected."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { pass "already on GitHub"; return 0; }
  local tmp=$SROOT/push-clone.git; mkdir -p $SROOT; rm -rf $tmp; git clone -q --bare $GREPO $tmp || return 1
  git -C $tmp fetch -q $BUNDLE "${BRANCH}:refs/heads/${BRANCH}" || return 1
  [[ $(git -C $tmp rev-parse $BRANCH) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head differs"; return 1; }
  print -r -- "authors and committers: $(git -C $tmp log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $tmp push $URL "${GCOMMIT}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && pass "GitHub $BRANCH = $GCOMMIT" || fail "GitHub $BRANCH is not $GCOMMIT"
  rm -rf $tmp
  (( OK ))
  ;;
*) print -r -- "usage: zsh $THIS pre|install|cli|pi-main|claude-pre|claude-plugin|claude-config|post|suite|SR|suite-base <ids>|push"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY591_OUT:-} ]] || { print "STOP: $H is not the Harness root"; exit 1; }
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
CENV=''
mkdir -p $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
{ run_step; print -r -- "STEP-END $STEP rc=$?"; } 2>&1 | tee $OUT/$STEP.txt
rc=$?
grep -q "^STEP-END $STEP rc=0\$" $OUT/$STEP.txt || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT/$STEP.txt; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
exit $rc
