# Task 392 steps 60 to 91: what they add to common.zsh. Sourced, never run.

# `run_residual <function> [argument]`: a stop inside is a FAIL line, and the step still saves.
run_residual() {
  setopt local_options no_err_exit
  (cd $RUN && $VENV/bin/python -E -s $HERE/residual.py "$@")
  local code=$?
  (( code == 0 )) || check FAIL "residual.py $* stopped with exit $code; see the terminal transcript"
}

# `run_scratch <function>`: the same, with the dedicated GraphTraj venv that step 88 builds.
run_scratch() {
  setopt local_options no_err_exit
  local gt=$AG/venv-graphtraj
  [[ -f $gt/installed-commit && $(<$gt/installed-commit) == $COMMIT ]] || fail "run step 88 first: zsh $HERE/88-graphtraj-venv.zsh"
  (cd $RUN && $gt/bin/python -E -s $HERE/scratch_project.py "$@")
  local code=$?
  (( code == 0 )) || check FAIL "scratch_project.py $* stopped with exit $code; see the terminal transcript"
}
