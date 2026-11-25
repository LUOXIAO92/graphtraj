#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 623 Main-run steps: push this Task's branch so the four desktop workflows run on it with graftling v0.10.2,
# and wait for all four results. Modelled on verify-621/steps.zsh (ghjson.py copied from there and extended).
#
# LOGIN: the user's own GitHub logins only. git push / ls-remote use the user's ssh key (SSH_AUTH_SOCK); gh uses
# its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN and every other
# credential-class variable are removed at start, so gh cannot use a token from the environment.
# REAL ENTRY: `git push origin agent/623-windows-desktop-adoption-green`. The push trigger lists of the four
# desktop workflows (desktop-win-adoption, desktop-macos-adoption, desktop-linux-adoption, desktop-repair-package)
# name that branch; each also changed its GRAFTLING_REF to v0.10.2, so each must run on the candidate.
# desktop-win-adoption has no workflow_dispatch, so there is no dispatch step; X re-runs failed jobs of one run.
# Run one step at a time:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh, git and gh versions; gh auth status (account only); origin is LUOXIAO92/graphtraj;
#       graftling tag v0.10.2 on LUOXIAO92/graftling resolves to commit 57bca736 (gh api); current branch; the
#       remote branch is absent, equal to or an ancestor of HEAD (else STOP, never force); the P preconditions
#       (P ready or not). Login: gh login, ssh key. Dialog: none. Network: GitHub. ~10 s.
#   P   Push and wait. OUTWARD-FACING: publishes the branch to GitHub (fast-forward only, never force); the push starts
#       the four desktop workflows. Checks first: on the Task branch, clean tracked tree, base an ancestor, nothing
#       changed under desktop/src desktop/electron src, under .github/workflows exactly the four files with only
#       Task 623's allowed lines, and the graftling tag. Then waits in this process for the push runs of HEAD of all
#       four workflows (by head_sha) to appear (bounded 300 s) and complete (bounded 3000 s, polling every 30 s);
#       prints per-run and per-job results with failing steps, the tail of --log-failed of each failed run, downloads
#       each run's artifacts into <Harness>/tmp/623 with a copy in /private/tmp/graphtraj-623 (Windows
#       GraphTraj-windows-evidence-<sha>, macOS graphtraj-macos-adoption-evidence, Linux linux-desktop-<sha>, repair
#       GraphTraj-windows-x64-<sha> and GraphTraj-linux-amd64-<sha>), the next commands and the VERDICT last: PASS
#       only when all four runs succeed. Login: ssh key, gh login. Dialog: none (ssh may ask a key passphrase if the
#       agent has none). Network: GitHub. Up to ~60 min.
#   W   Observe only (no push, no re-run): `W` for the pushed branch head, `W <sha>` for that commit's four push runs,
#       `W <run-id>` for one run. Same waiting and output as P after the push. Login: gh login (ssh key for `W`
#       without argument: ls-remote). Dialog: none. Network: GitHub. Up to ~55 min.
#   X   `X <run-id>`: re-run the failed jobs of one completed, failed run of this branch (gh run rerun --failed), for
#       transient failures only. OUTWARD-FACING (starts GitHub Actions jobs). Waits for the new attempt to appear
#       (bounded 300 s) and complete (bounded 3000 s), prints results and downloads its artifacts into
#       <prefix>-<run-id>-a<attempt>. Login: gh login. Dialog: none. Network: GitHub. Up to ~55 min.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY623_REMOTE (push/ls-remote target instead of origin), VERIFY623_GH (a gh
# stand-in), VERIFY623_HTMP / VERIFY623_PTMP (download and copy roots), VERIFY623_APPEAR_S / _DONE_S / _POLL_S
# (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
STEP=${1:-}
BRANCH=agent/623-windows-desktop-adoption-green
# dev cb433644 (621 adoption-win.mjs port and task_register fix, 622 process_reclaim guard, 626 styling).
BASE=cb433644d9d0e1bb04469dd644927a1a77946b43
REPO=LUOXIAO92/graphtraj
GREPO=LUOXIAO92/graftling
GTAG=v0.10.2
GCOMMIT=57bca73657d3135a4504904fcc3f1898c2419766
HARNESS=${WT:h:h:h:h}
HTMP=${VERIFY623_HTMP:-$HARNESS/tmp/623}
PTMP=${VERIFY623_PTMP:-/private/tmp/graphtraj-623}
REMOTE=${VERIFY623_REMOTE:-origin}
GH=${VERIFY623_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY623_APPEAR_S:-300}
DONE_S=${VERIFY623_DONE_S:-3000}
POLL_S=${VERIFY623_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
FROZEN=(desktop/src desktop/electron src)
# The four workflows the push triggers (all changed by this Task).
WORKFLOWS=(.github/workflows/desktop-win-adoption.yml .github/workflows/desktop-macos-adoption.yml
  .github/workflows/desktop-linux-adoption.yml .github/workflows/desktop-repair-package.yml)
NWF=${#WORKFLOWS}
WFNAMES="desktop-win-adoption, desktop-macos-adoption, desktop-linux-adoption and desktop-repair-package"
# artifacts_for <workflow path> <sha>: the run's uploaded artifact names (repair uploads only its two packages).
artifacts_for() {
  case $1 in
    *desktop-win-adoption.yml) print -r -- GraphTraj-windows-evidence-$2 ;;
    *desktop-macos-adoption.yml) print -r -- graphtraj-macos-adoption-evidence ;;
    *desktop-linux-adoption.yml) print -r -- linux-desktop-$2 ;;
    *desktop-repair-package.yml) print -r -- GraphTraj-windows-x64-$2 GraphTraj-linux-amd64-$2 ;;
  esac
}
prefix_for() {
  case $1 in
    *desktop-win-adoption.yml) print -r -- win-evidence ;;
    *desktop-macos-adoption.yml) print -r -- mac-evidence ;;
    *desktop-linux-adoption.yml) print -r -- linux-evidence ;;
    *) print -r -- repair-packages ;;
  esac
}

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
    TMPDIR=$PYTMP LANG=en_US.UTF-8 GH_PROMPT_DISABLED=1 $extra "$@"
}
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 623 $STEP: STOP"; exit 1; }
g() { allow $GIT -C $WT "$@"; }
hj() { allow $PY -I $HERE/ghjson.py "$@"; }
remote_sha() { allow $GIT -C $WT ls-remote $REMOTE refs/heads/$BRANCH | cut -f1; }
WORK=$(mktemp -d $PYTMP/verify623.XXXXXX)
trap 'rm -rf $WORK' EXIT

# api <file> <endpoint>: save a gh api response; on failure print the error and return 1.
api() {
  allow $GH api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}

# check_tag: PASS/FAIL line for graftling's tag (annotated or lightweight) resolving to GCOMMIT on GitHub.
check_tag() {
  local otype osha csha
  api $WORK/gref.json repos/$GREPO/git/ref/tags/$GTAG || { print -r -- "FAIL: cannot read tag $GTAG of $GREPO"; return 1; }
  otype=$(hj get $WORK/gref.json object.type); osha=$(hj get $WORK/gref.json object.sha)
  if [[ $otype == tag ]]; then
    api $WORK/gtag.json repos/$GREPO/git/tags/$osha || { print -r -- "FAIL: cannot read tag object $osha of $GREPO"; return 1; }
    csha=$(hj get $WORK/gtag.json object.sha)
  else
    csha=$osha
  fi
  if [[ $csha == $GCOMMIT ]]; then
    print -r -- "PASS: $GREPO tag $GTAG ($otype) -> commit $csha"; return 0
  fi
  print -r -- "FAIL: $GREPO tag $GTAG ($otype) -> ${csha:-nothing}, expected $GCOMMIT (the workflows would check out another graftling)"
  return 1
}

# check_tree: prints one PASS/FAIL line per local P precondition; returns the number of FAILs.
check_tree() {
  local cur=$(g rev-parse --abbrev-ref HEAD) bad=0 changed wf
  [[ $cur == $BRANCH ]] && print -r -- "PASS: on $BRANCH" || { print -r -- "FAIL: current branch is $cur, not $BRANCH (git -C $WT switch $BRANCH)"; (( bad++ )); }
  [[ -z $(g status --porcelain --untracked-files=no) ]] && print -r -- "PASS: tracked tree clean" \
    || { print -r -- "FAIL: tracked changes in $WT (git -C $WT status)"; (( bad++ )); }
  if g merge-base --is-ancestor $BASE HEAD 2> /dev/null; then
    print -r -- "PASS: base ${BASE[1,8]} is an ancestor of HEAD"
  else
    print -r -- "FAIL: base ${BASE[1,8]} is not an ancestor of HEAD"; (( bad++ ))
  fi
  changed=$(g diff --name-only $BASE HEAD -- $FROZEN 2> /dev/null)
  [[ -z $changed ]] && print -r -- "PASS: nothing changed since base under ${FROZEN}" \
    || { print -r -- "FAIL: changed since base under ${FROZEN}:"; print -r -- $changed | sed 's/^/  /'; (( bad++ )); }
  g diff --quiet $BASE HEAD -- desktop/tests/adoption-win.mjs 2> /dev/null \
    && print -r -- "INFO: desktop/tests/adoption-win.mjs unchanged since base" \
    || print -r -- "INFO: desktop/tests/adoption-win.mjs changed since base"
  # Under .github/workflows exactly the four files change, each only in Task 623's allowed lines (ghjson wfcheck).
  local -a wfchanged=("${(@f)$(g diff --name-only $BASE HEAD -- .github/workflows 2> /dev/null)}")
  wfchanged=(${wfchanged:#})
  if [[ ${(j: :)${(o)wfchanged}} != ${(j: :)${(o)WORKFLOWS}} ]]; then
    print -r -- "FAIL: workflow files changed since base must be exactly ${WORKFLOWS}; saw: ${wfchanged:-none}"; (( bad++ ))
  else
    for wf in $WORKFLOWS; do
      g show $BASE:$wf > $WORK/wf-base.yml && g show HEAD:$wf > $WORK/wf-head.yml || { print -r -- "FAIL: cannot read $wf"; (( bad++ )); continue; }
      if hj wfcheck $WORK/wf-base.yml $WORK/wf-head.yml $BRANCH $wf > $WORK/wfcheck.txt; then
        print -r -- "PASS: $wf: $(<$WORK/wfcheck.txt)"
      else
        print -r -- "FAIL: $wf:"; sed 's/^/  /' $WORK/wfcheck.txt; (( bad++ ))
      fi
    done
  fi
  return $bad
}

# fetch_one <run-id> <artifact> <dir under HTMP/PTMP>: download (unless present), copy for team sandboxes, summarise.
fetch_one() {
  local rid=$1 name=$2 sub=$3
  local dest=$HTMP/$sub copy=$PTMP/$sub
  mkdir -p ${dest:h} ${copy:h}
  if [[ -d $dest && -n $(ls -A $dest) ]]; then
    print -r -- "already present, not downloaded again: $dest"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dest"
    allow $GH run download $rid --repo $REPO -n $name -D $dest 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || { print -r -- "FAIL: download of $name from run $rid failed"; return 1; }
  fi
  if [[ -d $copy && -n $(ls -A $copy) ]]; then
    print -r -- "copy already present: $copy"
  else
    mkdir -p $copy && cp -R $dest/. $copy/ || { print -r -- "FAIL: copy to $copy failed"; return 1; }
    print -r -- "copied to: $copy"
  fi
  print -r -- "--- files (bytes, path under $dest)"
  hj evidence $dest
  return 0
}

# fetch_run <run-id> <workflow path> <sha> [suffix]: every artifact of that run; returns 1 when one failed.
fetch_run() {
  local rid=$1 wf=$2 sha=$3 sfx=${4:-} name bad=0
  local -a names=(${=$(artifacts_for $wf $sha)})
  local pre=$(prefix_for $wf)
  (( ${#names} )) || { print -r -- "FAIL: no artifact name known for $wf"; return 1; }
  for name in $names; do
    if [[ $pre == repair-packages ]]; then fetch_one $rid $name $pre-$rid$sfx/$name || bad=1
    else fetch_one $rid $name $pre-$rid$sfx || bad=1; fi
  done
  return $bad
}

# wait_run <run-id> <label> [suffix]: wait for completion, print results, fetch artifacts; ends with the VERDICT.
wait_run() {
  local rid=$1 label=$2 sfx=${3:-} start=$SECONDS rstate= concl= url= prev= line evid=ok wf sha
  print -r -- "waiting for run $rid (completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    if api $WORK/run.json repos/$REPO/actions/runs/$rid; then
      rstate=$(hj get $WORK/run.json status); concl=$(hj get $WORK/run.json conclusion); url=$(hj get $WORK/run.json html_url)
    fi
    line="${rstate:-unknown} ${concl:--}"
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] run $rid: $line"; prev=$line
    [[ $rstate == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "completion timeout after $((SECONDS - start))s (run still ${rstate:-unknown})"
      print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
      print -r -- "VERDICT 623 $label: FAIL (run $rid not completed within ${DONE_S}s; $url)"
      exit 1
    fi
    sleep $POLL_S
  done
  wf=$(hj get $WORK/run.json path); sha=$(hj get $WORK/run.json head_sha)
  print -r -- "--- run $rid | ${wf:t} | attempt $(hj get $WORK/run.json run_attempt) | $rstate | $concl | head $sha | $url"
  api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/jobs?per_page=100" && hj jobs $WORK/jobs.json
  if [[ $concl != success ]]; then
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 60
  fi
  print -r -- "--- artifacts of run $rid"
  fetch_run $rid $wf $sha $sfx || evid=failed
  print -r -- "next: zsh $THIS W $rid    (observe again; no push, no re-run)"
  print -r -- "next: zsh $THIS W $sha    (all four push runs of that commit; no push)"
  [[ $concl != success ]] && print -r -- "next: zsh $THIS X $rid    (re-run its failed jobs; only if the failure is transient)"
  [[ $concl != success ]] && print -r -- "next: after a committed correction, zsh $THIS 00 then zsh $THIS P"
  [[ $concl == success ]] && { print -r -- "VERDICT 623 $label: PASS (run $rid ${wf:t} success; artifacts $evid; $url)"; exit 0; }
  print -r -- "VERDICT 623 $label: FAIL (run $rid ${wf:t} $concl; artifacts $evid; $url)"; exit 1
}

# observe_push <sha> <label>: wait for the push runs of all four workflows for sha, print results, fetch their
# artifacts; ends with the VERDICT (PASS only when all four succeeded).
observe_push() {
  local sha=$1 label=$2 start=$SECONDS line prev= ok=0 rid wf concl evid
  local -a rows missing others failed notes
  local runs_api="repos/$REPO/actions/runs?head_sha=$sha&per_page=100"
  summ() {
    if api $WORK/runs.json $runs_api; then rows=("${(@f)$(hj pushruns $WORK/runs.json $WORKFLOWS)}")
    else rows=(${WORKFLOWS/#/MISSING$'\t'}); fi
    missing=(${(M)rows:#MISSING*}); others=(${(M)rows:#OTHER*})
  }
  print -r -- "observing push runs of $WFNAMES for $sha (appearance bound ${APPEAR_S}s, completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    summ
    (( ${#missing} == 0 )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s; present:"; print -lr -- ${(M)rows:#RUN*} | sed 's/^/  /'
      print -r -- "missing:"; print -lr -- $missing | sed 's/^/  /'
      (( ${#others} )) && { print -r -- "other workflows for this SHA:"; print -lr -- $others | sed 's/^/  /'; }
      print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
      print -r -- "VERDICT 623 $label: FAIL (0/$NWF success; ${#missing} of $NWF workflows never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "all $NWF push runs present after $((SECONDS - start))s"
  start=$SECONDS
  while true; do
    line=$(print -lr -- ${(M)rows:#RUN*} | cut -f2,4,5 | sed 's|^\.github/workflows/||' | tr '\t\n' ' ;')
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] $line"; prev=$line
    (( ${#missing} == 0 )) && [[ -z $(print -lr -- ${(M)rows:#RUN*} | cut -f4 | grep -v '^completed$') ]] && break
    if (( SECONDS - start >= DONE_S )); then print -r -- "completion timeout after $((SECONDS - start))s"; break; fi
    sleep $POLL_S; summ
  done
  print -r -- "--- results for $sha"
  for line in ${(M)rows:#RUN*}; do
    local -a f=("${(@ps:\t:)line}")
    wf=$f[2]; rid=$f[3]; concl=$f[5]
    print -r -- "RUN ${wf:t} | id $rid | ${f[4]} | $concl | ${f[6]}"
    api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/jobs?per_page=100" && hj jobs $WORK/jobs.json
    if [[ ${f[4]} == completed && $concl == success ]]; then (( ok++ )); else failed+=$rid; fi
  done
  (( ${#others} )) && { print -r -- "OTHER workflows triggered for this SHA:"; print -lr -- $others | sed 's/^/  /'; } \
    || print -r -- "no other workflow triggered for this SHA"
  for rid in $failed; do
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 60
  done
  for line in ${(M)rows:#RUN*}; do
    local -a f=("${(@ps:\t:)line}")
    wf=$f[2]; rid=$f[3]
    [[ $f[4] == completed ]] || { notes+="${wf:t} artifacts not fetched (run not completed)"; continue; }
    print -r -- "--- artifacts of ${wf:t} run $rid"
    fetch_run $rid $wf $sha && evid=ok || evid=failed
    notes+="${wf:t} ${f[5]}, artifacts $evid"
  done
  print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
  for rid in $failed; do print -r -- "next: zsh $THIS X $rid    (re-run its failed jobs; only if the failure is transient)"; done
  (( ok == NWF )) && { print -r -- "VERDICT 623 $label: PASS ($ok/$NWF success; ${(j:; :)notes})"; exit 0; }
  print -r -- "VERDICT 623 $label: FAIL ($ok/$NWF success; ${(j:; :)notes})"; exit 1
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: your gh login (account shown, no token) and ssh key (git ls-remote). Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
  local url=$(g remote get-url origin)
  [[ $url == (git@github.com:|https://github.com/|ssh://git@github.com/)$REPO(.git|) ]] && print -r -- "PASS: origin is $url" \
    || stop "origin is $url, not $REPO"
  [[ $REMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $REMOTE is used instead of origin for ls-remote/push"
  local cur=$(g rev-parse --abbrev-ref HEAD) head=$(g rev-parse HEAD) rsha=$(remote_sha) remote_state
  print -r -- "current branch: $cur | HEAD $head"
  if [[ -z $rsha ]]; then
    remote_state=absent; print -r -- "PASS: $BRANCH is absent on $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then
    remote_state=equal; print -r -- "PASS: $REMOTE already has $BRANCH at HEAD (no push needed; W observes)"
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then
    remote_state=ancestor; print -r -- "PASS: $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else
    stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force. Inspect: git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"
  fi
  print -r -- "--- P preconditions"
  local ready=yes; check_tree || ready=no
  check_tag || ready=no
  if [[ $ready == yes && $remote_state == equal ]]; then
    print -r -- "next: zsh $THIS W    (observes the four push runs of the already pushed HEAD; no push)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $THIS P    (pushes $BRANCH; the push starts the four desktop workflows; waits for all four)"
  else
    print -r -- "next: fix the FAIL lines above, then zsh $THIS 00"
  fi
  print -r -- "VERDICT 623 00: PASS (P ready: $ready; remote branch $remote_state; candidate $head)"
  ;;
P)
  say "[P] Push and wait. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force); the push starts $WFNAMES. Login: ssh key, gh login. Dialog: none. Network: GitHub."
  check_tree || stop "HEAD does not meet the preconditions above; run: zsh $THIS 00"
  check_tag || stop "graftling tag check failed; nothing pushed. Run: zsh $THIS 00"
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  [[ $rsha == $head ]] && stop "$REMOTE already has $BRANCH at $head; observe with: zsh $THIS W"
  [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null || stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD; never force. Run: zsh $THIS 00"
  print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head)"
  g push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "push failed; nothing was forced. Run: zsh $THIS 00"
  [[ $(remote_sha) == $head ]] || stop "$REMOTE does not show $BRANCH at $head; run: zsh $THIS 00"
  print -r -- "PASS: $REMOTE $BRANCH = $head"
  observe_push $head P
  ;;
W)
  # W [sha]: the four push runs of the pushed head (or sha). W <run-id>: one run.
  local target=${2:-}
  if [[ $target != [0-9a-f](#c40) && $target == <-> ]]; then
    say "[W] Observe only (no push, no re-run) run $target. Login: gh login. Dialog: none. Network: GitHub."
    wait_run $target W
  fi
  [[ -z $target || $target == [0-9a-f](#c40) ]] || stop "usage: zsh $THIS W [<40-hex sha> | <run-id>]"
  [[ -n $target ]] || target=$(remote_sha)
  say "[W] Observe only (no push, no re-run) the push runs of ${target:-<none>}. Login: gh login, ssh key (ls-remote). Dialog: none. Network: GitHub."
  [[ -n $target ]] || stop "$BRANCH is not on $REMOTE; run: zsh $THIS 00"
  [[ $target == $(g rev-parse HEAD) ]] || print -r -- "NOTE: observed SHA $target differs from local HEAD $(g rev-parse HEAD)"
  observe_push $target W
  ;;
X)
  local rid=${2:-} before after rbranch wf rconcl rstate start
  [[ $rid == <-> ]] || stop "usage: zsh $THIS X <run-id>"
  say "[X] Re-run failed jobs of run $rid. OUTWARD-FACING: gh run rerun $rid --failed starts GitHub Actions jobs. Login: gh login. Dialog: none. Network: GitHub."
  api $WORK/run.json repos/$REPO/actions/runs/$rid || stop "cannot read run $rid; nothing re-run"
  rbranch=$(hj get $WORK/run.json head_branch); wf=$(hj get $WORK/run.json path)
  rstate=$(hj get $WORK/run.json status); rconcl=$(hj get $WORK/run.json conclusion); before=$(hj get $WORK/run.json run_attempt)
  print -r -- "run $rid: ${wf:t} | branch $rbranch | attempt $before | $rstate | ${rconcl:--}"
  [[ $rbranch == $BRANCH ]] || stop "run $rid is on $rbranch, not $BRANCH; nothing re-run"
  (( ${WORKFLOWS[(Ie)$wf]} )) || stop "run $rid is $wf, not one of the four desktop workflows; nothing re-run"
  [[ $rstate == completed ]] || stop "run $rid is still $rstate; observe it with: zsh $THIS W $rid"
  [[ $rconcl == success ]] && stop "run $rid already succeeded; nothing to re-run"
  print -r -- "\$ gh run rerun $rid --repo $REPO --failed"
  allow $GH run rerun $rid --repo $REPO --failed 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh run rerun failed; run: zsh $THIS W $rid"
  print -r -- "waiting for attempt > $before to appear (bound ${APPEAR_S}s, poll ${POLL_S}s)"
  start=$SECONDS
  while true; do
    if api $WORK/run.json repos/$REPO/actions/runs/$rid; then after=$(hj get $WORK/run.json run_attempt); fi
    (( ${after:-0} > before )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "next: zsh $THIS W $rid    (observe; no re-run)"
      print -r -- "VERDICT 623 X: FAIL (re-run requested, but attempt $before is still the latest after ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "attempt $after appeared after $((SECONDS - start))s"
  wait_run $rid X -a$after
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|W [sha|run-id]|X <run-id>"; exit 2 ;;
esac
