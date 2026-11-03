#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 01-install. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/01-install.zsh
# Walks README's wheel install as written into the agents-only venv every later step uses, and checks the Pi sandbox.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# Downloads setuptools for the wheel's build and PyYAML and websockets, from PyPI, into this venv only.
step_begin 01-install 6 none 'one wheel, only agent-swarm, PyYAML, websockets and pip in the venv, a plain shell gets authority-denied, and the Pi sandbox installer says VERIFIED twice'
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi

# An earlier venv is kept beside the new one, never removed; a venv from this commit is kept in use.
if [[ -f $VENV/installed-commit && $(<$VENV/installed-commit) == $COMMIT ]]; then
  note "the venv was already built from $COMMIT; the install is not repeated. Move $VENV aside to walk it again"
else
  [[ -e $VENV ]] && mv $VENV $VENV.$STAMP && note "an earlier venv was moved to $VENV.$STAMP"
  CHECKOUT=$RUN/checkout
  git clone -q --no-hardlinks $WT $CHECKOUT
  git -C $CHECKOUT checkout -q --detach $COMMIT
  say "README's commands, as written, from that checkout"
  cd $CHECKOUT
  print -r -- "python3: $(command -v python3) $(python3 --version)"
  AGENTS_VENV=$VENV
  python3 -m venv "$AGENTS_VENV"
  # In a checkout of the repository. The new directory holds exactly one wheel.
  WHEELS="$(mktemp -d)"
  "$AGENTS_VENV/bin/python" -m pip wheel --no-deps -w "$WHEELS" ./src/agent_swarm 2>&1 | tee $OUT/readme-install.txt
  "$AGENTS_VENV/bin/python" -m pip install "$WHEELS"/agent_swarm-*.whl 2>&1 | tee -a $OUT/readme-install.txt
  "$AGENTS_VENV/bin/agents" --help 2>&1 | tee -a $OUT/readme-install.txt
  check PASS "README install commands ran as written: python3 $(python3 --version 2>&1)"
  WHEEL=($WHEELS/*.whl)
  judge $(( ${#WHEEL} != 1 )) "exactly one wheel: ${WHEEL:t}"
  mkdir -p $AG/wheels
  cp $WHEEL $AG/wheels/
  cd $RUN
  print -r -- $COMMIT > $VENV/installed-commit
fi

say "what is in the venv"
installed_versions $VENV
$VENV/bin/python -m pip list --disable-pip-version-check 2>/dev/null | tee $OUT/pip-list.txt
EXTRA=$(tail -n +3 $OUT/pip-list.txt | awk '{print tolower($1)}' | grep -vxE 'agent-swarm|pyyaml|websockets|pip' | tr '\n' ' ' || true)
[[ -z $EXTRA ]] && check PASS "only agents, its two dependencies and pip are installed" || check FAIL "the venv also holds: $EXTRA"
venv_check
check PASS "graphtraj is not importable; agent_swarm $($VENV/bin/python -I -c 'import agent_swarm; print(agent_swarm.__version__)')"
$VENV/bin/python -m pip check 2>&1 | tee $OUT/pip-check.txt | tail -1 || true

say "a plain shell, the one README describes"
CODE=0
(cd $RUN && env -u AGENT_SWARM_CONNECTION $VENV/bin/agents '{"action":"discover"}') > $OUT/plain-discover.txt 2>&1 || CODE=$?
grep -q authority-denied $OUT/plain-discover.txt && (( CODE == 1 )) \
  && check PASS "agents from a plain shell: authority-denied, exit 1" || check FAIL "agents from a plain shell: exit $CODE, $(cut -c1-200 $OUT/plain-discover.txt)"
CODE=0
$VENV/bin/agents-mcp </dev/null > $OUT/plain-mcp.txt 2>&1 || CODE=$?
judge $CODE "agents-mcp with stdin closed ends: exit $CODE"
for doc in README.md PUBLIC_API.md CHANGELOG.md install/claude-code.md install/codex.md install/pi.md install/dsh.md; do
  [[ -f $($VENV/bin/python -I -c 'import agent_swarm, pathlib; print(pathlib.Path(agent_swarm.__file__).parent)')/$doc ]] \
    || check FAIL "the wheel lacks $doc"
done
check PASS "the wheel carries the seven documents, or a FAIL line above names the one missing"

say "install-pi-sandbox.sh: plain, then --check"
for form in plain check; do
  CODE=0
  /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh ${${form:#plain}:+--check} > $OUT/install-pi-sandbox-$form.txt 2>&1 || CODE=$?
  (( CODE == 0 )) && check PASS "install-pi-sandbox.sh $form: $(tail -1 $OUT/install-pi-sandbox-$form.txt)" \
    || check FAIL "install-pi-sandbox.sh $form: exit $CODE; $(tail -1 $OUT/install-pi-sandbox-$form.txt); see install-pi-sandbox-$form.txt"
done
if [[ -f $PI_SANDBOX/pi-sandbox.env ]]; then
  cp $PI_SANDBOX/pi-sandbox.env $OUT/pi-sandbox.env
  read_sandbox
  FOUND=$(PATH=$SANDBOX_PATH command -v rg || true)
  [[ -n $FOUND ]] && check PASS "387: pi-sandbox.env puts rg on the child's PATH: $FOUND" || check FAIL "387: no rg on the child's PATH: $SANDBOX_PATH"
fi
step_end
