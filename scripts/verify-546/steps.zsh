#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 546: a send right after create is refused with runtime-input-closed while the child's execution is finishing.
#   zsh scripts/verify-546/steps.zsh <STEP>        (Main's Bash, from this Task's Worktree)
# Order: 00 -> B (repeat until VERDICT REPRODUCED, at most 5) -> A (repeat as often as B) -> T -> TS (until done) -> C
#   00  versions; builds BEFORE (GraphTraj f754d3a9 + graftling 6794ce0) and AFTER (this Worktree HEAD + graftling
#       candidate) venvs and projects; READY-546-CLAUDE (one line, model + login).
#   B   BEFORE: one headless Claude Main (Main kind: Claude Code; child Runtime: claude) runs create -> send at once
#       (up to 5 sends) -> wait; prints each agents call with times, the child's record (each input's receipt and its
#       gap to the execution's recorded end) and VERDICT 546.
#   A   AFTER: the same on the candidate. A send landing in the window shows delivery next-execution, not an error.
#   T   full suites in the background: graftling (candidate) and GraphTraj (this Worktree, candidate graftling).
#   TS  status/results of T (516-listed failures are non-blocking).
#   C   copies runs and suite outputs to <Worktree>/.state/realhost/.
# Every step raises no native dialog (headless claude -p with --allowedTools mcp__graphtraj__agents).
# Layout: BASE=/private/tmp/send-546 (VERIFY546_BASE overrides; rehearsal only): before/ after/ (venv, project, runs/),
# t/ (test venv, sources). Never written: ~/.claude, dotfiles, the Harness (except C's copy), .venv-runtime.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice no_hup
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY546_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY546_H:-${WT:h:h:h:h}}
BASE=${VERIFY546_BASE:-/private/tmp/send-546}
GD=$WT/.scratch/graftling-git                          # graftling clone's git dir (branch agent/546-...)
GT_BEFORE=f754d3a9 GL_BEFORE=6794ce0
GL_AFTER=${VERIFY546_GL_AFTER:-$(git --git-dir=$GD rev-parse agent/546-send-after-create-runtime-input-closed)}
GT_AFTER=$(git -C $WT rev-parse HEAD)
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: click, yaml, websockets
CONDA=${VERIFY546_CONDA:-$HOME/miniconda3/bin/python3.13}
MODEL=${VERIFY546_MODEL:-claude-sonnet-5-5}
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
CLAUDE=${VERIFY546_CLAUDE:-$(command -v claude || print -r -- $HOME/.local/bin/claude)}
DEST=${VERIFY546_DEST:-$WT/.state/realhost}
PYTEST_TMP=${TMPDIR:-/tmp}

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
copy_deps() {
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}

[[ -d $H/.graphtraj || -n ${VERIFY546_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE

build() {  # $1 phase, $2 GraphTraj commit, $3 graftling commit
  local PB=$BASE/$1 V=$BASE/$1/venv P=$BASE/$1/project S=$BASE/$1/src
  if [[ -f $V/installed && $(<$V/installed) == "$2 $3" ]]; then print "$1: venv holds GraphTraj ${2[1,10]} + graftling ${3[1,10]}"
  else
    rm -rf $V $S && mkdir -p $S/gt $S/gl $PB/wheels
    git -C $WT archive $2 | tar -x -C $S/gt && git --git-dir=$GD archive $3 | tar -x -C $S/gl \
      || { print "STOP: cannot extract $2 / $3"; return 1; }
    $CONDA -m venv $V && copy_deps $V || return 1
    { $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
        -w $PB/wheels $S/gl/src/graftling \
      && $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $PB/wheels/graftling-*.whl \
      && $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $PB/wheels $S/gt \
      && $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $PB/wheels/graphtraj-*.whl
    } > $PB/install.log 2>&1 || { print "STOP: $1 install failed:"; tail -8 $PB/install.log; return 1; }
    print -r -- "$2 $3" > $V/installed
  fi
  (cd $PB && clean $V/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m; print("venv:", m.version("graftling"), graftling.__file__, "| graphtraj", graphtraj.__file__)')
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P && (cd $P && git init -q -b main && print -r -- "# 546 scratch project" > README.md && git add README.md \
      && git -c user.name=546 -c user.email=546@invalid commit -qm "Initial source") || return 1
  fi
  [[ -f $P/.graphtraj/config.yml ]] || (cd $P && print y | clean $V/bin/graphtraj setup | tail -1) || return 1
  (cd $P && clean $V/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $CLAUDE --write >/dev/null) \
    && print "$1 project $P: claude host configuration written (.mcp.json, .claude/) with $V/bin/python" \
    || { print "STOP: $1 claude host configuration failed"; return 1; }
}

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | claude: $CLAUDE | $($CLAUDE --version 2>&1 | head -1) | model $MODEL"
  print -r -- "BEFORE: GraphTraj $GT_BEFORE + graftling $GL_BEFORE | AFTER: GraphTraj $GT_AFTER + graftling $GL_AFTER (git dir $GD)"
  say "builds (dialog: none)"
  build before $GT_BEFORE $GL_BEFORE || return 1
  build after $GT_AFTER $GL_AFTER || return 1
  say "READY-546-CLAUDE in $BASE/before/project (dialog: none)"
  mkdir -p $BASE/ready
  (cd $BASE/before/project && clean $CONDA -I $SD/drv546.py ready $BASE/before/project $BASE/ready $CLAUDE $MODEL) \
    || { print "STOP: Claude is not ready"; return 1; }
  next "zsh $THIS B"
}

run_phase() {  # $1 before|after
  local done_runs=($BASE/$1/runs/run-*(N/)); local P=$BASE/$1/project n=$(( ${#done_runs} + 1 ))
  [[ -f $BASE/$1/venv/installed ]] || { print "STOP: run 00 first"; return 1; }
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
  next "zsh $THIS A   (as many runs as B took, or until a CLOSING WINDOW HIT line), then: zsh $THIS T"
}

step_T() {
  local TB=$BASE/t; mkdir -p $TB
  [[ -z $(ps -axww -o command= | grep -E -- '-m pytest' | grep -v grep) ]] || { print "STOP: another test run is running"; return 1; }
  local RUNTMP=${PYTEST_TMP:A}/verify-546-T-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
  print -r -- "pytest temp root (TMPDIR, outside the Harness): $RUNTMP"
  local S=$TB/gl-$GL_AFTER V=$TB/venv-$GL_AFTER
  if [[ ! -f $V/installed ]]; then
    rm -rf $S $V && mkdir -p $S && git --git-dir=$GD archive $GL_AFTER | tar -x -C $S || return 1
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    { $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $S/src/graftling \
      && $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT
    } > $TB/install.log 2>&1 || { print "STOP: test venv install failed"; tail -8 $TB/install.log; return 1; }
    touch $V/installed
  fi
  (cd $RUNTMP && $V/bin/python -I -c 'import graftling, graphtraj, pytest; print("graftling", graftling.__file__, "| graphtraj", graphtraj.__file__, "| pytest", pytest.__version__)')
  local files=${VERIFY546_TESTS:-}
  say "suites started in the background (dialog: none)${files:+; REHEARSAL limited to: $files}"
  rm -f $TB/gl.txt $TB/gt.txt
  (cd $S && TMPDIR=$RUNTMP/gl $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${files:+${=files}} > $TB/gl.txt 2>&1; print "exit=$?" >> $TB/gl.txt) &!
  mkdir -p $RUNTMP/gl $RUNTMP/gt
  if [[ -z $files ]]; then
    (cd $WT && TMPDIR=$RUNTMP/gt $V/bin/python -m pytest -p no:cacheprovider -q -rfE tests > $TB/gt.txt 2>&1; print "exit=$?" >> $TB/gt.txt) &!
  else print "exit=skipped (rehearsal)" > $TB/gt.txt; fi
  print -r -- "graftling suite: $TB/gl.txt (tree $S) | GraphTraj suite: $TB/gt.txt (tree $WT)"
  next "zsh $THIS TS"
}

step_TS() {
  local TB=$BASE/t f
  for f in gl gt; do
    [[ -f $TB/$f.txt ]] || { print "$f: not started"; continue; }
    if grep -q '^exit=' $TB/$f.txt; then
      print -r -- "$f: $(grep '^exit=' $TB/$f.txt) | $(grep -E '(passed|failed|error)' $TB/$f.txt | tail -1)"
      grep -E '^(FAILED|ERROR) ' $TB/$f.txt | sed 's/^/    /'
    else print -r -- "$f: running | $(tail -c 200 $TB/$f.txt | tr '\n' ' ')"; fi
  done
  if grep -q '^exit=' $TB/gl.txt(N) && grep -q '^exit=' $TB/gt.txt(N); then
    next "zsh $THIS C   (compare FAILED lines above with the 516 list; any other one blocks)"
  else next "zsh $THIS TS   (again in a few minutes)"; fi
}

step_C() {
  say "copy to $DEST (dialog: none)"
  mkdir -p $DEST
  local ph
  for ph in before after; do [[ -d $BASE/$ph/runs ]] && { mkdir -p $DEST/$ph; cp -Rp $BASE/$ph/runs $DEST/$ph/; } done
  [[ -d $BASE/ready ]] && cp -Rp $BASE/ready $DEST/
  [[ -d $BASE/t ]] && { mkdir -p $DEST/t; cp -p $BASE/t/gl.txt(N) $BASE/t/gt.txt(N) $DEST/t/; }
  print -r -- "copied: $(cd $DEST && print -l **/summary.txt(N) t/*(N) | tr '\n' ' ')"
  grep -h 'VERDICT 546' $DEST/*/runs/run-*/summary.txt(N) | sort | uniq -c
  next "Leader: read $DEST/{before,after}/runs/run-*/summary.txt and $DEST/t/"
}

case $STEP in
  00) step_00 ;;
  B) step_B ;;
  A) step_A ;;
  T) step_T ;;
  TS) step_TS ;;
  C) step_C ;;
  *) print "usage: zsh $THIS <00|B|A|T|TS|C>"; return 2 ;;
esac
