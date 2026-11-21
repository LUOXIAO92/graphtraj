#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 551: which tools and MCP servers does a Task-free child created through `agents create` really get on
# Claude, Codex, Pi and DSH, and can it open a GraphTraj general method (`tasks` discover/describe) and read the
# installed manual (manual_ref)?        zsh scripts/verify-551/steps.zsh <STEP> [ARG]   (Main's Bash, this Worktree)
# Order: 00 -> (U only if 00 says so) -> B all -> (later, once the Leader names the commits) A0 -> A all -> G -> GR
#   00  versions; each host (claude, codex gpt-6-luna, pi and dsh deepseek-flash) answers one line with its model and
#       login; builds BASE/project-before with the IN-USE installation (.venv-runtime, read only): own git,
#       `graphtraj setup`, Claude host configuration, four inline child roles resolved by the Task-free driver
#       without a model; probe Tasks (tasks discover + describe concept-clarification, manual_ref readable); a
#       one-line Claude gate whose init must list the graphtraj server with mcp__graphtraj__agents.
#   U   USER, only when 00's gate reports folder trust: one dialog in a plain Terminal.
#   B   BEFORE evidence, `B <claude|codex|pi|dsh|all>`: a headless Claude Main (claude -p, the project's own
#       .mcp.json) creates ONE Task-free child of that Runtime with agents create, waits for it, and prints the
#       child's final message. The child lists its tools and MCP servers, calls tasks discover/describe
#       concept-clarification and reads the manual_ref. sum551.py judges from the child's own records too.
#   A0, A, G, GR: added with the candidate commits (README).
# Layout: BASE=/private/tmp/agents-551 (outside the Harness): project-before/, runs/<STEP>-<runtime>-<time>/
# (parent.jsonl, records/ = every project record changed during the run, plus the child's Codex rollout by id).
# Never written: ~/.claude, ~/.codex, ~/.pi, dotfiles, the Harness, .venv-runtime (only executed). The one exception
# is each host's normal session file of its own run (Claude parent transcript, Codex child rollout).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice extended_glob
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY551_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY551_H:-${WT:h:h:h:h}}
BASE=${VERIFY551_BASE:-/private/tmp/agents-551}
RT=${VERIFY551_RT:-$H/.venv-runtime}                   # BEFORE = the in-use installation, executed read only
CONDA=$HOME/miniconda3/bin/python3.13
OUT=$BASE/runs
PARENT_MODEL=${VERIFY551_PARENT_MODEL:-claude-sonnet-5-5}
CODEX_MODEL=gpt-6-luna; PI_PROVIDER=deepseek; PI_MODEL=deepseek-flash
PI_SANDBOX_ENV=${VERIFY551_PI_SANDBOX_ENV:-$HOME/agents-pi-sandbox/pi-sandbox.env}   # verify-513: srt for Pi
DSH_SESSIONS=${VERIFY551_DSH_SESSIONS:-$HOME/.dsh/sessions}   # DSH's own session logs (clean env: no DSH_HOME); read only
STEP=${1:-}; ARG=${2:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY551_STUB:-} ]] && path=($VERIFY551_STUB $path)        # rehearsal only: stub hosts first
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} \
  ${V551_PI_PATH:+V551_PI_PATH=$V551_PI_PATH} ${V551_PI_PYTHON:+V551_PI_PYTHON=$V551_PI_PYTHON} "$@"; }
load_key() {  # verify-513 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]]
}
pi_sandbox() {  # srt for the Pi child role, from the user's sandbox install (read only)
  if [[ -f $PI_SANDBOX_ENV ]]; then
    export V551_PI_PYTHON=$(sed -n 's/^sandbox_python=//p' $PI_SANDBOX_ENV) V551_PI_PATH=$(sed -n 's/^sandbox_path=//p' $PI_SANDBOX_ENV)
    print -r -- "Pi sandbox (srt) from $PI_SANDBOX_ENV: python ${V551_PI_PYTHON:-default}, path ${V551_PI_PATH:-?}"
  else print -r -- "Pi sandbox env $PI_SANDBOX_ENV missing: the Pi role uses PATH for srt"; fi
}
inst() {  # $1 label -> the installation's bin directory
  case $1 in before) print -r -- $RT/bin ;; *) print -r -- $BASE/venv-$1/bin ;; esac
}
project() { print -r -- $BASE/project-$1; }
build_project() {  # $1 label: isolated project with the installation of that label
  local p=$(project $1) b=$(inst $1)
  say "isolated project $p with $(cd $BASE && $b/python -I -c 'import importlib.metadata as m, graphtraj; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"), "from", graphtraj.__file__)')"
  if [[ ! -d $p/.git ]]; then
    mkdir -p $p; (cd $p && git init -q -b main && print -r -- "# 551 probe" > README.md && git add README.md \
      && git -c user.name=551 -c user.email=551@invalid commit -qm "Initial source") || return 1
  fi
  [[ -f $p/.graphtraj/config.yml ]] || (cd $p && print y | clean $b/graphtraj setup | tail -1) || return 1
  (cd $p && clean $b/python -m graphtraj.runtimes.claude.host configuration --project $p --claude $(command -v claude) --write >/dev/null) \
    && print -r -- "claude host configuration written: $p/.mcp.json (servers: $(tr -d '\n ' < $p/.mcp.json | grep -o '"mcpServers":{"[^"]*"' | cut -d'"' -f4))" \
    || { print "STOP: claude host configuration failed"; return 1; }
  clean $b/python -I $SD/../verify-common/claude_isolation.py settings $H $p >/dev/null 2>&1 \
    && print "Claude isolation settings: written" || print "Claude isolation settings: not written (project is outside the Harness; harmless)"
  mkdir -p $p/ws-551
  say "child roles (inline, no connection catalog), resolved by the Task-free driver without a model, each with
workspace $p/ws-551 (every child, all four Runtimes alike: the Pi driver refuses a Worktree containing the
project's .graphtraj/state, an existing isolation guard)"
  (cd $p && clean $b/python -I $SD/prep551.py roles $p $p/ws-551) | redact || FAILS+=(roles)
  say "probe Tasks: tasks discover + describe concept-clarification through $b/graphtraj-mcp (no host, no model)"
  (cd $p && clean $b/python -I $SD/prep551.py tasks $p $b/graphtraj-mcp $BASE/heading-$1.txt) || { FAILS+=(tasks-probe); return 1; }
}
gate() {  # $1 label: one one-line claude -p Main with the project's .mcp.json; its init must list graphtraj + agents
  local p=$(project $1) G=$OUT/gate-$1; mkdir -p $G
  (cd $p && clean $BOUND 180 claude -p --model $PARENT_MODEL --output-format stream-json --verbose --mcp-config $p/.mcp.json \
     --strict-mcp-config <<< 'Reply with one line: READY-551 and your exact model name. Use no tool.' > $G/gate.jsonl 2> $G/gate.err) \
     || print "claude rc=$?"
  clean $CONDA -I -c 'import json, sys
lines = []
for l in open(sys.argv[1], errors="replace"):
    try: lines.append(json.loads(l))
    except ValueError: pass
init = next((l for l in lines if l.get("subtype") == "init"), {}); res = next((l for l in lines if l.get("type") == "result"), {})
servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers", [])]
tools = [t for t in init.get("tools", []) if t.startswith("mcp__")]
source = str(init.get("apiKeySource"))
login = "none = no API key: Claude Code logged in with its OAuth (claude.ai subscription) login" if source == "none" else source + " = API key source"
print("parent model (init):", init.get("model"), "| login source (init apiKeySource):", login, "| answer (self-report):", str(res.get("result", ""))[:100].replace("\n", " "))
print("parent init mcp_servers:", servers, "| mcp tools:", tools)
# The GraphTraj host plugin (project .claude/skills/graphtraj-claude-host) verifies Main for agents create; an
# untrusted folder skips it (Main B run 1: plugin_warnings project-scope-suppressed-untrusted -> authority-denied).
warnings = init.get("plugin_warnings", [])
untrusted = [w for w in warnings if "untrusted" in json.dumps(w)]
plugins = init.get("plugins", [])
host = "graphtraj-claude-host" in json.dumps(plugins)
print("parent init plugin_warnings:", json.dumps(warnings)[:400])
print("parent init plugins:", json.dumps(plugins)[:400], "| graphtraj-claude-host loaded:", host)
ok = ("graphtraj", "connected") in servers and "mcp__graphtraj__agents" in tools and not untrusted and host
print("CHECK 551 Claude parent gate:", "PASS" if ok else "NOT PASSED" + (" (folder not trusted: run U)" if untrusted or not host else ""))
sys.exit(0 if ok else (3 if untrusted or not host else 1))' $G/gate.jsonl
  local rc=$?
  (( rc == 0 )) && return 0
  print -r -- "gate stderr: $(head -c 400 $G/gate.err)"
  return $rc
}
child_instruction() {
  print -r -- 'This is a scripted probe. Do not edit or create any file. Answer in English.
1. Without calling any tool, write one line "TOOLS-551: " followed by the exact names of every tool you can call, comma-separated, exactly as they were given to you.
2. Write one line "MCP-551: " followed by each MCP server you can use and its tools, or NONE.
3. If you have a GraphTraj tool named tasks (it may carry a prefix, such as mcp__graphtraj__tasks), call it with {"action": "discover"} and then with {"action": "describe", "feature": "concept-clarification"}. Write one line "TASKS-551: " followed by ok, or absent, or the exact error. Write one line "DESCRIBE-551: " followed by the manual_ref it returned, or the exact error.
4. If you got a manual_ref, read that file with your file-reading tool (not a shell) and write one line "READ-551: " followed by its first line that starts with #, or the exact error or refusal text. Otherwise write "READ-551: skipped".
5. Fetch https://example.com with your web tool (not a shell). Write one line "WEB-551: " followed by the page title, or the exact error or refusal text, or absent if you have no web tool.
Use no other tool. End your turn after these six lines.'
}
parent_prompt() {  # $1 runtime, $2 extra create arguments as JSON object members ("" for none)
  local child=$($CONDA -I -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$(child_instruction)")
  print -r -- "This is a scripted probe. Use only the MCP tool mcp__graphtraj__agents.
1. Call it with {\"action\": \"execute\", \"feature\": \"create\", \"arguments\": {\"runtime\": \"$1\", \"name\": \"probe-551-$1\"${2:+, $2}, \"instruction\": $child}}. Pass no other argument and do not change these. If create is refused, print one line CREATE-ERROR followed by the exact error, and stop.
2. Call it with {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": <the agent reference create returned>, \"timeout_seconds\": 300}}. Repeat the wait until the child's execution has ended, at most 4 times.
3. If a wait result shows a pending approval or input request of the child, call the requests feature for that agent once, print one line REQUEST-551 followed by the request's tool and text, answer it with the reply feature choosing deny (see describe reply), and wait again.
4. Finally print the line BEGIN-CHILD, then the child's final message exactly as returned, then the line END-CHILD. Do nothing else."
}
collect() {  # $1 project: project records changed since the marker, then the Codex child's rollout by its session id
  mkdir -p $D/records
  local f
  for f in $1/.graphtraj/**/*(N.,@); do
    [[ $f -nt $D/marker ]] || continue
    mkdir -p $D/records/${${f#$1/}:h}; cp -L $f $D/records/${f#$1/} 2>/dev/null
  done
  local ids=(${(u)${(f)"$(grep -rhoE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' $D/records/.graphtraj/swarm 2>/dev/null)"}}) id
  if [[ $2 == codex ]]; then
    mkdir -p $D/records/codex-rollouts
    for id in $ids; do for f in ${CODEX_HOME:-$HOME/.codex}/sessions/**/rollout-*${id}*.jsonl(N.); do
      cp $f $D/records/codex-rollouts/ && print -r -- "Codex child rollout copied (read only, by its id $id): $f"; done; done
  fi
  print -r -- "project records copied: $(find $D/records -type f | wc -l | tr -d ' ') files under $D/records"
}
probe() {  # $1 label, $2 runtime, $3 tag, $4 extra create arguments ("" for none)
  local p=$(project $1) rt=$2
  D=$OUT/$3-$rt-$(date +%Y%m%dT%H%M%S)-$$; mkdir -p $D; touch $D/marker
  local args="\"workspace\": \"$p/ws-551\"${4:+, $4}"
  print -r -- "label $1 | installation $(inst $1) | runtime $rt | create arguments besides runtime/name/instruction: $args" > $D/run.txt
  say "[$3 $rt] Claude Main ($PARENT_MODEL, claude -p in $p) creates one Task-free $rt child and waits (dialog: none). At most 25 min.
create arguments besides runtime/name/instruction: {$args} (workspace ws-551 for every child, all Runtimes alike)"
  parent_prompt $rt "$args" > $D/parent-prompt.txt
  local S=$(uuidgen | tr A-Z a-z); print -r -- $S > $D/parent-session.txt
  (cd $p && clean $BOUND 1500 claude -p --model $PARENT_MODEL --output-format stream-json --verbose \
     --mcp-config $p/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__agents --session-id $S \
     < $D/parent-prompt.txt > $D/parent.jsonl 2> $D/parent.err) || print "claude (parent) rc=$?"
  cp $p/.graphtraj/claude-host/host.log $D/host.log 2>/dev/null || true
  collect $p $rt
  clean $(inst $1)/python -I $SD/sum551.py $D $rt "$(cat $BASE/heading-$1.txt 2>/dev/null || print -- -)" | redact | tee $D/summary.txt
  local rc=$?
  print -r -- "evidence: $D (parent.jsonl, parent.err, records/, summary.txt)"
  return $rc
}
rt_list() { if [[ $1 == all ]]; then print claude codex pi dsh; elif [[ $1 == (claude|codex|pi|dsh) ]]; then print $1; else return 1; fi; }

[[ -d $H/.graphtraj || -n ${VERIFY551_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT

step_00() {
  say "[00] preflight (dialog: none). Each host prompt at most 120 s."
  print -r -- "script: zsh $ZSH_VERSION running $THIS | $(git --version)"
  print -r -- "claude $(claude --version 2>&1 | head -1) | codex $(codex --version 2>&1 | tail -1) | pi $(pi --version 2>&1 | tail -1) | dsh $(dsh --version 2>&1 | tail -1)"
  print -r -- "in-use installation (BEFORE): $(cd $BASE && $RT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "| graftling", m.version("graftling"))') at $RT"
  print -r -- "Worktree $WT at $(git -C $WT rev-parse --short HEAD) | BASE $BASE"
  local FAILS=()
  load_key || { print "NOTE: DEEPSEEK_API_KEY unset; pi and dsh cannot answer"; FAILS+=(DEEPSEEK_API_KEY); }
  pi_sandbox
  say "one-line prompts; each host's model is judged from its OWN record (the reply is only a self-report)"
  local ASK='Reply with one line: READY-551 and your exact model name. Use no tool.' R=$OUT/ready; mkdir -p $R
  # Claude: prompt on stdin (--mcp-config is variadic and would swallow a positional prompt).
  (cd $BASE && clean $BOUND 120 claude -p --model $PARENT_MODEL --output-format stream-json --verbose --strict-mcp-config \
     --mcp-config '{"mcpServers":{}}' <<< $ASK > $R/claude.jsonl 2> $R/claude.err) || print "claude rc=$?"
  clean $CONDA -I $SD/ready551.py claude $R/claude.jsonl $PARENT_MODEL || FAILS+=(READY-claude)
  (cd $BASE && clean $BOUND 120 codex exec --skip-git-repo-check -m $CODEX_MODEL $ASK < /dev/null > $R/codex.txt 2>&1) || print "codex rc=$?"
  clean $CONDA -I $SD/ready551.py codex $R/codex.txt $CODEX_MODEL || FAILS+=(READY-codex)
  (cd $BASE && clean $BOUND 120 pi --mode json --no-tools --no-session --provider $PI_PROVIDER --model $PI_MODEL $ASK < /dev/null 2>&1 | redact > $R/pi.jsonl) || print "pi rc=$?"
  clean $CONDA -I $SD/ready551.py pi $R/pi.jsonl $PI_MODEL $PI_PROVIDER || FAILS+=(READY-pi)
  (cd $BASE && clean $BOUND 120 dsh --profile headless --permission-mode read-only --json $ASK < /dev/null 2>&1 | redact > $R/dsh.jsonl) || print "dsh rc=$?"
  # DSH's --json stream names no model: read DSH's own session log by the stream's sessionId (read only, copied to
  # $R/dsh-session), else its resolved profile (--dump-config) as a documented limit.
  (cd $BASE && clean $BOUND 60 dsh --profile headless --dump-config < /dev/null > $R/dsh-config.yml 2>&1) || print "dsh --dump-config rc=$?"
  clean $CONDA -I $SD/ready551.py dsh $R/dsh.jsonl $PI_MODEL - $DSH_SESSIONS $R/dsh-session $R/dsh-config.yml || FAILS+=(READY-dsh)
  print -r -- "raw host outputs: $R/{claude.jsonl,codex.txt,pi.jsonl,dsh.jsonl,dsh-config.yml,dsh-session/}"
  build_project before || FAILS+=(build)
  say "Claude parent gate in $(project before)"
  gate before; local g=$?
  (( g == 3 )) && FAILS+=("gate: folder not trusted or graphtraj-claude-host not loaded; run zsh $THIS U before, then 00 again")
  (( g != 0 && g != 3 )) && FAILS+=(gate)
  print "READY when: 'READY-551 <host>: PASS' x4 (actual model from each host's record: claude $PARENT_MODEL, codex $CODEX_MODEL, pi $PI_PROVIDER/$PI_MODEL, dsh $PI_MODEL), 'CHECK 551 role <rt>: PASS' x4, 'CHECK 551 tasks probe: PASS', 'CHECK 551 Claude parent gate: PASS'."
  if (( $#FAILS )); then print -r -- "
NOT READY: ${FAILS[*]}"; return 1; fi
  print "READY: all checks passed"
  next "zsh $THIS B all"
}

step_U() {
  local label=${ARG:-before}
  say "[U] USER, required once for each new project path ($(project $label)). Plain macOS Terminal:"
  print -r -- "  cd $(project $label) && claude"
  print "Dialog 1: 'Do you trust the files in this folder?' naming that project: choose 'Yes, proceed'.
If Claude then shows an MCP server dialog for 'graphtraj' (this project's .mcp.json): choose to use it.
Then type /exit. Send no message."
  [[ $label == before ]] && next "zsh $THIS 00" || next "zsh $THIS A0"
}

step_B() {
  local list; list=($(rt_list ${ARG:-all})) || { print "usage: B <claude|codex|pi|dsh|all>"; return 2; }
  [[ -f $BASE/heading-before.txt ]] || { print "STOP: run 00 first"; return 1; }
  load_key || print "NOTE: DEEPSEEK_API_KEY unset; the pi and dsh children cannot reach their model"
  pi_sandbox
  say "Claude parent gate again (no paid child run unless it passes)"
  gate before; local g=$?
  if (( g != 0 )); then
    (( g == 3 )) && print -r -- "NOT READY: folder not trusted or graphtraj-claude-host not loaded: zsh $THIS U before, then B again" \
                 || print -r -- "NOT READY: parent gate failed (above)"
    return 1
  fi
  local rt FAILS=()
  for rt in $list; do probe before $rt B "" || FAILS+=(B-$rt); done
  print "Read per Runtime: 'RECORD init' / 'RECORD launch flags' (what the child really got, from its own records),
'self-report TOOLS-551/MCP-551' (the model's own list), 'RECORD tasks calls' and 'RECORD manual guide.md reads',
'a tool result holds the manual heading: YES/NO'. A missing tasks tool shows TASKS-551: absent and no tasks call."
  if (( $#FAILS )); then print -r -- "
NOT COMPLETE: ${FAILS[*]} (no created child or no child final message; see that Runtime's summary above)"; return 1; fi
  print "COMPLETE: every child was created and ended with a final message"
  next "Leader: read $OUT/B-*/summary.txt"
}

case $STEP in
  00) step_00 ;;
  U) step_U ;;
  B) step_B ;;
  *) print "usage: zsh $THIS <00|U|B <claude|codex|pi|dsh|all>>"; return 2 ;;
esac
