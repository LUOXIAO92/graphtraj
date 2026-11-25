#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 622 Main-run steps: show that a GitHub Actions run of desktop-win-adoption.yml whose commit holds the 622 guard
# (tests/process_reclaim.py skips the process reclaim on Windows) no longer logs the libproc.dylib noise.
# Modelled on verify-618/steps.zsh (00, P, check_tree, remote_sha, observe).
#
# LOGIN: the user's own logins only. git push / ls-remote use the user's ssh key (SSH_AUTH_SOCK, passed to those two
# commands only); gh uses its stored login (gh auth status shows the account; no token is printed). GH_TOKEN/
# GITHUB_TOKEN and every other credential-class variable are removed at start, so gh cannot use a token from the
# environment.
# REAL ENTRY: `git push origin agent/622-process-reclaim-windows-noise` starts desktop-win-adoption.yml (its push branch
# list names this branch; no other workflow does), and the run's log of step 'Build desktop and check Windows native
# settings' (the step that runs pytest on the Windows runner) is checked.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00        Preflight, read only. zsh; git and gh versions; gh auth status (token lines removed); origin is
#             LUOXIAO92/graphtraj; current branch is the Task branch, tracked tree clean, HEAD holds the guard and the
#             trigger line; strict YAML of every workflow and which of them a push of the branch starts (only
#             desktop-win-adoption); remote branch state (absent / ancestor -> next P; equal -> next O; diverged ->
#             STOP). Login: gh login, ssh key (ls-remote). Dialog: none. Network: GitHub. ~5 s.
#   P         Push and observe. OUTWARD-FACING: publishes the branch to GitHub (fast-forward only, never force). Then,
#             in this process: waits for the desktop-win-adoption.yml run of exactly HEAD's sha to appear (bounded ~5
#             min; else VERDICT PENDING with the next O command), prints other workflows triggered, and continues as O
#             with that run. Expect the run itself to fail at the graftling import (619); only the noise matters.
#             Login: ssh key, gh login. Dialog: none (ssh may ask a key passphrase if the agent has none).
#             Network: GitHub. Up to ~45 min.
#   O [ref]   Observe, read only. ref: a run id, a 40-hex commit sha (its desktop-win-adoption run), or none: the
#             newest of the latest 30 desktop-win-adoption.yml runs whose commit's tests/process_reclaim.py (contents
#             API, so a rebased or merged commit counts) holds the guard; none -> PENDING. Waits until the run
#             completes (poll 30 s, bound ~40 min), reads `gh run view <id> --log` and checks: (a) the pytest step
#             logged a final summary line (proves pytest_sessionfinish ran); (b) no line contains 'libproc' or
#             'leftover test processes'. The run's own conclusion is informational (it may fail for 619-621 reasons).
#             Login: gh login. Dialog: none. Network: GitHub. Up to ~41 min.
# Last line of P and O: VERDICT 622 <step>: PASS (exit 0) / FAIL (1) / PENDING (3) / INCONCLUSIVE (4); STOP exits 1.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set GH_CONFIG_DIR, XDG_CONFIG_HOME
# (where gh finds the user's own login); allow_ssh() adds SSH_AUTH_SOCK for git push and ls-remote only.
# No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY622_REMOTE (push/ls-remote target instead of origin), VERIFY622_GH (a gh
# stand-in), VERIFY622_APPEAR_S / _DONE_S / _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
STEP=${1:-}
BRANCH=agent/622-process-reclaim-windows-noise
REPO=LUOXIAO92/graphtraj
REMOTE=${VERIFY622_REMOTE:-origin}
WORKFLOW=desktop-win-adoption.yml
PYTEST_STEP='Build desktop and check Windows native settings'
GUARD_FILE=tests/process_reclaim.py
GH=${VERIFY622_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY622_APPEAR_S:-300}
DONE_S=${VERIFY622_DONE_S:-2400}
POLL_S=${VERIFY622_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}

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
  [[ -n ${GH_CONFIG_DIR:-} ]] && extra+=GH_CONFIG_DIR=$GH_CONFIG_DIR
  [[ -n ${XDG_CONFIG_HOME:-} ]] && extra+=XDG_CONFIG_HOME=$XDG_CONFIG_HOME
  /usr/bin/env -i HOME=$HOME USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=$PYTMP LANG=en_US.UTF-8 GH_PROMPT_DISABLED=1 $extra "$@"
}
allow_ssh() {  # git push and ls-remote only: the user's ssh agent as well
  if [[ -n ${SSH_AUTH_SOCK:-} ]]; then allow SSH_AUTH_SOCK=$SSH_AUTH_SOCK "$@"; else allow "$@"; fi
}
stop() { print -r -- "STOP: $*"; exit 1; }
g() { allow $GIT -C $WT "$@"; }
work=$(mktemp -d $PYTMP/verify622.XXXXXX)
trap 'rm -rf $work' EXIT

# The guard, as 00/P (local HEAD) and O (a run's commit) recognise it.
PYGUARD='import base64, json, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
if sys.argv[2] == "api":
    try: text = base64.b64decode(json.loads(text).get("content", "")).decode("utf-8", "replace")
    except ValueError: text = ""
sys.exit(0 if "def reclaim_supported()" in text and "if not reclaim_supported():" in text else 1)'
# A runs response, newest first: RUN (desktop-win-adoption) or OTHER, id, head_sha, status, conclusion, url, path.
PYRUNS='import json, sys
runs = json.load(open(sys.argv[1])).get("workflow_runs", [])
for r in sorted(runs, key=lambda r: (r.get("created_at", ""), r["id"]), reverse=True):
    kind = "RUN" if r.get("path", "").split("@")[0].endswith("/" + sys.argv[2]) else "OTHER"
    print(kind, r["id"], r["head_sha"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), r.get("path"), sep="\t")'
PYRUN='import json, sys
r = json.load(open(sys.argv[1]))
print("RUN", r["id"], r["head_sha"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), r.get("path"), sep="\t")'
# Checks a `gh run view --log` file (job<TAB>step<TAB>timestamp text). Prints SUMMARY/OFFENDING/STEPLINES rows.
PYLOG='import re, sys
ansi = re.compile(r"(\x1b|\^\[)\[[0-9;]*m")
summary = re.compile(r" (passed|failed|errors?|no tests ran).* in [0-9.]+s")
step, steplines, found, bad = sys.argv[2], 0, [], []
for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = ansi.sub("", raw.rstrip("\n"))
    parts = line.split("\t", 2)
    if len(parts) == 3 and parts[1] == step:
        steplines += 1
        if summary.search(parts[2]): found.append(line)
    if "libproc" in line or "leftover test processes" in line: bad.append(line)
print("STEPLINES", steplines, sep="\t")
for line in found: print("SUMMARY", line, sep="\t")
for line in bad: print("OFFENDING", line, sep="\t")'

has_guard_at() {  # has_guard_at SHA: the commit's guard file, read through the contents API
  allow $GH api "repos/$REPO/contents/$GUARD_FILE?ref=$1" > $work/content.json 2> /dev/null || return 1
  allow $PY -I -c $PYGUARD $work/content.json api
}
check_tree() {  # branch, clean tracked tree, guard and trigger at HEAD, workflow triggers; prints the result lines
  local cur=$(g rev-parse --abbrev-ref HEAD) wf
  [[ $cur == $BRANCH ]] || stop "current branch is $cur, not $BRANCH; run: git -C $WT switch $BRANCH"
  [[ -z $(g status --porcelain --untracked-files=no) ]] || stop "tracked changes in $WT; commit them or inspect: git -C $WT status"
  g show HEAD:$GUARD_FILE > $work/guard.py 2> /dev/null || stop "$GUARD_FILE missing at HEAD"
  allow $PY -I -c $PYGUARD $work/guard.py file || stop "HEAD's $GUARD_FILE lacks the 622 guard"
  print -r -- "PASS: HEAD's $GUARD_FILE holds the guard (reclaim_supported; pytest_sessionfinish returns on Windows)"
  rm -rf $work/wf; mkdir $work/wf
  for wf in ${(f)"$(g ls-tree --name-only HEAD .github/workflows/)"}; do g show HEAD:$wf > $work/wf/${wf:t}; done
  print -r -- "\$ triggercheck.py $BRANCH <HEAD's .github/workflows/*>"
  allow $PY -I $WT/scripts/verify-622/triggercheck.py $BRANCH $work/wf/* | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "HEAD's workflow triggers are not: $WORKFLOW gains $BRANCH and no other workflow runs"
}
remote_sha() {  # sets rsha: the remote branch's commit, empty when absent
  local out
  out=$(allow_ssh $GIT -C $WT ls-remote $REMOTE refs/heads/$BRANCH) || stop "git ls-remote $REMOTE failed; check: git -C $WT ls-remote $REMOTE"
  rsha=${out%%$'\t'*}
}

observe() {  # observe RUNROW LABEL: wait for completion, check the log, end with the VERDICT
  local -a cols=("${(@ps:\t:)1}") checks summaries offending
  local label=$2 rid=${cols[2]} sha=${cols[3]} run_state=${cols[4]} conclusion=${cols[5]} url=${cols[6]} start=$SECONDS steplines
  print -r -- "chosen run: $rid | head $sha | $run_state | $url"
  [[ $run_state != completed ]] && print -r -- "waiting for run $rid to complete (poll ${POLL_S}s, bound ${DONE_S}s)"
  while [[ $run_state != completed ]]; do
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "run $rid still $run_state after $((SECONDS - start))s"
      print -r -- "next: zsh $THIS O $rid    (keeps waiting for this run; read only)"
      print -r -- "VERDICT 622 $label: PENDING (run $rid not completed within ${DONE_S}s)"
      exit 3
    fi
    sleep $POLL_S
    if allow $GH api "repos/$REPO/actions/runs/$rid" > $work/run.json 2> /dev/null; then
      cols=("${(@ps:\t:)$(allow $PY -I -c $PYRUN $work/run.json)}")
      [[ ${cols[4]} != $run_state ]] && print -r -- "  [$(date +%H:%M:%S)] $rid ${cols[4]}"
      run_state=${cols[4]}; conclusion=${cols[5]}
    fi
  done
  print -r -- "run $rid completed, conclusion $conclusion (informational; 619-621 failures do not affect 622)"
  print -r -- "\$ gh run view $rid --repo $REPO --log"
  allow $GH run view $rid --repo $REPO --log > $work/log.txt 2> $work/err || {
    print -r -- "gh run view failed: $(<$work/err)"
    print -r -- "next: zsh $THIS O $rid    (read only)"
    print -r -- "VERDICT 622 $label: INCONCLUSIVE (log of run $rid unavailable)"; exit 4; }
  print -r -- "log: $(wc -l < $work/log.txt | tr -d ' ') lines"
  checks=("${(@f)$(allow $PY -I -c $PYLOG $work/log.txt $PYTEST_STEP)}")
  summaries=(${(M)checks:#SUMMARY*}); offending=(${(M)checks:#OFFENDING*})
  steplines=${${(M)checks:#STEPLINES*}#STEPLINES$'\t'}
  print -r -- "lines of step '$PYTEST_STEP': $steplines"
  if (( ${#summaries} )); then
    print -r -- "pytest summary line(s) in that step:"; print -lr -- ${summaries#SUMMARY$'\t'} | sed 's/^/  /'
  else
    print -r -- "no pytest summary line in that step"
  fi
  if (( ${#offending} )); then
    print -r -- "offending line(s) (${#offending}; 'libproc' or 'leftover test processes'):"
    print -lr -- ${offending#OFFENDING$'\t'} | head -n 20 | sed 's/^/  /'
  else
    print -r -- "no line contains 'libproc' or 'leftover test processes'"
  fi
  print -r -- "next: zsh $THIS O $rid    (re-reads this run; read only)"
  if (( ${#offending} )); then
    print -r -- "VERDICT 622 $label: FAIL (run $rid at $sha logs the reclaim noise)"; exit 1
  elif (( ${#summaries} == 0 )); then
    print -r -- "VERDICT 622 $label: INCONCLUSIVE (no pytest summary in '$PYTEST_STEP' of run $rid)"; exit 4
  fi
  print -r -- "VERDICT 622 $label: PASS (run $rid at $sha: pytest finished, no libproc noise)"
}
runs_for_sha() {  # runs_for_sha SHA: sets rows (RUN for this workflow first, then OTHER) for exactly that commit
  rows=()
  allow $GH api "repos/$REPO/actions/runs?head_sha=$1&per_page=100" > $work/runs.json 2> $work/err \
    || { print -r -- "  gh api failed: $(<$work/err)"; return 0; }
  rows=("${(@f)$(allow $PY -I -c $PYRUNS $work/runs.json $WORKFLOW)}"); rows=(${rows:#})
}
print_others() {
  local -a others=(${(M)rows:#OTHER*})
  if (( ${#others} )); then
    print -r -- "OTHER workflows triggered for this sha:"; print -lr -- $others | cut -f2,4,5,6,7 | sed 's/^/  /'
  else
    print -r -- "no other workflow triggered for this sha"
  fi
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: your gh login (account shown, no token), ssh key (ls-remote). Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
  origin_url=$(g remote get-url origin)
  [[ $origin_url == (git@github.com:|https://github.com/|ssh://git@github.com/)$REPO(.git|) ]] \
    && print -r -- "PASS: origin is $origin_url" || stop "origin is $origin_url, not $REPO"
  [[ $REMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $REMOTE is used instead of origin for ls-remote/push"
  check_tree
  head=$(g rev-parse HEAD); remote_sha
  print -r -- "candidate: $head"
  if [[ -z $rsha ]]; then
    print -r -- "PASS: $BRANCH is absent on $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then
    print -r -- "PASS: $REMOTE already has $BRANCH at HEAD; nothing to push"
    print -r -- "next: zsh $THIS O $head    (observes that commit's run; read only)"
    print -r -- "VERDICT 622 00: PASS (candidate $head already on $REMOTE; next O)"
    exit 0
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then
    print -r -- "PASS: $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else
    stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force. Inspect: git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"
  fi
  print -r -- "next: zsh $THIS P    (OUTWARD-FACING: pushes $BRANCH to $REMOTE, then waits for the $WORKFLOW run)"
  print -r -- "VERDICT 622 00: PASS (candidate $head)"
  ;;
P)
  say "[P] Push and observe. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force). Login: ssh key, gh login. Dialog: none. Network: GitHub."
  check_tree
  head=$(g rev-parse HEAD); remote_sha
  [[ $rsha == $head ]] && stop "$REMOTE already has $BRANCH at $head; nothing to push. Run: zsh $THIS O $head"
  [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null \
    || stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; nothing was pushed, never force. Run: zsh $THIS 00"
  print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head; remote ${rsha:-absent})"
  allow_ssh $GIT -C $WT push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "push failed; nothing was forced. Run: zsh $THIS 00"
  remote_sha
  [[ $rsha == $head ]] || stop "after the push $REMOTE does not show $head; run: zsh $THIS 00"
  print -r -- "PASS: $REMOTE $BRANCH = $head"
  print -r -- "waiting for the $WORKFLOW run of $head to appear (poll ${POLL_S}s, bound ${APPEAR_S}s)"
  start=$SECONDS
  while true; do
    runs_for_sha $head
    run_rows=(${(M)rows:#RUN*})
    (( ${#run_rows} )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "no $WORKFLOW run for $head after $((SECONDS - start))s"
      print_others
      print -r -- "next: zsh $THIS O $head    (observes that commit's run once it appears; read only, no push)"
      print -r -- "VERDICT 622 P: PENDING (pushed; the $WORKFLOW run of $head did not appear within ${APPEAR_S}s)"
      exit 3
    fi
    sleep $POLL_S
  done
  print -r -- "$WORKFLOW run present after $((SECONDS - start))s"
  print_others
  observe "${run_rows[1]}" P
  ;;
O)
  want=${2:-}
  say "[O] Observe, read only, ${want:+$want of }$WORKFLOW on $REPO. Login: your gh login. Dialog: none. Network: GitHub."
  if [[ -z $want ]]; then
    allow $GH api "repos/$REPO/actions/workflows/$WORKFLOW/runs?per_page=30" > $work/runs.json 2> $work/err \
      || stop "gh api runs failed: $(<$work/err)"
    rows=("${(@f)$(allow $PY -I -c $PYRUNS $work/runs.json $WORKFLOW)}"); rows=(${rows:#})
    chosen=
    typeset -A seen
    print -r -- "runs checked, newest first (id | head sha | status | conclusion | guard):"
    for row in $rows; do
      cols=("${(@ps:\t:)row}")
      if (( ! ${+seen[${cols[3]}]} )); then
        has_guard_at ${cols[3]} && seen[${cols[3]}]=yes || seen[${cols[3]}]=no
      fi
      print -r -- "  ${cols[2]} | ${cols[3]} | ${cols[4]} | ${cols[5]} | guard ${seen[${cols[3]}]}"
      if [[ ${seen[${cols[3]}]} == yes ]]; then chosen=$row; break; fi
    done
    (( ${#rows} )) || print -r -- "  (no runs listed)"
    if [[ -z $chosen ]]; then
      print -r -- "next: zsh $THIS 00    (then P pushes this Task's branch and starts $WORKFLOW)"
      print -r -- "VERDICT 622 O: PENDING (no qualifying run yet among ${#rows} runs)"
      exit 3
    fi
  else
    if [[ $want == [0-9a-f](#c40) ]]; then
      runs_for_sha $want
      run_rows=(${(M)rows:#RUN*})
      print_others
      if (( ! ${#run_rows} )); then
        print -r -- "next: zsh $THIS O $want    (once the run of that commit appears)"
        print -r -- "VERDICT 622 O: PENDING (no $WORKFLOW run for $want yet)"
        exit 3
      fi
      chosen=${run_rows[1]}
    else
      allow $GH api "repos/$REPO/actions/runs/$want" > $work/run.json 2> $work/err || stop "gh api run $want failed: $(<$work/err)"
      chosen=$(allow $PY -I -c $PYRUN $work/run.json)
    fi
    cols=("${(@ps:\t:)chosen}")
    if ! has_guard_at ${cols[3]}; then
      print -r -- "run ${cols[2]} head ${cols[3]}: $GUARD_FILE lacks the 622 guard"
      print -r -- "next: zsh $THIS O    (picks the newest qualifying run)"
      print -r -- "VERDICT 622 O: PENDING (run ${cols[2]} is not of a commit holding the guard)"
      exit 3
    fi
  fi
  observe "$chosen" O
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|O [run-id|sha]"; exit 2 ;;
esac
