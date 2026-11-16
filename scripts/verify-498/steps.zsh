#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 498 (design phase): read-only production facts about tool descendants.
#   zsh <this file> <P|F>      (one at a time; from any directory; no tee needed)
# Each step writes its own output to $OUT/<STEP>.txt (the script creates $OUT) as well as to the terminal.
# Dialog: none in every step (no model, no native host, no Claude Code, no pytest).
# P: preflight: shell, Python, CPUs, load; prints the F command with real paths. Seconds.
# F: facts, < 2 min. For every live execution of this user with a tool-descendants sidecar: per Runtime and per live
#    descendant pid, ppid, pgid, sid, session leader, executable, platform binary (csops), hardened runtime, P_EXEC,
#    environment read class (None/empty/readable) and marker class (this execution's/other/none). Retained sidecars
#    are scanned for recorded entries that are alive and readable without the marker, or whose recorded command looks
#    like a managed launch or a Runtime. Never prints an environment value or a marker value; command lines only
#    redacted (shown_command). Sends no signal; writes only $OUT/F.txt.
set -u
H=${VERIFY498_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
OUT=${VERIFY498_OUT:-$H/.graphtraj/core/state/tasks/498-tool-descendant-identification-design/realhost}
RT=${VERIFY498_RT:-$H/.venv-runtime}
STEP=${1:-help}
mkdir -p $OUT
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }

case $STEP in
P) {
  say "498 P preflight $(date '+%F %T %Z') | Expected dialog: none | seconds"
  print "script: $THIS (worktree $SRC at $(git -C $SRC rev-parse --short HEAD 2>/dev/null))"
  print "shell: $ZSH_VERSION | SHELL=${SHELL:-unset} | python: $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0], sys.executable)' 2>&1)"
  print "cpus: $(sysctl -n hw.ncpu 2>/dev/null) | load: $(sysctl -n vm.loadavg 2>/dev/null || uptime)"
  print "output dir: $OUT"
  $RT/bin/python -I -c "import sys; sys.path.insert(0, '$SRC/src'); import graftling.tool_descendants as t; print('graftling from', t.__file__, '| live processes of this user:', len(t._table()))" 2>&1
  next "zsh $THIS F"
} 2>&1 | tee $OUT/P.txt ;;
F) {
  say "498 F facts $(date '+%F %T %Z') | Expected dialog: none | < 2 min | read-only, no signals"
  /usr/bin/time -p $RT/bin/python -I $SD/facts498.py $SRC/src $H ${VERIFY498_SIDECARS:-}
  print "\nF done $(date +%T)"
  next "none; report $OUT/F.txt to the 498 Leader"
} 2>&1 | tee $OUT/F.txt ;;
*) print "usage: zsh $THIS <P|F>" ;;
esac
