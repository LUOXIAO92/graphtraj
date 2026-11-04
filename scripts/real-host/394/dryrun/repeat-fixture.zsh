#!/bin/zsh
# Dry run only: make step 30's two trees for 31-repeat, their python a stub_pytest.py link, after dry.zsh 00-preflight.
#   zsh repeat-fixture.zsh "<head fails>" "<base fails>"     each "<variant> <n>[; ...]", e.g. "cancelled 5"
HERE=${0:A:h:h}
D=$TMPDIR/rh394-dry
[[ -f $D/ag/COMMIT ]] || { print -r -- "run: zsh $HERE/dryrun/dry.zsh 00-preflight first"; exit 2; }
for pair in "suite:$(<$D/ag/COMMIT):$1" "suite-base:$(git -C $D/wt rev-parse 'cb29c3a4^{commit}'):$2"; do
  dir=$D/ag/${pair%%:*} rest=${pair#*:}
  rm -rf $dir; mkdir -p $dir/venv/bin $dir/clone $dir/home
  ln -s $HERE/dryrun/stub_pytest.py $dir/venv/bin/python
  print -r -- ${rest%%:*} > $dir/installed-commit
  print -rl -- ${(s:;:)rest#*:} > $dir/stub-fails.txt
done
