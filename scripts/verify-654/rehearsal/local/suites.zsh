#!/bin/zsh
# 654 scratch: graftling full suite at base 67b0fe9a and at the candidate, one after the other, allowlist environment.
S=${0:A:h}
for v in base cand; do
  dir=$S/base; [[ $v == cand ]] && dir=$S/graftling
  out=$S/out/suite-$v.txt
  print -r -- "suite $v: $(git -C $S/graftling rev-parse HEAD 2>/dev/null) (cand) / tree $dir; python $S/venv-$v/bin/python" > $out
  ( cd $dir && env -i HOME=$HOME USER=$USER TERM=xterm TMPDIR=${TMPDIR:-/tmp} LANG=en_US.UTF-8 \
      PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
      $S/venv-$v/bin/python -m pytest -q -p no:cacheprovider -rfEs ) >> $out 2>&1
  print -r -- "EXIT $?" >> $out
done
