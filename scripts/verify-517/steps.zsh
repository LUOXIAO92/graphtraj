#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 517 Main-run steps: re-judge 515's retained production records with the fixed adopt-515 checkers.
#   zsh scripts/verify-517/steps.zsh <STEP>          (from this Task's Worktree; read only; no dialog; no model)
#   P  preflight: commit, python, and whether 515's raw records and the archives/transcripts Rsr read are readable
#   R  Rsr re-judged: rec515.py calls --after <install end> on the leader's and the engineer's record files (graftling
#      archive + Claude transcript, as Rsr read them); expected PASS. Then the counterexample: the same files with the
#      split an hour before the install, where the pre-install old-name calls fall inside the window; expected FAIL.
#   N  Nr's 466/477/487/495 lines re-judged: the fixed nr499.py over the same production project, raw dir, child and
#      member as 515's Nr (read only; it never signals); expected those lines PASS (515 Leader: met from raw records).
# Each step writes only to <Harness>/tmp/517/<step>-<time>/ and prints its expected result. Nothing else is written:
# 515's raw directory, the archives and the transcripts are only read.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=${SD:h:h}                                            # this Task Worktree (scripts/verify-517/..)
# VERIFY517_* are set only by a rehearsal (empty scratch directories); the defaults are the real paths.
H=${VERIFY517_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
TASK=515-production-adoption-mcp-server-names
RAW=${VERIFY517_RAW:-$H/.graphtraj/core/state/tasks/$TASK/adoption/raw-4ad22e90}
OUTBASE=${VERIFY517_OUT:-$H/tmp/517}                    # a rehearsal sets a scratch directory
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
ADOPT=$WT/scripts/adopt-515
CHILD=n515                                              # adopt-515 steps.zsh CHILD
STEP=${1:-}

out_dir() { D=$OUTBASE/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D && print -r -- "output: $D"; }
readable() { if [[ -r $1 ]]; then print -r -- "  readable: $1"; else print -r -- "  NOT READABLE: $1"; return 1; fi; }
# Rsr's record files, from Rsr-archives.txt: each Claude transcript <session>.jsonl and the graftling archive whose
# first line (header) names that session. Roles from Main's Rsr-main-timestamps.txt ('Leader <sid8>', 'Engineer <sid8>').
role_sid() { grep -oE "$1 [0-9a-f]{8}" $RAW/Rsr-main-timestamps.txt 2>/dev/null | head -1 | cut -d' ' -f2; }
role_files() {  # $1 session prefix
  local f
  for f in ${(f)"$(<$RAW/Rsr-archives.txt)"}; do
    if [[ ${f:t} == $1*.jsonl ]]; then print -r -- $f
    elif [[ ${f:t} == session.jsonl ]] && head -c 4000 $f 2>/dev/null | grep -q "$1"; then print -r -- $f; fi
  done
}

case $STEP in
P) out_dir P; {
  print "[P] preflight. Dialog: none. Reads only. < 5 s."
  print "worktree: $WT  commit: $(git -C $WT rev-parse HEAD 2>&1)  dirty files: $(git -C $WT status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  print "python: $CONDA -> $($CONDA --version 2>&1)  yaml (nr499): $($CONDA -I -c 'import yaml; print(yaml.__version__)' 2>&1 | tail -1)"
  rc=0
  print "515 raw directory and inputs:"
  for f in $RAW $RAW/I-install-start.epoch $RAW/I-install-end.epoch $RAW/Rsr-archives.txt $RAW/Rsr-main-timestamps.txt $RAW/Nr.txt $RAW/N-reply.txt $RAW/Nw-snapshots.jsonl; do readable $f || rc=1; done
  [[ -r $RAW/I-install-end.epoch ]] && print "install end: $(<$RAW/I-install-end.epoch) = $(date -u -r $(<$RAW/I-install-end.epoch) +%Y-%m-%dT%H:%M:%SZ)"
  print "Rsr record files (Rsr-archives.txt):"
  if [[ -r $RAW/Rsr-archives.txt ]]; then for f in ${(f)"$(<$RAW/Rsr-archives.txt)"}; do readable $f || rc=1; done; fi
  print "leader session: $(role_sid Leader)  engineer session: $(role_sid Engineer)"
  NA=$(grep -oE 'archive=[^;]*session\.jsonl' $RAW/Nr.txt 2>/dev/null | tail -1 | cut -d= -f2)
  print "N member archive (Nr.txt): ${NA:-not named}"; [[ -n $NA ]] && { readable $NA || rc=1; }
  readable $H/.graphtraj/swarm/control/agents || rc=1
  print "expected: every path readable (rc 0). Any NOT READABLE line names a path R or N cannot judge."
  print "P rc=$rc"; exit $rc
} 2>&1 | tee $D/P.txt; exit ${pipestatus[1]} ;;

R) out_dir R; {
  print "[R] Rsr re-judged by record time. Dialog: none. Reads only. < 30 s."
  rc=0
  [[ -r $RAW/I-install-end.epoch && -r $RAW/I-install-start.epoch && -r $RAW/Rsr-archives.txt && -r $RAW/Rsr-main-timestamps.txt ]] || {
    print "STOP: not readable: one of $RAW/I-install-end.epoch, I-install-start.epoch, Rsr-archives.txt, Rsr-main-timestamps.txt (run P)"; exit 1; }
  AFTER=$(<$RAW/I-install-end.epoch); START=$(<$RAW/I-install-start.epoch)
  EARLY=$(( START - 3600 ))
  print "split (install end): $AFTER = $(date -u -r $AFTER +%Y-%m-%dT%H:%M:%SZ); counterexample split: $EARLY = $(date -u -r $EARLY +%Y-%m-%dT%H:%M:%SZ)"
  for spec in Leader:leader:agents Engineer:engineer:agents,tasks; do
    who=${spec#*:}; who=${who%%:*}; need=${spec##*:}; sid=$(role_sid ${spec%%:*})
    fs=(${(f)"$(role_files ${sid:-none})"})
    print "\n-- $who session ${sid:-unknown}: ${#fs} record file(s)"; print -rl -- "   "${^fs}
    print "expected: PASS (needed new-name calls ok after the install; no old-name call after it)"
    $CONDA -I $ADOPT/rec515.py calls "$who after-install" --after $AFTER --need $need $fs; r=$?
    print "result: $([[ $r == 0 ]] && print PASS || print FAIL) (rc $r; expected PASS)"; [[ $r == 0 ]] || rc=1
    print "\n-- $who counterexample: split before the pre-install old-name calls"
    print "expected: FAIL on 'no mcp__agents__* call after the split' with the pre-install old calls counted"
    $CONDA -I $ADOPT/rec515.py calls "$who counterexample" --after $EARLY --need $need $fs; r=$?
    print "result: $([[ $r != 0 ]] && print FAIL || print PASS) (rc $r; expected FAIL)"; [[ $r != 0 ]] || rc=1
  done
  print "\nR overall: $([[ $rc == 0 ]] && print 'as expected' || print 'NOT as expected (lines above)')"; exit $rc
} 2>&1 | tee $D/R.txt; exit ${pipestatus[1]} ;;

N) out_dir N; {
  print "[N] Nr's 466/477/487/495 with the fixed nr499.py. Dialog: none. Reads only (never signals). < 1 min."
  MEMBER=$(sed -n 's/^MEMBER //p' $RAW/Nr.txt 2>/dev/null | tail -1)
  print "project $H | raw $RAW | child $CHILD | member ${MEMBER:-none} | task $TASK"
  print "expected: CHECK 466 (three lines), 495 (466), 477 (two lines), 494 (487) lines PASS; '492: agents calls' lists the member's calls"
  $CONDA -I $ADOPT/nr499.py $H $RAW $CHILD "${MEMBER:-none}" $TASK > $D/nr499-full.txt 2>&1; r=$?
  print "nr499 rc=$r (other checks are 515's and may differ now; full output $D/nr499-full.txt)"
  grep -E 'agents tool calls by name|^492: agents calls|CHECK 466|CHECK 495 \(466\)|CHECK 477|CHECK 494|BLOCKED|^475: NO' $D/nr499-full.txt | cut -c1-400
  # 515's Nr printed 9 such lines: 466 x3, 495 (466), 477 x2, 494 (477), 494 (487) x2. Fewer means nr499 stopped early.
  total=$(grep -cE 'CHECK (466|495 \(466\)|477|494)' $D/nr499-full.txt); bad=$(grep -E 'CHECK (466|495 \(466\)|477|494)' $D/nr499-full.txt | grep -cvE ': PASS')
  if (( total >= 9 && bad == 0 )); then print "N: as expected ($total lines, all PASS)"; exit 0; fi
  print "N: NOT as expected: $total of 9 lines present, $bad not PASS (lines above; full output $D/nr499-full.txt)"; exit 1
} 2>&1 | tee $D/N.txt; exit ${pipestatus[1]} ;;

*) print "usage: zsh $THIS P|R|N   (Main, from the Worktree; read only; no dialog)"; exit 2 ;;
esac
