#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-555 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-555/rehearse.zsh <empty dir>
# Overrides: BASE (<dir>/base) and DEST (<dir>/realhost, not .state/realhost). T runs a subset through the same
# entry: the DSH standalone host tests (repository fixtures: fake DSH install, real graftling.dsh.host and agents
# CLI subprocesses) and the approval-layer tests; TB reruns the same arguments on the baseline (it reuses T's
# arguments when given none). The 555 test file is left out because the baseline has no such file. Nothing is
# replaced: no stub, no model.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
export VERIFY555_BASE=$R/base VERIFY555_DEST=$R/realhost
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
run 00
run D
run T tests/test_dsh_standalone_host.py tests/test_approval_layers.py
run TB
run C
