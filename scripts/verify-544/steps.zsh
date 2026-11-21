#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 544 — Codex Main's sent agents message as a collapsible MCP card. Real-host check in an ISOLATED project
# (/private/tmp/vproject-544); production is never touched: nothing is written to ~/.codex, the Codex install,
# dotfiles, .venv-runtime or the Harness's .codex (only the isolated project's own .codex).
#   zsh <absolute path>/steps.zsh <step>
# Phase A (probe, no product change): 00 → T [USER: folder trust] → P [USER: one prompt, 2 screenshots] → Pr
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

mkdir -p $W $BASE
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟（一次 codex exec）。成功可见: 'isolation: OK' 与 'answer: CODEX-544-OK gpt-6-luna'。"; logged $W/00.txt step_00 && next "zsh $THIS T    （USER 只做文件夹信任）" ;;
  T)  print "[T] USER. 在真实 codex 里只信任隔离项目文件夹，然后 /exit。对话框: 1 个（文件夹信任 → Yes）。<1 分钟。"; logged $W/T.txt step_T && next "zsh $THIS P    （USER 完成 T 之后）" ;;
  P)  print "[P] Main 写探针配置并自测，然后 USER 在真实 codex 里输入一条提示并截两张图。对话框: Main 无；USER 预期无。一轮模型调用。成功可见: 'CHECK probe server self-test: PASS'。"; logged $W/P.txt step_P ;;
  Pr) print "[Pr] Main. 只读探针会话的 rollout。对话框: 无。<10 秒。成功可见: 'CHECK 544 probe model input: PASS'。"; logged $W/Pr.txt step_Pr ;;
  *)  print "usage: zsh $THIS 00|T|P|Pr   (order: 00 → T (USER trust) → P (USER prompt + screenshots) → Pr)"; next "zsh $THIS 00" ;;
esac
