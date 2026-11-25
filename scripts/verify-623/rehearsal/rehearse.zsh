#!/bin/zsh
# Task 623 rehearsal driver (Engineer only), adapted from verify-621: runs steps.zsh in a scratch clone of this
# Worktree's HEAD against local bare remotes and the fakegh.py stand-in, chosen only through VERIFY623_* knobs. The
# clone's origin URL is set to the real repository's URL (00 checks it) but nothing is pushed there:
# VERIFY623_REMOTE is the bare remote. Consoles go to ./console.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; HERE=${0:A:h}; WT=$(git -C $HERE rev-parse --show-toplevel)
BRANCH=agent/623-windows-desktop-adoption-green
PY=/Users/luoxiao/miniconda3/bin/python3.13
OUT=$HERE/console; mkdir -p $OUT
rm -rf $S; mkdir -p $S
git clone -q --no-checkout $WT $S/repo
ORIG=$(git -C $WT rev-parse HEAD)
git -C $S/repo checkout -q -B $BRANCH $ORIG
git -C $S/repo remote set-url origin git@github.com:LUOXIAO92/graphtraj.git
STEPS=$S/repo/scripts/verify-623/steps.zsh
fresh() {  # fresh <scenario>: new bare remote and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git init -q --bare $S/$1/remote.git
  print -r -- ${2:-$1} > $S/$1/gh/scenario
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY623_REMOTE=$S/$1/remote.git VERIFY623_GH=$S/$1/gh/gh VERIFY623_HTMP=$S/$1/htmp \
    VERIFY623_PTMP=$S/$1/ptmp VERIFY623_POLL_S=1 VERIFY623_APPEAR_S=${2:-10} VERIFY623_DONE_S=${3:-30}
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc ${APPEAR:-10} ${DONE:-30}) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10} ${DONE:-30}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
W0=46300000000  # the stand-in Windows run id

# Candidate HEAD as committed: 00, P (all four succeed), 00 after P, W, W <sha>, W <run-id>.
fresh ok push-success; step ok 00.txt 00; step ok P-success.txt P; step ok 00-after-P.txt 00
step ok W-head.txt W; step ok W-sha.txt W $ORIG; step ok W-run-id.txt W $W0
# Windows fails: P FAIL 3/4 with the failing step, log tail and all artifacts; X re-runs it and passes;
# X on a succeeded run and on another branch's run is refused.
fresh fail push-fail; step fail P-windows-fails.txt P; step fail X-rerun-windows.txt X $W0
step fail X-on-success-refused.txt X $((W0 + 1)); step fail X-bad-id-refused.txt X 12345
APPEAR=4; fresh timeout push-timeout; step timeout P-appearance-timeout.txt P; APPEAR=10
DONE=5; fresh slow push-slow; step slow P-completion-timeout.txt P; DONE=30
fresh tag tag-wrong; step tag 00-tag-wrong.txt 00; step tag P-tag-wrong.txt P
# The remote branch diverged from HEAD: 00 and P STOP, nothing forced.
fresh diverged push-success; git -C $S/repo push -q $S/diverged/remote.git \
  $(git -C $S/repo commit-tree -p "${ORIG}~1" -m diverged "${ORIG}~1^{tree}"):refs/heads/$BRANCH
step diverged 00-diverged.txt 00; step diverged P-diverged.txt P
# Contrast commits in the scratch clone only: an extra workflow edit, then a product-code edit.
print -r -- "# rehearsal-only extra edit" >> $S/repo/.github/workflows/desktop-win-adoption.yml
git -C $S/repo commit -q -am "rehearsal stand-in: extra workflow edit"
fresh extra push-success; step extra 00-extra-workflow-edit.txt 00; step extra P-extra-workflow-edit.txt P
git -C $S/repo reset -q --hard $ORIG
print -r -- "// rehearsal-only product edit" >> $S/repo/desktop/src/main.tsx
git -C $S/repo commit -q -am "rehearsal stand-in: product edit"
fresh frozen push-success; step frozen 00-product-edit.txt 00; step frozen P-product-edit.txt P
git -C $S/repo reset -q --hard $ORIG
print -r -- "rehearsal-only dirty" >> $S/repo/README.md
fresh dirty push-success; step dirty P-dirty-tree.txt P
