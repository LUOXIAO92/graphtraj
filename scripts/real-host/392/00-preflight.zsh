#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 00: the preflight. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/00-preflight.zsh
#
# Each host answers one line with its configured model and login. A host's line shows that it is
# reachable; which model answered is not proven by what the model says (403). The shell, the commit,
# install-pi-sandbox.sh and its tools, and the local-binding probe of step 21 are checked too.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 00-preflight 8 none 'every line says PASS: four hosts answer, the shell is zsh, the Pi sandbox is verified, the tools resolve, the probes are ready'

ASK='In one line: name the model you are running as, and confirm you can answer. Do not use any tool or print any key.'
PROBE_DIR=$RUN/probe
mkdir -p $PROBE_DIR

# `answers <label> <stdin file> <command...>`: bounded; the answer is kept and judged by its exit.
answers() {
  setopt local_options no_err_exit
  local label=$1 input=$2 code=0; shift 2
  (cd $PROBE_DIR && bounded 180 "$@" < $input > $OUT/$label.answer.txt 2> $OUT/$label.stderr.txt) || code=$?
  if (( code == 0 )) && [[ -s $OUT/$label.answer.txt ]]; then
    check PASS "$label answers: $(tail -1 $OUT/$label.answer.txt | cut -c1-200)"
  else
    check FAIL "$label answers: exit $code (142 is the 180 s limit); $(tail -1 $OUT/$label.stderr.txt | cut -c1-300)"
  fi
}

check PASS "shell: zsh $ZSH_VERSION at $(command -v zsh)"
check PASS "commit: Worktree code is $COMMIT"
find_hosts
info "claude: $CLAUDE ($($CLAUDE --version 2>&1 | tail -1))"
info "codex: $CODEX ($($CODEX --version 2>&1 | tail -1))"
info "pi: $PI_BIN ($($PI_BIN --version 2>&1 | tail -1))"
info "dsh: $DSH ($($DSH --version 2>&1 | tail -1))"
print -rl -- "claude $($CLAUDE --version 2>&1 | tail -1)" "codex $($CODEX --version 2>&1 | tail -1)" \
  "pi $($PI_BIN --version 2>&1 | tail -1)" "dsh $($DSH --version 2>&1 | tail -1)" > $OUT/versions.txt

load_key
if [[ -n ${DEEPSEEK_BASE_URL:-} ]]; then
  note "DEEPSEEK_BASE_URL is set in this shell, to host ${${DEEPSEEK_BASE_URL#*://}%%/*}; the steps leave it set (411)"
else
  note "DEEPSEEK_BASE_URL is unset in this shell; the DSH-child check of 411 needs it set, so it says what it could show"
fi

MODEL=$(codex_model)
if [[ -n $MODEL ]]; then
  check PASS "codex model from ~/.codex/config.toml: $MODEL"
else
  check FAIL "codex model: no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run this again"
fi
LOGIN=$($CODEX login status 2>&1 | tail -1) && check PASS "codex login: $LOGIN" || check FAIL "codex login: $LOGIN"

print -r -- $ASK > $PROBE_DIR/ask.txt
print -n > $PROBE_DIR/empty.txt
mkdir -p $PROBE_DIR/pi-home $PROBE_DIR/dsh-home
print -rl -- '- id: llm-deepseek' '  config:' '    apiKeyEnv: DEEPSEEK_API_KEY' '    baseURL: https://api.deepseek.com' > $PROBE_DIR/dsh.patch.yml
answers claude $PROBE_DIR/ask.txt $CLAUDE -p --model $CLAUDE_MODEL
answers codex $PROBE_DIR/ask.txt $CODEX exec --skip-git-repo-check --ephemeral -s read-only -
answers pi $PROBE_DIR/empty.txt env PI_CODING_AGENT_DIR=$PROBE_DIR/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
  $PI_BIN --no-session --no-tools --model $PI_PROVIDER/$PI_MODEL -p $ASK
answers dsh $PROBE_DIR/empty.txt env DSH_HOME=$PROBE_DIR/dsh-home \
  $DSH --profile probe --from-default-profile headless --patch $PROBE_DIR/dsh.patch.yml $ASK

say "the Pi sandbox (nothing is downloaded when it is already complete; the user approved the install on 20261031)"
if /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh ${AGENTS_392_DRY_SANDBOX:+$AGENTS_392_DRY_SANDBOX} > $OUT/install-pi-sandbox.txt 2>&1 \
    && [[ -f $PI_SANDBOX/pi-sandbox.env ]]; then
  check PASS "install-pi-sandbox.sh: $(tail -1 $OUT/install-pi-sandbox.txt)"
  read_sandbox
  for tool in srt node rg; do
    FOUND=$(/usr/bin/env PATH=$SANDBOX_PATH /usr/bin/which $tool) && check PASS "sandbox tool $tool: $FOUND" || check FAIL "sandbox tool $tool: not on $SANDBOX_PATH"
  done
  $SANDBOX_PYTHON -c 'import agent_sandbox' 2>> $OUT/install-pi-sandbox.txt && check PASS "agent_sandbox imports in $SANDBOX_PYTHON" \
    || check FAIL "agent_sandbox does not import in $SANDBOX_PYTHON"
else
  check FAIL "install-pi-sandbox.sh: NOT VERIFIED; last line: $(tail -1 $OUT/install-pi-sandbox.txt); see install-pi-sandbox.txt"
fi

say "the probe of step 21: sandbox-exec refuses a TCP bind and leaves Unix sockets alone"
PROFILE='(version 1)(allow default)(deny network-bind (local ip "*:*"))'
PROBE=$(RH_PROBE_DIR=$PROBE_DIR /usr/bin/sandbox-exec -p $PROFILE $PY -I -c 'import os, socket, tempfile
s = socket.socket()
try:
    s.bind(("127.0.0.1", 0)); print("BOUND")
except PermissionError:
    print("EPERM")
u = socket.socket(socket.AF_UNIX)
u.bind(tempfile.mktemp(dir=os.environ["RH_PROBE_DIR"])); print("UNIX")' 2>&1 | tr '\n' ' ')
if [[ $PROBE == 'EPERM UNIX ' ]]; then
  check PASS "bind probe: $PROBE"
else
  check CANNOT "bind probe: expected EPERM UNIX, got $PROBE; the real resume and launch-failed checks of steps 21 and 22 will say CANNOT"
fi

step_end
