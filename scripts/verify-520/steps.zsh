#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 520 steps: how DSH's browser tool view shows an agents call, graftling alone (mcp__graftling__agents) and
# as GraphTraj DSH Main (mcp__graphtraj__agents); and step R, the content 'all' redaction test.
#   zsh scripts/verify-520/steps.zsh <STEP>        (Main, from this Task's Worktree)
# Order: 0 -> S -> G -> U (USER, plain Terminal and browser) ; R at any time.
#   0  preflight: versions, wheels and venv, isolated project and probe Task 1, the isolated DSH home with the web
#      profile web520 (fresh copy of the shipped web template) and graftling-dsh added to it, one one-line answer
#      from dsh/deepseek-flash (model and login). Dialog: none.
#   S  graftling alone: a headless DSH Session (graftling-dsh agents-host row) makes one mcp__graftling__agents call.
#   G  GraphTraj DSH Main (graphtraj-main row) makes one mcp__graphtraj__agents call.
#   U  USER: what to run in a plain Terminal to open the web UI on S's and G's Sessions, and what to screenshot.
#   R  tests/test_agents_session_read.py (Part 1) in a test venv; pytest's TMPDIR stays outside the Harness.
# Everything is under BASE=/private/tmp/graphtraj-520 (projects, venvs, DSH_HOME). The user's own DSH install,
# ~/.dsh and settings are never read or written: every dsh call has DSH_HOME=$DH. No step starts or connects to the
# Harness's production MCP servers, and no step signals a process it did not start. Nothing is written in the Harness.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree (the candidate)
H=${WT:h:h:h:h}                                        # <Harness>
GDEV=$H/.graphtraj/core/worktrees/graftling-dev        # graftling Integration Worktree (read only: git archive)
GCOMMIT=a51e1004a0fe77fe492681faa2f278d80b3d725e        # graftling 0.6.0 (513), as 514
# VERIFY520_* are set only by a rehearsal (scratch BASE; no model call); the defaults are the real paths.
BASE=${VERIFY520_BASE:-/private/tmp/graphtraj-520}
P=$BASE/project; W=$BASE/work-standalone; V=$BASE/venv; VT=$BASE/venv-test; DH=$BASE/dsh-home; OUT=$BASE/runs
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: yaml, websockets, click (no PyPI on this host)
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
MODEL=deepseek-flash
WEB=web520                                             # the isolated web profile (in $DH only)
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY520_STUB:-} ]] && path=($VERIFY520_STUB $path)   # rehearsal only: a stub dsh first

say() { print -r -- "== $*"; }
next() { print -r -- "next: zsh $THIS $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# A host inherits no marker of the Harness Main (GraphTraj/graftling connections, DSH Session); DSH_HOME is isolated.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} DSH_HOME=$DH ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
load_key() {  # verify-514 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
deps() {  # $1 venv: PyYAML, click and websockets from production's site-packages (copied, never changed there)
  local SP=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $RT/websockets $RT/websockets-*.dist-info(N) \
    $RT/click $RT/click-*.dist-info(N) $SP/
}
wheel() {  # $1 repository, $2 commit, $3 subdirectory, $4 output directory
  local src=$4/src-${2[1,10]}; rm -rf $src; mkdir -p $src $4
  git -C $1 archive $2 $3 | tar -x -C $src
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $4 $src/$3 >/dev/null
}
need() {  # $1 directory, $2 pattern: the one file it must hold
  local found=($1/$~2(N))
  (( $#found == 1 )) && { print -r -- $found; return 0; }
  print -r -- "STOP: expected exactly one $2 in $1, found ${#found}" >&2; return 1
}
candidate() { git -C $WT rev-parse HEAD; }
gdsh() { $V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
begin() {  # $1 step: the run directory and its time marker
  D=$OUT/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D; touch $D/marker
  print -r -- "candidate $(candidate) graftling $GCOMMIT step $1" > $D/run.txt
  print -r -- "run records: $D"
}
llm_patch() {  # the DeepSeek provider row (as 513/514), appended to a patch file
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
# The Session a headless run wrote: its id from --json stdout, and the DSH Session files changed since the marker.
session_of() {  # $1 run directory
  local id=$($CONDA -I -c 'import json, re, sys
ids = []
for line in open(sys.argv[1], errors="replace"):
    for key, value in re.findall(r"\"(sessionId|session_id|session)\"\s*:\s*\"([^\"]+)\"", line):
        if value not in ids: ids.append(value)
print(ids[0] if ids else "")' $1/stdout.jsonl 2>/dev/null)
  print -r -- ${id:-unknown} > $1/session.txt
  print -r -- "DSH Session id (stdout.jsonl): ${id:-not found; see the files below}"
  print -r -- "DSH Session files changed in this run:"
  find $DH -type f -newer $1/marker ! -path '*/profiles/*' 2>/dev/null | head -20 | sed 's/^/  /'
}
agents_calls() {  # $1 run directory: the agents tool calls and results in stdout.jsonl (names and status only)
  grep -oE '"(name|toolName)"\s*:\s*"mcp__[a-z]+__agents"|"(status|isError)"\s*:\s*("[a-z_-]+"|true|false)' $1/stdout.jsonl \
    2>/dev/null | sort | uniq -c | sed 's/^/  /' || print "  (no agents tool call in stdout.jsonl)"
}
web_command() {  # $1 patch file or '' : the plain-Terminal command that serves the isolated web profile
  print -r -- "cd ${2:-$P} && env DSH_HOME=$DH ${3:-}dsh --profile $WEB ${1:+--patch $1 }--port 0"
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT
case $STEP in
0)
  say "[0] preflight. Dialog: none. Builds wheels and a venv (no network), the isolated project and DSH home, then one one-line dsh answer (at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); dsh $(clean dsh --version 2>&1 | tail -1); node $(node --version 2>&1)"
  print "candidate: $WT $(candidate) (branch $(git -C $WT branch --show-current)); graftling: $GDEV ${GCOMMIT[1,10]}"
  print "isolated layout: BASE=$BASE  project=$P  standalone work=$W  venv=$V  DSH_HOME=$DH (never ~/.dsh)"
  local Wh=$BASE/wheels C=$(candidate); mkdir -p $Wh $W $DH
  if [[ ! -f $V/installed || $(<$V/installed) != "$C $GCOMMIT" ]]; then
    rm -f $Wh/graftling-*.whl(N) $Wh/graphtraj-*.whl(N)
    wheel $GDEV $GCOMMIT src/graftling $Wh && wheel $WT $C . $Wh || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $Wh 'graftling-*.whl') && hw=$(need $Wh 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V; deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw $hw
    print -r -- "$C $GCOMMIT" > $V/installed
  else print "venv $V already holds $C + graftling ${GCOMMIT[1,10]}"; fi
  (cd $BASE && clean $V/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m
print("venv: graftling", m.version("graftling"), "graphtraj", m.version("graphtraj"), "from", graphtraj.__file__.split("/lib/")[0])')
  say "isolated GraphTraj project and probe Task 1 (G)"
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 520 probe" > README.md && git add README.md \
      && git -c user.name=520 -c user.email=520@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $P && clean $V/bin/python -I $WT/scripts/verify-514/prep514.py $P) || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
  say "patches: G = GraphTraj's graphtraj-main row; S = graftling-dsh's agents-host row"
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $BASE/graphtraj-main.patch.yml >/dev/null
  llm_patch >> $BASE/graphtraj-main.patch.yml
  { print -r -- "- insert:"; print -r -- "  - {id: agents-host, name: $(gdsh)/plugin.mjs}"; llm_patch; } > $BASE/graftling-alone.patch.yml
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $BASE/graftling-data $(command -v dsh) $MODEL $BASE/dsh-host.json
  mkdir -p $BASE/graftling-data; print "save_normalized_sessions: true" > $BASE/graftling-data/config.yml
  say "isolated web profile $WEB in $DH: a fresh copy of the shipped web template, then graftling-dsh added (its browser tool view)"
  (cd $BASE && clean dsh --profile $WEB --from-default-profile web --dump-config > $BASE/web-dump-config.txt 2>&1) \
    && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $BASE/web-dump-config.txt; return 1; }
  if grep -q graftling-dsh $DH/profiles/$WEB/package.json 2>/dev/null; then print "graftling-dsh: already in $WEB"
  else
    # This host's /opt/homebrew/bin/pnpm is pnpm 12's placeholder (its native binary was never installed: spawn
    # ENOEXEC), so dsh plugin gets a shim running pnpm's own bin/pnpm.mjs, and a pnpm store under BASE.
    mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
    chmod +x $BASE/bin/pnpm
    (cd $BASE && clean PATH=$BASE/bin:${(j.:.)path} npm_config_store_dir=$BASE/pnpm-store $BOUND 300 \
       dsh plugin --profile $WEB add $(gdsh) > $BASE/plugin-add.txt 2>&1) && print "graftling-dsh: added to $WEB" \
      || { print "WARNING: dsh plugin add failed (rc $?); the web view then has no graftling-dsh tool view at all:"
           grep -vi npmrc $BASE/plugin-add.txt | tail -6; }
  fi
  print "web profile dependencies: $($CONDA -I -c 'import json, sys; print(list(json.load(open(sys.argv[1])).get("dependencies", {})))' $DH/profiles/$WEB/package.json)"
  # Which keys the added bundle's tool view registers (as verify-513 D's client-view-keys).
  node -e '
const { readFileSync } = require("node:fs"); const vm = require("node:vm"); let m;
vm.runInNewContext(readFileSync(process.argv[1], "utf8"), { window: { __ModuleLoader__: { load(d) { m = d; } } } });
const keys = [];
m.factory(() => ({ createElement: () => ({}) })).apply({ slots: { inject: (n, f) => f(), entriesOfSlot: () => [],
  subscribe: () => () => {}, register: (o) => { keys.push(o.key); return () => {}; } } });
console.log("graftling-dsh tool view keys: " + JSON.stringify(keys));' $(gdsh)/client.mjs | tee $BASE/client-view-keys.txt
  if [[ -n ${VERIFY520_NOMODEL:-} ]]; then print "VERIFY520_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    (cd $BASE && clean $BOUND 120 dsh --profile headless --permission-mode read-only \
      'Reply with one line: READY-520 and your exact model name. Use no tool.' < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  fi
  print "Ready when: the venv versions, 'roles OK' and 'probe Task 1 ready', profile $WEB created with graftling-dsh, view keys listed, and one READY-520 line naming the model."
  next S
  ;;
S|G)
  [[ -f $V/installed ]] || { print "STOP: run step 0 first"; return 1; }
  load_key || return 1
  local tool patch cwd envs=()
  if [[ $STEP == S ]]; then
    tool=mcp__graftling__agents patch=$BASE/graftling-alone.patch.yml cwd=$W
    envs=(GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$BASE/dsh-host.json)
    say "[S] graftling alone: headless DSH Session (agents-host row) in $W, one $tool call. Dialog: none. At most 10 min."
  else
    tool=mcp__graphtraj__agents patch=$BASE/graphtraj-main.patch.yml cwd=$P
    say "[G] GraphTraj DSH Main (graphtraj-main row) in $P, one $tool call. Dialog: none. At most 10 min."
  fi
  begin $STEP
  print -r -- "Call the MCP tool $tool exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}}. Use no other tool. Then reply with one line: DONE-520-$STEP followed by the exact name of the tool you called and ok or the exact error." > $D/host.prompt.txt
  (cd $cwd && clean $envs $BOUND 600 dsh --profile headless520 --from-default-profile headless --patch $patch \
     --json "$(<$D/host.prompt.txt)" < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "dsh rc=$?"
  redact < $D/stderr.txt | tail -3
  print "agents calls in stdout.jsonl (expected: one $tool call, its result not an error):"; agents_calls $D
  print "last line of the answer: $(grep -oE "DONE-520-${STEP}[^\"]*" $D/stdout.jsonl | tail -1)"
  session_of $D
  print -r -- "$STEP $(<$D/session.txt) $cwd $patch" > $BASE/session-$STEP.txt
  print -r -- "follow-up (paste as is): zsh $THIS $([[ $STEP == S ]] && print G || print U)"
  ;;
U)
  say "[U] USER, in a plain Terminal (not this sandbox) and the browser. Dialogs: none expected from dsh; the browser may ask nothing. No model call is needed when the recorded Sessions are listed."
  grep -q graftling-dsh $DH/profiles/$WEB/package.json 2>/dev/null && print "web profile $WEB has graftling-dsh: YES" \
    || print "web profile $WEB has graftling-dsh: NO (step 0's plugin add failed; both cards will be generic; tell the Leader)"
  local s rec id cwd patch tool envs ptext prompts
  for s in S G; do
    rec=$BASE/session-$s.txt id=unknown envs=''
    [[ -f $rec ]] && id=$(cut -d' ' -f2 $rec)
    prompts=($OUT/$s-*/host.prompt.txt(Nom))
    if (( $#prompts )); then ptext=$(<$prompts[1]); else ptext="(the prompt of step $s; run step $s first)"; fi
    if [[ $s == S ]]; then tool=mcp__graftling__agents cwd=$W patch=$BASE/graftling-alone.patch.yml
      envs="GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$BASE/dsh-host.json "
    else tool=mcp__graphtraj__agents cwd=$P patch=$BASE/graphtraj-main.patch.yml; fi
    print -r -- "
--- Session $s ($tool): recorded id $id $([[ -f $rec ]] || print '(step '$s' has not run yet)')
1. In a plain Terminal (DEEPSEEK_API_KEY set as usual), run:
     $(web_command $patch $cwd "$envs")
   It prints the served URL (http://127.0.0.1:<port>/...) and opens it; if no browser opens, open that URL.
2. In the page, open the Session $id from the Session list (sidebar / history). If it is not listed, start a new
   conversation there and paste this prompt (one model call):
     $ptext
3. Find the tool call card for $tool in the conversation. If it has a 'Details' button or a disclosure, open it.
4. Screenshot the whole card (and the expanded details), with the tool name visible. Save it as
     $BASE/screenshot-$s.png
5. Stop the server with Ctrl-C in that Terminal."
  done
  print -r -- "
What 'normal' looks like (graftling dsh/client.mjs AgentsRow): a compact row with a line 'sender → recipient'
and a line 'agents · <operation> · <state>' (here operation status), plus a 'Details' button.
A generic DSH tool card instead shows the raw tool name and its JSON arguments/result.
Expected from the source (prediction, to be confirmed by the screenshots): S renders as AgentsRow; G renders as a
generic card, because client.mjs registers its view only for mcp__graftling__agents and mcp__agents__agents, and
GraphTraj's graphtraj-main row registers no browser view of its own.
Send both screenshots (or say which one is missing) to the Leader."
  ;;
R)
  say "[R] Part 1: tests/test_agents_session_read.py (content 'all' redaction) in $VT. Dialog: none. < 1 min."
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
  local C=$(candidate)
  if [[ ! -f $VT/installed || $(<$VT/installed) != "$C $GCOMMIT" ]]; then
    local Wh=$BASE/wheels-test gw; mkdir -p $Wh; rm -f $Wh/graftling-*.whl(N)
    wheel $GDEV $GCOMMIT src/graftling $Wh; gw=$(need $Wh 'graftling-*.whl') || return 1
    [[ -e $VT ]] && mv $VT $VT.$(date +%H%M%S)
    $CONDA -m venv --system-site-packages $VT; deps $VT
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache || true
    print -r -- "$C $GCOMMIT" > $VT/installed
  fi
  (cd $PYTEST_TMP && $VT/bin/python -I -c 'import graftling, graphtraj, pytest; print("graftling", graftling.__version__, graftling.__file__, "| graphtraj", graphtraj.__file__, "| pytest", pytest.__version__)')
  begin R
  (cd $WT && TMPDIR=$PYTEST_TMP $VT/bin/python -m pytest -p no:cacheprovider -q -rfE tests/test_agents_session_read.py \
     > $D/pytest.txt 2>&1; print "exit=$?" >> $D/pytest.txt)
  tail -3 $D/pytest.txt; grep -E '^(FAILED|ERROR) ' $D/pytest.txt || print "(no FAILED/ERROR lines)"
  print "expected: all passed, including test_content_all_redacts_reasoning_streams_records_extra_fields_and_drafts"
  ;;
*) print -r -- "usage: zsh $THIS 0|S|G|U|R"; return 2 ;;
esac
