#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 526 steps: DSH's per-turn changes card must no longer list graftling's own session archive / runtime records
# ('session.jsonl を編集しました') after an agents call in a GIT workspace. Copied from verify-522 (accepted) and adapted:
# graftling is built from the 526 fix commit (a git bundle in this Worktree's .scratch), and BOTH cases run in a
# `git init`ed workspace whose graftling data root lies inside it, the case in which DSH's changes card can appear.
#   zsh scripts/verify-526/steps.zsh <STEP>        (from this Task's Worktree)
# Order: 0 (Main's Bash) -> UG (USER, plain Terminal + browser) -> US (USER, plain Terminal + browser) -> C (Main).
#   0   preflight: versions, wheels (graftling = 526 fix) and venv, isolated git project + probe Task 1, git standalone
#       workspace, the isolated DSH home with web profile web526 and graftling-dsh added, one one-line model answer.
#       STOPs (does not continue) when graftling-dsh is not in web526 and prints the plain-Terminal command.
#   UG  USER: GraphTraj DSH Main (graphtraj-main row) in the git project; one mcp__graphtraj__agents status.
#   US  USER: graftling alone (graftling-dsh agents-host row) in the git standalone workspace; one mcp__graftling__agents.
#   C   Main: screenshots; per DSH session file the count of workspace/changes events; graftling archives and
#       <root>/sessions/.gitignore; what `git status` lists under the graftling roots.
# Everything is under BASE=/private/tmp/graphtraj-526 (project, venv, DSH_HOME). The user's own DSH install, ~/.dsh
# and settings are never read or written: every dsh command has DSH_HOME=$DH. No step starts or connects to the
# Harness's production MCP servers, and no step signals a process it did not start. Nothing is written in the Harness.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>
# The 526 fix: graftling branch agent/526-dsh-workspace-shows-graftling-session-archive (from graftling dev 483b16a8),
# exported as a git bundle (its clone's git directory sits in the Engineer's sandbox TMPDIR, so the bundle carries it).
GBUNDLE=${VERIFY526_GBUNDLE:-$WT/.scratch/graftling-526-full.bundle}
GCOMMIT=40a0099f07052e4e6a6bdaba9910dcce6fe2d316        # graftling: keep runtime directories out of git (526)
# VERIFY526_* are set only by a rehearsal (scratch BASE, no model call, plugin assumed); the defaults are the real paths.
BASE=${VERIFY526_BASE:-/private/tmp/graphtraj-526}
GDEV=$BASE/graftling-src                               # clone of the bundle (wheel source; read by git archive)
P=$BASE/project; W=$BASE/work-standalone; V=$BASE/venv; DH=$BASE/dsh-home; OUT=$BASE/runs
GROOT_US=$W/graftling-data                             # standalone graftling data root, INSIDE the git workspace W
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: yaml, websockets, click (no PyPI on this host)
STEP=${1:-}
MODEL=deepseek-flash
WEB=web526                                             # the isolated web profile (in $DH only)
path=(/opt/homebrew/bin $HOME/.local/bin $path)        # dsh and node (Homebrew); same in Main's Bash and a Terminal

say() { print -r -- "== $*"; }
where() { print -r -- "RUN IN: $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# A dsh call inherits no marker of the Harness Main (GraphTraj/graftling connections, DSH Session); DSH_HOME is isolated.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} DSH_HOME=$DH ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
load_key() {  # verify-514 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
deps() {  # $1 venv: PyYAML, click and websockets from production's site-packages (copied, never changed there)
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
need() {  # $1 directory, $2 pattern: the one file it must hold
  local found=($1/$~2(N))
  (( $#found == 1 )) && { print -r -- $found; return 0; }
  print -r -- "STOP: expected exactly one $2 in $1, found ${#found}" >&2; return 1
}
candidate() { git -C $WT rev-parse HEAD; }
gdsh() { $V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
llm_patch() {  # the DeepSeek provider row (as 513/514/520)
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
has_plugin() {  # graftling-dsh is a dependency of web526 (rehearsal: VERIFY526_ASSUME_PLUGIN pretends it is)
  [[ -n ${VERIFY526_ASSUME_PLUGIN:-} ]] && { print "REHEARSAL: graftling-dsh assumed present in $WEB" >&2; return 0; }
  grep -q '"graftling-dsh"' $DH/profiles/$WEB/package.json 2>/dev/null
}
# The plain-Terminal command (no placeholders) that adds graftling-dsh to web526: this host's /opt/homebrew/bin/pnpm is
# pnpm 12's placeholder (spawn ENOEXEC), so a shim runs pnpm's own bin/pnpm.mjs; the pnpm store is under BASE.
plugin_cmd() {
  print -r -- "cd $BASE && env DSH_HOME=$DH PATH=$BASE/bin:/opt/homebrew/bin:\$PATH npm_config_store_dir=$BASE/pnpm-store $(command -v dsh) plugin --profile $WEB add $(gdsh)"
}
PROMPT_TEXT() {  # $1 tool, $2 case
  print -r -- "Call the MCP tool $1 exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}}. Use no other tool. Then reply with one line: DONE-526-$2 followed by the exact name of the tool you called and ok or the exact error."
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT
case $STEP in
0)
  where "Main's Bash (the plugin add, if missing, is then done once by the USER in a plain Terminal; then rerun 0)."
  say "[0] preflight. Dialog: none. Builds wheels and a venv (no network), the isolated project and DSH home, adds graftling-dsh to $WEB, then one one-line dsh answer (at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); dsh $(clean dsh --version 2>&1 | tail -1) ($(command -v dsh)); node $(node --version 2>&1)"
  print "candidate: $WT $(candidate) (branch $(git -C $WT branch --show-current)); graftling: $GDEV ${GCOMMIT[1,10]}"
  print "isolated layout: BASE=$BASE  project=$P  standalone work=$W  venv=$V  DSH_HOME=$DH (never ~/.dsh)"
  local Wh=$BASE/wheels C=$(candidate); mkdir -p $Wh $DH
  if [[ ! -d $GDEV ]]; then
    [[ -f $GBUNDLE ]] || { print "STOP: graftling bundle $GBUNDLE is missing"; return 1; }
    git clone -q --no-checkout $GBUNDLE $GDEV || { print "STOP: could not clone $GBUNDLE"; return 1; }
  fi
  git -C $GDEV cat-file -e $GCOMMIT^{commit} || { print "STOP: $GDEV lacks graftling $GCOMMIT"; return 1; }
  print "graftling source: $GDEV at ${GCOMMIT[1,10]}: $(git -C $GDEV log -1 --format=%s $GCOMMIT)"
  if [[ ! -f $V/installed || $(<$V/installed) != "$C $GCOMMIT" ]]; then
    rm -f $Wh/graftling-*.whl(N) $Wh/graphtraj-*.whl(N)
    wheel $GDEV $GCOMMIT src/graftling $Wh && wheel $WT $C . $Wh || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $Wh 'graftling-*.whl') && hw=$(need $Wh 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V; deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw $hw
    print -r -- "$C $GCOMMIT" > $V/installed
  else print "venv $V already holds $C + graftling ${GCOMMIT[1,10]}"; fi
  (cd $BASE && clean $V/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m
print("venv: graftling", m.version("graftling"), "graphtraj", m.version("graphtraj"), "from", graphtraj.__file__.split("/lib/")[0])')
  say "isolated GraphTraj project and probe Task 1 (UG)"
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 526 probe" > README.md && git add README.md \
      && git -c user.name=526 -c user.email=526@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $P && clean $V/bin/python -I $WT/scripts/verify-514/prep514.py $P | grep -E 'roles OK|probe Task 1|STOP|Error') \
    || { print "STOP: roles or probe Task 1 not ready in $P"; return 1; }
  say "patches: llm = DeepSeek provider row (US); graphtraj-main = GraphTraj's DSH Main row + llm (UG)"
  llm_patch > $BASE/llm.patch.yml
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $BASE/graphtraj-main.patch.yml >/dev/null
  llm_patch >> $BASE/graphtraj-main.patch.yml
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $GROOT_US $(command -v dsh) $MODEL $BASE/dsh-host.json
  say "git standalone workspace (US): $W, graftling data root $GROOT_US inside it (archives enabled)"
  if [[ ! -d $W/.git ]]; then
    mkdir -p $W; (cd $W && git init -q -b main && print -r -- "# 526 standalone" > README.md && git add README.md \
      && git -c user.name=526 -c user.email=526@invalid commit -qm "Initial source") || return 1
  fi
  mkdir -p $GROOT_US; print "save_normalized_sessions: true" > $GROOT_US/config.yml
  print "git work trees: project $(git -C $P rev-parse --is-inside-work-tree), standalone $(git -C $W rev-parse --is-inside-work-tree)"
  say "isolated web profile $WEB in $DH (fresh copy of the shipped web template on first run), then graftling-dsh"
  if [[ ! -f $DH/profiles/$WEB/package.json ]]; then
    (cd $BASE && clean dsh --profile $WEB --from-default-profile web --dump-config > $BASE/web-dump-config.txt 2>&1) \
      && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $BASE/web-dump-config.txt; return 1; }
  else print "profile $WEB: present ($DH/profiles/$WEB)"; fi
  mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
  chmod +x $BASE/bin/pnpm
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
  print "graftling-dsh: in $WEB; web profile dependencies: $($CONDA -I -c 'import json, sys; print(list(json.load(open(sys.argv[1])).get("dependencies", {})))' $DH/profiles/$WEB/package.json)"
  # The keys the graftling-dsh browser bundle registers for tool.call.toolview (as verify-513 D's client-view-keys).
  node -e '
const { readFileSync } = require("node:fs"); const vm = require("node:vm"); let m;
vm.runInNewContext(readFileSync(process.argv[1], "utf8"), { window: { __ModuleLoader__: { load(d) { m = d; } } } });
const keys = [];
m.factory(() => ({ createElement: () => ({}) })).apply({ slots: { inject: (n, f) => f(), entriesOfSlot: () => [],
  subscribe: () => () => {}, register: (o) => { if (o.name === "tool.call.toolview") keys.push(o.key); return () => {}; } } });
console.log("graftling-dsh tool view keys: " + JSON.stringify(keys));' $(gdsh)/client.mjs | tee $BASE/client-view-keys.txt
  say "composed web profile per case (dsh --dump-config; rows that matter)"
  (cd $W && clean dsh --profile $WEB --patch $BASE/llm.patch.yml --dump-config > $BASE/US-dump-config.txt 2>&1) || print "US dump-config rc=$?"
  (cd $P && clean dsh --profile $WEB --patch $BASE/graphtraj-main.patch.yml --dump-config > $BASE/UG-dump-config.txt 2>&1) || print "UG dump-config rc=$?"
  print "US rows: $(grep -oE '^- id: (agents-host|llm-deepseek)$' $BASE/US-dump-config.txt | cut -c7- | tr '\n' ' ')(expected agents-host llm-deepseek)"
  print "UG rows: $(grep -oE '^- id: (graphtraj-main|llm-deepseek)$' $BASE/UG-dump-config.txt | cut -c7- | tr '\n' ' ')(expected llm-deepseek graphtraj-main)"
  print "configured model (agent-default-model row): $(grep -A4 '^- id: agent-default-model$' $BASE/US-dump-config.txt | grep -E 'provider:|model:' | tr -s ' \n' ' ')"
  if [[ -n ${VERIFY526_NOMODEL:-} ]]; then print "VERIFY526_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    (cd $BASE && clean $BOUND 120 dsh --profile headless --patch $BASE/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-526, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  fi
  print "Ready when: graftling source at ${GCOMMIT[1,10]}, venv graftling 0.6.1, 'roles OK', 'probe Task 1 ready', both git work trees true, graftling-dsh in $WEB, the expected US and UG rows, and one READY-526 line naming the model."
  print -r -- "next (USER, plain Terminal): zsh $THIS UG"
  ;;
US|UG)
  where "Main's Bash or a Terminal (this step only prints). The server line below: the USER's plain Terminal (Terminal.app, not the Claude sandbox: it serves a local port and opens the browser), then the browser."
  [[ -f $V/installed && -f $BASE/llm.patch.yml ]] || { print "STOP: run step 0 first"; return 1; }
  local tool cwd patch envs label shot
  if [[ $STEP == US ]]; then
    has_plugin || { print "STOP: graftling-dsh is not in $WEB; run step 0 (it prints the plugin command)"; return 1; }
    tool=mcp__graftling__agents cwd=$W patch=$BASE/llm.patch.yml label="graftling alone (graftling-dsh agents-host row)"
    envs="GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$BASE/dsh-host.json "
  else
    has_plugin && print "note: graftling-dsh is in $WEB; its agents-host row stays inert here (no GRAFTLING_DSH_CONFIG)" \
      || print "note: graftling-dsh is NOT in $WEB (UG still runs; tell Main)"
    tool=mcp__graphtraj__agents cwd=$P patch=$BASE/graphtraj-main.patch.yml label="GraphTraj DSH Main (graphtraj-main row)"
    envs=""
  fi
  shot=$BASE/screenshot-$STEP.png
  PROMPT_TEXT $tool $STEP > $BASE/prompt-$STEP.txt
  say "[$STEP] $label: one $tool call in the browser UI of the isolated web profile $WEB. One model call."
  print -r -- "Dialogs: one native dialog, the macOS folder chooser in step 1b (only on a loopback Terminal launch; otherwise
DSH's in-app browse dialog). Inside the page DSH may ask to approve the tool call: approve it once.

1. In a plain Terminal where DEEPSEEK_API_KEY is set as usual (check: echo \${DEEPSEEK_API_KEY:+set}), paste this one line:

cd $cwd && env DSH_HOME=$DH PATH=/opt/homebrew/bin:\$PATH ${envs}$(command -v dsh) --profile $WEB --patch $patch --port 0

   It prints the served URL (http://127.0.0.1:<port>/...) and opens it in the default browser. If no browser opens,
   open that printed URL yourself.
1b. Select the workspace first: the page creates the Session in the workspace selected in the page, not in the
   server's cwd (an existing workspace such as '${BASE:t}' = $BASE fails: 'GraphTraj Config was not found').
   Click the composer's 'ワークスペースを選択' (or the sidebar workspace menu) -> 'ワークスペースを追加…'.
   A folder chooser opens (native macOS chooser on a loopback Terminal launch, else DSH's in-app browse dialog).
   Native: press Cmd-Shift-G; in-app: edit the path field. Enter exactly:
     $cwd
   and choose 開く/Open. Then select that workspace ('${cwd:t}') in the composer.
2. In the page start a NEW conversation (workspace '${cwd:t}') and paste this prompt exactly (also in $BASE/prompt-$STEP.txt):

$(<$BASE/prompt-$STEP.txt)

3. Wait until the turn has finished and the reply line DONE-526-$STEP is shown (the changes card, if any, appears
   under the reply when the turn ends).
4. Screenshot the area from the $tool call card down to everything below the DONE-526-$STEP reply line, so that
   whatever card sits under the reply is visible (Cmd-Shift-4, drag). Save or move it to exactly:
     $shot
5. Stop the server with Ctrl-C in that Terminal.

Expected (526): NO card 'session.jsonl を編集しました' (or any other file-change card) under the DONE-526-$STEP reply.
Before the fix 522's UG showed 'session.jsonl を編集しました +23 −1' there. Workspace '${cwd:t}' is a git work tree and
the graftling data root ($([[ $STEP == US ]] && print $GROOT_US || print $P/.graphtraj/swarm)) is inside it.
The conclusion is only what the screenshot and step C show."
  print -r -- "next: $([[ $STEP == UG ]] && print "zsh $THIS US (USER, plain Terminal)" || print "zsh $THIS C (Main's Bash)")"
  ;;
C)
  where "Main's Bash (reads only)."
  say "[C] screenshots, DSH changes events, graftling archives and their .gitignore. Dialog: none."
  local s f n r a
  for s in UG US; do
    [[ -f $BASE/screenshot-$s.png ]] && print "screenshot-$s.png: $(stat -f '%z bytes, %Sm' $BASE/screenshot-$s.png)" \
      || print "screenshot-$s.png: MISSING ($BASE/screenshot-$s.png)"
  done
  # DSH appends workspace/changes ({turn} only, no paths) only when a turn's change list is non-empty. The prompts allow
  # no file tool, so any such event in a session that records the UG/US agents call means DSH listed some file.
  print "DSH session files in $DH (excluding profiles/) that record an agents call, and their workspace/changes events"
  print "(the event carries only the turn, never paths; the listed files themselves are seen only in the screenshot):"
  local files=(${(f)"$(grep -rlIE 'mcp__(graftling|graphtraj|agents)__agents' $DH --exclude-dir=profiles 2>/dev/null)"})
  (( ${#files} )) || print "  (none among uncompressed files)"
  for f in $files; do
    n=$(grep -c 'workspace/changes' $f || true)
    print "  ${f#$DH/}: tool $(grep -oE 'mcp__(graftling|graphtraj|agents)__agents' $f | sort -u | tr '\n' ' ')| workspace/changes events $n"
  done
  local packed=(${(f)"$(find $DH -path $DH/profiles -prune -o -type f -name '*.jsonl.zstd' -print 2>/dev/null)"})
  for f in $packed; do print "  ${f#$DH/}: compressed (.jsonl.zstd), not inspected"; done
  for r in $P/.graphtraj/swarm $GROOT_US; do
    a=($r/sessions/*/session.jsonl(N))
    print "graftling root $r: archives ${#a}"
    for f in $a; do print "  ${f#$r/} ($(wc -l < $f | tr -d ' ') lines, $(stat -f %Sm $f))"; done
    for s in sessions control live native; do
      [[ -d $r/$s ]] || continue
      [[ -f $r/$s/.gitignore ]] && print -r -- "  $s/.gitignore: present, bytes $(od -An -c $r/$s/.gitignore | tr -d ' \n')" \
        || print "  $s/.gitignore: ABSENT"
    done
  done
  for s in $P $W; do
    print "git status --untracked-files=all in $s, lines under a graftling runtime directory (expected 0):" \
      "$(git -C $s status --porcelain --untracked-files=all | grep -cE '(swarm|graftling-data)/(sessions|control|live|native)/' || true)"
  done
  print "Expected: no screenshot shows a file-change card under DONE-526-UG / DONE-526-US; 'workspace/changes events 0' in"
  print "each session file recording the UG/US agents call; sessions/.gitignore present with bytes '*\\\\n'. Main reads the screenshots (Read tool) and records only what they show."
  ;;
*) print -r -- "usage: zsh $THIS 0|US|UG|C"; return 2 ;;
esac
