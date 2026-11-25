#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 638 (W6) Main-run steps: publish graftling's paths, links and encoding change (from the bundle) to
# LUOXIAO92/graftling, so GitHub Actions runs "Windows tests" (.github/workflows/windows.yml, W0's workflow) on a
# GitHub-hosted windows-latest x64 runner for the candidate commit, with the suite's temporary directory under a
# non-ASCII name; wait for the run in this process, download its JUnit artifact, and judge it.
# Built from scripts/verify-632/steps.zsh (same flow, waits, credential scrub and evidence); the run's results are
# judged by scripts/verify-632/wincheck.py (called by path) against scripts/verify-632/windows-expected.txt as 638
# edited it (its 37 'W6 (638)' entries removed); check638.py adds the workflow diff and non-ASCII checks.
#
# LOGIN: the user's own logins only. graftling push / ls-remote use https with the user's git credential helper
# (osxkeychain), as 632 did; gh uses its stored login (gh auth status shows the account; no token is printed).
# GH_TOKEN/GITHUB_TOKEN and every other credential-class variable are removed at start, so neither gh nor git can
# use a token from the environment. No step raises a native dialog (GH_PROMPT_DISABLED=1, GIT_TERMINAL_PROMPT=0;
# a credential helper that needs a dialog fails the push instead, and the step STOPs). Expect none.
# REAL ENTRY: the push run of windows.yml started by pushing agent/638-graftling-windows-paths-encoding to
# LUOXIAO92/graftling (638 appends that branch to the push trigger; graftling main has no windows.yml, so
# workflow_dispatch is not expected to be usable, see D). Nothing of GraphTraj is pushed.
# EVIDENCE: under scripts/verify-638/evidence/ (git-ignored by scripts/verify-638/.gitignore), so a real P/W/X/D
# never changes a tracked file of this Worktree.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git and gh versions; gh auth status (account only); <Harness>/graftling origin is
#       https://github.com/LUOXIAO92/graftling.git; the bundle verifies against <Harness>/graftling, every
#       prerequisite is graftling dev 478dfd7f or one of its ancestors (the branch's first commits sit on defad1db,
#       an ancestor of 478dfd7f, so the bundle also names defad1db) and its head is shown; read through a temporary
#       repository that borrows <Harness>/graftling's objects (nothing is written there): the head descends from
#       478dfd7f; the noreply identity on every bundle commit since 478dfd7f;
#       pyproject.toml, pytest.ini, .github/run_test_files.py, tests/posix_only.py and tests/conftest.py unchanged
#       since 478dfd7f; windows.yml differs from 478dfd7f's (632's accepted workflow with W1/W2's branches added)
#       only by this branch appended to the push branches and the non-ASCII temporary directory lines in the
#       suite step, with every step name
#       unchanged and PYTHONUTF8=1 kept; the expected list parses; the local branch in <Harness>/graftling and the
#       remote branch are each absent, the bundle head, or an ancestor of it (else STOP).
#       Login: gh login, git credential helper (ls-remote). Dialog: none. Network: GitHub. ~10 s.
#   P   Publish and wait. OUTWARD-FACING: (1) fetches the bundle into <Harness>/graftling as local branch
#       agent/638-graftling-windows-paths-encoding (only if absent or an ancestor; git fetch without '+' is
#       fast-forward only; nothing when equal); (2) pushes it to graftling origin, fast-forward only, never force, and
#       verifies with ls-remote; (3) waits in this process for the windows.yml push run of that SHA (appearance bound
#       300 s, completion bound 6000 s, poll 30 s); (4) judges it (below), saving the JUnit artifact, the job log and
#       the judgement under scripts/verify-638/evidence/run-<id>-a<attempt>/; (5) the next commands and the VERDICT
#       last. Login: git credential helper, gh login. Dialog: none. Network: GitHub. Up to ~105 min.
#   W   Observe only (no push, no re-run): `W` the push run of the remote branch head, `W <sha>` the newest
#       windows.yml run of that commit (any event), `W <run-id>` that run. Same waiting and judging as P.
#       Login: gh login (git credential helper for `W` without argument: ls-remote). Dialog: none. Network: GitHub.
#   X   `X <run-id>`: re-run the failed jobs of one completed, failed windows.yml run of this branch
#       (gh run rerun --failed), for transient failures only (a runner or download fault, not a test result).
#       OUTWARD-FACING (starts GitHub Actions jobs). Waits for the new attempt to appear (300 s) and complete
#       (6000 s), then judges it like P. Login: gh login. Dialog: none. Network: GitHub.
#   D   workflow_dispatch of windows.yml on this branch (gh workflow run --ref). GitHub dispatches only a workflow
#       that exists on the default branch, and graftling main has no windows.yml (inference, not tried), so D is
#       expected to STOP at `gh workflow run`; use P or X. OUTWARD-FACING if it works (starts GitHub Actions jobs).
#       Login: gh login, git credential helper (ls-remote). Dialog: none.
# VERDICT (P, W, X, D): PASS only when ALL of
#   mechanics: the run is for the candidate SHA and completed; in job windows-tests every setup step succeeded, the
#     suite step ran to its end (success or failure), the upload succeeded and no other step failed; the artifact was
#     downloaded; the per-file driver finished (exit code 0 or 1 in run-exit-code.txt) and files.json has a record
#     for every tests/test_*.py of the run commit, each ended with pytest exit 0 or 1 and its JUnit file, or stopped
#     after the file limit and recorded as hung;
#   non-ASCII paths: the artifact's temp-directory.txt (Python's tempfile.gettempdir() for the whole suite, written
#     by the suite step after it set TEMP and TMP) has a non-ASCII character and ends with graftling-<U+6D4B U+8BD5>-
#     <U+00FC>, so every tmp_path, data root, venv and worktree the tests made lay under a non-ASCII directory;
#   results: over the merged per-file JUnit files, the tests failing on Windows are exactly the `fail` entries of
#     windows-expected.txt, the hung files' last started tests are exactly its `hang` entries, and every skip either
#     starts with "POSIX-only: " (tests/posix_only.py) or is an allowed environment skip listed there.
#   Printed: as 632 prints them (unexpected failures and hangs with origin and a suggested Task, unexpected passes,
#   listed failures that were skipped or absent, every skip without the prefix), plus the temporary directory and
#   how many per-file logs print a path under it. The observed list is written for a correction round.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY638_GRAFTLING (a scratch graftling clone instead of <Harness>/graftling),
# VERIFY638_GREMOTE (push/ls-remote target instead of that clone's origin), VERIFY638_GH (a gh stand-in),
# VERIFY638_EXPECTED (another expected list), VERIFY638_EVIDENCE (evidence root), VERIFY638_APPEAR_S / _DONE_S /
# _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
STEP=${1:-}
BRANCH=agent/638-graftling-windows-paths-encoding
# graftling dev 478dfd7f (W0, W1 and W2 integrated; defad1db is an ancestor). The bundle's prerequisites are
# this commit and, through the branch's first commits, defad1db; only BASE and its ancestors are accepted.
BASE=478dfd7f91a1ffbf1cdd74aed9eb8f7c3c039ced
REPO=LUOXIAO92/graftling
GURL=https://github.com/LUOXIAO92/graftling.git
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY638_GRAFTLING:-$HARNESS/graftling}
GREMOTE=${VERIFY638_GREMOTE:-origin}
GH=${VERIFY638_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY638_APPEAR_S:-300}
DONE_S=${VERIFY638_DONE_S:-6000}
POLL_S=${VERIFY638_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
WORKFLOW=.github/workflows/windows.yml
JOB=windows-tests
BUNDLE=$HERE/graftling-638.bundle
# W0's list as 638 edited it (its W6 (638) entries removed), and W0's judge.
EXPECTED=${VERIFY638_EXPECTED:-$HERE/../verify-632/windows-expected.txt}
WINCHECK=$HERE/../verify-632/wincheck.py
EVID=${VERIFY638_EVIDENCE:-$HERE/evidence}
# The job's steps by their exact `name:` in $WORKFLOW at the bundle head.
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
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAFTLING_CONNECTION ]]; then
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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 638 $STEP: STOP"; exit 1; }
gg() { allow $GIT -C $GRAFT "$@"; }
wc_() { allow $PY -I $WINCHECK "$@"; }
c638() { allow $PY -I $HERE/check638.py "$@"; }
WORK=$(mktemp -d $PYTMP/verify638.XXXXXX)
trap 'rm -rf $WORK' EXIT

# api <file> <endpoint>: save a gh api response; on failure print the error and return 1.
api() {
  allow $GH api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}

GSHA=
bundle_head() { allow $GIT bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1; }
# Every prerequisite the bundle names ("requires this ref:" or "requires these N refs:"), one per line.
bundle_prereq() { gg bundle verify $BUNDLE 2>&1 | awk '/requires (this ref|these [0-9]+ refs)/ {f=1; next} /hash algorithm/ {f=0} f && NF {print $1}'; }
check_bundle() {  # the bundle verifies against $GRAFT; every prerequisite is BASE or an ancestor of it; sets GSHA
  local prereq; local -a prereqs
  [[ -f $BUNDLE ]] || stop "no bundle at $BUNDLE"
  gg bundle verify $BUNDLE > /dev/null 2>&1 || { gg bundle verify $BUNDLE 2>&1 | sed 's/^/  /'; stop "the bundle does not verify against $GRAFT"; }
  GSHA=$(bundle_head)
  [[ $GSHA == [0-9a-f](#c40) ]] || stop "the bundle has no refs/heads/$BRANCH"
  prereqs=(${(f)"$(bundle_prereq)"})
  (( ${#prereqs} )) || stop "the bundle names no prerequisite; expected graftling dev $BASE"
  (( ${prereqs[(Ie)$BASE]} )) || stop "the bundle's prerequisites ${prereqs} do not include graftling dev $BASE"
  for prereq in $prereqs; do
    [[ $prereq == [0-9a-f](#c40) ]] && gg merge-base --is-ancestor $prereq $BASE 2> /dev/null \
      || stop "the bundle's prerequisite $prereq is not graftling dev $BASE or an ancestor of it"
  done
  print -r -- "PASS: bundle verifies against $GRAFT; head $GSHA; prerequisites ${prereqs} are $BASE or its ancestors"
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
  local peek=$PEEK bad=0 changed
  peek_repo
  allow $GIT -C $peek merge-base --is-ancestor $BASE peek 2> /dev/null \
    && print -r -- "PASS: the bundle head descends from graftling dev $BASE (dev takes it fast-forward)" \
    || { print -r -- "FAIL: the bundle head does not descend from graftling dev $BASE"; (( bad++ )); }
  print -r -- "--- bundle commits on $BASE:"
  allow $GIT -C $peek log --format='  %h %an <%ae> | %cn <%ce> | %s' $BASE..peek
  local idents=$(allow $GIT -C $peek log --format='%ae%n%ce' $BASE..peek | sort -u)
  [[ $idents == 89069722+LUOXIAO92@users.noreply.github.com ]] && print -r -- "PASS: author and committer are the noreply identity" \
    || { print -r -- "FAIL: identities in the bundle: ${(f)idents}"; (( bad++ )); }
  print -r -- "--- files changed since $BASE:"; allow $GIT -C $peek diff --stat $BASE peek | sed 's/^/  /'
  changed=$(allow $GIT -C $peek diff --name-only $BASE peek -- pyproject.toml pytest.ini .github/run_test_files.py tests/posix_only.py tests/conftest.py)
  [[ -z $changed ]] && print -r -- "PASS: pyproject.toml, pytest.ini, the per-file driver, tests/posix_only.py and tests/conftest.py unchanged since $BASE" \
    || { print -r -- "FAIL: changed since $BASE: ${(f)changed}"; (( bad++ )); }
  # 632's wfcheck accepted windows.yml at $BASE; 638 may change only its push branches (append $BRANCH)
  # and add the non-ASCII temporary directory to the suite step (check638.py wfdiff).
  allow $GIT -C $peek show $BASE:$WORKFLOW > $WORK/windows-base.yml 2> /dev/null || { print -r -- "FAIL: no $WORKFLOW at $BASE"; return $(( bad + 1 )); }
  allow $GIT -C $peek show peek:$WORKFLOW > $WORK/windows.yml 2> /dev/null || { print -r -- "FAIL: no $WORKFLOW at $GSHA"; return $(( bad + 1 )); }
  print -r -- "--- $WORKFLOW at $GSHA against $BASE"
  c638 wfdiff $WORK/windows-base.yml $WORK/windows.yml $BRANCH $SETUP $SUITE $UPLOAD || (( bad++ ))
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
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res
  rid=$(wc_ get $runfile id); sha=$(wc_ get $runfile head_sha); attempt=$(wc_ get $runfile run_attempt)
  concl=$(wc_ get $runfile conclusion); url=$(wc_ get $runfile html_url); event=$(wc_ get $runfile event)
  dir=$EVID/run-$rid-a${attempt:-1}
  mkdir -p $dir
  print -r -- "--- run $rid | attempt $attempt | $event | conclusion $concl (information only) | head $sha | $url"
  [[ -z $GSHA || $sha == $GSHA ]] || print -r -- "NOTE: run head $sha is not the bundle head $GSHA"
  allow $PY -I -c 'import json, sys; print(json.dumps({"job": sys.argv[1], "setup": sys.argv[2:-2], "suite": sys.argv[-2], "upload": sys.argv[-1]}))' \
    $JOB $SETUP $SUITE $UPLOAD > $WORK/config.json
  if api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/attempts/${attempt:-1}/jobs?per_page=100"; then
    wc_ jobs $WORK/jobs.json $WORK/config.json > $WORK/jobs.txt 2>&1
  else
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
  fi
  grep -v '^JUDGE ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  # The job log (ANSI colour codes need --allow-escape-sequences, 619); kept with the evidence, tail printed.
  jid=$(allow $PY -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == sys.argv[2]), ""))' $WORK/jobs.json $JOB 2> /dev/null)
  if [[ -n $jid ]] && allow $GH api --allow-escape-sequences "repos/$REPO/actions/jobs/$jid/logs" > $dir/job.log 2> $WORK/err; then
    print -r -- "--- job log saved: $dir/job.log; files ended, hangs, driver exit:"
    print -r -- "  per-file pytest summaries: $(grep -cE '=+ .*(passed|failed|error|skipped|no tests ran).* in [0-9.]+s' $dir/job.log)"
    grep -E '(### HUNG|run_test_files exit code:|INTERNALERROR|has timed out)' $dir/job.log | tail -n 12 | cut -c1-240 | sed 's/^/  /'
  else
    print -r -- "job log unavailable: $(<$WORK/err 2> /dev/null)"
  fi
  # The JUnit artifact of this attempt.
  local name=graftling-windows-junit-$sha-${attempt:-1} files= tlist=
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
  # The suite's temporary directory had a non-ASCII name (638): part of the mechanics.
  local temp="TEMP FAIL no artifact downloaded ($name)"
  if [[ -d $dir/junit ]]; then
    print -r -- "--- non-ASCII paths"
    c638 tempdir $dir/junit > $WORK/temp.txt 2>&1
    grep -v '^TEMP ' $WORK/temp.txt
    temp=$(grep '^TEMP ' $WORK/temp.txt | tail -1); [[ -n $temp ]] || temp="TEMP FAIL temporary directory check failed: $(tail -2 $WORK/temp.txt)"
    print -r -- $temp
  fi
  if [[ $temp == "TEMP FAIL"* ]]; then
    [[ $files == "FILES FAIL"* ]] && files="$files; ${temp#TEMP FAIL }" || files="FILES FAIL ${temp#TEMP FAIL }"
  else
    files="$files; non-ASCII temporary directory"
  fi
  # Mechanics: the job's steps, the per-file records and the temporary directory.
  if [[ $files == "FILES FAIL"* ]]; then
    [[ $mech == "JUDGE PASS"* ]] && mech="JUDGE FAIL ${files#FILES FAIL }" || mech="$mech; ${files#FILES FAIL }"
  else
    mech="$mech; ${files#FILES PASS }"
  fi
  print -r -- "evidence: $dir"
  print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
  [[ $concl != success ]] && print -r -- "next: zsh $THIS X $rid    (re-run its failed jobs; only if the failure is transient, not a test result)"
  [[ $res == "JUDGE FAIL"* ]] && print -r -- "next: correction round: compare $dir/observed-expected.txt with $EXPECTED; after a new bundle: zsh $THIS 00 then zsh $THIS P"
  if [[ $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* ]]; then
    print -r -- "VERDICT 638 $label: PASS (run $rid attempt $attempt on $sha; mechanics: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; $url)"
    exit 0
  fi
  print -r -- "VERDICT 638 $label: FAIL (run $rid attempt $attempt on $sha; mechanics: ${mech#JUDGE }; results: ${res#JUDGE }; $url)"
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
      print -r -- "VERDICT 638 $label: FAIL (run $rid not completed within ${DONE_S}s)"
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
      print -r -- "VERDICT 638 $label: FAIL (the $WORKFLOW run never appeared within ${APPEAR_S}s)"
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
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
  local gurl=$(gg remote get-url origin)
  [[ $gurl == $GURL ]] && print -r -- "PASS: $GRAFT origin is $gurl" || stop "$GRAFT origin is $gurl, not $GURL"
  [[ $GREMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $GREMOTE is used instead of graftling origin"
  check_bundle
  local ready=yes
  check_head || ready=no
  wc_ expected $EXPECTED || ready=no
  graft_local_ok || true
  graft_remote_ok
  if [[ $ready == yes && $REMOTE_STATE == equal ]]; then
    print -r -- "next: zsh $THIS W    (the branch is already at the bundle head; observes its push run, no push)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $THIS P    (publishes graftling $GSHA to $REPO $BRANCH, then waits for the Windows tests run)"
  else
    print -r -- "next: fix the FAIL lines above (new bundle from the Engineer), then zsh $THIS 00"
  fi
  print -r -- "VERDICT 638 00: PASS (P ready: $ready; remote branch $REMOTE_STATE; candidate graftling $GSHA)"
  ;;
P)
  say "[P] Publish and wait. OUTWARD-FACING: pushes $BRANCH to graftling $GREMOTE (fast-forward only, never force); the push starts '$WORKFLOW'. Login: git credential helper, gh login. Dialog: none. Network: GitHub."
  check_bundle
  check_head || stop "the bundle head does not meet the checks above; nothing pushed. Run: zsh $THIS 00"
  wc_ expected $EXPECTED || stop "the expected list does not parse; nothing pushed"
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
      print -r -- "VERDICT 638 X: FAIL (re-run requested, but attempt $before is still the latest after ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "attempt $after appeared after $((SECONDS - start))s"
  wait_run $rid X
  ;;
D)
  say "[D] workflow_dispatch of $WORKFLOW on $BRANCH. OUTWARD-FACING: gh workflow run starts GitHub Actions jobs. Login: gh login, git credential helper (ls-remote). Dialog: none. Network: GitHub."
  check_bundle
  local head=$(gremote_sha) start old
  checked $head
  [[ -n $head ]] || stop "$BRANCH is not on graftling $GREMOTE; run: zsh $THIS 00 then P"
  [[ $head == $GSHA ]] || print -r -- "NOTE: remote head $head is not the bundle head $GSHA; the dispatch runs the remote head"
  api $WORK/before.json "repos/$REPO/actions/runs?head_sha=$head&event=workflow_dispatch&per_page=100" || stop "cannot list runs; nothing dispatched"
  old=$(allow $PY -I -c 'import json, sys; print(" ".join(str(r["id"]) for r in json.load(open(sys.argv[1])).get("workflow_runs", [])))' $WORK/before.json)
  print -r -- "\$ gh workflow run windows.yml --repo $REPO --ref $BRANCH"
  allow $GH workflow run windows.yml --repo $REPO --ref $BRANCH 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh workflow run failed; nothing started"
  start=$SECONDS
  while true; do
    if api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$head&event=workflow_dispatch&per_page=100"; then
      local row=$(wc_ newrun $WORK/runs.json $WORKFLOW workflow_dispatch ${=old})
      [[ $row == RUN* ]] && { local -a f=("${(@ps:\t:)row}"); print -r -- "dispatched run ${f[3]} present after $((SECONDS - start))s"; wait_run ${f[3]} D; }
    fi
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "next: zsh $THIS W $head    (observe; no dispatch)"
      print -r -- "VERDICT 638 D: FAIL (no new workflow_dispatch run of $head within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|W [sha|run-id]|X <run-id>|D"; exit 2 ;;
esac
