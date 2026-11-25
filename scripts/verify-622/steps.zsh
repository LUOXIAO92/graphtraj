#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 622 Main-run steps: observe that a GitHub Actions run of desktop-win-adoption.yml whose commit holds the 622
# guard (tests/process_reclaim.py skips the process reclaim on Windows) no longer logs the libproc.dylib noise.
# Modelled on verify-618/steps.zsh. This file never pushes: a run comes from 619's or a later push, asked for by Main.
#
# LOGIN: the user's own gh login only (gh auth status shows the account; no token is printed). GH_TOKEN/GITHUB_TOKEN
# and every other credential-class variable are removed at start, so gh cannot use a token from the environment.
# REAL ENTRY: the log of a desktop-win-adoption.yml run on LUOXIAO92/graphtraj, step 'Build desktop and check Windows
# native settings' (the step that runs pytest on the Windows runner).
# Run one step at a time:  zsh <this file> <STEP>
#   00      Preflight, read only. zsh; git and gh versions; gh auth status (token lines removed); origin is
#           LUOXIAO92/graphtraj; HEAD's tests/process_reclaim.py holds the guard. Prints the candidate HEAD and the next
#           command. Login: gh login. Dialog: none. Network: GitHub (gh auth status). ~5 s.
#   O [id]  Observe, read only. Without id: lists the newest 30 desktop-win-adoption.yml runs and picks the newest whose
#           head commit's tests/process_reclaim.py (read through the contents API, so a rebased or merged commit
#           counts) holds the guard; none -> PENDING, exit 3. With id: that run (PENDING if its commit lacks the guard).
#           Waits in this process until the run completes (poll 30 s, bound ~40 min), reads `gh run view <id> --log`
#           and checks: (a) the pytest step logged a final summary line (proves pytest_sessionfinish ran); (b) no line
#           contains 'libproc' or 'leftover test processes'. The run's own conclusion is informational (it may fail
#           for 619-621 reasons). Last line: VERDICT 622 O: PASS (exit 0) / FAIL (1) / PENDING (3) / INCONCLUSIVE (4).
#           Login: gh login. Dialog: none. Network: GitHub. Up to ~41 min.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing the removed NAMES. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, and when set GH_CONFIG_DIR, XDG_CONFIG_HOME
# (where gh finds the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer only): VERIFY622_GH (a gh stand-in), VERIFY622_DONE_S / _POLL_S (bounds). Unset, every
# step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
STEP=${1:-}
REPO=LUOXIAO92/graphtraj
WORKFLOW=desktop-win-adoption.yml
PYTEST_STEP='Build desktop and check Windows native settings'
GUARD_FILE=tests/process_reclaim.py
GH=${VERIFY622_GH:-$(whence -p gh || print -r -- gh)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
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
stop() { print -r -- "STOP: $*"; exit 1; }
g() { allow $GIT -C $WT "$@"; }

# The guard, as both 00 (local HEAD) and O (a run's commit) recognise it.
PYGUARD='import base64, json, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
if sys.argv[2] == "api":
    try: text = base64.b64decode(json.loads(text).get("content", "")).decode("utf-8", "replace")
    except ValueError: text = ""
sys.exit(0 if "def reclaim_supported()" in text and "if not reclaim_supported():" in text else 1)'
# A workflow runs response, newest first: id, head_sha, status, conclusion, url.
PYRUNS='import json, sys
runs = json.load(open(sys.argv[1])).get("workflow_runs", [])
for r in sorted(runs, key=lambda r: (r.get("created_at", ""), r["id"]), reverse=True):
    print(r["id"], r["head_sha"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), sep="\t")'
PYRUN='import json, sys
r = json.load(open(sys.argv[1]))
print(r["id"], r["head_sha"], r.get("status"), r.get("conclusion") or "-", r.get("html_url"), sep="\t")'
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

has_guard_at() {  # has_guard_at SHA WORK: the commit's guard file, read through the contents API
  allow $GH api "repos/$REPO/contents/$GUARD_FILE?ref=$1" > $2/content.json 2> /dev/null || return 1
  allow $PY -I -c $PYGUARD $2/content.json api
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: your gh login (account shown, no token). Dialog: none. Network: GitHub."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  print -r -- "git: $(allow $GIT --version) | gh: $(allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com; run: gh auth login --hostname github.com  then  zsh $THIS 00"
  origin_url=$(g remote get-url origin)
  [[ $origin_url == (git@github.com:|https://github.com/|ssh://git@github.com/)$REPO(.git|) ]] \
    && print -r -- "PASS: origin is $origin_url" || stop "origin is $origin_url, not $REPO"
  head=$(g rev-parse HEAD)
  work=$(mktemp -d $PYTMP/verify622.XXXXXX)
  g show HEAD:$GUARD_FILE > $work/guard.py 2> /dev/null || stop "$GUARD_FILE missing at HEAD $head"
  if allow $PY -I -c $PYGUARD $work/guard.py file; then
    print -r -- "PASS: HEAD's $GUARD_FILE holds the guard (reclaim_supported; pytest_sessionfinish returns on Windows)"
  else
    rm -rf $work; stop "HEAD $head: $GUARD_FILE lacks the 622 guard"
  fi
  rm -rf $work
  print -r -- "candidate: $head"
  print -r -- "next: zsh $THIS O    (after a desktop-win-adoption run of a commit holding the guard; read only, no push)"
  print -r -- "VERDICT 622 00: PASS (candidate $head)"
  ;;
O)
  want=${2:-}
  say "[O] Observe, read only, ${want:+run $want of }$WORKFLOW on $REPO. Login: your gh login. Dialog: none. Network: GitHub."
  work=$(mktemp -d $PYTMP/verify622.XXXXXX)
  trap 'rm -rf $work' EXIT
  if [[ -z $want ]]; then
    allow $GH api "repos/$REPO/actions/workflows/$WORKFLOW/runs?per_page=30" > $work/runs.json 2> $work/err \
      || stop "gh api runs failed: $(<$work/err)"
    rows=("${(@f)$(allow $PY -I -c $PYRUNS $work/runs.json)}")
    rows=(${rows:#})
    chosen=
    typeset -A seen
    print -r -- "runs checked, newest first (id | head sha | status | conclusion | guard):"
    for row in $rows; do
      cols=("${(@ps:\t:)row}")
      if (( ! ${+seen[${cols[2]}]} )); then
        has_guard_at ${cols[2]} $work && seen[${cols[2]}]=yes || seen[${cols[2]}]=no
      fi
      print -r -- "  ${cols[1]} | ${cols[2]} | ${cols[3]} | ${cols[4]} | guard ${seen[${cols[2]}]}"
      if [[ ${seen[${cols[2]}]} == yes ]]; then chosen=$row; break; fi
    done
    (( ${#rows} )) || print -r -- "  (no runs listed)"
    if [[ -z $chosen ]]; then
      print -r -- "next: zsh $THIS O    (after a push of a commit holding the guard has started $WORKFLOW)"
      print -r -- "VERDICT 622 O: PENDING (no qualifying run yet among ${#rows} runs)"
      exit 3
    fi
  else
    allow $GH api "repos/$REPO/actions/runs/$want" > $work/run.json 2> $work/err || stop "gh api run $want failed: $(<$work/err)"
    chosen=$(allow $PY -I -c $PYRUN $work/run.json)
    cols=("${(@ps:\t:)chosen}")
    if ! has_guard_at ${cols[2]} $work; then
      print -r -- "run $want head ${cols[2]}: $GUARD_FILE lacks the 622 guard"
      print -r -- "next: zsh $THIS O    (picks the newest qualifying run)"
      print -r -- "VERDICT 622 O: PENDING (run $want is not of a commit holding the guard)"
      exit 3
    fi
  fi
  cols=("${(@ps:\t:)chosen}")
  rid=${cols[1]}; sha=${cols[2]}; run_state=${cols[3]}; conclusion=${cols[4]}; url=${cols[5]}
  print -r -- "chosen run: $rid | head $sha | $run_state | $url"
  start=$SECONDS
  [[ $run_state != completed ]] && print -r -- "waiting for run $rid to complete (poll ${POLL_S}s, bound ${DONE_S}s)"
  while [[ $run_state != completed ]]; do
    if (( SECONDS - start >= DONE_S )); then
      print -r -- "run $rid still $run_state after $((SECONDS - start))s"
      print -r -- "next: zsh $THIS O $rid    (keeps waiting for this run)"
      print -r -- "VERDICT 622 O: PENDING (run $rid not completed within ${DONE_S}s)"
      exit 3
    fi
    sleep $POLL_S
    if allow $GH api "repos/$REPO/actions/runs/$rid" > $work/run.json 2> /dev/null; then
      cols=("${(@ps:\t:)$(allow $PY -I -c $PYRUN $work/run.json)}")
      [[ ${cols[3]} != $run_state ]] && print -r -- "  [$(date +%H:%M:%S)] $rid ${cols[3]}"
      run_state=${cols[3]}; conclusion=${cols[4]}
    fi
  done
  print -r -- "run $rid completed, conclusion $conclusion (informational; 619-621 failures do not affect 622)"
  print -r -- "\$ gh run view $rid --repo $REPO --log"
  allow $GH run view $rid --repo $REPO --log > $work/log.txt 2> $work/err || {
    print -r -- "gh run view failed: $(<$work/err)"
    print -r -- "next: zsh $THIS O $rid"
    print -r -- "VERDICT 622 O: INCONCLUSIVE (log of run $rid unavailable)"; exit 4; }
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
  print -r -- "next: zsh $THIS O $rid    (re-reads this run)"
  if (( ${#offending} )); then
    print -r -- "VERDICT 622 O: FAIL (run $rid at $sha logs the reclaim noise)"; exit 1
  elif (( ${#summaries} == 0 )); then
    print -r -- "VERDICT 622 O: INCONCLUSIVE (no pytest summary in '$PYTEST_STEP' of run $rid)"; exit 4
  fi
  print -r -- "VERDICT 622 O: PASS (run $rid at $sha: pytest finished, no libproc noise)"
  ;;
*)
  print -r -- "usage: zsh $THIS 00|O [run-id]"; exit 2 ;;
esac
