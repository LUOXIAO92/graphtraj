#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 619 Main-run steps: publish the graftling Windows fix branch (from the bundle) to LUOXIAO92/graftling and this
# Task's GraphTraj branch to LUOXIAO92/graphtraj, so GitHub Actions runs "Windows desktop adoption 266"
# (.github/workflows/desktop-win-adoption.yml) with graftling checked out at the candidate SHA; wait for the run and
# judge it by the job's counted steps. Modelled on verify-618/steps.zsh.
#
# LOGIN: the user's own logins only. GraphTraj push / ls-remote use the user's ssh key (SSH_AUTH_SOCK); graftling
# push / ls-remote use https with the user's git credential helper (osxkeychain), as adopt-617 rp did; gh uses its
# stored login (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN and every other
# credential-class variable are removed at start, so neither gh nor git can use a token from the environment.
# REAL ENTRY: the GitHub Actions run of desktop-win-adoption.yml started by `git push origin
# agent/619-graftling-windows-import` (its push trigger lists that branch; on it the graftling checkout uses
# the full candidate SHA below instead of GRAFTLING_REF). graftling has no workflows: its push triggers nothing.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only. zsh; git and gh versions; gh auth status (account only); GraphTraj origin is
#       LUOXIAO92/graphtraj and <Harness>/graftling origin is https://github.com/LUOXIAO92/graftling.git; the bundle
#       verifies against <Harness>/graftling and its head equals the graftling SHA in the workflow at HEAD; the
#       workflow at HEAD triggers on the 619 branch and names every counted step; the GraphTraj branch is clean at
#       HEAD; on both remotes the 619 branch is absent or an ancestor (else STOP); in <Harness>/graftling the local
#       619 branch is absent or equal to the bundle head (else STOP, never overwrite).
#       Login: gh login, ssh key, git credential helper. Dialog: none. Network: GitHub. ~10 s.
#   P   Publish and wait. OUTWARD-FACING: (1) fetches the bundle into <Harness>/graftling as local branch
#       agent/619-graftling-windows-import (only if absent or equal); (2) pushes it to the graftling origin,
#       fast-forward only, never force, and verifies with ls-remote; (3) pushes the GraphTraj branch to origin the
#       same way; (4) waits in this process for the desktop-win-adoption run for HEAD (appearance bound ~5 min,
#       completion ~40 min, poll 30 s); (5) prints the run and job conclusions, EVERY step of the job with its
#       conclusion and whether it counts, the candidate SHA lines of the job log, the --log-failed tail on failure,
#       and any other workflow run for that SHA; (6) the VERDICT last.
#       Login: ssh key, git credential helper, gh login. Dialog: none. Network: GitHub. Up to ~45 min.
#   W   Observe only (no push), same output, for the SHA given as 2nd argument or the remote branch head.
#       Login: gh login. Dialog: none. Network: GitHub.
# VERDICT (P and W): PASS only when, in the windows-adoption job, every COUNTED step is present with conclusion
# success, the job log names the candidate graftling SHA, and no other step failed: every other step is success or
# skipped (setup-python/setup-node post steps run only on success(), so a failed UI step skips them), except the UI
# step (not counted: its adoption scripts target the pre-D UI, Tasks 620/621) and the always() upload steps.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set SSH_AUTH_SOCK,
# GH_CONFIG_DIR, XDG_CONFIG_HOME (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY619_REMOTE (GraphTraj push/ls-remote target instead of origin),
# VERIFY619_GRAFTLING (a scratch graftling clone instead of <Harness>/graftling), VERIFY619_GREMOTE (graftling
# push/ls-remote target instead of that clone's origin), VERIFY619_GH (a gh stand-in), VERIFY619_APPEAR_S /
# _DONE_S / _POLL_S (bounds). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
STEP=${1:-}
BRANCH=agent/619-graftling-windows-import
REPO=LUOXIAO92/graphtraj
GURL=https://github.com/LUOXIAO92/graftling.git
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY619_GRAFTLING:-$HARNESS/graftling}
REMOTE=${VERIFY619_REMOTE:-origin}
GREMOTE=${VERIFY619_GREMOTE:-origin}
GH=${VERIFY619_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
APPEAR_S=${VERIFY619_APPEAR_S:-300}
DONE_S=${VERIFY619_DONE_S:-2400}
POLL_S=${VERIFY619_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
WORKFLOW=.github/workflows/desktop-win-adoption.yml
BUNDLE=$WT/scripts/verify-619/graftling-619.bundle
# The job's steps that decide the verdict, by their exact `name:` in $WORKFLOW at HEAD.
COUNTED=("Check out graftling at the version GraphTraj declares"
         "Fail unless graftling's linked package documents are real"
         "Install pinned build dependencies"
         "Build desktop and check Windows native settings"
         "Package pinned runtime and application"
         "Install archive to persistent user directory")
UI_STEP="Exercise actual installed window and native dialogs"
UPLOADS=("Retain installation artifact" "Retain exact checks and native UI evidence")

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
stop() { print -r -- "STOP: $*"; exit 1; }
g() { allow $GIT -C $WT "$@"; }
gg() { allow $GIT -C $GRAFT "$@"; }

# Summarise a runs response: the newest run of $WORKFLOW, then other workflows.
PYSUM='import json, sys
doc = json.load(open(sys.argv[1])); wanted = sys.argv[2]
latest = None
for r in doc.get("workflow_runs", []):
    if r.get("path", "") == wanted:
        if latest is None or (r["id"], r.get("run_attempt", 1)) > (latest["id"], latest.get("run_attempt", 1)):
            latest = r
    else:
        print("OTHER", r.get("path"), r["id"], r.get("event"), r.get("status"), r.get("conclusion"), r.get("html_url"), sep="\t")
if latest: print("RUN", wanted, latest["id"], latest.get("status"), latest.get("conclusion") or "-", latest.get("html_url"), latest.get("name"), sep="\t")
else: print("MISSING", wanted, sep="\t")'
# Print every job and step; judge the counted steps. argv: jobs.json config.json; last line: JUDGE PASS|FAIL <reason>.
PYSTEPS='import json, sys
jobs = json.load(open(sys.argv[1])).get("jobs", []); cfg = json.load(open(sys.argv[2]))
counted, ui, uploads = cfg["counted"], cfg["ui"], set(cfg["uploads"])
problems = []
job = next((j for j in jobs if j.get("name") == "windows-adoption"), None)
for j in jobs:
    print("JOB", j.get("name"), "|", j.get("status"), "|", j.get("conclusion"), "|", j.get("html_url"))
    if j is not job:
        continue
    for s in j.get("steps", []):
        name, concl = s.get("name"), s.get("conclusion")
        if name in counted: mark = "COUNTED"
        elif name == ui: mark = "not counted (pre-D UI script, 620/621)"
        elif name in uploads: mark = "not counted (always() upload)"
        else: mark = "must not fail (success or skipped)"
        print("  step %2s | %-9s | %s | %s" % (s.get("number"), concl, name, mark))
        if name in counted or name == ui or name in uploads: continue
        if concl not in ("success", "skipped"): problems.append("step %r is %s" % (name, concl))
if job is None:
    problems.append("no windows-adoption job")
else:
    seen = {s.get("name"): s.get("conclusion") for s in job.get("steps", [])}
    for name in counted:
        if name not in seen: problems.append("counted step %r is missing" % name)
        elif seen[name] != "success": problems.append("counted step %r is %s" % (name, seen[name]))
    others = [n for n, c in seen.items() if c not in ("success", "skipped") and n not in uploads]
    if cfg["run_conclusion"] == "failure" and others == [ui]:
        print("NOTE: the run concluded failure only because the not-counted UI step %r is %s" % (ui, seen[ui]))
print("JUDGE", "FAIL" if problems else "PASS", "; ".join(problems) or "all %d counted steps success" % len(counted))'

bundle_head() { allow $GIT bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1; }
bundle_prereq() { gg bundle verify $BUNDLE 2>&1 | awk '/requires this ref/ {getline; print $1}'; }
workflow_sha() {  # the 40-hex graftling ref the workflow at HEAD uses on the 619 branch
  g show HEAD:$WORKFLOW | grep -o "github.ref_name == '$BRANCH' && '[0-9a-f]\{40\}'" | grep -o '[0-9a-f]\{40\}'
}
check_tree() {  # GraphTraj branch, clean tracked tree, workflow trigger, ref, counted step names
  local cur=$(g rev-parse --abbrev-ref HEAD) body name bad=0
  [[ $cur == $BRANCH ]] || stop "current branch is $cur, not $BRANCH; run: git -C $WT switch $BRANCH"
  [[ -z $(g status --porcelain --untracked-files=no) ]] || stop "tracked changes in $WT; commit them or inspect: git -C $WT status"
  body=$(g show HEAD:$WORKFLOW) || stop "$WORKFLOW missing at HEAD"
  [[ $body == *"branches: ["*"$BRANCH"*"]"* ]] && print -r -- "PASS: $WORKFLOW push trigger lists $BRANCH" || { print -r -- "FAIL: trigger lacks $BRANCH"; bad=1; }
  [[ $body == *"GRAFTLING_REF: v0.10.1"* ]] && print -r -- "PASS: GRAFTLING_REF stays v0.10.1 for other branches" || { print -r -- "FAIL: GRAFTLING_REF changed"; bad=1; }
  for name in $COUNTED $UI_STEP; do
    if print -r -- $body | grep -qxF -- "      - name: $name"; then print -r -- "PASS: step named: $name"
    else print -r -- "FAIL: no step named: $name"; bad=1; fi
  done
  (( bad == 0 )) || stop "HEAD $(g rev-parse --short HEAD) does not hold the 619 workflow change"
}
check_bundle() {  # bundle verifies against $GRAFT; head equals the workflow SHA; sets GSHA
  gg bundle verify $BUNDLE > /dev/null 2>&1 || { gg bundle verify $BUNDLE 2>&1 | sed 's/^/  /'; stop "the bundle does not verify against $GRAFT"; }
  GSHA=$(bundle_head); local wsha=$(workflow_sha)
  [[ -n $GSHA && $GSHA == $wsha ]] || stop "bundle head ${GSHA:-none} != workflow graftling SHA ${wsha:-none} at HEAD"
  print -r -- "PASS: bundle verifies against $GRAFT; head $GSHA (on $(bundle_prereq)) = workflow graftling SHA"
}
graft_local_ok() {  # the local 619 branch in $GRAFT is absent (0) or equal (1) to the bundle head; else STOP
  local lsha=$(gg rev-parse -q --verify refs/heads/$BRANCH)
  if [[ -z $lsha ]]; then print -r -- "PASS: $GRAFT has no local $BRANCH (P creates it from the bundle)"; return 0; fi
  [[ $lsha == $GSHA ]] || stop "$GRAFT has local $BRANCH at $lsha, not the bundle head $GSHA; never overwrite. Inspect: git -C $GRAFT log --oneline -3 $BRANCH"
  print -r -- "PASS: $GRAFT local $BRANCH = bundle head"; return 1
}
# The branch head on a remote, empty when absent, "ERR <text>" when ls-remote fails (checked() then STOPs).
ls_sha() { local out; out=$(allow $GIT -C $1 ls-remote $2 refs/heads/$BRANCH 2>&1) || { print -r -- "ERR $out"; return 0; }; print -r -- ${out%%$'\t'*}; }
checked() { [[ ${1:-} != ERR* ]] || stop "git ls-remote failed (nothing was pushed): ${1#ERR }"; }
remote_sha() { ls_sha $WT $REMOTE; }
gremote_sha() { ls_sha $GRAFT $GREMOTE; }
graft_remote_ok() {  # the graftling remote branch is absent, the bundle head, or an ancestor of the bundle's base
  local rsha=$(gremote_sha) base=$(bundle_prereq)
  checked $rsha
  if [[ -z $rsha ]]; then print -r -- "PASS: $BRANCH is absent on graftling $GREMOTE"
  elif [[ $rsha == $GSHA ]]; then print -r -- "PASS: graftling $GREMOTE already has $BRANCH at the bundle head"
  elif gg merge-base --is-ancestor $rsha $base 2> /dev/null; then print -r -- "PASS: graftling $GREMOTE has $BRANCH at $rsha, an ancestor (fast-forward)"
  else stop "graftling $GREMOTE has $BRANCH at $rsha, not an ancestor of the bundle head; never force. Inspect: git -C $GRAFT fetch $GREMOTE $BRANCH && git -C $GRAFT log --oneline -5 FETCH_HEAD"
  fi
}

observe() {  # observe SHA LABEL: waits for the run, prints results, ends with the VERDICT
  local sha=$1 label=$2 work=$(mktemp -d $PYTMP/verify619.XXXXXX) start=$SECONDS line prev= rid jid judge hits runline
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
      print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
      print -r -- "next: $GH api 'repos/$REPO/actions/runs?head_sha=$sha&per_page=100' --jq '.workflow_runs[] | [.path, .status, .conclusion, .html_url] | @tsv'"
      rm -rf $work
      print -r -- "VERDICT 619 $label: FAIL (the desktop-win-adoption run never appeared within ${APPEAR_S}s)"
      exit 1
    fi
    sleep $POLL_S
  done
  print -r -- "run present after $((SECONDS - start))s"
  start=$SECONDS
  while true; do
    line=$(print -lr -- ${(M)rows:#RUN*} | cut -f4,5 | tr '\t\n' ' ;')
    [[ $line != "$prev" ]] && print -r -- "  [$(date +%H:%M:%S)] $line"; prev=$line
    (( ${#missing} == 0 )) && [[ $(print -lr -- ${(M)rows:#RUN*} | cut -f4) == completed ]] && break
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "completion timeout after $((SECONDS - start))s"; break
    fi
    sleep $POLL_S; fetch; summ
  done
  runline=${${(M)rows:#RUN*}[1]}
  f=("${(@ps:\t:)runline}")
  rid=$f[3]
  print -r -- "--- results for $sha"
  print -r -- "RUN ${f[7]} | id $rid | ${f[4]} | conclusion ${f[5]} (information only) | ${f[6]}"
  allow $GH api "repos/$REPO/actions/runs/$rid/jobs?per_page=100" > $work/jobs.json 2> $work/err || { print -r -- "  gh api jobs failed: $(<$work/err)"; print -r -- '{"jobs":[]}' > $work/jobs.json; }
  allow $PY -I -c 'import json, sys; print(json.dumps({"counted": sys.argv[1:7], "ui": sys.argv[7], "uploads": sys.argv[8:10], "run_conclusion": sys.argv[10]}))' \
    $COUNTED $UI_STEP $UPLOADS ${f[5]} > $work/config.json
  allow $PY -I -c $PYSTEPS $work/jobs.json $work/config.json > $work/judge.txt 2>&1
  grep -v '^JUDGE ' $work/judge.txt
  judge=$(grep '^JUDGE ' $work/judge.txt | tail -1)
  [[ -n $judge ]] || judge="JUDGE FAIL step judgement failed: $(tail -3 $work/judge.txt)"
  # The graftling checkout must have fetched the candidate commit: its full SHA appears in the job log.
  jid=$(allow $PY -I -c 'import json, sys; print(next((j["id"] for j in json.load(open(sys.argv[1])).get("jobs", []) if j.get("name") == "windows-adoption"), ""))' $work/jobs.json)
  hits=0
  if [[ -n $jid ]] && allow $GH api "repos/$REPO/actions/jobs/$jid/logs" > $work/job.log 2> $work/err; then
    hits=$(grep -c -- $GSHA $work/job.log || true)
    print -r -- "job log lines naming graftling $GSHA: $hits"; grep -m 3 -- $GSHA $work/job.log | cut -c1-220 | sed 's/^/  /'
  else
    print -r -- "job log unavailable: $(<$work/err)"
  fi
  (( ${#others} )) && { print -r -- "OTHER workflows triggered for this SHA:"; print -lr -- $others | sed 's/^/  /'; } \
    || print -r -- "no other workflow triggered for this SHA"
  if [[ ${f[5]} != success ]]; then
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 40
  fi
  rm -rf $work
  print -r -- "next: zsh $THIS W $sha    (re-observe; no push)"
  [[ ${f[5]} == success ]] || print -r -- "next: $GH run rerun $rid --repo $REPO --failed    (only if a counted step failed transiently; not run by this step)"
  if [[ $judge == "JUDGE PASS"* ]] && (( hits > 0 )); then
    print -r -- "VERDICT 619 $label: PASS (${judge#JUDGE PASS }; candidate graftling $GSHA in the job log; run $rid conclusion ${f[5]})"
  else
    (( hits > 0 )) || judge="$judge; candidate graftling $GSHA not found in the job log"
    print -r -- "VERDICT 619 $label: FAIL (${judge#JUDGE }; run $rid conclusion ${f[5]})"; exit 1
  fi
}

GSHA=
case $STEP in
00)
  say "[00] Preflight, read only. Login: gh login (account shown, no token), ssh key, git credential helper. Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
  local url=$(g remote get-url origin) gurl=$(gg remote get-url origin)
  [[ $url == (git@github.com:|https://github.com/|ssh://git@github.com/)$REPO(.git|) ]] && print -r -- "PASS: GraphTraj origin is $url" \
    || stop "GraphTraj origin is $url, not $REPO"
  [[ $gurl == $GURL ]] && print -r -- "PASS: $GRAFT origin is $gurl" || stop "$GRAFT origin is $gurl, not $GURL"
  [[ $REMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $REMOTE is used instead of GraphTraj origin"
  [[ $GREMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $GREMOTE is used instead of graftling origin"
  check_tree
  check_bundle
  graft_local_ok || true
  graft_remote_ok
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  checked $rsha
  if [[ -z $rsha ]]; then
    print -r -- "PASS: $BRANCH is absent on GraphTraj $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then
    print -r -- "next: zsh $THIS W $head"
    stop "GraphTraj $REMOTE already has $BRANCH at HEAD $head; nothing to push. Observe instead with the next command."
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then
    print -r -- "PASS: GraphTraj $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else
    stop "GraphTraj $REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force. Inspect: git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"
  fi
  print -r -- "candidate: GraphTraj $head, graftling $GSHA"
  print -r -- "next: zsh $THIS P    (publishes graftling $GSHA and GraphTraj $head, then waits for the run)"
  print -r -- "VERDICT 619 00: PASS (GraphTraj $head, graftling $GSHA)"
  ;;
P)
  say "[P] Publish and wait. OUTWARD-FACING: pushes $BRANCH to graftling $GREMOTE and to GraphTraj $REMOTE (fast-forward only, never force). Login: git credential helper, ssh key, gh login. Dialog: none. Network: GitHub."
  check_tree
  check_bundle
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  checked $rsha
  [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null || stop "GraphTraj $REMOTE has $BRANCH at $rsha, not an ancestor of HEAD; run: zsh $THIS 00"
  [[ $rsha == $head ]] && stop "GraphTraj $REMOTE already has $BRANCH at $head; run: zsh $THIS W $head"
  graft_remote_ok
  if graft_local_ok; then
    print -r -- "\$ git -C $GRAFT fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH}"
    gg fetch $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || stop "fetching the bundle failed; run: zsh $THIS 00"
    [[ $(gg rev-parse -q --verify refs/heads/$BRANCH) == $GSHA ]] || stop "$GRAFT local $BRANCH is not $GSHA after the fetch"
    print -r -- "PASS: $GRAFT local $BRANCH = $GSHA"
  fi
  if [[ $(gremote_sha) != $GSHA ]]; then
    print -r -- "\$ git -C $GRAFT push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   ($GSHA)"
    gg push $GREMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || stop "graftling push failed; nothing was forced. Run: zsh $THIS 00"
  fi
  [[ $(gremote_sha) == $GSHA ]] || stop "after the push graftling $GREMOTE does not show $GSHA; run: zsh $THIS 00"
  print -r -- "PASS: graftling $GREMOTE $BRANCH = $GSHA"
  print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head)"
  g push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "GraphTraj push failed; nothing was forced. Run: zsh $THIS 00"
  [[ $(remote_sha) == $head ]] || stop "after the push GraphTraj $REMOTE does not show $head; run: zsh $THIS 00"
  print -r -- "PASS: GraphTraj $REMOTE $BRANCH = $head"
  observe $head P
  ;;
W)
  check_bundle
  local sha=${2:-$(remote_sha)}
  checked $sha
  say "[W] Observe only (no push) the run for ${sha:-<none>}. Login: gh login. Dialog: none. Network: GitHub."
  [[ -n $sha ]] || stop "$BRANCH is not on GraphTraj $REMOTE; run: zsh $THIS 00"
  [[ $sha == $(g rev-parse HEAD) ]] || print -r -- "NOTE: observed SHA $sha differs from local HEAD $(g rev-parse HEAD)"
  observe $sha W
  ;;
*)
  print -r -- "usage: zsh $THIS 00|P|W [sha]"; exit 2 ;;
esac
