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
# The CANDIDATE (graftling branch agent/570-..., GCOMMIT below), in the isolated DSH home ROOT/home:
#   push          Main, after asking the user. Pushes the candidate branch to GitHub from the Engineer's bundle
#                 (.scratch/570/graftling-570.bundle). Dialog: none expected; git uses your usual GitHub login. ~30 s.
#   pre2          Main. The candidate is the bundle's head and on GitHub; creates ROOT/home and ROOT/claude-home; a
#                 one-line DSH prompt in ROOT/home and a one-line `claude -p` in CLAUDE_CONFIG_DIR=ROOT/claude-home
#                 (needs ANTHROPIC_API_KEY; without it pre2 says the share step will STOP). Dialog: none. ~1 min.
#   install       Main. The candidate's root URL pinned to GCOMMIT into profile headless of ROOT/home. ~1-2 min.
#   start         Main. GRAFTLING_DSH_CONFIG unset; a real headless Session in ROOT/proj creates a dsh child that
#                 answers one word, waits, reads status. Its record lands in ROOT/proj/.agents-control; nothing in
#                 ROOT/home or ROOT/agents-data. May ask for deps first. Dialog: none. ~1-3 min.
#   subdir        Main. The same from ROOT/proj/sub: the data root is ROOT/proj/sub/.agents-control. ~1-2 min.
#   explicit      Main. GRAFTLING_DSH_CONFIG=ROOT/dsh-host.json: the record lands in ROOT/agents-data;
#                 ROOT/proj/.agents-control gains none. Dialog: none. ~1-2 min.
#   share         Main. Claude Code and DSH on ROOT/proj/.agents-control at once: each creates one child, waits,
#                 lists status. Claude Code runs isolated in CLAUDE_CONFIG_DIR=ROOT/claude-home with
#                 ANTHROPIC_API_KEY (STOP if unset). VERIFY570_CLAUDE_USER_LOGIN=1 uses your own Claude login
#                 instead: Main, ask the user before setting it (it writes in ~/.claude and ~/.claude.json, as
#                 the step prints). Dialog: none expected. ~2-4 min.
#   off           Main, last. `dsh plugin --profile headless remove graftling-dsh` in ROOT/home, then a Session:
#                 no agents tool, no new data. Dialog: none. ~1 min.
#   post          Main. ~/.dsh's profile list again, compared with pre's; how to remove ROOT. <5 s.
# Everything is under ROOT=/private/tmp/graftling-570 (isolated DSH homes ROOT/home-base and ROOT/home);
# ~/.dsh is only listed, never written; ~/.claude is not used unless VERIFY570_CLAUDE_USER_LOGIN=1. Step output
# is kept in OUT. VERIFY570_ROOT / VERIFY570_OUT / VERIFY570_URL are for the Engineer's rehearsal only.
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
BRANCH=agent/570-graftling-dsh-plugin-default-host-config
GCOMMIT=2de0a386549cbe6766adb833082207b592bc10d0   # the graftling candidate (base: dev 00778d1)
BUNDLE=$WT/.scratch/570/graftling-570.bundle        # the candidate branch, from the base
DH=$ROOT/home                                       # isolated DSH home holding the candidate install
CH=$ROOT/claude-home                                # isolated CLAUDE_CONFIG_DIR for the share step
P=$ROOT/proj
path=(${VERIFY570_BIN:+$VERIFY570_BIN} /opt/homebrew/bin $path)   # VERIFY570_BIN: rehearsal stubs (stub/) only

say() { print -r -- "== $*"; }
# An isolated DSH: home $1, no explicit Python or host configuration, no inherited agents channel.
iso() { local home=$1; shift
        env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_AGENT_PACKAGE -u GRAFTLING_DSH_CONFIG \
          -u DSH_SESSION_ID -u DSH_AGENT_SOURCE -u DEEPSEEK_BASE_URL DSH_HOME=$home "$@" }
# Claude Code for the share step: no inherited agents channel or Claude Code session markers. By default isolated
# in CLAUDE_CONFIG_DIR=$CH (login: ANTHROPIC_API_KEY); with VERIFY570_CLAUDE_USER_LOGIN=1 the user's own login.
claude_iso() {
  local -a clean=(-u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_AGENT_PACKAGE -u GRAFTLING_DSH_CONFIG -u DSH_SESSION_ID
                  -u DSH_AGENT_SOURCE -u GRAFTLING_NATIVE_RUNTIME -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT)
  if [[ -n ${VERIFY570_CLAUDE_USER_LOGIN:-} ]]; then env $clean "$@"; else env $clean CLAUDE_CONFIG_DIR=$CH "$@"; fi
}
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
  local home=$1 p=$2 spec=$3 rc log
  log=$ROOT/install-${home:t}-$p.txt     # a separate statement: one `local` expands all its words first
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

CREATE='Use the agents tool (mcp__graftling__agents), not DSH'"'"'s own subagents. Create one child with runtime dsh whose task is: Answer with exactly one word: ready. Then call wait for that child, then call status for it. Report three lines: the child agent id; its one-word answer; the state and last_result.notification that status shows.'

count() { print -l $1/control/agents/*.json(N) | grep -c . }                    # agent records under root $1
need_candidate() {
  need_root || return 1
  [[ $(bundles $DH headless) == *graftling-dsh* ]] || { print -r -- "STOP: run zsh $THIS install first"; return 1; }
}
# After a candidate Session: did the plugin refuse for missing dependencies? Then print the deps step.
asks_deps() {  # step-to-rerun
  local out; out=$(verdict $DH 2>&1); print -r -- $out
  [[ $out == *lacks* ]] || return 1
  print "The plugin refused: python3 lacks PyYAML or websockets (the documented case); the Session had no agents tool."
  print -r -- "next: zsh $THIS deps   (then: zsh $THIS $1)"
}
# A candidate Session that creates one dsh child; checks that its record landed in data root $3 only.
create_in() {  # name dir root [VAR=value...]
  local name=$1 dir=$2 root=$3; shift 3
  local before=$(count $root) proj_before=$(count $P/.agents-control) data_before=$(count $ROOT/agents-data)
  session $DH $dir $name "$CREATE" "$@"
  asks_deps $STEP && return 0
  say "evidence"
  print -r -- "agent records: $root $before -> $(count $root); $P/.agents-control $proj_before -> $(count $P/.agents-control); $ROOT/agents-data $data_before -> $(count $ROOT/agents-data)"
  records $root
  roots
  print -r -- ".agents-control or control/ under the DSH home $DH: $(print -l $DH/**/.agents-control(N/D) $DH/control(N/) | tr '\n' ' ')"
  local ok=1
  (( SRC == 0 )) || { print -r -- "FAIL: the Session exited $SRC"; ok=0; }
  (( $(count $root) > before )) || { print -r -- "FAIL: no new agent record under $root"; ok=0; }
  [[ -z $(print -l $DH/**/.agents-control(N/D) $DH/control(N/)) ]] || { print "FAIL: data written in the DSH home"; ok=0; }
  return $(( 1 - ok ))
}

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
  print -r -- "next: zsh $THIS push   (Main: ask the user first; it pushes the candidate branch to GitHub)"
  ;;
push)
  say "[push] Main, after the user agreed. Push $BRANCH ($GCOMMIT) to $URL from $BUNDLE. Dialog: none expected. ~30 s."
  local G=${TMPDIR:-/tmp}/graftling-570-push.git
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { print "already on GitHub"; print -r -- "next: zsh $THIS pre2"; return 0; }
  [[ -f $BUNDLE ]] || { print -r -- "STOP: $BUNDLE missing; ask the Engineer"; return 1; }
  rm -rf $G && git clone -q --bare $URL $G || return 1                 # has the base, the bundle's prerequisite
  git -C $G fetch -q $BUNDLE "${BRANCH}:${BRANCH}" || return 1
  [[ $(git -C $G rev-parse $BRANCH) == $GCOMMIT ]] || { print "STOP: the bundle's branch is not $GCOMMIT"; return 1; }
  print -r -- "authors and committers: $(git -C $G log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $G push $URL "${BRANCH}:refs/heads/${BRANCH}" || return 1
  print -r -- "on GitHub now: $(git ls-remote $URL refs/heads/$BRANCH)"
  rm -rf $G
  print "Success: the GitHub line above shows $GCOMMIT."
  print -r -- "next: zsh $THIS pre2"
  ;;
pre2)
  say "[pre2] Main. Candidate preflight: GitHub, isolated homes, one-line prompts. Dialog: none. ~1 min."
  need_root || return 1
  local heads=$(git bundle list-heads $BUNDLE 2>/dev/null) remote=$(git ls-remote $URL refs/heads/$BRANCH | cut -f1)
  print -r -- "bundle: ${heads:-unreadable} | GitHub $BRANCH: ${remote:-absent}"
  [[ $heads == $GCOMMIT* ]] || { print -r -- "STOP: the bundle's head is not $GCOMMIT"; return 1; }
  [[ $remote == $GCOMMIT ]] || { print -r -- "STOP: $GCOMMIT is not on GitHub yet; run: zsh $THIS push"; return 1; }
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print -r -- "STOP: export DEEPSEEK_API_KEY=<your DeepSeek API key>, then: zsh $THIS pre2"; return 1; }
  mkdir -p $DH $CH || return 1
  say "one-line DSH prompt in $DH"
  (cd $P && iso $DH dsh --profile headless "Reply in one line with the name of the model you are and nothing else." < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: DSH could not answer in $DH; check DEEPSEEK_API_KEY and the network, then: zsh $THIS pre2"; return 1; }
  if [[ -n ${ANTHROPIC_API_KEY:-} ]]; then
    say "one-line claude -p in CLAUDE_CONFIG_DIR=$CH (login: ANTHROPIC_API_KEY, ${#ANTHROPIC_API_KEY} characters; not printed)"
    (cd $P && claude_iso claude -p --setting-sources project,local --strict-mcp-config --model haiku \
       "Reply in one line with the model id you are running as and nothing else." < /dev/null) 2>&1 | tail -5
    print -r -- "exit=$?"
  else
    print -r -- "ANTHROPIC_API_KEY is not set: the share step will STOP (export it first, or see share's VERIFY570_CLAUDE_USER_LOGIN)."
  fi
  print "Success: a DeepSeek model name and exit=0 (and a Claude model id when ANTHROPIC_API_KEY is set)."
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. Candidate root URL pinned to $GCOMMIT into profile headless of $DH. Dialog: none. ~1-2 min."
  need_root || return 1
  install_one $DH headless "git+$URL#$GCOMMIT" || return 1
  print -r -- "--dump-config lines naming agents-host or graftling:"
  (cd $P && iso $DH dsh --profile headless --dump-config 2>&1) | grep -n -i 'agents-host\|graftling' | head
  print -r -- "installed commit: $(grep -h graftling $DH/profiles/headless/package.json | tr -s ' ')"
  print "Success: 'PASS: headless registered graftling-dsh', the dependency names $GCOMMIT."
  print -r -- "next: zsh $THIS start"
  ;;
start)
  say "[start] Main. Candidate, GRAFTLING_DSH_CONFIG unset, Session in $P. Dialog: none. ~1-3 min."
  need_candidate || return 1
  create_in start $P $P/.agents-control; local rc=$?
  [[ -f $OUT/start.deps ]] && rm -f $OUT/start.deps
  print "Success: exit=0; the reply names the child, 'ready', standby (or completed) and delivered; a new dsh record"
  print -r -- "under $P/.agents-control; $ROOT/agents-data unchanged; nothing in $DH."
  (( rc == 0 )) && print -r -- "PASS: the default data root is $P/.agents-control" && print -r -- "next: zsh $THIS subdir"
  return $rc
  ;;
subdir)
  say "[subdir] Main. Candidate, GRAFTLING_DSH_CONFIG unset, Session in $P/sub. Dialog: none. ~1-2 min."
  need_candidate || return 1
  local proj=$(count $P/.agents-control)
  create_in subdir $P/sub $P/sub/.agents-control; local rc=$?
  (( $(count $P/.agents-control) == proj )) || { print -r -- "FAIL: $P/.agents-control gained a record"; rc=1; }
  print -r -- "Success: a new record under $P/sub/.agents-control and none under $P/.agents-control: the project"
  print "directory is the directory dsh was started in (headless)."
  (( rc == 0 )) && print -r -- "PASS: the Session cwd $P/sub chose the data root" && print -r -- "next: zsh $THIS explicit"
  return $rc
  ;;
explicit)
  say "[explicit] Main. Candidate, GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json, Session in $P. Dialog: none. ~1-2 min."
  need_candidate || return 1
  local proj=$(count $P/.agents-control)
  create_in explicit $P $ROOT/agents-data GRAFTLING_DSH_CONFIG=$ROOT/dsh-host.json; local rc=$?
  (( $(count $P/.agents-control) == proj )) || { print -r -- "FAIL: $P/.agents-control gained a record"; rc=1; }
  print -r -- "Success: a new record under $ROOT/agents-data; $P/.agents-control unchanged."
  (( rc == 0 )) && print -r -- "PASS: the explicit configuration wins" && print -r -- "next: zsh $THIS share"
  return $rc
  ;;
share)
  say "[share] Main. Claude Code and DSH on $P/.agents-control at the same time. Dialog: none expected. ~2-4 min."
  need_candidate || return 1
  local E=($(envs $DH)) claude=$(command -v claude)
  (( $#E == 1 )) || { print -r -- "STOP: expected one environment under $DH/graftling-python (run start first): $E"; return 1; }
  [[ -n $claude ]] || { print "STOP: no claude on PATH"; return 1; }
  if [[ -n ${VERIFY570_CLAUDE_USER_LOGIN:-} ]]; then
    print -r -- "VERIFY570_CLAUDE_USER_LOGIN=1: Claude Code uses YOUR login. Main: this needs the user's agreement. It reads"
    print -r -- "the keychain and ~/.claude.json, and writes ~/.claude/projects/-private-tmp-graftling-570-proj/ and a project"
    print -r -- "entry for $P in ~/.claude.json. No settings, plugins or skills under ~/.claude are written."
  elif [[ -z ${ANTHROPIC_API_KEY:-} ]]; then
    print -r -- "STOP: ANTHROPIC_API_KEY is not set. Claude Code runs isolated in CLAUDE_CONFIG_DIR=$CH, which holds no login."
    print -r -- "Fix: export ANTHROPIC_API_KEY=<your Anthropic API key> in this shell, then: zsh $THIS share"
    print -r -- "Or, only after the user agrees (it writes ~/.claude/projects/-private-tmp-graftling-570-proj/ and a project"
    print -r -- "entry for $P in ~/.claude.json; reads the keychain and ~/.claude.json):"
    print -r -- "  VERIFY570_CLAUDE_USER_LOGIN=1 zsh $THIS share"
    return 1
  fi
  say "graftling's Claude Code host configuration for $P (project files only), with $E/bin/python"
  if [[ ! -f $P/.agents-control/claude-host.json ]]; then
    (cd $P && claude_iso $E/bin/python -I -m graftling.claude.host configuration --project $P --claude $claude --write) \
      || { print "STOP: configuration --write failed"; return 1; }
    # DSH Sessions in $P must not start this server from the project's .mcp.json: keep it beside ROOT instead.
    mv $P/.mcp.json $ROOT/claude-mcp.json || return 1
  fi
  print -r -- "written: $(cd $P && print -l .claude/**/*(N.D) .agents-control/claude-host.json(N) | tr '\n' ' ') + $ROOT/claude-mcp.json"
  local sum_before=$(shasum $P/.agents-control/claude-host.json | cut -c1-12)
  local ds=$ROOT/share-dsh-$(date +%H%M%S).txt cs=$ROOT/share-claude-$(date +%H%M%S).txt
  local dprompt='Use the agents tool (mcp__graftling__agents), not DSH'"'"'s own subagents. Create one child with runtime dsh whose task is: Answer with exactly one word: dsh-ok. Call wait for it, then call status with no agent. Report: the child agent id, its answer, and every agent id that status lists.'
  local cprompt='Use the tool mcp__graftling__agents. Create one child with runtime claude and model haiku whose task is: Answer with exactly one word: claude-ok. Call wait for it, then call status with no agent. Report: the child agent id, its answer, and every agent id that status lists.'
  say "both Mains start now: DSH ($ds) and claude -p ($cs)"
  (cd $P && iso $DH dsh --profile headless "$dprompt" < /dev/null > $ds 2>&1; print -r -- "exit=$?" >> $ds) &
  (cd $P && claude_iso $claude -p --setting-sources project,local --strict-mcp-config --mcp-config $ROOT/claude-mcp.json \
     --allowedTools mcp__graftling__agents --model haiku --output-format text "$cprompt" < /dev/null > $cs 2>&1
   print -r -- "exit=$?" >> $cs) &
  wait
  say "DSH Main"; tail -25 $ds
  say "Claude Code Main"; tail -25 $cs
  say "evidence in $P/.agents-control"
  records $P/.agents-control
  print -r -- "live/: $(cd $P/.agents-control && print -l live/*(ND) live/dsh-host/*(ND) | tr '\n' ' ')"
  print -r -- "host.log: $([[ -f $P/.agents-control/host.log ]] && tail -3 $P/.agents-control/host.log | tr '\n' ' ' || print absent)"
  print -r -- "claude-host.json: $sum_before -> $(shasum $P/.agents-control/claude-host.json | cut -c1-12)"
  # Which host created each agent id a reply names: each Main must name only its own.
  python3 -I - $P/.agents-control $ds $cs <<'EOF'
import json, re, sys
from pathlib import Path
root, dsh, claude = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
owner = {}
for path in (root / 'control' / 'agents').glob('*.json'):
    record = json.loads(path.read_text())
    owner[record['agent']] = (record.get('creator') or {}).get('host')
ok = True
for name, path, host in (('DSH', dsh, 'dsh-native'), ('Claude Code', claude, 'claude-native')):
    ids = sorted(set(re.findall(r'agent-[0-9a-f]{32}', Path(path).read_text())))
    hosts = {i: owner.get(i, 'not in this root') for i in ids}
    print(f'{name} reply names: {hosts}')
    if not ids or any(h != host for h in hosts.values()):
        ok = False
print('PASS: each Main named only its own children, all in one root' if ok else 'FAIL: see the names above')
sys.exit(0 if ok else 1)
EOF
  local rc=$?
  grep -q '^exit=0' $ds && grep -q '^exit=0' $cs || { print "FAIL: a Main did not exit 0 (see above)"; rc=1; }
  print "Success: both exit=0; each reply names its own child (dsh-ok / claude-ok) and lists only it; both records"
  print "under one .agents-control; live/ holds channel.json (Claude Code, while it ran) and dsh-host/ apart."
  (( rc == 0 )) && print -r -- "next: zsh $THIS off"
  return $rc
  ;;
off)
  say "[off] Main, last. Remove graftling-dsh from profile headless of $DH; then a Session. Dialog: none. ~1 min."
  need_candidate || return 1
  local before=$(count $P/.agents-control) log=$ROOT/off-remove.txt
  (cd $P && iso $DH dsh plugin --profile headless remove graftling-dsh < /dev/null) > $log 2>&1
  print -r -- "remove exit=$? (output: $log)"; tail -5 $log
  print -r -- "bundles now: $(bundles $DH headless)"
  session $DH $P off "$TOOLS"
  evidence $DH
  print -r -- "agent records in $P/.agents-control: $before -> $(count $P/.agents-control)"
  local ok=1
  [[ $(bundles $DH headless) != *graftling-dsh* ]] || { print "FAIL: graftling-dsh is still a bundle"; ok=0; }
  grep -q 'NO AGENTS TOOL' $SOUT || { print "FAIL: the reply does not say NO AGENTS TOOL"; ok=0; }
  (( SRC == 0 && $(count $P/.agents-control) == before )) || { print "FAIL: exit or new records"; ok=0; }
  print "Success: removal exit 0, no graftling-dsh bundle, the reply says NO AGENTS TOOL, no new records."
  (( ok )) && print -r -- "PASS: removing the plugin turns it off" && print -r -- "next: zsh $THIS post"
  return $(( 1 - ok ))
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
# An expansion error under no_unset aborts run_step without a status the pipeline reports, so the step's
# own end line decides: no 'STEP-END rc=0' means it did not finish.
{ run_step; print -r -- "STEP-END rc=$?"; } 2>&1 | tee $OUT/$STEP.txt
local rc=$?
grep -q '^STEP-END rc=0$' $OUT/$STEP.txt || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT/$STEP.txt; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
