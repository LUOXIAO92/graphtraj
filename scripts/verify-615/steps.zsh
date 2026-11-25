#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 615 Main-run steps: graftling's discover with "start an agent" lists only create; a model-listing intent
# still lists models. graftling only; GraphTraj is used only by step T's test file. Modelled on verify-613/steps.zsh.
#
# LOGIN: NONE. No step starts Claude Code, Codex, Pi or DSH and no step reads a login, key or token.
# REAL ENTRY: the installed `subagents` console script (graftling.cli:main) of the candidate wheel. Without an owner
# connection (GRAFTLING_CONNECTION) the CLI refuses every request with authority-denied (PUBLIC_API 1.1), unless an
# installed host plugin claims the directory (PUBLIC_API 1.4, entry point group graftling.hosts, which GraphTraj
# uses the same way). Step I installs, beside the candidate wheel, a small host package `verify615-host` built here
# whose entry point claims only ROOT/proj; its dispatch executes nothing (every execute fails with
# operation-failed), and discover never reaches it: discover is graftling's own handle_request in the CLI. Step R
# also runs the same CLI outside ROOT/proj and expects authority-denied, which shows the plugin is what admits it.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight. zsh; versions (git, python); PyYAML and websockets in <Harness>/.venv-runtime; ROOT must not
#       exist (STOP with the exact rm); graftling base present in the local graftling repository; the bundle
#       verifies against it and holds GCOMMIT (else STOP with the exact command).
#       Login: none. Dialog: none. Network: none. ~5 s.
#   I   Install. ROOT/venv: graftling GCOMMIT from the bundle as a WHEEL (no network: PyYAML and websockets are
#       copied from <Harness>/.venv-runtime) and the verify615-host wheel. CHECK: version, commit, file location,
#       the graftling.hosts entry point. Login: none. Dialog: none. Network: none. ~30 s.
#   R   Real entry. In ROOT/proj: `ROOT/venv/bin/subagents '{"action":"discover","query":...}'` for
#       "start an agent" (exactly [create]), "list models", "providers", "choose a model" (each includes models);
#       in ROOT (not claimed): authority-denied. Login: none. Dialog: none. Network: none. ~5 s.
#   T   Optional. This Worktree's tests/test_agents_discovery_intents.py with the installed candidate graftling and
#       graphtraj from this Worktree's src, installed editable in ROOT/tvenv (pytest from the conda interpreter's
#       site-packages, click copied from <Harness>/.venv-runtime; no network). pytest temp under TMPDIR (outside the Harness). Login: none. Dialog: none. ~10 s.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR and LANG. No step passes any credential.
# VERIFY615_ROOT / _GCOMMIT are for the Engineer's rehearsal only (a writable ROOT inside the rehearsal sandbox; the
# base commit for the fails-before contrast). No other rehearsal knob exists: every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)     # this Task Worktree
H=${WT:h:h:h:h}                                      # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY615_ROOT:-/private/tmp/graftling-615}
GREPO=$H/graftling                                   # the local graftling repository (read only): holds BASE
BASE=2fdc0d38d8aa25ff22145a8d534911d38cf6bb01        # graftling dev, this Task's base
BRANCH=agent/615-graftling-models-description-intent-match
GCOMMIT=${VERIFY615_GCOMMIT:-3a35334e977d5a9536a42d320e2a3243d3989f6d}  # the graftling candidate (parent BASE)
BUNDLE=$WT/scripts/verify-615/graftling-615.bundle
RTSP=$H/.venv-runtime/lib/python3.13/site-packages
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
THIS=${0:A}
STEP=${1:-}
PYTMP=${TMPDIR:-/tmp}
V=$ROOT/venv
TV=$ROOT/tvenv
PROJ=$ROOT/proj

say() { print -r -- "== $*"; }
is_cred() {  # graftling's is_credential_name, restated
  local name=${(U)1} part
  [[ $name == GIT_CONFIG_KEY_<-> ]] && return 1
  for part in ${(s:_:)name}; do [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && return 0; done
  return 1
}
scrub() {
  local k; local -a removed=()
  for k in ${(k)parameters[(R)*export*]}; do
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAFTLING_CONNECTION ]]; then
      unset $k; removed+=$k
    fi
  done
  print -r -- "scrubbed at start (names only): ${removed:-none}"
}
scrub
APATH=/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables.
allow() {
  /usr/bin/env -i HOME=$HOME USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=$PYTMP LANG=en_US.UTF-8 "$@"
}
stop() { print -r -- "STOP: $*"; exit 1; }
need_venv() { [[ -x $V/bin/subagents && -f $V/installed ]] || stop "$V missing; run: zsh $THIS I"; }
pipq=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)

case $STEP in
00)
  say "[00] Preflight. Login: none. Dialog: none. Network: none."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  [[ -e $ROOT ]] && stop "$ROOT exists; run: rm -rf $ROOT && zsh $THIS 00"
  [[ -x $CONDA ]] || stop "$CONDA missing"
  print -r -- "git: $(git --version) | python: $($CONDA --version 2>&1) | pytest (for T): $($CONDA -c 'import pytest; print(pytest.__version__)' 2>&1)"
  [[ -d $RTSP/yaml && -d $RTSP/websockets && -d $RTSP/click ]] && print -r -- "PASS: PyYAML, websockets and click present in $RTSP" || stop "$RTSP lacks yaml, websockets or click"
  git -C $GREPO cat-file -e "$BASE^{commit}" 2>/dev/null || stop "graftling base $BASE missing; run: git -C $GREPO fetch origin dev && zsh $THIS 00"
  git -C $GREPO bundle verify $BUNDLE > /dev/null 2>&1 || stop "bundle does not verify against $GREPO: git -C $GREPO bundle verify $BUNDLE"
  if [[ $(git bundle list-heads $BUNDLE) == *3a35334e977d5a9536a42d320e2a3243d3989f6d* ]]; then
    print -r -- "next: zsh $THIS I"
    print -r -- "CHECK 615 00: bundle verifies against $GREPO and holds the candidate 3a35334e (branch $BRANCH); ROOT $ROOT absent: PASS"
  else
    stop "bundle head is not 3a35334e; inspect it with: git bundle list-heads $BUNDLE"
  fi
  ;;
I)
  say "[I] Install graftling $GCOMMIT as a wheel and the verify615-host plugin into $V. Login: none. Dialog: none. Network: none."
  [[ -e $V ]] && stop "$V exists; run: rm -rf $ROOT && zsh $THIS 00"
  mkdir -p $ROOT $PROJ
  local S=$ROOT/src
  git clone -q --bare --template= $GREPO $S/repo.git && git --git-dir=$S/repo.git fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" \
    || stop "fetch from the bundle failed"
  mkdir -p $S/graftling $S/wheels $S/host/verify615_host && git --git-dir=$S/repo.git archive $GCOMMIT | tar -x -C $S/graftling \
    || stop "graftling $GCOMMIT not in the bundle or the base repository"
  # The host plugin (PUBLIC_API 1.4): claims only ROOT/proj; its dispatch executes nothing.
  print -r -- "[build-system]
requires = [\"setuptools>=77\"]
build-backend = \"setuptools.build_meta\"

[project]
name = \"verify615-host\"
version = \"0\"

[project.entry-points.\"graftling.hosts\"]
verify615 = \"verify615_host:claim\"" > $S/host/pyproject.toml
  print -r -- "\"\"\"Task 615 verification host: lets the subagents CLI run in one directory; executes nothing.\"\"\"
from pathlib import Path

from graftling.tool import AgentsResult

PROJECT = Path('$PROJ').resolve()


def refuse(request: dict) -> AgentsResult:
    return AgentsResult({'error': {'code': 'operation-failed', 'message': 'verify-615 host executes nothing'}}, failed=True)


def claim(cwd: Path):
    return refuse if Path(cwd).resolve() == PROJECT else None" > $S/host/verify615_host/__init__.py
  $CONDA -m venv $V || stop "venv failed"
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ || stop "copying dependencies failed"
  allow $CONDA -m pip wheel $pipq -w $S/wheels $S/graftling $S/host > /dev/null \
    && allow $V/bin/python -m pip install $pipq $S/wheels/graftling-*.whl $S/wheels/verify615_host-*.whl \
    || stop "building or installing the wheels failed"
  local got=$(cd / && allow $V/bin/python -I -c 'import graftling; print(graftling.__version__, graftling.__file__)')
  local hosts=$(cd / && allow $V/bin/python -I -c 'from importlib.metadata import entry_points; print([e.value for e in entry_points(group="graftling.hosts")])')
  local desc=$(cd / && allow $V/bin/python -I -c 'from graftling.discovery import DESCRIPTIONS; print(DESCRIPTIONS["models"])')
  print -r -- "$GCOMMIT $got" > $V/installed
  print -r -- "wheels: $(cd $S/wheels && print -l -- *.whl | tr '\n' ' ')"
  print -r -- "graftling.hosts entry points: $hosts"
  print -r -- "installed models description: $desc"
  print -r -- "next: zsh $THIS R"
  [[ $got == *$V/* && $hosts == *verify615_host:claim* ]] && print -r -- "CHECK 615 I: graftling $got from $GCOMMIT, host plugin installed: PASS" \
    || print -r -- "CHECK 615 I: graftling $got, hosts $hosts: FAIL"
  ;;
R)
  say "[R] Real entry: the installed subagents CLI ($V/bin/subagents), claimed by verify615-host in $PROJ. Login: none. Dialog: none. Network: none."
  need_venv; print -r -- "installed: $(<$V/installed)"
  local q rc out; local -a lines=()
  for q in 'start an agent' 'list models' 'providers' 'choose a model'; do
    out=$(cd $PROJ && allow $V/bin/subagents "{\"action\":\"discover\",\"query\":\"$q\"}" 2>&1); rc=$?
    print -r -- "\$ (cd $PROJ && $V/bin/subagents '{\"action\":\"discover\",\"query\":\"$q\"}')  -> exit $rc"
    print -r -- "  $out"
    lines+=("$q"$'\t'"$rc"$'\t'"$out")
  done
  out=$(cd $ROOT && allow $V/bin/subagents '{"action":"discover","query":"start an agent"}' 2>&1); rc=$?
  print -r -- "\$ (cd $ROOT && $V/bin/subagents '{\"action\":\"discover\",\"query\":\"start an agent\"}')  -> exit $rc (not claimed)"
  print -r -- "  $out"
  lines+=("UNCLAIMED"$'\t'"$rc"$'\t'"$out")
  print -l -- $lines | $CONDA -I -c 'import json, sys
ok = True
for raw in sys.stdin:
    q, rc, out = raw.rstrip("\n").split("\t", 2)
    try: doc = json.loads(out)
    except ValueError: doc = {}
    feats = [f.get("feature") for f in doc.get("features", [])]
    if q == "UNCLAIMED":
        good = rc == "1" and doc.get("error", {}).get("code") == "authority-denied"
        what = "outside the claimed directory the CLI refuses (authority-denied)"
    elif q == "start an agent":
        good = rc == "0" and feats == ["create"]
        what = f"{q!r} -> {feats} is exactly [create]"
    else:
        good = rc == "0" and "models" in feats
        what = f"{q!r} -> {feats} includes models"
    print("CHECK 615 R:", what + ":", "PASS" if good else "FAIL")
    ok = ok and good
print("next: zsh '"$THIS"' T   (optional), then rm -rf '"$ROOT"' when done")
print("VERDICT 615 R:", "PASS" if ok else "FAIL")'
  ;;
T)
  say "[T] GraphTraj tests/test_agents_discovery_intents.py with the installed graftling ($V) and graphtraj from $WT/src. pytest temp under TMPDIR=$PYTMP (outside the Harness). Login: none. Dialog: none."
  need_venv
  if [[ ! -x $TV/bin/python ]]; then
    $CONDA -m venv --system-site-packages $TV || stop "test venv failed"
    local D=$($TV/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
    cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
      $RTSP/click $RTSP/click-*.dist-info(N) $D/ || stop "copying dependencies failed"
    allow $TV/bin/python -m pip install $pipq $ROOT/src/wheels/graftling-*.whl || stop "installing the wheel into $TV failed"
    # graphtraj: this Worktree editable, as verify-614's g_venv (GraphTraj's conftest needs its entry points).
    # setuptools writes only the git-ignored src/graphtraj.egg-info in the Worktree.
    (cd $WT && allow $TV/bin/python -m pip install $pipq -e $WT > /dev/null) || stop "installing $WT editable into $TV failed"
  fi
  local R=$(mktemp -d $PYTMP/verify615-T.XXXXXX)
  print -r -- "test interpreter: $TV/bin/python | $(cd / && allow $TV/bin/python -I -c 'import importlib.metadata as m, graftling; print(" | ".join(f"{n} {m.version(n)}" for n in ("pytest", "click", "PyYAML", "websockets", "graftling")), "| graftling.__file__", graftling.__file__)')"
  print -r -- "pytest temp root: $R (TMPDIR=$PYTMP, outside the Harness)"
  (cd $WT && allow $TV/bin/python -c 'import graftling, graphtraj; print("imported in the run: graftling", graftling.__file__, "| graphtraj", graphtraj.__file__)' 2>&1) | sed 's/^/  /'
  (cd $WT && /usr/bin/env -i HOME=$HOME USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} TMPDIR=$R LANG=en_US.UTF-8 \
     $TV/bin/python -m pytest -p no:cacheprovider -q -rA tests/test_agents_discovery_intents.py > $ROOT/T.txt 2>&1)
  local rc=$?
  grep -E '^(PASSED|FAILED|ERROR) ' $ROOT/T.txt
  grep -E '^E ' $ROOT/T.txt | head -5
  rm -rf $R
  print -r -- "pytest exit=$rc; full output: $ROOT/T.txt"
  print -r -- "next: rm -rf $ROOT  (when done)"
  local tail1=$(tail -1 $ROOT/T.txt)
  (( rc == 0 )) && print -r -- "VERDICT 615 T: $tail1: PASS" || print -r -- "VERDICT 615 T: $tail1: FAIL"
  ;;
*)
  print -r -- "usage: zsh $THIS 00|I|R|T"; exit 2 ;;
esac
