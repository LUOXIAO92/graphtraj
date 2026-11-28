#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 654 Main-run steps: run graftling's "Windows tests" workflow (.github/workflows/windows.yml, GitHub-hosted
# windows-latest x64) on one test-only commit, GCOMMIT, on graftling dev GBASE (= main = v0.11.0). The commit changes
# only tests/test_pi_dsh_notice_holding.py::test_a_request_notice_returns_promptly_while_pi_holds_it: after
# acknowledge it waits (wait_until) until the acknowledged request is no longer held, then asserts unchanged that
# exactly the second request is held (653's run 46114515028 attempt 1 failed there on the race). The commit is in
# graftling-654.bundle next to this file. Modelled on adopt-653/steps.zsh (P, W, X, its judge and evidence653.py's
# per-attempt artifact rule) and verify-652/steps.zsh.
# User decision (Worldline): 20261127T190418.319112+0900, the long-term authority to push agent branches to
# LUOXIAO92/graftling and run the Windows workflow. P and X rely on it. dev, main and tags are never pushed here
# (Main merges dev afterwards).
# Run one step at a time:  zsh <this file> <STEP>     order: 00 -> P  (W [run-id] observes; X <run-id> re-runs)
#   00  Preflight, read only (a scratch bare clone under TMPDIR borrows <Harness>/graftling's objects to read the bundle
#       and is deleted). zsh; TMPDIR outside the Harness; gh auth status (account only); <Harness>/graftling's origin
#       and dev = GBASE; the bundle's sha256, verification and head; the commit: parent GBASE, noreply author and
#       committer, exactly the one test file changed (so windows.yml is v0.11.0's) and the test defined; the local and
#       the GitHub agent branch each absent, GCOMMIT or its ancestor; scripts/verify-632/windows-expected.txt present,
#       parsing and identical to GraphTraj dev's. Login: gh's stored login, git credential helper (ls-remote).
#       Network: GitHub. Dialog: none. ~10 s.
#   P   OUTWARD-FACING (20261127T190418.319112+0900): (1) fetch only refs/heads/GBRANCH from the bundle into
#       <Harness>/graftling (absent or an ancestor: fast-forward); (2) push only GBRANCH to origin, fast-forward only,
#       never forced; (3) dispatch windows.yml on it by workflow_dispatch (its push trigger does not list this branch;
#       the workflow is not edited) unless a workflow_dispatch run of GCOMMIT exists, which is then observed; (4) wait
#       in this process (appearance APPEAR_S, completion DONE_S); (5) judge. Login: git credential helper, gh login.
#       Network: GitHub. Dialog: none. Up to ~100 min.
#   W   Observe and judge only: 'W <run-id>' that run; 'W' the newest workflow_dispatch run of GCOMMIT. No push,
#       dispatch or re-run. Login: gh login. Network: GitHub. Dialog: none.
#   X   'X <run-id>': re-run the FAILED jobs of one completed, failed windows.yml run of GCOMMIT (gh run rerun --failed),
#       for a transient runner or download fault only, NEVER for a test result. OUTWARD-FACING. Waits for the new
#       attempt and judges it. Login: gh login. Network: GitHub. Dialog: none.
# VERDICT (P, W, X) PASS only when ALL of: the run's head is GCOMMIT; windows-tests mechanics and results as 632's
# wincheck judges them against the unchanged scripts/verify-632/windows-expected.txt (this Task owns no line there):
# 0 unexpected failures, passes or hangs; the fixed test PASSED in windows-tests' JUnit; dsh-windows-tests and
# claude-real-entry: the job and every step succeeded, and claude-real-entry's results.json has every item PASS on
# win32 (652's realentry). Each job's evidence is the attempt that ran it (adopt-653/evidence653.py).
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG, and
# GH_CONFIG_DIR / XDG_CONFIG_HOME / SSH_AUTH_SOCK when set); cred_guard STOPs if a credential- or provider-like name is
# in it (names only). GH_PROMPT_DISABLED=1, GIT_TERMINAL_PROMPT=0: a login that needs a dialog fails instead.
# Evidence: scripts/verify-654/evidence/ (git-ignored by scripts/verify-654/.gitignore); no tracked file changes.
# Rehearsal knobs (Engineer only; Main leaves them unset): V654_G (a scratch graftling clone), V654_GURL (its origin),
# V654_GH (a gh stand-in), V654_EVIDENCE (evidence root), V654_APPEAR_S, V654_DONE_S, V654_POLL_S.
# No zsh special parameter name is used as a variable (path is used only as zsh's PATH array).
emulate -L zsh
setopt pipe_fail no_unset
TASK=654
THIS=${0:A}
SD=${0:A:h}
WT=$(/usr/bin/env -i PATH=/usr/bin:/bin git -C $SD rev-parse --show-toplevel 2>/dev/null)
H=${WT:h:h:h:h}                                     # the Harness holds this Worktree at .graphtraj/core/worktrees/<name>
STEP=${1:-}
IDS=("${(@)argv[2,-1]}")
WINDECISION=20261127T190418.319112+0900
path=($HOME/.local/bin /opt/homebrew/bin $path)     # gh (the user's usual install)
CONDA=$HOME/miniconda3/bin/python3.13               # read only; runs the helpers with -I
[[ -x $CONDA ]] || CONDA=/usr/bin/python3
G=${V654_G:-$H/graftling}
GURL=${V654_GURL:-https://github.com/LUOXIAO92/graftling.git}
REPO=LUOXIAO92/graftling
GBASE=67b0fe9aacc868c9c6b5a2818adc8449514221c4      # graftling dev = main = v0.11.0 (653)
GCOMMIT=0dad0db948f5a7ec5f069b4910a8d19282634a1e    # 654's test-only commit, parent GBASE
GBRANCH=agent/654-graftling-pi-notice-test-race
BUNDLE=$SD/graftling-654.bundle
BSHA=e9ec81fda434cd4bcaa505c8e2b1c4d68449e265e13298c28ec778ed173fc2aa
GFILE=tests/test_pi_dsh_notice_holding.py
FIXED=$GFILE::test_a_request_notice_returns_promptly_while_pi_holds_it
MAIL=89069722+LUOXIAO92@users.noreply.github.com
GH=${V654_GH:-$(whence -p gh || print -r -- gh)}
WORKFLOW=.github/workflows/windows.yml
APPEAR_S=${V654_APPEAR_S:-300}
DONE_S=${V654_DONE_S:-6000}
POLL_S=${V654_POLL_S:-30}
JOB=windows-tests
DSHJOB=dsh-windows-tests
REALJOB=claude-real-entry
SETUP=("Keep symbolic links on this runner" "Check out the commit under test" "Fail unless the linked package documents are symbolic links"
       "Set up Node 22.18.0 x64" "Set up Python 3.13.7 x64" "Install graftling and pinned test tools" "Show runner, Python and pytest versions")
SUITE="Run the graftling test suite"
UPLOAD="Retain JUnit results"
WINCHECK=$WT/scripts/verify-632/wincheck.py
EXPECTED=$WT/scripts/verify-632/windows-expected.txt
W652=$WT/scripts/verify-652/wincheck652.py
EV653=$WT/scripts/adopt-653/evidence653.py
R=${V654_EVIDENCE:-$SD/evidence}/live
WEV=$R/windows

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
clean() {
  local -a extra=()
  local v; for v in GH_CONFIG_DIR XDG_CONFIG_HOME SSH_AUTH_SOCK; do [[ -n ${(P)v:-} ]] && extra+=$v=${(P)v}; done
  env -i HOME=$HOME USER=${USER:-} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} $extra "$@"
}
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -vx SSH_AUTH_SOCK | grep -E '(KEY|TOKEN|SECRETS?|PASSWORD|CREDENTIALS?)$|_AUTH|_BASE_URL$|^(ANTHROPIC_|OPENAI_|DEEPSEEK_|CODEX_|CLAUDE_CODE_USE_|GRAFTLING_CONNECTION)' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean GIT_TERMINAL_PROMPT=0 git "$@"; }      # every git call: allowlist environment, no prompt
ghc() { clean GH_PROMPT_DISABLED=1 GIT_TERMINAL_PROMPT=0 $GH "$@"; }   # gh's stored login, no prompt
ck() { [[ $1 == 0 ]] && print -r -- "CHECK $TASK $2: PASS${3:+ ($3)}" || print -r -- "CHECK $TASK $2: FAIL${3:+ ($3)}"; }
wc_() { clean $CONDA -I $WINCHECK "$@"; }
w652_() { clean $CONDA -I $W652 "$@"; }
check_tmp() { [[ ${${TMPDIR:-/tmp}:A} != ${H:A}(|/*) ]]; }
branch_ok() {  # $1 = a commit or empty: absent, GCOMMIT, or an ancestor of GCOMMIT in repository $2
  [[ -z $1 || $1 == $GCOMMIT ]] || gg -C $2 merge-base --is-ancestor $1 $GCOMMIT 2>/dev/null
}

# ---- the Windows workflow: Actions API, waiting and judging (653's judge, with 654's fixed test) ----
api() {  # $1 = output file, $2 = endpoint: save a gh api response; on failure print the error and return 1
  ghc api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}
judge() {  # $1 = completed run's json, $2 = label: jobs, logs, artifacts, judgement; ends with the VERDICT line
  local runfile=$1 label=$2 rid sha attempt concl url event jid dir mech res files fix djob rjob real jname tlist= evj evr evd jdir rdir name rname w evsum
  rid=$(wc_ get $runfile id); sha=$(wc_ get $runfile head_sha); attempt=$(wc_ get $runfile run_attempt)
  concl=$(wc_ get $runfile conclusion); url=$(wc_ get $runfile html_url); event=$(wc_ get $runfile event)
  dir=$WEV/run-$rid-a${attempt:-1}; mkdir -p $dir
  print -r -- "--- run $rid | attempt $attempt | $event | conclusion $concl (information only) | head $sha | $url"
  [[ $sha == $GCOMMIT ]] || print -r -- "NOTE: run head $sha is not 654's commit $GCOMMIT (the VERDICT requires it)"
  clean $CONDA -I -c 'import json, sys; print(json.dumps({"job": sys.argv[1], "setup": sys.argv[2:-2], "suite": sys.argv[-2], "upload": sys.argv[-1]}))' \
    $JOB $SETUP $SUITE $UPLOAD > $WORK/config.json
  if api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/attempts/${attempt:-1}/jobs?per_page=100"; then
    cp $WORK/jobs.json $dir/jobs.json
    wc_ jobs $WORK/jobs.json $WORK/config.json > $WORK/jobs.txt 2>&1
    w652_ jobstate $WORK/jobs.json $DSHJOB > $WORK/dshjob.txt 2>&1
    w652_ jobstate $WORK/jobs.json $REALJOB > $WORK/realjob.txt 2>&1
  else
    print -r -- '{}' > $WORK/jobs.json
    print -r -- "JUDGE FAIL jobs of run $rid unreadable" > $WORK/jobs.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/dshjob.txt
    print -r -- "JOBSTATE FAIL jobs of run $rid unreadable" > $WORK/realjob.txt
  fi
  cat $WORK/jobs.txt $WORK/dshjob.txt $WORK/realjob.txt > $dir/jobs.txt
  # Each job's evidence comes from the attempt that ran it (653's evidence653.py): after `gh run rerun --failed` a
  # carried-over job keeps its earlier started_at and artifact; a re-run job must use its own attempt's artifact.
  api $WORK/arts.json "repos/$REPO/actions/runs/$rid/artifacts?per_page=100" && cp $WORK/arts.json $dir/artifacts.json || print -r -- '{"artifacts": []}' > $WORK/arts.json
  print -r -- "artifacts of run $rid: $(clean $CONDA -I -c 'import json, sys; print(" ".join(sorted(a["name"] for a in json.load(open(sys.argv[1])).get("artifacts", []) if not a.get("expired"))) or "none")' $WORK/arts.json 2>&1)"
  evj=$(clean $CONDA -I $EV653 $runfile $WORK/jobs.json $WORK/arts.json $JOB graftling-windows-junit-$sha- 2>&1)
  evr=$(clean $CONDA -I $EV653 $runfile $WORK/jobs.json $WORK/arts.json $REALJOB graftling-claude-real-entry-$sha- 2>&1)
  evd=$(clean $CONDA -I $EV653 $runfile $WORK/jobs.json $WORK/arts.json $DSHJOB - 2>&1)
  for w in "$JOB|$evj" "$REALJOB|$evr" "$DSHJOB|$evd"; do print -r -- "EVIDENCE ${w%%|*}: ${${w#*|}/ - |/ |}"; done | tee $dir/evidence.txt
  grep -v '^JUDGE \|^JOB ' $WORK/jobs.txt
  mech=$(grep '^JUDGE ' $WORK/jobs.txt | tail -1); [[ -n $mech ]] || mech="JUDGE FAIL step judgement failed: $(tail -2 $WORK/jobs.txt)"
  grep -v '^JOBSTATE ' $WORK/dshjob.txt | head -3
  djob=$(grep '^JOBSTATE ' $WORK/dshjob.txt | tail -1); [[ -n $djob ]] || djob="JOBSTATE FAIL $DSHJOB judgement failed"
  [[ $evd == ATTEMPT* ]] || djob="JOBSTATE FAIL $DSHJOB: ${evd#*| }"
  grep -v '^JOBSTATE ' $WORK/realjob.txt
  rjob=$(grep '^JOBSTATE ' $WORK/realjob.txt | tail -1); [[ -n $rjob ]] || rjob="JOBSTATE FAIL $REALJOB judgement failed"
  for jname in $JOB $REALJOB; do   # each job's log (ANSI colour codes need --allow-escape-sequences, 619)
    jid=$(clean $CONDA -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == sys.argv[2]), ""))' $WORK/jobs.json $jname 2> /dev/null)
    if [[ -n $jid ]] && ghc api --allow-escape-sequences "repos/$REPO/actions/jobs/$jid/logs" > $dir/$jname.log 2> $WORK/err; then print -r -- "--- job log saved: $dir/$jname.log"
    else print -r -- "$jname job log unavailable: $(<$WORK/err 2> /dev/null)"; fi
  done
  [[ -f $dir/$JOB.log ]] && grep -E '(### HUNG|run_test_files exit code:|INTERNALERROR|has timed out)' $dir/$JOB.log | tail -n 12 | cut -c1-240 | sed 's/^/  /'
  if [[ $evj == ATTEMPT* ]]; then
    w=(${=evj}); name=$w[3] jdir=$dir/junit-a$w[2]
    if [[ -f $jdir/environment.json ]]; then print -r -- "already present, not downloaded again: $jdir"
    else print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $jdir"; ghc run download $rid --repo $REPO -n $name -D $jdir 2>&1 | sed 's/^/  /'; fi
  else name="none (${evj#*| })" jdir=$dir/junit-none; fi
  if gg -C $G cat-file -e "$sha^{commit}" 2> /dev/null; then   # the commit's test files (in $G after P)
    gg -C $G ls-tree --name-only $sha tests/ | grep -E '^tests/test_[^/]*\.py$' > $WORK/testfiles.txt; tlist=$WORK/testfiles.txt
    print -r -- "test files in $sha: $(grep -c . $tlist)"
  else print -r -- "NOTE: $sha is not in $G; per-file records are not compared with its test files"; fi
  if [[ -f $jdir/environment.json ]]; then
    print -r -- "--- per-file records and results against $EXPECTED (evidence: $name)"
    wc_ junit $jdir $EXPECTED $dir/observed-expected.txt $tlist > $dir/judgement.txt 2>&1
    grep -v '^JUDGE \|^FILES ' $dir/judgement.txt
    files=$(grep '^FILES ' $dir/judgement.txt | tail -1); [[ -n $files ]] || files="FILES FAIL per-file judgement failed: $(tail -2 $dir/judgement.txt)"
    res=$(grep '^JUDGE ' $dir/judgement.txt | tail -1); [[ -n $res ]] || res="JUDGE FAIL JUnit judgement failed: $(tail -2 $dir/judgement.txt)"
    clean $CONDA -I $SD/wincheck654.py fixed $jdir $FIXED > $dir/fixed-test.txt 2>&1
  else
    files="FILES FAIL no artifact downloaded ($name)"; res="JUDGE FAIL no JUnit files"
    print -r -- "FIXED FAIL $FIXED: no JUnit files" > $dir/fixed-test.txt
  fi
  fix=$(grep '^FIXED ' $dir/fixed-test.txt | tail -1); [[ -n $fix ]] || fix="FIXED FAIL check failed: $(tail -2 $dir/fixed-test.txt)"
  if [[ $files == "FILES FAIL"* ]]; then [[ $mech == "JUDGE PASS"* ]] && mech="JUDGE FAIL ${files#FILES FAIL }" || mech="$mech; ${files#FILES FAIL }"
  else mech="$mech; ${files#FILES PASS }"; fi
  print -r -- "--- the fixed test (must PASS)"; grep -v '^FIXED ' $dir/fixed-test.txt
  if [[ $evr == ATTEMPT* ]]; then
    w=(${=evr}); rname=$w[3] rdir=$dir/real-entry-a$w[2]
    if [[ -f $rdir/results.json ]]; then print -r -- "already present, not downloaded again: $rdir"
    else print -r -- "\$ gh run download $rid --repo $REPO -n $rname -D $rdir"; ghc run download $rid --repo $REPO -n $rname -D $rdir 2>&1 | sed 's/^/  /'; fi
    w652_ realentry $rdir > $dir/real-entry-judgement.txt 2>&1
  else print -r -- "REALENTRY FAIL $REALJOB: ${evr#*| }" > $dir/real-entry-judgement.txt; fi
  grep -v '^REALENTRY ' $dir/real-entry-judgement.txt
  real=$(grep '^REALENTRY ' $dir/real-entry-judgement.txt | tail -1); [[ -n $real ]] || real="REALENTRY FAIL judgement failed: $(tail -2 $dir/real-entry-judgement.txt)"
  print -r -- "evidence: $dir"
  print -r -- "RUNID $rid"
  evsum="evidence: $(sed -E 's/^EVIDENCE ([^:]+): ATTEMPT ([0-9]+).*/\1 attempt \2/; s/^EVIDENCE ([^:]+): NONE.*/\1 none/' $dir/evidence.txt | tr '\n' ',' | sed 's/,$//')"
  if [[ $sha == $GCOMMIT && $mech == "JUDGE PASS"* && $res == "JUDGE PASS"* && $fix == "FIXED PASS"* && $djob == "JOBSTATE PASS"* \
        && $rjob == "JOBSTATE PASS"* && $real == "REALENTRY PASS"* ]]; then
    print -r -- "VERDICT $TASK $label: PASS (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE PASS }; results: ${res#JUDGE PASS }; fixed test: ${fix#FIXED PASS }; ${djob#JOBSTATE PASS }; ${rjob#JOBSTATE PASS }; real Claude Code: ${real#REALENTRY PASS }; $evsum; $url)"
    return 0
  fi
  print -r -- "VERDICT $TASK $label: FAIL (run $rid attempt $attempt on $sha; windows-tests: ${mech#JUDGE }; results: ${res#JUDGE }; fixed test: ${fix#FIXED }; ${djob#JOBSTATE }; ${rjob#JOBSTATE }; real Claude Code: ${real#REALENTRY }; $evsum; $url)"
  return 1
}
wait_run() {  # $1 = run id, $2 = label: wait for completion (bounded), then judge
  local rid=$1 label=$2 start=$SECONDS rstate= prev= line
  print -r -- "waiting in this process for run $rid (completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    api $WORK/run.json repos/$REPO/actions/runs/$rid && rstate=$(wc_ get $WORK/run.json status)
    line="${rstate:-unknown} $(wc_ get $WORK/run.json conclusion 2> /dev/null)"
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] run $rid: $line"; prev=$line
    [[ $rstate == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "RUNID $rid"; print -r -- "completion timeout after $((SECONDS - start))s (run still ${rstate:-unknown})"
      print -r -- "VERDICT $TASK $label: FAIL (run $rid not completed within ${DONE_S}s)"; return 1
    fi
    sleep $POLL_S
  done
  judge $WORK/run.json $label
}
dispatch_ids() {  # $1 = runs json: the windows.yml workflow_dispatch run ids in it, space separated
  clean $CONDA -I -c 'import json, sys; print(" ".join(str(r["id"]) for r in json.load(open(sys.argv[1])).get("workflow_runs", []) if r.get("path") == sys.argv[2] and r.get("event") == "workflow_dispatch"))' $1 $WORKFLOW
}
win_after() {  # $1 = the step (P, W, X): the verdict and the next commands, printed last
  local v rid; v=$(grep "^VERDICT $TASK " $R/$1.txt | tail -1); rid=$(sed -n 's/^RUNID //p' $R/$1.txt | tail -1)
  print -- "\n----- summary for Main ($1) -----"
  grep -E "^(CHECK|EVIDENCE|remote|dispatch|run [0-9])" $R/$1.txt
  print -r -- "evidence: $R/$1.txt and $WEV"
  if [[ $v == "VERDICT $TASK $1: PASS"* ]]; then
    print -r -- "$v"
    next "nothing more to run: report the VERDICT line above and $R/$1.txt to Task 654's Leader (Main merges dev; not this script)"
    return 0
  fi
  print -r -- "${v:-VERDICT $TASK $1: FAIL (no VERDICT; see above)}"
  print -r -- "Evidence under $WEV. A test result failing: hand $R/$1.txt to Task 654's Leader; never re-run it with X. Never push dev, main or a tag."
  if [[ -n $rid ]]; then next "zsh $THIS W $rid    (observe again; no push, no re-run)   or, only for a transient runner/download fault: zsh $THIS X $rid"
  else next "zsh $THIS W    (observe the newest workflow_dispatch run of $GCOMMIT)"; fi
  return 1
}

[[ -n $WT && -d $WT/scripts/verify-654 ]] || { print -r -- "STOP: cannot resolve the Worktree from $SD"; exit 1; }
mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only (a scratch bare clone under TMPDIR, deleted at the end). Login: gh's stored login (auth status, account only), git credential helper (ls-remote). Network: GitHub. Dialog: none."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/verify654-00.XXXXXX); trap 'rm -rf $WORK' EXIT
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    check_tmp; ck $? "00 TMPDIR outside the Harness"
    au=$(ghc auth status 2>&1); arc=$?
    print -r -- "gh: $(ghc --version 2>&1 | head -1) | $(print -r -- $au | grep -oE 'account [^ ]+' | head -1)"
    ck $arc "00 gh auth status rc 0 (gh's stored login; P, W, X use it)"
    say "graftling repository $G (read only)"
    gd=$(gg -C $G rev-parse -q --verify refs/heads/dev); print -r -- "dev: ${gd:-NOT FOUND} | origin: $(gg -C $G remote get-url origin 2>&1)"
    [[ $(gg -C $G remote get-url origin 2>&1) == $GURL ]]; ck $? "00 origin of $G is $GURL"
    [[ $gd == $GBASE ]]; ck $? "00 graftling dev = $GBASE (v0.11.0)" "${gd:-absent}"
    say "bundle $BUNDLE"
    bs=$(shasum -a 256 $BUNDLE | cut -d' ' -f1); print -r -- "sha256: $bs"
    [[ $bs == $BSHA ]]; ck $? "00 bundle sha256 = $BSHA"
    gg -C $G bundle verify -q $BUNDLE > /dev/null 2>&1; ck $? "00 bundle verifies against $G (prerequisite $GBASE)"
    heads=$(gg bundle list-heads $BUNDLE); print -r -- "list-heads: $heads"
    [[ $heads == "$GCOMMIT refs/heads/$GBRANCH" ]]; ck $? "00 bundle head = $GCOMMIT ($GBRANCH)"
    say "the commit, read from a scratch bare clone under TMPDIR (objects borrowed from $G, which is not written)"
    gg clone -q --bare --shared $G $WORK/g.git && gg -C $WORK/g.git fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" \
      || { ck 1 "00 read the bundle into a scratch clone"; }
    X=(gg -C $WORK/g.git)
    print -r -- "$GCOMMIT: $($X log -1 --format='%s | author %an <%ae> | committer %cn <%ce> | parent %P' $GCOMMIT 2>&1)"
    [[ $($X log -1 --format=%P $GCOMMIT 2>/dev/null) == $GBASE ]]; ck $? "00 $GCOMMIT is one commit on $GBASE"
    [[ $($X log -1 --format='%ae %ce' $GCOMMIT 2>/dev/null) == "$MAIL $MAIL" ]]; ck $? "00 author and committer are $MAIL"
    changed=$($X diff --name-only $GBASE $GCOMMIT 2>&1 | tr '\n' ' '); print -r -- "changed files: $changed"
    [[ $changed == "$GFILE " ]]; ck $? "00 the commit changes exactly $GFILE (no product code; windows.yml is v0.11.0's)"
    $X show $GCOMMIT:$GFILE 2>/dev/null | grep -q "^def ${FIXED##*::}("; ck $? "00 $FIXED is defined at $GCOMMIT"
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH); branch_ok "$lb" $WORK/g.git; ck $? "00 local $GBRANCH absent, $GCOMMIT or its ancestor" "${lb:-absent}"
    say "GitHub $GURL (git ls-remote, read only)"
    if rem=$(gg ls-remote $GURL refs/heads/$GBRANCH 2>&1); then
      rb=${rem%%$'\t'*}; print -r -- "GitHub $GBRANCH: ${rb:-absent}"
      branch_ok "$rb" $WORK/g.git; ck $? "00 GitHub $GBRANCH absent, $GCOMMIT or its ancestor (P pushes fast-forward only)" "${rb:-absent}"
    else ck 1 "00 git ls-remote $GURL" "${rem[1,200]}"; fi
    say "the Windows judgement's inputs (read only)"
    [[ -f $EXPECTED ]]; ck $? "00 $EXPECTED present"
    wc_ expected $EXPECTED | tail -2; ck ${pipestatus[1]} "00 windows-expected.txt parses"
    wb=$(gg -C $WT rev-parse -q --verify dev:scripts/verify-632/windows-expected.txt) wh=$(gg -C $WT hash-object $EXPECTED 2>/dev/null)
    print -r -- "windows-expected.txt: this Worktree $wh | GraphTraj dev ${wb:-absent}"
    [[ -n $wb && $wb == $wh ]]; ck $? "00 windows-expected.txt identical to GraphTraj dev's (this Task owns no line in it)"
    for f in $WINCHECK $W652 $EV653 $SD/wincheck654.py; do [[ -f $f ]] || print -r -- "missing: $f"; done
    [[ -f $WINCHECK && -f $W652 && -f $EV653 && -f $SD/wincheck654.py ]]; ck $? "00 the judge's helpers present (wincheck.py, wincheck652.py, evidence653.py, wincheck654.py)"
  } 2>&1 | tee $R/00.txt
  nf=$(grep -c "^CHECK $TASK .*: FAIL" $R/00.txt); np=$(grep -c "^CHECK $TASK .*: PASS" $R/00.txt)
  print -- "\n----- summary for Main (00) -----"; print -r -- "evidence: $R/00.txt"
  if (( nf == 0 && np > 0 )); then print -r -- "VERDICT $TASK 00: PASS ($np checks)"
    next "zsh $THIS P    (pushes $GBRANCH, dispatches the Windows workflow on it and waits for it in this process, up to ~100 min)"
  else grep "^CHECK $TASK .*: FAIL" $R/00.txt; print -r -- "VERDICT $TASK 00: FAIL ($nf of $((np + nf)) checks failed)"
    next "nothing: report $R/00.txt to Task 654's Leader (do not run P)"; exit 1; fi ;;

P) print "[P] Main. OUTWARD-FACING under the user's long-term authority $WINDECISION: (1) fetch only $GBRANCH from the bundle into $G; (2) push only $GBRANCH to origin ($GURL), fast-forward only, never forced; (3) dispatch $WORKFLOW on it by workflow_dispatch unless a dispatch run of $GCOMMIT exists, which is then observed; (4) wait in this process (appearance ${APPEAR_S}s, completion ${DONE_S}s); (5) judge. dev, main and tags are never pushed. Login: git credential helper (push), gh's stored login. Network: GitHub. Dialog: none. Up to ~100 min."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/verify654-P.XXXXXX); trap 'rm -rf $WORK' EXIT
    [[ $(shasum -a 256 $BUNDLE | cut -d' ' -f1) == $BSHA ]] && gg -C $G bundle verify -q $BUNDLE > /dev/null 2>&1 \
      && [[ $(gg bundle list-heads $BUNDLE) == "$GCOMMIT refs/heads/$GBRANCH" ]] || { print "STOP: the bundle (sha256 $BSHA, head $GCOMMIT) does not verify against $G. Nothing pushed."; exit 1; }
    [[ $(gg -C $G remote get-url origin 2>&1) == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL. Nothing fetched or pushed."; exit 1; }
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH)
    if [[ $lb != $GCOMMIT ]]; then   # only this ref; git fetch without '+' updates it only when it fast-forwards
      print -r -- "local $GBRANCH: ${lb:-absent}; \$ git fetch <bundle> refs/heads/${GBRANCH}:refs/heads/$GBRANCH"
      gg -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" || { print -r -- "STOP: fetching $GBRANCH from the bundle failed (local ${lb:-absent}; never overwritten). Nothing pushed."; exit 1; }
    fi
    lb=$(gg -C $G rev-parse -q --verify refs/heads/$GBRANCH); [[ $lb == $GCOMMIT ]]; ck $? "P local $GBRANCH = $GCOMMIT" "$lb"
    [[ $lb == $GCOMMIT ]] || exit 1
    rem=$(gg -C $G ls-remote origin refs/heads/$GBRANCH 2>&1) || { print -r -- "STOP: git ls-remote failed (nothing pushed): ${rem[1,200]}"; exit 1; }
    rb=${rem%%$'\t'*}
    if [[ $rb == $GCOMMIT ]]; then print -r -- "remote $GBRANCH: already $GCOMMIT (not pushed again)"
    elif branch_ok "$rb" $G; then
      print -r -- "remote $GBRANCH: ${rb:-absent}; pushing only refs/heads/$GBRANCH (fast-forward only, no force)"
      gg -C $G push origin refs/heads/${GBRANCH}:refs/heads/$GBRANCH 2>&1 | sed 's/^/  /'; (( ${pipestatus[1]} == 0 )) || { print "STOP: the push was refused (above). Nothing else changed."; exit 1; }
    else print -r -- "STOP: origin has $GBRANCH at $rb, not $GCOMMIT or its ancestor; never forced. Nothing pushed."; exit 1; fi
    now=$(gg -C $G ls-remote origin refs/heads/$GBRANCH 2>&1); [[ ${now%%$'\t'*} == $GCOMMIT ]]; ck $? "P remote $GBRANCH = $GCOMMIT" "${now%%$'\t'*}"
    api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" || { print "STOP: the Actions API is not readable (gh login?). The branch is pushed; rerun P (it will not push again)."; print -r -- "VERDICT $TASK P: FAIL (Actions API unreadable)"; exit 1; }
    old=($(dispatch_ids $WORK/runs.json))
    if (( $#old )); then
      print -r -- "dispatch: a workflow_dispatch run of $GCOMMIT exists (${old[*]}); P does not dispatch again and observes the newest"
      row=$(wc_ runs $WORK/runs.json $WORKFLOW workflow_dispatch | grep '^RUN' | head -1)
    else
      print -r -- "dispatch: \$ gh workflow run windows.yml --repo $REPO --ref $GBRANCH"
      ghc workflow run windows.yml --repo $REPO --ref $GBRANCH 2>&1 | sed 's/^/  /'; (( ${pipestatus[1]} == 0 )) || { print "STOP: the dispatch failed (above). The branch is pushed; rerun P."; print -r -- "VERDICT $TASK P: FAIL (dispatch refused)"; exit 1; }
      start=$SECONDS row=
      while true; do
        sleep $POLL_S
        api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" && row=$(wc_ newrun $WORK/runs.json $WORKFLOW workflow_dispatch $old | grep '^RUN' | head -1)
        [[ -n $row ]] && break
        (( SECONDS - start >= APPEAR_S )) && { print -r -- "VERDICT $TASK P: FAIL (the dispatched $WORKFLOW run of $GCOMMIT did not appear within ${APPEAR_S}s)"; exit 1; }
      done
    fi
    f=("${(@ps:\t:)row}"); print -r -- "run ${f[3]}: ${f[7]} | ${f[6]}"
    wait_run ${f[3]} P
  } 2>&1 | tee $R/P.txt
  win_after P || exit 1 ;;

W) print "[W] Main. Observe and judge only (no push, no dispatch, no re-run): 'W <run-id>' that run; 'W' the newest workflow_dispatch run of $GCOMMIT. Login: gh's stored login. Network: GitHub. Dialog: none."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/verify654-W.XXXXXX); trap 'rm -rf $WORK' EXIT
    rid=${IDS[1]:-}
    if [[ -z $rid ]]; then
      api $WORK/runs.json "repos/$REPO/actions/runs?head_sha=$GCOMMIT&per_page=100" || { print -r -- "VERDICT $TASK W: FAIL (Actions API unreadable)"; exit 1; }
      row=$(wc_ runs $WORK/runs.json $WORKFLOW workflow_dispatch | grep '^RUN' | head -1); f=("${(@ps:\t:)row}"); rid=${f[3]:-}
      [[ -n $rid ]] || { print -r -- "VERDICT $TASK W: FAIL (no workflow_dispatch run of $GCOMMIT: run P)"; exit 1; }
    fi
    [[ $rid =~ '^[0-9]+$' ]] || { print -r -- "VERDICT $TASK W: FAIL (not a run id: $rid)"; exit 1; }
    wait_run $rid W
  } 2>&1 | tee $R/W.txt
  win_after W || exit 1 ;;

X) print "[X] Main. OUTWARD-FACING (the user's long-term authority $WINDECISION): 'X <run-id>' re-runs the FAILED jobs of one completed, failed windows.yml run of $GCOMMIT (gh run rerun --failed), for a transient runner or download fault only, NEVER for a test result. Waits for the new attempt and judges it. Login: gh's stored login. Network: GitHub. Dialog: none."
  { WORK=$(mktemp -d ${TMPDIR:-/tmp}/verify654-X.XXXXXX); trap 'rm -rf $WORK' EXIT
    rid=${IDS[1]:-}; [[ $rid =~ '^[0-9]+$' ]] || { print -r -- "usage: zsh $THIS X <run-id>"; print -r -- "VERDICT $TASK X: FAIL (no run id)"; exit 2; }
    api $WORK/run.json repos/$REPO/actions/runs/$rid || { print -r -- "VERDICT $TASK X: FAIL (run $rid unreadable)"; exit 1; }
    a0=$(wc_ get $WORK/run.json run_attempt) st=$(wc_ get $WORK/run.json status) sh=$(wc_ get $WORK/run.json head_sha) cn=$(wc_ get $WORK/run.json conclusion)
    [[ $st == completed && $cn != success && $sh == $GCOMMIT ]] || { print -r -- "STOP: run $rid is $st/$cn on $sh; X re-runs only a completed, failed run of $GCOMMIT. Nothing re-run."; print -r -- "VERDICT $TASK X: FAIL (nothing re-run)"; exit 1; }
    print -r -- "\$ gh run rerun $rid --failed --repo $REPO   (attempt $a0 -> $((a0 + 1)))"
    ghc run rerun $rid --failed --repo $REPO 2>&1 | sed 's/^/  /'; (( ${pipestatus[1]} == 0 )) || { print "STOP: the re-run was refused (above)."; print -r -- "VERDICT $TASK X: FAIL (re-run refused)"; exit 1; }
    start=$SECONDS
    while true; do
      sleep $POLL_S
      api $WORK/run.json repos/$REPO/actions/runs/$rid && [[ $(wc_ get $WORK/run.json run_attempt) -gt $a0 ]] && break
      (( SECONDS - start >= APPEAR_S )) && { print -r -- "VERDICT $TASK X: FAIL (attempt $((a0 + 1)) of run $rid did not appear within ${APPEAR_S}s)"; exit 1; }
    done
    wait_run $rid X
  } 2>&1 | tee $R/X.txt
  win_after X || exit 1 ;;

*) print -r -- "usage: zsh $THIS 00|P|W [run-id]|X <run-id>"; exit 2 ;;
esac
