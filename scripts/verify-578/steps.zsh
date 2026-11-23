#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 578 Main-run steps: a Claude child created through the agents tool is failed with RUNTIME_REQUEST_FAILED
# 'Claude did not confirm the requested permission mode' when its system/init reports default for a requested auto.
#   zsh scripts/verify-578/steps.zsh <STEP>      (Main, from this Task's Worktree; one step at a time)
# Order: pre -> Tu (USER) -> repro -> [push, after the user agrees] -> check.
#   pre    Versions (zsh, python3, git, claude --version). Builds graftling base 99a66ae (dev, from <Harness>/graftling)
#          as a wheel into ROOT/venv-base; creates ROOT/proj-base and ROOT/proj-cand (STOP if either exists) and
#          writes the plugin files into proj-base (`configuration --write`, docs: Generate the plugin files). A
#          one-line `claude -p` in ROOT prints its model and apiKeySource (user login). Dialog: none. ~2 min.
#   Tu     USER, in a plain Terminal: trust ROOT/proj-base and ROOT/proj-cand in Claude Code's own dialog, then
#          /exit (an untrusted folder suppresses the project plugin, Task 576). The step only reads ~/.claude.json
#          and reports whether both folders are trusted. Dialog: Claude Code's trust dialog, twice.
#   repro  BASE. (a) DIAGNOSIS: per model in DIAG_MODELS, DIAG_RUNS direct runs of
#          `claude -p --permission-mode auto --model M --output-format stream-json --verbose --debug` (one-word
#          prompt, empty MCP config) in ROOT/diag; prints each init permissionMode and the stderr lines about auto
#          mode, and a per-model tally: the CONDITION under which Claude reports another mode. (b) ACCEPTANCE premise:
#          one real `claude -p` parent in proj-base creates four children through mcp__graftling__agents (inline
#          arguments, tools [Bash], each asked to run `echo r578-bash` and reply): A, B claude-haiku-4-5-20251001,
#          C claude-haiku-5-5, D the control CONTROL_MODEL. Per child: requested/observed mode, whether the work
#          ran, outcome and error. REPRODUCED only when at least one child's observed mode differs. Dialog: none.
#          ~4-6 min (model calls: DIAG_MODELS x DIAG_RUNS one-word runs, one parent, four children).
#   push   Main, after asking the user: pushes the candidate branch from the bundle to LUOXIAO92/graftling (backup).
#          Not needed by check. Dialog: none expected. ~30 s.
#   check  CANDIDATE (CAND, from this Worktree's .scratch/578/graftling-578.bundle) in ROOT/venv-cand and
#          ROOT/proj-cand, the same parent and children. Per child: matching mode -> completed and the work ran;
#          observed NARROWER than requested (default/manual/plan/dontAsk for auto) -> completed, the work ran,
#          session.yml permissions show matches_request false and narrower true, and the diagnostics carry the
#          warning permission_mode_narrower; WIDER or not comparable -> failed with the permission-mode error. It
#          FAILS (inconclusive) when no child showed a completed narrower mode. Dialog: none. ~4 min.
# User login: pre, repro and check run Claude Code with the user's own login and run only with
# VERIFY578_CLAUDE_USER_LOGIN=1 (Main asks the user first). Claude Code then reads the keychain, ~/.claude.json and
# ~/.claude settings as any start does and writes Session transcripts under ~/.claude/projects/-private-tmp-graftling-578*/
# and project entries in ~/.claude.json; each step lists the ~/.claude entries changed during it (names only).
# Nothing is installed under ~/.claude; no dotfile, no host installation is changed.
# Writes: ROOT=/private/tmp/graftling-578 and step output under <Harness>/tmp/578/<step>-<time>/.
# VERIFY578_ROOT, VERIFY578_OUT, VERIFY578_BIN (a stub claude, script check only), VERIFY578_H are for the
# Engineer's rehearsal, as is VERIFY578_OFFLINE_DEPS. VERIFY578_DIAG_MODELS / VERIFY578_DIAG_RUNS / VERIFY578_CONTROL_MODEL override the defaults.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)
H=${VERIFY578_H:-${WT:h:h:h:h}}                       # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY578_ROOT:-/private/tmp/graftling-578}
OUTBASE=${VERIFY578_OUT:-$H/tmp/578}
STEP=${1:-}
JUDGE=$SD/judge578.py
URL=https://github.com/LUOXIAO92/graftling.git
LOCAL=$H/graftling                                     # the Harness's graftling repository (read only)
BASE=99a66ae9beefa22cae23c02213b2dbeaaf80dd02          # graftling dev (0.7.0 + 570/572/574/576)
BRANCH=agent/578-claude-child-permission-mode-mismatch-fails-run
CAND=''                                                # the candidate commit; set by the Engineer
BUNDLE=$WT/.scratch/578/graftling-578.bundle
PMODEL=${VERIFY578_PARENT_MODEL:-claude-sonnet-5-5}
CONTROL=${VERIFY578_CONTROL_MODEL:-claude-opus-5-5}
DIAG_MODELS=(${=${VERIFY578_DIAG_MODELS:-claude-haiku-4-5-20251001 claude-haiku-5-5 claude-sonnet-5-5 claude-opus-5-5}})
DIAG_RUNS=${VERIFY578_DIAG_RUNS:-3}
path=(${VERIFY578_BIN:+$VERIFY578_BIN} $HOME/.local/bin $path)
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')

say() { print -r -- "== $*"; }
next() { print -r -- "next (paste): $*"; }
need_login() {
  [[ -n ${VERIFY578_CLAUDE_USER_LOGIN:-} ]] && {
    print -r -- "VERIFY578_CLAUDE_USER_LOGIN=1: the user's own Claude login (Main asked the user). Reads and writes: see this"
    print -r -- "file's header; the ~/.claude entries changed during the step are listed at its end."; return 0; }
  print -r -- "STOP: this step runs Claude Code with the user's own login. Ask the user first, then:"
  print -r -- "  VERIFY578_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"; return 1
}
# Claude Code as a user starts it: no inherited agents channel or Claude Code session markers.
claude_env() { env -u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u GRAFTLING_CLAUDE_HOST_CONFIG \
  -u GRAFTLING_CLAUDE_HOST_CHANNEL -u GRAFTLING_NATIVE_RUNTIME -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT \
  -u ANTHROPIC_BASE_URL "$@"; }
changed_claude() {
  say "~/.claude entries changed during this step (names only)"
  find $HOME/.claude -maxdepth 3 -newer $1 2>&1 | sed "s|$HOME|~|" | head -40
  python3 -I -c 'import json, sys
p = json.load(open(sys.argv[1])).get("projects") or {}
print("~/.claude.json project entries under", sys.argv[2] + ":", {k: v.get("hasTrustDialogAccepted") for k, v in p.items() if k.startswith(sys.argv[2])})' \
    $HOME/.claude.json ${ROOT:A} 2>&1
}
# install TAG COMMIT SOURCE: build the wheel at COMMIT from SOURCE (a repository or bundle) into ROOT/venv-TAG and
# write the plugin files into ROOT/proj-TAG (docs/install/claude-code.md); sets V and P.
install() {
  local tag=$1 commit=$2 source=$3 src=$ROOT/src-$1 wheels=$ROOT/wheels-$1
  typeset -g V=$ROOT/venv-$tag P=$ROOT/proj-$tag
  [[ -d $P ]] || { print -r -- "STOP: $P missing; run: zsh $THIS pre"; return 1; }
  local mark=$V/.graftling-578-commit
  if [[ ! -f $mark || $(<$mark) != $commit ]] || ! $V/bin/python -I -c 'import graftling' 2>/dev/null; then
    say "install graftling $commit from $source into $V"
    rm -rf $src $wheels $V
    git clone -q $source $src && git -C $src checkout -q $commit || { print -r -- "STOP: cannot check out $commit from $source"; return 1; }
    # VERIFY578_OFFLINE_DEPS=<dir> (rehearsal only, no PyPI): system site packages plus <dir>, no index.
    local -a venv=() pip=()
    [[ -n ${VERIFY578_OFFLINE_DEPS:-} ]] && venv=(--system-site-packages) pip=(--no-build-isolation --no-index)
    python3 -m venv $venv $V || { print "STOP: venv failed"; return 1; }
    [[ -n ${VERIFY578_OFFLINE_DEPS:-} ]] && print -r -- $VERIFY578_OFFLINE_DEPS > $(print -r -- $V/lib/python3*/site-packages(N[1]))/offline-deps.pth
    $V/bin/python -m pip -q wheel $pip --no-deps -w $wheels $src \
      && $V/bin/python -m pip -q install $pip $wheels/graftling-*.whl || { print "STOP: the wheel install failed"; return 1; }
    print -r -- $commit > $mark
  fi
  print -r -- "installed: $($V/bin/python -m pip show graftling 2>&1 | grep -E '^(Version|Location)' | tr '\n' ' ') commit $(<$mark)"
  CLAUDE=$(command -v claude) || { print "STOP: no claude on PATH"; return 1; }
  say "plugin files (configuration --write) in $P"
  (cd $P && $V/bin/python -I -m graftling.claude.host configuration --project $P --claude $CLAUDE --write) \
    || { print "STOP: configuration --write failed"; return 1; }
  # Print mode shows no project MCP server prompt: its answer is written where Claude Code keeps it, in the project.
  python3 -I -c 'import json, sys
f = sys.argv[1]; d = json.load(open(f)); d["enabledMcpjsonServers"] = sorted(set(d.get("enabledMcpjsonServers", [])) | {"graftling"})
json.dump(d, open(f, "w"), indent=2)' $P/.claude/settings.local.json || return 1
  print -r -- ".claude/settings.local.json: $(tr -d '\n ' < $P/.claude/settings.local.json)"
}
trusted() {  # prints the trust flag of folder $1 in ~/.claude.json
  python3 -I -c 'import json, sys
print((json.load(open(sys.argv[1])).get("projects") or {}).get(sys.argv[2], {}).get("hasTrustDialogAccepted"))' $HOME/.claude.json $1 2>&1
}
CHILD='{"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"MODEL","tools":["Bash"],"instruction":"MARK Use your Bash tool to run exactly this command: echo r578-bash . Then reply with its exact output and nothing else."}}'
child() { local c=${CHILD//MODEL/$1}; print -r -- ${c//MARK/$2}; }
PARENT_PROMPT="Use the tool mcp__graftling__agents, not your own subagents or any other tool. Its input is {\"action\":\"execute\",\"feature\":<name>,\"arguments\":{...}}. Make exactly these calls, in this order, one at a time:
1) $(child claude-haiku-4-5-20251001 R578-A.)
2) $(child claude-haiku-4-5-20251001 R578-B.)
3) $(child claude-haiku-5-5 R578-C.)
4) $(child $CONTROL R578-D.)
5) to 8) {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<agent id from call 1, 2, 3, then 4>\",\"timeout_seconds\":240}}
9) {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{}}
Do not approve, deny or answer anything for the children. Then report one line per child: CHILD-A / B / C / D: agent id, state, outcome and its reply. If any call returns an error, print it verbatim on a line prefixed ERROR:."
accept() {  # MODE: one parent Session in P creates the four children; computed verdicts
  local mode=$1 snap=$D/before.ids out=$D/parent.jsonl mark=$D/start.mark
  $V/bin/python -I $JUDGE snap $P/.agents-control > $snap 2>/dev/null || : > $snap
  : > $mark
  local -a cargv=($CLAUDE -p --model $PMODEL --output-format stream-json --verbose
                  --allowedTools mcp__graftling__agents -- $PARENT_PROMPT)
  say "parent argv (in $P): ${(j: :)${(@q-)cargv[1,-2]}} <prompt, ${#cargv[-1]} characters, in $D/prompt.txt>"
  print -r -- $PARENT_PROMPT > $D/prompt.txt
  (cd $P && claude_env $BOUND 900 $cargv < /dev/null > $out 2> $out.stderr)
  local prc=$?
  print -r -- "parent exit=$prc; stream-json $out; stderr tail: $(tail -5 $out.stderr)"
  python3 -I -c 'import json, sys
for line in open(sys.argv[1], errors="replace"):
    try: e = json.loads(line)
    except ValueError: continue
    if not isinstance(e, dict): continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("parent init: model", e.get("model"), "apiKeySource", e.get("apiKeySource"), "permissionMode", e.get("permissionMode"), "agents tool:", "mcp__graftling__agents" in (e.get("tools") or []))
    if e.get("type") == "result": print("parent result:", str(e.get("result"))[:1500])' $out
  say "verdicts (computed from the recorded files; each can fail)"
  $V/bin/python -I $JUDGE accept $mode $P/.agents-control $snap $out; local jrc=$?
  (( prc == 0 )) && print "PASS: the parent exited 0" || { print "FAIL: the parent exited $prc"; jrc=1; }
  changed_claude $mark
  say "follow-up (copy and paste)"
  print -r -- "  $V/bin/python -I $JUDGE accept $mode $P/.agents-control $snap $out"
  print -r -- "  ls $P/.agents-control/native/; grep -h -A6 '^permissions' $P/.agents-control/native/*/session.yml"
  return $jrc
}

run_step() {
case $STEP in
pre)
  say "[pre] Versions, base build, projects, one-line login check. Dialog: none. ~2 min."
  print -r -- "zsh: $ZSH_VERSION ($THIS)"
  local t; for t in python3 git claude; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  [[ -e $ROOT/proj-base || -e $ROOT/proj-cand ]] && { print -r -- "STOP: $ROOT/proj-base or proj-cand exists. Remove ROOT yourself if it is from an earlier attempt, then rerun: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  need_login || return 1
  print -r -- "base $BASE in $LOCAL: $(git -C $LOCAL log -1 --format='%h %s' $BASE 2>&1)"
  mkdir -p $ROOT/proj-base $ROOT/proj-cand $ROOT/diag || return 1
  print -r -- "created $ROOT/proj-base (base), $ROOT/proj-cand (candidate) and $ROOT/diag"
  install base $BASE $LOCAL || return 1
  local mark=$D/start.mark; : > $mark
  say "one-line prompt in $ROOT: its model and login source"
  (cd $ROOT && claude_env $BOUND 120 $(command -v claude) -p --model claude-haiku-5-5 --output-format stream-json --verbose \
     -- "Reply in one line with the model id you are running as and nothing else." < /dev/null > $D/pre.jsonl 2> $D/pre.stderr)
  local rc=$?
  python3 -I -c 'import json, sys
for line in open(sys.argv[1], errors="replace"):
    try: e = json.loads(line)
    except ValueError: print("non-JSON:", line.strip()[:300]); continue
    if not isinstance(e, dict): continue
    if e.get("type") == "system" and e.get("subtype") == "init": print("init: model", e.get("model"), "apiKeySource", e.get("apiKeySource"), "permissionMode", e.get("permissionMode"))
    if e.get("type") == "result": print("answer:", str(e.get("result"))[:300], "| is_error", e.get("is_error"))' $D/pre.jsonl
  print -r -- "exit=$rc; stderr: $(tail -3 $D/pre.stderr)"
  changed_claude $mark
  (( rc == 0 )) || { print -r -- "STOP: Claude Code did not answer with this login"; return 1; }
  print "Success: versions, the base venv, both projects, and a model id with its login source."
  print -r -- "next (USER, plain Terminal): cd $ROOT/proj-base && claude   -> trust the folder, then /exit"
  print -r -- "                             cd $ROOT/proj-cand && claude   -> trust the folder, then /exit"
  next "zsh $THIS Tu"
  ;;
Tu)
  say "[Tu] USER trusts both project folders in Claude Code's own dialog, then /exit. This step only reads ~/.claude.json."
  print -r -- "If not done yet, in a plain Terminal:"
  print -r -- "  cd $ROOT/proj-base && claude     (answer the trust dialog: trust this folder; then type /exit)"
  print -r -- "  cd $ROOT/proj-cand && claude     (the same)"
  local p ok=0
  for p in ${ROOT:A}/proj-base ${ROOT:A}/proj-cand; do
    local f=$(trusted $p); print -r -- "  $p: hasTrustDialogAccepted=$f"; [[ $f == True ]] || ok=1
  done
  (( ok == 0 )) || { print "NOT YET: a folder is not trusted; do the above, then rerun this step"; return 1; }
  print "Success: both folders are trusted."
  next "VERIFY578_CLAUDE_USER_LOGIN=1 zsh $THIS repro"
  ;;
repro)
  say "[repro] BASE $BASE: diagnosis of the condition, then the premise through the real entry. Dialog: none. ~4-6 min."
  need_login || return 1
  [[ $(trusted ${ROOT:A}/proj-base) == True ]] || { print -r -- "STOP: $ROOT/proj-base is not trusted; run: zsh $THIS Tu"; return 1; }
  install base $BASE $LOCAL || return 1
  local mark=$D/start.mark; : > $mark
  say "(a) DIAGNOSIS: direct claude -p --permission-mode auto, $DIAG_RUNS runs per model, in $ROOT/diag"
  local m n f
  for m in $DIAG_MODELS; do
    for n in {1..$DIAG_RUNS}; do
      f=$D/diag-$m-$n
      print -r -- "-- $m run $n"
      (cd $ROOT/diag && claude_env $BOUND 180 $CLAUDE -p --permission-mode auto --model $m --output-format stream-json \
         --verbose --debug --strict-mcp-config --mcp-config '{"mcpServers":{}}' -- "Reply with one word: ok." \
         < /dev/null > $f.jsonl 2> $f.stderr)
      print -r -- "   exit=$?"
      python3 -I $JUDGE diag $f.jsonl $f.stderr | tee $f.txt
    done
  done
  say "condition tally (requested auto -> observed: count, model, permissionMode)"
  cat $D/diag-*.txt | grep '^DIAG-MODE' | sort | uniq -c
  say "(b) ACCEPTANCE premise: children through mcp__graftling__agents in $P"
  accept repro || { print "NOT REPRODUCED or FAIL: see the verdicts above"; return 1; }
  print "Success: REPRODUCED (see the verdicts and the condition tally)."
  next "zsh $THIS check   (after the Engineer sets CAND; push only after asking the user)"
  ;;
push)
  say "[push] Main, after the user agreed. Push $BRANCH (${CAND:-unset}) to $URL from $BUNDLE. Dialog: none expected."
  [[ -n $CAND ]] || { print "STOP: CAND is not set in this script; ask the Engineer"; return 1; }
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $CAND ]] && { print "already on GitHub"; return 0; }
  local G=${TMPDIR:-/tmp}/graftling-578-push.git
  rm -rf $G && git clone -q --bare $URL $G && git -C $G fetch -q $BUNDLE "${BRANCH}:${BRANCH}" || return 1
  [[ $(git -C $G rev-parse $BRANCH) == $CAND ]] || { print "STOP: the bundle's branch is not $CAND"; return 1; }
  print -r -- "authors and committers: $(git -C $G log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $G push $URL "${BRANCH}:refs/heads/${BRANCH}" || return 1
  print -r -- "on GitHub now: $(git ls-remote $URL refs/heads/$BRANCH)"; rm -rf $G
  ;;
check)
  say "[check] CANDIDATE ${CAND:-unset} through the real entry. Dialog: none. ~4 min."
  [[ -n $CAND ]] || { print "STOP: CAND is not set in this script; ask the Engineer"; return 1; }
  need_login || return 1
  [[ $(trusted ${ROOT:A}/proj-cand) == True ]] || { print -r -- "STOP: $ROOT/proj-cand is not trusted; run: zsh $THIS Tu"; return 1; }
  [[ -f $BUNDLE ]] || { print -r -- "STOP: $BUNDLE missing; ask the Engineer"; return 1; }
  install cand $CAND $BUNDLE || return 1
  accept check || { print "FAIL: see the verdicts above"; return 1; }
  print "Success: narrower-mode children completed with the mismatch recorded and warned; matching ones completed."
  print -r -- "next: report $D to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|Tu|repro|push|check"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY578_OUT:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
D=$OUTBASE/$STEP-$(date +%Y%m%dT%H%M%S); mkdir -p $D || return 1
OUT_FILE=$D/output.txt
print -r -- "output: $D"
{ run_step; print -r -- "STEP-END rc=$?"; } 2>&1 | tee $OUT_FILE
local rc=$?
grep -q '^STEP-END rc=0$' $OUT_FILE || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT_FILE; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT_FILE; rc=$rc)"
return $rc
