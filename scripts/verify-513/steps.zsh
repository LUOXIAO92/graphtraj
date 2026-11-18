#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 513 Main-run steps: graftling alone, MCP server `graftling`, on four real hosts. One step at a time:
#   zsh <this file> <STEP>
#   0   preflight: versions, clone head and branch, each CLI's version, a one-line answer from claude and codex
#   B   dev wheel of the clone HEAD into a fresh venv under tmp/513, isolated projects, versions
#   F   graftling full suite of the clone HEAD in that venv (background, idle host)     R  its results
#   Ct  USER, plain Terminal: trust the Claude project (one dialog), then C
#   C X P D   Claude Code / Codex / Pi / DSH host: one prompt -> agents create of a reviewed child of the same
#             Runtime -> wait; raw records under the Task's realhost/<step>-<time>/ and check513.py lines
# Invocations follow scripts/real-host/394 (the standalone-graftling matrix, rh394.py and common.zsh):
# claude -p with --mcp-config/--strict-mcp-config/--allowedTools, python -m graftling.codex.host, pi --mode json
# -e extension.mjs --agents-config, dsh --profile --patch --json with GRAFTLING_DSH_CONFIG; keys as load_key there.
# pytest's TMPDIR stays outside the Harness; each test step prints it. No step signals a process it did not start.
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree (GraphTraj)
H=${WT:h:h:h:h}                                     # <Harness>
G=$WT/.scratch/513/graftling                        # the graftling clone under test
BR=agent/513-graftling-mcp-server-name
T=$H/tmp/513                                        # venv, wheels, projects, run scratch
OUT=$H/.graphtraj/core/state/tasks/513-graftling-mcp-server-name/realhost
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
V=$T/venv
CHECK=${0:A:h}/check513.py
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
CLAUDE_MODEL=claude-sonnet-5-5
CODEX_MODEL=gpt-6-luna            # user instruction: Codex tests use gpt-6-luna
DEEPSEEK_MODEL=deepseek-flash
PI_PROVIDER=deepseek
PI_SANDBOX=$HOME/agents-pi-sandbox   # scripts/real-host/install-pi-sandbox.sh
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: $PYTEST_TMP (outside the Harness)"
}
quiet() {  # the full suite runs on an idle host, never beside another suite
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun this step later:"; print -r -- $others; return 1; }
}
bounded() { local s=$1; shift; /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' $s "$@"; }
clone_head() {
  [[ $(git -C $G branch --show-current) == $BR ]] || { print "STOP: $G is not on $BR"; return 1; }
  git -C $G diff --quiet HEAD -- || { print "STOP: $G has uncommitted changes"; return 1; }
  git -C $G rev-parse HEAD
}
venv_check() {
  [[ -f $V/installed-commit && $(<$V/installed-commit) == $(clone_head) ]] \
    || { print -r -- "STOP: $V is not built from the clone HEAD; run: zsh ${0:A} B"; return 1; }
}
load_key() {  # scripts/real-host/394/common.zsh load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
clean_env() {  # a host inherits no other host's markers (rh394.clean_environment)
  local name
  for name in ${(k)parameters[(R)*export*]}; do
    [[ $name == (GRAPHTRAJ_|GRAFTLING_|AGENT_SWARM_)* || $name == (DSH_SESSION_ID|DSH_AGENT_SOURCE|DSH_AGENT_PACKAGE) ]] \
      && unset $name
  done
  return 0
}
# One step's run: scratch RUN under tmp/513, evidence D under the Task's realhost/, a reviewer and config.yml.
begin_run() {  # $1 step, $2 child runtime, $3 connection YAML lines (indented 4)
  venv_check || return 1
  local stamp=$(date +%Y%m%dT%H%M%S)
  RUN=$T/runs/$1-$stamp D=$OUT/$1-$stamp DATA=$T/runs/$1-$stamp/data
  mkdir -p $RUN $D $DATA
  print -r -- "clone $(clone_head) step $1 started $stamp" > $D/run.txt
  print -r -- "evidence: $D"; print -r -- "scratch:  $RUN"
  # The reviewer logs the tool of every call it is asked about and allows it.
  cat > $RUN/reviewer.py <<'PY'
import json, sys
request = json.load(sys.stdin)['request']
with open(sys.argv[1], 'a') as log:
    log.write(str(request.get('tool')) + '\n')
print(json.dumps({'decision': 'allow', 'reason': 'Task 513 test reviewer allows every call.'}))
PY
  cat > $DATA/config.yml <<EOF
save_normalized_sessions: true
reviewers:
  rev513:
    command: [$V/bin/python, -I, $RUN/reviewer.py, $D/reviewer.log]
    timeout_seconds: 60
connections:
  rev-$2:
    runtime: $2
    review: rev513
$3
presets:
  rev513:
    connection: rev-$2
EOF
  cp $DATA/config.yml $D/config.yml
  PROMPT="Use only the MCP tool mcp__graftling__agents, not your own subagents. Make these calls one at a time, in this order. Where an argument says <agent from 1>, use the \"agent\" field returned by call 1.
1. {\"action\": \"execute\", \"feature\": \"create\", \"arguments\": {\"runtime\": \"$2\", \"preset\": \"rev513\", \"instruction\": \"Call your agents tool exactly once with {\\\"action\\\": \\\"execute\\\", \\\"feature\\\": \\\"status\\\", \\\"arguments\\\": {}}. Then reply with exactly: PONG-513\"}}
2. {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": \"<agent from 1>\", \"timeout_seconds\": 300}}
A notice from agents may arrive at any time and changes nothing. Then reply with the child's answer and stop."
  print -r -- $PROMPT > $D/host.prompt.txt
}
end_run() {  # $1 runtime, $2.. extra paths to scan; copies the data root's records, then judges
  cp -R $DATA $D/data 2>/dev/null || true
  print -r -- "-- check513.py ($1)"
  $V/bin/python -I $CHECK $1 $D $D/reviewer.log $D "${@:2}" | tee $D/summary.txt || true
  print -r -- "raw records: $D"
}
CLAUDE_CHILD="    models: [$CLAUDE_MODEL]"

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case $STEP in
0)
  say "[0] preflight. Dialog: none. Two model answers (claude, codex), each at most 120 s."
  print "zsh: $ZSH_VERSION ($0)"; print "git: $(git --version)"
  print "conda python: $($CONDA --version 2>&1) ($CONDA)"
  print "Harness: $H"; print "Worktree: $WT ($(git -C $WT rev-parse --short HEAD))"
  print "clone: $G ($(git -C $G rev-parse --short HEAD) on $(git -C $G branch --show-current); expected $BR; base $(git -C $G merge-base HEAD dev | cut -c1-8))"
  print "clone graftling version: $(sed -n 's/^__version__ = "\(.*\)"$/\1/p' $G/src/graftling/__init__.py)"
  check_tmp
  local b; for b in claude codex pi dsh node; do
    print -r -- "$b: $(command -v $b || print 'not on PATH') | $(bounded 20 $b --version 2>&1 | head -1)"
  done
  print "pi sandbox: $([[ -f $PI_SANDBOX/pi-sandbox.env ]] && print present || print "MISSING ($PI_SANDBOX/pi-sandbox.env; /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh)")"
  mkdir -p $T/preflight
  print -r -- "-- claude -p ($CLAUDE_MODEL), from $T/preflight:"
  (cd $T/preflight && bounded 120 claude -p --model $CLAUDE_MODEL 'Reply with one line: your model name and the word READY-513.' 2>&1 | tail -3) || print "claude rc=$?"
  print -r -- "-- codex exec ($CODEX_MODEL), from $T/preflight:"
  (cd $T/preflight && bounded 120 codex exec --skip-git-repo-check -m $CODEX_MODEL 'Reply with one line: your model name and the word READY-513.' 2>&1 | tail -3) || print "codex rc=$?"
  print "pi and dsh: their model and login are observed by P and D themselves (DeepSeek key from ~/.zshrc, as 394)."
  load_key || true
  print -r -- "next: zsh ${0:A} B"
  ;;
B)
  say "[B] dev wheel of the clone HEAD, fresh venv $V, projects. Dialog: none."
  local C=$(clone_head) N=$T/wheels-$(clone_head | cut -c1-10)
  [[ -e $V ]] && { print -r -- "moving the earlier venv aside: $V -> $V.$(date +%H%M%S)"; mv $V $V.$(date +%H%M%S); }
  mkdir -p $T $N
  $CONDA -m venv $V
  local SP=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  # No PyPI on this host: production's yaml and websockets (verify-506 copy_deps).
  cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $RT/websockets $RT/websockets-*.dist-info(N) $SP/
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $N $G/src/graftling >/dev/null
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl
  print -r -- $C > $V/installed-commit
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graftling, yaml, websockets; print("graftling", graftling.__version__, graftling.__file__)
import importlib.util as u; print("graphtraj importable:", u.find_spec("graphtraj") is not None)')
  mkdir -p $T/claude-project
  print -r -- "wheel: $(print $N/graftling-*.whl)"; print -r -- "built from: $C"
  print -r -- "next: zsh ${0:A} F (idle host), then USER: zsh ${0:A} Ct"
  ;;
F)
  local VT=$T/venv-test
  say "[F] graftling full suite of the clone HEAD in $VT (editable install of the clone; conda's pytest), background. Dialog: none. Returns at once."
  check_tmp; quiet
  local C=$(clone_head) R=$OUT/F-$(clone_head | cut -c1-10)-$(date +%H%M%S)
  # The suite's conftest requires its subprocesses to import the clone itself, so this venv installs it
  # editable; the real-host venv $V keeps the wheel.
  if [[ ! -x $VT/bin/python ]]; then
    $CONDA -m venv --system-site-packages $VT
    cp -Rp $RT/websockets $RT/websockets-*.dist-info(N) $($VT/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $G/src/graftling 2>&1 | grep -vi cache || true
  fi
  (cd $PYTEST_TMP && $VT/bin/python -I -c 'import graftling, pytest; print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)')
  print -r -- "clone HEAD: $C"
  mkdir -p $R
  (cd $G && TMPDIR=$PYTEST_TMP nohup $VT/bin/python -m pytest -p no:cacheprovider -q -rfE > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- "started; result: tail -30 $R/suite.txt"
  print -r -- "next, when it ends: zsh ${0:A} R"
  ;;
R)
  say "[R] results. Dialog: none."
  local f=($OUT/F-*(N/om[1]))
  (( $#f )) || { print -r -- "no F result under $OUT yet; run: zsh ${0:A} F"; return 0; }
  print -r -- "---- $f"
  tail -6 $f/suite.txt
  print "failed/error lines:"
  grep -h -E '^(FAILED|ERROR) ' $f/suite.txt | sort -u || print "(none)"
  print -r -- "next: report $f to the Leader"
  ;;
Ct)
  say "[Ct] USER in a plain Terminal. Dialog: one, Claude Code's 'Do you trust the files in this folder?' for $T/claude-project -> choose 'Yes, proceed', then type /exit. (none when trusted before)"
  venv_check
  local P=$T/claude-project
  (cd $P && $V/bin/python -m graftling.claude.host configuration --project $P --claude $(command -v claude) --write) >/dev/null
  # The project's own settings: Harness instruction files excluded (verify-common, Task 489) and the
  # project's .mcp.json server pre-enabled, so the trust dialog is the only one.
  $H/.venv-runtime/bin/python -I $WT/scripts/verify-common/claude_isolation.py settings $H $P
  $V/bin/python -I -c 'import json, sys; p = sys.argv[1]; d = json.load(open(p)); d["enabledMcpjsonServers"] = ["graftling"]; json.dump(d, open(p, "w"), indent=2)' $P/.claude/settings.local.json
  print -r -- ".mcp.json servers: $($V/bin/python -I -c 'import json,sys; print(list(json.load(open(sys.argv[1]))["mcpServers"]))' $P/.mcp.json)"
  (cd $P && claude) || print "claude exit $?"
  print -r -- "next (Main): zsh ${0:A} C"
  ;;
C)
  say "[C] Claude Code host (configuration --write project $T/claude-project): claude -p -> create a reviewed Claude child -> wait. Dialog: none (Ct trusted the folder). At most 15 min."
  clean_env
  begin_run C claude $CLAUDE_CHILD || return 1
  local P=$T/claude-project S=$(uuidgen | tr A-Z a-z)
  (cd $P && $V/bin/python -m graftling.claude.host configuration --project $P --claude $(command -v claude) --write) >/dev/null
  $V/bin/python -I -c 'import json, sys
p, root, claude = sys.argv[1:4]
d = json.load(open(p)); d["root"] = root; d["settings"] = {"permission_mode": "default"}
d["runtimes"] = {"claude": {"executable": claude, "permission_mode": "default"}}
json.dump(d, open(p, "w"), indent=2)' $P/.agents-control/claude-host.json $DATA $(command -v claude)
  cp $P/.mcp.json $D/mcp.json; cp $P/.agents-control/claude-host.json $D/claude-host.json
  (cd $P && bounded 900 claude -p --model $CLAUDE_MODEL --output-format stream-json --verbose \
     --mcp-config $P/.mcp.json --strict-mcp-config --allowedTools mcp__graftling__agents --session-id $S \
     < $D/host.prompt.txt > $D/stream.jsonl 2> $D/stderr.txt) || print "claude rc=$?"
  cp $P/.agents-control/host.log $D/host.log 2>/dev/null || true
  # The display hook's ui.log rows go to the native transcript, not necessarily the -p stream.
  local tr=($HOME/.claude/projects/*/$S.jsonl(N))
  (( $#tr )) && cp $tr $D/ || print -r -- "no native transcript $S.jsonl under ~/.claude/projects"
  end_run claude
  print -r -- "observables: names = stream.jsonl system init 'tools' (+ every file); child = an agents result line with last_message PONG-513; review = reviewer.log has no *__agents tool while the child's records name mcp__graftling__agents; display = '┌ '/'agents · ' rows in the native transcript $S.jsonl or the stream"
  print -r -- "next: zsh ${0:A} X"
  ;;
X)
  say "[X] Codex host (python -m graftling.codex.host, $CODEX_MODEL): create a reviewed Codex child -> wait. Dialog: none (the parent's own native requests print to stderr; the step answers none). At most 15 min."
  clean_env
  begin_run X codex "    models: [$CODEX_MODEL]" || return 1
  local W=$RUN/work; mkdir -p $W
  $V/bin/python -I -c 'import json, sys
work, model, codex, out = sys.argv[1:5]
settings = lambda: {"arguments": [codex], "worktree_path": work, "session_parameters": {"cwd": work, "model": model,
  "developerInstructions": "", "config": {"default_permissions": "work", "permissions": {"work": {"extends": ":workspace",
  "filesystem": {":workspace_roots": {".": "write"}}}}}}}
json.dump({"adapter_request": settings()}, open(out, "w"), indent=2)' $W $CODEX_MODEL $(command -v codex) $D/codex-settings.json
  touch $RUN/started.marker
  (cd $W && bounded 900 $V/bin/python -m graftling.codex.host --settings $D/codex-settings.json --directory $DATA \
     --output $D/output.json "$(<$D/host.prompt.txt)" < /dev/null > $D/stdout.txt 2> $D/stderr.txt) || print "codex host rc=$?"
  # Codex records the model's MCP calls in its rollout under the Codex home's sessions/.
  local CH=${CODEX_HOME:-$HOME/.codex}
  mkdir -p $D/rollouts
  for f in $CH/sessions/**/rollout-*.jsonl(N.); do [[ $f -nt $RUN/started.marker ]] && cp $f $D/rollouts/; done
  print -r -- "rollouts copied: $(ls $D/rollouts | wc -l | tr -d ' ')"
  end_run codex
  print -r -- "observables: names = rollouts/*.jsonl and output.json; child = output.json operations (wait last_message PONG-513); review = reviewer.log has no *__agents tool; display = stderr '┌ <parent> → <agent>' rows"
  print -r -- "next: zsh ${0:A} P"
  ;;
P)
  say "[P] Pi host (pi --mode json -e graftling/pi/extension.mjs --agents-config): create a reviewed Pi child -> wait. Dialog: none. At most 15 min."
  clean_env; load_key || return 1
  [[ -f $PI_SANDBOX/pi-sandbox.env ]] || { print -r -- "STOP: $PI_SANDBOX/pi-sandbox.env missing; run: /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh"; return 1; }
  local SBP=$(sed -n 's/^sandbox_python=//p' $PI_SANDBOX/pi-sandbox.env) SBX=$(sed -n 's/^sandbox_path=//p' $PI_SANDBOX/pi-sandbox.env)
  begin_run P pi "    provider: $PI_PROVIDER
    api_key_env: DEEPSEEK_API_KEY
    models: [$DEEPSEEK_MODEL]" || return 1
  local W=$RUN/work PH=$RUN/pi-home SD=$RUN/sessions ID=rh513-$(uuidgen | cut -c1-8 | tr A-Z a-z)
  mkdir -p $W $PH $SD
  local EXT=$($V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "pi" / "extension.mjs")')
  $V/bin/python -I -c 'import json, sys
root, home, sbp, sbx, model, provider, out = sys.argv[1:8]
json.dump({"root": root, "pi": {"provider": provider, "model": model, "agent_dir": home, "sandbox_python": sbp,
  "sandbox_path": sbx, "worktree_access": "read", "api_key_env": "DEEPSEEK_API_KEY"}}, open(out, "w"), indent=2)' \
    $DATA $PH $SBP $SBX $DEEPSEEK_MODEL $PI_PROVIDER $D/pi-host.json
  (cd $W && PI_CODING_AGENT_DIR=$PH GRAFTLING_PYTHON=$V/bin/python bounded 900 pi --mode json --session-dir $SD --session-id $ID \
     --model $PI_PROVIDER/$DEEPSEEK_MODEL -e $EXT --agents-config $D/pi-host.json "$(<$D/host.prompt.txt)" \
     < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "pi rc=$?"
  local ps=($SD/*.jsonl(N))
  (( $#ps )) && cp $ps $D/ || print -r -- "no Pi Session file in $SD"
  end_run pi
  print -r -- "observables: names = the Pi Session file's tool calls and stdout.jsonl; child = toolResult with last_message PONG-513; review = reviewer.log has no *__agents tool; display = graftling:agent-communication entries (the display renders only with a UI: --mode json has none, so CANNOT there is expected and needs an interactive Pi run)"
  print -r -- "next: zsh ${0:A} D"
  ;;
D)
  say "[D] DSH host (the graftling-dsh plugin row, GRAFTLING_DSH_CONFIG): create a reviewed DSH child -> wait. Dialog: none. At most 15 min."
  clean_env; load_key || return 1
  begin_run D dsh "    api_key_env: DEEPSEEK_API_KEY
    models: [$DEEPSEEK_MODEL]" || return 1
  local W=$RUN/work DH=$RUN/dsh-home; mkdir -p $W $DH
  local PLUGIN=$($V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh" / "plugin.mjs")')
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $DATA $(command -v dsh) $DEEPSEEK_MODEL $D/dsh-host.json
  cat > $D/dsh-main.patch.yml <<EOF
- id: llm-deepseek
  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}
- insert:
  - {id: agents-host, name: $PLUGIN}
EOF
  (cd $W && DSH_HOME=$DH GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$D/dsh-host.json bounded 900 dsh --profile agents513 \
     --from-default-profile headless --patch $D/dsh-main.patch.yml --json "$(<$D/host.prompt.txt)" \
     < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "dsh rc=$?"
  # DSH's own Session logs (request headers list the model's tools).
  mkdir -p $D/dsh-home-logs
  [[ -d $DH/sessions ]] && cp -R $DH/sessions $D/dsh-home-logs/ || print -r -- "no sessions/ under $DH; $DH is scanned as a whole"
  # The display is the browser tool view (client.mjs): which keys the installed bundle registers.
  node -e '
const { readFileSync } = require("node:fs"); const vm = require("node:vm"); let m;
vm.runInNewContext(readFileSync(process.argv[1], "utf8"), { window: { __ModuleLoader__: { load(d) { m = d; } } } });
const keys = [];
m.factory(() => ({ createElement: () => ({}) })).apply({ slots: { inject: (n, f) => f(), entriesOfSlot: () => [],
  subscribe: () => () => {}, register: (o) => { keys.push(o.key); return () => {}; } } });
console.log("installed DSH tool view keys: " + JSON.stringify(keys));' ${PLUGIN:h}/client.mjs | tee $D/client-view-keys.txt
  end_run dsh $DH
  print -r -- "observables: names = DSH Session logs' request headers/tool calls and stdout.jsonl; child = tool_result with last_message PONG-513; review = reviewer.log has no *__agents tool; display = the web tool view only (client-view-keys.txt shows it renders mcp__graftling__agents; a browser observation is not part of this step)"
  print -r -- "next: report $OUT to the Leader"
  ;;
*) print -r -- "usage: zsh ${0:A} 0|B|F|R|Ct|C|X|P|D"; return 2 ;;
esac
