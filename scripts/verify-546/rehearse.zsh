#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-546 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>):
# 00, B before trust (must STOP at the gate), Tu before, Tu after, [simulated trust], P, B, A, C.
# G/GR were rehearsed on 070b40a5 (rehearsal/output-G-070b40a5.txt) and are unchanged since.
#   zsh scripts/verify-546/rehearse.zsh <empty dir>
# Replaced by stub_claude.py (as `claude`): every model answer and Claude Code's init record (its mcp_servers come
# from the real --mcp-config file; plugins/plugin_warnings are invented in the untrusted and trusted forms), the
# agents status call and its result (invented: authority-denied when untrusted, success when trusted; no MCP server
# is called), and the Main of B/A (no agents call -> NOT-HIT). Tu's dialog is not shown; the user's 'Yes, proceed' is
# simulated by creating <project>/.stub-trusted, which only the stub reads.
# Real: steps.zsh, both phase venvs from git archive, graphtraj setup, claude host configuration (.mcp.json),
# drv546.py gate/probe/summary parsing and verdicts, the gate STOP in B, C.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin
print -r -- "#!/bin/sh
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub_claude.py \"\$@\"" > $R/bin/claude
chmod +x $R/bin/claude
export VERIFY546_BASE=$R/base VERIFY546_T=$R/t VERIFY546_DEST=$R/realhost VERIFY546_CLAUDE=$R/bin/claude
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
run 00
run B
run Tu before
run Tu after
print -r -- "
=============== rehearsal: simulated USER 'Yes, proceed' (touch <project>/.stub-trusted) ==============="
touch $R/base/before/project/.stub-trusted $R/base/after/project/.stub-trusted
run P
run B
run A
run C
print -r -- "
=============== rehearsal files ==============="
print -r -- "B/A argv: $(tr -d '\n' < $R/base/before/runs/run-1/main.argv.json | cut -c1-400)"
print -r -- "realhost copy: $(cd $R/realhost && print -l **/*(N.) | tr '\n' ' ')"
