#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 455 checks: the full suite of this Worktree's HEAD, and one real-host child created with configuration
# 'advisor' whose create/status/retire results, record and native Session show the preset's model and effort.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/455-agents-child-preset-not-recorded/scripts/verify-455/steps.zsh <S|00|00u|01|02>
# S   Main. full suite at HEAD, 6 shards, --timeout 1500, in the background; refuses while another run_test_shards runs.
# 00  Main. preflight: scratch venv from COMMIT, isolated project, one-line model/login answer, plugin, roles, Task ready.
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust.
# 01  Main. starts a `claude -p` Main in the background: swarm -> member creates one child with configuration advisor,
#     waits for its end, reads its status, retires it and reports the raw results; Main then retires the member.
# 02  Main. waits (<= 9 min) for that Main to end, then prints one CHECK PASS/FAIL per criterion.
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex (the child's Session file is only read). No key value is read or printed.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/455-agents-child-preset-not-recorded
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY455_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY455_BASE:-$HOME/graphtraj-verify-455}
OUT=${VERIFY455_OUT:-$H/.graphtraj/core/state/tasks/455-agents-child-preset-not-recorded/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
# VERIFY455_CLAUDE names a stub host for a rehearsal without a model.
claude_bin() { [[ -n ${VERIFY455_CLAUDE:-} ]] && { print -r -- $VERIFY455_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
# click 8.5.0, yaml and websockets from production, copied (never changed there) into a venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
  [[ $(cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print(m.version("click"))') == 8.5.0 ]] \
    || { print "STOP: click in $1 is not production's 8.5.0"; return 1; }
}

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import graphtraj.interfaces.agents as a; import graftling.control as c, inspect; print("agents module:", a.__file__, "| 455 records configuration:", "\"configuration\"" in inspect.getsource(c.AgentControl._document))') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  # Same path every run (trust is per path); keep any per-project approval Claude Code wrote there.
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 455 probe" > README.md && git add README.md \
      && git -c user.name=455 -c user.email=455@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  (cd $P && clean $VV/bin/python -I $SD/probe.py prepare $P $MODEL) || { print "STOP: probe Task is not ready (text above)"; return 1; }
  [[ -n ${VERIFY455_NO_MODEL:-} ]] && { print "VERIFY455_NO_MODEL set: stopping before Claude Code (rehearsal)."; return 0; }
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
  say "plugin check: the init record must list graphtraj-claude-host"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"
    return 1
  fi
  print "Success: '455 records configuration: True', deps click 8.5.0, 'roles OK', 'task 1 ready', result 'MODEL OK' with $MODEL,"
  print "and 'graphtraj-claude-host loaded: YES'."
  next "zsh $THIS 01"
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: folder trust is recorded only through this dialog; claude -p never asks, and Main must not edit ~/.claude.json."
  next "Main: zsh $THIS 00"
}

step_01() {
  say "[01] Main. starts the probe Main in the background. Dialog: none. Returns at once; then run 02 (~3-6 min)."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  local C=$(claude_bin) S=$OUT/01-main-stream.jsonl
  local member='Use only the agents tool (mcp__agents__agents). 1. Execute feature create with arguments {"runtime": "claude", "configuration": "advisor", "instruction": "Reply with exactly PONG-455 and nothing else. Call no tool."}. 2. Execute feature wait with arguments {"agent": "<the agent of that result>", "timeout_seconds": 240}; if it is still active, call wait the same way once more. 3. Execute feature status with arguments {"agent": "<that agent>"}. 4. Execute feature retire with arguments {"agent": "<that agent>"}. Then end with a final reply holding, each on its own line: CREATE-RESULT followed by the raw create result text; WAIT-RESULT followed by the raw last wait result text; STATUS-RESULT followed by the raw status result text; RETIRE-RESULT followed by the raw retire result text; '$END_MARK'. Copy each result text verbatim as one line. Read no files and run no shell command.'
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  print -r -- "$swarm" > $OUT/01-swarm-arguments.json
  local W="$VV/bin/python $SD/probe.py wait $P 100"
  print -r -- "1. Call mcp__agents__tasks once with exactly these arguments: $swarm
Print its raw result text on one line starting with SWARM-RESULT.
2. Send nothing to the member. Ignore any notice from it. Run this exact Bash command, one call after another, until one prints MEMBER-DONE, at most 5 times: $W
3. Take the value of the field agent in the swarm result. Call mcp__agents__agents with {\"action\": \"execute\", \"feature\": \"retire\", \"arguments\": {\"agent\": \"<that value>\"}} and print its raw result starting with RETIRE-MEMBER. If the swarm result has no field agent, print NO-AGENT instead.
4. Print DONE and stop." > $OUT/01-main-prompt.txt
  print "dispatch at $(date +%T); prompt: $OUT/01-main-prompt.txt"
  (cd $P && clean nohup $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      --allowedTools "mcp__agents__tasks,mcp__agents__agents,Bash($W)" < $OUT/01-main-prompt.txt > $S 2> $OUT/01-main-stderr.txt &
   print $! > ${S:r}.pid)
  print "Main claude -p pid $(cat ${S:r}.pid), stream $S"
  print "Fallback: if 02 finds no member report, read $S and $OUT/01-main-stderr.txt (head -c 2000)."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. observe (read only, waits up to 9 min for the probe Main to end). Dialog: none."
  (cd $P && clean $VV/bin/python -I $SD/probe.py observe $P $OUT/01-main-stream.jsonl)
  local rc=$?
  local left=$(ps -axww -o pid=,command= 2>/dev/null | grep -F "$P" | grep -vE 'grep|steps.zsh')
  print -r -- "processes still naming $P: ${left:-none}"
  print ""
  print "Success: 'summary: ALL PASS'. Criteria: CREATE/STATUS/RETIRE results and the child's record show"
  print "configuration=advisor, model=$MODEL, reasoning_effort=high; the record keeps no 'applied'; the child's native"
  print "Session names only $MODEL and effort high."
  print "Fallbacks: 'still running after 9 min' -> rerun 02. No member report -> read $OUT/01-main-stream.jsonl."
  print "A line under 'processes still naming' -> send it to the Leader (nothing should be left running)."
  [[ $rc == 0 ]] && next "send $OUT/02.txt to the Leader" || next "send $OUT/02.txt and $OUT/01-main-stream.jsonl to the Leader"
  return $rc
}

step_S() {
  say "[S] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. Returns at once."
  [[ -z $(git -C $WT status --porcelain -- src tests) ]] || { print "STOP: uncommitted changes in $WT src/tests"; return 1; }
  print "loadavg: $(sysctl -n vm.loadavg 2>/dev/null)"
  local others=$(ps -axww -o pid=,etime=,command= 2>/dev/null | grep -E 'pytest|run_test_shards' | grep -vE 'grep|steps.zsh')
  print -r -- "other pytest / run_test_shards processes: ${others:-none}"
  [[ $others == *run_test_shards* ]] && { print "STOP: another run_test_shards is running; Main decides when to rerun S."; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV || return 1
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee $OUT/S-setup-imports.txt
  grep -qF "graphtraj.__file__ = $WT/" $OUT/S-setup-imports.txt || { print "STOP: graphtraj is not imported from $WT"; return 1; }
  rm -rf $OUT/S-shards; : > $OUT/S-suite.txt
  (cd $WT && nohup zsh $THIS _Srun >> $OUT/S-suite.txt 2>&1 &)
  print "started at $(date +%T) (~15-25 min). Status (Main, any time): tail -n 25 $OUT/S-suite.txt"
  print "Done when it shows '== DONE'. Success: no line starting with 'NEW '."
  next "zsh $THIS 00   (S keeps running in the background)"
}

step__Srun() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) loadavg $(sysctl -n vm.loadavg 2>/dev/null)"
  (cd $WT && clean $SV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $OUT/S-shards); print "== shards exit $?"
  print "== totals: $(grep -E '^[0-9]+ (failed|errors|passed)' $OUT/S-suite.txt | tail -1)"
  print "== baseline 0e099ac3 (453 adoption/raw/S-suite.txt): 3972 passed, 71 skipped, 0 failed; so every failure is NEW"
  local id ids=(${(f)"$(sed -n 's/^FAILED //p; s/^ERROR //p' $OUT/S-shards/failures.txt 2>/dev/null | sed 's/ - .*//' | sort -u)"})
  for id in $ids; do print "NEW $id"; done
  (( ${#ids} )) || print "(no failures)"
  print "== each failure alone (-rA):"
  for id in $ids; do
    local out=$(cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q -rA "$id" 2>&1)
    print "$(print -r -- "$out" | grep -oE '^(PASSED|FAILED|SKIPPED|ERROR)' | head -1) alone: $id"
  done
  print "== DONE $(date +%T)"
}

END_MARK=REPORT-455-END
case $STEP in
  S) step_S 2>&1 | tee $OUT/S.txt ;;
  _Srun) step__Srun ;;
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  *) print "usage: zsh ${0:A} <S|00|00u|01|02>" ;;
esac
