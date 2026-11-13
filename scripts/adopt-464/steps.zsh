#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 464 — production adoption of dev b3d522ad (449-459 integrated; not 460-463) into .venv-runtime;
# the production check of 459's normal end (no tool process of the child left), 455, 452 and 449/451.
# Taken from scripts/adopt-458/steps.zsh. Production holds 458's 4e3aafce. Same package names and versions
# (graphtraj 0.1.0, graftling 0.5.0), so every install claim is file by file (proddiff.py) against the new wheels.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V → S (background; Main queues it) → Vc (→ Vu USER once if asked) → [USER /exit Main]
#        → I (USER, waits for idle members, e.g. Tasks 460-463's) → [USER: claude --continue] → M → Mps → inbox
#        → Nw (background, read only) → N → Nr
#        → S2 (after S's '== DONE') → done.     Rollback after the backup: R (USER).
# Each step prints who runs it, its dialog (at most one) and how to judge success, then the next command.
# Main's Bash cannot run a foreground sleep: every Main step ends in < 10 min or starts itself in the
# background (S, Nw), and is polled by reading a file. Only I and R (USER's Terminal) wait in a loop.
# No step signals a process it did not start.
# Only rehearse.zsh sets ADOPT464_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT464_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT464_BASE:-$HOME/graphtraj-adoption-464}
RT=${ADOPT464_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT464_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT464_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/464-production-adoption-457-459}
TARGET=b3d522ad6f1a90c33dad19f81babc9c1d587d24f
OLD=4e3aafce010c1bc88353d502714cea5bb5c874bd   # production now: 458's wheels
TASK=464-production-adoption-457-459
TASK_ID=464
CHILD=n464
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw
N=$W/wheels
BK=$BASE/backup
VV=$BASE/vvenv
SV=$BASE/svenv
VP=$W/vplug/graphtraj-claude-host
VE=$W/ventries
VPROJECT=$BASE/vproject
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml $H/.codex/config.toml(N) $H/.codex/hooks.json(N))
INBOX=$H/.graphtraj/core/runner/main-sessions/inbox
PROJECTS=${ADOPT464_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT464_STUB:-} ]] && path=($ADOPT464_STUB $path)   # rehearsal only: stub hosts first
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
wheel_of() { local f=($N/$1-*.whl(N)); print -r -- ${f[1]:-}; }
summary() { print -- "\n----- 复制给 Main 的摘要（$1）-----"; shift; print -l -- "$@"; print -- "-----"; }
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
    *"$HOSTCFG"*) print "Main's Claude host" ;;
    *" serve "*|*" serve") print "a host (member's or other project)" ;;
    *) print "other" ;;
  esac
}
guard() {
  local listing rc line words hits=() timers=() marked
  listing=$(ps -axww -o pid=,etime=,command= 2>&1); rc=$?
  if (( rc != 0 )) || [[ -z $listing ]]; then
    print "无法列出进程（ps rc=$rc: ${listing[1,120]}），拒绝继续。在普通 Terminal 里运行本步。"; return 2
  fi
  for line in ${(f)listing}; do
    words=(${=line})
    [[ ${words[1]} == $$ ]] && continue
    if [[ $line == *"-m graphtraj.execution.budget_idle_timer"* ]]; then timers+=("${line[1,200]}"); continue; fi
    if [[ $line == *"$RT/"* || $line == *"$HOSTCFG"* || ( -n $MAIN && $line == *"$MAIN"* ) ]]; then
      hits+=("[$(kind_of $line)] ${line[1,200]}")
    fi
  done
  if (( ${#timers} )); then
    print "guard: ${#timers} 个 445 预算空闲计时器（NON-BLOCKING，不是成员；安装后醒来时载入新的 runner_control 并照常送达，见 README 3(a)）:"
    print -l -- "  "$timers
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
    print "$(date +%T) 正在等待：Task 460、461、462、463（或其它 Task）的成员还在运行（上面列出的 BLOCKING 进程）。不要结束（kill）这些进程；它们结束后本步自动继续。"
    print "         Waiting for Task 460, 461, 462, 463 (or other Task) members listed above. Do not kill them; this step continues by itself."
    print "         Ctrl-C 可以安全放弃：$1"
    sleep ${ADOPT464_WAIT:-20}
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
  say "Claude answers one line from the empty $BASE/scratch (expect model $MODEL, logged in)"
  print "claude: $C ($($C --version 2>&1))"
  (cd $BASE/scratch && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose \
      <<< 'In one line: name the model you are running as, and confirm you are logged in. Use no tool.' > $R/00-model.jsonl 2> $R/00-model.err)
  print "claude -p rc=$? (142 = 120 s timeout)"
  $CONDA -I -c 'import json,sys
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "result": print("answer:", str(d.get("result"))[:200], "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))' $R/00-model.jsonl
  say "production versions (expect graphtraj 0.1.0 and graftling 0.5.0; pip check clean)"
  $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  $RT/bin/python -m pip check --disable-pip-version-check; print "pip check rc=$?"
  say "plugin files and hashes"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  grep -n '^const PLUGIN' $PDIR/hooks/host_context.mjs | sed 's/^/production copy: /'
  say "entry files (hashes; .mcp.json agents entry)"; shasum -a 256 $ENTRIES; tree mcp $H/.mcp.json
  say "backup must be absent; 393/417/448/453/458 backups are listed, never touched (458's is kept until 464 is accepted)"; ls -d $BK 2>&1; ls -d $HOME/graphtraj-adoption-{393,417,448,453,458}/backup 2>&1
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "production holds 458's 4e3aafce: the 464 markers (457, 459) must be absent now"; $CONDA -I $SD/markers.py $(site) absent | tail -1
  say "running Task members (460-463 may be running; I waits for them)"; (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | tee $R/00-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/00-members.txt) (460-463 or other members may run now; I waits for them)"
  say "Task 460-464 members (information)"; grep -E '(^|[^0-9])46[0-4]([^0-9]|$)' $R/00-members.txt || print "none listed"
  say "N needs role opus_coding_team.advisor for Task $TASK_ID: the role and the role_tree lines naming it (453 and 458 dispatched it)"
  grep -nE 'opus_coding_team|advisor' $H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) 2>&1 | grep -iE 'advisor' | head -12
  say "Task $TASK_ID ready for N's root dispatch: Team 1 active, budget not stopped"
  grep -E '^(stopped|corrections|allowance_minutes):' $H/.graphtraj/core/state/tasks/$TASK/execution-budget.yml
  grep -E 'status|state' $H/.graphtraj/core/state/tasks/$TASK/teams/1/team.yml | head -5
  say "current Claude Main Session"; local id=$(detect_main)
  if [[ -n $id ]]; then print -r -- $id > $BASE/main.session; MAIN=$id; print "MAIN=$id (saved to $BASE/main.session)"; else print "MAIN NOT FOUND"; fi
  say "processes using the venv now, classified (information only; Main's host is expected here)"; guard
}

step_B() {
  rm -rf $W/src $N; mkdir -p $W/src $N
  git -C $WT archive $TARGET | tar -x -C $W/src || return 1
  local BP=$RT/bin/python
  $BP -c 'import setuptools, wheel' 2>/dev/null || { BP=$CONDA; print "生产 venv 没有 setuptools/wheel，用 $BP 构建（不修改 Conda）"; }
  say "build with $BP (--no-index --no-deps --no-build-isolation)"
  $BP -m pip wheel --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $W/src $W/src/src/graftling || return 1
  say "wheels and sha256 (expect graphtraj-0.1.0 and graftling-0.5.0)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT
  [[ $(wheel_of graphtraj) == *graphtraj-0.1.0-* && $(wheel_of graftling) == *graftling-0.5.0-* ]] || { print "wheel 名称不符"; return 1; }
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
  rm -rf $W/vplug; mkdir -p $W/vplug; cp -Rp $PDIR $W/vplug/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name differs=0; : > $R/V-plugin.diff
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; differs=1; diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  say "source diff 4e3aafce..$TARGET of the plugin and hook sources (expect empty)"
  git -C $WT diff --stat $OLD $TARGET -- src/graftling/claude/host_context.mjs src/graftling/claude-plugin plugins '*.mjs' '*hooks*' 2>&1 | tee $R/V-source.diff
  [[ -s $R/V-source.diff ]] && print "source diff: NOT EMPTY (see $R/V-source.diff)" || print "source diff: empty"
  if (( differs )); then print "STOP: plugin bytes change ($R/V-plugin.diff, $(grep -c '^[<>]' $R/V-plugin.diff) lines); 464 predicted none. Main decides before I."; rc=1
  else print "plugin unchanged: no plugin/hooks trust dialog is expected at resume."; fi
  say "local form kept: 'const PLUGIN = null'"
  grep -n '^const PLUGIN' $VP/hooks/host_context.mjs | sed 's/^/candidate: /'
  grep -q '^const PLUGIN = null;' $VP/hooks/host_context.mjs || { print "STOP: candidate is not the local-copy form"; rc=1; }
  say "464 markers (457, 459 and 459's correction b3d522ad): present in the candidate, absent in production"
  local VS=($VV/lib/python*/site-packages(N))
  $CONDA -I $SD/markers.py $VS[1] present || rc=1
  $CONDA -I $SD/markers.py $(site) absent || rc=1
  say "claude plugin validate: baseline, candidate"; print "claude: $C ($($C --version))"
  local base=$($C plugin validate $PDIR 2>&1 | tee -a $R/V-validate.txt | grep -c '✘') cand=$($C plugin validate $VP 2>&1 | tee -a $R/V-validate.txt | grep -c '✘')
  print "✘ lines: baseline=$base candidate=$cand"; (( cand > base )) && rc=1
  say "entry files: what configuration --write would change; predictions only"
  rm -rf $VE; $P -I $SD/adopt_plugin.py entries $H $C $RT/bin/python $VE || rc=1
  say "read only against the real project: archives, configuration, roles; Task graph on an APFS clone of state"
  touch $W/V-marker; [[ -e $BASE/vstate ]] && chmod -R u+w $BASE/vstate && rm -rf $BASE/vstate; mkdir -p $BASE/vstate
  local part; for part in tasks worldline; do [[ -d $H/.graphtraj/core/state/$part ]] && cp -cRp $H/.graphtraj/core/state/$part $BASE/vstate/; done
  $P -I $SD/adopt_plugin.py readcheck $H $BASE/vstate || rc=1
  chmod -R u+w $BASE/vstate; rm -rf $BASE/vstate
  say "recorded hashes (I checks these did not change before it writes)"; shasum -a 256 $ENTRIES | tee $W/entries.sha256
  return $rc
}

# S: full suite of TARGET from this Worktree (editable install), 450's method, in the background. Main runs it and
# queues suites: S refuses while another run_test_shards runs (a 460-463 suite may need the host).
# Venv as scripts/verify-450/steps.zsh: Conda python3.13 --system-site-packages, editable graftling and graphtraj,
# then production's click, yaml/_yaml/pyyaml and websockets COPIED into its site-packages (they shadow Conda's).
# Baseline: 459 at 81fc829e (verify-459 03): 2 failed, 4024 passed, 69 skipped. Both are rerun alone always.
# For comparison: 458's suite at 4e3aafce: 0 failed, 4011 passed, 71 skipped.
BASELINE_FAILS=(
  'tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations[waiting]'
  tests/test_claude_runner.py::test_second_child_batch_starts_while_first_batch_is_running
)
# The suite's pytest temporary root (under the TMPDIR clean() passes) and its newest pytest-<n> before the run.
pytest_root() { clean $CONDA -I -c 'import tempfile; print(tempfile.gettempdir())'; }
basetemp_max() { local d=($(pytest_root)/pytest-of-${USER:-luoxiao}/pytest-<->(N/)); print ${${(n)${d##*/pytest-}}[-1]:-0}; }
step_S() {
  git -C $WT diff --quiet $TARGET HEAD -- src tests pyproject.toml || { print "STOP: $WT HEAD differs from $TARGET in src/tests/pyproject.toml"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests pyproject.toml) ]] || { print "STOP: uncommitted changes in $WT src/tests/pyproject.toml"; return 1; }
  print "Worktree HEAD $(git -C $WT rev-parse --short HEAD): src, tests, pyproject.toml equal $TARGET and clean"
  say "quiet host: load and other test runs"
  print "loadavg: $(sysctl -n vm.loadavg 2>/dev/null)"
  local others=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -E 'pytest|run_test_shards' | grep -vE 'grep|steps.zsh')
  print -r -- "other pytest / run_test_shards processes: ${others:-none}"
  if [[ $others == *run_test_shards* ]]; then
    print "STOP: another run_test_shards is running (for example a 460-463 suite); the host is not quiet. Main queues S and reruns it later."; return 1
  fi
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  local S=$(site) D=($SV/lib/python*/site-packages(N)); D=${D[1]}
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml(N) $S/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/ || return 1
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj, click, yaml, websockets, pytest; from importlib.metadata import version; print("click", version("click"), "(expect 8.5.0) | graphtraj.__file__ =", graphtraj.__file__)') | tee $R/S-setup-imports.txt || return 1
  grep -qF "graphtraj.__file__ = $WT/" $R/S-setup-imports.txt || { print "STOP: graphtraj is not imported from $WT"; return 1; }
  # 447 guard: an inner venv built the way tests/conftest.py builds one must import websockets.
  rm -rf $BASE/sprobe; $SV/bin/python -m venv --system-site-packages $BASE/sprobe || return 1
  local PD=($BASE/sprobe/lib/python*/site-packages(N)); print -r -- $D > $PD[1]/graphtraj_test_dependencies.pth
  $BASE/sprobe/bin/python -I -c 'import websockets; print("inner-style venv: websockets", websockets.__version__)' || { print "GUARD: inner-style venv cannot import websockets"; return 1; }
  print "pytest temporary root: $(pytest_root)/pytest-of-${USER:-luoxiao} (newest before the run: pytest-$(basetemp_max))"
  basetemp_max > $W/S-basetemp-before
  rm -rf $R/S-shards; : > $R/S-suite.txt
  (cd $WT && nohup zsh $THIS _Srun >> $R/S-suite.txt 2>&1 &)
  print "started at $(date +%T) in the background (~20-30 min)."
}

step__Srun() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) (product files = $TARGET) loadavg $(sysctl -n vm.loadavg 2>/dev/null)"
  (cd $WT && clean $SV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/S-shards); print "== shards exit $?"
  local last=$(grep -E '^[0-9]+ (failed|errors|passed)' $R/S-suite.txt | tail -1)
  print "== totals: $last"
  print "== baseline 459 81fc829e: 2 failed, 4024 passed, 69 skipped"
  print "== for comparison 458 4e3aafce: 0 failed, 4011 passed, 71 skipped"
  print "== 454 line from run_test_shards: $(grep -E '^leftover processes of run' $R/S-suite.txt | tail -1)"
  print "== failures (BASELINE = also failed in 459's suite; NEW = not):"
  local id ids=(${(f)"$(sed -n 's/^FAILED //p; s/^ERROR //p' $R/S-shards/failures.txt 2>/dev/null | sed 's/ - .*//' | sort -u)"})
  for id in $ids; do (( ${BASELINE_FAILS[(Ie)$id]} )) && print "BASELINE $id" || print "NEW $id"; done
  (( ${#ids} )) || print "(none)"
  print "== each failure alone (-rA), and each 459 baseline failure alone even if it passed in the suite:"
  local all=(${(u)ids} $BASELINE_FAILS); all=(${(u)all})
  for id in $all; do
    local out=$(cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q -rA "$id" 2>&1)
    local verdict=$(print -r -- "$out" | grep -oE '^(PASSED|FAILED|SKIPPED|ERROR)' | head -1)
    local insuite=$( (( ${ids[(Ie)$id]} )) && print "failed in the suite" || print "passed in the suite")
    print "${verdict:-UNKNOWN} alone: $id ($insuite)"; print -r -- "$out" | grep -E '^(PASSED|FAILED|SKIPPED|ERROR)|passed|failed|skipped' | tail -2 | sed 's/^/    /'
  done
  print "== DONE $(date +%T)   (next, Main: zsh $THIS S2)"
}

# S2 (Main, after '== DONE'): 454's leftover count. Processes whose argv or environment (ps -E) names the suite
# venv, one of the suite's pytest-<n> base temporary directories, or this run's PYTEST_GRAPHTRAJ_RUN value.
# Listed and counted only; never signalled.
step_S2() {
  grep -q '^== DONE' $R/S-suite.txt 2>/dev/null || { print "S has not printed '== DONE' yet: tail -n 25 $R/S-suite.txt"; return 1; }
  local before=$(<$W/S-basetemp-before) root="$(pytest_root)/pytest-of-${USER:-luoxiao}" run n pats=() listing line hits=()
  run=$(sed -n 's/^test run id: \([0-9a-f]*\).*/\1/p' $R/S-suite.txt | head -1)
  pats=("$SV/" "$SV " "PYTEST_GRAPHTRAJ_RUN=${run:-none}-")
  for n in {$(( before + 1 ))..$(basetemp_max)}; do (( n > before )) && pats+=("$root/pytest-$n/"); done
  print "run id: ${run:-not found}; suite base temporary directories: pytest-$(( before + 1 )) .. pytest-$(basetemp_max) under $root"
  print -l -- "patterns:" "  "$pats
  listing=$(ps -E -axww -o pid=,ppid=,etime=,command= 2>&1) || { print "ps -E failed: ${listing[1,120]}; run S2 in a normal Terminal"; return 1; }
  for line in ${(f)listing}; do
    [[ ${${=line}[1]} == $$ ]] && continue
    for n in $pats; do [[ $line == *"$n"* ]] && { hits+=("${line[1,220]}"); break; }; done
  done
  print "leftover processes of the suite (never signalled): ${#hits}"
  (( ${#hits} )) && print -l -- "  "$hits
  return 0
}

vc_setup() {
  local G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 464 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=464 -c user.email=464@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $G setup) || return 1
  fi
  # Always regenerate: the scratch plugin and entries come from the new wheels.
  (cd $VPROJECT && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $(claude_bin) --write) || return 1
}

vc_stream() {
  local C=$(claude_bin)
  say "claude -p calls tasks discover and agents status (no dialog)"
  print -r -- 'Call mcp__agents__tasks once with {"action":"discover"} and mcp__agents__agents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && clean $C -p --model $MODEL --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) > $R/Vc-stream.jsonl
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
  tree stream $R/Vc-stream.jsonl mcp__agents__tasks mcp__agents__agents || return 1
  say "host.log tail"; tail -n 20 $VPROJECT/.graphtraj/claude-host/host.log
}

do_backup() {
  mkdir -p $BK && chmod 700 $BK || return 1
  date '+backup start %F %T'
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/proddiff.py $SD/adopt_tree.py $SD/adopt_plugin.py $SD/markers.py $SD/nr459.py $SD/watch459.py $BK/tools/ || return 1
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
  say "entry files still as V saw them (expect 3 x OK)"; shasum -a 256 -c $W/entries.sha256 || { print "入口文件在 V 之后被改过；重新运行 V。"; return 1; }
  say "install both wheels over the same versions (--force-reinstall)"
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
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graftling.control as c, graftling.tool_descendants as td, graftling.claude.execution as ce; print("graftling", graftling.__version__); print(h.__file__); print("457", c._stop_escaped.__name__, "| 459 SAMPLE_SECONDS", td.SAMPLE_SECONDS, td.DescendantSampler.__name__, "| 459 correction", td.shown_command.__name__); assert graftling.__version__ == "0.5.0"' || return 1
  say "464 markers in the installed site-packages (expect PASS 11/11)"; $CONDA -I $SD/markers.py $S present || return 1
  say "plugin regenerated by the installed code, plugin files only"; $P -I $SD/adopt_plugin.py regen $H $(claude_bin) $PDIR || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  diff -r $BK/plugin $PDIR > /dev/null && print "plugin bytes as before the install: no trust dialog expected" || print "plugin bytes CHANGED from before the install: one plugin/hooks trust dialog may appear at resume"
  say "entry files: write what V predicted, before -> after"
  $P -I $SD/adopt_plugin.py apply $H $VE || return 1
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
  say "archives: same graftling 0.5.0 before and after, so they stay; versions (information)"; tree versions $SESS
  say "a stale channel file would make the restored host refuse with host-busy"
  local CH=$H/.graphtraj/claude-host/live/channel.json
  if [[ -e $CH ]]; then mv $CH $KEEP/channel.json; print "moved out: $CH"; else print "no channel file"; fi
  say "versions and pip check"; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'; $RT/bin/python -m pip check --disable-pip-version-check || rc=1
  return $rc
}

# Nr: the production check of criterion 3, read only.
#   child record: <swarm>/control/agents/<agent>.json (graftling/control.py), name n464, parent = member alias;
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
check('two child executions (create, send)', len(exs) == 2, f'{len(exs)}')
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
files = [sess / str(sid) / 'session.jsonl'] if sid else []
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
        inputs = [e for e in events if e.get('type') == 'user/message' and eid in json.dumps(e) and 'graphtraj' in json.dumps(e)]
        print(f"  archive {f.parent.name}: execution {eid}: events naming it by type {by_type}; user/message inputs naming it with graphtraj: {len(inputs)}")
        check(f"449/451 one parent input for execution {eid}", 'PASS' if len(inputs) == 1 else
              f"CHECK BY HAND (count {len(inputs)}; Main counts user/message notice deliveries per execution with session_read, as 453 did)")
if not files: print('  archive: NOT FOUND (member Session archive)'); check('449/451 one parent input per execution', 'CHECK BY HAND (archive not found)')
print('MEMBER', alias or '')
print('SESSION', sid or '')
print('CHILD', child.get('agent') or '')
PY2
}

R_HINT="回退（USER，先在 Main 里 /exit）: zsh $BK/tools/steps.zsh R"

case $STEP in
help) print "顺序: 00 → B → V → S（后台，Main 排队）→ Vc（必要时 Vu）→ /exit Main → I（USER，等待成员结束）→ claude --continue → M → Mps → inbox → Nw（后台，只读）→ N → Nr → S2（S 完成后）→ done；备份完成后可回退: R。"
  next "zsh $THIS 00" ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE/scratch、$BASE/main.session 与 $R。约 2 分钟。"
  logged $R/00.txt step_00
  summary 00 "$(grep -E 'ZSH_VERSION|Node spawn|inherited|answer:|^Version|pip check rc|production copy|markers expected|running lines|^stopped|status|MAIN=|MAIN NOT|volume ids|^guard|advisor' $R/00.txt)"
  print "成功: ZSH_VERSION 有值；answer 里 models 含 $MODEL 且 is_error False；graphtraj 0.1.0 与 graftling 0.5.0；pip check rc=0；'markers expected absent: PASS (11/11)'（生产仍是 4e3aafce）；"
  print "  stopped: false 且 Team 1 active；roles 里有 opus_coding_team 的 advisor；$BK 'No such file'（393/417/448/453/458 的备份只列出，不动）；MAIN=<id>。"
  print "running lines 可以不为 0（例如 Task 460、461、462、463 的成员）；I 会等它们结束，不结束它们，不需要现在处理。guard 的 NON-BLOCKING 计时器不影响安装。"
  print "若 'inherited:' 列出名字：本脚本已对所有子命令 unset；记下它来自哪个项目（418 提醒）。"
  print "若 answer 有 login/API key 字样: USER 在 Terminal 运行 claude 登录后重跑 00。若 MAIN NOT FOUND 或 ps 被拒: 由 USER 在普通 Terminal 运行 00。"
  next "zsh $THIS B" ;;

B) print "[B] Main. 从 git archive $TARGET 构建两个 wheel（不联网、不改 Conda 和生产）。对话框: 无。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked' $R/B.txt)"; print "成功: graphtraj-0.1.0 与 graftling-0.5.0 各一个 wheel 及 sha256；leaked: 0。"
    next "zsh $THIS V"
  else print "\nB 失败。不要联网安装，把 $R/B.txt 交给 Main。"; exit 1; fi ;;

V) print "[V] Main. 安装前校验。对话框: 无。只读真实项目；scratch venv、候选插件、入口文件预测都在生产之外。"
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|source diff|plugin unchanged|markers expected|STOP|✘ lines|    |read_session|loaded|task graph' $R/V.txt)"
    print "成功: SAME ×3 与 'plugin unchanged: no plugin/hooks trust dialog is expected'；'source diff: empty'；'markers expected present: PASS (11/11)' 与 'markers expected absent: PASS (11/11)'；"
    print "  候选 ✘ 不多于 baseline；无 STOP；入口文件 SAME 或只列出可解释的变化；read_session failures=0。"
    next "zsh $THIS S"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

S) print "[S] Main. TARGET 的全套测试（从本 Worktree 导入，6 个 shard，--timeout 1500，后台）。对话框: 无。立即返回。另一个 run_test_shards（例如 460-463 的）在运行时拒绝；Main 排队，一次只跑一个，之后重跑。"
  if logged $R/S-setup.txt step_S; then
    print "状态（Main 随时）:  tail -n 25 $R/S-suite.txt"
    print "完成标志: '== DONE'。成功: 没有 'NEW ' 开头的失败（基线 459 81fc829e: 2 failed、4024 passed、69 skipped；对照 458 4e3aafce: 0 failed、4011 passed、71 skipped）；"
    print "  每个失败及 459 的两项基线失败都有一行 'PASSED/FAILED/SKIPPED alone: <id> (failed|passed in the suite)'。NEW 且单独仍 FAILED 的交 Main。"
    print "  '== 454 line' 给出 run_test_shards 自己的 leftover 计数；'== DONE' 之后 Main 运行 S2 统计遗留进程。"
    print "失败的 ID: $R/S-shards/failures.txt；某 shard 'ABNORMAL' 或 'timed out': 把那一行交给 Main。S 可与 Vc 同时进行。"
    next "zsh $THIS Vc    （S 打印 '== DONE' 之后再: zsh $THIS S2）"
  else print "\nS 未启动（见上面 STOP 或 GUARD 行），把 $R/S-setup.txt 交给 Main；主机不空闲时由 Main 决定何时重跑。"; exit 1; fi ;;

S2) print "[S2] Main. S 完成后的遗留进程（454）。对话框: 无。只读，从不发信号。"
  logged $R/S2.txt step_S2 || exit 1
  summary S2 "$(grep -E '^(run id|leftover)|^== (totals|454|DONE)' $R/S2.txt $R/S-suite.txt | sed 's#^[^:]*/##')"
  print "成功: 'leftover processes of the suite (never signalled): 0'。不为 0 时把列出的进程交给 Main（不要结束它们）。"
  next "zsh $THIS done" ;;

Vc) print "[Vc] Main. 隔离项目 $VPROJECT 里用新 wheel 的真实 claude -p。对话框: 无。约 2 分钟。"
  : > $R/Vc.txt; rm -f $R/Vc.ok   # 448: a rerun's summary showed an earlier run's FAIL
  logged $R/Vc.txt vc_setup || { print "\nVc 准备失败，把 $R/Vc.txt 交给 Main。"; exit 1; }
  logged $R/Vc.txt vc_stream; rc=$?
  if [[ $(grep 'graphtraj-claude-host loaded:' $R/Vc.txt | tail -1) == *'loaded: NO'* ]]; then
    print "\n插件未加载：Claude Code 只在已信任的文件夹加载项目插件。由 USER 做一次 Vu，然后 Main 重跑 Vc。"
    next "USER: zsh $THIS Vu    （之后 Main: zsh $THIS Vc）"; exit 1
  fi
  if (( rc == 0 )); then
    touch $R/Vc.ok
    summary Vc "$(grep -E '^(PASS|FAIL)|loaded:' $R/Vc.txt | tail -4)"
    print "成功: 'graphtraj-claude-host loaded: YES'，PASS mcp__agents__tasks 与 PASS mcp__agents__agents。"
    print "\n下一步是 USER 的: 先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。I 会等 Task 460、461、462、463（或其它 Task）的成员结束（不要结束它们）。S 在后台继续，不受影响（它不用 .venv-runtime 的进程）。"
    next "USER（Main 已 /exit）: zsh $THIS I"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（一次；需要终端和对话框，Main 做不了）。在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若再问项目的 MCP server 'agents' 或插件，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

I) need_main
  print "[I] USER. 等待成员结束、备份并安装。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。安装约 3 分钟（等待时间另计）。"
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
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|^457 _stop_escaped|markers expected|SAME-AS-VALIDATED|plugin bytes|WRITTEN|UNCHANGED|bytes unchanged|^changed|BLOCKING|-rw-------' $R/I.txt)"
  print "成功: Successfully installed graftling-0.5.0 graphtraj-0.1.0；PASS n FAIL 0；三个 -rw------- 备份入口文件；'markers expected present: PASS (11/11)'；'457 _stop_escaped | 459 SAMPLE_SECONDS 1.0 DescendantSampler | 459 correction shown_command'；SAME-AS-VALIDATED；"
  print "  'plugin bytes as before the install: no trust dialog expected'；入口文件 bytes unchanged 或 V 已列出的变化。"
  print "$R_HINT"
  print "\n下一步（USER，普通 Terminal）恢复 Main（同一个 Session）:\n  cd $H && claude --continue"
  print "预期对话框: 无（插件字节没有变）。若出现任何框: 选拒绝（Esc）并告诉 Main 标题；若 I 打印 'plugin bytes CHANGED'，至多一个插件/hooks 信任框，选信任。"
  print "若 --continue 打开的不是原来的对话: /exit，然后 cd $H && claude --resume $MAIN"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cat <<EOF2 | tee $R/M-prompts.txt
[M] Main（用 claude --continue 恢复的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。对话框: 无。Main 把原始结果存到 $R/M-<字母>.txt。

[a 定义第 4 项: 安装后第一次 Main 重启，通知正常显示、不重复] 恢复后第一句:
Before anything else: list every GraphTraj/Graftling notice delivered to you since this resume (alias, event, execution if shown in the title, first line), and for each say whether you had already seen that same notice before this resume. Use no tools.
  成功: 没有安装前已见过的通知再出现。Main 退出期间结束的 Task 460、461、462、463（或其它 Task）成员的通知可能在恢复时到达一次，这是预期的；它们不能再重复。
  若有重复: 记下 alias/event/execution/次数，由 Main 登记缺陷 Task。

[b 工具与插件] 粘贴:
Using only the tasks tool: discover. Print the raw list of feature names, and nothing else.
Using only the agents tool: status with no agent. Print the raw result.
  成功: discover 有功能列表；status 有结果（/agents-context 只能由 USER 输入，可选）。

[c] Main 的 Bash（无对话框）: zsh $THIS Mps   然后   zsh $THIS inbox
EOF2
  next "zsh $THIS Mps" ;;

Mps) need_main; print "[Mps] Main. 运行中的 host 与它的父 claude。对话框: 无。只读。"
  { print "at $(date '+%F %T')"; hit=$(ps -axww -o pid=,ppid=,command= | grep -F -- "$HOSTCFG" | grep -F -- ' serve ')
    print -r -- "host: $hit"; words=(${=hit}); PPIDV=${words[2]:-}
    if [[ -n $PPIDV ]]; then C=$(ps -ww -o command= -p $PPIDV); print -r -- "parent claude: $C"
      [[ $hit == *"$RT/bin/python"* ]] && print "host uses .venv-runtime: yes" || print "host uses .venv-runtime: NO"
      if [[ $C == *claude*' --continue'* || $C == *"--resume $MAIN"* ]]; then print "parent is claude --continue or --resume $MAIN: yes"
      else print "parent is claude --continue or --resume $MAIN: NO"; fi
    else print "NOT FOUND: no host serving $HOSTCFG"; fi
    say "host.log tail"; tail -n 30 $H/.graphtraj/claude-host/host.log; print "outcome=ok lines in tail: $(tail -n 30 $H/.graphtraj/claude-host/host.log | grep -c 'outcome=ok')"
  } 2>&1 | tee -a $R/Mps.txt
  summary Mps "$(grep -E '^(host uses|parent is|NOT FOUND|outcome=ok)' $R/Mps.txt | tail -3)"
  print "成功: host uses .venv-runtime: yes；parent is claude --continue or --resume $MAIN: yes；outcome=ok lines > 0。"
  next "zsh $THIS inbox" ;;

inbox) need_main; print "[inbox] Main. Main 的通知队列。对话框: 无。只读。"
  { for f in $INBOX/*.jsonl(N); do print "== ${f:t}"; tree inbox $f; done; } 2>&1 | tee -a $R/inbox.txt
  print "Claude Main $MAIN 的文件: $(inbox_key "claude:$MAIN").jsonl"
  summary inbox "$(grep -E '^(==|duplicate|records)' $R/inbox.txt | tail -12)"
  print "成功: 每个文件 duplicate ids: 0。"
  next "zsh $THIS Nw    （然后 zsh $THIS N）" ;;

Nw) print "[Nw] Main. 在 N 之前启动：后台只读观察 $CHILD 的 459 后代记录（每 0.2 秒读一次，不写生产、不发信号）。对话框: 无。立即返回。"
  print "  原因: 459 的采样线程在工具进程结束后就把它从记录里删掉，正常结束后记录里已没有那条 Bash 命令；Nw 在子级运行时把记录的每次变化复制到 $R/Nw-snapshots.jsonl。"
  print "  它在 $CHILD 的两个 execution 都结束、子级被清退或 15 分钟后自己退出；状态: tail -n 5 $R/Nw.txt（'== END' 表示已退出）。"
  if [[ -e $R/Nw.txt ]] && ! grep -q '^.* == END' $R/Nw.txt; then print "Nw 已在运行（$R/Nw.txt 没有 '== END'）；不重复启动。"; next "zsh $THIS N"; exit 0; fi
  : > $R/Nw.txt; : > $R/Nw-snapshots.jsonl
  ($CONDA -I $SD/watch459.py $H $R $CHILD 900 < /dev/null >> $R/Nw.txt 2>&1 &!)
  print "started at $(date +%T) in the background."
  next "zsh $THIS N" ;;

N) cat <<EOF2 | tee $R/N-prompts.txt
[N] Main. 定义第 3 项（459 正常结束；455、452、449/451 的生产核对）。先确认 Nw 已启动（tail -n 3 $R/Nw.txt 有 'start: watching'），再在 Claude Main 里粘贴这一条。对话框: 无（成员只用 agents 工具；子级用一次 Bash，若它向成员请求批准，由成员批准那一条命令）。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Use only the agents tool for all of this. Do NOT call submit_result or submit_report; this check needs only your final reply. (1) Create ONE claude child named $CHILD with configuration opus_coding_team.advisor (a preset role is required) and instruction 'Use the Bash tool once to run exactly: echo n464-tool && sleep 3 . Then reply DONE-464.' Quote the raw create result and note the agent id and the execution id it returned. If the child asks you to approve that one Bash command, approve exactly that command once and nothing else. (2) Use the agents wait on that agent id until that execution has ended. (3) Send to the same child by its agent id: 'Reply with exactly one line: PONG-464-2. Use no tools.' Note the execution id the send returned. (4) Wait again until that execution has ended. (5) Execute agents status with no agent: quote raw your own task_sessions entry and the raw status entry of the child $CHILD (its configuration and model fields). (6) Reply with: every parent input you received whose JSON has source graphtraj, in order, verbatim (including its execution field); the execution id each create/send returned; the number of such inputs for each execution id. (7) Then retire the child by its agent id and include the raw retire result. Then end your turn."}]}. Print the raw result and end your turn. Do not wait.
  Main 把这次 swarm 的原始结果存为 $R/N.txt（必须含 "agent"）。成功: launch_status 不是 failed。
  成员结束后 Main 收到它一次 completed 通知；把这条通知原文存为 $R/N-main-notice.txt（定义第 3 项 452: 正常结束并报告；第 4 项: 正常显示）。
  把成员的最终回复原文存为 $R/N-reply.txt（Nr 读它的 configuration/model 字段）。
  成员回复里: 两个 execution id 各恰好一条 source graphtraj 的输入，每条的 execution 等于该 id；子级条目的 configuration 与 model 不是 null。
  之后 Main 的 Bash（无对话框）:
EOF2
  next "zsh $THIS Nr" ;;

Nr) print "[Nr] Main. 子级记录、459 的后代记录、成员的结束与 Session 档案（只读，从不发信号）。对话框: 无。"
  nr_read 2>&1 | tee $R/Nr.txt; rc=${pipestatus[1]}
  [[ -d $W/src/src/graftling ]] || { print "没有 $W/src/src（B 的 git archive）；先运行 B。" | tee -a $R/Nr.txt; rc=1; }
  $CONDA -I $SD/nr459.py $H $R $W/src/src $HOSTCFG $CHILD 2>&1 | tee -a $R/Nr.txt; (( ${pipestatus[1]} == 0 )) || rc=1
  print "Nw: ${$(grep -E '== END|start:' $R/Nw.txt 2>/dev/null | tail -1):-not run}" | tee -a $R/Nr.txt
  (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | grep -F -- "$TASK_ID" | head -10 | tee -a $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1); CHILDAGENT=$(sed -n 's/^CHILD //p' $R/Nr.txt | tail -1)
  SWARM_AGENT=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
  { print "CHECK swarm result has agent: $([[ -n $SWARM_AGENT ]] && print "PASS ($SWARM_AGENT)" || print "FAIL (no \"agent\" in $R/N.txt, or the file is missing)")"
    if [[ -n $MEMBER ]]; then
      W2=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -F -- '-m graphtraj.execution.runner_worker' | grep -F -- "/sessions/$MEMBER/" | grep -vF grep)
      print -r -- "runner_worker for $MEMBER now: ${W2:-none}"
      [[ -z $W2 ]] && print "CHECK 452 no runner_worker of the member alive after its end: PASS" \
        || print "CHECK 452 no runner_worker of the member alive after its end: FAIL if the member's end was already reported (rerun Nr in a minute; never kill it)"
    fi
    print "CHECK task_sessions lists the child: BY THE MEMBER'S QUOTED ENTRY in $R/N-reply.txt"; } | tee -a $R/Nr.txt
  summary Nr "$(grep -E '^child|CHECK|^member|member end|archive|stored selection|^459:|tool_marker recorded|Nw snapshots|recorded identities|ALIVE|NAMED|escaped_processes|normal-end reclaim|^Nw:' $R/Nr.txt)"
  print "成功（定义第 3 项）: 每一行 CHECK 都是 PASS（459 三行；455 两行；452 子级两行、成员结束、成员报告、无残留 Worker；449/451 每个 execution 一条输入）。"
  print "  escaped_processes 那几行只是记录（正常结束时 owner 的回收结果在 claude-termination-<id>.yml；执行记录里只有 owner-exited 对账才写）。"
  print "  CHECK BY HAND 的那一行用下面的 session_read 由 Main 按事件类型计数（453 的做法）。PENDING: 子级还在运行，稍后重跑 Nr。不成立的交 Main 登记缺陷 Task。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session\":\"$SID\",\"limit\":400} (page with after until has_more is false). Count, per $CHILD execution id printed by Nr, the user/message events that deliver a parent input with source graphtraj naming it; print the counts by event type and each such input's execution field only."
  print "\n复核 task_sessions（Main 粘贴，成员结束后也可）:\nUsing only the agents tool: status with no agent. Print raw only the task_sessions entry whose alias is ${MEMBER:-<member alias>} (its children list)${CHILDAGENT:+, and the status of agent $CHILDAGENT (configuration, model)}."
  if [[ -n $SWARM_AGENT ]]; then print "\n清退成员（Main 粘贴，Nr 全部记录后）:\nUsing only the agents tool: retire with {\"agent\":\"$SWARM_AGENT\"} (the agent value of the N swarm result, not the alias), and print the raw result."
  else print "\n清退成员: 先把 N 的 swarm 原始结果存到 $R/N.txt 再重跑 Nr；它会打印按 agent 清退的提示。"; fi
  next "zsh $THIS S2    （S 已 '== DONE' 时；之后 zsh $THIS done）"; exit $rc ;;

done) print "[done] Main. 结束状态。对话框: 无。只读。"
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS|^FAIL' $R/done-verify.txt
    $CONDA -I $SD/markers.py $S present | tail -1
    shasum -a 256 $ENTRIES; tree versions $SESS
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    tail -n 14 $R/S-suite.txt 2>/dev/null; grep -E '^leftover' $R/S2.txt 2>/dev/null
    print "Nw watcher: ${$(grep -E '== END' $R/Nw.txt 2>/dev/null | tail -1):-no '== END' line (not run, or still running: tail -n 5 $R/Nw.txt)}"
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|markers expected|archives=|containing an exported key|== totals|== DONE|^leftover|^Nw watcher' $R/done.txt)"
  print "成功: PASS n FAIL 0；markers expected present: PASS；raw files containing an exported key value: 0；S 有 '== DONE'；S2 的 leftover 行；Nw watcher 有 '== END'（本团队没有后台进程还在运行）。把 $R 的路径交给 Main。$R_HINT" ;;

R) need_main; print "[R] USER. 回退到安装前（4e3aafce）。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  wait_idle "还没有回退任何东西。" || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过。"
    print "然后（USER）: cd $H && claude --continue （插件字节与安装前相同，预期无对话框；出现任何框选拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_Srun) step__Srun ;;
_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
