#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 536 — Pi Main shows agents traffic as who + Markdown content. Real-host check in an ISOLATED project
# (/private/tmp/vproject-536) with wheels built from exact commits; production is never touched:
# no install into .venv-runtime (read only), no change to ~/.pi or dotfiles; Pi Sessions go to --session-dir under $W.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V0 → [USER: BEFORE screenshots] → V1 → [USER: AFTER screenshots] → Vr
#        G (full suites, background, any time after B) → GR (read only)
# BASELINE = GraphTraj $GTBASE + graftling $GLBASE. CANDIDATE = this Worktree's HEAD (536 changes exactly $GTFILES
# against $GTBASE) + graftling $GLC of the clone $GLREPO (branch agent/536-pi-main-agents-message-display).
# Only rehearse.zsh sets VERIFY536_*. The defaults are the real paths.
set -u
setopt no_bg_nice
SD=${0:A:h}; THIS=${0:A}
H=${VERIFY536_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
WT=${VERIFY536_WT:-$H/.graphtraj/core/worktrees/536-pi-main-agents-message-display}
GLREPO=${VERIFY536_GLREPO:-$WT/.scratch/graftling}    # untracked clone (git dir $WT/.scratch/graftling-git)
GLC=${VERIFY536_GLC:-fc081a3f1cf2664f603d4deba14a86d59a16fd8f}   # candidate graftling
GLBASE=f67d147a222d7db214ecad14d24809debad999a4                    # graftling dev (533's notice_text)
GTBASE=8ac35e3195f3735b9742a7beff3842333cb4e48a                    # GraphTraj dev the Worktree branched from
GTFILES=src/graphtraj/runtimes/native_entry.py,src/graphtraj/runtimes/pi/extension.mjs,tests/test_pi_main_notice_display_536.py
BASE=${VERIFY536_BASE:-$H/tmp/536}
W=${VERIFY536_W:-$H/.graphtraj/core/state/tasks/536-pi-main-agents-message-display/realhost/536}
RT=${VERIFY536_RT:-$H/.venv-runtime}                   # production: only read (click/yaml/websockets copied out)
VPROJECT=${VERIFY536_VPROJECT:-/private/tmp/vproject-536}
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
PI_PROVIDER=deepseek; PI_MODEL=deepseek-flash          # as scripts/verify-444 and verify-514
CHILD=n536
CLAUDE_MODEL=claude-opus-5-5                           # the child host (role 'claude': claude/anthropic/opus-5_5)
ISO=$SD/../verify-common/claude_isolation.py
N=$BASE/wheels

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
ask_model() {  # verify-533's check: one real claude -p answer (tag, model, login, no Harness AGENTS.md, no echo)
  local C=$(claude_bin)
  $CONDA -I $ISO settings $H $VPROJECT || return 1
  $CONDA -I $ISO prompt 536-OK > $W/00-prompt.txt
  (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $CLAUDE_MODEL --output-format stream-json --verbose \
      < $W/00-prompt.txt > $W/00-model.jsonl 2> $W/00-model.err)
  print "claude -p rc=$? (142 = 120 s timeout)"
  $CONDA -I $ISO check $W/00-model.jsonl 536-OK $H $VPROJECT $W/00-prompt.txt
}
site_of() { local s=($1/lib/python*/site-packages(N)); print -r -- ${s[1]}; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local S=$(site_of $RT) D=$(site_of $1)
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/
}
load_key() {  # verify-514 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]]
}
ext_of() { $1/bin/python -I -c 'import graphtraj, pathlib; print(pathlib.Path(graphtraj.__file__).parent / "runtimes/pi/extension.mjs")'; }
vproject_init() {  # $1 = graphtraj executable used for setup; own git, own .graphtraj
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 536 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=536 -c user.email=536@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $1 setup | tail -2) || return 1
  fi
  local top=$(git -C $VPROJECT rev-parse --show-toplevel)
  print "isolated project: $VPROJECT | git top level: $top | .graphtraj: $([[ -d $VPROJECT/.graphtraj ]] && print yes || print no)"
  [[ ${top:A} == ${VPROJECT:A} && -d $VPROJECT/.graphtraj ]] && print "isolation: OK" || { print "isolation: NOT OK"; return 1; }
}
prompt_text() {
  cat <<EOF
Use only the mcp__graphtraj__agents tool (not any other subagent mechanism) for this check of how agents messages are shown.
1. Call agents with {"action":"discover"} and then describe "create", so you know its arguments.
2. Create ONE child with only these selections: runtime claude, name $CHILD. Pass NO model, configuration, preset, connection or reasoning effort (the project's one role 'claude' supplies them). If create is refused, report the exact error text and stop; do not retry with other settings. Its instruction is exactly this Markdown:

## Task 536 display check

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

5. When its second completion notice arrives, say DONE-536 and stop. Do not retire the child.
EOF
}

step_00() {
  say "shell (expect zsh)"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh} | running: $THIS"
  say "Pi"; print "pi: $(command -v pi) | version: $(pi --version 2>&1 | head -1)"
  say "isolated project $VPROJECT: own git, own .graphtraj (setup by production's graphtraj, read only)"
  vproject_init $RT/bin/graphtraj || { print "STOP: isolation NOT OK"; return 1; }
  say "Main host: pi --print one-line answer from the isolated project (no extension: it must not claim Main here)"
  load_key || { print "STOP: DEEPSEEK_API_KEY is unset (verify-514 reads it from ~/.zshrc)"; return 1; }
  (cd $VPROJECT && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 pi --print --no-tools --provider $PI_PROVIDER --model $PI_MODEL \
     'Reply with one line: READY-536 followed by your exact model name. Use no tool.' < /dev/null > $W/00-pi.txt 2>&1)
  print "pi --print rc=$? (142 = 120 s timeout)"; redact < $W/00-pi.txt | tail -3
  grep -q '^READY-536 ' $W/00-pi.txt && print "CHECK 536 Pi answer line (READY-536 + model): PASS" \
    || { print "STOP: no 'READY-536 <model>' answer from pi (above). If it is a key/login problem, tell the Leader."; return 1; }
  say "child host: claude -p one-line answer from the isolated project (expect $CLAUDE_MODEL, logged in, no Harness AGENTS.md)"
  print "claude: $(claude_bin) | version: $($(claude_bin) --version 2>&1 | head -1)"
  ask_model || { print "STOP: answer check failed (above). If it is a login problem: USER runs 'claude' once in Terminal and logs in, then rerun 00."; return 1; }
}

build() {  # $1 name, $2 GraphTraj commit, $3 graftling commit -> $BASE/venv-$1
  local S=$BASE/src-$1 V=$BASE/venv-$1 WH=$N/$1
  rm -rf $S $V $WH; mkdir -p $S/gt $S/gl $WH
  git -C $WT archive $2 | tar -x -C $S/gt || return 1
  git -C $GLREPO archive $3 | tar -x -C $S/gl || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WH $S/gl/src/graftling > /dev/null || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WH $S/gt > /dev/null || return 1
  (cd $WH && shasum -a 256 *.whl | tee SHA256SUMS)
  $CONDA -m venv $V && $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $WH/*.whl && copy_deps $V || return 1
  $V/bin/python -m pip check --disable-pip-version-check; print "$1 venv pip check rc=$?"
  local E=$(cd $BASE && ext_of $V)
  print "$1: GraphTraj $(git -C $WT rev-parse $2) + graftling $(git -C $GLREPO rev-parse $3) | extension $E"
  print "$1: notice renderer in the extension: $(grep -c registerNoticeDisplay $E)"
}

step_B() {
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml)
  [[ -z $dirty ]] || { print "STOP: uncommitted GraphTraj product changes: $dirty"; return 1; }
  local prod; prod=$(git -C $WT diff --name-only $GTBASE HEAD -- src tests pyproject.toml) || { print "STOP: cannot diff"; return 1; }
  print "GraphTraj product files changed $GTBASE..HEAD: ${(j:, :)${(f)prod}}"
  [[ ${(j:,:)${(f)prod}} == $GTFILES ]] || { print "STOP: expected exactly $GTFILES"; return 1; }
  print "CHECK 536 GraphTraj product diff is exactly the three 536 files: PASS"
  print "graftling candidate: $(git -C $GLREPO log -1 --format='%H %s | author %an <%ae>' $GLC)"
  mkdir -p $N
  say "BASELINE venv"; build baseline $GTBASE $GLBASE || return 1
  say "CANDIDATE venv"; build candidate HEAD $GLC || return 1
}

step_V() {  # $1 = baseline (V0, BEFORE) or candidate (V1, AFTER)
  local V=$BASE/venv-$1 tag=${2}
  [[ -x $V/bin/graphtraj ]] || { print "没有 $V，先运行 B。"; return 1; }
  vproject_init $V/bin/graphtraj || { print "STOP: isolation NOT OK"; return 1; }
  say "child role: ONE role 'claude' (claude/anthropic/opus-5_5, effort high, permission_mode auto, as production's"
  print "opus_coding_team.engineer; verify-533/roles533.py); resolved by this venv without launching a model"
  (cd $BASE && $V/bin/python -I $SD/../verify-533/roles533.py $VPROJECT) || { print "STOP: the child role does not resolve (above); Main reports it"; return 1; }
  local E=$(cd $BASE && ext_of $V)
  print "extension: $E | notice renderer in it: $(grep -c registerNoticeDisplay $E)"
  mkdir -p $W/pi-$tag
  prompt_text > $W/$tag-prompt.txt
  say "USER（真实交互式 Pi，Main 做不了）"
  print "1) 在普通 Terminal 运行（一行；你的 shell 已有 DEEPSEEK_API_KEY）:"
  print -r -- "   cd $VPROJECT && PATH=$V/bin:\$PATH GRAFTLING_PYTHON=$V/bin/python pi --session-dir $W/pi-$tag --extension $E --provider $PI_PROVIDER --model $PI_MODEL"
  print "2) 预期对话框: 无。若 Pi 询问是否信任此文件夹或扩展，选肯定选项并把标题告诉 Main；其它任何框按 Esc 并报告标题。"
  print "   启动后应看到提示 'GraphTraj Main Session associated.'"
  print "3) 粘贴下面整段提示（也在 $W/$tag-prompt.txt），回车:"
  print -- "----- prompt -----"; cat $W/$tag-prompt.txt; print -- "------------------"
  print "4) 截两张图: (i) 'agents · <session> → $CHILD' 那一块（发出的消息）; (ii) 来自 $CHILD 的完成通知那一块。"
  print "5) 看到 DONE-536 后 Ctrl-C 两次退出。把截图交给 Main。"
}

step_Vr() {
  local tag; for tag in V0 V1; do
    say "$tag Session under $W/pi-$tag (read only)"
    $CONDA -I $SD/vr536.py $W/pi-$tag $CHILD || true
  done
  print "Expected: V0 FAIL (BEFORE: JSON in the notice, no display details); V1 PASS (AFTER)."
}

step_G() {
  [[ -x $BASE/venv-candidate/bin/python ]] || { print "没有 B 的 venv，先运行 B。"; return 1; }
  local PT=${TMPDIR:-/tmp}; PT=${PT:A}
  [[ $PT == $H || $PT == $H/* ]] && { print "STOP: TMPDIR $PT is inside the Harness"; return 1; }
  local stamp=$(date +%Y%m%dT%H%M%S)
  local OUT=$W/G-$stamp GT=$PT/verify-536-gt-$stamp GL=$PT/verify-536-gl-$stamp; mkdir -p $OUT $GT $GL
  print -r -- "TMPDIR of the runs (outside the Harness): $PT | graphtraj temp $GT | graftling temp $GL" | tee $OUT/run.txt
  local V1=$BASE/venv-g V2=$BASE/venv-gl GLSRC=$BASE/src-candidate/gl
  rm -rf $V1 $V2
  $CONDA -m venv --system-site-packages $V1 && copy_deps $V1 && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/candidate/graftling-*.whl \
    && $V1/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
  $CONDA -m venv --system-site-packages $V2 && copy_deps $V2 && $V2/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $GLSRC/src/graftling 2>&1 | grep -vi cache
  (cd $GT && $V1/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)') | tee -a $OUT/run.txt
  (cd $GL && $V2/bin/python -I -c 'import graftling; print("graftling suite imports", graftling.__file__)') | tee -a $OUT/run.txt
  if [[ -n ${VERIFY536_TESTS:-} ]]; then
    print -r -- "REHEARSAL: graphtraj tests limited to $VERIFY536_TESTS; graftling to ${VERIFY536_GLTESTS:-tests/test_pi_notice_display_536.py}" | tee -a $OUT/run.txt
    (cd $WT && TMPDIR=$GT $V1/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY536_TESTS} > $OUT/graphtraj.txt 2>&1; print "exit=$?" >> $OUT/graphtraj.txt)
    (cd $GLSRC && TMPDIR=$GL $V2/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY536_GLTESTS:-tests/test_pi_notice_display_536.py} > $OUT/graftling.txt 2>&1; print "exit=$?" >> $OUT/graftling.txt)
  else
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
  print "Judge FAILED/ERROR lines against 516's list (never blocking) and the accepted baseline; any other is NEW."
}

mkdir -p $W $BASE
case ${1:-help} in
  00) print "[00] Main. 预检。对话框: 无。约 1 分钟。"; logged $W/00.txt step_00 && next "zsh $THIS B" ;;
  B)  print "[B] Main. 从确切提交构建 BASELINE 与 CANDIDATE 两个 venv（$BASE）。对话框: 无。约 2 分钟。"; logged $W/B.txt step_B && next "zsh $THIS V0    （也可以先 zsh $THIS G）" ;;
  V0) print "[V0] Main 准备，然后 USER 在真实 Pi 里操作一次（修改前 BEFORE，BASELINE）。对话框: Main 无；USER 预期无。"; logged $W/V0.txt step_V baseline V0 && next "USER 完成并给出截图后: zsh $THIS V1" ;;
  V1) print "[V1] Main 准备，然后 USER 在真实 Pi 里操作一次（修改后 AFTER，CANDIDATE）。对话框: Main 无；USER 预期无。"; logged $W/V1.txt step_V candidate V1 && next "USER 完成并给出截图后: zsh $THIS Vr" ;;
  Vr) print "[Vr] Main. 只读 USER 两次会话的 Pi Session 文件。对话框: 无。<10 秒。"; logged $W/Vr.txt step_Vr && next "zsh $THIS G   （若尚未运行）" ;;
  G)  print "[G] Main. 两个全套测试（后台）。对话框: 无。立即返回。"; logged $W/G.txt step_G ;;
  GR) print "[GR] Main. 只读。对话框: 无。"; logged $W/GR.txt step_GR ;;
  *)  print "usage: zsh $THIS 00|B|V0|V1|Vr|G|GR   (order: 00 → B → V0 → USER → V1 → USER → Vr; G any time after B, then GR)"; next "zsh $THIS 00" ;;
esac
