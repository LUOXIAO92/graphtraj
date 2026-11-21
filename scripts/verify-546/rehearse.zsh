#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Rehearsal of verify-546 from an EMPTY directory through the same entry Main uses (zsh steps.zsh <step>), every step.
#   zsh scripts/verify-546/rehearse.zsh <empty dir>
# Replaced by stub_claude.py (as `claude`): the READY answer, the 00 probe's init tool list and its agents status call
# and result (invented; no MCP server is called), and the whole Main model of B/A (no agents call -> NOT-HIT).
# Real: steps.zsh, both phase venvs from git archive of the exact commits, graphtraj setup, the claude host
# configuration, the MCP approval write, drv546.py ready/probe/summary parsing, G's guards, venvs, temp root and
# background runner with a test subset (VERIFY546_GT_TESTS: a GraphTraj file using its `project` fixture;
# VERIFY546_GL_TESTS: graftling files incl. the real-ClaudeDriver 546 test), GR's classification, C.
# Overrides: BASE, T (venvs/suites in the rehearsal dir instead of <Harness>/tmp/546), DEST, CLAUDE.
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
export VERIFY546_BASE=$R/base VERIFY546_T=$R/t VERIFY546_DEST=$R/realhost VERIFY546_CLAUDE=$R/bin/claude \
  VERIFY546_GT_TESTS=tests/test_agents_configuration_recorded.py \
  VERIFY546_GL_TESTS='tests/test_agent_control.py tests/test_claude_send_closing_546.py tests/test_dsh_standalone_child.py'
cd $R
run() { print -r -- "
=============== \$ zsh steps.zsh $* ==============="; zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
run 00
run B
run A
run G
for i in {1..200}; do
  G=$(cat $R/t/G-latest 2>/dev/null)
  [[ -n $G ]] && grep -q '^exit=' $G/gt.txt(N) && grep -q '^exit=' $G/gl.txt(N) && break; sleep 3
done
run GR
run C
print -r -- "
=============== rehearsal files ==============="
print -r -- "before project settings.local.json: $(tr -d '\n ' < $R/base/before/project/.claude/settings.local.json)"
print -r -- "realhost copy: $(cd $R/realhost && print -l **/*(N.) | tr '\n' ' ')"
