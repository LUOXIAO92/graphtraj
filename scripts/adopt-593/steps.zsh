#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 593 — graftling 0.9.0 (591: MCP tool agents -> subagents, commands agents/agents-mcp -> subagents/subagents-mcp,
# no alias) release and production adoption of the paired GraphTraj candidate.
# graftling: v0.9.0 = $GCOMMIT "graftling 0.9.0 (593)", one commit on graftling dev 49f97004 (v0.8.0 542a81df + 591),
# on branch agent/593-graftling-0.9.0, carried as scripts/adopt-593/graftling-0.9.0.bundle. Step rel (Main) fetches it
# by exact SHA, creates the annotated tag v0.9.0 at it (noreply tagger), fast-forwards main to it and brings dev to it:
# a fast-forward when dev is still 49f97004, else a merge of $GCOMMIT into dev with the noreply identity that STOPS on
# a conflict. rp (Main) pushes dev, main and v0.9.0: the USER pre-approved this push (Worldline user-decision
# 20261124T030105.522331+0900). gh (after rp; result 4) checks that GitHub's graftling main and v0.9.0 resolve to
# $GCOMMIT, reading with ls-remote only. The wheel builds from the archive ROOT (`pip wheel <archive>`).
# graphtraj: production eb009725 (579) -> a wheel built from `git archive $TARGET` (GraphTraj dev 3eb21101 = 588, 592,
# 595, already pinning graftling>=0.9.0,<0.10; no product change in 593). Production's 0.8.0 does not satisfy it: the
# two wheels are installed together by I and are a pair.
# No Task-state migration in 593; I and R touch packages, plugin and entries only.
# Plugin: graftling 0.8.0..0.9.0 changes claude/host_context.mjs (591: const TOOL = "subagents", TOOLS = [TOOL, ...],
# the plugin PREFIX, display labels) and claude/plugin.py (writes TOOLS as [TOOL, "tasks"]). Production's
# graphtraj-claude-host copy is regenerated ONLY through the product (`configuration --write`, as 579's I), never by
# hand. V regenerates it with the candidate and requires exactly the difference plugin593.py names (hooks/host_context.mjs
# only; plugin.json and hooks.json SAME); I checks the installed copy equals V's. At `claude --continue` the plugin/hooks
# trust dialog for graphtraj-claude-host is therefore expected (USER: trust).
# Full suite: G (Main) runs this Worktree's HEAD with the v0.9.0 wheel from B in a clean environment (no provider
# credential); pytest's temp root is under TMPDIR=${TMPDIR:-/tmp}, outside the Harness (printed). Main's suite queue is
# serial, so G WAITS (printing that it waits) while another suite runs, then starts by itself; a ps that cannot list
# processes STOPs G (never read as "no other suite"). GR reads G's record (candidate, graftling commit, interpreter
# dependencies, totals, exit) and classes whole FAILED/ERROR node ids from the shard logs (scripts/verify-581/
# suiteids.py) against 516's CURRENT definition only; a shard that timed out ('timed out after' in suite.txt) is
# ABNORMAL and NEW (593). SR prints them and, for NEW ids, the ready-to-paste suite-base command with each id a separate
# argument; suite-base reruns them on GraphTraj 3eb21101 + graftling 49f97004 (wheel; before the release commit) and on
# the candidate.
# Real entries after I: graphtraj-mcp tools/list is exactly [subagents, tasks] and 'agents' is an unknown tool (I);
# the Codex hooks entry (I); Main's resumed Claude host (M: one real mcp__graphtraj__subagents call and one tasks call,
# Mr reads them from Main's own transcript); real member dispatch and a child through subagents (N, Nr); the review
# exemption under the new name (X); the old-name scan of live configuration (scan, before and after I; scanhome for the
# USER's own allow rules, only after Main asked the USER). Requirement 5 (conda): C5 installs v0.9.0 from GitHub with
# `uv tool install` into /private/tmp/uvtool-593 only and checks, with the USER's conda env active, that a Claude Code
# project there creates and waits for a child through mcp__graftling__subagents served by the uv tool's Python.
# 588 and 595: not repeated here (README: their real checks are already accepted on installs holding the change).
# Copied from scripts/adopt-579/steps.zsh (unchanged there); every 503/515/525/528/532/560/571/579 protection kept
# (isolated vproject, proddiff file by file, markers both ways, backup + R from the backup's own tools, guard that waits
# and never signals, rerun right before pip, Claude Code version at 00, no key value in raw output, timers listed only,
# .mcp.json only graphtraj, plugin bytes compared, real MCP and Codex hooks entries).
# Credentials: every real-host process starts through clean() (env -i: HOME USER PATH TERM TMPDIR LANG only), so it
# gets no provider credential variable; Claude and Codex use their own logins (the USER pre-approved Claude's login
# for 593: Worldline user-decision 20261124T030105.522331+0900). No step starts Pi or DSH.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → scan → rel → rp (pre-approved push) → gh → B → G (waits for other suites) → GR
#        (→ SR → suite-base only if GR names NEW ids) → V → Vu (USER once, only if Vc asks) → Vc → [scanhome: Main asks
#        the USER first] → Mpre → [593's Leader and Engineer have ended their turns; Main asks the USER to /exit Main and
#        run I] → I (USER) → [USER: cd <Harness> && claude --continue] → M → Mr → Mp → Mps → inbox → Nw → N → Nr
#        → Nt → scan (after) → C5 → C5u (USER) → C5r → X (correction 3: on graftling's own host in the C5 project)
#        → done → [Leader accepts 593] → [Main integrates this Task's branch] → T.
#        Rollback: R (Main asks the USER first; the USER /exits Main and runs it).  Timer listing at any time: timers.
# B does not need the candidate on dev: it builds from `git archive $TARGET` behind product_guard.
# Restart: Main's tasks/agents calls run inside its host process `graphtraj.runtimes.claude.host serve`, which keeps
# the graphtraj and graftling modules it loaded (eb009725 + 0.8.0) until it restarts. So Main is exited (USER /exit)
# before I and resumes with `claude --continue` only after I: member Workers and the new host load the new code.
# No step signals a process it did not start. Backups and scratch under $H/tmp/593 (Main created it); the isolated
# real-host project /private/tmp/vproject-593. 579's backup $H/tmp/579/backup is only listed, never modified.
# Only rehearse.zsh sets ADOPT593_* / VERIFY593_*. The defaults are the real paths.
set -u
setopt no_bg_nice   # background samplers must not try to renice themselves (refused in a sandbox)
SD=${0:A:h}
H=${ADOPT593_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT593_BASE:-$H/tmp/593}
RT=${ADOPT593_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT593_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT593_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/593-graftling-0-9-0-release-and-production-adoption}
G=${ADOPT593_G:-$H/graftling}   # graftling repository: rel writes dev, main and v0.9.0 there; B reads `git archive v0.9.0`
GTAG=${VERIFY593_GTAG:-v0.9.0}
GVERSION=0.9.0      # the graftling I installs
GOLDVERSION=0.8.0   # production's graftling now (579)
GCOMMIT=${VERIFY593_GCOMMIT:-7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9}   # graftling 0.9.0 (593) = v0.9.0
GBASE=${VERIFY593_GBASE:-49f97004a86cc245ad32515b9dd056d7092b08f7}   # graftling dev when 593 was dispatched (its parent)
GOLDTAG=v0.8.0; GOLDCOMMIT=542a81df0c941f5b1a425d9807681b2a38daa87c   # production's graftling (579)
GBRANCH=agent/593-graftling-0.9.0
BUNDLE=$SD/graftling-0.9.0.bundle
GURL=${ADOPT593_GURL:-https://github.com/LUOXIAO92/graftling.git}   # gh: GitHub's graftling (read with ls-remote only)
GTBASE=${VERIFY593_GTBASE:-3eb21101b920d94da057566c9cfdc3c81b6acbfb}   # GraphTraj dev at dispatch (suite-base side)
SUITEIDS=$SD/../verify-581/suiteids.py   # whole pytest node ids from shard logs (581; used by verify-586's SR)
# GraphTraj candidate (correction 2): 6fe8c8d9 = GraphTraj dev 3eb21101 (588, 592, 595; already graftling>=0.9.0,<0.10)
# + the one-line test fix of tests/test_mcp_adoption.py (its fake Codex server lists subagents, as 592's c9d68f31
# assertion expects). product_guard requires this Worktree's src/tests/plugins/pyproject.toml to equal TARGET, and
# TARGET's src, plugins and pyproject.toml to equal PRODUCT0 (only tests differ), so the graphtraj wheel's contents are
# 3eb21101's (B checks the wheel against both archives). Raw directory, wheels, G records and V copies follow TARGET.
TARGET=${VERIFY593_TARGET:-6fe8c8d97b5eedaf3fae898cd3f3f86a66a7acf7}
PRODUCT0=${VERIFY593_PRODUCT0:-3eb21101b920d94da057566c9cfdc3c81b6acbfb}   # GraphTraj dev: the product 593 installs
C8=${TARGET[1,8]}   # per-commit names
OLD=eb00972580b0f8bb28dfc7f0da57a52ccafeb18f   # production's graphtraj now (579)
OLDBASE=${ADOPT593_OLDBASE:-$H/tmp/579}   # 579's backup: listed only, never touched
TASK=593-graftling-0-9-0-release-and-production-adoption
TASK_ID=593
CHILD=n593
NEWS=graphtraj; OLDS=agents   # .mcp.json server keys: the one production has (514/515) and the old one
NEWTOOL=subagents; OLDTOOL=agents   # graftling's MCP tool: 0.9.0's name and 0.8.0's (591; no alias)
ISO=$SD/../verify-common/claude_isolation.py   # 489's shared isolation (settings + answer check)
CC_EXPECT=$(cat ${ADOPT593_BASE:-$H/tmp/593}/cc.version 2>/dev/null)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CONDABIN=${ADOPT593_CONDABIN:-/Users/luoxiao/miniconda3/bin/conda}   # requirement 5: activated only, never changed
UVT=${ADOPT593_UVT:-/private/tmp/uvtool-593}   # requirement 5: isolated uv tool, bin, cache and Claude project (C5)
MODEL=claude-opus-5-5
W=${ADOPT593_W:-$H/.graphtraj/core/state/tasks/$TASK/adoption}
R=$W/raw-$C8
CTL=$R/ctl
N=$W/wheels-$C8   # graphtraj-0.1.0 AND graftling-0.8.0: what I installs (proddiff compares every wheel here)
SRC=$W/src-$C8
GSRC=$W/gsrc-$GVERSION   # git archive of graftling $GTAG (built from the archive root, as from 0.7.0)
# The newest G record of this candidate (G writes $W/G-<c8>-<time>/); GR reads it unless ADOPT593_GREC names one.
GREC=${ADOPT593_GREC:-${$(print -l $W/G-$C8-*(N/om[1])):-$W/G-$C8-none}}
BK=$BASE/backup
VV=$BASE/vvenv-$C8
VPL=$W/vplug-$C8
VP=$VPL/graphtraj-claude-host
VE=$W/ventries-$C8
VPROJECT=${ADOPT593_VPROJECT:-/private/tmp/vproject-593}
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
RUNNER=$H/.graphtraj/core/runner
STATE=$H/.graphtraj/core/state
# 516's CURRENT definition (known flaky tests), read through its task.yml (works before and after the migration).
D516=$STATE/tasks/516-low-priority-flaky-tests
KNOWN516=$D516/${${${(M)${(f)"$(cat $D516/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
DATAROOTS=($H/.graphtraj/swarm $RUNNER)   # graftling data roots in production (REPORT 526 .gitignore after N)
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml $H/.codex/config.toml(N) $H/.codex/hooks.json(N))
INBOX=$RUNNER/main-sessions/inbox
PROJECTS=${ADOPT593_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
THIS=${0:A}
STEP=${1:-help}
IDS=("${(@)argv[2,-1]}")   # suite-base: the node ids after the step name
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT593_STUB:-} ]] && path=($ADOPT593_STUB $path)   # rehearsal only: stub hosts first
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
# 560: one Codex answer from the isolated project with the configured model and login (no --model: the configured one).
codex_answer() {   # $1 = output name
  local X=$(command -v codex || print -r -- /opt/homebrew/bin/codex)
  print -r -- "codex: $X -> ${X:A} | version: $($X --version 2>&1 | head -1)"
  (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 180 $X exec --skip-git-repo-check --sandbox read-only \
      'Reply with exactly one line: CODEX-593-OK. Use no tools.' < /dev/null > $R/$1-codex.txt 2> $R/$1-codex.err)
  local rc=$?; print "codex exec rc=$rc (142 = 180 s timeout)"
  grep -m1 -E '^model:|model:' $R/$1-codex.err $R/$1-codex.txt 2>/dev/null | head -1 | sed 's/^/codex configured /'
  if grep -qx 'CODEX-593-OK' $R/$1-codex.txt; then print "CHECK 593 Codex answers CODEX-593-OK (configured model, logged in): PASS"
  else print "CHECK 593 Codex answers CODEX-593-OK (configured model, logged in): FAIL ($(tail -c 300 $R/$1-codex.err | tr '\n' ' '))"; return 1; fi
}
# 560: pytest and scratch temp stay outside the Harness.
check_tmp() {
  local t=${TMPDIR:-/tmp}
  case ${t:A}/ in ${H:A}/*) print "STOP: TMPDIR $t is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  print -r -- "TMPDIR=$t (outside the Harness)"
}
# 560: the Codex hooks entry of venv $1: its --configuration names this venv's python, and a neutral lifecycle event
# runs the whole hook module and answers {} (no Main binding is touched).
codex_hook_check() {
  local P=$1/bin/python out cmd
  out=$(cd ${2:-$VPROJECT} && clean $P -I -m graphtraj.runtimes.codex.stop_hook --configuration 2>&1)
  cmd=$(print -r -- "$out" | $CONDA -I -c 'import json,sys; d=json.load(sys.stdin); print(sorted({h["command"] for e in d["hooks"].values() for g in e for h in g["hooks"]}), sorted(d["hooks"]))' 2>&1)
  print -r -- "Codex hooks entry configuration: $cmd"
  [[ $cmd == *"'$P -m graphtraj.runtimes.codex.stop_hook'"*"'SessionEnd', 'SessionStart', 'Stop'"* ]] \
    && print "CHECK 593 Codex hooks entry names $P -m graphtraj.runtimes.codex.stop_hook for SessionStart/Stop/SessionEnd: PASS" \
    || { print "CHECK 593 Codex hooks entry names $P -m graphtraj.runtimes.codex.stop_hook for SessionStart/Stop/SessionEnd: FAIL"; return 1; }
  out=$(print -r -- '{"hook_event_name":"Probe593","session_id":"probe-593","cwd":"'${2:-$VPROJECT}'"}' | (cd ${2:-$VPROJECT} && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
  [[ $out == '{}' ]] && print "CHECK 593 Codex hooks entry runs (neutral event answers {}): PASS" \
    || { print -r -- "CHECK 593 Codex hooks entry runs (neutral event answers {}): FAIL (${out[1,300]})"; return 1; }
}
# 579: count matching paths; an empty glob counts 0 (560's done printed `print -l <glob>(N) | wc -l`, which counts the
# one empty line print -l writes for no arguments as 1).
count() { print -r -- $#; }
# 560 product guard: the Worktree's src/tests/plugins/pyproject.toml must equal $TARGET (only scripts/ may differ) and
# nothing may be uncommitted there. Return 1 = STOP.
GUARDED=(src tests plugins pyproject.toml)
product_guard() {
  local head=$(git -C $WT rev-parse HEAD) names dirty
  git -C $WT cat-file -e "$TARGET^{commit}" 2>/dev/null || { print "STOP: $TARGET is not a commit in this repository"; return 1; }
  names=$(git -C $WT diff --name-only $TARGET HEAD -- $GUARDED 2>&1)
  dirty=$(git -C $WT status --porcelain -- $GUARDED 2>&1)
  print "product guard: HEAD $head | git diff $C8 HEAD -- ${GUARDED[*]}: ${${names//$'\n'/ }:-empty} | uncommitted there: ${${dirty//$'\n'/ }:-none}"
  [[ -z $names ]] || { print "STOP: the Worktree's ${GUARDED[*]} differ from $C8 (only scripts/ may differ): ${names//$'\n'/ }"; return 1; }
  [[ -z $dirty ]] || { print "STOP: uncommitted changes in the Worktree's ${GUARDED[*]}"; return 1; }
  local p0=$(git -C $WT diff --name-only $PRODUCT0 $TARGET -- src plugins pyproject.toml 2>&1) t0=$(git -C $WT diff --name-only $PRODUCT0 $TARGET -- $GUARDED 2>&1)
  print -r -- "product guard: $C8 vs ${PRODUCT0[1,8]}: src plugins pyproject.toml ${${p0//$'\n'/ }:-identical} | every difference in ${GUARDED[*]}: ${${t0//$'\n'/ }:-none} (correction 2: only tests/test_mcp_adoption.py)"
  [[ -z $p0 ]] || { print "STOP: $C8's src, plugins or pyproject.toml differ from ${PRODUCT0[1,8]}"; return 1; }
  local pin=$(git -C $WT show $TARGET:pyproject.toml 2>/dev/null | grep -m1 -oE '"graftling[^"]*"')
  print -r -- "product guard: $C8 pyproject pins ${pin:-NOTHING} (593 expects \"graftling>=0.9.0,<0.10\")"
  [[ $pin == '"graftling>=0.9.0,<0.10"' ]] || { print "STOP: $C8 does not pin graftling>=0.9.0,<0.10"; return 1; }
  print "product guard: PASS (HEAD's ${GUARDED[*]} = $C8; only scripts/ differ)"
}
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
# 528/532 (526): whether each graftling runtime directory of production's data roots holds graftling's `.gitignore` ('*').
# Read only; a REPORT, never a CHECK (526 writes it only when its code next writes there; live/ is a known 526 leftover).
gitignore_report() {
  local root d f c
  for root in $DATAROOTS; do for d in sessions control live native; do
    f=$root/$d/.gitignore
    if [[ ! -d $root/$d ]]; then c="directory absent"
    elif [[ ! -e $f ]]; then c="no .gitignore"
    elif [[ $(<$f) == '*' ]]; then c="present ('*', $(stat -f '%Sm' -t '%F %T' $f))"
    else c="present, other content (graftling keeps an existing file): $(head -c 60 $f | tr '\n' ' ')"; fi
    print -r -- "REPORT 532 526 .gitignore ${root#$H/}/$d: $c"
  done; done
}
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

# 593 (requirement 3: adoption only with no member running): STOP (return 1) while any member Worker or swarm batch
# runs; Mpre lets Main's own host run (Main exits after it), I and I-before-pip also require guard's BLOCKING 0 (Main has
# exited). Never signals anything. 593's own Leader and Engineer must have ended their turns before Mpre.
members_idle() {
  local phase=$1 listing
  listing=$(ps -axww -o pid=,etime=,command= 2>&1) || { print "STOP: ps cannot list processes (${listing[1,120]}); run this step in a normal Terminal"; return 2; }
  local -a workers=(${${(f)"$(print -r -- $listing | grep -E -- '-m graphtraj\.execution\.runner_worker|-m graphtraj\.teams\.team_round' | grep -v -- 'grep -E')"}:#})
  print -r -- "members_idle [$phase]: Task $TASK_ID's Leader and Engineer must have ended their turns before the adoption; member Workers and swarm batches running now: ${#workers}"
  (( ${#workers} )) && print -l -- "  "${^workers[1,12]}
  (( ${#workers} == 0 )) || return 1
  if [[ $phase != Mpre ]]; then guard || return 1; fi
  print -r -- "members_idle [$phase]: no member execution is active: PASS"
}

# 593 C5 (correction 1): the uv tool environment and the interpreter uv based it on. $1 = the tool's bin/python.
# CHECK: sys.prefix is $UVT/tools/graftling and graftling is $GVERSION. REPORT: the base interpreter
# (sys._base_executable, else sys.base_prefix) and its class: uv-managed (under $UVT/python), conda (under the conda root)
# or other. A conda base prints a NOTE that is neither PASS nor FAIL: Main decides; C5r still runs.
c5_interp() {
  local py=$1 out prefix base version croot=${CONDABIN:h:h} class
  out=$($py -I -c 'import sys, graftling; print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix); print(graftling.__version__)' 2>&1) \
    || { print -r -- "CHECK 593 C5 one install from GitHub $GTAG in the uv tool environment $UVT/tools/graftling (sys.prefix), graftling $GVERSION: FAIL ($py: ${out[1,200]})"; return 1; }
  prefix=${${(f)out}[1]} base=${${(f)out}[2]} version=${${(f)out}[3]}
  print -r -- "uv tool python: $py | sys.prefix: $prefix | base interpreter: $base | graftling $version"
  if [[ ${prefix:A} == ${UVT:A}/tools/graftling && $version == $GVERSION ]]; then
    print -r -- "CHECK 593 C5 one install from GitHub $GTAG in the uv tool environment $UVT/tools/graftling (sys.prefix), graftling $GVERSION: PASS"
  else print -r -- "CHECK 593 C5 one install from GitHub $GTAG in the uv tool environment $UVT/tools/graftling (sys.prefix), graftling $GVERSION: FAIL"; return 1; fi
  case ${base:A}/ in
    ${UVT:A}/python/*) class=uv-managed ;;
    ${croot:A}/*) class=conda ;;
    *) case $base/ in $UVT/python/*) class=uv-managed ;; $croot/*) class=conda ;; *) class=other ;; esac ;;
  esac
  print -r -- "REPORT 593 C5 base interpreter: $base ($class)"
  [[ $class == conda ]] && print -r -- "NOTE 593 C5: the uv tool environment is based on conda's Python ($base); no install into conda was made; Main decides whether this meets requirement 5"
  return 0
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
    sleep ${ADOPT593_WAIT:-20}
  done
}

step_00() {
  mkdir -p $BASE/scratch
  say "shell (expect zsh) and PATH head"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"; print -l -- ${path[1,4]}
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
  print -r -- "provider used: Anthropic through claude's own login (clean environment: no provider credential variable passed)"
  ask_model MODEL-OK 00-model || { print "STOP: claude -p answer check failed (above): no answer, prompt echo, or the Harness AGENTS.md loaded (489). If it says login/API key: USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  print -r -- "provider used: OpenAI through codex's own login (clean environment: no provider credential variable passed)"
  say "579: Codex answers one line from the isolated $VPROJECT with its configured model and login (codex exec; no tools)"
  codex_answer 00 || { print "STOP: Codex did not answer CODEX-593-OK (above). If it says login: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
  say "560: scripts run through zsh, TMPDIR outside the Harness"
  print -r -- "this script: $THIS | interpreter: zsh $ZSH_VERSION"
  check_tmp || return 1
  say "593: Task state is already migrated (560); 593 does not touch it (information, read only)"
  print -r -- "Task directories: $(count $STATE/tasks/[^.]*(N/)) | task.md: $(count $STATE/tasks/*/task.md(N)) (expect 0) | definitions/*.md: $(count $STATE/tasks/*/definitions/*.md(N))"
  say "host quiet (the CPU report needs it): load average and running test runs (information)"
  print -r -- "load average: $(sysctl -n vm.loadavg 2>&1)"
  print -r -- "test runs now: $(ps -axww -o pid=,command= 2>/dev/null | grep -E 'run_test_shards|-m pytest' | grep -vc grep)"
  say "484/486: production agents control records before the install (states and notification fields; read only)"
  $CONDA -I $SD/ctl497.py snap $H $CTL/00.json
  say "490 / known interference: every budget_idle_timer now (listed only, never signalled)"; timer_list $R/00-timers-ps.txt
  say "production versions now (expect graphtraj 0.1.0 = ${OLD[1,8]} and graftling $GOLDVERSION, both from 579; pip check clean)"
  $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  $RT/bin/python -m pip check --disable-pip-version-check; print "pip check rc=$?"
  local d; for d in $(site)/graphtraj-*.dist-info(N) $(site)/graftling-*.dist-info(N); do
    print -r -- "production ${d:t} direct_url: $(cat $d/direct_url.json 2>/dev/null || print none)"; done
  print -r -- "(expected: both from 579's adoption/wheels-${OLD[1,8]}/: graphtraj-0.1.0-…whl and graftling-$GOLDVERSION-…whl)"
  print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')(expect agents agents-mcp now; I makes it subagents subagents-mcp)"
  say "plugin files and hashes (593 prediction: graftling 0.8.0..0.9.0 changes claude/host_context.mjs and plugin.py (591: TOOL, TOOLS, PREFIX, labels), so configuration --write changes hooks/host_context.mjs only (plugin593.py); V checks)"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  grep -nE '^const (TOOL|TOOLS|PLUGIN|SERVER|PREFIX) ' $PDIR/hooks/host_context.mjs | sed 's/^/production copy: /'
  say "entry files (hashes; .mcp.json: 515 left only '$NEWS')"; shasum -a 256 $ENTRIES; tree mcp $H/.mcp.json
  mcp_keys $H/.mcp.json
  say "Main-owned .claude/settings.local.json (read only)"; settings_view $H/.claude/settings.local.json
  say "backup must be absent; 579's backup $OLDBASE/backup is listed, never touched"
  ls -d $BK 2>&1; ls -ld $OLDBASE/backup 2>&1; [[ -e $OLDBASE/backup/COMPLETE ]] && print "579 backup COMPLETE marker: present" || print "579 backup COMPLETE marker: absent"
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "production holds graphtraj ${OLD[1,8]} + graftling $GOLDVERSION: the 593 markers must be absent now"; $CONDA -I $SD/markers.py $(site) absent | tail -1
  say "395 layout now (information)"
  $RT/bin/python -I $SD/onegraft.py $RT $GOLDVERSION | grep -E '^CHECK|layout:'
  say "526 .gitignore files in production's graftling data roots now (information only)"; gitignore_report
  say "Tasks whose members may run now (status not integrated): $(active_tasks)"
  say "running Task members (I waits for them)"; (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | tee $R/00-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/00-members.txt) (other Tasks' members may run now; I waits for them)"
  say "Task $TASK_ID members (Leader and Engineer; must be idle during I)"; grep -E "(^|[^0-9])$TASK_ID([^0-9]|\$)" $R/00-members.txt || print "none listed"
  say "N needs role opus_coding_team.advisor for Task $TASK_ID"
  grep -nE 'opus_coding_team|advisor' $H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) 2>&1 | grep -iE 'advisor' | head -12
  say "Task $TASK_ID ready for N's root dispatch: budget not stopped (expect stopped: false)"
  grep -E '^(stopped|corrections|allowance_minutes):' $STATE/tasks/$TASK/execution-budget.yml
  say "593 probe Task ready: Task $TASK_ID (N's dispatch and M's task_graph details) has a current definition"
  local cdef=${${${(M)${(f)"$(cat $STATE/tasks/$TASK/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  if [[ -n $cdef && -f $STATE/tasks/$TASK/$cdef ]]; then print "CHECK 593 probe Task $TASK_ID ready (current_definition $cdef exists): PASS"
  else print "CHECK 593 probe Task $TASK_ID ready (current_definition ${cdef:-none}): FAIL"; return 1; fi
  say "593 requirement 5 inputs (information): conda, uv, and the isolated uv tool directory C5 uses"
  print -r -- "conda: $CONDABIN -> ${CONDABIN:A} | $($CONDABIN --version 2>&1 | head -1) | envs: $(clean $CONDABIN env list 2>/dev/null | grep -vE '^#|^$' | awk '{print $1}' | tr '\n' ' ')"
  print -r -- "uv: $(command -v uv || print 'NOT FOUND') | $(uv --version 2>&1 | head -1)"
  print -r -- "C5 tool directory $UVT (must not exist yet, or be an earlier C5's): $([[ -e $UVT ]] && print exists || print absent)"
  say "current Claude Main Session"; local id=$(detect_main)
  if [[ -n $id ]]; then print -r -- $id > $BASE/main.session; MAIN=$id; print "MAIN=$id (saved to $BASE/main.session)"; else print "MAIN NOT FOUND"; fi
  say "processes using the venv now, classified (information only; Main's host is expected here)"
  guard || print "guard: BLOCKING at 00 is information only (Main's own host is expected here; I waits for members)"
  return 0
}

step_B() {
  say "the Worktree carries no product change beyond $C8 (only scripts/ differ)"
  product_guard || return 1
  rm -rf $SRC $GSRC $N; mkdir -p $SRC $GSRC $N   # this commit's own directories only
  # Information only. 593's candidate is GraphTraj dev 3eb21101 + correction 2's test fix; its identity is guarded by
  # product_guard and `git archive $TARGET`, so production installs exactly $C8.
  say "GraphTraj dev (information only)"
  local dv=$(git -C $WT rev-parse -q --verify refs/heads/dev 2>/dev/null)
  print -r -- "GraphTraj dev: ${dv:-NOT FOUND} | dev contains $C8: $(git -C $WT merge-base --is-ancestor $TARGET ${dv:-missing} 2>/dev/null && print yes || print no) | the wheel is built from git archive $TARGET"
  say "product diff production ${OLD[1,8]} -> $C8 (information; the 593 markers below are the gate)"
  print -r -- "git diff --stat ${OLD[1,8]} $C8 -- src plugins pyproject.toml: $(git -C $WT diff --shortstat $OLD $TARGET -- src plugins pyproject.toml)"
  say "graftling repository $G (read only here): tag $GTAG, dev, main"
  local gc=$(git -C $G rev-parse -q --verify "$GTAG^{commit}" 2>/dev/null) gm=$(git -C $G rev-parse -q --verify main 2>/dev/null) gd=$(git -C $G rev-parse -q --verify dev 2>/dev/null)
  print "$GTAG^{commit}: ${gc:-NOT FOUND} | tag object: $(git -C $G rev-parse -q --verify refs/tags/$GTAG 2>/dev/null || print none) | type: $(git -C $G cat-file -t $GTAG 2>/dev/null)"
  print "main: ${gm:-NOT FOUND} | dev: ${gd:-NOT FOUND} | main = $GTAG: $([[ -n $gc && $gc == $gm ]] && print yes || print NO) | dev contains $GTAG: $(git -C $G merge-base --is-ancestor ${gc:-missing} ${gd:-missing} 2>/dev/null && print yes || print NO)"
  [[ $gc == $GCOMMIT ]] && print "$GTAG peels to $GCOMMIT: yes" || { print "STOP: $GTAG^{commit} is ${gc:-missing}, not $GCOMMIT (graftling 0.9.0 (593)). Run rel first, or Main asks the Leader."; return 1; }
  [[ $(git -C $G cat-file -t refs/tags/$GTAG 2>/dev/null) == tag ]] && print "$GTAG is an annotated tag (cat-file -t: tag): yes" || { print "STOP: $GTAG is not an annotated tag (cat-file -t: $(git -C $G cat-file -t refs/tags/$GTAG 2>&1)). Main asks the Leader."; return 1; }
  print "$GTAG tagger: $(git -C $G for-each-ref --format='%(taggername) %(taggeremail) %(taggerdate:iso)' refs/tags/$GTAG)"
  print "$GTAG commit author / committer: $(git -C $G log -1 --format='%an %ae / %cn %ce' $gc) | parent: $(git -C $G rev-parse $gc~1)"
  git -C $G archive $GTAG | tar -x -C $GSRC || return 1
  git -C $WT archive $TARGET | tar -x -C $SRC || return 1
  [[ -e $SRC/src/graftling ]] && { print "STOP: $TARGET still carries src/graftling"; return 1; }
  print "graphtraj archive carries no src/graftling: yes"
  say "593: every version string of graftling $GTAG reads $GVERSION (archive root)"
  local vf vbad=0; for vf in src/graftling/__init__.py src/graftling/dsh/package.json src/graftling/pi/package.json src/graftling/claude-plugin/.claude-plugin/plugin.json; do
    local vl=$(grep -m1 -E '^__version__ = |"version": ' $GSRC/$vf 2>/dev/null)
    print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
  done
  (( vbad == 0 )) && print "CHECK 593 $GTAG version strings all $GVERSION: PASS" || { print "CHECK 593 $GTAG version strings all $GVERSION: FAIL"; return 1; }
  grep -m1 -E "^## $GVERSION " $GSRC/CHANGELOG.md | sed 's/^/CHANGELOG heading: /'
  [[ -f $GSRC/pyproject.toml ]] || { print "STOP: $GTAG lacks the root pyproject.toml"; return 1; }
  [[ ! -e $GSRC/package.json && ! -e $GSRC/src/graftling/dsh/plugin_python.py && ! -e $GSRC/.claude-plugin/marketplace.json ]] \
    && print "CHECK 593 $GTAG has no 0.7.0 install route (root package.json, dsh/plugin_python.py, root marketplace; 581): PASS" \
    || { print "CHECK 593 $GTAG has no 0.7.0 install route (root package.json, dsh/plugin_python.py, root marketplace; 581): FAIL"; return 1; }
  say "593 (591): $GTAG's console scripts are subagents and subagents-mcp, and no agents or agents-mcp"
  local eps=$(sed -n '/^\[project.scripts\]/,/^\[/p' $GSRC/pyproject.toml | grep -oE '^[A-Za-z0-9_-]+ *=' | tr -d ' =' | sort | tr '\n' ' ')
  print -r -- "  [project.scripts]: ${eps:-none}"
  [[ " $eps" == *" subagents "* && " $eps" == *" subagents-mcp "* && " $eps" != *" agents "* && " $eps" != *" agents-mcp "* ]] \
    && print "CHECK 593 $GTAG console scripts subagents, subagents-mcp and no agents, agents-mcp: PASS" \
    || { print "CHECK 593 $GTAG console scripts subagents, subagents-mcp and no agents, agents-mcp: FAIL"; return 1; }
  say "build with $CONDA (setuptools $($CONDA -c 'import setuptools; print(setuptools.__version__)'); --no-index --no-deps --no-build-isolation)"
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $SRC || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $GSRC || return 1
  say "the two wheels I installs, and sha256 (expect graphtraj-0.1.0 and graftling-$GVERSION in $N)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT; print "$GTAG ${gc}" > $N/GRAFTLING
  local all=($N/*.whl(N)) gv req
  [[ ${#all} == 2 && $(wheel_of graphtraj) == */graphtraj-0.1.0-* && $(wheel_of graftling) == */graftling-$GVERSION-* ]] || { print "STOP: wheel 名称不符（$N 只能有 graphtraj-0.1.0 与 graftling-$GVERSION）"; return 1; }
  gv=$(unzip -p $(wheel_of graftling) '*.dist-info/METADATA' 2>/dev/null | sed -n 's/^Version: //p')
  print "graftling wheel version: $gv"; [[ $gv == $GVERSION ]] || { print "STOP: graftling wheel version ${gv:-unreadable}, not $GVERSION"; return 1; }
  say "the new graphtraj's graftling requirement (wheel METADATA): satisfied by $GVERSION, NOT by production's $GOLDVERSION (a pair)"
  req=$(unzip -p $(wheel_of graphtraj) '*.dist-info/METADATA' | grep -E '^Requires-Dist: graftling')
  print "graphtraj wheel ${req:-Requires-Dist: NOT FOUND}"
  $CONDA -I -c 'import sys
from packaging.requirements import Requirement
r = Requirement(sys.argv[1].removeprefix("Requires-Dist: "))
new = r.specifier.contains(sys.argv[2])
verdict = {True: "PASS", False: "FAIL"}
print(f"CHECK 593 Requires-Dist {r} satisfied by {sys.argv[2]}: {verdict[new]}")
old = False
for other in sys.argv[3:]:   # production 0.8.0 and the next incompatible 0.10.0
    hit = r.specifier.contains(other); old = old or hit
    print(f"CHECK 593 Requires-Dist {r} NOT satisfied by {other}: {verdict[not hit]}")
sys.exit(0 if new and not old else 1)' "$req" $GVERSION $GOLDVERSION 0.10.0 || { print "STOP: the graphtraj requirement does not pair with graftling $GVERSION"; return 1; }
  say "both wheels = their git archives, file by file (gate)"
  $CONDA -I $SD/pkgdiff532.py graphtraj $(wheel_of graphtraj) archive:$SRC/src "593 graphtraj wheel equals git archive $C8" - || { print "STOP: the graphtraj wheel differs from git archive $C8"; return 1; }
  rm -rf $SRC-product0; mkdir -p $SRC-product0; git -C $WT archive $PRODUCT0 src | tar -x -C $SRC-product0 || return 1
  $CONDA -I $SD/pkgdiff532.py graphtraj $(wheel_of graphtraj) archive:$SRC-product0/src "593 graphtraj wheel content equals git archive ${PRODUCT0[1,8]} (GraphTraj dev; correction 2 changed tests only)" - || { print "STOP: the graphtraj wheel differs from git archive ${PRODUCT0[1,8]}"; return 1; }
  $CONDA -I $SD/pkgdiff532.py graftling $(wheel_of graftling) archive:$GSRC/src "593 graftling wheel equals git archive $GTAG" - || { print "STOP: the graftling wheel differs from git archive $GTAG"; return 1; }
  say "593 markers in the wheels (expect present)"
  rm -rf $W/wheelview-$C8; mkdir -p $W/wheelview-$C8; (cd $W/wheelview-$C8 && unzip -qo $(wheel_of graphtraj) 'graphtraj/*' && unzip -qo $(wheel_of graftling) 'graftling/*' && unzip -qo $(wheel_of graftling) '*.dist-info/entry_points.txt') || return 1
  $CONDA -I $SD/markers.py $W/wheelview-$C8 present || { print "STOP: a 593 marker is missing from the wheels"; return 1; }
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
  say "product guard (Worktree = $C8 outside scripts/)"; product_guard || return 1
  say "scratch venv: the $C8 graphtraj wheel + the $GTAG graftling wheel plus production's click, yaml, websockets"; scratch_venv || return 1
  # 593: production's plugin graphtraj-claude-host is written by graftling.claude.claude_host_plugin (claude/plugin.py)
  # from graftling/claude/host_context.mjs, with GraphTraj's host configuration (runtimes/claude/host.py). Prediction
  # from the diffs: graftling 0.8.0..0.9.0 changes host_context.mjs and plugin.py (591: TOOL, TOOLS = [TOOL, "tasks"],
  # PREFIX, labels) and GraphTraj eb009725..$C8 changes the plugin description (592). So hooks/host_context.mjs and
  # .claude-plugin/plugin.json are EXPECTED to change by exactly what plugin593.py names, hooks.json to stay, and the
  # plugin/hooks trust dialog for graphtraj-claude-host is expected at `claude --continue`. The copy is regenerated
  # only through the product (adopt_plugin.py regen = adoption_material + write_adoption here; configuration --write
  # in I), never by hand. Any other difference is shown and STOPS here.
  say "593 plugin prediction from the diffs (information)"
  print -r -- "graftling $GOLDTAG..$GTAG under src/graftling/claude: $(git -C $G diff --name-only $GOLDCOMMIT $GCOMMIT -- src/graftling/claude 2>&1 | tr '\n' ' ')"
  print -r -- "graphtraj ${OLD[1,8]}..$C8 under plugins/ and src/graphtraj/runtimes/claude: $(git -C $WT diff --name-only $OLD $TARGET -- plugins src/graphtraj/runtimes/claude 2>&1 | tr '\n' ' ')"
  say "candidate plugin: new code writes into a scratch copy of production's plugin (593: expected plugin.json description and hooks/host_context.mjs, by 591/592)"
  rm -rf $VPL; mkdir -p $VPL; cp -Rp $PDIR $VPL/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name changed=(); : > $R/V-plugin.diff
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; changed+=($name); diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  local extra=$(diff -rq $PDIR $VP 2>&1 | grep -vE 'plugin\.json|hooks\.json|host_context\.mjs' | tr '\n' ' ')
  print -r -- "V-plugin.diff: $(wc -l < $R/V-plugin.diff | tr -d ' ') lines ($R/V-plugin.diff) | other differences: ${extra:-none}"
  $CONDA -I $SD/plugin593.py $PDIR $VP; local prc=$?
  if [[ ${changed[*]} == '.claude-plugin/plugin.json hooks/host_context.mjs' && -z $extra ]] && (( prc == 0 )); then
    print "CHECK 593 candidate plugin as predicted (plugin.json description and hooks/host_context.mjs, by 591/592): PASS (the plugin/hooks trust dialog for graphtraj-claude-host is expected at claude --continue: USER trusts it)"
  else print "CHECK 593 candidate plugin as predicted (plugin.json description and hooks/host_context.mjs, by 591/592): FAIL (changed: ${changed[*]:-none} ${extra}; STOP: give $R/V-plugin.diff to the Leader)"; rc=1; fi
  (( ${#changed} )) && print "plugin dialog expected at claude --continue: yes (one: plugin/hooks trust for graphtraj-claude-host; choose trust)" > $R/V-dialog.txt || print "plugin dialog expected at claude --continue: no (plugin unchanged)" > $R/V-dialog.txt
  grep -q '^const SERVER = "graphtraj";' $VP/hooks/host_context.mjs && grep -q '^const TOOL = "subagents";' $VP/hooks/host_context.mjs \
    && grep -q '^const TOOLS = \[TOOL, "tasks"\];' $VP/hooks/host_context.mjs \
    && print "candidate host_context.mjs SERVER \"graphtraj\", TOOL \"subagents\", TOOLS [TOOL, \"tasks\"]: yes (the hook handles mcp__graphtraj__subagents and mcp__graphtraj__tasks)" \
    || { print "STOP: candidate host_context.mjs does not name server graphtraj, TOOL subagents and TOOLS [TOOL, \"tasks\"]"; rc=1; }
  say "graftling: production's $GOLDVERSION vs the $GTAG wheel (information: the files 0.8.0 changes)"
  $CONDA -I $SD/pkgdiff532.py graftling $(wheel_of graftling) $(site) "graftling $GTAG differs from production $GOLDVERSION (information)" - 2>&1 | sed -E 's/^CHECK /INFO /; s/: FAIL \(STOP\)$/: differs (expected; information, not a check)/; s/: FAIL( .*)?$/: differs (expected; information, not a check)\1/; s/: PASS/: same (information)/' | tail -2 | tee $R/V-gldiff.txt
  say "graphtraj: the $C8 wheel vs production's installed ${OLD[1,8]} (information)"
  $CONDA -I $SD/pkgdiff532.py graphtraj $(wheel_of graphtraj) $(site) "graphtraj $C8 differs from production ${OLD[1,8]} (information)" - 2>&1 | sed -E 's/^CHECK /INFO /; s/: FAIL \(STOP\)$/: differs (expected; information, not a check)/; s/: FAIL( .*)?$/: differs (expected; information, not a check)\1/; s/: PASS/: same (information)/' | tail -2 | tee $R/V-gtdiff.txt
  say "593 real entries in the scratch venv: graphtraj-mcp tools/list is exactly subagents, tasks and 'agents' is unknown; the Codex hooks entry (isolated $VPROJECT)"
  vproject_init $VV/bin/graphtraj || rc=1
  (cd ${TMPDIR:-/tmp} && clean $P -I $SD/mcp593.py scratch-graphtraj-mcp $VPROJECT $VV/bin/graphtraj-mcp) || rc=1
  codex_hook_check $VV || rc=1
  print -r -- "scratch venv bin: $(print -l $VV/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')(expect subagents subagents-mcp only)"
  [[ -x $VV/bin/subagents && -x $VV/bin/subagents-mcp && ! -e $VV/bin/agents && ! -e $VV/bin/agents-mcp ]] \
    && print "CHECK 593 scratch venv bin has subagents, subagents-mcp and no agents, agents-mcp: PASS" \
    || { print "CHECK 593 scratch venv bin has subagents, subagents-mcp and no agents, agents-mcp: FAIL"; rc=1; }
  say "593 markers: present in the candidate, absent in production"
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
  say "read only against the real project: archives, configuration, roles; Task graph of production state (migrated by 560)"
  touch $W/V-marker-$C8
  $P -I $SD/adopt_plugin.py readcheck $H $STATE || rc=1
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
  say "claude -p calls tasks discover and subagents status (no dialog)"; cv
  print -r -- 'Call mcp__graphtraj__tasks once with {"action":"discover"} and mcp__graphtraj__subagents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 300 $C -p --model $MODEL --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__tasks,mcp__graphtraj__subagents) > $R/Vc-stream.jsonl
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
  say "593: init lists mcp server graphtraj only and the tools mcp__graphtraj__subagents and tasks, no mcp__graphtraj__agents or mcp__agents__*"
  local irc=0; $CONDA -I $SD/rec593.py init $R/Vc-stream.jsonl || irc=1
  tree stream $R/Vc-stream.jsonl mcp__graphtraj__tasks mcp__graphtraj__subagents || return 1
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
  say "wheels (expect 2 x OK: graphtraj and graftling $GVERSION)"; cat $N/COMMIT $N/GRAFTLING; (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  [[ $(<$N/COMMIT) == $TARGET ]] || { print "COMMIT 不是目标提交"; return 1; }
  local all=($N/*.whl(N)); [[ ${#all} == 2 && -n $(wheel_of graphtraj) && $(wheel_of graftling) == */graftling-$GVERSION-* ]] || { print "STOP: $N 必须只有 graphtraj-0.1.0 与 graftling-$GVERSION 的 wheel"; return 1; }
  say "entry files still as V saw them (expect 3 x OK)"; shasum -a 256 -c $W/entries-$C8.sha256 || { print "入口文件在 V 之后被改过；重新运行 V。"; return 1; }
  say "484: production agents control records right before pip"
  $CONDA -I $SD/ctl497.py snap $H $CTL/I.json || return 1
  say "install BOTH wheels as a pair (graphtraj ${OLD[1,8]} -> $C8, graftling $GOLDVERSION -> $GVERSION; --no-deps --no-index --force-reinstall)"
  date +%s > $R/I-install-start.epoch   # 490: timers started before this are old (listed, not judged)
  $P -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  say "installed graphtraj and graftling files vs the new wheels, file by file (no $GOLDVERSION file or dist-info left)"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS|^FAIL' $R/I-verify.txt; (( rc == 0 )) || return 1
  local left=($S/graftling-$GOLDVERSION.dist-info(N))
  (( ${#left} == 0 )) && print "CHECK 593 graftling $GOLDVERSION dist-info gone: PASS" || { print "CHECK 593 graftling $GOLDVERSION dist-info gone: FAIL"; return 1; }
  say "entry scripts of the wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of graftling); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graftling.control as c, graftling.tool_descendants as td, graphtraj.execution.runner_worker as rw; print("graftling", graftling.__version__); print(h.__file__); print("457", c._stop_escaped.__name__, "| 459 SAMPLE_SECONDS", td.SAMPLE_SECONDS, "| 460", rw.TOOL_PROCESSES_RECORD); from graftling.tool import TOOL_NAME; print("591 TOOL_NAME", TOOL_NAME); assert graftling.__version__ == "0.9.0" and TOOL_NAME == "subagents"' || return 1
  $P -c 'import importlib.metadata as md, pathlib, graftling, graphtraj; gs = pathlib.Path(graftling.__file__).parent; print("395 layout graftling", graftling.__version__, "| distributions", sum(1 for d in md.distributions() if (d.metadata["Name"] or "").lower() == "graftling"), "| beside graphtraj:", gs.parent == pathlib.Path(graphtraj.__file__).parent.parent, "| graftling.mjs:", (pathlib.Path(graphtraj.__file__).parent / "runtimes/graftling.mjs").is_file(), "| graphtraj requires", [r for r in md.requires("graphtraj") if r.startswith("graftling")]); assert graftling.__version__ == "0.9.0"' || return 1
  say "593 (591): .venv-runtime/bin has subagents and subagents-mcp, and no agents or agents-mcp (pip removed 0.8.0's scripts)"
  print -r -- "production bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')"
  [[ -x $RT/bin/subagents && -x $RT/bin/subagents-mcp && ! -e $RT/bin/agents && ! -e $RT/bin/agents-mcp ]] \
    && print "CHECK 593 production bin has subagents, subagents-mcp and no agents, agents-mcp: PASS" \
    || { print "CHECK 593 production bin has subagents, subagents-mcp and no agents, agents-mcp: FAIL"; return 1; }
  say "593 sources: the wheels graphtraj and graftling were installed from (direct_url.json) and what they were built from"
  local d; for d in $S/graphtraj-0.1.0.dist-info $S/graftling-$GVERSION.dist-info; do print -r -- "${d:t} direct_url: $(cat $d/direct_url.json 2>/dev/null || print none)"; done
  local du=$(cat $S/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null) dg=$(cat $S/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null)
  [[ $du == *"wheels-$C8/graphtraj-0.1.0-"*".whl"* && $dg == *"wheels-$C8/graftling-$GVERSION-"*".whl"* ]] && print "CHECK 593 direct_url of both names the wheels-$C8 wheels: PASS" || { print "CHECK 593 direct_url of both names the wheels-$C8 wheels: FAIL"; return 1; }
  print -r -- "built from: graphtraj git archive $TARGET, graftling git archive $(<$N/GRAFTLING) (B: wheels = archives file by file; proddiff above: installed bytes = these wheels)"
  say "593 markers in the installed site-packages (expect PASS 8/8)"; $CONDA -I $SD/markers.py $S present || return 1
  say "395 layout in production: exactly one graftling, from the wheel file"
  $P -I $SD/onegraft.py $RT $GVERSION || return 1
  say "395: production's graftling.mjs resolves graftling to the sibling directory (empty environment: no python fallback)"
  node_resolve $RT || return 1
  date +%s > $R/I-install-end.epoch   # 490: timers started after this run the installed $C8 code (new)
  # 593: the hook copy is regenerated ONLY here, through the product (configuration --write), never edited by hand.
  say "configuration --write from the new installation (as 515/525/528/532/560/571/579; 593 expects plugin.json description and hooks/host_context.mjs changed by 591/592 only)"
  (cd $H && clean $P -m graphtraj.runtimes.claude.host configuration --write --project $H --claude $(claude_bin)) > $R/I-configuration.txt 2>&1
  local crc=$?; print "configuration --write rc=$crc (output lines: $(wc -l < $R/I-configuration.txt); kept in $R/I-configuration.txt)"; (( crc == 0 )) || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  local pch=$(diff -rq $BK/plugin $PDIR 2>&1 | sed -E 's|^Files .*/plugin/([^ ]+) and .*|\1|' | tr '\n' ' ')
  print -r -- "plugin files changed by the install: ${pch:-none} (V expected: $(cat $R/V-dialog.txt 2>/dev/null))"
  $CONDA -I $SD/plugin593.py $BK/plugin $PDIR
  [[ $pch == '.claude-plugin/plugin.json hooks/host_context.mjs ' ]] && print "CHECK 593 installed plugin changed as V predicted (plugin.json description and hooks/host_context.mjs): PASS (at claude --continue: the plugin/hooks trust dialog for graphtraj-claude-host; USER trusts it)" \
    || { print "CHECK 593 installed plugin changed as V predicted (plugin.json description and hooks/host_context.mjs): FAIL (changed: ${pch:-none}; V validated this copy, so I continues; at claude --continue trust the plugin/hooks dialog if it shows, and tell Main)"; }
  grep -nE '^const (TOOL|TOOLS|SERVER) ' $PDIR/hooks/host_context.mjs | sed 's/^/installed hook copy: /'
  say "CHECKs after configuration --write"
  mcp_keys $H/.mcp.json || return 1
  local f; for f in $ENTRIES; do
    if cmp -s $f $BK/entries/${${f#$H/}//\//__}; then print "bytes unchanged: ${f#$H/}"
    else print "changed: ${f#$H/} (before -> after, secret-like values hidden; not expected for 593: tell Main)"
      $CONDA -I $SD/adopt_tree.py redactjson $BK/entries/${${f#$H/}//\//__} > $BK/diff.before
      $CONDA -I $SD/adopt_tree.py redactjson $f > $BK/diff.after; diff $BK/diff.before $BK/diff.after; rm -f $BK/diff.before $BK/diff.after; fi
  done
  settings_view $H/.claude/settings.local.json
  tree mcp $H/.mcp.json
  say "also unchanged (information; any FAILED means another writer: tell Main)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  say "593 real entries of the installed venv (run in the isolated $VPROJECT): graphtraj-mcp tools/list is exactly subagents, tasks and 'agents' is unknown (the same command .mcp.json names); the Codex hooks entry"
  print -r -- ".mcp.json graphtraj command: $($CONDA -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["mcpServers"]["graphtraj"]; print(s.get("command"), *(s.get("args") or []))' $H/.mcp.json 2>&1)"
  (cd ${TMPDIR:-/tmp} && clean $P -I $SD/mcp593.py production-graphtraj-mcp $VPROJECT $RT/bin/graphtraj-mcp) || return 1
  codex_hook_check $RT || return 1
  return 0
}

step_R() {
  local KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S) rc=0 f
  date '+R start %F %T'; mkdir -p $KEEP
  say "before restoring: how the venv differs from the pre-install manifest"; tree compare $BK/venv.manifest $RT | tail -1
  # BOTH packages come back from the backup's whole venv (graphtraj ${OLD[1,8]}, graftling $GOLDVERSION). 593 does not
  # touch the Task state, so R does not either.
  local SNOW=($RT/lib/python*/site-packages(N/)) SOLD=($BK/venv/lib/python*/site-packages(N/))
  if [[ -n ${SNOW[1]:-} && -n ${SOLD[1]:-} ]]; then
    print -r -- "before R: graftling installed $(print -l ${SNOW[1]}/graftling-*.dist-info(N:t) | tr '\n' ' ')| backup $(print -l ${SOLD[1]}/graftling-*.dist-info(N:t) | tr '\n' ' ')"
    local gd=$(diff -rq -x __pycache__ -x '*.dist-info' ${SOLD[1]}/graphtraj ${SNOW[1]}/graphtraj 2>&1 | wc -l | tr -d ' ')
    print -r -- "graphtraj package installed vs backup: $gd differing entries (none after an earlier R)"
  else print "site-packages not found in one of the trees: not compared (tell Main)"; fi
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
  say "archives stay; versions (information)"; tree versions $SESS
  say "graftling and graphtraj after R identical to the backup (expect PASS twice)"
  local SA=($RT/lib/python*/site-packages(N/))
  $CONDA -I $SD/pkgdiff532.py graftling ${SA[1]:-$RT/missing} ${SOLD[1]:-$BK/venv/missing} "593 graftling restored (after R vs backup)" - | tail -1; (( ${pipestatus[1]} == 0 )) || rc=1
  $CONDA -I $SD/pkgdiff532.py graphtraj ${SA[1]:-$RT/missing} ${SOLD[1]:-$BK/venv/missing} "593 graphtraj restored (after R vs backup)" - | tail -1; (( ${pipestatus[1]} == 0 )) || rc=1
  print -r -- "restored bin: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')"
  [[ -x $RT/bin/agents && -x $RT/bin/agents-mcp && ! -e $RT/bin/subagents && ! -e $RT/bin/subagents-mcp ]] \
    && print "CHECK 593 R: bin has 0.8.0's agents, agents-mcp again and no subagents, subagents-mcp: PASS" \
    || { print "CHECK 593 R: bin has 0.8.0's agents, agents-mcp again and no subagents, subagents-mcp: FAIL"; rc=1; }
  local gv=$($RT/bin/python -I -c 'import graftling; print(graftling.__version__)' 2>&1)
  [[ $gv == $GOLDVERSION ]] && print "CHECK 593 R: graftling is $GOLDVERSION again: PASS" || { print "CHECK 593 R: graftling is $GOLDVERSION again: FAIL ($gv)"; rc=1; }
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
# 576 (571 F1): the child was created WITHOUT tools; with graftling 0.8.0 its default set has Bash, so it runs the
# command and gives the done reply (571's probe expected 0.7.0, where such a child had no Bash).
check('576 child created without tools (stored selection.tools is null)', sel.get('tools') is None, f"tools={sel.get('tools')!r}")
done_word = 'DONE-593'
if reply.is_file():
    check(f'576 child without tools ran Bash and replied {done_word} (member quotes the last_message)',
          done_word in reply.read_text(errors='replace'), f'{reply}')
else:
    check(f'576 child without tools ran Bash and replied {done_word}', 'PENDING', f'save the member reply to {reply}')
def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from _walk(v)
    elif isinstance(o, list):
        for v in o: yield from _walk(v)
bash = []
for f in sorted(sess.glob('*/session.jsonl')):
    try: text = f.read_text(errors='replace')
    except OSError: continue
    if f'echo {name}-tool' not in text: continue
    for line in text.splitlines():
        if f'echo {name}-tool' not in line: continue
        try: ev = json.loads(line)
        except ValueError: continue
        if any(d.get('type') == 'tool_use' and d.get('name') == 'Bash' and f'echo {name}-tool' in json.dumps(d.get('input'))
               for d in _walk(ev)):
            bash.append(str(f)); break
check(f'576 a Bash tool_use running echo {name}-tool is in a Session archive', 'PASS' if bash else
      'CHECK BY HAND (no archive under the swarm sessions holds it; Main reads the child with agents read)', ', '.join(bash[:2]) or 'none')
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

R_HINT="回退（Main 先问 USER；USER 同意后先在 Main 里 /exit，再在 Terminal 运行）: zsh $BK/tools/steps.zsh R"

# GR (593, as 579): read only. The product guard, then the G record $GREC (newest $W/G-<c8>-*/ unless ADOPT593_GREC
# names one; run.txt: candidate, graftling commit, pytest temp root and launch environment; suite.txt: totals and exit;
# shards/*.log: the FAILED/ERROR node ids). The candidate's src/tests/plugins/pyproject must equal $C8's and the
# graftling commit must be $GCOMMIT exactly (the v0.9.0 wheel). 593 expectations printed by GR:
# tests/test_runtime_distribution.py::test_wheels_have_separate_owners PASSES now (it is not in 516); and
# tests/test_execution_budgets.py::test_installed_runner_delivers_elapsed_notices_to_final_leader is not in 516, so a
# failure of it is NEW and goes to suite-base. sr_classify (shared with SR, as verify-586's SR) reads
# WHOLE node ids from the shard logs with scripts/verify-581/suiteids.py (suite.txt's summary cuts an id at its first
# space, so suite.txt is read only when there are no shard logs) and calls an id known only when 516's CURRENT
# definition (through its task.yml current_definition) names its test function. Any other id is NEW, and so is any
# ABNORMAL shard other than test failures (exit 1; exit 5 only under a rehearsal filter).
# 593: the two tests the Leader named, read from the shard logs' -rA lines (PASSED/FAILED/ERROR <id>).
named_tests() {
  local id st
  for id in tests/test_runtime_distribution.py::test_wheels_have_separate_owners \
            tests/test_execution_budgets.py::test_installed_runner_delivers_elapsed_notices_to_final_leader; do
    st=$(grep -hoE "^(PASSED|FAILED|ERROR) $id( |\$)" $GREC/shards/*.log(N.) $GREC/suite.txt 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
    print -r -- "named: $id: ${st:-not seen} ($([[ $id == *separate_owners ]] && print 'PASS expected now' || print 'not in 516: a failure is NEW and goes to suite-base'))"
  done
}
sr_classify() {   # sets SR_NEW (0/1), SR_ANY (ids seen) and SR_IDS (the NEW ids); writes $GREC/new-ids.txt
  local K=$KNOWN516 line t id; SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): $K"
  [[ -f $K ]] || { print -r -- "STOP: cannot read 516's current definition '$K'"; SR_NEW=1; return 1; }
  local -a logs=($GREC/shards/*.log(N.)); (( $#logs )) || logs=($GREC/suite.txt)
  print -r -- "node ids read from: $([[ ${logs[1]} == */shards/* ]] && print "${#logs} shard logs (whole ids)" || print 'suite.txt only (no shard logs; ids may be cut at a space)')"
  for id in ${(f)"$($CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print "  (no FAILED/ERROR lines)"
  # Every ABNORMAL line is read (595's SR read only 'exit N' lines and so missed a shard that timed out). 593: a shard
  # 'timed out after <s> s' (run_test_shards.py) is ABNORMAL and NEW, named as such; any other non-test-failure is too.
  local timeouts=0
  for line in ${(f)"$(grep -E '^ABNORMAL ' $GREC/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *': exit 5') grep -q '^REHEARSAL' $GREC/run.txt && print -r -- "  rehearsal filter, nothing collected: $line" \
                     || { print -r -- "  ABNORMAL shard: $line"; SR_NEW=1; } ;;
      *'timed out after '*) print -r -- "  ABNORMAL shard TIMED OUT (NEW): $line"; SR_NEW=1; timeouts=$(( timeouts + 1 )) ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -r -- "  shard timeouts ('timed out after' lines): $timeouts$( (( timeouts )) && print ' (NEW: each is a failure of this run, not a test id; give the shard log to the Leader)')"
  print -l -- $SR_IDS > $GREC/new-ids.txt
}
step_GR() {
  local ok=0 cand gl tot ex
  product_guard || { print "product guard STOP: the G record cannot stand for this Worktree"; ok=1; }
  [[ -f $GREC/run.txt && -f $GREC/suite.txt ]] || { print "STOP: no G record at $GREC (run.txt, suite.txt): run G first"; print "CHECK 593 GR (guard + G record): FAIL"; return 1; }
  grep -q '^exit=' $GREC/suite.txt || { print -r -- "G has not finished yet ($GREC/suite.txt has no 'exit=' line$([[ -f $GREC/wait.txt ]] && print -r -- "; queue: $(tail -1 $GREC/wait.txt)")). Rerun GR when it has."; print "CHECK 593 GR (guard + G record): FAIL (not finished)"; return 1; }
  print -r -- "G record: $GREC"; sed 's/^/  run.txt: /' $GREC/run.txt
  cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $GREC/run.txt | head -1)
  gl=$(grep -oE 'git archive [0-9a-f]{40}' $GREC/run.txt | head -1 | awk '{print $3}')
  local cd=$(git -C $WT diff --name-only ${cand:-missing} $TARGET -- $GUARDED 2>&1)
  print -r -- "candidate: ${cand:-NOT FOUND} | git diff ${cand[1,8]} $C8 -- ${GUARDED[*]}: ${${cd//$'\n'/ }:-empty} | same product: $([[ -n $cand && -z $cd ]] && print yes || print NO)"
  [[ -n $cand && -z $cd ]] || ok=1
  print -r -- "graftling commit of the wheel: ${gl:-NOT FOUND} | = $GTAG ($GCOMMIT): $([[ $gl == $GCOMMIT ]] && print yes || print NO)"
  [[ $gl == $GCOMMIT ]] || ok=1
  grep -m1 'pytest temp root' $GREC/run.txt | sed 's/^/pytest temp: /'
  grep -q 'outside the Harness' $GREC/run.txt || { print "STOP: run.txt does not record a pytest temp root outside the Harness"; ok=1; }
  grep -m1 '^launch environment' $GREC/run.txt || { print "STOP: run.txt does not record G's clean launch environment"; ok=1; }
  tot=$(grep -E '^=*.* (passed|failed)|^[0-9]+ (failed|errors|passed)' $GREC/suite.txt | tail -1); ex=$(sed -n 's/^exit=//p' $GREC/suite.txt | tail -1)
  print -r -- "totals: ${tot:-NOT FOUND} | exit: ${ex:-NOT FOUND}"
  grep -m1 'test interpreter dependencies' $GREC/run.txt || { print "STOP: run.txt does not record the test interpreter's click/PyYAML/websockets/pytest versions"; ok=1; }
  grep -q 'click 8.5.0' $GREC/run.txt && print "test interpreter click = production's 8.5.0: yes" || { print "test interpreter click is not production's 8.5.0 (564): NO"; ok=1; }
  sr_classify
  named_tests
  if (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && $SR_ANY == 1 ) ]]; then print "CHECK 593 G record (${cand[1,8]} + $GTAG) no new failure: PASS"
  else print "CHECK 593 G record (${cand[1,8]} + $GTAG) no new failure: FAIL$( (( $#SR_IDS )) && print " ($#SR_IDS NEW ids: run SR for the ready-to-paste suite-base command)")"; ok=1; fi
  print "CHECK 593 GR (guard + G record): $( (( ok == 0 )) && print PASS || print FAIL)"
  return $ok
}
# SR (579, Main, read only; as verify-586's SR): the newest G record's FAILED/ERROR node ids, whole, from the shard logs,
# classed against 516's current definition; writes new-ids.txt and prints the suite-base command with each NEW id a
# separate shell-quoted argument (and the --from form).
step_SR() {
  [[ -f $GREC/suite.txt ]] || { print -r -- "no G record yet ($GREC); run: zsh $THIS G"; return 1; }
  cat $GREC/run.txt; tail -6 $GREC/suite.txt
  grep -q '^exit=' $GREC/suite.txt || { print -r -- "G still running (no exit= line yet); next: zsh $THIS SR (later)"; return 1; }
  sr_classify
  named_tests
  grep -E '^(=+ )?[0-9]+ (passed|failed)|^[0-9]+ (passed|failed)' $GREC/shards/*(N.) | sed "s#^$GREC/shards/##"
  print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  print -r -- "NEW node ids ($#SR_IDS, one per line): $GREC/new-ids.txt"
  if (( $#SR_IDS )); then
    # Each id its own single-quoted word ((@qq) quotes element by element; joining first made one argument, 583).
    print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)SR_IDS}"
    print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)GREC}/new-ids.txt"
  else print -r -- "next: none (no NEW id); zsh $THIS V"; fi
  return $SR_NEW
}
# suite-base (593, Main, only for NEW ids): reruns exactly those ids on GraphTraj $GTBASE (= the candidate's product)
# with graftling $GBASE as a wheel (dev before the release commit), then on the candidate with G's venv (v0.9.0 wheel),
# each in a clean environment with a fresh pytest temp root under TMPDIR; suiteids.py classifies per id.
step_suite_base() {
  setopt local_options no_bg_nice
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then
    [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file '${IDS[2]:-}'; SR writes it (new-ids.txt)"; return 2; }
    ids=(${(f)"$(<${IDS[2]})"})
  else ids=("${(@)IDS}"); fi
  ids=(${ids:#})
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>...   (SR prints both)"; return 2; }
  check_tmp || return 1
  print -l -- "  id: "${^ids}
  local o orc; o=$(other_suites); orc=$?
  (( orc == 2 )) && { print -r -- "STOP: $o"; return 1; }
  [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun this command later"; print -r -- $o; return 1; }
  local B=${BASE:A}/graphtraj-base VB=${BASE:A}/sbvenv-${GTBASE[1,8]} VC=${BASE:A}/gvenv-$C8 S=$(site) D
  [[ -x $VC/bin/python ]] || { print -r -- "STOP: no G venv $VC; run G first"; return 1; }
  if [[ ! -d $B/.git ]]; then
    rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  if [[ ! -f $VB/installed ]]; then
    rm -rf -- $VB $VB-src && mkdir -p $VB-src/graftling $VB-src/wheels || return 1
    git -C $G archive $GBASE | tar -x -C $VB-src/graftling || { print -r -- "STOP: graftling $GBASE not in $G"; return 1; }
    $CONDA -m venv --system-site-packages $VB || return 1; D=($VB/lib/python*/site-packages(N))
    cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml(N) $S/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D[1]/ || return 1
    local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
    $CONDA -m pip wheel $pip -w $VB-src/wheels $VB-src/graftling > /dev/null || return 1
    $VB/bin/python -m pip install $pip $VB-src/wheels/graftling-*.whl && $VB/bin/python -m pip install $pip -e $B > /dev/null || return 1
    print -r -- "graftling $GBASE (wheel) + graphtraj $GTBASE (editable)" > $VB/installed
  fi
  local O=$W/suite-base-$(date +%Y%m%dT%H%M%S) side dir V rc RUNTMP; mkdir -p $O || return 1
  print -l -- $ids > $O/ids.txt
  print -r -- "base: $B ($(<$VB/installed)) | candidate: $WT with $VC (graftling $GTAG wheel)"
  for side dir V in base $B $VB candidate $WT $VC; do
    RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-593-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $dir | pytest temp root $RUNTMP (TMPDIR, outside the Harness) | launch environment: HOME USER PATH TERM TMPDIR LANG only"
    (cd $dir && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $O/$side-collected.txt 2>&1)
    $CONDA -I $SUITEIDS present $O/$side-collected.txt $O/ids.txt > $O/$side-ids.txt 2> $O/$side-missing.txt
    [[ -s $O/$side-missing.txt ]] && print -r -- "not on $side (not run there): $(tr '\n' ' ' < $O/$side-missing.txt)"
    local -a run=(${(f)"$(<$O/$side-ids.txt)"})
    if (( $#run )); then
      (cd $dir && clean env TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $O/$side.txt 2>&1); rc=$?
    else print -r -- "(no id present on $side)" > $O/$side.txt; rc=5; fi
    print -r -- "$side: pytest exit=$rc, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $O/$side.txt | tail -1) (output: $O/$side.txt)"
    $CONDA -I $SUITEIDS errors $O/$side.txt > $O/$side-errors.txt
  done
  say "classification (each id: base, then candidate)"
  $CONDA -I $SUITEIDS classify $O/ids.txt $O/base.txt $O/candidate.txt | tee $O/classification.txt; local fails=${pipestatus[1]}
  print -r -- "first E line + raise location per failing test: $O/base-errors.txt and $O/candidate-errors.txt"
  print -r -- "next: give $O/classification.txt to the Leader; a candidate-only id is a regression of this release"
  return $fails
}

# rel (593, as 579's; Main): the graftling release in <Harness>/graftling. Fetch the release branch from the bundle by exact SHA
# (one commit on $GBASE), bring dev to it (fast-forward when dev is still $GBASE; else, e.g. after 570 merged, a merge of
# $GCOMMIT into dev with the noreply identity that STOPS on a conflict, leaving dev as it was), fast-forward main to
# $GCOMMIT, and create the annotated tag $GTAG at $GCOMMIT with the noreply tagger. No push. dev goes first: if its merge
# stops, main and the tag are untouched.
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
RELMSG="graftling 0.9.0 (incompatible): the MCP tool agents is renamed subagents and the commands agents and agents-mcp are renamed subagents and subagents-mcp, with no alias (591); allow rules, --allowedTools and a create's tools/disallowed_tools naming the old tool must be changed"
rel_wt() {  # the worktree that has branch $1 checked out, if any
  git -C $G worktree list --porcelain | awk -v b="branch refs/heads/$1" '/^worktree /{w=substr($0,10)} $0==b{print w}'
}
step_rel() {
  local gd gm gt dw mw
  say "graftling repository $G before: dev, main, tags, working trees (each must be clean)"
  gd=$(git -C $G rev-parse -q --verify refs/heads/dev); gm=$(git -C $G rev-parse -q --verify refs/heads/main)
  gt=$(git -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}" 2>/dev/null)
  dw=$(rel_wt dev); mw=$(rel_wt main)
  print -r -- "dev: ${gd:-NOT FOUND} | main: ${gm:-NOT FOUND} | $GTAG: ${gt:-absent} | dev checked out in: ${dw:-no worktree} | main checked out in: ${mw:-no worktree}"
  if [[ -n $gt ]]; then
    [[ $gt == $GCOMMIT && $gm == $GCOMMIT ]] && git -C $G merge-base --is-ancestor $GCOMMIT $gd && { print "already released: $GTAG = main = $GCOMMIT, dev contains it (nothing to do)"; rel_verify; return; }
    print "STOP: $GTAG exists at $gt, not as expected ($GCOMMIT = main, inside dev). Main asks the Leader; nothing changed."; return 1
  fi
  git -C $G merge-base --is-ancestor $GBASE $gd || { print "STOP: graftling dev $gd does not contain $GBASE (593's base). Main asks the Leader; nothing changed."; return 1; }
  git -C $G merge-base --is-ancestor $gm $GBASE || { print "STOP: graftling main $gm is not an ancestor of $GBASE, so it cannot fast-forward to $GCOMMIT. Main asks the Leader; nothing changed."; return 1; }
  local w; for w in $dw $mw; do
    [[ -z $(git -C $w status --porcelain --untracked-files=no 2>/dev/null) ]] || { print "STOP: the worktree $w has uncommitted changes to tracked files; nothing changed"; return 1; }
  done
  say "bundle $BUNDLE (sha256 $(shasum -a 256 $BUNDLE | cut -c1-16)…): verify and fetch $GBRANCH by exact SHA"
  git -C $G bundle verify -q $BUNDLE || { print "STOP: the bundle does not verify against $G"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | awk '{print $1}') == $GCOMMIT ]] || { print "STOP: the bundle head is not $GCOMMIT"; return 1; }
  git -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/${GBRANCH}" || return 1
  [[ $(git -C $G rev-parse $GBRANCH) == $GCOMMIT && $(git -C $G rev-parse $GBRANCH~1) == $GBASE ]] \
    && print "$GBRANCH = $GCOMMIT (parent $GBASE): yes | author / committer: $(git -C $G log -1 --format='%an <%ae> / %cn <%ce>' $GCOMMIT)" \
    || { print "STOP: $GBRANCH is not the expected one commit on $GBASE"; return 1; }
  if [[ $gd == $GBASE || $gd == $GCOMMIT ]]; then
    say "dev: fast-forward $gd -> $GCOMMIT"
    if [[ -n $dw ]]; then git -C $dw merge --ff-only -q $GCOMMIT || return 1
    else git -C $G update-ref refs/heads/dev $GCOMMIT $gd || return 1; fi
    print "dev: fast-forwarded to $GCOMMIT"
  elif git -C $G merge-base --is-ancestor $GCOMMIT $gd; then
    print "dev $gd already contains $GCOMMIT (an earlier rel): unchanged"
  else
    say "dev moved since dispatch ($GBASE -> $gd: $(git -C $G rev-list --count $GBASE..$gd) commits, e.g. 570): merge $GCOMMIT into dev as $RELNAME <$RELMAIL>; STOP on a conflict"
    git -C $G log --oneline $GBASE..$gd | sed 's/^/  dev since dispatch: /'
    local msg="Merge graftling 0.9.0 (593) into dev"
    if [[ -n $dw ]]; then
      if ! git -C $dw -c user.name=$RELNAME -c user.email=$RELMAIL merge --no-ff --no-edit -q -m "$msg" $GCOMMIT; then
        print -r -- "conflicted files: $(git -C $dw diff --name-only --diff-filter=U | tr '\n' ' ')"
        git -C $dw merge --abort; print "STOP: merging $GCOMMIT into dev conflicts (above); the merge was aborted, dev is still $gd; main and $GTAG untouched. Main asks the Leader."; return 1
      fi
    else
      # Declared first: `local x=$(cmd)` returns local's status, which would hide merge-tree's conflict exit (1).
      local tree mc mrc
      tree=$(git -C $G merge-tree --write-tree $gd $GCOMMIT 2>&1); mrc=$?
      if (( mrc != 0 )); then print -r -- "merge-tree: exit $mrc | ${tree//$'\n'/ | }"; print "STOP: merging $GCOMMIT into dev conflicts (above); dev is still $gd; main and $GTAG untouched. Main asks the Leader."; return 1; fi
      mc=$(GIT_AUTHOR_NAME=$RELNAME GIT_AUTHOR_EMAIL=$RELMAIL GIT_COMMITTER_NAME=$RELNAME GIT_COMMITTER_EMAIL=$RELMAIL git -C $G commit-tree ${tree%%$'\n'*} -p $gd -p $GCOMMIT -m "$msg") || return 1
      git -C $G update-ref refs/heads/dev $mc $gd || return 1
    fi
    print -r -- "dev: merged, now $(git -C $G rev-parse dev) (parents: $(git -C $G log -1 --format=%P dev)) | author / committer: $(git -C $G log -1 --format='%an <%ae> / %cn <%ce>' dev)"
  fi
  say "main: fast-forward $gm -> $GCOMMIT"
  if [[ -n $mw ]]; then git -C $mw merge --ff-only -q $GCOMMIT || return 1
  else git -C $G update-ref refs/heads/main $GCOMMIT $gm || return 1; fi
  say "annotated tag $GTAG at $GCOMMIT, tagger $RELNAME <$RELMAIL>"
  GIT_COMMITTER_NAME=$RELNAME GIT_COMMITTER_EMAIL=$RELMAIL git -C $G tag -a $GTAG $GCOMMIT -m "$RELMSG" || return 1
  rel_verify
}
rel_verify() {
  local gt=$(git -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(git -C $G rev-parse dev) gm=$(git -C $G rev-parse main) ok=0
  print -r -- "$GTAG -> $gt | dev $gd | main $gm | type $(git -C $G cat-file -t refs/tags/$GTAG) | tagger $(git -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG)"
  [[ $gt == $GCOMMIT ]] && print "CHECK 593 $GTAG peels to $GCOMMIT: PASS" || { print "CHECK 593 $GTAG peels to $GCOMMIT: FAIL"; ok=1; }
  [[ $gm == $GCOMMIT ]] && print "CHECK 593 graftling main == $GTAG: PASS" || { print "CHECK 593 graftling main == $GTAG: FAIL"; ok=1; }
  if [[ $gd == $GCOMMIT ]]; then print "CHECK 593 graftling dev == $GTAG (fast-forward) or a noreply merge containing it: PASS (fast-forward)"
  elif git -C $G merge-base --is-ancestor $GCOMMIT $gd && [[ $(git -C $G log -1 --format='%ae %ce' $gd) == "$RELMAIL $RELMAIL" && $(git -C $G log -1 --format=%P $gd) == *$GCOMMIT* ]]; then
    print "CHECK 593 graftling dev == $GTAG (fast-forward) or a noreply merge containing it: PASS (merge $gd)"
  elif git -C $G merge-base --is-ancestor $GCOMMIT $gd; then print "CHECK 593 graftling dev == $GTAG (fast-forward) or a noreply merge containing it: PASS (dev contains it; later commits on dev)"
  else print "CHECK 593 graftling dev == $GTAG (fast-forward) or a noreply merge containing it: FAIL"; ok=1; fi
  [[ $(git -C $G cat-file -t refs/tags/$GTAG) == tag && $(git -C $G for-each-ref --format='%(taggeremail)' refs/tags/$GTAG) == "<$RELMAIL>" ]] \
    && print "CHECK 593 $GTAG is annotated with the noreply tagger: PASS" || { print "CHECK 593 $GTAG is annotated with the noreply tagger: FAIL"; ok=1; }
  print -r -- "version at $GTAG: $(git -C $G show ${GTAG}:src/graftling/__init__.py | grep -E '^__version__') | root package.json: $(git -C $G show ${GTAG}:package.json 2>/dev/null | grep -m1 '"version"' | tr -d ' ,') | version on dev: $(git -C $G show dev:src/graftling/__init__.py | grep -E '^__version__')"
  return $ok
}
# rp (593, Main): outward-facing push of graftling dev, main and v0.9.0 to its configured remote (fast-forward only; no
# force). The USER pre-approved this push (Worldline user-decision 20261124T030105.522331+0900), so Main runs it with
# ADOPT593_PUSH_CONFIRMED=yes without asking again; the variable stays so that the push is never started by accident.
step_rp() {
  local remote=$(git -C $G remote | head -1)
  [[ -n $remote ]] || { print "graftling has no remote: nothing to push"; return 0; }
  rel_verify || { print "STOP: rel is not complete"; return 1; }
  print -r -- "remote $remote: $(git -C $G remote get-url $remote)"
  print -r -- "remote before: $(git -C $G ls-remote $remote refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" | tr '\n' ' ')"
  print -r -- "will push: dev ($(git -C $G rev-parse dev)) main ($(git -C $G rev-parse main)) refs/tags/$GTAG (fast-forward only; no force)"
  [[ ${ADOPT593_PUSH_CONFIRMED:-} == yes ]] || { print "STOP: the push is outward-facing. It is pre-approved by the USER (Worldline user-decision 20261124T030105.522331+0900); run: ADOPT593_PUSH_CONFIRMED=yes zsh $THIS rp"; return 1; }
  git -C $G push $remote refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/${GTAG} || return 1
  local now=$(git -C $G ls-remote $remote refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}")
  print -r -- "remote now: ${now//$'\n'/ }"
  [[ $(print -r -- $now | awk '$2=="refs/heads/main"{print $1}') == $GCOMMIT && $(print -r -- $now | awk '$2=="refs/tags/'$GTAG'^{}"{print $1}') == $GCOMMIT && $(print -r -- $now | awk '$2=="refs/heads/dev"{print $1}') == $(git -C $G rev-parse dev) ]] \
    && print "CHECK 593 remote main and $GTAG = $GCOMMIT, remote dev = local dev: PASS" || { print "CHECK 593 remote main and $GTAG = $GCOMMIT, remote dev = local dev: FAIL"; return 1; }
}
# gh (593, Main, after rp; result 4): GitHub's graftling main and v0.9.0 must resolve to $GCOMMIT, read with git
# ls-remote only. 581 removed the bare-URL `dsh plugin add` route 571's gh used, so gh installs nothing: no host
# installation, dotfile or ~/.dsh is touched.
step_gh() {
  local ok=0 now rm rt rto lto
  now=$(git ls-remote $GURL refs/heads/main refs/tags/$GTAG "refs/tags/$GTAG^{}" 2>&1) || { print -r -- "STOP: git ls-remote $GURL failed: ${now[1,200]}"; return 1; }
  print -r -- "GitHub ($GURL): ${now//$'\n'/ | }"
  rm=$(print -r -- $now | awk '$2=="refs/heads/main"{print $1}')
  rt=$(print -r -- $now | awk -v r="refs/tags/$GTAG^{}" '$2==r{print $1}')
  rto=$(print -r -- $now | awk -v r="refs/tags/$GTAG" '$2==r{print $1}')
  lto=$(git -C $G rev-parse -q --verify refs/tags/$GTAG 2>/dev/null)
  [[ $rm == $GCOMMIT ]] && print "CHECK 593 gh: GitHub graftling main = $GCOMMIT: PASS" || { print "CHECK 593 gh: GitHub graftling main = $GCOMMIT: FAIL (${rm:-absent})"; ok=1; }
  [[ $rt == $GCOMMIT ]] && print "CHECK 593 gh: GitHub $GTAG resolves to $GCOMMIT: PASS" || { print "CHECK 593 gh: GitHub $GTAG resolves to $GCOMMIT: FAIL (${rt:-absent})"; ok=1; }
  [[ -n $rto && $rto != $GCOMMIT && $rto == $lto ]] && print "CHECK 593 gh: GitHub $GTAG is the local annotated tag object ($rto): PASS" \
    || { print "CHECK 593 gh: GitHub $GTAG is the local annotated tag object: FAIL (remote ${rto:-absent}, local ${lto:-absent})"; ok=1; }
  print "installed: nothing (no dsh plugin add, no host, dotfile or ~/.dsh change)"
  return $ok
}
# Test runs of anyone on this host (Main's suite queue is serial). Never our own: G starts its run only after this is
# empty. Lines 'pid command'. A ps that cannot list processes is reported (exit 2), never read as "no other suite".
other_suites() {
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then
    print -r -- "ps cannot list processes here (${listed[1,160]}); run this step in your own terminal"; return 2
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E|other_suites'
  return 0
}
# G (593, as 579's; Main): the full suite of this Worktree's HEAD with the $GTAG wheel from B, in the background (~25-30 min).
# Pytest temp under TMPDIR, outside the Harness. Main's suite queue is serial: while another suite runs, G WAITS (it
# says so now, and every ${ADOPT593_GWAIT:-60} s in <record>/wait.txt) and starts by itself; it never stops silently.
# When it ends (suite.txt's last line 'exit=N'), GR reads the newest record.
step_G() {
  setopt local_options no_bg_nice
  check_tmp || return 1
  [[ -n $(wheel_of graftling) ]] || { print "no graftling wheel in $N: run B first"; return 1; }
  product_guard || return 1
  local pscheck; pscheck=$(other_suites) || { print -r -- "STOP: $pscheck (G never reads a failed ps as 'no other suite'; nothing was built or started)"; return 1; }
  # Resolved paths (/tmp is a link to /private/tmp on macOS): tests/pi_parity_scenarios.py maps sys.prefix and the
  # installed graftling by their resolved paths, so a venv reached through a link fails test_pi_generic_execution.
  local GV=${BASE:A}/gvenv-$C8 O=$W/G-$C8-$(date +%Y%m%dT%H%M%S) RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-593-G-$(date +%Y%m%dT%H%M%S) D
  rm -rf $GV; $CONDA -m venv --system-site-packages $GV || return 1
  # Production's own dependency versions (click 8.5.0 and the rest), copied read only from $RT; they shadow the base
  # Python's copies (564: a Pi test needs click 8.5.0, Miniconda has 8.2.1). pytest comes from the base Python.
  local S=$(site); D=($GV/lib/python*/site-packages(N))
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml(N) $S/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D[1]/ || return 1
  $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(wheel_of graftling) || return 1
  $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  mkdir -p $O $RUNTMP
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=${TMPDIR:-/tmp}, outside the Harness)"
    print -r -- "launch environment: HOME USER PATH TERM TMPDIR LANG only (clean(); no provider credential variable reaches the suite)"
    print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT ($GTAG, $(wheel_of graftling))"; print -r -- "python: $GV/bin/python"
    (cd ${TMPDIR:-/tmp} && $GV/bin/python -I -c 'import importlib.metadata as m, click, yaml, websockets, pytest; print("test interpreter dependencies:", " | ".join(f"{n} {m.version(n)} ({p.__file__})" for n, p in (("click", click), ("PyYAML", yaml), ("websockets", websockets), ("pytest", pytest))))'); } > $O/run.txt
  local extra=(${(Q)${(z)${ADOPT593_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $O/run.txt
  : > $O/suite.txt   # GR reads 'not finished' until the last line is exit=N
  local busy brc every=${ADOPT593_GWAIT:-60}
  busy=$(other_suites); brc=$?
  if (( brc == 2 )); then
    print -r -- "STOP: $busy (G never reads a failed ps as 'no other suite')"; print "exit=ps-failed (G did not start)" >> $O/suite.txt; return 1
  fi
  if [[ -n $busy ]]; then
    print -r -- "WAITING: Main's suite queue is serial and another suite is running now; G is queued and starts by itself when it ends (checked every $every s; nothing to do meanwhile; progress: tail -f $O/wait.txt):"
    print -r -- "$busy" | sed 's/^/  running: /' | cut -c1-220
  else print "no other suite is running: G starts now"; fi
  (
    while true; do
      busy=$(other_suites); brc=$?
      if (( brc == 2 )); then
        print -r -- "$(date +%T) STOP: $busy; G did not start" >> $O/wait.txt; print "exit=ps-failed (G did not start)" >> $O/suite.txt; exit 1
      fi
      [[ -z $busy ]] && break
      print -r -- "$(date +%T) waiting for another suite: $(print -r -- $busy | awk '{print $1}' | tr '\n' ' ')" >> $O/wait.txt; sleep $every
    done
    print -r -- "$(date +%T) started" >> $O/wait.txt
    cd $WT && clean env TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra > $O/suite.txt 2>&1
    print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended ($(tail -1 $O/suite.txt))" >> $O/wait.txt
    $CONDA -I $SD/fails593.py $O/failures.txt $O/suite.txt $O/shards/*(N.) > /dev/null
  ) < /dev/null > /dev/null 2>&1 &!
  cat $O/run.txt; print -r -- "$([[ -n $busy ]] && print queued || print started) in the background at $(date +%T); output: $O/suite.txt (last line 'exit=N' when it ends; about 25-30 min of run time once started)"
  next "（G 结束后，suite.txt 最后一行 exit=N）zsh $THIS GR    （GR 自动读最新的 $W/G-$C8-*；也可 ADOPT593_GREC=$O）"
}

case $STEP in
help) print "顺序: 00 → scan（旧名扫描，安装前）→ rel（graftling 发布：dev 到 $GTAG（快进，或 dev 已移动时做 noreply 合并，冲突即停），main 快进到 $GTAG，建注释 tag）→ rp（推送 main 与 tag：USER 已预先同意，Worldline user-decision 20261124T030105.522331+0900）→ gh（结果 4：只读确认 GitHub 的 main 与 $GTAG 指向 $GCOMMIT，不安装）→ B → G（全套测试；另一套在跑时排队等待）→ GR（有 NEW 时 → SR → suite-base）→ V → Vc（若要求则先 USER 做 Vu）→ [Main 先问 USER] scanhome → Mpre → [593 的 Leader 与 Engineer 已结束各自的回合；Main 先问 USER] USER /exit Main → I（USER：备份并安装两个 wheel）→ USER: cd $H && claude --continue（预计出现 graphtraj-claude-host 的插件/hooks 信任框：选信任）→ M → Mr → Mp → Mps → inbox → Nw → N → Nr → Nt → scan（安装后）→ C5（结果 5，gh 之后）→ C5u（USER）→ C5r → X（更正 3：在 C5 项目的 graftling host 上）→ done → [Leader 接受 593] → [Main 把本 Task 的分支集成进 GraphTraj dev] → T；任何时候列计时器: timers；备份完成后可回退: R（Main 先问 USER；两个包、插件与入口文件；593 不动 Task 状态）。"
  print "USER 只做: Vu（仅当 Vc 要求；信任框 'Yes, proceed'）、/exit Main 与 I（Main 先问）、claude --continue（预测出现 graphtraj-claude-host 的插件/hooks 信任框：选信任，见 V），失败时 R（Main 先问）；scanhome 读 USER 的 ~/.claude 允许规则（只读，Main 先问 USER）。rp 的推送与 Claude 登录已由 USER 预先同意（20261124T030105.522331+0900）。其余都由 Main 运行。"
  next "zsh $THIS 00" ;;

rel) cv; print "[rel] Main. graftling 0.9.0 发布：从 $BUNDLE 按 SHA 取 $GBRANCH（$GCOMMIT，父提交 $GBASE），dev 到 $GCOMMIT（dev 仍为 ${GBASE[1,8]} 时快进；否则以 $RELNAME <$RELMAIL> 合并，冲突即中止并 STOP），main 快进到 $GCOMMIT，建注释 tag $GTAG（tagger $RELNAME <$RELMAIL>）。不推送。对话框: 无。< 10 秒。只改 $G 的 dev、main、$GBRANCH 与 tag。"
  [[ -e $R/rel.txt ]] && mv $R/rel.txt $R/rel-$(date +%Y%m%dT%H%M%S).txt   # earlier rel output kept; the summary reads this run only
  if logged $R/rel.txt step_rel; then
    summary rel "$(grep -E '^(dev:|already|CHECK|version at|.*= $GCOMMIT)' $R/rel.txt)"
    print "成功: 四行 CHECK 593 PASS（$GTAG peels to $GCOMMIT；main == $GTAG；dev == $GTAG (fast-forward) 或含它的 noreply 合并；annotated, noreply tagger）；version at $GTAG: __version__ = \"$GVERSION\"；root package.json: \"version\":\"$GVERSION\"。"
    print "dev 合并冲突时 rel 会中止合并并 STOP（dev、main、tag 都不变），交 Leader。"
    print "\n推送 graftling main 与 tag 是对外操作，单独一步 rp；USER 已预先同意（Worldline user-decision 20261124T030105.522331+0900），Main 直接运行；rp 之后运行 gh（结果 4，只读）。"
    print "B 不需要候选在 GraphTraj dev 上（它从 git archive $C8 构建；$C8 就是 GraphTraj dev）。"
    next "ADOPT593_PUSH_CONFIRMED=yes zsh $THIS rp   （然后 zsh $THIS gh，再 zsh $THIS B）"
  else print "\nrel STOP（见上）。把 $R/rel.txt 交给 Main/Leader。"; exit 1; fi ;;

rp) cv; print "[rp] Main。USER 已预先同意本次推送（Worldline user-decision 20261124T030105.522331+0900），不再另问。对外推送 graftling dev、main 与 $GTAG 到它的 remote（只快进，不 force）。对话框: 无（git 凭据由用户的 git 配置提供；若 git 要登录，用用户平常的 GitHub 登录）。< 30 秒。"
  logged $R/rp.txt step_rp || { print "\nrp 没有推送（见上）。"; exit 1; }
  print "成功: 'CHECK 593 remote main and $GTAG = $GCOMMIT, remote dev = local dev: PASS'。"
  next "zsh $THIS gh" ;;

gh) cv; print "[gh] Main，rp 之后（结果 4）。只用 git ls-remote 读 $GURL：main 与 $GTAG 都要指向 $GCOMMIT，$GTAG 是本地那个注释 tag 对象。本步不安装任何东西，不碰宿主安装、点文件或 ~/.dsh（C5 另行在隔离目录里从 $GTAG 安装）。对话框: 无。< 10 秒。"
  : > $R/gh.txt
  if logged $R/gh.txt step_gh; then
    summary gh "$(grep -E '^(GitHub|installed|CHECK|STOP)' $R/gh.txt)"
    print "成功: 'CHECK 593 gh: GitHub graftling main = $GCOMMIT: PASS'；'CHECK 593 gh: GitHub $GTAG resolves to $GCOMMIT: PASS'；'CHECK 593 gh: GitHub $GTAG is the local annotated tag object (…): PASS'；'installed: nothing'。"
    next "zsh $THIS B    （若 B 已做过: zsh $THIS G）"
  else print "\ngh 不通过（见上）。把 $R/gh.txt 交给 Main/Leader；生产未被改动。"; exit 1; fi ;;

scan) print "[scan] Main，只读，I 之前与 I 之后各一次（第二次在 Nt 之后）。在 Harness 的现用配置与真实启动脚本/包装里找旧名（mcp__graphtraj__agents、mcp__graftling__agents、mcp__plugin_<p>_agents__agents、tools/allowedTools/disallowed_tools 里的 agents、agents-mcp 与 bin/agents），逐条打印 file:line，并把现用配置、Harness 文档（采用后由 Main 更新）与历史记录分开。不读用户主目录（那是 scanhome）。对话框: 无。< 10 秒。"
  if [[ -e $R/I.ok ]]; then phase=after-I; else phase=before-I; fi
  logged $R/scan-$phase.txt $CONDA -I $SD/scan593.py live $H $phase
  summary scan "$(grep -E '^REPORT|LIVE |console scripts|launch scripts' $R/scan-$phase.txt)"
  if [[ $phase == before-I ]]; then
    print "成功（I 之前）: 每个现用命中都列出（预计 .claude/skills/graphtraj-claude-host/hooks/host_context.mjs 的 const TOOLS = [\"agents\", \"tasks\"]，以及 .venv-runtime/bin 的 agents、agents-mcp；这些由 I 通过产品更新）。其它现用命中（roles.yml、settings、.codex、启动脚本）: 交 Leader，I 之前决定如何处理（本 Task 不手改它们）。"
    next "zsh $THIS rel"
  else
    print "成功（I 之后）: 'REPORT 593 old-name scan [after-I]: live configuration hits 0'，console scripts 只有 subagents 与 subagents-mcp。docs 命中只是报告（Main 在采用后更新 Harness 文档）。现用命中不为 0: 交 Main/Leader。"
    next "zsh $THIS C5"
  fi ;;

scanhome) print "[scanhome] Main，只读，只在 Main 问过 USER 且 USER 同意之后运行（读 USER 主目录里的 ~/.claude/settings.json 与 ~/.claude.json）。只打印命中旧名的规则字符串及其键路径，不打印其它任何值；不改动任何文件。对话框: 无。< 5 秒。"
  [[ ${ADOPT593_HOME_ASKED:-} == yes ]] || { print "STOP: Main 先问 USER 是否允许只读检查 ~/.claude/settings.json 与 ~/.claude.json 里的允许规则；USER 同意后运行: ADOPT593_HOME_ASKED=yes zsh $THIS scanhome"; exit 1; }
  logged $R/scanhome.txt $CONDA -I $SD/scan593.py home $HOME/.claude/settings.json $HOME/.claude.json
  print "说明: 命中的规则是 USER 自己的设置；本 Task 不改它们。若有命中，第一次以新名调用 mcp__graphtraj__subagents 时可能出现 Claude Code 的工具权限框（见 M）：选 'Yes'（只本次），并告诉 Main；是否改规则由 USER 决定。"
  next "zsh $THIS Mpre" ;;

G) cv; print "[G] Main. 全套测试：本 Worktree HEAD + B 的 $GTAG wheel，6 shards 后台，开始后约 25-30 分钟；pytest 临时目录在 TMPDIR=${TMPDIR:-/tmp}（Harness 之外）。Main 的全套测试队列是串行的：另一套测试在跑时，G 会说明它在等待，并在那套结束后自己开始（不会悄悄停下）。对话框: 无。期间不要再启动别的测试。"
  logged $R/G.txt step_G || exit 1 ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE（scratch、main.session）、$VPROJECT 与 $R。约 2 分钟。"
  [[ -e $R/00.txt && ! -e $R/00-first.txt ]] && mv $R/00.txt $R/00-first.txt && print "previous 00.txt kept as $R/00-first.txt"
  : > $R/00.txt
  logged $R/00.txt step_00 || { print "\n00 STOP（see the STOP line above / 见上面的 STOP 行）。把 $R/00.txt 交给 Main，不要继续。"; exit 1; }
  summary 00 "$(grep -E '^claude:|^codex|ZSH_VERSION|inherited|answer|plugins in init|load average|test runs now|control records|timer pid|zombies|579 backup|Claude Code installed|^Version|pip check rc|direct_url|production bin|production copy|markers expected|CHECK|mcp.json servers|enabledMcpjsonServers|isolat|TMPDIR|task.md|running lines|may run now|^stopped|MAIN=|MAIN NOT|volume ids|^guard|advisor|^conda:|^uv:|C5 tool directory' $R/00.txt)"
  print "成功: 'claude:' 行给出路径与版本（Claude Code installed 已记录）；'answer check (expect clean): OK'（模型 $MODEL、已登录；USER 已预先同意 593 使用其 Claude 登录）；'CHECK 593 Codex answers CODEX-593-OK …: PASS'（codex configured model 行）；'TMPDIR=… (outside the Harness)'；graphtraj 0.1.0 与 graftling $GOLDVERSION（两个 direct_url 都是 579 的 wheels-${OLD[1,8]}）；pip check rc=0；production bin: agents agents-mcp；'markers expected absent: PASS (8/8)'；'CHECK 515 .mcp.json has graphtraj, no agents …: PASS'；'isolation: OK'；task.md: 0；stopped: false；roles 有 advisor；$BK 'No such file'；579 backup COMPLETE marker: present；'CHECK 593 probe Task 593 ready …: PASS'；conda:、uv: 两行有路径；MAIN=<id>。"
  print "running lines 可以不为 0（其它 Task 的成员）；I 会等它们结束，不结束它们。若 answer 有 login/API key 字样: USER 在 Terminal 运行 claude（或 codex login）登录后重跑 00。"
  next "zsh $THIS scan   （然后 zsh $THIS rel）" ;;

B) cv; print "[B] Main. 两个 wheel：graphtraj（git archive $C8）与 graftling（git -C $G archive $GTAG，从 archive 根目录构建）；I 两个一起装。不联网、不改 graftling 仓库和生产。对话框: 无。< 2 分钟。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked|peels|annotated|tagger|author|^main:|\^\{commit\}|product guard|GraphTraj dev|CHANGELOG heading|wheel version|Requires-Dist|CHECK|markers expected|carries' $R/B.txt)"
    print "成功: 'product guard: $C8 vs ${PRODUCT0[1,8]}: src plugins pyproject.toml identical | every difference in src tests plugins pyproject.toml: tests/test_mcp_adoption.py …' 与 'product guard: PASS'；'GraphTraj dev: … dev contains $C8: …' 只是信息；'CHECK 593 graphtraj wheel content equals git archive ${PRODUCT0[1,8]} …: PASS'；'$GTAG peels to $GCOMMIT: yes' 与 'annotated … yes'；'CHECK 593 $GTAG version strings all $GVERSION: PASS'；$N 有 graphtraj-0.1.0 与 graftling-$GVERSION 两个 wheel；'CHECK 593 Requires-Dist … satisfied by $GVERSION: PASS' 与 '… NOT satisfied by $GOLDVERSION: PASS'、'… NOT satisfied by 0.10.0: PASS'；'CHECK 593 $GTAG console scripts subagents, subagents-mcp and no agents, agents-mcp: PASS'；两行 'CHECK 593 … wheel equals git archive …: PASS'；'markers expected present: PASS (8/8)'；carries graftling/: 0；leaked: 0。"
    next "zsh $THIS G    （Main 的全套测试队列串行：另一套在跑时 G 会排队等待并说明）"
  else print "\nB 失败。把 $R/B.txt 交给 Main（product guard STOP: Worktree 的 src/tests/plugins/pyproject 不等于 $C8；'peels' 或 'annotated' 失败: 先运行 rel，或交 Leader）。"; exit 1; fi ;;

GR) cv; print "[GR] Main，G 结束后。只读：G 的记录 ${GREC}（本 Worktree 候选 + $GTAG wheel）。检查守卫、候选与 $C8 的产品文件相同、graftling 提交 = $GCOMMIT、测试解释器的 click/PyYAML/websockets/pytest 版本、总数与 exit、FAILED/ERROR 的完整 node id（从 shard 日志读，suiteids.py；已知只有 516 当前定义所列，其余都是 NEW）。对话框: 无。< 10 秒。"
  [[ -e $R/GR.txt ]] && cp -p $R/GR.txt $R/GR-$(date +%Y%m%dT%H%M%S).txt   # earlier GR results are kept
  : > $R/GR.txt   # a new GR replaces the old verdict: an earlier PASS never survives a later FAIL (I reads this file)
  logged $R/GR.txt step_GR; rc=$?
  summary GR "$(grep -E '^(product guard|STOP|G record|candidate|graftling commit|pytest temp|launch environment|totals|516|node ids|  known|  NEW|  ABNORMAL|  shard timeouts|named:|CHECK)' $R/GR.txt)"
  print "成功: 'product guard: PASS'；'candidate: … same product: yes'；'graftling commit of the wheel: $GCOMMIT | = $GTAG …: yes'；'totals: … passed …' 与 'exit: 0'（或只有 'known (516)' 行）；'CHECK 593 G record … no new failure: PASS' 与 'CHECK 593 GR (guard + G record): PASS'。FAIL: 不要继续，交 Leader（I 会拒绝运行）。"
  (( rc == 0 )) && next "zsh $THIS V" || { print "\nGR FAIL。把 $R/GR.txt 交给 Main/Leader；有 NEW id 时先运行 SR（打印可直接粘贴的 suite-base 命令）。"; next "zsh $THIS SR"; }; exit $rc ;;

SR) cv; print "[SR] Main，只读（如 verify-586 的 SR）。最新 G 记录的 FAILED/ERROR 完整 node id（从 shard 日志读；suite.txt 的摘要会在第一个空格处截断 id），按 516 当前定义分为 known 或 NEW；写 new-ids.txt；有 NEW 时打印 suite-base 命令（每个 id 是单独的参数）。对话框: 无。< 10 秒。"
  logged $R/SR.txt step_SR; exit $? ;;

suite-base) cv; print "[suite-base] Main，仅当 SR 列出 NEW id。在 GraphTraj ${GTBASE[1,8]} + graftling ${GBASE[1,8]}（wheel，发布前）与候选（G 的 venv，$GTAG wheel）上各重跑这些 id；干净环境（无 provider 凭据），pytest 临时目录在 TMPDIR=${TMPDIR:-/tmp}（Harness 之外）。对话框: 无。"
  logged $R/suite-base.txt step_suite_base; exit $? ;;

V) cv; print "[V] Main. 安装前校验。对话框: 无。只读真实项目；scratch venv、候选插件、入口文件预测都在生产之外。约 2 分钟。"
  rm -f $R/V.ok   # only this run's result counts for I
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|CHECK|^(PASS|FAIL):|markers expected|STOP|✘ lines|read_session|task graph|product guard: PASS|plugin dialog|^graftling v|^graphtraj [0-9a-f]' $R/V.txt)"
    print "成功: CHANGED .claude-plugin/plugin.json、SAME hooks/hooks.json、CHANGED hooks/host_context.mjs，'CHECK 593 plugin differs by exactly 591/592 (hook module lines, plugin.json description): PASS' 与 'CHECK 593 candidate plugin as predicted (plugin.json description and hooks/host_context.mjs, by 591/592): PASS'（claude --continue 时预计出现 graphtraj-claude-host 的插件/hooks 信任框：选信任）；INFO 行只是信息（differs (expected; …)）；'CHECK 593 scratch-graphtraj-mcp MCP tools/list is exactly subagents, tasks: PASS' 与 '… tool agents is unknown …: PASS'；'CHECK 593 scratch venv bin has subagents, subagents-mcp …: PASS'；两行 'CHECK 593 Codex hooks entry …: PASS'；"
    print "  'markers expected present: PASS (8/8)' 与 'markers expected absent: PASS (8/8)'；'503 layout: PASS' 与两行 node resolves PASS；候选 ✘ 不多于 baseline；read_session failures=0 与 task graph of the clone（生产 Task 状态，只读）；无 STOP。"
    next "zsh $THIS Vc"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

Vc) print "[Vc] Main. 隔离项目 $VPROJECT 里用新 wheel 的真实 claude -p（先确认 isolation: OK）。对话框: 无。约 2 分钟。"
  : > $R/Vc.txt; rm -f $R/Vc.ok
  logged $R/Vc.txt vc_setup || { print "\nVc 准备失败，把 $R/Vc.txt 交给 Main。"; exit 1; }
  logged $R/Vc.txt vc_stream; rc=$?
  if [[ $(grep 'graphtraj-claude-host loaded:' $R/Vc.txt | tail -1) == *'loaded: NO'* ]]; then
    print "\n插件未加载：Claude Code 只在已信任的文件夹加载项目插件。由 USER 做一次 Vu（$VPROJECT），然后 Main 重跑 Vc。"
    next "USER: zsh $THIS Vu    （之后 Main: zsh $THIS Vc）"; exit 1
  fi
  if (( rc == 0 )); then
    touch $R/Vc.ok
    summary Vc "$(grep -E '^(PASS|FAIL)|loaded:|CHECK 515' $R/Vc.txt | tail -8)"
    print "成功: 'isolation: OK'，'CHECK 515 .mcp.json has graphtraj, no agents …: PASS'，'answer check: OK'，'graphtraj-claude-host loaded: YES'，PASS mcp__graphtraj__tasks 与 PASS mcp__graphtraj__subagents，四行 'CHECK 593 init …: PASS'。"
    next "zsh $THIS Mpre    （GR 为 PASS 之后；然后 USER: /exit Main，再在 Terminal 运行 zsh $THIS I）"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（只有 Vc 要求时；需要终端和对话框，Main 做不了）。$(cv)"
  print "在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框（一个）: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若没有出现这个框，直接 /exit。若再问项目的 MCP server 'graphtraj' 或插件/hooks，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

Mpre) need_main; cv; print "[Mpre] Main，就在 USER /exit Main 之前（V、Vc 通过且 GR 为 PASS 之后）。486：重启前的生产 agents 控制记录快照（只读）。593：采用只在没有成员运行时进行：593 的 Leader 与 Engineer 必须已结束各自的回合，其它 Task 也没有成员在运行；有则 STOP（从不发信号）。对话框: 无。约 1 分钟。"
  grep -q "^CHECK 593 GR (guard + G record): PASS" $R/GR.txt 2>/dev/null && print "GR: PASS (CHECK 593 GR (guard + G record): PASS)" || print "GR 还不是 PASS（$R/GR.txt 没有 'CHECK 593 GR (guard + G record): PASS'）：先运行 GR；I 会拒绝运行。"
  members_idle Mpre 2>&1 | tee -a $R/Mpre.txt; (( ${pipestatus[1]} == 0 )) || { print "\nMpre STOP: 有成员在运行（见上）。等它们结束（593 的 Leader 与 Engineer 先结束回合），再重跑 Mpre；不要结束任何进程。"; exit 1; }
  $CONDA -I $SD/ctl497.py snap $H $CTL/Mpre.json 2>&1 | tee -a $R/Mpre.txt
  print "成功: 'GR: PASS' 与 'control records snapshot Mpre.json: agents=… executions=…'。Mps 在 claude --continue 之后对比它。"
  print "\n为什么要重启 Main: Main 的 tasks/agents 调用在它的 host 进程（graphtraj.runtimes.claude.host serve）里执行，该进程一直使用启动时载入的 graphtraj ${OLD[1,8]} 与 graftling $GOLDVERSION；安装会在它运行时替换这些文件。所以 Main 在 I 之前退出，I 安装完成后才用 claude --continue 恢复（新 host 载入新代码）。503 的保护也要求安装时 Main 已退出。"
  print "\n下一步是 USER 的，Main 先问 USER（需要 USER 在 Main 里 /exit）：USER 同意后先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。I 会等其它 Task（$(active_tasks)）的成员结束（不要结束它们）。"
  next "（Main 先问 USER；USER 同意并已在 Main 里 /exit 后，在 Terminal）zsh $THIS I" ;;

I) need_main
  print "[I] USER（Main 先问 USER；USER 同意后先在 Main 里 /exit，再在普通 Terminal 运行本步）。等待成员结束、备份、安装两个 wheel、复核真实入口（graphtraj-mcp、Codex hooks）。不动 Task 状态。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。约 5 分钟（等待时间另计）。"; cv
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。若它是一次放弃的 I 留下的（没有 INSTALL-STARTED）: 告诉 Main，由 Main 把它改名移开后再运行 I。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  grep -q "^CHECK 593 GR (guard + G record): PASS" $R/GR.txt 2>/dev/null || { print "GR 还不是 PASS（$R/GR.txt 没有 'CHECK 593 GR (guard + G record): PASS'）。先由 Main 运行 GR。没有改动任何东西。"; exit 1; }
  product_guard || { print "Worktree 守卫 STOP（见上）。没有改动任何东西。"; exit 1; }
  print "确认已在 Claude Code Main 里输入 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  members_idle I 2>&1 | tee -a $R/I.txt; (( ${pipestatus[1]} == 0 )) || { print "\nI STOP: 有成员或 host 在运行（见上）。还没有改动任何东西（没有备份、没有安装）。等它们结束后重跑 I；不要结束任何进程。"; exit 1; }
  date '+I start %F %T' | tee -a $R/I.txt
  logged $R/I.txt do_backup || { print "\n备份失败，生产未被改动。把输出交给 Main；$BK 需要由 Main 决定如何处理。"; exit 1; }
  say "guard again right before pip install (backup done)" | tee -a $R/I.txt
  members_idle I-before-pip 2>&1 | tee -a $R/I.txt; (( ${pipestatus[1]} == 0 )) || { print "\nI STOP: 备份已完成，生产还没有改动。有成员在运行（见上）。重来时由 Main 先把 $BK 改名移开。"; exit 1; }
  touch $BK/INSTALL-STARTED; INSTALL_FROM=$(date +%T)
  if ! logged $R/I.txt do_install; then
    print "\n安装或校验失败。不要恢复 Main，立刻运行回退:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  touch $R/I.ok
  { say "BLOCKING processes started during the install window ($INSTALL_FROM → $(date +%T)); information for Main"
    guard && print "none" || print "（上面 BLOCKING 列出的进程在安装期间启动，可能载入了新旧混合的文件；告诉 Main。）"; } 2>&1 | tee -a $R/I.txt
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|^395 layout|direct_url|built from|CHECK|503 layout|control records snapshot|timer pid|zombies|markers expected|SAME-AS-VALIDATED|plugin files|configuration --write rc|bytes unchanged|^changed|BLOCKING|-rw-------' $R/I.txt)"
  print "成功: Successfully installed graftling-$GVERSION graphtraj-0.1.0；PASS n FAIL 0（两个 wheel）；'CHECK 593 graftling $GOLDVERSION dist-info gone: PASS'；'CHECK 593 production bin has subagents, subagents-mcp and no agents, agents-mcp: PASS'；三个 -rw------- 备份入口文件；'591 TOOL_NAME subagents'；'CHECK 593 direct_url of both names the wheels-$C8 wheels: PASS'；'markers expected present: PASS (8/8)'；'503 layout: PASS'；两行 node resolves PASS；SAME-AS-VALIDATED；'CHECK 593 plugin differs by exactly 591/592 …: PASS' 与 'CHECK 593 installed plugin changed as V predicted (plugin.json description and hooks/host_context.mjs): PASS'；'CHECK 515 .mcp.json …: PASS'；"
  print "  'CHECK 593 production-graphtraj-mcp MCP tools/list is exactly subagents, tasks: PASS' 与 'CHECK 593 production-graphtraj-mcp MCP tool agents is unknown (error answer, no alias): PASS'；两行 'CHECK 593 Codex hooks entry …: PASS'。"
  print "$R_HINT"
  print "\n下一步（USER，普通 Terminal）恢复 Main（同一个 Session）:\n  cd $H && claude --continue"
  print "预期对话框: $(cat $R/V-dialog.txt 2>/dev/null || print 'see V')。.mcp.json 不变，仍只有 \"$NEWS\"。若仍出现插件/hooks 信任框（graphtraj-claude-host）: 选信任（trust）并告诉 Main（与预测不符）；其它任何框: Esc 并告诉 Main 标题。判断: Main 恢复为原来的对话，然后由 Main 运行 M。"
  print "若 --continue 打开的不是原来的对话: /exit，然后 cd $H && claude --resume $MAIN"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cv; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main（用 claude --continue 恢复的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。Main 把原始结果存到 $R/M-<字母>.txt。
对话框: 预计无。scanhome 与 00 已表明：USER 的 ~/.claude 允许规则与 .claude/settings.local.json 都没有 mcp__ 规则，所以改名不会丢失允许规则，第一次以新名调用 mcp__graphtraj__subagents 的表现与以前调用 agents 相同。若仍出现 Claude Code 的工具权限框（mcp__graphtraj__subagents 或 tasks）: 选 'Yes'（只本次，不选 always），并告诉 Main（与预测不符）。
恢复的历史里仍有旧名 mcp__graphtraj__agents（590 4.1）：若 Main 第一次调用用了旧名并被拒（Unknown tool / 没有这个工具），记录下来（原文存 $R/M-old.txt），不算失败；然后用新名。

[a 重启后通知正常、不重复；工具列表只有新名] 恢复后第一句（粘贴）:
Production was just upgraded by Task $TASK_ID (GraphTraj $C8 with graftling $GVERSION, which renames the agents tool to subagents with no alias) and this Session was restarted. Before anything else, using no tools: (1) list every GraphTraj/Graftling notice delivered to you since this resume (alias, event, execution if shown in the title, first line), and for each say whether you had already seen that same notice before this resume; (2) list exactly every tool in your current tool list whose name starts with mcp__graphtraj__, mcp__graftling__ or mcp__agents__, and say whether mcp__graphtraj__agents is among them.
  成功: (1) 没有重启前已见过的通知再出现（Main 退出期间结束的其它 Task（$(active_tasks)）成员的通知可能到达一次，不能重复）；(2) 只有 mcp__graphtraj__subagents 与 mcp__graphtraj__tasks；没有 mcp__graphtraj__agents、mcp__agents__*、mcp__graftling__*。

[b 新名的真实调用与 tasks 调用] 粘贴:
Using only mcp__graphtraj__subagents: execute status with arguments {} (no agent). Print the raw result and whether it was an error. Then using only mcp__graphtraj__tasks: execute task_graph with arguments {"view":"current","details":["$TASK_ID"]} and print only whether an error was returned and Task $TASK_ID's current definition path.
  成功: subagents status 返回结果且不是错误；task_graph 无错误，Task $TASK_ID 的当前定义路径为 definitions/<时间>.md。可选（USER 在 Main 里输入 /agents-context）: 显示 subagents 与 tasks 已注册，没有 agents。

[c] Main 的 Bash（无对话框）: zsh $THIS Mr   然后   zsh $THIS Mp   然后   zsh $THIS Mps   然后   zsh $THIS inbox（每个文件 duplicate ids: 0）
EOF2
  next "zsh $THIS Mr" ;;

Mr) need_main; cv; print "[Mr] Main，M[b] 之后。只读：Main 自己的 Session 存档（$PROJECTS/$MAIN.jsonl，以及同目录里更新的 transcript）中、I 安装结束之后的 MCP 调用：必须有 mcp__graphtraj__subagents 与 mcp__graphtraj__tasks 的 tool_use，且结果不是错误；旧名调用只记录（590 4.1：恢复的历史仍有旧名），不判失败。再列出生产的工具清单 = I 对 .mcp.json 同一命令的 tools/list 加上重新生成的 hook 的 TOOLS。对话框: 无。< 10 秒。"
  { split=$(cat $R/I-install-end.epoch 2>/dev/null)
    [[ -n $split ]] || { print "STOP: no $R/I-install-end.epoch (I has not finished)"; exit 1; }
    files=($PROJECTS/$MAIN.jsonl(N) ${(f)"$(find $PROJECTS -maxdepth 1 -name '*.jsonl' -newer $R/I-install-end.epoch 2>/dev/null)"})
    print -r -- "Main transcripts read (resumed Session and any newer one): ${(u)files}"
    $CONDA -I $SD/rec593.py calls "Main $MAIN" --after $split --need subagents,tasks --old-info ${(u)files}; mrc=$?
    say "production tool list after I (from I's raw output and the installed hook copy)"
    grep -hE "^production-graphtraj-mcp server:|CHECK 593 production-graphtraj-mcp" $R/I.txt | sort -u
    grep -nE '^const (TOOL|TOOLS|SERVER) ' $PDIR/hooks/host_context.mjs | sed 's/^/installed hook copy: /'
    exit $mrc
  } 2>&1 | tee $R/Mr.txt; rc=${pipestatus[1]}
  summary Mr "$(grep -E '^(Main transcripts|CHECK|INFO|installed hook|production-graphtraj)' $R/Mr.txt)"
  print "成功: 'CHECK 593 [Main …] mcp__graphtraj__subagents called and answered without error or refusal: PASS' 与 '… mcp__graphtraj__tasks …: PASS'；INFO 行只记录旧名调用；tools/list 是 subagents、tasks；hook copy 的 TOOL = \"subagents\"、TOOLS = [TOOL, \"tasks\"]。NOT OBSERVED: Main 还没做 M[b]。"
  next "zsh $THIS Mp" ; exit $rc ;;

Mp) cv; print "[Mp] Main，M 之后。Harness 里一次有时限（120 秒）的 claude -p 单行探测，看 init 记录的 MCP 服务器与工具名。对话框: 无。不调用工具。< 2 分钟。"
  print -r -- 'Reply with exactly one line: PROBE-593-OK. Use no tools.' > $R/Mp-prompt.txt
  (cd $H && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
      < $R/Mp-prompt.txt > $R/Mp-stream.jsonl 2> $R/Mp.err)
  print "claude -p rc=$? (142 = 120 s timeout) | stderr lines naming untrusted/trust: $(grep -ciE 'untrust|trust' $R/Mp.err)" | tee $R/Mp.txt
  $CONDA -I $SD/rec593.py init $R/Mp-stream.jsonl 2>&1 | tee -a $R/Mp.txt; rc=${pipestatus[1]}
  grep -ciE 'untrust' $R/Mp.err > /dev/null && { print "CHECK 515 Mp stderr has no untrusted-plugin warning: FAIL" | tee -a $R/Mp.txt; rc=1; }
  summary Mp "$(grep -E '^(claude|CHECK|init)' $R/Mp.txt)"
  print "成功: 四行 'CHECK 593 init …: PASS'（mcp server graphtraj only；mcp__graphtraj__subagents 与 tasks；没有旧名 mcp__graphtraj__agents、mcp__agents__*；没有 untrusted-plugin 警告）。FAIL 交 Main。"
  next "zsh $THIS Mps" ; exit $rc ;;

Mps) need_main; print "[Mps] Main. 运行中的 host 与它的父 claude；重启前后的控制记录。对话框: 无。只读。"; cv | tee -a $R/Mps.txt
  { print "at $(date '+%F %T')"; hit=$(ps -axww -o pid=,ppid=,lstart=,command= | grep -F -- "$HOSTCFG" | grep -F -- ' serve ')
    print -r -- "host: $hit"; words=(${=hit}); PPIDV=${words[2]:-}
    if [[ -n $PPIDV ]]; then C=$(ps -ww -o command= -p $PPIDV); print -r -- "parent claude: $C"
      [[ $hit == *"$RT/bin/python"* ]] && print "host uses .venv-runtime: yes" || print "host uses .venv-runtime: NO"
      if [[ $C == *claude*' --continue'* || $C == *"--resume $MAIN"* ]]; then print "parent is claude --continue or --resume $MAIN: yes"
      else print "parent is claude --continue or --resume $MAIN: NO"; fi
      [[ -s $R/I-install-end.epoch ]] && print "host started after the install (loads the new code): compare its start time above with $(date -r $(<$R/I-install-end.epoch) '+%a %b %e %T %Y')"
    else print "NOT FOUND: no host serving $HOSTCFG"; fi
    say "host.log tail"; tail -n 30 $H/.graphtraj/claude-host/host.log; print "outcome=ok lines in tail: $(tail -n 30 $H/.graphtraj/claude-host/host.log | grep -c 'outcome=ok')"
    ps -axww -o pid=,ppid=,command= > $R/Mps-ps.txt 2>&1
    $CONDA -I $SD/ctl497.py mcp ${PPIDV:-none} $R/Mps-ps.txt
    say "486: production agents control records across the restart (Mpre snapshot before /exit -> now)"
    if [[ -f $CTL/Mpre.json ]]; then $CONDA -I $SD/ctl497.py snap $H $CTL/Mps.json; $CONDA -I $SD/ctl497.py restart $CTL/Mpre.json $CTL/Mps.json
    else print "CHECK 486 no execution ended interrupted across the Main restart: BLOCKED (no $CTL/Mpre.json: Mpre was not run before /exit)"; fi
  } 2>&1 | tee -a $R/Mps.txt
  summary Mps "$(grep -E '^(host|parent is|host started|NOT FOUND|outcome=ok|486|CHECK|  )' $R/Mps.txt | tail -12)"
  print "成功: host uses .venv-runtime: yes；parent is claude --continue …: yes；host 的启动时间晚于安装结束；outcome=ok lines > 0；CHECK 486 两行 PASS。"
  next "zsh $THIS inbox" ;;

inbox) need_main; cv; print "[inbox] Main. Main 的通知队列。对话框: 无。只读。"
  { for f in $INBOX/*.jsonl(N); do print "== ${f:t}"; tree inbox $f; done; } 2>&1 | tee -a $R/inbox.txt
  print "Claude Main $MAIN 的文件: $(inbox_key "claude:$MAIN").jsonl"
  summary inbox "$(grep -E '^(==|duplicate|records)' $R/inbox.txt | tail -12)"
  print "成功: 每个文件 duplicate ids: 0。"
  next "zsh $THIS Nw    （然后 zsh $THIS N）" ;;

Nw) cv; print "[Nw] Main. 在 N 之前启动：后台只读采样 N 派发的成员（advisor）的 Worker（ps 每 ~10 秒；忽略此时已在运行的 Worker，如本 Task 的 Leader/Engineer）。对话框: 无。立即返回。"
  if [[ -e $R/Nw468.txt ]] && ! grep -q '== END' $R/Nw468.txt; then print "Nw 已在运行（$R/Nw468.txt 没有 '== END'）；不重复启动。"; next "zsh $THIS N"; exit 0; fi
  : > $R/Nw468.txt; : > $R/Nw468-ps.txt
  ($CONDA -I $SD/cpu468.py sample $H $R $TASK_ID ${ADOPT593_NW468_SECONDS:-900} advisor < /dev/null >> $R/Nw468.txt 2>&1 &!)
  print "started at $(date +%T) in the background ($R/Nw468.txt; ends by itself when the Worker ends or after 15 min: '== END 468 sampler')."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. 一次真实派发（593：成员通过新名 subagents 工具创建不带 tools 的 Claude 子级 $CHILD，它必须用 Bash 运行命令并回复 DONE-593）：成员创建子级 $CHILD，等待、读取、清退（通知一次；Worker 在创建前后 30 秒的 CPU 只报告）。先确认 593 的 Leader 与 Engineer 已结束回合、Nw 已启动（tail -n 2 $R/Nw468.txt 有 '468 sampler'），再在 Claude Main 里粘贴这一条。对话框: 预计无（Main 以前的 swarm 调用不出框；若出现工具权限框: 'Yes' 只本次，并告诉 Main）。约 3-5 分钟。
Using only mcp__graphtraj__tasks: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"This is a production check. Do NOT call submit_result or submit_report. (a) Using the subagents tool (mcp__graphtraj__subagents; there is no tool named agents any more), create ONE claude child named $CHILD with configuration opus_coding_team.advisor, WITHOUT a tools argument (do not pass tools or disallowed_tools: this checks the default tools), and this message: <<This is a scripted probe. Call Bash once with exactly: echo $CHILD-tool && sleep 20 ; then reply with exactly: DONE-593>>. Quote the raw create result (agent id, session, execution id). If the child asks you to approve a Bash command, approve exactly that command. (b) Call subagents wait on that agent id with timeout_seconds 300, repeating until the execution has ended; quote the final wait result's last_message. Then call subagents status with arguments {agent: <agent id>} and quote its configuration, model and last_message. (c) Retire the child by its agent id and quote the raw result. End your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main 把 swarm 原始结果存为 $R/N.txt（必须含 "agent"）；Main 收到的这个成员的每一条通知原文（每条一行，通知头与正文同一行，以 '[GraphTraj notice from <成员 alias> · … · execution <id>]' 或 '[Graftling notice from …]' 开头；说明行以 '# ' 开头）存为 $R/N-main-notice.txt；成员最终回复原文存为 $R/N-reply.txt。
  成员结束（Main 收到 completed 通知）后、清退成员之前，Main 的 Bash（无对话框）: zsh $THIS Nr，然后 zsh $THIS Nt。
EOF2
  next "zsh $THIS Nr    （然后 zsh $THIS Nt）" ;;

Nr) print "[Nr] Main. 子级与成员记录、通知一次、成员的工具调用、Worker CPU 报告（只读，从不发信号）。对话框: 无。"
  cv | tee $R/Nr.txt
  nr_read 2>&1 | tee -a $R/Nr.txt; rc=${pipestatus[1]}
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1)
  { if [[ -s $R/N-main-notice.txt ]]; then
      nc=$(notice_count $R/N-main-notice.txt "$MEMBER")
      print "CHECK 593 Main got exactly one completed notice of the member: $( (( nc == 1 )) && print PASS || print FAIL) ($nc notice lines of shape '[Graftling notice from ${MEMBER:-<member>} · completed · execution <id>]' in $R/N-main-notice.txt)"
    else print "CHECK 593 Main got exactly one completed notice of the member: PENDING (save every notice of the member to $R/N-main-notice.txt)"; fi
  } 2>&1 | tee -a $R/Nr.txt
  # Reported, never judged (not blocking). cpu468.py keeps its 525 label (the window it measures is the same).
  $CONDA -I $SD/cpu468.py window $R 2>&1 | tee -a $R/Nr.txt
  print "REPORT 532 Worker CPU comparison (window lines above are cpu468.py's, labelled 525): before 531's fix, production 528 (Nw468/Nr) 30 s before child creation 0.559, after 0.107 CPU-s per wall-s; 531 on a production-size copy 0.488 -> 0.116. 531's fix targets the 30 s BEFORE creation (not blocking)." | tee -a $R/Nr.txt
  say "REPORT 532 526: graftling's .gitignore in production's data roots after N (information only; not blocking)" | tee -a $R/Nr.txt
  gitignore_report 2>&1 | tee -a $R/Nr.txt
  grep -E '== END|Worker pid|already running' $R/Nw468.txt 2>/dev/null | tail -3 | tee -a $R/Nr.txt
  if [[ -n $MEMBER ]]; then
    mf=(${(f)"$(rs_session_files $MEMBER)"})
    print "member $MEMBER record files: ${#mf}" | tee -a $R/Nr.txt
    $CONDA -I $SD/rec593.py calls "member $MEMBER" --need subagents ${(u)mf} 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  else print "CHECK 593 [member] mcp__graphtraj__subagents called and answered without error or refusal: NOT OBSERVED (member alias not found)" | tee -a $R/Nr.txt; rc=1; fi
  SWARM_AGENT=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
  print "CHECK swarm result has agent: $([[ -n $SWARM_AGENT ]] && print "PASS ($SWARM_AGENT)" || print "FAIL (no \"agent\" in $R/N.txt, or the file is missing)")" | tee -a $R/Nr.txt
  grep -q '^CHECK.*: FAIL' $R/Nr.txt && rc=1
  summary Nr "$(grep -E '^claude:|^child|CHECK|REPORT|BLOCKED|^member|member end|archive|stored selection|Worker pid' $R/Nr.txt)"
  print "成功: 每一行 CHECK 都是 PASS（455 两行、一个子级 execution、452 子级 completed 与成员结束、通知 delivered、477 没有推送输入、'CHECK 593 Main got exactly one completed notice'、成员 mcp__graphtraj__subagents 调用无错误、成员没有旧名调用、swarm 有 agent）。"
  print "  REPORT 行（Worker CPU 两行 'REPORT 525 468 Worker CPU 30 s before/after child creation' 与 'REPORT 532 Worker CPU comparison'（对照 528 的 0.559/0.107 与 531 的 0.488 -> 0.116）；'REPORT 532 526 .gitignore …' 只是信息）是报告，不阻塞；NOT OBSERVED 时把 $R/Nw468.txt 交 Main。PENDING: 子级还在运行或通知尚未保存，稍后重跑 Nr。CHECK BY HAND 用下面的 session_read。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session_id\":\"$SID\",\"limit\":400} (page with after until has_more is false). Count, per $CHILD execution id printed by Nr, the user/message events that deliver a parent input with source graphtraj naming it; print the counts by event type and each such input's execution field only."
  if [[ -n $SWARM_AGENT ]]; then print "\n清退成员（Main 粘贴，Nr 与 Nt 之后）:\nUsing only mcp__graphtraj__subagents: retire with {\"agent\":\"$SWARM_AGENT\"} (the agent value of the N swarm result, not the alias), and print the raw result."
  else print "\n清退成员: 先把 N 的 swarm 原始结果存到 $R/N.txt 再重跑 Nr。"; fi
  next "zsh $THIS Nt    （清退成员后再跑一次 Nt，然后 zsh $THIS scan 与 zsh $THIS C5）"; exit $rc ;;

_c5interp) c5_interp ${IDS[1]:-$UVT/tools/graftling/bin/python}; exit $? ;;   # rehearsal only

C5) cv; print "[C5] Main，gh 之后（$GTAG 已在 GitHub）。结果 5（单一安装源 + conda）：在隔离目录 $UVT 按 graftling README 的唯一安装方式 uv tool install 从 GitHub 的 $GTAG 安装一次 graftling（只把 UV_TOOL_DIR、UV_TOOL_BIN_DIR、UV_CACHE_DIR、UV_PYTHON_INSTALL_DIR 放在 $UVT 下；不指定解释器偏好，uv 自己选或下载 Python 3.12+，并打印它用的解释器；不碰 ~/.local 与用户的 uv 工具目录），再用该安装为 $UVT/project 生成 Claude Code 的项目文件（configuration --write，只写这个项目）。之前先对 ~/.local、用户的 uv 工具目录、~/.pi、~/.dsh、~/.codex（按名字与 sha256，不含 logs_*.sqlite* 与 models_cache.json：USER 正在运行的 Codex 会写它们）与 conda（conda-meta 与 dist-info 名单）做快照。对话框: 无。需要网络（github.com、PyPI、uv 的 Python 下载）。约 2-3 分钟。"
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier C5). Main moves $UVT aside first, or runs C5r on it."; exit 1; }
    mkdir -p $UVT/project || exit 1
    say "before: USER directories that must stay unchanged (read only)"
    $CONDA -I $SD/homesnap593.py snap $R/C5-home-before.json local=$HOME/.local uvtools=$(clean uv tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=${CONDABIN:h:h} || exit 1
    say "uv tool install from GitHub $GTAG into $UVT only"
    # The release's single install method as graftling's README states it ("uv gets a Python 3.12 or later when it needs
    # one"): no interpreter preference is set; only uv's directories are isolated under $UVT.
    UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
    print -r -- "uv: $(command -v uv) | $(uv --version 2>&1) | environment: ${UVENV[*]}"
    clean env $UVENV uv tool install "git+https://github.com/LUOXIAO92/graftling.git@$GTAG" > $R/C5-uv.txt 2>&1; urc=$?
    grep -iE 'interpreter|cpython|python' $R/C5-uv.txt | head -4 | sed 's/^/uv said: /' || true
    tail -4 $R/C5-uv.txt
    print "uv tool install rc=$urc (full output: $R/C5-uv.txt)"; (( urc == 0 )) || exit 1
    UVPY=$UVT/tools/graftling/bin/python
    print -r -- "uv tool bin: $(print -l $UVT/bin/*(N:t) | tr '\n' ' ') | subagents-mcp shebang: $(head -1 $UVT/bin/subagents-mcp)"
    c5_interp $UVPY || exit 1
    say "Claude Code project $UVT/project: configuration --write from the uv installation (writes only that project)"
    [[ -d $UVT/project/.git ]] || git -C $UVT/project init -q --initial-branch=main
    (cd $UVT/project && clean $UVPY -m graftling.claude.host configuration --project $UVT/project --claude $(claude_bin) --write) 2>&1 | tail -8 || exit 1
    print -r -- ".mcp.json graftling command: $($CONDA -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["mcpServers"]["graftling"]; print(s.get("command"), *(s.get("args") or []))' $UVT/project/.mcp.json 2>&1)"
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nC5 STOP（见上）。把 $R/C5.txt 交给 Main。"; exit 1; }
  summary C5 "$(grep -E '^(uv|uv tool|uv said|CHECK|REPORT|NOTE|\.mcp\.json|snap)' $R/C5.txt)"
  print "成功: 'uv tool install rc=0'；'CHECK 593 C5 one install from GitHub $GTAG in the uv tool environment $UVT/tools/graftling (sys.prefix), graftling $GVERSION: PASS'；'REPORT 593 C5 base interpreter: …' 只是报告（若是 conda 的，会有 NOTE 行：既不是 PASS 也不是 FAIL，由 Main 判断是否满足结果 5；C5r 照常运行）；.mcp.json 的 graftling command 是 $UVT/tools/graftling/bin/python。"
  next "USER（仅一次）: zsh $THIS C5u    （之后 Main: zsh $THIS C5r）"; exit $rc ;;

C5u) print "[C5u] USER（一次；Claude Code 只在已信任的文件夹加载项目插件，Main 做不了）。$(cv)"
  print "在普通 Terminal 运行:\n  cd $UVT/project && claude"
  print "对话框（一个）: 'Do you trust the files in this folder?'（写着 $UVT/project）选 'Yes, proceed'。若再问项目的 MCP server 'graftling' 或插件/hooks，为本项目批准。然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS C5r" ;;

C5r) cv; print "[C5r] Main，C5 与 C5u 之后。在 USER 已有的 conda 环境（${ADOPT593_CONDA_ENV:-base}）激活的状态下（conda shell hook + conda activate；只读，不 install/create/config）：命令行 $UVT/bin/subagents 可用；真实 claude -p（Claude 登录已由 USER 预先同意；无 provider 凭据）在 $UVT/project 通过 mcp__graftling__subagents 创建一个 Claude 子级并等到它结束；后台 ps 采样记录 graftling 进程的可执行文件，必须在 $UVT 下、不在 conda 下；之后对比 USER 目录与 conda。对话框: 无。约 3 分钟。"
  { CENV=${ADOPT593_CONDA_ENV:-base}; CROOT=${CONDABIN:h:h}
    [[ -x $UVT/tools/graftling/bin/python ]] || { print "STOP: no uv installation under $UVT: run C5 first"; exit 1; }
    : > $R/C5r-ps.txt
    ( for i in {1..150}; do ps -axww -o pid=,ppid=,command= 2>/dev/null | grep -E 'graftling|subagents' | grep -vE 'grep -E|C5r' >> $R/C5r-ps.txt; [[ -e $R/C5r.done ]] && break; sleep 2; done ) &!
    rm -f $R/C5r.done
    print -r -- "Reply with exactly the agent id after these calls. Using only mcp__graftling__subagents: execute create with arguments {\"runtime\":\"claude\",\"name\":\"c593\",\"instruction\":\"Reply with exactly: C5-CHILD-OK\"}; then execute wait with {\"agent\": <the agent id>, \"timeout_seconds\": 300}, repeating until the execution has ended; print the final last_message; then retire the child. Print one line DONE and stop." > $R/C5r-prompt.txt
    env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} \
      CONDABIN=$CONDABIN CENV=$CENV UVT=$UVT MODEL=$MODEL CLAUDE=$(claude_bin) PROMPT=$R/C5r-prompt.txt OUT=$R/C5r-stream.jsonl /bin/zsh -f -c '
        eval "$($CONDABIN shell.zsh hook 2>/dev/null)" && conda activate $CENV || { print "STOP: conda activate $CENV failed"; exit 1; }
        print -r -- "conda active: CONDA_PREFIX=$CONDA_PREFIX | python on PATH: $(command -v python) | python3: $(command -v python3)"
        print -r -- "subagents CLI: $($UVT/bin/subagents --help 2>&1 | head -1)"
        print -r -- "subagents CLI from a plain shell (expected authority-denied, it only forwards to a host): $($UVT/bin/subagents "{\"action\":\"discover\"}" 2>&1 | head -c 200)"
        cd $UVT/project && /usr/bin/perl -e "alarm shift; exec @ARGV" 600 $CLAUDE -p --model $MODEL --output-format stream-json --verbose \
          --allowedTools mcp__graftling__subagents < $PROMPT > $OUT 2> $OUT.err
        print "claude -p rc=$? (142 = 600 s timeout)"'
    touch $R/C5r.done; sleep 3
    tree stream $R/C5r-stream.jsonl mcp__graftling__subagents
    grep -q 'C5-CHILD-OK' $R/C5r-stream.jsonl && print "CHECK 593 C5 the child created through mcp__graftling__subagents ended and replied C5-CHILD-OK: PASS" \
      || print "CHECK 593 C5 the child created through mcp__graftling__subagents ended and replied C5-CHILD-OK: FAIL"
    say "graftling processes seen while it ran (executables; the uv tool's Python must serve them)"
    sort -u $R/C5r-ps.txt | cut -c1-220 | head -12
    srv=$(sort -u $R/C5r-ps.txt | grep -c -- "${UVT:A}/tools/graftling/bin/python\|$UVT/tools/graftling/bin/python"); onconda=$(sort -u $R/C5r-ps.txt | grep -c -- "$CROOT/")
    (( srv > 0 && onconda == 0 )) && print "CHECK 593 C5 graftling ran as the uv tool environment's bin/python ($srv process lines), none naming the conda root: PASS" \
      || print "CHECK 593 C5 graftling ran as the uv tool environment's bin/python ($srv process lines), none naming the conda root: FAIL ($onconda lines under $CROOT)"
    say "after: USER directories and conda unchanged (no install into conda; codex compared by name and sha256 without logs_*.sqlite* and models_cache.json)"
    $CONDA -I $SD/homesnap593.py snap $R/C5-home-after.json local=$HOME/.local uvtools=$(clean uv tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT > /dev/null
    $CONDA -I $SD/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json && print "CHECK 593 C5 nothing installed into conda and USER directories unchanged: PASS" \
      || print "CHECK 593 C5 nothing installed into conda and USER directories unchanged: FAIL (see REPORT lines; a per-environment install would show under conda)"
  } 2>&1 | tee $R/C5r.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nC5r STOP（见上）。没有安装任何东西，conda 未被改动。把 $R/C5r.txt 交给 Main。"; exit 1; }
  grep -q '^CHECK 593 C5 .*: FAIL' $R/C5r.txt && rc=1
  summary C5r "$(grep -E '^(conda active|subagents CLI|claude -p rc|PASS|FAIL|CHECK|REPORT)' $R/C5r.txt)"
  print "成功: 'conda active: …'（python 在 conda 下）；'subagents CLI: …' 有 usage 行；四行 'CHECK 593 C5 …: PASS'（PASS mcp__graftling__subagents；子级回复；graftling 进程在 uv 工具的 Python 上；conda 与 USER 目录不变）。若发现必须在 conda 环境里另装才能工作: 本步不安装，如实报告并 STOP，交 Main。"
  next "zsh $THIS X    （更正 3：审查豁免在本项目的 graftling host 上；然后 zsh $THIS done）" ; exit $rc ;;

X) cv; print "[X] Main，C5r 之后（更正 3）。审查豁免在新名下（真实），在 graftling 自己的 Claude host 上：C5 建的项目 $UVT/project（uv 从 GitHub v0.9.0 安装；USER 在 C5u 信任了这个文件夹）。GraphTraj 的 driver 只按 roles.yml 的 configuration 选择，graftling 拒绝 preset（control.py），所以不在 GraphTraj host 上做。1) 只读列出生产的 reviewer 名字；2) 在该项目的 graftling 数据根（claude-host.json 的 root）的 config.yml 里（先保留原文件副本）加本地命令 reviewer x593-review（x593.py reviewer：只记录工具名并允许，不需要 provider）、connection x593c（runtime claude，review x593-review）、preset x593，并打开 save_normalized_sessions；只写在 $UVT 下，不碰生产配置、.venv-runtime 或 $VPROJECT；3) 一次真实的 claude -p（干净环境，Claude 登录已由 USER 预先同意；--allowedTools mcp__graftling__subagents）用 preset x593 创建带审查的 Claude 子级 x$TASK_ID，子级先调用自己的 subagents 工具（status），再用 Bash 运行 echo x$TASK_ID-tool，回复 DONE-X$TASK_ID，等待结束后清退；4) 只读判定。对话框: 预计无（文件夹已在 C5u 信任；若 Claude 问到项目 MCP server 'graftling'，为本项目批准）。没有 $UVT/project 或 C5r 未通过（信任来自 C5u）时 STOP，指向 C5/C5u/C5r。约 3 分钟。"
  # Correction 3: GraphTraj's driver selects only through roles.yml configurations (graftling/control.py refuses a
  # preset when the driver's prepare takes no selection), so X runs on graftling's own Claude host in the C5 project.
  for f in X.txt X-reviewer.jsonl X-stream.jsonl X.err; do [[ -e $R/$f ]] && mv $R/$f $R/${f:r}-$(date +%Y%m%dT%H%M%S).${f:e}; done
  : > $R/X.txt
  { XP=$UVT/project UVPY=$UVT/tools/graftling/bin/python
    [[ -x $UVPY && -f $XP/.mcp.json && -f $XP/.agents-control/claude-host.json ]] || { print "STOP: no graftling host project at $XP (or no uv installation): run C5 first (then the USER's C5u, then C5r)"; exit 1; }
    grep -q '^CHECK 593 C5 the child created through mcp__graftling__subagents ended and replied C5-CHILD-OK: PASS' $R/C5r.txt 2>/dev/null \
      || { print "STOP: C5r has not passed in $XP (its folder trust comes from the USER's C5u): run C5u, then C5r, first"; exit 1; }
    say "production reviewers (names only; read only)"
    $CONDA -I $SD/x593.py inventory $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/config.yml
    print "(production review is on only for a connection that names a reviewer; X checks the exemption on graftling's own host in $XP)"
    # The data root is the host configuration's 'root' (graftling/claude/host.py: <project>/.agents-control by default),
    # and graftling reads config.yml there (graftling/config.py).
    XROOT=$($CONDA -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' $XP/.agents-control/claude-host.json) || exit 1
    XC=$XROOT/config.yml XLOG=$R/X-reviewer.jsonl; : > $XLOG
    print -r -- "graftling host project: $XP | data root (claude-host.json root): $XROOT | config: $XC | .mcp.json graftling: $($CONDA -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["mcpServers"]["graftling"]; print(s.get("command"), *(s.get("args") or []))' $XP/.mcp.json 2>&1)"
    [[ ${XROOT:A} == ${UVT:A}/* ]] || { print "STOP: the data root $XROOT is outside $UVT; X writes only under $UVT"; exit 1; }
    [[ -f $XC && ! -e $R/X-config-before.yml ]] && cp -p $XC $R/X-config-before.yml && print -r -- "kept a copy of the existing config: $R/X-config-before.yml"
    $CONDA -I $SD/x593.py config $XC $CONDA $SD/x593.py $XLOG || exit 1
    (cd $XP && clean $UVPY -I -c 'import sys; from pathlib import Path; from graftling.config import read_connections; d = read_connections(Path(sys.argv[1])); print("graftling reads it:", sorted(d.get("connections", {})), sorted(d.get("presets", {})), sorted(d.get("reviewers", {})))' $XROOT) || { print "STOP: graftling does not accept $XC"; exit 1; }
    say "real claude -p in $XP: create the reviewed child x$TASK_ID with preset x593 through mcp__graftling__subagents"; cv
    print -r -- "Using only mcp__graftling__subagents: (1) execute create with arguments {\"runtime\":\"claude\",\"preset\":\"x593\",\"name\":\"x$TASK_ID\",\"instruction\":\"Scripted probe. First call your own subagents tool (its name ends with __subagents) with {\\\"action\\\":\\\"execute\\\",\\\"feature\\\":\\\"status\\\",\\\"arguments\\\":{}}. Then call Bash once with exactly: echo x$TASK_ID-tool . Then reply with exactly: DONE-X$TASK_ID\"}. (2) execute wait with {\"agent\": <the agent id>, \"timeout_seconds\": 300}, repeating until the execution has ended; if the child asks you to approve a Bash command, reply to approve exactly that command. (3) Print the final last_message, then retire the child. Print one line DONE and stop." > $R/X-prompt.txt
    (cd $XP && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 600 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
        --allowedTools mcp__graftling__subagents < $R/X-prompt.txt > $R/X-stream.jsonl 2> $R/X.err)
    print "claude -p rc=$? (142 = 600 s timeout)"
    tree stream $R/X-stream.jsonl mcp__graftling__subagents
    say "judge (read only): reviewer log, review.jsonl, the child's archive and record in $XROOT"
    $CONDA -I $SD/x593.py judge $XROOT $XLOG x$TASK_ID
  } 2>&1 | tee -a $R/X.txt; rc=${pipestatus[1]}
  summary X "$(grep -E '^(/|STOP|graftling host project|graftling reads|wrote|child|reviewer log|review.jsonl|archived|CHECK|claude -p rc|PASS|FAIL)' $R/X.txt)"
  if grep -q '^STOP' $R/X.txt; then print "\nX STOP（见上）。"; exit 1; fi
  print "成功: 'graftling reads it: [… x593c …] [… x593 …] [… x593-review …]'；PASS mcp__graftling__subagents；五行 'CHECK 593 X …: PASS'（reviewer 收到 create 的 subagents/connectivity-check 与子级的 Bash；没有任何 mcp__*__subagents 调用进入 reviewer 或 review.jsonl；子级的 subagents 调用有非错误结果；子级 completed）。FAIL 交 Main/Leader。"
  next "zsh $THIS done" ; exit $rc ;;

Nt) cv; print "[Nt] Main，N 的成员结束之后、清退之前；清退之后再跑一次。490：Task $TASK_ID 的 Session 的预算计时器（只读，从不发信号）。对话框: 无。< 30 秒。"
  { print "at $(date '+%F %T')"
    LC_ALL=C ps -axww -o pid=,ppid=,stat=,lstart=,command= > $R/Nt-ps.txt 2>&1
    w=$(install_window)
    [[ -n $w ]] || print "no install window ($R/I-install-*.epoch): I has not run or did not finish"
    $CONDA -I $SD/timers497.py nt $R/Nt-ps.txt $RT ${=w:-x x} $RUNNER/sessions $TASK_ID $R/Nt-timers.json; } 2>&1 | tee -a $R/Nt.txt
  rc=${pipestatus[1]}
  summary Nt "$(grep -E '^(Task|CHECK)|timer pid' $R/Nt.txt | tail -12)"
  print "成功: 'CHECK 490 a timer started by the new version for a Task $TASK_ID Session is listed …: PASS'。FAIL 且成员刚结束: 30 秒后重跑 Nt。清退成员后重跑 Nt: 成员的计时器应变为 absent。"
  next "zsh $THIS done" ; exit $rc ;;

T) cv; print "[T] Main，在 Leader 接受 593（状态变为 awaiting-integration）并集成之后。490：本 Task 的 Session 中由新版启动的计时器全部消失，Task 结束后没有预算通知（只读，从不发信号）。对话框: 无。< 30 秒。"
  ST=$STATE/tasks/$TASK
  tstat=$(sed -n 's/^status: //p' $ST/task.yml)
  if [[ ! -s $R/T-end.epoch ]]; then
    case $tstat in awaiting-integration|integrating|integrated)
      stat -f %m $ST/task.yml > $R/T-end.epoch; print "end time recorded from task.yml mtime at status $tstat: $(date -r $(<$R/T-end.epoch) '+%F %T')" | tee -a $R/T.txt ;;
    esac
  fi
  { print "at $(date '+%F %T') status $tstat"
    print "all timers now (old ones listed, not judged):"; timer_list $R/T-ps-all.txt
    LC_ALL=C ps -axww -o pid=,ppid=,stat=,lstart=,command= > $R/T-ps.txt 2>&1
    $CONDA -I $SD/timers497.py t $R/T-ps.txt $RT ${=$(install_window):-x x} $RUNNER/sessions $TASK_ID $R/Nt-timers.json $ST ${$(cat $R/T-end.epoch 2>/dev/null):-$(date +%s)}; } 2>&1 | tee -a $R/T.txt
  rc=${pipestatus[1]}
  summary T "$(grep -E '^(Task|CHECK|end time|budget_idle_timer)|new-version timer' $R/T.txt | tail -14)"
  print "成功: 两行 CHECK 490 都是 PASS。PENDING: Task 尚未结束或刚结束 < 30 秒，30 秒后重跑: zsh $THIS T。FAIL 或 BLOCKED 交 Main 登记。"
  exit $rc ;;

timers) cv; print "[timers] Main 或 USER，任何时候。所有 budget_idle_timer 进程（只读，从不发信号）。对话框: 无。< 10 秒。"
  timer_list $R/timers-ps.txt 2>&1 | tee -a $R/timers.txt ;;

done) print "[done] Main. 结束状态。对话框: 无。只读。"; cv | tee -a $R/done.txt
  { S=$(site); cat $N/COMMIT $N/GRAFTLING; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS|^FAIL' $R/done-verify.txt
    print -r -- "graphtraj direct_url: $(cat $S/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null || print none) | built from: graphtraj git archive $(<$N/COMMIT)"
    print -r -- "graftling direct_url: $(cat $S/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null || print none) | built from: graftling git archive $(<$N/GRAFTLING)"
    # 579: counted with count() (560's `print -l <glob>(N) | wc -l` printed 1 for no match).
    print -r -- "graftling $GOLDVERSION dist-info left: $(count $S/graftling-$GOLDVERSION.dist-info(N)) (expect 0)"
    print -r -- "Task state now: task.md $(count $STATE/tasks/*/task.md(N)) (expect 0; 593 does not touch it) | Tasks $(count $STATE/tasks/[^.]*(N/))"
    (cd ${TMPDIR:-/tmp} && clean $RT/bin/python -I $SD/mcp593.py production-graphtraj-mcp $VPROJECT $RT/bin/graphtraj-mcp); codex_hook_check $RT
    $CONDA -I $SD/markers.py $S present | tail -1
    $RT/bin/python -I $SD/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'
    node_resolve $RT
    shasum -a 256 $ENTRIES; tree versions $SESS
    mcp_keys $H/.mcp.json; settings_view $H/.claude/settings.local.json
    print "GR/Mp/Mr/Nr/X/C5r: $(grep -hE '^CHECK 5' $R/GR.txt $R/Mp.txt $R/Mr.txt $R/Nr.txt $R/X.txt $R/C5r.txt 2>/dev/null | sed -E 's/^CHECK 5[0-9]+ //; s/:? (PASS|FAIL|PENDING|NOT OBSERVED).*/ \1/' | tr '\n' ';')"
    grep -hE '^CHECK 593' $R/I.txt 2>/dev/null | sort -u
    grep -hE '^REPORT 593 old-name scan' $R/scan-before-I.txt $R/scan-after-I.txt 2>/dev/null
    print -r -- "production bin now: $(print -l $RT/bin/{agents,agents-mcp,subagents,subagents-mcp}(N:t) | tr '\n' ' ')"
    grep -hE '^REPORT (525 468|532)' $R/Nr.txt 2>/dev/null
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|CHECK|direct_url|dist-info left|Task state now|markers expected|layout:|mcp.json servers|enabledMcpjsonServers|^GR/Mp|^REPORT|production bin now|archives=|containing an exported key' $R/done.txt)"
  print "成功: PASS n FAIL 0（两个 wheel）；Version 0.1.0 与 $GVERSION；两个 direct_url 指向 wheels-$C8；'graftling $GOLDVERSION dist-info left: 0'；'Task state now: task.md 0'；markers expected present: PASS (8/8)；'503 layout: PASS' 与两行 node resolves PASS；MCP tools/list（subagents, tasks；agents unknown）与两行 Codex hooks CHECK 为 PASS；'CHECK 515 .mcp.json …: PASS'；I 的 CHECK 593 都是 PASS；GR/Mp/Mr/Nr/X/C5r 的 CHECK 都是 PASS；old-name scan after-I: live configuration hits 0；production bin now: subagents subagents-mcp；raw files containing an exported key value: 0。把 $R 的路径交给 Main。$R_HINT"
  print "\nLeader 接受 593 之后（Main，按集成流程）: 把本 Task 的分支 $(git -C $WT rev-parse --abbrev-ref HEAD)（产品 = $C8）集成进 GraphTraj dev；然后运行 T。"
  next "（Leader 接受 593 并集成之后，Main）zsh $THIS T" ;;

R) need_main; print "[R] USER（Main 先问 USER；USER 同意后先在 Main 里 /exit，再在普通 Terminal 运行本步）。回退到安装前：venv 整体（graphtraj ${OLD[1,8]} 与 graftling $GOLDVERSION）、.mcp.json、settings.local.json、插件，都从 $BK 恢复（579 不动 Task 状态）；当前文件移到 $BK/after-install-*。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; cv; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  members_idle R 2>&1 | tee -a $R/R.txt; (( ${pipestatus[1]} == 0 )) || { print "\nR STOP: 有成员或 host 在运行（见上）。还没有回退任何东西；它们结束后重跑 R，不要结束任何进程。"; exit 1; }
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK|graphtraj package|before R' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过；'CHECK 593 graftling restored …: PASS' 与 'CHECK 593 graphtraj restored …: PASS'；'CHECK 593 R: graftling is $GOLDVERSION again: PASS'；Version graphtraj 0.1.0 与 graftling $GOLDVERSION。"
    print "然后（USER）: cd $H && claude --continue （插件与安装前相同，预测无插件/hooks 信任框；若出现: 选信任并告诉 Main；其它框选拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
