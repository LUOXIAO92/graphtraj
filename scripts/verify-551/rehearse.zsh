#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-551 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-551/rehearse.zsh <empty dir> [steps...]       (default steps: 00 B)
# Replaced by stub551.py (first on PATH as claude, codex, pi, dsh): every model and host. The B parent's create and
# wait results and the child's record are FABRICATED by the stub. Real: steps.zsh, the in-use installation's
# `graphtraj setup`, Claude host configuration, the four child roles resolved by the Task-free driver (prep551.py
# roles), the tasks discover/describe probe through the in-use graphtraj-mcp, collect and sum551.py.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir> [steps...]}; shift
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin
local h; for h in claude codex pi dsh; do
  print -r -- "#!/bin/sh
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub551.py $h \"\$@\"" > $R/bin/$h; chmod +x $R/bin/$h
done
export VERIFY551_BASE=$R/base VERIFY551_STUB=$R/bin VERIFY551_PI_SANDBOX_ENV=$R/no-pi-sandbox.env
cd $R
local steps=("$@"); (( $#steps )) || steps=(00 "B claude")
local s; for s in $steps; do
  print -r -- "
=============== \$ zsh steps.zsh $s ==============="
  zsh $SD/steps.zsh ${=s}; print -r -- "(exit $?)"
done
