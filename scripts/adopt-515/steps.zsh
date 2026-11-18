#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 515 — production adoption of the MCP server rename: graftling 0.6.0 (a wheel built from <Harness>/graftling
# at tag v0.6.0, a51e1004) and GraphTraj dev 4ad22e90 (514: Main's .mcp.json server key `graphtraj`, tools
# mcp__graphtraj__agents/tasks; `configuration --write` drops GraphTraj's own old `agents` entry). Production holds
# 503's graftling 0.5.2 + 6115c724. Copied from scripts/adopt-503/steps.zsh (unchanged there); every 503 protection
# kept (isolated vproject, proddiff file by file, markers both ways, backup + R from the backup's own tools, guard that
# waits and never signals, rerun right before pip, Claude Code version at 00, no key value in raw output, timers
# listed only). New in 515: graftling CODE differences against production are expected (listed; STOP only when the
# wheel differs from the v0.6.0 archive); I runs `configuration --write` of the new installation and checks the
# .mcp.json key and the hook plugin's SERVER; M probes Main's tool names; Nr checks the member's calls by name
# (rec515.py on raw records); Rs/Rsr resume the standby Leader and Engineer Sessions; S prints the reused full suite.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V → S (reused suite evidence) → Vu (USER once: new path) → Vc → Mpre → [USER /exit Main] → I (USER)
#        → [USER: claude --continue] → M → Mps → inbox → Rs → Rsr → Nw (background, read only) → N → Nt → Nr → N484
#        → done → [Leader accepts 515] → T.  Rollback: R.  Timer listing at any time: timers.
# Each step prints who runs it, claude --version, its dialog (at most one) and how to judge success, then the next
# command. Main's Bash cannot run a foreground sleep: every Main step ends in < 10 min or starts itself in the
# background (Nw), and is polled by reading a file. Only I and R (USER's Terminal) wait in a loop.
# No step signals a process it did not start (budget timers included). Backups and scratch under $H/tmp/515; the
# isolated real-host project under /private/tmp/vproject-515 (user 2026-11-18: a project under the Harness would merge
# the Harness .mcp.json). 503's backup $H/tmp/503/backup is only listed, never modified.
# Only rehearse.zsh sets ADOPT515_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT515_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT515_BASE:-$H/tmp/515}
RT=${ADOPT515_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT515_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT515_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/515-production-adoption-mcp-server-names}
G=${ADOPT515_G:-$H/graftling}   # graftling repository; only `git archive v0.6.0` is read, never the working tree
GTAG=v0.6.0
GVERSION=0.6.0
GCOMMIT=${ADOPT515_GCOMMIT:-a51e1004a0fe77fe492681faa2f278d80b3d725e}   # user 2026-11-18: v0.6.0 = a51e100 (main, pushed)
GOLDTAG=v0.5.2; GOLDVERSION=0.5.2   # production's graftling (503)
TARGET=4ad22e9065cf38bc3c976eed184d29b1a299413a   # dev = 6115c724 + 501..506, 513, 514 (514's accepted commit)
C8=${TARGET[1,8]}   # per-commit names
OLD=6115c72491a238cc672d88ec539cda800e4c3651   # production now: 503's wheels (graftling 0.5.2 + graphtraj 6115c724)
OLDBASE=${ADOPT515_OLDBASE:-$H/tmp/503}   # 503's backup: listed only, never touched
TASK=515-production-adoption-mcp-server-names
TASK_ID=515
CHILD=n515
NEWS=graphtraj; OLDS=agents   # .mcp.json server keys: new (514) and old
ISO=$SD/../verify-common/claude_isolation.py   # 489's shared isolation (settings + answer check)
# Claude Code version: not assumed. 00 records the installed one (claude --version) in $BASE/cc.version; every later
# step prints whether the version it runs is the same.
CC_EXPECT=$(cat ${ADOPT515_BASE:-$H/tmp/515}/cc.version 2>/dev/null)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw-$C8
CTL=$R/ctl   # control-record snapshots (484, 486): states, notification fields, owner pids; no message text
N=$W/wheels-$C8
SRC=$W/src-$C8
GSRC=$W/gsrc-$GVERSION   # git archive of graftling $GTAG; its src/ holds graftling/ (readers of Nw/Nr use it)
BK=$BASE/backup
VV=$BASE/vvenv-$C8
SV=$BASE/svenv-$C8
VPL=$W/vplug-$C8
VP=$VPL/graphtraj-claude-host
VE=$W/ventries-$C8
VPROJECT=${ADOPT515_VPROJECT:-/private/tmp/vproject-515}   # user 2026-11-18: outside the Harness (no merged .mcp.json)
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml $H/.codex/config.toml(N) $H/.codex/hooks.json(N))
INBOX=$H/.graphtraj/core/runner/main-sessions/inbox
PROJECTS=${ADOPT515_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT515_STUB:-} ]] && path=($ADOPT515_STUB $path)   # rehearsal only: stub hosts first
mkdir -p $R $BASE
MAIN=$(cat $BASE/main.session 2>/dev/null)

# 418 reminder: a GRAFTLING_CLAUDE_HOST_CONFIG inherited from another configured project makes the old
# hook give up association. Recorded here (names and paths only), then removed for every child command.
INHERITED=(${(k)parameters[(I)GRAFTLING_CLAUDE_HOST_*]} ${(k)parameters[(I)GRAPHTRAJ_CLAUDE_HOST_*]})
INHERITED_REPORT=(); for n in $INHERITED; do INHERITED_REPORT+=("$n=${(P)n}"); unset $n; done

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
tree() { $CONDA -I $SD/adopt_tree.py "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
# Every real-host step prints which claude it uses (the default one; ~/.local/bin/claude is never repointed).
cv() { local C=$(claude_bin) v; v=$($C --version 2>&1 | head -1)
  if [[ -z $CC_EXPECT ]]; then print -r -- "claude: $C -> ${C:A} | version: $v | recorded at 00: none yet (00 records it)"
  else print -r -- "claude: $C -> ${C:A} | version: $v | same as recorded at 00 ($CC_EXPECT): $([[ $v == $CC_EXPECT ]] && print yes || print NO)"; fi; }
# Tasks whose members may run now: every Task in the state whose status is not integrated, except this one.
active_tasks() {
  local f st ids=()
  for f in $H/.graphtraj/core/state/tasks/*/task.yml(N); do
    st=$(sed -n 's/^status: //p' $f); [[ -z $st || $st == integrated ]] && continue
    [[ ${f:h:t} == ${TASK_ID}-* ]] && continue
    ids+=(${${f:h:t}%%-*})
  done
  print -r -- ${(j:, :)${(on)ids}}
}
# 465's isolation check (scripts/verify-465/probe.py isolation): graphtraj root, git top level, no CLAUDE.md upward.
isolation() {
  $1 -I - $VPROJECT <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('CLAUDE.md', 'CLAUDE.local.md') if (p / n).exists()]
agents = [str(p / 'AGENTS.md') for p in project.parents if (p / 'AGENTS.md').exists()]
print(f'graphtraj project root: {root} | isolated: {root == project}')
print(f'git top level: {top} | isolated: {Path(top).resolve() == project if top else False}')
print(f'CLAUDE.md/CLAUDE.local.md at or above the project: {upward or "none"}')
print(f'AGENTS.md above the project (Claude Code does not load AGENTS.md; graphtraj stops at the project): {agents or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward
print('isolation:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
}
# The isolated project: own git, own .graphtraj (setup by the given graphtraj), under $BASE.
vproject_init() {
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 503 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=503 -c user.email=503@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup) || return 1
  fi
  vsettings
}
# Task 489: claude -p in a project nested under the Harness loaded the Harness AGENTS.md through the builtin
# cc-plugin-agents-md. 497 uses 489's shared scripts/verify-common/claude_isolation.py, as the accepted verify
# scripts do: `settings` writes only the project's OWN .claude/settings.local.json (never ~/.claude; it refuses a
# project outside <harness>/tmp/), merged into existing keys; rerun after every `configuration --write`.
vsettings() { $CONDA -I $ISO settings $H $VPROJECT; }
# One real claude -p answer from the isolated project, judged by claude_isolation.py check (adopt-492's ans492.py
# criteria: tag, no prompt echo, no Harness file named, no distinctive Harness AGENTS.md line; plus: init plugins must
# not list cc-plugin-agents-md). The prompt is claude_isolation.py's PROMPT with the tag.
ask_model() {   # $1 = tag, $2 = output name; extra args go to claude
  local tag=$1 out=$2 C=$(claude_bin); shift 2
  $CONDA -I $ISO prompt $tag > $R/$out-prompt.txt
  (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose "$@" \
      < $R/$out-prompt.txt > $R/$out.jsonl 2> $R/$out.err)
  print "claude -p rc=$? (142 = 120 s timeout)"
  $CONDA -I $ISO check $R/$out.jsonl $tag $H $VPROJECT $R/$out-prompt.txt
}
wheel_of() { local f=($N/$1-*.whl(N)); print -r -- ${f[1]:-}; }
# 395: graphtraj/runtimes/graftling.mjs of venv $1 must resolve graftling to the sibling <site-packages>/graftling/.
# Run with an empty environment (no GRAFTLING_PYTHON, PATH without python3), so the python fallback cannot answer.
node_resolve() {
  local v=$1 s=($1/lib/python*/site-packages(N)) nodebin=$(command -v node) rel out ok=0
  [[ -n $nodebin ]] || { print "CHECK 503 node resolves graftling.mjs to the sibling: FAIL (node not on PATH)"; return 1; }
  for rel in pi/extension.mjs dsh/plugin.mjs; do
    out=$(cd ${TMPDIR:-/tmp} && env -i HOME=$HOME PATH=/var/empty $nodebin --input-type=module -e "const { pathToFileURL } = await import('node:url'); const m = await import(pathToFileURL(process.argv[1]).href); console.log(m.graftlingDirectory(process.argv[2], {}))" \
      $s[1]/graphtraj/runtimes/graftling.mjs $rel 2>&1)
    if [[ ${out:A} == ${s[1]:A}/graftling ]]; then print "CHECK 503 node resolves graftlingDirectory('$rel') to the sibling $s[1]/graftling/: PASS"
    else print -r -- "CHECK 503 node resolves graftlingDirectory('$rel') to the sibling $s[1]/graftling/: FAIL ($(print -r -- "$out" | grep -m1 -E '^Error' || print -r -- "${out[1,300]}"))"; ok=1; fi
  done
  return $ok
}
summary() { print -- "\n----- 复制给 Main 的摘要（$1）-----"; shift; print -l -- "$@"; print -- "-----"; }
# 515: the .mcp.json servers and which of them start GraphTraj or Graftling (command/args only; env values never
# printed). Exit 0 only when the servers that run graphtraj/graftling are exactly ['graphtraj'] and 'agents' is absent.
# With a second argument 'before' (00, production before I): the same facts as a state line without CHECK/PASS/FAIL,
# exit 0 (the old 'agents' entry is expected there; I must turn the CHECK to PASS).
mcp_keys() {
  $CONDA -I - $1 ${2:-} <<'MK'
import json, sys
before = sys.argv[2:] == ['before']
try: servers = json.load(open(sys.argv[1])).get('mcpServers') or {}
except (OSError, ValueError) as e: print(f'.mcp.json unreadable: {e}'); sys.exit(0 if before else 1)
ours = sorted(k for k, v in servers.items() if isinstance(v, dict) and any(w in ' '.join([str(v.get('command', ''))] + [str(a) for a in v.get('args') or []]) for w in ('graphtraj', 'graftling')))
print(f".mcp.json servers: {sorted(servers)} | servers running graphtraj/graftling: {ours}")
ok = ours == ['graphtraj'] and 'agents' not in servers
if before:
    print(f"state before I (not a check; expected 'not yet' now, I must make it so): .mcp.json has only graphtraj: {'yes' if ok else 'not yet'}")
    sys.exit(0)
print(f"CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
MK
}
# 515 Rs/Rsr: the record files of one member alias: its graftling archive(s) <swarm>/sessions/*/session.jsonl whose
# header id is the mapping's session, and Claude Code's own transcript <projects>/*/<session>.jsonl. Read only.
rs_session_files() {
  $CONDA -I - $H $SESS ${PROJECTS:h} "$1" <<'RSF'
import json, sys
from pathlib import Path
import yaml
h, sess, projects, alias = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
mapping = {}
for c in [h / '.graphtraj/core/runner/sessions' / alias / 'mapping.yml', *sorted(h.glob(f'.graphtraj/core/state/tasks/*/teams/*/traces/{alias}/runner/session.yml'))]:
    if c.is_file():
        d = yaml.safe_load(c.read_text()) or {}
        mapping = d if c.name == 'mapping.yml' else ((d.get('retirement') or {}).get('mapping') or {}); break
sid = mapping.get('session'); sid = sid.get('id') if isinstance(sid, dict) else sid
bare = str(sid or '').split(':', 1)[-1]
if not bare:
    print(f'no session for {alias}', file=sys.stderr); sys.exit(0)
for f in sorted(sess.glob('*/session.jsonl')):
    try: head = json.loads(f.open(errors='replace').readline())
    except (OSError, ValueError): continue
    head = head.get('header', head) if isinstance(head, dict) else {}
    if isinstance(head, dict) and str(head.get('id', '')).split(':', 1)[-1] == bare: print(f)
for f in sorted(projects.glob(f'*/{bare}.jsonl')): print(f)
RSF
}
rs_archives() { local a; for a in $(cat $R/Rs-leader.txt $R/Rs-engineer.txt 2>/dev/null); do rs_session_files $a; done; }
settings_view() {
  $CONDA -I - $1 <<'SV'
import json, sys
try: d = json.load(open(sys.argv[1]))
except (OSError, ValueError) as e: print(f'settings.local.json unreadable: {e}'); sys.exit(0)
rules = [r for k in ('allow', 'deny', 'ask') for r in (d.get('permissions') or {}).get(k, []) if str(r).startswith('mcp__')]
print(f"enabledMcpjsonServers: {d.get('enabledMcpjsonServers')} | enableAllProjectMcpServers: {d.get('enableAllProjectMcpServers')} | mcp__ permission rules: {rules or 'none'} | env names: {sorted((d.get('env') or {}).keys())}")
SV
}
# 499: completed notices of the member, by the notice's own shape only (497 defect b). $1 file, $2 member alias or ''.
notice_count() { $CONDA -I $SD/notices499.py "$1" "${2:-}"; }
inbox_key() { print -rn -- "$1" | shasum -a 256 | cut -d' ' -f1; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
need_main() { [[ -n $MAIN ]] || { print "没有 $BASE/main.session（Main 的 Session id）。先运行 00。"; exit 1; }; }

# Values of exported credential-like names, used only to count raw files that contain one (never printed).
key_values() {
  $CONDA -I -c '
import os, re
part = re.compile(r"(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
for n, v in os.environ.items():
    if len(v) >= 12 and not re.fullmatch(r"GIT_CONFIG_KEY_[0-9]+", n) and any(part.search(p) for p in n.upper().split("_") if p):
        print(v)'
}
credential_names() {
  $CONDA -I -c '
import os, re
part = re.compile(r"(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
print("credential-like exported names (values never printed):", sorted(n for n in os.environ if not re.fullmatch(r"GIT_CONFIG_KEY_[0-9]+", n) and any(part.search(p) for p in n.upper().split("_") if p)) or "none")'
}

# The running Claude Main: parent of the host serving this project's config.json. Its argv names
# --resume <id> / --session-id <id>, or is `claude --continue` (453: the user resumes that way), in which
# case the id is the newest transcript of this project (the Session --continue reopened).
detect_main() {
  local hit words pp cmd id=""
  hit=$(ps -axww -o pid=,ppid=,command= 2>/dev/null | grep -F -- "$HOSTCFG" | grep -F -- ' serve ' | head -1)
  words=(${=hit}); pp=${words[2]:-}
  if [[ -n $pp ]]; then
    cmd=$(ps -ww -o command= -p $pp 2>/dev/null); print -r -- "host pid ${words[1]}, parent $pp: ${cmd[1,160]}" >&2
    id=$(print -r -- "$cmd" | grep -oE -- '--(resume|session-id)[ =][0-9a-f-]{36}' | grep -oE '[0-9a-f-]{36}$' | head -1)
    [[ -n $id ]] && print -r -- "source: argv of the host's parent claude" >&2
    [[ -z $id && $cmd == *claude*' --continue'* ]] && print -r -- "parent is 'claude --continue': id from the newest transcript below" >&2
  else print -r -- "no host serving $HOSTCFG found by ps" >&2; fi
  if [[ -z $id ]]; then
    local t=($PROJECTS/*.jsonl(N.om[1]))
    [[ -n ${t[1]:-} ]] && { id=${t[1]:t:r}; print -r -- "source: newest transcript ${t[1]:t} (check it is this Main)" >&2; }
  fi
  print -r -- $id
}

# Long-lived processes that use .venv-runtime, by kind (code locations in README):
#   NON-BLOCKING  -m graphtraj.execution.budget_idle_timer  (445; one per idle timed Session; README judgement 3(a):
#                 one started under 4e3aafce that wakes after the install loads the new runner_control, graftling.control
#                 and tool_descendants and delivers; none of the modules it loaded at start changed)
#   BLOCKING      -m graphtraj.execution.runner_worker      (a member's Worker; 452: it keeps its agents child's owner thread
#                 and may outlive the member's turn until that child ends. 459: the owner of a Claude child samples
#                 the child's Runtime in a daemon thread 'tool-descendants' inside this same process. Still BLOCKING.)
#   BLOCKING      -m graphtraj.teams.team_round              (a swarm batch dispatching members; team_round.py:382)
#   BLOCKING      ... host serve --config <this project>     (Main's Claude host; graphtraj/runtimes/claude/host.py)
#   BLOCKING      anything else under $RT, or naming Main's Session id (a member's own host, a DSH watcher, a CLI call)
# 450's marked processes (GRAFTLING_MEMBER_RUN in the environment) are listed for information: a member's
# escaped process; it blocks only if it also uses $RT (then it is already in the BLOCKING list).
kind_of() {
  case $1 in
    *"-m graphtraj.execution.runner_worker"*)   # argv names <runner>/sessions/<alias>/{launch,resume}.yml; alias starts with the Task id
      local a=${${1##*/sessions/}%%/*}; print "member Worker of Task ${a%%-*} ($a)" ;;
    *"-m graphtraj.teams.team_round"*) print "swarm batch" ;;
    # 479: the Pi extension now spawns '<venv>/bin/graphtraj-session pi [--collect]' itself. Production Main is
    # Claude, so none is expected; one would be a Pi member's session tool under $RT: BLOCKING (same as before 479).
    *"graphtraj-session pi"*) print "Pi session tool (479; a Pi member's)" ;;
    # 486: graphtraj-mcp (Codex/DSH/Pi Main's tasks/agents server) now stops the Agents it runs as it exits; 481: a
    # user-started DSH Main's tool.mjs starts '<python> -I -m graphtraj.interfaces.mcp' and '... native_entry dsh'.
    # Production Main is Claude (graphtraj-claude-host): none expected. Under $RT they are BLOCKING (as before).
    *"graphtraj.interfaces.mcp"*|*"graphtraj-mcp"*) print "graphtraj MCP server (486; a Codex/DSH/Pi Main's)" ;;
    *"graphtraj.runtimes.native_entry dsh"*) print "DSH native entry (481; a DSH Main's)" ;;
    *"$HOSTCFG"*) print "Main's Claude host" ;;
    *" serve "*|*" serve") print "a host (member's or other project)" ;;
    *) print "other" ;;
  esac
}
# 492: process states (ps stat), only to recognise zombies (stat Z) and the timers' children.
# A zombie runs no code and holds no files: information only, never BLOCKING, never signalled.
typeset -A PSTAT PPARENT
ps_states() { local l w; PSTAT=(); PPARENT=()
  for l in ${(f)"$(ps -axww -o pid=,ppid=,stat= 2>/dev/null)"}; do w=(${=l}); [[ ${w[1]:-} == <-> ]] && { PSTAT[${w[1]}]=${w[3]:-?}; PPARENT[${w[1]}]=${w[2]:-?}; }; done; }
# 497 (490 + known interference): every budget_idle_timer with pid, ppid, stat, start time, executable (production
# .venv-runtime or other), session directory, token prefix and children with stat; classed old/new against I's
# install window once I has recorded it. Read only; never signals.
install_window() { [[ -s $R/I-install-start.epoch && -s $R/I-install-end.epoch ]] && print -r -- "$(<$R/I-install-start.epoch) $(<$R/I-install-end.epoch)"; }
timer_list() {   # $1 = file to keep the ps listing in
  local f=${1:-$R/timers-ps.txt}
  LC_ALL=C ps -axww -o pid=,ppid=,stat=,lstart=,command= > $f 2>&1   # C locale: lstart in English (parsed)
  $CONDA -I $SD/timers497.py list $f $RT ${=$(install_window)}
}
guard() {
  local listing rc line words hits=() timers=() tpids=() zombies=() marked
  listing=$(ps -axww -o pid=,etime=,command= 2>&1); rc=$?
  if (( rc != 0 )) || [[ -z $listing ]]; then
    print "无法列出进程（ps rc=$rc: ${listing[1,120]}），拒绝继续。在普通 Terminal 里运行本步。"; return 2
  fi
  ps_states
  for line in ${(f)listing}; do
    words=(${=line})
    [[ $line == *"-m graphtraj.execution.budget_idle_timer"* ]] && tpids+=(${words[1]})
  done
  for line in ${(f)listing}; do
    words=(${=line})
    [[ ${words[1]} == $$ ]] && continue
    if [[ ${PSTAT[${words[1]}]:-} == *Z* ]]; then zombies+=("${line[1,160]}"); continue; fi
    if [[ $line == *"-m graphtraj.execution.budget_idle_timer"* ]]; then timers+=("${line[1,200]}"); continue; fi
    if [[ $line == *"$RT/"* || $line == *"$HOSTCFG"* || ( -n $MAIN && $line == *"$MAIN"* ) ]]; then
      if (( ${tpids[(Ie)${PPARENT[${words[1]}]:-x}]} )); then
        # A live child of a timer: a parent Worker that a budget delivery started. It runs code under $RT, so it
        # blocks like any Worker. Old timers do not collect it when it ends (490 fixed that only in new timers).
        hits+=("[$(kind_of $line); child of budget_idle_timer ${PPARENT[${words[1]}]}] ${line[1,200]}")
      else
        hits+=("[$(kind_of $line)] ${line[1,200]}")
      fi
    fi
  done
  print "guard: budget_idle_timer processes (NON-BLOCKING; never signalled; README 3(a)):"
  timer_list | sed 's/^/guard: /'
  print "guard: zombies (ps stat Z; information only: no code runs, no files held; never signalled): ${#zombies}"
  (( ${#zombies} )) && print -l -- "  "$zombies
  if (( ${#tpids} )); then
    print "guard: the timers themselves never make I refuse. Only a LIVE child of a timer under $RT is BLOCKING (listed below as 'child of budget_idle_timer'); this script never signals a timer or its child — if one stays, USER decides (wait, or Ctrl-C and tell Main)."
  fi
  marked=$(ps -E -axww -o pid=,command= 2>/dev/null | grep -F 'GRAFTLING_MEMBER_RUN=' | grep -vF 'grep' | awk '{print $1}' | tr '\n' ' ')
  print "guard: 450 marked processes (information): ${marked:-none}"
  (( ${#hits} == 0 )) && { print "guard: BLOCKING 0 — 没有成员或 host 在使用 $RT。"; return 0; }
  print "guard: BLOCKING ${#hits} 个进程在使用 $RT（或是 Main ${MAIN:-?}）:"
  print -l -- "  "$hits
  print "自行查找: ps -axww -o pid,ppid,etime,command | grep -F .venv-runtime"
  return 1
}

# USER's Terminal only: wait (never kill) until no BLOCKING process remains. $1 says what Ctrl-C leaves.
wait_idle() {
  local g
  while true; do
    guard; g=$?
    (( g == 0 )) && return 0
    (( g == 2 )) && return 2
    local act=$(active_tasks)
    print "$(date +%T) 正在等待：可能有成员在运行的 Task（${act//, /、}）的成员还在运行（上面列出的 BLOCKING 进程）。不要结束（kill）这些进程；它们结束后本步自动继续。"
    print "         Waiting for members of Tasks that may run now ($act), listed above as BLOCKING. Do not kill them; this step continues by itself."
    print "         Ctrl-C 可以安全放弃：$1"
    sleep ${ADOPT515_WAIT:-20}
  done
}

step_00() {
  local C=$(claude_bin)
  mkdir -p $BASE/scratch
  say "shell (expect zsh) and PATH head"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"; print -l -- ${path[1,4]}
  print "pnpm: $(command -v pnpm) | Node spawn: $(node -e 'const r=require("child_process").spawnSync("pnpm",["--version"],{encoding:"utf8"}); console.log(r.error ? "FAILED "+r.error.code : "OK "+r.stdout.trim())' 2>&1)"
  say "418: inherited GRAFTLING_CLAUDE_HOST_* / GRAPHTRAJ_CLAUDE_HOST_* (name=path; unset for every child command of this script)"
  (( ${#INHERITED_REPORT} )) && print -l -- "inherited: "$INHERITED_REPORT || print "inherited: none"
  credential_names
  say "isolated project $VPROJECT: own git, own .graphtraj (setup by production graphtraj; Vc regenerates its entries), own settings (489)"
  vproject_init $RT/bin/graphtraj && isolation $RT/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  say "Claude Code version installed now (recorded once in $BASE/cc.version; later steps compare)"
  if [[ ! -s $BASE/cc.version ]]; then $(claude_bin) --version 2>&1 | head -1 > $BASE/cc.version; fi
  CC_EXPECT=$(<$BASE/cc.version); print -r -- "Claude Code installed: $CC_EXPECT"
  say "Claude answers from the isolated $VPROJECT (expect model $MODEL, logged in, no Harness AGENTS.md, not the prompt echoed; 489)"
  cv
  ask_model MODEL-OK 00-model || { print "STOP: claude -p answer check failed (above): no answer, prompt echo, or the Harness AGENTS.md loaded (489). If it says login/API key: USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "484/486: production agents control records before the install (states and notification fields; read only)"
  $CONDA -I $SD/ctl497.py snap $H $CTL/00.json
  say "490 / known interference: every budget_idle_timer now (listed only, never signalled)"; timer_list $R/00-timers-ps.txt
  say "production entry, read only: graphtraj task graph --task-id $TASK_ID (the Task graph Main's tasks tool reads; expect 503 listed, ready, not stopped)"
  (cd $H && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $RT/bin/graphtraj task graph --task-id $TASK_ID) > $R/00-graph.txt 2>&1
  print "task graph rc=$? lines=$(wc -l < $R/00-graph.txt) | Task $TASK_ID named: $(grep -cE "(^|[^0-9])$TASK_ID([^0-9]|\$)" $R/00-graph.txt)"
  print "Task $TASK_ID lines naming ready/status (information; expect ready or active):"; grep -E "(^|[^0-9])$TASK_ID([^0-9]|\$)" $R/00-graph.txt | grep -iE 'ready|status|active' | head -4
  say "production versions now (expect graphtraj 0.1.0 and graftling $GOLDVERSION, 503's; pip check clean)"
  $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  $RT/bin/python -m pip check --disable-pip-version-check; print "pip check rc=$?"
  say "plugin files and hashes"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  grep -nE '^const (PLUGIN|SERVER|PREFIX)' $PDIR/hooks/host_context.mjs | sed 's/^/production copy: /'
  say "entry files (hashes; .mcp.json servers now: expect '$OLDS' only, 503's)"; shasum -a 256 $ENTRIES; tree mcp $H/.mcp.json
  mcp_keys $H/.mcp.json before
  say "Main-owned .claude/settings.local.json (read only; Main removes '$OLDS' after the restart)"; settings_view $H/.claude/settings.local.json
  say "backup must be absent; 503's backup $OLDBASE/backup is listed, never touched"
  ls -d $BK 2>&1; ls -ld $OLDBASE/backup 2>&1; ls -l $OLDBASE/backup/COMPLETE 2>&1; [[ -e $OLDBASE/backup/COMPLETE ]] && print "503 backup COMPLETE marker: present" || print "503 backup COMPLETE marker: absent"
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "production holds 503's 6115c724 + graftling $GOLDVERSION: the 515 markers must be absent now"; $CONDA -I $SD/markers.py $(site) absent | tail -1
  say "395 layout now (information)"
  $RT/bin/python -I $SD/onegraft.py $RT $GOLDVERSION | grep -E '^CHECK|layout:'
  say "Tasks whose members may run now (status not integrated): $(active_tasks)"
  say "running Task members (I waits for them)"; (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | tee $R/00-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/00-members.txt) (other Tasks' members may run now; I waits for them)"
  say "Task $TASK_ID members (Rs resumes the Leader and the Engineer after M; they must be idle during I)"; grep -E "(^|[^0-9])$TASK_ID([^0-9]|\$)" $R/00-members.txt || print "none listed"
  say "N needs role opus_coding_team.advisor for Task $TASK_ID: the role and the role_tree lines naming it (464 dispatched it)"
  grep -nE 'opus_coding_team|advisor' $H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) 2>&1 | grep -iE 'advisor' | head -12
  say "Task $TASK_ID ready for N's root dispatch: Team 1 active, budget not stopped (expect stopped: false)"
  grep -E '^(stopped|corrections|allowance_minutes):' $H/.graphtraj/core/state/tasks/$TASK/execution-budget.yml
  grep -E 'status|state' $H/.graphtraj/core/state/tasks/$TASK/teams/1/team.yml | head -5
  say "current Claude Main Session"; local id=$(detect_main)
  if [[ -n $id ]]; then print -r -- $id > $BASE/main.session; MAIN=$id; print "MAIN=$id (saved to $BASE/main.session)"; else print "MAIN NOT FOUND"; fi
  # Information only (492 R1 correction): Main's own host is BLOCKING here; step_00 fails only through its STOP returns.
  say "processes using the venv now, classified (information only; Main's host is expected here)"
  guard || print "guard: BLOCKING at 00 is information only (Main's own host is expected here; I waits for members)"
  return 0
}

step_B() {
  rm -rf $SRC $GSRC $N; mkdir -p $SRC $GSRC $N   # this commit's own directories only
  say "graftling repository $G (read only): tag $GTAG, main, working tree state (information)"
  local gc=$(git -C $G rev-parse -q --verify "$GTAG^{commit}" 2>/dev/null) gm=$(git -C $G rev-parse -q --verify main 2>/dev/null)
  print "$GTAG^{commit}: ${gc:-NOT FOUND} | tag object: $(git -C $G rev-parse -q --verify refs/tags/$GTAG 2>/dev/null || print none) | type: $(git -C $G cat-file -t $GTAG 2>/dev/null)"
  print "main: ${gm:-NOT FOUND} | main points at $GTAG: $([[ -n $gc && $gc == $gm ]] && print yes || print NO)"
  print "working tree changes (not used: B reads only git archive $GTAG): $(git -C $G status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  [[ $gc == ${GCOMMIT}* ]] && print "$GTAG peels to $GCOMMIT…: yes" || { print "STOP: $GTAG^{commit} is ${gc:-missing}, not $GCOMMIT… (395's tag). Main asks the Leader."; return 1; }
  git -C $G archive $GTAG | tar -x -C $GSRC || return 1
  git -C $WT archive $TARGET | tar -x -C $SRC || return 1
  [[ -e $SRC/src/graftling ]] && { print "STOP: $TARGET still carries src/graftling"; return 1; }
  print "graphtraj archive carries no src/graftling: yes"
  print "graftling archive version line: $(grep -E '^__version__' $GSRC/src/graftling/__init__.py)"
  # setuptools >= 77 (graphtraj's pyproject since 395: license-files); Conda's is used, as in 395's step I. Not modified.
  say "build with $CONDA (setuptools $($CONDA -c 'import setuptools; print(setuptools.__version__)'); --no-index --no-deps --no-build-isolation)"
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $GSRC/src/graftling || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $SRC || return 1
  say "wheels and sha256 (expect graphtraj-0.1.0 and graftling-$GVERSION)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT; print "$GTAG ${gc}" > $N/GRAFTLING
  [[ $(wheel_of graphtraj) == *graphtraj-0.1.0-* && $(wheel_of graftling) == *graftling-$GVERSION-* ]] || { print "wheel 名称不符"; return 1; }
  local gv=$(unzip -p $(wheel_of graftling) '*.dist-info/METADATA' | sed -n 's/^Version: //p')
  print "graftling wheel version: $gv"; [[ $gv == $GVERSION ]] || { print "STOP: graftling wheel version $gv"; return 1; }
  local req=$(unzip -p $(wheel_of graphtraj) '*.dist-info/METADATA' | grep -E '^Requires-Dist: graftling')
  print "graphtraj $req"
  [[ $req == *'graftling'*'>=0.6.0'* && $req == *'<0.7'* ]] || { print "STOP: graphtraj does not require graftling>=0.6.0,<0.7"; return 1; }
  print "graphtraj wheel carries graftling/: $(unzip -Z1 $(wheel_of graphtraj) | grep -c '^graftling/') files (expect 0)"
  [[ $(unzip -Z1 $(wheel_of graphtraj) | grep -c '^graftling/') == 0 ]] || return 1
  say "no build/ or __pycache__ inside the wheels (expect leaked: 0)"
  local leaked=$(for f in $N/*.whl(N); do unzip -Z1 $f; done | grep -cE '(^|/)(build|__pycache__)/')
  print "leaked: $leaked"; [[ $leaked == 0 ]]
}

scratch_venv() {
  rm -rf $VV; $CONDA -m venv $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  local S=$(site) D=($VV/lib/python*/site-packages(N)); D=${D[1]}
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/ || return 1
  $VV/bin/python -m pip check --disable-pip-version-check; print "scratch venv pip check rc=$?"
  $VV/bin/python -I -c 'import graftling, graphtraj.runtimes.claude.host as h; print("graftling", graftling.__version__, h.__file__)'
}

step_V() {
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 步骤的 wheel，先运行 B。"; return 1; }
  (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  local rc=0 C=$(claude_bin) P=$VV/bin/python
  say "scratch venv: new wheels plus production's click, yaml, websockets"; scratch_venv || return 1
  say "candidate plugin: new code writes into a scratch copy of production's plugin"
  rm -rf $VPL; mkdir -p $VPL; cp -Rp $PDIR $VPL/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name differs=0; : > $R/V-plugin.diff
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; differs=1; diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  say "source diff of the Claude hook and plugin sources: graftling $GOLDTAG..$GTAG and graphtraj runtimes/claude ${OLD[1,8]}..${TARGET[1,8]} (information; 514 changes the server name)"
  { git -C $G diff --stat $GOLDTAG $GTAG -- src/graftling/claude src/graftling/claude-plugin
    git -C $WT diff --stat $OLD $TARGET -- src/graphtraj/runtimes/claude; } > $R/V-source.diff 2>&1
  cat $R/V-source.diff
  # 515: the plugin is expected to change: host_context.mjs names the server (514). Any change outside the
  # SERVER/PREFIX lines and plugin.json's version is listed for Main; it is not a STOP by itself.
  local other=$(grep -E '^[<>]' $R/V-plugin.diff | grep -vE '^[<>] const (SERVER|PREFIX) |"version"' | wc -l | tr -d ' ')
  if (( differs )); then print "plugin bytes change ($(grep -c '^[<>]' $R/V-plugin.diff) diff lines; lines other than const SERVER/PREFIX and \"version\": $other). Expected (514): one hooks trust dialog may appear at resume."
  else print "plugin unchanged: no plugin/hooks trust dialog is expected at resume (NOT expected for 515: the SERVER line should change)."; fi
  grep -E '^[<>]' $R/V-plugin.diff | head -12
  say "local form kept: 'const PLUGIN = null'; candidate names the server graphtraj"
  grep -nE '^const (PLUGIN|SERVER|PREFIX)' $VP/hooks/host_context.mjs | sed 's/^/candidate: /'
  grep -q '^const PLUGIN = null;' $VP/hooks/host_context.mjs || { print "STOP: candidate is not the local-copy form"; rc=1; }
  grep -q '^const SERVER = "graphtraj";' $VP/hooks/host_context.mjs && print "CHECK 515 candidate host_context.mjs const SERVER = \"graphtraj\": PASS" \
    || { print "CHECK 515 candidate host_context.mjs const SERVER = \"graphtraj\": FAIL (STOP)"; rc=1; }
  say "515 graftling code: wheel vs the $GTAG git archive (gate), and vs production's $GOLDVERSION (CODE files listed; expected)"
  $CONDA -I $SD/graftcode.py $(wheel_of graftling) $(site) $GSRC/src > $R/V-graftcode.txt; local gcr=$?
  grep -vE '^    ' $R/V-graftcode.txt; (( gcr == 0 )) || { print "STOP: the graftling wheel differs from git archive $GTAG ($R/V-graftcode.txt). Main gives it to the Leader before I."; rc=1; }
  say "515 markers (514 server name, graftling 0.6.0): present in the candidate, absent in production"
  local VS=($VV/lib/python*/site-packages(N))
  $CONDA -I $SD/markers.py $VS[1] present || rc=1
  $CONDA -I $SD/markers.py $(site) absent || rc=1
  say "395 layout in the scratch venv (one graftling from the wheel) and node resolution of graftling.mjs"
  $P -I $SD/onegraft.py $VV $GVERSION || rc=1
  node_resolve $VV || rc=1
  say "claude plugin validate: baseline, candidate"; cv
  local base=$($C plugin validate $PDIR 2>&1 | tee -a $R/V-validate.txt | grep -c '✘') cand=$($C plugin validate $VP 2>&1 | tee -a $R/V-validate.txt | grep -c '✘')
  print "✘ lines: baseline=$base candidate=$cand"; (( cand > base )) && rc=1
  say "entry files: what configuration --write would change; predictions only"
  rm -rf $VE; $P -I $SD/adopt_plugin.py entries $H $C $RT/bin/python $VE || rc=1
  say "read only against the real project: archives, configuration, roles; Task graph on an APFS clone of state"
  touch $W/V-marker-$C8; [[ -e $BASE/vstate ]] && chmod -R u+w $BASE/vstate && rm -rf $BASE/vstate; mkdir -p $BASE/vstate
  local part; for part in tasks worldline; do [[ -d $H/.graphtraj/core/state/$part ]] && cp -cRp $H/.graphtraj/core/state/$part $BASE/vstate/; done
  $P -I $SD/adopt_plugin.py readcheck $H $BASE/vstate || rc=1
  chmod -R u+w $BASE/vstate; rm -rf $BASE/vstate
  say "recorded hashes (I checks these did not change before it writes)"; shasum -a 256 $ENTRIES | tee $W/entries-$C8.sha256
  return $rc
}


vc_setup() {
  local G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  vproject_init $G || return 1
  say "isolation (candidate code; required)"; isolation $VV/bin/python || return 1
  # Always regenerate: the scratch plugin and entries come from the new wheels.
  (cd $VPROJECT && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $(claude_bin) --write) || return 1
  vsettings   # 489: re-merged after configuration --write
  say "515: the isolated project's .mcp.json has only graphtraj (required)"; mcp_keys $VPROJECT/.mcp.json || return 1
  say "489: the candidate project's claude -p answers without the Harness AGENTS.md and not as a prompt echo (required)"
  ask_model VC-OK Vc-model --mcp-config $VPROJECT/.mcp.json --strict-mcp-config || { print "STOP: Vc answer check failed (above)"; return 1; }
}

vc_stream() {
  local C=$(claude_bin)
  say "claude -p calls tasks discover and agents status (no dialog)"; cv
  print -r -- 'Call mcp__graphtraj__tasks once with {"action":"discover"} and mcp__graphtraj__agents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 300 $C -p --model $MODEL --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__tasks,mcp__graphtraj__agents) > $R/Vc-stream.jsonl
  print "claude rc=$?"
  $CONDA -I -c 'import json,sys
names = None
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "system" and d.get("subtype") == "init":
        names = [p.get("name") if isinstance(p, dict) else p for p in d.get("plugins") or []]
        break
print("plugins in init:", names)
print("graphtraj-claude-host loaded:", "YES" if names and any("graphtraj-claude-host" in str(n) for n in names) else "NO")' $R/Vc-stream.jsonl
  say "515: init lists mcp server graphtraj only and the new tool names, no mcp__agents__*"
  local irc=0; $CONDA -I $SD/rec515.py init $R/Vc-stream.jsonl || irc=1
  tree stream $R/Vc-stream.jsonl mcp__graphtraj__tasks mcp__graphtraj__agents || return 1
  (( irc == 0 )) || return 1
  # Information only: a missing host.log must not turn a passed Vc into a failure (492 R1 audit).
  say "host.log tail"; tail -n 20 $VPROJECT/.graphtraj/claude-host/host.log || print "no host.log (information)"
  return 0
}

do_backup() {
  mkdir -p $BK && chmod 700 $BK || return 1
  date '+backup start %F %T'
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/*.py $BK/tools/ || return 1
  print -r -- $MAIN > $BK/tools/main.session
  say "manifest, then whole venv copy (cp -Rp)"; tree manifest $RT $BK/venv.manifest || return 1
  cp -Rp $RT $BK/venv || return 1; tree compare $BK/venv.manifest $BK/venv || return 1
  say "plugin copy"; tree manifest $PDIR $BK/plugin.manifest || return 1; cp -Rp $PDIR $BK/plugin || return 1
  say "entry files: copies (mode 600) and hashes"; mkdir -p $BK/entries
  local f; for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || return 1; done
  # 448's `chmod 600 $BK/entries/*` matched nothing: every name starts with '.'. (D) includes dot files.
  chmod 600 $BK/entries/*(D) || return 1
  local bad=0; for f in $BK/entries/*(D); do stat -f '%Sp %N' $f; [[ $(stat -f '%Sp' $f) == -rw------- ]] || bad=1; done
  (( bad == 0 )) || { print "STOP: an entry copy is not -rw-------"; return 1; }
  shasum -a 256 $ENTRIES | tee $BK/entries.sha256
  say "archive clones (cp -cRp) and per-file version and sha256"
  mkdir -p $BK/archives
  if [[ -d $SESS ]]; then cp -cRp $SESS $BK/archives/sessions || return 1; else mkdir -p $BK/archives/sessions; fi
  tree archives $SESS $BK/archives.manifest || return 1
  for f in $ALSO; do [[ -r $f ]] && shasum -a 256 $f; done | sort -u > $BK/also.sha256
  touch $BK/COMPLETE; ls -ld $BK; date '+backup end %F %T'
}

do_install() {
  local S=$(site) P=$RT/bin/python w
  say "wheels (expect 2 x OK)"; cat $N/COMMIT; (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  [[ $(<$N/COMMIT) == $TARGET ]] || { print "COMMIT 不是目标提交"; return 1; }
  say "entry files still as V saw them (expect 3 x OK)"; shasum -a 256 -c $W/entries-$C8.sha256 || { print "入口文件在 V 之后被改过；重新运行 V。"; return 1; }
  say "484: production agents control records right before pip (N484 compares against this snapshot)"
  $CONDA -I $SD/ctl497.py snap $H $CTL/I.json || return 1
  say "install both wheels (graftling $GOLDVERSION -> $GVERSION from the $GTAG wheel; graphtraj 0.1.0 over the same version: --force-reinstall)"
  date +%s > $R/I-install-start.epoch   # 490: timers started before this are old (listed, not judged)
  $P -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  say "installed files vs the new wheels, file by file (versions are the same numbers as before)"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS|^FAIL' $R/I-verify.txt; (( rc == 0 )) || return 1
  say "entry scripts of both wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of graftling); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graftling.control as c, graftling.tool_descendants as td, graftling.claude.execution as ce, graphtraj.execution.runner_worker as rw, graphtraj.execution.runner_control as rc, graftling.pi.execution as pe, graftling.dsh.execution as de, graftling.codex.managed_session as cm; print("graftling", graftling.__version__); print(h.__file__); print("457", c._stop_escaped.__name__, "| 459 SAMPLE_SECONDS", td.SAMPLE_SECONDS, td.DescendantSampler.__name__, "| 459 correction", td.shown_command.__name__); print("460", rw.TOOL_PROCESSES_RECORD, rc._reclaim_tool_processes.__name__, "| 461", pe.PiExecution.__name__, "| 462", cm.CodexManagedExecution._reclaim_tools.__name__, "| 463", de.DshExecution._stop_escaped.__name__); assert graftling.__version__ == "0.6.0"' || return 1
  $P -c 'import inspect, graphtraj.runtimes.claude.execution as gce, graphtraj.runtimes.codex.access as ca, graphtraj.graph.task_graph as tg, graphtraj.execution.runner_launch as rl; print("465 Claude member settings call project_history_files:", "project_history_files" in inspect.getsource(gce.ClaudeExecution), "| Codex development reads history param:", "history" in inspect.signature(ca.project_development_reads).parameters); print("469", tg.UnknownTask.__name__, tg._load_task_state.__name__, rl._RegisteredTaskNames.__name__)' || return 1
  $P -c 'import inspect, graftling.sessions.reading as rd, graphtraj.interfaces.agents as ag, graftling.sessions.archive as ar, graftling.control as c, graphtraj.execution.runner_worker as rw; print("466 session_read DEFAULT_COUNT", rd.DEFAULT_COUNT, "| agents _member_session:", ag.GraphTrajAgents._member_session.__name__); print("468 archive _identity", ar._identity.__name__, "| BUDGET_SAMPLE_SECONDS", rw.BUDGET_SAMPLE_SECONDS); print("477 take_push", c.AgentControl.take_push.__name__, "| _waited", c._waited.__name__)' || return 1
  $P -c 'import inspect, graftling.control as c, graphtraj.interfaces.mcp as m, graphtraj.runtimes.dsh.main_entry as me, graphtraj.runtimes.codex.finalize as f, graphtraj.runtimes.pi.pi_adapter as pa; print("481 main_entry main_patch", me.main_patch.__name__, "| 484 _push_error", c._push_error.__name__); print("486 stop_owned_agents", m.stop_owned_agents.__name__, "| _terminated", m._terminated.__name__); print("485 finalize imports CHECKER_PERMISSION_PROFILE:", hasattr(f, "CHECKER_PERMISSION_PROFILE"), "| 480 member_policy write_paths:", "write_paths" in inspect.getsource(pa.member_policy)); print("487 wait timeout pops its waiter:", "waiters.pop(token, None)" in inspect.getsource(c.AgentControl.wait))' || return 1
  $P -c 'import inspect, graphtraj.execution.runner_process as rp, graphtraj.execution.budget_idle_timer as bt, graphtraj.execution.runner_cleanup as rcl, graftling.claude.host as ch, graftling.tool_descendants as td, graphtraj.interfaces.agents as ag; print("488 _worker_arguments", rp._worker_arguments.__name__, "| _process_ended", rp._process_ended.__name__); print("490 _work_ended", bt._work_ended.__name__, "| _collect_ended_children", bt._collect_ended_children.__name__, "| SLICE_SECONDS", bt.SLICE_SECONDS, "| cleanup uses process_is_zombie:", "process_is_zombie" in inspect.getsource(rcl)); print("494 Claude host receiver defers_push:", "receive.defers_push = True" in inspect.getsource(ch), "| hold thread started in the lock:", "_HOLDS.append(thread)\n            thread.start()" in inspect.getsource(ag)); print("495 argv refreshed each sample:", "shown_command(argv)}" in inspect.getsource(td))' || return 1
  $P -c 'import inspect, graftling.control as c, graftling.tool_descendants as td; print("496 has_exited", td.has_exited.__name__, "| control._alive uses has_exited:", "has_exited(pid)" in inspect.getsource(c._alive))' || return 1
  $P -c 'import inspect, graftling.tool_descendants as td; print("498 verdicts", td.OURS, td.FOREIGN, td.PROVISIONAL, td.LATER, "|", td._verdict.__name__, td._executed.__name__, td._platform.__name__, td._beneath.__name__, td.DescendantSampler._settle.__name__, "| unsettled only under remaining:", "sorted({*alive, *unsettled})" in inspect.getsource(td.stop_tool_processes))' || return 1
  $P -c 'import importlib.metadata as md, pathlib, sys, graftling, graphtraj; gs = pathlib.Path(graftling.__file__).parent; print("395 layout graftling", graftling.__version__, "| distributions", sum(1 for d in md.distributions() if (d.metadata["Name"] or "").lower() == "graftling"), "| beside graphtraj:", gs.parent == pathlib.Path(graphtraj.__file__).parent.parent, "| graftling.mjs:", (pathlib.Path(graphtraj.__file__).parent / "runtimes/graftling.mjs").is_file(), "| graphtraj requires", [r for r in md.requires("graphtraj") if r.startswith("graftling")]); assert graftling.__version__ == "0.6.0"' || return 1
  say "503 markers in the installed site-packages (expect PASS 7/7)"; $CONDA -I $SD/markers.py $S present || return 1
  say "395 layout in production: exactly one graftling, from the wheel file; no source link (expect 503 layout: PASS)"
  $P -I $SD/onegraft.py $RT $GVERSION || return 1
  say "395: production's graftling.mjs resolves graftling to the sibling directory (empty environment: no python fallback)"
  node_resolve $RT || return 1
  date +%s > $R/I-install-end.epoch   # 490: timers started after this run the installed 4ad22e90 code (new)
  say "515: configuration --write from the new installation (514: writes the graphtraj entry and drops its own old agents entry)"
  (cd $H && clean $P -m graphtraj.runtimes.claude.host configuration --write --project $H --claude $(claude_bin)) > $R/I-configuration.txt 2>&1
  local crc=$?; print "configuration --write rc=$crc (output lines: $(wc -l < $R/I-configuration.txt); kept in $R/I-configuration.txt)"; (( crc == 0 )) || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  diff -r $BK/plugin $PDIR > /dev/null && print "plugin bytes as before the install: no trust dialog expected (NOT expected for 515)" || print "plugin bytes CHANGED from before the install (expected: const SERVER = \"graphtraj\"): one hooks trust dialog may appear at resume"
  say "515 CHECKs after configuration --write"
  mcp_keys $H/.mcp.json || return 1
  grep -q '^const SERVER = "graphtraj";' $PDIR/hooks/host_context.mjs && print 'CHECK 515 host_context.mjs const SERVER = "graphtraj": PASS' \
    || { print 'CHECK 515 host_context.mjs const SERVER = "graphtraj": FAIL'; return 1; }
  if cmp -s $H/.claude/settings.local.json $BK/entries/.claude__settings.local.json; then print "CHECK 515 settings.local.json bytes unchanged by configuration --write: PASS"
  else print "CHECK 515 settings.local.json bytes unchanged by configuration --write: CHANGED (merge of GraphTraj's env keys; diff below with values hidden; R restores the backup copy; tell Main)"; fi
  settings_view $H/.claude/settings.local.json
  local f; for f in $ENTRIES; do
    if cmp -s $f $BK/entries/${${f#$H/}//\//__}; then print "bytes unchanged: ${f#$H/}"
    else print "changed: ${f#$H/} (before -> after, secret-like values hidden)"
      $CONDA -I $SD/adopt_tree.py redactjson $BK/entries/${${f#$H/}//\//__} > $BK/diff.before
      $CONDA -I $SD/adopt_tree.py redactjson $f > $BK/diff.after; diff $BK/diff.before $BK/diff.after; rm -f $BK/diff.before $BK/diff.after; fi
  done
  tree mcp $H/.mcp.json
  say "also unchanged (information; any FAILED means another writer: tell Main)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  return 0
}

step_R() {
  local KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S) rc=0 f
  date '+R start %F %T'; mkdir -p $KEEP
  say "before restoring: how the venv differs from the pre-install manifest"; tree compare $BK/venv.manifest $RT | tail -1
  # 515: graftling 0.5.2 and 0.6.0 differ in code, but not in the Session archive code (graftling/sessions/; v0.5.2..v0.6.0
  # changes no file there). Checked here on the installed files, before the old venv comes back.
  local ARCH_NOW=($RT/lib/python*/site-packages/graftling/sessions(N/)) ARCH_OLD=($BK/venv/lib/python*/site-packages/graftling/sessions(N/))
  if [[ -n ${ARCH_NOW[1]:-} && -n ${ARCH_OLD[1]:-} ]]; then
    ARCH_DIFF=$(diff -rq -x __pycache__ ${ARCH_OLD[1]} ${ARCH_NOW[1]} 2>&1 | wc -l | tr -d ' ')
    print "graftling/sessions (archive writer/reader) installed vs backup: $ARCH_DIFF differing files$( (( ARCH_DIFF == 0 )) && print ' (archives written since the install are read by the restored code)' || print ' (NOT the same: tell Main before resuming; the archives stay as they are)')"
  else print "graftling/sessions not found in one of the trees: archive compatibility not checked (tell Main)"; fi
  say "venv restored whole from the backup"; rm -rf $RT; cp -Rp $BK/venv $RT || return 1
  say "venv equals pre-install bytes? (expect SAME differences=0)"; tree compare $BK/venv.manifest $RT || rc=1
  say "plugin restored; the current one kept"; [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; mkdir -p ${PDIR:h}; cp -Rp $BK/plugin $PDIR || return 1
  tree compare $BK/plugin.manifest $PDIR || rc=1
  say "entry files restored from the backup copies; the current ones kept"
  mkdir -p $KEEP/entries
  for f in $ENTRIES; do
    local saved=$BK/entries/${${f#$H/}//\//__}
    if cmp -s $f $saved; then print "already as before: ${f#$H/}"; else cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $saved $f || rc=1; print "restored: ${f#$H/}"; fi
  done
  shasum -a 256 -c $BK/entries.sha256 || rc=1
  say "archives stay (see the graftling/sessions line above: the archive code of $GOLDVERSION and $GVERSION is compared file by file); versions (information)"; tree versions $SESS
  say "a stale channel file would make the restored host refuse with host-busy"
  local CH=$H/.graphtraj/claude-host/live/channel.json
  if [[ -e $CH ]]; then mv $CH $KEEP/channel.json; print "moved out: $CH"; else print "no channel file"; fi
  say "versions and pip check"; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'; $RT/bin/python -m pip check --disable-pip-version-check || rc=1
  return $rc
}

# Nr: the production check of criterion 3, read only.
#   child record: <swarm>/control/agents/<agent>.json (graftling/control.py), name n497, parent = member alias;
#     selection.configuration and selection.model (455, control.py create), executions[*]: id, state, outcome, error,
#     notification.
#   member record: found BY ALIAS in <runner>/sessions/<alias>/mapping.yml (with execution.yml, the member's own end),
#     else a retired one under the Task's teams/*/traces/<alias>/runner/session.yml (retirement.mapping).
#   archive: <swarm>/sessions/<session>/session.jsonl. 453's lesson: raw lines naming an id also count tool results and
#     the member's quotes. Nr counts only events of type user/message that name the execution and source graphtraj
#     (the delivered parent inputs); anything but exactly 1 is CHECK BY HAND with Main's session_read count by event type.
nr_read() {
  $CONDA -I - $H $SESS $TASK $R $CHILD <<'PY2'
import json, sys
from pathlib import Path
import yaml
h, sess, task, raw, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), sys.argv[5]
def check(name, ok, detail=''):
    print(f"CHECK {name}: {ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')}{(' (' + detail + ')') if detail else ''}")
roots = sorted({p.parent for g in ('.graphtraj/swarm/control/agents/*.json', '.graphtraj/*/control/agents/*.json', '.graphtraj/core/runner/control/agents/*.json') for p in h.glob(g)})
print('record directories:', [str(r) for r in roots] or 'NONE')
child = None
for r in roots:
    for p in r.glob('*.json'):
        try: d = json.loads(p.read_text())
        except Exception: continue
        if d.get('name') == name and (child is None or p.stat().st_mtime > child_path.stat().st_mtime): child, child_path = d, p
if child is None:
    print(f'NO {name} child found. Did N run, and did the member create it with that name?'); sys.exit(1)
sel = child.get('selection') or {}
exs = child.get('executions') or []
print(f"child {name}: agent={child.get('agent')} parent={child.get('parent')} executions={len(exs)} retired={child.get('retired_at') is not None} record={child_path}")
print(f"  stored selection: configuration={sel.get('configuration')!r} preset={sel.get('preset')!r} model={sel.get('model')!r} reasoning_effort={sel.get('reasoning_effort')!r}")
# 455
check('455 stored record: configuration and model not null', sel.get('configuration') is not None and sel.get('model') is not None,
      f"configuration={sel.get('configuration')!r} model={sel.get('model')!r}")
reply = raw / 'N-reply.txt'
if reply.is_file():
    text = reply.read_text(errors='replace')
    import re
    conf = re.findall(r'"configuration"\s*:\s*("[^"]*"|null)', text)
    model = re.findall(r'"model"\s*:\s*("[^"]*"|null)', text)
    check("455 create/status result quoted by the member: configuration and model not null",
          bool(conf) and bool(model) and 'null' not in conf and 'null' not in model, f"configuration values {conf[:4]} model values {model[:4]}")
else:
    check("455 create/status result quoted by the member", 'PENDING', f'save the member reply to {reply}')
# 452 (child side) and 449/451 notification
for ex in exs:
    err = (ex.get('error') or {}).get('code')
    print(f"  execution {ex.get('id')}: state={ex.get('state')} outcome={ex.get('outcome')} error={err} notification={ex.get('notification')}")
check('one child execution (create; 499 sends nothing else)', len(exs) == 1, f'{len(exs)}')
for ex in exs:
    err = (ex.get('error') or {}).get('code')
    check(f"452 child execution {ex.get('id')} ended completed, not owner-exited", ex.get('outcome') == 'completed' and err != 'owner-exited',
          f"outcome={ex.get('outcome')} error={err}")
    check(f"execution {ex.get('id')} notification delivered", ex.get('notification') == 'delivered', str(ex.get('notification')))
alias = child.get('parent')
mapping, where, sdir = {}, None, None
cands = [h / '.graphtraj/core/runner/sessions' / str(alias) / 'mapping.yml', h / '.graphtraj/runner/sessions' / str(alias) / 'mapping.yml']
cands += sorted(h.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/session.yml'))
for c in cands:
    if c.is_file():
        d = yaml.safe_load(c.read_text()) or {}
        mapping = d if c.name == 'mapping.yml' else ((d.get('retirement') or {}).get('mapping') or {})
        where, sdir = c, (c.parent if c.name == 'mapping.yml' else None); break
sid = mapping.get('session')
sid = sid.get('id') if isinstance(sid, dict) else sid
print(f"member {alias}: record={where} session={sid} task={mapping.get('task_id')} role={mapping.get('role')} execution={mapping.get('execution_id')}")
# 452 (member side): its execution ended and the end was recorded
end = {}
if sdir is not None and (sdir / 'execution.yml').is_file():
    end = yaml.safe_load((sdir / 'execution.yml').read_text()) or {}
print(f"  member end: execution.yml execution_id={end.get('execution_id')} outcome={end.get('outcome')} terminal_confirmed={end.get('terminal_confirmed')}")
check("452 member execution ended and recorded (execution.yml terminal, same execution as the mapping)",
      bool(end) and end.get('outcome') in ('completed', 'failed', 'interrupted') and end.get('execution_id') == mapping.get('execution_id'),
      f"outcome={end.get('outcome')}")
notice = raw / 'N-main-notice.txt'
check("452 member reported its end to Main (raw/N-main-notice.txt names completed)",
      ('PASS' if 'completed' in notice.read_text(errors='replace') else 'FAIL') if notice.is_file() else 'PENDING', str(notice))
# 449/451: exactly one delivered parent input per child execution
def _by_header(sid):
    out = []
    bare = str(sid).split(':', 1)[-1]
    for f in sess.glob('*/session.jsonl'):
        try: head = json.loads(f.open(errors='replace').readline())
        except (OSError, ValueError): continue
        head = head.get('header', head) if isinstance(head, dict) else {}
        hid = str(head.get('id', '')) if isinstance(head, dict) else ''
        if hid.split(':', 1)[-1] == bare and not (head.get('native') or {}).get('agentId'): out.append(f)
    return out
files = (_by_header(sid) if sid else [])[:1]
files = [f for f in files if f.exists()] or [f for f in sess.glob('*/session.jsonl') if exs and all(e.get('id') and e['id'] in f.read_text(errors='replace') for e in exs)]
for f in files:
    events = []
    for line in f.read_text(errors='replace').splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    for ex in exs:
        eid = ex.get('id')
        by_type = {}
        for e in events:
            s = json.dumps(e)
            if eid and eid in s:
                by_type[e.get('type')] = by_type.get(e.get('type'), 0) + 1
        inputs = [e for e in events if e.get('type') == 'user/message' and eid in json.dumps(e) and 'graphtraj' in json.dumps(e)
                  and not any(isinstance(i, dict) and i.get('type') == 'tool_result' for i in ((e.get('data') or {}).get('content') or []))]
        print(f"  archive {f.parent.name}: execution {eid}: events naming it by type {by_type}; user/message inputs naming it with graphtraj: {len(inputs)}")
        # 477: the member's wait took this end, so no notification input may follow (0). 451's 'one notice' is Main's.
        check(f"477 no parent input pushed for waited execution {eid}", 'PASS' if len(inputs) == 0 else
              f"CHECK BY HAND (count {len(inputs)}; tool results excluded? Main counts user/message notice deliveries with session_read)")
if not files: print('  archive: NOT FOUND (member Session archive)'); check('449/451 one parent input per execution', 'CHECK BY HAND (archive not found)')
print('MEMBER', alias or '')
print('SESSION', sid or '')
print('CHILD', child.get('agent') or '')
PY2
}

R_HINT="回退（USER，先在 Main 里 /exit）: zsh $BK/tools/steps.zsh R"

case $STEP in
help) print "顺序: 00 → B → V → S（复用 514 的全套结果，不运行测试）→ Vu（USER，一次：新路径 $VPROJECT 的信任框）→ Vc → Mpre → /exit Main → I（USER，等待成员结束）→ claude --continue → M → Mps → inbox → Rs（Main 恢复 Leader）→ Rsr → Nw（后台，只读）→ N → Nt（成员清退前）→ Nr → N484 → done → [Leader 接受 515] → T；任何时候列计时器: timers；备份完成后可回退: R。"
  print "USER 只做: Vu（信任框 'Yes, proceed'）、/exit Main、I、claude --continue（失败时 R）。其余都由 Main 运行。settings.local.json 的 enabledMcpjsonServers 由 Main 在重启后改（I 打印确切改法）。"
  next "zsh $THIS 00" ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE（scratch、vproject、main.session）与 $R。约 2 分钟。"
  # Keep the first run's 00.txt (a rerun would append to it): renamed once to 00-first.txt.
  [[ -e $R/00.txt && ! -e $R/00-first.txt ]] && mv $R/00.txt $R/00-first.txt && print "previous 00.txt kept as $R/00-first.txt"
  : > $R/00.txt   # later reruns start a fresh 00.txt
  logged $R/00.txt step_00 || { print "\n00 STOP（see the STOP line above / 见上面的 STOP 行）。把 $R/00.txt 交给 Main，不要继续。"; exit 1; }
  summary 00 "$(grep -E '^claude:|^state before I|ZSH_VERSION|Node spawn|inherited|answer|instruction files|echo of the prompt|plugins in init|control records|budget_idle_timer|timer pid|zombies|503 backup|Claude Code installed|^Version|pip check rc|production copy|markers expected|CHECK 503 layout|mcp.json servers|enabledMcpjsonServers|isolat|running lines|may run now|^stopped|status|MAIN=|MAIN NOT|volume ids|^guard|advisor' $R/00.txt)"
  print "成功: 'claude:' 行给出路径与版本（默认 claude，现为 $CC_EXPECT）；ZSH_VERSION 有值；'answer check (expect clean): OK'（answer 以 MODEL-OK 开头、models 含 $MODEL、is_error False、cc-plugin-agents-md loaded: NO、无 Harness AGENTS.md、不是 prompt 回显）；'control records snapshot 00.json'；计时器每个一行（照实记录，不发信号）；graphtraj 0.1.0 与 graftling $GOLDVERSION（503 安装的）；pip check rc=0；'markers expected absent: PASS (7/7)'（生产仍是 6115c724）；'task graph rc=0' 且 'Task $TASK_ID named' 不为 0；"
  print "  'isolation: OK'（$VPROJECT）；stopped: false 且 Team 1 active；roles 里有 opus_coding_team 的 advisor；'.mcp.json servers: [...'$OLDS'...]'（安装前，信息）与 'state before I (not a check …): .mcp.json has only graphtraj: not yet'（预期；不是失败，不要停；I 的 CHECK 515 .mcp.json 必须是 PASS）；'enabledMcpjsonServers: [...]'（信息）；$BK 'No such file'（503 的备份 $OLDBASE/backup 只列出，不动；'503 backup COMPLETE marker: present'）；'Claude Code installed: <版本>'；MAIN=<id>；Task $TASK_ID 的成员（Leader 与 Engineer）列出（I 期间应空闲）。"
  print "running lines 可以不为 0（其它 Task 的成员）；I 会等它们结束，不结束它们，不需要现在处理。计时器本身是 NON-BLOCKING，不影响安装；只有计时器的活子进程（预算送达启动的 Worker）在 \$RT 下时是 BLOCKING，由 USER 决定。"
  print "若 'inherited:' 列出名字：本脚本已对所有子命令 unset；记下它来自哪个项目（418 提醒）。"
  print "若 answer 有 login/API key 字样: USER 在 Terminal 运行 claude 登录后重跑 00。若 MAIN NOT FOUND 或 ps 被拒: 由 USER 在普通 Terminal 运行 00。"
  next "zsh $THIS B" ;;

B) cv; print "[B] Main. 两个仓库各构建一个 wheel（graftling: git -C $G archive $GTAG；graphtraj: git archive $TARGET；不联网、不改 Conda、不改 graftling 仓库和生产）。对话框: 无。< 2 分钟。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked|peels|^main:|\^\{commit\}|working tree|wheel version|Requires-Dist|carries' $R/B.txt)"
    print "成功: '$GTAG peels to $GCOMMIT…: yes'（并打印完整 sha 与 main 是否指向它）；graphtraj-0.1.0 与 graftling-$GVERSION 各一个 wheel 及 sha256；'graftling wheel version: $GVERSION'；'graphtraj Requires-Dist: graftling<0.7,>=0.6.0'；graphtraj wheel carries graftling/: 0；leaked: 0。"
    next "zsh $THIS V"
  else print "\nB 失败。不要联网安装，把 $R/B.txt 交给 Main。"; exit 1; fi ;;

V) cv; print "[V] Main. 安装前校验。对话框: 无。只读真实项目；scratch venv、候选插件、入口文件预测都在生产之外。约 2 分钟。"
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|plugin bytes change|plugin unchanged|^[<>] |graftling code vs production|515 graftling CODE|^  (VERSION|DOC|CODE|WHEEL-DIFFERS) |graftling wheel vs|markers expected|CHECK 5|STOP|✘ lines|read_session|loaded|task graph' $R/V.txt)"
    print "成功: 'CHANGED hooks/host_context.mjs'（514 预期：const SERVER/PREFIX 行；'lines other than const SERVER/PREFIX and \"version\": 0'）；'CHECK 515 candidate host_context.mjs const SERVER = \"graphtraj\": PASS'；'graftling wheel vs …: … differing 0: SAME'（CODE 行是 0.5.2→0.6.0 的预期变化，只列出）；"
    print "  'markers expected present: PASS (7/7)' 与 'markers expected absent: PASS (7/7)'；'503 layout: PASS' 与两行 'CHECK 503 node resolves … : PASS'（scratch venv）；候选 ✘ 不多于 baseline；无 STOP；入口文件预测列出 .mcp.json 的 graphtraj 条目（预测是合并，不含 configuration --write 对 agents 的删除；I 用真正的 --write 并核对）；read_session failures=0。"
    print "  'graftling wheel vs … STOP'：把 $R/V-graftcode.txt 交给 Leader，不要做 I。"
    next "zsh $THIS S    （然后 USER: zsh $THIS Vu）"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

Vc) print "[Vc] Main. 隔离项目 $VPROJECT 里用新 wheel 的真实 claude -p（先确认 isolation: OK）。对话框: 无（Vu 已信任该路径）。约 2 分钟。"
  : > $R/Vc.txt; rm -f $R/Vc.ok   # 448: a rerun's summary showed an earlier run's FAIL
  logged $R/Vc.txt vc_setup || { print "\nVc 准备失败，把 $R/Vc.txt 交给 Main。"; exit 1; }
  logged $R/Vc.txt vc_stream; rc=$?
  if [[ $(grep 'graphtraj-claude-host loaded:' $R/Vc.txt | tail -1) == *'loaded: NO'* ]]; then
    print "\n插件未加载：Claude Code 只在已信任的文件夹加载项目插件。$VPROJECT 是新路径：由 USER 做一次 Vu，然后 Main 重跑 Vc。"
    next "USER: zsh $THIS Vu    （之后 Main: zsh $THIS Vc）"; exit 1
  fi
  if (( rc == 0 )); then
    touch $R/Vc.ok
    summary Vc "$(grep -E '^(PASS|FAIL)|loaded:' $R/Vc.txt | tail -4)"
    print "成功: 'isolation: OK'，'CHECK 515 .mcp.json has graphtraj, no agents …: PASS'，'answer check: OK'（无 Harness AGENTS.md、不是 prompt 回显），'graphtraj-claude-host loaded: YES'，PASS mcp__graphtraj__tasks 与 PASS mcp__graphtraj__agents，四行 'CHECK 515 init …: PASS'。"
    next "zsh $THIS Mpre    （然后 USER: /exit Main，再在 Terminal 运行 zsh $THIS I）"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（预期需要一次：$VPROJECT 是新路径；需要终端和对话框，Main 做不了）。$(cv)"
  print "先由 Main 运行过 00（它建立 $VPROJECT）。在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框（一个）: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若没有出现这个框，直接 /exit。若再问项目的 MCP server 'graphtraj' 或插件/hooks，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

I) need_main
  print "[I] USER. 等待成员结束、备份并安装。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。安装约 3 分钟（等待时间另计）。"; cv
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。若它是一次放弃的 I 留下的（没有 INSTALL-STARTED）: 告诉 Main，由 Main 把它改名移开后再运行 I。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  print "确认已在 Claude Code Main 里输入 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  wait_idle "还没有改动任何东西（没有备份、没有安装）。" || exit 1
  date '+I start %F %T' | tee -a $R/I.txt
  logged $R/I.txt do_backup || { print "\n备份失败，生产未被改动。把输出交给 Main；$BK 需要由 Main 决定如何处理。"; exit 1; }
  say "guard again right before pip install (backup done)" | tee -a $R/I.txt
  wait_idle "备份已完成，生产还没有改动。重来时由 Main 先把 $BK 改名移开。" 2>&1 | tee -a $R/I.txt; (( ${pipestatus[1]} == 0 )) || exit 1
  touch $BK/INSTALL-STARTED; INSTALL_FROM=$(date +%T)
  if ! logged $R/I.txt do_install; then
    print "\n安装或校验失败。不要恢复 Main，立刻运行回退:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  touch $R/I.ok
  { say "BLOCKING processes started during the install window ($INSTALL_FROM → $(date +%T)); information for Main"
    guard && print "none" || print "（上面 BLOCKING 列出的进程在安装期间启动，可能载入了新旧混合的文件；告诉 Main。）"; } 2>&1 | tee -a $R/I.txt
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|^457 _stop_escaped|^460 tool-processes|^465 Claude|^469 Unknown|^4[89][0-9] |^395 layout|CHECK 503|503 layout|control records snapshot|budget_idle_timer|timer pid|zombies|markers expected|SAME-AS-VALIDATED|plugin bytes|configuration --write rc|CHECK 515|WRITTEN|UNCHANGED|bytes unchanged|^changed|BLOCKING|-rw-------' $R/I.txt)"
  print "成功: Successfully installed graftling-$GVERSION graphtraj-0.1.0（pip 卸载 graftling-$GOLDVERSION）；PASS n FAIL 0（含 LEFTOVER-DIST-INFO 0）；三个 -rw------- 备份入口文件；'markers expected present: PASS (7/7)'；'395 layout graftling $GVERSION | distributions 1 | beside graphtraj: True | graftling.mjs: True | graphtraj requires [...>=$GVERSION...]'；'503 layout: PASS (0 failed)'（六行 CHECK 503 layout）；两行 'CHECK 503 node resolves … : PASS'；'control records snapshot I.json'；464 的两行 import（457…463 仍在）、478 的三行 '466 session_read DEFAULT_COUNT 5 …'、'468 archive _identity …'、'477 take_push …'、492 的四行（481/484、486、485/480、487）与 497 的三行 '488 _worker_arguments _worker_arguments | _process_ended _process_ended'、'490 _work_ended … | SLICE_SECONDS 5.0 | cleanup uses process_is_zombie: True'、'494 Claude host receiver defers_push: True | hold thread started in the lock: True' 与 '495 argv refreshed each sample: True'；"
  print "  '465 Claude member settings call project_history_files: False | Codex development reads history param: True' 与 '469 UnknownTask _load_task_state _RegisteredTaskNames'；SAME-AS-VALIDATED；计时器列表三次（备份前、pip 前、安装后；安装后的一次按 old/new 分类），只报告不发信号；"
  print "  'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS'；'CHECK 515 host_context.mjs const SERVER = \"graphtraj\": PASS'；'plugin bytes CHANGED … (expected …)'；'CHECK 515 settings.local.json bytes unchanged …: PASS'（若 CHANGED：信息，交 Main；值不打印）；入口文件 changed: .mcp.json（agents → graphtraj）。"
  print "$R_HINT"
  print "\nMain 拥有的 .claude/settings.local.json（本步不写）: 重启之后由 Main 自己修改，从 enabledMcpjsonServers 里去掉 \"$OLDS\":"
  print "  现在: $(settings_view $H/.claude/settings.local.json | sed -n 's/^\(enabledMcpjsonServers: [^|]*\)|.*/\1/p')"
  print "  改为: enabledMcpjsonServers 只保留 [\"$NEWS\"]（其它键不动；enableAllProjectMcpServers 不动）。"
  print "\n下一步（USER，普通 Terminal）恢复 Main（同一个 Session）:\n  cd $H && claude --continue"
  print "预期对话框: 插件 hooks 的字节变了（host_context.mjs 的 const SERVER = \"graphtraj\"），所以至多出现一个插件/hooks 信任框（graphtraj-claude-host）→ 选信任（Yes / Trust）。"
  print "  MCP 服务器框: 预期没有（\"$NEWS\" 已在 enabledMcpjsonServers 里，且 enableAllProjectMcpServers 为 true）；若问 \"$NEWS\"，选批准；若问 \"$OLDS\"，选拒绝并告诉 Main。其它任何框: Esc 并告诉 Main 标题。"
  print "若 --continue 打开的不是原来的对话: /exit，然后 cd $H && claude --resume $MAIN"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cv; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main（用 claude --continue 恢复的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。对话框: 无。Main 把原始结果存到 $R/M-<字母>.txt。

[a 定义第 4 项: 安装后第一次 Main 重启，通知正常显示、不重复；第 3 项: Main 的工具名] 恢复后第一句（粘贴）:
GraphTraj's MCP server was renamed by Task 515: your GraphTraj tools are now mcp__graphtraj__agents and mcp__graphtraj__tasks (formerly mcp__agents__agents and mcp__agents__tasks). Before anything else, using no tools: (1) list every GraphTraj/Graftling notice delivered to you since this resume (alias, event, execution if shown in the title, first line), and for each say whether you had already seen that same notice before this resume; (2) state whether your tool list has mcp__graphtraj__agents and mcp__graphtraj__tasks, and whether it has any tool whose name starts with mcp__agents__ (list them exactly).
  成功: (1) 没有安装前已见过的通知再出现（Main 退出期间结束的其它 Task（$(active_tasks)）成员的通知可能到达一次，不能重复）；(2) 有 mcp__graphtraj__agents 与 mcp__graphtraj__tasks，没有 mcp__agents__*。
  若有重复或旧名字: 记下原文，由 Main 登记。

[b 新名字的工具可用] 粘贴:
Using only mcp__graphtraj__tasks: discover. Print the raw list of feature names, and nothing else. Then using only mcp__graphtraj__agents: status with no agent. Print the raw result.
  成功: discover 有功能列表；status 有结果。

[c settings.local.json（Main 自己改；本脚本不写）] 从 $H/.claude/settings.local.json 的 enabledMcpjsonServers 中去掉 "$OLDS"，只留 "$NEWS"。

[d] Main 的 Bash（无对话框）: zsh $THIS Mp   然后   zsh $THIS Mps   然后   zsh $THIS inbox
EOF2
  next "zsh $THIS Mp" ;;

# Mp (Main, after the restart): one bounded claude -p in the Harness. Its init record shows what a new host process
# of this project offers the model. It makes no tool call; a second host for the same config may refuse calls
# (host-busy) but still completes the handshake and lists the tools.
Mp) cv; print "[Mp] Main，M 之后。Harness 里一次有时限（120 秒）的 claude -p 单行探测，看 init 记录的 MCP 服务器与工具名。对话框: 无。不调用工具。< 2 分钟。"
  print -r -- 'Reply with exactly one line: PROBE-515-OK. Use no tools.' > $R/Mp-prompt.txt
  (cd $H && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
      < $R/Mp-prompt.txt > $R/Mp-stream.jsonl 2> $R/Mp.err)
  print "claude -p rc=$? (142 = 120 s timeout) | stderr lines naming untrusted/trust: $(grep -ciE 'untrust|trust' $R/Mp.err)" | tee $R/Mp.txt
  $CONDA -I $SD/rec515.py init $R/Mp-stream.jsonl 2>&1 | tee -a $R/Mp.txt; rc=${pipestatus[1]}
  grep -ciE 'untrust' $R/Mp.err > /dev/null && { print "CHECK 515 Mp stderr has no untrusted-plugin warning: FAIL" | tee -a $R/Mp.txt; rc=1; }
  summary Mp "$(grep -E '^(claude|CHECK|init)' $R/Mp.txt)"
  print "成功: 四行 'CHECK 515 init …: PASS'（mcp server graphtraj only；两个新工具名；没有 mcp__agents__*；没有 untrusted-plugin 警告）。FAIL 交 Main。"
  next "zsh $THIS Mps" ; exit $rc ;;

# S (Main, any time after V): the full suite is NOT run (definition 2; 514's F + V are reused). Prints the evidence and
# checks that no src change lies between 514's F commit and the adopted commit.
S) print "[S] Main. 全套测试不运行（复用 514 的结果）。对话框: 无。只读。< 10 秒。"; cv | tee $R/S.txt
  { print "reused evidence (514 teams/1/rounds/1/leader-2.md): F at 142bdd8e: 3587 passed (full suite, TMPDIR=\${TMPDIR:-/tmp}, single process ~73 min); V at ${TARGET[1,8]}: the 3 stale tests fixed in 4ad22e90 + the review-row test: 4 passed."
    print "pytest: none run by this step (no TMPDIR needed)."
    local_diff=$(git -C $WT diff --stat 142bdd8e $TARGET -- src)
    print "git diff 142bdd8e ${TARGET[1,8]} -- src: ${local_diff:-empty}"
    [[ -z $local_diff ]] && print "CHECK 515 no src change between 514's F commit and the adopted commit: PASS" || print "CHECK 515 no src change between 514's F commit and the adopted commit: FAIL"; } 2>&1 | tee -a $R/S.txt
  grep -q 'commit: PASS' $R/S.txt || exit 1
  next "USER: zsh $THIS Vu    （之后 Main: zsh $THIS Vc）" ;;

# Rs (Main, after M/Mps/inbox): the standby Leader of this Task, created under the old server name, is resumed with a
# fixed message; the Leader then resumes the Engineer with a fixed probe. Rs records the byte size of every archive of
# both Sessions (Rsr reads only what comes after) and prints Main's paste-ready message with the Leader's alias.
Rs) cv; print "[Rs] Main，M、Mps、inbox 之后。已保留的待命 Session（本 Task 的 Leader 与 Engineer，用旧名字创建）恢复。对话框: 无。< 1 分钟。"
  (cd $H && clean $RT/bin/graphtraj task members) > $R/Rs-members.txt 2>&1
  LEADER=$(grep -oE "${TASK_ID}-[A-Za-z0-9_.-]*team_leader[A-Za-z0-9_@.-]*" $R/Rs-members.txt | head -1)
  ENGINEER=$(grep -oE "${TASK_ID}-[A-Za-z0-9_.-]*engineer[A-Za-z0-9_@.-]*" $R/Rs-members.txt | head -1)
  print "Task $TASK_ID members (graphtraj task members):"; grep -E "(^|[^0-9])$TASK_ID-" $R/Rs-members.txt | head -8
  print "leader alias: ${LEADER:-NOT FOUND} | engineer alias: ${ENGINEER:-NOT FOUND}" | tee -a $R/Rs.txt
  [[ -n $LEADER ]] || { print "没有找到 Leader alias。Main 用 'Using only mcp__graphtraj__agents: status with no agent' 找 task_id $TASK_ID 的 team_leader alias，写入 $R/Rs-leader.txt 后重跑 Rs。"; [[ -s $R/Rs-leader.txt ]] || exit 1; LEADER=$(<$R/Rs-leader.txt); }
  print -r -- $LEADER > $R/Rs-leader.txt; [[ -n $ENGINEER ]] && print -r -- $ENGINEER > $R/Rs-engineer.txt
  [[ -z $ENGINEER && -s $R/Rs-engineer.txt ]] && ENGINEER=$(<$R/Rs-engineer.txt)
  [[ -n $ENGINEER ]] || print "engineer alias not found: Main writes it (from mcp__graphtraj__agents status, task_id $TASK_ID, role engineer) to $R/Rs-engineer.txt before Rsr"
  rs_archives > $R/Rs-archives.txt; print "archives of both Sessions:"; cat $R/Rs-archives.txt
  $CONDA -I $SD/rec515.py sizes $R/Rs-sizes.txt ${(f)"$(<$R/Rs-archives.txt)"} | tee -a $R/Rs.txt
  date +%s > $R/Rs.epoch
  cat <<EOF2 | tee $R/Rs-prompt.txt

[Rs] Main 粘贴（恢复 Leader $LEADER；不 wait，不等回复）:
Using only mcp__graphtraj__agents: send to the retained Session $LEADER (agent alias $LEADER) exactly this message, then print the raw result and end your turn: <<Task 515 production check (Rs). GraphTraj's MCP server is now named graphtraj: your tools are mcp__graphtraj__agents and mcp__graphtraj__tasks. Resume your Engineer${ENGINEER:+ ($ENGINEER)} with exactly this probe: "Task 515 probe after the rename. Make exactly one mcp__graphtraj__agents call with {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{}} and exactly one mcp__graphtraj__tasks call with {\"action\":\"discover\"}. Then reply one line: DONE-515-RESUMED names=<the two tool names you called> agents=<ok or the exact error> tasks=<ok or the exact error>." When the Engineer replies, report its line and your own line DONE-515-RESUMED leader names=<the tool names you used> to your parent.>>
  若 send 的参数名不同: 先 'Using only mcp__graphtraj__agents: describe send with schema true'，用同样的消息重试一次，两次原始结果都存到 $R/Rs-send.txt。
  Leader 与 Engineer 回复后（Main 收到 Leader 的通知），Main 的 Bash: zsh $THIS Rsr
EOF2
  next "（Leader 报告之后）zsh $THIS Rsr" ;;

Rsr) cv; print "[Rsr] Main，Leader 报告 DONE-515-RESUMED 之后。只读两个恢复后的 Session 的原始记录（只看 Rs 之后新增的部分）。对话框: 无。< 30 秒。"
  [[ -s $R/Rs-sizes.txt ]] || { print "没有 $R/Rs-sizes.txt：先运行 Rs。"; exit 1; }
  rs_archives > $R/Rsr-archives.txt; rc=0
  for who in leader engineer; do
    a=$(cat $R/Rs-$who.txt 2>/dev/null); [[ -n $a ]] || { print "CHECK 515 Rs $who: NOT OBSERVED (no alias recorded by Rs)" | tee -a $R/Rsr.txt; rc=1; continue; }
    fs=(${(f)"$(rs_session_files $a)"})
    print "$who $a record files: ${#fs}" | tee -a $R/Rsr.txt
    $CONDA -I $SD/rec515.py calls "$who $a" --since $R/Rs-sizes.txt --need $([[ $who == engineer ]] && print agents,tasks || print agents) ${(u)fs} 2>&1 | tee -a $R/Rsr.txt
    (( ${pipestatus[1]} == 0 )) || rc=1
  done
  summary Rsr "$(grep -E '^(CHECK|\[)' $R/Rsr.txt)"
  print "成功: Engineer 两行 PASS（mcp__graphtraj__agents 与 mcp__graphtraj__tasks 都有无错误、无拒绝的调用）与 'no mcp__agents__* call: PASS'；Leader 的 mcp__graphtraj__agents PASS 与无旧名字调用。NOT OBSERVED（档案没找到）交 Main，附 Leader 的回复原文。"
  next "zsh $THIS Nw    （然后 zsh $THIS N）" ; exit $rc ;;

Mps) need_main; print "[Mps] Main. 运行中的 host 与它的父 claude。对话框: 无。只读。"; cv | tee -a $R/Mps.txt
  { print "at $(date '+%F %T')"; hit=$(ps -axww -o pid=,ppid=,command= | grep -F -- "$HOSTCFG" | grep -F -- ' serve ')
    print -r -- "host: $hit"; words=(${=hit}); PPIDV=${words[2]:-}
    if [[ -n $PPIDV ]]; then C=$(ps -ww -o command= -p $PPIDV); print -r -- "parent claude: $C"
      [[ $hit == *"$RT/bin/python"* ]] && print "host uses .venv-runtime: yes" || print "host uses .venv-runtime: NO"
      if [[ $C == *claude*' --continue'* || $C == *"--resume $MAIN"* ]]; then print "parent is claude --continue or --resume $MAIN: yes"
      else print "parent is claude --continue or --resume $MAIN: NO"; fi
    else print "NOT FOUND: no host serving $HOSTCFG"; fi
    say "host.log tail"; tail -n 30 $H/.graphtraj/claude-host/host.log; print "outcome=ok lines in tail: $(tail -n 30 $H/.graphtraj/claude-host/host.log | grep -c 'outcome=ok')"
    say "486: Main's tool host is graphtraj-claude-host from .venv-runtime; no graphtraj-mcp under Main (486 changes only graphtraj-mcp)"
    [[ $hit == *"$RT/"* && ( $hit == *"graphtraj.runtimes.claude.host"* || $hit == *"graphtraj-claude-host"* ) && $hit == *" serve "* ]] && print "486 Main tool host: graphtraj-claude-host from .venv-runtime: yes" || print "486 Main tool host: graphtraj-claude-host from .venv-runtime: NO"
    ps -axww -o pid=,ppid=,command= > $R/Mps-ps.txt 2>&1
    $CONDA -I $SD/ctl497.py mcp ${PPIDV:-none} $R/Mps-ps.txt
    say "486: production agents control records across the restart (Mpre snapshot before /exit -> now)"
    if [[ -f $CTL/Mpre.json ]]; then $CONDA -I $SD/ctl497.py snap $H $CTL/Mps.json; $CONDA -I $SD/ctl497.py restart $CTL/Mpre.json $CTL/Mps.json
    else print "CHECK 486 no execution ended interrupted across the Main restart: BLOCKED (no $CTL/Mpre.json: Mpre was not run before /exit)"; fi
  } 2>&1 | tee -a $R/Mps.txt
  summary Mps "$(grep -E '^(host uses|parent is|NOT FOUND|outcome=ok|486|CHECK|  )' $R/Mps.txt | tail -12)"
  print "成功: host uses .venv-runtime: yes；parent is claude --continue or --resume $MAIN: yes；outcome=ok lines > 0；486 Main tool host … yes；CHECK 486 两行 PASS（Main 下没有 graphtraj-mcp；重启前后没有 execution 以 interrupted 结束）。列出的状态变化逐条交 Main 判断（其它 Task 的成员可能正常结束）。"
  next "zsh $THIS inbox" ;;

inbox) need_main; cv; print "[inbox] Main. Main 的通知队列。对话框: 无。只读。"
  { for f in $INBOX/*.jsonl(N); do print "== ${f:t}"; tree inbox $f; done; } 2>&1 | tee -a $R/inbox.txt
  print "Claude Main $MAIN 的文件: $(inbox_key "claude:$MAIN").jsonl"
  summary inbox "$(grep -E '^(==|duplicate|records)' $R/inbox.txt | tail -12)"
  print "成功: 每个文件 duplicate ids: 0。"
  next "zsh $THIS Rs" ;;

Nw) cv; print "[Nw] Main. 在 N 之前启动：后台只读观察 $CHILD 的 459 后代记录（每 0.2 秒读一次，不写生产、不发信号）。对话框: 无。立即返回。"
  print "  原因: 459 的采样线程在工具进程结束后就把它从记录里删掉，正常结束后记录里已没有那条 Bash 命令；Nw 在子级运行时把记录的每次变化复制到 $R/Nw-snapshots.jsonl。"
  print "  498: watch498.py 每 0.5 秒记录子级 Runtime 的环境/标记类别、工具进程（含子 shell）的内核事实与后代记录（$R/Nw498-samples.jsonl），execution 结束后再观察 15 秒，最长 25 分钟；只读，不发信号。"
  print "  它在 $CHILD 的 execution 结束、子级被清退或 15 分钟后自己退出；468 采样器 $R/Nw468.txt 在 Worker 消失或 15 分钟后退出（'== END 468 sampler'）；状态: tail -n 5 $R/Nw.txt（'== END' 表示已退出）。"
  if [[ -e $R/Nw.txt ]] && ! grep -q '^.* == END' $R/Nw.txt; then print "Nw 已在运行（$R/Nw.txt 没有 '== END'）；不重复启动。"; next "zsh $THIS N"; exit 0; fi
  : > $R/Nw.txt; : > $R/Nw-snapshots.jsonl
  ($CONDA -I $SD/watch459.py $H $R $CHILD 900 < /dev/null >> $R/Nw.txt 2>&1 &!)
  : > $R/Nw468.txt; : > $R/Nw468-ps.txt   # 468: ps of the Task 499 member Worker every ~10 s, ends itself after 15 min
  ($CONDA -I $SD/cpu468.py sample $H $R $TASK_ID ${ADOPT515_NW468_SECONDS:-900} < /dev/null >> $R/Nw468.txt 2>&1 &!)
  # 498: the child Runtime's env/marker classes, its tool processes' facts (P_EXEC, platform, env, marker) and the
  # record, every 0.5 s with the candidate's own readers (B's git archive); read only, never signals; ends itself.
  [[ -d $GSRC/src/graftling ]] || { print "没有 $GSRC/src（B 的 graftling git archive）；先运行 B。"; exit 1; }
  : > $R/Nw498.txt; : > $R/Nw498-samples.jsonl
  ($CONDA -I $SD/watch498.py $H $R $GSRC/src $CHILD ${ADOPT515_NW498_SECONDS:-1500} ${ADOPT515_NW498_AFTER:-15} < /dev/null >> $R/Nw498.txt 2>&1 &!)
  print "started at $(date +%T) in the background (Nw.txt, Nw468.txt, Nw498.txt)."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. 定义第 3 项（498：用 agents 工具创建的子级 $CHILD 在 Step 01b 启动子 shell 与两个后台进程（sleep 1201/1202/1203，约 20 分钟后自己结束），Nw498 观察其 Runtime 的标记与工具进程事实，Nr 判断记录与 execution 结束时的停止；494：成员 wait 子级，第一次短 wait 超时、回复只送达一次、子级 execution 不留 push_deferred；495：工具后代记录列出工具命令、凭据遮蔽；490：成员空闲后由新版启动的计时器（Nt）；486 子级与成员正常结束；466 session_read；477；468 Worker CPU；475 的核对；484 由 N484 读）。先确认 Nw 已启动（tail -n 3 $R/Nw.txt 有 'start: watching'，tail -n 2 $R/Nw468.txt 有 '468 sampler'，tail -n 2 $R/Nw498.txt 有 'start: watching'），再在 Claude Main 里粘贴这一条。对话框: 无。成员与子级约 5-10 分钟。
Using only mcp__graphtraj__tasks: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"This is a production check. Do NOT call submit_result or submit_report. Your GraphTraj tools are named mcp__graphtraj__agents and mcp__graphtraj__tasks. (a) Using the agents tool (mcp__graphtraj__agents), create ONE claude child named $CHILD with configuration opus_coding_team.advisor and this message: <<This is a scripted probe. Do exactly these steps in order, one Bash call at a time, nothing else: Step 01: write the sentence 'Now step 01.' then call Bash with exactly: echo $CHILD-tool && sleep 3; Step 01b: write the sentence 'Now step 01b.' then call Bash with exactly: ( sleep 1201; true ) >/dev/null 2>&1 & sleep 1202 >/dev/null 2>&1 & sh -c 'sleep 1203; : api_key=sk-probe503fake''value0000' >/dev/null 2>&1 & sleep 4; echo $CHILD-bg-started (it starts three background processes that end by themselves after about 20 minutes; do not wait for them and do not stop them); Step 02: write the sentence 'Now step 02, marker KW503-ORCHID.' then call Bash with exactly: seq -f '503-02-%g' 1 400; Step 03: write the sentence 'Now step 03.' then call Bash with exactly: seq -f '503-03-%g' 1 400; Step 04: write the sentence 'Now step 04.' then call Bash with exactly: seq -f '503-04-%g' 1 400; Step 05: write the sentence 'Now step 05.' then call Bash with exactly: seq -f '503-05-%g' 1 400; Step 06: write the sentence 'Now step 06.' then call Bash with exactly: seq -f '503-06-%g' 1 400; Step 07: write the sentence 'Now step 07.' then call Bash with exactly: seq -f '503-07-%g' 1 400; Step 08: write the sentence 'Now step 08.' then call Bash with exactly: seq -f '503-08-%g' 1 400; Step 09: write the sentence 'Now step 09.' then call Bash with exactly: seq -f '503-09-%g' 1 400; Step 10: write the sentence 'Now step 10.' then call Bash with exactly: seq -f '503-10-%g' 1 400; Step 11: write the sentence 'Now step 11.' then call Bash with exactly: seq -f '503-11-%g' 1 400; Step 12: write the sentence 'Now step 12.' then call Bash with exactly: seq -f '503-12-%g' 1 400; Step 13: write the sentence 'Now step 13.' then call Bash with exactly: seq -f '503-13-%g' 1 400; Step 14: write the sentence 'Now step 14.' then call Bash with exactly: seq -f '503-14-%g' 1 400; Step 15: write the sentence 'Now step 15.' then call Bash with exactly: seq -f '503-15-%g' 1 400; Step 16: write the sentence 'Now step 16.' then call Bash with exactly: seq -f '503-16-%g' 1 400; Step 17: write the sentence 'Now step 17.' then call Bash with exactly: seq -f '503-17-%g' 1 400; Step 18: write the sentence 'Now step 18.' then call Bash with exactly: seq -f '503-18-%g' 1 400; Step 19: write the sentence 'Now step 19.' then call Bash with exactly: seq -f '503-19-%g' 1 400; Step 20: write the sentence 'Now step 20.' then call Bash with exactly: seq -f '503-20-%g' 1 400; Step 21: write the sentence 'Now step 21.' then call Bash with exactly: seq -f '503-21-%g' 1 400; Step 22: write the sentence 'Now step 22.' then call Bash with exactly: seq -f '503-22-%g' 1 400; Step 23: write the sentence 'Now step 23.' then call Bash with exactly: seq -f '503-23-%g' 1 400; Step 24: write the sentence 'Now step 24.' then call Bash with exactly: seq -f '503-24-%g' 1 400; Step 25: write the sentence 'Now step 25.' then call Bash with exactly: seq -f '503-25-%g' 1 400; Step 26: write the sentence 'Now step 26.' then call Bash with exactly: seq -f '503-26-%g' 1 400; Step 27: write the sentence 'Now step 27.' then call Bash with exactly: seq -f '503-27-%g' 1 400; Step 28: write the sentence 'Now step 28.' then call Bash with exactly: seq -f '503-28-%g' 1 400; Step 29: write the sentence 'Now step 29.' then call Bash with exactly: seq -f '503-29-%g' 1 400; Step 30: write the sentence 'Now step 30.' then call Bash with exactly: seq -f '503-30-%g' 1 400; Step 31: write the sentence 'Now step 31.' then call Bash with exactly: seq -f '503-31-%g' 1 400; Step 32: write the sentence 'Now step 32.' then call Bash with exactly: seq -f '503-32-%g' 1 400; Step 33: write the sentence 'Now step 33.' then call Bash with exactly: seq -f '503-33-%g' 1 400; Step 34: write the sentence 'Now step 34.' then call Bash with exactly: seq -f '503-34-%g' 1 400; Step 35: write the sentence 'Now step 35.' then call Bash with exactly: seq -f '503-35-%g' 1 400; Step 36: write the sentence 'Now step 36.' then call Bash with exactly: seq -f '503-36-%g' 1 400; Step 37: write the sentence 'Now step 37.' then call Bash with exactly: seq -f '503-37-%g' 1 400; Step 38: write the sentence 'Now step 38.' then call Bash with exactly: seq -f '503-38-%g' 1 400; Step 39: write the sentence 'Now step 39.' then call Bash with exactly: seq -f '503-39-%g' 1 400; Step 40: write the sentence 'Now step 40.' then call Bash with exactly: seq -f '503-40-%g' 1 400; Step 41: write the sentence 'Now step 41.' then call Bash with exactly: seq -f '503-41-%g' 1 400; Step 42: write the sentence 'Now step 42.' then call Bash with exactly: seq -f '503-42-%g' 1 400; Step 43: write the sentence 'Now step 43.' then call Bash with exactly: echo api_key=sk-probe503fake''value0000. Then reply with exactly: DONE-503>>. Quote the raw create result (agent id, session, execution id). If the child asks you to approve a Bash command, approve exactly the commands the message lists. (b) Immediately after create, while the child is still running, call agents wait with arguments {agent: <agent id>, timeout_seconds: 5} and quote its raw result (it must show timed_out true). Then call agents wait on that agent id with timeout_seconds 300, repeating until the execution has ended; quote the final wait result's last_message. Then call agents status with arguments {agent: <agent id>} and quote its last_message. (c) Call the agents tool feature session_read on the child five times: {agent: <agent id>} (default read); {agent: <agent id>, start: -10, stop: -5}; {agent: <agent id>, search: KW503-ORCHID}; {agent: <agent id>, content: tools, search: api_key}; {agent: <agent id>, content: tools, search: [redacted]}. For each quote one compact line: total, start, stop, event indices (or hit index and seq), the size of the result, the number of occurrences of [redacted] in it and whether the substring sk-probe503 appears in it (yes or no; never quote any value); no event contents. Also quote one line exactly: SESSION-READ-$TASK_ID session=<the session value of the default read> events=<its total> . (d) Use your own Bash once: echo member-bash-ok . Quote its output or the exact error. (e) List every parent input you received whose JSON has source graphtraj (verbatim first line and execution field), or say none. (f) Retire the child by its agent id and quote the raw result. End your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main 把 swarm 原始结果存为 $R/N.txt（必须含 "agent"）；Main 收到的这个成员的每一条通知原文（每条一行，原样以 '[Graftling notice from <成员 alias> · … · execution <id>]' 开头；494：completed 必须恰好一条）存为 $R/N-main-notice.txt。每条通知的通知头与正文写在同一行（'[Graftling notice from … · completed · execution <id>] Session execution ended: {...}' 整条一行；499 教训 c：只存通知头的一行不够，正文不要另起一行）。说明文字可以写，但必须单独成行且不以 '[Graftling notice' 开头（例如以 '# ' 开头）；Nr 只按通知本身的格式计数，说明行不计入（497 缺陷 b）；成员最终回复原文存为 $R/N-reply.txt。
  成员结束（Main 收到 completed 通知）后、清退成员之前，Main 的 Bash（无对话框）: 先 Nt（490：成员空闲后新版启动的计时器），再 Nr。
EOF2
  next "zsh $THIS Nt    （然后 zsh $THIS Nr）" ;;

Nt) cv; print "[Nt] Main，N 的成员结束之后、清退之前；清退之后再跑一次（记录清退使计时器退出）。490：Task $TASK_ID 的 Session 的预算计时器（只读，从不发信号）。对话框: 无。< 30 秒。"
  { print "at $(date '+%F %T')"
    LC_ALL=C ps -axww -o pid=,ppid=,stat=,lstart=,command= > $R/Nt-ps.txt 2>&1
    w=$(install_window)
    [[ -n $w ]] || print "no install window ($R/I-install-*.epoch): I has not run or did not finish"
    $CONDA -I $SD/timers497.py nt $R/Nt-ps.txt $RT ${=w:-x x} $H/.graphtraj/core/runner/sessions $TASK_ID $R/Nt-timers.json; } 2>&1 | tee -a $R/Nt.txt
  rc=${pipestatus[1]}
  summary Nt "$(grep -E '^(Task|CHECK)|timer pid' $R/Nt.txt | tail -12)"
  print "成功: 'CHECK 490 a timer started by the new version for a Task $TASK_ID Session is listed …: PASS'（至少一个 [new]、production .venv-runtime 的计时器；每个已记录的计时器一行 present/absent）。"
  print "  FAIL 且成员刚结束: 30 秒后重跑 Nt（计时器在 Worker 结束时启动）。清退成员后重跑 Nt: 成员的计时器应变为 absent（490：mapping.yml 移除后 ≤ 5 秒退出）。T 在 Leader 接受 515 之后判定。"
  next "zsh $THIS Nr" ; exit $rc ;;

T) cv; print "[T] Main，在 Leader 接受 515（状态变为 awaiting-integration）之后。490：本 Task 的 Session 中由新版启动的计时器全部消失，Task 结束后没有预算通知（只读，从不发信号）。对话框: 无。< 30 秒。"
  ST=$H/.graphtraj/core/state/tasks/$TASK
  tstat=$(sed -n 's/^status: //p' $ST/task.yml)
  if [[ ! -s $R/T-end.epoch ]]; then
    case $tstat in awaiting-integration|integrating|integrated)
      stat -f %m $ST/task.yml > $R/T-end.epoch; print "end time recorded from task.yml mtime at status $tstat: $(date -r $(<$R/T-end.epoch) '+%F %T')" | tee -a $R/T.txt ;;
    esac
  fi
  { print "at $(date '+%F %T') status $tstat"
    print "all timers now (old ones listed, not judged):"; timer_list $R/T-ps-all.txt
    LC_ALL=C ps -axww -o pid=,ppid=,stat=,lstart=,command= > $R/T-ps.txt 2>&1
    # Last command of the group: its exit status is T's (a FAIL/PENDING/BLOCKED CHECK exits 1).
    $CONDA -I $SD/timers497.py t $R/T-ps.txt $RT ${=$(install_window):-x x} $H/.graphtraj/core/runner/sessions $TASK_ID $R/Nt-timers.json $ST ${$(cat $R/T-end.epoch 2>/dev/null):-$(date +%s)}; } 2>&1 | tee -a $R/T.txt
  rc=${pipestatus[1]}
  summary T "$(grep -E '^(Task|CHECK|end time|budget_idle_timer)|new-version timer' $R/T.txt | tail -14)"
  print "成功: 两行 CHECK 490 都是 PASS（Nt 记录的新版计时器全部 gone；end 之后没有已送达的预算通知）。PENDING: Task 尚未结束或刚结束 < 30 秒，30 秒后重跑: zsh $THIS T。FAIL 或 BLOCKED 交 Main 登记。"
  exit $rc ;;

timers) cv; print "[timers] Main 或 USER，任何时候。所有 budget_idle_timer 进程（只读，从不发信号）。对话框: 无。< 10 秒。"
  timer_list $R/timers-ps.txt 2>&1 | tee -a $R/timers.txt ;;

Mpre) need_main; cv; print "[Mpre] Main，就在 USER /exit Main 之前（Vc 通过之后）。486：重启前的生产 agents 控制记录快照（只读）。对话框: 无。约 1 分钟。"
  $CONDA -I $SD/ctl497.py snap $H $CTL/Mpre.json 2>&1 | tee $R/Mpre.txt
  print "成功: 'control records snapshot Mpre.json: agents=… executions=…'。Mps 在 claude --continue 之后对比它。"
  print "\n下一步是 USER 的: 先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。I 会等其它 Task（$(active_tasks)）的成员结束（不要结束它们）。S 不在此时运行（499 教训：S 在 Pr 之后）。"
  next "USER（Main 已 /exit）: zsh $THIS I" ;;

N484) print "[N484] Main，Nr 之后。484：安装前后生产 agents 控制记录的 notification / notification_error（只读）。对话框: 无。约 1 分钟。"; cv | tee $R/N484.txt
  before=$CTL/I.json; [[ -f $before ]] || before=$CTL/00.json
  $CONDA -I $SD/ctl497.py snap $H $CTL/N484.json 2>&1 | tee -a $R/N484.txt
  $CONDA -I $SD/ctl497.py n484 $before $CTL/N484.json 2>&1 | tee -a $R/N484.txt; rc=${pipestatus[1]}
  summary N484 "$(grep -E '^CHECK|^484' $R/N484.txt)"
  print "成功: 三行 CHECK 484 都是 PASS（安装前已有的 execution 的最终 notification 不变；新的 delivered 没有 notification_error；notification_error 只与 unavailable|unconfirmed 同在）。'settled since the snapshot' 是安装时仍为 pending/held 的，信息。FAIL 交 Main 登记。"
  next "zsh $THIS done"; exit $rc ;;

Nr) print "[Nr] Main. 子级记录、459 的后代记录、Bash 是否真正启动、465 成员设置与 session_read、成员的结束与 Session 档案（只读，从不发信号）。对话框: 无。"
  cv | tee $R/Nr.txt
  nr_read 2>&1 | tee -a $R/Nr.txt; rc=${pipestatus[1]}
  [[ -d $GSRC/src/graftling ]] || { print "没有 $GSRC/src（B 的 graftling git archive）；先运行 B。" | tee -a $R/Nr.txt; rc=1; }
  $CONDA -I $SD/nr459.py $H $R $GSRC/src $HOSTCFG $CHILD 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  print "Nw: ${$(grep -E '== END|start:' $R/Nw.txt 2>/dev/null | tail -1):-not run}" | tee -a $R/Nr.txt
  (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | grep -F -- "$TASK_ID" | head -10 | tee -a $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1); CHILDAGENT=$(sed -n 's/^CHILD //p' $R/Nr.txt | tail -1)
  $CONDA -I $SD/nr499.py $H $R $CHILD "${MEMBER:-none}" $TASK 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  # 498: the agents-tool child's Runtime marker facts, its tool processes, the record, the stop at the execution end
  # (claude-termination-<execution>.yml, written when the execution ends: Nr runs after that, before or after retire).
  $CONDA -I $SD/nr498.py $H $R $GSRC/src $CHILD 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  print "Nw498: ${$(grep -E '== END|start:' $R/Nw498.txt 2>/dev/null | tail -1):-not run}" | tee -a $R/Nr.txt
  # 494: the child's ended execution in the control record (delivered; no push_deferred/push_holder left), and Main's
  # notices of the member: exactly one 'completed' (Main saved every notice of the member, one per line).
  { $CONDA -I $SD/ctl497.py snap $H $CTL/Nr.json && $CONDA -I $SD/ctl497.py n494 $CTL/Nr.json $CHILD
    if [[ -s $R/N-main-notice.txt ]]; then
      # 499 (497 defect b): count only the notices themselves, by their own shape (497 raw N-main-notice.txt):
      #   [Graftling notice from <member alias> · completed · execution <hex>] Session execution ended: {...}
      # Main's explanatory or header lines (any other line, e.g. '# Every notice of …') are never counted.
      nc=$(notice_count $R/N-main-notice.txt "$MEMBER")
      print "CHECK 494 Main got exactly one completed notice of the member: $( (( nc == 1 )) && print PASS || print FAIL) ($nc notice lines of shape '[Graftling notice from ${MEMBER:-<member>} · completed · execution <id>]' in $R/N-main-notice.txt; other lines not counted)"
    else print "CHECK 494 Main got exactly one completed notice of the member: PENDING (save every notice of the member to $R/N-main-notice.txt)"; fi
  } 2>&1 | tee -a $R/Nr.txt
  # 503: 468's CPU figure is reported, not judged (Task 501 owns it): printed as REPORT, never sets rc.
  $CONDA -I $SD/cpu468.py report $R 2>&1 | sed 's/^CHECK 468 /REPORT 468 (Task 501; not blocking) /' | tee -a $R/Nr.txt
  $CONDA -I $SD/cpu468.py window $R 2>&1 | tee -a $R/Nr.txt   # 515: 30 s before / after the child's creation
  grep -E '== END|Worker pid' $R/Nw468.txt 2>/dev/null | tail -2 | tee -a $R/Nr.txt
  # 515: the member's own raw records (graftling archive + Claude transcript): calls by tool name, read only.
  if [[ -n $MEMBER ]]; then
    mf=(${(f)"$(rs_session_files $MEMBER)"})
    print "515 member $MEMBER record files: ${#mf}" | tee -a $R/Nr.txt
    $CONDA -I $SD/rec515.py calls "member $MEMBER" --need agents ${(u)mf} 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  else print "CHECK 515 [member] mcp__graphtraj__agents called and answered without error or refusal: NOT OBSERVED (member alias not found)" | tee -a $R/Nr.txt; rc=1; fi
  SWARM_AGENT=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
  { print "CHECK swarm result has agent: $([[ -n $SWARM_AGENT ]] && print "PASS ($SWARM_AGENT)" || print "FAIL (no \"agent\" in $R/N.txt, or the file is missing)")"
    if [[ -n $MEMBER ]]; then
      W2=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -F -- '-m graphtraj.execution.runner_worker' | grep -F -- "/sessions/$MEMBER/" | grep -vF grep)
      print -r -- "runner_worker for $MEMBER now: ${W2:-none}"
      [[ -z $W2 ]] && print "CHECK 452 no runner_worker of the member alive after its end: PASS" \
        || print "CHECK 452 no runner_worker of the member alive after its end: FAIL if the member's end was already reported (rerun Nr in a minute; never kill it)"
    fi
    print "CHECK task_sessions lists the child: BY THE MEMBER'S QUOTED ENTRY in $R/N-reply.txt"; } | tee -a $R/Nr.txt
  grep -q '^CHECK.*: FAIL' $R/Nr.txt && rc=1
  summary Nr "$(grep -E '^claude:|^child|CHECK|BLOCKED|^member|member end|member settings|member quoted|archive|stored selection|^459:|^475:|tool_marker recorded|Nw snapshots|recorded identities|record entries naming|ALIVE|NAMED|escaped_processes|normal-end reclaim|^Nw:' $R/Nr.txt)"
  print "成功（定义第 3 项）: 每一行 CHECK 都是 PASS。494: 'CHECK 494 (487) first wait timed out …'、'CHECK 494 (487) reply delivered once …'、'CHECK 494 (477) child end not pushed …'、'CHECK 494 child $CHILD ended execution has notification delivered'、'… keeps no push_deferred/push_holder'、'CHECK 494 Main got exactly one completed notice of the member'；495: 'CHECK 495 (459) descendants record lists the Bash tool command'、'CHECK 495 (466) credential masked …'。"
  print "  其余（478/492）：（459 四行，含 'child Bash started'；465 两行：成员设置没有逐会话文件授权、session_read 返回子级 Session；member Bash started；455 两行；452 子级两行、成员结束、成员报告、无残留 Worker；477 子级 execution 的推送输入为 0；466 四行（last 5、[-10:-5]、关键字、凭据遮蔽）；477 三行（wait/status last_message、未推送）；468 一行（CPU 低于 0.84-0.97 且 < 0.25））。Main 收到成员一次 completed 通知（N-main-notice.txt）是 449/451 的核对。"
  print "  用户的验收规则：未观察到的必需核对不算成立。任何 'BLOCKED: <check> not observed - <错误原文与出处>' 行都是 FAIL，交 Main 登记；不能当作 PASS 或 NOT OBSERVED 接受。"
  print "  escaped_processes 那几行只是记录（正常结束时 owner 的回收结果在 claude-termination-<id>.yml；执行记录里只有 owner-exited 对账才写）。"
  print "  CHECK BY HAND 的那一行用下面的 session_read 由 Main 按事件类型计数（453 的做法）。PENDING: 子级还在运行，稍后重跑 Nr。不成立的交 Main 登记缺陷 Task。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session_id\":\"$SID\",\"limit\":400} (page with after until has_more is false). Count, per $CHILD execution id printed by Nr, the user/message events that deliver a parent input with source graphtraj naming it; print the counts by event type and each such input's execution field only."
  print "\n复核 task_sessions（Main 粘贴，成员结束后也可）:\nUsing only the agents tool: status with no agent. Print raw only the task_sessions entry whose alias is ${MEMBER:-<member alias>} (its children list)${CHILDAGENT:+, and the status of agent $CHILDAGENT (configuration, model)}."
  if [[ -n $SWARM_AGENT ]]; then print "\n清退成员（Main 粘贴，Nr 全部记录后）:\nUsing only the agents tool: retire with {\"agent\":\"$SWARM_AGENT\"} (the agent value of the N swarm result, not the alias), and print the raw result."
  else print "\n清退成员: 先把 N 的 swarm 原始结果存到 $R/N.txt 再重跑 Nr；它会打印按 agent 清退的提示。"; fi
  next "（清退成员后）zsh $THIS Nt    （490：成员的计时器变为 absent），然后 zsh $THIS N484"; exit $rc ;;

done) print "[done] Main. 结束状态。对话框: 无。只读。"; cv | tee -a $R/done.txt
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS|^FAIL' $R/done-verify.txt
    $CONDA -I $SD/markers.py $S present | tail -1
    $RT/bin/python -I $SD/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'
    node_resolve $RT
    shasum -a 256 $ENTRIES; tree versions $SESS
    mcp_keys $H/.mcp.json; grep -nE '^const SERVER' $PDIR/hooks/host_context.mjs; settings_view $H/.claude/settings.local.json
    print "Mp/Rsr/Nr/S: $(grep -hE '^CHECK 515' $R/Mp.txt $R/Rsr.txt $R/Nr.txt $R/S.txt 2>/dev/null | sed -E 's/^CHECK 515 //; s/:? (PASS|FAIL|NOT OBSERVED).*/ \1/' | tr '\n' ';')"
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    print "Nw watcher: ${$(grep -E '== END' $R/Nw.txt 2>/dev/null | tail -1):-no '== END' line (not run, or still running: tail -n 5 $R/Nw.txt)}"
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|markers expected|CHECK 503|CHECK 515|layout:|mcp.json servers|^[0-9]+:const SERVER|enabledMcpjsonServers|^Mp/Rsr|archives=|containing an exported key|^Nw watcher' $R/done.txt)"
  print "成功: PASS n FAIL 0；Version 0.1.0 与 $GVERSION；markers expected present: PASS (7/7)；'503 layout: PASS' 与两行 node resolves PASS；'CHECK 515 .mcp.json …: PASS'；const SERVER = \"graphtraj\"；enabledMcpjsonServers 只有 \"$NEWS\"（Main 已改）；Mp/Rsr/Nr/S 的 CHECK 515 都是 PASS；raw files containing an exported key value: 0；Nw watcher 有 '== END'。把 $R 的路径交给 Main。$R_HINT"
  next "（Leader 接受 515 之后，Main）zsh $THIS T" ;;

R) need_main; print "[R] USER. 回退到安装前（${OLD[1,8]}，graftling $GOLDVERSION；.mcp.json、settings.local.json 与插件也从备份恢复）。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; cv; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  wait_idle "还没有回退任何东西。" || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过。"
    print "然后（USER）: cd $H && claude --continue （插件恢复为安装前的字节；至多一个插件/hooks 信任框 → 选信任；MCP 服务器 '$OLDS' 仍在 enabledMcpjsonServers 中（若 Main 尚未改），预期无 MCP 框；出现其它框选拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
