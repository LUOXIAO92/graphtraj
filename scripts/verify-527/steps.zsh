#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 527 steps: with the candidate graftling-dsh, DSH's browser shows a graftling-alone agents call
# (mcp__graftling__agents) as DSH's native collapsible Tool card, not graftling's AgentsRow with a 'Details' button.
# Based on verify-522 (graftling alone only: no GraphTraj project, probe Task or UG case; no pytest step).
#   zsh scripts/verify-527/steps.zsh <STEP>        (from this Task's Worktree)
# Order: 0 (Main's Bash) -> US (USER, plain Terminal + browser) -> C (Main).
#   0   preflight: versions, the candidate graftling wheel and a venv, the isolated DSH home with web profile web527
#       (fresh copy of the shipped web template) and the candidate graftling-dsh added, the tool view keys the bundle
#       registers (expected none), one one-line model answer. STOPs when graftling-dsh is missing from web527 or is
#       not the candidate's, and prints the plain-Terminal command.
#   US  USER: prints the plain-Terminal server line and the browser steps/screenshot.
#   C   Main (reads only): the screenshot, the agents tool names in the isolated DSH home, and that web527's
#       installed graftling-dsh client.mjs is the candidate commit's file.
# Everything is under BASE=/private/tmp/graphtraj-527 (venv, DSH_HOME, work dir); its own server uses --port 0, so it
# can run alongside another Task's browser step. The user's own DSH install, ~/.dsh and settings are never read or
# written: every dsh command has DSH_HOME=$DH. No step starts or connects to the Harness's production MCP servers,
# and no step signals a process it did not start. Nothing is written in the Harness.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>
# The candidate: graftling dev 483b16a8 + Task 527's change, branch agent/527-dsh-agents-native-tool-card in the clone
# $WT/tmp/527/graftling (untracked); the same change is committed here as scripts/verify-527/0001-*.patch.
GCOMMIT=c64a311b4ab8c8cdf3dcfa401c45b9e3aba17b4c
GREPOS=($WT/tmp/527/graftling $H/.graphtraj/core/worktrees/graftling-dev)   # read only: git archive / git show
# VERIFY527_* are set only by a rehearsal (scratch BASE, no model call, plugin assumed); the defaults are the real paths.
BASE=${VERIFY527_BASE:-/private/tmp/graphtraj-527}
W=$BASE/work-standalone; V=$BASE/venv; DH=$BASE/dsh-home
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: yaml, websockets, click (no PyPI on this host)
STEP=${1:-}
MODEL=deepseek-flash
WEB=web527                                             # the isolated web profile (in $DH only)
TOOL=mcp__graftling__agents
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
grepo() {  # the first repository that holds the pinned candidate commit
  local r
  for r in $GREPOS; do
    [[ -e $r/.git ]] && git -C $r cat-file -e "$GCOMMIT^{commit}" 2>/dev/null && { print -r -- $r; return 0; }
  done
  print -r -- "STOP: graftling commit $GCOMMIT is in none of: $GREPOS
  (the clone $WT/tmp/527/graftling holds it on branch agent/527-dsh-agents-native-tool-card; 'git am' of
  scripts/verify-527/0001-*.patch onto graftling dev gives the same files under another commit ID)" >&2
  return 1
}
gdsh() { $V/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "dsh")'; }
installed_client() { print -r -- $DH/profiles/$WEB/node_modules/graftling-dsh/client.mjs; }
same_client() {  # web527's installed graftling-dsh client.mjs equals the candidate commit's file
  local r; r=$(grepo) || return 2
  [[ -f $(installed_client) ]] || return 1
  same_blob $r $(installed_client)
}
same_blob() {  # $1 repository, $2 file: same Git blob ID as the candidate's client.mjs (reads only; no pipe into cmp)
  [[ $(git hash-object --no-filters $2) == $(git -C $1 rev-parse ${GCOMMIT}:src/graftling/dsh/client.mjs) ]]
}
llm_patch() {  # the DeepSeek provider row (as 513/514/520/522)
  print -r -- "- id: llm-deepseek"
  print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"
}
has_plugin() {  # graftling-dsh is a dependency of web527 (rehearsal: VERIFY527_ASSUME_PLUGIN pretends it is)
  [[ -n ${VERIFY527_ASSUME_PLUGIN:-} ]] && { print "REHEARSAL: graftling-dsh assumed present in $WEB" >&2; return 0; }
  grep -q '"graftling-dsh"' $DH/profiles/$WEB/package.json 2>/dev/null
}
# The plain-Terminal command (no placeholders) that adds graftling-dsh to web527: this host's /opt/homebrew/bin/pnpm is
# pnpm 12's placeholder (spawn ENOEXEC), so a shim runs pnpm's own bin/pnpm.mjs; the pnpm store is under BASE.
plugin_cmd() {
  print -r -- "cd $BASE && env DSH_HOME=$DH PATH=$BASE/bin:/opt/homebrew/bin:\$PATH npm_config_store_dir=$BASE/pnpm-store $(command -v dsh) plugin --profile $WEB add $(gdsh)"
}
PROMPT_TEXT() {
  print -r -- "Call the MCP tool $TOOL exactly once with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {}}. Use no other tool. Then reply with one line: DONE-527-US followed by the exact name of the tool you called and ok or the exact error."
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
case $STEP in
0)
  where "Main's Bash (the plugin add, if missing, is then done once by the USER in a plain Terminal; then rerun 0)."
  say "[0] preflight. Dialog: none. Builds the candidate graftling wheel and a venv (no network), the isolated DSH home, adds graftling-dsh to $WEB, then one one-line dsh answer (at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); dsh $(clean dsh --version 2>&1 | tail -1) ($(command -v dsh)); node $(node --version 2>&1)"
  local GR; GR=$(grepo) || return 1
  print "graftling candidate: $GR ${GCOMMIT} ($(git -C $GR log -1 --format=%s $GCOMMIT))"
  print "isolated layout: BASE=$BASE  work=$W  venv=$V  DSH_HOME=$DH (never ~/.dsh)"
  local Wh=$BASE/wheels; mkdir -p $Wh $W $DH
  if [[ ! -f $V/installed || $(<$V/installed) != "$GCOMMIT" ]]; then
    rm -f $Wh/graftling-*.whl(N)
    wheel $GR $GCOMMIT src/graftling $Wh || { print "STOP: the graftling wheel did not build"; return 1; }
    local gw; gw=$(need $Wh 'graftling-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V; deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw
    print -r -- "$GCOMMIT" > $V/installed
  else print "venv $V already holds graftling ${GCOMMIT[1,10]}"; fi
  (cd $BASE && clean $V/bin/python -I -c 'import graftling, importlib.metadata as m
print("venv: graftling", m.version("graftling"), "from", graftling.__file__)')
  same_blob $GR $(gdsh)/client.mjs \
    && print "venv graftling-dsh client.mjs = candidate's file" || { print "STOP: venv client.mjs differs from $GCOMMIT"; return 1; }
  say "patch: llm = DeepSeek provider row; graftling host config for the agents-host row"
  llm_patch > $BASE/llm.patch.yml
  $V/bin/python -I -c 'import json, sys
root, dsh, model, out = sys.argv[1:5]
json.dump({"root": root, "dsh": {"executable": dsh, "model": model, "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}},
  open(out, "w"), indent=2)' $BASE/graftling-data $(command -v dsh) $MODEL $BASE/dsh-host.json
  mkdir -p $BASE/graftling-data; print "save_normalized_sessions: true" > $BASE/graftling-data/config.yml
  say "isolated web profile $WEB in $DH (fresh copy of the shipped web template on first run), then graftling-dsh"
  if [[ ! -f $DH/profiles/$WEB/package.json ]]; then
    (cd $BASE && clean dsh --profile $WEB --from-default-profile web --dump-config > $BASE/web-dump-config.txt 2>&1) \
      && print "profile $WEB: created ($DH/profiles/$WEB)" || { print "STOP: the web profile was not created:"; tail -5 $BASE/web-dump-config.txt; return 1; }
  else print "profile $WEB: present ($DH/profiles/$WEB)"; fi
  mkdir -p $BASE/bin; printf '#!/bin/sh\nexec node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs "$@"\n' > $BASE/bin/pnpm
  chmod +x $BASE/bin/pnpm
  if ! has_plugin || { [[ -z ${VERIFY527_ASSUME_PLUGIN:-} ]] && ! same_client; }; then
    print "graftling-dsh missing from $WEB or not the candidate's: trying dsh plugin add here (fails inside the Claude sandbox: pnpm store lock EPERM)"
    (cd $BASE && clean PATH=$BASE/bin:${(j.:.)path} npm_config_store_dir=$BASE/pnpm-store $BOUND 300 \
       dsh plugin --profile $WEB add $(gdsh) > $BASE/plugin-add.txt 2>&1) && print "dsh plugin add: rc 0" \
      || { print "dsh plugin add failed (rc $?):"; grep -vi npmrc $BASE/plugin-add.txt | grep -v '^ *$' | tail -4 | sed 's/^/  /'; }
  fi
  if ! has_plugin || { [[ -z ${VERIFY527_ASSUME_PLUGIN:-} ]] && ! same_client; }; then
    print -r -- "
STOP: the candidate graftling-dsh is not in web profile $WEB ($DH/profiles/$WEB; installed client: $(installed_client)).
USER: open a plain Terminal (Terminal.app, not this sandbox) and paste this one line (dialog: none expected):
  $(plugin_cmd)
It ends with dsh's plugin summary and no error. Then Main reruns: zsh $THIS 0"
    return 1
  fi
  if [[ -n ${VERIFY527_ASSUME_PLUGIN:-} ]]; then print "REHEARSAL: installed client.mjs check skipped (plugin assumed)"
  else print "graftling-dsh: in $WEB, installed client.mjs = candidate's file (${$(installed_client):A})"; fi
  # What the candidate graftling-dsh browser bundle registers: tool.call.toolview keys (expected none) and the slots it
  # injects into (expected conversation.chat.node only: the incoming agent-message attribution).
  node -e '
const { readFileSync } = require("node:fs"); const vm = require("node:vm"); let m;
vm.runInNewContext(readFileSync(process.argv[1], "utf8"), { window: { __ModuleLoader__: { load(d) { m = d; } } } });
const keys = [], slots = [];
m.factory(() => ({ createElement: () => ({}) })).apply({ slots: { inject: (n, f) => { slots.push(n); f(); },
  entriesOfSlot: () => [], subscribe: () => () => {},
  register: (o) => { if (o.name === "tool.call.toolview") keys.push(o.key); return () => {}; } } });
console.log("graftling-dsh tool view keys: " + JSON.stringify(keys) + "; injected slots: " + JSON.stringify(slots));' \
    $(gdsh)/client.mjs | tee $BASE/client-view-keys.txt
  say "composed web profile (dsh --dump-config; rows that matter)"
  (cd $W && clean GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$BASE/dsh-host.json \
     dsh --profile $WEB --patch $BASE/llm.patch.yml --dump-config > $BASE/US-dump-config.txt 2>&1) || print "US dump-config rc=$?"
  print "US rows: $(grep -oE '^- id: (agents-host|llm-deepseek)$' $BASE/US-dump-config.txt | cut -c7- | tr '\n' ' ')(expected agents-host llm-deepseek)"
  print "configured model (agent-default-model row): $(grep -A4 '^- id: agent-default-model$' $BASE/US-dump-config.txt | grep -E 'provider:|model:' | tr -s ' \n' ' ')"
  if [[ -n ${VERIFY527_NOMODEL:-} ]]; then print "VERIFY527_NOMODEL: no model call (rehearsal)"
  else
    load_key || return 1
    (cd $BASE && clean $BOUND 120 dsh --profile headless --patch $BASE/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-527, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  fi
  print "Ready when: venv graftling from ${GCOMMIT[1,10]}, the candidate graftling-dsh in $WEB, view keys [] with injected slots [\"conversation.chat.node\"], US rows agents-host llm-deepseek, and one READY-527 line naming the model."
  print -r -- "next (USER, plain Terminal): zsh $THIS US"
  ;;
US)
  where "Main's Bash or a Terminal (this step only prints). The server line below: the USER's plain Terminal (Terminal.app, not the Claude sandbox: it serves a local port and opens the browser), then the browser."
  [[ -f $V/installed && -f $BASE/llm.patch.yml && -f $BASE/dsh-host.json ]] || { print "STOP: run step 0 first"; return 1; }
  has_plugin || { print "STOP: graftling-dsh is not in $WEB; run step 0 (it prints the plugin command)"; return 1; }
  local shot=$BASE/screenshot-US.png
  PROMPT_TEXT > $BASE/prompt-US.txt
  say "[US] graftling alone (graftling-dsh agents-host row, candidate ${GCOMMIT[1,10]}): one $TOOL call in the browser UI of the isolated web profile $WEB. One model call."
  print -r -- "Dialogs: exactly one native dialog, the macOS folder chooser in step 1b; in it you choose the folder
  $W
(on a launch that is not loopback DSH shows its in-app browse dialog instead). Inside the page DSH may ask to approve
the tool call: approve it once.

1. In a plain Terminal where DEEPSEEK_API_KEY is set as usual (check: echo \${DEEPSEEK_API_KEY:+set}), paste this one line:

cd $W && env DSH_HOME=$DH PATH=/opt/homebrew/bin:\$PATH GRAFTLING_PYTHON=$V/bin/python GRAFTLING_DSH_CONFIG=$BASE/dsh-host.json $(command -v dsh) --profile $WEB --patch $BASE/llm.patch.yml --port 0

   It prints the served URL (http://127.0.0.1:<port>/...) and opens it in the default browser. If no browser opens,
   open that printed URL yourself.
1b. Add and select the workspace first: the page creates the Session in the workspace selected in the page, not in
   the server's cwd. Click the composer's 'ワークスペースを選択' (or the sidebar workspace menu) -> 'ワークスペースを追加…'.
   The folder chooser opens (native macOS chooser; in-app browse dialog otherwise). Native: press Cmd-Shift-G;
   in-app: edit the path field. Enter exactly:
     $W
   and choose 開く/Open. Then select that workspace ('${W:t}') in the composer.
2. In the page start a NEW conversation (新規セッション, workspace '${W:t}') and paste this prompt exactly
   (also in $BASE/prompt-US.txt):

$(<$BASE/prompt-US.txt)

3. Wait for the reply line DONE-527-US. If the group 'ツールを呼び出しました' is collapsed, click it open. Then click the
   disclosure arrow (or the title) of the card 'ツール呼び出し · $TOOL · execute' so that its IN and OUT show.
4. Screenshot the expanded card with its title, IN and OUT, plus the DONE-527-US reply line (Cmd-Shift-4, drag).
   Save or move it to exactly:
     $shot
5. Stop the server with Ctrl-C in that Terminal.

Observable: $shot exists and shows, for this conversation's $TOOL call, DSH's native card titled
'ツール呼び出し · $TOOL · execute' with IN (the JSON arguments) and OUT, and no 'agents · status · …' row and no
'Details' button (as mcp__graphtraj__agents in 522's screenshot-UG.png, unlike 522's screenshot-US.png).
The conclusion is only what the screenshot shows."
  print -r -- "next: zsh $THIS C (Main's Bash)"
  ;;
C)
  where "Main's Bash (reads only)."
  say "[C] the screenshot, the agents tool names in the isolated DSH home $DH, and web527's installed client. Dialog: none."
  [[ -f $BASE/screenshot-US.png ]] && print "screenshot-US.png: $(stat -f '%z bytes, %Sm' $BASE/screenshot-US.png)" \
    || print "screenshot-US.png: MISSING ($BASE/screenshot-US.png)"
  print "agents tool names in $DH (excluding profiles/), files and counts:"
  grep -rIoE 'mcp__(graftling|graphtraj|agents)__agents' $DH --exclude-dir=profiles 2>/dev/null | sort | uniq -c | sed 's/^/  /' \
    || print "  (none)"
  local rc=0; same_client || rc=$?
  case $rc in
    0) print "web527 installed graftling-dsh client.mjs: SAME as ${GCOMMIT}:src/graftling/dsh/client.mjs (${$(installed_client):A})" ;;
    1) [[ -f $(installed_client) ]] && print "web527 installed graftling-dsh client.mjs: DIFFERS from ${GCOMMIT[1,10]} (${$(installed_client):A})" \
         || print "web527 installed graftling-dsh client.mjs: MISSING ($(installed_client))" ;;
    *) print "web527 installed graftling-dsh client.mjs: not compared (candidate commit not found)" ;;
  esac
  print "Main reads the screenshot (Read tool) and records only what it shows."
  ;;
*) print -r -- "usage: zsh $THIS 0|US|C"; return 2 ;;
esac
