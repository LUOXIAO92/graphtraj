#!/bin/zsh
# Engineer rehearsal of steps.zsh through the same entry Main uses (zsh steps.zsh <step>), without the user's logins
# and without network writes. Every run sets VERIFY641_* variables, so each step prints REHEARSAL and is not evidence.
# Stand-ins: `claude` runs the prompt's tasks calls through the MCP entry's python and env (no Claude host, no native
# association; the judge says STAND-IN); `gh` keeps Issues in a JSON file (x641.py fake-gh), answering a deleted Issue
# with HTTP 410 as GitHub does. Console output goes to rehearsal/<step>.txt with the home and temporary directories
# replaced by ~ and $TMPDIR.
# usage: zsh rehearse.zsh <step>...
#        REHEARSAL_BREAK_RUN=2 REHEARSAL_NAME=real-broken-run2 zsh rehearse.zsh real   (run 2 makes no call: cleanup
#        must still delete every Issue created so far)
emulate -L zsh
setopt pipe_fail
SD=${0:A:h}
CONDA=$HOME/miniconda3/bin/python3.13
SCRATCH=${TMPDIR:-/tmp}/641r
mkdir -p $SD/rehearsal $SCRATCH/bin $SCRATCH/claude $SCRATCH/userhome/.graphtraj $SCRATCH/userhome/.config/gh
print -r -- "#!/bin/sh
exec $CONDA -I $SD/x641.py fake-gh $SCRATCH/gh-state.json \"\$@\"" > $SCRATCH/bin/gh
print -r -- "#!/bin/sh
exec $CONDA -I $SD/x641.py fake-claude ${REHEARSAL_BREAK_RUN:+--rehearsal-break-run $REHEARSAL_BREAK_RUN} \"\$@\"" > $SCRATCH/claude/claude
chmod +x $SCRATCH/bin/gh $SCRATCH/claude/claude
export VERIFY641_ROOT=$SCRATCH/root VERIFY641_T=$SCRATCH/T VERIFY641_OUT=$SCRATCH/out VERIFY641_USERHOME=$SCRATCH/userhome
export VERIFY641_GH=$SCRATCH/bin/gh VERIFY641_CLAUDE=$SCRATCH/claude/claude VERIFY641_GHCONFIG=$SCRATCH/userhome/.config/gh
export VERIFY641_REPO=owner/repo VERIFY641_NO_PS=1 VERIFY641_GWAIT=5
export VERIFY641_PYTEST_ARGS=${VERIFY641_PYTEST_ARGS:-"-k 'test_github_backup or test_intent_queries_find_create'"}
T=${TMPDIR%/}
local step name; for step in "$@"; do
  name=${REHEARSAL_NAME:-$step}
  { print -r -- "\$ zsh steps.zsh $step   (rehearsal $(date +%FT%T))"; zsh $SD/steps.zsh $step 2>&1 } \
    | sed -e "s#/private$T#\$TMPDIR#g" -e "s#$T#\$TMPDIR#g" -e "s#$HOME#~#g" -e "s#${USER:-nobody}#<user>#g" \
    | tee $SD/rehearsal/$name.txt
done
