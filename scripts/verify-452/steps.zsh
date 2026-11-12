#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 452 real-host check: an agents-tool child of a Runner member ends with outcome completed, not
# owner-exited, after the member's turn ends. Runs 449's steps 00/00u/01/02 (scripts/verify-449/steps.zsh)
# at the commit under test in the same isolated project ~/graphtraj-verify-449, writing to 452's realhost/.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/452-isolated-default-model-child-hang/scripts/verify-452/steps.zsh <00|00u|01|02>
# 00  Main. Dialog: none. Keeps the 449 child records found in the project, then 449's 00: scratch venv
#     from COMMIT, recreated isolated project, one-line model/login answer. ~2-4 min.
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust (one dialog).
# 01  Main. Dialog: none. Starts the probe Main in the background; returns at once.
# 02  Main. Dialog: none. Waits (<= 9 min) for that Main, runs 449's checks, then 452's: every ended execution
#     of the child has outcome completed and no execution failed with owner-exited.
# Before/after: VERIFY452_COMMIT=cfd5e432 runs the same steps without the fix (expect 452 FAIL: owner-exited).
# Never touches production .venv-runtime (449's steps copy click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=${0:A:h:h:h}
THIS=${0:A}
INNER=$WT/scripts/verify-449/steps.zsh
COMMIT=${VERIFY452_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=$HOME/graphtraj-verify-449
OUT=${VERIFY452_OUT:-$H/.graphtraj/core/state/tasks/452-isolated-default-model-child-hang/realhost}
STEP=${1:-help}
mkdir -p $OUT

# 449's steps, at this commit and output directory; their 'next' lines name this script instead.
inner() {
  VERIFY449_WT=$WT VERIFY449_COMMIT=$COMMIT VERIFY449_BASE=$BASE VERIFY449_OUT=$OUT \
    zsh $INNER "$@" 2>&1 | sed "s#$INNER#$THIS#g"
  return $pipestatus[1]
}

case $STEP in
  00)
    print -r -- "### [452 00] commit under test: $COMMIT (Worktree $WT); output $OUT"
    # 449's 00 recreates the project; keep the 449 probe's child records once (small JSON files).
    if [[ -d $BASE/project/.graphtraj/swarm/control/agents && ! -e $OUT/449-records-before-00 ]]; then
      cp -Rp $BASE/project/.graphtraj/swarm/control/agents $OUT/449-records-before-00 \
        && print -r -- "kept the earlier records in $OUT/449-records-before-00"
    fi
    inner 00 ;;
  00u) inner 00u ;;
  01) inner 01 ;;
  02)
    inner 02 | tee $OUT/02.txt
    rc=$pipestatus[1]
    print -r -- ""
    print -r -- "### [452 02] child execution outcomes (from the lines above)"
    outcomes=(${(f)"$(grep -E '^ +child execution [0-9a-f]+ outcome ' $OUT/02.txt | awk '{print $3, $5}')"})
    print -rl -- $outcomes
    if (( ${#outcomes} >= 1 )) && ! print -rl -- $outcomes | grep -qv ' completed$' \
        && ! grep -q owner-exited $OUT/02.txt; then
      print -r -- "CHECK PASS: 452 every ended child execution completed; none owner-exited" | tee -a $OUT/02.txt
    else
      print -r -- "CHECK FAIL: 452 a child execution did not complete (or none ended); see outcomes above" | tee -a $OUT/02.txt
      rc=1
    fi
    print -r -- ""
    print -r -- "Success: 449's 'summary: ALL PASS' and '452 ... PASS'. Output kept in $OUT/02.txt."
    print -r -- "==> 下一步 / next (Main): send $OUT/02.txt to the Leader."
    exit $rc ;;
  *) print -r -- "usage: zsh $THIS <00|00u|01|02>   (VERIFY452_COMMIT=<sha> to test another commit)" ;;
esac
