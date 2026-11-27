#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 652 Main-run steps: publish graftling's three Claude-host fixes (a call refused before the plugin's hook reached
# the host names the unloaded plugin and the folder trust; a context step run under the same Claude Code is refused as
# such; the marketplace plugin on native Windows says it is unsupported and names configuration --write; from the
# bundle) to LUOXIAO92/graftling as agent/652-graftling-windows-claude-host-polish, so GitHub Actions runs "Windows
# tests" (.github/workflows/windows.yml) for the candidate commit on GitHub-hosted windows-latest x64 runners: the
# unchanged windows-tests (632) and dsh-windows-tests (649) jobs, and claude-real-entry, which this candidate appends
# and which runs only on this branch or by hand: real Claude Code 2.1.314 (release binary, SHA-256 checked against its
# release manifest) against a local stub of the Messages API with a dummy token (.github/claude_real_entry.py). The
# step waits for the run in this process, downloads the artifacts and judges them. Step M runs the same driver with
# real Claude Code on this Mac, for the base and the candidate. Modelled on verify-649/steps.zsh (P, W, X) and
# verify-650/steps.zsh step M; verify-632/wincheck.py judges windows-tests by reference, wincheck652.py the rest.
#
# LOGIN: the user's own logins only. graftling push / ls-remote use https with the user's git credential helper
# (osxkeychain); gh uses its stored login (gh auth status shows the account; no token is printed). No model and no
# Claude login anywhere: Claude Code talks only to the local stub (127.0.0.1) with the dummy token
# dummy-not-a-key-652, in temporary home and config directories; the user's ~/.claude, ~/.claude.json, settings and
# login are neither read nor changed. GH_TOKEN/GITHUB_TOKEN and every other credential-class variable are removed at
# start. Nothing of GraphTraj is pushed.
# DIALOGS: 00, P, W, X: none (GH_PROMPT_DISABLED=1, GIT_TERMINAL_PROMPT=0; a credential helper that needs a dialog fails
# the push instead, and the step STOPs). M: at most one, a macOS Keychain prompt for a 'Claude Code-credentials' item
# (expected none: the temporary config has no such item and a token is set); if it appears, choose Deny. The stub
# listens on 127.0.0.1 only (no firewall prompt expected).
# EVIDENCE: below scripts/verify-652/evidence/ (git-ignored by scripts/verify-652/.gitignore); no tracked file changes.
# Run one step at a time:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git, gh, uv versions; gh auth status (account only); <Harness>/graftling origin is
#       https://github.com/LUOXIAO92/graftling.git; the bundle verifies against <Harness>/graftling with prerequisite
#       graftling dev b179984, and its head contains b179984; read through a temporary repository that borrows
#       <Harness>/graftling's objects (nothing is written there): noreply identity; the paths changed since b179984 are
#       within ALLOWED (below); the workflow is b179984's with its push branches line gaining exactly this branch and
#       the claude-real-entry job appended (windows-tests and dsh-windows-tests unchanged; the new job's condition,
#       runner, pins, credentials, SHA-256 check, gating and upload), and both the base and the head workflow pass
#       632's wfcheck; .github/run_test_files.py and tests/posix_only.py are unchanged; the tests of new-tests.txt are
#       defined at the head; windows-expected.txt parses (this Task owns none of its lines; any difference from
#       GraphTraj d9954f5d's is another Task's and only noted); the local branch in <Harness>/graftling and the remote
#       branch are each absent, the bundle head, or an ancestor of it (else STOP). Login: gh login, git credential
#       helper (ls-remote). Dialog: none. Network: GitHub. ~10 s.
#   P   Publish and wait. OUTWARD-FACING: (1) fetches the bundle into <Harness>/graftling as the local branch (only if
#       absent or an ancestor; git fetch without '+' is fast-forward only); (2) pushes it to graftling origin,
#       fast-forward only, never force, and verifies with ls-remote; (3) waits in this process for the windows.yml
#       push run of that SHA (appearance bound 300 s, completion bound 6000 s, poll 30 s); (4) judges it (below),
#       saving the artifacts, the job logs and the judgement under scripts/verify-652/evidence/live/run-<id>-a<n>/;
#       (5) the real-entry items, the next commands and the VERDICT last. Login: git credential helper, gh login.
#       Dialog: none. Network: GitHub. Up to ~105 min.
#   W   Observe only (no push, no re-run): `W <run-id>` that run; `W` the push run of the remote branch head;
#       `W <sha>` the newest windows.yml run of that commit (any event). Same waiting and judging as P.
#   X   `X <run-id>`: re-run the failed jobs of one completed, failed windows.yml run of this branch (gh run rerun
#       --failed), for transient failures only (a runner or download fault, not a test result). OUTWARD-FACING.
#       Waits for the new attempt (300 s) and its completion (6000 s), then judges it like P.
#   M   On this Mac, no push: real Claude Code 2.1.314 (release binary for this Mac, SHA-256 checked against its
#       manifest) with graftling installed by uv tool install --managed-python from the bundle's base (b179984) and
#       candidate checkouts, each into its own tool directory, all inside one temporary directory under
#       ${TMPDIR:-/tmp} (outside the Harness), deleted at the end. The candidate's .github/claude_real_entry.py runs:
#       base: market; candidate: market, untrusted, caller. Login: none. Dialog: at most one Keychain prompt (above).
#       Network: downloads.claude.ai (Claude Code), PyPI and uv's Python downloads; the stub on 127.0.0.1. ~5-10 min.
# OBSERVABLES (what proves each required result):
#   R1  claude-real-entry item 'untrusted R1 ...' (and M's): real Claude Code in an untrusted folder offers
#       mcp__graftling__subagents, the generated plugin is not in init's plugins, and the call's tool_result is
#       authority-denied naming 'has not loaded it' and 'folder trust'; host.log has one 'subagents-call refused:'.
#   R2  claude-real-entry item 'market R2 native Windows ...': init lists graftling@<version>, its server is not
#       connected, a system/ui_log event from plugin graftling names 'not supported on native Windows' and
#       'configuration --write', and host.log holds that line. M: 'market R2 POSIX ...' PASS at base and candidate with
#       the same init plugins and server status (connected), no ui_log naming Windows (MCOMPARE).
#   R3  claude-real-entry item 'caller R3 ...' (and M's): the Bash tool's context step result says 'not started by
#       Claude Code itself' with 'Claude Code pid N', not 'another Claude Code session', exit=1; the same session's
#       subagents call is then answered (plugin loaded in the trusted folder).
#   R4  docs in the bundle (README, PUBLIC_API.md, docs/install/claude-code.md, CHANGELOG): read by the Leader.
# VERDICT (P, W, X): PASS only when ALL of
#   windows-tests mechanics and results as 632, against scripts/verify-632/windows-expected.txt;
#   652 tests: every node id of new-tests.txt PASSED in windows-tests' JUnit;
#   dsh-windows-tests: the job and every step succeeded (649's gating job, unchanged);
#   claude-real-entry: the job and every step succeeded, and its artifact's results.json has every item PASS on win32.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*, OPENAI_*,
# DEEPSEEK_*, CODEX_*, CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing only how many.
# Every started process runs through allow() (00, P, W, X: HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set
# SSH_AUTH_SOCK, GH_CONFIG_DIR, XDG_CONFIG_HOME) or, in M, menv (HOME, TMPDIR and uv's directories in the temporary
# directory). No provider credential is passed.
# TMPDIR: kept outside the Harness (a TMPDIR inside it is replaced by /tmp).
# Rehearsal knobs (Engineer only): VERIFY652_GRAFTLING (a scratch graftling clone instead of <Harness>/graftling),
# VERIFY652_GREMOTE (push/ls-remote target), VERIFY652_GH (a gh stand-in), VERIFY652_EVIDENCE (evidence root),
# VERIFY652_BUNDLE (another bundle), VERIFY652_APPEAR_S / _DONE_S / _POLL_S (bounds), VERIFY652_M_CLAUDE (a Claude Code
# binary already fetched), VERIFY652_M_PYTHON_BASE / _CAND (graftling Pythons instead of uv installs). Unset, every
# step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
REL=scripts/verify-652/steps.zsh
STEP=${1:-}
BRANCH=agent/652-graftling-windows-claude-host-polish
# graftling dev b179984: W0-W11 (632-649) and 651's docs.
BASE=b179984235decfedfe7ff3ec1d032b5399a712cb
# GraphTraj dev with the expected list as 651 left it; this Task owns none of its lines.
LIST_BASE=d9954f5d
REPO=LUOXIAO92/graftling
GURL=https://github.com/LUOXIAO92/graftling.git
# The Harness holds this Worktree at .graphtraj/core/worktrees/<name>.
HARNESS=${WT:A:h:h:h:h}
GRAFT=${VERIFY652_GRAFTLING:-$HARNESS/graftling}
GREMOTE=${VERIFY652_GREMOTE:-origin}
GH=${VERIFY652_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
# A Python with PyYAML for the workflow checks (the one 647-650's steps used), else the system's.
PY=$HOME/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY652_APPEAR_S:-300}
DONE_S=${VERIFY652_DONE_S:-6000}
POLL_S=${VERIFY652_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
[[ ${PYTMP:A} == ${HARNESS}(|/*) ]] && PYTMP=/tmp
CLAUDE_VERSION=2.1.314
WORKFLOW=.github/workflows/windows.yml
JOB=windows-tests
DSHJOB=dsh-windows-tests
REALJOB=claude-real-entry
BUNDLE=${VERIFY652_BUNDLE:-$HERE/graftling-652.bundle}
WINCHECK=$WT/scripts/verify-632/wincheck.py
EXPECTED=$WT/scripts/verify-632/windows-expected.txt
EVROOT=${VERIFY652_EVIDENCE:-$HERE/evidence}
EVID=$EVROOT/live
NEWTESTS=$HERE/new-tests.txt
# The only paths the candidate may change since BASE.
ALLOWED=(.github/claude_real_entry.py .github/workflows/windows.yml CHANGELOG.md PUBLIC_API.md README.md
         docs/install/claude-code.md src/graftling/claude-plugin/hooks/host_context.mjs src/graftling/claude/host.py
         src/graftling/claude/host_context.mjs src/graftling/claude/native_host.py
         tests/test_claude_host_messages_652.py tests/test_claude_windows_647.py)
# The windows-tests job's steps by their exact `name:` in $WORKFLOW (unchanged from 632).
SETUP=("Keep symbolic links on this runner"
       "Check out the commit under test"
       "Fail unless the linked package documents are symbolic links"
       "Set up Node 22.18.0 x64"
       "Set up Python 3.13.7 x64"
       "Install graftling and pinned test tools"
       "Show runner, Python and pytest versions")
SUITE="Run the graftling test suite"
UPLOAD="Retain JUnit results"

say() { print -r -- "== $*"; }
is_cred() {  # graftling's is_credential_name, restated
  local name=${(U)1} part
  [[ $name == GIT_CONFIG_KEY_<-> ]] && return 1
  for part in ${(s:_:)name}; do [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && return 0; done
  return 1
}
scrub() {
  local k; local -a removed=()
  for k in ${(k)parameters[(R)*export*]}; do
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == OPENAI_* || $k == DEEPSEEK_* || $k == CODEX_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAFTLING_CONNECTION ]]; then
      unset $k; removed+=$k
    fi
  done
  print -r -- "scrubbed at start: ${#removed} variable(s) (names not shown)"
}
scrub
APATH=${GH:h}:${GIT:h}:/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables.
allow() {
  local -a extra=()
  [[ -n ${SSH_AUTH_SOCK:-} ]] && extra+=SSH_AUTH_SOCK=$SSH_AUTH_SOCK
  [[ -n ${GH_CONFIG_DIR:-} ]] && extra+=GH_CONFIG_DIR=$GH_CONFIG_DIR
  [[ -n ${XDG_CONFIG_HOME:-} ]] && extra+=XDG_CONFIG_HOME=$XDG_CONFIG_HOME
  /usr/bin/env -i HOME=$HOME USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=$PYTMP LANG=en_US.UTF-8 GH_PROMPT_DISABLED=1 GIT_TERMINAL_PROMPT=0 $extra "$@"
}
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 652 $STEP: STOP"; exit 1; }
gg() { allow $GIT -C $GRAFT "$@"; }
wc_() { allow $PY -I $WINCHECK "$@"; }
w652_() { allow $PY -I $HERE/wincheck652.py "$@"; }
WORK=$(mktemp -d $PYTMP/verify652.XXXXXX)
trap 'rm -rf $WORK' EXIT

# api <file> <endpoint>: save a gh api response; on failure print the error and return 1.
api() {
  allow $GH api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}

GSHA=
bundle_head() { allow $GIT bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1; }
# Every prerequisite the bundle lists, one per line (as verify-634).
bundle_prereqs() { gg bundle verify $BUNDLE 2>&1 | awk '/^The bundle requires/ {on = 1; next} /^The bundle (uses|contains)/ {on = 0} on && NF {print $1}'; }
check_bundle() {  # the bundle verifies against $GRAFT; BASE is a prerequisite, any other an ancestor of it; sets GSHA
  [[ -f $BUNDLE ]] || stop "no bundle at $BUNDLE"
  gg bundle verify $BUNDLE > /dev/null 2>&1 || { gg bundle verify $BUNDLE 2>&1 | sed 's/^/  /'; stop "the bundle does not verify against $GRAFT"; }
  GSHA=$(bundle_head)
  [[ $GSHA == [0-9a-f](#c40) ]] || stop "the bundle has no refs/heads/$BRANCH"
  local -a prereqs=(${(f)"$(bundle_prereqs)"})
  local prereq
  (( ${prereqs[(Ie)$BASE]} )) || stop "the bundle's prerequisites are ${prereqs:-none}, without graftling dev $BASE"
  for prereq in $prereqs; do
    [[ $prereq == $BASE ]] && continue
    gg merge-base --is-ancestor $prereq $BASE 2> /dev/null \
      || stop "the bundle's prerequisite $prereq is not an ancestor of graftling dev $BASE"
  done
  ancestor_of_head $BASE || stop "graftling dev $BASE is not an ancestor of the bundle head $GSHA"
  print -r -- "PASS: bundle verifies against $GRAFT; head $GSHA contains graftling dev $BASE (prerequisites: ${prereqs})"
}
# check_head: read the bundle head through a temporary repository borrowing $GRAFT's objects (read only there);
# returns the number of FAILs.
PEEK=$WORK/peek.git
peek_repo() {  # once: $PEEK holds the bundle head as refs/heads/peek, borrowing $GRAFT's objects
  [[ -d $PEEK ]] && return 0
  allow $GIT init -q --bare $PEEK || stop "cannot make a temporary repository"
  print -r -- "$(gg rev-parse --path-format=absolute --git-common-dir)/objects" > $PEEK/objects/info/alternates
  allow $GIT -C $PEEK fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/peek 2> $WORK/peek-err \
    || stop "cannot read the bundle: $(<$WORK/peek-err)"
}
# test_files <sha> <out>: the commit's tests/test_*.py, one per line, when the commit is known here; else nothing.
test_files() {
  peek_repo
  allow $GIT -C $PEEK cat-file -e "$1^{commit}" 2> /dev/null || return 1
  allow $GIT -C $PEEK ls-tree --name-only $1 tests/ | grep -E '^tests/test_[^/]*\.py$' > $2
}
check_head() {
  local peek=$PEEK bad=0 changed one which
  local -a extra=()
  peek_repo
  print -r -- "--- bundle commits on $BASE:"
  allow $GIT -C $peek log --format='  %h %an <%ae> | %cn <%ce> | %s' $BASE..peek
  local idents=$(allow $GIT -C $peek log --format='%ae%n%ce' $BASE..peek | sort -u)
  [[ $idents == 89069722+LUOXIAO92@users.noreply.github.com ]] && print -r -- "PASS: author and committer are the noreply identity" \
    || { print -r -- "FAIL: identities in the bundle: ${(f)idents}"; (( bad++ )); }
  print -r -- "--- files changed since $BASE:"; allow $GIT -C $peek diff --stat $BASE peek | sed 's/^/  /'
  changed=$(allow $GIT -C $peek diff --name-only $BASE peek)
  for one in ${(f)changed}; do (( ${ALLOWED[(Ie)$one]} )) || extra+=$one; done
  (( ${#extra} == 0 )) && print -r -- "PASS: changed paths are within the allowed set: ${(j:, :)ALLOWED}" \
    || { print -r -- "FAIL: paths changed outside the allowed set: ${(j:, :)extra}"; (( bad++ )); }
  allow $GIT -C $peek show ${BASE}:${WORKFLOW} > $WORK/windows-base.yml 2> /dev/null \
    || { print -r -- "FAIL: no $WORKFLOW at $BASE"; return $(( bad + 1 )); }
  allow $GIT -C $peek show peek:$WORKFLOW > $WORK/windows-head.yml 2> /dev/null \
    || { print -r -- "FAIL: no $WORKFLOW at $GSHA"; return $(( bad + 1 )); }
  print -r -- "--- $WORKFLOW at $GSHA against $BASE"
  w652_ wfdiff $WORK/windows-base.yml $WORK/windows-head.yml || (( bad++ ))
  for which in base head; do
    print -r -- "--- $WORKFLOW at the $which: the windows-tests job and the whole file by 632's wfcheck"
    if w652_ as632 $WORK/windows-$which.yml $WORK/windows-$which-632.yml; then
      wc_ wfcheck $WORK/windows-$which-632.yml agent/632-graftling-windows-ci $JOB $SETUP $SUITE $UPLOAD || (( bad++ ))
    else
      (( bad++ ))
    fi
  done
  allow $GIT -C $peek diff --quiet $BASE peek -- .github/run_test_files.py tests/posix_only.py \
    && print -r -- "PASS: .github/run_test_files.py and tests/posix_only.py unchanged since $BASE" \
    || { print -r -- "FAIL: .github/run_test_files.py or tests/posix_only.py changed"; (( bad++ )); }
  local missing=0 node fn
  for node in ${(f)"$(grep -v '^#' $NEWTESTS)"}; do
    fn=${${node#*::}%%\[*}
    allow $GIT -C $peek show "peek:${node%%::*}" > $WORK/newtest.py 2> /dev/null || : > $WORK/newtest.py
    grep -q "^def $fn(" $WORK/newtest.py || { print -r -- "FAIL: $node is not defined at $GSHA"; (( missing++ )); }
  done
  (( missing == 0 )) && print -r -- "PASS: the $(grep -vc '^#' $NEWTESTS) tests of new-tests.txt are defined at $GSHA"
  return $(( bad + missing ))
}
check_list() {  # the expected list parses; this Task owns none of its lines, so a difference is only noted
  local bad=0
  wc_ expected $EXPECTED || (( bad++ ))
  allow $GIT -C $WT show ${LIST_BASE}:scripts/verify-632/windows-expected.txt > $WORK/expected-base.txt 2> /dev/null \
    || { print -r -- "FAIL: GraphTraj $LIST_BASE is not readable here"; return $(( bad + 1 )); }
  if cmp -s $WORK/expected-base.txt $EXPECTED; then
    print -r -- "PASS: windows-expected.txt is GraphTraj $LIST_BASE's (652 changes none of its lines)"
  else
    print -r -- "NOTE: windows-expected.txt differs from GraphTraj $LIST_BASE's; 652 owns none of its lines, so the change is another Task's:"
    diff $WORK/expected-base.txt $EXPECTED | grep '^[<>]' | cut -c1-200 | sed 's/^/  /'
  fi
  return $bad
}
ancestor_of_head() {  # is $1 an ancestor of the bundle head? (read in $PEEK, which holds the bundle's commits)
  peek_repo
  allow $GIT -C $PEEK merge-base --is-ancestor $1 peek 2> /dev/null
}
graft_local_ok() {  # local branch in $GRAFT: absent or an ancestor (0: P fetches, fast-forward), equal (1); else STOP
  local lsha=$(gg rev-parse -q --verify refs/heads/$BRANCH)
  if [[ -z $lsha ]]; then print -r -- "PASS: $GRAFT has no local $BRANCH (P creates it from the bundle)"; return 0; fi
  [[ $lsha == $GSHA ]] && { print -r -- "PASS: $GRAFT local $BRANCH = bundle head"; return 1; }
  ancestor_of_head $lsha || stop "$GRAFT has local $BRANCH at $lsha, not an ancestor of the bundle head $GSHA; never overwrite. Inspect: git -C $GRAFT log --oneline -3 $BRANCH"
  print -r -- "PASS: $GRAFT local $BRANCH is at $lsha, an ancestor of the bundle head (P fast-forwards it from the bundle)"
  return 0
}
# The branch head on the remote, empty when absent, "ERR <text>" when ls-remote fails (checked() then STOPs).
gremote_sha() { local out; out=$(gg ls-remote $GREMOTE refs/heads/$BRANCH 2>&1) || { print -r -- "ERR $out"; return 0; }; print -r -- ${out%%$'\t'*}; }
checked() { [[ ${1:-} != ERR* ]] || stop "git ls-remote failed (nothing was pushed): ${1#ERR }"; }
REMOTE_STATE=
graft_remote_ok() {  # absent, equal, or an ancestor of the bundle head (fast-forward); else STOP
  local rsha=$(gremote_sha)
  checked $rsha
  if [[ -z $rsha ]]; then REMOTE_STATE=absent; print -r -- "PASS: $BRANCH is absent on graftling $GREMOTE"
  elif [[ $rsha == $GSHA ]]; then REMOTE_STATE=equal; print -r -- "PASS: graftling $GREMOTE already has $BRANCH at the bundle head"
  elif ancestor_of_head $rsha; then
    REMOTE_STATE=ancestor; print -r -- "PASS: graftling $GREMOTE has $BRANCH at $rsha, an ancestor of the bundle head (fast-forward)"
  else
    stop "graftling $GREMOTE has $BRANCH at $rsha, not an ancestor of the bundle head; never force. Inspect: git -C $GRAFT fetch $GREMOTE $BRANCH && git -C $GRAFT log --oneline -5 FETCH_HEAD"
  fi
}

# judge <run-json-file> <label>: the run is completed; print jobs, fetch evidence, judge; ends with the VERDICT.
judge() {
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res files newt djob rjob real
  rid=$(wc_ get $runfile id); sha=$(wc_ get $runfile head_sha); attempt=$(wc_ get $runfile run_attempt)
  concl=$(wc_ get $runfile conclusion); url=$(wc_ get $runfile html_url); event=$(wc_ get $runfile event)
  dir=$EVID/run-$rid-a${attempt:-1}
  mkdir -p $dir
  print -r -- "--- run $rid | attempt $attempt | $event | conclusion $concl (information only) | head $sha | $url"
  [[ -z $GSHA || $sha == $GSHA ]] || print -r -- "NOTE: run head $sha is not the bundle head $GSHA"
  allow $PY -I -c 'import json, sys; print(json.dumps({"job": sys.argv[1], "setup": sys.argv[2:-2], "suite": sys.argv[-2], "upload": sys.argv[-1]}))' \
    $JOB $SETUP $SUITE $UPLOAD > $WORK/config.json
  if api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/attempts/${attempt:-1}/jobs?per_page=100"; then
    cp $WORK/jobs.json $dir/jobs.json
    wc_ jobs $WORK/jobs.json $WORK/config.json > $WORK/jobs.txt 2>&1
    w652_ jobstate $WORK/jobs.json $DSHJOB > $WORK/dshjob.txt 2>&1
    w652_ jobstate $WORK/jobs.json $REALJOB > $WORK/realjob.txt 2>&1
  else
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/dshjob.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/realjob.txt
  fi
  cat $WORK/jobs.txt $WORK/dshjob.txt $WORK/realjob.txt > $dir/jobs.txt
  grep -v '^JUDGE \|^JOB ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  grep -v '^JOBSTATE ' $WORK/dshjob.txt | head -3
  djob=$(grep '^JOBSTATE ' $WORK/dshjob.txt | tail -1); [[ -n $djob ]] || djob="JOBSTATE FAIL $DSHJOB judgement failed"
  grep -v '^JOBSTATE ' $WORK/realjob.txt
  rjob=$(grep '^JOBSTATE ' $WORK/realjob.txt | tail -1); [[ -n $rjob ]] || rjob="JOBSTATE FAIL $REALJOB judgement failed"
  # Each job's log (ANSI colour codes need --allow-escape-sequences, 619); kept with the evidence.
  local jname
  for jname in $JOB $REALJOB; do
    jid=$(allow $PY -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == sys.argv[2]), ""))' $WORK/jobs.json $jname 2> /dev/null)
    if [[ -n $jid ]] && allow $GH api --allow-escape-sequences "repos/$REPO/actions/jobs/$jid/logs" > $dir/$jname.log 2> $WORK/err; then
      print -r -- "--- job log saved: $dir/$jname.log"
    else
      print -r -- "$jname job log unavailable: $(<$WORK/err 2> /dev/null)"
    fi
  done
  [[ -f $dir/$JOB.log ]] && grep -E '(### HUNG|run_test_files exit code:|INTERNALERROR|has timed out)' $dir/$JOB.log | tail -n 12 | cut -c1-240 | sed 's/^/  /'
  # The windows-tests JUnit artifact of this attempt.
  local name=graftling-windows-junit-$sha-${attempt:-1} rname=graftling-claude-real-entry-$sha-${attempt:-1} tlist=
  if [[ -f $dir/junit/environment.json ]]; then
    print -r -- "already present, not downloaded again: $dir/junit"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dir/junit"
    allow $GH run download $rid --repo $REPO -n $name -D $dir/junit 2>&1 | sed 's/^/  /'
  fi
  if test_files $sha $WORK/testfiles.txt; then
    tlist=$WORK/testfiles.txt; print -r -- "test files in $sha: $(grep -c . $tlist)"
  else
    print -r -- "NOTE: $sha is not in the bundle; per-file records are not compared with its test files"
  fi
  if [[ -f $dir/junit/environment.json ]]; then
    print -r -- "--- per-file records and results against $EXPECTED"
    wc_ junit $dir/junit $EXPECTED $dir/observed-expected.txt $tlist > $dir/judgement.txt 2>&1
    grep -v '^JUDGE \|^FILES ' $dir/judgement.txt
    files=$(grep '^FILES ' $dir/judgement.txt | tail -1); [[ -n $files ]] || files="FILES FAIL per-file judgement failed: $(tail -2 $dir/judgement.txt)"
    res=$(grep '^JUDGE ' $dir/judgement.txt | tail -1); [[ -n $res ]] || res="JUDGE FAIL JUnit judgement failed: $(tail -2 $dir/judgement.txt)"
    w652_ newtests $dir/junit $NEWTESTS > $dir/652-tests.txt 2>&1
    newt=$(grep '^NEWTESTS ' $dir/652-tests.txt | tail -1); [[ -n $newt ]] || newt="NEWTESTS FAIL check failed: $(tail -2 $dir/652-tests.txt)"
  else
    files="FILES FAIL no artifact downloaded ($name)"; res="JUDGE FAIL no JUnit files"; newt="NEWTESTS FAIL no JUnit files"
    print -r -- "NEWTESTS FAIL no JUnit files" > $dir/652-tests.txt
  fi
  if [[ $files == "FILES FAIL"* ]]; then
    [[ $mech == "JUDGE PASS"* ]] && mech="JUDGE FAIL ${files#FILES FAIL }" || mech="$mech; ${files#FILES FAIL }"
  else
    mech="$mech; ${files#FILES PASS }"
  fi
  grep -v '^NEWTESTS ' $dir/652-tests.txt
  # The real Claude Code artifact: every item, printed last before the next commands and the VERDICT.
  if [[ -f $dir/real-entry/results.json ]]; then
    print -r -- "already present, not downloaded again: $dir/real-entry"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $rname -D $dir/real-entry"
    allow $GH run download $rid --repo $REPO -n $rname -D $dir/real-entry 2>&1 | sed 's/^/  /'
  fi
  w652_ realentry $dir/real-entry > $dir/real-entry-judgement.txt 2>&1
  grep -v '^REALENTRY ' $dir/real-entry-judgement.txt
  real=$(grep '^REALENTRY ' $dir/real-entry-judgement.txt | tail -1); [[ -n $real ]] || real="REALENTRY FAIL judgement failed: $(tail -2 $dir/real-entry-judgement.txt)"
  print -r -- "evidence: $dir (git-ignored)"
  print -r -- "next: zsh $REL W $rid    (observe again; no push, no re-run)"
  [[ $concl != success ]] && print -r -- "next: zsh $REL X $rid    (re-run its failed jobs; only if the failure is transient, not a test result)"
  [[ $res == "JUDGE FAIL"* || $newt == "NEWTESTS FAIL"* ]] && print -r -- "next: correction round: compare $dir/observed-expected.txt with $EXPECTED and read $dir/652-tests.txt"
  [[ $real == "REALENTRY FAIL"* ]] && print -r -- "next: correction round: read $dir/real-entry/ (each case's stdout, debug lines, host.log) and $dir/$REALJOB.log"
  if [[ $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* && $newt == "NEWTESTS PASS"* && $djob == "JOBSTATE PASS"* \
        && $rjob == "JOBSTATE PASS"* && $real == "REALENTRY PASS"* ]]; then
    print -r -- "VERDICT 652 $label: PASS (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; 652 tests: ${newt#NEWTESTS PASS }; ${djob#JOBSTATE PASS }; ${rjob#JOBSTATE PASS }; real Claude Code: ${real#REALENTRY PASS }; $url)"
    exit 0
  fi
  print -r -- "VERDICT 652 $label: FAIL (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE }; results: ${res#JUDGE }; 652 tests: ${newt#NEWTESTS }; ${djob#JOBSTATE }; ${rjob#JOBSTATE }; real Claude Code: ${real#REALENTRY }; $url)"
  exit 1
}

# wait_run <run-id> <label>: wait for completion (bounded), then judge.
wait_run() {
  local rid=$1 label=$2 start=$SECONDS rstate= prev= line
  print -r -- "waiting for run $rid (completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    api $WORK/run.json repos/$REPO/actions/runs/$rid && rstate=$(wc_ get $WORK/run.json status)
    line="${rstate:-unknown} $(wc_ get $WORK/run.json conclusion 2> /dev/null)"
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] run $rid: $line"; prev=$line
    [[ $rstate == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "completion timeout after $((SECONDS - start))s (run still ${rstate:-unknown})"
      print -r -- "next: zsh $REL W $rid    (observe again; no push, no re-run)"
      print -r -- "VERDICT 652 $label: FAIL (run $rid not completed within ${DONE_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  judge $WORK/run.json $label
}

# find_run <sha> <event|-> <label>: wait (bounded) for the newest windows.yml run of sha, then wait_run.
find_run() {
  local sha=$1 event=$2 label=$3 start=$SECONDS row rid
  local -a rows f
  print -r -- "looking for the $WORKFLOW run (event ${event/-/any}) of $sha on $REPO (appearance bound ${APPEAR_S}s, poll ${POLL_S}s)"
  while true; do
    if api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$sha&per_page=100"; then
      rows=("${(@f)$(wc_ runs $WORK/runs.json $WORKFLOW $event)}")
    else rows=("MISSING"); fi
    row=${${(M)rows:#RUN*}[1]:-}
    [[ -n $row ]] && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s: no $WORKFLOW run for $sha"
      print -r -- "next: zsh $REL W $sha    (re-observe; no push)"
      print -r -- "VERDICT 652 $label: FAIL (the $WORKFLOW run never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  f=("${(@ps:\t:)row}"); rid=$f[3]
  print -r -- "run $rid present after $((SECONDS - start))s: ${f[7]} | ${f[6]}"
  wait_run $rid $label
}

# --- M: real Claude Code on this Mac ------------------------------------------------------------
step_m() {
  say "[M] Real Claude Code $CLAUDE_VERSION on this Mac with graftling base ${BASE[1,8]} and candidate, no push. Login: none (a local stub, dummy token). Dialog: at most one macOS Keychain prompt for a 'Claude Code-credentials' item (expected none); if it appears, choose Deny. Network: downloads.claude.ai, PyPI, uv's Python downloads; the stub on 127.0.0.1."
  check_bundle
  local T=$WORK/m MOUT=$EVROOT/M plat claude pybase pycand stamp
  mkdir -p $T/home $T/tmp $T/uv/python $T/uv/cache $T/work
  [[ -e $MOUT ]] && { stamp=$(date +%Y%m%d%H%M%S); mv $MOUT $MOUT-prev-$stamp; print -r -- "an earlier M evidence directory kept beside it (M-prev-$stamp)"; }
  mkdir -p $MOUT
  case $(uname -m) in arm64) plat=darwin-arm64 ;; x86_64) plat=darwin-x64 ;; *) stop "unknown Mac architecture $(uname -m)" ;; esac
  if [[ -n ${VERIFY652_M_CLAUDE:-} ]]; then
    claude=$VERIFY652_M_CLAUDE; print -r -- "rehearsal: Claude Code from VERIFY652_M_CLAUDE"
  else
    local base_url=https://downloads.claude.ai/claude-code-releases/$CLAUDE_VERSION want
    print -r -- "\$ curl $base_url/manifest.json; curl $base_url/$plat/claude   (into the temporary directory)"
    allow curl -fsSL --max-time 120 -o $T/manifest.json $base_url/manifest.json || stop "the Claude Code $CLAUDE_VERSION manifest could not be fetched"
    want=$(allow $PY -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["platforms"][sys.argv[2]]["checksum"])' $T/manifest.json $plat 2> /dev/null)
    [[ $want == [0-9a-f](#c64) ]] || stop "the manifest names no SHA-256 for $plat"
    allow curl -fsSL --max-time 600 -o $T/claude $base_url/$plat/claude || stop "the Claude Code $CLAUDE_VERSION $plat binary could not be fetched"
    [[ $(shasum -a 256 $T/claude | cut -d' ' -f1) == $want ]] || stop "the binary's SHA-256 differs from the manifest's"
    chmod +x $T/claude; claude=$T/claude
    print -r -- "PASS: Claude Code $CLAUDE_VERSION $plat fetched; SHA-256 equals the manifest's"
  fi
  # The bundle needs graftling dev's objects: each checkout is a clone of $GRAFT (read only there), the candidate
  # with the bundle fetched into it.
  allow $GIT clone -q --no-checkout $GRAFT $T/base && allow $GIT -C $T/base checkout -q --detach $BASE \
    || stop "graftling dev ${BASE[1,12]} could not be checked out from $GRAFT"
  allow $GIT clone -q --no-checkout $GRAFT $T/cand && allow $GIT -C $T/cand fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/candidate \
    && allow $GIT -C $T/cand checkout -q --detach $GSHA \
    || stop "the candidate ${GSHA[1,12]} could not be checked out from the bundle"
  # The isolated environment of every process M starts from here (no credential variable; HOME etc. in the temp dir).
  local -a menv=(/usr/bin/env -i HOME=$T/home USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=/usr/bin:/bin:/usr/sbin:/sbin
                 TMPDIR=$T/tmp LANG=en_US.UTF-8 TERM=${TERM:-dumb} UV_PYTHON_INSTALL_DIR=$T/uv/python UV_CACHE_DIR=$T/uv/cache)
  if [[ -n ${VERIFY652_M_PYTHON_BASE:-} && -n ${VERIFY652_M_PYTHON_CAND:-} ]]; then
    pybase=$VERIFY652_M_PYTHON_BASE pycand=$VERIFY652_M_PYTHON_CAND; print -r -- "rehearsal: graftling Pythons from VERIFY652_M_PYTHON_BASE/_CAND"
  else
    local uvb=$(whence -p uv) which
    [[ -n $uvb ]] || stop "uv is not on PATH (graftling's README installs with uv)"
    for which in base cand; do
      print -r -- "\$ uv tool install --managed-python <$which checkout>   (tool dir $which, in the temporary directory; bound 10 min)"
      $menv UV_TOOL_DIR=$T/uv/tools-$which UV_TOOL_BIN_DIR=$T/uv/bin-$which $uvb tool install --managed-python $T/$which \
        > $MOUT/uv-tool-install-$which.txt 2>&1 || { tail -5 $MOUT/uv-tool-install-$which.txt; stop "uv tool install ($which) failed"; }
    done
    pybase=$T/uv/tools-base/graftling/bin/python pycand=$T/uv/tools-cand/graftling/bin/python
  fi
  print -r -- "\$ python claude_real_entry.py   (base: market; candidate: market, untrusted, caller; each Claude Code run bounded 240 s)"
  $menv $PY -I $T/cand/.github/claude_real_entry.py --claude $claude --python $pybase --work $T/work/base \
    --out $MOUT/base --cases market 2>&1 | tee $MOUT/console-base.txt
  $menv $PY -I $T/cand/.github/claude_real_entry.py --claude $claude --python $pycand --work $T/work/cand \
    --out $MOUT/candidate --cases market,untrusted,caller 2>&1 | tee $MOUT/console-candidate.txt
  # Nothing of M may outlive it: every process naming the temporary directory is ended and counted.
  local -a left=(${(f)"$(ps -axo pid=,command= | grep -F -- $T | grep -v grep | awk '{print $1}')"})
  (( ${#left} )) && kill -9 $left 2> /dev/null
  print -r -- "processes naming the temporary directory left after M: ${#left} (ended)"
  w652_ mcompare $MOUT/base $MOUT/candidate | tee $MOUT/mcompare.txt
  # Evidence: the temporary and home paths replaced (the user name is part of the home path).
  allow $PY -I -c 'import pathlib, sys
pairs = [(sys.argv[2], "<tmp>"), (sys.argv[3], "<tmp>"), (sys.argv[4], "<home>")]
for path in pathlib.Path(sys.argv[1]).rglob("*"):
    if path.is_file():
        data = path.read_bytes()
        for value, holder in pairs:
            data = data.replace(value.encode(), holder.encode())
        path.write_bytes(data)' $MOUT ${T:A} $T $HOME
  local rbase=$(grep '^RESULT ' $MOUT/console-base.txt | tail -1) rcand=$(grep '^RESULT ' $MOUT/console-candidate.txt | tail -1)
  local cmp=$(grep '^MCOMPARE ' $MOUT/mcompare.txt | tail -1)
  rm -rf $T
  print -r -- "temporary directory deleted: $([[ -e $T ]] && print no || print yes); evidence: scripts/verify-652/evidence/M/"
  print -r -- "next: zsh $REL 00   (then P, if not yet published)"
  if [[ $rbase == "RESULT PASS"* && $rcand == "RESULT PASS"* && $cmp == "MCOMPARE PASS"* ]]; then
    print -r -- "VERDICT 652 M: PASS (base: ${rbase#RESULT PASS }; candidate: ${rcand#RESULT PASS }; ${cmp#MCOMPARE PASS })"
    exit 0
  fi
  print -r -- "VERDICT 652 M: FAIL (base: ${rbase:-no RESULT line}; candidate: ${rcand:-no RESULT line}; ${cmp:-no MCOMPARE line}; read scripts/verify-652/evidence/M/)"
  exit 1
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: gh login (account shown, no token), git credential helper (ls-remote). Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | uv: $(whence -p uv > /dev/null && $(whence -p uv) --version || print 'not on PATH (M needs it)') | TMPDIR for started processes: $PYTMP"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $REL 00"
  local gurl=$(gg remote get-url origin)
  [[ $gurl == $GURL ]] && print -r -- "PASS: $GRAFT origin is $gurl" || stop "$GRAFT origin is $gurl, not $GURL"
  [[ $GREMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $GREMOTE is used instead of graftling origin"
  check_bundle
  local ready=yes
  check_head || ready=no
  check_list || ready=no
  graft_local_ok || true
  graft_remote_ok
  if [[ $ready == yes && $REMOTE_STATE == equal ]]; then
    print -r -- "next: zsh $REL W    (the branch is already at the bundle head; observes its push run, no push)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $REL P    (publishes graftling $GSHA to $REPO $BRANCH, then waits for the Windows tests run)"
  else
    print -r -- "next: fix the FAIL lines above (a new bundle from the Engineer), then zsh $REL 00"
  fi
  print -r -- "next: zsh $REL M    (real Claude Code on this Mac; independent of P)"
  print -r -- "VERDICT 652 00: PASS (P ready: $ready; remote branch $REMOTE_STATE; candidate graftling $GSHA)"
  ;;
P)
  say "[P] Publish and wait. OUTWARD-FACING: pushes $BRANCH to graftling $GREMOTE (fast-forward only, never force); the push starts '$WORKFLOW'. Login: git credential helper, gh login. Dialog: none. Network: GitHub."
  check_bundle
  check_head || stop "the bundle head does not meet the checks above; nothing pushed. Run: zsh $REL 00"
  check_list || stop "the expected list does not parse; nothing pushed"
  graft_remote_ok
  [[ $REMOTE_STATE == equal ]] && stop "graftling $GREMOTE already has $BRANCH at $GSHA; observe with: zsh $REL W"
  if graft_local_ok; then
    print -r -- "\$ git -C $GRAFT fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH}"
    gg fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || stop "fetching the bundle failed; run: zsh $REL 00"
    [[ $(gg rev-parse -q --verify refs/heads/$BRANCH) == $GSHA ]] || stop "$GRAFT local $BRANCH is not $GSHA after the fetch"
    print -r -- "PASS: $GRAFT local $BRANCH = $GSHA"
  fi
  print -r -- "\$ git -C $GRAFT push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   ($GSHA)"
  gg push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "graftling push failed; nothing was forced. Run: zsh $REL 00"
  local after=$(gremote_sha); checked $after
  [[ $after == $GSHA ]] || stop "after the push graftling $GREMOTE shows ${after:-nothing}, not $GSHA; run: zsh $REL 00"
  print -r -- "PASS: graftling $GREMOTE $BRANCH = $GSHA"
  find_run $GSHA push P
  ;;
W)
  local target=${2:-}
  check_bundle
  if [[ $target != [0-9a-f](#c40) && $target == <-> ]]; then
    say "[W] Observe only (no push, no re-run) run $target. Login: gh login. Dialog: none. Network: GitHub."
    wait_run $target W
  fi
  [[ -z $target || $target == [0-9a-f](#c40) ]] || stop "usage: zsh $REL W [<40-hex sha> | <run-id>]"
  if [[ -z $target ]]; then
    target=$(gremote_sha); checked $target
    [[ -n $target ]] || stop "$BRANCH is not on graftling $GREMOTE; run: zsh $REL 00"
    say "[W] Observe only (no push, no re-run) the push run of the remote head $target. Login: gh login, git credential helper (ls-remote). Dialog: none. Network: GitHub."
    find_run $target push W
  fi
  say "[W] Observe only (no push, no re-run) the newest run of $target. Login: gh login. Dialog: none. Network: GitHub."
  find_run $target - W
  ;;
X)
  local rid=${2:-} before after rbranch wf rconcl rstate start
  [[ $rid == <-> ]] || stop "usage: zsh $REL X <run-id>"
  say "[X] Re-run failed jobs of run $rid. OUTWARD-FACING: gh run rerun $rid --failed starts GitHub Actions jobs. Login: gh login. Dialog: none. Network: GitHub."
  check_bundle
  api $WORK/run.json repos/$REPO/actions/runs/$rid || stop "cannot read run $rid; nothing re-run"
  rbranch=$(wc_ get $WORK/run.json head_branch); wf=$(wc_ get $WORK/run.json path)
  rstate=$(wc_ get $WORK/run.json status); rconcl=$(wc_ get $WORK/run.json conclusion); before=$(wc_ get $WORK/run.json run_attempt)
  print -r -- "run $rid: $wf | branch $rbranch | attempt $before | $rstate | ${rconcl:--}"
  [[ $rbranch == $BRANCH ]] || stop "run $rid is on $rbranch, not $BRANCH; nothing re-run"
  [[ $wf == $WORKFLOW ]] || stop "run $rid is $wf, not $WORKFLOW; nothing re-run"
  [[ $rstate == completed ]] || stop "run $rid is still $rstate; observe it with: zsh $REL W $rid"
  [[ $rconcl == success ]] && stop "run $rid already succeeded; nothing to re-run"
  print -r -- "\$ gh run rerun $rid --repo $REPO --failed"
  allow $GH run rerun $rid --repo $REPO --failed 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh run rerun failed; run: zsh $REL W $rid"
  print -r -- "waiting for attempt > $before to appear (bound ${APPEAR_S}s, poll ${POLL_S}s)"
  start=$SECONDS
  while true; do
    api $WORK/run.json repos/$REPO/actions/runs/$rid && after=$(wc_ get $WORK/run.json run_attempt)
    (( ${after:-0} > before )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "next: zsh $REL W $rid    (observe; no re-run)"
      print -r -- "VERDICT 652 X: FAIL (re-run requested, but attempt $before is still the latest after ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "attempt $after appeared after $((SECONDS - start))s"
  wait_run $rid X
  ;;
M)
  step_m
  ;;
*)
  print -r -- "usage: zsh $REL 00|P|W [sha|run-id]|X <run-id>|M"; exit 2 ;;
esac
