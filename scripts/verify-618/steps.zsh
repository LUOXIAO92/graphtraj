#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 618 Main-run steps: push this Task's branch so GitHub Actions runs the four desktop workflows that now pin
# graftling v0.10.1 (root layout), and wait for their results. Modelled on verify-615/steps.zsh.
#
# LOGIN: the user's own GitHub logins only. git push / ls-remote use the user's ssh key (SSH_AUTH_SOCK); gh uses
# its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN and every other
# credential-class variable are removed at start, so gh cannot use a token from the environment.
# REAL ENTRY: GitHub Actions runs started by `git push origin agent/618-desktop-workflows-graftling-ref`; the push
# trigger lists of the four workflows name that branch (and nothing else changed in their triggers).
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git and gh versions; gh auth status (account only); origin is LUOXIAO92/graphtraj;
#       current branch is the Task branch, tracked tree clean, HEAD holds the four changes; the remote branch is
#       absent or an ancestor of HEAD (else STOP). Login: gh login, ssh key. Dialog: none. Network: GitHub. ~5 s.
#   P   Push and wait. OUTWARD-FACING: publishes the branch to GitHub (fast-forward only, never force). Then waits
#       (this process) until runs of exactly the four workflow files appear for HEAD (bounded ~5 min) and all are
#       completed (bounded ~75 min, polling every 30 s). Prints per-run and per-job conclusion and URL, the tail of
#       --log-failed for failed runs, other workflows triggered, next commands, and the VERDICT last.
#       Login: ssh key, gh login. Dialog: none (no review dialog; ssh may ask a key passphrase if the agent has none).
#       Network: GitHub. Up to ~80 min.
#   W   Wait/observe only (no push), same output, for the pushed branch head (or the SHA given as 2nd argument):
#       re-observation after an interruption or a correction push. Login: gh login. Dialog: none. Network: GitHub.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY618_REMOTE (push/ls-remote target instead of origin), VERIFY618_GH (a gh
# stand-in), VERIFY618_APPEAR_S / _DONE_S / _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
STEP=${1:-}
BRANCH=agent/618-desktop-workflows-graftling-ref
REPO=LUOXIAO92/graphtraj
REMOTE=${VERIFY618_REMOTE:-origin}
GH=${VERIFY618_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY618_APPEAR_S:-300}
DONE_S=${VERIFY618_DONE_S:-4500}
POLL_S=${VERIFY618_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
WORKFLOWS=(.github/workflows/desktop-linux-adoption.yml .github/workflows/desktop-macos-adoption.yml
           .github/workflows/desktop-repair-package.yml .github/workflows/desktop-win-adoption.yml)

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
stop() { print -r -- "STOP: $*"; exit 1; }
g() { allow $GIT -C $WT "$@"; }

# Summarise a runs response: the newest run per wanted path, then other workflows.
PYSUM='import json, sys
doc = json.load(open(sys.argv[1])); wanted = sys.argv[2:]
latest = {}
for r in doc.get("workflow_runs", []):
    p = r.get("path", "")
    if p in wanted:
        if p not in latest or (r["id"], r.get("run_attempt", 1)) > (latest[p]["id"], latest[p].get("run_attempt", 1)):
            latest[p] = r
    else:
        print("OTHER", p, r["id"], r.get("event"), r.get("status"), r.get("conclusion"), r.get("html_url"), sep="\t")
for p in wanted:
    r = latest.get(p)
    if r: print("RUN", p, r["id"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), r.get("name"), sep="\t")
    else: print("MISSING", p, sep="\t")'
PYJOBS='import json, sys
for j in json.load(open(sys.argv[1])).get("jobs", []):
    print("    job:", j.get("name"), "|", j.get("status"), "|", j.get("conclusion"), "|", j.get("html_url"))'

check_tree() {  # branch, clean tracked tree, the four changes at HEAD; prints the result lines
  local cur=$(g rev-parse --abbrev-ref HEAD) wf body bad=0
  [[ $cur == $BRANCH ]] || stop "current branch is $cur, not $BRANCH; run: git -C $WT switch $BRANCH"
  [[ -z $(g status --porcelain --untracked-files=no) ]] || stop "tracked changes in $WT; commit them or inspect: git -C $WT status"
  for wf in $WORKFLOWS; do
    body=$(g show HEAD:$wf) || stop "$wf missing at HEAD"
    if [[ $body == *"GRAFTLING_REF: v0.10.1"* && $body == *"agent/618-desktop-workflows-graftling-ref"* && $body != *graftling/src/graftling[\'\"\ ]* && $body != *"v0.5.2"* ]]; then
      print -r -- "PASS: $wf pins v0.10.1, root layout, 618 trigger"
    else
      print -r -- "FAIL: $wf lacks v0.10.1 / 618 trigger or still installs or packages graftling/src/graftling"; bad=1
    fi
  done
  (( bad == 0 )) || stop "HEAD $(g rev-parse --short HEAD) does not hold the four changes"
}
remote_sha() { allow $GIT -C $WT ls-remote $REMOTE refs/heads/$BRANCH | cut -f1; }

observe() {  # observe SHA LABEL: waits for the four runs, prints results, ends with the VERDICT
  local sha=$1 label=$2 work=$(mktemp -d $PYTMP/verify618.XXXXXX) start=$SECONDS line prev= ok=0 n=0 rid
  local -a rows others missing failed
  local runs=$work/runs.json
  fetch() { allow $GH api "repos/$REPO/actions/runs?head_sha=$sha&per_page=100" > $runs 2> $work/err || { print -r -- "  gh api failed: $(<$work/err)"; print -r -- '{"workflow_runs":[]}' > $runs; } }
  summ() { rows=("${(@f)$(allow $PY -I -c $PYSUM $runs $WORKFLOWS)}"); missing=(${(M)rows:#MISSING*}); others=(${(M)rows:#OTHER*}); }
  print -r -- "observing runs for $sha on $REPO (appearance bound ${APPEAR_S}s, completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    fetch; summ
    (( ${#missing} == 0 )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s; present:"; print -lr -- ${(M)rows:#RUN*} | sed 's/^/  /'
      print -r -- "missing:"; print -lr -- $missing | sed 's/^/  /'
      (( ${#others} )) && { print -r -- "other workflows for this SHA:"; print -lr -- $others | sed 's/^/  /'; }
      print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
      print -r -- "next: $GH api 'repos/$REPO/actions/runs?head_sha=$sha&per_page=100' --jq '.workflow_runs[] | [.path, .status, .conclusion, .html_url] | @tsv'"
      rm -rf $work
      print -r -- "VERDICT 618 $label: FAIL (0/4 success; ${#missing} of 4 workflows never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "all four workflow runs present after $((SECONDS - start))s"
  start=$SECONDS
  while true; do
    line=$(print -lr -- ${(M)rows:#RUN*} | cut -f2,4,5 | tr '\t\n' ' ;')
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] $line"; prev=$line
    # Done when every wanted run is present (a failed fetch reads as missing) and completed.
    (( ${#missing} == 0 )) && [[ -z $(print -lr -- ${(M)rows:#RUN*} | cut -f4 | grep -v '^completed$') ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "completion timeout after $((SECONDS - start))s"; break
    fi
    sleep $POLL_S; fetch; summ
  done
  print -r -- "--- results for $sha"
  for line in ${(M)rows:#RUN*}; do
    local -a f=("${(@ps:\t:)line}")
    rid=$f[3]
    print -r -- "RUN ${f[2]} | id $rid | ${f[4]} | ${f[5]} | ${f[6]}"
    allow $GH api "repos/$REPO/actions/runs/$rid/jobs?per_page=100" > $work/jobs.json 2> /dev/null && allow $PY -I -c $PYJOBS $work/jobs.json
    if [[ ${f[4]} == completed && ${f[5]} == success ]]; then (( ok++ )); else failed+=$rid; fi
    (( n++ ))
  done
  (( ${#others} )) && { print -r -- "OTHER workflows triggered for this SHA:"; print -lr -- $others | sed 's/^/  /'; } \
    || print -r -- "no other workflow triggered for this SHA"
  for rid in $failed; do
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 40
  done
  rm -rf $work
  print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
  for rid in $failed; do print -r -- "next: $GH run rerun $rid --repo $REPO --failed    (only if the failure is transient; not run by this step)"; done
  (( ok == 4 )) && print -r -- "VERDICT 618 $label: PASS ($ok/4 success)" || { print -r -- "VERDICT 618 $label: FAIL ($ok/4 success)"; exit 1; }
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
  check_tree
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  if [[ -z $rsha ]]; then
    print -r -- "PASS: $BRANCH is absent on $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then
    print -r -- "next: zsh $THIS W $head"
    stop "$REMOTE already has $BRANCH at HEAD $head; nothing to push. Observe instead with the next command."
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then
    print -r -- "PASS: $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else
    stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force. Inspect: git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"
  fi
  print -r -- "candidate: $head"
  print -r -- "next: zsh $THIS P    (pushes $BRANCH to $REMOTE and waits for the four runs)"
  print -r -- "VERDICT 618 00: PASS (candidate $head)"
  ;;
P)
  say "[P] Push and wait. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force). Login: ssh key, gh login. Dialog: none. Network: GitHub."
  check_tree
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null || stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD; run: zsh $THIS 00"
  [[ $rsha == $head ]] && stop "$REMOTE already has $BRANCH at $head; run: zsh $THIS W $head"
  print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head)"
  g push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "push failed; nothing was forced. Run: zsh $THIS 00"
  [[ $(remote_sha) == $head ]] || stop "after the push $REMOTE does not show $head; run: zsh $THIS 00"
  print -r -- "PASS: $REMOTE $BRANCH = $head"
  observe $head P
  ;;
W)
  local sha=${2:-$(remote_sha)}
  say "[W] Observe only (no push) runs for ${sha:-<none>}. Login: gh login. Dialog: none. Network: GitHub."
  [[ -n $sha ]] || stop "$BRANCH is not on $REMOTE; run: zsh $THIS 00"
  [[ $sha == $(g rev-parse HEAD) ]] || print -r -- "NOTE: observed SHA $sha differs from local HEAD $(g rev-parse HEAD)"
  observe $sha W
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|W [sha]"; exit 2 ;;
esac
