#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 499 acceptance helper: a second full S run on a quiet host, keeping run 1's evidence. steps.zsh is unchanged.
#   zsh <abs>/scripts/adopt-499/srerun.zsh keep      move run 1's S files into raw-871aaaa9/S-run1/, print the S command
#   zsh <abs>/scripts/adopt-499/srerun.zsh compare   after run 2's '== DONE' (and S2): run 1 vs run 2 failures
# Paths are derived as steps.zsh derives them (same TARGET, TASK, R). Read only apart from keep's moves inside R.
# Never signals a process. Native dialog: none. Only a rehearsal sets ADOPT499_*.
set -u
SD=${0:A:h}
H=${ADOPT499_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT499_BASE:-$H/tmp/499}
TARGET=871aaaa9ea7f63998990cb6600ca098d320e18c8
C8=${TARGET[1,8]}
TASK=499-production-adoption-496-498
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw-$C8
SV=$BASE/svenv-$C8
STEPS=$SD/steps.zsh
THIS=${0:A}
K=$R/S-run1
FILES=(S-setup.txt S-setup-imports.txt S-suite.txt S-shards S-ps.txt S-quiet-ps.txt S2.txt)
[[ -n ${ADOPT499_STUB:-} ]] && path=($ADOPT499_STUB $path)   # rehearsal only: stub ps first

# Failing test ids of a run, parsed as steps.zsh's _Srun does (FAILED/ERROR lines of S-shards/failures.txt).
ids_of() { sed -n 's/^FAILED //p; s/^ERROR //p' $1/S-shards/failures.txt 2>/dev/null | sed 's/ - .*//' | sort -u; }

case ${1:-help} in
keep)
  print "[srerun keep] Main. Keep S run 1's evidence in $K before a second S run. Dialog: none. Never signals."
  # Same rule as busy499.py 'ours' (steps.zsh S): our _Srun job, or a suite runner from our test venv.
  ps -axww -o pid=,ppid=,etime=,command= > $R/srerun-ps.txt 2>&1
  out=$($CONDA -I $SD/busy499.py $R/srerun-ps.txt $$ "$STEPS _Srun" "$SV/bin/"); print -r -- "$out" | grep -E '^(ours|  ours)'
  if [[ $(print -r -- "$out" | sed -n 's/^ours: //p') != 0 ]]; then
    print "STOP: an S of ours is running (listed under 'ours:'). Wait for its '== DONE': tail -n 25 $R/S-suite.txt"; exit 1
  fi
  [[ -e $K ]] && { print "STOP: $K already exists; run 1's evidence is kept there already. Nothing moved."; exit 1; }
  mkdir -p $K || exit 1
  n=0; for f in $FILES; do
    if [[ -e $R/$f ]]; then mv $R/$f $K/ || exit 1; print "moved: $R/$f -> $K/$f"; (( n++ )); else print "absent (not moved): $R/$f"; fi
  done
  print "kept $n of ${#FILES} in $K"
  print "\n==> 下一步 / next（直接粘贴）: zsh $STEPS S    （'== DONE' 与 S2 之后: zsh $THIS compare）" ;;
compare)
  print "[srerun compare] Main. S run 1 ($K) vs run 2 ($R). Dialog: none. Read only."
  [[ -d $K ]] || { print "STOP: no $K (run 'zsh $THIS keep' before the second S)"; exit 1; }
  if ! grep -q '^== DONE' $R/S-suite.txt 2>/dev/null; then
    print "PENDING: run 2 has no '== DONE' in $R/S-suite.txt yet (tail -n 25 $R/S-suite.txt). Rerun later: zsh $THIS compare"; exit 1
  fi
  print "run 1 $(grep -E '^== totals' $K/S-suite.txt 2>/dev/null | tail -1)"
  print "run 1 $(grep -E '^== new failures' $K/S-suite.txt 2>/dev/null | tail -1)"
  print "run 2 $(grep -E '^== totals' $R/S-suite.txt | tail -1)"
  run1=(${(f)"$(ids_of $K)"}); run2=(${(f)"$(ids_of $R)"})
  print "== run 1 failing ids (${#run1}): failed again in run 2?"
  for id in $run1; do (( ${run2[(Ie)$id]} )) && print "  FAILED AGAIN in run 2: $id" || print "  passed in run 2: $id"; done
  new2=(${(f)"$(sed -n 's/^NEW \([^ ]*\) .*/\1/p' $R/S-suite.txt | sort -u)"})
  print "== run 2 NEW ids (not ATTRIBUTED, from run 2's S-suite.txt):"
  (( ${#new2} )) && print -l -- "  "${^new2} || print "  (none)"
  grep -E '^leftover processes of the suite' $R/S2.txt 2>/dev/null | sed 's/^/run 2 S2: /' || print "run 2 S2: not run yet (zsh $STEPS S2)"
  print "== run 2 new failures: ${#new2}" ;;
*) print "usage: zsh $THIS keep | compare" ;;
esac
