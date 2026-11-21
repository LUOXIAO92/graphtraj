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
#   A0  candidate: wheels of GraphTraj $GT (this Worktree HEAD) + graftling $GL (551 branch of <Worktree>/.graftling-551.git)
#       into BASE/venv-after; dependency direction (graftling wheel alone in a clean venv: no GraphTraj requirement,
#       GraphTraj absent, every graftling module imports); project-after (needs its own U after), roles, tasks, gate.
#   A   per Runtime, headless (dialog: none): plain, one manual deny (claude WebSearch, codex web_search, pi bash,
#       dsh tool-web); Codex beyond web_search and an undefined MCP deny; DSH beyond tool-plugin-market.
#   AU  USER: `AU <claude|pi> <deny|allow>`: an interactive Claude Main parent shows the child's beyond-host request
#       and asks you; you type deny/allow and it answers through agents reply. AC <claude|pi> summarizes (read only).
#   G   both full suites in the background (GraphTraj 6 shards with graftling $GL; graftling's own suite). GR reads.
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
CLAUDE_PROJECTS=${VERIFY551_CLAUDE_PROJECTS:-$HOME/.claude/projects}   # AC copies only the AU parent's transcript, by id
# AFTER = the candidate: GraphTraj $GT (this Worktree) + graftling $GL (the 551 branch of the shared clone), as wheels.
GLREPO=${VERIFY551_GLREPO:-$WT/.graftling-551.git}; GLBRANCH=agent/551-task-free-children-reach-tasks-methods
GT=${VERIFY551_GT:-$(git -C $WT rev-parse HEAD)}
GL=${VERIFY551_GL:-$(git --git-dir=$GLREPO rev-parse $GLBRANCH 2>/dev/null || print -- missing)}
GLBASE=6794ce02b6210ec88837437affb8d7b525612804                 # graftling dev the branch starts from
T=${VERIFY551_T:-$H/tmp/551}                                     # G's venvs (Task: test directory Harness tmp/551)
RTSP=$RT/lib/python3.13/site-packages                            # click, yaml, websockets copied from here (read only)
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN528=$H/.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/G-8267f9e5-20261119T235550/suite.txt
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
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
child_instruction() {  # $1 runtime, $2 optional extra step (AU's beyond-host Pi tool)
  # Codex has no file-reading tool (Main's A run: 'READ-551: No file-reading tool is available'): it reads with its shell.
  local how='with your file-reading tool (not a shell)'
  [[ ${1:-} == codex ]] && how='with your shell (Codex has no separate file-reading tool), printing only its first line that starts with #'
  print -r -- "${2:+Before anything else: $2
}"'This is a scripted probe. Do not edit or create any file. Answer in English.
1. Without calling any tool, write one line "TOOLS-551: " followed by the exact names of every tool you can call, comma-separated, exactly as they were given to you.
2. Write one line "MCP-551: " followed by each MCP server you can use and its tools, or NONE.
3. If you have a GraphTraj tool named tasks (it may carry a prefix, such as mcp__graphtraj__tasks), call it with {"action": "discover"} and then with {"action": "describe", "feature": "concept-clarification"}. Write one line "TASKS-551: " followed by ok, or absent, or the exact error. Write one line "DESCRIBE-551: " followed by the manual_ref it returned, or the exact error.
4. If you got a manual_ref, read that file '"$how"' and write one line "READ-551: " followed by its first line that starts with #, or the exact error or refusal text. Otherwise write "READ-551: skipped".
5. Search or fetch https://example.com with your web tool (web search or web fetch; not a shell). Write one line "WEB-551: " followed by the tool you used and the page title, or the exact error or refusal text, or absent if you have no web tool.
Use no other tool. End your turn after these six lines.'
}
parent_prompt() {  # $1 runtime, $2 extra create arguments as JSON members ("" none), $3 'user' = ask the user, $4 extra child step
  local child=$($CONDA -I -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$(child_instruction $1 "${4:-}")")
  local answer='answer it with the reply feature choosing deny (see describe reply), and wait again.'
  [[ ${3:-} == user ]] && answer='then ask me, the user, exactly: "REQUEST-551: allow or deny?" and wait for my answer. Answer the request with the reply feature (see describe reply) choosing exactly what I said, print one line REPLY-551 followed by the reply you sent, and wait again. Never decide it yourself.'
  print -r -- "This is a scripted probe. Use only the MCP tool mcp__graphtraj__agents.
1. Call it with {\"action\": \"execute\", \"feature\": \"create\", \"arguments\": {\"runtime\": \"$1\", \"name\": \"probe-551-$1\"${2:+, $2}, \"instruction\": $child}}. Pass no other argument and do not change these. If create is refused, print one line CREATE-ERROR followed by the exact error, and stop.
2. Call it with {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": <the agent reference create returned>, \"timeout_seconds\": 300}}. Repeat the wait until the child's execution has ended, at most 6 times.
3. If a wait result shows a pending approval or input request of the child, call the requests feature for that agent once, print one line REQUEST-551 followed by the request's tool and text, $answer
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
  print -r -- "host versions: $HOSTV" >> $D/run.txt
  say "[$3 $rt] Claude Main ($PARENT_MODEL, claude -p in $p) creates one Task-free $rt child and waits (dialog: none). At most 25 min.
create arguments besides runtime/name/instruction: {$args} (workspace ws-551 for every child, all Runtimes alike)
host versions: $HOSTV"
  parent_prompt $rt "$args" > $D/parent-prompt.txt
  local S=$(uuidgen | tr A-Z a-z); print -r -- $S > $D/parent-session.txt
  (cd $p && clean $BOUND 1500 claude -p --model $PARENT_MODEL --output-format stream-json --verbose \
     --mcp-config $p/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__agents --session-id $S \
     < $D/parent-prompt.txt > $D/parent.jsonl 2> $D/parent.err) || print "claude (parent) rc=$?"
  cp $p/.graphtraj/claude-host/host.log $D/host.log 2>/dev/null || true
  collect $p $rt
  clean $(inst $1)/python -I $SD/sum551.py $D $rt "$(cat $BASE/heading-$1.txt 2>/dev/null || print -- -)" ${5:+--expect-refusal} \
    | redact | tee $D/summary.txt
  local rc=$?
  print -r -- "evidence: $D (parent.jsonl, parent.err, records/, summary.txt)"
  return $rc
}
# The host versions every A/AU run names (the user updated DSH 0.2.2-alpha.2 -> alpha.3 at ~22:47; Worldline
# 20261121T224836.947774+0900). Read once per step into HOSTV and DSHV.
host_versions() {
  DSHV=$(dsh --version 2>&1 | tail -1)
  HOSTV="claude $(claude --version 2>&1 | head -1) | codex $(codex --version 2>&1 | tail -1) | pi $(pi --version 2>&1 | tail -1) | dsh $DSHV"
  print -r -- "host versions for this step: $HOSTV"
}
HOSTV=unknown; DSHV=unknown
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
  print "READY when: 'READY-551 <host>: PASS' x4 (actual model from each host's record: claude $PARENT_MODEL, codex $CODEX_MODEL, pi $PI_PROVIDER/$PI_MODEL, dsh $PI_MODEL), 'CHECK 551 role <role>: PASS' x5 (claude, codex, pi, dsh, claude_ask), 'CHECK 551 tasks probe: PASS', 'CHECK 551 Claude parent gate: PASS'."
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

# ---------------------------------------------------------------- AFTER (candidate) and the full suites
deps() {  # $1 venv, $2...: packages copied from production's site-packages (read only)
  local v=$1; shift
  local SP=$($v/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') n
  for n in "$@"; do cp -Rp $RTSP/$n $RTSP/$n-*.dist-info(N) $SP/ 2>/dev/null; done
  [[ " $* " == *" yaml "* ]] && cp -Rp $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $SP/
  return 0
}
gitr() {  # $1 a bare/separate git dir (has objects/) or a work tree, then git arguments
  local r=$1; shift
  if [[ -d $r/objects ]]; then git --git-dir=$r "$@"; else git -C $r "$@"; fi
}
wheel() {  # $1 git dir or work tree, $2 commit, $3 subdirectory ('.' = all), $4 output directory: from git archive only
  local src=$4/src-${2[1,10]}; rm -rf $src; mkdir -p $src $4
  gitr $1 archive $2 $3 | tar -x -C $src || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $4 $src/$3 >/dev/null
}
one() { local found=($1/$~2(N)); (( $#found == 1 )) && print -r -- $found || { print -r -- "STOP: expected one $2 in $1, found ${#found}" >&2; return 1; }; }

step_A0() {
  local FAILS=()
  say "[A0] candidate installation (dialog: none): GraphTraj $GT + graftling $GL (branch $GLBRANCH of $GLREPO, base $GLBASE)"
  [[ $GL != missing ]] || { print "STOP: no graftling branch $GLBRANCH in $GLREPO"; return 1; }
  git --git-dir=$GLREPO merge-base --is-ancestor $GLBASE $GL && print "graftling $GL descends from dev $GLBASE" \
    || FAILS+=(graftling-base)
  print -r -- "graftling commits since dev: $(git --git-dir=$GLREPO log --oneline $GLBASE..$GL | tr '\n' ';')"
  print -r -- "GraphTraj commits since dev f754d3a9: $(git -C $WT log --oneline f754d3a9..$GT | wc -l | tr -d ' ')"
  local V=$BASE/venv-after W=$BASE/wheels-after
  if [[ ! -f $V/installed || $(<$V/installed) != "$GT $GL" ]]; then
    rm -rf $W; mkdir -p $W
    wheel $GLREPO $GL src/graftling $W && wheel $WT $GT . $W || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(one $W 'graftling-*.whl') && hw=$(one $W 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V && deps $V click yaml websockets && $V/bin/python -m pip install -q --disable-pip-version-check \
      --no-cache-dir --no-index --no-deps $gw $hw || { print "STOP: the candidate venv install failed"; return 1; }
    print -r -- "$GT $GL" > $V/installed
  else print -r -- "venv $V already holds $GT + $GL"; fi
  (cd $BASE && $V/bin/python -I -c 'import importlib.metadata as m, graftling, graphtraj, sysconfig
print("candidate venv: graphtraj", m.version("graphtraj"), "from", graphtraj.__file__, "| graftling", m.version("graftling"), "from", graftling.__file__)
print("manuals in the candidate:", sysconfig.get_path("data") + "/share/graphtraj/manuals")')
  say "dependency direction (required result 4): graftling's wheel alone in a clean venv, GraphTraj NOT installed"
  local VG=$BASE/venv-graftling-only
  rm -rf $VG; $CONDA -m venv $VG && deps $VG yaml websockets \
    && $VG/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(one $BASE/wheels-after 'graftling-*.whl') \
    || { FAILS+=(dependency-venv); }
  (cd $BASE && $VG/bin/python -I -c 'import importlib, importlib.metadata as m, importlib.util, pkgutil, sys, graftling
requires = m.requires("graftling") or []
print("graftling wheel Requires-Dist:", requires)
print("graphtraj installed in this venv:", importlib.util.find_spec("graphtraj") is not None)
failed = {}
names = [i.name for i in pkgutil.walk_packages(graftling.__path__, "graftling.")]
for name in names:
    try: importlib.import_module(name)
    except Exception as error: failed[name] = f"{type(error).__name__}: {error}"
print("graftling modules imported:", len(names), "| failed:", failed or "none", "| graphtraj modules loaded:", [n for n in sys.modules if n.split(".")[0] == "graphtraj"])
ok = not any(r.lower().startswith("graphtraj") for r in requires) and importlib.util.find_spec("graphtraj") is None and not failed
print("CHECK 551 dependency direction:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)') || FAILS+=(dependency-direction)
  # The roles need the Pi sandbox (srt) and the DeepSeek key exactly as in 00; prep551 rewrites roles.yml every run.
  load_key || FAILS+=(DEEPSEEK_API_KEY)
  pi_sandbox
  build_project after || FAILS+=(build)
  say "Claude parent gate in $(project after)"
  gate after; local g=$?
  (( g == 3 )) && FAILS+=("gate: folder not trusted or graphtraj-claude-host not loaded; run zsh $THIS U after, then A0 again")
  (( g != 0 && g != 3 )) && FAILS+=(gate)
  if (( $#FAILS )); then print -r -- "
NOT READY: ${FAILS[*]}"; return 1; fi
  print "READY: candidate installed, dependency direction PASS, roles x5, tasks probe and gate PASS"
  next "zsh $THIS A all"
}

# A's headless probes per Runtime: plain, one manual deny, and (Codex, DSH) the beyond-host requests that have no
# dialog. 'expect' = the create refusal code that is the correct outcome, or '-' for a created child.
# Fields: case | create tool arguments | expect | deny check on the summary's 'RECORD TOOLSET' line.
# The inherited Claude tools have WebSearch but no WebFetch (Main's A run), so Claude's deny is WebSearch.
# Codex web_search is the code-mode tool web__run in the rollout's additional_tools.
a_cases() {
  case $1 in
    claude) print -l -- 'plain||-|' 'deny|"disallowed_tools": ["WebSearch"]|-|absent:WebSearch' ;;
    codex)  print -l -- 'plain||-|' 'deny|"disallowed_tools": ["web_search"]|-|absent:web__run' \
                        'beyond|"tools": ["web_search"]|authorization-required-or-off|' \
                        'undefined-mcp|"disallowed_tools": ["mcp__undefined551__x"]|unavailable|' ;;
    pi)     print -l -- 'plain||-|' 'deny|"disallowed_tools": ["bash"]|-|has:--exclude-tools bash' ;;
    dsh)    print -l -- 'plain||-|' 'deny|"disallowed_tools": ["tool-web"]|-|has:tool-web=disabled' \
                        'beyond|"tools": ["tool-fs", "tool-plugin-market"]|authorization-required|' ;;
  esac
}
deny_check() {  # $1 check spec, $2 summary: the tool list from the child's own record proves the deny
  [[ -z $1 ]] && return 0
  local toolset=$(grep -m1 'RECORD TOOLSET' $2)
  [[ -n $toolset && $toolset != *'NOT IN RECORDS'* ]] || { print -r -- "no tool list in the child's records"; return 1; }
  case $1 in
    absent:*) [[ ", ${toolset#*: }," != *", ${1#absent:},"* ]] && print -r -- "${1#absent:} absent from the record's tool list" \
                || { print -r -- "${1#absent:} STILL IN the record's tool list"; return 1; } ;;
    has:*) [[ $toolset == *"${1#has:}"* ]] && print -r -- "record shows ${1#has:}" || { print -r -- "record lacks ${1#has:}"; return 1; } ;;
  esac
}
a_verdict() {  # $1 expect, $2 deny check, $3 probe rc; uses $D/summary.txt; prints the verdict
  local s=$D/summary.txt
  # The create's own refusal code, only from the parent's create result line.
  local code=$(grep -m1 'parent create result' $s | grep -o -m1 -E 'authorization-required|unavailable' || true)
  local created=0; grep -q -E 'CHECK 551 [a-z]+ child run: COMPLETE$' $s && created=1
  local check
  case $1 in
    -) if (( $3 != 0 )); then print -r -- "NOT COMPLETE ($(grep -m1 'RECORD execution outcome' $s | sed 's/.*): //'))"
       elif check=$(deny_check "$2" $s); then print -r -- "OK${2:+ ($check)}"
       else print -r -- "DENY NOT SHOWN ($check)"; fi ;;
    authorization-required-or-off)
       if [[ $code == authorization-required ]]; then print "OK (refused authorization-required)"
       elif (( created )); then print "CHILD CREATED: the host had web search on, so tools [web_search] is not beyond it; read WEB-551 and RECORD TOOLSET"
       else print -r -- "UNEXPECTED (${code:-no create code})"; fi ;;
    *) [[ $code == $1 ]] && print -r -- "OK (refused $1)" || print -r -- "UNEXPECTED (expected $1, got ${code:-a created child})" ;;
  esac
}
step_A() {
  local list; list=($(rt_list ${ARG:-all})) || { print "usage: A <claude|codex|pi|dsh|all>"; return 2; }
  [[ -f $BASE/venv-after/installed && -f $BASE/heading-after.txt ]] || { print "STOP: run A0 first"; return 1; }
  load_key || print "NOTE: DEEPSEEK_API_KEY unset; the pi and dsh children cannot reach their model"
  pi_sandbox
  host_versions
  say "Claude parent gate again in $(project after) (no paid child run unless it passes)"
  gate after; local g=$?
  if (( g != 0 )); then
    (( g == 3 )) && print -r -- "NOT READY: folder not trusted or graphtraj-claude-host not loaded: zsh $THIS U after, then A again" \
                 || print -r -- "NOT READY: parent gate failed (above)"
    return 1
  fi
  # Declared once, outside the loops: zsh prints an existing local that is declared again.
  local rt line name args expect check verdict refusal rc FAILS=() RESULTS=() fields
  for rt in $list; do
    for line in ${(f)"$(a_cases $rt)"}; do
      fields=("${(@s:|:)line}"); name=$fields[1]; args=$fields[2]; expect=$fields[3]; check=$fields[4]
      refusal=; [[ $expect == - ]] || refusal=yes
      probe after $rt A-$name "$args" $refusal; rc=$?
      verdict=$(a_verdict $expect "$check" $rc)
      if [[ $rt == dsh && $name == plain && $verdict != OK* ]]; then
        # Main's A run: DSH plain ended RUNTIME_CONNECTION_CLOSED after its turn completed; re-run once, keep both.
        RESULTS+=("A $rt $name {no tool arguments} (first run): $verdict | DSH $DSHV | $D/summary.txt")
        print -r -- "DSH plain did not complete ($verdict); re-running it once"
        probe after $rt A-$name-rerun "$args"; rc=$?
        verdict=$(a_verdict $expect "$check" $rc)
        name="$name (re-run)"
      fi
      [[ $rt == codex && $name == deny ]] && verdict+=" | note: judged by the tool list only; the child may still reach web pages through other host MCP tools (e.g. mcp__playwright), which this deny does not name"
      RESULTS+=("A $rt $name {${args:-no tool arguments}}: $verdict | DSH $DSHV | $D/summary.txt")
      [[ $verdict == (OK*|CHILD*) ]] || FAILS+=(A-$rt-${name%% *})
    done
  done
  say "A results"
  print -l -- $RESULTS
  if (( $#FAILS )); then print -r -- "
NOT COMPLETE: ${FAILS[*]}"; return 1; fi
  print "COMPLETE"
  next "zsh $THIS AU claude deny   (USER: the beyond-host request answered by you; then AC claude)"
}

# AX: the user's rule 'an allow/deny entry the child's Runtime does not know is refused or reported, never
# ignored' (551), one headless case per Runtime in project-after (dialog: none). Fields: create tool arguments |
# expected: 'report:<entry>' (child created, agents status tool_check lists it in tools_not_offered) or
# 'refuse:<entry>' (create refused `unavailable` naming it; Codex names the unknown server, as in A's
# undefined-mcp case: "MCP servers ['undefined551'] are not in the captured Codex settings ...").
ax_cases() {
  print -l -- 'claude|"tools": ["Read", "NoSuchTool551"]|report:NoSuchTool551' \
              'pi|"tools": ["read", "nosuchtool551"]|refuse:nosuchtool551' \
              'codex|"disallowed_tools": ["mcp__nosuchserver551__x"]|refuse:nosuchserver551' \
              'dsh|"tools": ["tool-nosuch551"]|refuse:tool-nosuch551'
}
step_AX() {
  [[ -f $BASE/venv-after/installed && -f $BASE/heading-after.txt ]] || { print "STOP: run A0 first"; return 1; }
  load_key || print "NOTE: DEEPSEEK_API_KEY unset; the pi and dsh children cannot reach their model"
  pi_sandbox
  host_versions
  say "[AX] unknown manual tool entries per Runtime are refused or reported, never ignored (dialog: none)"
  gate after; local g=$?
  (( g == 0 )) || { print -r -- "NOT READY: parent gate failed (above; U after if untrusted)"; return 1; }
  local line rt args expect entry kind verdict fields FAILS=() RESULTS=() check created
  for line in ${(f)"$(ax_cases)"}; do
    fields=("${(@s:|:)line}"); rt=$fields[1]; args=$fields[2]; expect=$fields[3]
    kind=${expect%%:*}; entry=${expect#*:}
    probe after $rt AX "$args" ${${kind:#report}:+yes}
    created=$(grep -m1 'parent create result' $D/summary.txt)
    if [[ $kind == refuse ]]; then
      [[ $created == *unavailable* && $created == *$entry* ]] && verdict="OK (create refused unavailable naming $entry)" \
        || verdict="NOT OK (expected create refused unavailable naming $entry; got: ${created[1,200]})"
    else
      check=$(grep -m1 'RECORD tool_check' $D/summary.txt)
      if [[ $check == *tools_not_offered* && $check == *$entry* ]]; then verdict="OK (child created; status tool_check reports $entry: ${check#*: })"
      else verdict="NOT OK (expected tool_check.tools_not_offered to list $entry; got: ${check:-no tool_check} | create: ${created[1,120]})"; fi
    fi
    RESULTS+=("AX $rt {$args}: $verdict | DSH $DSHV | $D/summary.txt")
    [[ $verdict == OK* ]] || FAILS+=(AX-$rt)
  done
  say "AX results"
  print -l -- $RESULTS
  if (( $#FAILS )); then print -r -- "
NOT COMPLETE: ${FAILS[*]}"; return 1; fi
  print "COMPLETE"
}

# AU: the beyond-host request reaches the USER. An interactive Claude Main parent creates the child; the child's
# request (Claude: WebSearch, not pre-allowed -> can_use_tool; Pi: a built-in the host's defaultTools lacks ->
# Pi's confirm dialog) is retained for the parent, which shows it and asks you; it relays your answer via agents reply.
step_AU() {
  local rt=${ARG:-} answer=${3:-deny}
  [[ $rt == (claude|pi) && $answer == (allow|deny) ]] || { print "usage: AU <claude|pi> <deny|allow>"; return 2; }
  # Claude: WebSearch (the inherited host tools have no WebFetch, Main's A run).
  local p=$(project after) extra="" args="\"workspace\": \"$(project after)/ws-551\"" tool=WebSearch mode=-
  if [[ $rt == claude ]]; then
    # Auto mode's classifier may decide WebSearch itself; role claude_ask runs the child in Claude's default mode.
    args+=", \"configuration\": \"claude_ask\""
    mode=$(cd $p && clean $BASE/venv-after/bin/python -I -c 'import sys
from pathlib import Path
from graftling import Caller
from graphtraj.execution.agent_driver import AdapterDriver
p = Path(sys.argv[1])
r = AdapterDriver(p, p).prepare("claude", Caller("verify-551", None, "probe-551", "claude"), configuration="claude_ask", workspace=p / "ws-551")
print(r["adapter_request"].get("permission_mode"))' $p 2>&1 | tail -1)
    print -r -- "Claude child role claude_ask: resolved permission_mode $mode (expected default)"
    [[ $mode == default ]] || { print "STOP: the child would not run in Claude's default permission mode"; return 1; }
  fi
  if [[ $rt == pi ]]; then
    load_key || { print "STOP: DEEPSEEK_API_KEY unset"; return 1; }
    pi_sandbox
    tool=$(cd $BASE && $BASE/venv-after/bin/python -I -c 'import os, sys
from pathlib import Path
from graftling.pi.execution import host_default_tools
host = host_default_tools(Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi/agent"))
print(next((t for t in ("grep", "find", "ls") if t not in host), ""))')
    [[ -n $tool ]] || { print "STOP: the host Pi already enables grep, find and ls; no built-in is beyond it"; return 1; }
    args+=", \"tools\": [\"read\", \"$tool\"]"
    extra="use your $tool tool once on your working directory (any harmless argument). Write one line \"BEYOND-551: \" followed by its result or the exact error or refusal."
    print -r -- "Pi beyond-host tool: $tool (not in the host Pi's defaultTools)"
  fi
  D=$OUT/AU-$rt-$answer-$(date +%Y%m%dT%H%M%S)-$$; mkdir -p $D; touch $D/marker
  parent_prompt $rt "$args" user "$extra" > $D/parent-prompt.txt
  local S=$(uuidgen | tr A-Z a-z); print -r -- $S > $D/parent-session.txt
  print -r -- "$rt $answer $p $tool $mode" > $D/run.txt
  host_versions; print -r -- "host versions: $HOSTV" > $D/hosts.txt
  say "[AU $rt] USER, in THIS terminal: an interactive Claude Main ($PARENT_MODEL) in $p.
Dialog: none of Claude Code itself is expected (project trusted in U; the parent's agents calls are pre-allowed).
What you type: when Claude prints 'REQUEST-551 ...' and asks 'REQUEST-551: allow or deny?', type exactly: $answer
That request is the child's beyond-host ask: $([[ $rt == claude ]] && print "Claude Code's can_use_tool for WebSearch (child permission mode $mode)" || print "Pi's confirm dialog 'agents: allow a tool beyond the host settings' for $tool"), retained for the parent.
If no REQUEST-551 appears, type nothing; AC will report NO REQUEST honestly.
The child's tasks calls raise NO request (user decision 551: tasks is allowed like agents unless disallowed);
if a REQUEST-551 names a tasks tool, answer it as asked anyway: AC counts it as a FAIL.
When Claude has printed END-CHILD, type /exit."
  # --mcp-config and --allowedTools are variadic: the rule list is one argument and `--` ends the options,
  # so the prompt is never read as their value (Main's AU run 1 on f8c39a95).
  (cd $p && clean claude --model $PARENT_MODEL --session-id $S \
     --mcp-config $p/.mcp.json --strict-mcp-config --allowedTools 'mcp__graphtraj__agents' \
     -- "$(<$D/parent-prompt.txt)") || print "claude exit $?"
  next "zsh $THIS AC $rt"
}
step_AC() {  # read only: the newest AU run of $ARG
  local rt=${ARG:-}; [[ $rt == (claude|pi) ]] || { print "usage: AC <claude|pi>"; return 2; }
  D=($OUT/AU-$rt-*(N/om[1])); D=${D[1]:-}; [[ -n $D ]] || { print "STOP: no AU $rt run"; return 1; }
  local S=$(<$D/parent-session.txt) f run=(${=$(<$D/run.txt)})
  for f in $CLAUDE_PROJECTS/*/$S.jsonl(N.); do cp $f $D/parent.jsonl && print -r -- "parent transcript (read only, by its session id): $f"; done
  [[ -f $D/parent.jsonl ]] || print "NOTE: no Claude transcript named $S.jsonl"
  collect $(project after) $rt
  # run.txt: runtime, the user's instructed answer, project, beyond-host tool, child permission mode
  clean $BASE/venv-after/bin/python -I $SD/sum551.py $D $rt "$(cat $BASE/heading-after.txt 2>/dev/null || print -- -)" \
    ${run[4]} ${run[5]} | redact | tee $D/summary.txt
  local rc=$?
  print -r -- "$(cat $D/hosts.txt 2>/dev/null || print 'host versions: not recorded (AU before this field)')"
  print -r -- "the step told the user to answer: ${run[2]} | parent REQUEST/REPLY lines:"
  grep -ho 'REQUEST-551[^"\\]*\|REPLY-551[^"\\]*' $D/parent.jsonl 2>/dev/null | sort -u | head -6
  (( rc == 0 )) || { print "NOT COMPLETE: no created child or no final message in this AU run (above)"; return 1; }
  grep -q '^AU CLASS: REQUEST reached the user' $D/summary.txt \
    && print "beyond-host evidence: YES (the request reached the user and the answer was relayed)" \
    || print "beyond-host evidence: NO (see AU CLASS above; not counted)"
  grep -q '^AU tasks calls raised requests: 0 ' $D/summary.txt \
    || { print "NOT COMPLETE: a tasks call raised a request (user decision 551: tasks needs none; see above)"; return 1; }
  if [[ $rt == pi ]]; then
    # AU pi creates the child with a `tools` list: the available set must keep the owner's own entries
    # (Main's AU pi run on f8c39a95: --tools read,grep left the child with no MCP, TASKS-551 absent).
    local ok=$(grep -c -E 'self-report TASKS-551: TASKS-551: ok' $D/summary.txt) listed
    listed=$(grep -m1 'RECORD child MCP server name' $D/summary.txt | grep -o 'mcp__graphtraj__tasks' | head -1)
    local argv=$(grep -m1 'RECORD TOOLSET' $D/summary.txt | sed 's/.*): //')
    print -r -- "tools-list child keeps the owner entries: TASKS-551 ok: $( (( ok )) && print YES || print NO) | mcp__graphtraj__tasks in its record: $([[ -n $listed ]] && print YES || print NO) | launch: $argv"
    (( ok )) && [[ -n $listed ]] || { print "NOT COMPLETE: the child's available set dropped the owner's tasks entry"; return 1; }
  fi
  next "zsh $THIS AU $rt $([[ ${run[2]} == deny ]] && print allow || print deny)   (the other answer), then AC $rt; or G"
}

check_tmp() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  print -r -- "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
g_venv() {  # G's venv: conda --system-site-packages + production click/yaml/websockets + graftling $GL wheel + this Worktree editable
  V=$T/venv-g-${GL[1,8]}
  if [[ -x $V/bin/python && -f $V/installed && $(<$V/installed) == "$GL $WT" ]]; then print -r -- "reusing $V"; return 0; fi
  rm -rf $V $T/wheels-g; mkdir -p $T/wheels-g
  wheel $GLREPO $GL src/graftling $T/wheels-g || return 1   # never the working tree
  $CONDA -m venv --system-site-packages $V && deps $V click yaml websockets || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(one $T/wheels-g 'graftling-*.whl') || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  print -r -- "$GL $WT" > $V/installed
}
step_G() {
  say "[G] GraphTraj full suite of this Worktree ($(git -C $WT rev-parse --short HEAD); 6 shards, background) with graftling $GL,
then graftling's own suite at $GL (git archive, editable). Dialog: none. Run nothing else meanwhile."
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  [[ $GL != missing ]] || { print "STOP: no graftling branch"; return 1; }
  check_tmp || return 1
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print -r -- "STOP: another test run is running: $others"; return 1; }
  mkdir -p $T; local V; g_venv || { print "STOP: G venv failed"; return 1; }
  local RUNTMP=${PYTEST_TMP:A}/verify-551-G-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-${GL[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  local GS=$T/graftling-src-${GL[1,8]}
  rm -rf $GS; mkdir -p $GS; gitr $GLREPO archive $GL | tar -x -C $GS || return 1
  local GV=$T/venv-gl-suite-${GL[1,8]}
  rm -rf $GV; $CONDA -m venv --system-site-packages $GV && deps $GV click yaml websockets \
    && $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $GS/src/graftling 2>&1 | grep -vi cache
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("G venv: graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') | tee $R/run.txt
  (cd $RUNTMP && $GV/bin/python -I -c 'import graftling; print("graftling suite venv: graftling", graftling.__file__)') | tee -a $R/run.txt
  print -r -- "candidate: GraphTraj $(git -C $WT rev-parse HEAD) | graftling $GL | pytest temp root $RUNTMP (TMPDIR=$PYTEST_TMP)" | tee -a $R/run.txt
  if [[ -n ${VERIFY551_TESTS:-} ]]; then
    print -r -- "REHEARSAL: GraphTraj tests limited to $VERIFY551_TESTS; graftling tests limited to ${VERIFY551_GL_TESTS:-tests/test_no_graphtraj_dependency.py} (same venvs, temp root, exit files)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY551_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt
     cd $GS && TMPDIR=$RUNTMP $GV/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY551_GL_TESTS:-tests/test_no_graphtraj_dependency.py} > $R/graftling-suite.txt 2>&1; print "exit=$?" >> $R/graftling-suite.txt) &!
  else
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt
     cd $GS && TMPDIR=$RUNTMP $GV/bin/python -m pytest -p no:cacheprovider -q -rfE > $R/graftling-suite.txt 2>&1; print "exit=$?" >> $R/graftling-suite.txt) &!
  fi
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T): $R/suite.txt then $R/graftling-suite.txt (each ends with 'exit=N')"
  next "zsh $THIS GR   (after both files end with exit=; ~30 min)"
}
classify() {  # FAILED/ERROR lines of files $@ as known (528's accepted G, 516) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $KNOWN528 2>/dev/null; then print -r -- "known (528 accepted G): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}
step_GR() {
  say "[GR] read only: newest G; FAILED/ERROR lines classed known (528 accepted G, 516) or NEW. Dialog: none."
  local g=$(cat $OUT/G-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 1; }
  cat $g/run.txt
  print -r -- "---- GraphTraj $g/suite.txt"; tail -4 $g/suite.txt; classify $g/suite.txt $g/shards/*(N.)
  print -r -- "---- graftling $g/graftling-suite.txt"; tail -3 $g/graftling-suite.txt 2>/dev/null; classify $g/graftling-suite.txt
  local done=1; grep -q '^exit=' $g/suite.txt && grep -q '^exit=' $g/graftling-suite.txt 2>/dev/null || done=0
  (( done )) || { print "NOT COMPLETE: G still running (no exit= line yet); GR again later"; return 1; }
  if classify $g/suite.txt $g/shards/*(N.) $g/graftling-suite.txt | grep -q '^NEW'; then print "NOT COMPLETE: NEW failures (above)"; return 1; fi
  print "COMPLETE: no NEW failure in either suite"
}

case $STEP in
  00) step_00 ;;
  U) step_U ;;
  B) step_B ;;
  A0) step_A0 ;;
  A) step_A ;;
  AX) step_AX ;;
  AU) step_AU "$@" ;;
  AC) step_AC ;;
  G) step_G ;;
  GR) step_GR ;;
  *) print "usage: zsh $THIS <00|U [before|after]|B <rt|all>|A0|A <rt|all>|AX|AU <claude|pi> <deny|allow>|AC <claude|pi>|G|GR>"; return 2 ;;
esac
