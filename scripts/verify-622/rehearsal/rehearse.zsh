#!/bin/zsh
# Task 622 rehearsal driver (Engineer only): runs steps.zsh 00 and O against the fakegh.py stand-in, chosen only
# through VERIFY622_* knobs. Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
OUT=$HERE/console; mkdir -p $OUT
fresh() {  # fresh <scenario>: new fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() { print -r -- VERIFY622_GH=$S/$1/gh/gh VERIFY622_POLL_S=1 VERIFY622_DONE_S=30; }
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
fresh clean; step clean 00.txt 00
step clean O-clean.txt O
step clean O-clean-by-id.txt O 45600000622
fresh noise; step noise O-noise.txt O
fresh nosummary; step nosummary O-nosummary.txt O
fresh none; step none O-none.txt O
step none O-none-by-id.txt O 45546698610
fresh wait; step wait O-wait.txt O
