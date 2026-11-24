#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 611 Main-run steps: GraphTraj chooses a DSH provider from the user catalog. A catalog DSH provider without
# base_url (opencode-go) reaches DSH as is, keyed only by its api_key_env; discovery lists it by provider; a Task member
# dispatched through the public swarm entry runs on it; deepseek-official still works. Candidate = this Worktree's
# HEAD (GraphTraj dev 06353b38 + 611); graftling dev 026267b (608 + 609) from <Harness>/graftling, as a WHEEL.
# Modelled on scripts/verify-603/steps.zsh (suite, SR, suite-base) and scripts/adopt-608/steps.zsh (credential scrub,
# isolated DSH homes, ps -E sampling, judge). Production (<Harness>/.venv-runtime) is only read (deps copied).
# PROVIDER (user decisions, Worldline 20261124T210658.357614+0900 and 20261124T212525.892346+0900): OpenCode Go via
# DSH, key variable OPENCODE_API_KEY, model glm-5.3 (608's real host ran it); deepseek-official keyed by
# DEEPSEEK_API_KEY, model deepseek-flash.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre        Main. ROOT must not exist (STOP with the exact rm); creates it. zsh, candidate HEAD, base 06353b38 and
#              graftling 026267b resolvable; TMPDIR outside the Harness; dsh/node versions; both keys set (names and
#              lengths only); your locations listed into ROOT/user-before.txt (names, sizes, mtimes; no content).
#              Then a ONE-LINE DSH prompt on opencode-go/glm-5.3 (fresh DSH home, OPENCODE_API_KEY its only
#              credential) and one on deepseek-official/deepseek-flash (fresh DSH home, DEEPSEEK_API_KEY only).
#              Dialog: none. Network: opencode.ai, api.deepseek.com. Keys: both. ~1-2 min.
#              Observable: "PASS: DSH answered on opencode-go/glm-5.3 ..." and "PASS: DSH answered on deepseek-official".
#   install    Main. ROOT/venv: this HEAD as a WHEEL (git archive) and graftling 026267b as a WHEEL, offline; click,
#              PyYAML, websockets copied from <Harness>/.venv-runtime. Dialog: none. No network, no key. ~1 min.
#              Observable: "PASS: venv imports graphtraj <HEAD> (wheel) and graftling 0.9.1 (026267b wheel)".
#   setup      Main. ROOT/proj (own git) through the public `graphtraj setup`; the isolated user catalog
#              ROOT/home/.graphtraj/connections.yml (HOME=ROOT/home is how GraphTraj locates it): previewed through the
#              public `graphtraj connections --action preview`, then written (a public save needs the owning host's
#              native review, which a shell has no route to), then read back through `--action read`; roles
#              probe_team.opencode (connection dsh-611/opencode-go/glm) and probe_team.deepseek
#              (dsh-611/deepseek-official/flash); probe Tasks 1 and 2 registered and ready through `graphtraj task`.
#              Dialog: none. No network, no key. <1 min. Observable: every line PASS ("roles: OK", both Tasks ready).
#   list       Main. Public `graphtraj connections --action discover --runtime dsh-611 --provider opencode-go`
#              (OPENCODE_API_KEY only), the same for deepseek-official (DEEPSEEK_API_KEY only), and an undeclared provider
#              (refused by graftling). Dialog: none. Network: none expected (DSH reads its installed catalog). ~1 min.
#              Observable: "listing: ALL PASS" twice (grouped under the one provider, glm-5.3 / deepseek-flash listed,
#              no key value in the output) and "PASS: an undeclared DSH provider is refused".
#   child-opencode  Main. ONE `agent-runner --swarm-input` call in ROOT/proj dispatches Task 1's probe_team.opencode
#              member (a real DSH member on opencode-go/glm-5.3). The runner holds BOTH keys; a sampler reads the member
#              DSH process's environment NAMES (ps -E on the recorded runtime_pid). Judge: launch request on
#              opencode-go/glm-5.3 keyed by OPENCODE_API_KEY, execution completed, native DSH trace names
#              (opencode-go, glm-5.3) and no other provider, reply READY-611-OPENCODE, only credential OPENCODE_API_KEY.
#              Dialog: none expected (no tool call; if a native permission request appears, DENY it and report it).
#              Network: opencode.ai. Keys: both. ~1-3 min. Observable: "judge: ALL PASS" then "SUCCESS: ...".
#   child-deepseek  Main. The same for Task 2's probe_team.deepseek (deepseek-official/deepseek-flash); only
#              credential DEEPSEEK_API_KEY although the runner holds both. Network: api.deepseek.com. ~1-3 min.
#   post       Main. Your ~/.pi/agent, ~/.dsh, ~/.codex, ~/.graphtraj vs pre (names, sizes, mtimes; any difference
#              FAILs). <5 s. Observable: "PASS: your locations are unchanged".
#   suite      Main. GraphTraj full suite of HEAD (scripts/run_test_shards.py, 6 shards, --timeout 1500, -rA, background,
#              ~25 min) in a venv under $T with graftling 026267b as a WHEEL and GraphTraj editable. Both keys dropped
#              first. pytest's temp root is a fresh directory under TMPDIR=${TMPDIR:-/tmp}, outside the Harness
#              (checked, printed). Dialog: none. No key, no login.
#   SR         Read only: the newest suite's FAILED/ERROR node ids (scripts/verify-581/suiteids.py) classed
#              'known (516)' (Task 516's CURRENT definition via its task.yml current_definition) or NEW; prints the
#              ready-to-paste suite-base command. Dialog: none.
#   suite-base Main, only if SR reports NEW: reruns exactly those ids on base GraphTraj 06353b38 (a local clone under
#              $T), then on the candidate, both with the graftling 026267b wheel. Both keys dropped. Dialog: none.
# Credentials: at start, before any step, every exported credential-class variable (graftling's is_credential_name,
# restated in x611.py; GIT_CONFIG_KEY_<n> excepted) other than OPENCODE_API_KEY and DEEPSEEK_API_KEY is unset; the
# removed NAMES are printed. On top, every command a step starts runs through allow(): only PATH, HOME=ROOT/home,
# TMPDIR, LANG, the step's own variables (names shown) and the credentials that step names. Keys are never printed
# and never arguments. suite, SR and suite-base drop both keys. No step reads or writes ~/.dsh, ~/.pi, ~/.codex,
# ~/.claude or ~/.graphtraj/connections.yml (post lists names, sizes and mtimes only). Writes: ROOT, $T, OUT, and
# pytest temp roots under TMPDIR. Nothing is pushed.
# Rehearsal only (Engineer): VERIFY611_ROOT, VERIFY611_T, VERIFY611_OUT, VERIFY611_USERHOME, VERIFY611_PYTEST_ARGS,
# VERIFY611_NO_PS=1, VERIFY611_NO_PROMPT=1 (pre skips the two DSH prompts), VERIFY611_DRY=1 (child steps stop before
# the dispatch). A run with any of them set is a rehearsal, not acceptance evidence.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
STEP=${1:-}
TASKDIR=611-graphtraj-provider-selection-adaptation
GREPO=$H/graftling                                  # the local graftling repository (read only)
GCOMMIT=026267b5804d660caf1ea4f76610e9a73257c169   # graftling dev: 608 + 609 (version 0.9.1)
GVERSION=0.9.1
GTBASE=06353b380677843f656796798a7023f91457ad70     # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)                   # the candidate
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: click, PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
ROOT=${VERIFY611_ROOT:-/private/tmp/graphtraj-611}  # the isolated project, homes and venv (outside the Harness)
T=${VERIFY611_T:-$H/tmp/611}                        # suite venvs, sources and outputs
OUT=${VERIFY611_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost}
UH=${VERIFY611_USERHOME:-$HOME}                     # your home: its .pi/agent, .dsh, .codex, .graphtraj are only listed
HOMEDIR=$ROOT/home                                  # HOME of every started command: its .graphtraj holds the catalog
DSHHOME=$ROOT/dsh-home                              # the catalog entry's DSH home (both providers)
P=$ROOT/proj                                        # the isolated GraphTraj project
VENV=$ROOT/venv
X611=$SD/x611.py
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
OKEY=OPENCODE_API_KEY
DKEY=DEEPSEEK_API_KEY
OMODEL=glm-5.3
DMODEL=deepseek-flash
PYTEST_TMP=${TMPDIR:-/tmp}
BASEPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
export PATH=$BASEPATH:$PATH

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
key_ready() {  # variable names
  local k; for k in "$@"; do
    [[ -n ${(P)k:-} ]] && continue
    print -r -- "STOP: $k is not set (Main asks the user first). Fix: export $k=<the key>; zsh $THIS $STEP"; return 1
  done
}
# Run a command with ONLY PATH, HOME=ROOT/home, TMPDIR, LANG, the named credentials and the step's variables.
# Usage: allow <credentials, comma-separated, or -> [NAME=value...] -- command...
allow() {
  local creds=$1; shift; local -a add=() keep=(${(s:,:)creds:#-})
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k
    for k in ${(k)parameters[(R)*export*]}; do (( ${keep[(Ie)$k]} )) || unset $k 2>/dev/null; done
    export PATH=$VENV/bin:$BASEPATH HOME=$HOMEDIR TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8
    (( $#add )) && export "${add[@]}"
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,TMPDIR,LANG${keep:+,${(j:,:)keep}}${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# Your locations: names, sizes and mtimes only, never contents.
user_state() {
  local d; for d in $UH/.pi/agent $UH/.dsh $UH/.dsh/profiles $UH/.codex $UH/.graphtraj; do
    ls -laT $d 2>&1 | awk -v d=${d#$UH/} 'NF >= 10 && $10 != ".." {print d, $5, $6, $7, $8, $9, $10}'
  done
}
outside() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
others() {
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1); then
    [[ ${VERIFY611_NO_PS:-} == 1 ]] && { print -u2 -r -- "NOTE: ps cannot list processes here; check skipped (rehearsal)"; return 0; }
    print -r -- "ps cannot list processes here; run this script in your own terminal"; return 0
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -v grep || true
}
copy_deps() {  # venv: click, PyYAML, websockets from production (read only) when the venv lacks them
  local V=$1 D m
  D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
graftling_wheel() {  # source dir: graftling GCOMMIT built offline from a git archive into $1/wheels
  local S=$1
  rm -rf -- $S/graftling && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null
}
suite_venv() {  # venv graphtraj-checkout: graftling GCOMMIT as a WHEEL, GraphTraj editable
  local V=$1 gt=$2 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf -- $V $S && mkdir -p $S || return 1
  graftling_wheel $S || return 1
  $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  $V/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && $V/bin/python -m pip install $PIP -e $gt || return 1
  print -r -- "graftling $GCOMMIT (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
run_root() {  # label: a fresh pytest temp root under TMPDIR, outside the Harness, no Harness marker above; sets RUNTMP
  outside || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-611-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
}
versions() {
  (cd $RUNTMP && $1/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))')
}
# One-line DSH prompt: patch file, fresh DSH home, credential, label.
dsh_prompt() {
  local patch=$1 home=$2 cred=$3 label=$4 log=$ROOT/dsh-prompt-$4.txt rc
  say "one-line DSH prompt ($label): dsh --profile headless --patch $patch (DSH_HOME=$home; credential $cred only)"
  print -r -- "login: $cred from the allowlisted environment (set, ${#${(P)cred}} characters, not printed); $home/.credentials.yaml $([[ -e $home/.credentials.yaml ]] && print PRESENT || print absent)"
  (cd $ROOT && allow $cred DSH_HOME=$home -- perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless --patch $patch \
     "Reply in one line with the exact model id you are running as, nothing else." < /dev/null) > $log 2>&1; rc=$?
  tail -4 $log; print -r -- "exit=$rc (full output: $log)"
  return $rc
}
# The isolated project's GraphTraj commands, in ROOT/proj, with the named credentials.
inproj() { local creds=$1; shift; (cd $P && allow $creds -- "$@"); }
venv_ready() {
  [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]] || { print -r -- "STOP: $VENV is not this HEAD $HEAD; run: zsh $THIS install"; return 1; }
}
# Samples the environment NAMES of the member DSH process of Task $1 while its execution runs.
sampler() {  # task, env dir, seconds
  local task=$1 dir=$2 until=$(( SECONDS + $3 )) pid S=$P/.graphtraj/runner/sessions
  mkdir -p $dir; : > $dir/sampler.log
  while (( SECONDS < until )); do
    for pid in ${(f)"$($VENV/bin/python -I $X611 pids $S $task 2>>$dir/sampler.log)"}; do
      [[ -n $pid && ! -e $dir/env-$pid.txt ]] || continue
      kill -0 $pid 2>/dev/null || { print -r -- "pid $pid already gone" >> $dir/sampler.log; continue; }
      if [[ ${VERIFY611_NO_PS:-} == 1 ]]; then print -r -- "pid $pid: ps -E skipped (rehearsal)" >> $dir/sampler.log; continue; fi
      ps -E -ww -o command= -p $pid 2>>$dir/sampler.log | python3 -I $X611 envnames $dir/env-$pid.txt >> $dir/sampler.log 2>&1
      [[ -s $dir/env-$pid.txt ]] || { rm -f $dir/env-$pid.txt; print -r -- "pid $pid: ps -E gave nothing" >> $dir/sampler.log; }
    done
    [[ -n $($VENV/bin/python -I $X611 ended $P/.graphtraj/runner/sessions $task 0 2>/dev/null | grep 'execution ended') ]] && break
    sleep 0.2
  done
}
# One member of Task $1 through ONE swarm call; judged on provider $2, model $3, only credential $4, reply $5.
member_case() {
  local task=$1 prov=$2 mdl=$3 want=$4 word=$5 ED=$ROOT/env-task-$1 S=$P/.graphtraj/runner/sessions
  local batch=$P/.graphtraj/probe-611/batch-$task.yml
  venv_ready && need $P/.graphtraj/probe-611/evidence.md setup && key_ready $DKEY $OKEY || return 1
  [[ -z $(print -l $S/$task-*(N/)) ]] || { print -r -- "STOP: Task $task already has a member Session ($(print $S/$task-*(N/))); start over: rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  inproj - $VENV/bin/python -I $X611 batch $task > $batch || return 1
  print -r -- "batch: $batch"; cat $batch
  print -r -- "runner environment (names; values not printed): $(allow $DKEY,$OKEY -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  [[ ${VERIFY611_DRY:-} == 1 ]] && { print -r -- "DRY (rehearsal): stopped before agent-runner --swarm-input"; return 0; }
  rm -rf $ED; mkdir -p $ED
  # The sampler starts first, so a short turn's DSH process is not missed; it ends with the execution.
  sampler $task $ED 360 &
  local spid=$!
  print -r -- "dispatch at $(date +%T)"
  inproj $DKEY,$OKEY $VENV/bin/agent-runner --swarm-input $batch > $ROOT/launch-task-$task.yml 2>&1; local rc=$?
  print -r -- "agent-runner --swarm-input exit=$rc (output: $ROOT/launch-task-$task.yml)"
  grep -E "alias:|launch_status:|code:|message:" $ROOT/launch-task-$task.yml | head -8
  (( rc == 0 )) || { kill $spid 2>/dev/null; print -r -- "STOP: the swarm call failed (output above)"; return 1; }
  wait $spid
  $VENV/bin/python -I $X611 ended $S $task 60 || { print -r -- "STOP: the member's execution has not ended (above); report it"; return 1; }
  print -r -- "sampler log: $(tr '\n' ' ' < $ED/sampler.log)"
  say "verdict (computed from the retained records)"
  $VENV/bin/python -I $X611 judge $S $task $prov $mdl $ED $want $word; local jrc=$?
  print -r -- "follow-up (paste): $VENV/bin/python -I $X611 judge $S $task $prov $mdl $ED $want $word"
  cp $ROOT/launch-task-$task.yml $OUT/ 2>/dev/null; cp -R $ED $OUT/ 2>/dev/null
  cp -R $S/$task-*(N/) $OUT/ 2>/dev/null
  return $jrc
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT; two one-line DSH prompts. Dialog: none. Keys: $OKEY, $DKEY. ~1-2 min."
  OK=1
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists (an earlier run). Look at it, then run exactly:"
                      print -r -- "  rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  key_ready $OKEY $DKEY || return 1
  mkdir -p $ROOT $HOMEDIR $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT cat-file -e "$GTBASE^{commit}" 2>/dev/null && pass "base GraphTraj $GTBASE resolvable" || fail "base GraphTraj $GTBASE not in $WT"
  git -C $GREPO cat-file -e "$GCOMMIT^{commit}" 2>/dev/null && pass "graftling $GCOMMIT resolvable in $GREPO ($(git -C $GREPO log --format=%s -1 $GCOMMIT | cut -c1-70))" || fail "graftling $GCOMMIT not in $GREPO"
  local dirty=$(git -C $WT status --porcelain -- src tests scripts pyproject.toml)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, scripts" || fail "uncommitted changes in $WT: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m; for m in click yaml websockets; do [[ -d $RTSP/$m ]] && pass "$m present in $RTSP" || fail "$m missing in $RTSP"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  local t; for t in node dsh; do print -r -- "$t: $(command -v $t) $(cd $ROOT && allow - -- $t --version < /dev/null 2>&1 | head -1)"; done
  print -r -- "$OKEY: set (${#OPENCODE_API_KEY} characters; not printed). $DKEY: set (${#DEEPSEEK_API_KEY} characters; not printed)."
  print -r -- "allowlisted environment of a child step's runner (names only): $(allow $DKEY,$OKEY EXAMPLE_STEP_VAR=1 -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/ 2>/dev/null
  print -r -- "your locations before (names, sizes, mtimes): $(wc -l < $ROOT/user-before.txt | xargs) lines in $ROOT/user-before.txt"
  if [[ ${VERIFY611_NO_PROMPT:-} == 1 ]]; then
    print -r -- "REHEARSAL: DSH prompts skipped (VERIFY611_NO_PROMPT=1)"
  else
    mkdir -p $ROOT/dsh-pre-opencode $ROOT/dsh-pre-deepseek
    print -r -- "- id: llm-pi-ai
  config:
    providers:
      opencode-go:
        apiKeyEnv: $OKEY
- id: agent-default-model
  config:
    provider: opencode-go
    model: $OMODEL" > $ROOT/dsh-pre-opencode.patch.yml
    dsh_prompt $ROOT/dsh-pre-opencode.patch.yml $ROOT/dsh-pre-opencode $OKEY opencode \
      && pass "DSH answered on opencode-go/$OMODEL with $OKEY as its only credential (fresh DSH home)" \
      || fail "DSH did not answer on opencode-go/$OMODEL (above)"
    print -r -- "- id: llm-deepseek
  config:
    apiKeyEnv: $DKEY
    models:
      - id: $DMODEL
- id: agent-default-model
  config:
    provider: deepseek-official
    model: $DMODEL" > $ROOT/dsh-pre-deepseek.patch.yml
    dsh_prompt $ROOT/dsh-pre-deepseek.patch.yml $ROOT/dsh-pre-deepseek $DKEY deepseek \
      && pass "DSH answered on deepseek-official/$DMODEL with $DKEY as its only credential (fresh DSH home)" \
      || fail "DSH did not answer on deepseek-official/$DMODEL (above)"
    cp $ROOT/dsh-prompt-*.txt $OUT/ 2>/dev/null
  fi
  print -r -- "writes: $ROOT and copies in $OUT only. dialog: none."
  (( OK )) && print -r -- "next (paste): zsh $THIS install" || print -r -- "STOP: FAIL lines above; report them (then: rm -rf ${(qq)ROOT} && zsh $THIS pre)"
  (( OK ))
  ;;
install)
  say "[install] Main. $VENV: GraphTraj $HEAD (wheel) + graftling $GCOMMIT (wheel), offline. Dialog: none. No key."
  OK=1
  need $ROOT/user-before.txt pre || return 1
  local S=$ROOT/venv-src
  if [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]]; then print -r -- "reusing $VENV (graphtraj $HEAD)"
  else
    rm -rf -- $VENV $S && mkdir -p $S/graphtraj || return 1
    git -C $WT archive $HEAD | tar -x -C $S/graphtraj || return 1
    graftling_wheel $S || return 1
    $CONDA -m pip wheel $PIP -w $S/wheels $S/graphtraj > /dev/null || { print -r -- "STOP: GraphTraj wheel build failed"; return 1; }
    $CONDA -m venv $VENV && copy_deps $VENV || return 1
    $VENV/bin/python -m pip install $PIP $S/wheels/graftling-*.whl $S/wheels/graphtraj-*.whl || return 1
    print -r -- $HEAD > $VENV/installed
  fi
  (cd $ROOT && allow - -- $VENV/bin/python -I -c 'import sys, graphtraj, graftling, importlib.metadata as m
from pathlib import Path
url = m.distribution("graphtraj").read_text("direct_url.json") or ""
site = Path(sys.argv[1]).resolve()
ok = Path(graphtraj.__file__).resolve().is_relative_to(site) and "editable" not in url
print("graphtraj", graphtraj.__file__, "| wheel:", ok, "| graftling", graftling.__version__, graftling.__file__)
sys.exit(0 if ok and graftling.__version__ == sys.argv[2] and Path(graftling.__file__).resolve().is_relative_to(site) else 1)' $VENV $GVERSION) \
    && pass "venv imports graphtraj $HEAD (wheel) and graftling $GVERSION ($GCOMMIT wheel)" || fail "venv does not import both wheels"
  grep -q "'provider': provider," $VENV/lib/python3.13/site-packages/graphtraj/runtimes/dsh/adapter.py \
    && pass "installed DSH adapter passes the catalog provider (611)" || fail "installed adapter lacks the 611 change"
  grep -q 'def pi_ai_route' $VENV/lib/python3.13/site-packages/graftling/dsh/settings.py \
    && pass "installed graftling has the 608 DSH provider route" || fail "installed graftling lacks 608"
  for m in graphtraj agent-runner graphtraj-session; do [[ -x $VENV/bin/$m ]] && pass "$VENV/bin/$m" || fail "$VENV/bin/$m missing"; done
  print -r -- "writes: $VENV and $S only. dialog: none."
  (( OK )) && print -r -- "next (paste): zsh $THIS setup" || print -r -- "STOP: fix the FAIL lines above, then: zsh $THIS install"
  (( OK ))
  ;;
setup)
  say "[setup] Main. Project $P, isolated catalog $HOMEDIR/.graphtraj/connections.yml, roles, probe Tasks. Dialog: none. No key."
  OK=1
  venv_ready || return 1
  [[ -e $P ]] && { print -r -- "STOP: $P exists (an earlier setup). Start over: rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  mkdir -p $P $DSHHOME $HOMEDIR/.graphtraj || return 1
  (cd $P && git init -q -b main && print -r -- "# 611 probe: DSH provider selection" > README.md && git add README.md \
     && git -c user.name=611 -c user.email=611@invalid commit -qm "Initial source") || return 1
  print y | inproj - $VENV/bin/graphtraj setup 2>&1 | tail -3
  inproj - $VENV/bin/python -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); root = Path.cwd().resolve()
print("runner directory:", found, "| inside the project:", found.is_relative_to(root)); sys.exit(0 if found.is_relative_to(root) else 1)' \
    && pass "graphtraj setup created the project's own .graphtraj" || fail "GraphTraj does not resolve the project's own .graphtraj"
  local draft=$ROOT/catalog-draft.yml
  inproj - $VENV/bin/python -I $X611 catalog $draft $DSHHOME || return 1
  inproj - $VENV/bin/graphtraj connections --action preview --catalog-file $draft > $ROOT/catalog-preview.yml 2>&1 \
    && pass "public preview accepts the catalog (a DSH provider without base_url; $ROOT/catalog-preview.yml)" \
    || { fail "public preview refused the catalog: $(tail -3 $ROOT/catalog-preview.yml)"; return 1; }
  cp $draft $HOMEDIR/.graphtraj/connections.yml || return 1
  inproj - $VENV/bin/graphtraj connections --action read > $ROOT/catalog-read.yml 2>&1 \
    && grep -q "path: $HOMEDIR/.graphtraj/connections.yml" $ROOT/catalog-read.yml \
    && pass "public read uses the isolated catalog $HOMEDIR/.graphtraj/connections.yml ($(grep -m1 'revision:' $ROOT/catalog-read.yml))" \
    || fail "public read does not show the isolated catalog ($ROOT/catalog-read.yml)"
  inproj - $VENV/bin/python -I $X611 prepare $P || OK=0
  inproj - $VENV/bin/graphtraj roles organize > $ROOT/roles-preview.yml 2>&1 \
    && pass "public role preview lists: $(grep -oE 'probe_team\.(opencode|deepseek)' $ROOT/roles-preview.yml | sort -u | xargs)" \
    || fail "public role preview failed ($ROOT/roles-preview.yml)"
  cp $ROOT/catalog-read.yml $ROOT/roles-preview.yml $OUT/ 2>/dev/null
  print -r -- "writes: $ROOT only (project, isolated HOME and DSH home). dialog: none."
  (( OK )) && print -r -- "next (paste): zsh $THIS list" || print -r -- "STOP: FAIL lines above; report them"
  (( OK ))
  ;;
list)
  say "[list] Main. Public discover by provider: opencode-go ($OKEY only), deepseek-official ($DKEY only), an undeclared one. Dialog: none."
  venv_ready && need $HOMEDIR/.graphtraj/connections.yml setup && key_ready $OKEY $DKEY || return 1
  OK=1
  local prov key mdl
  for prov key mdl in opencode-go $OKEY $OMODEL deepseek-official $DKEY $DMODEL; do
    say "graphtraj connections --action discover --runtime dsh-611 --provider $prov (credential $key only)"
    inproj $key $VENV/bin/graphtraj connections --action discover --runtime dsh-611 --provider $prov > $ROOT/list-$prov.yml 2>&1 \
      || fail "discover $prov exited nonzero: $(tail -3 $ROOT/list-$prov.yml)"
    (cd $ROOT && allow $key -- $VENV/bin/python -I $X611 listing $ROOT/list-$prov.yml $prov $mdl $key) || OK=0
  done
  inproj $OKEY $VENV/bin/graphtraj connections --action discover --runtime dsh-611 --provider no-such-611 > $ROOT/list-refused.txt 2>&1 \
    && fail "an undeclared DSH provider was listed ($ROOT/list-refused.txt)" \
    || pass "an undeclared DSH provider is refused: $(tail -1 $ROOT/list-refused.txt | cut -c1-200)"
  cp $ROOT/list-*.yml $ROOT/list-refused.txt $OUT/ 2>/dev/null
  print -r -- "writes: $ROOT/list-* and copies in $OUT only. dialog: none."
  (( OK )) && print -r -- "next (paste): zsh $THIS child-opencode" || print -r -- "STOP: FAIL lines above; report them"
  (( OK ))
  ;;
child-opencode)
  say "[child-opencode] Main. ONE swarm call: Task 1's probe_team.opencode DSH member on opencode-go/$OMODEL. Dialog: none expected (deny any). Keys: both in the runner."
  member_case 1 opencode-go $OMODEL $OKEY READY-611-OPENCODE; local rc=$?
  [[ ${VERIFY611_DRY:-} == 1 ]] && return $rc
  (( rc == 0 )) && print -r -- "SUCCESS: a real DSH member ran on opencode-go/$OMODEL with $OKEY as its only credential" \
    || print -r -- "NOT ACCEPTED (FAIL/STOP lines above); report them. The next step still runs."
  print -r -- "next (paste): zsh $THIS child-deepseek"
  return $rc
  ;;
child-deepseek)
  say "[child-deepseek] Main. ONE swarm call: Task 2's probe_team.deepseek DSH member on deepseek-official/$DMODEL. Dialog: none expected (deny any). Keys: both in the runner."
  member_case 2 deepseek-official $DMODEL $DKEY READY-611-DEEPSEEK; local rc=$?
  [[ ${VERIFY611_DRY:-} == 1 ]] && return $rc
  (( rc == 0 )) && print -r -- "SUCCESS: the deepseek-official DSH member still completes, holding only $DKEY" \
    || print -r -- "NOT ACCEPTED (FAIL/STOP lines above); report them."
  print -r -- "next (paste): zsh $THIS post"
  return $rc
  ;;
post)
  say "[post] Main. Your ~/.pi/agent, ~/.dsh, ~/.codex, ~/.graphtraj vs pre (names, sizes, mtimes). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "your locations are unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT (copies in $OUT). To remove everything afterwards: rm -rf ${(qq)ROOT}"
  print -r -- "next (paste): zsh $THIS suite"
  (( OK ))
  ;;
suite)
  setopt local_options no_bg_nice
  unset $DKEY $OKEY; print -r -- "keys: $DKEY and $OKEY dropped for this step; python3 now sees: $(python3 -I $X611 selfenv)"
  say "[suite] Main. GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg 2>/dev/null || print unavailable)"
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $o; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $WT || return 1
  versions $V || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP (TMPDIR, outside the Harness) | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY611_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${(j: :)${(@qq)extra}}" >> $R/run.txt
  cat $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only. dialog: none."
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  unset $DKEY $OKEY
  say "[SR] read only: newest suite; FAILED/ERROR node ids classed against 516's current definition. Dialog: none."
  local cur=${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  local K=$D516/$cur
  print -r -- "516 current definition (task.yml current_definition): $K"
  [[ -n $cur && -f $K ]] || { print -r -- "STOP: cannot read 516's current definition '$K'"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet); next: zsh $THIS SR (later)"; return 1; }
  local -a logs=($g/shards/*.log(N.)); (( $#logs )) || logs=($g/suite.txt)
  local line t id new=0 any=0; local -a ids=()
  for id in ${(f)"$(python3 -I $SUITEIDS ids $logs)"}; do
    any=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $id"
    else print -r -- "NEW: $id"; new=1; ids+=$id; fi
  done
  print -l -- $ids > $g/new-ids.txt
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; new=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; new=1 ;;
    esac
  done
  grep -E '^(=+ )?[0-9]+ (passed|failed)|^[0-9]+ (passed|failed)' $g/shards/*(N.) | sed "s#^$g/shards/##"
  mkdir -p $OUT 2>/dev/null && cp $g/run.txt $g/new-ids.txt $OUT/ 2>/dev/null && cp $g/suite.txt $OUT/suite-${g:t}.txt 2>/dev/null
  print -r -- "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  print -r -- "NEW node ids ($#ids, one per line): $g/new-ids.txt"
  if (( $#ids )); then
    print -r -- "next (paste): zsh ${(qq)THIS} suite-base --from ${(qq)g}/new-ids.txt"
  else
    print -r -- "next: none (no NEW id); report the SR verdict"
  fi
  return $new
  ;;
suite-base)
  setopt local_options no_bg_nice
  unset $DKEY $OKEY; print -r -- "keys: $DKEY and $OKEY dropped for this step; python3 now sees: $(python3 -I $X611 selfenv)"
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then
    [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file '${IDS[2]:-}'; SR writes it (new-ids.txt)"; return 2; }
    ids=(${(f)"$(<${IDS[2]})"})
  else ids=("${(@)IDS}"); fi
  ids=(${ids:#})
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>...   (SR prints it)"; return 2; }
  say "[suite-base] Main. $#ids node ids: base (GraphTraj $GTBASE), then candidate (HEAD $HEAD), both with graftling $GCOMMIT (wheel). Dialog: none. No login."
  print -l -- "  id: "${^ids}
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun this command later"; print -r -- $o; return 1; }
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  local VB=$T/venv-base-${GTBASE[1,8]} VC=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $VB $B && suite_venv $VC $WT || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R || return 1
  print -l -- $ids > $R/ids.txt
  local side dir V rc
  for side dir V in base $B $VB candidate $WT $VC; do
    run_root $side || return 1
    say "$side: pytest in $dir; $(versions $V)"
    (cd $dir && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $R/$side-collected.txt 2>&1)
    python3 -I $SUITEIDS present $R/$side-collected.txt $R/ids.txt > $R/$side-ids.txt 2> $R/$side-missing.txt
    [[ -s $R/$side-missing.txt ]] && print -r -- "not on $side (not run there): $(tr '\n' ' ' < $R/$side-missing.txt)"
    local -a run=(${(f)"$(<$R/$side-ids.txt)"})
    if (( $#run )); then
      (cd $dir && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $R/$side.txt 2>&1); rc=$?
    else print -r -- "(no id present on $side)" > $R/$side.txt; rc=5; fi
    print -r -- "$side: pytest exit=$rc, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $R/$side.txt | tail -1) (output: $R/$side.txt)"
    python3 -I $SUITEIDS errors $R/$side.txt > $R/$side-errors.txt
  done
  say "classification (each id: base, then candidate)"
  python3 -I $SUITEIDS classify $R/ids.txt $R/base.txt $R/candidate.txt | tee $R/classification.txt; local fails=${pipestatus[1]}
  mkdir -p $OUT 2>/dev/null && cp -R $R $OUT/ 2>/dev/null
  print -r -- "writes: $T (venvs, $B, $R), a copy in $OUT/${R:t} and pytest temp roots under $PYTEST_TMP only. dialog: none."
  print -r -- "next: report the classification ($R/classification.txt); a candidate-only id is a regression of this Task"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|install|setup|list|child-opencode|child-deepseek|post|suite|SR|suite-base --from <file>|<ids>..."; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n ${VERIFY611_OUT:-} ]] || { print "STOP: $H is not the Harness root"; exit 1; }
# No provider credential other than the two approved ones reaches anything this script starts.
scrub() {  # unset credential-class exported names except $OKEY and $DKEY; print the names removed
  local k u part; local -a gone=()
  for k in ${(k)parameters[(R)*export*]}; do
    [[ $k == ($DKEY|$OKEY) ]] && continue
    u=${(U)k}; [[ $u == GIT_CONFIG_KEY_<-> ]] && continue
    for part in ${(s:_:)u}; do
      [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && { gone+=$k; unset $k; break; }
    done
  done
  print -r -- "credential scrub: removed from this script's environment (names only): ${gone:-none}; kept if set: $OKEY $DKEY"
}
scrub
print -r -- "credential-class names a python3 started here sees: $(python3 -I $X611 selfenv)"
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: node ids or --from <file>
mkdir -p $OUT 2>/dev/null
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
