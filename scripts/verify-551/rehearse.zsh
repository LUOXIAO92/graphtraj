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
  # While $R/untrusted exists the stub Claude's init carries the untrusted-folder warning (survives clean()).
  print -r -- "#!/bin/sh
[ -f $R/untrusted ] && export STUB551_UNTRUSTED=1
[ -f $R/au-request ] && export STUB551_AU_REQUEST=1
[ -f $R/tasks-request ] && export STUB551_TASKS_REQUEST=1
export STUB551_PROJECTS=$R/claude-projects
exec $HOME/miniconda3/bin/python3.13 -I $SD/stub551.py $h \"\$@\"" > $R/bin/$h; chmod +x $R/bin/$h
done
export VERIFY551_BASE=$R/base VERIFY551_STUB=$R/bin VERIFY551_PI_SANDBOX_ENV=${VERIFY551_PI_SANDBOX_ENV:-$R/no-pi-sandbox.env} \
  VERIFY551_DSH_SESSIONS=$R/dsh-sessions \
  VERIFY551_T=$R/t \
  VERIFY551_CLAUDE_PROJECTS=$R/claude-projects    # G's venvs and AU transcripts here (rehearsal only)
# VERIFY551_TESTS / VERIFY551_GL_TESTS (set by the caller) limit G to real test files through the same entry.
cd $R
local steps=("$@"); (( $#steps )) || steps=(untrusted 00 "B claude" U trusted 00 "B claude")
local s; for s in $steps; do
  case $s in   # rehearsal-only switches of the stub's folder trust, and waiting for G's background suites
    untrusted) touch $R/untrusted; print -r -- "
=============== (rehearsal: the project folder is UNTRUSTED from here) ==============="; continue ;;
    trusted) rm -f $R/untrusted; print -r -- "
=============== (rehearsal: the user trusted the folder in U) ==============="; continue ;;
    au-request) touch $R/au-request; print -r -- "
=============== (rehearsal: the stub child's WebFetch asks the parent; the parent relays deny) ==============="; continue ;;
    tasks-request) touch $R/tasks-request; print -r -- "
=============== (rehearsal: the stub child's tasks call ALSO raises a request: the FAIL path) ==============="; continue ;;
    au-norequest) rm -f $R/au-request; print -r -- "
=============== (rehearsal: the stub child's WebFetch runs without any request) ==============="; continue ;;
    waitG) local g i; for i in {1..600}; do g=$(cat $R/base/runs/G-latest 2>/dev/null)
             [[ -n $g ]] && grep -q '^exit=' $g/suite.txt 2>/dev/null && grep -q '^exit=' $g/graftling-suite.txt 2>/dev/null && break
             sleep 1; done
           print -r -- "
=============== (rehearsal: G's background suites ended after ~${i}s) ==============="; continue ;;
  esac
  print -r -- "
=============== \$ zsh steps.zsh $s ==============="
  zsh $SD/steps.zsh ${=s}; print -r -- "(exit $?)"
done
