#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 572 Main-run steps: graftling's Pi package works once installed, with no --agents-config (data root
# <project>/.agents-control) and no GRAFTLING_PYTHON (the Python of the installation the extension was loaded from).
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre       Main. Versions; ROOT must not exist (STOP otherwise) and is created; hashes of the Pi global files
#             (~/.pi/agent: settings.json, trust.json, models.json, mcp.json, keybindings.json; auth.json separately);
#             a one-line Pi prompt (--no-session --no-extensions) naming its model and provider. Dialog: none. ~30 s.
#   repro     Main. The premises on the BASE (graftling dev cadc419): `pi install -l` of the base package in
#             ROOT/proj-base, then (a) no flag, no GRAFTLING_PYTHON: does the model list mcp__graftling__agents?
#             (b) --agents-config given, GRAFTLING_PYTHON unset: the actual output. Dialog: none. ~1-2 min.
#   push      Main, after asking the user. Pushes the candidate branch to LUOXIAO92/graftling from the bundle.
#             Dialog: none expected; git uses your usual GitHub login. ~30 s.
#   install   Main. Builds ROOT/venv from the candidate (bundle, no network: dependencies copied from the Harness's
#             .venv-runtime), a Python-less copy ROOT/nopy, and runs `pi install -l` in ROOT/proj and ROOT/proj-nopy.
#             Checks that only the projects' .pi/settings.json changed. Dialog: none. ~1 min.
#   start     Main. In ROOT/proj, no flag, no GRAFTLING_PYTHON, PATH without ROOT/venv: real Pi Main uses the agents
#             tool to create a claude child (claude-haiku-5-5) that answers 'ready', waits, reads status. The record
#             lands in ROOT/proj/.agents-control. Child login: ANTHROPIC_API_KEY in an isolated
#             CLAUDE_CONFIG_DIR=ROOT/claude-home, or your own Claude login with VERIFY572_CLAUDE_USER_LOGIN=1
#             (writes ~/.claude/projects/<ROOT/proj key>/ and a ~/.claude.json project entry). Dialog: none. ~1-3 min.
#   explicit  Main. --agents-config ROOT/pi-host.json (root ROOT/agents-data) and GRAFTLING_PYTHON=ROOT/venv/bin/python:
#             the record lands in ROOT/agents-data; ROOT/proj/.agents-control gains none. Same login. ~1-3 min.
#   nopy      Main. In ROOT/proj-nopy (package copy with no interpreter), no flag, no GRAFTLING_PYTHON: a real Pi start
#             shows the extension error naming GRAFTLING_PYTHON and the model lists no agents tool. ~30 s.
#   post      Main. The Pi global hashes again, compared with pre's; how to remove ROOT. <5 s.
# Everything is under ROOT=/private/tmp/graftling-572. Pi uses your own login (~/.pi/agent) with
# --session-dir ROOT/pi-sessions, --approve (project trust for that run only) and a project-local (-l) install.
# VERIFY572_ROOT / VERIFY572_OUT are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY572_ROOT:-/private/tmp/graftling-572}
OUT=${VERIFY572_OUT:-$H/.graphtraj/core/state/tasks/572-graftling-pi-default-host-config/realhost}
URL=https://github.com/LUOXIAO92/graftling.git
BASE=cadc419271dabc8f4a0b11da1bb46c70ef598c77        # graftling dev before 572 (v0.7.0 + Task 570)
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/572-graftling-pi-default-host-config
GCOMMIT=8bdc1b2bca1edf48e7cacc65406e735efafd1e61   # the graftling candidate (base: dev cadc419)
BUNDLE=$WT/.scratch/572/graftling-572.bundle
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
JUDGE=$WT/scripts/verify-570/judge.py               # 570's verdicts: records on disk + the answer's lines
PIDIR=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}
THIS=${0:A}
STEP=${1:-}
P=$ROOT/proj
CMODEL=claude-haiku-5-5
path=(/opt/homebrew/bin ${path:#$ROOT/*})

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
# Pi with no explicit Python or channel; the Claude child's login per VERIFY572_CLAUDE_USER_LOGIN.
clean() {
  local -a drop=(-u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u GRAFTLING_NATIVE_RUNTIME
                 -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u PI_SUBAGENT_CHILD)
  if [[ -n ${VERIFY572_CLAUDE_USER_LOGIN:-} ]]; then env $drop "$@"; else env $drop CLAUDE_CONFIG_DIR=$ROOT/claude-home "$@"; fi
}
# One real Pi print-mode Session: dir name prompt [pi options...] ; sets SRC and SOUT.
session() {
  local dir=$1 name=$2 prompt=$3; shift 3
  SOUT=$ROOT/$name-$(date +%H%M%S).txt
  say "pi -p in $dir ($name) ${*:-no --agents-config}, GRAFTLING_PYTHON ${PYVAR:-unset}"
  (cd $dir && clean ${PYVAR:+GRAFTLING_PYTHON=$PYVAR} perl -e 'alarm shift; exec @ARGV' 600 \
     pi -p --session-dir $ROOT/pi-sessions --approve "$@" "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  tail -25 $SOUT; print -r -- "exit=$SRC (full output: $SOUT)"
  mkdir -p $OUT 2>/dev/null && cp $SOUT $OUT/ 2>/dev/null
}
hashes() {  # the Pi global files: name and sha256 (never contents)
  local f; for f in settings.json trust.json models.json mcp.json keybindings.json; do
    print -r -- "$f $( [[ -f $PIDIR/$f ]] && shasum -a 256 < $PIDIR/$f | cut -c1-16 || print absent)"; done
  print -r -- "packages-dirs $(print -l -- $PIDIR/{git,npm,packages}(N/) | tr '\n' ' ')"
}
count() { print -l -- $1/control/agents/*.json(N) | grep -c . }
TOOLS='List the names of all tools available to you whose names start with mcp__ on one line prefixed TOOLS: (write TOOLS: NONE if there are none). If mcp__graftling__agents is among them, call it exactly once with the input {"action":"execute","feature":"status","arguments":{}} and print its result verbatim on one line prefixed RESULT:. If it is not among them, write exactly: NO AGENTS TOOL.'
CREATE='Use the tool mcp__graftling__agents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"'$CMODEL'","instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
4) {"action":"execute","feature":"status","arguments":{}}
Then report exactly four lines: AGENT: the agent id; ANSWER: the child'"'"'s one-word answer; STATUS: the state and last_result.notification from call 3; LISTED: every agent id that call 4 lists. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
child_login() {
  if [[ -n ${VERIFY572_CLAUDE_USER_LOGIN:-} ]]; then print "Claude child login: your own (VERIFY572_CLAUDE_USER_LOGIN=1)"; return 0; fi
  [[ -n ${ANTHROPIC_API_KEY:-} ]] || { print -r -- "STOP: the Claude child needs a login. Either export ANTHROPIC_API_KEY (isolated in $ROOT/claude-home), or, after asking the user, rerun as: VERIFY572_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"; return 1; }
  mkdir -p $ROOT/claude-home; print "Claude child login: ANTHROPIC_API_KEY (set, not printed) in CLAUDE_CONFIG_DIR=$ROOT/claude-home"
}
# A create Session: name dir root [pi options...]; the record must land in root, nowhere else.
create_in() {
  local name=$1 dir=$2 root=$3; shift 3
  local snap=$ROOT/$name-before.ids other=$ROOT/agents-data
  [[ $root == $other ]] && other=$P/.agents-control
  local other_before=$(count $other) existed=$([[ -d $root ]] && print yes || print no)
  python3 -I $JUDGE snap $root > $snap
  session $dir $name "$CREATE" "$@"
  say "evidence"
  print -r -- "$root existed before: $existed; records $(wc -l < $snap | tr -d ' ') -> $(count $root); $other $other_before -> $(count $other)"
  say "verdict (computed)"
  OK=1
  (( SRC == 0 )) && pass "pi exited 0" || fail "pi exited $SRC"
  grep -q 'Extension error' $SOUT && fail "Pi printed an extension error: $(grep -m1 'Extension error' $SOUT)" || pass "no extension error"
  python3 -I $JUDGE create $SOUT $root $snap pi-native ready || OK=0
  (( $(count $other) == other_before )) && pass "no record in $other" || fail "$other gained a record"
  (( OK )) || { print -r -- "next: inspect $SOUT and $root/control/agents/, then rerun: zsh $THIS $STEP"; return 1; }
  print -r -- "SUCCESS. Agent records: $(print -l -- $root/control/agents/*.json(N:t:r) | tr '\n' ' ')"
}
build_venv() {  # dir source-commit: a venv with graftling built from the bundle at that commit (no network)
  local v=$1 c=$2 src=$ROOT/src-${1:t}
  [[ -f $v/installed ]] && { print -r -- "reusing $v ($(<$v/installed))"; return 0; }
  rm -rf $v ${v}-wheels                              # an unfinished earlier build
  [[ -d $src ]] || git clone -q --no-checkout $GREPO $src || return 1
  git -C $src fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $src -c advice.detachedHead=false checkout -q $c || { print -r -- "STOP: $c not in $BUNDLE"; return 1; }
  python3 -m venv $v || return 1
  local sp=$($v/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/yaml $RTSP/_yaml $sp/ || return 1
  python3 -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w ${v}-wheels $src 2>&1 | grep -vi cache
  $v/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps ${v}-wheels/graftling-*.whl || return 1
  local got; got=$(cd / && $v/bin/python -I -c 'import graftling, yaml, websockets; print(graftling.__version__, graftling.__file__)') \
    || { print -r -- "STOP: $v cannot import graftling with its dependencies"; return 1; }
  print -r -- "$c $got" > $v/installed; print -r -- "$v: $(<$v/installed)"
}
pkg() { print -r -- $1/lib/python3.13/site-packages/graftling/pi }
pi_install() {  # project package-dir
  local before=$(hashes)
  (cd $1 && pi install -l $2 < /dev/null 2>&1 | tail -2)
  print -r -- "$1/.pi/settings.json: $(tr -d ' \n' < $1/.pi/settings.json 2>&1)"
  [[ $(<$1/.pi/settings.json) == *graftling/pi* ]] && pass "$1 declares the package" || fail "$1 does not declare the package"
  [[ $(hashes) == $before ]] && pass "pi install -l changed no Pi global file" || fail "a Pi global file changed: $(hashes)"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~30 s."
  local t; for t in zsh pi node python3 git claude; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists. Remove it yourself, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { fail "bundle does not verify"; return 1; }
  mkdir -p $ROOT/{proj,proj-base,proj-nopy,agents-data,pi-sessions} $OUT || return 1
  print -r -- "{\"root\": \"$ROOT/agents-data\"}" > $ROOT/pi-host.json
  hashes > $ROOT/pi-global-before.txt; cp $ROOT/pi-global-before.txt $OUT/
  print -r -- "Pi global files ($PIDIR), sha256 prefixes:"; cat $ROOT/pi-global-before.txt
  print -r -- "auth.json present: $([[ -f $PIDIR/auth.json ]] && print yes || print no) (not hashed: a token refresh may rewrite it)"
  print -r -- "settings.json default model keys: $(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print({k: d.get(k) for k in ("defaultProvider","defaultModel")})' $PIDIR/settings.json 2>&1)"
  say "one-line Pi prompt (--no-session --no-extensions --no-tools; nothing saved)"
  (cd $P && clean perl -e 'alarm shift; exec @ARGV' 120 pi -p --no-session --no-extensions --no-tools \
     "Reply in one line: the exact model id and the provider you are running as, nothing else." < /dev/null) 2>&1 | tail -3
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer. Log in with pi (/login), then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print "Success: a model and provider line, exit=0."; print -r -- "next: zsh $THIS repro"
  ;;
repro)
  say "[repro] Main. The premises on the base $BASE_SHORT. Dialog: none. ~1-2 min."
  need $ROOT/proj-base pre || return 1
  build_venv $ROOT/venv-base $BASE_REF || return 1
  OK=1; pi_install $ROOT/proj-base $(pkg $ROOT/venv-base)
  say "(a) no --agents-config, no GRAFTLING_PYTHON"
  PYVAR=''; session $ROOT/proj-base repro-a "$TOOLS"
  python3 -I $JUDGE tools $SOUT absent && print "PREMISE (a) REPRODUCED: no agents tool" || { print "PREMISE (a) NOT REPRODUCED"; OK=0; }
  print -r -- "$ROOT/proj-base/.agents-control exists: $([[ -d $ROOT/proj-base/.agents-control ]] && print yes || print no)"
  say "(b) --agents-config $ROOT/pi-host.json, GRAFTLING_PYTHON unset"
  session $ROOT/proj-base repro-b "$TOOLS" --agents-config $ROOT/pi-host.json
  grep -q 'requires its selected Python installation' $SOUT && print "PREMISE (b) REPRODUCED: $(grep -m1 'Extension error' $SOUT)" \
    || { print "PREMISE (b) NOT REPRODUCED: no 'requires its selected Python installation' line"; OK=0; }
  python3 -I $JUDGE tools $SOUT absent; print -r -- "pi exit=$SRC (the Session still ran: $([[ -n $(grep -m1 'TOOLS:' $SOUT) ]] && print yes || print no))"
  (( OK )) || return 1
  print -r -- "next: ask the user, then: zsh $THIS push"
  ;;
push)
  say "[push] Main, after asking the user. $GCOMMIT -> $URL $BRANCH. Dialog: none expected."
  local tmp=$ROOT/push-clone; rm -rf $tmp; git clone -q --bare $GREPO $tmp || return 1
  git -C $tmp fetch -q $BUNDLE "${BRANCH}:refs/heads/${BRANCH}" || return 1
  [[ $(git -C $tmp rev-parse $BRANCH) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { fail "bundle head differs"; return 1; }
  git -C $tmp push $URL "${GCOMMIT}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && pass "GitHub $BRANCH = $GCOMMIT" || fail "GitHub $BRANCH is not $GCOMMIT"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. Candidate venv, Python-less copy, pi install -l. Dialog: none. ~1 min."
  need $P pre || return 1
  build_venv $ROOT/venv $GCOMMIT || return 1
  rm -rf $ROOT/nopy; mkdir -p $ROOT/nopy/lib/python3.13/site-packages && cp -Rp ${$(pkg $ROOT/venv):h} $ROOT/nopy/lib/python3.13/site-packages/
  print -r -- "$ROOT/nopy has no interpreter: $(print -l -- $ROOT/nopy/bin/*(N) | grep -c .) files in bin"
  OK=1
  pi_install $P $(pkg $ROOT/venv)
  pi_install $ROOT/proj-nopy $(pkg $ROOT/nopy)
  (( OK )) || return 1; print -r -- "next: zsh $THIS start"
  ;;
start)
  say "[start] Main. No flag, no GRAFTLING_PYTHON; record expected under $P/.agents-control. Dialog: none. ~1-3 min."
  need $ROOT/venv/installed install || return 1; child_login || return 1
  print -r -- "python3 on PATH imports graftling: $(python3 -I -c 'import graftling; print(graftling.__file__)' 2>&1 | tail -1)"
  PYVAR=''; create_in start $P $P/.agents-control || return 1
  print -r -- "next: zsh $THIS explicit"
  ;;
explicit)
  say "[explicit] Main. --agents-config + GRAFTLING_PYTHON; record expected under $ROOT/agents-data. Dialog: none."
  need $ROOT/venv/installed install || return 1; child_login || return 1
  PYVAR=$ROOT/venv/bin/python; create_in explicit $P $ROOT/agents-data --agents-config $ROOT/pi-host.json || return 1
  print -r -- "next: zsh $THIS nopy"
  ;;
nopy)
  say "[nopy] Main. No interpreter beside the package, no GRAFTLING_PYTHON. Dialog: none. ~30 s."
  need $ROOT/nopy/lib install || return 1
  PYVAR=''; session $ROOT/proj-nopy nopy "$TOOLS"
  say "verdict (computed)"; OK=1
  grep -q 'Extension error.*Set GRAFTLING_PYTHON' $SOUT && pass "extension error names GRAFTLING_PYTHON: $(grep -m1 -o 'no Python that imports this graftling[^;]*' $SOUT)" \
    || fail "no extension error naming GRAFTLING_PYTHON"
  [[ ! -e $ROOT/proj-nopy/.agents-control ]] && pass "no data root created" || fail "$ROOT/proj-nopy/.agents-control was created"
  python3 -I $JUDGE tools $SOUT absent || OK=0
  (( OK )) || return 1; print -r -- "next: zsh $THIS post"
  ;;
post)
  say "[post] Main. Pi global files vs pre. <5 s."
  [[ -f $ROOT/pi-global-before.txt ]] || { print -r -- "STOP: run pre first"; return 1; }
  hashes > $ROOT/pi-global-after.txt; cp $ROOT/pi-global-after.txt $OUT/ 2>/dev/null
  OK=1; cmp -s $ROOT/pi-global-before.txt $ROOT/pi-global-after.txt && pass "Pi global files unchanged" \
    || { fail "Pi global files changed:"; cat $ROOT/pi-global-before.txt $ROOT/pi-global-after.txt; }
  print -r -- "Sessions of these runs: $ROOT/pi-sessions ($(print -l -- $ROOT/pi-sessions/**/*.jsonl(N) | grep -c .) files)"
  print -r -- "To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
*) print -r -- "usage: zsh $THIS pre|repro|push|install|start|explicit|nopy|post"; return 2 ;;
esac
}
BASE_REF=$BASE
BASE_SHORT=${BASE[1,7]}
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
