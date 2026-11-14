#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 450 real-host check: a Claude member leaves a detached background process and ends its turn;
# its Worker stops that process by the member marker and records it in the termination record.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/450-orphaned-member-processes-and-hung-tests/scripts/verify-450/steps.zsh <00|00u|01|02|03>
# 00 preflight (Main): scratch venv from COMMIT, isolated project, one-line model answer, plugin check, task 1 ready.
# 00u (USER, only when 00 says the plugin is not loaded): the folder-trust dialog for the new path.
# 01 probe (Main, ~5 min, may run in background): a `claude -p` Main dispatches the Leader, whose only Bash
#    command starts `(python ... probe450-<nonce> &)` and returns; Main waits for the Leader's termination record.
#    Then 02 runs automatically.
# 02 observe (Main, read only, signals nothing): escaped_processes per termination record and a live argv scan.
# 03 full suite (Main) in the background from the Worktree at HEAD.
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/450-orphaned-member-processes-and-hung-tests
SD=${0:A:h}
COMMIT=${VERIFY450_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY450_BASE:-$HOME/graphtraj-verify-450}
OUT=${VERIFY450_OUT:-$H/.graphtraj/core/state/tasks/450-orphaned-member-processes-and-hung-tests/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
SRC=$BASE/src
VV=$BASE/venv
P=$BASE/project
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  local S=($RT/lib/python*/site-packages(N)) D
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  D=($VV/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $VV/bin/python -I -c 'import graftling.member_processes as m; print("member_processes module:", m.__file__)') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  # Same path every run (trust is per path); keep any per-project approval Claude Code wrote there.
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 450 probe" > README.md && git add README.md \
      && git -c user.name=450 -c user.email=450@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  (cd $P && clean $VV/bin/python -I $SD/probe.py prepare $P $MODEL) || { print "STOP: probe Task is not ready (text above)"; return 1; }
  local C=$(claude_bin)
  [[ -f $BASE/settings.local.json.keep ]] && mkdir -p $P/.claude && cp -p $BASE/settings.local.json.keep $P/.claude/settings.local.json
  (cd $P && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write) || return 1
  say "host answers one line with $MODEL (login check; no tool)"
  (cd $P && clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      <<< 'Reply with exactly: MODEL OK' > $OUT/00-model-stream.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  $VV/bin/python -I -c 'import json,sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d.get("type") == "result": print("result:", d.get("result"), "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))' $OUT/00-model-stream.jsonl \
      || { print "STOP: claude -p gave no stream. stderr:"; head -c 300 $OUT/00-model-stderr.txt; print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "plugin check: the init record must list graphtraj-claude-host (it prepares each call's association)"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    print "Run step 00u (USER, once), then rerun 00. The project path stays $P, so the trust carries over."
    next "USER: zsh $SD/steps.zsh 00u   (then Main: zsh $SD/steps.zsh 00)"
    return 1
  fi
  print "Success: member_processes module from $SRC, 'roles OK', 'task 1 ready', result 'MODEL OK' with $MODEL in models,"
  print "and 'graphtraj-claude-host loaded: YES'."
  next "zsh $SD/steps.zsh 01 2>&1 | tee $OUT/01.txt"
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: Claude Code records folder trust in ~/.claude.json only through this dialog; claude -p never"
  print "asks, and the only other way is editing ~/.claude.json, which Main must not touch. No supported"
  print "non-interactive trust exists inside the probe project (393 step Vc needed the same start)."
  next "Main: zsh $SD/steps.zsh 00"
}

step_01() {
  say "[01] Main. probe: the Leader leaves one detached process and ends its turn. Dialog: none expected. ~5 min."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  local C=$(claude_bin) NONCE=$($VV/bin/python -I -c 'import uuid; print(uuid.uuid4().hex[:12])')
  print -r -- $NONCE > $BASE/nonce
  local tool="($VV/bin/python -c 'import time; time.sleep(600)' probe450-$NONCE >/dev/null 2>&1 &); echo started"
  local member="Run exactly one Bash command, exactly as written: $tool -- then reply with exactly STARTED and end your turn. Run nothing else."
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  # 471: a fresh 01 stream (its creation time is this dispatch's time); PROBE_OUT lets the probe find it
  # and the swarm result (which member this dispatch created).
  local W="env PROBE_OUT=$OUT $VV/bin/python $SD/probe.py wait $P 100"
  rm -f $OUT/01-main-stream.jsonl
  print "nonce: $NONCE; dispatch at $(date +%T)"
  (cd $P && print -r -- "Call mcp__agents__tasks once with exactly these arguments: $swarm
Then send nothing to any Agent. Run this exact Bash command, one run after another, at most three times, and stop
running it as soon as its output says 'termination record present':
$W
Then print DONE and stop." \
    | clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
        --allowedTools "mcp__agents__tasks,Bash($W)" > $OUT/01-main-stream.jsonl 2> $OUT/01-main-stderr.txt)
  print "claude -p rc=$? at $(date +%T); Main stream: $OUT/01-main-stream.jsonl"
  step_02
}

step_02() {
  say "[02] Main. observe (read only; signals nothing). Dialog: none."
  [[ -f $BASE/nonce ]] || { print "STOP: no nonce; run 01 first"; return 1; }
  (cd $P && clean PROBE_OUT=$OUT $VV/bin/python -I $SD/probe.py observe $P probe450-$(cat $BASE/nonce)) | tee $OUT/02.txt
  local rc=${pipestatus[1]}
  print ""
  print "Success: 'CRITERION PASS': the tagged pid is in escaped_processes.found and .stopped, and no tagged process is alive."
  print "If a tagged process is still alive, leave it: it exits by itself 600 s after 01 started it."
  print "If 'NO termination record': the Leader never ended; read $OUT/01-main-stream.jsonl for the swarm result."
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. ~15-20 min (6 shards)."
  local head=$(git -C $WT rev-parse HEAD) built=$(cat $BASE/src-commit 2>/dev/null)
  [[ $built == $head ]] || { print "STOP: scratch venv was built from '${built:-unknown}', not HEAD $head; rerun 00 first"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  (cd /tmp && $VV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee $OUT/03-suite.txt
  # The suite runs from the Worktree (HEAD); the editable venv resolves $SRC, an archive of the same commit.
  (cd $WT && nohup $VV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $OUT/03-shards >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time):"
  print "  tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows a line like 'N failed, N passed, N skipped'; failing IDs are in $OUT/03-shards/failures.txt."
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 ;;
  02) step_02 ;;
  03) step_03 ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
