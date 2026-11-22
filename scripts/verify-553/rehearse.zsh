#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-553 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-553/rehearse.zsh <empty dir>
# Stubs (stub553.py, first on PATH): claude, codex, dsh, and sandbox-exec (VERIFY553_SBX). Real: step V (wheels and venv
# from git archive of HEAD and of graftling dev), the candidate graphtraj-mcp S calls, steps F/C/T and a real pytest
# run through `steps.zsh G <args>`. See README.md for exactly what is stub and what is real.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin $R/fake-workspace/other-project $R/codex-sessions/2026/11/20
print -r -- '{"decoy": "another session"}' > $R/codex-sessions/2026/11/20/rollout-2026-11-20T10-00-00-00000000-0000-0000-0000-decoy0000000.jsonl
for h in claude codex dsh sandbox-exec; do
  print -r -- "#!/bin/sh
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub553.py $h \"\$@\"" > $R/bin/$h
  chmod +x $R/bin/$h
done
export VERIFY553_STUBBIN=$R/bin VERIFY553_STUB_STATE=$R/stub-state VERIFY553_BASE=$R/base VERIFY553_T=$R/t \
  VERIFY553_DENYROOT=$R/fake-workspace VERIFY553_DEST=$R/realhost VERIFY553_SBX=$R/bin/sandbox-exec \
  VERIFY553_CODEX_SESSIONS=$R/codex-sessions DEEPSEEK_API_KEY=sk-rehearsal-fake-553
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
wait_for() {  # $1 glob under base, $2 count
  local i
  for i in {1..300}; do (( $(print -l $R/base/$~1(N) | wc -l) >= $2 )) && return 0; sleep 1; done
  print "rehearsal: timed out waiting for $1"; return 1
}
run
run 00          # refused: no candidate venv yet
run V
run 00
run P codex dsh
run F
run W
run R all all 1 8
wait_for 'logs/*-S?-r1/status.json' 16
run W
run A all 8
wait_for 'logs/*-S?-r1/audit.md' 16
run W
run C
run T
run G tests/test_gateway.py tests/test_wheel_installation.py
print -r -- "
=============== rehearsal files ==============="
print -r -- "realhost: $(ls $R/realhost | tr '\n' ' ')"
print -r -- "realhost/codex/S1-r1: $(ls $R/realhost/codex/S1-r1 | tr '\n' ' ') | logs/rollouts: $(ls $R/realhost/codex/S1-r1/logs/rollouts | tr '\n' ' ')"
print -r -- "decoy rollout copied anywhere: $(grep -rl decoy0000000 $R/realhost $R/base/logs $R/base/audit 2>/dev/null | head -3 || true)"
print -r -- "hidden text of S1 under any S ws: $(grep -rl 'accepted AND merged' $R/base/project/runs 2>/dev/null || print none)"
print -r -- "U system prompt carries the copied notes (haiku-S1-r1 turn 02 stub reply): $(grep -o 'RESEARCH NOTES present: [A-Za-z]*' $R/base/logs/haiku-S1-r1/02-U.jsonl | head -1)"
print -r -- "S's MCP server is the candidate venv's (sonnet/haiku s-mcp.json, codex argv, dsh patch): $(grep -l "$R/t/venv/bin/graphtraj-mcp" $R/base/logs/sonnet-S1-r1/s-mcp.json $R/base/logs/haiku-S1-r1/s-mcp.json $R/base/logs/codex-S1-r1/01-S.argv.json $R/base/dsh/dsh-S1-r1/dsh-patch.yml 2>/dev/null | wc -l | tr -d ' ') of 4 files"
print -r -- "production graphtraj-mcp named by any S config: $(grep -l '.venv-runtime/bin/graphtraj-mcp' $R/base/logs/*/s-mcp.json $R/base/logs/*/01-S.argv.json $R/base/dsh/*/dsh-patch.yml 2>/dev/null | wc -l | tr -d ' ') files"
print -r -- "
--- realhost/dsh/S2-r1/digest.md (head) ---"; head -24 $R/realhost/dsh/S2-r1/digest.md
print -r -- "
--- realhost/compare-552.md (head) ---"; head -16 $R/realhost/compare-552.md
