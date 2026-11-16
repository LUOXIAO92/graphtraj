#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 489: `claude -p` in an isolated project nested under the Harness (own git) was given the Harness AGENTS.md.
# A shows it without project settings; B attributes it (claudeMdExcludes only / plugin only) and shows the fix
# (scripts/verify-common/claude_isolation.py settings) gives a clean answer. Judged by claude_isolation.py check
# from the stream-json records (init plugins, FILES line, no prompt echo).
#   zsh <this file> <00|A|B>   order: 00 -> A -> B
# Writes only the project's OWN .claude/settings.local.json under Harness tmp/489 (user authorization
# Worldline 20261116T180057.272969+0900); never ~/.claude, global plugin settings or the Harness AGENTS.md.
set -u
H=${VERIFY489_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY489_BASE:-$H/tmp/489}
OUT=${VERIFY489_OUT:-$H/.graphtraj/core/state/tasks/489-verify-project-loads-harness-agents-md/realhost}
PYH=${VERIFY489_PY:-$H/.venv-runtime/bin/python}
ISO=$SRC/scripts/verify-common/claude_isolation.py
PLUGIN=cc-plugin-agents-md
MODEL=claude-opus-5-5
STEP=${1:-help}
# VERIFY489_H, VERIFY489_BASE, VERIFY489_OUT, VERIFY489_PY and VERIFY489_STUB_BIN serve the rehearsal only.
path=(${VERIFY489_STUB_BIN:+$VERIFY489_STUB_BIN} /opt/homebrew/bin $HOME/.local/bin /usr/bin /bin /usr/sbin /sbin)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): zsh $THIS $1 2>&1 | tee $OUT/$1.txt"; }
# No CLAUDE_*/GRAPHTRAJ_* or other Session variables of Main leak in.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
limit() { local s=$1; shift; clean /usr/bin/perl -e "alarm $s; exec @ARGV" "$@"; }
iso() { clean $PYH -I $ISO "$@"; }
# A fresh project $BASE/<name> with its own git. Looks before deleting: only a directory carrying this script's marker.
fresh() {
  local d=$BASE/$1
  if [[ -e $d ]]; then
    [[ -f $d/.verify489 ]] || { print "STOP: $d exists without the marker .verify489 this script writes; not removed (look at it first)"; return 1; }
    rm -rf $d
  fi
  mkdir -p $d && git -C $d init -q && print -r -- "created by $THIS" > $d/.verify489 || { print "STOP: could not create $d"; return 1; }
  print "fresh project $d (own git, marker .verify489)"
}
# One headless claude -p of the shared prompt from inside the project: $1 project, $2 output name, $3 tag.
ask() {
  local d=$1 name=$2 tag=$3
  iso prompt $tag > $OUT/$name-prompt.txt || return 1
  (cd $d && limit 120 claude -p --model $MODEL --output-format stream-json --verbose \
    < $OUT/$name-prompt.txt > $OUT/$name.jsonl 2> $OUT/$name.err)
  print "claude -p in $d: rc=$? (142 = 120 s limit) | records $OUT/$name.jsonl, stderr $OUT/$name.err"
}
# Judge one run; the check text goes to stdout and to $OUT/<name>-check.txt. $1 project, $2 name, $3 tag, $4 expect.
judge() { iso check $OUT/$2.jsonl $3 $H $1 $OUT/$2-prompt.txt --expect $4 > $OUT/$2-check.txt; local rc=$?; cat $OUT/$2-check.txt; return $rc; }
field() { grep -m1 -o "$2.*" $OUT/$1-check.txt; }
loaded() { grep -q 'Harness instruction file loaded: YES' $OUT/$1-check.txt && print YES || print NO; }
answered() { grep -q 'host answered: yes' $OUT/$1-check.txt && print yes || print NO; }

step_00() {
  say "[00] preflight via /bin/zsh. Dialog: none (headless claude -p). Wait: claude <= 120 s. These steps run no pytest, so the pytest TMPDIR rule does not apply."
  local commit=$(git -C $SRC rev-parse HEAD)
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; candidate $SRC commit $commit (uncommitted paths: $(git -C $SRC status --porcelain | wc -l | tr -d ' '))"
  local C=$(whence -p claude)
  print "claude: ${C:-NOT FOUND} | version: $([[ -n $C ]] && limit 120 claude --version 2>&1 | head -1)"
  [[ -n $C ]] || { print "STOP 00: no claude on PATH ${(j.:.)path}"; return 1; }
  print "BASE=$BASE | OUT=$OUT | helper $ISO run by $PYH -I"
  print "No GraphTraj Task is used by these steps, so there is no Task readiness to check."
  say "isolated project $BASE/project with the shared isolation settings"
  fresh project || return 1
  iso settings $H $BASE/project || { print "STOP 00: settings refused or failed (text above)"; return 1; }
  say "one real read-only claude -p (limit 120 s), judged from its records: answered with the tag, not the prompt echoed, no Harness instruction file"
  ask $BASE/project 00 CLAUDE-OK
  if judge $BASE/project 00 CLAUDE-OK clean; then
    print "PASS 00: model $(field 00 'models: ' | cut -c9-) | logged in: answered | no Harness instruction file loaded"
    next A
  else
    print "STOP 00: see the check above. Head of $OUT/00.err:"; head -20 $OUT/00.err
    print "If it says login/API key: the USER runs \`claude\` in Terminal and logs in, then rerun 00"
    return 1
  fi
}

step_A() {
  say "[A] before the fix: a project with its own git and NO project settings. Dialog: none (headless claude -p). Wait <= 120 s. No pytest."
  fresh before || return 1
  print "$BASE/before/.claude/settings.local.json: $([[ -e $BASE/before/.claude/settings.local.json ]] && print PRESENT || print 'none (no .claude directory)')"
  ask $BASE/before A BEFORE-OK
  if judge $BASE/before A BEFORE-OK loaded; then
    local seen=()
    grep -q "$PLUGIN loaded: YES" $OUT/A-check.txt && seen+=("init plugins list $PLUGIN")
    field A 'Harness files among them: ' | grep -qF "$H/AGENTS.md" && seen+=("FILES names $H/AGENTS.md")
    grep -q 'Harness AGENTS.md line in the answer: YES' $OUT/A-check.txt && seen+=("the answer holds a Harness AGENTS.md line")
    print "PASS A: without project settings the Harness instruction file is loaded: ${(j: and :)seen}"
    next B
  else
    print "FAIL A: the before-fix load was not reproduced, or the host did not answer (check above; head of $OUT/A.err):"; head -20 $OUT/A.err
    return 1
  fi
}

step_B() {
  say "[B] attribution and the fix. Dialog: none (headless claude -p). Waits: 3 x claude <= 120 s. No pytest."
  say "B1 excludes-only: claudeMdExcludes for the Harness CLAUDE.md/AGENTS.md, plugin left on (informational)"
  fresh excludes-only || return 1
  iso settings $H $BASE/excludes-only --only excludes || return 1
  ask $BASE/excludes-only B-excludes B-EXCL-OK
  judge $BASE/excludes-only B-excludes B-EXCL-OK clean
  say "B2 plugin-only: $PLUGIN@builtin disabled, no excludes (expect clean)"
  fresh plugin-only || return 1
  iso settings $H $BASE/plugin-only --only plugin || return 1
  ask $BASE/plugin-only B-plugin B-PLUG-OK
  judge $BASE/plugin-only B-plugin B-PLUG-OK clean; local plug=$?
  say "B3 full: $BASE/project after rerunning the full settings (expect clean)"
  [[ -f $BASE/project/.verify489 ]] || fresh project || return 1
  iso settings $H $BASE/project || return 1
  ask $BASE/project B-full B-FULL-OK
  judge $BASE/project B-full B-FULL-OK clean; local full=$?
  say "results"
  print "| project | settings | answered | Harness file loaded | check (expect clean) |"
  print "| excludes-only | claudeMdExcludes | $(answered B-excludes) | $(loaded B-excludes) | $(field B-excludes 'answer check' | sed 's/.*: //') (informational) |"
  print "| plugin-only | $PLUGIN@builtin false | $(answered B-plugin) | $(loaded B-plugin) | $(field B-plugin 'answer check' | sed 's/.*: //') |"
  print "| project (full) | both | $(answered B-full) | $(loaded B-full) | $(field B-full 'answer check' | sed 's/.*: //') |"
  if [[ $(loaded B-excludes) == YES && $plug == 0 ]]; then print "source: builtin $PLUGIN"
  else print "attribution: inconclusive (table above)"; fi
  if [[ $plug == 0 && $full == 0 ]]; then print "PASS B: plugin-only and full settings give a clean answer (no Harness instruction file loaded)"
  else print "FAIL B: plugin-only or full settings still load a Harness instruction file or did not answer (table above)"; return 1; fi
}

# Everything runs from this last line and exits on it, so zsh reads nothing after it even if the file changes.
dispatch() {
case $STEP in
  00|A|B) step_$STEP 2>&1; return $? ;;
  *) print "usage: zsh $THIS <00|A|B>   order: 00 -> A -> B" ;;
esac
}
dispatch; exit $?
