#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Round-2 rehearsal (546) of the changed steps, from an EMPTY directory, through the same entry (zsh steps.zsh <step>):
#  1. the state Main has now, built with the OLD AFTER candidate (VERIFY546_GL_AFTER=7b349f0): 00, simulated trust,
#     P, B x5 (B complete), A x2 (old AFTER attempts);
#  2. the new candidate (branch head): 00 (BEFORE venv cached, AFTER venv rebuilt; next line = A), A x5 into
#     after/attempts-<new gl12>, S after (only the new candidate's attempts), C.
# Replaced by stub_claude.py (as `claude`): every model answer, Claude Code's init record (mcp_servers from the real
# --mcp-config file; plugins/plugin_warnings invented), the agents status call and result (invented), and B/A's Main
# (it reads the project's real roles.yml; with the role it invents a create success, one submitted send and a wait,
# so every attempt is valid NOT-HIT; no child exists). The USER trust is simulated by <project>/.stub-trusted.
# Real: steps.zsh, venv builds from git archive of the exact commits, graphtraj setup, claude host configuration,
# roles write + doctor, drv546.py, the attempts directories and their counting, S, C.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
R=${1:?usage: rehearse-r2.zsh <empty dir>}
mkdir -p $R; R=${R:A}
[[ -z $(ls -A $R) ]] || { print "STOP: $R is not empty"; return 1; }
mkdir -p $R/bin
print -r -- "#!/bin/sh
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub_claude.py \"\$@\"" > $R/bin/claude
chmod +x $R/bin/claude
export VERIFY546_BASE=$R/base VERIFY546_T=$R/t VERIFY546_DEST=$R/realhost VERIFY546_CLAUDE=$R/bin/claude
cd $R
run() { print -r -- "
=============== \$ ${VERIFY546_GL_AFTER:+VERIFY546_GL_AFTER=$VERIFY546_GL_AFTER }zsh steps.zsh $* ==============="
  zsh $SD/steps.zsh "$@"; print -r -- "(exit $?)"; }
quiet() { "$@" > /dev/null 2>&1; print -r -- "(quiet) steps.zsh ${@[3,-1]}: exit $?"; }
print -r -- "=============== part 1: the state Main has now (old AFTER candidate 7b349f0), output shortened ==============="
export VERIFY546_GL_AFTER=7b349f088c2afbefa569ac0ee0a7f1841f9cc997
quiet zsh $SD/steps.zsh 00
touch $R/base/before/project/.stub-trusted $R/base/after/project/.stub-trusted
quiet zsh $SD/steps.zsh P
for i in 1 2 3 4 5; do quiet zsh $SD/steps.zsh B; done
for i in 1 2; do quiet zsh $SD/steps.zsh A; done
print -r -- "after part 1: $(cd $R/base && print -l before/attempts/*(N/) after/attempts*/*(N/) | tr '\n' ' ')"
unset VERIFY546_GL_AFTER
print -r -- "
=============== part 2: the new candidate (branch head) ==============="
run 00
for i in 1 2 3 4 5; do run A; done
run S after
run C
print -r -- "
=============== rehearsal files ==============="
print -r -- "attempt dirs: $(cd $R/base && print -l before/attempts/*(N/) after/attempts*/*(N/) | tr '\n' ' ')"
print -r -- "venvs: $(cd $R/t && for v in venv-before venv-after; do print -n "$v=$(<$v/installed) "; done)"
