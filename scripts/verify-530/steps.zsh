#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 530 steps: does the FIRST agents call on a BRAND-NEW graftling data root inside a git workspace make DSH's
# per-turn changes card ('…を編集しました') list graftling/GraphTraj runtime files (root config.yml, live/config.lock, …)?
# Copied from verify-526 (accepted; in-page workspace add/select step 1b) and adapted. Two builds:
#   BEFORE = graftling 4a002129 (v0.6.2, production) + GraphTraj c917f5fc (this Worktree's base)
#   AFTER  = graftling 95cffda1 (530: live/ ignores itself before config.lock) + GraphTraj 974cb8e9 (530: GraphTraj's
#            own .graphtraj/swarm gets a '*' .gitignore before its config.yml is written)
# Each build has its OWN fresh git project and git standalone workspace; no data root exists before its UG/US turn.
#   zsh scripts/verify-530/steps.zsh <STEP>        (from this Task's Worktree)
# Order: 0 (Main) -> UG, US (USER, BEFORE) -> C (Main) -> UG2, US2 (USER, AFTER) -> C2 (Main) -> T (Main) -> TR (Main).
#   0    preflight for both builds: wheels, venvs, git projects (graphtraj setup, roles OK, probe Task 1), git standalone
#        workspaces, web530 + graftling-dsh, one READY line; STOPs when any graftling data root already exists.
#   UG   USER: GraphTraj DSH Main (graphtraj-main row), BEFORE project; first mcp__graphtraj__agents call.
#   US   USER: graftling alone (graftling-dsh agents-host row), BEFORE standalone workspace; first mcp__graftling__agents.
#   C    Main (read only): screenshots, workspace/changes events per DSH session file, files under each root with
#        birth/modify times, git status lines under each root (now vs. the record step 0 took).
#   UG2, US2, C2: the same on the AFTER build's own fresh project/workspace.
#   T    Main: graftling full suite on 4a002129 and on 95cffda1, then GraphTraj full suite (6 shards) on 974cb8e9 with
#        graftling 4a002129; background; pytest TMPDIR outside the Harness. TR: counts, failures and the difference.
# Everything is under BASE=/private/tmp/graphtraj-530. The user's own DSH install, ~/.dsh and settings are never read or
# written: every dsh command has DSH_HOME=$DH with web profile web530 (Task 531 runs in parallel with its own). No step
# starts or connects to the Harness's production MCP servers; nothing is written in the Harness.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>
# graftling: branch agent/530-graftling-root-files-in-dsh-changes (from 4a002129), exported as a git bundle.
GBUNDLE=${VERIFY530_GBUNDLE:-$WT/.scratch/graftling-530.bundle}
GOLD=4a002129f8b97f32980afd59e5a1a64c428fe684          # graftling 0.6.2 (528), production
GFIX=${VERIFY530_GFIX:-95cffda1ff7aa22396a88922864c3ed2e0f94fb9}   # graftling 530 fix
GTBASE=c917f5fcca35e36f981c6eee2d592956fd7a832b        # GraphTraj: this Worktree's base
GTFIX=${VERIFY530_GTFIX:-974cb8e95680ac607e420329517470aca9239629} # GraphTraj 530 fix
BASE=${VERIFY530_BASE:-/private/tmp/graphtraj-530}
GSRC=$BASE/graftling-src                               # clone of the bundle (wheel source; read by git archive)
DH=$BASE/dsh-home; OUT=$BASE/runs
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: yaml, websockets, click (no PyPI on this host)
STEP=${1:-}
MODEL=deepseek-flash
WEB=web530
PYTEST_TMP=${TMPDIR:-/tmp}
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
where() { print -r -- "RUN IN: $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
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
# Per build: $1 = before|after sets the globals the steps use.
phase() {
  PH=$1; PB=$BASE/$1; P=$PB/project; W=$PB/work-standalone; V=$PB/venv; GROOT_US=$W/graftling-data
  if [[ $1 == before ]]; then GC=$GOLD TC=$GTBASE; else GC=$GFIX TC=$GTFIX; fi
}
roots() { print -r -- $P/.graphtraj/swarm $GROOT_US; }
gdsh() { $V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
llm_patch() {
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
has_plugin() {
  [[ -n ${VERIFY530_ASSUME_PLUGIN:-} ]] && { print "REHEARSAL: graftling-dsh assumed present in $WEB" >&2; return 0; }
  grep -q '"graftling-dsh"' $DH/profiles/$WEB/package.json 2>/dev/null
}
plugin_cmd() {  # graftling-dsh from the BEFORE venv; its dsh/ files are identical in 4a002129 and 95cffda1
  phase before
  print -r -- "cd $BASE && env DSH_HOME=$DH PATH=$BASE/bin:/opt/homebrew/bin:\$PATH npm_config_store_dir=$BASE/pnpm-store $(command -v dsh) plugin --profile $WEB add $(gdsh)"
}
PROMPT_TEXT() {  # $1 tool, $2 step
  print -r -- "Call the MCP tool $1 exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}}. Use no other tool. Then reply with one line: DONE-530-$2 followed by the exact name of the tool you called and ok or the exact error."
}
git_ws() {  # $1 directory, $2 label: a git work tree with one commit
  [[ -d $1/.git ]] && return 0
  mkdir -p $1; (cd $1 && git init -q -b main && print -r -- "# 530 $2" > README.md && git add README.md \
    && git -c user.name=530 -c user.email=530@invalid commit -qm "Initial source")
}
no_roots() {  # STOP when a graftling data root of this build already exists
  local r bad=0
  for r in $(roots); do
    [[ -e $r ]] && { print "STOP: graftling data root already exists: $r (this build is not fresh; use a new BASE)"; bad=1; }
  done
  (( bad == 0 )) && print "fresh: no data root yet at $P/.graphtraj/swarm or $GROOT_US"
  return $bad
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT

build() {  # 0 for the current phase: venv, project, standalone workspace, patches, git status record
  say "[$PH] graftling ${GC[1,10]} + GraphTraj ${TC[1,10]}: venv $V, project $P, standalone $W"
  local Wh=$PB/wheels
  git -C $GSRC cat-file -e $GC^{commit} || { print "STOP: $GSRC lacks graftling $GC"; return 1; }
  git -C $WT cat-file -e $TC^{commit} || { print "STOP: $WT lacks GraphTraj $TC"; return 1; }
  if [[ ! -f $V/installed || $(<$V/installed) != "$TC $GC" ]]; then
    mkdir -p $Wh; rm -f $Wh/graftling-*.whl(N) $Wh/graphtraj-*.whl(N)
    wheel $GSRC $GC src/graftling $Wh && wheel $WT $TC . $Wh || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $Wh 'graftling-*.whl') && hw=$(need $Wh 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V; deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw $hw
    print -r -- "$TC $GC" > $V/installed
  else print "venv $V already holds GraphTraj ${TC[1,10]} + graftling ${GC[1,10]}"; fi
  (cd $PB && clean $V/bin/python -I -c 'import graftling, graphtraj, inspect, importlib.metadata as m, graftling.config as c, graphtraj.interfaces.agents as a
print("venv: graftling", m.version("graftling"), "| live/ ignored before config.lock:", "ignore_in_git(root / \"live\")" in inspect.getsource(c._update),
      "| graphtraj", m.version("graphtraj"), "| swarm .gitignore:", hasattr(a, "default_archive"))')
  no_roots || return 1
  git_ws $P project || return 1
  if [[ ! -f $P/.graphtraj/config.yml ]]; then (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1; fi
  (cd $P && clean $V/bin/python -I $WT/scripts/verify-514/prep514.py $P | grep -E 'roles OK|probe Task 1|STOP|Error') \
    || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
  git_ws $W standalone || return 1
  print "git work trees: project $(git -C $P rev-parse --is-inside-work-tree), standalone $(git -C $W rev-parse --is-inside-work-tree)"
  llm_patch > $PB/llm.patch.yml
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $PB/graphtraj-main.patch.yml >/dev/null
  llm_patch >> $PB/graphtraj-main.patch.yml
  # graftling alone needs no config.yml (it never writes one; PUBLIC_API section 3): the root is NOT created here.
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $GROOT_US $(command -v dsh) $MODEL $PB/dsh-host.json
  no_roots || { print "STOP: preparing $PH created a data root (see above)"; return 1; }
  git -C $P status --porcelain --untracked-files=all > $PB/status-before-project.txt
  git -C $W status --porcelain --untracked-files=all > $PB/status-before-standalone.txt
  print "git status --porcelain --untracked-files=all recorded: project $(wc -l < $PB/status-before-project.txt | tr -d ' ') lines ($PB/status-before-project.txt), standalone $(wc -l < $PB/status-before-standalone.txt | tr -d ' ') lines"
  sed 's/^/  project: /' $PB/status-before-project.txt | head -8
}

turn() {  # UG/US/UG2/US2: print the user's browser steps
  local s=$1 kind=${1[1,2]} tool cwd patch envs label shot next
  [[ -f $V/installed && -f $PB/llm.patch.yml ]] || { print "STOP: run step 0 first"; return 1; }
  if [[ $kind == US ]]; then
    has_plugin || { print "STOP: graftling-dsh is not in $WEB; run step 0 (it prints the plugin command)"; return 1; }
    tool=mcp__graftling__agents cwd=$W patch=$PB/llm.patch.yml label="graftling alone (graftling-dsh agents-host row)"
    envs="GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$PB/dsh-host.json "
  else
    tool=mcp__graphtraj__agents cwd=$P patch=$PB/graphtraj-main.patch.yml label="GraphTraj DSH Main (graphtraj-main row)"
    envs=""
  fi
  [[ -e $([[ $kind == US ]] && print $GROOT_US || print $P/.graphtraj/swarm) ]] \
    && print "WARNING: the data root of this case already exists; this is not a first call on a fresh root (tell Main)"
  shot=$BASE/screenshot-$s.png
  PROMPT_TEXT $tool $s > $BASE/prompt-$s.txt
  case $s in UG) next="zsh $THIS US" ;; US) next="zsh $THIS C (Main's Bash)" ;; UG2) next="zsh $THIS US2" ;; US2) next="zsh $THIS C2 (Main's Bash)" ;; esac
  say "[$s] $PH build (graftling ${GC[1,10]}, GraphTraj ${TC[1,10]}): $label, the FIRST $tool call on a brand-new data root, in the browser UI of $WEB. One model call."
  print -r -- "Dialogs: at most one native dialog, the macOS folder chooser in step 1b (choice: Open). If no native chooser
appears, DSH's in-app browse dialog is used instead. Inside the page DSH may ask to approve the tool call: approve it once.

1. In a plain Terminal (Terminal.app, not the Claude sandbox) where DEEPSEEK_API_KEY is set as usual
   (check: echo \${DEEPSEEK_API_KEY:+set}), paste this one line:

cd $cwd && env DSH_HOME=$DH PATH=/opt/homebrew/bin:\$PATH ${envs}$(command -v dsh) --profile $WEB --patch $patch --port 0

   It prints the served URL (http://127.0.0.1:<port>/...) and opens it in the default browser. If no browser opens,
   open that printed URL yourself.
1b. Select the workspace first: the page creates the Session in the workspace selected in the page, not in the
   server's cwd. Click the composer's 'ワークスペースを選択' (or the sidebar workspace menu) -> 'ワークスペースを追加…'.
   A folder chooser opens (native macOS chooser, else DSH's in-app browse dialog).
   Native: press Cmd-Shift-G; in-app: edit the path field. Enter exactly:
     $cwd
   and choose 開く/Open. Then select that workspace ('${cwd:t}') in the composer.
2. In the page start a NEW conversation (workspace '${cwd:t}') and paste this prompt exactly (also in $BASE/prompt-$s.txt):

$(<$BASE/prompt-$s.txt)

3. Wait until the turn has finished and the reply line DONE-530-$s is shown (a changes card, if any, appears under the
   reply when the turn ends).
4. Screenshot the area from the $tool call card down to everything below the DONE-530-$s reply line, so that any card
   under the reply is visible; if a '…を編集しました' card is there, expand it so its file names are readable
   (Cmd-Shift-4, drag). Save or move it to exactly:
     $shot
5. Stop the server with Ctrl-C in that Terminal."
  if [[ $s == UG ]]; then
    print -r -- "
Expected BEFORE (code analysis and a scratch reproduction, not yet the real entry): if GraphTraj's first use happens in
this turn, a card '…を編集しました' listing .graphtraj/swarm/config.yml and .graphtraj/swarm/live/config.lock. If GraphTraj
initialised its data root already when the page/server started (before the turn), no card: step C tells which."
  elif [[ $s == US ]]; then
    print -r -- "
Expected BEFORE: probably NO card. graftling alone writes no config.yml; a status call creates only
graftling-data/live/dsh-host/control-*/ (a socket, which git does not list). The screenshot decides."
  else
    print -r -- "
Expected AFTER: NO file-change card under DONE-530-$s. The data root of this case is new and inside the git workspace."
  fi
  print -r -- "The conclusion is only what the screenshot and step ${${s/US/C}/UG/C} show.
next: $next"
}

check() {  # C/C2 (read only): $1 = UG suffix ('' or 2)
  local x=$1 s f n r a t
  for s in UG$x US$x; do
    [[ -f $BASE/screenshot-$s.png ]] && print "screenshot-$s.png: $(stat -f '%z bytes, %Sm' $BASE/screenshot-$s.png)" \
      || print "screenshot-$s.png: MISSING ($BASE/screenshot-$s.png)"
  done
  print "DSH session files in $DH (excluding profiles/) whose text holds DONE-530-UG$x or DONE-530-US$x, and their"
  print "workspace/changes events (the event carries only the turn; the listed files are seen only in the screenshot):"
  local files=(${(f)"$(grep -rlIE "DONE-530-(UG|US)$x([^0-9]|\$)" $DH --exclude-dir=profiles 2>/dev/null)"})
  (( ${#files} )) || print "  (none among uncompressed files)"
  for f in $files; do
    n=$(grep -c 'workspace/changes' $f || true)
    t=$(grep -oE "DONE-530-(UG|US)$x" $f | sort -u | tr '\n' ' ')
    print "  ${f#$DH/}: ${t}| tool $(grep -oE 'mcp__(graftling|graphtraj|agents)__agents' $f | sort -u | tr '\n' ' ')| workspace/changes events $n | file born $(stat -f %SB $f), modified $(stat -f %Sm $f)"
  done
  local packed=(${(f)"$(find $DH -path $DH/profiles -prune -o -type f -name '*.jsonl.zstd' -print 2>/dev/null)"})
  for f in $packed; do print "  ${f#$DH/}: compressed (.jsonl.zstd), not inspected"; done
  for r in $(roots); do
    if [[ ! -e $r ]]; then print "data root $r: does not exist"; continue; fi
    print "data root $r (born $(stat -f %SB $r)): files (birth | modify | type):"
    find $r \( -type f -o -type s \) -print 2>/dev/null | sort | while read -r f; do
      print -r -- "  ${f#$r/}  $(stat -f '%SB | %Sm | %HT' $f)"; done
  done
  for s in project standalone; do
    local d=$P; [[ $s == standalone ]] && d=$W
    git -C $d status --porcelain --untracked-files=all > $PB/status-after-$s.txt
    print "git status in $d: lines now $(wc -l < $PB/status-after-$s.txt | tr -d ' '), new since step 0:"
    comm -13 <(sort $PB/status-before-$s.txt) <(sort $PB/status-after-$s.txt) | sed 's/^/  /'
    print "  lines under a graftling data root: $(grep -cE '(\.graphtraj/swarm|graftling-data)/' $PB/status-after-$s.txt || true)"
  done
  print "Main reads the screenshots (Read tool) and records only what they show (card present or not, file names)."
  if [[ -z $x ]]; then
    print "Fix scope: apply the GraphTraj fix only if UG's screenshot shows the card with .graphtraj/swarm files; apply the"
    print "graftling fix only if US (or UG without GraphTraj's rule) shows a graftling-data/live file. Step 0 already prepared the AFTER"
    print "build (no rebuild). next (USER, plain Terminal + browser): zsh $THIS UG2"
  else
    print "Expected AFTER: no card in either screenshot; 'new since step 0' holds no data-root line (with the GraphTraj fix"
    print "the project's new lines are none: .graphtraj/swarm/.gitignore '*' ignores itself). next: zsh $THIS T"
  fi
}

new_runtmp() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/verify-530-T-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  print -r -- "pytest TMPDIR=\${TMPDIR:-/tmp} = $PYTEST_TMP; this run's temp root $RUNTMP is outside the Harness: yes"
}
t_venvs() {  # graftling clones (editable) for both commits; GraphTraj fix clone (editable) + graftling 4a002129 wheel
  local TB=$BASE/t c d v
  mkdir -p $TB
  for c in $GOLD $GFIX; do
    d=$TB/graftling-${c[1,10]} v=$TB/v-graftling-${c[1,10]}
    [[ -d $d ]] || { git clone -q $GSRC $d && git -C $d checkout -q $c; } || return 1
    if [[ ! -f $v/installed ]]; then
      $CONDA -m venv --system-site-packages $v; deps $v
      $v/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $d/src/graftling >/dev/null || return 1
      print -r -- $c > $v/installed
    fi
  done
  # The fix's new test also runs on 4a002129 (copied in, untracked) so T shows it failing on the old code.
  cp $TB/graftling-${GFIX[1,10]}/tests/test_config_lock_git_ignored_530.py $TB/graftling-${GOLD[1,10]}/tests/
  d=$TB/graphtraj-${GTFIX[1,10]} v=$TB/v-graphtraj-${GTFIX[1,10]}
  [[ -d $d ]] || { git clone -q $WT $d && git -C $d checkout -q $GTFIX; } || return 1
  if [[ ! -f $v/installed ]]; then
    wheel $GSRC $GOLD src/graftling $TB/wheels || return 1
    $CONDA -m venv --system-site-packages $v; deps $v
    $v/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(need $TB/wheels "graftling-*.whl") >/dev/null || return 1
    $v/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $d >/dev/null || return 1
    print -r -- "$GTFIX $GOLD" > $v/installed
  fi
}

case $STEP in
0)
  where "Main's Bash (if graftling-dsh is missing from $WEB, the USER adds it once in a plain Terminal; then rerun 0)."
  say "[0] preflight for BEFORE and AFTER. Dialog: none. Builds wheels and venvs (no network), two fresh git projects and two git standalone workspaces (no data roots), $WEB with graftling-dsh, then one one-line dsh answer (at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); dsh $(clean dsh --version 2>&1 | tail -1) ($(command -v dsh)); node $(node --version 2>&1)"
  print "candidate: $WT $(git -C $WT rev-parse HEAD) (branch $(git -C $WT branch --show-current))"
  print "BEFORE: graftling ${GOLD[1,10]} + GraphTraj ${GTBASE[1,10]} | AFTER: graftling ${GFIX[1,10]} + GraphTraj ${GTFIX[1,10]}"
  print "isolated layout: BASE=$BASE (before/, after/), DSH_HOME=$DH (never ~/.dsh), web profile $WEB"
  mkdir -p $DH
  if [[ ! -d $GSRC ]]; then
    [[ -f $GBUNDLE ]] || { print "STOP: graftling bundle $GBUNDLE is missing"; return 1; }
    git clone -q --no-checkout $GBUNDLE $GSRC || { print "STOP: could not clone $GBUNDLE"; return 1; }
  fi
  print "graftling source $GSRC: ${GOLD[1,10]} $(git -C $GSRC log -1 --format=%s $GOLD) | ${GFIX[1,10]} $(git -C $GSRC log -1 --format='%s (%an <%ae>)' $GFIX)"
  phase before; build || return 1
  phase after; build || return 1
  say "isolated web profile $WEB in $DH (fresh copy of the shipped web template on first run), then graftling-dsh"
  if [[ ! -f $DH/profiles/$WEB/package.json ]]; then
    (cd $BASE && clean dsh --profile $WEB --from-default-profile web --dump-config > $BASE/web-dump-config.txt 2>&1) \
      && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $BASE/web-dump-config.txt; return 1; }
  else print "profile $WEB: present ($DH/profiles/$WEB)"; fi
  mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
  chmod +x $BASE/bin/pnpm
  phase before
  if ! has_plugin; then
    print "graftling-dsh not in $WEB: trying dsh plugin add here (fails inside the Claude sandbox: pnpm store lock EPERM)"
    (cd $BASE && clean PATH=$BASE/bin:${(j.:.)path} npm_config_store_dir=$BASE/pnpm-store $BOUND 300 \
       dsh plugin --profile $WEB add $(gdsh) > $BASE/plugin-add.txt 2>&1) && print "dsh plugin add: rc 0" \
      || { print "dsh plugin add failed (rc $?):"; grep -vi npmrc $BASE/plugin-add.txt | grep -v '^ *$' | tail -4 | sed 's/^/  /'; }
  fi
  if ! has_plugin; then
    print -r -- "
STOP: graftling-dsh is not in web profile $WEB ($DH/profiles/$WEB/package.json).
USER: open a plain Terminal (Terminal.app, not this sandbox) and paste this one line (dialog: none expected):
  $(plugin_cmd)
It ends with dsh's plugin summary and no error. Then Main reruns: zsh $THIS 0"
    return 1
  fi
  print "graftling-dsh: in $WEB; web profile dependencies: $($CONDA -I -c 'import json, sys; print(list(json.load(open(sys.argv[1])).get("dependencies", {})))' $DH/profiles/$WEB/package.json 2>/dev/null || print '(rehearsal: no package.json)')"
  say "composed web profile per case (dsh --dump-config; rows that matter)"
  for ph in before after; do
    phase $ph
    (cd $W && clean dsh --profile $WEB --patch $PB/llm.patch.yml --dump-config > $PB/US-dump-config.txt 2>&1) || print "$ph US dump-config rc=$?"
    (cd $P && clean dsh --profile $WEB --patch $PB/graphtraj-main.patch.yml --dump-config > $PB/UG-dump-config.txt 2>&1) || print "$ph UG dump-config rc=$?"
    print "$ph US rows: $(grep -oE '^- id: (agents-host|llm-deepseek)$' $PB/US-dump-config.txt | cut -c7- | tr '\n' ' ')(expected agents-host llm-deepseek)"
    print "$ph UG rows: $(grep -oE '^- id: (graphtraj-main|llm-deepseek)$' $PB/UG-dump-config.txt | cut -c7- | tr '\n' ' ')(expected llm-deepseek graphtraj-main)"
  done
  phase before
  print "configured model (agent-default-model row): $(grep -A4 '^- id: agent-default-model$' $PB/US-dump-config.txt | grep -E 'provider:|model:' | tr -s ' \n' ' ')"
  if [[ -n ${VERIFY530_NOMODEL:-} ]]; then print "VERIFY530_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    (cd $BASE && clean $BOUND 120 dsh --profile headless --patch $PB/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-530, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  fi
  for ph in before after; do phase $ph; no_roots || return 1; done
  print "Ready when: both venv lines (BEFORE: 'live/ ignored … False', 'swarm .gitignore: False'; AFTER: both True), 'roles OK' and 'probe Task 1 ready' twice, all git work trees true, two 'fresh: no data root yet' lines at the end (BEFORE, AFTER), graftling-dsh in $WEB, the expected rows, and one READY-530 line naming the model."
  print -r -- "next (USER, plain Terminal + browser): zsh $THIS UG"
  ;;
UG|US)  phase before; where "Main's Bash or a Terminal (this step only prints); then the USER's plain Terminal and browser."; turn $STEP ;;
UG2|US2) phase after; where "Main's Bash or a Terminal (this step only prints); then the USER's plain Terminal and browser."; turn $STEP ;;
C)  phase before; where "Main's Bash (reads only)."; say "[C] BEFORE: screenshots, DSH changes events, data-root files, git status. Dialog: none."; check "" ;;
C2) phase after;  where "Main's Bash (reads only)."; say "[C2] AFTER: screenshots, DSH changes events, data-root files, git status. Dialog: none."; check 2 ;;
T)
  setopt local_options no_bg_nice
  where "Main's Bash. Dialog: none. Returns at once; the suites run one after another in the background."
  [[ -d $GSRC ]] || { print "STOP: run step 0 first (it clones the graftling bundle)"; return 1; }
  say "[T] graftling full suite on ${GOLD[1,10]} and ${GFIX[1,10]}, then GraphTraj full suite (6 shards) on ${GTFIX[1,10]} with graftling ${GOLD[1,10]}."
  print "GraphTraj's base ${GTBASE[1,10]}: its full suite is the accepted adopt-528 G/Gt/GR evidence (no rerun here)."
  print -r -- "load average: $(sysctl -n vm.loadavg 2>&1) | other test runs: $(ps -axww -o pid=,command= 2>/dev/null | grep -E 'run_test_shards|-m pytest' | grep -vc grep)"
  local RUNTMP TB=$BASE/t; new_runtmp || return 1
  t_venvs || { print "STOP: a test venv was not built"; return 1; }
  local R=$OUT/T-$(date +%Y%m%dT%H%M%S) c; mkdir -p $R $RUNTMP
  for c in $GOLD $GFIX; do
    (cd $RUNTMP && $TB/v-graftling-${c[1,10]}/bin/python -I -c 'import graftling, pytest; print("graftling", graftling.__file__, "| pytest", pytest.__version__)')
  done
  (cd $RUNTMP && $TB/v-graphtraj-${GTFIX[1,10]}/bin/python -I -c 'import graphtraj, graftling, graphtraj.interfaces.agents as a; print("graphtraj", graphtraj.__file__, "| default_archive:", hasattr(a, "default_archive"), "| graftling", graftling.__version__, graftling.__file__)')
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD)"
    print -r -- "graftling ${GOLD[1,10]} vs ${GFIX[1,10]}; GraphTraj ${GTFIX[1,10]} + graftling ${GOLD[1,10]}"
    [[ -n ${VERIFY530_TESTS_G:-} ]] && print -r -- "REHEARSAL: graftling tests limited to $VERIFY530_TESTS_G"
    [[ -n ${VERIFY530_TESTS_GT:-} ]] && print -r -- "REHEARSAL: GraphTraj tests limited to $VERIFY530_TESTS_GT (plain pytest)"; } | tee $R/run.txt
  (
    setopt no_err_return no_err_exit   # a failing suite must not end the chain
    for c in $GOLD $GFIX; do
      (cd $TB/graftling-${c[1,10]} && TMPDIR=$RUNTMP $TB/v-graftling-${c[1,10]}/bin/python -m pytest -p no:cacheprovider -q -rfE \
        --basetemp=$RUNTMP/bt-graftling-${c[1,10]} ${=VERIFY530_TESTS_G:-tests} > $R/graftling-${c[1,10]}.txt 2>&1
       print "exit=$?" >> $R/graftling-${c[1,10]}.txt)
    done
    if [[ -n ${VERIFY530_TESTS_GT:-} ]]; then
      (cd $TB/graphtraj-${GTFIX[1,10]} && TMPDIR=$RUNTMP $TB/v-graphtraj-${GTFIX[1,10]}/bin/python -m pytest -p no:cacheprovider -q -rfE \
        --basetemp=$RUNTMP/bt-graphtraj ${=VERIFY530_TESTS_GT} > $R/graphtraj-${GTFIX[1,10]}.txt 2>&1; print "exit=$?" >> $R/graphtraj-${GTFIX[1,10]}.txt)
    else
      (cd $TB/graphtraj-${GTFIX[1,10]} && TMPDIR=$RUNTMP $TB/v-graphtraj-${GTFIX[1,10]}/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 \
        --log-dir $R/shards -- -rA > $R/graphtraj-${GTFIX[1,10]}.txt 2>&1; print "exit=$?" >> $R/graphtraj-${GTFIX[1,10]}.txt)
    fi
    print "all done $(date +%T)" >> $R/run.txt
  ) &!
  print -r -- $R > $OUT/T-latest
  print -r -- "started in the background at $(date +%T); output $R ('all done' in run.txt when it ends; graftling ~3+3 min, GraphTraj ~25 min).
next (Main, when run.txt says 'all done'): zsh $THIS TR"
  ;;
TR)
  where "Main's Bash (reads only). Dialog: none."
  local R=$(<$OUT/T-latest) f
  print -r -- "run: $R"; cat $R/run.txt
  for f in $R/graftling-*.txt $R/graphtraj-*.txt(N); do
    print -r -- "== ${f:t}: $(grep -E '[0-9]+ (passed|failed|error)' $f | tail -1) | $(grep '^exit=' $f || print 'running')"
    { grep -E '^(FAILED|ERROR) ' $f || true; } | sed 's/ - .*//' | sort -u | sed 's/^/  /'
  done
  local o=$R/graftling-${GOLD[1,10]}.txt n=$R/graftling-${GFIX[1,10]}.txt
  if [[ -f $o && -f $n ]]; then
    print "graftling failures on the fix that are not on ${GOLD[1,10]} (new failures):"
    comm -13 <({ grep -E '^(FAILED|ERROR) ' $o || true; } | sed 's/ - .*//' | sort -u) \
      <({ grep -E '^(FAILED|ERROR) ' $n || true; } | sed 's/ - .*//' | sort -u) | sed 's/^/  /'
  fi
  print "Expected on ${GOLD[1,10]}: tests/test_config_lock_git_ignored_530.py fails (copied in from the fix); it passes on ${GFIX[1,10]}."
  print "Judge: no new graftling failure; GraphTraj failures only those 516 lists or adopt-528 GR accepted as flakes (Main compares)."
  ;;
*) print -r -- "usage: zsh $THIS 0|UG|US|C|UG2|US2|C2|T|TR"; return 2 ;;
esac
