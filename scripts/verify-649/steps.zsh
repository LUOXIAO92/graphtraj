#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 649 (W11, phase B) Main-run steps: publish graftling's DSH support on Windows (graftling finds the DSH package
# behind npm's dsh.cmd shim; a gating job, dsh-windows-tests, in .github/workflows/windows.yml; from the bundle) to
# LUOXIAO92/graftling as agent/649-graftling-windows-dsh, fast-forward from phase A's 21818f59 and containing graftling
# dev 5715323 (647, 648). GitHub Actions then runs "Windows tests" on GitHub-hosted windows-latest x64 runners for the
# candidate commit: the unchanged windows-tests job (632) and dsh-windows-tests, which installs DSH 0.2.2-rc.5 with npm
# on Node 24.22.3 and runs every tests/test_*dsh*.py against it. The step waits for the run in this process, downloads
# both artifacts and judges them. Phase A (run 45984855702) showed DSH runs there; its probe evidence is kept in
# evidence/run-45984855702-a1/. Modelled on verify-639/steps.zsh (accepted); verify-632/wincheck.py judges both jobs'
# JUnit by reference, wincheck649.py the workflow change, the DSH job's steps and the tests that must pass.
#
# LOGIN: the user's own logins only. graftling push / ls-remote use https with the user's git credential helper
# (osxkeychain); gh uses its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN
# and every other credential-class variable are removed at start. No step raises a native dialog (GH_PROMPT_DISABLED=1,
# GIT_TERMINAL_PROMPT=0; a credential helper that needs a dialog fails the push instead, and the step STOPs).
# REAL ENTRY: the push run of windows.yml started by pushing agent/649-graftling-windows-dsh to LUOXIAO92/graftling
# (the candidate adds exactly that branch to the workflow's push trigger; the branch is already there at 21818f59, so
# the push is a fast-forward). The DSH job installs DSH from npm and starts it on the runner with no provider variable
# and an empty DSH_HOME; no model, key or provider is involved.
# Nothing of GraphTraj is pushed.
# EVIDENCE: the real steps write only below scripts/verify-649/evidence/live/ (git-ignored by scripts/verify-649/
# .gitignore) and never modify a tracked file; after Main's run the evidence is copied into tracked files in a new
# commit and submission.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git and gh versions; gh auth status (account only); <Harness>/graftling origin is
#       https://github.com/LUOXIAO92/graftling.git; the bundle verifies against <Harness>/graftling, its prerequisites
#       are graftling dev 5715323 (W0-W8, 645, 648) and phase A's 21818f59 or ancestors of either, and the head contains
#       both and is shown; read through a temporary repository that borrows <Harness>/graftling's objects (nothing is
#       written there): noreply identity; the paths changed since 5715323 are within ALLOWED (below); the workflow is
#       5715323's with its push branches line gaining exactly agent/649-graftling-windows-dsh and the dsh-windows-tests
#       job appended (its runner, pins, Node, steps, gating install and DSH test files, upload checked), windows-tests
#       unchanged, and both the base and the head workflow pass 632's wfcheck; .github/run_test_files.py and
#       tests/posix_only.py are unchanged; the tests of dsh-new-tests.txt are defined at the head; windows-expected.txt
#       parses and its DSH-related lines are GraphTraj b5653bac's (other lines belong to other Tasks and are only
#       noted); dsh-expected.txt parses; the local branch in <Harness>/graftling and the remote branch are each absent,
#       the bundle head, or an ancestor of it (else STOP). Login: gh login, git credential helper (ls-remote).
#       Dialog: none. ~10 s.
#   P   Publish and wait. OUTWARD-FACING: (1) fetches the bundle into <Harness>/graftling as local branch
#       agent/649-graftling-windows-dsh (only if absent or an ancestor; git fetch without '+' is fast-forward only;
#       nothing when equal); (2) pushes it to graftling origin, fast-forward only, never force, and verifies with
#       ls-remote; (3) waits in this process for the windows.yml push run of that SHA (appearance bound 300 s,
#       completion bound 6000 s, poll 30 s); (4) judges it (below), saving both artifacts, the job log and the
#       judgement under scripts/verify-649/evidence/live/run-<id>-a<attempt>/; (5) the DSH install facts and the tests
#       that must pass, the next commands and the VERDICT last. Login: git credential helper, gh login. Dialog: none. Network: GitHub. Up to ~105 min.
#   W   Observe only (no push, no re-run): `W <run-id>` that run; `W` the push run of the remote branch head,
#       `W <sha>` the newest windows.yml run of that commit (any event). Same waiting and judging as P.
#       Login: gh login (git credential helper for `W` without argument: ls-remote). Dialog: none. Network: GitHub.
#   X   `X <run-id>`: re-run the failed jobs of one completed, failed windows.yml run of this branch
#       (gh run rerun --failed), for transient failures only (a runner or download fault, not a test result).
#       OUTWARD-FACING (starts GitHub Actions jobs). Waits for the new attempt to appear (300 s) and complete
#       (6000 s), then judges it like P. Login: gh login. Dialog: none. Network: GitHub.
# VERDICT (P, W, X): PASS only when ALL of
#   mechanics: as 632 for windows-tests (the run is for the candidate SHA and completed; every setup step succeeded,
#     the suite step ran to its end, the upload succeeded; the artifact was downloaded; the per-file driver finished
#     and files.json has a record for every tests/test_*.py of the run commit, each ended or recorded hung);
#   results: as 632, against scripts/verify-632/windows-expected.txt (a listed entry that passes is an unexpected
#     pass, a listed entry that is skipped or absent also fails, a new failure is unexpected);
#   DSH job: every step of dsh-windows-tests succeeded (the npm install and the DSH test files gate);
#   DSH mechanics: its artifact was downloaded; the per-file driver finished and files.json has a record for every
#     tests/test_*dsh*.py of the run commit, each ended (as 632's per-file check);
#   DSH results: as 632, against scripts/verify-649/dsh-expected.txt (no failure, no hang; every skip POSIX-only or
#     listed there, each listed one also on macOS);
#   DSH tests: every node id of dsh-new-tests.txt PASSED in the DSH job's JUnit (not failed, skipped or absent): the
#     npm shim resolution, the real DSH service through the shim (start, session/list, close; owner killed without
#     close), the DSH host and child tests and the installed-DSH tests phase A saw fail. Each is printed before the
#     VERDICT, after the DSH install facts (Node, npm, DSH version, install seconds, npm cache hit, code page).
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*, OPENAI_*,
# DEEPSEEK_*, CODEX_*, CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES.
# Every started process runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set
# SSH_AUTH_SOCK, GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential
# is passed.
# TMPDIR: kept outside the Harness (a TMPDIR inside it is replaced by /tmp).
# Rehearsal knobs (Engineer only): VERIFY649_GRAFTLING (a scratch graftling clone instead of <Harness>/graftling),
# VERIFY649_GREMOTE (push/ls-remote target instead of that clone's origin), VERIFY649_GH (a gh stand-in),
# VERIFY649_EXPECTED (another expected list), VERIFY649_EVIDENCE (evidence root), VERIFY649_BUNDLE (another bundle),
# VERIFY649_APPEAR_S / _DONE_S / _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
STEP=${1:-}
BRANCH=agent/649-graftling-windows-dsh
# graftling dev 5715323: W0 (632) to W7 (639), 645, W8/W9 (647) and W10 (648) integrated.
BASE=57153234f90829e6629765e5b985f20c1491353c
# Phase A's head, already on LUOXIAO92/graftling and in <Harness>/graftling: the bundle head must fast-forward from it.
PREV=21818f59d73a4954b981302b4e8ed5dd20aaf465
# GraphTraj dev with 647's and 648's expected list; this Task changes none of its DSH-related lines.
LIST_BASE=b5653bac
REPO=LUOXIAO92/graftling
GURL=https://github.com/LUOXIAO92/graftling.git
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY649_GRAFTLING:-$HARNESS/graftling}
GREMOTE=${VERIFY649_GREMOTE:-origin}
GH=${VERIFY649_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY649_APPEAR_S:-300}
DONE_S=${VERIFY649_DONE_S:-6000}
POLL_S=${VERIFY649_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
[[ ${PYTMP:A} == ${HARNESS}(|/*) ]] && PYTMP=/tmp
WORKFLOW=.github/workflows/windows.yml
JOB=windows-tests
BUNDLE=${VERIFY649_BUNDLE:-$HERE/graftling-649.bundle}
WINCHECK=$WT/scripts/verify-632/wincheck.py
EXPECTED=${VERIFY649_EXPECTED:-$WT/scripts/verify-632/windows-expected.txt}
EVID=${VERIFY649_EVIDENCE:-$HERE/evidence/live}
DSH_EXPECTED=$HERE/dsh-expected.txt
NEWTESTS=$HERE/dsh-new-tests.txt
# The only paths the candidate may change since BASE (phase A's probe script is added and removed again).
ALLOWED=(.github/workflows/windows.yml src/graftling/dsh/settings.py src/graftling/dsh/driver.py src/graftling/dsh/plugin.mjs
         src/graftling/models.py
         tests/conftest.py tests/test_dsh_live.py tests/test_dsh_mcp.py tests/test_dsh_official.py
         tests/test_dsh_providers_608.py tests/test_dsh_standalone_child.py tests/test_dsh_windows_649.py
         tests/test_pi_dsh_child_tools_551.py tests/test_pi_dsh_owner_tools_no_ask_551.py)
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
  print -r -- "scrubbed at start (names only): ${removed:-none}"
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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 649 $STEP: STOP"; exit 1; }
gg() { allow $GIT -C $GRAFT "$@"; }
wc_() { allow $PY -I $WINCHECK "$@"; }
w649_() { allow $PY -I $HERE/wincheck649.py "$@"; }
WORK=$(mktemp -d $PYTMP/verify649.XXXXXX)
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
check_bundle() {  # the bundle verifies against $GRAFT; BASE is a prerequisite, any other is PREV or an ancestor of
  # BASE or PREV; the head contains both (a fast-forward from PREV, which is on the remote); sets GSHA
  [[ -f $BUNDLE ]] || stop "no bundle at $BUNDLE"
  gg bundle verify $BUNDLE > /dev/null 2>&1 || { gg bundle verify $BUNDLE 2>&1 | sed 's/^/  /'; stop "the bundle does not verify against $GRAFT"; }
  GSHA=$(bundle_head)
  [[ $GSHA == [0-9a-f](#c40) ]] || stop "the bundle has no refs/heads/$BRANCH"
  local -a prereqs=(${(f)"$(bundle_prereqs)"})
  local prereq
  (( ${prereqs[(Ie)$BASE]} )) || stop "the bundle's prerequisites are ${prereqs:-none}, without graftling dev $BASE"
  for prereq in $prereqs; do
    [[ $prereq == $BASE || $prereq == $PREV ]] && continue
    gg merge-base --is-ancestor $prereq $BASE 2> /dev/null || gg merge-base --is-ancestor $prereq $PREV 2> /dev/null \
      || stop "the bundle's prerequisite $prereq is not an ancestor of graftling dev $BASE or of phase A's $PREV"
  done
  ancestor_of_head $BASE || stop "graftling dev $BASE is not an ancestor of the bundle head $GSHA"
  ancestor_of_head $PREV || stop "phase A's $PREV is not an ancestor of the bundle head $GSHA: the push would not fast-forward"
  print -r -- "PASS: bundle verifies against $GRAFT; head $GSHA contains graftling dev $BASE and phase A's $PREV (prerequisites: ${prereqs})"
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
  w649_ wfdiff $WORK/windows-base.yml $WORK/windows-head.yml || (( bad++ ))
  for which in base head; do
    print -r -- "--- $WORKFLOW at the $which: the windows-tests job and the whole file by 632's wfcheck"
    if w649_ as632 $WORK/windows-$which.yml $WORK/windows-$which-632.yml; then
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
  (( missing == 0 )) && print -r -- "PASS: the $(grep -vc '^#' $NEWTESTS) tests of dsh-new-tests.txt are defined at $GSHA"
  return $(( bad + missing ))
}
check_list() {  # the expected list parses; its DSH-related lines are LIST_BASE's
  local bad=0
  wc_ expected $EXPECTED || (( bad++ ))
  allow $GIT -C $WT show ${LIST_BASE}:scripts/verify-632/windows-expected.txt > $WORK/expected-base.txt 2> /dev/null \
    || { print -r -- "FAIL: GraphTraj $LIST_BASE is not readable here"; return $(( bad + 1 )); }
  w649_ dshlines $WORK/expected-base.txt $EXPECTED || (( bad++ ))
  wc_ expected $DSH_EXPECTED || (( bad++ ))
  [[ $EXPECTED == $WT/scripts/verify-632/windows-expected.txt ]] || print -r -- "NOTE: judged against $EXPECTED (rehearsal)"
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
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res djob dfiles dres newt
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
    w649_ dshjob $WORK/jobs.json > $WORK/dshjob.txt 2>&1
  else
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
    print -r -- "DSHJOB FAIL jobs of run $rid unreadable" > $WORK/dshjob.txt
  fi
  cat $WORK/jobs.txt $WORK/dshjob.txt > $dir/jobs.txt
  grep -v '^JUDGE ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  grep -v '^DSHJOB ' $WORK/dshjob.txt
  djob=$(grep '^DSHJOB ' $WORK/dshjob.txt | tail -1); [[ -n $djob ]] || djob="DSHJOB FAIL DSH job judgement failed: $(tail -2 $WORK/dshjob.txt)"
  # The windows-tests job log (ANSI colour codes need --allow-escape-sequences, 619); kept with the evidence, tail printed.
  jid=$(allow $PY -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == sys.argv[2]), ""))' $WORK/jobs.json $JOB 2> /dev/null)
  if [[ -n $jid ]] && allow $GH api --allow-escape-sequences "repos/$REPO/actions/jobs/$jid/logs" > $dir/job.log 2> $WORK/err; then
    print -r -- "--- job log saved: $dir/job.log; files ended, hangs, driver exit:"
    print -r -- "  per-file pytest summaries: $(grep -cE '=+ .*(passed|failed|error|skipped|no tests ran).* in [0-9.]+s' $dir/job.log)"
    grep -E '(### HUNG|run_test_files exit code:|INTERNALERROR|has timed out)' $dir/job.log | tail -n 12 | cut -c1-240 | sed 's/^/  /'
  else
    print -r -- "job log unavailable: $(<$WORK/err 2> /dev/null)"
  fi
  # The JUnit artifact of this attempt.
  local name=graftling-windows-junit-$sha-${attempt:-1} dname=graftling-dsh-windows-$sha-${attempt:-1} files= tlist= dlist=
  if [[ -f $dir/junit/environment.json ]]; then
    print -r -- "already present, not downloaded again: $dir/junit"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dir/junit"
    allow $GH run download $rid --repo $REPO -n $name -D $dir/junit 2>&1 | sed 's/^/  /'
  fi
  # The test files every record must cover: the run commit's tests/test_*.py.
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
  else
    files="FILES FAIL no artifact downloaded ($name)"; res="JUDGE FAIL no JUnit files"
  fi
  # Mechanics: the job's steps and the per-file records.
  if [[ $files == "FILES FAIL"* ]]; then
    [[ $mech == "JUDGE PASS"* ]] && mech="JUDGE FAIL ${files#FILES FAIL }" || mech="$mech; ${files#FILES FAIL }"
  else
    mech="$mech; ${files#FILES PASS }"
  fi
  # The DSH job's artifact of this attempt: the run commit's tests/test_*dsh*.py against dsh-expected.txt, then the
  # tests that must pass, printed last before the next commands and the VERDICT.
  if [[ -f $dir/dsh/files.json ]]; then
    print -r -- "already present, not downloaded again: $dir/dsh"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $dname -D $dir/dsh"
    allow $GH run download $rid --repo $REPO -n $dname -D $dir/dsh 2>&1 | sed 's/^/  /'
  fi
  if [[ -n $tlist ]]; then
    grep -E '^tests/test_[^/]*dsh[^/]*\.py$' $tlist > $WORK/dshfiles.txt; dlist=$WORK/dshfiles.txt
  fi
  if [[ -d $dir/dsh ]]; then
    w649_ install $dir/dsh
    print -r -- "--- DSH job: per-file records and results against $DSH_EXPECTED"
    wc_ junit $dir/dsh $DSH_EXPECTED $dir/dsh-observed-expected.txt $dlist > $dir/dsh-judgement.txt 2>&1
    grep -v '^JUDGE \|^FILES ' $dir/dsh-judgement.txt
    dfiles=$(grep '^FILES ' $dir/dsh-judgement.txt | tail -1); [[ -n $dfiles ]] || dfiles="FILES FAIL per-file judgement failed: $(tail -2 $dir/dsh-judgement.txt)"
    dres=$(grep '^JUDGE ' $dir/dsh-judgement.txt | tail -1); [[ -n $dres ]] || dres="JUDGE FAIL JUnit judgement failed: $(tail -2 $dir/dsh-judgement.txt)"
    w649_ newtests $dir/dsh $NEWTESTS > $dir/dsh-new-tests.txt 2>&1
    newt=$(grep '^NEWTESTS ' $dir/dsh-new-tests.txt | tail -1); [[ -n $newt ]] || newt="NEWTESTS FAIL check failed: $(tail -2 $dir/dsh-new-tests.txt)"
  else
    dfiles="FILES FAIL no DSH artifact downloaded ($dname)"; dres="JUDGE FAIL no DSH JUnit files"; newt="NEWTESTS FAIL no DSH JUnit files"
    print -r -- "NEWTESTS FAIL no DSH JUnit files" > $dir/dsh-new-tests.txt
  fi
  # DSH mechanics: the job's steps and the per-file records.
  if [[ $dfiles == "FILES FAIL"* ]]; then
    [[ $djob == "DSHJOB PASS"* ]] && djob="DSHJOB FAIL ${dfiles#FILES FAIL }" || djob="$djob; ${dfiles#FILES FAIL }"
  else
    djob="$djob; ${dfiles#FILES PASS }"
  fi
  grep -v '^NEWTESTS ' $dir/dsh-new-tests.txt
  print -r -- "evidence: $dir (git-ignored unless a rehearsal root was given; copy it into tracked files in a new commit)"
  print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
  [[ $concl != success ]] && print -r -- "next: zsh $THIS X $rid    (re-run its failed jobs; only if the failure is transient, not a test result)"
  [[ $res == "JUDGE FAIL"* ]] && print -r -- "next: correction round: compare $dir/observed-expected.txt with $EXPECTED; after a new bundle: zsh $THIS 00 then zsh $THIS P"
  [[ $dres == "JUDGE FAIL"* || $newt == "NEWTESTS FAIL"* ]] && print -r -- "next: correction round: compare $dir/dsh-observed-expected.txt with $DSH_EXPECTED and read $dir/dsh-new-tests.txt"
  if [[ $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* && $djob == "DSHJOB PASS"* && $dres == "JUDGE PASS"* && $newt == "NEWTESTS PASS"* ]]; then
    print -r -- "VERDICT 649 $label: PASS (run $rid attempt $attempt on $sha; windows-tests mechanics: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; DSH job: ${djob#DSHJOB PASS }; DSH results: ${dres#JUDGE PASS }; DSH tests: ${newt#NEWTESTS PASS }, listed above; $url)"
    exit 0
  fi
  print -r -- "VERDICT 649 $label: FAIL (run $rid attempt $attempt on $sha; windows-tests mechanics: ${mech#JUDGE }; results: ${res#JUDGE }; DSH job: ${djob#DSHJOB }; DSH results: ${dres#JUDGE }; DSH tests: ${newt#NEWTESTS }; $url)"
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
      print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
      print -r -- "VERDICT 649 $label: FAIL (run $rid not completed within ${DONE_S}s)"
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
      (( ${#${(M)rows:#OTHER*}} )) && { print -r -- "other workflows for this SHA:"; print -lr -- ${(M)rows:#OTHER*} | sed 's/^/  /'; }
      print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
      print -r -- "VERDICT 649 $label: FAIL (the $WORKFLOW run never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  f=("${(@ps:\t:)row}"); rid=$f[3]
  print -r -- "run $rid present after $((SECONDS - start))s: ${f[7]} | ${f[6]}"
  (( ${#${(M)rows:#OTHER*}} )) && { print -r -- "other workflows for this SHA:"; print -lr -- ${(M)rows:#OTHER*} | sed 's/^/  /'; }
  wait_run $rid $label
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: gh login (account shown, no token), git credential helper (ls-remote). Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH | TMPDIR for started processes: $PYTMP"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
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
    print -r -- "next: zsh $THIS W    (the branch is already at the bundle head; observes its push run, no push)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $THIS P    (publishes graftling $GSHA to $REPO $BRANCH, then waits for the Windows tests run)"
  else
    print -r -- "next: fix the FAIL lines above (new bundle or list from the Engineer), then zsh $THIS 00"
  fi
  print -r -- "VERDICT 649 00: PASS (P ready: $ready; remote branch $REMOTE_STATE; candidate graftling $GSHA)"
  ;;
P)
  say "[P] Publish and wait. OUTWARD-FACING: pushes $BRANCH to graftling $GREMOTE (fast-forward only, never force); the push starts '$WORKFLOW'. Login: git credential helper, gh login. Dialog: none. Network: GitHub."
  check_bundle
  check_head || stop "the bundle head does not meet the checks above; nothing pushed. Run: zsh $THIS 00"
  check_list || stop "the expected list does not meet the checks above; nothing pushed"
  graft_remote_ok
  [[ $REMOTE_STATE == equal ]] && stop "graftling $GREMOTE already has $BRANCH at $GSHA; observe with: zsh $THIS W"
  if graft_local_ok; then
    print -r -- "\$ git -C $GRAFT fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH}"
    gg fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || stop "fetching the bundle failed; run: zsh $THIS 00"
    [[ $(gg rev-parse -q --verify refs/heads/$BRANCH) == $GSHA ]] || stop "$GRAFT local $BRANCH is not $GSHA after the fetch"
    print -r -- "PASS: $GRAFT local $BRANCH = $GSHA"
  fi
  print -r -- "\$ git -C $GRAFT push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   ($GSHA)"
  gg push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "graftling push failed; nothing was forced. Run: zsh $THIS 00"
  local after=$(gremote_sha); checked $after
  [[ $after == $GSHA ]] || stop "after the push graftling $GREMOTE shows ${after:-nothing}, not $GSHA; run: zsh $THIS 00"
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
  [[ -z $target || $target == [0-9a-f](#c40) ]] || stop "usage: zsh $THIS W [<40-hex sha> | <run-id>]"
  if [[ -z $target ]]; then
    target=$(gremote_sha); checked $target
    [[ -n $target ]] || stop "$BRANCH is not on graftling $GREMOTE; run: zsh $THIS 00"
    say "[W] Observe only (no push, no re-run) the push run of the remote head $target. Login: gh login, git credential helper (ls-remote). Dialog: none. Network: GitHub."
    find_run $target push W
  fi
  say "[W] Observe only (no push, no re-run) the newest run of $target. Login: gh login. Dialog: none. Network: GitHub."
  find_run $target - W
  ;;
X)
  local rid=${2:-} before after rbranch wf rconcl rstate start
  [[ $rid == <-> ]] || stop "usage: zsh $THIS X <run-id>"
  say "[X] Re-run failed jobs of run $rid. OUTWARD-FACING: gh run rerun $rid --failed starts GitHub Actions jobs. Login: gh login. Dialog: none. Network: GitHub."
  check_bundle
  api $WORK/run.json repos/$REPO/actions/runs/$rid || stop "cannot read run $rid; nothing re-run"
  rbranch=$(wc_ get $WORK/run.json head_branch); wf=$(wc_ get $WORK/run.json path)
  rstate=$(wc_ get $WORK/run.json status); rconcl=$(wc_ get $WORK/run.json conclusion); before=$(wc_ get $WORK/run.json run_attempt)
  print -r -- "run $rid: $wf | branch $rbranch | attempt $before | $rstate | ${rconcl:--}"
  [[ $rbranch == $BRANCH ]] || stop "run $rid is on $rbranch, not $BRANCH; nothing re-run"
  [[ $wf == $WORKFLOW ]] || stop "run $rid is $wf, not $WORKFLOW; nothing re-run"
  [[ $rstate == completed ]] || stop "run $rid is still $rstate; observe it with: zsh $THIS W $rid"
  [[ $rconcl == success ]] && stop "run $rid already succeeded; nothing to re-run"
  print -r -- "\$ gh run rerun $rid --repo $REPO --failed"
  allow $GH run rerun $rid --repo $REPO --failed 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh run rerun failed; run: zsh $THIS W $rid"
  print -r -- "waiting for attempt > $before to appear (bound ${APPEAR_S}s, poll ${POLL_S}s)"
  start=$SECONDS
  while true; do
    api $WORK/run.json repos/$REPO/actions/runs/$rid && after=$(wc_ get $WORK/run.json run_attempt)
    (( ${after:-0} > before )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "next: zsh $THIS W $rid    (observe; no re-run)"
      print -r -- "VERDICT 649 X: FAIL (re-run requested, but attempt $before is still the latest after ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "attempt $after appeared after $((SECONDS - start))s"
  wait_run $rid X
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|W [sha|run-id]|X <run-id>"; exit 2 ;;
esac
