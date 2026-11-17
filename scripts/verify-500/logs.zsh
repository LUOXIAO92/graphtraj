#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 500: did the kernel's memory-pressure killer (jetsam / memorystatus) end processes during the suites?
#   zsh <this file> <W498S|W499S1|W499S2|WSI>      (one window per step, in this order; from any directory)
# Read only: /usr/bin/log show over one suite's window with a narrow predicate (memorystatus/jetsam messages).
# No signal, no pytest, no model. Expected dialog: none. Duration < 2 min per window (19-20 min of log each).
# Writes the raw matching lines to $OUT/L-<window>.txt and this step's output to $OUT/L-<window>-run.txt.
# Prints per window: the suite (commit, result), the count of kill lines, each killed pid/name and reason, the
# window's peak 5-min load in the retained suite output (only start, quiet-check and end lines hold a load).
set -u
H=${VERIFY500_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
THIS=${0:A}
T=$H/.graphtraj/core/state/tasks
OUT=${VERIFY500_OUT:-$T/500-host-shutdown-survivor-death-after-498/realhost}
W=${1:-help}
case $W in
  W498S)  FROM='2026-11-17 10:08:00' TO='2026-11-17 10:27:00' NEXT=W499S1
          LABEL='498 S, 871aaaa9, 10:08:53-10:26:43: FAILED 5 (1 survivor test + 4 test_claude_native_host)'
          EVIDENCE=$T/498-tool-descendant-identification-design/realhost/S-suite.txt ;;
  W499S1) FROM='2026-11-17 11:56:00' TO='2026-11-17 12:16:00' NEXT=W499S2
          LABEL='499 S run 1, 871aaaa9, 11:56:32-12:15:35 (with install and probes): FAILED 7 (2 survivor tests + test_claude_native_host)'
          EVIDENCE=$T/499-production-adoption-496-498/adoption/raw-871aaaa9/S-run1/S-suite.txt ;;
  W499S2) FROM='2026-11-17 12:28:00' TO='2026-11-17 12:47:00' NEXT=WSI
          LABEL='499 S run 2, 871aaaa9, 12:28:22-12:46:21 (quiet host): FAILED 3 (1 survivor test + 2 test_claude_native_host)'
          EVIDENCE=$T/499-production-adoption-496-498/adoption/raw-871aaaa9/S-suite.txt ;;
  WSI)    FROM='2026-11-17 13:47:00' TO='2026-11-17 14:06:00' NEXT=
          LABEL='500 SI new, 871aaaa9 instrumented, 13:47:50-14:05:36: PASSED 4181, 0 failed (control)'
          EVIDENCE=$OUT/SI-new-suite.txt ;;
  *) print "usage: zsh $THIS <W498S|W499S1|W499S2|WSI>   e.g. zsh $THIS W498S"; exit 1 ;;
esac
mkdir -p $OUT
RAW=$OUT/L-$W.txt
{
  print -r -- ""
  print -r -- "### [L $W] unified log $FROM .. $TO, memorystatus/jetsam lines. Expected dialog: none. Duration < 2 min."
  print -r -- "suite: $LABEL"
  print -r -- "== start $(date +%T)"
  /usr/bin/log show --style compact --start "$FROM" --end "$TO" \
    --predicate 'eventMessage CONTAINS[c] "memorystatus" OR eventMessage CONTAINS[c] "jetsam"' > $RAW 2>&1
  print -r -- "== log show exit $? at $(date +%T); raw lines: $(grep -c . $RAW) in $RAW"
  # The first line of log show is its header ("Timestamp Ty Process[PID:TID]").
  kills=$(grep -ic 'kill' $RAW)
  print -r -- "kill lines (containing 'kill'): $kills"
  # memorystatus kill lines name "pid <n> [<name>] (<reason> ...)"; print each with its time.
  grep -i 'kill' $RAW | sed -nE 's/^([0-9-]+ [0-9:.]+).*pid ([0-9]+) \[([^]]*)\] \(([^)]*)\).*/  \1 pid \2 [\3] reason (\4)/p' | head -n 80
  (( kills > 0 )) && { print -r -- "first raw kill lines:"; grep -i 'kill' $RAW | head -n 10 | cut -c1-300; }
  print -r -- "other lines (no 'kill'), first 5:"; grep -iv 'kill' $RAW | sed -n '2,6p' | cut -c1-300
  if [[ -r $EVIDENCE ]]; then
    peak=$(grep -o 'loadavg { [0-9.]* [0-9.]* [0-9.]* }' $EVIDENCE | awk '{ if ($4 + 0 > m) m = $4 + 0 } END { print m + 0 }')
    print -r -- "peak 5-min load in the retained suite output ($(grep -c 'loadavg {' $EVIDENCE) load lines: start, quiet checks, end only): $peak  [$EVIDENCE]"
  else
    print -r -- "suite output not readable: $EVIDENCE"
  fi
  print -r -- ""
  if [[ -n $NEXT ]]; then print -r -- "==> next (Main pastes): zsh $THIS $NEXT"
  else print -r -- "==> next (Main pastes): none; report $OUT (L-W498S-run.txt L-W499S1-run.txt L-W499S2-run.txt L-WSI-run.txt and the L-*.txt raw files) to the 500 Engineer"; fi
} 2>&1 | tee $OUT/L-$W-run.txt
