#!/bin/zsh
# Task 622 rehearsal driver (Engineer only): runs steps.zsh 00, P and O against a local bare remote and the fakegh.py
# stand-in, chosen only through VERIFY622_* knobs. Consoles are written to <scratch>/console while steps run (steps
# check that the tracked tree is clean) and copied into console/ at the end.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
BRANCH=agent/622-process-reclaim-windows-noise
OUT=$S/console; rm -rf $OUT; mkdir -p $OUT
fresh() {  # fresh <scenario>: new bare remote and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() { print -r -- VERIFY622_REMOTE=$S/$1/remote.git VERIFY622_GH=$S/$1/gh/gh VERIFY622_POLL_S=1 VERIFY622_APPEAR_S=${APPEAR:-10} VERIFY622_DONE_S=30; }
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
remote_ref() { print -r -- "remote $BRANCH: $(git -C $S/$1/remote.git rev-parse -q --verify refs/heads/$BRANCH || print -r -- absent)"; }
# O cases (no push).
fresh clean; step clean O-clean.txt O
step clean O-clean-by-id.txt O 45600000622
fresh noise; step noise O-noise.txt O
fresh nosummary; step nosummary O-nosummary.txt O
fresh none; step none O-none.txt O
step none O-none-by-id.txt O 45546698610
fresh wait; step wait O-wait.txt O
# P success: 00 with the branch absent, push, run appears in_progress then completes; 00 again (equal -> O); O by sha.
fresh psuccess; step psuccess 00-absent.txt 00
step psuccess P-success.txt P
remote_ref psuccess >> $OUT/P-success.txt
step psuccess 00-equal.txt 00
step psuccess O-by-sha.txt O $(git -C $HERE rev-parse HEAD)
# P appearance timeout.
APPEAR=4; fresh ptimeout; step ptimeout P-timeout.txt P; APPEAR=10
remote_ref ptimeout >> $OUT/P-timeout.txt
# P with a diverged remote branch: a commit that is not an ancestor of HEAD; nothing is pushed.
fresh pdiverged
foreign=$(git -C $S/pdiverged/remote.git commit-tree $(git -C $S/pdiverged/remote.git hash-object -w -t tree /dev/null) -m 'foreign 622 rehearsal commit')
git -C $S/pdiverged/remote.git update-ref refs/heads/$BRANCH $foreign
step pdiverged 00-diverged.txt 00
{ print -r -- "before P: $(remote_ref pdiverged)"; } > $S/pdiverged/before
step pdiverged P-diverged.txt P
{ cat $S/pdiverged/before; print -r -- "after P:  $(remote_ref pdiverged)"; } >> $OUT/P-diverged.txt
mkdir -p $HERE/console; cp $OUT/*.txt $HERE/console/
