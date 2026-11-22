#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 569 Main-run steps: graftling-dsh installed from its GitHub address (the repository root's package.json)
# registers in DSH and builds its own Python environment on the first Session start.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   push    Main, only when pre says the branch is not on GitHub. Pushes the candidate from the bundle the Engineer
#           left in .scratch/569 (their sandbox had no GitHub credentials). Dialog: none expected; git uses your
#           usual GitHub login (if it asks, answer with that login). ~30 s.
#   pre     Main. Versions (zsh, dsh, pnpm, node, python3 and its PyYAML/websockets); the candidate commit is the
#           clone's HEAD and is on GitHub; DEEPSEEK_API_KEY is set (an isolated DSH_HOME has no login; STOP with
#           the fix if not); ~/.dsh's profile list (read only); creates ROOT (STOP if it exists); a one-line DSH
#           prompt in the isolated home naming its model. Dialog: none. ~30 s.
#   install Main. Profile headless <- git+https://github.com/LUOXIAO92/graftling.git#<commit> (no path); profile
#           sub569 <- the same with &path:/src/graftling/dsh. Exit codes, bundles, --dump-config agents-host, no
#           ERR_PNPM_IGNORED_BUILDS, what landed in node_modules. Dialog: none. ~1-2 min.
#   start   Main. No GRAFTLING_PYTHON; GRAFTLING_DSH_CONFIG under ROOT. A real headless Session uses the agents tool
#           (not DSH subagents) to create one DSH child that answers one word, waits, and reads its status. Shows
#           the environment built under ROOT/home. If python3 lacks PyYAML or websockets, it prints the plugin's
#           refusal and 'next: ... deps'. Dialog: none. ~1-3 min.
#   deps    Main, only when start says so. Runs the documented command: pip downloads PyYAML and websockets from
#           PyPI into the environment under ROOT/home (nothing else changes). Dialog: none. ~30 s. Then start again.
#   again   Main. A second Session: the environment is reused, not rebuilt; its agents tool answers. ~1 min.
#   local   Main. Profile local569 <- the installed graftling/dsh directory inside that environment (the local
#           directory form). Exit code, bundles, --dump-config. Dialog: none. ~30 s.
#   post    Main. ~/.dsh's profile list again, compared with pre's; how to remove ROOT. <5 s.
# Everything is under ROOT=/private/tmp/graftling-569 with DSH_HOME=ROOT/home; ~/.dsh is only listed. Step output
# is kept in OUT. VERIFY569_ROOT / VERIFY569_OUT / VERIFY569_URL are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY569_ROOT:-/private/tmp/graftling-569}
OUT=${VERIFY569_OUT:-$H/.graphtraj/core/state/tasks/569-graftling-dsh-plugin-install-from-github-url/realhost}
URL=${VERIFY569_URL:-https://github.com/LUOXIAO92/graftling.git}
BRANCH=agent/569-graftling-dsh-plugin-install-from-github-url
GCOMMIT=00778d17a543f35d49e218de5f9ede061f977dac   # the graftling candidate (base: dev 305bfcf)
CLONE=$WT/.scratch/569/graftling                   # the Engineer's clone (its git directory may be gone)
BUNDLE=$WT/.scratch/569/graftling-569.bundle        # the candidate branch, from 305bfcf
THIS=${0:A}
STEP=${1:-}
DH=$ROOT/home
path=(/opt/homebrew/bin $path)

say() { print -r -- "== $*"; }
# The isolated DSH: its own home, no explicit Python, no inherited agents channel or endpoint override.
iso() { env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_AGENT_PACKAGE -u GRAFTLING_DSH_CONFIG \
          -u DEEPSEEK_BASE_URL DSH_HOME=$DH "$@" }
profiles() { print -l $HOME/.dsh/profiles/*(N:t) }
bundles() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["dsh"]["profile"]["bundles"])' \
              $DH/profiles/$1/package.json 2>&1 }
# Environments built under the isolated home (not .partial, not .lock).
envs() { print -l $DH/graftling-python/*~*.partial~*.lock(N/) }
need_root() { [[ -d $DH ]] || { print -r -- "STOP: $DH missing; run: zsh $THIS pre"; return 1; } }

install_one() {  # profile spec
  local p=$1 spec=$2 rc
  say "dsh plugin --profile $p add '$spec'"
  (cd $ROOT/proj && iso dsh plugin --profile $p add "$spec" < /dev/null) > $ROOT/install-$p.txt 2>&1; rc=$?
  cat $ROOT/install-$p.txt
  print -r -- "exit=$rc"
  print -r -- "ERR_PNPM_IGNORED_BUILDS lines: $(grep -c ERR_PNPM_IGNORED_BUILDS $ROOT/install-$p.txt)"
  print -r -- "bundles: $(bundles $p)"
  print -r -- "dependency saved: $(grep -h graftling $DH/profiles/$p/package.json | tr -s ' ')"
  print -r -- "--dump-config lines naming agents-host or graftling:"
  (cd $ROOT/proj && iso dsh --profile $p --dump-config 2>&1) | grep -n -i 'agents-host\|graftling' | head
  local ok=0
  (( rc == 0 )) && [[ $(bundles $p) == *graftling-dsh* ]] && \
    ! grep -q ERR_PNPM_IGNORED_BUILDS $ROOT/install-$p.txt && ok=1
  (( ok )) && print -r -- "PASS: $p registered graftling-dsh" || print -r -- "FAIL: $p did not register graftling-dsh"
  return $(( 1 - ok ))
}

session() {  # name prompt: one real headless Session without GRAFTLING_PYTHON; sets SRC to its exit code
  local name=$1 prompt=$2
  say "headless Session '$name' (GRAFTLING_PYTHON unset, GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json)"
  (cd $ROOT/proj && iso GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json dsh --profile headless "$prompt" < /dev/null) \
    > $ROOT/$name.txt 2>&1; SRC=$?
  tail -60 $ROOT/$name.txt
  print -r -- "exit=$SRC (full output: $ROOT/$name.txt)"
}

verdict() {  # what the plugin's own bootstrap says now (it builds nothing new once the environment exists)
  local script=$DH/profiles/headless/node_modules/graftling-dsh/src/graftling/dsh/plugin_python.py
  say "the plugin's bootstrap now: python3 -I $script $DH"
  iso python3 -I $script $DH
}

run_step() {
case $STEP in
push)
  say "[push] Main. Push $BRANCH ($GCOMMIT) to $URL from $BUNDLE. Dialog: none expected. ~30 s."
  local P=${TMPDIR:-/tmp}/graftling-569-push.git
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { print "already on GitHub"; print -r -- "next: zsh $THIS pre"; return 0; }
  [[ -f $BUNDLE ]] || { print -r -- "STOP: $BUNDLE missing; ask the Engineer"; return 1; }
  rm -rf $P && git clone -q --bare $URL $P || return 1                 # has 305bfcf, the bundle's base
  git -C $P fetch -q $BUNDLE "${BRANCH}:${BRANCH}" || return 1
  [[ $(git -C $P rev-parse $BRANCH) == $GCOMMIT ]] || { print "STOP: the bundle's branch is not $GCOMMIT"; return 1; }
  print -r -- "authors: $(git -C $P log --format='%an <%ae>' 305bfcf902d3b2391f77371a646b9c58ef2e7cdb..$BRANCH | sort -u)"
  git -C $P push $URL "${BRANCH}:refs/heads/${BRANCH}" || return 1
  print -r -- "on GitHub now: $(git ls-remote $URL refs/heads/$BRANCH)"
  rm -rf $P
  print -r -- "next: zsh $THIS pre"
  ;;
pre)
  say "[pre] Main. Preflight in a fresh $ROOT. Dialog: none. ~30 s."
  print -r -- "zsh: $ZSH_VERSION ($THIS)"
  local t; for t in dsh pnpm node python3 git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  python3 -I -c 'import sys, importlib.metadata as m
print("python3:", sys.executable, sys.version.split()[0])
for n in ("PyYAML", "websockets"):
    try: print(" ", n, m.version(n))
    except Exception: print(" ", n, "missing (start will ask for the deps step)")'
  profiles > $OUT/dsh-profiles-before.txt
  print -r -- "~/.dsh profiles (read only, kept in $OUT/dsh-profiles-before.txt): $(print -r -- ${(f)"$(<$OUT/dsh-profiles-before.txt)"})"
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists. Remove it yourself, then rerun: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  local head=$(git -C $CLONE rev-parse HEAD 2>/dev/null) heads=$(git bundle list-heads $BUNDLE 2>/dev/null)
  print -r -- "clone HEAD: ${head:-unreadable} | bundle: ${heads:-unreadable}"
  [[ $head == $GCOMMIT || ( -z $head && $heads == $GCOMMIT* ) ]] || { print -r -- "STOP: the candidate is not $GCOMMIT"; return 1; }
  local remote=$(git ls-remote $URL refs/heads/$BRANCH | cut -f1)
  print -r -- "GitHub $BRANCH: ${remote:-absent}"
  [[ $remote == $GCOMMIT ]] || { print -r -- "STOP: $GCOMMIT is not on GitHub yet; run: zsh $THIS push"; return 1; }
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    print -r -- "STOP: DEEPSEEK_API_KEY is not set. The isolated DSH_HOME $DH holds no login, and the agents host's DSH"
    print -r -- "child reads DEEPSEEK_API_KEY. Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key> in this shell, then:"
    print -r -- "  zsh $THIS pre"
    return 1
  fi
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed). DEEPSEEK_BASE_URL is removed for these runs."
  mkdir -p $DH $ROOT/proj $ROOT/agents-data || return 1
  print -r -- "{\"root\": \"$ROOT/agents-data\"}" > $ROOT/dsh-host.json
  print -r -- "created $ROOT: home (DSH_HOME), proj (cwd), agents-data, dsh-host.json: $(<$ROOT/dsh-host.json)"
  say "one-line prompt in the isolated home (login: DEEPSEEK_API_KEY; $DH/.credentials.yaml: $([[ -e $DH/.credentials.yaml ]] && print present || print absent))"
  (cd $ROOT/proj && iso dsh --profile headless "Reply in one line with the name of the model you are and nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: DSH could not answer with DEEPSEEK_API_KEY. Check the key and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  print "Success: a model name and exit=0; GitHub $BRANCH equals the candidate."
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. Root URL (no path) into profile headless; subdirectory form into sub569. Dialog: none. ~1-2 min."
  need_root || return 1
  local rc=0 g=$DH/profiles/headless/node_modules/graftling-dsh s=$DH/profiles/sub569/node_modules/graftling-dsh
  install_one headless "git+$URL#$GCOMMIT" || rc=1
  print -r -- "headless package directory: $(ls $g 2>&1 | tr '\n' ' ')"
  print -r -- "  size $(du -sh $g 2>/dev/null | cut -f1); plugin_python.py: $([[ -f $g/src/graftling/dsh/plugin_python.py ]] && print yes || print NO); pyproject.toml: $([[ -f $g/pyproject.toml ]] && print yes || print NO); tests/: $([[ -e $g/tests ]] && print present || print absent); src/graftling/install: $([[ -e $g/src/graftling/install ]] && print present || print absent)"
  install_one sub569 "git+$URL#$GCOMMIT&path:/src/graftling/dsh" || rc=1
  print -r -- "sub569 package directory: $(ls $s 2>&1 | tr '\n' ' ')"
  print "Success: both 'PASS', exit=0, ERR_PNPM_IGNORED_BUILDS lines: 0, agents-host in both dump-configs."
  print -r -- "next: zsh $THIS start"
  return $rc
  ;;
start)
  say "[start] Main. A real headless Session, no GRAFTLING_PYTHON. Dialog: none. ~1-3 min."
  need_root || return 1
  [[ -d $DH/profiles/headless/node_modules/graftling-dsh ]] || { print -r -- "STOP: run zsh $THIS install first"; return 1; }
  print -r -- "environments before: $(envs | tr '\n' ' ')"
  session start-$(date +%H%M%S) 'Use the agents tool (mcp__graftling__agents), not DSH'"'"'s own subagents. Create one child with runtime dsh whose task is: Answer with exactly one word: ready. Then call wait for that child, then call status for it. Report three lines: the child agent id; its one-word answer; the state and last_result.notification that status shows.'
  print -r -- "environments after: $(envs | tr '\n' ' ')"
  print -r -- "$DH/graftling-python: $(ls $DH/graftling-python 2>&1 | tr '\n' ' ')"
  local out; out=$(verdict 2>&1); print -r -- $out
  if [[ $out == *lacks* ]]; then
    print "The plugin refused: python3 lacks PyYAML or websockets (the documented case). The Session above had no agents tool."
    print -r -- "next: zsh $THIS deps   (then: zsh $THIS start)"
    return 0
  fi
  say "evidence in the isolated home"
  print -r -- "files under $DH naming mcp__graftling__agents: $(grep -rl 'mcp__graftling__agents' $DH --exclude-dir=node_modules --exclude-dir=graftling-python 2>/dev/null | wc -l | tr -d ' ')"
  print -r -- "agents data states: $(grep -rhoE '"state": *"[a-z_-]+"' $ROOT/agents-data 2>/dev/null | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  print "Success: exit=0; one environment under $DH/graftling-python; the report names the child, its word 'ready', and state completed or standby with notification delivered."
  (( SRC == 0 )) || { print -r -- "FAIL: the Session exited $SRC; see its output above"; return 1; }
  print -r -- "next: zsh $THIS again"
  ;;
deps)
  say "[deps] Main. The documented dependency command (pip downloads from PyPI into the environment). Dialog: none. ~30 s."
  need_root || return 1
  local e=($(envs))
  (( $#e == 1 )) || { print -r -- "STOP: expected one environment under $DH/graftling-python, found: $e"; return 1; }
  print -r -- "running: '$e/bin/python' -m ensurepip && '$e/bin/python' -m pip install 'PyYAML>=6,<7' 'websockets>=15,<17'"
  $e/bin/python -m ensurepip && $e/bin/python -m pip install 'PyYAML>=6,<7' 'websockets>=15,<17' || return 1
  verdict
  print "Success: the bootstrap prints $e/bin/python."
  print -r -- "next: zsh $THIS start"
  ;;
again)
  say "[again] Main. A second Session reuses the environment. Dialog: none. ~1 min."
  need_root || return 1
  local before=$(envs) inode=$(stat -f %i $(envs) 2>/dev/null)
  session again-$(date +%H%M%S) 'Call the agents tool (mcp__graftling__agents) with status, and report in one line how many agents it lists and their states.'
  local after=$(envs)
  print -r -- "environments before: $before | after: $after | inode $inode -> $(stat -f %i $(envs) 2>/dev/null)"
  [[ $before == $after && -n $before && $inode == $(stat -f %i $(envs) 2>/dev/null) ]] \
    && print "PASS: the same environment was reused" || { print "FAIL: the environment changed"; return 1; }
  (( SRC == 0 )) || { print -r -- "FAIL: the Session exited $SRC; see its output above"; return 1; }
  print -r -- "next: zsh $THIS local"
  ;;
local)
  say "[local] Main. Local-directory install of the installed graftling/dsh directory. Dialog: none. ~30 s."
  need_root || return 1
  local d=($(envs)); d=($d[1]/lib/python*/site-packages/graftling/dsh(N/))
  (( $#d == 1 )) || { print "STOP: no installed graftling/dsh directory; run start first"; return 1; }
  install_one local569 $d; local rc=$?
  print "Success: 'PASS: local569 registered graftling-dsh'."
  print -r -- "next: zsh $THIS post"
  return $rc
  ;;
post)
  say "[post] Main. ~/.dsh untouched? <5 s."
  profiles > $OUT/dsh-profiles-after.txt
  diff $OUT/dsh-profiles-before.txt $OUT/dsh-profiles-after.txt && print "PASS: ~/.dsh profile list unchanged" || print "FAIL: ~/.dsh profile list changed"
  print -r -- "To remove the isolated run when you no longer need it: rm -rf $ROOT"
  print -r -- "next: report $OUT to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS push|pre|install|start|deps|again|local|post"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY569_OUT:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
