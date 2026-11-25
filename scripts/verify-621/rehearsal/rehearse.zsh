#!/bin/zsh
# Task 621 rehearsal driver (Engineer only): runs steps.zsh in a scratch clone of this Worktree's HEAD against
# local bare remotes and the fakegh.py stand-in, chosen only through VERIFY621_* knobs. The clone's origin URL is
# set to the real repository's URL (00 checks it) but nothing is pushed there: VERIFY621_REMOTE is the bare remote.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; WT=$(git -C $HERE rev-parse --show-toplevel)
BRANCH=agent/621-macos-adoption-script-d-ui
PY=/Users/luoxiao/miniconda3/bin/python3.13
OUT=$HERE/console; mkdir -p $OUT
rm -rf $S; mkdir -p $S
git clone -q --no-checkout $WT $S/repo
git -C $S/repo checkout -q -b $BRANCH $(git -C $WT rev-parse HEAD)
git -C $S/repo remote set-url origin git@github.com:LUOXIAO92/graphtraj.git
STEPS=$S/repo/scripts/verify-621/steps.zsh
fresh() {  # fresh <scenario>: new bare remote and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  print -r -- $1 > $S/$1/gh/scenario
  print -r -- $S/$1/remote.git > $S/$1/gh/remote
  git -C $WT show origin/main:.github/workflows/desktop-macos-adoption.yml > $S/$1/gh/wf-main.yml
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY621_REMOTE=$S/$1/remote.git VERIFY621_GH=$S/$1/gh/gh VERIFY621_HTMP=$S/$1/htmp \
    VERIFY621_PTMP=$S/$1/ptmp VERIFY621_POLL_S=1 VERIFY621_APPEAR_S=${2:-10} VERIFY621_DONE_S=30
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -3 $OUT/$file
}
# At the A commit adoption.mjs is unchanged: 00 reports E ready and P not ready; E downloads; P refuses.
fresh evidence; step evidence a-00.txt 00; step evidence a-E.txt E; step evidence a-E-again.txt E
step evidence a-00-after-E.txt 00; step evidence a-P-refused.txt P
# Stand-in for the B fix: one committed change to adoption.mjs in the scratch clone only.
print -r -- "// rehearsal stand-in change" >> $S/repo/desktop/tests/adoption.mjs
git -C $S/repo commit -q -am "rehearsal stand-in: adoption.mjs changed"
fresh success; step success b-00.txt 00; step success b-P-success.txt P; step success b-00-after-P.txt 00
step success b-W-newest.txt W; step success b-W-id.txt W 46100000002
fresh failure; step failure b-P-failure.txt P
APPEAR=4; fresh timeout; step timeout b-P-appearance-timeout.txt P; APPEAR=10
fresh dispatch; git -C $S/repo push -q $S/dispatch/remote.git $BRANCH; step dispatch b-D-success.txt D
fresh diverged; git -C $S/repo push -q $S/diverged/remote.git $(git -C $S/repo rev-parse HEAD~1):refs/heads/main \
  $(git -C $S/repo commit-tree -p HEAD~1 -m diverged HEAD~1^{tree}):refs/heads/$BRANCH
step diverged b-00-diverged.txt 00; step diverged b-P-diverged.txt P
