#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 465 real-host check: with >= 1000 associated Sessions, a Runner-launched Claude member starts Bash under
# Claude Code 2.1.323 and 2.1.325, reads an associated Session through session_read, and cannot read an unassociated
# production Session file or a ~/.codex credential file. Its claude-settings.yml has no per-Session entry.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/465-bounded-team-history-read-grants/scripts/verify-465/steps.zsh <00|00u|01|02|02c|02t [task]|03|04>
# 00  Main. preflight: scratch venv from COMMIT, isolated project (own git, own .graphtraj), isolation facts,
#     the fix line, and each binary's version and one-line model/login answer.
# 00u USER, only if a member step reports a folder-trust or login refusal.
# 01  Main. seeds N (default 1000) associated Sessions + one Claude and one Codex Session in the isolated archive.
# 02  Main. fresh project only: one member under 2.1.323 (`claude` on PATH); it session_reads the seeded Claude
#     Session. Refuses (STOP, nothing dispatched) when Task 1 already has a member; then run 02c.
# 02c Main. collect-only for Task 1's existing member: same CHECKs, writes 02-facts.out.json for 03.
# 02t Main. diagnostic: an existing member's tool calls and is_error flags (02t 2 for Task 2); no content.
# 03  Main. adds 500 more associations, then one member under 2.1.325 (explicit path through a link directory under
#     the base; ~/.local/bin/claude is never changed); it session_reads the 02 member's Session.
# 04  Main. full suite at HEAD in the background (self-stopping after 25 min; ends with '== totals:').
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only), the user's
# dotfiles, ~/.claude, ~/.codex or the Claude install. No key value is read or printed. No step signals a process.
# Rehearsal without a model: VERIFY465_NO_MODEL=1 VERIFY465_BASE=... VERIFY465_OUT=... (00 stops before Claude Code;
# 01 runs fully; 02/03 stop before dispatch).
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/465-bounded-team-history-read-grants
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY465_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY465_BASE:-$H/tmp/465}
OUT=${VERIFY465_OUT:-$H/.graphtraj/core/state/tasks/465-bounded-team-history-read-grants/realhost}
N=${VERIFY465_N:-1000}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
C325=/Users/luoxiao/.local/share/claude/versions/2.1.325
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
HIST=$BASE/histories
BIN325=$BASE/bin-2.1.325
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next ($1 pastes): $2"; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${P465PATH:-${(j.:.)path}} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
}
probe() { (cd $P && clean $VV/bin/python -I $SD/probe.py "$@") }
# An unassociated production Session file (path only; never read here) and the credential file name.
unassociated() {
  [[ -n ${VERIFY465_UNASSOCIATED:-} ]] && { print -r -- $VERIFY465_UNASSOCIATED; return; }
  # A finished production Claude Main Session (not this Main's live one); the oldest file if it is gone.
  local D=$HOME/.claude/projects/-Users-luoxiao-workspace-you-are-a-product-architect-delivery
  local F=($D/f3ce62db-d94b-4ba0-87c3-0238fcd12b61.jsonl(N) $D/*.jsonl(N.Om[1]))
  print -r -- ${F[1]:-$D/none.jsonl}
}
CRED=$HOME/.codex/auth.json

model_line() {  # $1 binary, $2 label
  local B=$1 L=$2
  print "$L: $($B --version 2>&1 | head -1)"
  [[ -n ${VERIFY465_NO_MODEL:-} ]] && return 0
  (cd $P && clean $B -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly: MODEL OK' > $OUT/00-model-$L.jsonl 2> $OUT/00-model-$L-stderr.txt)
  print "claude -p rc=$?"
  $VV/bin/python -I -c 'import json,sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d.get("type") == "result": print("result:", d.get("result"), "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))' $OUT/00-model-$L.jsonl \
      || { print "STOP: no stream. stderr:"; head -c 300 $OUT/00-model-$L-stderr.txt; return 1; }
  $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-$L.jsonl -
}

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  print "commit under test: $COMMIT | base: $BASE"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import inspect, graphtraj.runtimes.claude.execution as e, graphtraj.runtimes.codex.access as a
print("execution:", e.__file__)
fixed = "project_history_files" not in inspect.getsource(e.ClaudeExecution.native_settings) and "history=False" in inspect.getsource(a.member_project_reads)
print("465 fix loaded:", "YES" if fixed else "NO")') || return 1
  say "isolated project $P (own git init, own .graphtraj from graphtraj setup)"
  rm -rf $P $HIST; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 465 probe" > README.md && git add README.md \
      && git -c user.name=465 -c user.email=465@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  probe prepare $P $MODEL || { print "STOP: probe Tasks are not ready (text above)"; return 1; }
  probe isolation $P - || { print "STOP: the project is not isolated"; return 1; }
  say "binaries (2.1.325 by explicit path; ~/.local/bin/claude is not changed)"
  mkdir -p $BIN325; ln -sfn $C325 $BIN325/claude
  model_line ${$(command -v claude):-$HOME/.local/bin/claude} 2.1.323 || return 1
  model_line $BIN325/claude 2.1.325 || return 1
  print "unassociated production Session file (path only): $(unassociated) | exists: $([[ -f $(unassociated) ]] && print yes || print no)"
  print "credential file checked by the member (never read here): $CRED | exists: $([[ -e $CRED ]] && print yes || print no)"
  print ""
  print "Success: '465 fix loaded: YES', 'roles OK', ready tasks ['1', '2'], 'isolation: OK',"
  print "'2.1.323: 2.1.323 (Claude Code)' and '2.1.325: 2.1.325 (Claude Code)', each 'result: MODEL OK' with $MODEL and an init line."
  next Main "zsh $THIS 01 2>&1 | tee $OUT/01.txt"
}

step_00u() {
  say "[00u] USER, only if 02 or 03 reports a folder-trust or login refusal. Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'. Then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message. Any other dialog: Esc, and tell Main its title."
  next Main "the step that refused, again"
}

step_01() {
  say "[01] Main. seed $N associated Sessions under $HIST and the isolated archive. Dialog: none."
  [[ -x $VV/bin/agent-runner ]] || { print "STOP: run 00 first"; return 1; }
  probe seed $P $N:$HIST || return 1
  (cd $P && clean $VV/bin/graphtraj doctor | grep -E 'roles|runner|ERROR' | head -5)
  print ""
  print "Success: 'associated JSONL files (project_history_files): $N' (or more) and both SEEDED IDs printed."
  next Main "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

member_step() {  # $1 task, $2 label, $3 expected version, $4 session_read target, $5 PATH prefix
  local F=$OUT/$2-facts.json
  $VV/bin/python -I -c 'import json, sys; json.dump(dict(zip(("task","label","expect_version","target","unassociated","credential"), sys.argv[2:])), open(sys.argv[1], "w"))' \
      $F $1 $2 $3 $4 "$(unassociated)" $CRED
  if [[ -n ${VERIFY465_NO_MODEL:-} ]]; then print "VERIFY465_NO_MODEL set: stopping before dispatch."; cat $F; return 0; fi
  P465PATH=$5:${(j.:.)path} probe run $P $F
}

step_02() {
  say "[02] Main. one member under 2.1.323 ($(command -v claude)); waits <= 9 min. Dialog: none."
  local T=$($VV/bin/python -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import probe; print(probe.SEEDED_CLAUDE)' $SD)
  print "session_read target: the seeded Claude Session $T in the isolated archive"
  member_step 1 02 2.1.323 $T ${$(command -v claude):h}
  local rc=$?
  print ""
  if (( rc == 2 )); then
    print "Task 1 already has its 2.1.323 member: collect it without dispatching."
    next Main "zsh $THIS 02c 2>&1 | tee $OUT/02c.txt"
    return $rc
  fi
  print "Success: '== summary: ALL PASS' (CHECK 1-7), and the settings line (allowRead, allow, deny, bytes) with 'seeded paths present': 0."
  next Main "zsh $THIS 03 2>&1 | tee $OUT/03.txt"
  return $rc
}

step_02c() {
  say "[02c] Main. collect-only for Task 1's existing 2.1.323 member: dispatches nothing; checks; writes 02-facts.out.json. Dialog: none."
  [[ -f $OUT/02-facts.json ]] || { print "STOP: no $OUT/02-facts.json; run 02 on a fresh project instead"; return 1; }
  # The first 02 run did not keep agent-runner's stdout; its 'settled: ... native=...' line names the Session.
  local E=${VERIFY465_EXPECT_SESSION:-$(grep -o 'native=[0-9a-f-]*' $OUT/02.txt 2>/dev/null | tail -1 | cut -d= -f2)}
  print "expected member Session (from 02.txt unless a dispatch record exists): ${E:-none}"
  $VV/bin/python -I -c 'import json, sys; f = json.load(open(sys.argv[1])); f["expect_session"] = sys.argv[2]; json.dump(f, open(sys.argv[1], "w"))' \
      $OUT/02-facts.json "$E" || return 1
  if [[ -n ${VERIFY465_NO_MODEL:-} ]]; then print "VERIFY465_NO_MODEL set: stopping before collect."; cat $OUT/02-facts.json; return 0; fi
  P465PATH=${$(command -v claude):h}:${(j.:.)path} probe collect $P $OUT/02-facts.json
  local rc=$?
  print ""
  print "Success: the 'identity:' line shows the same session on both sides, '== summary: ALL PASS' (CHECK 1-7),"
  print "and the settings line with 'seeded paths present': 0."
  next Main "zsh $THIS 03 2>&1 | tee $OUT/03.txt"
  return $rc
}

step_02t() {  # $1 task (default 1): diagnostic only; reads the archive, dispatches and signals nothing
  local T=${1:-1} F=$OUT/02-facts.json
  [[ $T == 2 ]] && F=$OUT/03-facts.json
  say "[02t] Main. tool calls of Task $T's existing member (names, file_path/command, is_error; no successful content). Dialog: none."
  [[ -f $F ]] || { print "STOP: no $F"; return 1; }
  probe tools $P $F
  local rc=$?
  next Main "zsh $THIS 03 2>&1 | tee $OUT/03.txt   (if 03 has not run yet)"
  return $rc
}

step_03() {
  say "[03] Main. +500 associations, then one member under 2.1.325 ($C325 via $BIN325/claude); waits <= 9 min. Dialog: none."
  [[ -f $OUT/02-facts.out.json ]] || { print "STOP: run 02 first"; return 1; }
  probe seed $P 500:$HIST || return 1
  local T=$($VV/bin/python -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["native"])' $OUT/02-facts.out.json)
  print "session_read target: the 02 member's own Claude Session $T"
  member_step 2 03 2.1.325 $T $BIN325
  local rc=$?
  say "settings counts at N and N+500 (must be equal except bytes, which differ only by path lengths)"
  $VV/bin/python -I -c 'import json, sys
a, b = (json.load(open(f)) for f in sys.argv[1:])
keys = ("allow", "deny", "additionalDirectories", "allowRead", "denyRead", "allowWrite", "denyWrite")
print("02:", a["seeded"], {k: a["settings"].get(k) for k in keys + ("bytes",)})
print("03:", b["seeded"], {k: b["settings"].get(k) for k in keys + ("bytes",)})
print("counts independent of N:", all(a["settings"].get(k) == b["settings"].get(k) for k in keys))' $OUT/02-facts.out.json $OUT/03-facts.out.json
  print ""
  print "Success: '== summary: ALL PASS' and 'counts independent of N: True'."
  next Main "zsh $THIS 04"
  return $rc
}

step_04() {
  say "[04] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV > $OUT/04-suite.txt 2>&1 || { cat $OUT/04-suite.txt; return 1; }
  cat $OUT/04-suite.txt
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee -a $OUT/04-suite.txt
  rm -rf $OUT/04-shards
  (cd $WT && nohup zsh $THIS _04run >> $OUT/04-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time): tail -n 25 $OUT/04-suite.txt"
  print "Done when it shows '== totals:'; failing IDs are in $OUT/04-shards/failures.txt."
}

step__04run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit (only what this step started).
  clean $SV/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $OUT/04-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $OUT/04-suite.txt | tail -1)"
  print "== baseline: compare with the dev full-suite run Main last used"
  print "== failures:"; cat $OUT/04-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 ;;
  02) step_02 ;;
  02c) step_02c ;;
  02t) step_02t ${2:-1} ;;
  03) step_03 ;;
  04) step_04 ;;
  _04run) step__04run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|02c|02t [task]|03|04>" ;;
esac
