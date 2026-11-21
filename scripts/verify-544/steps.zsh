#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 544 — Codex Main's sent agents message as a collapsible MCP card. Real-host check in an ISOLATED project
# (/private/tmp/vproject-544); production is never touched: nothing is written to ~/.codex, the Codex install,
# dotfiles, .venv-runtime or the Harness's .codex (only the isolated project's own .codex).
#   zsh <absolute path>/steps.zsh <step>
# Phase A (probe, no product change): 00 → T [USER: folder trust] → P [USER: one prompt, 2 screenshots] → Pr
# Phase B (candidate = Worktree HEAD + graftling dev 6794ce02): B → V [USER: one prompt, 2 screenshots] → Vr;
#          G (full suite, background) → Gt (focused) → GR (read only)
# Only rehearse.zsh sets VERIFY544_*. The defaults are the real paths.
set -u
setopt no_bg_nice
SD=${0:A:h}; THIS=${0:A}
H=${VERIFY544_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
WT=${VERIFY544_WT:-$H/.graphtraj/core/worktrees/544-codex-sent-message-collapsible-card}
BASE=${VERIFY544_BASE:-$H/tmp/544}                   # scratch venvs and wheels
W=${VERIFY544_W:-$BASE/realhost}                     # raw output + the USER's screenshots
RT=${VERIFY544_RT:-$H/.venv-runtime}                  # production: only read
VPROJECT=${VERIFY544_VPROJECT:-/private/tmp/vproject-544}
CODEX_HOME_USED=${VERIFY544_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}   # only read (Pr/Vr read rollouts)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CODEX_MODEL=gpt-6-luna
path=(/opt/homebrew/bin $HOME/.local/bin ${path:#$RT/bin})

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
codex_bin() { [[ -n ${VERIFY544_CODEX:-} ]] && { print -r -- $VERIFY544_CODEX; return; }; command -v codex; }
cv() { local C=$(codex_bin); print -r -- "codex: $C -> ${C:A} | version: $($C --version 2>&1 | head -1)"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
bounded() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
isolation() {  # git top level is the project; no AGENTS.md/CLAUDE.md at or above it (Codex/Claude read those)
  $CONDA -I - $VPROJECT <<'ISO'
import subprocess, sys
from pathlib import Path
project = Path(sys.argv[1]).resolve()
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'CLAUDE.local.md') if (p / n).exists()]
print(f'git top level: {top} | AGENTS.md/CLAUDE.md at or above: {upward or "none"}')
ok = bool(top) and Path(top).resolve() == project and not upward
print('isolation:', 'OK' if ok else 'NOT OK'); sys.exit(0 if ok else 1)
ISO
}
vproject_init() {
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 544 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=544 -c user.email=544@invalid commit -qm "Initial source" || return 1
  fi
}
ask_model() {
  local C=$(codex_bin)
  print "codex login: $(clean $C login status 2>&1 | sed -E 's/ - .*//' | head -1)"
  print -r -- "Reply with exactly one line: CODEX-544-OK followed by your model name. Use no tool." > $W/00-prompt.txt
  (cd $VPROJECT && bounded 300 $C exec -m $CODEX_MODEL --sandbox read-only - < $W/00-prompt.txt > $W/00-codex.txt 2>&1)
  print "codex exec rc=$? (142 = 300 s limit) | header model: $(grep -m1 -E '^model: ' $W/00-codex.txt | cut -c8-) | answer: $(grep -E '^CODEX-544-OK' $W/00-codex.txt | tail -1)"
  grep -qE '^CODEX-544-OK' $W/00-codex.txt && grep -qE "^model: $CODEX_MODEL" $W/00-codex.txt || { tail -5 $W/00-codex.txt; return 1; }
}
PROBE_PROMPT='call probe.send_note with to=member-x and a 5-line message including **bold**, then tell me exactly what the tool returned'

step_00() {
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} | running: $THIS"
  say "Codex version (the user's install, only run)"; cv
  say "isolated project $VPROJECT: own git, nothing at or above it"
  vproject_init && isolation || { print "STOP: isolation NOT OK"; return 1; }
  [[ -e $VPROJECT/.codex ]] && print "note: $VPROJECT/.codex exists already: $(ls $VPROJECT/.codex | tr '\n' ' ')"
  say "codex exec one-line answer from the isolated project (expect model $CODEX_MODEL, logged in; limit 300 s)"
  ask_model || { print "STOP: answer check failed (above). If it is a login problem: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
}

step_T() {
  [[ -d $VPROJECT/.git ]] || { print "没有 $VPROJECT，先运行 00。"; return 1; }
  [[ -e $VPROJECT/.codex ]] && print "note: $VPROJECT/.codex already exists; T is meant to run before it. If a further dialog appears, Esc and tell Main its title."
  say "USER（真实交互式 Codex，只做文件夹信任，不输入提示）"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) 预期对话框（唯一一个，Codex 自己的）: 'Do you trust the contents of this directory?' → 选 Yes。其它任何框按 Esc 并把标题告诉 Main。"
  print "   这个选择由 Codex 自己记录在用户的 Codex 配置里；本脚本不向那里写任何东西（只写 $VPROJECT/.codex）。"
  print "3) 不输入任何提示，直接输入 /exit。"
  print "成功可见: Codex 启动到输入框，/exit 后回到 shell。"
}

step_P() {
  [[ -d $VPROJECT/.git ]] || { print "没有 $VPROJECT，先运行 00 和 T。"; return 1; }
  say "the isolated project's OWN .codex/config.toml: ONLY the probe MCP server (tool pre-approved); no hooks.json"
  mkdir -p $VPROJECT/.codex || return 1
  rm -f $VPROJECT/.codex/hooks.json
  cp $SD/probe544.py $BASE/probe544.py || return 1
  print -r -- "[mcp_servers.probe]
command = \"$CONDA\"
args = [\"-I\", \"$BASE/probe544.py\"]
default_tools_approval_mode = \"approve\"" > $VPROJECT/.codex/config.toml
  print "wrote $VPROJECT/.codex/config.toml:"; sed 's/^/    /' $VPROJECT/.codex/config.toml
  say "probe server answers initialize + tools/call (one local JSON-RPC exchange, no model)"
  print -r -- '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"send_note","arguments":{"to":"member-x","message":"hi"}}}' \
    | $CONDA -I $BASE/probe544.py > $W/P-selftest.jsonl || return 1
  $CONDA -I -c 'import json, sys
r = [json.loads(l) for l in open(sys.argv[1])]
res = r[1]["result"]; text = res["content"][0]["text"]
print("probe text tail:", text.split("\n")[-3:], "| structuredContent:", res["structuredContent"])
ok = r[0]["result"]["serverInfo"]["name"] == "probe" and text.split("\n")[-3:] == ["status: sent", "from: main", "→ member-x [probe-id]"] and res["structuredContent"] == {"ok": True, "marker": "PROBE-SC-544"}
print("CHECK probe server self-test:", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)' $W/P-selftest.jsonl || return 1
  date +%s > $W/P.start
  print -r -- "$PROBE_PROMPT" > $W/P-prompt.txt
  say "USER（真实交互式 Codex，Main 做不了）— 探针截图"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) 预期对话框: 无（文件夹已在 T 信任；没有 hooks.json；工具已预先批准）。若出现 MCP 工具批准框 → 选允许（Allow/Approve），并把标题告诉 Main。其它任何框按 Esc 并报告标题。"
  print "3) 粘贴下面这一行提示（也在 $W/P-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/P-prompt.txt; print -- "------------------"
  print "4) 截两张图:"
  print -r -- "   (i)  折叠卡片: 'Called probe.send_note' 及其下方的行 → $W/probe-collapsed.png"
  print -r -- "   (ii) 点 '+ Show details' 展开后 → $W/probe-expanded.png"
  print "5) 复制模型这一轮的回复文字交给 Main，然后输入 /exit。"
  print "PASS（截图）= 折叠态恰好 3 行: 'status: sent'、'from: main'、'→ member-x [probe-id]'；展开态有参数 JSON 一行和完整正文（含 '## Probe note PROBE-BODY-544'，'**bold**' 与反引号按原样显示）。"
  print "FAIL = 折叠态多于或少于 3 行，或展开没有完整正文。"
  next "zsh $THIS Pr    （USER 截图并 /exit 之后）"
}

step_Pr() {
  [[ -f $W/P.start ]] || { print "no P stamp in $W: run P first"; return 1; }
  say "the probe session's rollout under $CODEX_HOME_USED/sessions (cwd $VPROJECT, changed after P's stamp $(cat $W/P.start); read only)"
  $CONDA -I $SD/pr544.py $CODEX_HOME_USED/sessions $VPROJECT $(cat $W/P.start)
}

# ---------------- Phase B: the candidate (Worktree HEAD) + graftling dev $GLBASE ----------------
GTBASE=f754d3a955fe7740fa11b54f194d19fb70d2d438 # GraphTraj dev the Worktree branched from (checked in B)
GLDEV=${VERIFY544_GLDEV:-$H/.graphtraj/core/worktrees/graftling-dev}
GLBASE=6794ce02b6210ec88837437affb8d7b525612804  # graftling dev; 544 changes no graftling file
GTFILES=src/graphtraj/interfaces/mcp.py,src/graphtraj/runtimes/codex/display_hook.py,tests/test_codex_agent_display.py,tests/test_codex_agents_card_544.py
ACTIVE=$BASE/active
CHILD=$(cat $W/child-name 2>/dev/null || print n544)
SD535=${SD:h}/verify-535                             # 535's accepted helpers, used unchanged
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
FOCUSED=(tests/test_codex_agents_card_544.py tests/test_codex_agent_display.py tests/test_agents_native_codex.py
         tests/test_mcp_host_tools.py tests/test_agents_mcp_bridge.py tests/test_current_host_events.py
         tests/test_codex_main_root_notice_401.py tests/test_agents_native_claude.py tests/test_stop_instruction.py)
site_of() { local s=($1/lib/python*/site-packages(N)); print -r -- ${s[1]}; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local S=$(site_of $RT) D=$(site_of $1)
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/
}
graphtraj_init() {  # the isolated project's own .graphtraj (setup by the candidate)
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup) || return 1
  fi
}
step_B() {
  local dirty=$(git -C $WT status --porcelain -- src tests plugins pyproject.toml)
  [[ -z $dirty ]] || { print "STOP: uncommitted GraphTraj product changes: $dirty"; return 1; }
  git -C $WT merge-base --is-ancestor $GTBASE HEAD || { print "STOP: $GTBASE is not an ancestor of HEAD"; return 1; }
  local prod=$(git -C $WT diff --name-only $GTBASE HEAD -- src tests plugins pyproject.toml)
  print "GraphTraj product files changed $GTBASE..HEAD: ${(j:, :)${(f)prod}}"
  [[ ${(j:,:)${(f)prod}} == $GTFILES ]] || { print "STOP: expected exactly $GTFILES"; return 1; }
  print "CHECK 544 product diff is exactly the 544 files: PASS"
  local L=$BASE/cand C=$(git -C $WT rev-parse HEAD); rm -rf $L; mkdir -p $L/wheels $L/gl-src $L/gt-src
  git -C $GLDEV cat-file -e $GLBASE^{commit} || { print "STOP: graftling $GLBASE is not in $GLDEV"; return 1; }
  print "GraphTraj $(git -C $WT log -1 --format='%H %s' $C)"; print "graftling $(git -C $GLDEV log -1 --format='%H %s' $GLBASE)"
  git -C $GLDEV archive $GLBASE | tar -x -C $L/gl-src && git -C $WT archive $C | tar -x -C $L/gt-src || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $L/wheels $L/gl-src/src/graftling > /dev/null || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $L/wheels $L/gt-src > /dev/null || return 1
  (cd $L/wheels && shasum -a 256 *.whl | tee SHA256SUMS)
  $CONDA -m venv $L/venv && $L/venv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $L/wheels/*.whl && copy_deps $L/venv || return 1
  $L/venv/bin/python -m pip check --disable-pip-version-check; print "venv pip check rc=$?"
  print -r -- "$C $GLBASE" > $L/commits
  (cd $BASE && $L/venv/bin/python -I -c 'import graftling, graphtraj.interfaces.mcp as m; print("graftling", graftling.__version__, graftling.__file__); print("graphtraj", m.__file__, "| has _agents_card:", hasattr(m, "_agents_card"))')
}
v_prompt() {
  cat <<EOF
Use only the agents tool of the graphtraj MCP server (not Codex's own subagents) for this check of how agents messages are shown.
1. Call agents with {"action":"discover"}, then describe "create" and "wait", so you know their arguments.
2. Create ONE child with only these selections: runtime claude, name $CHILD. Pass NO model, configuration, preset, connection or reasoning effort (the project's one role 'claude' supplies them). If create is refused, report the exact error text and stop; do not retry with other settings. Its instruction is exactly this Markdown:

## Task 544 display check

Reply **without using any tool**, in Markdown, with:
- a level-2 heading \`## Reply from $CHILD\`
- a bullet list of two items, one holding an inline code span like \`agents\`
- one quoted line starting with \`> \`

Then stop.

3. Call agents wait for $CHILD (up to 300 seconds) until its reply arrives.
4. Then call agents send to $CHILD with exactly this Markdown message, and again call agents wait for it:

### Second message

1. Answer again in Markdown: a heading, a two-item list and a \`code span\`.
2. Use no tool.

5. Say DONE-544 and stop. Do not retire the child.
EOF
}
step_V() {
  local L=$BASE/cand
  [[ -x $L/venv/bin/graphtraj-mcp ]] || { print "没有 $L/venv，先运行 B。"; return 1; }
  rm -f $ACTIVE && ln -s $L $ACTIVE || return 1
  say "$ACTIVE -> $L ($(cat $L/commits)): the isolated project runs this graphtraj + graftling"
  vproject_init && graphtraj_init $ACTIVE/venv/bin/graphtraj && isolation || { print "STOP: isolation NOT OK"; return 1; }
  say "the project's OWN .codex (535's codex_files535.py, unchanged): config.toml = graphtraj MCP only (the probe server is gone); hooks.json = SessionStart stop_hook + PostToolUse/Stop display_hook"
  (cd $VPROJECT && clean $ACTIVE/venv/bin/python -I $SD535/codex_files535.py $VPROJECT $ACTIVE/venv) || return 1
  sed 's/^/    /' $VPROJECT/.codex/config.toml $VPROJECT/.codex/hooks.json
  say "child role: ONE role 'claude' (535's roles535.py: claude/anthropic/opus-5_5, effort high, permission_mode auto), resolved without a model"
  (cd $BASE && $ACTIVE/venv/bin/python -I $SD535/roles535.py $VPROJECT) || { print "STOP: the child role does not resolve (above)"; return 1; }
  local MS=$VPROJECT/.graphtraj/runner/main-sessions
  if [[ -d $MS ]]; then print "removing stale Main state $MS"; rm -rf $MS || return 1; else print "no stale Main state ($MS absent)"; fi
  CHILD=n544$(date +%H%M); print -r -- $CHILD > $W/child-name
  print "child name for this run: $CHILD"
  date +%s > $W/V.start
  v_prompt > $W/V-prompt.txt
  say "USER（真实交互式 Codex，Main 做不了）— 修改后截图"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) 预期对话框（至多一个，Codex 自己的）: $VPROJECT/.codex/hooks.json 的 hook 审核 → approve。若 hooks.json 以前已批准则无。其它任何框按 Esc 并把标题告诉 Main。"
  print "   启动后若没有 graphtraj 工具: /exit 再运行同一命令一次。"
  print "3) 粘贴下面整段提示（也在 $W/V-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/V-prompt.txt; print -- "------------------"
  print "4) 截两张图（发给 $CHILD 的 'Called graphtraj.agents' 卡片，create 或 send 那张）:"
  print -r -- "   (i)  折叠态 → $W/after-collapsed.png   （PASS: 'Called graphtraj.agents' 下只有收件人行 '→ $CHILD [agent-…]'（send 若带回复，其上为回复文字与 '← $CHILD replied'）；不出现消息正文；没有 'Hook · agents →' 块）"
  print -r -- "   (ii) '+ Show details' 展开 → $W/after-expanded.png   （PASS: 参数行（一行 JSON）里有消息原文；下面仍只有收件人行，没有第二份正文）"
  print "   wait 的卡片不在本 Task 范围内，仍是 YAML。"
  print "5) 看到 DONE-544 后输入 /exit，把截图交给 Main。"
  next "zsh $THIS Vr    （USER /exit 之后）"
}
step_Vr() {
  [[ -f $W/V.start ]] || { print "no V stamp in $W: run V first"; return 1; }
  say "the Main's rollout (continuity claim after V's stamp $(cat $W/V.start)) under $CODEX_HOME_USED/sessions (read only), child $CHILD"
  $CONDA -I $SD/vr544.py $CODEX_HOME_USED/sessions $VPROJECT $CHILD $(cat $W/V.start)
}
check_tmp() {
  local PT=${TMPDIR:-/tmp}; PT=${PT:A}
  [[ $PT == ${H:A} || $PT == ${H:A}/* ]] && { print "STOP: TMPDIR $PT is inside the Harness"; return 1; }
  print -r -- "pytest temp: TMPDIR=$PT (outside the Harness)"
}
g_venv() {  # conda --system-site-packages + click/yaml/websockets + B's graftling wheel + this Worktree editable
  V=$BASE/venv-g
  local N=$BASE/cand/wheels
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 的 wheel，先运行 B。"; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  rm -rf $V && $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) (Worktree editable) | graftling wheel from git archive $GLBASE"
}
new_runtmp() {
  local PT=${TMPDIR:-/tmp}; RUNTMP=${PT:A}/verify-544-$1-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
  print -r -- "pytest temp root (outside the Harness): $RUNTMP"
}
classify() {
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}
step_G() {
  setopt local_options no_bg_nice
  check_tmp || return 1
  local V RUNTMP; g_venv || return 1; new_runtmp G
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)')
  local R=$W/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP | candidate $(git -C $WT rev-parse HEAD) | graftling $GLBASE" > $R/run.txt
  if [[ -n ${VERIFY544_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY544_TESTS (plain pytest, same venv, temp root and exit line)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY544_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  else
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
    print "started in the background at $(date +%T) (~25 min); $R/suite.txt ends with 'exit=N'"
  fi
  print -r -- $R > $W/G-latest
  print "成功可见: graphtraj 路径在 $WT/src 下，'graftling ... graftling/__init__.py'，'started in the background'。"
  next "zsh $THIS Gt    （在 G 的 suite.txt 出现 exit= 之后运行：test_mcp_host_tools 有 30 秒的投递轮询，与全套并行时负载会使其超时），然后 zsh $THIS GR"
}
step_Gt() {
  check_tmp || return 1
  local V RUNTMP; g_venv || return 1; new_runtmp Gt
  local R=$W/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt $FOCUSED > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  tail -3 $R/suite.txt; classify $R/suite.txt
  print -r -- $R > $W/Gt-latest
  print "成功可见: 'N passed' 且 exit=0，'(no FAILED/ERROR lines)'。"
  next "zsh $THIS GR    （G 的 suite.txt 以 exit= 结尾之后）"
}
step_GR() {
  local g=$(cat $W/G-latest 2>/dev/null) t=$(cat $W/Gt-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print "no G result yet: zsh $THIS G"; return 1; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify $t/suite.txt; }
  print "成功可见: G 'exit=0' 或只有 'known (516)' 行；G 与 Gt 无 'NEW' 行。"
}

mkdir -p $W $BASE
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟（一次 codex exec）。成功可见: 'isolation: OK' 与 'answer: CODEX-544-OK gpt-6-luna'。"; logged $W/00.txt step_00 && next "zsh $THIS T    （USER 只做文件夹信任）" ;;
  T)  print "[T] USER. 在真实 codex 里只信任隔离项目文件夹，然后 /exit。对话框: 1 个（文件夹信任 → Yes）。<1 分钟。"; logged $W/T.txt step_T && next "zsh $THIS P    （USER 完成 T 之后）" ;;
  P)  print "[P] Main 写探针配置并自测，然后 USER 在真实 codex 里输入一条提示并截两张图。对话框: Main 无；USER 预期无。一轮模型调用。成功可见: 'CHECK probe server self-test: PASS'。"; logged $W/P.txt step_P ;;
  Pr) print "[Pr] Main. 只读探针会话的 rollout。对话框: 无。<10 秒。成功可见: 'CHECK 544 probe model input: PASS'。"; logged $W/Pr.txt step_Pr ;;
  B)  print "[B] Main. 核对 544 改动文件并构建候选 wheel 与 venv（$BASE/cand）。对话框: 无。约 1 分钟。成功可见: 'CHECK 544 product diff ...: PASS'、'venv pip check rc=0'、'has _agents_card: True'。"; logged $W/B.txt step_B && next "zsh $THIS G    （后台立即返回；G 用自己的 venv-g，与 V 的 cand 互不影响），然后 zsh $THIS V（USER 会话可与 G 同时进行）" ;;
  V)  print "[V] Main 准备隔离项目（候选），然后 USER 在真实 codex 里操作一次（修改后截图）。对话框: Main 无；USER 至多 1 个（hook 审核 → approve）。"; logged $W/V.txt step_V ;;
  Vr) print "[Vr] Main. 只读 USER 那次会话的 rollout。对话框: 无。<10 秒。成功可见: 'CHECK 544 rollout: PASS'。"; logged $W/Vr.txt step_Vr ;;
  G)  print "[G] Main. GraphTraj 全套测试（6 分片，后台约 25 分钟）。对话框: 无。立即返回。"; logged $W/G.txt step_G ;;
  Gt) print "[Gt] Main. 544 相关测试（前台约 3 分钟）。对话框: 无。"; logged $W/Gt.txt step_Gt ;;
  GR) print "[GR] Main. 只读 G 与 Gt 结果。对话框: 无。<10 秒。"; logged $W/GR.txt step_GR ;;
  *)  print "usage: zsh $THIS 00|T|P|Pr|B|V|Vr|G|Gt|GR   (A: 00 → T (USER trust) → P (USER) → Pr;  B: B → V (USER) → Vr; G → Gt → GR)"; next "zsh $THIS 00" ;;
esac
