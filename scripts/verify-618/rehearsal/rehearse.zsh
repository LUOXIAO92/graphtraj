#!/bin/zsh
# Task 618 rehearsal driver (Engineer only): runs steps.zsh 00/P/W against a local bare remote and the fakegh.py
# stand-in, chosen only through VERIFY618_* knobs. Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
OUT=$HERE/console; mkdir -p $OUT
fresh() {  # fresh <scenario>: new bare remote and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() { print -r -- VERIFY618_REMOTE=$S/$1/remote.git VERIFY618_GH=$S/$1/gh/gh VERIFY618_POLL_S=1 VERIFY618_APPEAR_S=${2:-10} VERIFY618_DONE_S=30; }
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -3 $OUT/$file
}
fresh success; step success success-00.txt 00; step success success-P.txt P; step success success-00-again.txt 00
rm -f $S/success/gh/polls; step success success-W.txt W
fresh failure; step failure failure-P.txt P
APPEAR=4; fresh timeout; step timeout timeout-P.txt P
