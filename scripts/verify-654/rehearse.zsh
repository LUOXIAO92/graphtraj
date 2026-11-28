#!/bin/zsh
# Task 654 rehearsal (Engineer's sandbox only; Main does not run this): steps.zsh's judge, offline, through
# `zsh steps.zsh W 46114515028` on Main's RETAINED records of 653's run 46114515028 (attempt 1 failed on the race this
# Task fixes; attempt 2, after `gh run rerun --failed`, passed), with 654's commit as a FIXTURE head_sha and artifact
# names (gh-standin.zsh). Expected: attempt 1 FAIL naming the fixed test, attempt 2 PASS. Also runs 00 as far as the
# sandbox lets it. Outputs, scrubbed of this machine's paths, go to rehearsal/ next to this file.
#   zsh rehearse.zsh
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
WT=$(/usr/bin/env -i PATH=/usr/bin:/bin git -C $SD rev-parse --show-toplevel)
H=${WT:h:h:h:h}
RW=$H/.graphtraj/core/state/tasks/653-graftling-0-11-0-release-and-production-adoption/realhost/main-raw/windows
SHA=0dad0db948f5a7ec5f069b4910a8d19282634a1e
SB=${TMPDIR:-/tmp}/r654
OUT=$SD/rehearsal
scrub() { sed -e "s|$H|<Harness>|g" -e "s|${TMPDIR:-/tmp}|<TMPDIR>|g" -e "s|/private<TMPDIR>|<TMPDIR>|g" -e "s|$HOME|<HOME>|g" -e "s|pytest-of-$USER|pytest-of-<USER>|g"; }
rm -rf $SB; mkdir -p $SB/bin $OUT
cp $SD/gh-standin.zsh $SB/bin/gh; chmod +x $SB/bin/gh
# A scratch graftling with the bundle's commit (W reads the commit's test files from it); <Harness>/graftling is not written.
git clone -q --bare --shared --template= $H/graftling $SB/g.git && git -C $SB/g.git fetch -q $SD/graftling-654.bundle \
  "refs/heads/agent/654-graftling-pi-notice-test-race:refs/heads/agent/654-graftling-pi-notice-test-race" || exit 1
for at in 1 2; do
  print -l -- $RW $at $SHA $SB/calls-a$at.txt > $SB/conf
  env V654_G=$SB/g.git V654_GH=$SB/bin/gh V654_EVIDENCE=$SB/ev-a$at V654_POLL_S=1 zsh $SD/steps.zsh W 46114515028 > $SB/W-a$at.txt 2>&1
  print -r -- "EXIT $?" >> $SB/W-a$at.txt
  scrub < $SB/W-a$at.txt > $OUT/W-46114515028-a$at.txt
  for f in judgement.txt fixed-test.txt evidence.txt real-entry-judgement.txt; do
    [[ -f $SB/ev-a$at/live/windows/run-46114515028-a$at/$f ]] && scrub < $SB/ev-a$at/live/windows/run-46114515028-a$at/$f > $OUT/W-a$at-$f
  done
  scrub < $SB/calls-a$at.txt > $OUT/W-a$at-gh-calls.txt
  print -r -- "== attempt $at: $(grep '^VERDICT ' $OUT/W-46114515028-a$at.txt | tail -1 | cut -c1-400)"
done
zsh $SD/steps.zsh 00 > $SB/00.txt 2>&1; print -r -- "EXIT $?" >> $SB/00.txt
scrub < $SB/00.txt > $OUT/00.txt
print -r -- "== 00: $(grep '^VERDICT ' $OUT/00.txt | tail -1)"
