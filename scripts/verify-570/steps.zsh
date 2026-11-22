#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 570 Main-run steps: graftling-dsh works right after install, without GRAFTLING_DSH_CONFIG, on the
# project's own data root <project>/.agents-control.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre           Main. Versions (zsh, dsh, pnpm, node, python3 + PyYAML/websockets, git, claude); the base commit
#                 on GitHub; DEEPSEEK_API_KEY set (STOP with the fix if not); ~/.dsh's profile list (read only);
#                 creates ROOT (STOP if it exists); a one-line DSH prompt in the isolated home naming its model.
#                 Dialog: none. ~30 s.
#   repro         Main. The premise, on the BASE (dev 00778d1, before 570): install the GitHub root URL pinned to
#                 the base into profile headless of the isolated home ROOT/home-base, then a real headless Session
#                 in ROOT/proj with GRAFTLING_DSH_CONFIG removed. Shows whether mcp__graftling__agents exists,
#                 whether a Python environment was built, whether any data root appeared. Dialog: none. ~2-3 min.
#   repro-control Main. The same base Session WITH GRAFTLING_DSH_CONFIG=ROOT/dsh-host.json (root ROOT/agents-data):
#                 the variable alone makes the difference. If python3 lacks websockets it prints the plugin's
#                 refusal and 'next: ... deps'. Dialog: none. ~1-2 min.
#   deps          Main, only when a step says so. The documented command: pip downloads PyYAML and websockets from
#                 PyPI into each graftling Python environment under ROOT/home*/ that lacks them. Dialog: none. ~30 s.
#   post          Main. ~/.dsh's profile list again, compared with pre's; how to remove ROOT. <5 s.
# Everything is under ROOT=/private/tmp/graftling-570 (isolated DSH homes ROOT/home-base, later ROOT/home);
# ~/.dsh is only listed, never written. Step output is kept in OUT. VERIFY570_ROOT / VERIFY570_OUT /
# VERIFY570_URL are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY570_ROOT:-/private/tmp/graftling-570}
OUT=${VERIFY570_OUT:-$H/.graphtraj/core/state/tasks/570-graftling-dsh-plugin-default-host-config/realhost}
URL=${VERIFY570_URL:-https://github.com/LUOXIAO92/graftling.git}
BASE=00778d17a543f35d49e218de5f9ede061f977dac      # graftling dev before 570 (Task 569's accepted commit)
THIS=${0:A}
STEP=${1:-}
DB=$ROOT/home-base                                  # isolated DSH home holding the base install
path=(/opt/homebrew/bin $path)

say() { print -r -- "== $*"; }
# An isolated DSH: home $1, no explicit Python or host configuration, no inherited agents channel.
iso() { local home=$1; shift
        env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_AGENT_PACKAGE -u GRAFTLING_DSH_CONFIG \
          -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u DEEPSEEK_BASE_URL DSH_HOME=$home "$@" }
profiles() { print -l $HOME/.dsh/profiles/*(N:t) }
bundles() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["dsh"]["profile"]["bundles"])' \
              $1/profiles/$2/package.json 2>&1 }
envs() { print -l $1/graftling-python/*~*.partial~*.lock(N/) }                 # environments under home $1
need_root() { [[ -d $ROOT/proj ]] || { print -r -- "STOP: $ROOT/proj missing; run: zsh $THIS pre"; return 1; } }
# Every .agents-control directory under ROOT (the default data roots), and what ROOT/agents-data holds.
roots() { print -r -- ".agents-control under $ROOT: $(print -l $ROOT/**/.agents-control(N/D) | tr '\n' ' ')"
          print -r -- "$ROOT/agents-data holds: $(cd $ROOT/agents-data 2>/dev/null && print -l **/*(ND) | head -20 | tr '\n' ' ')" }
# Agent records (control/agents/*.json) under directory $1, with each record's runtime and creator.
records() { local f; for f in $1/control/agents/*.json(N); do
              python3 -c 'import json, sys; r = json.load(open(sys.argv[1]))
print(" ", r["agent"], "runtime", r.get("runtime"), "creator", r.get("creator"), "state",
      (r.get("executions") or [{}])[-1].get("state"))' $f 2>&1; done }

install_one() {  # home profile spec: one plugin add; PASS when graftling-dsh is a bundle of the profile
  local home=$1 p=$2 spec=$3 rc log=$ROOT/install-${home:t}-$2.txt
  if [[ $(bundles $home $p) == *graftling-dsh* ]]; then print -r -- "$p in $home already has graftling-dsh"; return 0; fi
  say "DSH_HOME=$home dsh plugin --profile $p add '$spec'"
  (cd $ROOT/proj && iso $home dsh plugin --profile $p add "$spec" < /dev/null) > $log 2>&1; rc=$?
  tail -15 $log
  print -r -- "exit=$rc (full output: $log)"
  print -r -- "ERR_PNPM_IGNORED_BUILDS lines: $(grep -c ERR_PNPM_IGNORED_BUILDS $log)"
  print -r -- "bundles: $(bundles $home $p)"
  print -r -- "dependency saved: $(grep -h graftling $home/profiles/$p/package.json | tr -s ' ')"
  if (( rc == 0 )) && [[ $(bundles $home $p) == *graftling-dsh* ]]; then print -r -- "PASS: $p registered graftling-dsh"
  else print -r -- "FAIL: $p did not register graftling-dsh"; return 1; fi
}

# One real headless Session: home dir prompt [VAR=value...]; sets SRC (exit code) and SOUT (its output file).
session() {
  local home=$1 dir=$2 name=$3 prompt=$4; shift 4
  SOUT=$ROOT/$name-$(date +%H%M%S).txt
  say "headless Session '$name' in $dir, DSH_HOME=$home, ${*:-GRAFTLING_DSH_CONFIG unset}"
  (cd $dir && iso $home "$@" dsh --profile headless "$prompt" < /dev/null) > $SOUT 2>&1; SRC=$?
  tail -40 $SOUT
  print -r -- "exit=$SRC (full output: $SOUT)"
}

# The plugin's Python bootstrap for home $1 (builds nothing once the environment exists).
verdict() {
  local script=$1/profiles/headless/node_modules/graftling-dsh/src/graftling/dsh/plugin_python.py
  [[ -f $script ]] || { print -r -- "no plugin_python.py under $1"; return 0; }
  say "the plugin's bootstrap now: python3 -I $script $1"
  iso $1 python3 -I $script $1
}

TOOLS='First list the names of all tools available to you whose names start with mcp__ (one line, comma separated; write NONE if there are none). Then, if a tool named mcp__graftling__agents exists, call it with action status and report its result in one line; if it does not exist, write exactly: NO AGENTS TOOL.'

evidence() {  # home: what the Session left behind
  local home=$1
  print -r -- "Session output mentions: mcp__graftling__agents $(grep -c 'mcp__graftling__agents' $SOUT) line(s); 'NO AGENTS TOOL' $(grep -c 'NO AGENTS TOOL' $SOUT); graftling-dsh/agents host messages: $(grep -c -i 'graftling\|agents host' $SOUT)"
  print -r -- "files under $home naming mcp__graftling__agents (Session logs): $(grep -rl 'mcp__graftling__agents' $home --exclude-dir=node_modules --exclude-dir=graftling-python 2>/dev/null | wc -l | tr -d ' ')"
  print -r -- "Python environments under $home/graftling-python: $(envs $home | tr '\n' ' ')"
  roots
  print -r -- "log files under $home mentioning graftling: $(grep -rli graftling $home --include='*.log' --exclude-dir=node_modules --exclude-dir=graftling-python 2>/dev/null | tr '\n' ' ')"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight in a fresh $ROOT. Dialog: none. ~30 s."
  print -r -- "zsh: $ZSH_VERSION ($THIS)"
  local t; for t in dsh pnpm node python3 git claude; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  python3 -I -c 'import sys, importlib.metadata as m
print("python3:", sys.executable, sys.version.split()[0])
for n in ("PyYAML", "websockets"):
    try: print(" ", n, m.version(n))
    except Exception: print(" ", n, "missing (a later step will ask for the deps step)")'
  profiles > $OUT/dsh-profiles-before.txt
  print -r -- "~/.dsh profiles (read only, kept in $OUT/dsh-profiles-before.txt): $(print -r -- ${(f)"$(<$OUT/dsh-profiles-before.txt)"})"
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists. Remove it yourself, then rerun: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print -r -- "GitHub refs at the base $BASE: $(git ls-remote $URL | grep $BASE | cut -f2 | tr '\n' ' ')"
  print -r -- "GitHub dev now: $(git ls-remote $URL refs/heads/dev | cut -f1)"
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    print -r -- "STOP: DEEPSEEK_API_KEY is not set. The isolated DSH homes under $ROOT hold no login, and the agents"
    print -r -- "host's DSH child reads DEEPSEEK_API_KEY. Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key> in this shell, then:"
    print -r -- "  zsh $THIS pre"
    return 1
  fi
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  mkdir -p $DB $ROOT/proj/sub $ROOT/agents-data || return 1
  print -r -- "{\"root\": \"$ROOT/agents-data\"}" > $ROOT/dsh-host.json
  print -r -- "created $ROOT: home-base (DSH_HOME of the base), proj and proj/sub (cwd), agents-data, dsh-host.json: $(<$ROOT/dsh-host.json)"
  say "one-line prompt in the isolated home $DB (login: DEEPSEEK_API_KEY)"
  (cd $ROOT/proj && iso $DB dsh --profile headless "Reply in one line with the name of the model you are and nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: DSH could not answer with DEEPSEEK_API_KEY. Check the key and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print "Success: a model name and exit=0; the base commit is listed on GitHub."
  print -r -- "next: zsh $THIS repro"
  ;;
repro)
  say "[repro] Main. Base $BASE installed from GitHub; a real headless Session WITHOUT GRAFTLING_DSH_CONFIG. Dialog: none. ~2-3 min."
  need_root || return 1
  install_one $DB headless "git+$URL#$BASE" || return 1
  print -r -- "--dump-config lines naming agents-host or graftling:"
  (cd $ROOT/proj && iso $DB dsh --profile headless --dump-config 2>&1) | grep -n -i 'agents-host\|graftling' | head
  session $DB $ROOT/proj repro "$TOOLS"
  evidence $DB
  print "What it means: the premise holds when the Session exits 0, its answer says NO AGENTS TOOL (no"
  print "mcp__graftling__agents among its tools), no Python environment was built and no .agents-control or"
  print "agents-data content appeared, although the plugin is registered (dump-config shows agents-host)."
  (( SRC == 0 )) || { print -r -- "FAIL: the Session exited $SRC; see its output above"; return 1; }
  print -r -- "next: zsh $THIS repro-control"
  ;;
repro-control)
  say "[repro-control] Main. The same base Session WITH GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json. Dialog: none. ~1-2 min."
  need_root || return 1
  [[ $(bundles $DB headless) == *graftling-dsh* ]] || { print -r -- "STOP: run zsh $THIS repro first"; return 1; }
  session $DB $ROOT/proj repro-control "$TOOLS" GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json
  local out; out=$(verdict $DB 2>&1); print -r -- $out
  if [[ $out == *lacks* ]]; then
    print "The plugin refused: python3 lacks PyYAML or websockets (the documented case); the Session had no agents tool."
    print -r -- "next: zsh $THIS deps   (then: zsh $THIS repro-control)"
    return 0
  fi
  evidence $DB
  print "What it means: with only GRAFTLING_DSH_CONFIG added, the Session lists mcp__graftling__agents and its"
  print "status answers (no agents yet), and $ROOT/agents-data gains live/ (the host's endpoint directory)."
  (( SRC == 0 )) || { print -r -- "FAIL: the Session exited $SRC; see its output above"; return 1; }
  print -r -- "next: zsh $THIS post   (later candidate steps are added to this file by the Engineer)"
  ;;
deps)
  say "[deps] Main. The documented dependency command (pip downloads from PyPI into the environment). Dialog: none. ~30 s."
  need_root || return 1
  local e found=0
  for e in $ROOT/home*/graftling-python/*~*.partial~*.lock(N/); do
    found=1
    if $e/bin/python -I -c 'import yaml, websockets' 2>/dev/null; then print -r -- "$e: has both"; continue; fi
    print -r -- "running: '$e/bin/python' -m ensurepip && '$e/bin/python' -m pip install 'PyYAML>=6,<7' 'websockets>=15,<17'"
    $e/bin/python -m ensurepip && $e/bin/python -m pip install 'PyYAML>=6,<7' 'websockets>=15,<17' || return 1
  done
  (( found )) || { print -r -- "STOP: no environment under $ROOT/home*/graftling-python; run the step that asked for deps first"; return 1; }
  local h; for h in $ROOT/home*(N/); do verdict $h; done
  print "Success: each bootstrap above prints its environment's bin/python."
  print -r -- "next: rerun the step that asked for deps (zsh $THIS repro-control, or the step it named)"
  ;;
post)
  say "[post] Main. ~/.dsh untouched? <5 s."
  profiles > $OUT/dsh-profiles-after.txt
  diff $OUT/dsh-profiles-before.txt $OUT/dsh-profiles-after.txt && print "PASS: ~/.dsh profile list unchanged" || print "FAIL: ~/.dsh profile list changed"
  print -r -- "To remove the isolated run when you no longer need it: rm -rf $ROOT"
  print -r -- "next: report $OUT to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|repro|repro-control|deps|post"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY570_OUT:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
