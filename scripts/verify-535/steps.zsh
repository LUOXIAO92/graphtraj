#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 535 — interactive Codex Main shows agents traffic as who + Markdown content. Real-host check in an ISOLATED
# project (/private/tmp/vproject-535) with wheels built from exact commits; production is never touched: no install
# into .venv-runtime, no change to the Harness's .codex, ~/.codex, the Codex install or dotfiles.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B0 → T [USER: directory trust only] → Vb → [USER: real interactive codex, prompt, 2 BEFORE screenshots] → Vr
#        → B → V → [USER: same, 2 AFTER screenshots] → Vr ;  G (full suites, background, after B) → GR (read only)
# Baseline = GraphTraj $GTBASE (dev) + graftling $GLBASE (dev). Candidate = this Worktree's HEAD + commit $GLC of
# the untracked clone $GLREPO (branch agent/535-codex-main-agents-message-display, based on graftling dev $GLBASE).
# Vb and V write the SAME project files: they name $ACTIVE, a link to the venv of B0 or B, so Codex sees the same
# hooks.json both times. Only rehearse.zsh sets VERIFY535_*. The defaults are the real paths.
set -u
setopt no_bg_nice   # background suites must not try to renice themselves (refused in a sandbox)
SD=${0:A:h}; THIS=${0:A}
H=${VERIFY535_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
WT=${VERIFY535_WT:-$H/.graphtraj/core/worktrees/535-codex-main-agents-message-display}
GLDEV=${VERIFY535_GLDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # baseline graftling commit is read from here
GLREPO=${VERIFY535_GLREPO:-$WT/.scratch/graftling}    # untracked clone (its git dir: $WT/.scratch/graftling-git)
GTBASE=8ac35e3195f3735b9742a7beff3842333cb4e48a       # GraphTraj dev the Worktree branched from
GLBASE=f67d147a222d7db214ecad14d24809debad999a4       # graftling dev (533's notice_text)
GLC=${VERIFY535_GLC:-}                                # candidate graftling commit (set in the second delivery)
BASE=${VERIFY535_BASE:-$H/tmp/535}                    # scratch venvs and wheels (Main creates it)
W=${VERIFY535_W:-$H/.graphtraj/core/state/tasks/535-codex-main-agents-message-display/realhost/535}   # raw output
PRODH=${VERIFY535_PRODH:-$H}                         # production roles.yml: only read
RT=${VERIFY535_RT:-$H/.venv-runtime}                  # production: only read (click/yaml/websockets copied out)
VPROJECT=${VERIFY535_VPROJECT:-/private/tmp/vproject-535}
CODEX_HOME_USED=${VERIFY535_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}   # only read (Vr reads rollouts)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CODEX_MODEL=gpt-6-luna
CHILD=n535
ACTIVE=$BASE/active                                    # link -> $BASE/base or $BASE/cand
path=(/opt/homebrew/bin $HOME/.local/bin ${path:#$RT/bin})

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
codex_bin() { [[ -n ${VERIFY535_CODEX:-} ]] && { print -r -- $VERIFY535_CODEX; return; }; command -v codex; }
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
vproject_init() {  # $1 = graphtraj executable used for setup
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 535 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=535 -c user.email=535@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup) || return 1
  fi
}
ask_model() {  # one real codex exec answer from the isolated project: model and login
  local C=$(codex_bin)
  print "codex login: $(clean $C login status 2>&1 | sed -E 's/ - .*//' | head -1)"
  print -r -- "Reply with exactly one line: CODEX-535-OK followed by your model name. Use no tool." > $W/00-prompt.txt
  (cd $VPROJECT && bounded 300 $C exec -m $CODEX_MODEL --sandbox read-only - < $W/00-prompt.txt > $W/00-codex.txt 2>&1)
  print "codex exec rc=$? (142 = 300 s limit) | header model: $(grep -m1 -E '^model: ' $W/00-codex.txt | cut -c8-) | answer: $(grep -E '^CODEX-535-OK' $W/00-codex.txt | tail -1)"
  grep -qE '^CODEX-535-OK' $W/00-codex.txt && grep -qE "^model: $CODEX_MODEL" $W/00-codex.txt || { tail -5 $W/00-codex.txt; return 1; }
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
roles() { (cd $BASE && $ACTIVE/venv/bin/python -I $SD/roles535.py $PRODH $VPROJECT $CODEX_MODEL); }
codex_files() {  # the isolated project's OWN .codex: graphtraj MCP server + GraphTraj's Codex hooks, all via $ACTIVE
  local PY=$ACTIVE/venv/bin/python
  mkdir -p $VPROJECT/.codex
  (cd $VPROJECT && clean $PY -I $SD/codex_files535.py $VPROJECT $ACTIVE/venv) || return 1
  print "wrote $VPROJECT/.codex/config.toml and hooks.json:"; sed 's/^/    /' $VPROJECT/.codex/config.toml $VPROJECT/.codex/hooks.json
}
prompt_text() {
  cat <<EOF
Use only the agents tool of the graphtraj MCP server (not Codex's own subagents) for this check of how agents messages are shown.
1. Call agents with {"action":"discover"} and then describe "create", so you know its arguments.
2. Create ONE child with only these selections: runtime codex, name $CHILD. Pass NO model, configuration, preset, connection or reasoning effort (the project's one role 'codex' supplies them). If create is refused, report the exact error text and stop; do not retry with other settings. Its instruction is exactly this Markdown:

## Task 535 display check

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

5. When its second completion notice arrives, say DONE-535 and stop. Do not retire the child.
EOF
}

step_00() {
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} | running: $THIS"
  say "Codex version (the user's install, only run)"; cv
  say "isolated project $VPROJECT: own git, own .graphtraj (setup by production's graphtraj, read only)"
  vproject_init $RT/bin/graphtraj && isolation $RT/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  say "codex exec one-line answer from the isolated project (expect model $CODEX_MODEL, logged in; limit 300 s)"
  ask_model || { print "STOP: answer check failed (above). If it is a login problem: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
}

step_B0() {
  say "BASELINE: GraphTraj $GTBASE (dev) + graftling $GLBASE (dev) -> $BASE/base"
  build base $WT $GTBASE $GLDEV $GLBASE
}

step_T() {
  [[ -d $VPROJECT/.git ]] || { print "没有 $VPROJECT，先运行 00。"; return 1; }
  [[ -e $VPROJECT/.codex ]] && print "note: $VPROJECT/.codex already exists (Vb ran before); the trust dialog may then be followed by a hook review: approve it."
  say "USER（真实交互式 Codex，只做文件夹信任，不输入提示）"
  print "1) 在普通 Terminal 运行（一行）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) 预期对话框（唯一一个，Codex 自己的）: 'Do you trust the contents of this directory?' → 选 Yes。其它任何框按 Esc 并把标题告诉 Main。"
  print "   这个选择由 Codex 自己记录在用户的 Codex 配置里；本脚本不向那里写任何东西（只写 $VPROJECT/.codex）。"
  print "3) 不输入任何提示，直接输入 /exit。"
}

step_B() {
  [[ -n $GLC ]] || { print "STOP: no candidate graftling commit yet (GLC empty): the Engineer has not delivered the candidate."; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins pyproject.toml)
  [[ -z $dirty ]] || { print "STOP: uncommitted GraphTraj product changes: $dirty"; return 1; }
  say "CANDIDATE: GraphTraj $(git -C $WT rev-parse HEAD) (Worktree HEAD) + graftling $GLC -> $BASE/cand"
  print "GraphTraj product files changed $GTBASE..HEAD: $(git -C $WT diff --name-only $GTBASE HEAD -- src tests plugins pyproject.toml | tr '\n' ' ')"
  print "graftling files changed $GLBASE..$GLC: $(git -C $GLREPO diff --name-only $GLBASE $GLC | tr '\n' ' ')"
  build cand $WT HEAD $GLREPO $GLC
}

step_V() {  # $1 = base (Vb) | cand (V)
  local L=$BASE/$1
  [[ -x $L/venv/bin/graphtraj-mcp ]] || { print "没有 $L/venv，先运行 $([[ $1 == base ]] && print B0 || print B)。"; return 1; }
  rm -f $ACTIVE && ln -s $L $ACTIVE || return 1
  say "$ACTIVE -> $L ($(cat $L/commits)): the isolated project now runs this graphtraj + graftling"
  vproject_init $ACTIVE/venv/bin/graphtraj && isolation $ACTIVE/venv/bin/python || { print "STOP: isolation NOT OK"; return 1; }
  codex_files || { print "STOP: project .codex files not written (above)"; return 1; }
  say "child role: ONE role 'codex' copied from a production preset (runtime codex, model $CODEX_MODEL; production roles only read); resolved without launching a model"
  roles || { print "STOP: the child role does not resolve (above); Main reports it to the Leader"; return 1; }
  date +%s > $W/V$1.start
  prompt_text > $W/V-prompt.txt
  local tag=$([[ $1 == base ]] && print BEFORE || print AFTER)
  say "USER（真实交互式 Codex，Main 做不了）— $tag 截图"
  print "1) 在普通 Terminal 运行（一行，不加任何 -c 选项: 否则 Codex 不用共享后台服务，收不到通知）:"
  print -r -- "   cd $VPROJECT && codex -m $CODEX_MODEL"
  if [[ $1 == base ]]; then
    print "2) 预期对话框（最多一个，Codex 自己的）: $VPROJECT/.codex/hooks.json 的 hook 审核 → approve（或无）。文件夹信任已在 T 完成；若仍出现信任框 → Yes 并告诉 Main。其它任何框按 Esc 并把标题告诉 Main。"
  else
    print "2) 预期对话框: 无（Vb 时已信任文件夹与 hooks；hooks.json 与 Vb 相同）。若仍出现 hook 审核框 → approve，并把标题告诉 Main。其它任何框按 Esc 并报告标题。"
  fi
  print "   启动后若没有 'GraphTraj' 的 SessionStart 提示或没有 graphtraj 工具: /exit 再运行同一命令一次。"
  print "3) 粘贴下面整段提示（也在 $W/V-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/V-prompt.txt; print -- "------------------"
  print "4) 截两张图（$tag）: (i) 发给 $CHILD 的消息（agents send 的展示）; (ii) 来自 $CHILD 的完成通知。"
  print "5) 看到 DONE-535 后输入 /exit。把截图交给 Main。"
  next "Main: zsh $THIS Vr"
}

step_Vr() {
  say "newest isolated Main rollout under $CODEX_HOME_USED/sessions whose cwd is $VPROJECT (read only)"
  $CONDA -I $SD/vr535.py $CODEX_HOME_USED/sessions $VPROJECT $CHILD
}

# Full suites against the candidates, background; pytest temp roots under TMPDIR (outside the Harness).
step_G() {
  local N=$BASE/cand/wheels GLSRC=$BASE/cand/gl-src
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 的 wheel，先运行 B。"; return 1; }
  local PT=${TMPDIR:-/tmp}; PT=${PT:A}
  [[ $PT == $H || $PT == $H/* ]] && { print "STOP: TMPDIR $PT is inside the Harness"; return 1; }
  local stamp=$(date +%Y%m%dT%H%M%S)
  local OUT=$W/G-$stamp GT=$PT/verify-535-gt-$stamp GL=$PT/verify-535-gl-$stamp; mkdir -p $OUT $GT $GL
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
  if [[ -n ${VERIFY535_TESTS:-} ]]; then
    print -r -- "REHEARSAL: graphtraj tests limited to $VERIFY535_TESTS; graftling to ${VERIFY535_GLTESTS:-tests/test_notice_text.py}" | tee -a $OUT/run.txt
    (cd $WT && TMPDIR=$GT $V1/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY535_TESTS} > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt)
    (cd $GLSRC && TMPDIR=$GL $V2/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY535_GLTESTS:-tests/test_notice_text.py} > $OUT/graftling.txt 2>&1; print "exit=$?" >> $OUT/graftling.txt)
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

mkdir -p $W $BASE
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟（一次 codex exec）。"; logged $W/00.txt step_00 && next "zsh $THIS B0" ;;
  B0) print "[B0] Main. 构建基线 wheel 与 venv（$BASE/base）。对话框: 无。约 1 分钟。"; logged $W/B0.txt step_B0 && next "zsh $THIS T    （USER 只做文件夹信任）" ;;
  T)  print "[T] USER. 在真实 codex 里只信任隔离项目文件夹，然后 /exit。对话框: 1 个（文件夹信任 → Yes）。<1 分钟。"; logged $W/T.txt step_T && next "zsh $THIS Vb    （USER 完成 T 之后）" ;;
  Vb) print "[Vb] Main 准备隔离项目（基线），然后 USER 在真实 codex 里操作一次（修改前截图）。对话框: Main 无；USER 最多 1 个（hooks.json 审核 → approve，或无）。"; logged $W/Vb.txt step_V base ;;
  B)  print "[B] Main. 构建候选 wheel 与 venv（$BASE/cand）。对话框: 无。约 1 分钟。"; logged $W/B.txt step_B && next "zsh $THIS V    （也可以先 zsh $THIS G）" ;;
  V)  print "[V] Main 准备隔离项目（候选），然后 USER 在真实 codex 里操作一次（修改后截图）。对话框: Main 无；USER 见下方第 2 条。"; logged $W/V.txt step_V cand ;;
  Vr) print "[Vr] Main. 只读 USER 那次会话的 rollout。对话框: 无。<10 秒。"; logged $W/Vr.txt step_Vr ;;
  G)  print "[G] Main. 两个全套测试（后台）。对话框: 无。立即返回。"; logged $W/G.txt step_G ;;
  GR) print "[GR] Main. 只读。对话框: 无。"; logged $W/GR.txt step_GR ;;
  *)  print "usage: zsh $THIS 00|B0|T|Vb|Vr|B|V|G|GR   (order: 00 → B0 → T (USER trust) → Vb → USER → Vr → B → V → USER → Vr; G after B, then GR)"; next "zsh $THIS 00" ;;
esac
