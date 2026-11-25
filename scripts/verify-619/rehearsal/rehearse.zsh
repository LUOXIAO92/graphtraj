#!/bin/zsh
# Task 619 rehearsal driver (Engineer only): runs steps.zsh 00/P/W against local bare remotes, a scratch clone of
# <Harness>/graftling (never the real one) and the fakegh.py stand-in, chosen only through VERIFY619_* knobs.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
GSHA=$(git bundle list-heads $HERE/../graftling-619.bundle | cut -d' ' -f1)
OUT=$HERE/console; mkdir -p $OUT
fresh() {  # fresh <scenario>: new bare remotes, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- $1 > $S/$1/gh/scenario; print -r -- $GSHA > $S/$1/gh/gsha
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY619_REMOTE=$S/$1/remote.git VERIFY619_GRAFTLING=$S/$1/graftling VERIFY619_GREMOTE=$S/$1/gremote.git \
    VERIFY619_GH=$S/$1/gh/gh VERIFY619_POLL_S=1 VERIFY619_APPEAR_S=${2:-10} VERIFY619_DONE_S=30
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
fresh success; step success success-00.txt 00; step success success-P.txt P; step success success-00-again.txt 00
rm -f $S/success/gh/polls; step success success-W.txt W
fresh counted-fail; step counted-fail counted-fail-P.txt P
fresh missing; step missing missing-P.txt P
APPEAR=4; fresh timeout; step timeout timeout-P.txt P; APPEAR=10
# Guard: a local 619 branch in the graftling clone that differs from the bundle head stops 00 (never overwritten).
fresh guard; git -C $S/guard/graftling branch -q agent/619-graftling-windows-import 82e9d12; step guard guard-local-00.txt 00
# The real <Harness>/graftling was only read: no 619 branch there.
print -r -- "real graftling 619 branch after rehearsal: '$(git -C $REAL branch --list 'agent/619*')' (expected empty)" | tee $OUT/real-graftling-untouched.txt
