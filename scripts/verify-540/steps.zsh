#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 540 — a Task-free codex child created by an interactive Codex Main through the agents tool runs the project's
# Codex SessionStart hook and claims Main (continuity.jsonl), so its completion notice goes to its own ended thread.
# Real-host check in an ISOLATED project (/private/tmp/vproject-540) with wheels built from exact commits; production
# is never touched: no install into .venv-runtime, no change to the Harness's .codex, ~/.codex, the Codex install or
# dotfiles.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B0 → T [USER: folder trust] → Vb [USER: BEFORE run] → C → B → V [USER: AFTER run] → C ;
#        G (GraphTraj full suite, background, after B) → GR (read only)
# BEFORE = GraphTraj $GTBASE (dev) + graftling $GLBASE (dev). AFTER = GraphTraj $GTC (this Worktree's candidate)
# + graftling $GLC. Vb and V write the SAME project files: they name $ACTIVE, a link to the venv of B0 or B, so
# Codex sees the same hooks.json both times. Only rehearse.zsh sets VERIFY540_*. The defaults are the real paths.
set -u
setopt no_bg_nice   # background suites must not try to renice themselves (refused in a sandbox)
SD=${0:A:h}; THIS=${0:A}
H=${VERIFY540_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
WT=${VERIFY540_WT:-$H/.graphtraj/core/worktrees/540-codex-task-free-child-claims-main}
GLDEV=${VERIFY540_GLDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # graftling commits are read from here
GTBASE=f754d3a955fe7740fa11b54f194d19fb70d2d438       # GraphTraj dev the Worktree branched from
GLBASE=6794ce02b6210ec88837437affb8d7b525612804       # graftling dev
GTC=${VERIFY540_GTC:-}                                 # candidate GraphTraj commit (filled in when delivered)
GLC=${VERIFY540_GLC:-$GLBASE}                          # 540 changes no graftling file: the candidate uses graftling dev
GTFILES=${VERIFY540_GTFILES:-}                         # the candidate's exact product files (filled in when delivered)
BASE=${VERIFY540_BASE:-$H/tmp/540}                    # scratch venvs and wheels
ST=${VERIFY540_ST:-$H/.graphtraj/core/state/tasks/540-codex-task-free-child-claims-main/realhost}
W=$ST/540                                             # raw step output
RT=${VERIFY540_RT:-$H/.venv-runtime}                  # production: only read (click/yaml/websockets copied out)
VPROJECT=${VERIFY540_VPROJECT:-/private/tmp/vproject-540}
CODEX_HOME_USED=${VERIFY540_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}   # only read (C reads rollouts)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CODEX_MODEL=gpt-6-luna
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
CHILD=$(cat $W/child-name 2>/dev/null || print n540)   # step_V picks a fresh one per run; C reads it
ACTIVE=$BASE/active                                    # link -> $BASE/base or $BASE/cand
path=(/opt/homebrew/bin $HOME/.local/bin ${path:#$RT/bin})

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
codex_bin() { [[ -n ${VERIFY540_CODEX:-} ]] && { print -r -- $VERIFY540_CODEX; return; }; command -v codex; }
cv() { local C=$(codex_bin); print -r -- "codex: $C -> ${C:A} | version: $($C --version 2>&1 | head -1)"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
bounded() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
site_of() { local s=($1/lib/python*/site-packages(N)); print -r -- ${s[1]}; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local S=$(site_of $RT) D=$(site_of $1)
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/
}
isolation() {  # graphtraj root and git top level are the project; no AGENTS.md at or above it (Codex reads those)
  $1 -I - $VPROJECT <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('AGENTS.md', 'AGENTS.override.md') if (p / n).exists()]
print(f'graphtraj project root: {root} | git top level: {top} | AGENTS.md at or above: {upward or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward
print('isolation:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
}
vproject_init() {  # $1 = graphtraj executable used for setup (GraphTraj's public setup command)
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 540 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=540 -c user.email=540@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup) || return 1
  fi
}
ask_model() {  # one real codex exec answer from the isolated project: model and login
  local C=$(codex_bin)
  print "codex login: $(clean $C login status 2>&1 | sed -E 's/ - .*//' | head -1)"
  print -r -- "Reply with exactly one line: CODEX-540-OK followed by your model name. Use no tool." > $W/00-prompt.txt
  (cd $VPROJECT && bounded 300 $C exec -m $CODEX_MODEL --sandbox read-only - < $W/00-prompt.txt > $W/00-codex.txt 2>&1)
  print "codex exec rc=$? (142 = 300 s limit) | header model: $(grep -m1 -E '^model: ' $W/00-codex.txt | cut -c8-) | answer: $(grep -E '^CODEX-540-OK' $W/00-codex.txt | tail -1)"
  grep -qE '^CODEX-540-OK' $W/00-codex.txt && grep -qE "^model: $CODEX_MODEL" $W/00-codex.txt || { tail -5 $W/00-codex.txt; return 1; }
}
build() {  # $1 label (base|cand) $2 GraphTraj repo $3 commit $4 graftling repo $5 commit -> $BASE/$1/{wheels,venv}
  local L=$BASE/$1; rm -rf $L; mkdir -p $L/wheels $L/gl-src $L/gt-src
  git -C $4 cat-file -e $5^{commit} || { print "STOP: graftling $5 is not in $4"; return 1; }
  git -C $2 cat-file -e $3^{commit} || { print "STOP: GraphTraj $3 is not in $2"; return 1; }
  print "GraphTraj $(git -C $2 log -1 --format='%H %s' $3)"
  print "graftling $(git -C $4 log -1 --format='%H %s' $5)"
  git -C $4 archive $5 | tar -x -C $L/gl-src && git -C $2 archive $3 | tar -x -C $L/gt-src || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $L/wheels $L/gl-src/src/graftling > /dev/null || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $L/wheels $L/gt-src > /dev/null || return 1
  (cd $L/wheels && shasum -a 256 *.whl | tee SHA256SUMS)
  $CONDA -m venv $L/venv && $L/venv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $L/wheels/*.whl && copy_deps $L/venv || return 1
  $L/venv/bin/python -m pip check --disable-pip-version-check; print "venv pip check rc=$?"
  print -r -- "$3 $5" > $L/commits
  (cd $BASE && $L/venv/bin/python -I -c 'import graftling, graphtraj; print("graftling", graftling.__version__, graftling.__file__); print("graphtraj", graphtraj.__file__)')
}
prompt_text() {
  cat <<EOF
Use only the agents tool of the graphtraj MCP server (not Codex's own subagents) for this check.
1. Call agents with {"action":"discover"} and then describe "create", so you know its arguments.
2. Create ONE child with only these selections: runtime codex, name $CHILD. Pass NO model, configuration, preset, connection, workspace or reasoning effort (the project's one role 'codex' supplies $CODEX_MODEL). If create is refused, report the exact error text and stop; do not retry with other settings. Its instruction is exactly: Reply with exactly one line: CHILD-540-OK. Use no tool.
3. Do NOT call wait or status. End your turn with one short sentence.
4. When the completion notice from $CHILD arrives, reply exactly DONE-540 and stop. Do not retire the child.
EOF
}

step_00() {
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} | running: $THIS"
  say "Codex version (the user's install, only run)"; cv
  say "isolated project $VPROJECT: own git, own .graphtraj (GraphTraj's public 'graphtraj setup', production's graphtraj, read only)"
  vproject_init $RT/bin/graphtraj && isolation $RT/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  say "codex exec one-line answer from the isolated project (expect model $CODEX_MODEL, logged in; limit 300 s)"
  ask_model || { print "STOP: answer check failed (above). If it is a login problem: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
}

step_B0() {
  say "BEFORE: GraphTraj $GTBASE (dev) + graftling $GLBASE (dev) -> $BASE/base"
  build base $WT $GTBASE $GLDEV $GLBASE
}

step_T() {
  [[ -d $VPROJECT/.git ]] || { print "没有 $VPROJECT，先运行 00。"; return 1; }
  say "USER（真实交互式 Codex，只做文件夹信任，不输入提示）"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) 预期对话框（唯一一个，Codex 自己的）: 'Do you trust the contents of this directory?' → 选 Yes。其它任何框按 Esc 并把标题告诉 Main。"
  print "   这个选择由 Codex 自己记录在用户的 Codex 配置里；本脚本不向那里写任何东西（只写 $VPROJECT/.codex）。"
  print "3) 不输入任何提示，直接输入 /exit。"
}

step_B() {
  [[ -n $GTC ]] || { print "STOP: no candidate GraphTraj commit yet (GTC empty): the Engineer has not delivered the candidate."; return 1; }
  git -C $WT cat-file -e $GTC^{commit} || { print "STOP: candidate $GTC is not in $WT"; return 1; }
  say "AFTER: GraphTraj $GTC (candidate) + graftling $GLC -> $BASE/cand"
  local prod=$(git -C $WT diff --name-only $GTBASE $GTC -- src tests plugins pyproject.toml)
  print "GraphTraj product files changed $GTBASE..$GTC: ${(j:, :)${(f)prod}}"
  [[ ${(j:,:)${(f)prod}} == $GTFILES ]] || { print "STOP: expected exactly $GTFILES"; return 1; }
  print "CHECK 540 GraphTraj product diff is exactly the 540 files: PASS"
  build cand $WT $GTC $GLDEV $GLC
}

step_V() {  # $1 = base (Vb) | cand (V)
  local L=$BASE/$1
  [[ -x $L/venv/bin/graphtraj-mcp ]] || { print "没有 $L/venv，先运行 $([[ $1 == base ]] && print B0 || print B)。"; return 1; }
  rm -f $ACTIVE && ln -s $L $ACTIVE || return 1
  say "$ACTIVE -> $L ($(cat $L/commits)): the isolated project now runs this graphtraj + graftling"
  vproject_init $ACTIVE/venv/bin/graphtraj && isolation $ACTIVE/venv/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  (cd $VPROJECT && clean $ACTIVE/venv/bin/python -I $SD/codex_files540.py $VPROJECT) || { print "STOP: project .codex files not written"; return 1; }
  print "wrote $VPROJECT/.codex/config.toml and hooks.json (GraphTraj's public Codex hook material, SessionStart + SessionEnd):"
  sed 's/^/    /' $VPROJECT/.codex/config.toml $VPROJECT/.codex/hooks.json
  say "child role: ONE role 'codex' = the user's catalog model $CODEX_MODEL (read only); resolved without launching a model"
  (cd $BASE && $ACTIVE/venv/bin/python -I $SD/roles540.py $VPROJECT $CODEX_MODEL) || { print "STOP: the child role does not resolve (above); Main reports it to the Leader"; return 1; }
  say "stale Main state of the isolated project (only its runner/main-sessions): removed so no earlier claim redirects the notice"
  local MS; for MS in $VPROJECT/.graphtraj/runner/main-sessions $VPROJECT/.graphtraj/core/runner/main-sessions; do
    if [[ -d $MS ]]; then print "removing $MS:"; find $MS -type f | sed 's/^/    /'; rm -rf $MS || return 1; else print "none: $MS absent"; fi
  done
  CHILD=n540$(date +%H%M); print -r -- $CHILD > $W/child-name
  print "child name for this run (fresh): $CHILD"
  date +%s > $W/V$1.start
  prompt_text > $W/V-prompt.txt
  local tag=$([[ $1 == base ]] && print BEFORE || print AFTER)
  say "USER（真实交互式 Codex，Main 做不了）— $tag"
  print "1) 在普通 Terminal 运行（一行，不加任何 -c 选项）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  if [[ $1 == base ]]; then
    print "2) 预期对话框（最多一个，Codex 自己的）: $VPROJECT/.codex/hooks.json 的 hook 审核 → approve。文件夹信任已在 T 完成；若仍出现信任框 → Yes 并告诉 Main。其它任何框按 Esc 并把标题告诉 Main。"
  else
    print "2) 预期对话框: 无（hooks.json 与 Vb 相同）。若仍出现 hook 审核框 → approve，并把标题告诉 Main。其它任何框按 Esc 并报告标题。"
  fi
  print "   启动后应看到 'GraphTraj Main Session associated.'；若没有: /exit 再运行同一命令一次。"
  print "3) 粘贴下面整段提示（也在 $W/V-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/V-prompt.txt; print -- "------------------"
  if [[ $1 == base ]]; then
    print "4) 预期（修改前，缺陷）: 创建成功后 Main 结束本轮；之后等 3 分钟，来自 $CHILD 的完成通知不会出现，Main 也不会说 DONE-540。"
  else
    print "4) 预期（修改后）: 创建成功后 Main 结束本轮；约 1 分钟内出现来自 $CHILD 的完成通知，Main 回复 DONE-540。"
  fi
  print "5) 截一张图（$tag）: 从创建 $CHILD 到（通知 + DONE-540 或 等满 3 分钟）。然后输入 /exit，把截图交给 Main。"
  next "Main: zsh $THIS C"
}

step_C() {
  local s=($W/V{base,cand}.start(N.om))
  [[ -n ${s[1]:-} ]] || { print "no Vb/V start stamp in $W: run Vb or V first"; return 1; }
  local tag=$([[ ${s[1]:t} == Vbase.start ]] && print before || print after)
  say "read only: $VPROJECT continuity, the $CHILD control record, the Main's rollout under $CODEX_HOME_USED/sessions; copies -> $ST/$tag"
  print "run: ${s[1]:t} at $(cat ${s[1]}) | active: $(readlink $ACTIVE) ($(cat $ACTIVE/commits 2>/dev/null))"
  $CONDA -I $SD/c540.py $VPROJECT $CODEX_HOME_USED/sessions $CHILD $(cat ${s[1]}) $ST/$tag
  print "Expected: BEFORE 'VERDICT 540: REPRODUCED'; AFTER 'VERDICT 540: FIXED'."
}

# GraphTraj full suite against the candidate (graftling wheel $GLC), background; pytest temp roots under TMPDIR.
step_G() {
  local N=$BASE/cand/wheels
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 的 wheel，先运行 B。"; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  git -C $WT merge-base --is-ancestor $GTC HEAD || { print "STOP: $WT HEAD does not contain $GTC"; return 1; }
  local PT=${TMPDIR:-/tmp}; PT=${PT:A}
  [[ $PT == $H || $PT == $H/* ]] && { print "STOP: TMPDIR $PT is inside the Harness"; return 1; }
  local stamp=$(date +%Y%m%dT%H%M%S)
  local OUT=$W/G-$stamp GT=$PT/verify-540-gt-$stamp; mkdir -p $OUT $GT
  print -r -- "TMPDIR=\${TMPDIR:-/tmp} -> $PT (outside the Harness) | pytest temp root $GT | candidate $(git -C $WT rev-parse HEAD) | graftling $GLC" | tee $OUT/run.txt
  say "venv for GraphTraj: conda --system-site-packages + the candidate graftling wheel + this Worktree editable"
  local V1=$BASE/venv-g; rm -rf $V1
  $CONDA -m venv --system-site-packages $V1 && copy_deps $V1 && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl \
    && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  (cd $GT && $V1/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)') | tee -a $OUT/run.txt
  if [[ -n ${VERIFY540_TESTS:-} ]]; then
    print -r -- "REHEARSAL: graphtraj tests limited to $VERIFY540_TESTS (same venv, temp root and exit line)" | tee -a $OUT/run.txt
    (cd $WT && TMPDIR=$GT $V1/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY540_TESTS} > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt)
  else
    (cd $WT && TMPDIR=$GT $V1/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $OUT/shards -- -rA > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt) &!
    print "started in the background at $(date +%T) (~25 min); the output ends with 'exit=N'"
  fi
  print -r -- $OUT > $W/G-latest
  next "zsh $THIS GR    （输出有 'exit=' 之后）"
}

step_GR() {
  local OUT=$(cat $W/G-latest 2>/dev/null)
  [[ -n $OUT ]] || { print "no G yet: zsh $THIS G"; return 1; }
  cat $OUT/run.txt
  print -r -- "---- $OUT/graphtraj.txt"; tail -3 $OUT/graphtraj.txt
  grep -q '^exit=' $OUT/graphtraj.txt || print "still running"
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $OUT/graphtraj.txt $OUT/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
  print "Success: 'exit=0', or only 'known (516)' lines; judge any 'NEW' line against the base."
}

mkdir -p $W $BASE
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟（一次 codex exec）。"; logged $W/00.txt step_00 && next "zsh $THIS B0" ;;
  B0) print "[B0] Main. 构建修改前 wheel 与 venv（$BASE/base）。对话框: 无。约 1 分钟。"; logged $W/B0.txt step_B0 && next "zsh $THIS T    （USER 只做文件夹信任）" ;;
  T)  print "[T] USER. 在真实 codex 里只信任隔离项目文件夹，然后 /exit。对话框: 1 个（文件夹信任 → Yes）。<1 分钟。"; logged $W/T.txt step_T && next "zsh $THIS Vb    （USER 完成 T 之后）" ;;
  Vb) print "[Vb] Main 准备隔离项目（修改前），然后 USER 在真实 codex 里操作一次。对话框: Main 无；USER 最多 1 个（hooks.json 审核 → approve）。"; logged $W/Vb.txt step_V base ;;
  C)  print "[C] Main. 只读收集 continuity、子 Agent 控制记录与 Main rollout，复制到 realhost/<before|after>。对话框: 无。<10 秒。"; logged $W/C.txt step_C ;;
  B)  print "[B] Main. 构建修改后 wheel 与 venv（$BASE/cand）。对话框: 无。约 1 分钟。"; logged $W/B.txt step_B && next "zsh $THIS V    （也可以先 zsh $THIS G）" ;;
  V)  print "[V] Main 准备隔离项目（修改后），然后 USER 在真实 codex 里操作一次。对话框: Main 无；USER 预期无。"; logged $W/V.txt step_V cand ;;
  G)  print "[G] Main. GraphTraj 全套测试（后台）。对话框: 无。立即返回。"; logged $W/G.txt step_G ;;
  GR) print "[GR] Main. 只读。对话框: 无。"; logged $W/GR.txt step_GR ;;
  *)  print "usage: zsh $THIS 00|B0|T|Vb|C|B|V|G|GR   (order: 00 → B0 → T (USER) → Vb (USER) → C → B → V (USER) → C; G after B, then GR)"; next "zsh $THIS 00" ;;
esac
