#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 393 — production adoption of graftling 0.5.0 + graphtraj 0.1.0 (d11f3226) into .venv-runtime,
# replacing agent-swarm 0.2.4 (417, 1a648ca). Taken from scripts/adopt-417/steps.zsh with 417's five fixes.
# Run from the user's own plain macOS Terminal:   zsh <absolute path>/steps.zsh <step>
# Order: 0 → B → V → Vc → I (Main /exit first) → M → P → F → H1 → H2 (Codex Main) → H3 (Pi Main)
#        → H4a/H4b/H4c (headless DSH Main) → H5 (back to this Claude Main) → done.   Rollback after the backup: R.
# Each step says beforehand which dialog it can show (at most one) and how to judge success.
# PATH: this script puts /opt/homebrew/bin and ~/.local/bin first, and $PNPM_SHIM first of all when it
# exists (Homebrew's pnpm has no #! line, so Node's spawn gets ENOEXEC; 394's shim works around it).
# Only rehearse.zsh sets ADOPT393_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT393_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT393_BASE:-$HOME/graphtraj-adoption-393}
RT=${ADOPT393_RT:-$H/.venv-runtime}
PISBX=${ADOPT393_PI_SANDBOX:-$HOME/agents-pi-sandbox}
PNPM_SHIM=${ADOPT393_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/393-graphtraj-adoption-after-agents-release
TARGET=d11f3226422cb7a4de5e59d347f8d211d59350be
TASK=393-graphtraj-adoption-after-agents-release
TASK_ID=393
LEADER=393-graphtraj_adoption_after_agents_release-handover0-team_leader@team_leader
ENGINEER=393-graphtraj_adoption_after_agents_release-handover0-engineer@engineer
OLD_LEADER=417-production_adoption_agents_024-handover0-team_leader@team_leader
MAIN=1845493c-4a13-43d4-b4ea-c5864f8b22cb
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
CODEX_MODEL=gpt-6-luna          # user instruction 20261105T192335: never gpt-6-astra
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw
N=$W/wheels
BK=$BASE/backup
VV=$BASE/vvenv
VP=$W/vplug/graphtraj-claude-host
VE=$W/ventries
VPROJECT=$BASE/vproject
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml $H/.codex/config.toml(N) $H/.codex/hooks.json(N))
INBOX=$H/.graphtraj/core/runner/main-sessions/inbox
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT393_STUB:-} ]] && path=($ADOPT393_STUB $path)   # rehearsal only: stub hosts first
mkdir -p $R

next() { print -- "\n==> 下一步（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
tree() { $CONDA -I $SD/adopt_tree.py "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
redact() { local line=$1; [[ -n ${DEEPSEEK_API_KEY:-} ]] && line=${line//$DEEPSEEK_API_KEY/[redacted]}; print -r -- "$line"; }
wheel_of() { local f=($N/$1-*.whl(N)); print -r -- ${f[1]:-}; }
summary() { print -- "\n----- 复制给 Main 的摘要（$1）-----"; shift; print -l -- "$@"; print -- "-----"; }
back_to_main() { print -- "回到这个 Claude Main: 在 Terminal 运行  cd $H && claude --resume $MAIN"; }
inbox_key() { print -rn -- "$1" | shasum -a 256 | cut -d' ' -f1; }

# Pi probe (P): 417's inline role through ~/agents-pi-sandbox, instruction changed to read a file of the
# member's own Worktree (Task 425). Printed only; roles.yml and the env file stay as they are.
pi_prompt() {
  local SBP RGAT PIROLE INSTR="Use your read tool on AGENTS.md in your working directory, then reply with exactly one line: PONG-393-PI: followed by that file's first line."
  if [[ -r $PISBX/pi-sandbox.env ]]; then
    SBP=$(sed -n 's/^sandbox_path=//p' $PISBX/pi-sandbox.env | tail -1)
    if [[ -e $PISBX/bin/rg && ":$SBP:" != *":$PISBX/bin:"* ]]; then SBP=$PISBX/bin:$SBP; fi
    RGAT=$($CONDA -I -c 'import shutil,sys; print(shutil.which("rg",path=sys.argv[1]) or "")' "$SBP")
    PIROLE=$($CONDA -I -c 'import json,sys; d=dict(l.strip().split("=",1) for l in open(sys.argv[1]) if "=" in l); print(json.dumps({"pi_dsh_trial.merge_resolver":{"connection":"pi/deepseek/deepseek-flash","worktree_access":"read","pi":{"sandbox_python":d["sandbox_python"],"sandbox_path":sys.argv[3],"agent_dir":sys.argv[2]}}}))' $PISBX/pi-sandbox.env $HOME/.pi/agent "$SBP")
    [[ -n $RGAT ]] && print "（$PISBX 存在；sandbox PATH 里的 rg: $RGAT）" || print "（$PISBX 存在，但 sandbox PATH 里没有 rg，预期 Pi 启动失败；把错误带回）"
  else
    PIROLE='"pi_dsh_trial.team_leader"'
    print "（$PISBX 不存在：预期 launch_status failed，RUNTIME_EXECUTABLE_INVALID。这条拒绝就是 Pi 未派发的原因；不要安装沙箱。）"
  fi
  print -r -- "Using only the tasks tool: execute swarm with arguments {\"tasks\":[{\"task_id\":\"$TASK_ID\",\"role\":$PIROLE,\"instruction\":\"$INSTR\"}]}. Print the raw result and end your turn. Do not wait."
}

# GraphTraj's Pi extension spawns graphtraj-session from PATH and imports graftling's Pi extension
# beside it in site-packages; GRAFTLING_PYTHON names the venv for graftling's own host.
pi_main_command() {
  print -r -- "cd $H && PATH=$RT/bin:\$PATH GRAFTLING_PYTHON=$RT/bin/python pi --extension $(site)/graphtraj/runtimes/pi/extension.mjs --provider deepseek --model deepseek-flash"
}

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

# Names only (never values) of exported variables 433's rule treats as credentials: a Claude, Codex,
# Pi or DSH child no longer inherits these unless its own connection or roles.yml pass_env names them.
credential_names() {
  $CONDA -I -c '
import os, re
part = re.compile(r"(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
names = sorted(n for n in os.environ if not re.fullmatch(r"GIT_CONFIG_KEY_[0-9]+", n)
               and any(part.search(p) for p in n.upper().split("_") if p))
print("credential-like exported names (values never printed):", names or "none")'
}

step_0() {
  local ASK='In one line: name the model you are running as, and confirm you are logged in. Do not use any tool or print any key.'
  mkdir -p $BASE/scratch $BASE/scratch/pi-home; print -r -- "$ASK" > $BASE/scratch/ask.txt
  say "shell (expect zsh) and PATH head"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"; print -l -- ${path[1,4]}
  say "credential is present? (value never printed)"; [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset"
  say "433: names a child no longer inherits"; credential_names
  say "production versions (expect graphtraj 0.1.0, agent-swarm 0.2.4; pip check clean)"
  $RT/bin/python -m pip show graphtraj agent-swarm graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  ls -d $(site)/*.dist-info(N) | sed 's|.*/||'; $RT/bin/python -m pip check; print "pip check rc=$?"
  say "plugin and hashes"; ls -la $PDIR $PDIR/hooks $PDIR/.claude-plugin; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  say ".mcp.json (agents entry; other entries by name only), settings env names, hashes"; tree mcp $H/.mcp.json
  $CONDA -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print("settings.local.json env names:", sorted(d.get("env",{})), "| top-level:", sorted(d))' $H/.claude/settings.local.json
  shasum -a 256 $ENTRIES
  say "Harness-root Codex entry files (names of MCP servers and hook commands only; for H2)"
  for f in $H/.codex/config.toml(N) $H/.codex/hooks.json(N); do print "== $f"; grep -nE '^\[mcp_servers\.|^command|^args|agent_swarm|graftling|"command"' $f | sed -E 's/(KEY|TOKEN|SECRET)[^ ]*=.*/\1=<hidden>/' | head -30; done
  say "Pi and DSH packages that name the old package (for H3, H4)"
  grep -lsE 'agent_swarm|agent-swarm|graphtraj' $HOME/.pi/agent/settings.json 2>/dev/null | sed 's/^/pi settings mentions old\/graphtraj: /'
  grep -oE '"[^"]*(agent[-_]swarm|graftling|graphtraj)[^"]*"' $HOME/.pi/agent/settings.json 2>/dev/null | sort -u | head
  say "backup must be absent; same volume as the project; 417's backup untouched"; ls -d $BK 2>&1; ls -d $HOME/graphtraj-adoption-417/backup 2>&1
  print "volume ids: $(stat -f %d $H) $(stat -f %d ${BASE:h})"; du -sh $RT
  say "archives by version (0.2.4 writes 5 and reads 4)"; tree versions $SESS
  say "Pi sandbox, pnpm through Node, dsh, node"; ls -d $PISBX/pi-sandbox.env 2>&1
  print "pnpm on PATH: $(command -v pnpm) ($(pnpm --version 2>&1 | tail -1))"
  print "node: $(command -v node) $(node --version 2>&1)"
  node -e 'const r=require("child_process").spawnSync("pnpm",["--version"],{encoding:"utf8"}); console.log(r.error ? "Node spawn pnpm FAILED: "+r.error.code : "Node spawn pnpm OK "+r.stdout.trim())'
  say "hosts answer one line, from the empty $BASE/scratch (no project MCP involved)"
  local C=$(claude_bin); print "claude: $C ($($C --version))"
  one_line "claude $MODEL" $BASE/scratch/ask.txt $C -p --model $MODEL
  local X=$(command -v codex); print "codex: $X ($($X --version))"; $X login status 2>&1 | tail -1
  one_line "codex $CODEX_MODEL" $BASE/scratch/ask.txt $X exec --skip-git-repo-check --ephemeral -s read-only -m $CODEX_MODEL -
  local PI=$(command -v pi); print "pi: $PI ($($PI --version 2>&1 | head -1))"
  one_line "pi deepseek-flash" /dev/null env PI_CODING_AGENT_DIR=$BASE/scratch/pi-home PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
    $PI --print --no-tools --provider deepseek --model deepseek-flash "$ASK"
  say "DSH headless profile plugins (read only; H4 needs the GraphTraj/graftling plugin there)"; dsh plugin --profile headless list 2>&1 | head -20
  local D=$(command -v dsh); print "dsh: $D ($($D --version 2>&1 | head -1); floor 0.2.0-rc.2)"
  one_line "dsh configured model" $BASE/scratch/ask.txt env -u DEEPSEEK_BASE_URL $D headless --permission-mode read-only -
  say "running Task members (public read; expect no 'running')"; (cd $H && $RT/bin/graphtraj task members) 2>&1 | tee $R/0-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/0-members.txt)"
  say "Task $TASK_ID ready for root dispatch: Team 1 active, budget not stopped"
  grep -E '^(stopped|corrections|allowance_minutes):' $H/.graphtraj/core/state/tasks/$TASK/execution-budget.yml
  grep -E 'status|state' $H/.graphtraj/core/state/tasks/$TASK/teams/1/team.yml | head -5
  say "processes using the venv now (information only; Main is expected here)"; guard
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
  say "no build/ or __pycache__ inside the wheels (expect 0); no agent_swarm inside (expect 0)"
  local leaked=$(for f in $N/*.whl(N); do unzip -Z1 $f; done | grep -cE '(^|/)(build|__pycache__)/')
  local old=$(for f in $N/*.whl(N); do unzip -Z1 $f; done | grep -c '^agent_swarm')
  print "leaked: $leaked  agent_swarm entries: $old"; [[ $leaked == 0 && $old == 0 ]]
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
  (( differs )) && print "差异: $R/V-plugin.diff；host_context.mjs 改变，所以 resume 时可能出现一次插件信任框。"
  grep -c 'GRAFTLING_CLAUDE_HOST_' $VP/hooks/host_context.mjs | sed 's/^/candidate lines reading GRAFTLING_CLAUDE_HOST_*: /'
  grep -c 'GRAPHTRAJ_CLAUDE_HOST_' $VP/hooks/host_context.mjs | sed 's/^/candidate lines reading GRAPHTRAJ_CLAUDE_HOST_* (expect 0): /'
  grep -n '^const TOOLS' $VP/hooks/host_context.mjs
  say "claude plugin validate: baseline, candidate"; print "claude: $C ($($C --version))"
  $C plugin validate $PDIR; print "baseline rc=$?"; $C plugin validate $VP; print "candidate rc=$?"
  local base=$($C plugin validate $PDIR 2>&1 | grep -c '✘') cand=$($C plugin validate $VP 2>&1 | grep -c '✘')
  print "✘ lines: baseline=$base candidate=$cand"; (( cand > base )) && rc=1
  say "entry files: what configuration --write (419's merge) plus the rename would change; predictions only"
  rm -rf $VE; $P -I $SD/adopt_plugin.py entries $H $C $RT/bin/python $VE || rc=1
  say "read only against the real project: archives, configuration, roles; Task graph on an APFS clone of state"
  touch $W/V-marker; [[ -e $BASE/vstate ]] && chmod -R u+w $BASE/vstate && rm -rf $BASE/vstate; mkdir -p $BASE/vstate
  local part; for part in tasks worldline; do [[ -d $H/.graphtraj/core/state/$part ]] && cp -cRp $H/.graphtraj/core/state/$part $BASE/vstate/; done
  $P -I $SD/adopt_plugin.py readcheck $H $BASE/vstate || rc=1
  chmod -R u+w $BASE/vstate; rm -rf $BASE/vstate
  print "state or archive files changed since the marker (Main may be writing; expect only its own):"
  find $H/.graphtraj/core $H/.graphtraj/swarm -type f -newer $W/V-marker -not -path "$W/*" 2>/dev/null | head -20
  say "recorded hashes (I checks these did not change before it writes)"; shasum -a 256 $ENTRIES | tee $W/entries.sha256
  return $rc
}

# Vc has three parts. Only the interactive start stays out of `logged`: it runs with the Terminal's
# own inherited stdio (417: /dev/tty crashed it; inherited stdio gave rc=0), so it is not in Vc.txt.
vc_setup() {
  local G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 393 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=393 -c user.email=393@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | $G setup) || return 1
  fi
}

vc_instructions() {
  print "现在 Claude Code 在 $VPROJECT 启动一次。对话框 'Do you trust the files in this folder?' 选 'Yes, proceed'。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
}

vc_stream() {
  local C=$(claude_bin)
  local WRITTEN=$VPROJECT/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs
  if [[ ! -e $VPROJECT/.mcp.json || ! -e $WRITTEN ]]; then
    (cd $VPROJECT && $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $C --write) || return 1
  fi
  say "claude -p calls tasks discover and agents status (no dialog)"
  print -r -- 'Call mcp__agents__tasks once with {"action":"discover"} and mcp__agents__agents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && $C -p --model $MODEL --session-id $(uuidgen | tr A-Z a-z) --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) > $R/Vc-stream.jsonl
  print "claude rc=$?"
  tree stream $R/Vc-stream.jsonl mcp__agents__tasks mcp__agents__agents || return 1
  say "host.log tail"; tail -n 20 $VPROJECT/.graphtraj/claude-host/host.log
  print "\n这证明: 当前 Claude Code 能用新 wheel、新代码写的插件（读 GRAFTLING_CLAUDE_HOST_*）和 host 回答 tasks 与 agents。"
  print "这不证明: 生产入口文件、Main 的 resume、通知送达、生产记录的读取，这些在 M 观察。"
}

do_backup() {
  mkdir -p $BK && chmod 700 $BK || return 1
  date '+backup start %F %T'
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/proddiff.py $SD/adopt_tree.py $SD/adopt_plugin.py $BK/tools/ || return 1
  say "manifest, then whole venv copy (cp -Rp)"; tree manifest $RT $BK/venv.manifest || return 1
  cp -Rp $RT $BK/venv || return 1; tree compare $BK/venv.manifest $BK/venv || return 1
  say "plugin copy"; tree manifest $PDIR $BK/plugin.manifest || return 1; cp -Rp $PDIR $BK/plugin || return 1
  say "entry files: copies (mode 600) and hashes"; mkdir -p $BK/entries
  local f; for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || return 1; done; chmod 600 $BK/entries/*
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
  say "remove agent-swarm (the renamed package), then install both wheels"
  $P -m pip uninstall -y --disable-pip-version-check agent-swarm || return 1
  $P -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  say "installed files vs wheels, including data files and leftovers"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS' $R/I-verify.txt; (( rc == 0 )) || return 1
  local left=($S/agent_swarm(N) $S/agent_swarm-*.dist-info(N))
  (( ${#left} == 0 )) && print "agent_swarm package and dist-info gone" || { print "agent_swarm still here: $left"; return 1; }
  say "entry scripts of both wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of graftling); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, importlib.util as u; print("graftling", graftling.__version__); print(h.__file__); assert graftling.__version__ == "0.5.0"; assert u.find_spec("agent_swarm") is None' || return 1
  say "plugin regenerated by the installed code, plugin files only"; $P -I $SD/adopt_plugin.py regen $H $(claude_bin) $PDIR || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  say "entry files: write what V predicted (graftling write_adoption), before -> after"
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

# What the restored 0.2.4 reads: every archive through its own reader and the native_header glob.
old_read() {
  $RT/bin/python -I -c '
import sys; from pathlib import Path
from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive
bad = 0
for p in sorted(Path(sys.argv[1]).glob("*/session.jsonl")):
    try: JsonlSessionStore(p)
    except Exception as e: bad += 1; print("OLD-READ-FAIL", p.parent.name, type(e).__name__, str(e)[:160])
SessionArchive(Path(sys.argv[1]).parent).native_header("claude", "no-such-native")
print("old reader failures:", bad)
sys.exit(1 if bad else 0)' $SESS
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
  say "archives: graftling 0.5.0 writes version 5, which 0.2.4 also writes and reads; any other version is kept, then restored or moved out"
  tree rollback $SESS $BK/archives/sessions $BK/archives.manifest $KEEP/archives || rc=1
  say "the restored 0.2.4 reads every archive (expect old reader failures: 0)"; old_read || rc=1
  say "a channel file would make the old host refuse with host-busy, even a stale one"
  local CH=$H/.graphtraj/claude-host/live/channel.json
  if [[ -e $CH ]]; then mv $CH $KEEP/channel.json; print "moved out: $CH"; else print "no channel file"; fi
  say "notices still held (information)"; tree held ${SESS:h}
  say "also unchanged since the backup? (information)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  say "versions and pip check"; $RT/bin/python -m pip show graphtraj agent-swarm graftling 2>/dev/null | grep -E '^(Name|Version)'; $RT/bin/python -m pip check --disable-pip-version-check || rc=1
  print "\n回退的代价: 安装后新建或改写的 Session 档案仍是 version 5，0.2.4 照常读；只有 0.2.4 读不了的才移到 $KEEP/archives。"
  return $rc
}

R_HINT="回退: zsh $BK/tools/steps.zsh R （任何时候可运行，先在 Main 里 /exit）"

# Prompts below are printed text with real IDs. A probe's agent id is only known from its create or
# swarm result, so a retire prompt says to use the id that result returned (417 fix 3), never a name.
RETIRE='Then, using only the agents tool, retire that agent by the agent id the create or swarm result returned (not by its name), and print the raw result.'

case $STEP in
help) print "顺序: 0 → B → V → Vc → I → M → P → F → H1 → H2 → H3 → H4a → H4b → H4c → H5 → done；备份完成后任何时候可回退: R。"
  next "zsh $THIS 0" ;;

0) print "[0] 预检。无对话框。除了 $BASE/scratch，不写任何东西；约 4 分钟。Main 可以保持运行。"
  logged $R/0.txt step_0
  summary 0 "$(grep -E 'ZSH_VERSION|credential-like|^Version|pip check rc|Node spawn|OK:|FAILED|running lines|^stopped|archives=|volume ids' $R/0.txt | tail -30)"
  print "证明: ZSH_VERSION 有值；agent-swarm 0.2.4；pip check rc=0；Node spawn pnpm OK；每个宿主一行 OK（codex 用 $CODEX_MODEL）；running lines: 0；stopped: false；backup 'No such file'；两个 volume id 相同。"
  print "任一不符，停下告诉 Main。权威的成员检查：在 Main 里粘贴（无对话框），确认没有 running，否则不要做 I："
  print "  Using only the agents tool: status with no agent. Print, for every agent and Task session, its alias, activity and state, and say whether any is running."
  next "zsh $THIS B" ;;

B) print "[B] 从 git archive $TARGET 构建两个 wheel（不用 Worktree、不联网、不改 Conda 和生产）。无对话框。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked' $R/B.txt)"
    print "证明: graphtraj-0.1.0、graftling-0.5.0 各一个 wheel 及 sha256；leaked: 0  agent_swarm entries: 0。"
    next "zsh $THIS V"
  else print "\nB 失败。不要联网安装，把上面的输出交给 Main。"; exit 1; fi ;;

V) print "[V] 安装前校验。无对话框。只读真实项目，不写生产；scratch venv、候选插件与入口文件预测都在生产之外。Main 可以保持运行。"
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|✘ lines|GRAFTLING_CLAUDE|GRAPHTRAJ_CLAUDE|    |read_session|loaded|task graph' $R/V.txt)"
    print "证明: 候选 ✘ 不多于 baseline；候选读 GRAFTLING_CLAUDE_HOST_*（GRAPHTRAJ_ 为 0）；.mcp.json 与 config.json 为 SAME 或只列出可解释的变化，agents.env kept 含 LANGUAGE；settings.local.json 的 CHANGES 只有 GRAFTLING_CLAUDE_HOST_* 两项新增与 GRAPHTRAJ_CLAUDE_HOST_* 两项移除；read_session failures=0。"
    next "zsh $THIS Vc"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

Vc) print "[Vc] 隔离 scratch 项目里的真实 Claude 演练。首次运行有一个对话框（scratch 文件夹信任），选信任；其它框按 Esc。之后的 claude -p 无对话框。约 2 分钟。"
  vc_fail() {
    print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"
    print "交互启动不在 Vc.txt 里，所以请把屏幕上 Claude Code 的输出也复制给 Main。修好后重新运行本步：已完成的部分不会重做。"
    exit 1
  }
  TRUSTED=$VPROJECT/.git/adopt393-trust-start-ok
  logged $R/Vc.txt vc_setup || vc_fail
  if [[ ! -e $TRUSTED ]]; then
    logged $R/Vc.txt vc_instructions
    if [[ -z ${ADOPT393_NO_TTY:-} ]] && ! [[ -t 0 && -t 1 ]]; then
      print "拒绝启动：本步要显示信任框，stdin 和 stdout 都必须是终端。请在普通 Terminal 里直接运行，不要加管道或重定向。" | tee -a $R/Vc.txt
      vc_fail
    fi
    (cd $VPROJECT && $(claude_bin)); rc=$?
    print "trust start rc=$rc" | tee -a $R/Vc.txt
    if (( rc != 0 )); then
      print "Claude Code 退出码是 $rc。信任框出现过、你选了信任、并且用 /exit 离开了吗？按 y 表示是，按其它键表示否（没有反应就再按回车）。"
      if read -q -u 0 REPLY; then
        print "\ntrust start: user answered yes: the dialog appeared, was accepted and Claude was left with /exit" | tee -a $R/Vc.txt
      else
        print "\ntrust start: user answered no" | tee -a $R/Vc.txt
        vc_fail
      fi
    fi
    touch $TRUSTED
  fi
  if logged $R/Vc.txt vc_stream; then
    touch $R/Vc.ok
    summary Vc "$(grep -E '^(PASS|FAIL)|trust start' $R/Vc.txt)"
    print "证明: PASS mcp__agents__tasks 与 PASS mcp__agents__agents。"
    next "zsh $THIS I"
  else vc_fail; fi ;;

_backup) # Rehearsal only: the backup part of I, so a half-way install can be made and rolled back.
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。"; exit 1; }
  guard || exit 1; logged $R/I.txt do_backup || exit 1 ;;

I) print "[I] 备份并安装。本步无对话框。需用户已同意，且 Main 已 /exit；Main 退出后不要再打开，直到本步结束。约 3 分钟。"
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  print "确认已在 Claude Code Main 里输入 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  guard || exit 1
  date '+I start %F %T' | tee -a $R/I.txt
  logged $R/I.txt do_backup || { print "\n备份失败，生产未被改动。把输出交给 Main；$BK 需要由 Main 决定如何处理。"; exit 1; }
  if ! logged $R/I.txt do_install; then
    print "\n安装或校验失败。不要 resume Main，立刻运行回退:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  summary I "$(grep -E 'Successfully|^PASS|agent_swarm package|^graftling 0|SAME-AS-VALIDATED|WRITTEN|UNCHANGED|bytes unchanged|^changed' $R/I.txt)"
  print "证明: Successfully installed graftling-0.5.0 graphtraj-0.1.0；PASS n FAIL 0；agent_swarm package and dist-info gone；graftling 0.5.0；SAME-AS-VALIDATED；settings.local.json WRITTEN-AS-VALIDATED；.mcp.json 与 config.json UNCHANGED（或 V 已列出的变化）。"
  print "$R_HINT"
  print "\n重新进入 Main（普通 Terminal）: cd $H && claude --resume $MAIN"
  print "预期对话框: 至多一个插件/hooks 信任框（host_context.mjs 的字节变了），选信任。其它任何框选拒绝并告诉 Main。"
  print "升级前未确认的通知可能再送达一次（394 Handed on）：只在这一次 resume 时可接受，记下来。"
  next "zsh $THIS M" ;;

M) cat <<EOF | tee $R/M-prompts.txt
[M] 在重新进入的 Claude Code Main（Session $MAIN）里逐条粘贴，一次一条。每条无对话框；Main 把原始结果存到 $R/M-<字母>.txt。

[a 插件、工具、已批准的 .mcp.json] 先输入 /agents-context ，再粘贴:
Using only the tasks tool: discover. Print the raw list of feature names, and nothing else.
Using only the agents tool: status with no agent. Print the raw result.
  证明: /agents-context 显示 current Session $MAIN、MCP agents/tasks registered；discover 有功能列表；status 有结果。
  然后在另一个 Terminal（Main 保持运行，无对话框）: zsh $THIS Mps

[b 旧记录仍能读（v4/v5 档案）]
Using only the tasks tool: run task_graph with {"task_id":"378"} and session_reports with {"alias":"$OLD_LEADER"}. Print for each only whether it succeeded, the number of tasks and the report names. Do not print report bodies.
  证明: 两个调用都成功；417 的报告名非空。

[c 空闲 Main 被子级完成唤醒且只一次]
Using only the agents tool: create a claude child named "p393a" with configuration "opus_coding_team.advisor" and instruction "Reply with exactly one line: PONG-393-A. Use no tools." Do NOT wait. Print the raw result including the agent id, then end your turn immediately.
  证明: 3 分钟内 Main 被自动唤醒，出现一次 "[GraphTraj notice from … · completed] PONG-393-A"。记下时间与次数（必须 1 次）。Terminal（无对话框）: zsh $THIS inbox ，duplicate ids: 0。
Using only the agents tool: retire the agent whose id the p393a create result returned, by that agent id, and print the raw result.
  证明: 无框，已清退（417 用名字清退被拒，这里用 id）。

[d 新插件已加载：下一次 Main 重启后通知不重复] 这个在 H5 回到 Claude Main 时观察（那是安装后的下一次 Main 重启）。
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
  summary Mps "$(grep -E '^(host|parent|NOT FOUND)' $R/Mps.txt | tail -3)"
  print "证明: host 的 argv 是 $RT/bin/python -m graphtraj.runtimes.claude.host serve --config $HOSTCFG；parent 是 claude --resume $MAIN；host.log 有 outcome=ok。" ;;

inbox) print "[inbox] Main 的通知队列（Claude、Pi、DSH Main 各一个文件）。无对话框。只读。"
  { for f in $INBOX/*.jsonl(N); do print "== ${f:t}"; tree inbox $f; done; } 2>&1 | tee -a $R/inbox.txt
  print "Claude Main $MAIN 的文件: $(inbox_key "claude:$MAIN").jsonl"
  summary inbox "$(grep -E '^(==|duplicate|records)' $R/inbox.txt | tail -12)"
  print "证明: 每个文件 duplicate ids: 0（无 id 的旧记录不参与比较）。" ;;

P) cat <<EOF | tee $R/P-prompts.txt
[P] 真实 Runner 派发，全部派进 Task $TASK_ID（Team 1 active，预算未停）。逐条粘贴到 Claude Main，每条无对话框；Main 把每个原始结果保存到 $R/P-<runtime>.txt。
role 必须是 role_tree 的根；内联 role 用允许的根引用，不改 roles.yml。Codex 一律 $CODEX_MODEL（用户指示，roles.yml 的 gpt-6-astra 连接不用）。

[claude，433 收紧子级环境后仍能登录] opus_coding_team.advisor 是配置好的根。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Reply with exactly one line: PONG-393-CLAUDE. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: launch_status 不是 failed；Main 被唤醒一次，completed 通知里有 PONG-393-CLAUDE。若失败且错误是未登录，把 0.txt 的 credential-like names 一行带回：需要显式放行（roles.yml pass_env）的就是其中 Claude 登录用的那个。

[codex] 内联 role，连接 codex/openai/$CODEX_MODEL。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":{"pi_dsh_trial.merge_resolver":{"connection":"codex/openai/$CODEX_MODEL"}},"instruction":"Reply with exactly one line: PONG-393-CODEX. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: 同上，PONG-393-CODEX。

[dsh，定义 4a] 417 时被拒（420 已修）。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":{"pi_dsh_trial.merge_resolver":{"connection":"dsh/deepseek-official/deepseek-flash","worktree_access":"read"}},"instruction":"Reply with exactly one line: PONG-393-DSH. Use no tools."}]}. Print the raw result and end your turn. Do not wait.
  证明: 同上，PONG-393-DSH。若拒绝，原始错误带回（417 的文字来自 runtimes/dsh/adapter.py 的 which 检查）。

[pi，定义 4b / Task 425：附加自己 Worktree 内的文件]
$(pi_prompt)
  证明: 回复首行是 PONG-393-PI: 加上该 Worktree 中 AGENTS.md 的第一行；之后 Main 粘贴:
Using only the tasks tool: session_read for the Pi probe's session (the execution.session_id from its swarm result) with limit 20. Print only whether any attachment or read result is marked missing, and the file path it names.
  证明: 没有 missing。

[清理] 每个结束的探针各一条（Leader 与 Engineer 不清退）:
Using only the agents tool: retire the probe agent by the agent id its swarm result returned (not by its alias), and print the raw result. Repeat for each of the four probes.
  证明: 无框；task_members 中它们是 retired。

[Terminal，无对话框] zsh $THIS inbox ，duplicate ids: 0。
EOF
  next "zsh $THIS F" ;;

F) cat <<EOF | tee $R/F-prompts.txt
[F] 仍在 Claude Main。F10 后半段与预算通知（定义第 2 项）。每条无对话框。

[F10 后半段] 来源 375 必需结果 1：Driver 启动的子级以失败、中断或出错结束时立即送达父级；之后的汇总轮次（"Direct child execution results"）只引用，不再重发这条结束。
父级必须是由 Driver 启动的 Agent（不是 Main），所以由 Main 派一个 Claude 探针当父级:
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Using only the agents tool: create two claude children with configuration opus_coding_team.advisor: f10-stop with instruction 'Run the shell command sleep 600, then reply DONE.' and f10-ok with instruction 'Reply with exactly one line: PONG-F10-OK. Use no tools.' Then stop f10-stop by the agent id create returned. Wait until both have ended. Then reply with a list of every parent input you received, in order, each with its event (interrupted, failed, completed), the child alias and execution id, and say whether the f10-stop end appeared more than once, including inside any 'Direct child execution results' summary."}]}. Print the raw result and end your turn. Do not wait.
  证明: 探针的回复里 f10-stop 的结束只出现一次（立即送达），汇总里只有 f10-ok 的完成或对 f10-stop 的引用，没有第二次送达。之后清退探针（按 swarm 返回的 agent id）。
  不能通过用户步骤直接看到的: 子级的结束在父级 Session 里的确切位置；探针转述即是观察，Main 可用 session_read 读探针 Session 复核。

[预算通知送达带计时的 Leader] Task $TASK_ID 的预算 80 分钟（execution-budget.yml）。到点时 Leader 会收到 "System notice: Elapsed time: … The planned budget of 1h 20m has been reached."
  Terminal（无对话框）: grep -A3 '^notifications' $H/.graphtraj/core/state/tasks/$TASK/execution-budget.yml
  然后发给 Leader:
Using only the agents tool: send to agent "$LEADER" the message "Reply with one line: did you receive a System notice or System reminder about elapsed time in this Session, and its exact text?" Print the raw result and end your turn. Do not wait.
  证明: notifications 非空，Leader 转述的文字与之对应且只一次。若还没到 80 分钟，这一条留到 H5 之后再做。
EOF
  next "zsh $THIS H1" ;;

H1) cat <<EOF | tee $R/H1-prompts.txt
[H1] 换 Main 前的准备（Claude Main 里）。目标：在换到 Codex 之前，让一条通知排在 Claude Main 的队列里（Task 397）。无对话框。
Using only the agents tool: create a claude child named "h397" with configuration "opus_coding_team.advisor" and instruction "Run the shell command sleep 90, then reply with exactly one line: PONG-397. Use no tools other than that one command." Do NOT wait. Print the raw result including the agent id, then end your turn.
  然后立刻在 Main 里输入 /exit（不要等 h397 完成）。90 秒后 h397 的完成通知排在 Claude Main 的队列里。
  Terminal（无对话框）: zsh $THIS inbox  → Claude Main 文件 $(inbox_key "claude:$MAIN").jsonl 里有 h397 的 completed，记下它的 id。
注意: 这一步结束 Claude Main（换人）。回来的方法: $(back_to_main)
EOF
  next "zsh $THIS H2" ;;

H2) print "[H2] 换到 Codex Main（$CODEX_MODEL）。本步只打印；你在 Terminal 自己启动 Codex。"
  print "这会把 Main 换成 Codex。$(back_to_main)"
  cat <<EOF | tee $R/H2-prompts.txt
启动（普通 Terminal）: cd $H && PATH=$RT/bin:\$PATH codex -m $CODEX_MODEL
  预期对话框: 至多一个（Codex 对项目 hooks/MCP 的信任或 hooks 审查），选允许。其它框拒绝并告诉 Main。
  若 0.txt 的 .codex/config.toml 一节显示 MCP 命令仍指向 agent_swarm（改名前的入口），先不要启动，告诉 Main（这是要改的 Harness 根入口文件）。

[f 397: 换人前排队的通知在 Codex Main 上只送达一次] Codex 的 SessionStart 把队列作为 additionalContext 交给模型。第一句粘贴:
Before anything else: quote every GraphTraj notice you were given at session start (alias, event, first line of the message), and say how many times the h397 completion appears. Use no tools.
  证明: h397 completed（PONG-397）出现且只一次。Terminal: zsh $THIS inbox → Claude 文件里这条已被转走，不再待送。

[h 401: Main 创建的根级 Agent 结束时，通知在 Codex Main 上只送达一次]
Using only the graftling agents tool: create a claude child named "h401" with configuration "opus_coding_team.advisor" and instruction "Reply with exactly one line: PONG-401. Use no tools." Do not wait; end your turn.
  证明: Codex Main 收到一次 PONG-401（turn/start 的 toolOutput 推送），不是两次；之后 status 里它的 notification 是 delivered。
Using only the graftling agents tool: status for the agent id the h401 create returned. Print its notification field.

[c 373: 一次执行内的多个原生请求都到达 Main（Codex 作为 Main）]
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Run these two shell commands, one tool call each, in this order: touch /private/tmp/393-req-a and touch /private/tmp/393-req-b. Each needs approval; wait for each answer. Then reply with one line saying which were allowed or denied."}]}. Print the raw result and end your turn.
  证明: Codex Main 依次收到两个原生请求（第二个也到达，这是 373 修的）。两次都选拒绝（Deny），不需要真的写文件。成员回复两条都 denied。
  清退: 用 swarm 结果返回的 agent id 清退这个成员与 h401。
最后在 Codex 里 /exit（或 Ctrl-C 两次）。
EOF
  next "zsh $THIS H3" ;;

H3) print "[H3] 换到 Pi Main。本步只打印。这会把 Main 换成 Pi。$(back_to_main)"
  cat <<EOF | tee $R/H3-prompts.txt
启动（普通 Terminal）: $(pi_main_command)
  预期对话框: 无（Pi 没有原生审查框；请求以 Pi 内的选择出现）。
  若启动后第一条消息看不到 GraphTraj 的通知或 tasks 工具，停下告诉 Main（Pi 的 GraphTraj 扩展入口未在本 Task 实测，见 engineer.md 的 open questions）。

[c 373: Pi 作为 Main] 粘贴:
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Run these two shell commands, one tool call each, in this order: touch /private/tmp/393-req-c and touch /private/tmp/393-req-d. Each needs approval; wait for each answer. Then reply with one line saying which were allowed or denied."}]}. Print the raw result and end your turn.
  证明: 两个请求都以 graftling:agent-communication 自定义消息到达 Pi Main（约 5 秒内）。两次都拒绝。成员回复两条 denied。
  清退: 用返回的 agent id。然后 Ctrl-C 退出 Pi。
  Terminal: zsh $THIS inbox → Pi 的文件 duplicate ids: 0。
EOF
  next "zsh $THIS H4a" ;;

H4a|H4b|H4c) print "[$STEP] 无界面 DSH Main（dsh --profile headless，从 $H 启动，PATH 前置 $RT/bin）。这会把 Main 换成 DSH。$(back_to_main)"
  print "398 的结论: headless DSH 一次只做一件事就退出；退出后到达的通知留在队列，直到用 --session-id 续接，或别的 Claude/Pi/DSH Main 接手队列。"
  print "预期对话框: 无（headless 没有界面；--permission-mode 不改）。DSH 的 GraphTraj 插件形式见 0.txt 的 dsh plugin list；若列表里没有 graphtraj/graftling-dsh，本步的 Main 接续不成立，停下告诉 Main。"
  SID_FILE=$R/H4.session
  case $STEP in
    H4a) MSG="Using only the agents tool: create a claude child named g398 with configuration opus_coding_team.advisor and instruction 'Run the shell command sleep 60, then reply with exactly one line: PONG-398.' Do not wait. Print the agent id it returned and stop."; RESUME=() ;;
    H4b) [[ -s $SID_FILE ]] || { print "没有 H4a 的 session id（$SID_FILE）。先运行 H4a。"; exit 1; }
         MSG="Quote every GraphTraj notice you received at the start of this turn (alias, event), and say how many times g398 appears. Then, using only the tasks tool, execute swarm with arguments {\"tasks\":[{\"task_id\":\"$TASK_ID\",\"role\":\"opus_coding_team.advisor\",\"instruction\":\"Run these two shell commands, one tool call each: touch /private/tmp/393-req-e and touch /private/tmp/393-req-f. Each needs approval. Then reply which were allowed or denied.\"}]}. Print the raw result and stop."; RESUME=(--session-id $(<$SID_FILE)) ;;
    H4c) [[ -s $SID_FILE ]] || { print "没有 H4a 的 session id（$SID_FILE）。先运行 H4a。"; exit 1; }
         MSG="Quote every GraphTraj notice you received at the start of this turn (alias, event, request text), and say how many permission requests from the swarm member arrived and whether any appears twice. Deny every pending request. Then stop."; RESUME=(--session-id $(<$SID_FILE)) ;;
  esac
  print -r -- "dsh 输入: $MSG" | tee -a $R/$STEP.txt
  (cd $H && PATH=$RT/bin:$PATH dsh --profile headless --json $RESUME "$MSG") 2>&1 | tee $R/$STEP.json | tail -40
  if [[ $STEP == H4a ]]; then
    $CONDA -I -c 'import json,sys
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    s = d.get("session") or d.get("sessionId") or d.get("session_id")
    s = s.get("id") if isinstance(s, dict) else s
    if isinstance(s, str) and s: print(s); break' $R/H4a.json > $SID_FILE
    [[ -s $SID_FILE ]] && print "DSH Main session id: $(<$SID_FILE)" || print "没在 --json 输出里找到 session id；把 $R/H4a.json 交给 Main。"
  fi
  case $STEP in
    H4a) summary H4a "$(tail -3 $R/H4a.json)" "session id: $(<$SID_FILE 2>/dev/null)"
         print "证明: 输出里有 g398 的 agent id，进程已退出。等 90 秒，再运行 zsh $THIS inbox：DSH 文件里有 g398 completed、未确认（与 398 一致：退出后不送达）。"
         next "zsh $THIS inbox   （90 秒后），然后  zsh $THIS H4b" ;;
    H4b) summary H4b "$(tail -5 $R/H4b.json)"
         print "证明: g398 在续接时送达且只一次（398 的结论）；swarm 成员已派出。等 2 分钟（成员发出两个请求后，headless 已退出，请求排队）。"
         next "zsh $THIS H4c   （2 分钟后）" ;;
    H4c) summary H4c "$(tail -5 $R/H4c.json)"
         print "证明（373，DSH 作为 Main）: 两个请求都在，各一次。若 headless 无法回答请求，在 H5 的 Claude Main 里拒绝它们。"
         next "zsh $THIS H5" ;;
  esac ;;

H5) print "[H5] 回到这个 Claude Main。这是安装后的下一次 Main 重启（定义 4c）。"
  cat <<EOF | tee $R/H5-prompts.txt
启动（普通 Terminal）: cd $H && claude --resume $MAIN
  预期对话框: 无（插件在 I 之后的 resume 已被信任）。若出现插件信任框，选信任并告诉 Main（说明插件字节又变了）。
第一句粘贴:
Before anything else: list every GraphTraj notice delivered to you since this resume (alias, event), and say whether any notice you already saw before (PONG-393-A, the P probes, h397, h401, g398) appears again. Then, using only the agents tool, status with no agent; retire, by agent id, every probe from this adoption that is still not retired.
  证明: 已见过的通知没有再出现（新插件已加载且确认了送达）；DSH/Pi 期间排队的通知只出现一次；之后 zsh $THIS inbox，duplicate ids: 0。
EOF
  next "zsh $THIS done" ;;

done) print "[done] 记录结束状态。无对话框。只读。"
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling agent-swarm 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS' $R/done-verify.txt
    shasum -a 256 $ENTRIES; tree versions $SESS
    if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then print "files in raw containing the key: $(grep -rlF -- "$DEEPSEEK_API_KEY" $R 2>/dev/null | wc -l | tr -d ' ')"; fi
    ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^Version|archives=|含密钥|containing the key' $R/done.txt)"
  print "证明: PASS n FAIL 0；raw 中含密钥的文件数 0。把 $R 的路径交给 Main。$R_HINT" ;;

R) print "[R] 回退到安装前（agent-swarm 0.2.4 + graphtraj 1a648ca）。本步无对话框。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  guard || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|old reader failures|left:|^Version' $R/R.txt)"
    print "证明: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；old reader failures: 0；agent-swarm 0.2.4；pip check 通过。"
    print "然后: cd $H && claude --resume $MAIN （插件字节又变了，至多一个插件信任框，选信任；其它框拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（见上面的 DIFF、PROBLEM、OLD-READ-FAIL 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac
