#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 514 Main-run steps: GraphTraj's own MCP server is named graphtraj on Claude Code, Codex, Pi and DSH.
#   zsh <this file> <STEP>
# Order: 0 -> Ct (USER) -> Rt (USER) -> Rs1 -> Rs2 -> C -> X -> P -> D, then on an idle host T and F (R reads F).
#   0    preflight: wheels (candidate = this Worktree HEAD; graftling a51e1004; for Rs the base e746cfc4 with graftling
#        v0.5.2), venvs, isolated projects under /private/tmp/graphtraj-514, probe Task 1, a no-model check of every
#        generated host configuration, then one one-line prompt per host (model and login)
#   Ct   USER, plain Terminal: trust the C/X project (one dialog)      Rt  USER: trust the Rs project (one dialog)
#   Rs1  old configuration (base + graftling 0.5.2): a Claude Main dispatches a Claude member (old name `agents`)
#   Rs2  the same project rewritten by the candidate; a new Claude Main resumes that member (observation, req 5)
#   C    Claude Main host + one Claude member      X  one Codex member (gpt-6-luna)
#   P    Pi Main                                   D  DSH Main
#   T    focused tests in Harness tmp/514 venv     F  full suite there (background)      R  F's results
# Projects live outside the Harness (user 2026-11-18): a project under it would merge the Harness .mcp.json and
# instruction files. No step starts or connects to the Harness's production MCP servers; every host here is started
# from an isolated project with --strict-mcp-config or its own extension/patch. No step signals a process it did not
# start. Names are judged from Runtime records only (check514.py leaves the step's own files out).
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)       # this Task Worktree (the candidate)
H=${WT:h:h:h:h}                                        # <Harness>
GDEV=$H/.graphtraj/core/worktrees/graftling-dev        # graftling Integration Worktree (read only: git archive)
GCOMMIT=a51e1004a0fe77fe492681faa2f278d80b3d725e        # graftling dev 0.6.0 (513)
GREPO=$H/graftling; GOLD=v0.5.2                        # Rs: graftling before 513, as production (503)
BASECOMMIT=e746cfc4                                    # Rs: GraphTraj dev before 514
# VERIFY514_* are set only by a rehearsal (scratch BASE/T/OUT, a fake RT, stub hosts first on PATH); defaults are real.
BASE=${VERIFY514_BASE:-/private/tmp/graphtraj-514}     # resolved form (verify-common claude_isolation accepts it)
P=$BASE/project; PO=$BASE/project-rs
V=$BASE/venv; OV=$BASE/venv-old
T=${VERIFY514_T:-$H/tmp/514}                           # test venv and suite output (Harness tmp)
OUT=${VERIFY514_OUT:-$H/.graphtraj/core/state/tasks/514-graphtraj-mcp-server-name/realhost}
CONDA=$HOME/miniconda3/bin/python3.13
RT=${VERIFY514_RT:-$H/.venv-runtime/lib/python3.13/site-packages}   # read only: yaml, websockets, click (no PyPI on this host)
SD=${0:A:h}; THIS=${0:A}; CHECK=$SD/check514.py
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
MODEL=claude-opus-5-5
PI_PROVIDER=deepseek; PI_MODEL=deepseek-flash
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY514_STUB:-} ]] && path=($VERIFY514_STUB $path)   # rehearsal only: stub hosts first

say() { print -r -- "== $*"; }
next() { print -r -- "next: zsh $THIS $*"; }
# A time limit that env -i (clean) can exec: a command, not a shell function. Usage: clean ... $BOUND <seconds> cmd...
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# A host inherits no marker of the Harness Main (GraphTraj/graftling connections, DSH Session).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
load_key() {  # verify-513 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
candidate() {
  git -C $WT diff --quiet HEAD -- || { print "STOP: $WT has uncommitted changes"; return 1; }
  git -C $WT rev-parse HEAD
}
venv_check() {
  [[ -f $V/installed && $(<$V/installed) == "$(candidate) $GCOMMIT" ]] \
    || { print -r -- "STOP: $V does not hold the candidate $(candidate) + graftling $GCOMMIT; run: zsh $THIS 0"; return 1; }
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
need() {  # $1 directory, $2 pattern: print the one file it must hold, else STOP with the listing
  local found=($1/$~2(N))
  (( $#found == 1 )) && { print -r -- $found; return 0; }
  print -r -- "STOP: expected exactly one $2 in $1, found ${#found}:" >&2; ls -la $1 >&2
  return 1
}
make_venv() {  # $1 venv, $2.. wheels
  local dir=$1; shift
  [[ -e $dir ]] && mv $dir $dir.$(date +%H%M%S)
  $CONDA -m venv $dir; deps $dir
  $dir/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps "$@"
}
project() {  # $1 project, $2 venv: own git and .graphtraj, isolation settings, roles and Task 1
  local p=$1 v=$2
  if [[ ! -d $p/.git ]]; then
    mkdir -p $p; (cd $p && git init -q -b main && print -r -- "# 514 probe" > README.md && git add README.md \
      && git -c user.name=514 -c user.email=514@invalid commit -qm "Initial source") || return 1
    (cd $p && print y | clean $v/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $p && clean $v/bin/python -I $SD/prep514.py $p) || { print "STOP: roles or probe Task 1 not ready in $p"; return 1; }
}
configure_claude() {  # $1 project, $2 venv: configuration --write, isolation, only the graphtraj/agents entry enabled
  local p=$1 v=$2
  (cd $p && clean $v/bin/python -m graphtraj.runtimes.claude.host configuration --project $p --claude $(command -v claude) --write) >/dev/null
  # Task 489: the project's own settings exclude the Harness instruction files (rerun after every --write).
  clean $CONDA -I $WT/scripts/verify-common/claude_isolation.py settings $H $p
}
host_check() {  # $1 project, $2 expected server key: the no-model load of the generated Claude host configuration
  clean $V/bin/python -I - $1 $2 <<'PY'
import json, sys
from pathlib import Path
project, server = Path(sys.argv[1]), sys.argv[2]
servers = json.loads((project / '.mcp.json').read_text())['mcpServers']
config = json.loads((project / '.graphtraj/claude-host/config.json').read_text())
module = (project / '.claude/skills/graphtraj-claude-host/hooks/host_context.mjs').read_text()
# What serve checks first (graphtraj.runtimes.claude.host main): exactly these keys, absolute paths.
keys = set(config) == {'root', 'cwd', 'claude', 'channel_file'} and all(Path(v).is_absolute() for v in config.values())
module_ok = f'const SERVER = "{server}";' in module and 'const TOOLS = ["agents", "tasks"];' in module
print(f'.mcp.json servers: {list(servers)}; host config keys/paths valid: {keys}; plugin module server {server}: {module_ok}')
sys.exit(0 if list(servers) == [server] and keys and module_ok else 1)
PY
}
begin() {  # $1 step: evidence directory and the time marker for the record scans
  D=$OUT/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D; touch $D/marker
  print -r -- "candidate $(git -C $WT rev-parse HEAD) step $1" > $D/run.txt
  print -r -- "evidence: $D"
}
claude_main() {  # $1 project, $2 tool prefix, $3 prompt file: one claude -p Main of the GraphTraj host plugin
  local p=$1 prefix=$2 S=$(uuidgen | tr A-Z a-z)
  print -r -- $S > $D/main-session.txt
  (cd $p && clean $BOUND 1500 claude -p --model $MODEL --output-format stream-json --verbose \
     --mcp-config $p/.mcp.json --strict-mcp-config --allowedTools "${prefix}agents,${prefix}tasks" --session-id $S \
     < $3 > $D/stream.jsonl 2> $D/stderr.txt) || print "claude rc=$?"
  cp $p/.graphtraj/claude-host/host.log $D/host.log 2>/dev/null || true
}
# Every Claude transcript written since the marker for projects under BASE (Main and members; the checks judge a
# member from its own native transcript only), and, as evidence, the project's records changed since then.
collect_claude() {  # $1 project
  mkdir -p $D/claude-projects $D/project-records
  local f
  for f in $HOME/.claude/projects/*graphtraj-514*/**/*.jsonl(N.); do [[ $f -nt $D/marker ]] && cp $f $D/claude-projects/; done
  for f in $1/.graphtraj/**/*(N.); do [[ $f -nt $D/marker ]] && { mkdir -p $D/project-records/${${f#$1/}:h}; cp $f $D/project-records/${f#$1/}; }; done
  print -r -- "claude transcripts copied: $(ls $D/claude-projects | wc -l | tr -d ' '); project records copied: $(find $D/project-records -type f | wc -l | tr -d ' ')"
}
# The plugin gate before every paid Claude step: one one-line claude -p from the project (the same .mcp.json and
# --strict-mcp-config as the step). Its system init record must list exactly the expected server, no untrusted
# plugin warning, and mcp__<expected>__agents. Returns 1 otherwise (the step then runs no claude -p of its own).
gate() {  # $1 project, $2 expected server
  local p=$1 server=$2
  (cd $p && clean $BOUND 120 claude -p --model $MODEL --output-format stream-json --verbose --mcp-config $p/.mcp.json \
     --strict-mcp-config <<< 'Reply with one line: READY-514 and your exact model name. Use no tool.' > $D/gate.jsonl 2> $D/gate.err) \
     || print "claude rc=$?"
  clean $CONDA -I -c 'import json, sys
server = sys.argv[2]
lines = []
for l in open(sys.argv[1], errors="replace"):
    try: lines.append(json.loads(l))
    except ValueError: pass
init = next((l for l in lines if l.get("subtype") == "init"), {}); res = next((l for l in lines if l.get("type") == "result"), {})
servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers", [])]
warnings = json.dumps(init.get("plugin_warnings", []))
tools = [t for t in init.get("tools", []) if t.startswith("mcp__")]
print("claude model:", init.get("model"), "| answer:", str(res.get("result", ""))[:120].replace("\n", " "))
print("claude init mcp_servers:", servers, "| mcp tools:", tools, "| plugin_warnings:", warnings[:300])
ok = [n for n, _ in servers] == [server] and "untrusted" not in warnings and f"mcp__{server}__agents" in tools
print(f"claude plugin gate ({sys.argv[3]}, expected server {server}):", "PASS" if ok else "NOT PASSED")
sys.exit(0 if ok else 1)' $D/gate.jsonl $server $p
}
member_prompt() {  # $1 role, $2 prefix of the member's own tools as the Main names them, $3 tag
  print -r -- "Use only the MCP tools ${2}tasks and ${2}agents. 1. With ${2}tasks execute swarm with arguments {\"tasks\":[{\"task_id\":\"1\",\"role\":\"$1\",\"instruction\":\"This is a scripted probe. Call your agents MCP tool exactly once with {\\\"action\\\": \\\"execute\\\", \\\"feature\\\": \\\"status\\\", \\\"arguments\\\": {}} and your tasks MCP tool exactly once with {\\\"action\\\": \\\"discover\\\"}. Use no other tool. Then reply with one line: $3 followed by the exact names of the two tools you called and, for each, ok or the exact error.\"}]} and print the raw result on one line starting with SWARM-RESULT. 2. Call ${2}agents with {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": <the member's agent or alias from step 1>, \"timeout_seconds\": 300}}, repeating until its execution has ended. 3. Print one line MEMBER <the member's alias> <its session> and one line REPLY <its final last_message>. Stop."
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT
case $STEP in
0)
  say "[0] preflight. Dialog: none. Builds wheels and venvs (no network), isolated projects, a no-model configuration check, then one-line prompts (claude, codex, pi, dsh; each at most 120 s)."
  print "zsh $ZSH_VERSION; git $(git --version); conda $($CONDA --version 2>&1)"
  local C=$(candidate) W=$BASE/wheels
  print "candidate: $WT $C (branch $(git -C $WT branch --show-current)); graftling: $GDEV $GCOMMIT ($(git -C $GDEV log -1 --format='%h %s' $GCOMMIT | cut -c1-80))"
  print "pytest temp for T/F: $PYTEST_TMP"
  mkdir -p $BASE $W
  if [[ ! -f $V/installed || $(<$V/installed) != "$C $GCOMMIT" ]]; then
    rm -f $W/graftling-*.whl(N) $W/graphtraj-*.whl(N)
    wheel $GDEV $GCOMMIT src/graftling $W && wheel $WT $C . $W || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $W 'graftling-*.whl') && hw=$(need $W 'graphtraj-*.whl') || return 1
    make_venv $V $gw $hw && print -r -- "$C $GCOMMIT" > $V/installed
  else print "venv $V already holds $C + $GCOMMIT"; fi
  if [[ ! -f $OV/installed ]]; then
    local O=$BASE/wheels-old; mkdir -p $O; rm -f $O/graftling-*.whl(N) $O/graphtraj-*.whl(N)
    wheel $GREPO $GOLD src/graftling $O && wheel $WT $BASECOMMIT . $O || { print "STOP: an Rs wheel did not build"; return 1; }
    local ogw ohw; ogw=$(need $O 'graftling-*.whl') && ohw=$(need $O 'graphtraj-*.whl') || return 1
    make_venv $OV $ogw $ohw && print -r -- "$BASECOMMIT $GOLD" > $OV/installed
  fi
  local v; for v in $V $OV; do
    (cd $PYTEST_TMP && clean $v/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m
print(graftling.__file__.split("/lib/")[0], "graftling", m.version("graftling"), "graphtraj", m.version("graphtraj"), "from", graphtraj.__file__.split("/lib/")[0])')
  done
  print "installed: $(<$V/installed) (venv) | $(<$OV/installed) (venv-old)"
  say "isolated projects (own git and .graphtraj) and probe Task 1"
  project $P $V && project $PO $OV || return 1
  say "no-model configuration check of every generated host configuration"
  configure_claude $P $V && host_check $P graphtraj || { print "STOP: the C/X Claude host configuration is refused (above)"; return 1; }
  configure_claude $PO $OV
  print "Rs project (base e746cfc4) .mcp.json servers: $(clean $V/bin/python -I -c 'import json,sys; print(list(json.load(open(sys.argv[1]))["mcpServers"]))' $PO/.mcp.json) (expected ['agents'])"
  clean claude plugin validate $P/.claude/skills/graphtraj-claude-host 2>&1 | tail -3 || print "plugin validate rc=$?"
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $BASE/dsh-main.patch.yml >/dev/null && \
    { print -r -- "- id: llm-deepseek"
      print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"; } >> $BASE/dsh-main.patch.yml
  (cd $P && clean dsh --profile headless --patch $BASE/dsh-main.patch.yml --dump-config > $BASE/dsh-dump-config.txt 2>&1) || true
  grep -q graphtraj-main $BASE/dsh-dump-config.txt && print "DSH composed tree has the graphtraj-main row: YES" \
    || { print "STOP: no graphtraj-main row in the composed DSH tree:"; head -20 $BASE/dsh-dump-config.txt | redact; return 1; }
  local EXT=$($V/bin/python -I -c 'import graphtraj, pathlib; print(pathlib.Path(graphtraj.__file__).parent / "runtimes/pi/extension.mjs")')
  print "Pi extension: $EXT (registers graphtraj; $(grep -c "registerMcpServer('graphtraj'" $EXT) line)"
  say "one-line prompts (model and login). The Claude one runs from the C/X project and its init record is the plugin gate."
  load_key || true
  local ASK='Reply with one line: READY-514 and your exact model name. Use no tool.'
  begin 0
  # Information only here: before Ct trusts the folder the plugin is skipped; Rs1, Rs2, C and X gate themselves.
  gate $P graphtraj || print "(expected before Ct: the steps that need it re-check and stop)"
  (cd $BASE && clean $BOUND 120 codex exec --skip-git-repo-check -m gpt-6-luna $ASK 2>&1 | tail -2) || print "codex rc=$?"
  (cd $BASE && clean $BOUND 120 pi --print --no-tools --provider $PI_PROVIDER --model $PI_MODEL $ASK < /dev/null 2>&1 | redact | tail -2) || print "pi rc=$?"
  (cd $BASE && clean $BOUND 120 dsh --profile headless --permission-mode read-only $ASK < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  print "Ready when: both venvs print their versions, 'roles OK' and 'probe Task 1 ready' twice, '.mcp.json servers: ['graphtraj']', the DSH row YES, and four READY-514 lines."
  next "Ct   (USER, plain Terminal)"
  ;;
Ct|Rt)
  local p=$([[ $STEP == Ct ]] && print $P || print $PO)
  say "[$STEP] USER in a plain Terminal. Dialog: one, expected to be the only one: Claude Code's 'Do you trust the files in this folder?' for $p -> choose 'Yes, proceed', then type /exit. Should an MCP server approval dialog appear anyway, choose the option that does NOT enable the server (press Esc); the steps pass --mcp-config --strict-mcp-config."
  (cd $p && claude) || print "claude exit $?"
  [[ $STEP == Ct ]] && next "Rt  (USER, plain Terminal)" || next "Rs1  (Main)"
  ;;
Rs1)
  say "[Rs1] OLD configuration (GraphTraj $BASECOMMIT + graftling $GOLD, .mcp.json key agents) in $PO: a Claude Main dispatches one Claude member, which calls mcp__agents__agents/tasks. Dialog: none. At most 25 min."
  begin Rs1
  configure_claude $PO $OV
  gate $PO agents || { print "STOP: plugin gate not passed for $PO (above); no claude -p of Rs1 was run. Trust it with: zsh $THIS Rt"; return 1; }
  member_prompt claude_member mcp__agents__ DONE-514-OLD > $D/host.prompt.txt
  claude_main $PO mcp__agents__ $D/host.prompt.txt
  collect_claude $PO
  clean $CONDA -I $CHECK Rs1-old --observe --skip $(<$D/main-session.txt) $D/claude-projects | tee $D/summary.txt
  # The member alias (and session) from the MEMBER line of the Main's last result record.
  local member=$(clean $CONDA -I -c 'import json, sys
text = ""
for l in open(sys.argv[1], errors="replace"):
    try: d = json.loads(l)
    except ValueError: continue
    if d.get("type") == "result": text = str(d.get("result", ""))
hits = [l.split()[1:3] for l in text.splitlines() if l.strip().startswith("MEMBER ") and len(l.split()) >= 2]
if hits: print(" ".join(hits[-1]))
else: print("NONE"); print(text[-1500:], file=sys.stderr)' $D/stream.jsonl)
  if [[ -z $member || $member == NONE* ]]; then
    print "STOP: no MEMBER line in the Main's last result ($D/stream.jsonl); its text is above. Rs2 needs the member alias."
    return 1
  fi
  print -r -- $member > $D/member.txt
  print -r -- "member alias and session: $member"
  next "Rs2 ${member%% *}"
  ;;
Rs2)
  local alias=${2:-}; [[ -n $alias ]] || { print "usage: zsh $THIS Rs2 <member alias from Rs1>"; return 2; }
  say "[Rs2] resume observation (req 5): rewrite $PO with the candidate (.mcp.json must keep only graphtraj), then a new Claude Main resumes member $alias, whose Session was created under the name agents. Dialog: none. At most 25 min. An observation, not a pass gate."
  venv_check; begin Rs2
  configure_claude $PO $V
  host_check $PO graphtraj || print "NOTE: the rewritten Rs configuration is not exactly graphtraj (above)"
  gate $PO graphtraj || { print "STOP: plugin gate not passed for $PO after the rewrite (above); no claude -p of Rs2 was run"; return 1; }
  print -r -- "Use only the MCP tools mcp__graphtraj__agents and mcp__graphtraj__tasks. 1. Call mcp__graphtraj__agents with {\"action\": \"execute\", \"feature\": \"resume\", \"arguments\": {\"agent\": \"$alias\", \"message\": \"This is a scripted probe after an update. Call your agents MCP tool exactly once with {\\\"action\\\": \\\"execute\\\", \\\"feature\\\": \\\"status\\\", \\\"arguments\\\": {}} and your tasks MCP tool exactly once with {\\\"action\\\": \\\"discover\\\"}. Use no other tool. Then reply with one line: DONE-514-RESUMED followed by the exact names of the two tools you called and, for each, ok or the exact error.\"}} and print the raw result. If resume is refused, describe resume with schema true, retry once with the documented arguments, and print both raw results. 2. Wait for it with mcp__graphtraj__agents wait (timeout_seconds 300), repeating until its execution has ended. 3. Print one line REPLY <its final last_message>. Stop." > $D/host.prompt.txt
  claude_main $PO mcp__graphtraj__ $D/host.prompt.txt
  collect_claude $PO
  clean $CONDA -I $CHECK Rs2-resumed-member --observe --skip $(<$D/main-session.txt) $D/claude-projects | tee $D/summary.txt
  print "Observation: the resumed member's calls of mcp__graphtraj__agents and mcp__graphtraj__tasks (OBSERVED lines), its REPLY line in the Main's result, and any 'No such tool'/error for mcp__agents__*. Report it either way."
  next C
  ;;
C)
  say "[C] Claude Main host (GraphTraj host plugin, .mcp.json with only graphtraj) in $P dispatches one Claude member (claude_member, permission_mode auto). Dialog: none (Ct trusted the folder). At most 25 min."
  venv_check; begin C
  configure_claude $P $V; host_check $P graphtraj || { print "STOP: the host configuration is refused; no claude -p was run"; return 1; }
  gate $P graphtraj || { print "STOP: plugin gate not passed for $P (above); no claude -p of $STEP was run. Trust it with: zsh $THIS Ct"; return 1; }
  member_prompt claude_member mcp__graphtraj__ DONE-514-C > $D/host.prompt.txt
  claude_main $P mcp__graphtraj__ $D/host.prompt.txt
  collect_claude $P
  local S=$(<$D/main-session.txt) rc=0
  clean $CONDA -I $CHECK claude-main --init $D/stream.jsonl $D/stream.jsonl $D/claude-projects/$S.jsonl(N) | tee $D/summary.txt || rc=1
  clean $CONDA -I $CHECK claude-member --skip $S $D/claude-projects | tee -a $D/summary.txt || rc=1
  print "C: $([[ $rc == 0 ]] && print PASS || print 'FAIL or CANNOT (lines above)'). The member's REPLY line is in the last result record of $D/stream.jsonl."
  next X
  ;;
X)
  say "[X] a Claude Main in $P dispatches one Codex member (codex_member, gpt-6-luna). Dialog: none. At most 25 min. Judged: the Codex member's records."
  venv_check; begin X
  configure_claude $P $V; host_check $P graphtraj || { print "STOP: the host configuration is refused; no claude -p was run"; return 1; }
  gate $P graphtraj || { print "STOP: plugin gate not passed for $P (above); no claude -p of $STEP was run. Trust it with: zsh $THIS Ct"; return 1; }
  member_prompt codex_member mcp__graphtraj__ DONE-514-X > $D/host.prompt.txt
  claude_main $P mcp__graphtraj__ $D/host.prompt.txt
  collect_claude $P
  mkdir -p $D/rollouts
  local f; for f in ${CODEX_HOME:-$HOME/.codex}/sessions/**/rollout-*.jsonl(N.); do [[ $f -nt $D/marker ]] && cp $f $D/rollouts/; done
  print "codex rollouts copied: $(ls $D/rollouts | wc -l | tr -d ' ')"
  clean $CONDA -I $CHECK codex-member $D/rollouts | tee $D/summary.txt \
    && print "X: PASS" || print "X: FAIL or CANNOT (lines above); the Main's REPLY line is in $D/stream.jsonl"
  next P
  ;;
P)
  say "[P] Pi Main (pi --mode json with GraphTraj's Pi extension) in $P: one agents call and one tasks call. Dialog: none. At most 10 min."
  venv_check; load_key || return 1; begin P
  local EXT=$($V/bin/python -I -c 'import graphtraj, pathlib; print(pathlib.Path(graphtraj.__file__).parent / "runtimes/pi/extension.mjs")')
  print -r -- "Call the MCP tool mcp__graphtraj__agents exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}} and the MCP tool mcp__graphtraj__tasks exactly once with {\"action\": \"discover\"}. Use no other tool. Then reply with one line: DONE-514-P followed by the exact names of the tools you have whose names start with mcp__, and for each call ok or the exact error." > $D/host.prompt.txt
  (cd $P && clean PATH=$V/bin:${(j.:.)path} GRAFTLING_PYTHON=$V/bin/python $BOUND 600 pi --mode json --session-dir $D/pi-sessions \
     --extension $EXT --provider $PI_PROVIDER --model $PI_MODEL "$(<$D/host.prompt.txt)" < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "pi rc=$?"
  clean $CONDA -I $CHECK pi-main $D/pi-sessions $D/stdout.jsonl | redact | tee $D/summary.txt && print "P: PASS" || print "P: FAIL or CANNOT (lines above)"
  next D
  ;;
D)
  say "[D] DSH Main (headless, GraphTraj's graphtraj-main row) in $P: one agents call and one tasks call. Dialog: none. At most 10 min."
  venv_check; load_key || return 1; begin D
  local DH=$D/dsh-home; mkdir -p $DH
  print -r -- "Call your GraphTraj MCP tool mcp__graphtraj__agents exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}} and mcp__graphtraj__tasks exactly once with {\"action\": \"discover\"}. Use no other tool. Then reply with one line: DONE-514-D followed by the exact names of the tools you have whose names start with mcp__, and for each call ok or the exact error." > $D/host.prompt.txt
  (cd $P && clean DSH_HOME=$DH $BOUND 600 dsh --profile graphtraj514 --from-default-profile headless --patch $BASE/dsh-main.patch.yml \
     --json "$(<$D/host.prompt.txt)" < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "dsh rc=$?"
  clean $CONDA -I $CHECK dsh-main $D/stdout.jsonl $DH | redact | tee $D/summary.txt && print "D: PASS" || print "D: FAIL or CANNOT (lines above)"
  next "T, then F (idle host), then R"
  ;;
T|F)
  local VT=$T/venv-test
  check_tmp() { case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac; print "pytest temp: $PYTEST_TMP (outside the Harness)"; }
  check_tmp
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later:"; print -r -- $others; return 1; }
  # The suite requires the checkout itself (editable) beside an installed graftling wheel (tests/conftest.py).
  if [[ ! -f $VT/installed || $(<$VT/installed) != "$(candidate) $GCOMMIT" ]]; then
    mkdir -p $T; [[ -e $VT ]] && mv $VT $VT.$(date +%H%M%S)
    $CONDA -m venv --system-site-packages $VT; deps $VT
    local W=$T/wheels gw; mkdir -p $W; rm -f $W/graftling-*.whl(N); wheel $GDEV $GCOMMIT src/graftling $W
    gw=$(need $W 'graftling-*.whl') || return 1
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache || true
    print -r -- "$(candidate) $GCOMMIT" > $VT/installed
  fi
  (cd $PYTEST_TMP && $VT/bin/python -I -c 'import graftling, graphtraj, pytest; print("graftling", graftling.__version__, graftling.__file__, "| graphtraj", graphtraj.__file__, "| pytest", pytest.__version__)')
  [[ -n ${VERIFY514_PREFIX_ONLY:-} ]] && { print "VERIFY514_PREFIX_ONLY: venv ready, no pytest started (rehearsal)"; return 0; }
  local R=$OUT/$STEP-$(candidate | cut -c1-10)-$(date +%H%M%S); mkdir -p $R
  if [[ $STEP == T ]]; then
    say "[T] focused tests (foreground, about 5 min). Dialog: none."
    (cd $WT && TMPDIR=$PYTEST_TMP $VT/bin/python -m pytest -p no:cacheprovider -q -rfE \
      tests/test_graphtraj_mcp_server_name.py tests/test_configuration_write_keeps_settings.py tests/test_claude_native_host.py \
      tests/test_claude_runtime.py tests/test_claude_host_context.py tests/test_host_plugin_tools.py \
      tests/test_claude_host_concurrent_calls.py tests/test_release_low_bundle.py tests/test_review_plugin_pi_dsh.py \
      tests/test_pi_attachment_private_paths.py tests/test_agents_native_claude.py tests/test_agents_mcp_bridge.py \
      tests/test_independent_claude.py tests/test_agents_refused_reply.py tests/test_graphtraj_public_agents_api.py \
      tests/test_mcp_adoption.py > $R/focused.txt 2>&1; print "exit=$?" >> $R/focused.txt)
    tail -4 $R/focused.txt; grep -E '^(FAILED|ERROR) ' $R/focused.txt || print "(no FAILED/ERROR lines)"
    next "F  (on an idle host)"
  else
    say "[F] GraphTraj full suite (background). Dialog: none. Returns at once."
    (cd $WT && TMPDIR=$PYTEST_TMP nohup $VT/bin/python -m pytest -p no:cacheprovider -q -rfE > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
    print -r -- "started; result: tail -30 $R/suite.txt"; next R
  fi
  ;;
R)
  say "[R] F's results. Dialog: none."
  local f=($OUT/F-*(N/om[1])); (( $#f )) || { print "no F result yet; run: zsh $THIS F"; return 0; }
  print -r -- "---- $f"; tail -6 $f/suite.txt; print "failed/error lines:"; grep -h -E '^(FAILED|ERROR) ' $f/suite.txt | sort -u || print "(none)"
  ;;
*) print -r -- "usage: zsh $THIS 0|Ct|Rt|Rs1|Rs2 <alias>|C|X|P|D|T|F|R"; return 2 ;;
esac
