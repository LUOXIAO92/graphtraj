#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 626 Main-run steps: build the exact candidate desktop/ outside the Harness, run the desktop unit checks, and
# capture the real Electron window in light and dark (task graph, expanded chat, Teams & roles, Project usage).
# Modelled on verify-619/steps.zsh. Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight, read only: zsh / node (>= 22.18) / npm versions; graphtraj-tool found; this Worktree is clean at
#       HEAD; prints the candidate SHA, the work dir and the entry difference below. Writes nothing.
#       Login: none. Dialog: none. Network: none. ~2 s. Observable: the printed facts and VERDICT.
#   B   Build + unit checks: exports exactly HEAD:desktop (git archive) to WORK=${TMPDIR:-/tmp}/graphtraj-626-<sha>
#       (outside the Harness; replaced if present), npm ci (fetches the Electron binary if npm did not), npm run build
#       (tsc + vite), then the desktop unit checks tests/*.test.cjs (= `npm test` minus its repeated build). Prints
#       tests/pass/fail counts; VERDICT last. The tests/*.test.mjs window checks are NOT run here (window.test.mjs
#       adds projects to the real ${HOME}/.graphtraj index; monitor-ui/team-graph need a Playwright Chromium download).
#       Login: none. Dialog: none. Network: registry.npmjs.org and github.com (Electron zip). ~1-3 min.
#   S   Screens: from B's build, creates a disposable fixture project under $WORK/s-run (tasks implementing /
#       superseded / pending, two agents with messages, a tool call and usage records, the default team config made by
#       project_setup) and launches the built app with Playwright _electron (Electron from $WORK/desktop/node_modules,
#       main = dist-electron/main.js) with HOME=$WORK/s-run/home and --user-data-dir under $WORK/s-run, passing the
#       project with --project (no picker). The theme is forced only inside the app with Electron
#       nativeTheme.themeSource = 'light' then 'dark'; the system appearance is never changed. Per theme: task graph
#       with task #1 selected, expanded chat, Teams & roles, Project usage, 1440x900 (8 PNGs). Nothing is saved, no
#       native dialog is opened. Machine checks per theme: matchMedia(prefers-color-scheme: dark) matches the forced
#       theme; computed --bg equals the token; X6 edge strokes are edge/accent token values and the dependency edge and
#       project frame colours differ between themes and equal the tokens; no pageerror; every PNG > 10 kB.
#       Copies PNGs + facts.json to <Worktree>/scripts/verify-626/evidence/<sha>/ (untracked), prints their paths,
#       VERDICT last. A window appears on screen for ~30-60 s and closes itself; do not interact with it.
#       Login: none. Dialog: none. Network: none. ~1 min.
# ENTRY DIFFERENCE: S runs the development build (Electron 44.5.1 from npm, unpackaged dist + dist-electron) rather
# than the user's installed /Applications/GraphTraj.app (packaged by scripts/package-mac.mjs from the same sources):
# same renderer, CSS and main process code; differs in packaging, app name/icon and the bundled runtime path.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S)) and every ANTHROPIC_*, OPENAI_*, CLAUDE_CODE_USE_*, *_BASE_URL and
# GRAPHTRAJ_*_CONNECTION variable, printing the removed NAMES. Every started process runs through allow(): only HOME,
# USER, LOGNAME, PATH, TERM, TMPDIR, LANG (S: HOME is the isolated $WORK/s-run/home). No provider credential is passed.
# Rehearsal knob (Engineer sandbox only): VERIFY626_REHEARSAL=1 also passes the sandbox proxy variables,
# NODE_USE_ENV_PROXY=1 and npm_config_cache=$TMPDIR/npm-cache-626. Unset, nothing else is passed.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
STEP=${1:-}
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GIT=$(whence -p git)
NODE=$(whence -p node || print -r -- /usr/local/bin/node)
TOOL=$(whence -p graphtraj-tool || print -r -- $HARNESS/.venv-runtime/bin/graphtraj-tool)
SHA=$($GIT -C $WT rev-parse HEAD)
WORK=${TMPDIR:-/tmp}
WORK=${WORK%/}/graphtraj-626-$SHA
EVIDENCE=$WT/scripts/verify-626/evidence/$SHA

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
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == OPENAI_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAPHTRAJ_*CONNECTION ]]; then
      unset $k; removed+=$k
    fi
  done
  print -r -- "scrubbed at start (names only): ${removed:-none}"
}
scrub
APATH=${NODE:h}:${TOOL:h}:${GIT:h}:/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables; RUN_HOME overrides HOME for S.
allow() {
  local -a extra=()
  if [[ ${VERIFY626_REHEARSAL:-} == 1 ]]; then
    local v; for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
      [[ -n ${(P)v:-} ]] && extra+=$v=${(P)v}; done
    extra+=(NODE_USE_ENV_PROXY=1 npm_config_cache=${TMPDIR:-/tmp}/npm-cache-626 electron_config_cache=${TMPDIR:-/tmp}/electron-cache-626)
  fi
  /usr/bin/env -i HOME=${RUN_HOME:-$HOME} USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=${TMPDIR:-/tmp} LANG=en_US.UTF-8 GRAPHTRAJ_TOOL=$TOOL $extra "$@"
}
verdict() { print -r -- "VERDICT $1${2:+: $2}"; exit ${3:-0}; }

case $STEP in
00)
  say "Task 626 step 00 (read only)"
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
  [[ -z $dirty ]] || { print -r -- "tracked changes:"; print -r -- $dirty; bad+="Worktree not clean at HEAD"; }
  (( ${#bad} )) && verdict FAIL "${(j:; :)bad}" 1
  verdict PASS "ready for B";;
B)
  say "Task 626 step B: export HEAD:desktop to $WORK, npm ci, build, unit checks"
  rm -rf $WORK/desktop; mkdir -p $WORK || verdict FAIL "cannot create $WORK" 1
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
  say "Task 626 step S: light/dark screens from $WORK/desktop"
  [[ -f $WORK/B.ok && $(<$WORK/B.ok) == $SHA ]] || verdict FAIL "run B for $SHA first" 1
  local run=$WORK/s-run
  rm -rf $run; mkdir -p $run/home
  RUN_HOME=$run/home allow $NODE $WT/scripts/verify-626/screens.mjs $WORK/desktop $run 2>&1 | tee $run/driver.log; local drv=$?
  mkdir -p $EVIDENCE
  cp $run/*.png $run/facts.json $run/driver.log $EVIDENCE/ 2>/dev/null
  say "evidence (untracked):"
  ls -l $EVIDENCE
  (( drv == 0 )) || verdict FAIL "driver exit $drv; see $EVIDENCE/facts.json and driver.log" 1
  local n=$(ls $EVIDENCE/*.png 2>/dev/null | wc -l | tr -d ' ')
  (( n == 8 )) || verdict FAIL "$n of 8 screenshots" 1
  verdict PASS "8 screenshots and machine checks for $SHA in $EVIDENCE";;
*)
  print -r -- "usage: zsh ${0:t} 00|B|S"; exit 2;;
esac
