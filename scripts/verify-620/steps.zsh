#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 620 Main-run steps: read run 45546698887's full log, then push this Task's branch so GitHub Actions runs
# desktop-linux-adoption with the fixed controlled Codex scenario, and wait for its result. Modelled on
# verify-618/steps.zsh.
#
# LOGIN: the user's own GitHub logins only. git push / ls-remote use the user's ssh key (SSH_AUTH_SOCK); gh uses
# its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN and every other
# credential-class variable are removed at start, so gh cannot use a token from the environment.
# REAL ENTRY: the GitHub Actions run started by `git push origin agent/620-linux-adoption-codex-fixture`; only
# .github/workflows/desktop-linux-adoption.yml lists that branch (one added trigger line, nothing else changed).
# Outputs: <Harness>/tmp/620/ (run logs). <Harness> is derived from the layout (git common dir's parent's parent,
# holding .graphtraj/core/worktrees/<this worktree>) and checked.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh, git and gh versions; gh auth status (account only); origin is LUOXIAO92/graphtraj;
#       current branch is the Task branch, tracked tree clean, HEAD holds the scenario fix and the trigger line; the
#       remote branch is absent or an ancestor of HEAD (else STOP); <Harness>/tmp/620 can be created.
#       Login: gh login, ssh key. Dialog: none. Network: GitHub (gh auth status, git ls-remote). ~5 s.
#   L   Read run 45546698887's full log, read only: gh run view 45546698887 --repo LUOXIAO92/graphtraj --log into
#       <Harness>/tmp/620/run-45546698887.log; prints byte and line counts and the (bounded) matches for the
#       cause. Login: gh login. Dialog: none. Network: GitHub (read). ~10 s.
#   P   Push and wait. OUTWARD-FACING: publishes the branch to GitHub (fast-forward only, never force). Then waits
#       (this process) until the desktop-linux-adoption run for HEAD appears (bounded ~5 min) and completes (bounded
#       ~30 min; the job timeout is 20 min), polling every 30 s. Prints run and job conclusion and URL, the tail of
#       --log-failed on failure, other workflows triggered for the SHA, saves the full run log to
#       <Harness>/tmp/620/run-<id>.log, then next commands and the VERDICT last.
#       Login: ssh key, gh login. Dialog: none (ssh may ask a key passphrase if the agent has none). Network: GitHub.
#       Up to ~35 min.
#   W   Wait/observe only (no push), same output, for the pushed branch head (or the SHA given as 2nd argument).
#       Login: gh login. Dialog: none. Network: GitHub (read).
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY620_REMOTE (push/ls-remote target instead of origin), VERIFY620_GH (a gh
# stand-in), VERIFY620_APPEAR_S / _DONE_S / _POLL_S (bounds), VERIFY620_OUT (output directory instead of
# <Harness>/tmp/620). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
STEP=${1:-}
BRANCH=agent/620-linux-adoption-codex-fixture
REPO=LUOXIAO92/graphtraj
OLD_RUN=45546698887
REMOTE=${VERIFY620_REMOTE:-origin}
GH=${VERIFY620_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY620_APPEAR_S:-300}
DONE_S=${VERIFY620_DONE_S:-1800}
POLL_S=${VERIFY620_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
WORKFLOW=.github/workflows/desktop-linux-adoption.yml
OTHER_WORKFLOWS=(.github/workflows/desktop-macos-adoption.yml .github/workflows/desktop-repair-package.yml
                 .github/workflows/desktop-win-adoption.yml)
COMMON=$(git -C $WT rev-parse --path-format=absolute --git-common-dir)
HARNESS=${COMMON:h:h}
OUT=${VERIFY620_OUT:-$HARNESS/tmp/620}

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
outdir() {  # the layout-derived output directory exists (created if needed) and is writable
  [[ -d $HARNESS/.graphtraj && $WT == $HARNESS/.graphtraj/core/worktrees/* ]] \
    || stop "derived Harness $HARNESS does not hold .graphtraj/core/worktrees/${WT:t}"
  mkdir -p $OUT 2> /dev/null && [[ -w $OUT ]] || stop "cannot create or write $OUT"
}

# Summarise a runs response: the newest run of the wanted path, then other workflows.
PYSUM='import json, sys
doc = json.load(open(sys.argv[1])); wanted = sys.argv[2]
latest = None
for r in doc.get("workflow_runs", []):
    if r.get("path", "") == wanted:
        if latest is None or (r["id"], r.get("run_attempt", 1)) > (latest["id"], latest.get("run_attempt", 1)):
            latest = r
    else:
        print("OTHER", r.get("path"), r["id"], r.get("event"), r.get("status"), r.get("conclusion"), r.get("html_url"), sep="\t")
if latest:
    r = latest
    print("RUN", wanted, r["id"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), r.get("name"), sep="\t")
else:
    print("MISSING", wanted, sep="\t")'
PYJOBS='import json, sys
for j in json.load(open(sys.argv[1])).get("jobs", []):
    print("    job:", j.get("name"), "|", j.get("status"), "|", j.get("conclusion"), "|", j.get("html_url"))'

check_tree() {  # branch, clean tracked tree, the fix and the single trigger at HEAD; prints the result lines
  local cur=$(g rev-parse --abbrev-ref HEAD) body wf
  [[ $cur == $BRANCH ]] || stop "current branch is $cur, not $BRANCH; run: git -C $WT switch $BRANCH"
  [[ -z $(g status --porcelain --untracked-files=no) ]] || stop "tracked changes in $WT; commit them or inspect: git -C $WT status"
  body=$(g show HEAD:tests/linux_adoption_runtime.py) || stop "tests/linux_adoption_runtime.py missing at HEAD"
  [[ $body == *"'codex-home/sessions/fake'"* && $body == *FAKE_CODEX_SESSION_ID* && $body != *LINUX_ADOPTION_ROLLOUT* ]] \
    && print -r -- "PASS: HEAD scenario reads the peer's rollout (codex-home beside the scenario, FAKE_CODEX_SESSION_ID)" \
    || stop "HEAD $(g rev-parse --short HEAD) lacks the scenario fix (still reads LINUX_ADOPTION_ROLLOUT / CODEX_HOME)"
  body=$(g show HEAD:$WORKFLOW) || stop "$WORKFLOW missing at HEAD"
  [[ ${(M)${(f)body}:#    branches: \[*} == *", $BRANCH]"* ]] && print -r -- "PASS: $WORKFLOW push branches list $BRANCH" \
    || stop "HEAD $WORKFLOW does not list $BRANCH in its push branches"
  for wf in $OTHER_WORKFLOWS; do
    [[ $(g show HEAD:$wf 2> /dev/null) != *$BRANCH* ]] || stop "$wf also lists $BRANCH; a push would trigger it too"
  done
  print -r -- "PASS: no other desktop workflow lists $BRANCH"
}
remote_sha() { allow $GIT -C $WT ls-remote $REMOTE refs/heads/$BRANCH | cut -f1; }

observe() {  # observe SHA LABEL: waits for the run, prints results, saves its log, ends with the VERDICT
  local sha=$1 label=$2 work=$(mktemp -d $PYTMP/verify620.XXXXXX) start=$SECONDS line prev= rid runstate concl url
  local -a rows others missing f
  local runs=$work/runs.json
  fetch() { allow $GH api "repos/$REPO/actions/runs?head_sha=$sha&per_page=100" > $runs 2> $work/err || { print -r -- "  gh api failed: $(<$work/err)"; print -r -- '{"workflow_runs":[]}' > $runs; } }
  summ() { rows=("${(@f)$(allow $PY -I -c $PYSUM $runs $WORKFLOW)}"); missing=(${(M)rows:#MISSING*}); others=(${(M)rows:#OTHER*}); }
  print -r -- "observing $WORKFLOW for $sha on $REPO (appearance bound ${APPEAR_S}s, completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    fetch; summ
    (( ${#missing} == 0 )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s: no $WORKFLOW run for $sha"
      (( ${#others} )) && { print -r -- "other workflows for this SHA:"; print -lr -- $others | sed 's/^/  /'; }
      rm -rf $work
      print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
      print -r -- "next: gh api 'repos/$REPO/actions/runs?head_sha=$sha&per_page=100' --jq '.workflow_runs[] | [.path, .status, .conclusion, .html_url] | @tsv'"
      print -r -- "VERDICT 620 $label: FAIL ($WORKFLOW never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "run present after $((SECONDS - start))s"
  start=$SECONDS
  while true; do
    line=$(print -lr -- ${(M)rows:#RUN*} | cut -f3,4,5 | tr '\t\n' ' ;')
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] $line"; prev=$line
    (( ${#missing} == 0 )) && [[ $(print -lr -- ${(M)rows:#RUN*} | cut -f4) == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "completion timeout after $((SECONDS - start))s"; break
    fi
    sleep $POLL_S; fetch; summ
  done
  line=${${(M)rows:#RUN*}[1]:-}
  [[ -n $line ]] || { rm -rf $work; print -r -- "next: zsh $THIS W $sha"; print -r -- "VERDICT 620 $label: FAIL (run disappeared from the listing)"; exit 1; }
  f=("${(@ps:\t:)line}"); rid=$f[3]; runstate=$f[4]; concl=$f[5]; url=$f[6]
  print -r -- "--- result for $sha"
  print -r -- "RUN $WORKFLOW | id $rid | $runstate | $concl | $url"
  allow $GH api "repos/$REPO/actions/runs/$rid/jobs?per_page=100" > $work/jobs.json 2> /dev/null && allow $PY -I -c $PYJOBS $work/jobs.json
  (( ${#others} )) && { print -r -- "OTHER workflows triggered for this SHA:"; print -lr -- $others | sed 's/^/  /'; } \
    || print -r -- "no other workflow triggered for this SHA"
  if [[ $runstate == completed ]]; then
    allow $GH run view $rid --repo $REPO --log > $OUT/run-$rid.log 2> $work/logerr \
      && print -r -- "full log: $OUT/run-$rid.log ($(wc -c < $OUT/run-$rid.log | tr -d ' ') bytes, $(wc -l < $OUT/run-$rid.log | tr -d ' ') lines)" \
      || print -r -- "full log not saved: $(<$work/logerr)"
  fi
  if [[ $runstate == completed && $concl != success ]]; then
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 60
  fi
  rm -rf $work
  print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
  print -r -- "next: gh run view $rid --repo $REPO --log > $OUT/run-$rid.log"
  [[ $runstate == completed && $concl != success ]] && print -r -- "next: gh run rerun $rid --repo $REPO --failed    (only if the failure is transient; not run by this step)"
  [[ $runstate == completed && $concl == success ]] && { print -r -- "VERDICT 620 $label: PASS (run $rid success, $url)"; return 0; }
  print -r -- "VERDICT 620 $label: FAIL (run $rid $runstate/$concl, $url)"; exit 1
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
  outdir; print -r -- "PASS: output directory $OUT (Harness $HARNESS)"
  print -r -- "candidate: $head"
  print -r -- "next: zsh $THIS L    (reads run $OLD_RUN's full log; read only)"
  print -r -- "VERDICT 620 00: PASS (candidate $head)"
  ;;
L)
  say "[L] Read run $OLD_RUN's full log, read only. Login: your gh login. Dialog: none. Network: GitHub (read)."
  outdir
  local log=$OUT/run-$OLD_RUN.log
  print -r -- "\$ gh run view $OLD_RUN --repo $REPO --log > $log"
  allow $GH run view $OLD_RUN --repo $REPO --log > $log 2> $log.err || stop "gh run view failed: $(<$log.err)"
  rm -f $log.err
  print -r -- "saved: $log ($(wc -c < $log | tr -d ' ') bytes, $(wc -l < $log | tr -d ' ') lines)"
  print -r -- "--- matches for Traceback|FileNotFoundError|scenario failed|rollout-|LINUX_ADOPTION (3 lines context, first 200 lines)"
  grep -n -E -C 3 'Traceback|FileNotFoundError|scenario failed|rollout-|LINUX_ADOPTION' $log | cut -c1-400 | head -n 200
  print -r -- "--- match count: $(grep -c -E 'Traceback|FileNotFoundError|scenario failed|rollout-|LINUX_ADOPTION' $log)"
  print -r -- "next: zsh $THIS P    (OUTWARD-FACING: pushes $BRANCH and waits for the run)"
  ;;
P)
  say "[P] Push and wait. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force). Login: ssh key, gh login. Dialog: none. Network: GitHub."
  check_tree; outdir
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
  say "[W] Observe only (no push) the run for ${sha:-<none>}. Login: gh login. Dialog: none. Network: GitHub (read)."
  [[ -n $sha ]] || stop "$BRANCH is not on $REMOTE; run: zsh $THIS 00"
  [[ $sha == $(g rev-parse HEAD) ]] || print -r -- "NOTE: observed SHA $sha differs from local HEAD $(g rev-parse HEAD)"
  outdir
  observe $sha W
  ;;
*)
  print -r -- "usage: zsh $THIS 00|L|P|W [sha]"; exit 2 ;;
esac
