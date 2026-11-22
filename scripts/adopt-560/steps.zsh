#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 560 — graftling 0.6.3 release and production adoption of the paired GraphTraj candidate.
# graftling: v0.6.3 = $GCOMMIT, the release branch agent/560-graftling-0.6.3 (two commits on graftling dev 9f962bc:
# 10dd56b5 conventional layout, ef7c37db version 0.6.3), carried as scripts/adopt-560/graftling-0.6.3.bundle. Step rel
# (Main) fetches it by exact SHA, fast-forwards graftling dev and main to it and creates the annotated tag v0.6.3; rp
# (Main, after the USER confirms) pushes. From 0.6.3 the wheel builds from the archive ROOT (`pip wheel <archive>`).
# graphtraj: production a7b20447 (532) -> a wheel built from `git archive $TARGET` (GraphTraj dev 3b9c2af7 + 560's
# range graftling>=0.6.3,<0.7). Production 0.6.2 does not satisfy it: the two wheels are installed together by I and are
# a pair (553: each base fails the other's interface tests).
# Task state: 563's `graphtraj migrate-task-definitions` runs in I right after the install (preview, migration with its
# own backup, a second run that renames nothing, per-Task hash comparison of the current definition and every version).
# I also keeps its own copy of every Task's task.yml/task.md/definitions/ and the Worldline, so R restores BOTH packages
# and the pre-migration Task state.
# Full suite: GR reads the committed G record scripts/adopt-560/G-record (this Worktree's candidate with the v0.6.3
# wheel, run by the Engineer) and checks candidate, graftling commit, totals, exit=0 and FAILED lines (known: 516's
# CURRENT definition). G (Main, optional) reruns it here if the Leader asks.
# Copied from scripts/adopt-532/steps.zsh (unchanged there); every 503/515/525/528/532 protection kept (isolated
# vproject, proddiff file by file, markers both ways, backup + R from the backup's own tools, guard that waits and
# never signals, rerun right before pip, Claude Code version at 00, no key value in raw output, timers listed only,
# .mcp.json only graphtraj, plugin bytes compared).
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → rel → [rp after USER confirms] → B → GR → V
#        → Vu (USER once, only if Vc asks) → Vc → Mpre → [USER /exit Main] → I (USER)
#        → [USER: cd <Harness> && claude --continue] → M → Mp → Mps → inbox → Nw → N → Nr → Nt → done
#        → [Leader accepts 560] → [Main integrates this Task's branch into GraphTraj dev, with the AGENTS.md lines
#        122-124 replacement from engineer.md] → T.  Rollback: R.  Timer listing at any time: timers.
# B does not need the candidate on dev (Correction 1): it builds from `git archive $TARGET` behind product_guard.
# Restart: Main's tasks/agents calls run inside its host process `graphtraj.runtimes.claude.host serve`, which keeps
# the graphtraj and graftling modules it loaded (a7b20447 + 0.6.2) until it restarts. Its Task reads after I would also
# meet migrated state with old code. So Main is exited (USER /exit) before I and resumes with `claude --continue` only
# after I has installed and migrated: no host ever reads the migrated state with the old code. Member Workers started
# after I load the new code.
# No step signals a process it did not start. Backups and scratch under $H/tmp/560 (Main created it); the isolated
# real-host project under /private/tmp/vproject-560. 532's backup $H/tmp/532/backup is only listed, never modified.
# Only rehearse.zsh sets ADOPT560_* / VERIFY560_*. The defaults are the real paths.
set -u
setopt no_bg_nice   # background samplers must not try to renice themselves (refused in a sandbox)
SD=${0:A:h}
H=${ADOPT560_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT560_BASE:-$H/tmp/560}
RT=${ADOPT560_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT560_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT560_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/560-graftling-0-6-3-release-and-production-adoption}
G=${ADOPT560_G:-$H/graftling}   # graftling repository: rel writes dev, main and v0.6.3 there; B reads `git archive v0.6.3`
GTAG=${VERIFY560_GTAG:-v0.6.3}
GVERSION=0.6.3      # the graftling I installs
GOLDVERSION=0.6.2   # production's graftling now (528)
GCOMMIT=${VERIFY560_GCOMMIT:-ef7c37db15f4e6318fd5b6bf5bd79321b876eac5}   # graftling 0.6.3 (560) = v0.6.3
GLAYOUT=10dd56b553e7202cbf1dc9773b3a8fa6d5d9bfcc   # its parent: conventional layout (560)
GBASE=${VERIFY560_GBASE:-9f962bcff91c37fc2aef177b4ab1457f3de5680b}   # graftling dev when 560 was dispatched
GBRANCH=agent/560-graftling-0.6.3
BUNDLE=$SD/graftling-0.6.3.bundle
TARGET=${VERIFY560_TARGET:-8949caff74156d14625f45d7d6b762a04cef87eb}   # GraphTraj candidate: dev 3b9c2af7 + 560
C8=${TARGET[1,8]}   # per-commit names
OLD=a7b20447ce9c4ffeee62aba026265f6a1e0f10d2   # production's graphtraj now (532)
GREC=${ADOPT560_GREC:-$SD/G-record}   # the committed full-suite record (run.txt, suite.txt, failures.txt)
OLDBASE=${ADOPT560_OLDBASE:-$H/tmp/532}   # 532's backup: listed only, never touched
TASK=560-graftling-0-6-3-release-and-production-adoption
TASK_ID=560
CHILD=n560
NEWS=graphtraj; OLDS=agents   # .mcp.json server keys: the one production has (514/515) and the old one
ISO=$SD/../verify-common/claude_isolation.py   # 489's shared isolation (settings + answer check)
CC_EXPECT=$(cat ${ADOPT560_BASE:-$H/tmp/560}/cc.version 2>/dev/null)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
W=${ADOPT560_W:-$H/.graphtraj/core/state/tasks/$TASK/adoption}
R=$W/raw-$C8
CTL=$R/ctl
N=$W/wheels-$C8   # graphtraj-0.1.0 AND graftling-0.6.3: what I installs (proddiff compares every wheel here)
SRC=$W/src-$C8
GSRC=$W/gsrc-$GVERSION   # git archive of graftling $GTAG (the archive root holds pyproject.toml from 0.6.3)
GOLDSRC=$W/gsrc-base     # git archive of graftling $GBASE, built the old way (src/graftling) for the layout proof
GOLDW=$W/glwheel-base    # that old-layout wheel: B's layout comparison only, never installed
BK=$BASE/backup
VV=$BASE/vvenv-$C8
VPL=$W/vplug-$C8
VP=$VPL/graphtraj-claude-host
VE=$W/ventries-$C8
VPROJECT=${ADOPT560_VPROJECT:-/private/tmp/vproject-560}
DEMO=$BASE/demo/h   # V's migration demo: a copy of production Task state
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
PROJECTS=${ADOPT560_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT560_STUB:-} ]] && path=($ADOPT560_STUB $path)   # rehearsal only: stub hosts first
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
      'Reply with exactly one line: CODEX-560-OK. Use no tools.' < /dev/null > $R/$1-codex.txt 2> $R/$1-codex.err)
  local rc=$?; print "codex exec rc=$rc (142 = 180 s timeout)"
  grep -m1 -E '^model:|model:' $R/$1-codex.err $R/$1-codex.txt 2>/dev/null | head -1 | sed 's/^/codex configured /'
  if grep -qx 'CODEX-560-OK' $R/$1-codex.txt; then print "CHECK 560 Codex answers CODEX-560-OK (configured model, logged in): PASS"
  else print "CHECK 560 Codex answers CODEX-560-OK (configured model, logged in): FAIL ($(tail -c 300 $R/$1-codex.err | tr '\n' ' '))"; return 1; fi
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
    && print "CHECK 560 Codex hooks entry names $P -m graphtraj.runtimes.codex.stop_hook for SessionStart/Stop/SessionEnd: PASS" \
    || { print "CHECK 560 Codex hooks entry names $P -m graphtraj.runtimes.codex.stop_hook for SessionStart/Stop/SessionEnd: FAIL"; return 1; }
  out=$(print -r -- '{"hook_event_name":"Probe560","session_id":"probe-560","cwd":"'${2:-$VPROJECT}'"}' | (cd ${2:-$VPROJECT} && clean $P -I -m graphtraj.runtimes.codex.stop_hook) 2>&1)
  [[ $out == '{}' ]] && print "CHECK 560 Codex hooks entry runs (neutral event answers {}): PASS" \
    || { print -r -- "CHECK 560 Codex hooks entry runs (neutral event answers {}): FAIL (${out[1,300]})"; return 1; }
}
# 560 (563): every Task's task.yml, task.md and definitions/ plus the Worldline and the task index, copied (APFS clone)
# from state $1 into $2, and the symlinks under $1/tasks with their targets. R restores from it.
state_copy() {
  local S=$1 D=$2 d
  mkdir -p $D/tasks || return 1
  cp -cRp $S/worldline $D/ || return 1
  [[ -e $S/task-index.json ]] && { cp -cp $S/task-index.json $D/ || return 1; }
  for d in $S/tasks/[^.]*(N/); do
    mkdir $D/tasks/$d:t && cp -cp $d/task.yml $d/task.md(N) $D/tasks/$d:t/ || return 1
    [[ -d $d/definitions ]] && { cp -cRp $d/definitions $D/tasks/$d:t/ || return 1; }
  done
  (cd $S/tasks && find . -type l -exec sh -c 'printf "%s\t%s\n" "$1" "$(readlink "$1")"' _ {} \;) > $D/links.tsv
  print -r -- "state copy: $(print -l $D/tasks/[^.]*(N/) | wc -l | tr -d ' ') Task directories, $(print -l $D/tasks/*/task.md(N) | wc -l | tr -d ' ') task.md, $(print -l $D/tasks/*/definitions/*.md(N) | wc -l | tr -d ' ') definitions/*.md, $(wc -l < $D/links.tsv | tr -d ' ') links -> $D"
}
# 560 (563): preview, migrate, migrate again, hash before/after; $1 = graphtraj of the venv, $2 = Harness root
# (production or the demo copy), $3 = output prefix. Prints PASS/FAIL lines; returns 1 on any failure.
migrate_check() {
  local GT=$1 HR=$2 O=$3 S=$2/.graphtraj/core/state rc
  (cd ${TMPDIR:-/tmp} && clean ${GT:h}/python -I $SD/defs563.py hashes $S $O-before.json) || return 1
  say "563 preview (public entry; writes nothing)"
  (cd $HR && clean $GT migrate-task-definitions --preview) > $O-preview.yml; rc=$?
  print "preview rc=$rc"; (( rc == 0 )) || { cat $O-preview.yml; return 1; }
  grep -E '^(tasks|unchanged|preview):' $O-preview.yml; print -r -- "planned renames: $(grep -c '^- task_id:' $O-preview.yml)"
  say "563 migrate (its own backup under .graphtraj/backups)"
  (cd $HR && clean $GT migrate-task-definitions) > $O-migrate.yml; rc=$?
  print "migrate rc=$rc"; (( rc == 0 )) || { cat $O-migrate.yml; return 1; }
  grep -E '^(tasks|unchanged|backup|event_id):' $O-migrate.yml; print -r -- "renamed: $(grep -c '^- task_id:' $O-migrate.yml)"
  say "563 migrate again (must rename nothing)"
  (cd $HR && clean $GT migrate-task-definitions) > $O-again.yml; rc=$?
  print "again rc=$rc"; grep -E '^(renamed|message):' $O-again.yml
  local fail=0
  grep -q '^renamed: \[\]' $O-again.yml && print "CHECK 560 563 second run renames nothing: PASS" || { print "CHECK 560 563 second run renames nothing: FAIL"; fail=1; }
  (cd ${TMPDIR:-/tmp} && clean ${GT:h}/python -I $SD/defs563.py hashes $S $O-after.json) || return 1
  (cd ${TMPDIR:-/tmp} && clean ${GT:h}/python -I $SD/defs563.py compare $O-before.json $O-after.json $S) || fail=1
  print "CHECK 560 563 migration: every Task's current definition and all versions hash-equal: $( (( fail == 0 )) && print PASS || print FAIL)"
  return $fail
}
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
    sleep ${ADOPT560_WAIT:-20}
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
  ask_model MODEL-OK 00-model || { print "STOP: claude -p answer check failed (above): no answer, prompt echo, or the Harness AGENTS.md loaded (489). If it says login/API key: USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "560: Codex answers one line from the isolated $VPROJECT with its configured model and login (codex exec; no tools)"
  codex_answer 00 || { print "STOP: Codex did not answer CODEX-560-OK (above). If it says login: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
  say "560: scripts run through zsh, TMPDIR outside the Harness"
  print -r -- "this script: $THIS | interpreter: zsh $ZSH_VERSION"
  check_tmp || return 1
  say "560: production Task state still unmigrated (563): task.md files now (I migrates them; read only)"
  print -r -- "Task directories: $(print -l $STATE/tasks/[^.]*(N/) | wc -l | tr -d ' ') | task.md: $(print -l $STATE/tasks/*/task.md(N) | wc -l | tr -d ' ') | definitions/*.md: $(print -l $STATE/tasks/*/definitions/*.md(N) | wc -l | tr -d ' ')"
  say "host quiet (the CPU report needs it): load average and running test runs (information)"
  print -r -- "load average: $(sysctl -n vm.loadavg 2>&1)"
  print -r -- "test runs now: $(ps -axww -o pid=,command= 2>/dev/null | grep -E 'run_test_shards|-m pytest' | grep -vc grep)"
  say "484/486: production agents control records before the install (states and notification fields; read only)"
  $CONDA -I $SD/ctl497.py snap $H $CTL/00.json
  say "490 / known interference: every budget_idle_timer now (listed only, never signalled)"; timer_list $R/00-timers-ps.txt
  say "production versions now (expect graphtraj 0.1.0 = ${OLD[1,8]} from 532 and graftling $GOLDVERSION from 528; pip check clean)"
  $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  $RT/bin/python -m pip check --disable-pip-version-check; print "pip check rc=$?"
  local d; for d in $(site)/graphtraj-*.dist-info(N) $(site)/graftling-*.dist-info(N); do
    print -r -- "production ${d:t} direct_url: $(cat $d/direct_url.json 2>/dev/null || print none)"; done
  print -r -- "(expected: graphtraj from 532's adoption/wheels-${OLD[1,8]}/graphtraj-0.1.0-…whl; graftling from 528's adoption/wheels-8267f9e5/graftling-$GOLDVERSION-…whl)"
  say "plugin files and hashes (560: graftling 0.6.3 changes claude/host_context.mjs (533), so I's configuration --write is expected to change hooks/host_context.mjs; V shows the diff)"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  grep -nE '^const (PLUGIN|SERVER|PREFIX)' $PDIR/hooks/host_context.mjs | sed 's/^/production copy: /'
  say "entry files (hashes; .mcp.json: 515 left only '$NEWS')"; shasum -a 256 $ENTRIES; tree mcp $H/.mcp.json
  mcp_keys $H/.mcp.json
  say "Main-owned .claude/settings.local.json (read only)"; settings_view $H/.claude/settings.local.json
  say "backup must be absent; 532's backup $OLDBASE/backup is listed, never touched"
  ls -d $BK 2>&1; ls -ld $OLDBASE/backup 2>&1; [[ -e $OLDBASE/backup/COMPLETE ]] && print "532 backup COMPLETE marker: present" || print "532 backup COMPLETE marker: absent"
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "production holds graphtraj ${OLD[1,8]} + graftling $GOLDVERSION: the 560 markers must be absent now"; $CONDA -I $SD/markers.py $(site) absent | tail -1
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
  say "current Claude Main Session"; local id=$(detect_main)
  if [[ -n $id ]]; then print -r -- $id > $BASE/main.session; MAIN=$id; print "MAIN=$id (saved to $BASE/main.session)"; else print "MAIN NOT FOUND"; fi
  say "processes using the venv now, classified (information only; Main's host is expected here)"
  guard || print "guard: BLOCKING at 00 is information only (Main's own host is expected here; I waits for members)"
  return 0
}

step_B() {
  say "the Worktree carries no product change beyond $C8 (only scripts/ differ)"
  product_guard || return 1
  rm -rf $SRC $GSRC $GOLDSRC $N $GOLDW; mkdir -p $SRC $GSRC $GOLDSRC $N $GOLDW   # this commit's own directories only
  # Correction 1: information only. GraphTraj integration comes after the Leader accepts 560 (just before T); the
  # candidate's identity is guarded by product_guard and `git archive $TARGET`, so production installs exactly $C8.
  say "GraphTraj dev (information only; integration follows the Leader's acceptance, before T)"
  local dv=$(git -C $WT rev-parse -q --verify refs/heads/dev 2>/dev/null)
  print -r -- "GraphTraj dev: ${dv:-NOT FOUND} | dev contains $C8: $(git -C $WT merge-base --is-ancestor $TARGET ${dv:-missing} 2>/dev/null && print yes || print no) | the wheel is built from git archive $TARGET"
  say "product diff production ${OLD[1,8]} -> $C8 (information; the 560 markers below are the gate)"
  print -r -- "git diff --stat ${OLD[1,8]} $C8 -- src plugins pyproject.toml: $(git -C $WT diff --shortstat $OLD $TARGET -- src plugins pyproject.toml)"
  say "graftling repository $G (read only here): tag $GTAG, dev, main"
  local gc=$(git -C $G rev-parse -q --verify "$GTAG^{commit}" 2>/dev/null) gm=$(git -C $G rev-parse -q --verify main 2>/dev/null) gd=$(git -C $G rev-parse -q --verify dev 2>/dev/null)
  print "$GTAG^{commit}: ${gc:-NOT FOUND} | tag object: $(git -C $G rev-parse -q --verify refs/tags/$GTAG 2>/dev/null || print none) | type: $(git -C $G cat-file -t $GTAG 2>/dev/null)"
  print "main: ${gm:-NOT FOUND} | dev: ${gd:-NOT FOUND} | main = dev = $GTAG: $([[ -n $gc && $gc == $gm && $gc == $gd ]] && print yes || print NO)"
  [[ $gc == $GCOMMIT ]] && print "$GTAG peels to $GCOMMIT: yes" || { print "STOP: $GTAG^{commit} is ${gc:-missing}, not $GCOMMIT (graftling 0.6.3 (560)). Run rel first, or Main asks the Leader."; return 1; }
  [[ $(git -C $G cat-file -t refs/tags/$GTAG 2>/dev/null) == tag ]] && print "$GTAG is an annotated tag (cat-file -t: tag): yes" || { print "STOP: $GTAG is not an annotated tag (cat-file -t: $(git -C $G cat-file -t refs/tags/$GTAG 2>&1)). Main asks the Leader."; return 1; }
  print "$GTAG tagger: $(git -C $G for-each-ref --format='%(taggername) %(taggeremail) %(taggerdate:iso)' refs/tags/$GTAG)"
  print "$GTAG commit author / committer: $(git -C $G log -1 --format='%an %ae / %cn %ce' $gc)"
  git -C $G archive $GTAG | tar -x -C $GSRC || return 1
  git -C $G archive $GBASE | tar -x -C $GOLDSRC || return 1
  git -C $WT archive $TARGET | tar -x -C $SRC || return 1
  [[ -e $SRC/src/graftling ]] && { print "STOP: $TARGET still carries src/graftling"; return 1; }
  print "graphtraj archive carries no src/graftling: yes"
  say "560 layout: graftling $GTAG builds from the archive root"
  print "archive root pyproject.toml: $([[ -f $GSRC/pyproject.toml ]] && print yes || print NO) | src/graftling/pyproject.toml: $([[ -e $GSRC/src/graftling/pyproject.toml ]] && print 'present (NOT expected)' || print absent) | root README/CHANGELOG/PUBLIC_API: $(ls $GSRC/README.md $GSRC/CHANGELOG.md $GSRC/PUBLIC_API.md 2>/dev/null | wc -l | tr -d ' ')/3 | docs/install: $(print -l $GSRC/docs/install/*.md(N) | wc -l | tr -d ' ') guides"
  [[ -f $GSRC/pyproject.toml && ! -e $GSRC/src/graftling/pyproject.toml ]] || { print "STOP: $GTAG does not have the 560 root layout"; return 1; }
  print "graftling archive version line: $(grep -E '^__version__' $GSRC/src/graftling/__init__.py)"
  say "build with $CONDA (setuptools $($CONDA -c 'import setuptools; print(setuptools.__version__)'); --no-index --no-deps --no-build-isolation)"
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $SRC || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $GSRC || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $GOLDW $GOLDSRC/src/graftling || return 1
  say "the two wheels I installs, and sha256 (expect graphtraj-0.1.0 and graftling-$GVERSION in $N)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT; print "$GTAG ${gc}" > $N/GRAFTLING
  local all=($N/*.whl(N)) gv req
  [[ ${#all} == 2 && $(wheel_of graphtraj) == */graphtraj-0.1.0-* && $(wheel_of graftling) == */graftling-$GVERSION-* ]] || { print "STOP: wheel 名称不符（$N 只能有 graphtraj-0.1.0 与 graftling-$GVERSION）"; return 1; }
  gv=$(unzip -p $(wheel_of graftling) '*.dist-info/METADATA' 2>/dev/null | sed -n 's/^Version: //p')
  print "graftling wheel version: $gv"; [[ $gv == $GVERSION ]] || { print "STOP: graftling wheel version ${gv:-unreadable}, not $GVERSION"; return 1; }
  say "560 layout: the $GTAG wheel against the old-layout wheel of graftling dev ${GBASE[1,8]} (same code, entry points, metadata; the documents dropped)"
  $CONDA -I $SD/wheelcmp560.py $GOLDW/graftling-*.whl(N[1]) $(wheel_of graftling) || { print "STOP: the 560 layout changed the wheel's code, entry points or metadata"; return 1; }
  say "the new graphtraj's graftling requirement (wheel METADATA): satisfied by $GVERSION, NOT by production's $GOLDVERSION (a pair)"
  req=$(unzip -p $(wheel_of graphtraj) '*.dist-info/METADATA' | grep -E '^Requires-Dist: graftling')
  print "graphtraj wheel ${req:-Requires-Dist: NOT FOUND}"
  $CONDA -I -c 'import sys
from packaging.requirements import Requirement
r = Requirement(sys.argv[1].removeprefix("Requires-Dist: "))
new, old = r.specifier.contains(sys.argv[2]), r.specifier.contains(sys.argv[3])
verdict = {True: "PASS", False: "FAIL"}
print(f"CHECK 560 Requires-Dist {r} satisfied by {sys.argv[2]}: {verdict[new]}")
print(f"CHECK 560 Requires-Dist {r} NOT satisfied by {sys.argv[3]}: {verdict[not old]}")
sys.exit(0 if new and not old else 1)' "$req" $GVERSION $GOLDVERSION || { print "STOP: the graphtraj requirement does not pair with graftling $GVERSION"; return 1; }
  say "both wheels = their git archives, file by file (gate)"
  $CONDA -I $SD/pkgdiff532.py graphtraj $(wheel_of graphtraj) archive:$SRC/src "560 graphtraj wheel equals git archive $C8" - || { print "STOP: the graphtraj wheel differs from git archive $C8"; return 1; }
  $CONDA -I $SD/pkgdiff532.py graftling $(wheel_of graftling) archive:$GSRC/src "560 graftling wheel equals git archive $GTAG" - || { print "STOP: the graftling wheel differs from git archive $GTAG"; return 1; }
  say "560 markers in the wheels (expect present)"
  rm -rf $W/wheelview-$C8; mkdir -p $W/wheelview-$C8; (cd $W/wheelview-$C8 && unzip -qo $(wheel_of graphtraj) 'graphtraj/*' && unzip -qo $(wheel_of graftling) 'graftling/*') || return 1
  $CONDA -I $SD/markers.py $W/wheelview-$C8 present || { print "STOP: a 560 marker is missing from the wheels"; return 1; }
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
  # 560: production's plugin graphtraj-claude-host is written by graftling.claude.claude_host_plugin from
  # graftling/claude/host_context.mjs and hooks. 0.6.3 changes host_context.mjs (533: notices drawn as transcript rows),
  # so hooks/host_context.mjs is EXPECTED to change and nothing else; at `claude --continue` Claude Code may show ONE
  # native dialog for it: the plugin/hooks trust dialog of graphtraj-claude-host (USER trusts it).
  say "candidate plugin: new code writes into a scratch copy of production's plugin (560: only hooks/host_context.mjs may change)"
  rm -rf $VPL; mkdir -p $VPL; cp -Rp $PDIR $VPL/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name changed=(); : > $R/V-plugin.diff
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; changed+=($name); diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  print -r -- "V-plugin.diff: $(wc -l < $R/V-plugin.diff | tr -d ' ') lines ($R/V-plugin.diff)"
  if [[ ${changed[*]} == '' || ${changed[*]} == hooks/host_context.mjs ]]; then
    print "CHECK 560 candidate plugin changes only hooks/host_context.mjs (533): PASS ($( (( ${#changed} )) && print 'changed: at claude --continue expect at most ONE native dialog, the plugin/hooks trust dialog of graphtraj-claude-host' || print 'unchanged: no dialog expected'))"
  else print "CHECK 560 candidate plugin changes only hooks/host_context.mjs (533): FAIL (changed: ${changed[*]}; STOP: give $R/V-plugin.diff to the Leader)"; rc=1; fi
  (( ${#changed} )) && print "plugin dialog expected at claude --continue: yes (one: plugin/hooks trust for graphtraj-claude-host)" > $R/V-dialog.txt || print "plugin dialog expected at claude --continue: no" > $R/V-dialog.txt
  grep -q '^const SERVER = "graphtraj";' $VP/hooks/host_context.mjs && print "candidate host_context.mjs const SERVER = \"graphtraj\": yes (515's, unchanged)" \
    || { print "STOP: candidate host_context.mjs does not name the server graphtraj"; rc=1; }
  say "graftling: production's $GOLDVERSION vs the $GTAG wheel (information: the files 0.6.3 changes)"
  $CONDA -I $SD/pkgdiff532.py graftling $(wheel_of graftling) $(site) "graftling $GTAG differs from production $GOLDVERSION (information)" - 2>&1 | sed 's/^CHECK /INFO /' | tail -2 | tee $R/V-gldiff.txt
  say "graphtraj: the $C8 wheel vs production's installed ${OLD[1,8]} (information)"
  $CONDA -I $SD/pkgdiff532.py graphtraj $(wheel_of graphtraj) $(site) "graphtraj $C8 differs from production ${OLD[1,8]} (information)" - 2>&1 | sed 's/^CHECK /INFO /' | tail -2 | tee $R/V-gtdiff.txt
  say "560 real entries in the scratch venv: graphtraj-mcp tools/list and the Codex hooks entry (isolated $VPROJECT)"
  vproject_init $VV/bin/graphtraj || rc=1
  (cd ${TMPDIR:-/tmp} && clean $P -I $SD/mcp560.py scratch-graphtraj-mcp $VPROJECT $VV/bin/graphtraj-mcp) || rc=1
  codex_hook_check $VV || rc=1
  say "560 (563): migration demo on a copy of production Task state with the candidate (production is only read)"
  [[ -e $BASE/demo ]] && chmod -R u+w $BASE/demo && rm -rf $BASE/demo
  state_copy $STATE $DEMO/.graphtraj/core/state || { print "STOP: state copy failed"; return 1; }
  print -r -- 'version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/core/worktrees
  state: .graphtraj/core/state
agent_runner:
  max_concurrency: 1' > $DEMO/.graphtraj/core/config.yml
  migrate_check $VV/bin/graphtraj $DEMO $BASE/demo/V || rc=1
  say "560 markers: present in the candidate, absent in production"
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
  say "read only against the real project: archives, configuration, roles; Task graph of the MIGRATED demo copy (the candidate refuses unmigrated state)"
  touch $W/V-marker-$C8
  $P -I $SD/adopt_plugin.py readcheck $H $DEMO/.graphtraj/core/state || rc=1
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
  say "560 (563): pre-migration Task state (every Task's task.yml, task.md, definitions/; Worldline; task index; links) for R"
  state_copy $STATE $BK/state || return 1
  (cd ${TMPDIR:-/tmp} && $CONDA -I -c 'import sys; sys.path.insert(0, sys.argv[3]); import json, defs563; from pathlib import Path; Path(sys.argv[2]).write_text(json.dumps(defs563.hashes(Path(sys.argv[1])), indent=1)); print("hashed", sys.argv[1])' $BK/state $BK/state.hashes.json $SD) || return 1
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
  say "installed graphtraj and graftling files vs the new wheels, file by file (no 0.6.2 file or dist-info left)"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS|^FAIL' $R/I-verify.txt; (( rc == 0 )) || return 1
  local left=($S/graftling-$GOLDVERSION.dist-info(N))
  (( ${#left} == 0 )) && print "CHECK 560 graftling $GOLDVERSION dist-info gone: PASS" || { print "CHECK 560 graftling $GOLDVERSION dist-info gone: FAIL"; return 1; }
  say "entry scripts of the wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of graftling); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graftling.control as c, graftling.tool_descendants as td, graphtraj.execution.runner_worker as rw; print("graftling", graftling.__version__); print(h.__file__); print("457", c._stop_escaped.__name__, "| 459 SAMPLE_SECONDS", td.SAMPLE_SECONDS, "| 460", rw.TOOL_PROCESSES_RECORD); assert graftling.__version__ == "0.6.3"' || return 1
  $P -c 'import importlib.metadata as md, pathlib, graftling, graphtraj; gs = pathlib.Path(graftling.__file__).parent; print("395 layout graftling", graftling.__version__, "| distributions", sum(1 for d in md.distributions() if (d.metadata["Name"] or "").lower() == "graftling"), "| beside graphtraj:", gs.parent == pathlib.Path(graphtraj.__file__).parent.parent, "| graftling.mjs:", (pathlib.Path(graphtraj.__file__).parent / "runtimes/graftling.mjs").is_file(), "| graphtraj requires", [r for r in md.requires("graphtraj") if r.startswith("graftling")]); assert graftling.__version__ == "0.6.3"' || return 1
  say "560 sources: the wheels graphtraj and graftling were installed from (direct_url.json) and what they were built from"
  local d; for d in $S/graphtraj-0.1.0.dist-info $S/graftling-$GVERSION.dist-info; do print -r -- "${d:t} direct_url: $(cat $d/direct_url.json 2>/dev/null || print none)"; done
  local du=$(cat $S/graphtraj-0.1.0.dist-info/direct_url.json 2>/dev/null) dg=$(cat $S/graftling-$GVERSION.dist-info/direct_url.json 2>/dev/null)
  [[ $du == *"wheels-$C8/graphtraj-0.1.0-"*".whl"* && $dg == *"wheels-$C8/graftling-$GVERSION-"*".whl"* ]] && print "CHECK 560 direct_url of both names the wheels-$C8 wheels: PASS" || { print "CHECK 560 direct_url of both names the wheels-$C8 wheels: FAIL"; return 1; }
  print -r -- "built from: graphtraj git archive $TARGET, graftling git archive $(<$N/GRAFTLING) (B: wheels = archives file by file; proddiff above: installed bytes = these wheels)"
  say "560 markers in the installed site-packages (expect PASS 6/6)"; $CONDA -I $SD/markers.py $S present || return 1
  say "395 layout in production: exactly one graftling, from the wheel file"
  $P -I $SD/onegraft.py $RT $GVERSION || return 1
  say "395: production's graftling.mjs resolves graftling to the sibling directory (empty environment: no python fallback)"
  node_resolve $RT || return 1
  date +%s > $R/I-install-end.epoch   # 490: timers started after this run the installed $C8 code (new)
  say "configuration --write from the new installation (as 515/525/528/532; 560 expects only hooks/host_context.mjs to change)"
  (cd $H && clean $P -m graphtraj.runtimes.claude.host configuration --write --project $H --claude $(claude_bin)) > $R/I-configuration.txt 2>&1
  local crc=$?; print "configuration --write rc=$crc (output lines: $(wc -l < $R/I-configuration.txt); kept in $R/I-configuration.txt)"; (( crc == 0 )) || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  local pch=$(diff -rq $BK/plugin $PDIR 2>&1 | sed -E 's|^Files .*/plugin/([^ ]+) and .*|\1|' | tr '\n' ' ')
  print -r -- "plugin files changed by the install: ${pch:-none} (V expected: $(cat $R/V-dialog.txt 2>/dev/null))"
  [[ -z $pch || $pch == 'hooks/host_context.mjs ' ]] && print "CHECK 560 installed plugin changes only hooks/host_context.mjs: PASS" || { print "CHECK 560 installed plugin changes only hooks/host_context.mjs: FAIL"; return 1; }
  say "CHECKs after configuration --write"
  mcp_keys $H/.mcp.json || return 1
  local f; for f in $ENTRIES; do
    if cmp -s $f $BK/entries/${${f#$H/}//\//__}; then print "bytes unchanged: ${f#$H/}"
    else print "changed: ${f#$H/} (before -> after, secret-like values hidden; not expected for 560: tell Main)"
      $CONDA -I $SD/adopt_tree.py redactjson $BK/entries/${${f#$H/}//\//__} > $BK/diff.before
      $CONDA -I $SD/adopt_tree.py redactjson $f > $BK/diff.after; diff $BK/diff.before $BK/diff.after; rm -f $BK/diff.before $BK/diff.after; fi
  done
  settings_view $H/.claude/settings.local.json
  tree mcp $H/.mcp.json
  say "also unchanged (information; any FAILED means another writer: tell Main)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  say "560 real entries of the installed venv (run in the isolated $VPROJECT): graphtraj-mcp tools/list and the Codex hooks entry"
  (cd ${TMPDIR:-/tmp} && clean $P -I $SD/mcp560.py production-graphtraj-mcp $VPROJECT $RT/bin/graphtraj-mcp) || return 1
  codex_hook_check $RT || return 1
  return 0
}

# 560 (563): migrate production Task state with the installed code, right after the install, before Main resumes.
do_migrate() {
  say "560 (563): production Task state migration (no member runs: guard checked right before pip)"
  migrate_check $RT/bin/graphtraj $H $R/I-migrate || return 1
  say "pre-migration copy in the backup still equals what was migrated from (I's own copy vs the migration's before-hashes)"
  (cd ${TMPDIR:-/tmp} && $CONDA -I -c 'import json, sys; a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2])); same = a == b; print("CHECK 560 backup state copy equals the state just before the migration:", "PASS" if same else "FAIL"); sys.exit(0 if same else 1)' $BK/state.hashes.json $R/I-migrate-before.json) || return 1
  print -r -- "the migration's own backup: $(sed -n 's/^backup: //p' $R/I-migrate-migrate.yml) | I's copy for R: $BK/state"
}

# 560 (563): put I's pre-migration copy back. Current files are moved (never deleted) to $1/state. A Task created
# after I (absent from the copy) is listed and left alone; Worldline events appended after I move with the Worldline.
state_restore() {
  local KS=$1/state t d f line link target rc=0
  [[ -d $BK/state/tasks ]] || { print "no pre-migration copy $BK/state (I stopped before the migration): Task state not touched"; return 0; }
  say "560 (563): Task state restored from I's pre-migration copy; the current files kept in $KS"
  mkdir -p $KS/tasks || return 1
  for d in $BK/state/tasks/[^.]*(N/); do
    t=$d:t; mkdir -p $KS/tasks/$t
    for f in task.yml task.md definitions; do [[ -e $STATE/tasks/$t/$f ]] && { mv $STATE/tasks/$t/$f $KS/tasks/$t/ || rc=1; }; done
    cp -cp $d/task.yml $d/task.md(N) $STATE/tasks/$t/ || rc=1
    [[ -d $d/definitions ]] && { cp -cRp $d/definitions $STATE/tasks/$t/ || rc=1; }
  done
  local extra=(); for d in $STATE/tasks/[^.]*(N/); do [[ -d $BK/state/tasks/$d:t ]] || extra+=($d:t); done
  print -r -- "Tasks created after I (left as they are; tell Main): ${extra[*]:-none}"
  mv $STATE/worldline $KS/worldline && cp -cRp $BK/state/worldline $STATE/ || rc=1
  [[ -e $BK/state/task-index.json ]] && { mv $STATE/task-index.json $KS/ 2>/dev/null; cp -cp $BK/state/task-index.json $STATE/ || rc=1; }
  while IFS=$'\t' read -r link target; do
    [[ -n $link ]] || continue
    [[ $(readlink $STATE/tasks/$link 2>/dev/null) == $target ]] || { ln -sfn $target $STATE/tasks/$link && print -r -- "link restored: $link -> $target" || rc=1; }
  done < $BK/state/links.tsv
  (cd ${TMPDIR:-/tmp} && $CONDA -I -c 'import sys; sys.path.insert(0, sys.argv[3]); import json, defs563; from pathlib import Path
before = json.load(open(sys.argv[2])); now = defs563.hashes(Path(sys.argv[1]))
same = {k: now.get(k) for k in before} == before
print("CHECK 560 Task state after R equals the pre-migration copy (every Task in it: versions, current, modes):", "PASS" if same else "FAIL")
print("task.md files after R:", sum(1 for k in before if "task.md" in before[k]["names"]), "expected from the copy;", sum(1 for p in (Path(sys.argv[1]) / "tasks").glob("*/task.md")), "present")
sys.exit(0 if same else 1)' $STATE $BK/state.hashes.json $SD) || rc=1
  return $rc
}

step_R() {
  local KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S) rc=0 f
  date '+R start %F %T'; mkdir -p $KEEP
  say "before restoring: how the venv differs from the pre-install manifest"; tree compare $BK/venv.manifest $RT | tail -1
  # 560: BOTH packages come back from the backup's whole venv (graphtraj ${OLD[1,8]}, graftling $GOLDVERSION), and the
  # Task state comes back from I's pre-migration copy (the old code refuses nothing, but it reads task.md).
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
  $CONDA -I $SD/pkgdiff532.py graftling ${SA[1]:-$RT/missing} ${SOLD[1]:-$BK/venv/missing} "560 graftling restored (after R vs backup)" - | tail -1; (( ${pipestatus[1]} == 0 )) || rc=1
  $CONDA -I $SD/pkgdiff532.py graphtraj ${SA[1]:-$RT/missing} ${SOLD[1]:-$BK/venv/missing} "560 graphtraj restored (after R vs backup)" - | tail -1; (( ${pipestatus[1]} == 0 )) || rc=1
  state_restore $KEEP || rc=1
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

# GR (560): read only. The product guard, then the G record $GREC (run.txt: candidate and graftling commit; suite.txt:
# totals and exit; failures.txt: every FAILED/ERROR line of suite.txt and the shard logs). The candidate's
# src/tests/plugins/pyproject must equal $C8's and the graftling commit must be $GCOMMIT exactly (the v0.6.3 wheel).
# A FAILED/ERROR line is known only when 516's CURRENT definition (through its task.yml current_definition) names it.
step_GR() {
  local ok=0 cand gl tot ex line t any=0
  product_guard || { print "product guard STOP: the G record cannot stand for this Worktree"; ok=1; }
  [[ -f $GREC/run.txt && -f $GREC/suite.txt ]] || { print "STOP: no G record at $GREC (run.txt, suite.txt)"; print "CHECK 560 GR (guard + G record): FAIL"; return 1; }
  print -r -- "G record: $GREC"; sed 's/^/  run.txt: /' $GREC/run.txt
  cand=$(sed -n 's/^candidate: \([0-9a-f]\{40\}\).*/\1/p' $GREC/run.txt | head -1)
  gl=$(grep -oE 'git archive [0-9a-f]{40}' $GREC/run.txt | head -1 | awk '{print $3}')
  local cd=$(git -C $WT diff --name-only ${cand:-missing} $TARGET -- $GUARDED 2>&1)
  print -r -- "candidate: ${cand:-NOT FOUND} | git diff ${cand[1,8]} $C8 -- ${GUARDED[*]}: ${${cd//$'\n'/ }:-empty} | same product: $([[ -n $cand && -z $cd ]] && print yes || print NO)"
  [[ -n $cand && -z $cd ]] || ok=1
  print -r -- "graftling commit of the wheel: ${gl:-NOT FOUND} | = $GTAG ($GCOMMIT): $([[ $gl == $GCOMMIT ]] && print yes || print NO)"
  [[ $gl == $GCOMMIT ]] || ok=1
  grep -q 'TMPDIR=\|pytest temp root' $GREC/run.txt && print -r -- "pytest temp: $(grep -m1 'pytest temp root' $GREC/run.txt)"
  tot=$(grep -E '^=*.* (passed|failed)' $GREC/suite.txt | tail -1); ex=$(sed -n 's/^exit=//p' $GREC/suite.txt | tail -1)
  print -r -- "totals: ${tot:-NOT FOUND} | exit: ${ex:-NOT FOUND}"
  grep -m1 'test interpreter dependencies' $GREC/run.txt || { print "STOP: run.txt does not record the test interpreter's click/PyYAML/websockets/pytest versions"; ok=1; }
  grep -q 'click 8.5.0' $GREC/run.txt && print "test interpreter click = production's 8.5.0: yes" || { print "test interpreter click is not production's 8.5.0 (564): NO"; ok=1; }
  print -r -- "516 current definition (flaky tests): $KNOWN516"
  [[ -f $GREC/failures.txt ]] || { print "STOP: no failures.txt in $GREC"; ok=1; }
  any=$(grep -cE '^(FAILED|ERROR) ' $GREC/failures.txt 2>/dev/null)
  $CONDA -I $SD/gr560.py $GREC/failures.txt $KNOWN516 $WT; local cr=$?
  if [[ $ex == 0 && $any == 0 ]] || (( any > 0 && cr == 0 )); then print "CHECK 560 G record (${cand[1,8]} + $GTAG) no new failure: PASS"
  else print "CHECK 560 G record (${cand[1,8]} + $GTAG) no new failure: FAIL"; ok=1; fi
  print "CHECK 560 GR (guard + G record): $( (( ok == 0 )) && print PASS || print FAIL)"
  return $ok
}

# rel (560, Main): the graftling release in <Harness>/graftling. Fetch the release branch from the bundle by exact SHA,
# fast-forward dev and main to it, and create the annotated tag v0.6.3 there with the noreply tagger. No push.
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
step_rel() {
  local gd gm gt cur
  say "graftling repository $G before: dev, main, tags, working tree (dev's worktree must be clean)"
  gd=$(git -C $G rev-parse -q --verify refs/heads/dev); gm=$(git -C $G rev-parse -q --verify refs/heads/main)
  gt=$(git -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}" 2>/dev/null)
  print -r -- "dev: ${gd:-NOT FOUND} | main: ${gm:-NOT FOUND} | $GTAG: ${gt:-absent}"
  if [[ -n $gt ]]; then
    [[ $gt == $GCOMMIT && $gd == $GCOMMIT && $gm == $GCOMMIT ]] && { print "already released: $GTAG = dev = main = $GCOMMIT (nothing to do)"; rel_verify; return; }
    print "STOP: $GTAG exists at $gt, not as expected ($GCOMMIT with dev = main). Main asks the Leader; nothing changed."; return 1
  fi
  [[ $gd == $GBASE || $gd == $GCOMMIT ]] || { print "STOP: graftling dev is $gd, not $GBASE (560's base): dev moved since dispatch. Main asks the Leader; nothing changed."; return 1; }
  local dw=$(git -C $G worktree list --porcelain | awk '/^worktree /{w=$2} /^branch refs\/heads\/dev$/{print w}')
  print -r -- "dev is checked out in: ${dw:-no worktree}"
  [[ -z $dw || -z $(git -C $dw status --porcelain 2>/dev/null) ]] || { print "STOP: dev's worktree $dw has uncommitted changes; nothing changed"; return 1; }
  say "bundle $BUNDLE (sha256 $(shasum -a 256 $BUNDLE | cut -c1-16)…): verify and fetch $GBRANCH by exact SHA"
  git -C $G bundle verify -q $BUNDLE || { print "STOP: the bundle does not verify against $G"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | awk '{print $1}') == $GCOMMIT ]] || { print "STOP: the bundle head is not $GCOMMIT"; return 1; }
  git -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/${GBRANCH}" || return 1
  [[ $(git -C $G rev-parse $GBRANCH) == $GCOMMIT && $(git -C $G rev-parse $GBRANCH~1) == $GLAYOUT && $(git -C $G rev-parse $GBRANCH~2) == $GBASE ]] \
    && print "$GBRANCH = $GCOMMIT (parent $GLAYOUT, grandparent $GBASE): yes" || { print "STOP: $GBRANCH is not the expected two commits on $GBASE"; return 1; }
  say "merge $GBRANCH into dev (fast-forward only), main to dev (fast-forward only)"
  if [[ -n $dw ]]; then git -C $dw merge --ff-only -q $GBRANCH || return 1
  else git -C $G update-ref refs/heads/dev $GCOMMIT $gd || return 1; fi
  cur=$(git -C $G symbolic-ref -q --short HEAD 2>/dev/null)
  if [[ $cur == main ]]; then git -C $G merge --ff-only -q dev || return 1
  else git -C $G merge-base --is-ancestor $gm $GCOMMIT && git -C $G update-ref refs/heads/main $GCOMMIT $gm || { print "STOP: main is not an ancestor of dev"; return 1; }; fi
  say "annotated tag $GTAG at $GCOMMIT, tagger $RELNAME <$RELMAIL>"
  GIT_COMMITTER_NAME=$RELNAME GIT_COMMITTER_EMAIL=$RELMAIL git -C $G tag -a $GTAG $GCOMMIT \
    -m "graftling 0.6.3: agents notices as who · event over Markdown on Claude/Codex/Pi/DSH (533/535/536/538); DSH next-turn relay (545); send after a closing execution goes to the next (546); every input problem at once and arguments_file (555); DSH inject (561); conventional repository layout (560)" || return 1
  rel_verify
}
rel_verify() {
  local gt=$(git -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(git -C $G rev-parse dev) gm=$(git -C $G rev-parse main) ok=0
  print -r -- "$GTAG -> $gt | dev $gd | main $gm | type $(git -C $G cat-file -t refs/tags/$GTAG) | tagger $(git -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG)"
  [[ $gt == $GCOMMIT ]] && print "CHECK 560 $GTAG peels to $GCOMMIT: PASS" || { print "CHECK 560 $GTAG peels to $GCOMMIT: FAIL"; ok=1; }
  [[ $gd == $gm && $gm == $GCOMMIT ]] && print "CHECK 560 graftling dev == main == $GTAG: PASS" || { print "CHECK 560 graftling dev == main == $GTAG: FAIL"; ok=1; }
  [[ $(git -C $G cat-file -t refs/tags/$GTAG) == tag && $(git -C $G for-each-ref --format='%(taggeremail)' refs/tags/$GTAG) == "<$RELMAIL>" ]] \
    && print "CHECK 560 $GTAG is annotated with the noreply tagger: PASS" || { print "CHECK 560 $GTAG is annotated with the noreply tagger: FAIL"; ok=1; }
  print -r -- "version at $GTAG: $(git -C $G show ${GTAG}:src/graftling/__init__.py | grep -E '^__version__') | root pyproject: $(git -C $G cat-file -e ${GTAG}:pyproject.toml 2>/dev/null && print yes || print NO)"
  return $ok
}
# rp (560, Main, only after the USER confirms in this conversation): outward-facing push of graftling dev, main and
# v0.6.3 to its configured remote (528 released without a push step; the push is a separate, confirmed step here).
step_rp() {
  local remote=$(git -C $G remote | head -1)
  [[ -n $remote ]] || { print "graftling has no remote: nothing to push"; return 0; }
  rel_verify || { print "STOP: rel is not complete"; return 1; }
  print -r -- "remote $remote: $(git -C $G remote get-url $remote)"
  print -r -- "will push: dev main refs/tags/$GTAG (fast-forward only; no force)"
  [[ ${ADOPT560_PUSH_CONFIRMED:-} == yes ]] || { print "STOP: the push is outward-facing. Main asks the USER; after an explicit yes run: ADOPT560_PUSH_CONFIRMED=yes zsh $THIS rp"; return 1; }
  git -C $G push $remote refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/${GTAG} || return 1
  print -r -- "remote now: $(git -C $G ls-remote $remote refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" | tr '\n' ' ')"
}
# G (560, Main, optional; only if the Leader asks for a new suite run instead of the committed record): the full suite
# of this Worktree's HEAD with the $GTAG wheel from B, in the background (~25 min). Pytest temp under TMPDIR, outside
# the Harness. When it ends, GR with ADOPT560_GREC=<its directory>.
step_G() {
  setopt local_options no_bg_nice
  check_tmp || return 1
  [[ -n $(wheel_of graftling) ]] || { print "no graftling wheel in $N: run B first"; return 1; }
  product_guard || return 1
  # Resolved paths (/tmp is a link to /private/tmp on macOS): tests/pi_parity_scenarios.py maps sys.prefix and the
  # installed graftling by their resolved paths, so a venv reached through a link fails test_pi_generic_execution.
  local GV=${BASE:A}/gvenv-$C8 O=$W/G-$C8-$(date +%Y%m%dT%H%M%S) RUNTMP=${${TMPDIR:-/tmp}:A}/adopt-560-G-$(date +%Y%m%dT%H%M%S) D
  rm -rf $GV; $CONDA -m venv --system-site-packages $GV || return 1
  # Production's own dependency versions (click 8.5.0 and the rest), copied read only from $RT; they shadow the base
  # Python's copies (564: a Pi test needs click 8.5.0, Miniconda has 8.2.1). pytest comes from the base Python.
  local S=$(site); D=($GV/lib/python*/site-packages(N))
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml(N) $S/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D[1]/ || return 1
  $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(wheel_of graftling) || return 1
  $GV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  mkdir -p $O $RUNTMP
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR, outside the Harness)"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT ($GTAG, $(wheel_of graftling))"; print -r -- "python: $GV/bin/python"
    (cd ${TMPDIR:-/tmp} && $GV/bin/python -I -c 'import importlib.metadata as m, click, yaml, websockets, pytest; print("test interpreter dependencies:", " | ".join(f"{n} {m.version(n)} ({p.__file__})" for n, p in (("click", click), ("PyYAML", yaml), ("websockets", websockets), ("pytest", pytest))))'); } > $O/run.txt
  local extra=(${(Q)${(z)${ADOPT560_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $O/run.txt
  (cd $WT && TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra > $O/suite.txt 2>&1; print "exit=$?" >> $O/suite.txt; $CONDA -I $SD/fails560.py $O/failures.txt $O/suite.txt $O/shards/*(N.) > /dev/null) &!
  cat $O/run.txt; print -r -- "started in the background at $(date +%T); output: $O/suite.txt (last line 'exit=N' when it ends)"
  next "（G 结束后）ADOPT560_GREC=$O zsh $THIS GR"
}

case $STEP in
help) print "顺序: 00 → rel（graftling 发布：dev/main 快进到 $GTAG，建注释 tag）→ [rp 推送：仅在 USER 明确确认后] → B → GR（只读：已提交的全套测试记录）→ V（含 563 迁移演示）→ Vc（若要求则先 USER 做 Vu）→ Mpre → USER /exit Main → I（USER：安装两个 wheel 并迁移 Task 状态）→ USER: cd $H && claude --continue → M → Mp → Mps → inbox → Nw → N → Nr → Nt → done → [Leader 接受 560] → [Main 把本 Task 的分支集成进 GraphTraj dev，并替换 AGENTS.md 第 122-124 行（见 engineer.md）] → T；任何时候列计时器: timers；备份完成后可回退: R（两个包与迁移前的 Task 状态）。"
  print "USER 只做: rp 的确认（对外推送）、Vu（仅当 Vc 要求；信任框 'Yes, proceed'）、/exit Main、I、claude --continue（可能出现一个插件/hooks 信任框，见 V），失败时 R。其余都由 Main 运行。"
  next "zsh $THIS 00" ;;

rel) cv; print "[rel] Main. graftling 0.6.3 发布：从 $BUNDLE 按 SHA 取 $GBRANCH，dev 与 main 快进到 $GCOMMIT，建注释 tag $GTAG（tagger $RELNAME <$RELMAIL>）。不推送。对话框: 无。< 10 秒。只改 $G 的 dev、main、$GBRANCH 与 tag。"
  if logged $R/rel.txt step_rel; then
    summary rel "$(grep -E '^(dev:|already|CHECK|version at|.*= $GCOMMIT)' $R/rel.txt)"
    print "成功: 三行 CHECK 560 PASS（$GTAG peels to $GCOMMIT；dev == main == $GTAG；annotated, noreply tagger）；version at $GTAG: __version__ = \"0.6.3\"；root pyproject: yes。"
    print "\n推送是对外操作，单独一步：Main 先问 USER，USER 明确同意后才运行 rp（528 发布时没有推送步骤）。"
    print "B 不需要候选在 GraphTraj dev 上（它从 git archive $C8 构建）。GraphTraj 集成在 Leader 接受 560 之后、T 之前。"
    next "zsh $THIS B   （rp 另行：USER 确认推送后 ADOPT560_PUSH_CONFIRMED=yes zsh $THIS rp）"
  else print "\nrel STOP（见上）。把 $R/rel.txt 交给 Main/Leader。"; exit 1; fi ;;

rp) cv; print "[rp] Main，仅在 USER 明确确认之后。对外推送 graftling dev、main 与 $GTAG 到它的 remote（只快进，不 force）。对话框: 无（git 凭据由用户的 git 配置提供）。"
  logged $R/rp.txt step_rp || { print "\nrp 没有推送（见上）。"; exit 1; }
  next "zsh $THIS B" ;;

G) cv; print "[G] Main（只在 Leader 要求重跑全套测试时）。本 Worktree HEAD + B 的 $GTAG wheel，6 shards 后台约 25 分钟；pytest 临时目录在 TMPDIR（Harness 之外）。对话框: 无。期间不要跑别的测试。"
  logged $R/G.txt step_G || exit 1 ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE（scratch、main.session）、$VPROJECT 与 $R。约 2 分钟。"
  [[ -e $R/00.txt && ! -e $R/00-first.txt ]] && mv $R/00.txt $R/00-first.txt && print "previous 00.txt kept as $R/00-first.txt"
  : > $R/00.txt
  logged $R/00.txt step_00 || { print "\n00 STOP（see the STOP line above / 见上面的 STOP 行）。把 $R/00.txt 交给 Main，不要继续。"; exit 1; }
  summary 00 "$(grep -E '^claude:|^codex|ZSH_VERSION|inherited|answer|plugins in init|load average|test runs now|control records|timer pid|zombies|532 backup|Claude Code installed|^Version|pip check rc|direct_url|production copy|markers expected|CHECK|mcp.json servers|enabledMcpjsonServers|isolat|TMPDIR|task.md|running lines|may run now|^stopped|MAIN=|MAIN NOT|volume ids|^guard|advisor' $R/00.txt)"
  print "成功: 'claude:' 行给出路径与版本（Claude Code installed 已记录）；'answer check (expect clean): OK'；'CHECK 560 Codex answers CODEX-560-OK …: PASS'；'TMPDIR=… (outside the Harness)'；graphtraj 0.1.0 与 graftling $GOLDVERSION（direct_url: graphtraj 为 532 的 wheels-${OLD[1,8]}，graftling 为 528 的 wheels-8267f9e5）；pip check rc=0；'markers expected absent: PASS (6/6)'；'CHECK 515 .mcp.json has graphtraj, no agents …: PASS'；'isolation: OK'；task.md 行给出未迁移的数量；stopped: false；roles 有 advisor；$BK 'No such file'；532 backup COMPLETE marker: present；MAIN=<id>。"
  print "running lines 可以不为 0（其它 Task 的成员）；I 会等它们结束，不结束它们。若 answer 有 login/API key 字样: USER 在 Terminal 运行 claude（或 codex login）登录后重跑 00。"
  next "zsh $THIS rel" ;;

B) cv; print "[B] Main. 两个 wheel：graphtraj（git archive $C8）与 graftling（git -C $G archive $GTAG，从 archive 根目录构建）；I 两个一起装。不联网、不改 graftling 仓库和生产。对话框: 无。< 2 分钟。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked|peels|annotated|tagger|author|^main:|\^\{commit\}|product guard|GraphTraj dev|archive root|wheel version|Requires-Dist|CHECK|markers expected|carries|RESULT' $R/B.txt)"
    print "成功: 'product guard: PASS'；'GraphTraj dev: … dev contains $C8: …' 只是信息；'$GTAG peels to $GCOMMIT: yes' 与 'annotated … yes'；'archive root pyproject.toml: yes | src/graftling/pyproject.toml: absent'；$N 有 graphtraj-0.1.0 与 graftling-$GVERSION 两个 wheel；六行 'CHECK 560 layout …: PASS' 与 'RESULT 560 layout: PASS'；'CHECK 560 Requires-Dist … satisfied by $GVERSION: PASS' 与 '… NOT satisfied by $GOLDVERSION: PASS'；两行 'CHECK 560 … wheel equals git archive …: PASS'；'markers expected present: PASS (6/6)'；carries graftling/: 0；leaked: 0。"
    next "zsh $THIS GR"
  else print "\nB 失败。把 $R/B.txt 交给 Main（product guard STOP: Worktree 的 src/tests/plugins/pyproject 不等于 $C8；'peels' 或 'annotated' 失败: 先运行 rel，或交 Leader）。"; exit 1; fi ;;

GR) cv; print "[GR] Main. 只读：已提交的全套测试记录 ${GREC}（本 Worktree 候选 + $GTAG wheel，由 Engineer 运行）。检查守卫、候选与 $C8 的产品文件相同、graftling 提交 = $GCOMMIT、总数与 exit、FAILED 行（已知：516 当前定义）。对话框: 无。< 10 秒。"
  [[ -e $R/GR.txt ]] && cp -p $R/GR.txt $R/GR-$(date +%Y%m%dT%H%M%S).txt   # earlier GR results are kept
  : > $R/GR.txt   # a new GR replaces the old verdict: an earlier PASS never survives a later FAIL (I reads this file)
  logged $R/GR.txt step_GR; rc=$?
  summary GR "$(grep -E '^(product guard|STOP|G record|candidate|graftling commit|pytest temp|totals|516|  known|  NEW|  FAILED|CHECK)' $R/GR.txt)"
  print "成功: 'product guard: PASS'；'candidate: … same product: yes'；'graftling commit of the wheel: $GCOMMIT | = $GTAG …: yes'；'totals: … passed …' 与 'exit: 0'（或只有 'known (516)' 行）；'CHECK 560 G record … no new failure: PASS' 与 'CHECK 560 GR (guard + G record): PASS'。FAIL: 不要继续，交 Leader（I 会拒绝运行）。"
  (( rc == 0 )) && next "zsh $THIS V" || print "\nGR FAIL。把 $R/GR.txt 交给 Main/Leader。"; exit $rc ;;

V) cv; print "[V] Main. 安装前校验。对话框: 无。只读真实项目；scratch venv、候选插件、入口文件预测都在生产之外。约 2 分钟。"
  rm -f $R/V.ok   # only this run's result counts for I
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|CHECK|^(PASS|FAIL):|RESULT|markers expected|STOP|✘ lines|read_session|task graph|planned renames|renamed:|state copy|product guard: PASS|plugin dialog' $R/V.txt)"
    print "成功: 'CHECK 560 candidate plugin changes only hooks/host_context.mjs (533): PASS'（若 CHANGED，claude --continue 时最多一个插件/hooks 信任框）；'CHECK 560 scratch-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS'；两行 'CHECK 560 Codex hooks entry …: PASS'；"
    print "  563 演示: 'preview rc=0'、'migrate rc=0'、'CHECK 560 563 second run renames nothing: PASS'、defs563 的每行 PASS 与 'RESULT: PASS'、'CHECK 560 563 migration: … hash-equal: PASS'；'markers expected present: PASS (6/6)' 与 'markers expected absent: PASS (6/6)'；'503 layout: PASS' 与两行 node resolves PASS；候选 ✘ 不多于 baseline；read_session failures=0 与 task graph of the clone（迁移后的副本）；无 STOP。"
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
    print "成功: 'isolation: OK'，'CHECK 515 .mcp.json has graphtraj, no agents …: PASS'，'answer check: OK'，'graphtraj-claude-host loaded: YES'，PASS mcp__graphtraj__tasks 与 PASS mcp__graphtraj__agents，四行 'CHECK 515 init …: PASS'。"
    next "zsh $THIS Mpre    （GR 为 PASS 之后；然后 USER: /exit Main，再在 Terminal 运行 zsh $THIS I）"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（只有 Vc 要求时；需要终端和对话框，Main 做不了）。$(cv)"
  print "在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框（一个）: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若没有出现这个框，直接 /exit。若再问项目的 MCP server 'graphtraj' 或插件/hooks，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

Mpre) need_main; cv; print "[Mpre] Main，就在 USER /exit Main 之前（V、Vc 通过且 GR 为 PASS 之后）。486：重启前的生产 agents 控制记录快照（只读）。对话框: 无。约 1 分钟。"
  grep -q "^CHECK 560 GR (guard + G record): PASS" $R/GR.txt 2>/dev/null && print "GR: PASS (CHECK 560 GR (guard + G record): PASS)" || print "GR 还不是 PASS（$R/GR.txt 没有 'CHECK 560 GR (guard + G record): PASS'）：先运行 GR；I 会拒绝运行。"
  $CONDA -I $SD/ctl497.py snap $H $CTL/Mpre.json 2>&1 | tee $R/Mpre.txt
  print "成功: 'GR: PASS' 与 'control records snapshot Mpre.json: agents=… executions=…'。Mps 在 claude --continue 之后对比它。"
  print "\n为什么要重启 Main: Main 的 tasks/agents 调用在它的 host 进程（graphtraj.runtimes.claude.host serve）里执行，该进程一直使用启动时载入的 graphtraj ${OLD[1,8]} 与 graftling $GOLDVERSION。I 之后 Task 状态已迁移（563），旧代码不应再读它；所以 Main 在 I 之前退出，I 安装并迁移完成后才用 claude --continue 恢复（新 host 载入新代码）。503 的保护也要求安装时 Main 已退出。"
  print "\n下一步是 USER 的: 先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。I 会等其它 Task（$(active_tasks)）的成员结束（不要结束它们）。"
  next "USER（Main 已 /exit）: zsh $THIS I" ;;

I) need_main
  print "[I] USER. 等待成员结束、备份、安装两个 wheel、迁移 Task 状态（563）。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。约 5 分钟（等待时间另计）。"; cv
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。若它是一次放弃的 I 留下的（没有 INSTALL-STARTED）: 告诉 Main，由 Main 把它改名移开后再运行 I。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  grep -q "^CHECK 560 GR (guard + G record): PASS" $R/GR.txt 2>/dev/null || { print "GR 还不是 PASS（$R/GR.txt 没有 'CHECK 560 GR (guard + G record): PASS'）。先由 Main 运行 GR。没有改动任何东西。"; exit 1; }
  product_guard || { print "Worktree 守卫 STOP（见上）。没有改动任何东西。"; exit 1; }
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
  # 560: the migration follows the install in the same step, while Main is still exited and the guard held; a member
  # that started meanwhile is caught by the guard below (information) and by the migration's own lock.
  say "guard again right before the Task state migration" | tee -a $R/I.txt
  guard 2>&1 | tee -a $R/I.txt; (( ${pipestatus[1]} == 0 )) || { print "\n安装后有进程开始使用 $RT（见上），迁移没有运行。不要恢复 Main；告诉 Main（可以等它结束后单独运行: zsh $THIS Im，或回退 R）。"; exit 1; }
  if ! logged $R/I.txt do_migrate; then
    print "\nTask 状态迁移或核对失败。不要恢复 Main，立刻运行回退（两个包与迁移前的 Task 状态）:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  touch $R/I.ok
  { say "BLOCKING processes started during the install window ($INSTALL_FROM → $(date +%T)); information for Main"
    guard && print "none" || print "（上面 BLOCKING 列出的进程在安装期间启动，可能载入了新旧混合的文件；告诉 Main。）"; } 2>&1 | tee -a $R/I.txt
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|^395 layout|direct_url|built from|CHECK|503 layout|control records snapshot|timer pid|zombies|markers expected|SAME-AS-VALIDATED|plugin files|configuration --write rc|bytes unchanged|^changed|BLOCKING|-rw-------|state copy|preview rc|migrate rc|again rc|planned renames|renamed:|RESULT|backup:' $R/I.txt)"
  print "成功: Successfully installed graftling-$GVERSION graphtraj-0.1.0；PASS n FAIL 0（两个 wheel）；'CHECK 560 graftling $GOLDVERSION dist-info gone: PASS'；三个 -rw------- 备份入口文件；state copy 行；'graftling $GVERSION'；'CHECK 560 direct_url of both names the wheels-$C8 wheels: PASS'；'markers expected present: PASS (6/6)'；'503 layout: PASS'；两行 node resolves PASS；SAME-AS-VALIDATED；'CHECK 560 installed plugin changes only hooks/host_context.mjs: PASS'；'CHECK 515 .mcp.json …: PASS'；"
  print "  'CHECK 560 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS'；两行 'CHECK 560 Codex hooks entry …: PASS'；迁移: preview/migrate/again rc=0，'CHECK 560 563 second run renames nothing: PASS'，defs563 每行 PASS 与 'RESULT: PASS'，'CHECK 560 563 migration: … hash-equal: PASS'，'CHECK 560 backup state copy equals the state just before the migration: PASS'。"
  print "$R_HINT"
  print "\n下一步（USER，普通 Terminal）恢复 Main（同一个 Session）:\n  cd $H && claude --continue"
  print "预期对话框: $(cat $R/V-dialog.txt 2>/dev/null || print 'see V')。.mcp.json 不变，仍只有 \"$NEWS\"。插件/hooks 信任框（graphtraj-claude-host）出现时选信任（trust）；其它任何框: Esc 并告诉 Main 标题。判断: Main 恢复为原来的对话，然后由 Main 运行 M。"
  print "若 --continue 打开的不是原来的对话: /exit，然后 cd $H && claude --resume $MAIN"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cv; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main（用 claude --continue 恢复的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。对话框: 无。Main 把原始结果存到 $R/M-<字母>.txt。

[a 重启后通知正常、不重复；工具在] 恢复后第一句（粘贴）:
Production was just upgraded by Task 560 (GraphTraj $C8 with graftling $GVERSION; Task definitions migrated) and this Session was restarted. Before anything else, using no tools: (1) list every GraphTraj/Graftling notice delivered to you since this resume (alias, event, execution if shown in the title, first line), and for each say whether you had already seen that same notice before this resume; (2) state whether your tool list has mcp__graphtraj__agents and mcp__graphtraj__tasks (list every tool whose name starts with mcp__graphtraj__ or mcp__agents__ exactly).
  成功: (1) 没有重启前已见过的通知再出现（Main 退出期间结束的其它 Task（$(active_tasks)）成员的通知可能到达一次，不能重复）；(2) 有 mcp__graphtraj__agents 与 mcp__graphtraj__tasks，没有 mcp__agents__*。

[b 工具可用] 粘贴:
Using only mcp__graphtraj__tasks: discover. Print the raw list of feature names, and nothing else. Then using only mcp__graphtraj__agents: status with no agent. Print the raw result. Then using only mcp__graphtraj__tasks: execute task_graph with arguments {"view":"summary"} and print only the number of Tasks and whether any error was returned; then execute task_graph with Task $TASK_ID in details and print only its current definition path.
  成功: discover 有功能列表；status 有结果；task_graph 无错误（迁移后的状态可读），Task $TASK_ID 的当前定义路径为 definitions/<时间>.md（563 迁移后 task.md 已不存在）。

[c] Main 的 Bash（无对话框）: zsh $THIS Mp   然后   zsh $THIS Mps   然后   zsh $THIS inbox（每个文件 duplicate ids: 0）
EOF2
  next "zsh $THIS Mp" ;;

Mp) cv; print "[Mp] Main，M 之后。Harness 里一次有时限（120 秒）的 claude -p 单行探测，看 init 记录的 MCP 服务器与工具名。对话框: 无。不调用工具。< 2 分钟。"
  print -r -- 'Reply with exactly one line: PROBE-560-OK. Use no tools.' > $R/Mp-prompt.txt
  (cd $H && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $(claude_bin) -p --model $MODEL --output-format stream-json --verbose \
      < $R/Mp-prompt.txt > $R/Mp-stream.jsonl 2> $R/Mp.err)
  print "claude -p rc=$? (142 = 120 s timeout) | stderr lines naming untrusted/trust: $(grep -ciE 'untrust|trust' $R/Mp.err)" | tee $R/Mp.txt
  $CONDA -I $SD/rec515.py init $R/Mp-stream.jsonl 2>&1 | tee -a $R/Mp.txt; rc=${pipestatus[1]}
  grep -ciE 'untrust' $R/Mp.err > /dev/null && { print "CHECK 515 Mp stderr has no untrusted-plugin warning: FAIL" | tee -a $R/Mp.txt; rc=1; }
  summary Mp "$(grep -E '^(claude|CHECK|init)' $R/Mp.txt)"
  print "成功: 四行 'CHECK 515 init …: PASS'（mcp server graphtraj only；两个工具名；没有 mcp__agents__*；没有 untrusted-plugin 警告）。FAIL 交 Main。"
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
  ($CONDA -I $SD/cpu468.py sample $H $R $TASK_ID ${ADOPT560_NW468_SECONDS:-900} advisor < /dev/null >> $R/Nw468.txt 2>&1 &!)
  print "started at $(date +%T) in the background ($R/Nw468.txt; ends by itself when the Worker ends or after 15 min: '== END 468 sampler')."
  next "zsh $THIS N" ;;

N) print "[N] Main. $(cv)"; print -r -- $CHILD > $R/N-child-name; cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. 一次真实派发：成员创建 agents 子级 $CHILD，等待、读取、清退（通知一次；Worker 在创建前后 30 秒的 CPU 只报告）。先确认 Nw 已启动（tail -n 2 $R/Nw468.txt 有 '468 sampler'），再在 Claude Main 里粘贴这一条。对话框: 无。约 3-5 分钟。
Using only mcp__graphtraj__tasks: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"This is a production check. Do NOT call submit_result or submit_report. (a) Using the agents tool (mcp__graphtraj__agents), create ONE claude child named $CHILD with configuration opus_coding_team.advisor and this message: <<This is a scripted probe. Call Bash once with exactly: echo $CHILD-tool && sleep 20 ; then reply with exactly: DONE-532>>. Quote the raw create result (agent id, session, execution id). If the child asks you to approve a Bash command, approve exactly that command. (b) Call agents wait on that agent id with timeout_seconds 300, repeating until the execution has ended; quote the final wait result's last_message. Then call agents status with arguments {agent: <agent id>} and quote its configuration, model and last_message. (c) Retire the child by its agent id and quote the raw result. End your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main 把 swarm 原始结果存为 $R/N.txt（必须含 "agent"）；Main 收到的这个成员的每一条通知原文（每条一行，通知头与正文同一行，以 '[Graftling notice from <成员 alias> · … · execution <id>]' 开头；说明行以 '# ' 开头）存为 $R/N-main-notice.txt；成员最终回复原文存为 $R/N-reply.txt。
  成员结束（Main 收到 completed 通知）后、清退成员之前，Main 的 Bash（无对话框）: zsh $THIS Nr，然后 zsh $THIS Nt。
EOF2
  next "zsh $THIS Nr    （然后 zsh $THIS Nt）" ;;

Nr) print "[Nr] Main. 子级与成员记录、通知一次、成员的工具调用、Worker CPU 报告（只读，从不发信号）。对话框: 无。"
  cv | tee $R/Nr.txt
  nr_read 2>&1 | tee -a $R/Nr.txt; rc=${pipestatus[1]}
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1)
  { if [[ -s $R/N-main-notice.txt ]]; then
      nc=$(notice_count $R/N-main-notice.txt "$MEMBER")
      print "CHECK 560 Main got exactly one completed notice of the member: $( (( nc == 1 )) && print PASS || print FAIL) ($nc notice lines of shape '[Graftling notice from ${MEMBER:-<member>} · completed · execution <id>]' in $R/N-main-notice.txt)"
    else print "CHECK 560 Main got exactly one completed notice of the member: PENDING (save every notice of the member to $R/N-main-notice.txt)"; fi
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
    $CONDA -I $SD/rec515.py calls "member $MEMBER" --need agents ${(u)mf} 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  else print "CHECK 515 [member] mcp__graphtraj__agents called and answered without error or refusal: NOT OBSERVED (member alias not found)" | tee -a $R/Nr.txt; rc=1; fi
  SWARM_AGENT=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
  print "CHECK swarm result has agent: $([[ -n $SWARM_AGENT ]] && print "PASS ($SWARM_AGENT)" || print "FAIL (no \"agent\" in $R/N.txt, or the file is missing)")" | tee -a $R/Nr.txt
  grep -q '^CHECK.*: FAIL' $R/Nr.txt && rc=1
  summary Nr "$(grep -E '^claude:|^child|CHECK|REPORT|BLOCKED|^member|member end|archive|stored selection|Worker pid' $R/Nr.txt)"
  print "成功: 每一行 CHECK 都是 PASS（455 两行、一个子级 execution、452 子级 completed 与成员结束、通知 delivered、477 没有推送输入、'CHECK 560 Main got exactly one completed notice'、成员 mcp__graphtraj__agents 调用无错误、swarm 有 agent）。"
  print "  REPORT 行（Worker CPU 两行 'REPORT 525 468 Worker CPU 30 s before/after child creation' 与 'REPORT 532 Worker CPU comparison'（对照 528 的 0.559/0.107 与 531 的 0.488 -> 0.116）；'REPORT 532 526 .gitignore …' 只是信息）是报告，不阻塞；NOT OBSERVED 时把 $R/Nw468.txt 交 Main。PENDING: 子级还在运行或通知尚未保存，稍后重跑 Nr。CHECK BY HAND 用下面的 session_read。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session_id\":\"$SID\",\"limit\":400} (page with after until has_more is false). Count, per $CHILD execution id printed by Nr, the user/message events that deliver a parent input with source graphtraj naming it; print the counts by event type and each such input's execution field only."
  if [[ -n $SWARM_AGENT ]]; then print "\n清退成员（Main 粘贴，Nr 与 Nt 之后）:\nUsing only the agents tool: retire with {\"agent\":\"$SWARM_AGENT\"} (the agent value of the N swarm result, not the alias), and print the raw result."
  else print "\n清退成员: 先把 N 的 swarm 原始结果存到 $R/N.txt 再重跑 Nr。"; fi
  next "zsh $THIS Nt    （清退成员后再跑一次 Nt），然后 zsh $THIS done"; exit $rc ;;

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

T) cv; print "[T] Main，在 Leader 接受 560（状态变为 awaiting-integration）之后。490：本 Task 的 Session 中由新版启动的计时器全部消失，Task 结束后没有预算通知（只读，从不发信号）。对话框: 无。< 30 秒。"
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
    print -r -- "graftling $GOLDVERSION dist-info left: $(print -l $S/graftling-$GOLDVERSION.dist-info(N) | wc -l | tr -d ' ') (expect 0)"
    print -r -- "Task state now: task.md $(print -l $STATE/tasks/*/task.md(N) | wc -l | tr -d ' ') (expect 0 after 563) | Tasks $(print -l $STATE/tasks/[^.]*(N/) | wc -l | tr -d ' ')"
    (cd ${TMPDIR:-/tmp} && clean $RT/bin/python -I $SD/mcp560.py production-graphtraj-mcp $VPROJECT $RT/bin/graphtraj-mcp); codex_hook_check $RT
    $CONDA -I $SD/markers.py $S present | tail -1
    $RT/bin/python -I $SD/onegraft.py $RT $GVERSION | grep -E '^CHECK|layout:'
    node_resolve $RT
    shasum -a 256 $ENTRIES; tree versions $SESS
    mcp_keys $H/.mcp.json; settings_view $H/.claude/settings.local.json
    print "GR/Mp/Nr: $(grep -hE '^CHECK 5' $R/GR.txt $R/Mp.txt $R/Nr.txt 2>/dev/null | sed -E 's/^CHECK 5[0-9]+ //; s/:? (PASS|FAIL|PENDING|NOT OBSERVED).*/ \1/' | tr '\n' ';')"
    grep -hE '^CHECK 560' $R/I.txt 2>/dev/null | sort -u
    grep -hE '^REPORT (525 468|532)' $R/Nr.txt 2>/dev/null
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|CHECK|direct_url|dist-info left|Task state now|markers expected|layout:|mcp.json servers|enabledMcpjsonServers|^GR/Mp|^REPORT|archives=|containing an exported key' $R/done.txt)"
  print "成功: PASS n FAIL 0（两个 wheel）；Version 0.1.0 与 $GVERSION；两个 direct_url 指向 wheels-$C8；'graftling $GOLDVERSION dist-info left: 0'；'Task state now: task.md 0'；markers expected present: PASS (6/6)；'503 layout: PASS' 与两行 node resolves PASS；MCP tools/list 与两行 Codex hooks CHECK 为 PASS；'CHECK 515 .mcp.json …: PASS'；I 的 CHECK 560 都是 PASS；GR/Mp/Nr 的 CHECK 都是 PASS；raw files containing an exported key value: 0。把 $R 的路径交给 Main。$R_HINT"
  print "\nLeader 接受 560 之后（Main，按集成流程）: 把本 Task 的分支 $(git -C $WT rev-parse --abbrev-ref HEAD)（产品 = $C8）集成进 GraphTraj dev，同时按 engineer.md 替换 AGENTS.md 第 122-124 行；然后运行 T。"
  next "（Leader 接受 560 并集成之后，Main）zsh $THIS T" ;;

Im) need_main; print "[Im] USER（只在 I 安装后因有进程开始而没有迁移时）。等待成员结束后只运行 563 迁移与核对。对话框: 无。Main 必须仍已退出。"; cv
  [[ -e $BK/INSTALL-STARTED && -e $BK/state/links.tsv ]] || { print "没有 I 的安装或迁移前副本：先运行 I。"; exit 1; }
  wait_idle "安装已完成，迁移还没有运行。" || exit 1
  logged $R/I.txt do_migrate || { print "\n迁移或核对失败。不要恢复 Main，运行回退: zsh $BK/tools/steps.zsh R"; exit 1; }
  touch $R/I.ok; next "USER: cd $H && claude --continue   然后 Main: zsh $THIS M" ;;

R) need_main; print "[R] USER. 回退到安装前：venv 整体（graphtraj ${OLD[1,8]} 与 graftling $GOLDVERSION）、.mcp.json、settings.local.json、插件，以及 563 迁移前的 Task 状态（I 的副本），都从 $BK 恢复；当前文件移到 $BK/after-install-*。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; cv; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  wait_idle "还没有回退任何东西。" || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK|graphtraj package|before R|Tasks created after|task.md files' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过；'CHECK 560 graftling restored …: PASS' 与 'CHECK 560 graphtraj restored …: PASS'；Version graphtraj 0.1.0 与 graftling $GOLDVERSION；'CHECK 560 Task state after R equals the pre-migration copy …: PASS'；'Tasks created after I …: none'（否则告诉 Main）。"
    print "然后（USER）: cd $H && claude --continue （插件回到旧的 host_context.mjs，可能再出现一次插件/hooks 信任框：选信任；其它框选拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
