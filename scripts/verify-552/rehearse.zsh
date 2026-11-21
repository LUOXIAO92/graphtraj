#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-552 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-552/rehearse.zsh <empty dir>
# Stubs (stub552.py, first on PATH): claude, codex, dsh, and sandbox-exec (VERIFY552_SBX). See README.md for exactly
# what is stub and what is real. Overrides: BASE, DENYROOT (a fake tree), DEST (C's copy into the rehearsal dir),
# CODEX_SESSIONS (a fake ~/.codex/sessions with a decoy rollout of another session), stub bin first on PATH.
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
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub552.py $h \"\$@\"" > $R/bin/$h
  chmod +x $R/bin/$h
done
export VERIFY552_STUBBIN=$R/bin VERIFY552_STUB_STATE=$R/stub-state VERIFY552_BASE=$R/base \
  VERIFY552_DENYROOT=$R/fake-workspace VERIFY552_DEST=$R/realhost VERIFY552_SBX=$R/bin/sandbox-exec \
  VERIFY552_CODEX_SESSIONS=$R/codex-sessions DEEPSEEK_API_KEY=sk-rehearsal-fake-552
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
wait_for() {  # $1 glob under base, $2 count
  local i
  for i in {1..300}; do (( $(print -l $R/base/$~1(N) | wc -l) >= $2 )) && return 0; sleep 1; done
  print "rehearsal: timed out waiting for $1"; return 1
}
run
run 00
run P
run P codex dsh   # correction: re-probe only codex and dsh
run F
wait_for 'u/research/S?.md' 4
run W
run R all all 1 8
wait_for 'logs/*-S?-r1/status.json' 16
run W
run A all 8
wait_for 'logs/*-S?-r1/audit.md' 16
run W
run C
print -r -- "
=============== rehearsal files ==============="
print -r -- "realhost: $(ls $R/realhost | tr '\n' ' ')"
print -r -- "realhost/codex/S1-r1: $(ls $R/realhost/codex/S1-r1 | tr '\n' ' ') | logs/rollouts: $(ls $R/realhost/codex/S1-r1/logs/rollouts | tr '\n' ' ')"
print -r -- "decoy rollout copied anywhere: $(grep -rl decoy0000000 $R/realhost $R/base/logs $R/base/audit 2>/dev/null | head -3 || true)"
print -r -- "realhost/dsh/S2-r1: $(ls $R/realhost/dsh/S2-r1 | tr '\n' ' ')"
print -r -- "hidden text of S1 under any S ws: $(grep -rl 'accepted AND merged' $R/base/project/runs 2>/dev/null || print none)"
print -r -- "U argv placeholder (haiku-S1-r1 turn 02): $(grep -o '<instruction with HIDDEN[^"]*>' $R/base/logs/haiku-S1-r1/02-U.argv.json)"
print -r -- "
--- realhost/dsh/S2-r1/digest.md (head) ---"; head -40 $R/realhost/dsh/S2-r1/digest.md
print -r -- "
--- realhost/runs-table.md ---"; cat $R/realhost/runs-table.md
