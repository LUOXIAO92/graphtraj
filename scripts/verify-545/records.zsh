#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 545 c1: re-read each case's DSH session record with the fixed sessions545.mjs (all zstd frames).
#   zsh scripts/verify-545/records.zsh before|after          (Main's Bash, from this Task's Worktree; dialog: none)
# For every case dir $BASE/<phase>/runs/run1/<case> (G, S, GI) it rewrites session-record.txt there and prints the
# verdict lines. A case keeps only the session created between its build.txt (case start) and its summary.json
# (driver end), so G and GI, which share one project, do not show each other's session.
# Read only on DSH_HOME and the projects; writes only session-record.txt in the case dirs (or, with
# VERIFY545_RECORDS_OUT=<dir>, <dir>/<phase>-<case>-session-record.txt instead: the Engineer rehearsal).
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
BASE=${VERIFY545_BASE:-/private/tmp/dsh-ui-545}
PH=${1:-}
[[ $PH == (before|after) ]] || { print -r -- "usage: zsh $THIS before|after"; return 2; }
PB=$BASE/$PH; DH=$PB/dsh-home
path=(/opt/homebrew/bin $path)
print -r -- "== [records $PH] DSH_HOME $DH (read only). Dialog: none."
[[ -d $DH && -d $PB/runs/run1 ]] || { print -r -- "STOP: no $PH runs under $PB"; return 1; }
local c R cwd since until out n=0
for R in $PB/runs/run1/*(N/); do
  c=${R:t}
  case $c in G|GI) cwd=$PB/project ;; S) cwd=$PB/work-standalone ;; *) continue ;; esac
  [[ -f $R/build.txt ]] || { print -r -- "$c: no build.txt; skipped"; continue; }
  since=$(( $(stat -f %m $R/build.txt) * 1000 - 5000 ))
  if [[ -f $R/summary.json ]]; then until=$(( $(stat -f %m $R/summary.json) * 1000 + 5000 )); else until=Infinity; fi
  if [[ -n ${VERIFY545_RECORDS_OUT:-} ]]; then mkdir -p $VERIFY545_RECORDS_OUT; out=$VERIFY545_RECORDS_OUT/$PH-$c-session-record.txt
  else out=$R/session-record.txt; fi
  node $SD/sessions545.mjs $DH $cwd $since $until > $out 2>&1 || print -r -- "$c: reader rc $?"
  print -r -- "-- $PH $c ($(<$R/build.txt | cut -d' ' -f4) prompt; $out)"
  grep -E '^(session|  relay|skipped|no Main session)' $out | sed 's/^/   /'
  (( ++n ))
done
(( n )) || print -r -- "no case dirs (G, S, GI) under $PB/runs/run1"
print -r -- "Expected: before = 'inside a running turn' per relay; after = each relay 'turn >= 2 step 1 -> opened its turn', 'inside a running turn 0', 'duplicate ids []' (GI: turn 2 step 1 as well)."
print -r -- "
==> next (paste as is): $([[ $PH == before ]] && print "zsh $THIS after" || print "zsh $SD/steps.zsh C")"
