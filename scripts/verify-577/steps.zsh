#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 577 Main-run steps: one variable, GRAFTLING_DATA_ROOT, chooses the data root of the DSH and Pi hosts; without
# it the data root stays <project>/.agents-control; the old GRAFTLING_DSH_CONFIG / --agents-config still win; a child
# that inherits GRAFTLING_DATA_ROOT starts no host of its own.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre          Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions; the
#                bundle verifies; DEEPSEEK_API_KEY set (STOP with the fix if not; never printed); the 'before' state of
#                ~/.pi/agent (file names + sha256 prefixes), ~/.dsh (listing without '..' entries), ~/.claude/projects
#                and ~/.codex (names only); a one-line DSH prompt in the isolated DSH_HOME=ROOT/dsh-home and a one-line
#                Pi prompt in the isolated PI_CODING_AGENT_DIR=ROOT/pi-agent (--provider deepseek, the flash id from
#                `pi --list-models deepseek`), each naming its model; graftling's DSH model discovery for the Pi
#                Main's dsh child (saved to ROOT/dsh-model.txt). Dialog: none. ~1-2 min.
#   install      Main. Builds ROOT/venv from the candidate (bundle; no network: PyYAML and websockets are copied from
#                the Harness's .venv-runtime), adds graftling-dsh from ROOT/venv to profile headless of ROOT/dsh-home
#                (`dsh plugin add <dir>`, which runs pnpm), and `pi install -l` into ROOT/proj-pi. Dialog: none. ~1-2 min.
#   dsh-default  Main. DSH Main in ROOT/proj, no GRAFTLING_DATA_ROOT, no GRAFTLING_DSH_CONFIG: creates a dsh child,
#                waits; the record lands in ROOT/proj/.agents-control only. Dialog: none. ~1-3 min.
#   dsh-unified  Main. The same with GRAFTLING_DATA_ROOT=ROOT/unified-dsh: the record lands only there; the child's own
#                shell lists GRAFTLING_DATA_ROOT and GRAFTLING_CONNECTION; that root holds one host (live/dsh-host with
#                at most one entry, no other *-host, no host.log). Dialog: none. ~1-3 min.
#   dsh-old      Main. GRAFTLING_DSH_CONFIG=ROOT/dsh-host.json (root ROOT/explicit-dsh) AND GRAFTLING_DATA_ROOT: the
#                record lands in ROOT/explicit-dsh; ROOT/unified-dsh gains none. Dialog: none. ~1-3 min.
#   pi-default   Main. Pi Main in ROOT/proj-pi, no flag, no variable: dsh child; record in ROOT/proj-pi/.agents-control.
#   pi-unified   Main. GRAFTLING_DATA_ROOT=ROOT/unified-pi, as dsh-unified (one host: live/pi-host).
#   pi-old       Main. --agents-config ROOT/pi-host.json (root ROOT/explicit-pi) AND GRAFTLING_DATA_ROOT: the record
#                lands in ROOT/explicit-pi; ROOT/unified-pi gains none. Each Pi step: Dialog: none. ~1-3 min.
#   post         Main. The 'after' state of the four user locations, compared with pre's. <5 s.
#   push         Main, ONLY after asking the user. Pushes the candidate branch to LUOXIAO92/graftling from the bundle.
#                Dialog: none expected; git uses your usual GitHub login. ~30 s. No other step needs it.
# Order: pre, install, dsh-default, dsh-unified, dsh-old, pi-default, pi-unified, pi-old, post (push: separately).
# Login and credentials: only DEEPSEEK_API_KEY from your environment (never printed, never on a command line), for the
# DSH Main, the Pi Main and every dsh child. Claude Code and Codex are not started. DEEPSEEK_BASE_URL is removed.
# Writes outside ROOT: none expected from DSH (DSH_HOME=ROOT/dsh-home; children's homes under their data root's
# native/) or Pi (PI_CODING_AGENT_DIR=ROOT/pi-agent, --session-dir ROOT/pi-sessions, project-local install).
# `dsh plugin add` runs pnpm, which may add the package to pnpm's own content store (pre prints `pnpm store path`).
# OUT keeps every Session output. VERIFY577_ROOT / _OUT / _BIN (rehearsal stubs) / _USERHOME (stand-in for $HOME's four
# locations) / _DMODEL (skips discovery) are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY577_ROOT:-/private/tmp/graftling-577}
OUT=${VERIFY577_OUT:-$H/.graphtraj/core/state/tasks/577-unified-host-configuration/realhost}
URL=https://github.com/LUOXIAO92/graftling.git
BASE=80e1bf058c1e408c653fb5ec0a4e1f269fe07146       # graftling dev before 577 (570 + 572 + 574)
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/577-unified-host-configuration
GCOMMIT=c3e530e65e1fa2c9bb8476ed61ec63de43b643d7   # the graftling candidate (base: dev 80e1bf0)
BUNDLE=$WT/.scratch/577/graftling-577.bundle
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
JUDGE=$WT/scripts/verify-570/judge.py               # records on disk + the answer's lines (Task 570, unchanged)
UH=${VERIFY577_USERHOME:-$HOME}                     # your home: its .pi/agent, .dsh, .claude, .codex are only read
DH=$ROOT/dsh-home                                   # isolated DSH home of every dsh command here
PIAGENT=$ROOT/pi-agent                              # isolated Pi agent directory of every pi command here
P=$ROOT/proj                                        # the DSH Main's project
PP=$ROOT/proj-pi                                    # the Pi Main's project
MODELF=$ROOT/dsh-model.txt                          # the dsh child's model for the Pi Main (pre)
PIMODELF=$ROOT/pi-model.txt                         # the Pi Main's deepseek model id (pre)
THIS=${0:A}
STEP=${1:-}
path=(${VERIFY577_BIN:+$VERIFY577_BIN} /opt/homebrew/bin ${path:#$ROOT/*})

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
# No inherited agents channel, host settings or Session markers; DSH and Pi confined to ROOT.
clean() {
  env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u GRAFTLING_DATA_ROOT -u GRAFTLING_DSH_CONFIG -u DSH_AGENT_PACKAGE \
      -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u GRAFTLING_NATIVE_RUNTIME -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT \
      -u PI_SUBAGENT_CHILD -u DEEPSEEK_BASE_URL DSH_HOME=$DH PI_CODING_AGENT_DIR=$PIAGENT "$@"
}
# The four user locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh), never contents.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  # ~/.dsh and its profiles, without '..' (that is the parent's own entry, which other programs change).
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  print -r -- "claude projects naming ${ROOT:t}: $(print -l -- $UH/.claude/projects/*${ROOT:t}*(N:t) | tr '\n' ' ')"
}
count() { print -l -- $1/control/agents/*.json(N) | grep -c . }
dmodel() { [[ -n ${VERIFY577_DMODEL:-} ]] && print -r -- $VERIFY577_DMODEL || print -r -- "$(<$MODELF)"; }
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set (DSH Main, Pi Main and dsh children use it). Fix:"
  print -r -- "  export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"; return 1
}
PIFLAGS=()
pi_ready() {  # sets PIFLAGS from pre's model
  [[ -s $PIMODELF ]] || { print -r -- "STOP: $PIMODELF missing; run: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  PIFLAGS=(--provider deepseek --model $(<$PIMODELF))
}
# The child reports the two names from its own shell; the Main reports the usual four lines.
ENVCMD='env | cut -d= -f1 | grep -E "^GRAFTLING_(DATA_ROOT|CONNECTION)$" | sort | xargs'
create_prompt() {  # runtime-model-json-fragment instruction
  print -r -- 'Use the tool mcp__graftling__agents, not your own subagents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"dsh"'$1',"instruction":'$2'}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
4) {"action":"execute","feature":"status","arguments":{}}
Then report exactly four lines: AGENT: the agent id; ANSWER: the child'"'"'s answer; STATUS: the state and last_result.notification from call 3; LISTED: every agent id that call 4 lists. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
}
PLAIN='"Answer with exactly one word: ready."'
ENVASK=$(python3 -c 'import json, sys; print(json.dumps("Run this exact shell command: " + sys.argv[1] + " -- then answer with one line: its output followed by the word ready."))' "$ENVCMD")
# One real Main Session: kind dir name prompt [VAR=value...] [-- pi options...]; sets SRC and SOUT.
session() {
  local kind=$1 dir=$2 name=$3 prompt=$4; shift 4
  local -a vars=() opts=()
  while (( $# )) && [[ $1 != -- ]]; do vars+=$1; shift; done
  (( $# )) && shift; opts=("$@")
  SOUT=$ROOT/$name-$(date +%H%M%S).txt
  say "$kind Main '$name' in $dir; added: ${vars:-nothing} ${opts:-}"
  if [[ $kind == dsh ]]; then
    (cd $dir && clean GRAFTLING_PYTHON=$ROOT/venv/bin/python $vars perl -e 'alarm shift; exec @ARGV' 600 \
       dsh --profile headless "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  else
    (cd $dir && clean $vars perl -e 'alarm shift; exec @ARGV' 600 \
       pi -p $PIFLAGS --session-dir $ROOT/pi-sessions --approve $opts "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  fi
  tail -25 $SOUT; print -r -- "exit=$SRC (full output: $SOUT)"
  mkdir -p $OUT 2>/dev/null && cp $SOUT $OUT/ 2>/dev/null
}
# The one-host check for a data root: live/ holds only <host>-host (at most one entry) and agents' locks.
one_host() {  # root host
  local root=$1 host=$2
  print -r -- "$root/live: $(print -l -- $root/live/*(N:t) | tr '\n' ' '); $root/live/$host-host: $(print -l -- $root/live/$host-host/*(ND:t) | tr '\n' ' ')"
  local others=(${(f)"$(print -l -- $root/live/*-host(N/:t) | grep -v "^$host-host\$")"})
  (( ${#${others:#}} == 0 )) && pass "no other host's endpoint in $root/live" || fail "other hosts in $root/live: $others"
  [[ ! -e $root/live/channel.json && ! -e $root/host.log && ! -e $root/claude-host.json ]] \
    && pass "no Claude host files (live/channel.json, host.log, claude-host.json) in $root" || fail "Claude host files in $root"
  (( $(print -l -- $root/live/$host-host/*(ND) | grep -c .) <= 1 )) && pass "at most one $host host endpoint in $root" \
    || fail "more than one $host host endpoint in $root"
}
# Create one child; its record must land in root, and the listed other roots must not gain one.
create_in() {  # kind name dir root env-check(yes|no) others... -- session-args...
  local kind=$1 name=$2 dir=$3 root=$4 envcheck=$5; shift 5
  local -a others=(); while (( $# )) && [[ $1 != -- ]]; do others+=$1; shift; done; (( $# )) && shift
  local snap=$ROOT/$name-before.ids o; typeset -A before
  for o in $others; do before[$o]=$(count $o); done
  local existed=$([[ -d $root ]] && print yes || print no)
  python3 -I $JUDGE snap $root > $snap
  local model='' instruction=$PLAIN
  [[ $kind == pi ]] && model=',"model":"'$(dmodel)'"'
  [[ $envcheck == yes ]] && instruction=$ENVASK
  session $kind $dir $name "$(create_prompt "$model" "$instruction")" "$@"
  say "evidence"
  print -r -- "$root existed before: $existed; records $(grep -c . $snap) -> $(count $root)"
  for o in $others; do print -r -- "$o: records $before[$o] -> $(count $o)"; done
  say "verdict (computed)"
  OK=1
  (( SRC == 0 )) && pass "the $kind Main exited 0" || fail "the $kind Main exited $SRC"
  grep -q 'Extension error' $SOUT && fail "Pi printed an extension error: $(grep -m1 'Extension error' $SOUT)"
  python3 -I $JUDGE create $SOUT $root $snap $kind-native ready || OK=0
  for o in $others; do (( $(count $o) == before[$o] )) && pass "no record in $o" || fail "$o gained a record"; done
  local agent; agent=$(python3 -I $JUDGE snap $root | grep -v -x -F -f $snap | head -1)
  if [[ $envcheck == yes ]]; then
    local said=$(python3 -I -c 'import json, sys; r = json.load(open(sys.argv[1])); print((r.get("executions") or [{}])[-1].get("last_message") or "")' $root/control/agents/$agent.json 2>/dev/null)
    print -r -- "the child's own shell said: ${said:-nothing}"
    [[ $said == *GRAFTLING_DATA_ROOT* && $said == *GRAFTLING_CONNECTION* ]] \
      && pass "the child holds GRAFTLING_DATA_ROOT and GRAFTLING_CONNECTION" || fail "the child did not list both names"
    one_host $root $kind
  fi
  if (( OK )); then
    print -r -- "SUCCESS. follow-ups (paste as needed):"
    print -r -- "  python3 -m json.tool $root/control/agents/$agent.json"
    print -r -- "  ls -laR $root/live"
  else
    print -r -- "next: inspect $SOUT and $root/control/agents/, then rerun: zsh $THIS $STEP"
  fi
  return $(( 1 - OK ))
}
build_venv() {  # dir commit: a venv with graftling built from the bundle at that commit (no network)
  local v=$1 c=$2 src=$ROOT/src
  [[ -f $v/installed ]] && { print -r -- "reusing $v ($(<$v/installed))"; return 0; }
  rm -rf $v ${v}-wheels $src
  git clone -q --no-checkout $GREPO $src || return 1
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
pkg() { print -r -- $ROOT/venv/lib/python3.13/site-packages/graftling/$1 }

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1-2 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  key_ready || return 1
  mkdir -p $P $PP $DH $PIAGENT $ROOT/pi-sessions $OUT || return 1
  touch $ROOT/pre-marker
  print -r -- "zsh $ZSH_VERSION ($THIS)"
  local t; for t in dsh pi node pnpm python3 git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  print -r -- "pnpm store path (dsh plugin add may add the package there): $(pnpm store path 2>&1 | tail -1)"
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { print -r -- "STOP: bundle does not verify"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | cut -d' ' -f1) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head is not $GCOMMIT"; return 1; }
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  print -r -- "{\"root\": \"$ROOT/explicit-dsh\"}" > $ROOT/dsh-host.json
  print -r -- "{\"root\": \"$ROOT/explicit-pi\"}" > $ROOT/pi-host.json
  say "one-line DSH prompt, DSH_HOME=$DH (login: DEEPSEEK_API_KEY)"
  (cd $P && clean perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless \
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
  if [[ -n ${VERIFY577_DMODEL:-} ]]; then print -r -- $VERIFY577_DMODEL > $MODELF; else
    say "graftling's DSH model discovery for the Pi Main's dsh child (Python $H/.venv-runtime, read only)"
    (cd $ROOT && clean perl -e 'alarm shift; exec @ARGV' 180 $H/.venv-runtime/bin/python -I -c '
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
  [[ -s $MODELF ]] || { print -r -- "STOP: no flash DSH model; see above. Then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "DSH Main answered; Pi Main model deepseek/$(<$PIMODELF); dsh child model for Pi: $(<$MODELF)"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. Candidate venv; graftling-dsh into $DH profile headless; pi install -l in $PP. Dialog: none."
  need $P pre || return 1
  build_venv $ROOT/venv $GCOMMIT || return 1
  OK=1
  local log=$ROOT/install-dsh.txt
  say "DSH_HOME=$DH dsh plugin --profile headless add $(pkg dsh)"
  (cd $P && clean dsh plugin --profile headless add $(pkg dsh) < /dev/null) > $log 2>&1; local rc=$?
  tail -8 $log; print -r -- "exit=$rc (full output: $log)"
  [[ $(cat $DH/profiles/headless/package.json 2>/dev/null) == *graftling-dsh* ]] && pass "profile headless of $DH has graftling-dsh" \
    || fail "graftling-dsh is not in $DH/profiles/headless/package.json"
  say "PI_CODING_AGENT_DIR=$PIAGENT pi install -l $(pkg pi) (in $PP)"
  (cd $PP && clean pi install -l $(pkg pi) < /dev/null 2>&1 | tail -2)
  [[ $(cat $PP/.pi/settings.json 2>/dev/null) == *graftling/pi* ]] && pass "$PP/.pi/settings.json declares the package" \
    || fail "$PP/.pi/settings.json does not declare the package"
  (( OK )) || return 1; print -r -- "next: zsh $THIS dsh-default"
  ;;
dsh-default)
  key_ready && need $ROOT/venv/installed install || return 1
  say "[dsh-default] Main. No GRAFTLING_DATA_ROOT, no GRAFTLING_DSH_CONFIG; record expected in $P/.agents-control. Dialog: none."
  create_in dsh dsh-default $P $P/.agents-control no $ROOT/unified-dsh $ROOT/explicit-dsh || return 1
  print -r -- "next: zsh $THIS dsh-unified"
  ;;
dsh-unified)
  key_ready && need $ROOT/venv/installed install || return 1
  say "[dsh-unified] Main. GRAFTLING_DATA_ROOT=$ROOT/unified-dsh; record, child env and one host there. Dialog: none."
  create_in dsh dsh-unified $P $ROOT/unified-dsh yes $P/.agents-control $ROOT/explicit-dsh -- \
    GRAFTLING_DATA_ROOT=$ROOT/unified-dsh || return 1
  print -r -- "next: zsh $THIS dsh-old"
  ;;
dsh-old)
  key_ready && need $ROOT/venv/installed install || return 1
  say "[dsh-old] Main. GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json and GRAFTLING_DATA_ROOT; record expected in $ROOT/explicit-dsh."
  create_in dsh dsh-old $P $ROOT/explicit-dsh no $P/.agents-control $ROOT/unified-dsh -- \
    GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json GRAFTLING_DATA_ROOT=$ROOT/unified-dsh || return 1
  print -r -- "next: zsh $THIS pi-default"
  ;;
pi-default)
  key_ready && pi_ready && need $PP/.pi/settings.json install || return 1
  say "[pi-default] Main. No flag, no GRAFTLING_DATA_ROOT; record expected in $PP/.agents-control. Dialog: none."
  create_in pi pi-default $PP $PP/.agents-control no $ROOT/unified-pi $ROOT/explicit-pi || return 1
  print -r -- "next: zsh $THIS pi-unified"
  ;;
pi-unified)
  key_ready && pi_ready && need $PP/.pi/settings.json install || return 1
  say "[pi-unified] Main. GRAFTLING_DATA_ROOT=$ROOT/unified-pi; record, child env and one host there. Dialog: none."
  create_in pi pi-unified $PP $ROOT/unified-pi yes $PP/.agents-control $ROOT/explicit-pi -- \
    GRAFTLING_DATA_ROOT=$ROOT/unified-pi || return 1
  print -r -- "next: zsh $THIS pi-old"
  ;;
pi-old)
  key_ready && pi_ready && need $PP/.pi/settings.json install || return 1
  say "[pi-old] Main. --agents-config $ROOT/pi-host.json and GRAFTLING_DATA_ROOT; record expected in $ROOT/explicit-pi."
  create_in pi pi-old $PP $ROOT/explicit-pi no $PP/.agents-control $ROOT/unified-pi -- \
    GRAFTLING_DATA_ROOT=$ROOT/unified-pi -- --agents-config $ROOT/pi-host.json || return 1
  print -r -- "next: zsh $THIS post"
  ;;
post)
  say "[post] Main. Your four locations vs pre (any difference FAILs). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh and ~/.claude/projects unchanged" || fail "a location changed (diff above)"
  local codex=(${(f)"$(find $UH/.codex -newer $ROOT/pre-marker -type f 2>/dev/null | xargs grep -l -F $ROOT 2>/dev/null)"})
  (( ${#${codex:#}} == 0 )) && pass "no ~/.codex file written since pre names $ROOT" || fail "~/.codex files naming $ROOT: $codex"
  print -r -- "Sessions of these runs: $ROOT/pi-sessions, and the DSH Sessions under $DH."
  print -r -- "To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $GCOMMIT -> $URL $BRANCH. Dialog: none expected."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { pass "already on GitHub"; return 0; }
  local tmp=$ROOT/push-clone.git; rm -rf $tmp; git clone -q --bare $GREPO $tmp || return 1
  git -C $tmp fetch -q $BUNDLE "${BRANCH}:refs/heads/${BRANCH}" || return 1
  [[ $(git -C $tmp rev-parse $BRANCH) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head differs"; return 1; }
  print -r -- "authors and committers: $(git -C $tmp log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $tmp push $URL "${GCOMMIT}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && pass "GitHub $BRANCH = $GCOMMIT" || fail "GitHub $BRANCH is not $GCOMMIT"
  rm -rf $tmp
  ;;
*) print -r -- "usage: zsh $THIS pre|install|dsh-default|dsh-unified|dsh-old|pi-default|pi-unified|pi-old|post|push"; return 2 ;;
esac
}
OK=1
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
