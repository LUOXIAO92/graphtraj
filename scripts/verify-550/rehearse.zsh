#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-550 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>).
#   zsh scripts/verify-550/rehearse.zsh <empty dir>
# Replaced by the stub (stub_claude.py, first on PATH as `claude`): every model and Claude Code's permission
# enforcement. Real: steps.zsh, drv550.py, design.md parsing, the scenario files, the production graphtraj setup +
# claude host configuration (read only) in the scratch project, S's tasks describe concept-clarification through
# the production graphtraj-mcp, the Reads of the guide and ws files, the relay loop with --resume, the audit folder,
# C's copy and its K0a / path / audit-line output. Overrides: BASE, DENYROOT (a fake tree; the sandbox cannot list
# the real one), DEST (C's copy goes into the rehearsal dir, not .state/realhost), CLAUDE (the stub).
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin $R/fake-workspace/other-project $R/fake-workspace/harness/.venv-runtime
print -r -- "#!/bin/sh
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub_claude.py \"\$@\"" > $R/bin/claude
chmod +x $R/bin/claude
export STUB550_STATE=$R/stub-state VERIFY550_BASE=$R/base VERIFY550_DENYROOT=$R/fake-workspace \
  VERIFY550_DEST=$R/realhost VERIFY550_CLAUDE=$R/bin/claude
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
wait_for() {  # $1 glob under base/logs, $2 count
  local i
  for i in {1..120}; do (( $(print -l $R/base/logs/$~1(N) | wc -l) >= $2 )) && return 0; sleep 1; done
  print "rehearsal: timed out waiting for $1"; return 1
}
run 00
run R all
wait_for 'S?/status.json' 4
run W
run A all
wait_for 'S?/audit.md' 4
run W
run C
print -r -- "
=============== rehearsal files ==============="
print -r -- "S1 ws after the run: $(ls $R/base/project/runs/S1/ws | tr '\n' ' ')"
print -r -- "S1 handoff.md last line: $(tail -1 $R/base/project/runs/S1/ws/handoff.md)"
print -r -- "S1 U turn argv (hidden block replaced in the log):"; grep -A1 append-system-prompt $R/base/logs/S1/02-U.argv.json
print -r -- "hidden text of S1 in any file under S1's ws: $(grep -rl 'accepted AND merged' $R/base/project/runs/S1/ws || print none)"
print -r -- "S1 audit.md:"; cat $R/base/logs/S1/audit.md
print -r -- "realhost copy: $(ls $R/realhost/S1 | tr '\n' ' ') | S1/logs: $(ls $R/realhost/S1/logs | tr '\n' ' ')"
