#!/bin/zsh
# Task 395 Main-run steps. Run one step at a time:  zsh <this file> <STEP>
#   0  preflight: versions, paths, the final candidate's provenance
#   C  clone the checked candidate to <Harness>/graftling, origin LUOXIAO92/graftling, re-run the history check
#   P  push main to origin (normal push, never --force). Only after Main confirms the history check.
#   T  tag v0.5.2 at the pushed head and push the tag (GraphTraj CI's GRAFTLING_REF)
#   G  GraphTraj full suite from this Worktree with graftling installed as a wheel built from <Harness>/graftling (background)
#   I  production install path: both wheels, from the two repositories, installed offline into a throwaway venv
# Every step prints its follow-up with real values. No step signals processes it did not start.
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
# STEPS_395_TMP / STEPS_395_GRAFTLING: team rehearsal only (Main leaves them unset).
T=${STEPS_395_TMP:-$H/tmp/395}
G=${STEPS_395_GRAFTLING:-$H/graftling}
FINAL=$WT/.scratch/395/FINAL                        # written by the team: out=, head=, source=
REPORT_DIR=$WT/.scratch/395
REMOTE=https://github.com/LUOXIAO92/graftling.git
VERSION=0.5.2
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
# pytest's temporary directory stays outside the Harness.
PYTEST_TMP=${TMPDIR:-/tmp}

say() { print -r -- "== $*"; }
final() {
  [[ -f $FINAL ]] || { print "STOP: $FINAL missing; the team has not produced the final candidate"; return 1; }
  OUT=$(sed -n 's/^out=//p' $FINAL); HEAD_SHA=$(sed -n 's/^head=//p' $FINAL); SOURCE=$(sed -n 's/^source=//p' $FINAL)
  [[ -n $OUT && -n $HEAD_SHA && -n $SOURCE ]] || { print "STOP: $FINAL incomplete"; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
graftling_wheel() {  # build graftling's wheel from <Harness>/graftling into $1; print its path
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $1 $G/src/graftling >/dev/null
  print -r -- $1/graftling-$VERSION-py3-none-any.whl
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case $STEP in
0)
  say "[0] preflight. Dialog: none."
  print "claude: $(claude --version 2>&1)"; print "git: $(git --version)"; print "node: $(node --version 2>&1)"
  print "conda python: $($CONDA --version 2>&1) ($CONDA)"
  print "Harness: $H"; print "Worktree: $WT ($(git -C $WT rev-parse --short HEAD))"; print "pytest temp: $PYTEST_TMP"
  final || return 1
  print "candidate: out=$OUT head=$HEAD_SHA source=$SOURCE"
  [[ $(git -C $OUT rev-parse HEAD) == $HEAD_SHA ]] && print "PASS candidate HEAD is $HEAD_SHA" || { print "FAIL candidate HEAD differs"; return 1; }
  [[ -e $G ]] && { print "STOP: $G exists; it is not overwritten"; return 1; } || print "PASS $G absent"
  git -C $WT merge-base --is-ancestor $SOURCE HEAD && print "PASS source $SOURCE is in this branch" || { print "FAIL source not in this branch"; return 1; }
  # Requirement 7: dev holds no graftling change after the dev commit the source was made on.
  local base=$(git -C $WT rev-parse $SOURCE^1)
  local kept=(src/graftling examples/sessions .claude-plugin ${(f)"$(git -C $OUT ls-files tests | grep -v '^tests/conftest.py$')"})
  if git -C $WT diff --quiet $base dev -- $kept; then print "PASS dev has no change to graftling paths since $base"
  else print "STOP: dev changed graftling paths since $base; the team re-runs the split:"; git -C $WT diff --stat $base dev -- $kept | tail -5; return 1; fi
  [[ $(sed -n 's/^__version__ = "\(.*\)"$/\1/p' $OUT/src/graftling/__init__.py) == $VERSION ]] && print "PASS candidate version $VERSION" || { print "FAIL version"; return 1; }
  print "next: zsh ${0:A} C"
  ;;
C)
  say "[C] clone the candidate to $G (origin $REMOTE) and re-check its history. Dialog: none."
  final || return 1
  [[ -e $G ]] && { print "STOP: $G exists"; return 1; }
  mkdir -p $T
  git clone -q --no-hardlinks $OUT $G
  git -C $G remote set-url origin $REMOTE
  git -C $G branch -q -r -d origin/main
  git -C $G symbolic-ref -q refs/remotes/origin/HEAD >/dev/null 2>&1 && git -C $G update-ref -d refs/remotes/origin/HEAD
  print "refs: $(git -C $G for-each-ref --format='%(refname)' | tr '\n' ' ')"
  [[ $(git -C $G rev-parse HEAD) == $HEAD_SHA ]] && print "PASS $G HEAD is $HEAD_SHA" || { print "FAIL HEAD differs"; return 1; }
  print "remote: $(git -C $G remote get-url origin)"
  python3 ${0:A:h}/history_check.py $G $T/history-check-$HEAD_SHA.md
  diff <(sed 1d $REPORT_DIR/history-check-$HEAD_SHA.md) <(sed 1d $T/history-check-$HEAD_SHA.md) >/dev/null \
    && print "PASS history check of $G equals the team's report (apart from the repository path)" \
    || print "FAIL history check differs: diff $REPORT_DIR/history-check-$HEAD_SHA.md $T/history-check-$HEAD_SHA.md"
  sed -n '2,14p' $T/history-check-$HEAD_SHA.md
  print "next, ONLY after Main confirms the history check: zsh ${0:A} P"
  ;;
P)
  say "[P] push main to $REMOTE (normal push). Dialog: possibly the macOS keychain prompt for git-credential-osxkeychain; choose Allow."
  final || return 1
  [[ $(git -C $G rev-parse HEAD) == $HEAD_SHA ]] || { print "STOP: $G HEAD is not $HEAD_SHA"; return 1; }
  [[ $(git -C $G remote get-url origin) == $REMOTE ]] || { print "STOP: origin is not $REMOTE"; return 1; }
  git -C $G push -u origin main
  print "remote main: $(git -C $G ls-remote origin refs/heads/main)"
  print "expect:      $HEAD_SHA"
  print "next: zsh ${0:A} T"
  ;;
T)
  say "[T] tag v$VERSION at $HEAD_SHA and push the tag. Dialog: as in P (keychain; Allow)."
  final || return 1
  [[ $(git -C $G rev-parse HEAD) == $HEAD_SHA ]] || { print "STOP: HEAD is not $HEAD_SHA"; return 1; }
  [[ $(git -C $G ls-remote origin refs/heads/main | cut -f1) == $HEAD_SHA ]] || { print "STOP: remote main is not $HEAD_SHA; run P first"; return 1; }
  [[ $(sed -n 's/^__version__ = "\(.*\)"$/\1/p' $G/src/graftling/__init__.py) == $VERSION ]] || { print "STOP: version is not $VERSION"; return 1; }
  git -C $G -c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com \
    tag -a v$VERSION -m "graftling $VERSION" $HEAD_SHA
  git -C $G push origin v$VERSION
  print "remote tag: $(git -C $G ls-remote origin refs/tags/v$VERSION "refs/tags/v$VERSION^{}")"
  ;;
G)
  say "[G] GraphTraj full suite from $WT with graftling installed as a wheel from $G (6 shards, --timeout 1500, background). Dialog: none. Returns at once."
  [[ -d $G/src/graftling ]] || { print "STOP: run C first"; return 1; }
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another run_test_shards is running; queue G and rerun later:"; print -r -- $others; return 1; }
  local V=$T/venv-gt R=$T/suite-$(git -C $WT rev-parse --short HEAD) N=$T/wheels-gt
  [[ -e $V || -e $N ]] && { print "STOP: $V or $N exists; move them to $H/tmp/.trash/ first"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  $CONDA -m venv --system-site-packages $V && copy_deps $V
  local wheel=$(graftling_wheel $N)
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    $wheel -e $WT 2>&1 | grep -vi cache || true
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $R
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print "failures:   grep -h -E '^(FAILED|ERROR) ' $R/suite.txt $R/shards/*(N) | sort -u"
  ;;
I)
  say "[I] production install path: graftling wheel from $G, graphtraj wheel from $WT, installed offline into a throwaway venv. Dialog: none."
  [[ -d $G/src/graftling ]] || { print "STOP: run C first"; return 1; }
  local V=$T/venv-install N=$T/wheels
  [[ -e $V || -e $N ]] && { print "STOP: $V or $N exists; move them to $H/tmp/.trash/ first"; return 1; }
  $CONDA -m venv $V && copy_deps $V
  graftling_wheel $N >/dev/null
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $WT
  ls $N
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/*.whl
  $V/bin/python -m pip check
  (cd $PYTEST_TMP && $V/bin/python -I -c 'from importlib.metadata import version, metadata, requires, entry_points as e; print("graftling", version("graftling"), metadata("graftling")["License-Expression"]); print("graphtraj", version("graphtraj"), metadata("graphtraj")["License-Expression"], [r for r in requires("graphtraj") if r.startswith("graftling")]); print("hosts", [x.value for x in e(group="graftling.hosts")])')
  # GraphTraj's Pi and DSH modules find graftling beside graphtraj in an installed layout.
  (cd $PYTEST_TMP && node --input-type=module -e "const { pathToFileURL } = await import('node:url'); const m = await import(pathToFileURL(process.argv[1]).href); console.log('graftling for GraphTraj modules:', m.graftlingDirectory('pi/extension.mjs'))" \
    "$($V/bin/python -c 'import graphtraj, pathlib; print(pathlib.Path(graphtraj.__file__).parent / "runtimes/graftling.mjs")')")
  $V/bin/graphtraj --help | head -3
  $V/bin/agents --help | head -3
  print "done; nothing outside $T changed"
  ;;
*) print "usage: zsh ${0:A} 0|C|P|T|G|I"; return 2 ;;
esac
