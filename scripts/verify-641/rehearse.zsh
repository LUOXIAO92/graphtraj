#!/bin/zsh
# Engineer rehearsal of steps.zsh through the same entry Main uses (zsh steps.zsh <step>), without the user's logins
# and without network writes. Every run sets VERIFY641_* variables, so each step prints REHEARSAL and is not evidence.
# Stand-ins: `claude` runs the prompt's tasks calls through the MCP entry's python and env (no Claude host, no native
# association; the judge says STAND-IN); `gh` keeps Issues in a JSON file (x641.py fake-gh), answering a deleted Issue
# with HTTP 410 as GitHub does, and answers at all only when HOME is the (stand-in) user HOME, as gh's stored login. Console output goes to rehearsal/<step>.txt with the home and temporary directories
# replaced by ~ and $TMPDIR.
# usage: zsh rehearse.zsh <step>...
#        REHEARSAL_BREAK_RUN=2 REHEARSAL_NAME=real-broken-run2 zsh rehearse.zsh real   (run 2 makes no call: cleanup
#        must still delete every Issue created so far)
#        REHEARSAL_OTHER_TOOL=1 REHEARSAL_NAME=real-other-tool zsh rehearse.zsh real   (the stand-in also uses Bash:
#        the judge must FAIL it; the stand-in always loads the tool with ToolSearch first, as the real host did)
emulate -L zsh
setopt pipe_fail
SD=${0:A:h}
CONDA=$HOME/miniconda3/bin/python3.13
SCRATCH=${TMPDIR:-/tmp}/641r
mkdir -p $SD/rehearsal $SCRATCH/bin $SCRATCH/claude $SCRATCH/userhome/.graphtraj $SCRATCH/userhome/.config/gh $SCRATCH/userhome/.codex
# Stand-in user files for post: Codex runtime-volatile ones (INFO) and one judged file.
local f; for f in logs_2.sqlite logs_2.sqlite-wal models_cache.json config.toml; do
  [[ -e $SCRATCH/userhome/.codex/$f ]] || print -r -- stand-in > $SCRATCH/userhome/.codex/$f; done
print -r -- "#!/bin/sh
exec $CONDA -I $SD/x641.py fake-gh $SCRATCH/gh-state.json $SCRATCH/userhome \"\$@\"" > $SCRATCH/bin/gh
print -r -- "#!/bin/sh
exec $CONDA -I $SD/x641.py fake-claude ${REHEARSAL_BREAK_RUN:+--rehearsal-break-run $REHEARSAL_BREAK_RUN} ${REHEARSAL_OTHER_TOOL:+--rehearsal-other-tool} \"\$@\"" > $SCRATCH/claude/claude
chmod +x $SCRATCH/bin/gh $SCRATCH/claude/claude
export VERIFY641_ROOT=$SCRATCH/root VERIFY641_T=$SCRATCH/T VERIFY641_OUT=$SCRATCH/out VERIFY641_USERHOME=$SCRATCH/userhome
export VERIFY641_GH=$SCRATCH/bin/gh VERIFY641_CLAUDE=$SCRATCH/claude/claude
export VERIFY641_REPO=owner/repo VERIFY641_NO_PS=1 VERIFY641_GWAIT=5
export VERIFY641_PYTEST_ARGS=${VERIFY641_PYTEST_ARGS:-"-k 'test_github_backup or test_intent_queries_find_create'"}
T=${TMPDIR%/}
local step name; for step in "$@"; do
  name=${REHEARSAL_NAME:-${step%% *}}   # a step word may carry arguments: 'suite-base <node id>'
  { print -r -- "\$ zsh steps.zsh $step   (rehearsal $(date +%FT%T))"; zsh $SD/steps.zsh ${(z)step} 2>&1 } \
    | sed -e "s#/private$T#\$TMPDIR#g" -e "s#$T#\$TMPDIR#g" -e "s#$HOME#~#g" -e "s#${USER:-nobody}#<user>#g" \
    | tee $SD/rehearsal/$name.txt
done
