#!/bin/zsh
# Task 600 rehearsal (Engineer's sandbox only; Main does not run this). Runs every step of steps.zsh against a scratch
# clone of <Harness>/graftling (main checked out, dev in a second worktree) and a scratch bare repository standing in
# for GitHub (its dev set to 7b5f4e6b, as GitHub's dev after 593). Real G, the graftling-dev Worktree and GitHub are
# only read (the clone's source). Outputs: rehearsal/console-*.txt and rehearsal/raw*/.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
HH=${WT:h:h:h:h}
OUTD=$SD/rehearsal
SB=${${TMPDIR:-/tmp}:A}/r600                       # scratch root
GBASE=2b4a33aef93dc45b953bd412e4d5dd61347c38ea
GMAIN0=7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB $OUTD
git clone -q --bare --no-hardlinks $HH/graftling $SB/origin.git || exit 1
git -C $SB/origin.git update-ref refs/heads/dev $GMAIN0 || exit 1
git clone -q --no-hardlinks $HH/graftling $SB/g || exit 1
git -C $SB/g branch -q dev $GBASE && git -C $SB/g worktree add -q $SB/gdev dev || exit 1
git -C $SB/g remote set-url origin $SB/origin.git
git -C $SB/g config user.name LUOXIAO92; git -C $SB/g config user.email 89069722+LUOXIAO92@users.noreply.github.com
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT600_G=$SB/g ADOPT600_GDEV=$SB/gdev ADOPT600_GURL=$SB/origin.git ADOPT600_SCRATCH=$SB/tmp600 ADOPT600_UVT=$SB/uvtool-600
        ADOPT600_NOSNAP=1 "ADOPT600_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print -r -- "\n######## rehearsal: $tag (exit code follows)"; env $common ADOPT600_OUT=$out "$@"; print -r -- "######## exit=$?"; }
S=$SD/steps.zsh
{ print "scratch: $SB | G=$SB/g (main) | GDEV=$SB/gdev (dev) | GitHub stand-in: $SB/origin.git (dev $GMAIN0)"
  print "## zsh special parameter collisions among names assigned in steps.zsh"
  specials=(${(k)parameters[(R)*special*]})
  assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local )?[A-Za-z_][A-Za-z0-9_]*=' $S | sed -E 's/^[ ;({]//; s/^local //; s/=$//')"}})
  hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER); other=(${hits:|intended})
  print -r -- "assigned names: ${#assigned} | special names among them: ${hits:-none} | other than clean()'s intended pass-throughs (HOME PATH TERM LANG TMPDIR USER as env -i arguments): ${other:-none}"
  print "## \$NAME: followed by a letter (zsh modifier trap, e.g. \$GBRANCH:refs -> :r): $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "## STOP: rel with dev moved"
  echo moved > $SB/gdev/moved.txt && git -C $SB/gdev add moved.txt && git -C $SB/gdev commit -q -m 'dev moved (rehearsal)'
  run $OUTD/raw-stop "rel, dev moved" zsh $S rel
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag v0.9.1 $(git -C $SB/g rev-parse -q --verify refs/tags/v0.9.1 || print absent) branch agent/600 $(git -C $SB/g rev-parse -q --verify refs/heads/agent/600-graftling-0.9.1 || print absent)"
  git -C $SB/gdev reset -q --hard $GBASE
  print "## STOP: rp before rel"
  run $OUTD/raw-stop "rp before rel" zsh $S rp
} 2>&1 | tee $OUTD/console-stops.txt
{ for st in 00 rel rel B rp; do run $OUTD/raw $st zsh $S $st; done
  run $OUTD/raw "rp confirmed" env ADOPT600_PUSH_CONFIRMED=yes zsh $S rp
  run $OUTD/raw "rp confirmed again (idempotent)" env ADOPT600_PUSH_CONFIRMED=yes zsh $S rp
  run $OUTD/raw gh zsh $S gh
} 2>&1 | tee $OUTD/console-release.txt
{ run $OUTD/raw "C5 (source git+file:// scratch origin @v0.9.1)" env ADOPT600_SOURCE="git+file://$SB/origin.git@v0.9.1" zsh $S C5
  run $OUTD/raw done zsh $S done
} 2>&1 | tee $OUTD/console-C5.txt
