#!/bin/zsh
# Task 620 rehearsal driver (Engineer only), no network and no real gh.
#   (a) scenario_driver.py: tests/linux_adoption_runtime.py + runner_codex_peer.py at base 055669d9 vs this worktree.
#   (b) steps.zsh 00/L/P/W against a local bare remote and the fakegh.py stand-in, chosen only through VERIFY620_*
#       knobs (VERIFY620_OUT because <Harness>/tmp is not writable from the Engineer sandbox).
# Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh; WT=$(git -C $HERE rev-parse --show-toplevel)
PY=/Users/luoxiao/miniconda3/bin/python3.13
OUT=$HERE/console; mkdir -p $OUT $S

# (a) base vs fixed scenario
mkdir -p $S/base-src
for n in linux_adoption_runtime.py runner_codex_peer.py; do git -C $WT show 055669d9:tests/$n > $S/base-src/$n; done
for label src in base $S/base-src fixed $WT/tests; do
  print -r -- "\$ python -I scenario_driver.py $label <${label} tests> <scratch>" > $OUT/a-scenario-$label.txt
  $PY -I $HERE/scenario_driver.py $label $src $S >> $OUT/a-scenario-$label.txt 2>&1; print -r -- "[exit $?]" >> $OUT/a-scenario-$label.txt
  print -r -- "--- a-scenario-$label.txt"; grep '^CHECK' $OUT/a-scenario-$label.txt
done

# (b) steps
fresh() {  # fresh <scenario>: new bare remote, fake gh state and output dir
  rm -rf $S/$1; mkdir -p $S/$1/gh $S/$1/out
  git init -q --bare $S/$1/remote.git
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() { print -r -- VERIFY620_REMOTE=$S/$1/remote.git VERIFY620_GH=$S/$1/gh/gh VERIFY620_OUT=$S/$1/out VERIFY620_POLL_S=1 VERIFY620_APPEAR_S=${2:-10} VERIFY620_DONE_S=30; }
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc ${APPEAR:-10}) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" 2>&1 | sed "s#$S#<scratch>#g" >> $OUT/$file; print -r -- "[exit ${pipestatus[1]}]" >> $OUT/$file
  print -r -- "--- $file"; tail -3 $OUT/$file
}
fresh success; step success b-success-00.txt 00; step success b-success-L.txt L; step success b-success-P.txt P
step success b-success-00-again.txt 00; rm -f $S/success/gh/polls; step success b-success-W.txt W
fresh failure; step failure b-failure-P.txt P
APPEAR=4; fresh timeout; step timeout b-timeout-P.txt P
# Default output directory (no VERIFY620_OUT): the derived <Harness>/tmp/620 is checked; not writable here.
fresh default
print -r -- "\$ VERIFY620_REMOTE=... VERIFY620_GH=... (no VERIFY620_OUT) zsh steps.zsh 00" > $OUT/b-default-out-00.txt
env VERIFY620_REMOTE=$S/default/remote.git VERIFY620_GH=$S/default/gh/gh zsh $STEPS 00 2>&1 | sed "s#$S#<scratch>#g" >> $OUT/b-default-out-00.txt
print -r -- "[exit ${pipestatus[1]}]" >> $OUT/b-default-out-00.txt
print -r -- "--- b-default-out-00.txt"; tail -3 $OUT/b-default-out-00.txt
