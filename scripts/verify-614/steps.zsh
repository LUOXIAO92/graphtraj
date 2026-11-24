#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 614 Main-run steps: GraphTraj's subagents `models` (graftling 0.10.0's feature) is listed by discover AND
# executes: it lists the project roles create can select for a Runtime, grouped by each role's catalog provider, key
# variable NAMES only. Candidate = this Worktree's HEAD (GraphTraj dev 78f4c207 + 614); graftling 0.10.0 (v0.10.0 =
# 6f4aeb8f) from <Harness>/graftling, as a WHEEL. Modelled on scripts/verify-611/steps.zsh (credential scrub, allowlist
# environment, isolated ROOT, wheels, setup, judge) and scripts/adopt-612/steps.zsh (G waits for its shards and ends
# with the verdict; SR against Task 516's CURRENT definition; suite-base). Production (<Harness>/.venv-runtime) is only
# read (click, PyYAML, websockets copied). graftling is not changed. Nothing is pushed.
# Run one step at a time, in this order:  zsh <this file> <STEP>     (README.md says what each step proves)
#   pre     Main. ROOT must not exist (STOP with the exact rm). zsh, candidate HEAD, base 78f4c207 and graftling v0.10.0
#           resolvable; TMPDIR outside the Harness; your locations (~/.graphtraj, ~/.codex, ~/.pi/agent, ~/.dsh) listed
#           into ROOT/user-before.txt (names, sizes, mtimes). ONE one-line `claude -p` (no MCP server, no tool) in
#           ROOT: the host names its model and login. LOGIN: the user's Claude login (Main asks the user first).
#           Dialog: none. Network: Claude. ~30 s. Observable: "PASS: the Claude host answered: ...".
#   install Main. ROOT/venv: HEAD as a WHEEL (git archive) + graftling v0.10.0 as a WHEEL, offline; click, PyYAML,
#           websockets copied from production. Dialog: none. No login. ~1 min.
#   setup   Main. ROOT/proj (own git) through public `graphtraj setup`; the isolated catalog
#           ROOT/home/.graphtraj/connections.yml (HOME=ROOT/home locates it): previewed through public
#           `graphtraj connections --action preview`, written, read back through `--action read`. claude-614 has
#           providers anthropic and gw614 (base_url + api_key_env FAKE614_KEY; never launched); codex-614 has openai.
#           Roles: claude (anthropic), routed (gw614), inline (no catalog provider), coder (codex). Public
#           `graphtraj roles organize` preview. Claude host material through `host configuration --write`
#           (.mcp.json, the graphtraj-claude-host plugin). No probe Task is needed (models starts nothing).
#           Dialog: none. No login. <1 min.
#   trust   USER, once per ROOT path (Claude Code loads the project plugin only in a trusted folder). See README.
#           Dialog: "Do you trust the files in this folder?" -> "Yes, proceed"; then /exit.
#   real    Main. ONE `claude -p` in ROOT/proj (--mcp-config ROOT/mcp-614.json --strict-mcp-config, --allowedTools
#           mcp__graphtraj__subagents only) makes three inline calls: discover (empty query), describe models,
#           execute models {runtime: claude}. The judge reads the stream: the serving path (init plugins), discover
#           lists models, execute models is not an error, groups anthropic / gw614 / provider-null, key NAMES only,
#           the fake key value nowhere. LOGIN: the user's Claude login. Dialog: none. Network: Claude. ~1-2 min.
#   plain   Main (optional, also rehearsed): the plain MCP entry graphtraj-mcp (no Claude, no native association).
#           It refuses every subagents action of an unverified caller (authority-unavailable); PASS = discover lists
#           models and models is refused only as status is, never not-implemented. Dialog: none. No login. <30 s.
#   selftest  rehearsal aid: the judge on a SYNTHETIC stream made through the native host's backend binding.
#   post    Main. Your locations vs pre (names, sizes, mtimes). <5 s.
#   G       Main. Full suite of HEAD + the v0.10.0 wheel (6 shards, scripts/run_test_shards.py); waits for other test
#           runs first, then for its shards; its LAST lines are the verdict, counts and next command. pytest temp
#           under TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Dialog: none. No login. ~25-30 min.
#   SR      Main, read only: the newest G record classed against 516's CURRENT definition (+ the known 611 id).
#   suite-base  Main, only for SR's NEW ids: base 78f4c207 vs candidate, both with the v0.10.0 wheel.
# Credentials: before any step, every exported credential-class variable (names ending KEY, TOKEN, SECRET(S),
# PASSWORD, CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) is unset and its NAME printed. Every started process gets an
# ALLOWLIST environment (clean(): PATH HOME USER TERM TMPDIR LANG and the step's own NAME=value). Claude processes get
# your HOME (their login); GraphTraj processes get HOME=ROOT/home. FAKE614_KEY is a fake value the script makes; it is
# given only to the graphtraj MCP server (in ROOT/mcp-614.json) so the judge can show it never appears. No API key.
# Rehearsal only (Engineer; Main leaves all unset): VERIFY614_ROOT, VERIFY614_T, VERIFY614_OUT, VERIFY614_USERHOME,
# VERIFY614_DEPS, VERIFY614_PYTEST_ARGS, VERIFY614_GWAIT, VERIFY614_CLAUDE (a stand-in path recorded by setup, never
# run), VERIFY614_NO_PROMPT=1 (pre and real stop before claude -p).
# A run with any of them set prints REHEARSAL and is not acceptance evidence.
# No zsh special parameter name is used as a variable (path, status, argv, prompt, reply, match, ...).
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
STEP=${1:-}
TASKDIR=614-graphtraj-subagents-models-discovery
GREPO=$H/graftling                                  # read only
GCOMMIT=6f4aeb8fe9f47b71d81b9771486167b123308066    # graftling 0.10.0 (612), tag v0.10.0
GVERSION=0.10.0
GTBASE=78f4c207c9261e5f66420ac7c8b135406d3d54f5    # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: deps are copied from here
DEPS=(${=${VERIFY614_DEPS:-$RTSP}})
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
ROOT=${VERIFY614_ROOT:-/private/tmp/graphtraj-614}  # isolated project, HOME and venv (outside the Harness)
T=${VERIFY614_T:-$H/tmp/614}                        # suite venvs, sources and records
OUT=${VERIFY614_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost}
UH=${VERIFY614_USERHOME:-$HOME}
HOMEDIR=$ROOT/home
P=$ROOT/proj
VENV=$ROOT/venv
FAKE=$ROOT/fake614.value                            # a FAKE key value (not a credential)
X614=$SD/x614.py
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN_EXTRA=("tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]")   # 611; base too
PYTEST_TMP=${TMPDIR:-/tmp}
BASEPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
REHEARSAL=$(print -r -- ${(k)parameters[(I)VERIFY614_*]})

say()  { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
# Allowlist environment: PATH HOME USER TERM TMPDIR LANG and the given NAME=value words, then the command.
clean() { env -i PATH=$VENV/bin:$HOME/.local/bin:$BASEPATH HOME=$HOMEDIR USER=${USER:-user} TERM=${TERM:-xterm} \
            TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8 "$@"; }
claude_bin() {  # the user's Claude CLI (absolute); VERIFY614_CLAUDE only in a rehearsal (a stand-in path, never run there)
  local c=${VERIFY614_CLAUDE:-$HOME/.local/bin/claude}; [[ -x $c ]] || c=$(command -v claude 2>/dev/null)
  print -r -- ${c:-NOT-FOUND}
}
inproj() { (cd $P && clean "$@"); }
user_state() {  # names, sizes and mtimes only, never contents
  local d; for d in $UH/.graphtraj $UH/.codex $UH/.pi/agent $UH/.dsh; do
    ls -laT $d 2>&1 | awk -v d=${d#$UH/} 'NF >= 10 && $10 != ".." {print d, $5, $6, $7, $8, $9, $10}'
  done
}
outside() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
copy_deps() {  # venv: click, PyYAML, websockets copied from production (read only) when the venv lacks them
  local V=$1 D m s found
  D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    found=0
    for s in $DEPS; do
      [[ -d $s/$m ]] || continue
      case $m in
        yaml) cp -Rp $s/yaml $s/_yaml(N) $s/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
        *) cp -Rp $s/$m $s/$m-*.dist-info(N) $D/ ;;
      esac && { found=1; break; }
    done
    (( found )) || { print -r -- "STOP: $m not found in ${DEPS[*]}"; return 1; }
  done
}
graftling_wheel() {  # $1 dir: graftling v0.10.0 built offline from git archive into $1/wheels
  local S=$1
  rm -rf -- $S/graftling && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  clean $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null
}
venv_ready() { [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]] || { print -r -- "STOP: $VENV is not HEAD $HEAD; run: zsh $THIS install"; return 1; } }
other_suites() {  # exit 2 when ps cannot list (never read as "none")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then print -r -- "ps cannot list processes"; return 2; fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E' ; return 0
}
cdef_516() {  # Task 516's CURRENT definition file, through its task.yml current_definition
  local c=${${${(M)${(f)"$(cat $D516/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- ${c:+$D516/$c}
}
grec() { print -r -- ${$(print -l $T/G-*(N/om[1])):-$T/G-none}; }
sr_classify() {  # $1 = G record; sets SR_NEW SR_ANY SR_IDS; writes <record>/new-ids.txt
  local rec=$1 line t id K=$(cdef_516); SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): ${K:-unreadable}"
  [[ -f $K ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if (( ${KNOWN_EXTRA[(Ie)$id]} )); then print -r -- "  known (611, fails on base too; graftling's models description says 'starts no Agent'): $id"
    elif grep -qF -- "${t##*::}" $K; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print -r -- "  (no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL ' $rec/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *': exit 5') grep -q '^REHEARSAL' $rec/run.txt && print -r -- "  rehearsal filter, nothing collected: $line" || { print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1; } ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -l -- $SR_IDS > $rec/new-ids.txt
}
g_venv() {  # $1 venv, $2 checkout: graftling v0.10.0 WHEEL + the checkout editable (the suite needs its metadata)
  local V=$1 S=$1-src
  [[ $(cat $V/installed 2>/dev/null) == "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" ]] && { print -r -- "reusing $V"; return 0; }
  rm -rf -- $V $S && mkdir -p $S || return 1
  graftling_wheel $S || return 1
  clean $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  clean $V/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && clean $V/bin/python -m pip install $PIP -e $2 > /dev/null || return 1
  print -r -- "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" > $V/installed
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT; ONE one-line claude -p (no MCP, no tool). LOGIN: the user's Claude login (Main asks the user first). Dialog: none."
  OK=1
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists (an earlier run). Look at it, then run exactly:"; print -r -- "  rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  mkdir -p $ROOT $HOMEDIR $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT cat-file -e "$GTBASE^{commit}" 2>/dev/null && pass "base GraphTraj $GTBASE resolvable" || fail "base $GTBASE not in $WT"
  [[ $(git -C $GREPO rev-parse -q --verify 'v0.10.0^{commit}' 2>/dev/null) == $GCOMMIT ]] \
    && pass "graftling v0.10.0 = $GCOMMIT in $GREPO (wheel source)" || fail "graftling v0.10.0 is not $GCOMMIT in $GREPO"
  local dirty=$(git -C $WT status --porcelain -- src tests scripts/verify-614/steps.zsh scripts/verify-614/x614.py pyproject.toml)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, the step files" || fail "uncommitted changes: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m s; for m in click yaml websockets; do s=0; for d in $DEPS; do [[ -d $d/$m ]] && s=1; done
    (( s )) && pass "$m present in ${DEPS[*]}" || fail "$m missing in ${DEPS[*]}"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/ 2>/dev/null
  print -r -- "your locations before (names, sizes, mtimes): $(wc -l < $ROOT/user-before.txt | xargs) lines in $ROOT/user-before.txt (~/.claude and ~/.claude.json are not compared: claude -p records its Sessions there)"
  local C=$(claude_bin)
  [[ -x $C ]] && pass "claude: $C -> ${C:A}" || fail "no Claude CLI at ~/.local/bin/claude or on PATH"
  [[ ${VERIFY614_NO_PROMPT:-} == 1 ]] || print -r -- "claude --version: $(clean HOME=$HOME $C --version 2>&1 | head -1)"
  print -r -- "claude's environment (names only): $(clean HOME=$HOME /usr/bin/env | cut -d= -f1 | sort | xargs)"
  if [[ ${VERIFY614_NO_PROMPT:-} == 1 ]]; then print -r -- "REHEARSAL: claude -p skipped (VERIFY614_NO_PROMPT=1)"
  else
    (cd $ROOT && clean HOME=$HOME /usr/bin/perl -e 'alarm shift; exec @ARGV' 180 $C -p --output-format stream-json --verbose --strict-mcp-config \
       <<< 'Reply in one line: the exact model id you run as, and whether you are signed in with a Claude account or an API key.' \
       > $ROOT/pre-stream.jsonl 2> $ROOT/pre-stderr.txt); print -r -- "claude -p exit=$?"
    clean $CONDA -I -c 'import json, sys
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "system" and d.get("subtype") == "init": print("init: model", d.get("model"), "| apiKeySource", d.get("apiKeySource"))
    if d.get("type") == "result": print("answer:", str(d.get("result"))[:200], "| is_error", d.get("is_error")); sys.exit(1 if d.get("is_error") else 0)
sys.exit(1)' $ROOT/pre-stream.jsonl && pass "the Claude host answered (model and login above)" \
      || fail "no answer from claude -p; stderr: $(head -c 300 $ROOT/pre-stderr.txt). If it says login: the USER signs in with 'claude' in Terminal, then rm -rf ${(qq)ROOT} && zsh $THIS pre"
    cp $ROOT/pre-stream.jsonl $ROOT/pre-stderr.txt $OUT/ 2>/dev/null
  fi
  print -r -- "writes: $ROOT and copies in $OUT only. dialog: none."
  (( OK )) && print -r -- "RESULT 614 pre: PASS" || print -r -- "RESULT 614 pre: FAIL (lines above)"
  (( OK )) && print -r -- "next (paste): zsh $THIS install" || print -r -- "next: report the FAIL lines (then: rm -rf ${(qq)ROOT} && zsh $THIS pre)"
  (( OK ))
  ;;
install)
  say "[install] Main. $VENV: GraphTraj $HEAD (wheel) + graftling $GVERSION ($GCOMMIT wheel), offline. Dialog: none. No login."
  OK=1
  need $ROOT/user-before.txt pre || return 1
  local S=$ROOT/venv-src
  if [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]]; then print -r -- "reusing $VENV (graphtraj $HEAD)"
  else
    rm -rf -- $VENV $S && mkdir -p $S/graphtraj || return 1
    git -C $WT archive $HEAD | tar -x -C $S/graphtraj || return 1
    graftling_wheel $S || return 1
    clean $CONDA -m pip wheel $PIP -w $S/wheels $S/graphtraj > /dev/null || { print -r -- "STOP: GraphTraj wheel build failed"; return 1; }
    clean $CONDA -m venv $VENV && copy_deps $VENV || return 1
    clean $VENV/bin/python -m pip install $PIP $S/wheels/graftling-*.whl $S/wheels/graphtraj-*.whl || return 1
    print -r -- $HEAD > $VENV/installed
  fi
  (cd $ROOT && clean $VENV/bin/python -I -c 'import sys, graphtraj, graftling, importlib.metadata as m
from pathlib import Path
url = m.distribution("graphtraj").read_text("direct_url.json") or ""
site = Path(sys.argv[1]).resolve()
ok = Path(graphtraj.__file__).resolve().is_relative_to(site) and "editable" not in url
print("graphtraj", graphtraj.__file__, "| wheel:", ok, "| graftling", graftling.__version__, graftling.__file__)
sys.exit(0 if ok and graftling.__version__ == sys.argv[2] and Path(graftling.__file__).resolve().is_relative_to(site) else 1)' $VENV $GVERSION) \
    && pass "venv imports graphtraj $HEAD (wheel) and graftling $GVERSION ($GCOMMIT wheel)" || fail "venv does not import both wheels"
  grep -q 'def role_models' $VENV/lib/python3.13/site-packages/graphtraj/execution/agent_driver.py \
    && pass "installed GraphTraj has role_models (614)" || fail "installed GraphTraj lacks the 614 change"
  for m in graphtraj graphtraj-mcp; do [[ -x $VENV/bin/$m ]] && pass "$VENV/bin/$m" || fail "$VENV/bin/$m missing"; done
  print -r -- "writes: $VENV and $S only. dialog: none."
  (( OK )) && print -r -- "RESULT 614 install: PASS" || print -r -- "RESULT 614 install: FAIL (lines above)"
  (( OK )) && print -r -- "next (paste): zsh $THIS setup" || print -r -- "next: fix the FAIL lines, then: zsh $THIS install"
  (( OK ))
  ;;
setup)
  say "[setup] Main. Project $P, isolated catalog $HOMEDIR/.graphtraj/connections.yml, roles, Claude host material. Dialog: none. No login."
  OK=1
  venv_ready || return 1
  [[ -e $P ]] && { print -r -- "STOP: $P exists (an earlier setup). Start over: rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  mkdir -p $P $HOMEDIR/.graphtraj || return 1
  (cd $P && git init -q -b main && print -r -- "# 614 probe: subagents models" > README.md && git add README.md \
     && git -c user.name=614 -c user.email=614@invalid commit -qm "Initial source") || return 1
  print y | inproj $VENV/bin/graphtraj setup 2>&1 | tail -2
  [[ -d $P/.graphtraj ]] && pass "graphtraj setup created $P/.graphtraj" || fail "graphtraj setup made no $P/.graphtraj"
  local draft=$ROOT/catalog-draft.yml
  clean $VENV/bin/python -I $X614 catalog $draft || return 1
  inproj $VENV/bin/graphtraj connections --action preview --catalog-file $draft > $ROOT/catalog-preview.yml 2>&1 \
    && pass "public preview accepts the catalog (gw614: base_url + api_key_env)" \
    || { fail "public preview refused the catalog: $(tail -3 $ROOT/catalog-preview.yml)"; return 1; }
  cp $draft $HOMEDIR/.graphtraj/connections.yml || return 1
  inproj $VENV/bin/graphtraj connections --action read > $ROOT/catalog-read.yml 2>&1 \
    && grep -q "path: $HOMEDIR/.graphtraj/connections.yml" $ROOT/catalog-read.yml \
    && pass "public read uses the isolated catalog ($(grep -m1 'revision:' $ROOT/catalog-read.yml | xargs))" \
    || fail "public read does not show the isolated catalog ($ROOT/catalog-read.yml)"
  inproj $VENV/bin/python -I $X614 roles $P || OK=0
  inproj $VENV/bin/graphtraj roles organize > $ROOT/roles-preview.yml 2>&1 \
    && pass "public role preview: $(grep -oE '\b(claude|routed|inline|coder)\b' $ROOT/roles-preview.yml | sort -u | xargs)" \
    || fail "public role preview failed: $(tail -3 $ROOT/roles-preview.yml)"
  local C=$(claude_bin)
  inproj $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write > $ROOT/host-configuration.txt 2>&1 \
    && pass "Claude host material written: $(tr -d '\n ' < $ROOT/host-configuration.txt | cut -c1-200)" || fail "host configuration --write failed ($ROOT/host-configuration.txt)"
  clean $CONDA -I -c 'import secrets; print("fake-614-" + secrets.token_hex(12))' > $FAKE && chmod 600 $FAKE
  clean $VENV/bin/python -I $X614 mcpconfig $P/.mcp.json $ROOT/mcp-614.json $HOMEDIR $FAKE || OK=0
  cp $ROOT/catalog-read.yml $ROOT/roles-preview.yml $ROOT/mcp-614.json $OUT/ 2>/dev/null
  print -r -- "writes: $ROOT only (project, isolated HOME, the fake value $FAKE). dialog: none."
  (( OK )) && print -r -- "RESULT 614 setup: PASS" || print -r -- "RESULT 614 setup: FAIL (lines above)"
  (( OK )) && print -r -- "next: the USER runs the trust step once (zsh $THIS trust prints it), then Main: zsh $THIS real" \
           || print -r -- "next: report the FAIL lines"
  (( OK ))
  ;;
trust)
  say "[trust] USER, once per path $P (Main cannot: it needs a terminal and a dialog). In a plain macOS Terminal:"
  print -r -- "  cd ${(qq)P} && $(claude_bin) --strict-mcp-config"
  print -r -- "Dialog: 'Do you trust the files in this folder?' naming $P. Choose 'Yes, proceed'."
  print -r -- "If a second dialog asks about this project's plugin graphtraj-claude-host or its hooks, approve it for this project."
  print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print -r -- "Why: Claude Code loads a project's plugin (here the graphtraj-claude-host hook that prepares each native call)"
  print -r -- "only in a trusted folder, and records trust only through this dialog; claude -p never asks."
  print -r -- "--strict-mcp-config: this start loads no MCP server, so no MCP approval dialog appears."
  print -r -- "RESULT 614 trust: instructions printed (nothing was run)"
  print -r -- "next (Main, after the USER's /exit): zsh $THIS real"
  ;;
real)
  say "[real] Main. ONE claude -p in $P: subagents discover, describe models, execute models {runtime: claude}. LOGIN: the user's Claude login. Dialog: none (the folder was trusted in the trust step). ~1-2 min."
  OK=1
  venv_ready && need $ROOT/mcp-614.json setup && need $FAKE setup || return 1
  local C=$(claude_bin) PR=$(clean $VENV/bin/python -I $X614 prompt)
  print -r -- "prompt (one line): $PR"
  print -r -- "MCP: $(clean $VENV/bin/python -I -c 'import json, sys; e = json.load(open(sys.argv[1]))["mcpServers"]["graphtraj"]; print(e["command"], *e["args"], "| env names:", sorted(e.get("env", {})))' $ROOT/mcp-614.json)"
  print -r -- "claude's environment (names only): $(clean HOME=$HOME /usr/bin/env | cut -d= -f1 | sort | xargs) | allowed tools: mcp__graphtraj__subagents"
  if [[ ${VERIFY614_NO_PROMPT:-} == 1 ]]; then print -r -- "REHEARSAL: claude -p skipped (VERIFY614_NO_PROMPT=1)"; print -r -- "RESULT 614 real: NOT RUN (rehearsal)"; return 0; fi
  rm -f $ROOT/real-stream.jsonl $ROOT/real-stderr.txt
  (cd $P && clean HOME=$HOME /usr/bin/perl -e 'alarm shift; exec @ARGV' 600 $C -p --output-format stream-json --verbose \
     --mcp-config $ROOT/mcp-614.json --strict-mcp-config --allowedTools mcp__graphtraj__subagents \
     <<< $PR > $ROOT/real-stream.jsonl 2> $ROOT/real-stderr.txt); print -r -- "claude -p exit=$? (stream $ROOT/real-stream.jsonl)"
  print -r -- "host log (last lines): $(tail -3 $P/.graphtraj/claude-host/host.log 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
  cp $ROOT/real-stream.jsonl $ROOT/real-stderr.txt $OUT/ 2>/dev/null
  say "judge (from the stream)"
  clean $VENV/bin/python -I $X614 judge $ROOT/real-stream.jsonl $ROOT/real-stderr.txt $FAKE | tee $ROOT/real-judge.txt; local jrc=${pipestatus[1]}
  cp $ROOT/real-judge.txt $OUT/ 2>/dev/null
  print -r -- "re-judge (paste): $VENV/bin/python -I $X614 judge $ROOT/real-stream.jsonl $ROOT/real-stderr.txt $FAKE"
  (( jrc == 0 )) && print -r -- "RESULT 614 real: PASS ($(grep -m1 '^serving path:' $ROOT/real-judge.txt | cut -c1-80))" \
                 || print -r -- "RESULT 614 real: FAIL (judge above; if 'NOT loaded': the USER runs: zsh $THIS trust; then zsh $THIS real)"
  print -r -- "next (paste): zsh $THIS plain"
  return $jrc
  ;;
selftest)
  say "[selftest] Rehearsal aid (Main may skip it): the judge on a SYNTHETIC stream made in-process through graftling's handle_request bound to GraphTraj's backend as the native host binds a Main. Not a real host, not evidence. Dialog: none. No login."
  venv_ready && need $FAKE setup || return 1
  inproj FAKE614_KEY=$(<$FAKE) $VENV/bin/python -I $X614 selftest $P $FAKE $ROOT/selftest-stream.jsonl | tee $ROOT/selftest-judge.txt; local jrc=${pipestatus[1]}
  cp $ROOT/selftest-stream.jsonl $ROOT/selftest-judge.txt $OUT/ 2>/dev/null
  (( jrc == 0 )) && print -r -- "RESULT 614 selftest: PASS (synthetic; not evidence)" || print -r -- "RESULT 614 selftest: FAIL (above)"
  print -r -- "next (paste): zsh $THIS real"
  return $jrc
  ;;
plain)
  say "[plain] Main (optional supplement). The plain MCP entry $VENV/bin/graphtraj-mcp in $P (no Claude, no native association): discover, describe models, execute models, execute status. Without a verified caller this entry refuses every subagents action alike; PASS = models is listed and refused only as status is (never not-implemented). Dialog: none. No login."
  venv_ready && need $FAKE setup || return 1
  inproj FAKE614_KEY=$(<$FAKE) $VENV/bin/python -I $X614 mcp $P $FAKE $VENV/bin/graphtraj-mcp | tee $ROOT/plain-judge.txt; local jrc=${pipestatus[1]}
  cp $ROOT/plain-judge.txt $OUT/ 2>/dev/null
  (( jrc == 0 )) && print -r -- "RESULT 614 plain: PASS" || print -r -- "RESULT 614 plain: FAIL (above)"
  print -r -- "next (paste): zsh $THIS post"
  return $jrc
  ;;
post)
  say "[post] Main. Your ~/.graphtraj, ~/.codex, ~/.pi/agent, ~/.dsh vs pre (names, sizes, mtimes). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "your locations are unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT (copies in $OUT). To remove everything afterwards: rm -rf ${(qq)ROOT}"
  (( OK )) && print -r -- "RESULT 614 post: PASS" || print -r -- "RESULT 614 post: FAIL"
  print -r -- "next (paste): zsh $THIS G"
  (( OK ))
  ;;
G)
  say "[G] Main. Full GraphTraj suite: HEAD $HEAD (editable) + graftling $GVERSION ($GCOMMIT wheel), 6 shards. This process waits for any other test run, then for its shards, then judges; its LAST lines are the verdict, counts and next command. pytest temp under TMPDIR=$PYTEST_TMP (outside the Harness). Dialog: none. No login. ~25-30 min."
  outside || return 1
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  local busy; busy=$(other_suites) || { print -r -- "STOP: $busy (nothing started)"; return 1; }
  local GV=$T/gvenv-614 O=$T/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${PYTEST_TMP:A}/verify-614-G-$(date +%Y%m%dT%H%M%S)
  mkdir -p $T $O $RUNTMP || return 1
  g_venv $GV $WT || { print -r -- "STOP: suite venv"; return 1; }
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
    print -r -- "launch environment: PATH HOME USER TERM TMPDIR LANG only (clean(); no provider credential)"
    print -r -- "candidate: $HEAD | graftling wheel from git archive $GCOMMIT (v$GVERSION)"
    (cd $RUNTMP && clean $GV/bin/python -I -c 'import importlib.metadata as m; print("test interpreter:", " | ".join(f"{n} {m.version(n)}" for n in ("click", "PyYAML", "websockets", "pytest", "graftling", "graphtraj")))')
    [[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not evidence): $REHEARSAL"; } > $O/run.txt
  local -a extra=(${(Q)${(z)${VERIFY614_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${extra[*]}" >> $O/run.txt
  cat $O/run.txt; print -r -- "record: $O"
  while true; do
    busy=$(other_suites) || { print -r -- "STOP: ps failed; G did not start"; return 1; }
    [[ -z $busy ]] && break
    print -r -- "$(date +%T) waiting for another test run: $(print -r -- $busy | awk '{print $1}' | xargs)" | tee -a $O/wait.txt; sleep ${VERIFY614_GWAIT:-60}
  done
  print -r -- "$(date +%T) started (6 shards; this step waits for them)" | tee -a $O/wait.txt
  (cd $WT && clean TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra \
     > $O/suite.txt 2>&1 < /dev/null)
  print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended: $(tail -1 $O/suite.txt)" | tee -a $O/wait.txt
  STEP=GR; run_step; return $?
  ;;
GR)
  say "[GR] read only: the newest G record judged (G runs this at its end; Main may rerun it)."
  local rec=$(grec); print -r -- "G record: $rec"
  [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "RESULT 614 G: NOT ENDED (no exit= line in $rec/suite.txt)"; return 1; }
  sed 's/^/  run.txt: /' $rec/run.txt
  local tot=$(grep -hE '^=*.* (passed|failed)' $rec/shards/*(N.) | sed "s#^#  #") ex=$(sed -n 's/^exit=//p' $rec/suite.txt | tail -1)
  print -r -- "shard totals:"; print -r -- $tot
  sr_classify $rec
  local rf=0; grep -q '^REHEARSAL' $rec/run.txt && rf=1
  local verdict=FAIL; (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && ( $SR_ANY == 1 || $rf == 1 ) ) ]] && verdict=PASS
  cp -R $rec $OUT/ 2>/dev/null
  local kn=$(sr_classify $rec | grep -c '^  known') nw=$#SR_IDS
  print -r -- ""
  print -r -- "RESULT 614 G: $verdict | exit $ex | known non-blocking ids: $kn | NEW ids: $nw$( (( rf )) && print ' | REHEARSAL (not evidence)')"
  if [[ $verdict == PASS ]]; then print -r -- "next: report RESULT 614 G (record $rec)"
  else print -r -- "next (paste): zsh $THIS SR"; return 1; fi
  ;;
SR)
  say "[SR] Main, read only: the newest G record's FAILED/ERROR ids and ABNORMAL shards against 516's current definition. Dialog: none."
  local rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no ended G record ($rec)"; return 1; }
  tail -4 $rec/suite.txt; sr_classify $rec
  print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else print -r -- "next: none for suite-base (no NEW id)"; fi
  return $SR_NEW
  ;;
suite-base)
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file"; return 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; return 2; }
  say "[suite-base] Main, only for SR's NEW ids ($#ids): base GraphTraj $GTBASE vs candidate HEAD $HEAD, both with graftling $GVERSION (wheel). pytest temp under TMPDIR (outside the Harness). Dialog: none."
  outside || return 1
  local o; o=$(other_suites) || { print -r -- "STOP: $o"; return 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; return 1; }
  local B=$T/graphtraj-base VB=$T/sbvenv-${GTBASE[1,8]} VC=$T/gvenv-614
  if [[ ! -d $B/.git ]]; then rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
     && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1; fi
  g_venv $VB $B && g_venv $VC $WT || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S) side dir V src RUNTMP; mkdir -p $R; print -l -- $ids > $R/ids.txt
  for side dir V in base $B $VB candidate $WT $VC; do
    RUNTMP=${PYTEST_TMP:A}/verify-614-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $dir | temp $RUNTMP"
    (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $R/$side-collected.txt 2>&1)
    clean $CONDA -I $SUITEIDS present $R/$side-collected.txt $R/ids.txt > $R/$side-ids.txt 2> $R/$side-missing.txt
    local -a run=(${(f)"$(<$R/$side-ids.txt)"})
    if (( $#run )); then (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $R/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $R/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $R/$side.txt | tail -1) ($R/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $R/ids.txt $R/base.txt $R/candidate.txt | tee $R/classification.txt; local fails=${pipestatus[1]}
  cp -R $R $OUT/ 2>/dev/null
  print -r -- ""; print -r -- "RESULT 614 suite-base: $( (( fails == 0 )) && print 'PASS (no candidate-only failure)' || print 'FAIL (classification above)') | ids: $#ids | record: $R"
  print -r -- "next: report the classification; a candidate-only id is a regression of this Task"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|install|setup|trust|selftest|real|plain|post|G|GR|SR|suite-base --from <file>|<ids>..."; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n $REHEARSAL ]] || { print "STOP: $H is not the Harness root"; exit 1; }
scrub() {  # unset every exported credential-class name; print the names removed
  local k u part; local -a gone=()
  for k in ${(k)parameters[(R)*export*]}; do
    u=${(U)k}; [[ $u == GIT_CONFIG_KEY_<-> ]] && continue
    for part in ${(s:_:)u}; do
      [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && { gone+=$k; unset $k; break; }
    done
  done
  print -r -- "credential scrub: removed from this script's environment (names only): ${gone:-none}"
}
scrub
[[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not acceptance evidence): $REHEARSAL"
OK=1
IDS=("${(@)@[2,-1]}")
mkdir -p $OUT 2>/dev/null
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
