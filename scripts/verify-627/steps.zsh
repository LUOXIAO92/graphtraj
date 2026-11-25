#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 627 Main-run steps (desktop UI structure: V4-V12, U1-U3). Modelled on verify-626/steps.zsh (00, B, S) and
# verify-621/steps.zsh (P, W; its ghjson.py is reused read-only). Run one step at a time:  zsh <this file> <STEP>
# Each step waits for all of its own work, then prints its result, ready-to-paste next commands and VERDICT last.
#   00  Local preflight, read only: zsh / node (>= 22.18) / npm versions; graphtraj-tool found; this Worktree is clean
#       at HEAD; HEAD contains BASE (dev 4fa79a8d); prints the candidate SHA, work dir, evidence dir and the entry
#       difference below. Writes nothing. Login: none. Dialog: none. Network: none. ~2 s.
#       Observable: the printed facts and VERDICT.
#   B   Build + unit checks: exports exactly HEAD:desktop (git archive) to WORK=${TMPDIR:-/tmp}/graphtraj-627-<sha>
#       (outside the Harness; replaced if present), npm ci (fetches the Electron binary if npm did not), npm run build
#       (tsc + vite), then the desktop unit checks tests/*.test.cjs. Prints tests/pass/fail counts.
#       The tests/*.test.mjs window checks run on CI (the 627 step of desktop-macos-adoption.yml), not here:
#       window.test.mjs adds projects to the real ${HOME}/.graphtraj index.
#       Login: none. Dialog: none. Network: registry.npmjs.org, github.com (Electron zip). ~1-3 min.
#       Observable: "build exit 0", "unit exit 0" and the pass count.
#   S   Screens: from B's build, creates a disposable fixture project under $WORK/s-run (tasks implementing /
#       superseded / pending; a summary #5 with child #6; members with messages, a tool call and usage records on #1
#       (one historical) and #6; a configured team in the fixture's .graphtraj/roles.yml) and launches the built app with
#       Playwright _electron (Electron from $WORK/desktop/node_modules, main = dist-electron/main.js) with
#       HOME=$WORK/s-run/home and --user-data-dir under $WORK/s-run, passing the project with --project (no picker).
#       The theme is forced only inside the app with Electron nativeTheme.themeSource = 'light' then 'dark' and
#       Playwright colorScheme null; the system appearance is never changed. Per theme at 1440x900: task graph with #1
#       selected (right inspector), search active (panel + zoomed-in cards), Members tree table, expanded chat (tool
#       call, usage, historical member), Teams & roles, Agents & models, Project usage; at 1000x760: task graph and
#       task graph with #1 selected (bottom shelf). 18 PNGs. Machine checks: overlap by bounding-box intersection
#       (no card under the minimap; the 'Search results' panel intersects neither the canvas nor a card; legend/zoom
#       contacts are recorded as notes), Task details right of the canvas at 1440 and below it at 1000, sidebar order
#       Current project > PROJECTS > GLOBAL, the 'Monitor view' switch, the 'Detail width' slider, one SVG legend incl.
#       Crossing and no .map-caption, the Electron window backgroundColor per theme, HeroUI shadows = --shadow-*, and
#       verify-626's token, X6 colour and org-tree checks; no pageerror; every PNG > 10 kB. On failure: the stage and
#       message in facts.json and <theme>-failure.png. The app is always closed (killed after 10 s). Copies PNGs +
#       facts.json + driver.log to <Worktree>/scripts/verify-627/evidence/<sha>/ (untracked). A window appears for
#       ~1-3 min and closes itself; do not interact with it. Nothing is saved; no native dialog opens.
#       Login: none. Dialog: none. Network: none. ~2-4 min. Observable: 18 PNGs, facts.json verdict PASS.
#   P0  Push preflight, read only on GitHub: gh/git versions; gh auth status (account only); origin is LUOXIAO92/graphtraj;
#       remote branch absent, equal to or an ancestor of HEAD (else STOP, never force); the P preconditions.
#       Login: gh login, ssh key (ls-remote). Dialog: none. Network: GitHub. ~10 s.
#   P   Push and wait. OUTWARD-FACING (Main asks the user first): `git push origin agent/627-desktop-ui-structure-redesign`
#       (fast-forward only, never force). The push starts desktop-macos-adoption and desktop-linux-adoption (their push
#       lists name this branch); Windows and repair are not triggered. Then waits in this process for both push runs of
#       HEAD to appear (bound 300 s) and complete (bound 3300 s, poll 30 s); prints per-run/per-job results with failing
#       steps, the tail of --log-failed, downloads both evidence artifacts into <Harness>/tmp/627 with a copy in
#       /private/tmp/graphtraj-627. VERDICT PASS only when both runs succeed.
#       Login: ssh key, gh login. Dialog: none (ssh may ask a key passphrase). Network: GitHub. Up to ~60 min.
#   W   Observe only (no push): `W` for the pushed branch head or `W <sha>`; same waiting and output as P after the
#       push. Login: gh login. Dialog: none. Network: GitHub. Up to ~60 min.
# NO HOST/MODEL LOGIN: no step starts Claude, Codex, Pi or any other model Runtime and no provider login is used.
# ENTRY DIFFERENCE (S): the development build (Electron 44.5.1 from npm, unpackaged dist + dist-electron) rather than the
# installed /Applications/GraphTraj.app (packaged by scripts/package-mac.mjs from the same sources): same renderer,
# CSS and main process code; differs in packaging, app name/icon and the bundled runtime path. CI runs the packaged app.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*, OPENAI_*,
# CLAUDE_CODE_USE_*, *_BASE_URL and GRAPHTRAJ_*CONNECTION / GRAFTLING_CONNECTION variable, printing the removed NAMES.
# Every started process runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG (+ GRAPHTRAJ_TOOL for
# 00/B/S; S: HOME is the isolated $WORK/s-run/home), and for P0/P/W also SSH_AUTH_SOCK, GH_CONFIG_DIR,
# XDG_CONFIG_HOME when set (where git and gh find the user's own login). No provider credential is passed.
# Rehearsal knobs (Engineer sandbox only): VERIFY627_REHEARSAL=1 passes the sandbox proxy variables, NODE_USE_ENV_PROXY=1
# and npm/electron caches under $TMPDIR (B); VERIFY627_FIXTURE_ONLY=1 makes S build the fixture without Electron;
# VERIFY627_REMOTE, VERIFY627_GH, VERIFY627_HTMP / VERIFY627_PTMP, VERIFY627_APPEAR_S / _DONE_S / _POLL_S (P/W).
# Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
STEP=${1:-}
SELF=${0:A}
HERE=${0:A:h}
NEXT=
BRANCH=agent/627-desktop-ui-structure-redesign
# dev 4fa79a8d: 621 (adoption scripts) and 626 (tokens) integrated; the Task branch starts here.
BASE=4fa79a8d05e6532fc912f8b00673970960a7f0ba
HARNESS=${WT:h:h:h:h}
REPO=LUOXIAO92/graphtraj
GIT=$(whence -p git)
NODE=$(whence -p node || print -r -- /usr/local/bin/node)
TOOL=$(whence -p graphtraj-tool || print -r -- $HARNESS/.venv-runtime/bin/graphtraj-tool)
GH=${VERIFY627_GH:-$(whence -p gh || print -r -- gh)}
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
GHJSON=$WT/scripts/verify-621/ghjson.py
REMOTE=${VERIFY627_REMOTE:-origin}
HTMP=${VERIFY627_HTMP:-$HARNESS/tmp/627}
PTMP=${VERIFY627_PTMP:-/private/tmp/graphtraj-627}
APPEAR_S=${VERIFY627_APPEAR_S:-300}
DONE_S=${VERIFY627_DONE_S:-3300}
POLL_S=${VERIFY627_POLL_S:-30}
SHA=$($GIT -C $WT rev-parse HEAD)
WORK=${TMPDIR:-/tmp}
WORK=${WORK%/}/graphtraj-627-$SHA
EVIDENCE=$WT/scripts/verify-627/evidence/$SHA
SCREEN_COUNT=18
WORKFLOWS=(.github/workflows/desktop-linux-adoption.yml .github/workflows/desktop-macos-adoption.yml)
WFNAMES="desktop-macos-adoption.yml and desktop-linux-adoption.yml"
artifact_for() { [[ $1 == *macos* ]] && print -r -- graphtraj-macos-adoption-evidence || print -r -- linux-desktop-$2; }
prefix_for() { [[ $1 == *macos* ]] && print -r -- mac-evidence || print -r -- linux-evidence; }

say() { print -r -- "== $*"; }
is_cred() {
  local name=${(U)1} part
  [[ $name == GIT_CONFIG_KEY_<-> ]] && return 1
  for part in ${(s:_:)name}; do [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && return 0; done
  return 1
}
scrub() {
  local k; local -a removed=()
  for k in ${(k)parameters[(R)*export*]}; do
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == OPENAI_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAPHTRAJ_*CONNECTION || $k == GRAFTLING_CONNECTION ]]; then
      unset $k; removed+=$k
    fi
  done
  print -r -- "scrubbed at start (names only): ${removed:-none}"
}
scrub
APATH=${NODE:h}:${TOOL:h}:${GH:h}:${GIT:h}:/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables; RUN_HOME overrides HOME for S; LOGIN=1 adds git/gh login locations.
allow() {
  local -a extra=()
  if [[ ${VERIFY627_REHEARSAL:-} == 1 ]]; then
    local v; for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
      [[ -n ${(P)v:-} ]] && extra+=$v=${(P)v}; done
    extra+=(NODE_USE_ENV_PROXY=1 npm_config_cache=${TMPDIR:-/tmp}/npm-cache-627 electron_config_cache=${TMPDIR:-/tmp}/electron-cache-627)
  fi
  if [[ ${LOGIN:-} == 1 ]]; then
    [[ -n ${SSH_AUTH_SOCK:-} ]] && extra+=SSH_AUTH_SOCK=$SSH_AUTH_SOCK
    [[ -n ${GH_CONFIG_DIR:-} ]] && extra+=GH_CONFIG_DIR=$GH_CONFIG_DIR
    [[ -n ${XDG_CONFIG_HOME:-} ]] && extra+=XDG_CONFIG_HOME=$XDG_CONFIG_HOME
    extra+=GH_PROMPT_DISABLED=1
  fi
  /usr/bin/env -i HOME=${RUN_HOME:-$HOME} USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=${TMPDIR:-/tmp} LANG=en_US.UTF-8 GRAPHTRAJ_TOOL=$TOOL $extra "$@"
}
g() { LOGIN=1 allow $GIT -C $WT "$@"; }
hj() { allow $PY -I $GHJSON "$@"; }
remote_sha() { g ls-remote $REMOTE refs/heads/$BRANCH | cut -f1; }
# Print the ready-to-paste next command (NEXT overrides the default), then VERDICT last.
verdict() {
  local next=${NEXT:-}
  if [[ -z $next ]]; then
    case $STEP:$1 in
      00:PASS) next="zsh $SELF B";;
      B:PASS) next="zsh $SELF S";;
      S:PASS) next="tell the Leader: evidence at $EVIDENCE; after the Leader's review and the user's approval of the push: zsh $SELF P0";;
      S:FAIL) next="tell the Leader: facts at $EVIDENCE/facts.json (driver log $EVIDENCE/driver.log); re-run after a fix: zsh $SELF S";;
      P0:PASS) next="ask the user before pushing, then: zsh $SELF P";;
      *) next="fix the reported cause, then re-run: zsh $SELF $STEP";;
    esac
  fi
  print -r -- "NEXT: $next"
  print -r -- "VERDICT 627 $STEP: $1${2:+ ($2)}"; exit ${3:-0}
}
stop() { NEXT="${2:-zsh $SELF P0}"; verdict STOP "$1" 1; }

# ---- GitHub helpers (P0/P/W), as in verify-621 ----
GHW=
ghwork() { [[ -n $GHW ]] || { GHW=$(mktemp -d ${TMPDIR:-/tmp}/verify627.XXXXXX); trap 'rm -rf $GHW' EXIT; }; }
api() {
  LOGIN=1 allow $GH api $2 > $1 2> $GHW/api-err && return 0
  print -r -- "  gh api $2 failed: $(<$GHW/api-err)"; return 1
}
# check_tree: one PASS/FAIL line per P precondition; returns the number of FAILs.
check_tree() {
  local cur=$(g rev-parse --abbrev-ref HEAD) bad=0 wf
  [[ $cur == $BRANCH ]] && print -r -- "PASS: on $BRANCH" || { print -r -- "FAIL: current branch is $cur, not $BRANCH"; (( bad++ )); }
  [[ -z $(g status --porcelain --untracked-files=no) ]] && print -r -- "PASS: tracked tree clean" \
    || { print -r -- "FAIL: tracked changes in $WT (git -C $WT status)"; (( bad++ )); }
  if g merge-base --is-ancestor $BASE HEAD 2> /dev/null; then print -r -- "PASS: base ${BASE[1,8]} is an ancestor of HEAD"
  else print -r -- "FAIL: base ${BASE[1,8]} is not an ancestor of HEAD"; (( bad++ )); fi
  local -a wfchanged=("${(@f)$(g diff --name-only $BASE HEAD -- .github/workflows 2> /dev/null)}")
  wfchanged=(${wfchanged:#})
  if [[ ${(j: :)${(o)wfchanged}} != ${(j: :)${(o)WORKFLOWS}} ]]; then
    print -r -- "FAIL: workflow files changed since base must be exactly ${WORKFLOWS}; saw: ${wfchanged:-none}"; (( bad++ ))
  else
    print -r -- "PASS: only $WFNAMES changed under .github/workflows (Windows and repair untouched)"
    for wf in $WORKFLOWS; do
      if g show HEAD:$wf | grep -qE "^    branches: \[.*${BRANCH}[],]"; then print -r -- "PASS: $wf push branches name $BRANCH"
      else print -r -- "FAIL: $wf push branches do not name $BRANCH"; (( bad++ )); fi
    done
    local linux=("${(@f)$(g diff -U0 $BASE HEAD -- .github/workflows/desktop-linux-adoption.yml | grep -E '^[-+]' | grep -vE '^(---|\+\+\+) ')}")
    (( ${#linux} == 2 )) && print -r -- "PASS: desktop-linux-adoption.yml changes only its push branches line" \
      || { print -r -- "FAIL: desktop-linux-adoption.yml has other changes:"; print -lr -- $linux | sed 's/^/  /'; (( bad++ )); }
    g show HEAD:.github/workflows/desktop-macos-adoption.yml | grep -q "Desktop window tests for the Task 627 surfaces" \
      && print -r -- "PASS: desktop-macos-adoption.yml has the 627 window-test step" \
      || { print -r -- "FAIL: desktop-macos-adoption.yml lacks the 627 window-test step"; (( bad++ )); }
  fi
  [[ -f $WORK/B.ok && $(<$WORK/B.ok) == $(g rev-parse HEAD) ]] && print -r -- "NOTE: B passed for HEAD in this TMPDIR" \
    || print -r -- "NOTE: no B pass recorded for HEAD in $WORK (not required for P)"
  [[ -f $EVIDENCE/facts.json ]] && print -r -- "NOTE: S evidence for HEAD at $EVIDENCE" || print -r -- "NOTE: no S evidence for HEAD at $EVIDENCE"
  return $bad
}
fetch_evidence() {
  local rid=$1 name=$2 prefix=$3
  local dest=$HTMP/$prefix-$rid copy=$PTMP/$prefix-$rid
  mkdir -p $HTMP $PTMP
  if [[ -d $dest && -n $(ls -A $dest) ]]; then print -r -- "already present, not downloaded again: $dest"
  else
    print -r -- "\$ gh run download $rid --repo $REPO -n $name -D $dest"
    LOGIN=1 allow $GH run download $rid --repo $REPO -n $name -D $dest 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || { print -r -- "FAIL: download of $name from run $rid failed"; return 1; }
  fi
  if [[ -d $copy && -n $(ls -A $copy) ]]; then print -r -- "copy already present: $copy"
  else mkdir -p $copy && cp -R $dest/. $copy/ || { print -r -- "FAIL: copy to $copy failed"; return 1; }; print -r -- "copied to: $copy"; fi
  print -r -- "--- files (bytes, path under $dest)"
  hj evidence $dest
  return 0
}
# observe_push <sha>: wait for both push runs of sha, print results, fetch both artifacts; VERDICT last.
observe_push() {
  local sha=$1 start=$SECONDS line prev= ok=0 rid wf concl evid
  local -a rows missing others failed notes
  local runs_api="repos/$REPO/actions/runs?head_sha=$sha&per_page=100"
  summ() {
    if api $GHW/runs.json $runs_api; then rows=("${(@f)$(hj pushruns $GHW/runs.json $WORKFLOWS)}")
    else rows=(${WORKFLOWS/#/MISSING$'\t'}); fi
    missing=(${(M)rows:#MISSING*}); others=(${(M)rows:#OTHER*})
  }
  print -r -- "observing push runs of $WFNAMES for $sha (appearance bound ${APPEAR_S}s, completion bound ${DONE_S}s, poll ${POLL_S}s)"
  while true; do
    summ
    (( ${#missing} == 0 )) && break
    if (( SECONDS - start >= APPEAR_S )); then
      print -r -- "appearance timeout after $((SECONDS - start))s; missing:"; print -lr -- $missing | sed 's/^/  /'
      (( ${#others} )) && { print -r -- "other workflows for this SHA:"; print -lr -- $others | sed 's/^/  /'; }
      NEXT="zsh $SELF W $sha    (re-observe; no push)"; verdict FAIL "0/2 success; ${#missing} of 2 workflows never appeared within ${APPEAR_S}s" 1
    fi
    sleep $POLL_S
  done
  print -r -- "both push runs present after $((SECONDS - start))s"
  start=$SECONDS
  while true; do
    line=$(print -lr -- ${(M)rows:#RUN*} | cut -f2,4,5 | tr '\t\n' ' ;')
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
    api $GHW/jobs.json "repos/$REPO/actions/runs/$rid/jobs?per_page=100" && hj jobs $GHW/jobs.json
    if [[ ${f[4]} == completed && $concl == success ]]; then (( ok++ )); else failed+=$rid; fi
  done
  (( ${#others} )) && { print -r -- "OTHER workflows triggered for this SHA:"; print -lr -- $others | sed 's/^/  /'; } \
    || print -r -- "no other workflow triggered for this SHA"
  for rid in $failed; do
    print -r -- "--- tail of: gh run view $rid --repo $REPO --log-failed"
    LOGIN=1 allow $GH run view $rid --repo $REPO --log-failed 2>&1 | tail -n 60
  done
  for line in ${(M)rows:#RUN*}; do
    local -a f=("${(@ps:\t:)line}")
    wf=$f[2]; rid=$f[3]
    [[ $f[4] == completed ]] || { notes+="${wf:t} evidence not fetched (run not completed)"; continue; }
    print -r -- "--- evidence of ${wf:t} run $rid"
    fetch_evidence $rid $(artifact_for $wf $sha) $(prefix_for $wf) && evid=ok || evid=failed
    notes+="${wf:t} evidence $evid"
  done
  for rid in $failed; do print -r -- "next (only if the failure is transient; not run by this step): $GH run rerun $rid --repo $REPO --failed"; done
  NEXT="zsh $SELF W $sha    (re-observe; no push)"
  (( ok == 2 )) && verdict PASS "2/2 success; ${(j:; :)notes}"
  verdict FAIL "$ok/2 success; ${(j:; :)notes}" 1
}

case $STEP in
00)
  say "Task 627 step 00 (read only). Login: none. Dialog: none. Network: none."
  print -r -- "zsh $ZSH_VERSION"
  local nv=$(allow $NODE -v 2>&1) npmv=$(allow ${NODE:h}/npm -v 2>&1)
  print -r -- "node $nv ($NODE)"; print -r -- "npm $npmv"
  print -r -- "graphtraj-tool $TOOL"
  print -r -- "candidate SHA $SHA"
  print -r -- "work dir $WORK"
  print -r -- "evidence dir $EVIDENCE"
  print -r -- "entry: development build via Playwright _electron (Electron from npm, dist-electron/main.js), not /Applications/GraphTraj.app; same renderer/CSS/main sources, differs in packaging, app name/icon, bundled runtime path"
  local dirty=$($GIT -C $WT status --porcelain --untracked-files=no)
  local -a bad=()
  [[ $nv == v<->.<->.<-> ]] || bad+="node not found"
  if [[ $nv == (#b)v(<->).(<->).* ]]; then (( match[1] > 22 || (match[1] == 22 && match[2] >= 18) )) || bad+="node $nv < 22.18"; fi
  [[ -x $TOOL ]] || bad+="graphtraj-tool not executable at $TOOL"
  $GIT -C $WT merge-base --is-ancestor $BASE HEAD 2> /dev/null || bad+="base ${BASE[1,8]} is not an ancestor of HEAD"
  [[ -z $dirty ]] || { print -r -- "tracked changes:"; print -r -- $dirty; bad+="Worktree not clean at HEAD"; }
  (( ${#bad} )) && verdict FAIL "${(j:; :)bad}" 1
  verdict PASS "ready for B at $SHA";;
B)
  say "Task 627 step B: export HEAD:desktop to $WORK, npm ci, build, unit checks. Login: none. Dialog: none. Network: npm registry, github.com."
  rm -rf $WORK/desktop $WORK/B.ok; mkdir -p $WORK || verdict FAIL "cannot create $WORK" 1
  $GIT -C $WT archive --format=tar HEAD desktop | tar -x -C $WORK || verdict FAIL "git archive failed" 1
  print -r -- "exported $($GIT -C $WT rev-parse HEAD:desktop) (tree of HEAD:desktop) to $WORK/desktop"
  cd $WORK/desktop
  allow ${NODE:h}/npm ci --no-audit --no-fund > $WORK/npm-ci.log 2>&1; local ci=$?
  tail -3 $WORK/npm-ci.log; print -r -- "npm ci exit $ci"
  (( ci == 0 )) || verdict FAIL "npm ci exit $ci (log $WORK/npm-ci.log)" 1
  if [[ ! -d node_modules/electron/dist ]]; then
    allow $NODE node_modules/electron/install.js > $WORK/electron-install.log 2>&1
    print -r -- "electron install.js exit $? (log $WORK/electron-install.log)"
  fi
  print -r -- "electron binary: $(ls -d node_modules/electron/dist/*(N) | head -1)"
  allow ${NODE:h}/npm run build > $WORK/build.log 2>&1; local build=$?
  grep -E "built in|error" $WORK/build.log | tail -3; print -r -- "build exit $build"
  (( build == 0 )) || verdict FAIL "build exit $build (log $WORK/build.log)" 1
  allow $NODE --preserve-symlinks --preserve-symlinks-main --test tests/*.test.cjs > $WORK/unit.log 2>&1; local unit=$?
  grep -E "^ℹ (tests|pass|fail|cancelled|skipped) " $WORK/unit.log
  grep -E "^✖" $WORK/unit.log | head -10
  print -r -- "unit exit $unit (log $WORK/unit.log)"
  (( unit == 0 )) || verdict FAIL "unit checks exit $unit" 1
  print -r -- $SHA > $WORK/B.ok
  verdict PASS "build and $(grep -E '^ℹ pass ' $WORK/unit.log | awk '{print $3}') unit checks passed for $SHA";;
S)
  say "Task 627 step S: light/dark screens from $WORK/desktop. Login: none. Dialog: none. Network: none. A window opens and closes itself."
  [[ -f $WORK/B.ok && $(<$WORK/B.ok) == $SHA ]] || { NEXT="zsh $SELF B"; verdict FAIL "run B for $SHA first" 1; }
  local run=$WORK/s-run
  local -a drvargs=($WORK/desktop $run)
  [[ ${VERIFY627_FIXTURE_ONLY:-} == 1 ]] && drvargs+=--fixture-only
  rm -rf $run; mkdir -p $run/home
  RUN_HOME=$run/home allow $NODE $HERE/screens.mjs $drvargs 2>&1 | tee $run/driver.log; local drv=${pipestatus[1]}
  rm -rf $EVIDENCE; mkdir -p $EVIDENCE
  local -a files=($run/*.png(N) $run/facts.json(N) $run/driver.log(N))
  (( ${#files} )) && cp $files $EVIDENCE/
  say "evidence (untracked):"
  ls -l $EVIDENCE
  [[ -f $EVIDENCE/facts.json ]] && print -r -- "facts: $EVIDENCE/facts.json"
  (( drv == 0 )) || verdict FAIL "driver exit $drv; see $EVIDENCE/facts.json and driver.log" 1
  if [[ ${VERIFY627_FIXTURE_ONLY:-} == 1 ]]; then NEXT="zsh $SELF S   (without VERIFY627_FIXTURE_ONLY, on a host that can open windows)"; verdict PASS "fixture-only rehearsal (no screenshots) for $SHA"; fi
  local -a pngs=($EVIDENCE/*.png(N))
  local n=${#${pngs:#*-failure.png}}
  (( n == SCREEN_COUNT )) || verdict FAIL "$n of $SCREEN_COUNT screenshots" 1
  verdict PASS "$SCREEN_COUNT screenshots and machine checks for $SHA in $EVIDENCE";;
P0)
  say "[P0] Push preflight, read only. Login: your gh login (account shown, no token) and ssh key (git ls-remote). Dialog: none. Network: GitHub."
  ghwork
  print -r -- "git: $(allow $GIT --version) | gh: $(LOGIN=1 allow $GH --version | head -1) | gh path: $GH"
  print -r -- "\$ gh auth status --hostname github.com   (token lines removed)"
  LOGIN=1 allow $GH auth status --hostname github.com 2>&1 | grep -v -i 'token' | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "gh is not logged in to github.com" "gh auth login --hostname github.com  then  zsh $SELF P0"
  local url=$(g remote get-url origin)
  [[ $url == (git@github.com:|https://github.com/|ssh://git@github.com/)$REPO(.git|) ]] && print -r -- "PASS: origin is $url" || stop "origin is $url, not $REPO"
  [[ $REMOTE != origin ]] && print -r -- "NOTE: rehearsal remote $REMOTE is used instead of origin for ls-remote/push"
  local head=$(g rev-parse HEAD) rsha=$(remote_sha) remote_state
  print -r -- "current branch: $(g rev-parse --abbrev-ref HEAD) | HEAD $head"
  if [[ -z $rsha ]]; then remote_state=absent; print -r -- "PASS: $BRANCH is absent on $REMOTE (P creates it)"
  elif [[ $rsha == $head ]]; then remote_state=equal; print -r -- "PASS: $REMOTE already has $BRANCH at HEAD (no push needed; observe with W)"
  elif g merge-base --is-ancestor $rsha $head 2> /dev/null; then remote_state=ancestor; print -r -- "PASS: $REMOTE has $BRANCH at $rsha, an ancestor of HEAD (fast-forward)"
  else stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD $head; never force" "git -C $WT fetch $REMOTE $BRANCH && git -C $WT log --oneline --graph HEAD FETCH_HEAD"; fi
  print -r -- "--- P preconditions"
  check_tree || verdict FAIL "P preconditions not met (above); remote branch $remote_state" 1
  [[ $remote_state == equal ]] && { NEXT="zsh $SELF W    (observes the push runs of the already pushed HEAD; no push)"; verdict PASS "P not needed; remote branch equal to $head"; }
  verdict PASS "P ready; remote branch $remote_state; candidate $head";;
P)
  say "[P] Push and wait. OUTWARD-FACING: git push $REMOTE $BRANCH (fast-forward only, never force); starts $WFNAMES. Login: ssh key, gh login. Dialog: none. Network: GitHub."
  ghwork
  check_tree || stop "HEAD does not meet the preconditions above"
  local head=$(g rev-parse HEAD) rsha=$(remote_sha)
  [[ $rsha == $head ]] && stop "$REMOTE already has $BRANCH at $head" "zsh $SELF W"
  [[ -z $rsha ]] || g merge-base --is-ancestor $rsha $head 2> /dev/null || stop "$REMOTE has $BRANCH at $rsha, not an ancestor of HEAD; never force"
  print -r -- "\$ git push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH}   (HEAD $head)"
  g push $REMOTE refs/heads/${BRANCH}:refs/heads/${BRANCH} 2>&1 | sed 's/^/  /'
  (( ${pipestatus[1]} == 0 )) || stop "push failed; nothing was forced"
  [[ $(remote_sha) == $head ]] || stop "$REMOTE does not show $BRANCH at $head"
  print -r -- "PASS: $REMOTE $BRANCH = $head"
  observe_push $head;;
W)
  say "[W] Observe only (no push). Login: gh login. Dialog: none. Network: GitHub."
  ghwork
  local target=${2:-}
  [[ -n $target ]] || target=$(remote_sha)
  [[ -n $target ]] || stop "$BRANCH is not on $REMOTE"
  [[ $target == $(g rev-parse HEAD) ]] || print -r -- "NOTE: observed SHA $target differs from local HEAD $(g rev-parse HEAD)"
  observe_push $target;;
*)
  print -r -- "usage: zsh ${0:t} 00|B|S|P0|P|W [sha]"; exit 2;;
esac
