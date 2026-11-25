#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 636 (W4) Main-run steps: publish graftling's W4 candidate (the owner connection as a named pipe on Windows,
# its caller identity, withdraw and close; claim_channel and owner.lock through locks) from the bundle to
# LUOXIAO92/graftling as agent/636-graftling-windows-named-pipe; the push starts "Windows tests"
# (.github/workflows/windows.yml, Task 632) on a GitHub-hosted windows-latest x64 runner. The step waits for that run
# in this process, downloads its artifact and judges it with Task 632's judgement (scripts/verify-632/wincheck.py)
# against the edited list scripts/verify-632/windows-expected.txt. Modelled on scripts/verify-634/steps.zsh.
#
# LOGIN: the user's own logins only. graftling push / ls-remote use https with the user's git credential helper
# (osxkeychain); gh uses its stored login (gh auth status shows the account; no token is printed). GH_TOKEN,
# GITHUB_TOKEN and every other credential-class variable are removed at start, so neither gh nor git can use a token
# from the environment. No step raises a native dialog (GH_PROMPT_DISABLED=1, GIT_TERMINAL_PROMPT=0; a credential
# helper that needs a dialog fails the push instead, and the step STOPs).
# REAL ENTRY: the push run of windows.yml started by pushing this branch to LUOXIAO92/graftling. windows.yml at the
# bundle head lists this branch in on.push.branches (the one workflow change; workflow_dispatch cannot run it because
# the workflow is not on graftling's default branch). Nothing of GraphTraj is pushed; dev, main and tags never are.
# EXPECTED FLOW: the first real run is also discovery. The 37 W4 (636) entries were removed from the list because
# this change removes their failure point (the refusal 'Windows does not support the authenticated local control
# pipe', the directory lock of the control channel); a test that now fails later, at a point another Windows Task
# owns (W3's process groups, say), is an unexpected failure. P/W print every difference and write the observed
# list; the correction round reports those entries for re-placement, and Main runs W <run-id> again or, after a new
# bundle, 00 then P (fast-forward only). W4's own tests (tests/test_channel_windows_636.py, real pipes, another
# local account, a killed host; tests/test_channel_windows_emulated_636.py) are not listed, so they must pass.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git and gh versions; gh auth status (account only); <Harness>/graftling origin is
#       https://github.com/LUOXIAO92/graftling.git; the bundle verifies against <Harness>/graftling, its base is
#       graftling dev d5fb80c7 (W1, W2 and W6 integrated) and every other prerequisite git lists is an ancestor of
#       d5fb80c7 (478dfd7f, the parent of W4's first commit); read through a temporary repository that borrows
#       <Harness>/graftling's objects (nothing is written there): noreply author and committer, changed files since
#       d5fb80c7 only under src/graftling/ and tests/ plus the workflow and README.md (the stat is shown), the
#       workflow equal to d5fb80c7's except the one push branches line, its job steps present by name; the expected
#       list parses; the local branch in
#       <Harness>/graftling and the remote branch are each absent, the bundle head, or an ancestor of it (else STOP).
#       Login: gh login, git credential helper (ls-remote). Dialog: none. Network: GitHub. ~10 s.
#   P   Publish and wait. OUTWARD-FACING: (1) fetches the bundle into <Harness>/graftling as the local branch (only if
#       absent or an ancestor; git fetch without '+' is fast-forward only; nothing when equal); (2) pushes it to
#       graftling origin, fast-forward only, never force, and verifies with ls-remote; (3) waits in this process for
#       the windows.yml push run of that SHA (appearance bound 300 s, completion bound 6000 s, poll 30 s); (4) judges it
#       (below); (5) prints the next commands and the VERDICT last.
#       Login: git credential helper, gh login. Dialog: none. Network: GitHub. Up to ~105 min.
#   W   Observe only (no push, no re-run): `W` the push run of the remote branch head, `W <sha>` the newest windows.yml
#       run of that commit (any event), `W <run-id>` that run. Same waiting and judging as P.
#       Login: gh login (git credential helper for `W` without argument: ls-remote). Dialog: none. Network: GitHub.
#   X   `X <run-id>`: re-run the failed jobs of one completed, failed windows.yml run of this branch (gh run rerun
#       --failed), for transient failures only (a runner or download fault, not a test result). OUTWARD-FACING
#       (starts GitHub Actions jobs). Waits for the new attempt to appear (300 s) and complete (6000 s), then judges
#       it like P. Login: gh login. Dialog: none. Network: GitHub.
# VERDICT (P, W, X): PASS only when BOTH
#   mechanics: the run completed; in job windows-tests every setup step succeeded, the suite step ran to its end
#     (success or failure), the upload succeeded and no other step failed; the artifact was downloaded; the per-file
#     driver finished and files.json has a record for every tests/test_*.py of the run commit, each ended or recorded
#     as hung;
#   results: the tests failing on Windows are exactly the `fail` entries of windows-expected.txt, hangs exactly its
#     `hang` entries, and every skip is "POSIX-only: " or an allowed environment skip. W4's own new tests
#     (tests/test_channel_windows_636.py and tests/test_channel_windows_emulated_636.py) are not listed, so they
#     must pass.
# EVIDENCE: each judgement writes a NEW directory scripts/verify-636/runs/<UTC time>-<step>-run-<id>-a<attempt>/
#   (job.log, junit/ = the artifact, judgement.txt, observed-expected.txt). runs/ is gitignored
#   (scripts/verify-636/.gitignore), so no step rewrites a tracked file. To retain a run, the next Engineer round
#   copies that directory to scripts/verify-636/evidence/ (a new path) and commits it.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY636_GRAFTLING (a scratch graftling clone instead of <Harness>/graftling),
# VERIFY636_GREMOTE (push/ls-remote target instead of that clone's origin), VERIFY636_GH (a gh stand-in),
# VERIFY636_BUNDLE (another bundle of this branch), VERIFY636_EXPECTED (another expected list), VERIFY636_EVIDENCE
# (evidence root), VERIFY636_APPEAR_S / _DONE_S /
# _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
STEP=${1:-}
BRANCH=agent/636-graftling-windows-named-pipe
# graftling dev d5fb80c7 (W1, W2 and W6 integrated): the bundle's base. W4's own history starts on 478dfd7f, so git
# also lists 478dfd7f as a prerequisite; check_bundle accepts it only as an ancestor of BASE.
BASE=d5fb80c7cf5d85a19971c434e7f247568ad22bef
REPO=LUOXIAO92/graftling
GURL=https://github.com/LUOXIAO92/graftling.git
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY636_GRAFTLING:-$HARNESS/graftling}
GREMOTE=${VERIFY636_GREMOTE:-origin}
GH=${VERIFY636_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY636_APPEAR_S:-300}
DONE_S=${VERIFY636_DONE_S:-6000}
POLL_S=${VERIFY636_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
WORKFLOW=.github/workflows/windows.yml
JOB=windows-tests
BUNDLE=${VERIFY636_BUNDLE:-$HERE/graftling-636.bundle}
WINCHECK=$WT/scripts/verify-632/wincheck.py
EXPECTED=${VERIFY636_EXPECTED:-$WT/scripts/verify-632/windows-expected.txt}
EVID=${VERIFY636_EVIDENCE:-$HERE/runs}
# The one workflow change: the push branches line at d5fb80c7 and at the bundle head.
BRANCHES_BASE="    branches: [agent/632-graftling-windows-ci, agent/633-graftling-windows-process, agent/634-graftling-windows-durable-writes, dev, agent/638-graftling-windows-paths-encoding]"
BRANCHES_HEAD="    branches: [agent/632-graftling-windows-ci, agent/633-graftling-windows-process, agent/634-graftling-windows-durable-writes, dev, agent/638-graftling-windows-paths-encoding, $BRANCH]"
# The one documentation file this change edits (the Windows security difference); everything else is code or tests.
DOC=README.md
# The job's steps by their exact `name:` in $WORKFLOW (unchanged since defad1db).
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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 636 $STEP: STOP"; exit 1; }
gg() { allow $GIT -C $GRAFT "$@"; }
wc_() { allow $PY -I $WINCHECK "$@"; }
WORK=$(mktemp -d $PYTMP/verify636.XXXXXX)
trap 'rm -rf $WORK' EXIT
[[ $BRANCH == agent/636-* ]] || stop "this script publishes only its own agent/636 branch"

# api <file> <endpoint>: save a gh api response; on failure print the error and return 1.
api() {
  allow $GH api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}

GSHA=
bundle_head() { allow $GIT bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1; }
# Every prerequisite the bundle lists, one per line.
bundle_prereqs() { gg bundle verify $BUNDLE 2>&1 | awk '/^The bundle requires/ {on = 1; next} /^The bundle (uses|contains)/ {on = 0} on && NF {print $1}'; }
check_bundle() {  # the bundle verifies against $GRAFT; BASE is a prerequisite and any other is an ancestor of it; sets GSHA
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
  print -r -- "PASS: bundle verifies against $GRAFT; head $GSHA on base $BASE (prerequisites: ${prereqs}; others are ancestors of the base)"
}
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
# check_head: read the bundle head through $PEEK; returns the number of FAILs.
check_head() {
  local peek=$PEEK bad=0 changed outside wdiff names want n
  peek_repo
  print -r -- "--- bundle commits on $BASE:"
  allow $GIT -C $peek log --format='  %h %an <%ae> | %cn <%ce> | %s' $BASE..peek
  local idents=$(allow $GIT -C $peek log --format='%ae%n%ce' $BASE..peek | sort -u)
  [[ $idents == 89069722+LUOXIAO92@users.noreply.github.com ]] && print -r -- "PASS: author and committer are the noreply identity" \
    || { print -r -- "FAIL: identities in the bundle: ${(f)idents}"; (( bad++ )); }

  # The product diff: src/graftling/ and tests/ only, plus the workflow's one line and the one document.
  print -r -- "--- files changed since $BASE:"; allow $GIT -C $peek diff --stat $BASE peek | sed 's/^/  /'
  changed=$(allow $GIT -C $peek diff --name-only $BASE peek)
  outside=$(print -r -- $changed | grep -vE '^(src/graftling/|tests/)' | grep -vxF $WORKFLOW | grep -vxF $DOC)
  [[ -z $outside ]] && print -r -- "PASS: changed files are under src/graftling/ and tests/, plus $WORKFLOW and $DOC" \
    || { print -r -- "FAIL: files changed outside src/graftling/ and tests/ (besides $WORKFLOW and $DOC): ${(f)outside}"; (( bad++ )); }

  # The workflow equals the base's except the push branches line.
  wdiff=$(allow $GIT -C $peek diff -U0 $BASE peek -- $WORKFLOW | grep -E '^[-+]' | grep -vE '^(\+\+\+|---) ')
  want="-$BRANCHES_BASE"$'\n'"+$BRANCHES_HEAD"
  if [[ $wdiff == $want ]]; then
    print -r -- "PASS: $WORKFLOW differs from $BASE only in on.push.branches, which adds $BRANCH"
  else
    print -r -- "FAIL: $WORKFLOW differs from $BASE otherwise than the one push branches line:"
    print -r -- "${wdiff:-  (no difference: the push of $BRANCH would start no run)}" | sed 's/^/  /'
    (( bad++ ))
  fi
  local missing=0
  names=$(allow $GIT -C $peek show peek:$WORKFLOW 2> /dev/null | sed -nE 's/^[[:space:]]*(- )?name: //p')
  for n in $SETUP $SUITE $UPLOAD; do
    print -r -- $names | grep -qxF -- $n || { print -r -- "FAIL: $WORKFLOW has no step named '$n'"; (( missing++ )); }
  done
  (( missing )) || print -r -- "PASS: the ${#SETUP} setup steps, '$SUITE' and '$UPLOAD' are named as judged"
  return $(( bad + missing ))
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
check_expected() {  # the list parses; how many W4 entries remain
  wc_ expected $EXPECTED || return 1
  print -r -- "W4 (636) entries left in the list: $(grep -c $'\tW4 (636)\t' $EXPECTED)"
}

# judge <run-json-file> <label>: the run is completed; print jobs, fetch evidence into a new directory, judge;
# ends with the VERDICT.
judge() {
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res
  rid=$(wc_ get $runfile id); sha=$(wc_ get $runfile head_sha); attempt=$(wc_ get $runfile run_attempt)
  concl=$(wc_ get $runfile conclusion); url=$(wc_ get $runfile html_url); event=$(wc_ get $runfile event)
  dir=$EVID/$(date -u +%Y%m%dT%H%M%SZ)-$label-run-$rid-a${attempt:-1}
  [[ -e $dir ]] && dir=$dir-$$
  mkdir -p $dir || stop "cannot make the evidence directory $dir"
  print -r -- "--- run $rid | attempt $attempt | $event | conclusion $concl (information only) | head $sha | $url"
  [[ -z $GSHA || $sha == $GSHA ]] || print -r -- "NOTE: run head $sha is not the bundle head $GSHA"
  allow $PY -I -c 'import json, sys; print(json.dumps({"job": sys.argv[1], "setup": sys.argv[2:-2], "suite": sys.argv[-2], "upload": sys.argv[-1]}))' \
    $JOB $SETUP $SUITE $UPLOAD > $WORK/config.json
  if api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/attempts/${attempt:-1}/jobs?per_page=100"; then
    wc_ jobs $WORK/jobs.json $WORK/config.json > $WORK/jobs.txt 2>&1
  else
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
  fi
  cp $WORK/jobs.txt $dir/jobs.txt
  grep -v '^JUDGE ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  # The job log (ANSI colour codes need --allow-escape-sequences); kept with the evidence, tail printed.
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
  print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dir/junit"
  allow $GH run download $rid --repo $REPO -n $name -D $dir/junit 2>&1 | sed 's/^/  /'
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
  print -r -- "evidence (new directory, gitignored): $dir"
  print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
  [[ $concl != success ]] && print -r -- "next: zsh $THIS X $rid    (re-run its failed jobs; only if the failure is transient, not a test result)"
  [[ $res == "JUDGE FAIL"* ]] && print -r -- "next: correction round: compare $dir/observed-expected.txt with $EXPECTED; after a new bundle: zsh $THIS 00 then zsh $THIS P"
  if [[ $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* ]]; then
    print -r -- "VERDICT 636 $label: PASS (run $rid attempt $attempt on $sha; mechanics: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; $url)"
    exit 0
  fi
  print -r -- "VERDICT 636 $label: FAIL (run $rid attempt $attempt on $sha; mechanics: ${mech#JUDGE }; results: ${res#JUDGE }; $url)"
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
      print -r -- "VERDICT 636 $label: FAIL (run $rid not completed within ${DONE_S}s)"
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
      print -r -- "VERDICT 636 $label: FAIL (the $WORKFLOW run never appeared within ${APPEAR_S}s)"
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
  check_expected || ready=no
  graft_local_ok || true
  graft_remote_ok
  if [[ $ready == yes && $REMOTE_STATE == equal ]]; then
    print -r -- "next: zsh $THIS W    (the branch is already at the bundle head; observes its push run, no push)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $THIS P    (publishes graftling $GSHA to $REPO $BRANCH, then waits for the Windows tests run)"
  else
    print -r -- "next: fix the FAIL lines above (new bundle from the Engineer), then zsh $THIS 00"
  fi
  print -r -- "VERDICT 636 00: PASS (P ready: $ready; remote branch $REMOTE_STATE; candidate graftling $GSHA)"
  ;;
P)
  say "[P] Publish and wait. OUTWARD-FACING: pushes $BRANCH to graftling $GREMOTE (fast-forward only, never force); the push starts '$WORKFLOW'. Login: git credential helper, gh login. Dialog: none. Network: GitHub."
  check_bundle
  check_head || stop "the bundle head does not meet the checks above; nothing pushed. Run: zsh $THIS 00"
  check_expected || stop "the expected list does not parse; nothing pushed"
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
      print -r -- "VERDICT 636 X: FAIL (re-run requested, but attempt $before is still the latest after ${APPEAR_S}s)"
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
