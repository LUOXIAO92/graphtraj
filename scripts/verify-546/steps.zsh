#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 546: a send right after create is refused with runtime-input-closed while the child's execution is finishing.
#   zsh scripts/verify-546/steps.zsh <STEP>        (Main's Bash, from this Task's Worktree)
# Order: 00 -> B (repeat until VERDICT REPRODUCED, at most 5) -> A (as many runs) -> G -> GR (until both exit=) -> C
#   00  versions; BEFORE (GraphTraj f754d3a9 + graftling 6794ce0) and AFTER (this Worktree HEAD + graftling
#       candidate) venvs from git archive, isolated projects (graphtraj setup + claude host configuration);
#       READY-546-CLAUDE; in BOTH projects a headless Main with B/A's flags loads the agents tool and an agents status
#       call (no agent) is not refused for authority.
#   B   BEFORE: one headless Claude Main (Main kind Claude Code; child Runtime claude) runs create -> send at once (up
#       to 5 sends) -> wait; prints each agents call with times, the child's record (each input receipt and its gap to
#       the execution's recorded end) and VERDICT 546.
#   A   AFTER: the same on the candidate. A send landing in the window shows delivery next-execution, not an error.
#   G   full suites in the background, one after the other: GraphTraj (scripts/run_test_shards.py --shards 6
#       --timeout 1500 -- -rA; this Worktree's src, graftling wheel from git archive of the candidate) then graftling
#       (git archive of the candidate). New pytest temp root under TMPDIR, outside the Harness (printed).
#   GR  read only: newest G; exit lines and every FAILED/ERROR line classed known (516; graftling pi/DSH flake) or NEW.
#   C   copies the runs, probes and the newest G to <Worktree>/.state/realhost/.
# No step raises a native dialog (headless claude -p, --allowedTools mcp__graphtraj__agents, MCP server approved in
# the isolated project's own .claude/settings.local.json as verify-533 did).
# Layout: projects under BASE=/private/tmp/send-546/<before|after>/project, runs under BASE/<phase>/runs; venvs and
# suite outputs under T=<Harness>/tmp/546. Never written: ~/.claude, dotfiles, the Harness outside tmp/546 (and C's
# copy), .venv-runtime (read only: click, yaml, websockets copied out). VERIFY546_* overrides are for the rehearsal.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice no_hup
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY546_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY546_H:-${WT:h:h:h:h}}
BASE=${VERIFY546_BASE:-/private/tmp/send-546}
T=${VERIFY546_T:-$H/tmp/546}
GD=$WT/.scratch/graftling-git                          # graftling clone's git dir (branch agent/546-...)
GT_BEFORE=f754d3a9 GL_BEFORE=6794ce0
GL_AFTER=${VERIFY546_GL_AFTER:-$(git --git-dir=$GD rev-parse agent/546-send-after-create-runtime-input-closed)}
GT_AFTER=$(git -C $WT rev-parse HEAD)
RT=$H/.venv-runtime/lib/python3.13/site-packages
CONDA=${VERIFY546_CONDA:-$HOME/miniconda3/bin/python3.13}
MODEL=${VERIFY546_MODEL:-claude-sonnet-5-5}
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
KNOWN_GL=(test_a_request_notice_returns_promptly_while_pi_holds_it)   # graftling flake, also fails on base 6794ce0 (546 validation)
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
CLAUDE=${VERIFY546_CLAUDE:-$(command -v claude || print -r -- $HOME/.local/bin/claude)}
DEST=${VERIFY546_DEST:-$WT/.state/realhost}
PYTEST_TMP=${TMPDIR:-/tmp}

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
copy_deps() {
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
pipq() { "$@" -q --disable-pip-version-check --no-cache-dir --no-index --no-deps; }
gl_wheel() {  # $1 graftling commit -> prints the wheel path built from git archive (cached under T)
  local S=$T/src-gl-${1[1,12]} N=$T/wheels-gl-${1[1,12]}
  if [[ -z $(print $N/graftling-*.whl(N)) ]]; then
    rm -rf $S $N && mkdir -p $S $N && git --git-dir=$GD archive $1 | tar -x -C $S \
      && pipq $CONDA -m pip wheel --no-build-isolation -w $N $S/src/graftling >/dev/null || return 1
  fi
  print -r -- $N/graftling-*.whl(N[1])
}
check_tmp() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}

[[ -d $H/.graphtraj || -n ${VERIFY546_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE $T

build() {  # $1 phase, $2 GraphTraj commit, $3 graftling commit
  local PB=$BASE/$1 V=$T/venv-$1 P=$BASE/$1/project S=$T/src-gt-${2[1,12]} N=$T/wheels-gt-${2[1,12]} w
  if [[ -f $V/installed && $(<$V/installed) == "$2 $3" ]]; then print "$1: venv $V holds GraphTraj ${2[1,10]} + graftling ${3[1,10]}"
  else
    w=$(gl_wheel $3) || { print "STOP: graftling $3 wheel failed"; return 1; }
    rm -rf $V $S $N && mkdir -p $S $N && git -C $WT archive $2 | tar -x -C $S || { print "STOP: cannot extract $2"; return 1; }
    $CONDA -m venv $V && copy_deps $V || return 1
    { pipq $V/bin/python -m pip install $w && pipq $CONDA -m pip wheel --no-build-isolation -w $N $S \
      && pipq $V/bin/python -m pip install $N/graphtraj-*.whl(N[1]); } > $T/install-$1.log 2>&1 \
      || { print "STOP: $1 install failed:"; tail -8 $T/install-$1.log; return 1; }
    print -r -- "$2 $3" > $V/installed
  fi
  (cd $T && clean $V/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m, sys
from graftling.control import AgentControl as A
print(sys.argv[1], "venv:", m.version("graftling"), graftling.__file__, "| graphtraj", graphtraj.__file__,
      "| 546 fallback in graftling:", hasattr(A, "_send_after_close"))' $1)
  mkdir -p $PB
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P && (cd $P && git init -q -b main && print -r -- "# 546 scratch project" > README.md && git add README.md \
      && git -c user.name=546 -c user.email=546@invalid commit -qm "Initial source") || return 1
  fi
  [[ -f $P/.graphtraj/config.yml ]] || (cd $P && print y | clean $V/bin/graphtraj setup | tail -1) || return 1
  (cd $P && clean $V/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $CLAUDE --write >/dev/null) \
    || { print "STOP: $1 claude host configuration failed"; return 1; }
  # The host configuration writes .mcp.json and .claude/settings.local.json (env only); it does not approve the
  # .mcp.json server, so -p would not load it. As verify-533: approve it in this isolated project's own file.
  $CONDA -I -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); s = json.loads(p.read_text()) if p.exists() else {}
s["enabledMcpjsonServers"] = sorted(set(s.get("enabledMcpjsonServers") or []) | {"graphtraj"})
p.write_text(json.dumps(s, indent=2) + "\n")
m = json.loads(pathlib.Path(sys.argv[2]).read_text())["mcpServers"]["graphtraj"]
print(sys.argv[3], "project", sys.argv[4] + ": .mcp.json graphtraj ->", " ".join([m["command"]] + m["args"][:3]),
      "| approval: enabledMcpjsonServers", s["enabledMcpjsonServers"], "in", p)' \
    $P/.claude/settings.local.json $P/.mcp.json $1 $P || return 1
}

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | claude: $CLAUDE | $($CLAUDE --version 2>&1 | head -1) | model $MODEL"
  print -r -- "BEFORE: GraphTraj $GT_BEFORE + graftling $GL_BEFORE | AFTER: GraphTraj $GT_AFTER + graftling $GL_AFTER (git dir $GD)"
  print -r -- "projects: $BASE/{before,after}/project | venvs and suites: $T"
  say "builds (dialog: none)"
  build before $GT_BEFORE $GL_BEFORE || return 1
  build after $GT_AFTER $GL_AFTER || return 1
  mkdir -p $BASE/ready
  say "READY-546-CLAUDE (dialog: none)"
  (cd $BASE/before/project && clean $CONDA -I $SD/drv546.py ready $BASE/before/project $BASE/ready $CLAUDE $MODEL) \
    || { print "STOP: Claude is not ready"; return 1; }
  say "agents tool in each project with B/A's flags; one agents status call without agent (dialog: none)"
  local ph rc=0
  for ph in before after; do
    (cd $BASE/$ph/project && clean $CONDA -I $SD/drv546.py probe $BASE/$ph/project $BASE/ready $CLAUDE $MODEL $ph) || rc=1
  done
  (( rc == 0 )) || { print "STOP: a CHECK 546 AGENTS line is FAIL (stream: $BASE/ready/probe-<phase>.jsonl); report it to the Leader"; return 1; }
  next "zsh $THIS B"
}

run_phase() {  # $1 before|after
  local done_runs=($BASE/$1/runs/run-*(N/)); local P=$BASE/$1/project n=$(( ${#done_runs} + 1 ))
  [[ -f $T/venv-$1/installed ]] || { print "STOP: run 00 first"; return 1; }
  local O=$BASE/$1/runs/run-$n; mkdir -p $O
  say "$1 run $n: Claude Main ($MODEL) in $P: create -> send at once -> wait (dialog: none; up to ~5 min)"
  clean $CONDA -I $SD/drv546.py main $P $O $CLAUDE $MODEL | tee $O/summary.txt
}

step_B() {
  run_phase before || return 1
  if grep -q 'VERDICT 546: REPRODUCED' $BASE/before/runs/run-*/summary.txt(N); then next "zsh $THIS A"
  else next "zsh $THIS B   (again; the window is short. After 5 runs without REPRODUCED, report to the Leader)"; fi
}

step_A() {
  run_phase after || return 1
  local nb=($BASE/before/runs/run-*(N/)) na=($BASE/after/runs/run-*(N/))
  if (( ${#na} < ${#nb} )); then next "zsh $THIS A   (run ${#na} of ${#nb}; as many runs as B took)"
  else next "zsh $THIS G"; fi
}

step_G() {
  say "G: GraphTraj full suite (6 shards, --timeout 1500, -rA) then graftling full suite, background (dialog: none; ~30 min; run nothing else meanwhile)"
  check_tmp || return 1
  local dirty=$(git -C $WT status --porcelain -- src tests)
  print -r -- "uncommitted in $WT src/tests: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  local RUNTMP=${PYTEST_TMP:A}/verify-546-G-$(date +%Y%m%dT%H%M%S) d
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP/gt $RUNTMP/gl
  print -r -- "pytest temp root (new; outside the Harness, no Harness marker above): $RUNTMP"
  local w; w=$(gl_wheel $GL_AFTER) || { print "STOP: graftling wheel failed"; return 1; }
  # GraphTraj suite venv: graftling = the candidate wheel (git archive); GraphTraj = this Worktree (editable; it
  # writes no build files into the Worktree: git status --ignored shows only __pycache__).
  local V=$T/venv-g-${GL_AFTER[1,12]}
  if [[ ! -f $V/installed ]]; then
    rm -rf $V && $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    { pipq $V/bin/python -m pip install $w && pipq $V/bin/python -m pip install --no-build-isolation -e $WT; } > $T/install-g.log 2>&1 \
      || { print "STOP: GraphTraj test venv failed"; tail -8 $T/install-g.log; return 1; }
    touch $V/installed
  fi
  # graftling suite: its conftest requires subprocesses to import the tested tree, so the git-archive tree of the
  # candidate (not the clone) is installed editable into its own venv.
  local GS=$T/src-gl-${GL_AFTER[1,12]} VL=$T/venv-gl-${GL_AFTER[1,12]}
  if [[ ! -f $VL/installed ]]; then
    rm -rf $VL && $CONDA -m venv --system-site-packages $VL && copy_deps $VL || return 1
    pipq $VL/bin/python -m pip install --no-build-isolation -e $GS/src/graftling > $T/install-gl.log 2>&1 \
      || { print "STOP: graftling test venv failed"; tail -8 $T/install-gl.log; return 1; }
    touch $VL/installed
  fi
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("GraphTraj suite imports: graphtraj", graphtraj.__file__, "| graftling", graftling.__file__, "| pytest", pytest.__version__)') || return 1
  (cd $RUNTMP && $VL/bin/python -I -c 'import graftling; print("graftling suite imports: graftling", graftling.__file__)') || return 1
  local R=$T/G-${GT_AFTER[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "GraphTraj $GT_AFTER (tree $WT) | graftling $GL_AFTER (tree $GS)"; } > $R/run.txt
  local gtcmd glcmd
  if [[ -n ${VERIFY546_GT_TESTS:-} ]]; then
    print -r -- "REHEARSAL: GraphTraj tests limited to $VERIFY546_GT_TESTS, graftling to ${VERIFY546_GL_TESTS:-all} (plain pytest, same venvs, temp root and exit lines)" | tee -a $R/run.txt
    gtcmd=($V/bin/python -m pytest -p no:cacheprovider -q -rA ${=VERIFY546_GT_TESTS})
  else
    gtcmd=($V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA)
  fi
  glcmd=($VL/bin/python -m pytest -p no:cacheprovider -q -rA ${=${VERIFY546_GL_TESTS:-tests}})
  ( (cd $WT && TMPDIR=$RUNTMP/gt $gtcmd > $R/gt.txt 2>&1; print "exit=$?" >> $R/gt.txt)
    (cd $GS && TMPDIR=$RUNTMP/gl $glcmd > $R/gl.txt 2>&1; print "exit=$?" >> $R/gl.txt) ) < /dev/null > /dev/null 2>&1 &!
  print -r -- $R > $T/G-latest
  print -r -- "started in the background at $(date +%T): $R/gt.txt then $R/gl.txt (each ends with a line 'exit=N')"
  next "zsh $THIS GR   (repeat until both show exit=)"
}

classify() {  # FAILED/ERROR lines of files $@ as known (516, graftling flake) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    elif (( ${KNOWN_GL[(Ie)${t##*::}]} )); then print -r -- "known (graftling flake, fails on base 6794ce0 too): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

step_GR() {
  say "GR: read only; newest G (dialog: none)"
  local R=$(cat $T/G-latest 2>/dev/null)
  [[ -n $R && -f $R/run.txt ]] || { print "no G yet"; next "zsh $THIS G"; return 0; }
  cat $R/run.txt
  local f done=1
  for f in gt gl; do
    print -r -- "---- $f ($R/$f.txt)"
    if [[ -f $R/$f.txt ]] && grep -q '^exit=' $R/$f.txt; then
      grep -E '^(exit=|leftover processes|ABNORMAL)' $R/$f.txt; grep -E '(passed|failed|error)' $R/$f.txt | grep -E '^=*.* in [0-9.]+s' | tail -1
    else done=0; print -r -- "running | $(tail -c 160 $R/$f.txt 2>/dev/null | tr '\n' ' ')"; fi
  done
  print -r -- "---- classification (GraphTraj gt.txt + shards, graftling gl.txt)"
  classify $R/gt.txt $R/shards/*(N.) $R/gl.txt
  if (( done )); then next "zsh $THIS C   (pass: exit=0, or only 'known' lines; any NEW line blocks)"
  else next "zsh $THIS GR   (again in a few minutes)"; fi
}

step_C() {
  say "copy to $DEST (dialog: none)"
  mkdir -p $DEST
  local ph R=$(cat $T/G-latest 2>/dev/null)
  for ph in before after; do [[ -d $BASE/$ph/runs ]] && { mkdir -p $DEST/$ph; cp -Rp $BASE/$ph/runs $DEST/$ph/; } done
  [[ -d $BASE/ready ]] && cp -Rp $BASE/ready $DEST/
  [[ -n $R && -d $R ]] && { rm -rf $DEST/G; mkdir -p $DEST/G; cp -Rp $R/. $DEST/G/; }
  print -r -- "copied: $(cd $DEST && print -l */runs/run-*/summary.txt(N) ready/probe-*.jsonl(N) G/*.txt(N) | tr '\n' ' ')"
  grep -h 'VERDICT 546' $DEST/*/runs/run-*/summary.txt(N) | sort | uniq -c
  next "Leader: read $DEST/{before,after}/runs/run-*/summary.txt, $DEST/ready/ and $DEST/G/"
}

case $STEP in
  00) step_00 ;;
  B) step_B ;;
  A) step_A ;;
  G) step_G ;;
  GR) step_GR ;;
  C) step_C ;;
  *) print "usage: zsh $THIS <00|B|A|G|GR|C>"; return 2 ;;
esac
