#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-546 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-546/rehearse.zsh <empty dir>
# Replaced by a stub `claude` (first on PATH): the READY answer and the whole Main model (it makes no agents call, so
# B prints VERDICT NOT-HIT). Real: steps.zsh, both venv builds from exact commits, graphtraj setup and claude host
# configuration, drv546.py summary, T with VERIFY546_TESTS (one graftling test file with its fixtures), TS, C.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin
print -r -- '#!/bin/sh
[ "$1" = --version ] && { echo "0.0.0 (stub 546)"; exit 0; }
cat >/dev/null
echo "{\"type\":\"system\",\"subtype\":\"init\",\"model\":\"claude-sonnet-5-5\",\"apiKeySource\":\"stub\",\"tools\":[]}"
echo "{\"type\":\"result\",\"result\":\"READY-546-CLAUDE\"}"' > $R/bin/claude
chmod +x $R/bin/claude
export VERIFY546_BASE=$R/base VERIFY546_DEST=$R/realhost VERIFY546_CLAUDE=$R/bin/claude \
  VERIFY546_TESTS=tests/test_agent_control.py
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
run 00
run B
run T
for i in {1..60}; do grep -q '^exit=' $R/base/t/gl.txt(N) && break; sleep 2; done
run TS
run C
