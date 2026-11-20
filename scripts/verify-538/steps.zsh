#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 538 steps (from 537's verify-537 at 6317b20d): the GraphTraj notice block in DSH, captured by a HEADLESS browser
# with no user action. Each case starts an isolated DSH web server in the background (SSH_CONNECTION set, so DSH mounts
# its in-page "Select Workspace Directory" dialog; --no-open), drives it with playwright-core + Playwright's cached
# chromium_headless_shell only (or an explicit VERIFY538_BROWSER), saves screenshots + page text, and stops only the
# processes it started.
#   zsh scripts/verify-538/steps.zsh <STEP>        (Main's Bash, from this Task's Worktree)
# Order: 00 -> B -> (candidate) A -> T -> TR -> C
#   00  preflight: zsh/git/dsh/node/claude versions; playwright-core + headless browser; each host answers a one-line
#       prompt with its configured model and login (DSH: deepseek-flash; Claude Code: the G child's
#       claude-opus-5-5); builds the BEFORE phase (venv, git project with roles OK + probe Task 1, standalone
#       workspace, DSH_HOME with web538 + graftling-dsh). READY line.
#   B   BEFORE = GraphTraj dev $GTBASE + graftling dev $GLBASE: G (GraphTraj DSH Main) and S (graftling alone), run1.
#   A   AFTER = this Worktree's HEAD + graftling $GLC (clone $GLREPO): builds that phase, then G and S run1, then the
#       same again as run2 on the same commits, and compares run1 with run2.
#   T   full GraphTraj suite of the AFTER build (background, 6 shards; TMPDIR=${TMPDIR:-/tmp}, outside the Harness);
#       TR reads it (read only). VERIFY538_TESTS=<files> runs plain pytest on those files instead (rehearsal).
#   C   (read only on BASE) copies shots + redacted text to <Worktree>/.state/realhost/ and prints the tables.
# Everything real-host is under BASE=/private/tmp/dsh-ui-538/<phase> (outside the Harness): DSH_HOME, projects, venvs.
# The user's DSH install, ~/.dsh, browser profile and dotfiles are never written. No step starts or connects to the
# Harness's production MCP servers.
emulate -L zsh
setopt err_return pipe_fail no_unset no_bg_nice
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY538_WT:-$(git -C $SD rev-parse --show-toplevel)}   # this Task Worktree
H=${VERIFY538_H:-${WT:h:h:h:h}}                                # <Harness>
GTBASE=9ae7a1491f49816687a4f7f481f7fabc57981f85                # GraphTraj dev the Worktree branched from (536 integrated)
GLBASE=fc081a3f1cf2664f603d4deba14a86d59a16fd8f                # graftling dev (536)
GLSRC=$H/graftling                                             # read only (git archive of $GLBASE)
GLREPO=${VERIFY538_GLREPO:-$WT/.scratch/graftling}             # untracked clone, branch agent/538-dsh-graphtraj-notice-block-display
GLC=${VERIFY538_GLC:-70542bc58fa69cfb6fb62bdf5f5cb0b8046646ec} # candidate graftling (clone branch agent/538-dsh-graphtraj-notice-block-display)
BASE=${VERIFY538_BASE:-/private/tmp/dsh-ui-538}
NODE=$BASE/node
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages               # read only: yaml, websockets, click, pytest for T
STEP=${1:-}
MODEL=deepseek-flash
CLAUDE_MODEL=claude-opus-5-5                                   # the G child (the project's only claude role)
WEB=web538
PWVER=1.65.1                                                   # playwright-core (npm); drives the browser, downloads none
TURN_S=${VERIFY538_TURN_S:-300}; NOTICE_S=${VERIFY538_NOTICE_S:-300}; SETTLE_S=${VERIFY538_SETTLE_S:-20}
VIEW_H=${VERIFY538_VIEW_H:-2600}
PYTEST_TMP=${TMPDIR:-/tmp}
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
rd() { [[ -f $1 ]] && print -r -- "$(<$1)"; }      # a file's text, or nothing (status 1) when it is missing
next() { print -r -- "
==> next (paste as is): $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Phase layout: PH=before|after; every per-phase path hangs off PB.
phase_vars() {
  PH=$1; PB=$BASE/$PH
  P=$PB/project; W=$PB/work-standalone; V=$PB/venv; DH=$PB/dsh-home; OUT=$PB/runs; GROOT_US=$W/graftling-data
  if [[ $PH == before ]]; then GT_REPO=$WT GT=$GTBASE GL_REPO=$GLSRC GL=$GLBASE
  else GT_REPO=$WT GT=$(git -C $WT rev-parse HEAD) GL_REPO=$GLREPO GL=$GLC; fi
}
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$BASE/tmp \
  LANG=${LANG:-en_US.UTF-8} DSH_HOME=${DH:-$BASE/dsh-home-00} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
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
gdsh() { $V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
llm_patch() {
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
has_plugin() {
  [[ -n ${VERIFY538_ASSUME_PLUGIN:-} ]] && { print "REHEARSAL: graftling-dsh assumed present in $WEB" >&2; return 0; }
  grep -q '"graftling-dsh"' $DH/profiles/$WEB/package.json 2>/dev/null
}
plugin_cmd() {
  print -r -- "cd $BASE && env DSH_HOME=$DH PATH=$BASE/bin:/opt/homebrew/bin:\$PATH npm_config_store_dir=$BASE/pnpm-store $(command -v dsh) plugin --profile $WEB add $(gdsh)"
}
git_ws() {  # $1 directory, $2 label: a git work tree with one commit
  [[ -d $1/.git ]] && return 0
  mkdir -p $1; (cd $1 && git init -q -b main && print -r -- "# 538 $2" > README.md && git add README.md \
    && git -c user.name=538 -c user.email=538@invalid commit -qm "Initial source")
}
SHELL_GLOB='$HOME/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell'
browser_path() {  # VERIFY538_BROWSER, else ONLY the newest cached Playwright headless shell (no Google Chrome fallback)
  [[ -n ${VERIFY538_BROWSER:-} ]] && { print -r -- $VERIFY538_BROWSER; return 0; }
  local shells=($HOME/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell(NnOn))
  (( $#shells )) && { print -r -- ${shells[1]}; return 0; }
  print -r -- "STOP: no cached Playwright headless shell found (searched $SHELL_GLOB). Google Chrome is not used automatically; set VERIFY538_BROWSER=<path to a headless browser> explicitly." >&2
  return 1
}
PROMPT_TEXT() {  # $1 tool, $2 child runtime, $3 child model ('' = none). Markers are spelled as words (537 c4).
  # G: runtime claude and NO model (GraphTraj's Task-free driver takes no selection; graftling refuses a create naming
  # a model or connection, control.py ~788); it resolves to the project's only claude role. S: graftling's dsh driver.
  # 538: the member answers in multi-line Markdown (heading, list, code block) both times.
  local margs="\"runtime\": \"$2\", "; [[ -n $3 ]] && margs+="\"model\": \"$3\", "
  local reply='Reply with exactly this Markdown and nothing else: a level-2 heading Result 538, a blank line, a two-item bullet list (alpha, beta), a blank line, and a fenced code block holding the line: echo 538'
  # 538 round 1 (after Main's B on f15f20fd): G's send right after create was refused with runtime-input-closed
  # (graftling claude/execution.py:1270) while the create execution was still finishing, so step 2 waits for that
  # execution to end first; and one rule says what to do when a notice comes before the turn ends (S's Think was torn
  # between the two markers). B's recorded run used the f15f20fd prompt.
  print -r -- "Use the MCP tool $1. Do exactly these four steps and nothing else.
1. Call $1 with {\"action\": \"execute\", \"feature\": \"create\", \"arguments\": {${margs}\"name\": \"echo538\", \"instruction\": \"$reply\"}}. Use exactly these arguments; add no others and do not try other models.
2. Call $1 with {\"action\": \"execute\", \"feature\": \"wait\", \"arguments\": {\"agent\": <the agent id that step 1 returned>, \"timeout_seconds\": 180}}, so the member's first reply has ended before you send.
3. Call $1 with {\"action\": \"execute\", \"feature\": \"send\", \"arguments\": {\"agent\": <the same agent id>, \"message\": \"## Report 538\\n\\n- first item\\n- second item with \`code span\`\\n\\n\`\`\`text\\nline one\\nline two\\n\`\`\`\\n\\nReply in the same Markdown form as before.\"}}.
4. Do not wait for the member after step 3. End your turn with exactly one line made of the two words SENT and 538 joined by a hyphen.
If step 1, 2 or 3 fails, call nothing else and end your turn with exactly one line made of the two words FAILED and 538 joined by a hyphen.
Notice rule: each notice saying that this member ended or replied gets exactly one line made of the three words GOT, NOTICE and 538 joined by hyphens, and nothing else. If such a notice arrives before you have written the step 4 line, write only that notice line and end your turn; do not write the step 4 line after it."
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || [[ -n ${VERIFY538_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/tmp

# ---- one phase's build: venv from exact commits, project (roles + probe Task 1), standalone workspace, DSH_HOME ----
build_phase() {  # $1 before|after
  phase_vars $1
  [[ -n $GL ]] || { print "STOP: no candidate graftling commit (VERIFY538_GLC / GLC in $THIS)"; return 1; }
  git -C $GL_REPO cat-file -e $GL^{commit} || { print "STOP: $GL_REPO lacks graftling $GL"; return 1; }
  git -C $GT_REPO cat-file -e $GT^{commit} || { print "STOP: $GT_REPO lacks GraphTraj $GT"; return 1; }
  say "[$PH] build GraphTraj ${GT[1,10]} + graftling ${GL[1,10]} under $PB (DSH_HOME=$DH, never ~/.dsh)"
  mkdir -p $PB $OUT $DH
  local Wh=$PB/wheels
  if [[ ! -f $V/installed || $(<$V/installed) != "$GT $GL" ]]; then
    mkdir -p $Wh; rm -f $Wh/graftling-*.whl(N) $Wh/graphtraj-*.whl(N)
    wheel $GL_REPO $GL src/graftling $Wh && wheel $GT_REPO $GT . $Wh || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $Wh 'graftling-*.whl') && hw=$(need $Wh 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V; deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw $hw
    print -r -- "$GT $GL" > $V/installed
  else print "venv $V already holds GraphTraj ${GT[1,10]} + graftling ${GL[1,10]}"; fi
  (cd $PB && clean $V/bin/python -I -c 'import importlib.metadata as m; print("venv: graftling", m.version("graftling"), "| graphtraj", m.version("graphtraj"))')
  git_ws $P project || return 1
  if [[ ! -f $P/.graphtraj/config.yml ]]; then (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1; fi
  (cd $P && clean $V/bin/python -I $WT/scripts/verify-514/prep514.py $P | grep -E 'roles OK|probe Task 1|STOP|Error') \
    || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
  git_ws $W standalone || return 1
  llm_patch > $PB/llm.patch.yml
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $PB/graphtraj-main.patch.yml >/dev/null
  llm_patch >> $PB/graphtraj-main.patch.yml
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $GROOT_US $(command -v dsh) $MODEL $PB/dsh-host.json
  if [[ ! -f $DH/profiles/$WEB/package.json ]]; then
    (cd $PB && clean dsh --profile $WEB --from-default-profile web --dump-config > $PB/web-dump-config.txt 2>&1) \
      && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $PB/web-dump-config.txt; return 1; }
  else print "profile $WEB: present ($DH/profiles/$WEB)"; fi
  mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
  chmod +x $BASE/bin/pnpm
  # the plugin is added from this venv's graftling/dsh; the record names that path, so a rebuilt venv re-adds it
  local want=$(gdsh)
  if ! has_plugin || [[ $(rd $PB/plugin-source) != "$want $GL" ]]; then
    print "dsh plugin add graftling-dsh from $want"
    (cd $PB && clean PATH=$BASE/bin:${(j.:.)path} npm_config_store_dir=$BASE/pnpm-store $BOUND 300 \
       dsh plugin --profile $WEB add $want > $PB/plugin-add.txt 2>&1) && { print "dsh plugin add: rc 0"; print -r -- "$want $GL" > $PB/plugin-source; } \
      || { print "dsh plugin add failed (rc $?):"; grep -vi npmrc $PB/plugin-add.txt | grep -v '^ *$' | tail -4 | sed 's/^/  /'; }
  fi
  if ! has_plugin; then
    print -r -- "STOP: graftling-dsh is not in web profile $WEB of $DH. This one line in a plain Terminal adds it (dialog: none):
  $(plugin_cmd)
Then rerun this step."
    return 1
  fi
  print "graftling-dsh: in $WEB ($(rd $PB/plugin-source || print 'source not recorded'))"
  (cd $W && clean dsh --profile $WEB --patch $PB/llm.patch.yml --dump-config > $PB/S-dump-config.txt 2>&1) || print "S dump-config rc=$?"
  (cd $P && clean dsh --profile $WEB --patch $PB/graphtraj-main.patch.yml --dump-config > $PB/G-dump-config.txt 2>&1) || print "G dump-config rc=$?"
  print "S rows: $(grep -oE '^- id: (agents-host|llm-deepseek)$' $PB/S-dump-config.txt | cut -c7- | tr '\n' ' ')(expected agents-host llm-deepseek)"
  print "G rows: $(grep -oE '^- id: (graphtraj-main|llm-deepseek)$' $PB/G-dump-config.txt | cut -c7- | tr '\n' ' ')(expected llm-deepseek graphtraj-main)"
}

# ---- one headless case: start the server, drive the page, stop everything this step started ----
STARTED=()        # PIDs this step started (server, driver)
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
run_case() {  # $1 G|S, $2 run label (run1|run2); phase_vars already set
  local c=$1 R=$OUT/$2/$1 cwd patch tool url= t0=$SECONDS spid dpid i
  local -a envs
  [[ -f $V/installed && -f $PB/llm.patch.yml && -f $NODE/node_modules/playwright-core/package.json ]] \
    || { print "STOP: the $PH phase is not built or step 00 was not run"; return 1; }
  has_plugin || { print "STOP: graftling-dsh is not in $WEB of $DH"; return 1; }
  load_key || return 1
  if [[ $c == G ]]; then cwd=$P patch=$PB/graphtraj-main.patch.yml tool=mcp__graphtraj__agents envs=()
  else cwd=$W patch=$PB/llm.patch.yml tool=mcp__graftling__agents
    envs=(GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$PB/dsh-host.json); fi
  [[ -e $R ]] && mv $R $R.$(date +%H%M%S)
  mkdir -p $R
  if [[ $c == G ]]; then PROMPT_TEXT $tool claude '' > $R/prompt.txt; else PROMPT_TEXT $tool dsh $MODEL > $R/prompt.txt; fi
  if grep -qE 'SENT-538|FAILED-538|GOT-NOTICE-538' $R/prompt.txt; then print "STOP: the prompt holds a literal marker"; return 1; fi
  print -r -- "$PH $c $2 GraphTraj $GT graftling $GL" > $R/build.txt
  say "[$PH $c/$2] $([[ $c == G ]] && print 'GraphTraj DSH Main (graphtraj-main row)' || print 'graftling alone (graftling-dsh agents-host row)'), workspace $cwd, $tool, output $R"
  trap 'stop_started' EXIT INT TERM
  (cd $cwd && exec env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$BASE/tmp \
     LANG=en_US.UTF-8 DSH_HOME=$DH DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY SSH_CONNECTION="127.0.0.1 1 127.0.0.1 1" $envs \
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
url, ws, prompt, out, browser, pw, ts, ns, ss, vh = sys.argv[1:11]
json.dump({"url": url, "workspace": ws, "prompt": open(prompt).read().strip(), "out": out, "browser": browser,
  "playwright": pw, "sendMarker": "SENT-538", "failMarker": "FAILED-538", "noticeMarker": "GOT-NOTICE-538",
  "turnTimeoutS": int(ts), "noticeTimeoutS": int(ns), "settleS": int(ss), "viewportHeight": int(vh)},
  open(out + "/driver.json", "w"), indent=2)' "$url" $cwd $R/prompt.txt $R "$(browser_path)" $NODE/node_modules/playwright-core $TURN_S $NOTICE_S $SETTLE_S $VIEW_H
  (exec env -i HOME=$HOME PATH=${(j.:.)path} TMPDIR=$BASE/tmp LANG=en_US.UTF-8 node $SD/ui538.mjs $R/driver.json) > $R/driver.log 2>&1 &
  dpid=$!; STARTED+=$dpid
  print "headless driver pid $dpid (log $R/driver.log); waiting (bounded: ${TURN_S} s turn + ${NOTICE_S} s notice + slack)"
  local limit=$(( TURN_S + NOTICE_S + SETTLE_S + 240 )) waited=0
  while kill -0 $dpid 2>/dev/null && (( waited < limit )); do sleep 2; (( waited += 2 )); done
  kill -0 $dpid 2>/dev/null && print "WARNING: the driver did not end within $limit s; stopping it"
  local drc; wait $dpid 2>/dev/null && drc=0 || drc=$?   # a failing driver must not end the step before its log
  print "driver exit: $drc"
  sed 's/token=[^ &]*/token=[redacted]/g' $R/driver.log | redact | tail -14
  $V/bin/python -I -c 'import json, sys; f = sys.argv[1]; d = json.load(open(f)); d["url"] = "[redacted: served URL with token]"
json.dump(d, open(f, "w"), indent=2)' $R/driver.json || true
  stop_started; trap - EXIT INT TERM
  print "case seconds: $(( SECONDS - t0 ))"
  print "files: $(cd $R && ls *.png 2>/dev/null | tr '\n' ' ')"
}
table() { $CONDA -I $SD/table538.py $1/runs; }   # $1 phase dir: per case and run, from summary.json + observed.json

case $STEP in
00)
  say "[00] preflight (Main's Bash). Dialog: none expected (the Bash approval of this command only). ~3-6 min on the first run."
  print "zsh $ZSH_VERSION ($(command -v zsh)); this script runs under zsh: ${ZSH_NAME:-?}"
  print "$(git --version); conda $($CONDA --version 2>&1); dsh $(dsh --version 2>&1 | tail -1) ($(command -v dsh)); node $(node --version 2>&1); claude $(claude --version 2>&1 | head -1)"
  print "Worktree $WT HEAD $(git -C $WT rev-parse HEAD) (branch $(git -C $WT branch --show-current))"
  print "BEFORE: GraphTraj ${GTBASE[1,10]} + graftling ${GLBASE[1,10]} ($GLSRC); AFTER: Worktree HEAD + graftling ${GLC:-(not set yet)} ($GLREPO)"
  print "isolated layout: BASE=$BASE/<before|after> (DSH_HOME, projects, venvs; never ~/.dsh), web profile $WEB"
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
  local B
  if [[ -n ${VERIFY538_NOBROWSER:-} ]]; then print "REHEARSAL (VERIFY538_NOBROWSER): headless browser check skipped"
  else B=$(browser_path) || return 1
  (cd $BASE && clean $BOUND 60 node -e '
const { chromium } = require(process.argv[1]);
(async () => { const b = await chromium.launch({ executablePath: process.argv[2], headless: true, args: ["--disable-crash-reporter", "--disable-breakpad", "--crash-dumps-dir=" + process.env.TMPDIR + "/crash"] });
  const p = await b.newPage(); await p.setContent("<p>ok-538</p>"); console.log("headless browser:", b.version(), await p.innerText("p")); await b.close(); })()
  .catch((e) => { console.error("headless browser failed:", e.message); process.exit(1); });' $NODE/node_modules/playwright-core "$B") || { print "STOP: the headless browser did not start"; return 1; }
  fi
  build_phase before || return 1
  if [[ -n ${VERIFY538_NOMODEL:-} ]]; then print "VERIFY538_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    say "host 1/2: DSH (the Main of G and S, and the S child) answers one line (at most 120 s)"
    print "configured model (agent-default-model row): $(grep -A4 '^- id: agent-default-model$' $PB/S-dump-config.txt | grep -E 'provider:|model:' | tr -s ' \n' ' ')"
    (cd $PB && clean $BOUND 120 dsh --profile headless --patch $PB/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-538-DSH, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$? (142 = 120 s timeout)"
    say "host 2/2: Claude Code (the G child, role claude -> $CLAUDE_MODEL) answers one line in the isolated project (at most 120 s)"
    (cd $P && clean $BOUND 120 claude -p --model $CLAUDE_MODEL \
      'Reply with one line: READY-538-CLAUDE, your exact model id, and the login or account type you answer through (for example Claude subscription or API key). Use no tool.' \
      < /dev/null 2>&1 | tail -2) || print "claude rc=$? (142 = 120 s timeout)"
  fi
  print "READY when: 'headless browser:' line, venv line, 'roles OK' + 'probe Task 1 ready', 'graftling-dsh: in $WEB', S rows agents-host llm-deepseek, G rows llm-deepseek graphtraj-main, one READY-538-DSH line naming the model, one READY-538-CLAUDE line naming $CLAUDE_MODEL and the login."
  next "zsh $THIS B"
  ;;
B)
  say "[B] BEFORE: GraphTraj ${GTBASE[1,10]} + graftling ${GLBASE[1,10]}; G then S (run1). Dialog: none (headless; in-page directory dialog; no default-browser launch). ~2-12 min."
  build_phase before || return 1
  local rc=0
  run_case G run1 || rc=1
  run_case S run1 || rc=1
  say "[B] observables (a: agents rows with IN; b: notice blocks; sender/duplicates/Markdown source)"
  table $PB
  print "Proof: (a) a-send-card.png with IN shown; (b) b-notice*.png (S: b-notice-region.png when the notice came inside the turn); full pages 04-expanded-full.png. Main and the Leader look at the images."
  next "zsh $THIS C"
  return $rc
  ;;
A)
  say "[A] AFTER: Worktree HEAD $(git -C $WT rev-parse --short HEAD) + graftling ${GLC[1,10]:-?}; G and S run1, then run2 on the same commits, then the comparison. Dialog: none. ~5-25 min."
  build_phase after || return 1
  local rc=0
  run_case G run1 || rc=1
  run_case S run1 || rc=1
  run_case G run2 || rc=1
  run_case S run2 || rc=1
  say "[A] run1 vs run2 (same commits)"
  table $PB
  print "Same result when run1 and run2 reach the same phases and show the same (a)/(b) observables per case."
  next "zsh $THIS C"
  return $rc
  ;;
T)
  setopt local_options no_bg_nice
  say "[T] full GraphTraj suite of the AFTER build (Worktree HEAD + graftling ${GLC[1,10]:-?}), 6 shards, --timeout 1500, -rA, in the background (~25 min). Dialog: none. pytest TMPDIR=$PYTEST_TMP (outside the Harness)."
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  build_phase after > $BASE/T-build.txt 2>&1 || { tail -5 $BASE/T-build.txt; print "STOP: the AFTER build failed ($BASE/T-build.txt)"; return 1; }
  print "AFTER build: $(grep -E '^venv:' $BASE/T-build.txt)"
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  print "uncommitted in src/tests/plugins: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  # as verify-531 g_venv: conda's site packages (pytest) + production's deps + the AFTER graftling wheel + this
  # Worktree editable (pyproject's pythonpath points pytest at this Worktree's src)
  local TV=$PB/venv-tests
  if [[ ! -f $TV/installed || $(<$TV/installed) != "$GT $GL" ]]; then
    rm -rf $TV; $CONDA -m venv --system-site-packages $TV && deps $TV || return 1
    $TV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(need $PB/wheels 'graftling-*.whl') || return 1
    $TV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache || true
    print -r -- "$GT $GL" > $TV/installed
  fi
  local RUNTMP=$PYTEST_TMP/graphtraj-538-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
  local d=$RUNTMP; while [[ $d != / ]]; do [[ -e $d/.graphtraj ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker"; return 1; }; d=${d:h}; done
  (cd $RUNTMP && $TV/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  local R=$PB/suite-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root (outside the Harness): $RUNTMP"; print -r -- "candidate: $GT | graftling $GL"; } | tee $R/run.txt
  if [[ -n ${VERIFY538_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY538_TESTS (plain pytest, same venv, temp root and exit file)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $TV/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY538_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  else
    (cd $WT && TMPDIR=$RUNTMP nohup $TV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  fi
  print -r -- $R > $BASE/T-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  next "zsh $THIS TR    (when $R/suite.txt ends with exit=)"
  ;;
TR)
  say "[TR] read only: the newest T result; FAILED/ERROR lines listed for comparison with dev (516's list does not block). Dialog: none."
  local R=$(cat $BASE/T-latest 2>/dev/null)
  [[ -n $R && -f $R/suite.txt ]] || { print "no T result yet; run: zsh $THIS T"; return 0; }
  cat $R/run.txt; tail -4 $R/suite.txt
  grep -q '^exit=' $R/suite.txt || print "T still running (no exit= line yet)"
  local K516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $R/suite.txt $R/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $K516 2>/dev/null; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
  print "Success: exit=0, or only 'known (516)' lines; any 'NEW' line goes to the Leader."
  next "zsh $THIS C"
  ;;
C)
  local D=${VERIFY538_REALHOST:-$WT/.state/realhost} ph run c f
  say "[C] (read only on BASE) copy shots + redacted text to $D/. Dialog: none."
  mkdir -p $D
  for ph in before after; do for run in run1 run2; do for c in G S; do
    [[ -d $BASE/$ph/runs/$run/$c ]] || continue
    for f in $BASE/$ph/runs/$run/$c/*.(png|txt|json|log)(N); do
      [[ ${f:t} == server.log ]] && continue
      if [[ $f == *.png ]]; then cp -p $f $D/$ph-$run-$c-${f:t}; else sed 's/token=[^ &"]*/token=[redacted]/g' $f | redact > $D/$ph-$run-$c-${f:t}; fi
    done
  done; done; done
  local R=$(cat $BASE/T-latest 2>/dev/null)
  [[ -n $R && -f $R/suite.txt ]] && { cp $R/run.txt $D/T-run.txt; tail -40 $R/suite.txt > $D/T-suite-tail.txt; }
  ls $D | grep -E '\.png$' | sed 's/^/  /'
  for ph in before after; do [[ -d $BASE/$ph/runs ]] && { say "$ph"; table $BASE/$ph; }; done
  print "Main and the Leader look at <phase>-run1-<case>-a-send-card.png, -b-notice*.png and -04-expanded-full.png (Read tool); the conclusion is only what they show."
  ;;
*) print -r -- "usage: zsh $THIS 00|B|A|T|TR|C"; return 2 ;;
esac
