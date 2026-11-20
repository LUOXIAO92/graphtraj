#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 533 — Claude Code Main shows agents traffic as who + Markdown content. Real-host check in an ISOLATED project
# (/private/tmp/vproject-533) with wheels built from the exact candidate commits; production is never touched:
# no install into .venv-runtime, no change to the Harness's .claude, ~/.claude or dotfiles.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V → [USER: real interactive claude in the isolated project, paste the prompt, 2 screenshots] → Vr
#        G (full suites, background, any time after B; no Vc/V meanwhile) → GR (read only)
# Candidates: GraphTraj = this Worktree's HEAD (533 changes exactly $GTFILES: B checks
# `git diff --name-only $GTBASE HEAD -- src tests plugins pyproject.toml`); graftling = commit $GLC of the clone
# $GLREPO (branch agent/533-claude-main-agents-message-display, based on graftling dev 4a002129 = v0.6.2).
# Only rehearse.zsh sets VERIFY533_*. The defaults are the real paths.
set -u
setopt no_bg_nice   # background suites must not try to renice themselves (refused in a sandbox)
SD=${0:A:h}; THIS=${0:A}
H=${VERIFY533_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
WT=${VERIFY533_WT:-$H/.graphtraj/core/worktrees/533-claude-main-agents-message-display}
GLREPO=${VERIFY533_GLREPO:-$WT/.scratch/graftling}    # untracked clone (its git dir: $WT/.scratch/graftling-git)
GLC=${VERIFY533_GLC:-f67d147a222d7db214ecad14d24809debad999a4}
GTFILES=src/graphtraj/runtimes/claude/host.py,tests/test_claude_main_notice_text_533.py   # 533's GraphTraj product change
GTBASE=27029f96a92d001eb1e9da6e7dda25bfa34c1777      # dev head the Worktree branched from (532's adoption scripts)
BASE=${VERIFY533_BASE:-$H/tmp/533}                     # Main created it; scratch venvs and wheels
W=${VERIFY533_W:-$H/.graphtraj/core/state/tasks/533-claude-main-agents-message-display/realhost/533}   # raw output
RT=${VERIFY533_RT:-$H/.venv-runtime}                   # production: only read (click/yaml/websockets copied out)
VPROJECT=${VERIFY533_VPROJECT:-/private/tmp/vproject-533}
PROJECTS=${VERIFY533_PROJECTS:-$HOME/.claude/projects}
ISO=$SD/../verify-common/claude_isolation.py
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
MINCC=2.1.314
CHILD=n533
N=$BASE/wheels; VV=$BASE/venv; GLSRC=$BASE/gl-src; GTSRC=$BASE/gt-src

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
cv() { local C=$(claude_bin); print -r -- "claude: $C -> ${C:A} | version: $($C --version 2>&1 | head -1)"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
site_of() { local s=($1/lib/python*/site-packages(N)); print -r -- ${s[1]}; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local S=$(site_of $RT) D=$(site_of $1)
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/
}
version_ok() { $CONDA -I -c 'import re, sys
v = re.match(r"(\d+)\.(\d+)\.(\d+)", sys.argv[1]); m = tuple(map(int, sys.argv[2].split(".")))
sys.exit(0 if v and tuple(map(int, v.groups())) >= m else 1)' "$1" $MINCC; }
vsettings() { $CONDA -I $ISO settings $H $VPROJECT; }
isolation() {  # 465's check: graphtraj root and git top level are the project; no CLAUDE.md at or above it
  $1 -I - $VPROJECT <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('CLAUDE.md', 'CLAUDE.local.md') if (p / n).exists()]
print(f'graphtraj project root: {root} | git top level: {top} | CLAUDE.md at or above: {upward or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward
print('isolation:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
}
vproject_init() {  # $1 = graphtraj executable used for setup
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 533 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=533 -c user.email=533@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup) || return 1
  fi
  vsettings
}
ask_model() {  # one real claude -p answer from the isolated project (489's check: tag, no Harness AGENTS.md, no echo)
  local C=$(claude_bin); $CONDA -I $ISO prompt 533-OK > $W/00-prompt.txt
  (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose \
      < $W/00-prompt.txt > $W/00-model.jsonl 2> $W/00-model.err)
  print "claude -p rc=$? (142 = 120 s timeout)"
  $CONDA -I $ISO check $W/00-model.jsonl 533-OK $H $VPROJECT $W/00-prompt.txt
}
plugin_dir() { local d=($VPROJECT/.claude/skills/graphtraj-claude-host(N/) $VPROJECT/.claude/plugins/graphtraj-claude-host(N/)); print -r -- ${d[1]:-}; }
prompt_text() {
  cat <<EOF
Use only the mcp__graphtraj__agents tool (not Claude Code's own subagents) for this check of how agents messages are shown.
1. Call agents with {"action":"discover"} and then describe "create", so you know its arguments.
2. Create ONE child with only these selections: runtime claude, name $CHILD. Pass NO model, configuration, preset, connection or reasoning effort (the project's one role 'claude' supplies them). If create is refused, report the exact error text and stop; do not retry with other models or settings. Its instruction is exactly this Markdown:

## Task 533 display check

Reply **without using any tool**, in Markdown, with:
- a level-2 heading \`## Reply from $CHILD\`
- a bullet list of two items, one holding an inline code span like \`agents\`
- one quoted line starting with \`> \`

Then stop.

3. Do NOT call wait or status. End your turn with one short sentence.
4. When the completion notice from $CHILD arrives, call agents send to $CHILD with exactly this Markdown message, then again do NOT wait, and end your turn:

### Second message

1. Answer again in Markdown: a heading, a two-item list and a \`code span\`.
2. Use no tool.

5. When its second completion notice arrives, say DONE-533 and stop. Do not retire the child.
EOF
}

step_00() {
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} | running: $THIS"
  say "Claude Code version (533 needs >= $MINCC for \$.ui.place)"; cv
  local v=$($(claude_bin) --version 2>&1 | head -1)
  version_ok "$v" || { print "STOP: Claude Code '$v' is older than $MINCC (or unreadable): placed rows need $MINCC. Tell the Leader."; return 1; }
  print "Claude Code >= $MINCC: yes"
  say "isolated project $VPROJECT: own git, own .graphtraj (setup by production's graphtraj, read only), own settings (489)"
  vproject_init $RT/bin/graphtraj && isolation $RT/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  say "claude -p one-line answer from the isolated project (expect $MODEL, logged in, no Harness AGENTS.md)"
  ask_model || { print "STOP: answer check failed (above). If it is a login problem: USER runs 'claude' once in Terminal and logs in, then rerun 00."; return 1; }
}

step_B() {
  say "candidates: GraphTraj $(git -C $WT rev-parse HEAD) (Worktree HEAD) | graftling $GLC"
  local dirty=$(git -C $WT status --porcelain -- src tests plugins pyproject.toml)
  [[ -z $dirty ]] || { print "STOP: uncommitted GraphTraj product changes: $dirty"; return 1; }
  local prod; prod=$(git -C $WT diff --name-only $GTBASE HEAD -- src tests plugins pyproject.toml) || { print "STOP: cannot diff $GTBASE..HEAD"; return 1; }
  print "GraphTraj product files changed $GTBASE..HEAD: ${(j:, :)${(f)prod}}"
  [[ ${(j:,:)${(f)prod}} == $GTFILES ]] || { print "STOP: expected exactly $GTFILES"; return 1; }
  print "CHECK 533 GraphTraj product diff is exactly the two 533 files: PASS"
  git -C $GLREPO cat-file -e $GLC^{commit} || { print "STOP: graftling $GLC is not in $GLREPO"; return 1; }
  print "graftling $GLC: $(git -C $GLREPO log -1 --format='%s | author %an <%ae>' $GLC)"
  rm -rf $N $GLSRC $GTSRC $VV; mkdir -p $N $GLSRC $GTSRC
  git -C $GLREPO archive $GLC | tar -x -C $GLSRC || return 1
  git -C $WT archive HEAD | tar -x -C $GTSRC || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $GLSRC/src/graftling > /dev/null || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $GTSRC > /dev/null || return 1
  (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  say "scratch venv $VV: both wheels + production's click, yaml, websockets"
  $CONDA -m venv $VV && $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/*.whl && copy_deps $VV || return 1
  $VV/bin/python -m pip check --disable-pip-version-check; print "scratch venv pip check rc=$?"
  (cd $BASE && $VV/bin/python -I -c 'import graftling, graphtraj, pathlib
m = (pathlib.Path(graftling.__file__).parent / "claude/host_context.mjs").read_text()
print("graftling", graftling.__version__, graftling.__file__, "| notice_text:", hasattr(graftling, "notice_text"))
print("graphtraj", graphtraj.__file__)
print("candidate mod has ui.place / UserMessage render:", "$.ui.place(" in m, "component: \x27UserMessage\x27" in m)')
}

step_V() {
  [[ -x $VV/bin/graphtraj ]] || { print "没有 scratch venv，先运行 B。"; return 1; }
  say "isolated project with the CANDIDATE graphtraj + graftling"
  vproject_init $VV/bin/graphtraj && isolation $VV/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  (cd $VPROJECT && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $(claude_bin) --write) || return 1
  vsettings   # 489: re-merged after configuration --write
  local P=$(plugin_dir)
  [[ -n $P ]] || { print "STOP: no graphtraj-claude-host plugin written under $VPROJECT/.claude"; return 1; }
  say "written plugin $P"
  grep -c 'ui.place(' $P/hooks/host_context.mjs | sed 's/^/ui.place calls in the written mod: /'
  grep -q "component: 'UserMessage'" $P/hooks/host_context.mjs && print "UserMessage render in the written mod: yes" || { print "STOP: the written mod is not 533's"; return 1; }
  grep -nE '^const (PLUGIN|SERVER)' $P/hooks/host_context.mjs
  say "claude plugin validate (no ✘ expected)"; cv; $(claude_bin) plugin validate $P 2>&1 | tail -5
  say "MCP approval: the project's .claude/settings.local.json must enable the .mcp.json server graphtraj (no separate MCP dialog)"
  # configuration --write and claude_isolation leave enabledMcpjsonServers unset (try 1 showed the MCP dialog), so
  # V merges graphtraj into the isolated project's OWN settings (never ~/.claude, never the Harness's).
  $CONDA -I -c 'import json, sys
p = sys.argv[1]; s = json.load(open(p)); m = json.load(open(sys.argv[2])).get("mcpServers") or {}
en = list(s.get("enabledMcpjsonServers") or [])
if "graphtraj" in m and "graphtraj" not in en:
    s["enabledMcpjsonServers"] = en + ["graphtraj"]; open(p, "w").write(json.dumps(s, indent=2) + "\n")
    print("enabledMcpjsonServers: graphtraj added to", p)
else:
    print("enabledMcpjsonServers: graphtraj already present (or not in .mcp.json)")
en = s.get("enabledMcpjsonServers") or []
print("enabledMcpjsonServers:", en, "| enableAllProjectMcpServers:", s.get("enableAllProjectMcpServers"), "| .mcp.json servers:", sorted(m))
ok = "graphtraj" in en and "graphtraj" in m
print("CHECK 533 graphtraj MCP server enabled in project settings:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)' $VPROJECT/.claude/settings.local.json $VPROJECT/.mcp.json || { print "STOP: the graphtraj MCP server is not enabled in $VPROJECT/.claude/settings.local.json"; return 1; }
  say "child role: ONE role 'claude' (connection claude/anthropic/opus-5_5, effort low, permission_mode auto); resolved without launching a model"
  (cd $BASE && $VV/bin/python -I $SD/roles533.py $VPROJECT) || { print "STOP: the child role does not resolve (above); Main reports it to the Leader"; return 1; }
  prompt_text > $W/V-prompt.txt
  say "USER（真实交互式 Claude Code，Main 做不了）"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && claude --allowedTools mcp__graphtraj__agents,mcp__graphtraj__tasks"
  print "2) 预期对话框: 无（上次已信任此文件夹；graphtraj MCP 已在项目设置中启用，见上方 CHECK）。若仍出现信任框（文件夹、MCP server 'graphtraj' 或 hooks），选它的肯定选项（信任/使用，例如 'Yes, I trust this folder' / 'Use this and all future MCP servers'），并把对话框标题告诉 Main。其它任何框按 Esc 并报告标题。"
  print "3) 粘贴下面整段提示（也在 $W/V-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/V-prompt.txt; print -- "------------------"
  print "4) 截两张图: (i) 'agents → $CHILD' 那一行（发出的消息，Markdown 渲染）; (ii) 来自 $CHILD 的完成通知（粗体发送方 · completed、Markdown 内容、灰色 Facts 行）。"
  print "5) 看到 DONE-533 后输入 /exit。把截图交给 Main。"
  next "Main: zsh $THIS Vr"
}

step_Vr() {
  local f=($PROJECTS/*vproject-533*/*.jsonl(N.om))
  [[ -n ${f[1]:-} ]] || { print "no transcript under $PROJECTS/*vproject-533*/ yet; the USER part of V comes first"; return 1; }
  say "newest isolated Main transcript: ${f[1]} (read only)"
  $CONDA -I $SD/vr533.py ${f[1]} $CHILD
}

# Full suites against the candidates, background; pytest temp roots under TMPDIR (outside the Harness).
step_G() {
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 的 wheel，先运行 B。"; return 1; }
  local PT=${TMPDIR:-/tmp}; PT=${PT:A}
  [[ $PT == $H || $PT == $H/* ]] && { print "STOP: TMPDIR $PT is inside the Harness"; return 1; }
  local stamp=$(date +%Y%m%dT%H%M%S)
  local OUT=$W/G-$stamp GT=$PT/verify-533-gt-$stamp GL=$PT/verify-533-gl-$stamp; mkdir -p $OUT $GT $GL
  print -r -- "TMPDIR of the runs (outside the Harness): $PT | graphtraj temp $GT | graftling temp $GL" | tee $OUT/run.txt
  say "venv for GraphTraj: conda --system-site-packages + the candidate graftling wheel + this Worktree editable"
  local V1=$BASE/venv-g V2=$BASE/venv-gl
  rm -rf $V1 $V2
  $CONDA -m venv --system-site-packages $V1 && copy_deps $V1 && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl \
    && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  say "venv for graftling: its archive $GLC editable (graftling's tests require their own checkout)"
  $CONDA -m venv --system-site-packages $V2 && copy_deps $V2 && $V2/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $GLSRC/src/graftling 2>&1 | grep -vi cache
  (cd $GT && $V1/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)') | tee -a $OUT/run.txt
  (cd $GL && $V2/bin/python -I -c 'import graftling; print("graftling suite imports", graftling.__file__)') | tee -a $OUT/run.txt
  if [[ -n ${VERIFY533_TESTS:-} ]]; then
    print -r -- "REHEARSAL: graphtraj tests limited to $VERIFY533_TESTS; graftling to ${VERIFY533_GLTESTS:-tests/test_notice_text.py}" | tee -a $OUT/run.txt
    (cd $WT && TMPDIR=$GT $V1/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY533_TESTS} > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt)
    (cd $GLSRC && TMPDIR=$GL $V2/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY533_GLTESTS:-tests/test_notice_text.py} > $OUT/graftling.txt 2>&1; print "exit=$?" >> $OUT/graftling.txt)
  else
    # No nohup: it fails without a console ("can't detach", exit 127); &! already disowns the job.
    (cd $WT && TMPDIR=$GT $V1/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $OUT/shards -- -rA > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt) &!
    (cd $GLSRC && TMPDIR=$GL $V2/bin/python -m pytest -p no:cacheprovider -q -rfE > $OUT/graftling.txt 2>&1; print "exit=$?" >> $OUT/graftling.txt) &!
    print "started both suites in the background at $(date +%T) (~25 min); each output ends with 'exit=N'"
  fi
  print -r -- $OUT > $W/G-latest
  next "zsh $THIS GR    （两个输出都有 'exit=' 之后）"
}

step_GR() {
  local OUT=$(cat $W/G-latest 2>/dev/null)
  [[ -n $OUT ]] || { print "no G yet: zsh $THIS G"; return 1; }
  cat $OUT/run.txt
  local f; for f in graphtraj graftling; do
    print -r -- "---- $f: $OUT/$f.txt"; tail -3 $OUT/$f.txt
    grep -q '^exit=' $OUT/$f.txt || print "$f still running"
    grep -h -E '^(FAILED|ERROR) ' $OUT/$f.txt $OUT/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u | sed 's/^/  /'
  done
  print "Judge FAILED/ERROR lines against 516's list (never blocking) and the 532-accepted baseline; any other is NEW."
}

mkdir -p $W
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟。"; logged $W/00.txt step_00 && next "zsh $THIS B" ;;
  B)  print "[B] Main. 从确切提交构建两个 wheel 和 scratch venv（$BASE）。对话框: 无。约 1 分钟。"; logged $W/B.txt step_B && next "zsh $THIS V    （也可以先 zsh $THIS G）" ;;
  V)  print "[V] Main 准备隔离项目，然后 USER 在真实 claude 里操作一次。对话框: Main 无；USER 预期无（文件夹已在第一次尝试时信任）。"; logged $W/V.txt step_V ;;
  Vr) print "[Vr] Main. 只读 USER 那次会话的记录。对话框: 无。<10 秒。"; logged $W/Vr.txt step_Vr ;;
  G)  print "[G] Main. 两个全套测试（后台）。对话框: 无。立即返回。"; logged $W/G.txt step_G ;;
  GR) print "[GR] Main. 只读。对话框: 无。"; logged $W/GR.txt step_GR ;;
  *)  print "usage: zsh $THIS 00|B|V|Vr|G|GR   (order: 00 → B → V → USER → Vr; G any time after B, then GR)"; next "zsh $THIS 00" ;;
esac
