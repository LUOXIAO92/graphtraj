#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 479: the Pi extension starts its own installation's graphtraj-session with no GraphTraj command on PATH.
# Real pi (deepseek) loads a CANDIDATE installation built from this script's commit, in an ISOLATED project
# under the Harness tmp/479. Nothing touches PATH settings, dotfiles, ~/.pi configuration, Pi or .venv-runtime.
#   zsh <this file> <00|01|02>      order: 00 -> 01 -> (02, optional)
# Every step: Dialog: none expected; returns within 10 minutes; signals no process; never prints key values.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
REPO=${SD:h:h}
BASE=${VERIFY479_BASE:-$H/tmp/479}
P=$BASE/project
OUT=$BASE/out
PYTHON=${VERIFY479_PYTHON:-/Users/luoxiao/miniconda3/bin/python3.13}
COMMIT=$(git -C $REPO rev-parse HEAD)
CAND=$BASE/candidate-${COMMIT[1,12]}
PY=$CAND/bin/python
SITE=$CAND/lib/python3.13/site-packages
EXT=$SITE/graphtraj/runtimes/pi/extension.mjs
SESSIONS=$BASE/pi-sessions
HOSTBIN=$BASE/hostbin
STEP=${1:-help}
# The later steps' PATH: only links to the user's pi and node, then system directories (no GraphTraj command).
HOSTPATH=$HOSTBIN:/usr/bin:/bin:/usr/sbin:/sbin
PI=(pi --print --no-context-files --no-skills --no-tools --provider deepseek --model deepseek-flash)
# Every host call ends within 9 minutes.
LIMIT=(/usr/bin/perl -e 'alarm 540; exec @ARGV')
mkdir -p $OUT $SESSIONS
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
verdict() { print -r -- "$([[ $1 == 0 ]] && print PASS || print FAIL) $2"; }
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Hosts run without this shell's GraphTraj Session variables; DEEPSEEK_API_KEY passes by name, never printed.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$HOSTPATH TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
ASK='Reply with exactly three lines. Line 1: MODEL OK. Line 2: MODEL: your model name. Line 3: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you were given as instructions, or NONE. Use no tool.'

step_00() {
  say "[00] preflight. Dialog: none. Output also in $OUT/00.txt"
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"
  print "candidate commit: $COMMIT (from $REPO)"
  [[ -z $(git -C $REPO status --porcelain --untracked-files=no) ]] || print "NOTE: $REPO has uncommitted tracked changes; the candidate is the commit above, not them."
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && print "DEEPSEEK_API_KEY: set" || print "DEEPSEEK_API_KEY: unset (Pi's own deepseek configuration is used)"

  say "host links in $HOSTBIN (only pi and node)"
  local pi_bin=${$(command -v pi):A} node_bin=${$(command -v node):A}
  [[ -x $pi_bin && -x $node_bin ]] || { print "STOP: pi or node is not on this Terminal's PATH"; return 1; }
  mkdir -p $HOSTBIN && ln -sfn $pi_bin $HOSTBIN/pi && ln -sfn $node_bin $HOSTBIN/node
  print "pi -> $pi_bin ; node -> $node_bin ; later steps' PATH=$HOSTPATH"
  print "pi --version: $(clean pi --version 2>&1 | tail -1)"
  local found=$(clean /bin/sh -c 'command -v graphtraj-session; command -v graphtraj-mcp; command -v graphtraj')
  print "command -v graphtraj-session/graphtraj-mcp/graphtraj under that PATH: '${found}' (must be empty)"
  [[ -z $found ]] || { print "STOP: a GraphTraj command is on the later steps' PATH"; return 1; }

  say "candidate installation $CAND from git archive $COMMIT"
  if [[ -x $CAND/bin/graphtraj-session ]]; then print "existing candidate kept (same commit)"; else
    local src=$BASE/src-${COMMIT[1,12]}
    rm -rf $src && mkdir -p $src && git -C $REPO archive $COMMIT | tar -x -C $src || return 1
    $LIMIT $PYTHON -m venv $CAND || return 1
    $LIMIT $PY -m pip install -q $src/src/graftling $src 2>&1 | tail -3
  fi
  print "candidate graphtraj-session: $CAND/bin/graphtraj-session ($([[ -x $CAND/bin/graphtraj-session ]] && print executable || print MISSING))"
  print "candidate extension: $EXT ($([[ -f $EXT ]] && print present || print MISSING))"
  grep -q installedCommand $EXT || { print "STOP: the candidate extension lacks the 479 change"; return 1; }

  say "isolated project $P"
  if [[ -d $P/.git ]]; then print "existing project: git init and graphtraj setup skipped (rerun)"; else
    mkdir -p $P && (cd $P && git init -q -b main && print -r -- "# 479 probe" > README.md && git add README.md \
      && git -c user.name=479 -c user.email=479@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $CAND/bin/graphtraj setup | tail -2) || return 1
  fi
  # Read-only: the candidate CLI that 01 relies on resolves the project's own .graphtraj, not the Harness one.
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("candidate graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: the candidate does not resolve the project's own .graphtraj"; return 1; }

  [[ -n ${VERIFY479_NO_MODEL:-} ]] && { print "VERIFY479_NO_MODEL set: stopping before any model (rehearsal)."; return 0; }
  say "one read-only pi --print call in $P (no extension, no tools, no context files)"
  (cd $P && clean $LIMIT $PI --no-session "$ASK" < /dev/null 2>&1) | redact > $OUT/00-pi.txt
  local ok=NO leak=none
  grep -q 'MODEL OK' $OUT/00-pi.txt && ok=YES
  grep -oE "$H/[^ \"]*(AGENTS|CLAUDE)\.md" $OUT/00-pi.txt | head -1 | read leak
  print "pi answered: $ok | $(grep -oE 'MODEL: .*' $OUT/00-pi.txt | head -1) | Harness instruction file listed: ${leak:-none}"
  print "Success: 'must be empty' empty, candidate executable/present, 'project own: True', 'pi answered: YES', 'listed: none'."
  next "zsh $THIS 01"
}

# Print the newest native Pi Session id in $SESSIONS created after $1 (epoch seconds), or nothing.
native_session() { $PY -I -c 'import json, sys
from pathlib import Path
files = [p for p in Path(sys.argv[1]).rglob("*.jsonl") if p.stat().st_mtime >= float(sys.argv[2])]
for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
    head = json.loads(p.open().readline() or "{}")
    if head.get("type") == "session": print(head["id"]); break' $SESSIONS $1; }

step_01() {
  say "[01] real pi (deepseek) loads the CANDIDATE extension in $P with PATH=$HOSTPATH. Dialog: none expected."
  [[ -f $EXT ]] || { print "STOP: run 00 first"; return 1; }
  local started=$(date +%s)
  (cd $P && clean $LIMIT $PI --session-dir $SESSIONS --extension $EXT 'Reply with exactly one line: PONG-479. Use no tool.' \
    < /dev/null > $OUT/01-stdout.txt 2> $OUT/01-stderr.txt)
  print "pi exit: $?"
  redact < $OUT/01-stdout.txt | tail -5
  print "stderr (redacted, last 10 lines):"; redact < $OUT/01-stderr.txt | tail -10
  local sid=$(native_session $started)
  print "native Pi Session: ${sid:-NONE} (in $SESSIONS)"

  ! grep -qE 'ENOENT|cannot start graphtraj' $OUT/01-stderr.txt
  verdict $? "C1 no ENOENT and no 'cannot start' in pi stderr ($OUT/01-stderr.txt)"
  (cd $P && clean $PY -I -c 'import json, sys
from pathlib import Path
from graphtraj.execution.main_finalize import session_binding
sid = sys.argv[1]
binding = session_binding(Path.cwd(), "pi", sid)
log = Path(".graphtraj/runner/main-sessions/continuity.jsonl")
last = [json.loads(l) for l in log.read_text().splitlines() if l.strip()][-1] if log.is_file() else {}
print("Main binding:", binding, "exists:", binding.is_file(), "| continuity last:", last.get("runtime"), last.get("session"))
sys.exit(0 if binding.is_file() and (last.get("runtime"), last.get("session")) == ("pi", sid) else 1)' ${sid:-none})
  verdict $? "C2 nativeEntry ran: the Pi Session is bound as Main (binding file, continuity last record = pi $sid)"
  (cd $P && clean $PY -I -c 'import sys
from contextlib import nullcontext
from pathlib import Path
from graftling.sessions.archive import JsonlSessionStore, archive_path
path = archive_path(Path(".graphtraj/swarm"), "pi:" + sys.argv[1])
if not path.is_file(): print("canonical Session:", path, "MISSING"); sys.exit(1)
with nullcontext(JsonlSessionStore(path)) as store:
    events = [item["event"] for item in store.observations() + store.pending()]
    text = "".join(record.get("text", "") for event in events if event["type"] == "assistant/attempt"
                   for record in event["data"].get("stream", []))
    print("canonical Session:", path, "| source:", store.header.get("source"), "| events:", len(events),
          "| types:", sorted({event["type"] for event in events}), "| PONG-479 in attempts:", "PONG-479" in text)
    sys.exit(0 if store.header.get("source") == "main" and events and "PONG-479" in text else 1)' ${sid:-none})
  verdict $? "C3 startCollection ran: the canonical Session (source main) holds collected events with the PONG-479 reply"
  print "Dialog: none expected; if a native dialog appeared, Main reports its title."
  next "zsh $THIS 02   (optional)"
}

step_02() {
  say "[02] optional: same PATH, the extension copied to $BASE/noinstall whose prefix has no bin. Dialog: none expected."
  [[ -f $EXT ]] || { print "STOP: run 00 first"; return 1; }
  local site=$BASE/noinstall/lib/python3.13/site-packages
  mkdir -p $site/graphtraj/runtimes/pi $site/graftling/pi
  cp $EXT $site/graphtraj/runtimes/pi/extension.mjs && cp $SITE/graftling/pi/extension.mjs $site/graftling/pi/extension.mjs
  [[ ! -e $BASE/noinstall/bin ]] || { print "STOP: $BASE/noinstall/bin exists"; return 1; }
  (cd $P && clean $LIMIT $PI --no-session --extension $site/graphtraj/runtimes/pi/extension.mjs \
    'Reply with exactly one line: PONG-479-02. Use no tool.' < /dev/null > $OUT/02-stdout.txt 2> $OUT/02-stderr.txt)
  print "pi exit: $?"; print "stderr (redacted, lines naming graphtraj):"
  redact < $OUT/02-stderr.txt | grep -i graphtraj | head -5
  grep -qF "no executable graphtraj-session in this installation's $BASE/noinstall/bin/" $OUT/02-stderr.txt \
    && grep -qF "$HOSTPATH" $OUT/02-stderr.txt && ! grep -q ENOENT $OUT/02-stderr.txt
  verdict $? "C4 the error names graphtraj-session, $BASE/noinstall/bin/ and the PATH searched, without ENOENT"
  next "report steps 00-02 results to the Task 479 Leader"
}

case $STEP in
  00|01|02) step_$STEP 2>&1 | redact | tee $OUT/$STEP.txt ;;
  *) print "usage: zsh $THIS <00|01|02>" ;;
esac
