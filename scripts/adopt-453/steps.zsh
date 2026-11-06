#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 453 — production adoption of dev cfd5e432 (449, 450 integrated) into .venv-runtime; 449's production check.
# Taken from scripts/adopt-448/steps.zsh. Same package names and versions as production (graphtraj 0.1.0,
# graftling 0.5.0), so every install claim is file by file (proddiff.py) against the new wheels.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V → S (background) → Vc (→ Vu USER once if asked) → [USER /exit Main] → I (USER, waits for idle members)
#        → [USER: claude --continue] → M → Mps → inbox → N → Nr → done.     Rollback after the backup: R (USER).
# Each step prints who runs it, its dialog (at most one) and how to judge success, then the next command.
# Main's Bash cannot run a foreground sleep: every Main step ends in < 10 min or starts itself in the
# background (S), and is polled by reading a file. Only I and R (USER's Terminal) wait in a loop.
# Only rehearse.zsh sets ADOPT453_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT453_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT453_BASE:-$HOME/graphtraj-adoption-453}
RT=${ADOPT453_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT453_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT453_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/453-production-adoption-449-450}
TARGET=cfd5e4322318dff8354317225f3127859328b8c0
TASK=453-production-adoption-449-450
TASK_ID=453
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
PROJECTS=${ADOPT453_PROJECTS:-$HOME/.claude/projects/${H//\//-}}
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT453_STUB:-} ]] && path=($ADOPT453_STUB $path)   # rehearsal only: stub hosts first
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
#   NON-BLOCKING  -m graphtraj.execution.budget_idle_timer  (445; budget_idle_timer.py:57, one per idle timed Session)
#   BLOCKING      -m graphtraj.execution.runner_worker      (a member's Worker; runner_control.py:1302, team_round.py:1339)
#   BLOCKING      -m graphtraj.teams.team_round              (a swarm batch dispatching members; team_round.py:382)
#   BLOCKING      ... host serve --config <this project>     (Main's Claude host; graphtraj/runtimes/claude/host.py)
#   BLOCKING      anything else under $RT, or naming Main's Session id (a member's own host, a DSH watcher, a CLI call)
# 450's marked processes (GRAFTLING_MEMBER_RUN in the environment) are listed for information: a member's
# escaped process; it blocks only if it also uses $RT (then it is already in the BLOCKING list).
kind_of() {
  case $1 in
    *"-m graphtraj.execution.runner_worker"*) print "member Worker" ;;
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
    print "guard: ${#timers} 个 445 预算空闲计时器（NON-BLOCKING，不是成员；安装后醒来最多让该 Session 的一条预算通知推迟，见 README）:"
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
    print "$(date +%T) 正在等待：Task 451/452（或其它 Task）的成员还在运行。不要结束（kill）这些进程；它们空闲后本步自动继续。"
    print "         Ctrl-C 可以安全放弃：$1"
    sleep ${ADOPT453_WAIT:-20}
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
  say "backup must be absent; 393/417/448 backups are never touched"; ls -d $BK 2>&1; ls -d $HOME/graphtraj-adoption-{393,417,448}/backup 2>&1
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "running Task members (451/452/453 may be running; I waits for them)"; (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | tee $R/00-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/00-members.txt) (451/452/453 members may run now; I waits for them)"
  say "Task 451 / 452 / 453 members (information)"; grep -E '(^|[^0-9])45[123]([^0-9]|$)' $R/00-members.txt || print "none listed"
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
  (( differs )) && print "差异: $R/V-plugin.diff（$(grep -c '^[<>]' $R/V-plugin.diff) 行）；host_context.mjs 改变，所以 resume 时可能出现一次插件信任框。"
  say "449 judgement: the copy keeps 'const PLUGIN = null' (local form) and gains the notice title ' · execution <id>' (display only)"
  grep -n '^const PLUGIN' $VP/hooks/host_context.mjs | sed 's/^/candidate: /'
  grep -q '^const PLUGIN = null;' $VP/hooks/host_context.mjs || { print "STOP: candidate is not the local-copy form"; rc=1; }
  if grep -q 'body.execution' $VP/hooks/host_context.mjs && ! grep -q 'body.execution' $PDIR/hooks/host_context.mjs; then
    print "449 hook change: notice title gains ' · execution <id>' (display only; local form kept)"
  else print "STOP: expected 449's body.execution only in the candidate"; rc=1; fi
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

# S: full suite of TARGET from this Worktree (editable install), 450's method, in the background.
# Venv as scripts/verify-450/steps.zsh: Conda python3.13 --system-site-packages, editable graftling and graphtraj,
# then production's click, yaml/_yaml/pyyaml and websockets COPIED into its site-packages (they shadow Conda's).
BASELINE_FAILS=(
  tests/test_pi_runtime.py::test_srt_gone_before_launch_is_refused
  'tests/test_codex_app_server.py::test_unhandled_server_requests_fail_visibly_without_blocking_peers[cancelled-RUNTIME_REQUEST_FAILED]'
  'tests/test_claude_host_integration_resolver.py::test_host_serves_main_while_the_conflict_resolver_waits_for_its_reply[True]'
)
step_S() {
  [[ $(git -C $WT rev-parse HEAD) == $TARGET ]] || git -C $WT diff --quiet $TARGET HEAD -- src tests pyproject.toml conftest.py \
    || { print "STOP: $WT differs from $TARGET in src/tests"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests) ]] || { print "STOP: uncommitted changes in $WT src/tests"; return 1; }
  say "quiet host: load and other test runs"
  print "loadavg: $(sysctl -n vm.loadavg 2>/dev/null)"
  local others=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -E 'pytest|run_test_shards' | grep -vE 'grep|steps.zsh')
  print -r -- "other pytest / run_test_shards processes: ${others:-none}"
  if [[ $others == *run_test_shards* ]]; then
    print "STOP: another run_test_shards is running; the host is not quiet. Main decides when to rerun S."; return 1
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
  rm -rf $R/S-shards; : > $R/S-suite.txt
  (cd $WT && nohup zsh $THIS _Srun >> $R/S-suite.txt 2>&1 &)
  print "started at $(date +%T) in the background (~15-25 min)."
}

step__Srun() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) (product files = $TARGET) loadavg $(sysctl -n vm.loadavg 2>/dev/null)"
  (cd $WT && clean $SV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/S-shards); print "== shards exit $?"
  local last=$(grep -E '^[0-9]+ (failed|errors|passed)' $R/S-suite.txt | tail -1)
  print "== totals: $last"
  print "== baseline 450 bb8b07db: 3 failed, 3963 passed, 71 skipped"
  print "== failures (BASELINE = also failed in 450's suite; NEW = not):"
  local id ids=(${(f)"$(sed -n 's/^FAILED //p; s/^ERROR //p' $R/S-shards/failures.txt 2>/dev/null | sed 's/ - .*//' | sort -u)"})
  for id in $ids; do (( ${BASELINE_FAILS[(Ie)$id]} )) && print "BASELINE $id" || print "NEW $id"; done
  (( ${#ids} )) || print "(none)"
  print "== each failure alone (-rA):"
  for id in $ids; do
    local out=$(cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q -rA "$id" 2>&1)
    local verdict=$(print -r -- "$out" | grep -oE '^(PASSED|FAILED|SKIPPED|ERROR)' | head -1)
    print "${verdict:-UNKNOWN} alone: $id"; print -r -- "$out" | grep -E '^(PASSED|FAILED|SKIPPED|ERROR)|passed|failed|skipped' | tail -2 | sed 's/^/    /'
  done
  print "== DONE $(date +%T)"
}

vc_setup() {
  local G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 453 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=453 -c user.email=453@invalid commit -qm "Initial source" || return 1
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
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/proddiff.py $SD/adopt_tree.py $SD/adopt_plugin.py $BK/tools/ || return 1
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
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graftling.member_processes as m, graftling.claude.execution as ce; from graphtraj.execution.runner_models import MEMBER_RUN_ENV; print("graftling", graftling.__version__); print(h.__file__); print("450 member_processes:", m.__file__, MEMBER_RUN_ENV); assert ce.MEMBER_RUN_ENV == MEMBER_RUN_ENV; assert graftling.__version__ == "0.5.0"' || return 1
  say "plugin regenerated by the installed code, plugin files only"; $P -I $SD/adopt_plugin.py regen $H $(claude_bin) $PDIR || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  grep -q 'body.execution' $PDIR/hooks/host_context.mjs && print "449 installed host_context.mjs names body.execution" || { print "installed host_context.mjs lacks body.execution"; return 1; }
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

# Nr: 449's production check, read only.
#   child record: <swarm>/control/agents/<agent>.json (graftling/control.py), name n453, parent = member alias,
#     executions[*]: id, state, outcome, notification (control.py ~403-463).
#   member record: found BY ALIAS (448 looked for agent == alias and found nothing): the Runner Session directory
#     <runner>/sessions/<alias>/mapping.yml, else a retired one under the Task's teams/*/traces/<alias>/runner/session.yml
#     (retirement.mapping), as scripts/verify-449/probe.py reads them. mapping 'session' names the Session archive.
#   archive: <swarm>/sessions/<session>/session.jsonl; lines naming each execution id, and lines that look like a
#     parent notice ("source": "graphtraj"/"graftling" or "notice") naming it.
nr_read() {
  $CONDA -I - $H $SESS $TASK <<'PY2'
import json, sys
from pathlib import Path
import yaml
h, sess, task = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
roots = sorted({p.parent for g in ('.graphtraj/swarm/control/agents/*.json', '.graphtraj/*/control/agents/*.json', '.graphtraj/core/runner/control/agents/*.json') for p in h.glob(g)})
print('record directories:', [str(r) for r in roots] or 'NONE')
child = None
for r in roots:
    for p in r.glob('*.json'):
        try: d = json.loads(p.read_text())
        except Exception: continue
        if d.get('name') == 'n453': child = d
if child is None:
    print('NO n453 child found. Did N run, and did the member create it with that name?'); sys.exit(1)
exs = child.get('executions') or []
print(f"child n453: agent={child.get('agent')} parent={child.get('parent')} executions={len(exs)} retired={child.get('retired_at') is not None}")
for ex in exs:
    print(f"  execution {ex.get('id')}: state={ex.get('state')} outcome={ex.get('outcome')} notification={ex.get('notification')}")
print(f"  CHECK two executions: {'PASS' if len(exs) == 2 else 'FAIL'}")
for ex in exs:
    print(f"  CHECK execution {ex.get('id')} notification delivered: {'PASS' if ex.get('notification') == 'delivered' else 'FAIL'}")
alias = child.get('parent')
mapping, where = {}, None
cands = [h / '.graphtraj/core/runner/sessions' / str(alias) / 'mapping.yml', h / '.graphtraj/runner/sessions' / str(alias) / 'mapping.yml']
cands += sorted(h.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/session.yml'))
for c in cands:
    if c.is_file():
        d = yaml.safe_load(c.read_text()) or {}
        mapping = d if c.name == 'mapping.yml' else ((d.get('retirement') or {}).get('mapping') or {})
        where = c; break
sid = mapping.get('session')
sid = sid.get('id') if isinstance(sid, dict) else sid
print(f"member {alias}: record={where} session={sid} task={mapping.get('task_id')} role={mapping.get('role')}")
files = [sess / str(sid) / 'session.jsonl'] if sid else []
files = [f for f in files if f.exists()] or [f for f in sess.glob('*/session.jsonl') if any(e.get('id') and e['id'] in f.read_text(errors='replace') for e in exs)]
for f in files:
    lines = f.read_text(errors='replace').splitlines()
    for ex in exs:
        eid = ex.get('id')
        hits = [i for i, l in enumerate(lines) if eid and eid in l]
        notices = [i for i in hits if any(k in lines[i] for k in ('"source"', 'notice', 'Notice'))]
        print(f"  archive {f.parent.name}: execution {eid}: lines naming it {len(hits)} at {hits[:8]}; notice-like {len(notices)} at {notices[:8]}")
        print(f"  CHECK one notice for execution {eid} in the archive: {'PASS' if len(notices) == 1 else 'CHECK BY HAND (count ' + str(len(notices)) + '; tool results also name the id)'}")
if not files: print('  archive: NOT FOUND (member Session archive)')
print('MEMBER', alias or '')
print('SESSION', sid or '')
PY2
}

R_HINT="回退（USER，先在 Main 里 /exit）: zsh $BK/tools/steps.zsh R"

case $STEP in
help) print "顺序: 00 → B → V → S（后台）→ Vc（必要时 Vu）→ /exit Main → I（USER，等待成员空闲）→ claude --continue → M → Mps → inbox → N → Nr → done；备份完成后可回退: R。"
  next "zsh $THIS 00" ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE/scratch、$BASE/main.session 与 $R。约 2 分钟。"
  logged $R/00.txt step_00
  summary 00 "$(grep -E 'ZSH_VERSION|Node spawn|inherited|answer:|^Version|pip check rc|production copy|running lines|^stopped|status|MAIN=|MAIN NOT|volume ids|^guard' $R/00.txt)"
  print "成功: ZSH_VERSION 有值；answer 里 models 含 $MODEL 且 is_error False；graphtraj 0.1.0 与 graftling 0.5.0；pip check rc=0；stopped: false 且 Team 1 active；$BK 'No such file'；MAIN=<id>。"
  print "running lines 可以不为 0（451/452/453 的成员）；I 会等它们空闲，不需要现在处理。guard 的 NON-BLOCKING 计时器不影响安装。"
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
    summary V "$(grep -E '^(SAME|CHANGE)|差异|449|STOP|✘ lines|    |read_session|loaded|task graph' $R/V.txt)"
    print "成功: 候选 ✘ 不多于 baseline；'449 hook change: notice title gains ...'，无 STOP；入口文件 SAME 或只列出可解释的变化；read_session failures=0。"
    next "zsh $THIS S"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

S) print "[S] Main. TARGET 的全套测试（从本 Worktree 导入，6 个 shard，--timeout 1500，后台）。对话框: 无。立即返回。另一个 run_test_shards 在运行时拒绝。"
  if logged $R/S-setup.txt step_S; then
    print "状态（Main 随时）:  tail -n 25 $R/S-suite.txt"
    print "完成标志: '== DONE'。成功: 没有 'NEW ' 开头的失败（基线 450 bb8b07db: 3 failed、3963 passed、71 skipped）；"
    print "  每个失败单独复核一行 'PASSED/FAILED/SKIPPED alone: <id>'。NEW 且单独仍 FAILED 的交 Main。"
    print "失败的 ID: $R/S-shards/failures.txt；某 shard 'ABNORMAL' 或 'timed out': 把那一行交给 Main。S 可与 Vc 同时进行。"
    next "zsh $THIS Vc"
  else print "\nS 未启动（见上面 STOP 或 GUARD 行），把 $R/S-setup.txt 交给 Main；主机不空闲时由 Main 决定何时重跑。"; exit 1; fi ;;

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
    print "\n下一步是 USER 的: 先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。I 会等 451/452/453 的成员空闲（不要结束它们）。S 在后台继续，不受影响（它不用 .venv-runtime 的进程）。"
    next "USER（Main 已 /exit）: zsh $THIS I"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（一次；需要终端和对话框，Main 做不了）。在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若再问项目的 MCP server 'agents' 或插件，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

I) need_main
  print "[I] USER. 等待成员空闲、备份并安装。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。安装约 3 分钟（等待时间另计）。"
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
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|450 member_processes|449 installed|SAME-AS-VALIDATED|WRITTEN|UNCHANGED|bytes unchanged|^changed|BLOCKING|-rw-------' $R/I.txt)"
  print "成功: Successfully installed graftling-0.5.0 graphtraj-0.1.0；PASS n FAIL 0；四个 -rw------- 备份入口文件；450 member_processes 在 $RT；SAME-AS-VALIDATED；449 installed host_context.mjs names body.execution；入口文件 bytes unchanged 或 V 已列出的变化。"
  print "$R_HINT"
  print "\n下一步（USER，普通 Terminal）恢复 Main（同一个 Session）:\n  cd $H && claude --continue"
  print "预期对话框: 至多一个插件/hooks 信任框（host_context.mjs 的字节变了），选信任。其它任何框选拒绝并告诉 Main。"
  print "若 --continue 打开的不是原来的对话: /exit，然后 cd $H && claude --resume $MAIN"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cat <<EOF | tee $R/M-prompts.txt
[M] Main（用 claude --continue 恢复的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。对话框: 无。Main 把原始结果存到 $R/M-<字母>.txt。

[a 定义第 4 项: 安装后第一次 Main 重启，通知不重复 → 新插件已加载] 恢复后第一句:
Before anything else: list every GraphTraj/Graftling notice delivered to you since this resume (alias, event, execution if shown in the title, first line), and for each say whether you had already seen that same notice before this resume. Use no tools.
  成功: 没有安装前已见过的通知再出现。Main 退出期间结束的 451/452 成员的通知可能在恢复时到达一次，这是预期的；它们不能再重复。
  若有重复: 记下 alias/event/execution/次数，由 Main 登记缺陷 Task。

[b 工具与插件] 先输入 /agents-context ，再粘贴:
Using only the tasks tool: discover. Print the raw list of feature names, and nothing else.
Using only the agents tool: status with no agent. Print the raw result.
  成功: /agents-context 显示 current Session $MAIN 与 agents/tasks 已注册；discover 有功能列表；status 有结果。

[c] Main 的 Bash（无对话框）: zsh $THIS Mps   然后   zsh $THIS inbox
EOF
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
  next "zsh $THIS N" ;;

N) cat <<EOF | tee $R/N-prompts.txt
[N] Main. 定义第 3 项（449 的生产核对）。在 Claude Main 里粘贴这一条。对话框: 无（成员只用 agents 工具；子级不用工具）。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Use only the agents tool for all of this. (1) Create ONE claude child named n453 with configuration opus_coding_team.advisor (this preset role is required; a child on the login's default model hung in 449) and instruction 'Reply with exactly one line: PONG-453-1. Use no tools.' Note the agent id and the execution id the create returned. (2) Use the agents wait on that agent id until that execution has ended. (3) Send to the same child by its agent id: 'Reply with exactly one line: PONG-453-2. Use no tools.' Note the execution id the send returned. (4) Wait again until that execution has ended. (5) Execute agents status with no agent and quote your own task_sessions entry raw. (6) Reply with: every parent input you received, in order, raw (including any execution field); the execution id each create/send returned; the number of inputs you received for each execution id. (7) Then retire the child by its agent id and include the raw retire result."}]}. Print the raw result and end your turn. Do not wait.
  Main 把这次 swarm 的原始结果存为 $R/N.txt（必须含 "agent"）。成功: launch_status 不是 failed。
  几分钟后 Main 收到这个成员一次 completed 通知；标题应形如 [GraphTraj notice from <alias> · completed · execution <id>]。
  把这条通知的原文粘贴存为 $R/N-main-notice.txt（定义第 4 项：带 execution 字段仍正常显示）。
  成员回复里: 两个 execution id 各恰好一条输入，每条的 execution 等于该 id；task_sessions 条目列出子级的 agent。
  之后 Main 的 Bash（无对话框）:
EOF
  next "zsh $THIS Nr" ;;

Nr) print "[Nr] Main. 子级记录与成员 Session 档案（只读）。对话框: 无。"
  nr_read 2>&1 | tee $R/Nr.txt; rc=${pipestatus[1]}
  (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | grep -F -- "$TASK_ID" | head -10 | tee -a $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1)
  SWARM_AGENT=$([[ -r $R/N.txt ]] && grep -oE '"agent" *: *"[^"]+"' $R/N.txt | head -1 | sed -E 's/.*: *"([^"]+)"/\1/')
  { print "CHECK swarm result has agent: $([[ -n $SWARM_AGENT ]] && print "PASS ($SWARM_AGENT)" || print "FAIL (no \"agent\" in $R/N.txt, or the file is missing)")"
    if [[ -r $R/N-main-notice.txt ]]; then grep -q ' · execution ' $R/N-main-notice.txt && print "CHECK Main's notice title names the execution: PASS" || print "CHECK Main's notice title names the execution: FAIL"
    else print "CHECK Main's notice title names the execution: PENDING (save $R/N-main-notice.txt)"; fi
    print "CHECK task_sessions lists the child: BY THE MEMBER'S QUOTED ENTRY (no read-only CLI for agents status; see the Main prompt below)"; } | tee -a $R/Nr.txt
  summary Nr "$(grep -E '^child|CHECK|^member|archive' $R/Nr.txt)"
  print "成功（定义第 3 项）: CHECK two executions PASS；每个 execution 的 'notification delivered: PASS'；成员回复中每个 execution 恰好一条输入且 execution 等于该 id；"
  print "  成员引用的 task_sessions 条目含子级 agent；swarm 结果带 agent。不成立的交 Main 登记缺陷 Task。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session\":\"$SID\",\"limit\":80}. For each n453 execution id printed by Nr, count the parent inputs (notices) naming it and print the counts and each input's execution field only."
  print "\n复核 task_sessions（Main 粘贴，成员结束后也可）:\nUsing only the agents tool: status with no agent. Print raw only the task_sessions entry whose alias is ${MEMBER:-<member alias>} (its children list)."
  if [[ -n $SWARM_AGENT ]]; then print "\n清退成员（Main 粘贴）:\nUsing only the agents tool: retire with {\"agent\":\"$SWARM_AGENT\"} (the agent value of the N swarm result, not the alias), and print the raw result."
  else print "\n清退成员: 先把 N 的 swarm 原始结果存到 $R/N.txt 再重跑 Nr；它会打印按 agent 清退的提示。"; fi
  next "zsh $THIS done"; exit $rc ;;

done) print "[done] Main. 结束状态。对话框: 无。只读。"
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS|^FAIL' $R/done-verify.txt
    shasum -a 256 $ENTRIES; tree versions $SESS
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    tail -n 12 $R/S-suite.txt 2>/dev/null; ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|archives=|containing an exported key|== totals|== DONE' $R/done.txt)"
  print "成功: PASS n FAIL 0；raw files containing an exported key value: 0；S 有 '== DONE'。把 $R 的路径交给 Main。$R_HINT" ;;

R) need_main; print "[R] USER. 回退到安装前。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  wait_idle "还没有回退任何东西。" || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过。"
    print "然后（USER）: cd $H && claude --continue （插件字节又变了，至多一个插件信任框，选信任；其它框拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_Srun) step__Srun ;;
_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
