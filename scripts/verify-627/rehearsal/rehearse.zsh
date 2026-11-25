#!/bin/zsh
# Task 627 rehearsal driver (Engineer only): runs verify-627/steps.zsh P0, P and W in a scratch clone of this
# Worktree's HEAD against local bare remotes and verify-621's fakegh.py stand-in (push scenarios), chosen only through
# VERIFY627_* knobs. The clone's origin URL is the real repository's URL (P0 checks it) but nothing is pushed there:
# VERIFY627_REMOTE is the bare remote. Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; WT=$(git -C $HERE rev-parse --show-toplevel)
BRANCH=agent/627-desktop-ui-structure-redesign
PY=/Users/luoxiao/miniconda3/bin/python3.13
FAKE=$WT/scripts/verify-621/rehearsal/fakegh.py
OUT=$HERE/console; mkdir -p $OUT
rm -rf $S; mkdir -p $S
git clone -q --no-checkout $WT $S/repo
git -C $S/repo checkout -q -B $BRANCH $(git -C $WT rev-parse HEAD)
git -C $S/repo remote set-url origin git@github.com:LUOXIAO92/graphtraj.git
STEPS=$S/repo/scripts/verify-627/steps.zsh
fresh() {  # fresh <scenario>: new bare remote and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- $S/$1/remote.git > $S/$1/gh/remote
  print -r -- "#!/bin/zsh
exec $PY -I $FAKE $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY627_REMOTE=$S/$1/remote.git VERIFY627_GH=$S/$1/gh/gh VERIFY627_HTMP=$S/$1/htmp \
    VERIFY627_PTMP=$S/$1/ptmp VERIFY627_POLL_S=1 VERIFY627_APPEAR_S=${2:-10} VERIFY627_DONE_S=30
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
APPEAR=10
fresh push-success; step push-success P0.txt P0; step push-success P-success.txt P
step push-success P0-after-P.txt P0; rm -f $S/push-success/gh/push-polls; step push-success W.txt W
fresh push-fail; step push-fail P-linux-fails.txt P
APPEAR=4; fresh push-timeout; step push-timeout P-appearance-timeout.txt P; APPEAR=10
# Contrast: an edit to another workflow since the base is refused.
print -r -- "# rehearsal-only extra edit" >> $S/repo/.github/workflows/desktop-win-adoption.yml
git -C $S/repo commit -q -am "rehearsal stand-in: extra workflow edit"
fresh push-extra; step push-extra P0-extra-workflow-edit.txt P0; step push-extra P-extra-workflow-edit.txt P
