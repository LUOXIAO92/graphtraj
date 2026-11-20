#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 539 steps: does DSH's changes card still list GraphTraj's private .graphtraj files (the Main notice inbox)?
# Copied from verify-537 (6317b20d: the headless DSH web server + playwright driver ui537.mjs, unchanged) and adapted.
#   zsh scripts/verify-539/steps.zsh <STEP>        (Main's Bash; from anywhere; one step at a time)
# Order: 0 -> B -> A -> AR -> C, and T / TB / TR for the full suite (any time, quiet host).
#   0   preflight: two venvs (BEFORE = GraphTraj 9ae7a149, AFTER = the candidate; both graftling 4a002129 v0.6.2),
#       project-before set up by BEFORE's public setup, project-after by AFTER's, roles + probe Task 1, isolated DSH
#       home with web profile web539 + graftling-dsh, playwright-core, headless browser, one one-line model answer.
#   B   BEFORE: GraphTraj DSH Main in project-before (create + send a member, write the user file notes-539.txt,
#       answer the member's notice). Expected card: notes-539.txt AND .graphtraj/... inbox paths (the defect).
#   A   AFTER: the same in project-after. Expected card: notes-539.txt, no .graphtraj/ path.
#   AR  REPAIR: project-before (set up by 9ae7a149, already used by B) re-set-up by AFTER's setup (must REGISTER the
#       .graphtraj/.gitignore), then the same case with AFTER's Main. Expected card: notes-539.txt, no .graphtraj/ path.
#   C   (read only on BASE) copies shots + text into <Worktree>/.state/realhost/ as before-*, after-*, repair-*.
#   T   full suite of the candidate (6 shards, background); TB the same for base 9ae7a149; TR compares (read only).
#       VERIFY539_TESTS=<files> runs plain pytest on those files instead (rehearsal of the entry).
# Dialog in every step: none (headless browser, DSH's in-page directory dialog, no native chooser, no default browser;
# the driver itself clicks DSH's in-page tool approvals). Everything is under BASE=/private/tmp/dsh-ui-539; test venvs
# and the base source under <Harness>/tmp/539; pytest temp under TMPDIR=${TMPDIR:-/tmp} (outside the Harness).
# The user's DSH install, ~/.dsh, browser profile and dotfiles are never written (DSH_HOME=$DH everywhere). Each run
# step stops only the processes it started. No step starts or connects to the Harness's production MCP servers.
# Rehearsal-only overrides: VERIFY539_BASE, VERIFY539_T, VERIFY539_REALHOST, VERIFY539_NODE, VERIFY539_NOMODEL,
# VERIFY539_ASSUME_PLUGIN.
emulate -L zsh
setopt err_return pipe_fail no_unset no_bg_nice
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>
GCOMMIT=4a002129f8b97f32980afd59e5a1a64c428fe684       # graftling 0.6.2 (528), production
GSRC=$H/graftling                                      # read only (git archive)
BEFORE_COMMIT=9ae7a149                                 # GraphTraj dev base of 539
AFTER_COMMIT=${VERIFY539_AFTER:-$(git -C $WT rev-parse --short HEAD)}
BASE=${VERIFY539_BASE:-/private/tmp/dsh-ui-539}
DH=$BASE/dsh-home; OUT=$BASE/runs; NODE=${VERIFY539_NODE:-$BASE/node}
T=${VERIFY539_T:-$H/tmp/539}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: yaml, websockets, click
STEP=${1:-}
MODEL=deepseek-flash
WEB=web539
PWVER=1.65.1
TURN_S=${VERIFY539_TURN_S:-300}; NOTICE_S=${VERIFY539_NOTICE_S:-240}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$BASE/tmp \
  LANG=${LANG:-en_US.UTF-8} DSH_HOME=$DH ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
load_key() {
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
deps() {
  local SP=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $RT/websockets $RT/websockets-*.dist-info(N) \
    $RT/click $RT/click-*.dist-info(N) $SP/
}
wheel() {  # $1 repository, $2 commit, $3 subdirectory, $4 output directory
  local src=$4/src-${2[1,10]}; rm -rf $src; mkdir -p $src $4
  git -C $1 archive $2 $3 | tar -x -C $src
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $4 $src/$3 >/dev/null
}
need() {
  local found=($1/$~2(N))
  (( $#found == 1 )) && { print -r -- $found; return 0; }
  print -r -- "STOP: expected exactly one $2 in $1, found ${#found}" >&2; return 1
}
# label -> GraphTraj commit, venv, project. 'repair' is project-before served by the AFTER venv.
commit_of() { [[ $1 == before ]] && print -r -- $BEFORE_COMMIT || print -r -- $AFTER_COMMIT; }
venv_of() { [[ $1 == before ]] && print -r -- $BASE/venv-before || print -r -- $BASE/venv-after; }
project_of() { [[ $1 == after ]] && print -r -- $BASE/project-after || print -r -- $BASE/project-before; }
patch_of() { [[ $1 == before ]] && print -r -- $BASE/graphtraj-main-before.patch.yml || print -r -- $BASE/graphtraj-main-after.patch.yml; }
gdsh() { $BASE/venv-after/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
llm_patch() {
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
has_plugin() {
  [[ -n ${VERIFY539_ASSUME_PLUGIN:-} ]] && { print "REHEARSAL: graftling-dsh assumed present in $WEB" >&2; return 0; }
  grep -q '"graftling-dsh"' $DH/profiles/$WEB/package.json 2>/dev/null
}
plugin_cmd() {
  print -r -- "cd $BASE && env DSH_HOME=$DH PATH=$BASE/bin:/opt/homebrew/bin:\$PATH npm_config_store_dir=$BASE/pnpm-store $(command -v dsh) plugin --profile $WEB add $(gdsh)"
}
git_ws() {  # $1 directory: a git work tree with one commit
  [[ -d $1/.git ]] && return 0
  mkdir -p $1; (cd $1 && git init -q -b main && print -r -- "# 539 ${1:t}" > README.md && git add README.md \
    && git -c user.name=539 -c user.email=539@invalid commit -qm "Initial source")
}
build_venv() {  # $1 label before|after: GraphTraj wheel from git archive of its commit + graftling wheel
  local V=$(venv_of $1) C=$(git -C $WT rev-parse $(commit_of $1)) Wh=$BASE/wheels-$1
  if [[ -f $V/installed && $(<$V/installed) == "$C $GCOMMIT" ]]; then print "venv $V already holds GraphTraj ${C[1,10]} + graftling ${GCOMMIT[1,10]}"; return 0; fi
  mkdir -p $Wh; rm -f $Wh/graftling-*.whl(N) $Wh/graphtraj-*.whl(N)
  wheel $GSRC $GCOMMIT src/graftling $Wh && wheel $WT $C . $Wh || { print "STOP: a wheel did not build"; return 1; }
  local gw hw; gw=$(need $Wh 'graftling-*.whl') && hw=$(need $Wh 'graphtraj-*.whl') || return 1
  [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
  $CONDA -m venv $V; deps $V
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw $hw
  print -r -- "$C $GCOMMIT" > $V/installed
  print "venv $V: GraphTraj ${C[1,10]} + graftling ${GCOMMIT[1,10]}"
}
setup_project() {  # $1 project, $2 venv: GraphTraj's public setup, answering yes; prints its action lines
  (cd $1 && print -l y y | clean $2/bin/graphtraj setup 2>&1 | grep -vE '^\s*$' | tail -25 | sed 's/^/  setup: /')
}
ignore_state() {  # $1 project: what git ignores there now (read only)
  local P=$1 f
  print -r -- "  $P/.graphtraj/.gitignore: $([[ -f $P/.graphtraj/.gitignore ]] && print present || print absent)"
  for f in .graphtraj/runner/main-sessions/inbox/x.jsonl .graphtraj/state/x .graphtraj/config.yml notes-539.txt; do
    git -C $P check-ignore -q --no-index $f && print -r -- "  ignored:     $f" || print -r -- "  not ignored: $f"
  done
}
SHELL_GLOB='$HOME/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell'
browser_path() {
  [[ -n ${VERIFY539_BROWSER:-} ]] && { print -r -- $VERIFY539_BROWSER; return 0; }
  local shells=($HOME/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell(NnOn))
  (( $#shells )) && { print -r -- ${shells[1]}; return 0; }
  print -r -- "STOP: no cached Playwright headless shell found (searched $SHELL_GLOB). Google Chrome is not used automatically; set VERIFY539_BROWSER=<path to a headless browser>." >&2
  return 1
}
PROMPT_TEXT() {  # $1 tool. 537's G prompt (runtime claude, no model) + one step writing the user file notes-539.txt.
  print -r -- "Use the MCP tool $1. Do exactly these four steps and nothing else.
1. Call $1 with {\"action\": \"execute\", \"feature\": \"create\", \"arguments\": {\"runtime\": \"claude\", \"name\": \"echo539\", \"instruction\": \"Reply with the single word DONE and nothing else.\"}}. Use exactly these arguments; add no others and do not try other models.
2. Call $1 with {\"action\": \"execute\", \"feature\": \"send\", \"arguments\": {\"agent\": <the agent id that step 1 returned>, \"message\": \"## Report 539\\n\\n- first item\\n- second item with \`code span\`\\n\\nReply DONE.\"}}.
3. Create the file notes-539.txt in the workspace root containing the single line: user note.
4. Do not wait for the member. End your turn with exactly one line made of the two words SENT and 539 joined by a hyphen.
If step 1 or step 2 fails, call nothing else and end your turn with exactly one line made of the two words FAILED and 539 joined by a hyphen.
Later, when a notice says that this member ended or replied, answer it with exactly one line made of the three words GOT, NOTICE and 539 joined by hyphens, and nothing else."
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT $BASE/tmp

# ---- one headless case (as 537): start the server, drive the page, stop everything this step started ----
STARTED=()
descendants() { local p c; for p in "$@"; do for c in $(pgrep -P $p 2>/dev/null || true); do print $c; descendants $c; done; done; }
ours_by_base() { pgrep -f -- "$BASE/" 2>/dev/null | grep -vx -- "$$" || true; }
stop_started() {
  (( ${#STARTED} )) || return 0
  local all=(${STARTED} $(descendants ${STARTED}) $(ours_by_base)) p left=()
  all=(${(u)all}); all=(${all:#$$})
  print "stopping processes this step started: ${all}"
  for p in $all; do kill -TERM $p 2>/dev/null || true; done
  sleep 3
  for p in $all; do kill -0 $p 2>/dev/null && left+=$p; done
  for p in $left; do kill -KILL $p 2>/dev/null || true; done
  sleep 1; left=()
  for p in $all; do kill -0 $p 2>/dev/null && left+=$p; done
  local rest=($(ours_by_base))
  if (( ${#left} + ${#rest} )); then print "WARNING: still running: ${left} ${rest}"; else print "verified: none of them is running (and no process names $BASE/)"; fi
  STARTED=()
}
card_check() {  # $1 output directory: what the expanded page shows in the changes card
  local f=$1/04-expanded-full.txt
  [[ -f $f ]] || { print "card check: no 04-expanded-full.txt"; return 0; }
  print "card check ($f):"
  grep -nE 'Edited [0-9]+ file' $f | sed 's/^/  /' || print "  (no 'Edited N file(s)' line)"
  local gt=$(grep -c '\.graphtraj/' $f || true) nt=$(grep -c 'notes-539\.txt' $f || true)
  grep -n '\.graphtraj/' $f | sed 's/^/  /' || true
  print "  .graphtraj/ paths shown: $gt | notes-539.txt shown: $nt"
}
run_case() {  # $1 label before|after|repair
  local L=$1 R=$OUT/$1 cwd=$(project_of $1) V=$(venv_of $1) patch=$(patch_of $1) tool=mcp__graphtraj__agents url= t0=$SECONDS spid dpid i
  [[ -f $V/installed && -f $patch && -f $NODE/node_modules/playwright-core/package.json ]] || { print "STOP: run step 0 first"; return 1; }
  has_plugin || { print "STOP: graftling-dsh is not in $WEB; run step 0"; return 1; }
  load_key || return 1
  [[ -e $R ]] && mv $R $R.$(date +%H%M%S)
  mkdir -p $R
  rm -f $cwd/notes-539.txt   # the user file must be written in this turn
  PROMPT_TEXT $tool > $R/prompt.txt
  if grep -qE 'SENT-539|FAILED-539|GOT-NOTICE-539' $R/prompt.txt; then print "STOP: the prompt holds a literal marker"; return 1; fi
  say "[$L] GraphTraj DSH Main (graphtraj-main row, GraphTraj $(commit_of $L)), workspace $cwd, output $R"
  print "Dialog: none (headless browser; DSH's in-page directory dialog; in-page tool approvals clicked by the driver)."
  ignore_state $cwd
  trap 'stop_started' EXIT INT TERM
  (cd $cwd && exec env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$BASE/tmp \
     LANG=en_US.UTF-8 DSH_HOME=$DH DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY SSH_CONNECTION="127.0.0.1 1 127.0.0.1 1" \
     dsh --profile $WEB --patch $patch --port 0 --no-open) > $R/server.log 2>&1 &
  spid=$!; STARTED+=$spid
  print "server pid $spid (log $R/server.log)"
  for i in {1..180}; do
    url=$(grep -oE 'dsh web: https?://[^ ]+' $R/server.log 2>/dev/null | head -1 | cut -c10-) || url=
    [[ -n $url ]] && break
    kill -0 $spid 2>/dev/null || break
    sleep 0.5
  done
  if [[ -z $url ]]; then print "STOP: no 'dsh web:' URL within 90 s; server log tail:"; tail -15 $R/server.log | redact; stop_started; trap - EXIT INT TERM; return 1; fi
  print "served (token not shown): ${${url#*://}%%/*} after $(( SECONDS - t0 )) s"
  $V/bin/python -I -c 'import json, sys
url, ws, prompt, out, browser, pw, ts, ns = sys.argv[1:9]
json.dump({"url": url, "workspace": ws, "prompt": open(prompt).read().strip(), "out": out, "browser": browser,
  "playwright": pw, "sendMarker": "SENT-539", "failMarker": "FAILED-539", "noticeMarker": "GOT-NOTICE-539", "turnTimeoutS": int(ts), "noticeTimeoutS": int(ns)},
  open(out + "/driver.json", "w"), indent=2)' "$url" $cwd $R/prompt.txt $R "$(browser_path)" $NODE/node_modules/playwright-core $TURN_S $NOTICE_S
  (exec env -i HOME=$HOME PATH=${(j.:.)path} TMPDIR=$BASE/tmp LANG=en_US.UTF-8 node $SD/ui537.mjs $R/driver.json) > $R/driver.log 2>&1 &
  dpid=$!; STARTED+=$dpid
  print "headless driver pid $dpid (log $R/driver.log); waiting (bounded: ${TURN_S} s turn + ${NOTICE_S} s notice + slack)"
  local limit=$(( TURN_S + NOTICE_S + 180 )) waited=0
  while kill -0 $dpid 2>/dev/null && (( waited < limit )); do sleep 2; (( waited += 2 )); done
  kill -0 $dpid 2>/dev/null && print "WARNING: the driver did not end within $limit s; stopping it"
  local drc; wait $dpid 2>/dev/null && drc=0 || drc=$?
  print "driver exit: $drc"
  sed 's/token=[^ &]*/token=[redacted]/g' $R/driver.log | redact | tail -25
  $V/bin/python -I -c 'import json, sys; f = sys.argv[1]; d = json.load(open(f)); d["url"] = "[redacted: served URL with token]"
json.dump(d, open(f, "w"), indent=2)' $R/driver.json || true
  stop_started; trap - EXIT INT TERM
  print "notes-539.txt in the workspace after the turn: $([[ -f $cwd/notes-539.txt ]] && print present || print ABSENT)"
  { print "git status --porcelain --untracked-files=all in $cwd:"; git -C $cwd status --porcelain --untracked-files=all; } > $R/git-status.txt 2>&1
  sed 's/^/  /' $R/git-status.txt | head -20
  card_check $R
  print "case seconds: $(( SECONDS - t0 ))"
  print "files: $(cd $R && ls *.png *.txt 2>/dev/null | tr '\n' ' ')"
}

# ---- full suite (as verify-531 G/GR): <Harness>/tmp/539 venvs, new pytest temp root outside the Harness ----
check_tmp() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-539-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
t_venv() {  # $1 cand|base. Sets V (venv) and S (source tree: this Worktree, or git archive of base)
  local GS=${GCOMMIT[1,8]} N=$T/wheels-gl-${GCOMMIT[1,8]}
  if [[ $1 == cand ]]; then S=$WT; else S=$T/base-src-$BEFORE_COMMIT; fi
  V=$T/venv-t-$1
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $GSRC"; return 1; }
  if [[ $1 == base && ! -f $S/pyproject.toml ]]; then   # a Git checkout: the test fixtures run git ls-files in it
    rm -rf $S; mkdir -p $T
    git clone -q --shared --no-checkout $WT $S && git -C $S checkout -q --detach $BEFORE_COMMIT \
      || { print "STOP: cannot check out $BEFORE_COMMIT into $S"; return 1; }
  fi
  if [[ -x $V/bin/python && -f $V/installed && $(<$V/installed) == "$S $GCOMMIT" ]]; then print "reusing $V ($S editable; graftling $GS)"; return 0; fi
  rm -rf $V; mkdir -p $T
  if [[ ! -f $N/installed ]]; then
    rm -rf $N; wheel $GSRC $GCOMMIT src/graftling $N || { print "STOP: graftling wheel"; return 1; }; touch $N/installed
  fi
  $CONDA -m venv --system-site-packages $V && deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $S 2>&1 | grep -vi cache || true
  print -r -- "$S $GCOMMIT" > $V/installed
}
t_run() {  # $1 cand|base
  local V S RUNTMP
  if [[ $1 == cand ]]; then
    local dirty=$(git -C $WT status --porcelain -- src tests plugins)
    print "uncommitted in src/tests/plugins: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  fi
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later"; print -r -- $others; return 1; }
  new_runtmp $1 || return 1
  t_venv $1 || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  local R=$T/runs/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "$1: $S at $(git -C $WT rev-parse $([[ $1 == cand ]] && print HEAD || print $BEFORE_COMMIT)) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY539_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY539_TESTS (plain pytest, same venv, temp root and exit file); foreground" | tee -a $R/run.txt
    (cd $S && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY539_TESTS} > $R/suite.txt 2>&1 \
      && print "exit=0" >> $R/suite.txt || print "exit=$?" >> $R/suite.txt)
    tail -4 $R/suite.txt
  else
    (cd $S && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1 \
      && print "exit=0" >> $R/suite.txt || print "exit=$?" >> $R/suite.txt) &!
    print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends, ~25 min)"
  fi
  print -r -- $R > $T/runs/$1-latest
}
failures() { grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u; }

case $STEP in
0)
  say "[0] preflight (Main's Bash). Dialog: none. Two venvs (no network), project-before (setup by $BEFORE_COMMIT) and project-after (setup by $AFTER_COMMIT), isolated DSH home with $WEB + graftling-dsh, playwright-core, headless browser, one one-line model answer (at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); dsh $(clean dsh --version 2>&1 | tail -1) ($(command -v dsh)); node $(node --version 2>&1)"
  print "BEFORE GraphTraj $(git -C $WT rev-parse $BEFORE_COMMIT); AFTER (candidate) $(git -C $WT rev-parse $AFTER_COMMIT) (branch $(git -C $WT branch --show-current)); graftling ${GCOMMIT[1,10]} from $GSRC"
  print "isolated layout: BASE=$BASE, DSH_HOME=$DH (never ~/.dsh), web profile $WEB"
  mkdir -p $DH
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: $GSRC lacks graftling $GCOMMIT"; return 1; }
  build_venv before && build_venv after || return 1
  local L P V
  for L in before after; do
    P=$(project_of $L); V=$(venv_of $L)
    (cd $BASE && clean $V/bin/python -I -c 'import importlib.metadata as m, graphtraj; print("venv '$L': graftling", m.version("graftling"), "| graphtraj", graphtraj.__file__)')
    git_ws $P || return 1
    if [[ ! -f $P/.graphtraj/config.yml ]]; then say "public setup of $P by GraphTraj $(commit_of $L)"; setup_project $P $V || return 1
    else print "$P already set up"; fi
    (cd $P && clean $V/bin/python -I $WT/scripts/verify-514/prep514.py $P | grep -E 'roles OK|probe Task 1|STOP|Error') \
      || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
    ignore_state $P
    clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $(patch_of $L) >/dev/null
    llm_patch >> $(patch_of $L)
  done
  llm_patch > $BASE/llm.patch.yml
  say "isolated web profile $WEB in $DH, then graftling-dsh"
  if [[ ! -f $DH/profiles/$WEB/package.json ]]; then
    (cd $BASE && clean dsh --profile $WEB --from-default-profile web --dump-config > $BASE/web-dump-config.txt 2>&1) \
      && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $BASE/web-dump-config.txt; return 1; }
  else print "profile $WEB: present ($DH/profiles/$WEB)"; fi
  mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
  chmod +x $BASE/bin/pnpm
  if ! has_plugin; then
    print "graftling-dsh not in $WEB: dsh plugin add (inside a Claude sandbox this fails: pnpm store lock EPERM)"
    (cd $BASE && clean PATH=$BASE/bin:${(j.:.)path} npm_config_store_dir=$BASE/pnpm-store $BOUND 300 \
       dsh plugin --profile $WEB add $(gdsh) > $BASE/plugin-add.txt 2>&1) && print "dsh plugin add: rc 0" \
      || { print "dsh plugin add failed (rc $?):"; grep -vi npmrc $BASE/plugin-add.txt | grep -v '^ *$' | tail -4 | sed 's/^/  /'; }
  fi
  if ! has_plugin; then
    print -r -- "STOP: graftling-dsh is not in web profile $WEB. If Main's Bash cannot add it, this one line in a plain Terminal
adds it (dialog: none):
  $(plugin_cmd)
Then rerun: zsh $THIS 0"
    return 1
  fi
  print "graftling-dsh: in $WEB"
  for L in before after; do
    (cd $(project_of $L) && clean dsh --profile $WEB --patch $(patch_of $L) --dump-config > $BASE/G-$L-dump-config.txt 2>&1) || print "G $L dump-config rc=$?"
    print "G $L rows: $(grep -oE '^- id: (graphtraj-main|llm-deepseek)$' $BASE/G-$L-dump-config.txt | cut -c7- | tr '\n' ' ')(expected llm-deepseek graphtraj-main)"
  done
  say "playwright-core $PWVER in $NODE (no browser download) and the headless browser"
  if [[ ! -f $NODE/node_modules/playwright-core/package.json ]]; then
    mkdir -p $NODE; print '{"private": true}' > $NODE/package.json
    local -a netenv; local v
    for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy NODE_EXTRA_CA_CERTS SSL_CERT_FILE; do
      [[ -n ${(P)v:-} ]] && netenv+=("$v=${(P)v}"); done
    (cd $NODE && clean $netenv npm_config_cache=$BASE/npm-cache PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 $BOUND 300 \
      npm install --no-audit --no-fund --ignore-scripts playwright-core@$PWVER > $BASE/npm-install.txt 2>&1) \
      || { print "STOP: npm install playwright-core failed:"; tail -5 $BASE/npm-install.txt; return 1; }
  fi
  print "playwright-core: $(node -p "require('$NODE/node_modules/playwright-core/package.json').version")"
  local B; B=$(browser_path) || return 1
  print "browser: $B"
  (cd $BASE && clean $BOUND 60 node -e '
const { chromium } = require(process.argv[1]);
(async () => { const b = await chromium.launch({ executablePath: process.argv[2], headless: true, args: ["--disable-crash-reporter", "--disable-breakpad", "--crash-dumps-dir=" + process.env.TMPDIR + "/crash"] });
  const p = await b.newPage(); await p.setContent("<p>ok-539</p>"); console.log("headless browser:", b.version(), await p.innerText("p")); await b.close(); })()
  .catch((e) => { console.error("headless browser failed:", e.message); process.exit(1); });' $NODE/node_modules/playwright-core "$B") || { print "STOP: the headless browser did not start"; return 1; }
  if [[ -n ${VERIFY539_NOMODEL:-} ]]; then print "VERIFY539_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    print "configured model (agent-default-model row): $(grep -A4 '^- id: agent-default-model$' $BASE/G-after-dump-config.txt | grep -E 'provider:|model:' | tr -s ' \n' ' ')"
    (cd $BASE && clean $BOUND 120 dsh --profile headless --patch $BASE/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-539, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  fi
  print "READY when: both venv lines, 'roles OK' + 'probe Task 1 ready' for both projects, project-before .gitignore absent and"
  print "  project-after present (runner/state ignored there, config.yml and notes-539.txt not), graftling-dsh in $WEB,"
  print "  both G rows, the headless browser line, one READY-539 line naming the model."
  print -r -- "next (Main's Bash, in this order; each case starts and stops its own server + headless browser, no user action):
  zsh $THIS B
  zsh $THIS A
  zsh $THIS AR
  zsh $THIS C
full suite (quiet host, any time): zsh $THIS T ; zsh $THIS TB ; then zsh $THIS TR"
  ;;
B)
  run_case before || return 1
  print "Expected (BEFORE): notes-539.txt and .graphtraj/ inbox path(s) in the card."
  print -r -- "next: zsh $THIS A"
  ;;
A)
  run_case after || return 1
  print "Expected (AFTER): notes-539.txt shown, '.graphtraj/ paths shown: 0'."
  print -r -- "next: zsh $THIS AR"
  ;;
AR)
  [[ -d $OUT/before ]] || { print "STOP: run B first (AR re-sets-up B's project)"; return 1; }
  local P=$(project_of repair)
  say "[AR] re-setup of $P (first set up by $BEFORE_COMMIT) with the candidate's public setup. Dialog: none."
  ignore_state $P
  setup_project $P $(venv_of after) | tee $BASE/repair-setup.txt || return 1
  grep -q 'Ignore GraphTraj runtime files' $BASE/repair-setup.txt && print "setup listed the GraphTraj ignore action" || print "WARNING: setup output does not name 'Ignore GraphTraj runtime files'"
  ignore_state $P
  run_case repair || return 1
  cp -p $BASE/repair-setup.txt $OUT/repair/setup.txt
  print "Expected (REPAIR): setup REGISTERs the ignore; the card shows notes-539.txt and '.graphtraj/ paths shown: 0'."
  print -r -- "next: zsh $THIS C"
  ;;
C)
  local D=${VERIFY539_REALHOST:-$WT/.state/realhost} L f
  say "[C] (read only on BASE) copy shots + redacted text to $D/ as before-*, after-*, repair-*. Dialog: none."
  mkdir -p $D
  for L in before after repair; do
    [[ -d $OUT/$L ]] || { print "no $OUT/$L (step not run)"; continue; }
    for f in $OUT/$L/*.(png|txt|json|log)(N); do
      [[ ${f:t} == server.log ]] && continue
      if [[ $f == *.png ]]; then cp -p $f $D/$L-${f:t}; else sed 's/token=[^ &"]*/token=[redacted]/g' $f | redact > $D/$L-${f:t}; fi
    done
    card_check $OUT/$L | sed "s/^/$L /"
  done
  ls -l $D | awk 'NR>1 {print "  " $5 "\t" $9}'
  print "Main and the Leader read before-/after-/repair-04-expanded-full.png (and 03-before-expand.png) with the Read tool; the conclusion is only what they show."
  ;;
T|TB)
  local which=$([[ $STEP == T ]] && print cand || print base)
  say "[$STEP] full suite of the $which ($([[ $which == cand ]] && print "Worktree HEAD $(git -C $WT rev-parse --short HEAD)" || print "base $BEFORE_COMMIT")), venvs under $T. Dialog: none. Run nothing else meanwhile."
  t_run $which || return 1
  print -r -- "next: $([[ $STEP == T ]] && print "zsh $THIS TB" || print "zsh $THIS TR") (TR after both suite.txt end with exit=)"
  ;;
TR)
  say "[TR] read only: candidate vs base 9ae7a149 FAILED/ERROR lines; NEW = failing on the candidate only. Dialog: none."
  local c=$(cat $T/runs/cand-latest 2>/dev/null) b=$(cat $T/runs/base-latest 2>/dev/null) line any=0
  [[ -n $c && -f $c/suite.txt && -n $b && -f $b/suite.txt ]] || { print -r -- "need both runs: zsh $THIS T ; zsh $THIS TB"; return 0; }
  for r in $c $b; do print -r -- "---- $r"; cat $r/run.txt; tail -3 $r/suite.txt; grep -q '^exit=' $r/suite.txt || print "still running"; done
  local base_fail=$(failures $b/suite.txt $b/shards/*(N.))
  for line in ${(f)"$(failures $c/suite.txt $c/shards/*(N.))"}; do
    any=1
    if print -r -- $base_fail | grep -qxF -- $line; then print -r -- "known (fails on base too): $line"
    elif grep -qF -- "${${line#* }%%\[*}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines on the candidate)"
  print "Success: no 'NEW' line."
  ;;
*) print -r -- "usage: zsh $THIS 0|B|A|AR|C|T|TB|TR"; return 2 ;;
esac
