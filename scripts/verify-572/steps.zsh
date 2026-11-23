#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 572 Main-run steps: graftling's Pi package works once installed, with no --agents-config (data root
# <project>/.agents-control) and no GRAFTLING_PYTHON (the Python of the installation the extension was loaded from).
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre       Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created; hashes of EVERY
#             regular file directly in ~/.pi/agent (auth.json and models-store.json included; names and sha256 only) plus
#             its directory names, and a listing of ~/.dsh, taken before any pi runs; DEEPSEEK_API_KEY set (STOP with the
#             fix if not; never printed); versions; the Pi Main's model: the deepseek flash id from
#             `pi --list-models deepseek`, saved to ROOT/pi-model.txt (STOP if none); a one-line Pi prompt
#             (--provider deepseek --model <id> --no-session --no-extensions --no-tools) naming its provider and model;
#             graftling's own DSH model discovery (DSH_HOME=ROOT/dsh-home), whose accepted id for the child is saved to
#             ROOT/dsh-model.txt. Dialog: none. ~1 min.
#   repro     Main, required (premise (a) is the model-visible tool list, not observable without a login). The premises on the BASE (graftling dev cadc419): `pi install -l` of the base package in
#             ROOT/proj-base, then (a) no flag, no GRAFTLING_PYTHON: does the model list mcp__graftling__agents?
#             (b) --agents-config given, GRAFTLING_PYTHON unset: the actual output. Dialog: none. ~1-2 min.
#   push      Main, after asking the user. Pushes the candidate branch to LUOXIAO92/graftling from the bundle.
#             Dialog: none expected; git uses your usual GitHub login. ~30 s.
#   install   Main. Builds ROOT/venv from the candidate (bundle, no network: dependencies copied from the Harness's
#             .venv-runtime), a Python-less copy ROOT/nopy, and runs `pi install -l` in ROOT/proj and ROOT/proj-nopy.
#             Checks that only the projects' .pi/settings.json changed. Dialog: none. ~1 min.
#   start     Main. In ROOT/proj, no flag, no GRAFTLING_PYTHON, PATH without ROOT/venv: real Pi Main uses the agents
#             tool to create a dsh child (model from ROOT/dsh-model.txt, key DEEPSEEK_API_KEY, no config.yml) that
#             answers 'ready', waits, reads status. The record lands in ROOT/proj/.agents-control. A Pi child is not
#             used: it is refused on a root inside the project (pre-existing; see engineer.md). Dialog: none. ~1-3 min.
#   explicit  Main. --agents-config ROOT/pi-host.json (root ROOT/agents-data) and GRAFTLING_PYTHON=ROOT/venv/bin/python:
#             the record lands in ROOT/agents-data; ROOT/proj/.agents-control gains none. Same child. ~1-3 min.
#   nopy      Main. In ROOT/proj-nopy (package copy with no interpreter), no flag, no GRAFTLING_PYTHON: a real Pi start
#             shows the extension error naming GRAFTLING_PYTHON and the model lists no agents tool. ~30 s.
#   post      Main. The Pi global hashes and the ~/.dsh listing again, compared with pre's; how to remove ROOT. <5 s.
# Order: pre, repro, push (ask the user first), install, start, explicit, nopy, post.
# Everything is under ROOT=/private/tmp/graftling-572. Every pi command (install -l included) runs with
# PI_CODING_AGENT_DIR=ROOT/pi-agent and, for a Session, --provider deepseek --model <ROOT/pi-model.txt>
# (key: DEEPSEEK_API_KEY from the environment, never on a command line), --session-dir ROOT/pi-sessions, --approve
# (project trust for that run only) and a project-local (-l) install. Your ~/.pi/agent and Pi login are not used;
# post FAILs if any file directly in it changed. The Pi Main runs with DSH_HOME=ROOT/dsh-home, so DSH model discovery
# writes there; each dsh child gets its own home under its root's native/ directory. Nothing is expected outside ROOT.
# VERIFY572_ROOT / VERIFY572_OUT / VERIFY572_BIN (stub pi for the verdict rehearsal) / VERIFY572_PIUSER (a stand-in for
# ~/.pi/agent, which the Engineer's sandbox cannot read) are for the Engineer only.
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
GCOMMIT=b93bf6db2877beb2751ad0e5b0d96ed69640e13e   # the graftling candidate: 8bdc1b2 + docs (base: dev cadc419)
BUNDLE=$WT/.scratch/572/graftling-572.bundle
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
JUDGE=$WT/scripts/verify-570/judge.py               # 570's verdicts: records on disk + the answer's lines
PIUSER=${VERIFY572_PIUSER:-$HOME/.pi/agent}         # your Pi directory: only hashed (pre/post), never used
PIAGENT=$ROOT/pi-agent                              # the Pi agent directory of every pi command here
PIMODELF=$ROOT/pi-model.txt                         # the Pi Main's deepseek model id (pre)
PIFLAGS=()                                          # --provider deepseek --model <id>, set by pi_ready
THIS=${0:A}
STEP=${1:-}
P=$ROOT/proj
MODELF=$ROOT/dsh-model.txt                          # the DSH model id graftling's discovery accepted (pre)
path=(${VERIFY572_BIN:+$VERIFY572_BIN} /opt/homebrew/bin ${path:#$ROOT/*})

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
# Pi with no explicit Python or channel, DSH discovery confined to ROOT/dsh-home, no inherited DSH endpoint.
clean() {
  local -a drop=(-u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u GRAFTLING_NATIVE_RUNTIME
                 -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u PI_SUBAGENT_CHILD -u DSH_AGENT_PACKAGE -u DEEPSEEK_BASE_URL)
  env $drop PI_CODING_AGENT_DIR=$PIAGENT DSH_HOME=$ROOT/dsh-home "$@"
}
# One real Pi print-mode Session: dir name prompt [pi options...] ; sets SRC and SOUT.
session() {
  local dir=$1 name=$2 prompt=$3; shift 3
  SOUT=$ROOT/$name-$(date +%H%M%S).txt
  say "pi -p $PIFLAGS in $dir ($name) ${*:-no --agents-config}, GRAFTLING_PYTHON ${PYVAR:-unset}, PI_CODING_AGENT_DIR=$PIAGENT"
  (cd $dir && clean ${PYVAR:+GRAFTLING_PYTHON=$PYVAR} perl -e 'alarm shift; exec @ARGV' 600 \
     pi -p $PIFLAGS --session-dir $ROOT/pi-sessions --approve "$@" "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  tail -25 $SOUT; print -r -- "exit=$SRC (full output: $SOUT)"
  mkdir -p $OUT 2>/dev/null && cp $SOUT $OUT/ 2>/dev/null
}
hashes() {  # every regular file directly in your Pi directory: name and sha256 (never contents); its directory names
  local f; for f in $PIUSER/*(N.D); do print -r -- "${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "directories: $(print -l -- $PIUSER/*(N/D:t) | tr '\n' ' ')"
  # ~/.dsh: top-level and profile names with modification times (DSH discovery and children must not write there).
  print -r -- "dsh-home $(ls -laT $HOME/.dsh $HOME/.dsh/profiles 2>&1 | awk '{print $6,$7,$8,$9,$10}' | tr '\n' ';')"
}
count() { print -l -- $1/control/agents/*.json(N) | grep -c . }
TOOLS='List the names of all tools available to you whose names start with mcp__ on one line prefixed TOOLS: (write TOOLS: NONE if there are none). If mcp__graftling__agents is among them, call it exactly once with the input {"action":"execute","feature":"status","arguments":{}} and print its result verbatim on one line prefixed RESULT:. If it is not among them, write exactly: NO AGENTS TOOL.'
create_prompt() { print -r -- 'Use the tool mcp__graftling__agents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"dsh","model":"'$DMODEL'","instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
4) {"action":"execute","feature":"status","arguments":{}}
Then report exactly four lines: AGENT: the agent id; ANSWER: the child'"'"'s one-word answer; STATUS: the state and last_result.notification from call 3; LISTED: every agent id that call 4 lists. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'; }
pi_ready() {  # the Pi Main's model from pre; sets PIFLAGS
  [[ -s $PIMODELF ]] || { print -r -- "STOP: $PIMODELF missing; run: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print -r -- "STOP: DEEPSEEK_API_KEY is not set (the Pi Main's key). Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key>, then: zsh $THIS $STEP"; return 1; }
  PIFLAGS=(--provider deepseek --model $(<$PIMODELF))
  print -r -- "Pi Main: $PIFLAGS (key DEEPSEEK_API_KEY from the environment), PI_CODING_AGENT_DIR=$PIAGENT"
}
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
child_ready() {  # DEEPSEEK_API_KEY and the discovered model; sets DMODEL; prints what is written outside ROOT
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print -r -- "STOP: DEEPSEEK_API_KEY is not set. Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key>, then: zsh $THIS $STEP"; return 1; }
  [[ -s $MODELF ]] || { print -r -- "STOP: $MODELF missing; run: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  DMODEL=$(<$MODELF)
  print -r -- "dsh child: model $DMODEL (from $MODELF), key DEEPSEEK_API_KEY (set, ${#DEEPSEEK_API_KEY} characters, not printed), no config.yml"
  print -r -- "outside ROOT this step writes: nothing expected (Pi: PI_CODING_AGENT_DIR=$PIAGENT; DSH: DSH_HOME=$ROOT/dsh-home and the child homes under its root); post checks $PIUSER and ~/.dsh"
}
# A create Session: name dir root [pi options...]; the record must land in root, nowhere else.
create_in() {
  local name=$1 dir=$2 root=$3; shift 3
  local snap=$ROOT/$name-before.ids other=$ROOT/agents-data
  [[ $root == $other ]] && other=$P/.agents-control
  local other_before=$(count $other) existed=$([[ -d $root ]] && print yes || print no)
  python3 -I $JUDGE snap $root > $snap
  session $dir $name "$(create_prompt)" "$@"
  say "evidence"
  print -r -- "$root existed before: $existed; records $(grep -c . $snap) -> $(count $root); $other $other_before -> $(count $other)"
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
  say "PI_CODING_AGENT_DIR=$PIAGENT pi install -l $2 (in $1)"
  (cd $1 && clean pi install -l $2 < /dev/null 2>&1 | tail -2)
  print -r -- "$1/.pi/settings.json: $(tr -d ' \n' < $1/.pi/settings.json 2>&1)"
  [[ $(<$1/.pi/settings.json) == *graftling/pi* ]] && pass "$1 declares the package" || fail "$1 does not declare the package"
  [[ $(hashes) == $before ]] && pass "pi install -l changed no Pi global file" || fail "a Pi global file changed: $(hashes)"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' hashes must be taken fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  mkdir -p $ROOT/{proj,proj-base,proj-nopy,agents-data,pi-sessions,dsh-home,pi-agent} $OUT || return 1
  hashes > $ROOT/pi-global-before.txt; cp $ROOT/pi-global-before.txt $OUT/
  print -r -- "Your Pi directory $PIUSER, before any pi command (name, sha256 prefix; never used here):"; cat $ROOT/pi-global-before.txt
  local t; for t in zsh dsh node python3 git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  print -r -- "pi: $(command -v pi) $(clean pi --version 2>&1 | head -1) (PI_CODING_AGENT_DIR=$PIAGENT)"
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { fail "bundle does not verify"; return 1; }
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    print -r -- "STOP: DEEPSEEK_API_KEY is not set. start/explicit create a dsh child, whose key it is. Fix:"
    print -r -- "  export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS pre"; return 1
  fi
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  print -r -- "{\"root\": \"$ROOT/agents-data\"}" > $ROOT/pi-host.json
  say "the Pi Main's model: PI_CODING_AGENT_DIR=$PIAGENT pi --list-models deepseek"
  local listed; listed=$(cd $ROOT && clean perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed"
  print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $PIMODELF
  [[ -s $PIMODELF ]] && pass "Pi Main model: deepseek/$(<$PIMODELF) (saved in $PIMODELF)" \
    || { print -r -- "STOP: pi --list-models deepseek lists no flash model (above). Report it (do not guess an id), then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pi_ready || return 1
  say "one-line Pi prompt: pi -p $PIFLAGS --no-session --no-extensions --no-tools (nothing saved)"
  (cd $P && clean perl -e 'alarm shift; exec @ARGV' 120 pi -p $PIFLAGS --no-session --no-extensions --no-tools \
     "Reply in one line: the exact model id and the provider you are running as, nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer with $PIFLAGS. Check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  say "graftling's DSH model discovery (the check create applies), DSH_HOME=$ROOT/dsh-home, Python $H/.venv-runtime (read only)"
  (cd $ROOT && clean perl -e 'alarm shift; exec @ARGV' 180 $H/.venv-runtime/bin/python -I -c '
import json, sys
from graftling.models import discover_models
found = discover_models({"runtime": "dsh"})
models = found.get("models") or []
print("status", found.get("status"), "|", found.get("message") or "")
for m in models: print("  model", m["id"], "| alias", m.get("alias"), "| provider", m.get("provider"))
flash = [m["id"] for m in models if "flash" in (m["id"] + " " + str(m.get("alias"))).lower()]
if flash: open(sys.argv[1], "w").write(flash[0]); print("chosen", flash[0])
' $MODELF) 2>&1 | tail -15
  [[ -s $MODELF ]] && pass "DSH child model: $(<$MODELF) (saved in $MODELF)" \
    || { print -r -- "STOP: discovery gave no flash model; see the list above. Report it (do not guess an id), then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print "Success: a model and provider line, exit=0, a DSH model saved."; print -r -- "next: zsh $THIS repro"
  ;;
repro)
  say "[repro] Main. The premises on the base $BASE_SHORT. Dialog: none. ~1-2 min."
  pi_ready || return 1
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
  pi_ready || return 1
  need $ROOT/venv/installed install || return 1; child_ready || return 1
  print -r -- "python3 on PATH imports graftling: $(python3 -I -c 'import graftling; print(graftling.__file__)' 2>&1 | tail -1)"
  PYVAR=''; create_in start $P $P/.agents-control || return 1
  print -r -- "next: zsh $THIS explicit"
  ;;
explicit)
  say "[explicit] Main. --agents-config + GRAFTLING_PYTHON; record expected under $ROOT/agents-data. Dialog: none."
  pi_ready || return 1
  need $ROOT/venv/installed install || return 1; child_ready || return 1
  PYVAR=$ROOT/venv/bin/python; create_in explicit $P $ROOT/agents-data --agents-config $ROOT/pi-host.json || return 1
  print -r -- "next: zsh $THIS nopy"
  ;;
nopy)
  say "[nopy] Main. No interpreter beside the package, no GRAFTLING_PYTHON. Dialog: none. ~30 s."
  pi_ready || return 1
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
  say "[post] Main. Every file directly in $PIUSER and the ~/.dsh listing vs pre (any difference FAILs). <5 s."
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
