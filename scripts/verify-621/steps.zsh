#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 621 Main-run steps: fetch the evidence of the failed macOS adoption run, then push this Task's branch and
# start desktop-macos-adoption (mode standard) on it by workflow_dispatch, and wait for the result. Modelled on
# verify-618/steps.zsh.
#
# LOGIN: the user's own GitHub logins only. git push / ls-remote use the user's ssh key (SSH_AUTH_SOCK); gh uses
# its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN and every other
# credential-class variable are removed at start, so gh cannot use a token from the environment.
# REAL ENTRY: no workflow's push trigger lists agent/621-macos-adoption-script-d-ui and this Task edits no workflow,
# so the run is started by `gh workflow run desktop-macos-adoption.yml --repo LUOXIAO92/graphtraj
# --ref agent/621-macos-adoption-script-d-ui -f mode=standard` after the push. GitHub runs the workflow file at that
# ref (unchanged by this Task since BASE); the default branch's copy must offer workflow_dispatch (checked by 00).
# Run one step at a time:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh, git and gh versions; gh auth status (account only); origin is LUOXIAO92/graphtraj;
#       the default branch's desktop-macos-adoption.yml offers workflow_dispatch with mode standard and the workflow
#       is active; run 45546698537 still lists its evidence artifact unexpired; current branch; the remote branch is
#       absent, equal to or an ancestor of HEAD (else STOP, never force); whether adoption.mjs changed since the base
#       (E only, or P ready). Login: gh login, ssh key. Dialog: none. Network: GitHub. ~10 s.
#   E   Evidence, read only on GitHub. Downloads artifact graphtraj-macos-adoption-evidence of run 45546698537 into
#       <Harness>/tmp/621/mac-evidence-45546698537 (skipped when already non-empty), copies it to
#       /private/tmp/graphtraj-621/mac-evidence-45546698537 (team sandboxes cannot read Harness tmp), lists the files
#       and summarises every evidence.json. Login: gh login. Dialog: none. Network: GitHub. ~30 s.
#   P   Push, dispatch and wait. OUTWARD-FACING: publishes the branch to GitHub (fast-forward only, never force) and
#       starts one workflow_dispatch run of desktop-macos-adoption.yml (mode standard) on it. Checks first: on the
#       Task branch, clean tracked tree, base an ancestor, adoption.mjs changed since the base, nothing changed under
#       .github/workflows desktop/src desktop/electron src. Then waits in this process for the new run of HEAD to
#       appear (bounded 300 s) and complete (bounded 2700 s, polling every 30 s); prints job and failing-step
#       conclusions, the tail of --log-failed on failure, downloads that run's evidence like E, the next commands and
#       the VERDICT last. Login: ssh key, gh login. Dialog: none (ssh may ask a key passphrase if the agent has
#       none). Network: GitHub. Up to ~55 min.
#   D   Dispatch and wait, without a push: as P when the remote branch already equals HEAD. OUTWARD-FACING (starts
#       a GitHub Actions run). Login: gh login, ssh key (ls-remote). Dialog: none. Network: GitHub. Up to ~55 min.
#   W   Observe only: `W <run-id>`, or `W` alone for the newest dispatched run of HEAD; same waiting and output as P
#       after the dispatch. Login: gh login. Dialog: none. Network: GitHub. Up to ~45 min.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY621_REMOTE (push/ls-remote target instead of origin), VERIFY621_GH (a gh
# stand-in), VERIFY621_HTMP / VERIFY621_PTMP (download and copy roots), VERIFY621_APPEAR_S / _DONE_S / _POLL_S
# (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
STEP=${1:-}
BRANCH=agent/621-macos-adoption-script-d-ui
# dev 4b71012c (618, 620, 622, 619) merged into the Task branch; it changed only Linux/Windows trigger lines.
BASE=4b71012cc36b15063576c86038cf36c383d5989b
REPO=LUOXIAO92/graphtraj
WF=desktop-macos-adoption.yml
FAILED_RUN=45546698537
ARTIFACT=graphtraj-macos-adoption-evidence
SCRIPT=desktop/tests/adoption.mjs
HARNESS=${WT:h:h:h:h}
HTMP=${VERIFY621_HTMP:-$HARNESS/tmp/621}
PTMP=${VERIFY621_PTMP:-/private/tmp/graphtraj-621}
REMOTE=${VERIFY621_REMOTE:-origin}
GH=${VERIFY621_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY621_APPEAR_S:-300}
DONE_S=${VERIFY621_DONE_S:-2700}
POLL_S=${VERIFY621_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
FROZEN=(.github/workflows desktop/src desktop/electron src)
RUNS_API="repos/$REPO/actions/workflows/$WF/runs?branch=$BRANCH&event=workflow_dispatch&per_page=30"

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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 621 $STEP: STOP"; exit 1; }
g() { allow $GIT -C $WT "$@"; }
hj() { allow $PY -I $HERE/ghjson.py "$@"; }
remote_sha() { allow $GIT -C $WT ls-remote $REMOTE refs/heads/$BRANCH | cut -f1; }
WORK=$(mktemp -d $PYTMP/verify621.XXXXXX)
trap 'rm -rf $WORK' EXIT

# api <file> <endpoint>: save a gh api response; on failure print the error and return 1.
api() {
  allow $GH api $2 > $1 2> $WORK/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$WORK/api-err)"; return 1
}

# check_tree: prints one PASS/FAIL line per P precondition; returns the number of FAILs.
check_tree() {
  local cur=$(g rev-parse --abbrev-ref HEAD) bad=0 changed
  [[ $cur == $BRANCH ]] && print -r -- "PASS: on $BRANCH" || { print -r -- "FAIL: current branch is $cur, not $BRANCH (git -C $WT switch $BRANCH)"; (( bad++ )); }
  [[ -z $(g status --porcelain --untracked-files=no) ]] && print -r -- "PASS: tracked tree clean" \
    || { print -r -- "FAIL: tracked changes in $WT (git -C $WT status)"; (( bad++ )); }
  if g merge-base --is-ancestor $BASE HEAD 2> /dev/null; then
    print -r -- "PASS: base ${BASE[1,8]} is an ancestor of HEAD"
  else
    print -r -- "FAIL: base ${BASE[1,8]} is not an ancestor of HEAD"; (( bad++ ))
  fi
  if g diff --quiet $BASE HEAD -- $SCRIPT 2> /dev/null; then
    print -r -- "FAIL: $SCRIPT unchanged since base (the fix is not committed yet)"; (( bad++ ))
  else
    print -r -- "PASS: $SCRIPT changed since base"
  fi
  changed=$(g diff --name-only $BASE HEAD -- $FROZEN 2> /dev/null)
  [[ -z $changed ]] && print -r -- "PASS: nothing changed since base under ${FROZEN}" \
    || { print -r -- "FAIL: changed since base under ${FROZEN}:"; print -r -- $changed | sed 's/^/  /'; (( bad++ )); }
  return $bad
}

# fetch_evidence <run-id>: download the run's evidence artifact (unless present), copy it for team sandboxes, summarise.
fetch_evidence() {
  local rid=$1 dest=$HTMP/mac-evidence-$1 copy=$PTMP/mac-evidence-$1
  mkdir -p $HTMP $PTMP
  if [[ -d $dest && -n $(ls -A $dest) ]]; then
    print -r -- "already present, not downloaded again: $dest"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $ARTIFACT -D $dest"
    allow $GH run download $rid --repo $REPO -n $ARTIFACT -D $dest 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || { print -r -- "FAIL: download of $ARTIFACT from run $rid failed"; return 1; }
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

# wait_run <run-id> <label>: wait for completion, print results, fetch evidence; ends with the VERDICT.
wait_run() {
  local rid=$1 label=$2 start=$SECONDS rstate= concl= url= prev= line evid=ok
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
      print -r -- "next: zsh $THIS W $rid    (observe again; no push, no dispatch)"
      print -r -- "VERDICT 621 $label: FAIL (run $rid not completed within ${DONE_S}s; $url)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "--- run $rid | $rstate | $concl | head $(hj get $WORK/run.json head_sha) | $url"
  api $WORK/jobs.json "repos/$REPO/actions/runs/$rid/jobs?per_page=100" && hj jobs $WORK/jobs.json
  if [[ $concl != success ]]; then
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 60
  fi
  print -r -- "--- evidence of run $rid"
  fetch_evidence $rid || evid=failed
  print -r -- "next: zsh $THIS W $rid    (observe again; no push, no dispatch)"
  [[ $concl != success ]] && print -r -- "next: after a committed correction, zsh $THIS 00 then zsh $THIS P"
  [[ $concl == success ]] && { print -r -- "VERDICT 621 $label: PASS (run $rid success; evidence download $evid; $url)"; exit 0; }
  print -r -- "VERDICT 621 $label: FAIL (run $rid $concl; evidence download $evid; $url)"; exit 1
}

# dispatch_and_wait <head> <label>: record existing dispatch runs, dispatch, find the new run of head, wait for it.
dispatch_and_wait() {
  local head=$1 label=$2 start rid= found
  local -a old
  api $WORK/before.json $RUNS_API || stop "cannot list existing dispatch runs, nothing dispatched; run: zsh $THIS D"
  old=(${=$(hj ids $WORK/before.json)})
  print -r -- "existing dispatch runs of $WF on $BRANCH: ${#old}"
  print -r -- "\$ gh workflow run $WF --repo $REPO --ref $BRANCH -f mode=standard"
  allow $GH workflow run $WF --repo $REPO --ref $BRANCH -f mode=standard 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh workflow run failed; run: zsh $THIS 00"
  print -r -- "waiting for the new run of $head to appear (bound ${APPEAR_S}s, poll ${POLL_S}s)"
  start=$SECONDS
  while true; do
    if api $WORK/after.json $RUNS_API; then
      found=$(hj newrun $WORK/after.json $head $old)
      [[ -n $found ]] && { rid=${found%%$'\t'*}; break; }
    fi
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s: no new dispatch run with head_sha $head"
      print -r -- "next: zsh $THIS W    (takes the newest dispatched run of HEAD once it appears; no dispatch)"
      print -r -- "next: $GH run list --repo $REPO --workflow $WF --branch $BRANCH --event workflow_dispatch"
      print -r -- "VERDICT 621 $label: FAIL (dispatched, but no run for $head appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "new run $rid appeared after $((SECONDS - start))s: ${found//$'\t'/ | }"
  wait_run $rid $label
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
  api $WORK/repo.json repos/$REPO || stop "cannot read repos/$REPO"
  local defb=$(hj get $WORK/repo.json default_branch)
  api $WORK/wf.json "repos/$REPO/contents/.github/workflows/$WF?ref=$defb" || stop "cannot read $WF on $defb"
  local dsp
  dsp=$(hj dispatch $WORK/wf.json) && print -r -- "PASS: $WF on default branch $defb: $dsp" \
    || stop "$WF on default branch $defb: $dsp; gh workflow run cannot dispatch it"
  api $WORK/wfstate.json repos/$REPO/actions/workflows/$WF || stop "cannot read workflow $WF"
  local wstate=$(hj get $WORK/wfstate.json state)
  [[ $wstate == active ]] && print -r -- "PASS: workflow $WF state $wstate" || stop "workflow $WF state is $wstate, not active"
  local localwf=$(g show HEAD:.github/workflows/$WF)
  [[ $localwf == *workflow_dispatch:* && $localwf == *"options: ["*standard* ]] && print -r -- "PASS: $WF at HEAD offers workflow_dispatch mode standard" \
    || stop "$WF at HEAD lacks workflow_dispatch with mode standard"
  local evstate=unavailable art
  if api $WORK/art.json repos/$REPO/actions/runs/$FAILED_RUN/artifacts; then
    art=$(hj artifact $WORK/art.json $ARTIFACT)
    if [[ $art == FOUND*expired=false* ]]; then evstate=available; print -r -- "PASS: run $FAILED_RUN artifact $ARTIFACT: ${art//$'\t'/ }"
    else print -r -- "FAIL: run $FAILED_RUN artifact $ARTIFACT: ${art//$'\t'/ } (E cannot download it)"; fi
  fi
  [[ -d $HTMP/mac-evidence-$FAILED_RUN && -n $(ls -A $HTMP/mac-evidence-$FAILED_RUN) ]] && print -r -- "NOTE: E already downloaded to $HTMP/mac-evidence-$FAILED_RUN"
  local cur=$(g rev-parse --abbrev-ref HEAD) head=$(g rev-parse HEAD) rsha=$(remote_sha) remote_state
  print -r -- "current branch: $cur | HEAD $head"
  if [[ -z $rsha ]]; then
    remote_state=absent; print -r -- "PASS: $BRANCH is absent on $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then
    remote_state=equal; print -r -- "PASS: $REMOTE already has $BRANCH at HEAD (no push needed; D dispatches)"
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then
    remote_state=ancestor; print -r -- "PASS: $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else
    stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force. Inspect: git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"
  fi
  print -r -- "--- P preconditions"
  local ready=yes; check_tree || ready=no
  [[ $evstate == available ]] && print -r -- "next: zsh $THIS E    (downloads the evidence of run $FAILED_RUN; read only)"
  if [[ $ready == yes && $remote_state == equal ]]; then
    print -r -- "next: zsh $THIS D    (dispatches on the already pushed HEAD and waits)"
  elif [[ $ready == yes ]]; then
    print -r -- "next: zsh $THIS P    (pushes $BRANCH, dispatches and waits)"
  fi
  print -r -- "VERDICT 621 00: PASS (E $evstate; P ready: $ready; remote branch $remote_state; candidate $head)"
  ;;
E)
  say "[E] Evidence of run $FAILED_RUN, read only on GitHub. Login: gh login. Dialog: none. Network: GitHub."
  fetch_evidence $FAILED_RUN || { print -r -- "next: zsh $THIS 00"; print -r -- "VERDICT 621 E: FAIL (evidence of $FAILED_RUN not available)"; exit 1; }
  print -r -- "VERDICT 621 E: PASS (evidence at $HTMP/mac-evidence-$FAILED_RUN and $PTMP/mac-evidence-$FAILED_RUN)"
  ;;
P|D)
  if [[ $STEP == P ]]; then
    say "[P] Push, dispatch and wait. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force) and gh workflow run $WF. Login: ssh key, gh login. Dialog: none. Network: GitHub."
  else
    say "[D] Dispatch and wait (no push). OUTWARD-FACING: gh workflow run $WF. Login: gh login, ssh key. Dialog: none. Network: GitHub."
  fi
  check_tree || stop "HEAD does not meet the preconditions above; run: zsh $THIS 00"
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  if [[ $STEP == P ]]; then
    [[ $rsha == $head ]] && stop "$REMOTE already has $BRANCH at $head; run: zsh $THIS D"
    [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null || stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD; never force. Run: zsh $THIS 00"
    print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head)"
    g push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || stop "push failed; nothing was forced. Run: zsh $THIS 00"
  fi
  [[ $(remote_sha) == $head ]] || stop "$REMOTE does not show $BRANCH at $head; run: zsh $THIS 00"
  print -r -- "PASS: $REMOTE $BRANCH = $head"
  dispatch_and_wait $head $STEP
  ;;
W)
  local rid=${2:-} head=$(g rev-parse HEAD) found
  say "[W] Observe only (no push, no dispatch) run ${rid:-<newest dispatch of $head>}. Login: gh login. Dialog: none. Network: GitHub."
  if [[ -z $rid ]]; then
    api $WORK/after.json $RUNS_API || stop "cannot list dispatch runs; run: zsh $THIS 00"
    found=$(hj newrun $WORK/after.json $head)
    [[ -n $found ]] || stop "no dispatch run of $WF on $BRANCH for HEAD $head; run: zsh $THIS 00"
    rid=${found%%$'\t'*}
  fi
  [[ $rid == <-> ]] || stop "run id $rid is not a number"
  wait_run $rid W
  ;;
*)
  print -r -- "usage: zsh $THIS 00|E|P|D|W [run-id]"; exit 2 ;;
esac
