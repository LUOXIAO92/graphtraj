#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 01-install. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/01-install.zsh
#
# README's wheel install as written, from a clean checkout of COMMIT, into /Users/luoxiao/agents-394/venv
# (graftling only), then the metadata check: graftling and graphtraj wheels of COMMIT in a second venv,
# /Users/luoxiao/agents-394/venv-graphtraj, where pip resolves graphtraj's graftling range. Never the
# production .venv-runtime, Conda or the system. Downloads setuptools, PyYAML, websockets and click from
# PyPI into these two venvs only.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 01-install 6 none 'one wheel graftling-0.5.0; the venv holds only graftling, PyYAML, websockets and pip; graphtraj resolves graftling>=0.5.0,<0.6 and pip check is clean'
if [[ -n ${AGENTS_394_DRY_BIN:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi

CHECKOUT=$RUN/checkout
git clone -q --no-hardlinks $WT $CHECKOUT
git -C $CHECKOUT checkout -q --detach $COMMIT

say "graftling only: README's commands, as written, from that checkout"
if [[ -f $VENV/installed-commit && $(<$VENV/installed-commit) == $COMMIT ]]; then
  note "the venv was already built from $COMMIT; the install is not repeated. To walk it again: mv $VENV $VENV.$STAMP"
else
  [[ -e $VENV ]] && mv $VENV $VENV.$STAMP && note "an earlier venv was moved to $VENV.$STAMP"
  cd $CHECKOUT
  print -r -- "python3: $(command -v python3) $(python3 --version)"
  AGENTS_VENV=$VENV
  python3 -m venv "$AGENTS_VENV"
  WHEELS="$(mktemp -d)"
  "$AGENTS_VENV/bin/python" -m pip wheel --no-deps -w "$WHEELS" ./src/graftling 2>&1 | tee $OUT/readme-install.txt
  "$AGENTS_VENV/bin/python" -m pip install "$WHEELS"/graftling-*.whl 2>&1 | tee -a $OUT/readme-install.txt
  "$AGENTS_VENV/bin/agents" --help 2>&1 | tee -a $OUT/readme-install.txt
  check PASS "README install commands ran as written: python3 $(python3 --version 2>&1)"
  WHEEL=($WHEELS/*.whl)
  [[ ${#WHEEL} == 1 && ${WHEEL:t} == graftling-$DIST_VERSION-*.whl ]] && check PASS "exactly one wheel: ${WHEEL:t}" \
    || check FAIL "expected one wheel graftling-$DIST_VERSION-*.whl, found: ${WHEEL:t}"
  mkdir -p $AG/wheels
  cp $WHEEL $AG/wheels/
  cd $RUN
  print -r -- $COMMIT > $VENV/installed-commit
fi
installed_versions $VENV
$VENV/bin/python -m pip list --disable-pip-version-check 2>/dev/null | tee $OUT/pip-list.txt
EXTRA=$(tail -n +3 $OUT/pip-list.txt | awk '{print tolower($1)}' | grep -vxE 'graftling|pyyaml|websockets|pip' | tr '\n' ' ' || true)
[[ -z $EXTRA ]] && check PASS "only graftling, its two dependencies and pip are installed" || check FAIL "the venv also holds: $EXTRA"
venv_check
check PASS "neither graphtraj nor agent_swarm is importable; graftling $($VENV/bin/python -I -c 'import graftling; print(graftling.__version__)')"
PACKAGE=$($VENV/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent)')
for doc in README.md PUBLIC_API.md CHANGELOG.md install/claude-code.md install/codex.md install/pi.md install/dsh.md; do
  [[ -f $PACKAGE/$doc ]] || check FAIL "the wheel lacks $doc"
done
check PASS "the wheel carries the seven documents, or a FAIL line above names the one missing"
for pair in dsh:graftling-dsh pi:graftling-pi; do
  NAME=$($PY -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["name"])' $PACKAGE/${pair%%:*}/package.json 2>&1 || true)
  [[ $NAME == ${pair#*:} ]] && check PASS "npm package name in ${pair%%:*}/package.json: $NAME" \
    || check FAIL "npm package name in ${pair%%:*}/package.json: $NAME, not ${pair#*:}"
done

say "a plain shell, the one README describes"
CODE=0
(cd $RUN && env -u GRAFTLING_CONNECTION $VENV/bin/agents '{"action":"discover"}') > $OUT/plain-discover.txt 2>&1 || CODE=$?
grep -q authority-denied $OUT/plain-discover.txt && (( CODE == 1 )) \
  && check PASS "agents from a plain shell: authority-denied, exit 1" || check FAIL "agents from a plain shell: exit $CODE, $(cut -c1-200 $OUT/plain-discover.txt)"
CODE=0
$VENV/bin/agents-mcp </dev/null > $OUT/plain-mcp.txt 2>&1 || CODE=$?
judge $CODE "agents-mcp with stdin closed ends: exit $CODE"

say "the metadata check: graphtraj and graftling wheels of $COMMIT in $GT"
if [[ -f $GT/installed-commit && $(<$GT/installed-commit) == $COMMIT ]]; then
  note "$GT was already built from $COMMIT; not repeated. To build it again: mv $GT $GT.$STAMP"
else
  [[ -e $GT ]] && mv $GT $GT.$STAMP && note "an earlier venv was moved to $GT.$STAMP"
  $PY -m venv $GT
  GT_WHEELS=$RUN/gt-wheels
  (cd $CHECKOUT && $GT/bin/python -m pip wheel -q --no-deps -w $GT_WHEELS ./src/graftling . ) 2>&1 | tee $OUT/gt-wheels.txt | tail -3
  # Only graphtraj is named: pip must find graftling itself, in the local wheel, through graphtraj's range.
  CODE=0
  $GT/bin/python -m pip install --find-links $GT_WHEELS $GT_WHEELS/graphtraj-*.whl > $OUT/gt-install.txt 2>&1 || CODE=$?
  judge $CODE "pip install of the graphtraj wheel alone, graftling found through its range in $GT_WHEELS: exit $CODE; $(tail -1 $OUT/gt-install.txt | cut -c1-200)"
  (( CODE == 0 )) && print -r -- $COMMIT > $GT/installed-commit
fi
$GT/bin/python -m pip list --disable-pip-version-check 2>/dev/null > $OUT/gt-pip-list.txt || true
installed_versions $GT
$GT/bin/python -m pip check > $OUT/gt-pip-check.txt 2>&1 && check PASS "pip check in $GT: $(tail -1 $OUT/gt-pip-check.txt)" \
  || check FAIL "pip check in $GT: $(tail -1 $OUT/gt-pip-check.txt)"
$GT/bin/python -I - > $OUT/gt-metadata.txt 2>&1 <<'PYEOF' || true
import importlib.metadata as m
requires = [r for r in (m.requires('graphtraj') or []) if r.replace('_', '-').lower().startswith(('graftling', 'agent-swarm'))]
print('requires', ' | '.join(requires))
print('graftling.hosts', ' '.join(sorted(f'{e.name}={e.value}' for e in m.entry_points(group='graftling.hosts'))))
print('old hosts group', ' '.join(sorted(e.name for e in m.entry_points(group='agent' + '_swarm.hosts'))) or 'none')
import graftling, graphtraj
print('imports', graftling.__version__, graftling.__file__)
PYEOF
cat $OUT/gt-metadata.txt
REQUIRES=$(sed -n 's/^requires //p' $OUT/gt-metadata.txt)
[[ $REQUIRES == graftling* && $REQUIRES == *'>=0.5.0'* && $REQUIRES == *'<0.6'* && $REQUIRES != *agent* ]] \
  && check PASS "graphtraj requires: $REQUIRES" || check FAIL "graphtraj requires: '${REQUIRES:-nothing}', not graftling>=0.5.0,<0.6"
HOSTS=$(sed -n 's/^graftling\.hosts //p' $OUT/gt-metadata.txt)
[[ $HOSTS == *graphtraj=* ]] && check PASS "entry points graftling.hosts: $HOSTS" || check FAIL "entry points graftling.hosts: '${HOSTS:-none}'"
OLD=$(sed -n 's/^old hosts group //p' $OUT/gt-metadata.txt)
[[ $OLD == none ]] && check PASS "entry points of the old group (agent_swarm.hosts): none" || check FAIL "entry points of the old group (agent_swarm.hosts): '${OLD:-unread}'"
grep -q '^imports ' $OUT/gt-metadata.txt && check PASS "graftling and graphtraj import together: $(sed -n 's/^imports //p' $OUT/gt-metadata.txt)" \
  || check FAIL "graftling and graphtraj do not import together: $(tail -1 $OUT/gt-metadata.txt)"
for tool in graphtraj agent-runner graphtraj-session agents agents-mcp; do
  [[ -x $GT/bin/$tool ]] || check FAIL "$tool missing from $GT/bin"
done
check PASS "graphtraj, agent-runner, graphtraj-session, agents and agents-mcp sit beside $GT/bin/python, or a FAIL line above names one"
old_names
step_end
