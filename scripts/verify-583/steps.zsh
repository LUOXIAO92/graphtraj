#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 583 Main-run steps: GraphTraj's Pi extension calls graftling's agents.start only with GRAFTLING_CONNECTION or
# --agents-config, so since graftling 572 a GraphTraj Pi Session is no longer taken over by graftling's default host.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre            Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions; zsh;
#                  DEEPSEEK_API_KEY set (STOP with the fix if not; never printed); the 'before' state of ~/.pi/agent
#                  (file names + sha256 prefixes), ~/.dsh (listing without '..'), ~/.claude/projects (names naming
#                  ROOT); the deepseek flash id from `pi --list-models deepseek` and one one-line Pi prompt naming its
#                  model, both in the isolated PI_CODING_AGENT_DIR=ROOT/pi-agent. Dialog: none. ~1 min.
#   install        Main. For BEFORE (GraphTraj 24674e30, unfixed) and AFTER (this Worktree's HEAD): a venv ROOT/venv-<lab>
#                  with GraphTraj and graftling a4f008f both installed as WHEELS (as `uv tool install` does; no network:
#                  click, PyYAML and websockets are copied from <Harness>/.venv-runtime); a git project ROOT/proj-<lab>
#                  set up through GraphTraj's public entry (`graphtraj setup`, answering y to its dev-branch question),
#                  a member Worktree ROOT/proj-<lab>/.graphtraj/.agent-worktrees/member (`git worktree add`), and the
#                  lab's extension.mjs loaded as a real user does: `pi install -l <extension.mjs>` in the project and in
#                  the member Worktree (project-local .pi/settings.json; every pi run passes --approve to trust it).
#                  --no-extensions is never passed: Pi's built-in MCP connector stays. Dialog: none. ~1-2 min.
#   main-before    Main. (a) on BEFORE: un-flagged Pi Main in ROOT/proj-before. Expected: the takeover (graftling.pi.host,
#                  .agents-control, no graphtraj MCP server, no Main association). Dialog: none. ~1-2 min.
#   main-after     Main. (a) on AFTER: expected no graftling.pi.host, no .agents-control, the graphtraj MCP server with a
#                  REAL mcp__graphtraj__tasks discover call, the Main association (continuity.jsonl claim + finalize
#                  binding), a notice queued for that Main (by this script, through GraphTraj's queue_notice, as a
#                  member's end would be) delivered into the Pi Session and acknowledged, and the collection under
#                  .graphtraj/swarm. Dialog: none. ~1-2 min.
#   member-before  Main. (b) on BEFORE: Pi members in the member Worktree, PI_SUBAGENT_CHILD=1 (plugin-child) and
#                  GRAPHTRAJ_CLI_CONNECTION=unused (runner), one run each. Expected: the takeover. Dialog: none. ~2 min.
#   member-after   Main. (b) on AFTER: expected no host, no .agents-control, the graphtraj MCP server. Dialog: none.
#   config-before  Main. (c) on BEFORE: Pi Main with --agents-config ROOT/pi-host-before.json: graftling's host starts
#                  with that config and its data root appears. Dialog: none. ~1 min.
#   config-after   Main. (c) on AFTER: the same expected. Dialog: none. ~1 min.
#   post           Main. The 'after' state of your three locations, compared with pre's. <5 s.
#   push           Main, ONLY after asking the user. Pushes this branch (HEAD) to LUOXIAO92/graphtraj. Dialog: none
#                  expected; git uses your usual GitHub login. ~30 s.
#   suite          Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a fresh venv
#                  under <Harness>/tmp/583 with graftling a4f008f built as a WHEEL and GraphTraj editable. pytest's temp
#                  root is under TMPDIR=${TMPDIR:-/tmp}, outside the Harness (checked). Dialog: none. No login.
#   SR             Read only: the newest suite's FAILED/ERROR lines classed known (Task 516's CURRENT definition, via its
#                  task.yml current_definition) or NEW; prints the ready-to-paste suite-base command. Dialog: none.
#   suite-base     Main, only if SR reports NEW: `zsh <this file> suite-base <node id>...` reruns exactly those node ids
#                  on GraphTraj 24674e30 (a local clone under <Harness>/tmp/583) with the same graftling wheel.
# Order: pre, install, main-before, main-after, member-before, member-after, config-before, config-after, post
# (push separately). suite, SR (and suite-base) need no ROOT and no key; they write only <Harness>/tmp/583 and pytest's
# temp root under TMPDIR.
# Login and credentials (decided: DeepSeek only): only DEEPSEEK_API_KEY from your environment (never printed, never on
# a command line). Every command starts from an ALLOWLIST (launch(): HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE
# TMPDIR PATH, PI_CODING_AGENT_DIR, the case's own variables, and DEEPSEEK_API_KEY for Pi only), so OPENCODE_*,
# OPEN_ROUTER_*, GEMINI_*, ALI_BAILIAN_*, HF_TOKEN, DEEPSEEK_BASE_URL and every other name of yours do not reach Pi or
# its children. A guard STOPs a launch (exit 97, names only) if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* other
# than DEEPSEEK_API_KEY is left. pre pins ROOT/pi-agent/settings.json to deepseek and the flash id, and every pi gets
# --provider deepseek --model <id>. After each run the provider and model of every assistant message in the run's Pi
# Session files (Main and any child) are printed, and the step FAILs if any is not deepseek. Claude Code and Codex are
# not started. Pi runs with PI_CODING_AGENT_DIR=ROOT/pi-agent and --session-dir ROOT/sessions/<run>.
# Writes: ROOT only for the real-host steps (no write to your home is expected; pre/post check it). OUT keeps a copy
# of every output. VERIFY583_ROOT / _OUT / _T / _BIN (rehearsal stubs first on PATH) / _USERHOME (stand-in for $HOME)
# / _PYTEST_ARGS / _WAIT are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY583_ROOT:-/private/tmp/graphtraj-583}
OUT=${VERIFY583_OUT:-$H/.graphtraj/core/state/tasks/583-graphtraj-pi-extension-no-graftling-default-host/realhost}
URL=https://github.com/LUOXIAO92/graphtraj.git
BRANCH=agent/583-graphtraj-pi-extension-no-graftling-default-host
GREPO=$H/graftling                                  # the local graftling repository (read only)
GCOMMIT=a4f008f3712614cbdcae714ae46cad07c1f8de6e   # graftling dev (572 + 577 + 578)
GTBASE=24674e308d9747f05bdaacded00ffabf83183857     # GraphTraj dev, this Task's base (unfixed)
HEAD=$(git -C $WT rev-parse HEAD)                   # the candidate
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: click, PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
UH=${VERIFY583_USERHOME:-$HOME}                     # your home: its .pi/agent, .dsh, .claude/projects are only read
PIAGENT=$ROOT/pi-agent                              # isolated Pi agent directory of every pi command here
PIMODELF=$ROOT/pi-model.txt                         # the deepseek flash id (pre)
WAIT=${VERIFY583_WAIT:-120}                         # seconds the notice watcher waits for the Main claim
THIS=${0:A}
STEP=${1:-}
T=${VERIFY583_T:-$H/tmp/583}                        # suite venvs, sources and outputs
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
path=(${VERIFY583_BIN:+$VERIFY583_BIN} /opt/homebrew/bin ${path:#$ROOT/*})

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
# Every command here starts from an ALLOWLIST, not a deny-list: in a subshell every exported name outside ALLOW is
# unset, then PI_CODING_AGENT_DIR and the case's own VAR=value are exported (DEEPSEEK_API_KEY only with --key, and
# only from your environment: never on a command line). A guard then STOPs (exit 97) if any *_API_KEY, *_TOKEN,
# *_BASE_URL or *_AUTH* name other than DEEPSEEK_API_KEY is left; it prints names only, never values.
ALLOW=(HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE TMPDIR PATH)
launch() {  # [--key] [VAR=value...] -- command...
  local key=0; [[ ${1:-} == --key ]] && { key=1; shift; }
  local -a add=(); while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done
  (( $# )) && shift
  (
    local n
    for n in ${(k)parameters[(R)*export*]}; do
      (( ${ALLOW[(Ie)$n]} )) && continue
      [[ $n == DEEPSEEK_API_KEY ]] && (( key )) && continue
      unset $n 2>/dev/null
    done
    export PI_CODING_AGENT_DIR=$PIAGENT
    for n in $add; do export "$n"; done
    local -a bad=(${(M)${(k)parameters[(R)*export*]}:#(*_API_KEY|*_TOKEN|*_BASE_URL|*_AUTH*)})
    bad=(${bad:#DEEPSEEK_API_KEY})
    (( $#bad )) && { print -u2 -r -- "STOP: provider credential names in the launch environment: $bad"; exit 97; }
    exec "$@"
  )
}
# The provider and model of every assistant message in the given Pi Session files (Main and any child); no secrets.
PJUDGE='
import json, sys
seen = {}
for path in sys.argv[1:]:
    for line in open(path, encoding="utf-8"):
        def walk(value):
            if isinstance(value, dict):
                if value.get("role") == "assistant" and "provider" in value:
                    key = (path.rsplit("/", 1)[-1], value.get("provider"), value.get("model"))
                    seen[key] = seen.get(key, 0) + 1
                for item in value.values(): walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        walk(json.loads(line))
for (name, provider, model), n in sorted(seen.items()): print("used:", name, "provider", provider, "model", model, "x", n)
bad = sorted({(p, m) for (_, p, m) in seen if p != "deepseek"})
print("provider verdict:", "NONE" if not seen else ("NOT-DEEPSEEK " + str(bad) if bad else "deepseek only"))
'
# Your three locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh), never contents.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  ls -laT $UH/.dsh 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  print -r -- "claude projects naming ${ROOT:t}: $(print -l -- $UH/.claude/projects/*${ROOT:t}*(N:t) | tr '\n' ' ')"
}
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set (every Pi run here uses it). Fix:"
  print -r -- "  export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"; return 1
}
PIFLAGS=()
pi_ready() {
  [[ -s $PIMODELF ]] || { print -r -- "STOP: $PIMODELF missing; run: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  PIFLAGS=(--provider deepseek --model $(<$PIMODELF))
}
lab_commit() { [[ $1 == before ]] && print -r -- $GTBASE || print -r -- $HEAD; }
# Per lab: V venv, P project, W member Worktree, EXT the installed extension.
lab() {
  V=$ROOT/venv-$1; P=$ROOT/proj-$1; W=$P/.graphtraj/.agent-worktrees/member
  EXT=$V/lib/python3.13/site-packages/graphtraj/runtimes/pi/extension.mjs
}
lab_ready() { lab $1; need $V/installed install && need $W/.pi/settings.json install && need $P/.pi/settings.json install; }
# A venv with GraphTraj ($2) and graftling GCOMMIT both installed as wheels (no network).
build_lab() {  # lab commit
  lab $1; local c=$2 S=$ROOT/src-$1
  [[ -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf $V $S && mkdir -p $S/graphtraj $S/graftling $S/wheels || return 1
  git -C $WT archive $c | tar -x -C $S/graphtraj || { print -r -- "STOP: GraphTraj $c not found"; return 1; }
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  $CONDA -m venv $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/click $RTSP/click-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
     $RTSP/websockets $RTSP/websockets-*.dist-info(N) $D/ || return 1
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling $S/graphtraj > /dev/null || return 1
  $V/bin/python -m pip install $pip $S/wheels/*.whl || return 1
  local got; got=$(cd / && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__)') \
    || { print -r -- "STOP: $V cannot import graphtraj and graftling"; return 1; }
  [[ -f $EXT ]] || { print -r -- "STOP: $EXT missing"; return 1; }
  print -r -- "graphtraj $c (wheel) + graftling $GCOMMIT (wheel): $got" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
# A git project set up through `graphtraj setup`, a member Worktree, and the extension installed project-locally.
build_project() {  # lab
  lab $1; OK=1
  if [[ ! -f $P/.graphtraj/config.yml ]]; then
    rm -rf $P && mkdir -p $P && git -C $P init -q -b main && print -r -- "# verify-583 $1" > $P/README.md \
      && git -C $P add README.md && git -C $P -c user.name=verify-583 -c user.email=verify-583@example.invalid commit -q -m init \
      || return 1
    say "graphtraj setup in $P (its question 'Create dev from ...? [y/N]' is answered y on stdin)"
    (cd $P && print y | launch PATH=$V/bin:$PATH -- $V/bin/graphtraj setup 2>&1 | tail -4)
  fi
  [[ -f $P/.graphtraj/config.yml && -d $P/.graphtraj/runner ]] && pass "$P has GraphTraj Config and runner" || fail "graphtraj setup did not create $P/.graphtraj/config.yml"
  if [[ ! -d $W ]]; then
    git -C $P worktree add -q -b agent/member $W dev || fail "git worktree add $W"
  fi
  (cd $P && launch PATH=$V/bin:$PATH -- $V/bin/graphtraj doctor 2>&1 | tail -3)
  local d; for d in $P $W; do
    (cd $d && launch -- pi install -l $EXT < /dev/null 2>&1 | tail -1)
    [[ $(cat $d/.pi/settings.json 2>/dev/null) == *graphtraj/runtimes/pi/extension.mjs* ]] \
      && pass "$d/.pi/settings.json names $EXT" || fail "$d/.pi/settings.json does not name the extension"
  done
  (( OK ))
}
# One real Pi run: name dir prompt [VAR=value...] [-- pi options...]; sets SRC SOUT SFILE SID.
pirun() {
  local name=$1 dir=$2 prompt=$3; shift 3
  local -a vars=() opts=()
  while (( $# )) && [[ $1 != -- ]]; do vars+=$1; shift; done
  (( $# )) && shift; opts=("$@")
  SOUT=$ROOT/out/$name.txt; local sdir=$ROOT/sessions/$name
  rm -rf $sdir $SOUT $SOUT.ps; mkdir -p $sdir ${SOUT:h}
  say "pi -p $PIFLAGS --session-dir $sdir --approve $opts  (in $dir; added: ${vars:-nothing}; PATH starts $V/bin)"
  # Processes of this ROOT only (your other Sessions' hosts are not counted).
  ( while :; do ps -axww -o pid=,command= | grep -E 'graftling\.(pi\.host|mcp)|graphtraj-(session|mcp)' \
      | grep -F -- $ROOT | grep -v grep; sleep 0.3; done > $SOUT.ps 2>&1 ) &
  local wk=$!
  (cd $dir && launch --key PATH=$V/bin:$PATH $vars -- perl -e 'alarm shift; exec @ARGV' 300 \
     pi -p $PIFLAGS --session-dir $sdir --approve $opts "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  kill $wk 2>/dev/null; wait $wk 2>/dev/null
  tail -20 $SOUT; print -r -- "pi exit=$SRC (full output: $SOUT)"
  SFILE=$(print -l -- $sdir/**/*.jsonl(N.om) | head -1)
  SID=$( [[ -n $SFILE ]] && head -1 $SFILE | python3 -I -c 'import json, sys; print(json.loads(sys.stdin.read()).get("id", ""))' )
  print -r -- "Pi Session file: ${SFILE:-none}; id: ${SID:-none}"
  # Main and any child Session: this run's session dir and Pi's default sessions under the isolated agent dir.
  local -a sfiles=($sdir/**/*.jsonl(N.) $PIAGENT/sessions/**/*.jsonl(N.))
  PUSED=$( (( $#sfiles )) && python3 -I -c $PJUDGE $sfiles || print -r -- "provider verdict: NONE (no Session file)" )
  print -r -- $PUSED
  mkdir -p $OUT 2>/dev/null && cp $SOUT $SOUT.ps $OUT/ 2>/dev/null; [[ -n $SFILE ]] && cp $SFILE $OUT/$name.session.jsonl 2>/dev/null
  return 0
}
sampling_ok() {  # FAIL when the process samples could not be taken (then every process count is meaningless)
  [[ -f $SOUT.ps ]] && ! grep -qiE 'not permitted|denied' $SOUT.ps && pass "process sampling worked (ps)" \
    || fail "process sampling failed: $(head -1 $SOUT.ps 2>/dev/null); the process counts above are not evidence"
}
provider_ok() {  # FAIL unless every assistant message of the run was deepseek
  [[ $PUSED == *'provider verdict: deepseek only'* ]] && pass "every Pi Session of this run used provider deepseek" \
    || fail "provider check: ${(M)${(f)PUSED}:#provider verdict*}"
}
seen() { sed -E 's/^ *[0-9]+ //' $SOUT.ps | grep -cE -- $1; }   # how many samples matched a pattern
procs() {
  print -r -- "processes of $ROOT seen while pi ran (unique, cut): $(sed -E 's/^ *[0-9]+ //' $SOUT.ps | sort -u | cut -c1-150 | head -6 | tr '\n' '|')"
}
# The Session file's MCP tool results and GraphTraj notices.
SJUDGE='
import json, sys
path, token = sys.argv[1], sys.argv[2]
calls, notices, token_seen = [], 0, False
def walk(value):
    if isinstance(value, dict):
        if value.get("role") == "toolResult" and str(value.get("toolName", "")).startswith("mcp__"):
            text = json.dumps(value.get("content"))[:160]
            calls.append((value["toolName"], bool(value.get("isError")), text))
        for item in value.values(): walk(item)
    elif isinstance(value, list):
        for item in value: walk(item)
for line in open(path, encoding="utf-8"):
    if "graphtraj:main-notice" in line:
        notices += 1
        token_seen = token_seen or (token != "-" and token in line)
    walk(json.loads(line))
for name, error, text in calls: print("MCP call", name, "isError" if error else "ok", "|", text)
print("MCP calls:", len(calls), "| ok graphtraj calls:", sum(1 for n, e, _ in calls if n.startswith("mcp__graphtraj__") and not e))
print("graphtraj:main-notice lines:", notices, "| token in them:", token_seen)
'
# The member / config prompt: what MCP tools the model has; the Main prompt adds a real call and a wait.
TOOLASK='Reply with exactly one line: TOOLS: the names of all your tools whose names start with mcp__, comma separated, or none.'
mainask() {
  print -r -- 'Do exactly these steps in order. 1) Call the tool mcp__graphtraj__tasks with input {"action":"discover"}. 2) Run this shell command: sleep 25. 3) Reply with two lines: TOOLS: the names of all your tools whose names start with mcp__, comma separated, or none; DISCOVER: ok, or the error text step 1 returned. If a GraphTraj notice message reaches you at any time, also reply with a line NOTICE: followed by the token it contains.'
}
# Queue one notice for the Main once a new Main claim appears (as a member's end would); writes $1.
watch_and_queue() {  # result-file token
  local res=$1 token=$2 runner=$P/.graphtraj/runner i
  local cont=$runner/main-sessions/continuity.jsonl
  local before=$( [[ -f $cont ]] && grep -c . $cont || print 0 )
  for i in {1..$WAIT}; do
    if [[ -f $cont ]] && (( $(grep -c . $cont) > before )); then
      (cd / && $V/bin/python -I -c '
import json, sys
from pathlib import Path
from graphtraj.execution.main_continuity import current_main, queue_notice
runner, token = Path(sys.argv[1]), sys.argv[2]
main = current_main(runner)
queue_notice(runner, main["connection"], {"source": "graphtraj", "alias": "verify583@script", "event": "message",
                                          "message": "verify-583 notice; token " + token})
print(json.dumps({"queued_for": main["runtime"] + ":" + main["session"], "token": token}))
' $runner $token) > $res 2>&1
      return 0
    fi
    sleep 1
  done
  print -r -- "no new Main claim in $cont within ${WAIT}s; no notice queued" > $res
}
# (a): an un-flagged Pi Main in the Config-backed project.
step_main() {  # lab
  key_ready && pi_ready && lab_ready $1 || return 1
  local name=main-$1 token=V583-$1-$(date +%H%M%S) res=$ROOT/out/main-$1.queued
  local runner=$P/.graphtraj/runner cont=$P/.graphtraj/runner/main-sessions/continuity.jsonl
  local claims0=$( [[ -f $cont ]] && grep -c . $cont || print 0 )
  rm -f $res; mkdir -p $ROOT/out
  watch_and_queue $res $token &
  local wq=$!
  pirun $name $P "$(mainask)"
  kill $wq 2>/dev/null; wait $wq 2>/dev/null
  say "evidence"
  procs
  print -r -- "graftling.pi.host samples: $(seen 'graftling\.pi\.host') | graftling.mcp: $(seen 'graftling\.mcp') | graphtraj-mcp: $(seen 'graphtraj-mcp') | graphtraj-session pi --collect: $(seen 'graphtraj-session pi --collect')"
  print -r -- ".agents-control: project $( [[ -e $P/.agents-control ]] && print YES || print no ); member $( [[ -e $W/.agents-control ]] && print YES || print no )"
  local claims1=$( [[ -f $cont ]] && grep -c . $cont || print 0 )
  print -r -- "continuity.jsonl ($cont): $claims0 -> $claims1 claims"; (( claims1 > claims0 )) && tail -1 $cont | cut -c1-400
  local key bind=none
  if [[ -n $SID ]]; then
    key=$(print -rn -- "pi:$SID" | shasum -a 256 | cut -d' ' -f1)
    bind=$runner/main-sessions/finalize_$key/session.yml
  fi
  print -r -- "binding: $bind $( [[ -f $bind ]] && print exists || print absent )"
  local collected=( ${(f)"$( [[ -n $SID && -d $P/.graphtraj/swarm ]] && grep -rlF -- $SID $P/.graphtraj/swarm 2>/dev/null )"} )
  print -r -- "collection: files under $P/.graphtraj/swarm naming Session $SID: ${#${collected:#}} $(print -l -- ${collected:#} | head -3 | tr '\n' ' ')"
  print -r -- "notice queue (watcher): $(cat $res 2>/dev/null || print 'nothing written')"
  local pend=-1
  if [[ -n $SID && -d $runner ]]; then
    pend=$(cd / && $V/bin/python -I -c 'import sys; from pathlib import Path; from graphtraj.execution.main_continuity import pending_notices; print(len(pending_notices(Path(sys.argv[1]), "pi", sys.argv[2])[0]))' $runner $SID 2>&1)
  fi
  print -r -- "notices still pending for pi:$SID: $pend"
  [[ -n $SFILE ]] && python3 -I -c $SJUDGE $SFILE $token | tee $ROOT/out/$name.judge
  print -r -- "model's TOOLS/DISCOVER/NOTICE lines: $(grep -E '^(TOOLS|DISCOVER|NOTICE):' $SOUT | tr '\n' '|')"
  local judge=$(cat $ROOT/out/$name.judge 2>/dev/null)
  say "verdict (computed)"
  OK=1
  (( SRC == 0 )) && pass "pi exited 0" || fail "pi exited $SRC"
  provider_ok
  sampling_ok
  local host=$(seen 'graftling\.pi\.host') ac=$( [[ -e $P/.agents-control || -e $W/.agents-control ]] && print 1 || print 0 )
  if [[ $1 == before ]]; then
    (( host > 0 || ac )) && pass "BEFORE shows the takeover (graftling.pi.host samples $host, .agents-control $ac), as expected for the unfixed code" \
      || fail "BEFORE shows no takeover (no graftling.pi.host, no .agents-control); report this"
    (( claims1 == claims0 )) && pass "BEFORE: no Main claim (Main not associated), as expected" || print -r -- "NOTE: BEFORE added a Main claim"
  else
    (( host == 0 )) && pass "no graftling.pi.host process" || fail "graftling.pi.host ran ($host samples)"
    (( ac == 0 )) && pass "no .agents-control in $P or $W" || fail ".agents-control appeared"
    (( $(seen 'graftling\.mcp') == 0 )) && pass "no graftling.mcp server process" || fail "graftling.mcp ran"
    (( $(seen 'graphtraj-mcp') > 0 )) && pass "the graphtraj MCP server (graphtraj-mcp of $V) ran" || fail "no graphtraj-mcp process seen"
    [[ $judge == *'ok graphtraj calls: '[1-9]* ]] && pass "a real mcp__graphtraj__* tool call returned without error (Session file)" \
      || fail "no successful mcp__graphtraj__* call in the Session file"
    (( claims1 > claims0 )) && [[ $(tail -1 $cont) == *"\"session\": \"$SID\""* ]] && pass "continuity.jsonl claims Main for pi:$SID" \
      || fail "no Main claim for pi:$SID"
    [[ -f $bind ]] && pass "finalize binding $bind exists" || fail "no finalize binding for pi:$SID"
    (( ${#${collected:#}} > 0 )) && pass "the collection under $P/.graphtraj/swarm names Session $SID" || fail "no collection naming $SID"
    [[ $judge == *'token in them: True'* ]] && pass "the queued notice (token $token) is in the Pi Session as graphtraj:main-notice" \
      || fail "the notice with token $token is not in the Pi Session"
    [[ $pend == 0 && $(cat $res 2>/dev/null) == *queued_for* ]] && pass "the queued notice was acknowledged (none pending)" \
      || fail "notice not queued or still pending ($pend pending)"
  fi
  if (( OK )); then print -r -- "next: zsh $THIS $( [[ $1 == before ]] && print main-after || print member-before )"
  else print -r -- "next: inspect $SOUT, $SOUT.ps and ${SFILE:-the Session file}; then rerun: zsh $THIS $STEP"; fi
  (( OK ))
}
# (b): Pi members in the member Worktree.
step_member() {  # lab
  key_ready && pi_ready && lab_ready $1 || return 1
  OK=1; local owner host ac var
  for owner in plugin-child runner; do
    [[ $owner == plugin-child ]] && var=PI_SUBAGENT_CHILD=1 || var=GRAPHTRAJ_CLI_CONNECTION=unused
    rm -rf $W/.agents-control
    pirun member-$1-$owner $W "$TOOLASK" $var
    say "evidence ($1 / $owner)"; procs
    host=$(seen 'graftling\.pi\.host'); ac=$( [[ -e $W/.agents-control ]] && print 1 || print 0 )
    print -r -- "graftling.pi.host samples: $host | graftling.mcp: $(seen 'graftling\.mcp') | graphtraj-mcp: $(seen 'graphtraj-mcp') | .agents-control in member: $ac"
    print -r -- "model's TOOLS line: $(grep -m1 '^TOOLS:' $SOUT || print none)"
    say "verdict ($1 / $owner, computed)"
    (( SRC == 0 )) && pass "pi exited 0" || fail "pi exited $SRC"
    provider_ok
    sampling_ok
    if [[ $1 == before ]]; then
      (( host > 0 || ac )) && pass "BEFORE shows the takeover (host samples $host, .agents-control $ac), as expected" \
        || fail "BEFORE shows no takeover; report this"
    else
      (( host == 0 )) && pass "no graftling.pi.host process" || fail "graftling.pi.host ran ($host samples)"
      (( ac == 0 )) && pass "no .agents-control in $W" || fail ".agents-control appeared in $W"
      (( $(seen 'graftling\.mcp') == 0 )) && pass "no graftling.mcp server process" || fail "graftling.mcp ran"
      (( $(seen 'graphtraj-mcp') > 0 )) && pass "the graphtraj MCP server ran" || fail "no graphtraj-mcp process seen"
    fi
  done
  (( OK )) && print -r -- "next: zsh $THIS $( [[ $1 == before ]] && print member-after || print config-before )" \
    || print -r -- "next: inspect $ROOT/out/member-$1-*.txt(.ps); then rerun: zsh $THIS $STEP"
  (( OK ))
}
# (c): --agents-config still hands the Session to graftling's host.
step_config() {  # lab
  key_ready && pi_ready && lab_ready $1 || return 1
  local cfg=$ROOT/pi-host-$1.json data=$ROOT/explicit-$1
  print -r -- "{\"root\": \"$data\"}" > $cfg
  pirun config-$1 $P "$TOOLASK" -- --agents-config $cfg
  say "evidence"; procs
  local host=$(seen 'graftling\.pi\.host --config') ; local gs=$(seen 'graphtraj-(mcp|session)')
  print -r -- "graftling.pi.host --config samples: $host | graftling.mcp: $(seen 'graftling\.mcp') | graphtraj-mcp/session: $gs | data root $data: $( [[ -d $data ]] && print exists || print absent )"
  print -r -- "model's TOOLS line: $(grep -m1 '^TOOLS:' $SOUT || print none)"
  say "verdict (computed)"
  OK=1
  (( SRC == 0 )) && pass "pi exited 0" || fail "pi exited $SRC"
  provider_ok
  sampling_ok
  (( host > 0 )) && pass "graftling.pi.host ran with --config" || fail "no graftling.pi.host --config process seen"
  [[ -d $data ]] && pass "graftling's data root $data was created" || fail "$data was not created"
  (( gs == 0 )) && pass "GraphTraj's own entry and MCP server did not run" || fail "graphtraj-mcp/session ran ($gs samples)"
  (( OK )) && print -r -- "next: zsh $THIS $( [[ $1 == before ]] && print config-after || print post )" \
    || print -r -- "next: inspect $SOUT and $SOUT.ps; then rerun: zsh $THIS $STEP"
  (( OK ))
}
# A venv with graftling installed as a WHEEL from GCOMMIT and GraphTraj editable from checkout $2 (no network).
suite_venv() {  # venv graphtraj-checkout
  local V=$1 gt=$2 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf $V $S && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
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
  print -r -- "graftling $GCOMMIT (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
# A fresh pytest temp root under TMPDIR, outside the Harness, with no Harness marker above it; sets RUNTMP.
run_root() {  # label
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/verify-583-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  key_ready || return 1
  ps -axww -o pid=,command= > /dev/null 2>&1 || { print -r -- "STOP: ps cannot list processes here (the run steps sample processes with it); run this script in your own terminal: zsh $THIS pre"; return 1; }
  mkdir -p $PIAGENT $ROOT/out $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  local t; for t in pi node python3 git; do print -r -- "$t: $(command -v $t) $(launch -- $t --version 2>&1 | head -1)"; done
  print -r -- "GraphTraj BEFORE $GTBASE ($(git -C $WT log --format=%s -1 $GTBASE 2>&1 | cut -c1-80)); AFTER = HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-80))"
  print -r -- "graftling $GCOMMIT: $(git -C $GREPO log --format=%s -1 $GCOMMIT 2>&1 | cut -c1-80)"
  [[ -d $RTSP/websockets && -d $RTSP/yaml && -d $RTSP/click ]] || { print -r -- "STOP: $RTSP lacks click, websockets or yaml"; return 1; }
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "the Pi model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$PIAGENT)"
  local listed; listed=$(cd $ROOT && launch --key -- perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $PIMODELF
  [[ -s $PIMODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pi_ready || return 1
  # Pin the isolated agent dir to DeepSeek flash, so a Session that names no model cannot pick another provider.
  print -r -- "{\"defaultProvider\": \"deepseek\", \"defaultModel\": \"$(<$PIMODELF)\", \"enabledModels\": [\"deepseek/$(<$PIMODELF)\"]}" > $PIAGENT/settings.json
  print -r -- "pinned $PIAGENT/settings.json: $(<$PIAGENT/settings.json)"
  say "names in a Pi launch environment (values never printed)"
  launch --key -- /usr/bin/env | cut -d= -f1 | sort | tr '\n' ' '; print
  local leaked=$(launch --key -- /usr/bin/env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | grep -vx DEEPSEEK_API_KEY)
  [[ -z $leaked ]] && pass "no provider credential other than DEEPSEEK_API_KEY reaches Pi" || { print -r -- "STOP: leaked names: $leaked"; return 1; }
  say "one-line Pi prompt: pi -p $PIFLAGS --no-session --no-tools (in $ROOT, no project extension there)"
  (cd $ROOT && launch --key -- perl -e 'alarm shift; exec @ARGV' 120 pi -p $PIFLAGS --no-session --no-tools \
     "Reply in one line: the exact model id and the provider you are running as, nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer with $PIFLAGS; check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "Pi answered as deepseek/$(<$PIMODELF)"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. BEFORE and AFTER venvs (wheels), Config-backed projects, member Worktrees, pi install -l. Dialog: none."
  need $PIMODELF pre || return 1
  local l rc=0
  for l in before after; do
    say "$l: GraphTraj $(lab_commit $l)"
    build_lab $l $(lab_commit $l) || return 1
    build_project $l || rc=1
  done
  (( rc == 0 )) && print -r -- "next: zsh $THIS main-before" || print -r -- "next: fix the FAIL above, then: zsh $THIS install"
  return $rc
  ;;
main-before) say "[main-before] Main. (a) un-flagged Pi Main, BEFORE (unfixed): the takeover is expected. Dialog: none."; step_main before ;;
main-after) say "[main-after] Main. (a) un-flagged Pi Main, AFTER: GraphTraj owns the Session. Dialog: none."; step_main after ;;
member-before) say "[member-before] Main. (b) Pi members, BEFORE: the takeover is expected. Dialog: none."; step_member before ;;
member-after) say "[member-after] Main. (b) Pi members, AFTER: not taken over. Dialog: none."; step_member after ;;
config-before) say "[config-before] Main. (c) --agents-config, BEFORE: graftling's host starts. Dialog: none."; step_config before ;;
config-after) say "[config-after] Main. (c) --agents-config, AFTER: graftling's host still starts. Dialog: none."; step_config after ;;
post)
  say "[post] Main. Your three locations vs pre (any difference FAILs). <5 s. Dialog: none."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh and ~/.claude/projects unchanged" || fail "a location changed (diff above)"
  print -r -- "Evidence copies: $OUT. Pi Sessions of these runs: $ROOT/sessions."
  print -r -- "To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $HEAD -> $URL $BRANCH. Dialog: none expected."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && { pass "already on GitHub"; return 0; }
  print -r -- "authors and committers: $(git -C $WT log --format='%an <%ae> | %cn <%ce>' $GTBASE..$HEAD | sort -u)"
  git -C $WT push $URL "${HEAD}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && pass "GitHub $BRANCH = $HEAD" || { fail "GitHub $BRANCH is not $HEAD"; return 1; }
  ;;
suite)
  setopt local_options no_bg_nice
  say "[suite] GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $others; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $WT || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))') || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP (TMPDIR, outside the Harness) | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  cat $R/run.txt
  local extra=(${(Q)${(z)${VERIFY583_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $R/run.txt
  (cd $WT && launch TMPDIR=$RUNTMP -- $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: newest suite; FAILED/ERROR lines classed against 516's current definition. Dialog: none."
  local K=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- "516 current definition: $K"; [[ -f $K ]] || { print -r -- "STOP: cannot read $K"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet)"; return 1; }
  local line t id new=0 any=0; local -a ids=()
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; id=${line#* }; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; new=1; ids+=$id; fi
  done
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
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
  say "[suite-base] the NEW node ids on GraphTraj $GTBASE with graftling $GCOMMIT (wheel). Dialog: none. No login."
  run_root base || return 1
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  print -r -- "base checkout: $B (a git clone; $(git -C $B log --oneline -1))"
  local V=$T/venv-base-${GTBASE[1,8]}
  suite_venv $V $B || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  (cd $B && launch TMPDIR=$RUNTMP -- $V/bin/python -m pytest -p no:cacheprovider -q -rA "${ids[@]}" > $R/base.txt 2>&1); local rc=$?
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
*) print -r -- "usage: zsh $THIS pre|install|main-before|main-after|member-before|member-after|config-before|config-after|post|push|suite|SR|suite-base <ids>"; return 2 ;;
esac
}
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
