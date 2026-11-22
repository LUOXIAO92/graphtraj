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
*) print -r -- "usage: zsh $THIS diagnose"; return 2 ;;
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
