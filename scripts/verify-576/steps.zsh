#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 576 Main-run steps: a Claude child created through the agents tool without `tools` has no Bash on
# graftling 0.7.0. Run one step at a time:  zsh <this file> <STEP>
#   diagnose  Main. DIAGNOSIS ONLY, NOT ACCEPTANCE. Runs the installed `claude` directly, with the launch flags of
#             graftling 0.7.0's ClaudeExecution._prepare (a minimal equivalent --settings), and reads each run's
#             system/init `tools` list. No model call and no login, enforced: the runs start from an empty
#             environment (env -i: no ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or CLAUDE_CODE_OAUTH_TOKEN),
#             CLAUDE_CONFIG_DIR=ROOT/diag/config*, ANTHROPIC_BASE_URL=http://127.0.0.1:9 (nothing leaves the
#             machine), and each process is stopped as soon as init is read (hard timeout 60 s). Claude Code may
#             look up a keychain credential for that config dir (read only). Writes only under ROOT/diag; the
#             mtimes of ~/.claude and ~/.claude.json are printed before and after. STOP if ROOT/diag exists.
#             Dialog: none. ~1-2 min.
# ACCEPTANCE (the real entry users go through: a wheel installed per docs/install/claude-code.md, the generated plugin
# files `configuration --write` in the project, then `claude -p` started in it; the parent creates its children only
# through its own mcp__graftling__agents tool). No --plugin-dir, no direct calls of graftling.
#   pre       Main. Versions (zsh, python3, git, claude); the base and candidate on GitHub; the login check (below);
#             creates ROOT/proj-base and ROOT/proj (STOP if either exists). A one-line `claude -p` in ROOT names
#             its model and login source (system/init model and apiKeySource). Dialog: none. ~30 s.
#   push      Main, after asking the user. Pushes the candidate branch from the Engineer's bundle
#             (.scratch/576/graftling-576.bundle) to LUOXIAO92/graftling. Dialog: none expected; git uses your usual
#             GitHub login. ~30 s.
#   probe     Main. DIAGNOSIS ONLY, NOT ACCEPTANCE. Installs the CANDIDATE wheel (from GitHub, after push) into
#             ROOT/venv and runs its probe function graftling.claude.execution.probe_default_tools against the
#             installed claude, as a child launch would (model CMODEL, permission mode auto, the CLAUDE_CODE_*
#             variables graftling sets). No model call and no login: the probe removes ANTHROPIC_API_KEY,
#             ANTHROPIC_AUTH_TOKEN and CLAUDE_CODE_OAUTH_TOKEN, uses ANTHROPIC_BASE_URL=http://127.0.0.1:9 and an
#             empty CLAUDE_CONFIG_DIR under ROOT/probe-state (removed after), and stops at system/init. Prints the
#             probe argv, the set, its cache file, and for comparison the same argv plus --safe-mode. Writes only
#             under ROOT (venv, src-cand, wheels-cand, proj, probe-state). Dialog: none. ~1-2 min.
#   repro     Main. The premise on the BASE (graftling dev cadc419 = 0.7.0): clone at BASE from GitHub, build and
#             install the wheel into ROOT/venv-base, `configuration --write` into ROOT/proj-base, then one `claude -p`
#             parent there creates three claude children (model CMODEL): (i) no tools, asked to run
#             `echo r576-bash` with Bash; (ii) tools [Read]; (iii) disallowed_tools [Bash]. It waits for each and
#             reads status. Verdicts: (i) Bash ABSENT from the child's recorded system/init tools (premise; if it is
#             present the step says PREMISE NOT REPRODUCED and fails); (ii)/(iii) Bash absent. Dialog: none
#             (-p shows none). ~3-5 min.
#   check     Main. The same on the CANDIDATE (GCOMMIT, from GitHub after push) in ROOT/venv and ROOT/proj.
#             Verdicts: (i) Bash PRESENT in the recorded system/init tools AND its Bash call returned output
#             containing `r576-bash`; (iv) the (i) child's built-in init tools equal the probed set graftling
#             cached in the data root (printed); (ii) Bash absent, Read present; (iii) Bash absent.
#             Dialog: none. ~3-5 min.
# Order: diagnose (done), pre, push, probe, repro, check.
# Login for pre/repro/check: by default Claude Code runs isolated in CLAUDE_CONFIG_DIR=ROOT/claude-home with
# ANTHROPIC_API_KEY (STOP if unset). With VERIFY576_CLAUDE_USER_LOGIN=1 (Main asks the user first) it uses the user's
# own login: it READS the keychain login, ~/.claude.json and the user's ~/.claude settings, plugins and CLAUDE.md as
# any start does; it WRITES Session transcripts under ~/.claude/projects/-private-tmp-graftling-576*/, project entries
# for ROOT, ROOT/proj-base and ROOT/proj in ~/.claude.json, and Claude Code's own per-start files under ~/.claude
# (the step lists every ~/.claude entry changed during the run, names only). Nothing under ~/.claude is installed:
# the plugin files go only into the project (configuration --write); no `claude plugin` command is run.
# Everything is under ROOT=/private/tmp/graftling-576. Step output is kept in OUT. VERIFY576_ROOT / VERIFY576_OUT /
# VERIFY576_BIN are for the Engineer's rehearsal only (VERIFY576_BIN: a stub claude, script check only).
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY576_ROOT:-/private/tmp/graftling-576}
OUT=${VERIFY576_OUT:-$H/.graphtraj/core/state/tasks/576-claude-agents-child-without-tools-has-no-bash/realhost}
THIS=${0:A}
STEP=${1:-}
JUDGE=${0:A:h}/judge.py
path=(${VERIFY576_BIN:+$VERIFY576_BIN} $path)
URL=${VERIFY576_URL:-https://github.com/LUOXIAO92/graftling.git}
BASE=cadc419271dabc8f4a0b11da1bb46c70ef598c77      # graftling dev = 0.7.0 + 570 (the production behaviour)
BRANCH=agent/576-claude-agents-child-without-tools-has-no-bash
GCOMMIT=e17ccd09a3c74587f9cf207baf23a9594bbe4c0c   # the graftling candidate (base: dev cadc419)
BUNDLE=$WT/.scratch/576/graftling-576.bundle        # the candidate branch, from the base
CH=$ROOT/claude-home                                # isolated CLAUDE_CONFIG_DIR (default login mode)
CMODEL=${VERIFY576_CHILD_MODEL:-claude-haiku-5-5}   # children: the cheapest model
PMODEL=${VERIFY576_PARENT_MODEL:-claude-sonnet-5-5} # the parent follows a 5-call script

say() { print -r -- "== $*"; }
mtimes() { local f; for f in $HOME/.claude $HOME/.claude.json; do
             print -r -- "  $f: $(stat -f '%Sm' -t '%Y-%m-%dT%H:%M:%S' $f 2>&1)"; done }

# One diagnosis run: label config-dir cwd flags...; the row is printed by judge.py.
diag_run() {
  local label=$1 cfg=$2 cwd=$3; shift 3
  local out=$D/run-${label%%:*}.json
  print -r -- "$label" > $out.label
  print -r -- "argv: claude ${(q-)@}" > $out.argv
  env -i HOME=$HOME PATH=$PATH TMPDIR=${TMPDIR:-/tmp} USER=${USER:-} LANG=${LANG:-en_US.UTF-8} \
    CLAUDE_CONFIG_DIR=$cfg ANTHROPIC_BASE_URL=http://127.0.0.1:9 \
    DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    CLAUDE_CODE_SDK_READS_SESSION_STATE=1 CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 \
    python3 -I $JUDGE init $out 60 $cwd -- $CLAUDE "$@"
  python3 -I $JUDGE row "$label" $out Bash WebFetch WebSearch CronList Edit Write Read
  print -r -- "   $(<$out.argv)"
}
has() { python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1]))
sys.exit(0 if d["init"] and d["tools"] and sys.argv[2] in d["tools"] else 1 if d["init"] and d["tools"] else 2)' $D/run-$1.json $2; }

# Claude Code as a user starts it: no inherited agents channel or Claude Code session markers. Isolated by default.
claude_env() {
  local -a clean=(-u GRAFTLING_PYTHON -u GRAFTLING_CONNECTION -u GRAFTLING_CLAUDE_HOST_CONFIG -u GRAFTLING_CLAUDE_HOST_CHANNEL
                  -u GRAFTLING_NATIVE_RUNTIME -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u ANTHROPIC_BASE_URL)
  if [[ -n ${VERIFY576_CLAUDE_USER_LOGIN:-} ]]; then env $clean "$@"; else env $clean CLAUDE_CONFIG_DIR=$CH "$@"; fi
}
login_check() {
  if [[ -n ${VERIFY576_CLAUDE_USER_LOGIN:-} ]]; then
    print -r -- "VERIFY576_CLAUDE_USER_LOGIN=1: the user's own Claude login (Main asked the user). Reads and writes: see this"
    print -r -- "file's header; the ~/.claude entries changed during the step are listed at its end."
  elif [[ -z ${ANTHROPIC_API_KEY:-} ]]; then
    print -r -- "STOP: ANTHROPIC_API_KEY is not set, and Claude Code would run isolated in CLAUDE_CONFIG_DIR=$CH (no login)."
    print -r -- "Either export ANTHROPIC_API_KEY=<key> and rerun: zsh $THIS $STEP"
    print -r -- "or, after the user agrees to their own login:  VERIFY576_CLAUDE_USER_LOGIN=1 zsh $THIS $STEP"
    return 1
  else
    mkdir -p $CH
    print -r -- "Isolated: CLAUDE_CONFIG_DIR=$CH, ANTHROPIC_API_KEY (${#ANTHROPIC_API_KEY} characters; not printed)."
  fi
}
changed_claude() {  # marker file: names of ~/.claude entries changed since it, and the ~/.claude.json entries for ROOT
  [[ -n ${VERIFY576_CLAUDE_USER_LOGIN:-} ]] || { print -r -- "$CH now holds: $(cd $CH && print -l -- *(ND) | tr '\n' ' ')"; return 0; }
  say "~/.claude entries changed during this step (names only)"
  find $HOME/.claude -maxdepth 3 -newer $1 2>&1 | sed "s|$HOME|~|" | head -40
  python3 -I -c 'import json, sys
p = json.load(open(sys.argv[1])).get("projects") or {}
print("~/.claude.json project entries under", sys.argv[2] + ":", [k for k in p if k.startswith(sys.argv[2])])' \
    $HOME/.claude.json ${ROOT:A} 2>&1
}
# install_wheel TAG COMMIT: clone at COMMIT from GitHub, build and install the wheel (docs/install/claude-code.md) into
# ROOT/venv-TAG ("venv" for the candidate), then `configuration --write` into the project; sets V and P.
install_wheel() {
  local tag=$1 commit=$2 src=$ROOT/src-$1 wheels=$ROOT/wheels-$1
  typeset -g V=$ROOT/venv${${tag:#cand}:+-$tag} P=$ROOT/proj${${tag:#cand}:+-$tag}
  [[ -d $P ]] || { print -r -- "STOP: $P missing; run: zsh $THIS pre"; return 1; }
  if [[ ! -x $V/bin/python ]] || ! $V/bin/python -I -c 'import graftling' 2>/dev/null; then
    say "install graftling $commit into $V (docs/install/claude-code.md: Install the wheel)"
    rm -rf $src $wheels
    git clone -q $URL $src && git -C $src checkout -q $commit || { print "STOP: cannot clone $URL at $commit"; return 1; }
    python3 -m venv $V && $V/bin/python -m pip -q wheel --no-deps -w $wheels $src \
      && $V/bin/python -m pip -q install $wheels/graftling-*.whl || { print "STOP: the wheel install failed"; return 1; }
  fi
  print -r -- "installed: $($V/bin/python -m pip show graftling 2>&1 | grep -E '^(Name|Version|Location)' | tr '\n' ' ')"
  print -r -- "source commit: $(git -C $src rev-parse HEAD 2>&1)"
  CLAUDE=$(command -v claude) || { print "STOP: no claude on PATH"; return 1; }
  say "generated plugin files (docs: Generate the plugin files) in $P"
  (cd $P && $V/bin/python -I -m graftling.claude.host configuration --project $P --claude $CLAUDE --write) \
    || { print "STOP: configuration --write failed"; return 1; }
  # The approval Claude Code's project MCP server prompt records (docs: 'Approve ... project MCP server prompts');
  # print mode shows no prompt, so the answer is written where Claude Code keeps it, in the project only.
  python3 -I -c 'import json, sys
f = sys.argv[1]; d = json.load(open(f)); d.setdefault("enabledMcpjsonServers", [])
d["enabledMcpjsonServers"] = sorted(set(d["enabledMcpjsonServers"]) | {"graftling"}); json.dump(d, open(f, "w"), indent=2)' \
    $P/.claude/settings.local.json || return 1
  print -r -- "project files: $(cd $P && print -l -- .mcp.json .claude/**/*(N.D) .agents-control/claude-host.json(N) | tr '\n' ' ')"
  print -r -- ".claude/settings.local.json: $(tr -d '\n' < $P/.claude/settings.local.json)"
}
PARENT_PROMPT='Use the tool mcp__graftling__agents, not your own subagents or any other tool. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls, in this order, one at a time:
1) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"CMODEL","instruction":"R576-I. Use your Bash tool to run exactly this command: echo r576-bash . Then reply with its exact output and nothing else. If you have no Bash tool, reply exactly: NO-BASH"}}
2) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"CMODEL","tools":["Read"],"instruction":"R576-II. Do not run any command. Reply with the names of all your tools on one line."}}
3) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"CMODEL","disallowed_tools":["Bash"],"instruction":"R576-III. Do not run any command. Reply with the names of all your tools on one line."}}
4) {"action":"execute","feature":"wait","arguments":{"agent":"<agent id from call 1>","timeout_seconds":240}}
5) {"action":"execute","feature":"wait","arguments":{"agent":"<agent id from call 2>","timeout_seconds":240}}
6) {"action":"execute","feature":"wait","arguments":{"agent":"<agent id from call 3>","timeout_seconds":240}}
7) {"action":"execute","feature":"status","arguments":{}}
Do not approve, deny or answer anything for the children. Then report one line per child: CHILD-I / CHILD-II / CHILD-III: agent id, state, and its reply. If any call returns an error, print it verbatim on a line prefixed ERROR:.'
# accept MODE: one parent Session in P creates the three children; computed verdicts.
accept() {
  local mode=$1 snap=$ROOT/$1-before.ids out=$ROOT/$1-parent-$(date +%H%M%S).jsonl mark=$ROOT/$1-start.mark
  $V/bin/python -I $JUDGE snap $P/.agents-control > $snap 2>/dev/null || : > $snap
  : > $mark
  say "parent: claude -p --model $PMODEL --output-format stream-json --verbose --allowedTools mcp__graftling__agents (in $P)"
  (cd $P && claude_env $CLAUDE -p --model $PMODEL --output-format stream-json --verbose \
     --allowedTools mcp__graftling__agents "${PARENT_PROMPT//CMODEL/$CMODEL}" < /dev/null > $out 2> $out.stderr)
  local prc=$?
  print -r -- "parent exit=$prc; stream-json $out; stderr: $(tail -5 $out.stderr)"
  python3 -I -c 'import json, sys
for line in open(sys.argv[1], errors="replace"):
    try: e = json.loads(line)
    except ValueError: continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("parent init: model", e.get("model"), "apiKeySource", e.get("apiKeySource"), "agents tool:", "mcp__graftling__agents" in (e.get("tools") or []))
    if e.get("type") == "result": print("parent result:", str(e.get("result"))[:1500])' $out
  say "verdicts (computed from the recorded files; each can fail)"
  $V/bin/python -I $JUDGE accept $mode $P/.agents-control $snap $out; local jrc=$?
  (( prc == 0 )) && print "PASS: the parent exited 0" || { print "FAIL: the parent exited $prc"; jrc=1; }
  changed_claude $mark
  say "follow-up (copy and paste)"
  print -r -- "  $V/bin/python -I $JUDGE accept $mode $P/.agents-control $snap $out"
  print -r -- "  ls $P/.agents-control/control/agents/; grep -rn r576-bash $P/.agents-control --include=session.yml --include='*.jsonl' | head"
  return $jrc
}

run_step() {
case $STEP in
diagnose)
  say "[diagnose] Main. DIAGNOSIS, not acceptance: which launch flag removes Bash/WebFetch from Claude's init tools. Dialog: none. ~1-2 min."
  D=$ROOT/diag
  [[ -e $D ]] && { print -r -- "STOP: $D exists. Remove it yourself, then rerun: rm -rf $D && zsh $THIS diagnose"; return 1; }
  CLAUDE=$(command -v claude) || { print "STOP: no claude on PATH"; return 1; }
  print -r -- "claude: $CLAUDE -> ${CLAUDE:A}"
  print -r -- "claude --version: $(env -i HOME=$HOME PATH=$PATH CLAUDE_CONFIG_DIR=$ROOT/diag-version-unused $CLAUDE --version 2>&1)"
  rm -rf $ROOT/diag-version-unused
  print -r -- "python3: $(command -v python3) $(python3 --version 2>&1)"
  say "mtimes before (must be equal after)"
  local before; before=$(mtimes); print -r -- $before
  mkdir -p $D/config $D/config-user $D/work $D/proj/.claude $D/runtime-home $D/private || return 1
  print -r -- '{"permissions": {"deny": ["WebSearch"]}}' > $D/proj/.claude/settings.json
  print -r -- '{"permissions": {"deny": ["CronList"]}}' > $D/config-user/settings.json
  print -r -- "created $D: config (CLAUDE_CONFIG_DIR, empty), config-user (CLAUDE_CONFIG_DIR with settings.json"
  print -r -- "denying CronList), work (cwd, no settings), proj (cwd, .claude/settings.json denying WebSearch),"
  print -r -- "runtime-home and private (stand for runtime_home and private control state in the settings)"
  say "claude --help: --restricted, --tools, --disallowedTools, --setting-sources"
  local help; help=$(env -i HOME=$HOME PATH=$PATH CLAUDE_CONFIG_DIR=$D/config $CLAUDE --help 2>&1)
  print -r -- $help > $D/help.txt
  print -r -- $help | grep -E -A3 -- '--restricted|--tools|--disallowedTools|--disallowed-tools|--setting-sources'
  local toolshelp; toolshelp=$(print -r -- $help | grep -E -A3 -- '--tools')
  # The --settings of ClaudeExecution.native_settings for a write-access child (worktree_access write), with the
  # 'auto' permission mode the host's settings default to.
  local rt=$D/runtime-home pv=$D/private
  pj() { print -r -- '"permissions": {"blockReadsOutsideWorkingDirectories": true, "allow": [], "deny": ["Edit(/'$rt')", "Edit(/'$rt'/**)", "Edit(/'$pv')", "Edit(/'$pv'/**)", "Read(/'$rt')", "Read(/'$rt'/**)", "Read(/'$pv')", "Read(/'$pv'/**)"], "additionalDirectories": []'$1'}' }
  local perms=$(pj ', "defaultMode": "auto"')
  local sandbox='"sandbox": {"enabled": true, "failIfUnavailable": true, "allowUnsandboxedCommands": false, "autoAllowBashIfSandboxed": false, "excludedCommands": [], "filesystem": {"denyRead": ["'$rt'", "'$pv'"], "allowRead": [], "allowWrite": [], "denyWrite": ["'$rt'", "'$pv'"]}}'
  local full="{$perms, $sandbox}" nosandbox="{$perms}"
  print -r -- "settings (row 1): $full"
  local -a head=(--print --verbose --input-format stream-json --output-format stream-json --include-partial-messages
                 --replay-user-messages --permission-prompt-tool stdio)
  local -a tail=(--strict-mcp-config --mcp-config '{"mcpServers": {}}')
  local -a end=(--model claude-opus-5-5 --append-system-prompt 'Task 576 diagnosis.')
  sid() { print -r -- --session-id $(uuidgen | tr A-Z a-z) }
  say "matrix (cwd $D/work, CLAUDE_CONFIG_DIR $D/config)"
  diag_run "1: graftling 0.7.0 flags (--restricted, sandbox settings, no --tools)" $D/config $D/work \
    $head --restricted $tail --settings $full $end ${=$(sid)} --permission-mode auto
  diag_run "2: row 1 without --restricted" $D/config $D/work \
    $head $tail --settings $full $end ${=$(sid)} --permission-mode auto
  diag_run "3: row 1 without the sandbox block" $D/config $D/work \
    $head --restricted $tail --settings $nosandbox $end ${=$(sid)} --permission-mode auto
  if [[ $toolshelp == *default* ]]; then
    diag_run "4: row 1 + --tools default" $D/config $D/work \
      $head --restricted $tail --settings $full --tools default $end ${=$(sid)} --permission-mode auto
  else print -r -- "-- 4: NOT RUN: claude --help does not document --tools default"; fi
  diag_run "5: row 1 + --tools Bash" $D/config $D/work \
    $head --restricted $tail --settings $full --tools Bash $end ${=$(sid)} --permission-mode auto
  diag_run "6: row 1 with permission mode default (no defaultMode, no --permission-mode)" $D/config $D/work \
    $head --restricted $tail --settings "{$(pj ''), $sandbox}" $end ${=$(sid)}
  say "settings sources (cwd $D/proj with .claude/settings.json deny WebSearch; CLAUDE_CONFIG_DIR $D/config-user with settings.json deny CronList)"
  diag_run "7: row 1 in proj with project and user settings" $D/config-user $D/proj \
    $head --restricted $tail --settings $full $end ${=$(sid)} --permission-mode auto
  diag_run "8: row 2 (no --restricted) in proj with project and user settings" $D/config-user $D/proj \
    $head $tail --settings $full $end ${=$(sid)} --permission-mode auto
  say "mtimes after"
  local after; after=$(mtimes); print -r -- $after
  if [[ $before == *'not permitted'* ]]; then print "INCONCLUSIVE: the mtimes could not be read"
  elif [[ $before == $after ]]; then print "PASS: ~/.claude and ~/.claude.json mtimes unchanged (a missing file stays missing)"
  else print "FAIL: an mtime changed (see above)"; fi
  print -r -- "written under $D: $(cd $D && print -l -- **/*(ND.) | wc -l | tr -d ' ') files; top level: $(cd $D && print -l -- *(ND) | tr '\n' ' ')"
  say "findings (computed; INCONCLUSIVE where a row had no init or empty tools)"
  local r n s
  for n in Bash WebFetch; do
    for r in 1 2 3 4 5 6; do
      [[ -f $D/run-$r.json ]] || continue
      has $r $n; s=$?
      print -r -- "  row $r: $n $( (( s == 0 )) && print present || { (( s == 1 )) && print absent || print INCONCLUSIVE; })"
    done
  done
  has 1 Bash; local b1=$?
  if (( b1 == 1 )); then
    for r n in 2 --restricted 3 'the sandbox block' 6 'permission mode auto'; do
      has $r Bash; s=$?
      (( s == 0 )) && print -r -- "FINDING: removing $n (row $r) restores Bash"
      (( s == 1 )) && print -r -- "FINDING: removing $n (row $r) does not restore Bash"
      (( s == 2 )) && print -r -- "INCONCLUSIVE: row $r"
    done
  elif (( b1 == 0 )); then print "FINDING: row 1 HAS Bash: the bare flags do not reproduce the premise"
  else print "INCONCLUSIVE: row 1 had no init tools"; fi
  local proj usr
  has 7 WebSearch; proj=$?; has 1 WebSearch; local base=$?
  if (( proj == 2 || base == 2 )); then print "INCONCLUSIVE: project settings under --restricted (rows 1/7)"
  elif (( base == 1 )); then print "INCONCLUSIVE: WebSearch is absent already in row 1, so its deny shows nothing"
  else (( proj == 1 )) && print "FINDING: under --restricted the project settings ARE read (WebSearch denied, row 7)" \
                        || print "FINDING: under --restricted the project settings are NOT read (WebSearch still offered, row 7)"; fi
  has 7 CronList; usr=$?; has 1 CronList; base=$?
  if (( usr == 2 || base == 2 )); then print "INCONCLUSIVE: user settings under --restricted (rows 1/7)"
  elif (( base == 1 )); then print "INCONCLUSIVE: CronList is absent already in row 1, so its deny shows nothing"
  else (( usr == 1 )) && print "FINDING: under --restricted the user settings ARE read (CronList denied, row 7)" \
                       || print "FINDING: under --restricted the user settings are NOT read (CronList still offered, row 7)"; fi
  has 8 WebSearch; proj=$?; has 8 CronList; usr=$?
  word() { (( $1 == 0 )) && print 'offered' || { (( $1 == 1 )) && print 'absent (denied)' || print INCONCLUSIVE; } }
  print -r -- "row 8 (no --restricted), for comparison: WebSearch $(word $proj) under the project deny, CronList $(word $usr) under the user deny"
  print -r -- "Raw records: $D/run-*.json (+ .argv, .label), $D/help.txt"
  print -r -- "next: report $OUT/diagnose.txt to the Leader"
  ;;
pre)
  say "[pre] Main. Versions, GitHub refs, login check, ROOT. Dialog: none. ~30 s."
  print -r -- "zsh: $ZSH_VERSION ($THIS)"
  local t; for t in python3 git claude; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  [[ -e $ROOT/proj || -e $ROOT/proj-base ]] && { print -r -- "STOP: $ROOT/proj or proj-base exists. Remove them yourself, then rerun: rm -rf $ROOT/proj $ROOT/proj-base $ROOT/venv* $ROOT/src-* $ROOT/wheels-* && zsh $THIS pre"; return 1; }
  print -r -- "GitHub refs at the base $BASE: $(git ls-remote $URL | grep $BASE | cut -f2 | tr '\n' ' ')"
  print -r -- "GitHub $BRANCH: $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) (candidate GCOMMIT=${GCOMMIT:-not set yet})"
  login_check || return 1
  mkdir -p $ROOT/proj $ROOT/proj-base || return 1
  print -r -- "created $ROOT/proj-base (base project) and $ROOT/proj (candidate project)"
  local mark=$ROOT/pre-start.mark; : > $mark
  say "one-line prompt (model $CMODEL) in $ROOT: its model and login source"
  (cd $ROOT && claude_env $(command -v claude) -p --model $CMODEL --output-format stream-json --verbose \
     "Reply in one line with the model id you are running as and nothing else." < /dev/null > $ROOT/pre.jsonl 2>&1)
  local rc=$?
  python3 -I -c 'import json, sys
for line in open(sys.argv[1], errors="replace"):
    try: e = json.loads(line)
    except ValueError: print("non-JSON:", line.strip()[:300]); continue
    if e.get("type") == "system" and e.get("subtype") == "init": print("init: model", e.get("model"), "apiKeySource", e.get("apiKeySource"))
    if e.get("type") == "result": print("answer:", str(e.get("result"))[:300], "| is_error", e.get("is_error"))' $ROOT/pre.jsonl
  print -r -- "exit=$rc"
  changed_claude $mark
  (( rc == 0 )) || { print -r -- "STOP: Claude Code did not answer with this login; fix the login, then: rm -rf $ROOT/proj $ROOT/proj-base && zsh $THIS pre"; return 1; }
  print "Success: a model id, its login source and exit=0."
  print -r -- "next: (after asking the user) zsh $THIS push; then zsh $THIS probe; zsh $THIS repro (same login variables)"
  ;;
push)
  say "[push] Main, after the user agreed. Push $BRANCH (${GCOMMIT:-unset}) to $URL from $BUNDLE. Dialog: none expected. ~30 s."
  [[ -n $GCOMMIT ]] || { print "STOP: GCOMMIT is not set in this script; ask the Engineer"; return 1; }
  local G=${TMPDIR:-/tmp}/graftling-576-push.git
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { print "already on GitHub"; print -r -- "next: zsh $THIS probe"; return 0; }
  [[ -f $BUNDLE ]] || { print -r -- "STOP: $BUNDLE missing; ask the Engineer"; return 1; }
  rm -rf $G && git clone -q --bare $URL $G || return 1
  git -C $G fetch -q $BUNDLE "${BRANCH}:${BRANCH}" || return 1
  [[ $(git -C $G rev-parse $BRANCH) == $GCOMMIT ]] || { print "STOP: the bundle's branch is not $GCOMMIT"; return 1; }
  print -r -- "authors and committers: $(git -C $G log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $G push $URL "${BRANCH}:refs/heads/${BRANCH}" || return 1
  print -r -- "on GitHub now: $(git ls-remote $URL refs/heads/$BRANCH)"
  rm -rf $G
  print "Success: the GitHub line above shows $GCOMMIT."
  print -r -- "next: zsh $THIS probe"
  ;;
probe)
  say "[probe] Main. DIAGNOSIS, not acceptance: the candidate's probe against the installed claude. Dialog: none. ~1-2 min."
  [[ -n $GCOMMIT ]] || { print "STOP: GCOMMIT is not set in this script; ask the Engineer"; return 1; }
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] || { print -r -- "STOP: $GCOMMIT is not on GitHub; run: zsh $THIS push"; return 1; }
  install_wheel cand $GCOMMIT || return 1
  local exe=${$(command -v claude):A} version; version=$(env -i HOME=$HOME PATH=$PATH CLAUDE_CONFIG_DIR=$ROOT/probe-version $exe --version 2>&1)
  rm -rf $ROOT/probe-version $ROOT/probe-state
  print -r -- "executable $exe; version $version; model $CMODEL; permission mode auto"
  say "probe_default_tools (state $ROOT/probe-state)"
  claude_env CLAUDE_CODE_SDK_READS_SESSION_STATE=1 CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 \
    $V/bin/python -I -c 'import json, os, sys, time
from pathlib import Path
from graftling.claude.execution import (probe_default_tools, read_init_tools, tool_probe_argv,
                                        tool_probe_environment, tool_probe_key)
exe, version, model, state = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
env = dict(os.environ)
print("probe argv:", json.dumps(tool_probe_argv(exe, model, "auto")))
started = time.monotonic()
try:
    tools = probe_default_tools(exe, version, model, "auto", env, state)
except Exception as error:
    print("STOP: the probe failed:", type(error).__name__, error); sys.exit(1)
print("probed set (%d, %.1f s): %s" % (len(tools), time.monotonic() - started, json.dumps(tools)))
for name in ("Bash", "WebFetch", "Glob", "Grep", "Read", "Edit", "Write"):
    print("  %s: %s" % (name, "present" if name in tools else "absent"))
key = tool_probe_key(exe, version, model, "auto", env)
cache = state / "claude-default-tools" / (key + ".json")
print("cache file:", cache, "exists" if cache.exists() else "MISSING")
print("left in", state / "claude-default-tools", ":", sorted(p.name for p in (state / "claude-default-tools").iterdir()))
scratch = state / "safe-mode"; (scratch / "home").mkdir(parents=True); (scratch / "cwd").mkdir()
safe, cause = read_init_tools(tool_probe_argv(exe, model, "auto") + ["--safe-mode"],
                              tool_probe_environment(env, scratch / "home"), scratch / "cwd")
print("for comparison, + --safe-mode:", json.dumps(safe), "" if safe else cause)
if safe is not None:
    print("  only without --safe-mode:", sorted(set(tools) - set(safe)), "only with:", sorted(set(safe) - set(tools)))
' $exe "$version" $CMODEL $ROOT/probe-state || return 1
  print "Success: the probe read a set without a model call."
  print -r -- "next: zsh $THIS repro"
  ;;
repro)
  say "[repro] Main. The premise on the BASE $BASE through the real entry. Dialog: none. ~3-5 min."
  login_check || return 1
  install_wheel base $BASE || return 1
  accept repro || { print "FAIL or PREMISE NOT REPRODUCED: see the verdicts above"; return 1; }
  print "Success: the base child without tools has no Bash; tools [Read] and disallowed [Bash] have none either."
  print -r -- "next: (after push) zsh $THIS check"
  ;;
check)
  say "[check] Main. The CANDIDATE ${GCOMMIT:-unset} through the real entry. Dialog: none. ~3-5 min."
  [[ -n $GCOMMIT ]] || { print "STOP: GCOMMIT is not set in this script; ask the Engineer"; return 1; }
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] || { print -r -- "STOP: $GCOMMIT is not on GitHub; run: zsh $THIS push"; return 1; }
  login_check || return 1
  install_wheel cand $GCOMMIT || return 1
  accept check || { print "FAIL: see the verdicts above"; return 1; }
  print "Success: the child without tools ran Bash; tools [Read] and disallowed [Bash] still have no Bash."
  print -r -- "next: report $OUT to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS diagnose|pre|push|probe|repro|check"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY576_OUT:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
{ run_step; print -r -- "STEP-END rc=$?"; } 2>&1 | tee $OUT/$STEP.txt
local rc=$?
grep -q '^STEP-END rc=0$' $OUT/$STEP.txt || { print -r -- "FAIL: the step did not end with rc=0 (see above)" | tee -a $OUT/$STEP.txt; (( rc )) || rc=1; }
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
