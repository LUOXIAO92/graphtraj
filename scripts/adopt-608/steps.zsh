#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 608 Main-run steps: a graftling DSH child (and DSH model listing) on a provider DSH serves through its llm-pi-ai
# route, keyed only by the connection's api_key_env. graftling only, no GraphTraj. Modelled on verify-591/steps.zsh.
# PROVIDER (user decision, Worldline 20261124T210658.357614+0900): OpenCode, key variable OPENCODE_API_KEY (the user
# says it serves deepseek and glm5.3 models). The DSH provider id (opencode-go or opencode) and the model id are NOT
# assumed: `list` reads them from graftling's real DSH listing, `probe` keeps the first candidate DSH answers with.
# glm models are preferred so the child is clearly not DeepSeek.
# ACCEPTANCE ENTRY: a real Pi Main (DeepSeek) with the candidate installed as a WHEEL calls mcp__graftling__subagents
# itself and creates real DSH children; verdicts read Pi's Session file, the child record under
# <project>/.agents-control, the child's native DSH trace and the child DSH process's environment NAMES. No stub.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre        Main. ROOT must not exist (STOP with the exact rm otherwise) and is created. Versions (zsh, node, pi, dsh,
#              git); the bundle verifies and its head is GCOMMIT; DEEPSEEK_API_KEY and OPENCODE_API_KEY set (names and
#              lengths only); the allowlisted environment's names; 'before' state of ~/.pi/agent (names + sha256
#              prefixes), ~/.dsh, ~/.codex and ~/.graphtraj/connections.yml (names + mtimes); the Pi Main's deepseek
#              flash id and a ONE-LINE Pi prompt. Dialog: none. Network: api.deepseek.com. ~1 min.
#   install    Main. ROOT/venv-cand: the candidate as a WHEEL (graftling only; no network: PyYAML and websockets copied
#              from <Harness>/.venv-runtime); graftling's DSH listing for deepseek-official picks the deepseek child's
#              flash model; a ONE-LINE DSH prompt with it (DSH_HOME=ROOT/dsh-home, DEEPSEEK_API_KEY the only
#              credential); `pi install` of the candidate's Pi package into ROOT/agent-cand. Dialog: none. Network:
#              api.deepseek.com. ~1-2 min.
#   list       Main. graftling discover_models (the candidate) for runtime dsh, provider opencode-go and opencode,
#              api_key_env OPENCODE_API_KEY, DSH_HOME=ROOT/dsh-home; OPENCODE_API_KEY the only credential. Prints for
#              each provider its status, provider_status and model ids (names only); the deepseek-official refusal
#              checks (no api_key_env; an unknown provider). Writes ROOT/opencode-listing.json and the ordered
#              candidates ROOT/opencode-candidates.txt (glm first); STOP if neither provider lists one. Dialog: none.
#              Network: none expected (DSH answers a catalog route from its installed catalog). ~1 min.
#   probe      Main. A ONE-LINE DSH prompt on each candidate in order (DSH_HOME=ROOT/dsh-probe-home, fresh; only
#              OPENCODE_API_KEY), with the child's llm-pi-ai route and DSH's default model set to the candidate; the
#              first that answers is written to ROOT/opencode-choice.txt. STOP if none answers. Dialog: none.
#              Network: opencode.ai. ~1-3 min.
#   child-opencode  Main. A real Pi Main (deepseek flash; env DEEPSEEK_API_KEY + OPENCODE_API_KEY) in ROOT/proj-opencode,
#              whose .agents-control/config.yml declares ONE dsh connection opencode-dsh {provider <choice>,
#              api_key_env OPENCODE_API_KEY} without models (create verifies the model by graftling's real listing),
#              creates ONE dsh child with the chosen model through mcp__graftling__subagents and waits for it. A sampler
#              reads the child DSH process's environment (ps -E on the record's runtime_pid; NAMES only). Verdicts:
#              tool calls/results; the one new record (connection opencode-dsh, model, completed 'ready'); the native
#              DSH trace names (provider, model); the only credential-class variable is OPENCODE_API_KEY.
#              Dialog: none. Network: api.deepseek.com (Main), opencode.ai (child). ~2-4 min.
#   child-deepseek  Main. The same in ROOT/proj-deepseek without config.yml (deepseek-official, the existing path):
#              a dsh child on the install step's flash model; the only credential-class variable is DEEPSEEK_API_KEY
#              although the Main also carries OPENCODE_API_KEY. Dialog: none. Network: api.deepseek.com. ~2-4 min.
#   post       Main. ~/.pi/agent, ~/.dsh, ~/.codex and ~/.graphtraj/connections.yml vs pre (any difference FAILs). <5 s.
#   suite      Main. graftling's full suite on GCOMMIT: a clean clone from the bundle in SROOT, a venv with conda's
#              pytest and graftling editable (no network), TMPDIR=${TMPDIR:-/tmp} outside the Harness (checked and
#              printed). Foreground. Dialog: none. No login. ~5-15 min. ADOPT608_PYTEST_ARGS='<args>' (rehearsal only).
#   SR         Read only: the newest suite log's summary and FAILED/ERROR node ids; for any, the ready-to-paste
#              suite-base command. Dialog: none.
#   suite-base Main, only if SR lists failures: reruns exactly those node ids on graftling dev BASE in SROOT; per id
#              'also fails on base' (not new) or 'candidate-only' (NEW). Dialog: none. No login.
# Order: pre, install, list, probe, child-opencode, child-deepseek, post. suite and SR (suite-base) need no ROOT and no key.
# Credentials (correction 1): at start, before any step, the script unsets every exported variable whose name is
# credential-class (graftling's is_credential_name, restated in judge.py: a '_'-separated part ending in KEY, TOKEN,
# SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) other than DEEPSEEK_API_KEY and OPENCODE_API_KEY,
# printing the removed NAMES. So every process a step starts (pi, dsh, python, judge, sampler, pip, git, ps, pgrep, ...)
# holds at most those two. suite and suite-base also drop those two before they start anything (the tests need
# neither) and say so. On top of that, pi, dsh and graftling's python run through allow(): only PATH,
# HOME=ROOT/home, TMPDIR, LANG, PI_CODING_AGENT_DIR, the step's own variables (shown by name) and the credentials that
# step names: DEEPSEEK_API_KEY (the Pi Main, the deepseek child, its listing and prompt) and OPENCODE_API_KEY (list,
# probe, and the Pi Main of child-opencode, which must hold it to hand it to its child). Keys are never printed
# and never arguments. These steps never read or write ~/.dsh, ~/.pi, ~/.codex, ~/.claude or
# ~/.graphtraj/connections.yml (names, hashes of ~/.pi/agent files and mtimes only, as 591). Writes outside ROOT and
# SROOT: none expected. ADOPT608_ROOT / _OUT / _BUNDLE / _GCOMMIT / _SUITE_ROOT / _PYTEST_ARGS / _USERHOME are for the
# Engineer's rehearsal only; a run with any of them set is a rehearsal, not acceptance evidence.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${ADOPT608_ROOT:-/private/tmp/graftling-608}
SROOT=${ADOPT608_SUITE_ROOT:-/private/tmp/graftling-608-suite}
OUT=${ADOPT608_OUT:-$H/.graphtraj/core/state/tasks/608-graftling-dsh-multi-provider/realhost}
BASE=aa40b184b25acb21599d196a32cdafc1579dc6c2       # graftling dev (619db60 + Task 605), this Task's base
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/608-graftling-dsh-multi-provider
GCOMMIT=${ADOPT608_GCOMMIT:-ccff30e1d8160b50cab2432f0b9bcac9a56fda05}  # the graftling candidate (parent BASE)
BUNDLE=${ADOPT608_BUNDLE:-$WT/scripts/adopt-608/graftling-608.bundle}
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
JUDGE=${0:A:h}/judge.py
UH=${ADOPT608_USERHOME:-$HOME}                      # your home: its .pi/agent, .dsh, .codex, .graphtraj are only listed
DH=$ROOT/dsh-home                                   # isolated DSH home of the listings and the deepseek prompt
MODELF=$ROOT/pi-model.txt                           # the Pi Main's deepseek model id (pre)
DMODELF=$ROOT/dsh-model.txt                         # the deepseek child's model (install)
LISTF=$ROOT/opencode-listing.json                   # list: the opencode listings
CANDF=$ROOT/opencode-candidates.txt                 # list: "provider model" lines, probe order
CHOICEF=$ROOT/opencode-choice.txt                   # probe: the "provider model" DSH answered with
OKEY=OPENCODE_API_KEY
DKEY=DEEPSEEK_API_KEY
PTOOL=mcp__graftling__subagents
THIS=${0:A}
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
PIPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
path=(/opt/homebrew/bin $path)

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
gcommit() { [[ -n $GCOMMIT ]] || { print -r -- "STOP: GCOMMIT is not set"; return 1; } }
key_ready() {  # variable names
  local k; for k in "$@"; do
    [[ -n ${(P)k:-} ]] && continue
    print -r -- "STOP: $k is not set (Main asks the user first). Fix: export $k=<the key>; zsh $THIS $STEP"; return 1
  done
}
# Run "$@" with ONLY the allowlisted variables and the named credentials.
# Usage: allow <credentials, comma-separated or -> <agent dir> [NAME=value...] -- command...
allow() {
  local creds=$1 a=$2; shift 2; local -a add=() keep=(${(s:,:)creds:#-})
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k
    for k in ${(k)parameters[(R)*export*]}; do (( ${keep[(Ie)$k]} )) || unset $k 2>/dev/null; done
    export PATH=$PIPATH HOME=$ROOT/home TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8 PI_CODING_AGENT_DIR=$a
    (( $#add )) && export "${add[@]}"
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,TMPDIR,LANG,PI_CODING_AGENT_DIR${keep:+,${(j:,:)keep}}${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# Your locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes otherwise), never contents.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  ls -laT $UH/.codex 2>&1 | awk 'NF >= 10 && $10 != ".." {print "codex", $6, $7, $8, $9, $10}'
  [[ -e $UH/.graphtraj/connections.yml ]] && ls -lT $UH/.graphtraj/connections.yml | awk '{print "graphtraj", $6, $7, $8, $9, $10}' \
    || print -r -- "graphtraj connections.yml absent"
}
pimodel() { [[ -s $MODELF ]] && print -r -- "$(<$MODELF)" || { print -r -- "STOP: $MODELF missing; run: rm -rf $ROOT && zsh $THIS pre" >&2; return 1; } }
venv() { print -r -- $ROOT/venv-$1; }
site() { print -r -- $(venv $1)/lib/python3.13/site-packages/graftling; }
mkproj() { rm -rf $1 && mkdir -p $1 && git -C $1 init -q; }
# Builds a venv with graftling installed as a WHEEL from commit $2 of the bundle; graftling only (as verify-591).
build_venv() {  # dir commit
  local v=$1 c=$2 S=$1-src
  [[ -f $v/installed && $(<$v/installed) == $c* ]] && { print -r -- "reusing $v ($(<$v/installed))"; return 0; }
  rm -rf $v $S && mkdir -p $S/graftling $S/wheels || return 1
  git clone -q --no-checkout $GREPO $S/repo && git -C $S/repo fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $S/repo archive $c | tar -x -C $S/graftling || { print -r -- "STOP: graftling $c not found"; return 1; }
  $CONDA -m venv $v || return 1
  local D=$($v/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ || return 1
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $v/bin/python -m pip install $pip $S/wheels/graftling-*.whl || return 1
  local got; got=$(cd / && $v/bin/python -I -c 'import graftling, yaml, websockets, importlib.util as u; print(graftling.__version__, graftling.__file__, "| graphtraj importable:", u.find_spec("graphtraj") is not None)') \
    || { print -r -- "STOP: $v cannot import graftling with its dependencies"; return 1; }
  [[ $got == *'graphtraj importable: False' ]] || { print -r -- "STOP: graphtraj is importable in $v: $got"; return 1; }
  print -r -- "$c $got" > $v/installed; print -r -- "$v: $(<$v/installed)"
}
defaults() {  # agent dir, model: Pi's default provider/model there
  python3 -I -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "settings.json"; s = json.loads(p.read_text()) if p.exists() else {}
s.update(defaultProvider="deepseek", defaultModel=sys.argv[2]); p.write_text(json.dumps(s, indent=2))
print("settings.json: packages", s.get("packages"), "| default", s["defaultProvider"], s["defaultModel"])' $1 $2
}
# One-line DSH prompt: patch file, DSH home, credential, label. The answer and DSH's configured route are printed.
dsh_prompt() {
  local patch=$1 home=$2 cred=$3 label=$4 log=$ROOT/dsh-prompt-$4.txt rc
  say "one-line DSH prompt ($label): dsh --profile headless --patch $patch (DSH_HOME=$home; credential $cred only)"
  local dumped; dumped=$(cd $ROOT && allow $cred $ROOT/agent-probe DSH_HOME=$home -- dsh --profile headless --patch $patch --dump-config < /dev/null 2>&1)
  print -r -- "configured (from --dump-config): $(print -r -- $dumped | awk '/^- id: (llm-pi-ai|agent-default-model|llm-deepseek)$/ {f=1; print; next} f && /^- id:/ {f=0} f' | grep -E 'id:|provider|model|apiKeyEnv|  [a-z0-9-]+:$' | xargs)"
  print -r -- "login: $cred from the allowlisted environment (set, ${#${(P)cred}} characters, not printed); $home/.credentials.yaml $([[ -e $home/.credentials.yaml ]] && print PRESENT || print absent), $home/.env $([[ -e $home/.env ]] && print PRESENT || print absent)"
  (cd $ROOT && allow $cred $ROOT/agent-probe DSH_HOME=$home -- perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless --patch $patch \
     "Reply in one line with the exact model id you are running as, nothing else." < /dev/null) > $log 2>&1; rc=$?
  tail -5 $log; print -r -- "exit=$rc (full output: $log)"
  return $rc
}
create_prompt() {  # tool, child runtime, child model
  print -r -- 'Use the MCP tool '$1' (not any built-in Task or Agent tool of yours). Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"'$2'","model":"'$3'","instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
Do not retry or change any argument. Then report exactly two lines: AGENT: the agent id; ANSWER: the child'"'"'s answer. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
}
# Samples, while the Main runs, the environment NAMES of each new child DSH process (ps -E on its runtime_pid).
sampler() {  # data root, snap, env dir, Main pid
  local root=$1 snap=$2 dir=$3 main=$4 pid
  mkdir -p $dir; : > $dir/sampler.log
  while kill -0 $main 2>/dev/null; do
    for pid in ${(f)"$(python3 -I $JUDGE pids $root $snap 2>>$dir/sampler.log)"}; do
      [[ -n $pid && ! -e $dir/env-$pid.txt ]] || continue
      kill -0 $pid 2>/dev/null || { print -r -- "pid $pid already gone" >> $dir/sampler.log; continue; }
      ps -E -ww -o command= -p $pid 2>>$dir/sampler.log | python3 -I $JUDGE envnames $dir/env-$pid.txt >> $dir/sampler.log 2>&1
      [[ -s $dir/env-$pid.txt ]] || { rm -f $dir/env-$pid.txt; print -r -- "pid $pid: ps -E gave nothing" >> $dir/sampler.log; }
    done
    sleep 0.2
  done
}
# A real Pi Main in project $1 creates one dsh child with model $2; credentials $3; judged against connection $4,
# provider $5 and the child's expected only credential $6.
child_case() {
  local P=$1 dmodel=$2 creds=$3 conn=$4 prov=$5 want=$6 model
  local root=$P/.agents-control snap=$ROOT/${P:t}-before.ids SD=$ROOT/sessions-${P:t} SOUT=$ROOT/${P:t}.txt ED=$ROOT/env-${P:t}
  model=$(pimodel) || return 1
  : > $snap; rm -rf $SD $ED; mkdir -p $SD $ED
  say "pi -p --provider deepseek --model $model --approve --session-dir $SD '<create+wait+status prompt: dsh, $dmodel>'"
  print -r -- "Main environment (names; values not printed): $(allow $creds $ROOT/agent-cand DSH_HOME=$DH -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  ( cd $P && allow $creds $ROOT/agent-cand DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 600 pi -p --provider deepseek --model $model \
      --approve --session-dir $SD "$(create_prompt $PTOOL dsh $dmodel)" ) < /dev/null > $SOUT 2>&1 &
  local main=$!
  sampler $root $snap $ED $main &
  local spid=$!
  wait $main; local src=$?
  wait $spid
  tail -8 $SOUT; print -r -- "exit=$src (full output: $SOUT)"
  print -r -- "sampler log: $(tr '\n' ' ' < $ED/sampler.log)"
  cp $SOUT $OUT/ 2>/dev/null; cp -R $ED $OUT/ 2>/dev/null
  say "verdict (computed)"
  OK=1
  (( src == 0 )) && pass "the Pi Main exited 0" || fail "the Pi Main exited $src"
  python3 -I $JUDGE pi $SD $SOUT $root $snap $PTOOL ready "$conn" $prov $dmodel $ED $want || OK=0
  print -r -- "follow-up (paste): python3 -I $JUDGE pi $SD $SOUT $root $snap $PTOOL ready '$conn' $prov $dmodel $ED $want"
  print -r -- "processes still naming $P (expect none): $(pgrep -fl -- $P 2>/dev/null | head -3 | tr '\n' ' ')"
  (( OK ))
}
run_root() {  # label: a fresh pytest temp root under TMPDIR, outside the Harness; sets RUNTMP
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/adopt-608-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
}
suite_tree() {  # dir commit: a clean checkout in $1/src and a venv $1/venv (conda's pytest, graftling editable)
  local S=$1 c=$2
  if [[ ! -d $S/src/.git || $(git -C $S/src rev-parse HEAD 2>/dev/null) != $c || -n $(git -C $S/src status --porcelain 2>/dev/null) ]]; then
    rm -rf $S && mkdir -p $S || return 1
    git clone -q --no-checkout $GREPO $S/src && git -C $S/src fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" \
      && git -C $S/src -c advice.detachedHead=false checkout -q $c || { print -r -- "STOP: cannot check out $c"; return 1; }
  fi
  print -r -- "suite source: $S/src at $(git -C $S/src rev-parse HEAD) (clean: $([[ -z $(git -C $S/src status --porcelain) ]] && print yes || print NO))"
  if [[ ! -f $S/venv/installed ]]; then
    $CONDA -m venv --system-site-packages $S/venv || return 1
    local D=$($S/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
    for m in yaml websockets; do
      $S/venv/bin/python -I -c "import $m" 2>/dev/null && continue
      case $m in
        yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
        *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
      esac || return 1
    done
    $S/venv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S/src > $S/pip.txt 2>&1 || { tail -5 $S/pip.txt; print -r -- "STOP: editable install failed ($S/pip.txt)"; return 1; }
    print -r -- $c > $S/venv/installed
  fi
  (cd / && $S/venv/bin/python -I -c 'import graftling, pytest, importlib.util as u; print("imports graftling", graftling.__version__, "from", graftling.__file__, "| pytest", pytest.__version__, "| graphtraj importable:", u.find_spec("graphtraj") is not None)')
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  gcommit && key_ready $DKEY $OKEY || return 1
  mkdir -p $ROOT/home $ROOT/agent-probe $DH $OUT || return 1
  print -r -- "zsh $ZSH_VERSION ($THIS)"
  local t; for t in node git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  for t in pi dsh; do print -r -- "$t: $(command -v $t) $(cd $ROOT && allow - $ROOT/agent-probe DSH_HOME=$DH -- $t --version < /dev/null 2>&1 | head -1)"; done
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { print -r -- "STOP: bundle does not verify"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | cut -d' ' -f1) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head is not $GCOMMIT"; return 1; }
  print -r -- "$DKEY: set (${#DEEPSEEK_API_KEY} characters; not printed). $OKEY: set (${#OPENCODE_API_KEY} characters; not printed)."
  print -r -- "allowlisted environment, e.g. child-opencode's Main (names only): $(allow $DKEY,$OKEY $ROOT/agent-probe EXAMPLE_STEP_VAR=1 -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "the Pi Main's model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$ROOT/agent-probe; $DKEY only)"
  local listed; listed=$(cd $ROOT && allow $DKEY $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $MODELF
  [[ -s $MODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  say "one-line Pi prompt: pi -p --provider deepseek --model $(<$MODELF) --no-session --no-extensions --no-tools"
  (cd $ROOT && allow $DKEY $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi -p --provider deepseek --model $(<$MODELF) \
     --no-session --no-extensions --no-tools "Reply in one line: the exact model id and the provider you are running as, nothing else." \
     < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc (login: $DKEY from the allowlisted environment)"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer; check $DKEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "Pi Main model: deepseek/$(<$MODELF)"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. venv-cand ($GCOMMIT), deepseek-official DSH listing and one-line prompt, agent-cand. Dialog: none."
  gcommit && need $MODELF pre && key_ready $DKEY || return 1
  build_venv $(venv cand) $GCOMMIT || return 1
  say "graftling's DSH listing for deepseek-official ($(venv cand)/bin/python; DSH_HOME=$DH; $DKEY only)"
  (cd $ROOT && allow $DKEY $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 180 $(venv cand)/bin/python -I -c '
import sys
from graftling.models import discover_models
found = discover_models({"runtime": "dsh"})
models = found.get("models") or []
print("status", found.get("status"), "| provider_status", found.get("provider_status"), "|", found.get("message") or "")
for m in models: print("  model", m["provider"], m["id"])
flash = [m["id"] for m in models if m["provider"] == "deepseek-official" and "flash" in m["id"].lower()]
if flash: open(sys.argv[1], "w").write(flash[0]); print("chosen", flash[0])
' $DMODELF) 2>&1 | tail -12
  [[ -s $DMODELF ]] || { print -r -- "STOP: no deepseek-official flash model; see above. Then: zsh $THIS install"; return 1; }
  print -r -- "- id: llm-deepseek
  config:
    models:
      - id: $(<$DMODELF)" > $ROOT/dsh-deepseek.patch.yml
  dsh_prompt $ROOT/dsh-deepseek.patch.yml $DH $DKEY deepseek \
    || { print -r -- "STOP: DSH could not answer on deepseek-official (above). Check $DKEY and api.deepseek.com; then: zsh $THIS install"; return 1; }
  pass "DSH answered on deepseek-official $(<$DMODELF) (login: $DKEY)"
  local a=$ROOT/agent-cand model; model=$(pimodel) || return 1
  rm -rf $a && mkdir -p $a || return 1
  say "PI_CODING_AGENT_DIR=$a pi install $(site cand)/pi"
  allow - $a -- pi install $(site cand)/pi < /dev/null 2>&1 | tail -3
  defaults $a $model
  allow - $a -- pi list < /dev/null 2>&1 | head -6
  pass "installed; deepseek child model: $(<$DMODELF)"
  print -r -- "next: zsh $THIS list"
  ;;
list)
  say "[list] Main. graftling's DSH listing for opencode-go and opencode, api_key_env $OKEY (DSH_HOME=$DH; $OKEY only). Dialog: none."
  need $(venv cand)/installed install && key_ready $OKEY || return 1
  [[ $(<$(venv cand)/installed) == $GCOMMIT* ]] || { print -r -- "STOP: $(venv cand) is not $GCOMMIT; rerun: zsh $THIS install"; return 1; }
  (cd $ROOT && allow $OKEY $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 300 $(venv cand)/bin/python -I -c '
import json, sys
from graftling.models import discover_models
key = sys.argv[2]
everything = {}
for provider in ("opencode-go", "opencode"):
    found = discover_models({"runtime": "dsh", "provider": provider, "api_key_env": key})
    everything[provider] = found
    models = found.get("models") or []
    ids = [m["id"] for m in models]
    print(provider + ":", "status", found.get("status"), "|", found.get("message"))
    print("  provider_status", found.get("provider_status"))
    print("  " + str(len(ids)), "models, every one with provider", provider + ":", all(m["provider"] == provider for m in models))
    print("  ids: " + " ".join(ids))
json.dump(everything, open(sys.argv[1], "w"), indent=1)
for connection, label in (({"provider": "opencode-go"}, "no api_key_env"), ({"provider": "no-such-608", "api_key_env": key}, "unknown provider")):
    try:
        discover_models({"runtime": "dsh", **connection})
        print(f"FAIL: {label}: not refused")
    except ValueError as error:
        print(f"PASS: {label} refused: {error}")
' $LISTF $OKEY) 2>&1 | tail -20
  [[ -s $LISTF ]] || { print -r -- "STOP: the listing wrote nothing (above). Then: zsh $THIS list"; return 1; }
  cp $LISTF $OUT/ 2>/dev/null
  python3 -I $JUDGE pick $LISTF $CANDF \
    || { print -r -- "STOP: neither opencode-go nor opencode lists a usable model with $OKEY (above). Report it to the Leader."; return 1; }
  print -r -- "next: zsh $THIS probe"
  ;;
probe)
  say "[probe] Main. One-line DSH prompt on each candidate of $CANDF until one answers ($OKEY only). Dialog: none."
  need $CANDF list && key_ready $OKEY || return 1
  local line prov mdl n=0; rm -f $CHOICEF
  for line in ${(f)"$(<$CANDF)"}; do
    prov=${line%% *} mdl=${line#* }; (( ++n ))
    local home=$ROOT/dsh-probe-home-$n patch=$ROOT/dsh-probe-$n.patch.yml
    rm -rf $home && mkdir -p $home
    print -r -- "- id: llm-pi-ai
  config:
    providers:
      $prov:
        apiKeyEnv: $OKEY
- id: agent-default-model
  config:
    provider: $prov
    model: $mdl" > $patch
    if dsh_prompt $patch $home $OKEY probe-$n; then
      print -r -- "$prov $mdl" > $CHOICEF
      pass "DSH answered on provider $prov model $mdl with $OKEY only (no $DKEY in its environment, fresh DSH home)"
      break
    fi
    print -r -- "candidate $prov $mdl did not answer (above); trying the next"
  done
  [[ -s $CHOICEF ]] || { print -r -- "STOP: DSH answered on no candidate of $CANDF with $OKEY (outputs: $ROOT/dsh-prompt-probe-*.txt). Report it to the Leader."; return 1; }
  cp $CHOICEF $ROOT/dsh-prompt-probe-*.txt $OUT/ 2>/dev/null
  print -r -- "choice: $(<$CHOICEF)"
  print -r -- "next: zsh $THIS child-opencode"
  ;;
child-opencode)
  need $CHOICEF probe && need $ROOT/agent-cand/settings.json install && key_ready $DKEY $OKEY || return 1
  local prov mdl; read prov mdl < $CHOICEF
  local P=$ROOT/proj-opencode
  say "[child-opencode] Main. Pi Main (deepseek) in $P creates ONE dsh child on $prov/$mdl (connection opencode-dsh, api_key_env $OKEY) through $PTOOL. Dialog: none."
  mkproj $P && mkdir -p $P/.agents-control || return 1
  print -r -- "connections:
  opencode-dsh:
    runtime: dsh
    provider: $prov
    api_key_env: $OKEY" > $P/.agents-control/config.yml
  print -r -- "$P/.agents-control/config.yml:"; cat $P/.agents-control/config.yml
  child_case $P $mdl $DKEY,$OKEY opencode-dsh $prov $OKEY
  local rc=$?
  (( rc == 0 )) && print -r -- "SUCCESS: a real DSH child ran on $prov/$mdl with $OKEY as its only credential" \
    || print -r -- "NOT ACCEPTED (FAIL lines above); report them. The next step still runs."
  print -r -- "next: zsh $THIS child-deepseek"
  return $rc
  ;;
child-deepseek)
  need $DMODELF install && need $ROOT/agent-cand/settings.json install && key_ready $DKEY $OKEY || return 1
  local P=$ROOT/proj-deepseek
  say "[child-deepseek] Main. Pi Main (deepseek) in $P (no config.yml: deepseek-official) creates ONE dsh child ($(<$DMODELF)) through $PTOOL; the Main also holds $OKEY. Dialog: none."
  mkproj $P || return 1
  child_case $P $(<$DMODELF) $DKEY,$OKEY '' deepseek-official $DKEY
  local rc=$?
  (( rc == 0 )) && print -r -- "SUCCESS: the deepseek-official DSH child still completes, holding only $DKEY" \
    || print -r -- "NOT ACCEPTED (FAIL lines above); report them."
  print -r -- "next: zsh $THIS post"
  return $rc
  ;;
post)
  say "[post] Main. Your ~/.pi/agent, ~/.dsh, ~/.codex and ~/.graphtraj/connections.yml vs pre (any difference FAILs). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "your locations are unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT/*.txt (copied to $OUT). To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
suite)
  gcommit || return 1
  unset $DKEY $OKEY; print -r -- "keys: $DKEY and $OKEY dropped for this step (the tests need neither); python3 now sees: $(python3 -I $JUDGE selfenv)"
  say "[suite] Main. graftling full suite on $GCOMMIT (clean clone from the bundle in $SROOT/cand). TMPDIR=$PYTEST_TMP (outside the Harness, checked below). Dialog: none. No login. ~5-15 min."
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 || { print -r -- "STOP: $BUNDLE does not verify"; return 1; }
  run_root suite || return 1
  suite_tree $SROOT/cand $GCOMMIT || return 1
  local extra=(${(Q)${(z)${ADOPT608_PYTEST_ARGS:-}}}) log=$SROOT/suite-$(date +%Y%m%dT%H%M%S).txt
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args: $extra (a filtered run is not the full suite)"
  print -r -- "pytest: cd $SROOT/cand/src && TMPDIR=$RUNTMP $SROOT/cand/venv/bin/python -m pytest -q -p no:cacheprovider -rfE $extra"
  { print -r -- "candidate $GCOMMIT | TMPDIR $RUNTMP | extra: $extra"
    (cd $SROOT/cand/src && TMPDIR=$RUNTMP $SROOT/cand/venv/bin/python -m pytest -q -p no:cacheprovider -rfE $extra 2>&1)
    print -r -- "exit=$?"; } > $log
  print -r -- $log > $SROOT/suite-latest; cp $log $OUT/ 2>/dev/null
  tail -25 $log; print -r -- "(full output: $log)"
  local prc=${$(tail -1 $log)#exit=}
  (( prc == 0 )) && ! grep -qE '[0-9] passed' $log && { print -r -- "FAIL: pytest exited 0 but no test passed"; prc=1; }
  (( prc == 0 )) && print -r -- "SUCCESS: graftling suite passed on $GCOMMIT$( (( $#extra )) && print ' (FILTERED rehearsal run)')" \
    || print -r -- "FAIL: pytest exit $prc; classify with: zsh $THIS SR"
  print -r -- "next (paste): zsh $THIS SR"
  return $prc
  ;;
SR)
  say "[SR] read only: the newest suite log. Dialog: none."
  local g=$(cat $SROOT/suite-latest 2>/dev/null)
  [[ -n $g && -f $g ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  print -r -- "log: $g"; head -1 $g; tail -3 $g
  local -a summary=(${(M)${(f)"$(<$g)"}:#*[0-9] (passed|failed|skipped|error)*})
  [[ $summary == *[0-9]\ passed* ]] || { print -r -- "SR verdict: FAIL (no test passed: '${summary[-1]:-no summary}')"; return 1; }
  local -a ids=(${(f)"$(grep -E '^(FAILED|ERROR) ' $g | sed -E 's/^(FAILED|ERROR) //; s/ - .*//' | sort -u)"})
  if (( $#ids )); then
    print -l -- "FAILED/ERROR: "${^ids}
    print -r -- "SR verdict: $#ids failing node id(s); compare with base (paste):"
    print -r -- "  zsh $THIS suite-base ${(j: :)${(@q)ids}}"
    return 1
  fi
  grep -q '^exit=0$' $g && { print -r -- "SR verdict: PASS (no FAILED/ERROR line, exit 0)$(head -1 $g | grep -q 'extra: .' && print ' — FILTERED rehearsal run')"; return 0; }
  print -r -- "SR verdict: FAIL (no FAILED line but pytest did not exit 0; see $g)"; return 1
  ;;
suite-base)
  local -a ids=("${(@)IDS}")
  unset $DKEY $OKEY; print -r -- "keys: $DKEY and $OKEY dropped for this step (the tests need neither); python3 now sees: $(python3 -I $JUDGE selfenv)"
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base <node id>...   (SR prints the command with its node ids)"; return 2; }
  say "[suite-base] the failing node ids on graftling dev $BASE (clean clone in $SROOT/base). Dialog: none. No login."
  run_root base || return 1
  suite_tree $SROOT/base $BASE || return 1
  local log=$SROOT/suite-base-$(date +%Y%m%dT%H%M%S).txt
  (cd $SROOT/base/src && TMPDIR=$RUNTMP $SROOT/base/venv/bin/python -m pytest -q -p no:cacheprovider -rA "${ids[@]}" > $log 2>&1); local rc=$?
  tail -4 $log; print -r -- "pytest exit=$rc (output: $log)"; cp $log $OUT/ 2>/dev/null
  local id new=0
  for id in $ids; do
    if grep -qE "^(FAILED|ERROR) ${(b)id}( |\$)" $log; then print -r -- "also fails on base (not new): $id"
    elif grep -qE "^PASSED ${(b)id}\$" $log; then print -r -- "candidate-only (NEW): $id"; new=1
    else print -r -- "NOT RUN on base (a new or renamed test; NEW unless explained): $id"; new=1; fi
  done
  return $new
  ;;
*) print -r -- "usage: zsh $THIS pre|install|list|probe|child-opencode|child-deepseek|post|suite|SR|suite-base <ids>"; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${ADOPT608_OUT:-} ]] || { print "STOP: $H is not the Harness root"; exit 1; }
# Correction 1: no provider credential other than the two approved ones reaches anything this script starts.
scrub() {  # unset credential-class exported names except $DKEY and $OKEY; print the names removed
  local k u p; local -a gone=()
  for k in ${(k)parameters[(R)*export*]}; do
    [[ $k == ($DKEY|$OKEY) ]] && continue
    u=${(U)k}; [[ $u == GIT_CONFIG_KEY_<-> ]] && continue
    for p in ${(s:_:)u}; do
      [[ $p == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && { gone+=$k; unset $k; break; }
    done
  done
  print -r -- "credential scrub: removed from this script's environment (names only): ${gone:-none}; kept if set: $DKEY $OKEY"
}
scrub
print -r -- "credential-class names a judge-run python3 sees: $(python3 -I $JUDGE selfenv)"
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
mkdir -p $OUT 2>/dev/null
run_step
