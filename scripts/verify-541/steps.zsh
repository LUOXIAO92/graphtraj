#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 541 — in a project with NO local Task, Main's completion check starts no checker/model and shows no error.
# Real host: the user's interactive Codex (gpt-6-luna) in an ISOLATED project with the candidate's own hooks.
#   zsh scripts/verify-541/steps.zsh <step>          (Main's Bash, from this Task's Worktree)
# Order: 00 -> T [USER: folder trust only] -> U [USER: one turn + screenshot] -> R ;  G (background) -> GR
#   00  Main. Versions; candidate venv (Worktree HEAD + graftling dev $GLC, scratch, under BASE); isolated project with
#       no Task; codex exec one-line answer (model + login). Dialog: none.
#   T   USER. Trust the isolated folder only, /exit. Dialog: exactly 1 (Codex folder trust -> Yes). Skip if trusted.
#   U   Main writes the project's own .codex/hooks.json (the product's finalize.hook() material on the candidate
#       python) and stamps the start; then USER runs one interactive turn. Dialog: exactly 1 (Codex hook review of
#       the new hooks.json -> approve; none if already approved for these exact hooks).
#   R   Main. Read only: continuity claim, binding/check records, task graph, Main rollout. Dialog: none.
#   G   Main. GraphTraj full suite of the Worktree HEAD (6 shards, background ~25 min). Dialog: none.
#   GR  Main. Read only: G result; every FAILED/ERROR line classed known (516 list, baseline 547 G) or NEW. Dialog: none.
# Never written: ~/.codex, the Codex install, dotfiles, .venv-runtime, the Harness's .codex. BASE and the project's
# own .codex only. VERIFY541_* overrides are for rehearse.zsh only; the defaults are the real paths.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY541_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY541_H:-${WT:h:h:h:h}}                       # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
BASE=${VERIFY541_BASE:-$H/tmp/541}                    # scratch venvs and wheels
W=${VERIFY541_W:-$H/.graphtraj/core/state/tasks/541-finish-check-reviewer-without-task/realhost}   # step output
VPROJECT=${VERIFY541_VPROJECT:-/private/tmp/vproject-541}
GL=${VERIFY541_GL:-$H/graftling}
GLC=6794ce02b6210ec88837437affb8d7b525612804           # graftling dev
RT=${VERIFY541_RT:-$H/.venv-runtime}/lib/python3.13/site-packages   # production: click/yaml/websockets copied out
CODEX_HOME_USED=${VERIFY541_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}  # only read (R reads rollouts)
CONDA=$HOME/miniconda3/bin/python3.13
CODEX_MODEL=gpt-6-luna
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
BASELINE=$H/.graphtraj/core/state/tasks/547-backup-cross-repository-sub-issues/realhost/G-22946e4c-20261121T155123/suite.txt
V=$BASE/venv-cand
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say()  { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
codex_bin() { [[ -n ${VERIFY541_CODEX:-} ]] && { print -r -- $VERIFY541_CODEX; return; }; command -v codex; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
bounded() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
check_tmp() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  print -r -- "pytest temp: TMPDIR=${PYTEST_TMP:A} (outside the Harness)"
}

# Candidate venv: conda --system-site-packages + production deps + graftling wheel (git archive $GLC) + the
# Worktree HEAD as a wheel (git archive, never the working tree). Used by the project hooks and by G.
build() {
  local head=$(git -C $WT rev-parse HEAD) dirty=$(git -C $WT status --porcelain -- src tests plugins pyproject.toml)
  [[ -z $dirty ]] || { print "STOP: uncommitted product changes in $WT: $dirty"; return 1; }
  if [[ -f $V/installed && $(<$V/installed) == "$head $GLC" ]]; then print "reusing $V ($head + graftling $GLC)"; return 0; fi
  git -C $GL cat-file -e $GLC^{commit} || { print "STOP: graftling $GLC is not in $GL"; return 1; }
  rm -rf $V $BASE/src-gt $BASE/src-gl $BASE/wheels; mkdir -p $BASE/src-gt $BASE/src-gl $BASE/wheels
  git -C $GL archive $GLC | tar -x -C $BASE/src-gl && git -C $WT archive $head | tar -x -C $BASE/src-gt || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $BASE/wheels $BASE/src-gl/src/graftling $BASE/src-gt > /dev/null || return 1
  (cd $BASE/wheels && shasum -a 256 *.whl)
  $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $BASE/wheels/*.whl || return 1
  print -r -- "$head $GLC" > $V/installed
}
imports() { (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)'); }
isolation() {  # graphtraj root and git top level are the project; no AGENTS.md/CLAUDE.md at or above; no Task
  (cd $VPROJECT && $V/bin/python -I - $VPROJECT <<'ISO'
import subprocess, sys
from pathlib import Path
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.task_index import read_index
from graphtraj.workspace.runner_project import discover_project_root
project = Path(sys.argv[1]).resolve()
root = discover_project_root(project)
top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
upward = [str(p / n) for p in (project, *project.parents) for n in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md') if (p / n).exists()]
tasks = read_index(load_project_configuration(project).state)['tasks']
print(f'graphtraj project root: {root} | git top level: {top} | AGENTS.md/CLAUDE.md at or above: {upward or "none"} | local Tasks: {sorted(tasks) or "none"}')
ok = root == project and bool(top) and Path(top).resolve() == project and not upward and not tasks
print('isolation and empty task graph:', 'OK' if ok else 'NOT OK')
sys.exit(0 if ok else 1)
ISO
  )
}

step_00() {
  say "versions (dialog: none)"
  local C=$(codex_bin)
  print -r -- "zsh $ZSH_VERSION ($THIS) | Worktree $WT at $(git -C $WT rev-parse HEAD) | codex: $C -> ${C:A} | $($C --version 2>&1 | head -1)"
  check_tmp || return 1
  say "candidate venv $V: Worktree HEAD + graftling $GLC (scratch; .venv-runtime only read)"
  build && imports || { print "STOP: candidate venv not built (above)"; return 1; }
  say "isolated project $VPROJECT (own git, own .graphtraj by the candidate's graphtraj setup; no Task)"
  case ${VPROJECT:A}/ in ${H:A}/*) print "STOP: $VPROJECT is inside the Harness"; return 1 ;; esac
  mkdir -p $VPROJECT
  if [[ ! -d $VPROJECT/.git ]]; then
    (cd $VPROJECT && git init -q -b main && print -r -- "# 541 scratch project" > README.md && git add README.md \
      && git -c user.name=541 -c user.email=541@invalid commit -qm "Initial source") || return 1
  fi
  [[ -f $VPROJECT/.graphtraj/config.yml ]] || (cd $VPROJECT && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  isolation || { print "STOP: the project is not isolated or has a Task (above)"; return 1; }
  say "codex exec one-line answer from the project (expect model $CODEX_MODEL, logged in; limit 300 s; dialog: none)"
  print "codex login: $(clean $C login status 2>&1 | sed -E 's/ - .*//' | head -1)"
  print -r -- "Reply with exactly one line: CODEX-541-OK followed by your model name. Use no tool." > $W/00-prompt.txt
  (cd $VPROJECT && bounded 300 $C exec -m $CODEX_MODEL --sandbox read-only - < $W/00-prompt.txt > $W/00-codex.txt 2>&1)
  print "codex exec rc=$? (142 = 300 s limit) | header model: $(grep -m1 -E '^model: ' $W/00-codex.txt | cut -c8-) | answer: $(grep -E '^CODEX-541-OK' $W/00-codex.txt | tail -1)"
  grep -qE '^CODEX-541-OK' $W/00-codex.txt && grep -qE "^model: $CODEX_MODEL" $W/00-codex.txt \
    || { tail -5 $W/00-codex.txt; print "STOP: answer check failed. Login problem: USER runs 'codex login' in Terminal, then rerun 00."; return 1; }
  next "zsh $THIS T    (USER: folder trust only; skip T if Codex already trusts $VPROJECT)"
}

step_T() {
  [[ -d $VPROJECT/.git ]] || { print "no $VPROJECT: run 00 first"; return 1; }
  say "USER (real interactive Codex; folder trust only, no prompt)"
  print -r -- "1) In a plain Terminal (one line):   cd $VPROJECT && codex -m $CODEX_MODEL"
  print "2) Expected dialog (exactly one, Codex's own): 'Do you trust the contents of this directory?' -> Yes."
  print "   Any other dialog: Esc, and tell Main its title. Codex records the choice itself; this script writes nothing there."
  print "3) Type no prompt; enter /exit."
  next "zsh $THIS U    (after the USER finished T)"
}

step_U() {
  [[ -f $V/installed ]] || { print "no candidate venv: run 00 first"; return 1; }
  isolation || { print "STOP: the project is not isolated or has a Task (above)"; return 1; }
  say "project's own .codex/hooks.json = the product's finalize.hook() material on $V/bin/python (dialog: none)"
  mkdir -p $VPROJECT/.codex
  (cd $VPROJECT && $V/bin/python -I -c 'import json, sys
from pathlib import Path
from graphtraj.runtimes.codex.finalize import hook
Path(sys.argv[1]).write_text(json.dumps(hook(Path("unused"), {}), indent=2) + "\n", encoding="utf-8")' $VPROJECT/.codex/hooks.json) || return 1
  sed 's/^/    /' $VPROJECT/.codex/hooks.json
  local MS=$VPROJECT/.graphtraj/runner/main-sessions
  if [[ -d $MS ]]; then print "removing the project's earlier Main records $MS (only this scratch project)"; rm -rf $MS || return 1; fi
  date +%s > $W/U.start
  print -r -- "Reply with exactly one line: HELLO-541. Use no tool." > $W/U-prompt.txt
  say "USER (real interactive Codex) — one turn, one screenshot"
  print -r -- "1) In a plain Terminal (one line, no -c options):   cd $VPROJECT && codex -m $CODEX_MODEL"
  print -r -- "2) Expected dialog (exactly one, Codex's own): review of the hooks in $VPROJECT/.codex/hooks.json -> approve."
  print "   If no dialog appears, the same hooks were approved before: fine. Any other dialog: Esc, tell Main its title."
  print -r -- "3) Type this prompt and press Enter:   $(<$W/U-prompt.txt)"
  print "4) When the turn ends, screenshot the whole turn end. PASS = a 'Completion Check · completed' message saying the"
  print "   project has no local Task and no checker ran; NO 'Reviewer Usage' line; NO red 'Hook stopped' or error."
  print -r -- "   Save it as $W/after-541.png, then enter /exit."
  next "zsh $THIS R    (after the USER's screenshot and /exit)"
}

step_R() {
  [[ -f $W/U.start ]] || { print "no U stamp: run U first"; return 1; }
  say "session records since $(<$W/U.start) (read only; rollouts under $CODEX_HOME_USED/sessions; dialog: none)"
  $CONDA -I $SD/rc541.py $CODEX_HOME_USED/sessions $VPROJECT $(<$W/U.start)
  local rc=$?
  (( rc == 0 )) && next "zsh $THIS G    (if not yet run; then zsh $THIS GR)"
  return $rc
}

step_G() {
  say "GraphTraj suite of the Worktree HEAD against graftling $GLC (dialog: none)"
  check_tmp || return 1
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later"; print -r -- $others; return 1; }
  local head=$(git -C $WT rev-parse HEAD) dirty=$(git -C $WT status --porcelain -- src tests plugins)
  [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  local G=$BASE/venv-g
  if [[ ! -f $G/installed || $(<$G/installed) != $GLC ]]; then
    rm -rf $G $BASE/src-gl-g $BASE/wheels-gl; mkdir -p $BASE/src-gl-g $BASE/wheels-gl
    git -C $GL archive $GLC | tar -x -C $BASE/src-gl-g || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $BASE/wheels-gl $BASE/src-gl-g/src/graftling > /dev/null || return 1
    $CONDA -m venv --system-site-packages $G && copy_deps $G || return 1
    $G/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $BASE/wheels-gl/*.whl || return 1
    $G/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache
    print -r -- $GLC > $G/installed
  else print "reusing $G (graftling $GLC; this Worktree editable)"; fi
  local RUNTMP=${PYTEST_TMP:A}/verify-541-G-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
  local R=$W/G-${head[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root (TMPDIR of the run, outside the Harness): $RUNTMP"
    print -r -- "candidate: $head | graftling $GLC"
    (cd $RUNTMP && $G/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)'); } | tee $R/run.txt
  if [[ -n ${VERIFY541_TESTS:-} ]]; then
    print -r -- "REHEARSAL: tests limited to $VERIFY541_TESTS (plain pytest, foreground; same venv, temp root, exit line)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $G/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY541_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  else
    # No nohup: without a console it fails ("can't detach"); &! already disowns the job.
    (cd $WT && TMPDIR=$RUNTMP $G/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
    print -r -- "started in the background at $(date +%T) (~25 min); $R/suite.txt ends with 'exit=N'"
  fi
  print -r -- $R > $W/G-latest
  next "zsh $THIS GR    (when $R/suite.txt ends with exit=)"
}

classify() {  # FAILED/ERROR lines of files $@: known (baseline 547 G on dev 22946e4c, or the 516 list) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $BASELINE 2>/dev/null; then print -r -- "known (547 baseline G): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

step_GR() {
  local R=$(cat $W/G-latest 2>/dev/null)
  [[ -n $R && -f $R/suite.txt ]] || { print -r -- "no G result yet: zsh $THIS G"; return 0; }
  say "G $R (read only; dialog: none)"
  cat $R/run.txt; tail -4 $R/suite.txt
  grep -q '^exit=' $R/suite.txt || print "G still running (no exit= line yet)"
  print -r -- "baseline: $BASELINE ($(tail -1 $BASELINE 2>/dev/null)) | 516 list: $KNOWN516"
  classify $R/suite.txt $R/shards/*(N.)
  print "Success: 'exit=0', or only 'known' lines; no 'NEW' line."
}

[[ -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $W $BASE
local OUT=$W/$STEP.txt
case $STEP in
  00|T|U|R|G|GR) [[ -f $OUT ]] && mv $OUT $W/$STEP-$(date -r $OUT +%Y%m%dT%H%M%S).txt
                 step_$STEP 2>&1 | tee $OUT; local rc=${pipestatus[1]}
                 print -r -- "(output kept in $OUT; rc=$rc)"; return $rc ;;
  *) print "usage: zsh $THIS 00|T|U|R|G|GR   (order: 00 -> T (USER trust) -> U (USER turn) -> R; G -> GR)"; return 2 ;;
esac
