#!/bin/zsh
# Task 417 — production adoption of agents 0.2.4 (1a648ca) into .venv-runtime, adapted from 402.
# Run from the user's own plain Terminal, in ~:   zsh <absolute path>/steps.zsh <step>
# Order: 0 → B → V → Vc → I (Main /exit first) → M → P → done.   Rollback any time after the backup: R.
# Each step says beforehand which dialog it can show (at most one) and how to judge success.
# Only rehearse.zsh sets ADOPT417_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT417_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT417_BASE:-$HOME/graphtraj-adoption-417}
RT=${ADOPT417_RT:-$H/.venv-runtime}
PISBX=${ADOPT417_PI_SANDBOX:-$HOME/agents-pi-sandbox}
WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/417-production-adoption-agents-024
TARGET=1a648ca32d651ce379dbfaa89040a35745c182af
TASK=417-production-adoption-agents-024
LEADER=417-production_adoption_agents_024-handover0-team_leader@team_leader
ENGINEER=417-production_adoption_agents_024-handover0-engineer@engineer
OLD_LEADER=402-integrate_resolver_approval_deadlock-handover0-team_leader@team_leader
OLD_SESSION=d0251020-c512-4db5-939f-a6993aae74fd
MAIN=1845493c-4a13-43d4-b4ea-c5864f8b22cb
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw
N=$W/wheels
BK=$BASE/backup
VV=$BASE/vvenv
VP=$W/vplug/graphtraj-claude-host
VPROJECT=$BASE/vproject
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
UNTOUCHED=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml)
THIS=${0:A}
STEP=${1:-help}
mkdir -p $R

next() { print -- "\n==> 下一步（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
tree() { $CONDA -I $SD/adopt_tree.py "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
redact() { local line=$1; [[ -n ${DEEPSEEK_API_KEY:-} ]] && line=${line//$DEEPSEEK_API_KEY/[redacted]}; print -r -- "$line"; }
wheel_of() { local f=($N/$1-*.whl(N)); print -r -- ${f[1]:-}; }

# Lists what would be damaged by replacing the venv. Refuses when the list cannot be read.
guard() {
  local listing rc line words hits=()
  listing=$(ps -axww -o pid=,command= 2>&1); rc=$?
  if (( rc != 0 )) || [[ -z $listing ]]; then
    print "无法列出进程（ps rc=$rc: ${listing[1,120]}），拒绝继续。"; return 2
  fi
  for line in ${(f)listing}; do
    words=(${=line})
    [[ ${words[1]} == $$ ]] && continue
    if [[ $line == *"$RT/"* || $line == *"$HOSTCFG"* || $line == *"--resume $MAIN"* ]]; then
      hits+=("$(redact "${line[1,220]}")")
    fi
  done
  (( ${#hits} == 0 )) && { print "guard: 没有进程在使用 $RT，Main 的 host 不在运行。"; return 0; }
  print "拒绝继续：以下 ${#hits} 个进程仍在使用 $RT（或是 Main）。先在 Main 里 /exit，并等它们结束。"
  print -l -- $hits
  print "自行查找: ps -axww -o pid,ppid,etime,command | grep -F .venv-runtime"
  return 1
}

one_line() {  # label, stdin file, command...: bounded at 120 s; prints the answer or the last failure line; never fatal
  local label=$1 input=$2 rc=0 out=$BASE/scratch/out.$$ err=$BASE/scratch/err.$$; shift 2
  (cd $BASE/scratch && /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' 120 "$@" < $input > $out 2> $err) || rc=$?
  if (( rc == 0 )); then redact "$label OK: $(tail -1 $out)"
  else redact "$label FAILED rc=$rc (142 是 120 秒超时): $(tail -1 $err) $(tail -1 $out)"; fi
  rm -f $out $err
}

step_0() {
  local ASK='In one line: name the model you are running as, and confirm you are logged in. Do not use any tool or print any key.'
  mkdir -p $BASE/scratch $BASE/scratch/pi-home; print -r -- "$ASK" > $BASE/scratch/ask.txt
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"
  say "credential is present? (value never printed)"; [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset"
  say "production versions (expect graphtraj 0.1.0, agent-swarm 0.1.2; pip check clean)"
  $RT/bin/python -m pip show graphtraj agent-swarm 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  ls -d $(site)/*.dist-info(N) | sed 's|.*/||'; $RT/bin/python -m pip check; print "pip check rc=$?"
  say "plugin and hashes"; ls -la $PDIR $PDIR/hooks $PDIR/.claude-plugin; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  say ".mcp.json (agents entry; other entries by name only) and hashes"; tree mcp $H/.mcp.json; shasum -a 256 $UNTOUCHED
  say "backup must be absent; same volume as the project"; ls -d $BK 2>&1; print "volume ids: $(stat -f %d $H) $(stat -f %d ${BASE:h})"; du -sh $RT
  say "archives by version (expect only version 4 before the install)"; tree versions $SESS
  say "Pi sandbox"; ls -d $PISBX/pi-sandbox.env 2>&1; ls -d /private/tmp/pi-asb-247 2>&1
  say "hosts answer one line, from the empty $BASE/scratch (no project MCP involved)"
  local C=$(claude_bin); print "claude: $C ($($C --version))"
  one_line "claude $MODEL" $BASE/scratch/ask.txt $C -p --model $MODEL
  local X=$(command -v codex); print "codex: $X ($($X --version))"; $X login status 2>&1 | tail -1
  one_line "codex gpt-6-astra" $BASE/scratch/ask.txt $X exec --skip-git-repo-check --ephemeral -s read-only -m gpt-6-astra -
  one_line "codex deepseek-flash" $BASE/scratch/ask.txt $X exec --skip-git-repo-check --ephemeral -s read-only -m deepseek-flash \
    -c model_provider=graphtraj-role \
    -c 'model_providers.graphtraj-role={name="GraphTraj role",base_url="https://api.deepseek.com",env_key="DEEPSEEK_API_KEY",requires_openai_auth=false,wire_api="responses"}' -
  local PI=$(command -v pi); print "pi: $PI ($($PI --version 2>&1 | head -1))"
  one_line "pi deepseek-flash" /dev/null env PI_CODING_AGENT_DIR=$BASE/scratch/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
    $PI --print --no-tools --provider deepseek --model deepseek-flash "$ASK"
  local D=$(command -v dsh); print "dsh: $D ($($D --version 2>&1 | head -1); floor 0.2.0-rc.2)"
  one_line "dsh configured model" $BASE/scratch/ask.txt env -u DEEPSEEK_BASE_URL $D headless --permission-mode read-only -
  say "running Task members (public read; expect no 'running')"; (cd $H && $RT/bin/graphtraj task members) 2>&1 | tee $R/0-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/0-members.txt)"
  say "processes using the venv now (information only; Main is expected here)"; guard
}

step_B() {
  rm -rf $W/src $N; mkdir -p $W/src $N
  git -C $WT archive $TARGET | tar -x -C $W/src || return 1
  local BP=$RT/bin/python
  $BP -c 'import setuptools, wheel' 2>/dev/null || { BP=$CONDA; print "生产 venv 没有 setuptools/wheel，用 $BP 构建（不修改 Conda）"; }
  say "build with $BP (--no-index --no-deps --no-build-isolation)"
  $BP -m pip wheel --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $W/src $W/src/src/agent_swarm || return 1
  say "wheels and sha256 (expect graphtraj-0.1.0 and agent_swarm-0.2.4)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT
  [[ -n $(wheel_of graphtraj) && -n $(wheel_of agent_swarm) && $(wheel_of agent_swarm) == *agent_swarm-0.2.4-* ]] || { print "wheel 名称不符"; return 1; }
  say "no build/ or __pycache__ inside the wheels (expect 0)"
  local leaked=$(for f in $N/*.whl(N); do unzip -Z1 $f; done | grep -cE '(^|/)(build|__pycache__)/')
  print "leaked: $leaked"; [[ $leaked == 0 ]]
}

scratch_venv() {
  rm -rf $VV; $CONDA -m venv $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(wheel_of graphtraj) $(wheel_of agent_swarm) || return 1
  local S=$(site) D=($VV/lib/python*/site-packages(N)); D=${D[1]}
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/ || return 1
  $VV/bin/python -m pip check --disable-pip-version-check; print "scratch venv pip check rc=$?"
  $VV/bin/python -I -c 'import agent_swarm, graphtraj.runtimes.claude.host as h; print("agent_swarm", agent_swarm.__version__, h.__file__)'
}

step_V() {
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 步骤的 wheel，先运行 B。"; return 1; }
  (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  local rc=0 C=$(claude_bin) P=$VV/bin/python
  say "scratch venv: new wheels plus production's click, yaml, websockets"; scratch_venv || return 1
  say "candidate plugin: new code writes into a scratch copy of production's plugin"
  rm -rf $W/vplug; mkdir -p $W/vplug; cp -Rp $PDIR $W/vplug/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name differs=0
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; differs=1; diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  (( differs )) && print "差异: $R/V-plugin.diff；host_context.mjs 改变，所以 resume 时可能出现一次插件信任框。"
  grep -c 'agent_swarm.claude.host' $VP/hooks/host_context.mjs | sed 's/^/forwarding lines to agent_swarm.claude.host: /'
  grep -n '^const TOOLS' $VP/hooks/host_context.mjs
  say "claude plugin validate: baseline, candidate"; print "claude: $C ($($C --version))"
  $C plugin validate $PDIR; print "baseline rc=$?"; $C plugin validate $VP; print "candidate rc=$?"
  local base=$($C plugin validate $PDIR 2>&1 | grep -c '✘') cand=$($C plugin validate $VP 2>&1 | grep -c '✘')
  print "✘ lines: baseline=$base candidate=$cand"; (( cand > base )) && rc=1
  say "the full material, not written: how the other three would differ from production"
  $P -I $SD/adopt_plugin.py material $H $C $RT/bin/python || rc=1
  say "read only against the real project: archives, configuration, roles; Task graph on an APFS clone of state"
  # read_index may rebuild the index and creates its lock, so the graph never reads the live state directory.
  touch $W/V-marker; [[ -e $BASE/vstate ]] && chmod -R u+w $BASE/vstate && rm -rf $BASE/vstate; mkdir -p $BASE/vstate
  local part; for part in tasks worldline; do [[ -d $H/.graphtraj/core/state/$part ]] && cp -cRp $H/.graphtraj/core/state/$part $BASE/vstate/; done
  $P -I $SD/adopt_plugin.py readcheck $H $BASE/vstate || rc=1
  chmod -R u+w $BASE/vstate; rm -rf $BASE/vstate
  print "state or archive files changed since the marker (Main may be writing; expect only its own):"
  find $H/.graphtraj/core $H/.graphtraj/swarm -type f -newer $W/V-marker -not -path "$W/*" 2>/dev/null | head -20
  say "recorded hashes (I checks these did not change)"; shasum -a 256 $UNTOUCHED | tee $W/untouched.sha256
  return $rc
}

step_Vc() {
  local C=$(claude_bin) G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  if [[ ! -d $VPROJECT/.git ]]; then
    mkdir -p $VPROJECT; git -C $VPROJECT init -q --initial-branch=main; print -r -- "# 417 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=417 -c user.email=417@invalid commit -qm "Initial source"
    (cd $VPROJECT && print -r -- y | $G setup) || return 1
    print "现在 Claude Code 在 $VPROJECT 启动一次。对话框 'Do you trust the files in this folder?' 选 'Yes, proceed'。"
    print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
    (cd $VPROJECT && $C)
    (cd $VPROJECT && $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $C --write) || return 1
  fi
  say "claude -p calls tasks discover and agents status (no dialog)"
  print -r -- 'Call mcp__agents__tasks once with {"action":"discover"} and mcp__agents__agents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && $C -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) > $R/Vc-stream.jsonl
  print "claude rc=$?"
  tree stream $R/Vc-stream.jsonl mcp__agents__tasks mcp__agents__agents || return 1
  say "host.log tail"; tail -n 20 $VPROJECT/.graphtraj/claude-host/host.log
  print "\n这证明: 当前 Claude Code 能用新 wheel、新代码写的插件和 host 回答 tasks 与 agents，插件转发到 agent_swarm.claude.host context 也接受 GraphTraj 的 config.json。"
  print "这不证明: 生产 .mcp.json 的已批准路径、Main 的 resume、通知送达、生产记录的读取，这些在 M 观察。"
}

do_backup() {
  mkdir -p $BK && chmod 700 $BK || return 1
  date '+backup start %F %T'
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/proddiff.py $SD/adopt_tree.py $SD/adopt_plugin.py $BK/tools/ || return 1
  say "manifest, then whole venv copy (cp -Rp)"; tree manifest $RT $BK/venv.manifest || return 1
  cp -Rp $RT $BK/venv || return 1; tree compare $BK/venv.manifest $BK/venv || return 1
  say "plugin copy"; tree manifest $PDIR $BK/plugin.manifest || return 1; cp -Rp $PDIR $BK/plugin || return 1
  say "archive clones (cp -cRp) and per-file version and sha256"
  mkdir -p $BK/archives
  if [[ -d $SESS ]]; then cp -cRp $SESS $BK/archives/sessions || return 1; else mkdir -p $BK/archives/sessions; fi
  tree archives $SESS $BK/archives.manifest || return 1
  say "hashes only; these are never copied"; shasum -a 256 $UNTOUCHED | tee $BK/untouched.sha256
  local f; for f in $ALSO; do [[ -r $f ]] && shasum -a 256 $f; done | sort -u > $BK/also.sha256
  touch $BK/COMPLETE; ls -ld $BK; date '+backup end %F %T'
}

do_install() {
  local S=$(site) P=$RT/bin/python w
  say "wheels (expect 2 x OK)"; cat $N/COMMIT; (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  [[ $(<$N/COMMIT) == $TARGET ]] || { print "COMMIT 不是目标提交"; return 1; }
  say "install"; $P -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $(wheel_of graphtraj) $(wheel_of agent_swarm) || return 1
  say "installed files vs wheels, including data files and leftovers"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS' $R/I-verify.txt; (( rc == 0 )) || return 1
  [[ ! -e $S/agent_swarm-0.1.2.dist-info ]] && print "agent_swarm-0.1.2.dist-info gone" || { print "agent_swarm-0.1.2.dist-info still here"; return 1; }
  say "entry scripts of both wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of agent_swarm); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import agent_swarm, graphtraj.runtimes.claude.host as h; print("agent_swarm", agent_swarm.__version__); print(h.__file__); assert agent_swarm.__version__ == "0.2.4"' || return 1
  say "plugin regenerated by the installed code, plugin files only"; $P -I $SD/adopt_plugin.py regen $H $(claude_bin) $PDIR || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  say "the untouched files (expect 3 x OK)"; shasum -a 256 -c $BK/untouched.sha256 || return 1; tree mcp $H/.mcp.json
  say "also unchanged (information; any FAILED means another writer: tell Main)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  return 0
}

step_R() {
  local KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S) rc=0
  date '+R start %F %T'; mkdir -p $KEEP
  say "before restoring: how the venv differs from the pre-install manifest"; tree compare $BK/venv.manifest $RT | tail -1
  say "venv restored whole from the backup"; rm -rf $RT; cp -Rp $BK/venv $RT || return 1
  say "venv equals pre-install bytes? (expect SAME differences=0)"; tree compare $BK/venv.manifest $RT || rc=1
  say "plugin restored; the current one kept"; [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; mkdir -p ${PDIR:h}; cp -Rp $BK/plugin $PDIR || return 1
  tree compare $BK/plugin.manifest $PDIR || rc=1
  say "archives: every non-v4 archive is kept, then restored or moved out of the old reader's glob"
  tree rollback $SESS $BK/archives/sessions $BK/archives.manifest $KEEP/archives || rc=1
  say "a channel file would make the old host refuse with host-busy, even a stale one"
  local CH=$H/.graphtraj/claude-host/live/channel.json
  if [[ -e $CH ]]; then mv $CH $KEEP/channel.json; print "moved out: $CH"; else print "no channel file"; fi
  say "notices 0.2.4 is still holding: the old code does not deliver these; status and wait still show the end"; tree held ${SESS:h}
  say "the untouched files (expect 3 x OK)"; shasum -a 256 -c $BK/untouched.sha256 || rc=1
  say "also unchanged since the backup? (information; a new reviewers or review entry in swarm/config.yml stops the old code loading it)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  say "versions and pip check"; $RT/bin/python -m pip show graphtraj agent-swarm 2>/dev/null | grep -E '^(Name|Version)'; $RT/bin/python -m pip check --disable-pip-version-check || rc=1
  print "\n回退的代价: 安装后记录的 Session 事件不在恢复后的档案里，只在 $KEEP/archives 的保留副本中；旧代码读不了它们。"
  return $rc
}

R_HINT="回退: zsh $BK/tools/steps.zsh R （任何时候可运行，先在 Main 里 /exit）"

case $STEP in
help) print "顺序: 0 → B → V → Vc → I → M → P → done；备份完成后任何时候可回退: R。"
  next "zsh $THIS 0" ;;

0) print "[0] 预检。无对话框。除了在 $BASE/scratch 下的空目录，不写任何东西；约 3 分钟。"
  logged $R/0.txt step_0
  print "\n证明: ZSH_VERSION 有值；agent-swarm 0.1.2；pip check rc=0；archives 全是 version 4；backup 'No such file'；两个 volume id 相同；每个宿主一行 OK（pi-sandbox 缺失只记录，不阻塞）；running lines: 0；dsh 版本不低于 0.2.0-rc.2。"
  print "任一不符，停下告诉 Main。权威的成员检查：在 Main 里粘贴（无对话框），确认没有 running，否则不要做 I："
  print "  Using only the agents tool: status with no agent. Print, for every agent and Task session, its alias, activity and state, and say whether any is running."
  next "zsh $THIS B" ;;

B) print "[B] 从 git archive $TARGET 构建两个 wheel（不用 Worktree、不联网、不改 Conda 和生产）。无对话框。"
  if logged $R/B.txt step_B; then
    print "\n证明: graphtraj-0.1.0、agent_swarm-0.2.4 各一个 wheel 及 sha256；leaked: 0。"
    next "zsh $THIS V"
  else print "\nB 失败。不要联网安装，把上面的输出交给 Main。"; exit 1; fi ;;

V) print "[V] 安装前校验。无对话框。只读真实项目，不写生产；scratch venv 与候选插件都在生产之外。Main 可以保持运行。"
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    print "\n证明: 候选 ✘ 不多于 baseline；config.json keys exactly True；--write would drop 列出 env（这就是不用 --write 的原因）；settings 的 GRAPHTRAJ_ 变量 same；read_session failures=0；configuration、roles、task graph 都有数字。"
    next "zsh $THIS Vc"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

Vc) print "[Vc] 隔离 scratch 项目里的真实 Claude 演练。首次运行有一个对话框（scratch 文件夹信任），选信任；其它框按 Esc。之后的 claude -p 无对话框。约 2 分钟。"
  if logged $R/Vc.txt step_Vc; then
    touch $R/Vc.ok
    print "\n证明: PASS mcp__agents__tasks 与 PASS mcp__agents__agents，且 error=False。"
    next "zsh $THIS I"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

_backup) # Rehearsal only: the backup part of I, so a half-way install can be made and rolled back.
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。"; exit 1; }
  guard || exit 1; logged $R/I.txt do_backup || exit 1 ;;

I) print "[I] 备份并安装。本步无对话框。需用户已同意，且 Main 已 /exit；Main 退出后不要再打开，直到本步结束。"
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  print "确认已在 Claude Code Main 里输入 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  guard || exit 1
  date '+I start %F %T' | tee -a $R/I.txt
  logged $R/I.txt do_backup || { print "\n备份失败，生产未被改动。把输出交给 Main；$BK 需要由 Main 决定如何处理。"; exit 1; }
  if ! logged $R/I.txt do_install; then
    print "\n安装或校验失败。不要 resume Main，立刻运行回退:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  print "\n证明: Successfully installed agent-swarm-0.2.4 graphtraj-0.1.0；PASS n FAIL 0（n 来自 wheel）；agent_swarm-0.1.2.dist-info gone；agent_swarm 0.2.4；SAME-AS-VALIDATED；三个文件 OK。"
  print "$R_HINT"
  print "\n重新进入 Main（普通 Terminal）: cd $H && claude --resume $MAIN"
  print "预期对话框: 至多一个插件/hooks 信任框（host_context.mjs 的字节变了），选信任。其它任何框选拒绝并告诉 Main。"
  next "zsh $THIS M" ;;

M) cat <<EOF | tee $R/M-prompts.txt
[M] 在重新进入的 Claude Code Main 里逐条粘贴，一次一条。每条无对话框；原始输出由 Main 留在会话记录里。

[a 插件、工具、已批准的 .mcp.json 路径] 这是 406 核对项的第一次真实观察：裸 claude --resume，没有 --mcp-config。先输入 /agents-context ，再粘贴:
Using only the tasks tool: discover. Print the raw list of feature names and the service block, and nothing else.
Using only the agents tool: status with no agent. Print the raw result.
  证明: /agents-context 显示 current Session $MAIN、MCP agents/tasks registered；discover 有功能列表；status 有结果。
  然后在另一个 Terminal（Main 保持运行，无对话框）: zsh $THIS Mps

[b 旧 Task 的记录仍能读]
Using only the tasks tool: run task_graph with {"task_id":"378"}, session_reports with {"alias":"$OLD_LEADER"}, and session_read with {"session_id":"$OLD_SESSION","limit":3}. Print for each only: whether it succeeded, the number of tasks / the report names / execution.session_id / the session header. Do not print report bodies.
  证明: 三个调用都成功；402 的报告名非空，execution.session_id 是 $OLD_SESSION；旧 Session 有 header。这是 v4 档案，新代码读，读取不改写。

[c 空闲 Main 被子级完成唤醒且只一次]
Using only the agents tool: create a claude child named "p417a" with configuration "opus_coding_team.advisor" and instruction "Reply with exactly one line: PONG-417-A. Use no tools." Do NOT wait. Print the raw result, then end your turn immediately.
  证明: 3 分钟内 Main 被自动唤醒，出现一次 "[GraphTraj notice from … · completed] PONG-417-A"。记下时间与次数（必须 1 次）。Terminal（无对话框）: zsh $THIS inbox ，duplicate ids: 0。
Using only the agents tool: retire p417a and print the raw result.
  证明: 无框，已清退。这一条走 agents create，不是 Runner 派发；派发在 P。
EOF
  next "zsh $THIS P" ;;

Mps) print "[Mps] 记录运行中的 host 与它的父 claude。无对话框。只读。Main 要保持运行。"
  { print "at $(date '+%F %T')"; hit=$(ps -axww -o pid=,ppid=,command= | grep -F -- "$HOSTCFG" | grep -F -- ' serve ')
    print -r -- "host: $hit"; words=(${=hit}); PPIDV=${words[2]:-}
    if [[ -n $PPIDV ]]; then C=$(ps -ww -o command= -p $PPIDV); print -r -- "parent claude: $C"
      [[ $C == *--mcp-config* ]] && print "parent has --mcp-config: yes" || print "parent has --mcp-config: no"
    else print "NOT FOUND: no host serving $HOSTCFG"; fi
    say "host.log tail"; tail -n 40 $H/.graphtraj/claude-host/host.log
  } 2>&1 | tee -a $R/Mps.txt
  print "\n证明: host 的 argv 是 $RT/bin/python -m graphtraj.runtimes.claude.host serve --config $HOSTCFG；parent has --mcp-config: no；host.log 有 agents-call finished ... outcome=ok。" ;;

inbox) print "[inbox] Main 的通知队列。无对话框。只读。"
  K=$(print -rn -- "claude:$MAIN" | shasum -a 256 | cut -d' ' -f1)
  logged $R/inbox.txt tree inbox $H/.graphtraj/core/runner/main-sessions/inbox/$K.jsonl
  print "\n证明: duplicate ids: 0。" ;;

P) HOSTED=$(unzip -p $(wheel_of graphtraj) graphtraj/interfaces/hosted_cli.py | shasum -a 256 | cut -d' ' -f1)
  if [[ -r $PISBX/pi-sandbox.env ]]; then
    PIROLE=$($CONDA -I -c 'import json,sys; d=dict(l.strip().split("=",1) for l in open(sys.argv[1]) if "=" in l); print(json.dumps({"pi_dsh_trial.merge_resolver":{"connection":"pi/deepseek/deepseek-flash","worktree_access":"read","pi":{"sandbox_python":d["sandbox_python"],"sandbox_path":d["sandbox_path"],"agent_dir":sys.argv[2]}}}))' $PISBX/pi-sandbox.env $HOME/.pi/agent)
    PINOTE="$PISBX 存在：内联 role 用它，不改 roles.yml。证明同上，PONG-417-PI。"
    PIEXPECT="Reply with exactly one line: PONG-417-PI. Use no tools."
  else
    PIROLE='"pi_dsh_trial.team_leader"'
    PINOTE="$PISBX 不存在：配置的 Pi preset 指向已删除的 /private/tmp/pi-asb-247。预期 launch_status failed，error.code RUNTIME_EXECUTABLE_INVALID（'Pi requires srt on pi.sandbox_path; no fallback.' 或 'Pi and agent-sandbox must be installed in the selected environment.'）。这条拒绝就是 Pi 未派发的原因，写进报告；不要安装沙箱。"
    PIEXPECT="Reply with exactly one line: PONG-417-PI. Use no tools."
  fi
  cat <<EOF | tee $R/P-prompts.txt
[P] 真实 Runner 派发，每个 Runtime 一次，全部派进 Task 417。逐条粘贴到 Main，无对话框。Main 把每个原始结果保存到 $R/P-<runtime>.txt。
路径（读代码确认）: 417 的 Team 1 是 active，Main 的根派发走 team_round._deliver_task 的 else 分支，不新建 Task、不新建 Worktree，因此不用注册探针 Task，也没有要清理的 Task；成员记录留在 417。role 必须是 role_tree 的根。

[codex] pi_dsh_trial.merge_resolver 是配置好的根（codex/openai/gpt-6-astra，medium，无 instructions 文件）。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"417","role":"pi_dsh_trial.merge_resolver","instruction":"Reply with exactly one line: PONG-417-CODEX. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: launch_status 不是 failed，有 alias 与 execution_id；Main 被唤醒一次，completed 通知里有 PONG-417-CODEX。

[dsh] pi_dsh_trial.engineer 只在 Pi Leader 之下，Main 不能直接派。内联 role 用允许的根引用，保持 role_tree 检查，不改 roles.yml。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"417","role":{"pi_dsh_trial.merge_resolver":{"connection":"dsh/deepseek-official/deepseek-flash","worktree_access":"read"}},"instruction":"Reply with exactly one line: PONG-417-DSH. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: 同上，PONG-417-DSH。

[pi] $PINOTE
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"417","role":$PIROLE,"instruction":"$PIEXPECT"}]}. Print the raw result and end your turn. Do not wait.

[claude 新启动] opus_coding_team.advisor 是配置好的根（claude/anthropic/opus-5_5）。这是 Claude 的一次新 Runner 启动。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"417","role":"opus_coding_team.advisor","instruction":"Reply with exactly one line: PONG-417-CLAUDE. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: 同 codex，PONG-417-CLAUDE。

[claude 继续] 已有成员在新代码上继续。只有记录中的直接父级能继续成员（runner_control.continue_member），所以 Main 发给 Leader，Leader 再发给 Engineer。
Using only the agents tool: send to agent "$LEADER" the message "Send your Engineer $ENGINEER this message, wait for its reply, and repeat it to me: Call the tasks tool once with discover. Reply with one line: service.host.sha256 and service.host.executable from its result. Do no other work." Print the raw result and end your turn. Do not wait.
  证明: Main 被唤醒一次；转述的 sha256 等于 wheel 里 hosted_cli.py 的 $HOSTED，executable 是 $RT/bin/python。

[清理] 每个结束的探针各一条（Leader 与 Engineer 不清退）:
Using only the agents tool: retire <alias> and print the raw result.
  证明: 无框；task_members 中它们是 retired。

[Terminal，无对话框] zsh $THIS inbox ，duplicate ids: 0。

未能从代码确认、要看真实结果的: Main 的 tasks 工具在新代码下暴露 swarm（Engineer 自己的列表有）；Codex、DSH、Pi 在 417 Worktree 里以根身份启动不需要额外批准；Team 或时间预算若已停止，swarm 会被拒绝，这时把错误带回，由 Leader 决定是否 continue。
EOF
  next "zsh $THIS done" ;;

done) print "[done] 记录结束状态。无对话框。只读。"
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj agent-swarm | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS' $R/done-verify.txt
    shasum -a 256 -c $BK/untouched.sha256; tree versions $SESS
    if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then print "files in raw containing the key: $(grep -rlF -- "$DEEPSEEK_API_KEY" $R 2>/dev/null | wc -l | tr -d ' ')"; fi
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  print "\n证明: PASS n FAIL 0；三个文件 OK；raw 中含密钥的文件数 0。把 $R 的路径交给 Main。$R_HINT" ;;

R) print "[R] 回退到安装前的字节。本步无对话框。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  guard || exit 1
  if logged $R/R.txt step_R; then
    print "\n证明: venv 与 plugin 都是 SAME differences=0（字节等于安装前）；problems=0；not-version-4 left: 0；三个文件 OK；agent-swarm 0.1.2；pip check 通过。"
    print "然后: cd $H && claude --resume $MAIN （插件字节又变了，至多一个插件信任框，选信任；其它框拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（见上面的 DIFF、PROBLEM 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
