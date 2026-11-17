#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 501 Main-run steps. Run one step at a time:  zsh <this file> <STEP>
#   0  preflight: claude --version, quiet host, scratch venv BEFORE (78279964 + graftling 0.5.2 copied from
#      production, plus the prof501 stack sampler), isolated project, probe Task ready, one-line claude -p answer
#   P  BEFORE profiled run: a Runner-dispatched Claude member creates an agents child holding six sleeps ~2.5 min,
#      waits, reads it back; its Worker's ps every ~10 s, per-phase CPU, CHECK 468 window, the Worker's stacks (<10 min)
#   A  AFTER: the same with AFTER (VERIFY501_AFTER commit, default the Worktree HEAD; graftling from
#      <Harness>/tmp/501/graftling-after when that exists, else 0.5.2), then BEFORE vs AFTER
#   B  498 per-sample cost: DescendantSampler.sample() with six marked sleeps, pre-498 (2da634af) / 498 (871aaaa9) /
#      0.5.2 (<1 min)
#   G  GraphTraj full suite of the Worktree HEAD (background), graftling wheel from <Harness>/graftling
#   R  results of the newest G
#   U  USER, only if P or A reports a folder-trust or login refusal (waits for the user)
# Dialog: none in every Main step. No production install: .venv-runtime is only read (graftling 0.5.2, click, yaml,
# websockets copied out). Test directories only under <Harness>/tmp/501. No step signals a process it did not start.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=$H/tmp/501
OUT=$H/.graphtraj/core/state/tasks/501-runner-worker-cpu-bursts/realhost
G=$H/graftling
SD=${0:A:h}
THIS=${0:A}
BEFORE_COMMIT=78279964
AFTER_COMMIT=${VERIFY501_AFTER:-$(git -C $WT rev-parse --short HEAD)}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
MODEL=claude-opus-5-5
F477=tests/test_wait_handover_477.py
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$PYTEST_TMP LANG=${LANG:-en_US.UTF-8} "$@"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: $PYTEST_TMP (outside the Harness)"
}
quiet() {  # measurements and suites run on a quiet host, one Main step at a time
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS $STEP"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
venv() { print -r -- $T/venv-$1; }
project() { print -r -- $T/project-$1; }
probe() { local L=$1; shift; (cd $(project $L) && clean $(venv $L)/bin/python -I $SD/probe.py "$@") }
claude_version() { print -r -- "claude --version: $(claude --version 2>&1 | head -1) ($(command -v claude || print none))"; }

build() {  # $1 label, $2 commit, $3 graftling package directory to copy
  local S=$T/src-$1 V=$(venv $1) P=$(project $1)
  say "$1: scratch venv from $2 + graftling from $3 + prof501 (writes $T/prof-$1)"
  git -C $WT cat-file -e $2^{commit} || { print "STOP: $2 is not in $WT"; return 1; }
  rm -rf $S $V $T/prof-$1; mkdir -p $S; git -C $WT archive $2 | tar -x -C $S || return 1
  [[ -e $S/src/graftling ]] && { print "STOP: $2 still has src/graftling"; return 1; }
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $3 $D/graftling && cp -Rp $RT/graftling-0.5.2.dist-info $D/ || return 1
  copy_deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S 2>&1 | grep -vi cache
  sed "s|@OUT@|$T/prof-$1|" $SD/prof501.py > $D/prof501.py && print 'import prof501' > $D/prof501.pth || return 1
  (cd $PYTEST_TMP && $V/bin/python -I $SD/probe.py imports $S -) || { print "STOP: the $1 venv does not import $S"; return 1; }
  say "$1: isolated project $P (own git, own .graphtraj; Claude settings without the Harness instruction files)"
  rm -rf $P; mkdir -p $P
  $V/bin/python -I -c 'import json, sys
from pathlib import Path
harness = sys.argv[1]
for path in map(Path, sys.argv[2:]):
    settings = json.loads(path.read_text()) if path.is_file() else {}
    settings["claudeMdExcludes"] = sorted({*settings.get("claudeMdExcludes", []), harness + "/CLAUDE.md",
        harness + "/CLAUDE.local.md", harness + "/.claude/CLAUDE.md", harness + "/**/CLAUDE.md", harness + "/**/CLAUDE.local.md",
        harness + "/AGENTS.md", harness + "/**/AGENTS.md"})
    settings["enabledPlugins"] = {**settings.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")' $H $P/.claude/settings.json $P/.claude/settings.local.json || return 1
  (cd $P && git init -q -b main && print -r -- "# 501 probe" > README.md && git add README.md .claude/settings.json \
      && git -c user.name=501 -c user.email=501@invalid commit -qm "Initial source with Claude settings") || return 1
  (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  probe $1 prepare $P $MODEL || { print "STOP: the $1 probe Task is not ready (above)"; return 1; }
  probe $1 isolation $P - || { print "STOP: the $1 project is not isolated"; return 1; }
}

member() {  # $1 label
  local F=$OUT/$1-facts.json
  mkdir -p $OUT
  $(venv $1)/bin/python -I -c 'import json, sys; json.dump({"label": sys.argv[2], "out": sys.argv[3], "prof": sys.argv[4]}, open(sys.argv[1], "w"))' \
      $F ${(U)1} $OUT/$1.json $T/prof-$1 || return 1
  probe $1 run $(project $1) $F
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT
case $STEP in
0)
  { say "[0] preflight. Dialog: none. Output also in $OUT/0.txt"
  claude_version; print "zsh: $ZSH_VERSION ($THIS)"
  print "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | BEFORE $BEFORE_COMMIT | AFTER $AFTER_COMMIT"
  check_tmp && quiet || return 1
  build before $BEFORE_COMMIT $RT/graftling || return 1
  say "host answers one line with $MODEL in the BEFORE project (model and login source name from the init record)"
  (cd $(project before) && clean claude -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config \
      --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' \
      > $OUT/0-model.jsonl 2> $OUT/0-model-stderr.txt)
  print "claude -p rc=$?"
  probe before init $OUT/0-model.jsonl $H || { print "STOP: no MODEL OK or no init record (above). stderr:"
      head -c 300 $OUT/0-model-stderr.txt; print "\nIf it names a login or folder trust: USER step: zsh $THIS U"; return 1; }
  print "Success: 'under ...: True', 'graftling: ... 0.5.2', 'profiler hook prof501: ...', 'roles OK', 'probe Task ready: YES',"
  print "'isolation: OK', 'init: ... model $MODEL | apiKeySource <name>', 'result: MODEL OK | MEMORY: NONE'."
  print -r -- "next: zsh $THIS P 2>&1 | tee $OUT/P.txt"
  } 2>&1 | tee $OUT/0.txt
  ;;
P|A)
  local L=before
  if [[ $STEP == A ]]; then
    L=after
    local GA=$T/graftling-after; [[ -d $GA ]] || GA=$RT/graftling
    say "[A] AFTER ($AFTER_COMMIT, graftling from $GA). Dialog: none (U if refused). <10 min."
    quiet || return 1
    [[ -f $OUT/before.json ]] || { print -r -- "STOP: run P first"; return 1; }
    build after $AFTER_COMMIT $GA || return 1
  else
    say "[P] BEFORE ($BEFORE_COMMIT + graftling 0.5.2), profiled. Dialog: none (U if refused). <10 min."
    quiet || return 1
    [[ -x $(venv before)/bin/agent-runner ]] || { print -r -- "STOP: run 0 first"; return 1; }
  fi
  claude_version
  member $L; local rc=$?
  (( rc == 2 )) && { print -r -- "rerun 0 (and then this step) for a fresh project"; return $rc; }
  if [[ $STEP == A ]]; then
    probe after compare $OUT/before.json $OUT/after.json
  fi
  print "Success: raw ps lines with child_running, 'phase start/child/after' lines, 'CHECK 468 window', the profile windows"
  print "and the top working stacks per phase. If the member was refused (trust/login): USER step zsh $THIS U."
  print -r -- "next: zsh $THIS B 2>&1 | tee $OUT/B.txt   (then report $OUT/${L}.json and ${STEP}.txt to the Leader)"
  ;;
B)
  say "[B] 498 per-sample cost on this host (six marked sleeps this step starts and stops). Dialog: none. <1 min."
  quiet || return 1
  local W=$T/bench; rm -rf $W; mkdir -p $W/g497 $W/g499 $W/g052
  git -C $WT archive 2da634af src/graftling | tar -x -C $W/g497 && git -C $WT archive 871aaaa9 src/graftling | tar -x -C $W/g499 \
    && cp -Rp $RT/graftling $W/g052/ || return 1
  for spec in "g497/src pre498-2da634af" "g499/src 498-871aaaa9" "g052 0.5.2-production"; do
    local parts=(${=spec})
    (cd $PYTEST_TMP && clean $H/.venv-runtime/bin/python -I $SD/bench498.py $W/$parts[1] $parts[2] 60)
  done
  print -r -- "next: report this output to the Leader; full suite on an idle host: zsh $THIS G"
  ;;
G)
  say "[G] GraphTraj full suite of the Worktree HEAD, graftling as a wheel from $G (6 shards, --timeout 1500, -rA, background). Dialog: none. Returns at once."
  check_tmp && quiet || return 1
  [[ -d $G/src/graftling ]] || { print "STOP: $G/src/graftling missing"; return 1; }
  print "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  git -C $WT diff --quiet HEAD -- || { print "STOP: tracked changes in $WT are uncommitted"; return 1; }
  local C=$(git -C $WT rev-parse --short HEAD)
  local V=$T/venv-gt-$C N=$T/wheels-gt-$C R=$OUT/G-$C-$(date +%H%M%S)
  if [[ -x $V/bin/python ]]; then
    print "reusing $V (made for $C)"
  else
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $G/src/graftling >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      $N/graftling-*.whl -e $WT 2>&1 | grep -vi cache
  fi
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $R
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print -r -- "next, when it ends: zsh $THIS R"
  ;;
R)
  say "[R] results. Dialog: none."
  local g=($OUT/G-*(N/om[1]))
  (( $#g )) || { print -r -- "no G result under $OUT yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- $g"
  [[ -f $g/suite.txt ]] || { print -r -- "(no suite.txt yet)"; return 0; }
  tail -8 $g/suite.txt
  print "failed/error lines:"
  grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sort -u || print "(none)"
  local lines=$(grep -h -F "$F477::" $g/suite.txt $g/shards/*(N.) 2>/dev/null | grep -E '^(PASSED|FAILED|ERROR|SKIPPED) ' | sort -u || true)
  print -r -- "$F477 result lines: $(print -r -- $lines | grep -c . || true), failed or error: $(print -r -- $lines | grep -c -E '^(FAILED|ERROR) ' || true)"
  print -r -- "next: report $g to the Leader"
  ;;
U)
  say "[U] USER, only if P or A reported a folder-trust or login refusal. Plain macOS Terminal:"
  claude_version
  print -r -- "  cd $(project before) && claude      (for A: $(project after))"
  print "Dialog: 'Do you trust the files in this folder?' naming that project: choose 'Yes, proceed', then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message."
  print -r -- "next (Main): the refused step again (zsh $THIS P or A)"
  ;;
*) print -r -- "usage: zsh $THIS 0|P|A|B|G|R|U" ; return 2 ;;
esac
