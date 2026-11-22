#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 574 Main-run steps: a Claude child requested with the alias `haiku` or the full id `claude-haiku-5-5`.
# ACCEPTANCE ENTRY (user rule 2026-11-23): every judged step below goes through the entry users use. A real Claude
# Code Main (`claude -p`, the user's own login), graftling pip-installed from the pinned commit into a venv, its Claude
# Code host written by `graftling.claude.host configuration --write` and loaded as in Task 570 launch (b)
# (--mcp-config + --plugin-dir), the model itself calling the real mcp__graftling__agents tool (create, wait,
# status), and a real Claude child. The verdicts read the agent records under <project>/.agents-control and the tool
# results in the Main's own stream-json output; none echoes expected text, and each can fail. No stub, fake or direct
# call of graftling's API is used here. A step that cannot run for real is reported unaccepted, never replaced.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   preflight  Main. Versions (zsh, python, git, claude, `claude --help` offers --plugin-dir); creates ROOT; a
#              one-line `claude -p` in ROOT/pre with the Main's flags naming its model.
#              Run as `VERIFY574_CLAUDE_USER_LOGIN=1 zsh <this file> preflight`. Dialog: none expected. ~30 s.
#   repro      Main. The BASE (graftling dev cadc419, before 574): pip-installs it into ROOT/venv-base, writes the
#              Claude Code host for ROOT/proj-base, dumps Claude's own initialize model catalog (model entries in full;
#              supporting data only), then two real Mains each create+wait+status one Claude child: model `haiku`
#              (expected: accepted, the child fails RUNTIME_REQUEST_FAILED 'requested model haiku, observed model
#              claude-haiku-...') and model `claude-haiku-5-5` (expected: invalid-model 'is not a candidate of the
#              native claude login', no record). SUCCESS = both old failures reproduce.
#              Run as `VERIFY574_CLAUDE_USER_LOGIN=1 zsh <this file> repro`. Dialog: none expected. ~3-5 min.
#   suite      Main. graftling's full suite on the FIX commit (a clean clone in ROOT/suite-src, editable install
#              plus pytest in ROOT/venv-suite, as README says), TMPDIR=${TMPDIR:-/tmp}. No Claude login. ~5-15 min.
#   verify     Main. The FIX commit pip-installed into ROOT/venv-fix, host for ROOT/proj-fix; three real Mains:
#              `haiku` and `claude-haiku-5-5` each create AND wait to completion with a reply (record keeps the
#              requested model, an alias also shows resolved_model claude-haiku-..., also in the status result), and
#              `claude-haiku-9-9` (not a resolution of any catalog alias) is still refused invalid-model with no record.
#              Run as `VERIFY574_CLAUDE_USER_LOGIN=1 zsh <this file> verify`. Dialog: none expected. ~4-6 min.
# The user's Claude login (VERIFY574_CLAUDE_USER_LOGIN=1, required by preflight/repro/verify; STOP without it):
# Claude Code reads the macOS keychain login and ~/.claude.json, and writes Session transcripts under
# ~/.claude/projects/-private-tmp-graftling-574-*/ and a project entry per ROOT/<dir> in ~/.claude.json. The Main
# runs with --setting-sources project,local --strict-mcp-config, so no user settings, plugins or MCP servers load.
# Nothing else under ~/.claude is written by these steps; each step lists (names only) every ~/.claude entry that
# changed during it, so whatever Claude Code itself touched is visible. Network: pip downloads setuptools, PyYAML,
# websockets (and pytest for suite) from PyPI; Claude Code talks to Anthropic.
# VERIFY574_ROOT / VERIFY574_OUT / VERIFY574_GREPO / VERIFY574_BIN are for the Engineer's rehearsal only; a run with
# them set (or with stubs) is a rehearsal, not acceptance evidence.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY574_ROOT:-/private/tmp/graftling-574}
OUT=${VERIFY574_OUT:-$H/.graphtraj/core/state/tasks/574-graftling-claude-model-alias-and-candidate-mismatch/realhost}
GREPO=${VERIFY574_GREPO:-$WT/.scratch/574/graftling}  # the Engineer's graftling clone holding BASE and FIX
BASE=cadc419271dabc8f4a0b11da1bb46c70ef598c77      # graftling dev before 574 (v0.7.0 + 570)
FIX=''                                              # the 574 fix commit on agent/574-...; set by the Engineer
THIS=${0:A}
STEP=${1:-}
PY=${VERIFY574_PYTHON:-python3}
path=(${VERIFY574_BIN:+$VERIFY574_BIN} /opt/homebrew/bin $path)
JUDGE=${0:A:h}/judge.py
MMODEL=claude-haiku-5-5                             # the Main's own model (as in 570); the child's model varies
CLAUDE=''

say() { print -r -- "== $*"; }
# Claude Code with no inherited agents channel or Claude Code session markers; the user's own login.
claude_iso() {
  env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u DSH_AGENT_PACKAGE -u GRAFTLING_DSH_CONFIG -u DSH_SESSION_ID \
      -u DSH_AGENT_SOURCE -u GRAFTLING_NATIVE_RUNTIME -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT "$@"
}
login_gate() {
  [[ -n ${VERIFY574_CLAUDE_USER_LOGIN:-} ]] || {
    print -r -- "STOP: this step uses the user's own Claude login; Main asks the user first, then runs:"
    print -r -- "  VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"
    return 1 }
  CLAUDE=$(command -v claude)
  [[ -n $CLAUDE ]] || { print "STOP: no claude on PATH"; return 1; }
  print -r -- "VERIFY574_CLAUDE_USER_LOGIN=1: Claude Code uses the user's own login. It reads the keychain and ~/.claude.json,"
  print -r -- "and writes Session transcripts under ~/.claude/projects/-private-tmp-graftling-574-*/ and a project entry"
  print -r -- "per directory under $ROOT in ~/.claude.json. No settings, plugins or skills under ~/.claude are written."
  : > $ROOT/.claude-marker-$STEP
}
claude_outside() {  # names only: what changed under ~/.claude and the ~/.claude.json project keys under ROOT
  say "what changed outside $ROOT during this step (names only; no values printed)"
  print -r -- "~/.claude entries newer than the step start (depth 2): $(find $HOME/.claude -maxdepth 2 -newer $ROOT/.claude-marker-$STEP 2>/dev/null | sed "s|^$HOME|~|" | tr '\n' ' ')"
  print -r -- "~/.claude/projects directories naming ${ROOT:t}: $(print -l -- $HOME/.claude/projects/*${ROOT:t}*(N/:t) | tr '\n' ' ')"
  $PY -I -c 'import json, sys
p = json.load(open(sys.argv[1])).get("projects") or {}
print("~/.claude.json project keys under", sys.argv[2] + ":", [k for k in p if k.startswith(sys.argv[2])])' \
    $HOME/.claude.json ${ROOT:A} 2>&1
}
# pip-install graftling at commit $2 into venv $1, the way users install a pinned commit; checks the commit.
install_at() {
  local venv=$1 sha=$2 log=$ROOT/pip-${1:t}.txt
  if [[ ! -x $venv/bin/python ]]; then
    $PY -m venv $venv || { print "STOP: $PY -m venv failed"; return 1; }
  fi
  say "pip install 'graftling @ git+file://$GREPO@$sha' into $venv"
  $venv/bin/python -m pip install --disable-pip-version-check -q "graftling @ git+file://$GREPO@$sha" > $log 2>&1 \
    || { tail -20 $log; print -r -- "STOP: pip install failed (full output: $log)"; return 1; }
  local got=$($venv/bin/python -I -c 'import json, importlib.metadata as m
d = m.distribution("graftling"); print(d.version, json.loads(d.read_text("direct_url.json"))["vcs_info"]["commit_id"])')
  print -r -- "installed graftling: $got"
  [[ ${got#* } == $sha ]] && print -r -- "PASS: installed commit is $sha" || { print -r -- "FAIL: installed commit is not $sha"; return 1; }
}
# Write graftling's Claude Code host for project $2 with venv $1; sets LAUNCH (Task 570 launch (b)).
host_for() {
  local venv=$1 P=$2
  mkdir -p $P
  if [[ ! -f $P/.agents-control/claude-host.json ]]; then
    (cd $P && claude_iso $venv/bin/python -I -m graftling.claude.host configuration --project $P --claude $CLAUDE --write) \
      || { print "STOP: configuration --write failed"; return 1; }
  fi
  print -r -- "written: $(cd $P && print -l -- .mcp.json(N) .claude/**/*(N.D) .agents-control/claude-host.json(N) | tr '\n' ' ')"
  typeset -ga LAUNCH=(-p --setting-sources project,local --strict-mcp-config --model $MMODEL --mcp-config $P/.mcp.json
                      --allowedTools mcp__graftling__agents --plugin-dir $P/.claude/skills/agents-claude-host
                      --output-format stream-json --verbose)
}
create_prompt() {  # model word
  print -r -- 'Use the tool mcp__graftling__agents, not your own subagents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"claude","instruction":"Answer with exactly one word: '$2'.","model":"'$1'"}}
2) only if create returned an agent id: {"action":"execute","feature":"wait","arguments":{"agent":"<that agent id>","timeout_seconds":240}}
3) only if create returned an agent id: {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
Do not retry or change any argument. Then report: AGENT: the agent id or NONE; RESULT: one line with what the calls returned.'
}
# One real Main in project $1 creating a child with model $2; judged with expectation $3. Returns the judge's rc.
one_case() {
  local P=$1 model=$2 expect=$3 word=${4:-pong}
  local tag=${model//[^a-z0-9.-]/_} stamp=$(date +%H%M%S)
  local out=$ROOT/${P:t}-$tag-$stamp.jsonl snap=$ROOT/${P:t}-$tag-before.ids
  $PY -I $JUDGE snap $P/.agents-control > $snap
  say "Main in $P: create model $model (expect $expect); claude ${LAUNCH[*]} ..."
  (cd $P && claude_iso $CLAUDE $LAUNCH "$(create_prompt $model $word)" < /dev/null > $out 2> $out.err)
  local mrc=$?
  print -r -- "Main exit=$mrc (stream: $out; stderr: $out.err)"
  $PY -I -c 'import json, sys
for raw in open(sys.argv[1], errors="replace"):
    try: e = json.loads(raw)
    except ValueError: continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("  Main init: model", e.get("model"), "| agents tool listed:", "mcp__graftling__agents" in (e.get("tools") or []),
              "| mcp servers:", [(s.get("name"), s.get("status")) for s in e.get("mcp_servers") or []])
    if e.get("type") == "result": print("  Main result:", str(e.get("result"))[:400].replace("\n", " | "))' $out
  (( mrc == 0 )) && print "PASS: the Main exited 0" || print "FAIL: the Main exited $mrc"
  $PY -I $JUDGE case $out $P/.agents-control $snap $expect $model $word
  return $(( $? | (mrc != 0) ))
}
verdicts() {  # label rc ...
  local rc=0
  while (( $# )); do (( $2 == 0 )) && print -r -- "PASS: $1" || { print -r -- "FAIL: $1"; rc=1; }; shift 2; done
  return $rc
}

run_step() {
case $STEP in
preflight)
  say "[preflight] Main. Versions, ROOT, one-line claude -p with the Main's flags. Dialog: none expected. ~30 s."
  local t; for t in zsh git claude; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  print -r -- "python ($PY): $(command -v $PY) $($PY --version 2>&1)"
  $PY -c 'import sys; sys.exit(sys.version_info < (3, 12))' && print "PASS: python >= 3.12 (graftling requires it)" \
    || { print -r -- "STOP: $PY is older than 3.12; rerun with VERIFY574_PYTHON=<a python >= 3.12>"; return 1; }
  git -C $GREPO cat-file -e "$BASE^{commit}" 2>/dev/null && print -r -- "PASS: $GREPO holds BASE $BASE" \
    || { print -r -- "STOP: $GREPO lacks $BASE"; return 1; }
  mkdir -p $ROOT/pre || return 1
  login_gate || return 1
  [[ $($CLAUDE --help 2>&1) == *--plugin-dir* ]] && print "PASS: claude --help offers --plugin-dir (launch (b))" \
    || { print "STOP: claude --help offers no --plugin-dir"; return 1; }
  say "one-line check: claude -p --setting-sources project,local --strict-mcp-config --model $MMODEL in $ROOT/pre"
  local ans; ans=$(cd $ROOT/pre && claude_iso $CLAUDE -p --setting-sources project,local --strict-mcp-config --model $MMODEL \
                    "Reply in one line with the model id you are running as and nothing else." < /dev/null 2>&1)
  local crc=$?; print -r -- "answer: ${ans[1,200]}"; print -r -- "exit=$crc"
  claude_outside
  (( crc == 0 )) || { print -r -- "STOP: Claude Code did not answer; check its login, then rerun this step"; return 1; }
  print -r -- "next: VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS repro"
  ;;
repro)
  say "[repro] Main. BASE $BASE: alias haiku and full claude-haiku-5-5, each through a real Main. Dialog: none expected. ~3-5 min."
  [[ -d $ROOT/pre ]] || { print -r -- "STOP: run preflight first: VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS preflight"; return 1; }
  login_gate || return 1
  install_at $ROOT/venv-base $BASE || return 1
  local P=$ROOT/proj-base
  host_for $ROOT/venv-base $P || return 1
  say "Claude's own initialize model catalog (what graftling's discovery reads; supporting data, not a verdict)"
  (cd $P && claude_iso $PY -I $JUDGE catalog $CLAUDE $P)
  local a f
  one_case $P haiku old-alias; a=$?
  one_case $P claude-haiku-5-5 old-full; f=$?
  claude_outside
  say "verdict (computed)"
  verdicts "old failure 1 reproduced: alias haiku accepted, child failed RUNTIME_REQUEST_FAILED (requested haiku, observed claude-haiku-...)" $a \
           "old failure 2 reproduced: claude-haiku-5-5 refused before start, invalid-model 'not a candidate'" $f
  local rc=$?
  (( rc == 0 )) && print "SUCCESS: both old failures reproduce on the base through the real entry" \
    || print "NOT REPRODUCED (see the FAIL lines): report to the Leader before any fix is accepted"
  print -r -- "next: report $OUT/repro.txt to the Leader; later: zsh $THIS suite, then VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS verify"
  return $rc
  ;;
suite)
  say "[suite] Main. graftling full suite on FIX ${FIX:-<unset>}. TMPDIR=${TMPDIR:-/tmp}. Dialog: none. ~5-15 min."
  [[ -n $FIX ]] || { print "STOP: FIX is not set yet in this script"; return 1; }
  mkdir -p $ROOT || return 1
  local src=$ROOT/suite-src log=$ROOT/suite-pytest.txt
  rm -rf $src; git clone -q $GREPO $src && git -C $src checkout -q $FIX || { print "STOP: cannot check out $FIX"; return 1; }
  print -r -- "suite source: $src at $(git -C $src rev-parse HEAD)"
  [[ -x $ROOT/venv-suite/bin/python ]] || $PY -m venv $ROOT/venv-suite || return 1
  (cd $src && $ROOT/venv-suite/bin/python -m pip install --disable-pip-version-check -q -e . pytest) > $ROOT/pip-suite.txt 2>&1 \
    || { tail -20 $ROOT/pip-suite.txt; print "STOP: pip install -e . pytest failed"; return 1; }
  print -r -- "imports graftling from: $($ROOT/venv-suite/bin/python -I -c 'import graftling; print(graftling.__file__)')"
  print -r -- "TMPDIR=${TMPDIR:-/tmp} (tests' tmp_path lives there)"
  (cd $src && TMPDIR=${TMPDIR:-/tmp} $ROOT/venv-suite/bin/python -m pytest -q -p no:cacheprovider ${VERIFY574_PYTEST_ARGS:-}) > $log 2>&1
  local prc=$?
  tail -30 $log; print -r -- "pytest exit=$prc (full output: $log)"
  (( prc == 0 )) && print "SUCCESS: graftling suite passed on FIX" || print "FAIL: the suite failed; compare the failures with dev $BASE"
  print -r -- "next: VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS verify"
  return $prc
  ;;
verify)
  say "[verify] Main. FIX ${FIX:-<unset>}: alias haiku and full claude-haiku-5-5 complete; claude-haiku-9-9 refused. Dialog: none expected. ~4-6 min."
  [[ -n $FIX ]] || { print "STOP: FIX is not set yet in this script"; return 1; }
  [[ -d $ROOT/pre ]] || { print -r -- "STOP: run preflight first: VERIFY574_CLAUDE_USER_LOGIN=1 zsh $THIS preflight"; return 1; }
  login_gate || return 1
  install_at $ROOT/venv-fix $FIX || return 1
  local P=$ROOT/proj-fix
  host_for $ROOT/venv-fix $P || return 1
  local a f n
  one_case $P haiku completed; a=$?
  one_case $P claude-haiku-5-5 completed; f=$?
  one_case $P claude-haiku-9-9 refused; n=$?
  claude_outside
  say "verdict (computed)"
  verdicts "alias haiku: child created and completed; record keeps model haiku and shows its resolved model" $a \
           "full claude-haiku-5-5: child created and completed" $f \
           "negative claude-haiku-9-9: refused invalid-model before start, no record" $n
  local rc=$?
  (( rc == 0 )) && print "SUCCESS: alias and full name both work through the real entry; an unknown full id is still refused"
  print -r -- "next: report $OUT/verify.txt to the Leader"
  return $rc
  ;;
*) print -r -- "usage: zsh $THIS preflight|repro|suite|verify"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY574_OUT:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT $ROOT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
{ run_step; print -r -- "STEP-END rc=$?"; } 2>&1 | tee $OUT/$STEP.txt
local rc=$?
grep -q '^STEP-END rc=0$' $OUT/$STEP.txt || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT/$STEP.txt; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
