#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 613 Main-run steps: a Claude child of a connection with base_url never carries a host Claude login there.
# graftling only, no GraphTraj. Modelled on adopt-608/steps.zsh (credential scrub) and verify-574 (Claude host launch).
#
# !! THESE STEPS RUN THE USER'S OWN LOGGED-IN CLAUDE CODE. MAIN ASKS THE USER BEFORE RUNNING 00, A OR B. !!
# OWNER HOST: graftling's Claude Code host. The owner is the user's own `claude` on PATH, logged in with the user's
# Claude login (macOS keychain or ~/.claude/.credentials.json; no key variable is passed). It is started as
# `claude -p --setting-sources project,local --strict-mcp-config --mcp-config <proj>/.mcp.json
#  --plugin-dir <proj>/.claude/skills/agents-claude-host --allowedTools mcp__graftling__subagents` (verify-574's
# launch), in a project whose files `graftling.claude.host configuration --write` wrote. That Main's model itself
# calls the installed graftling's public tool mcp__graftling__subagents (create/models/wait/retire). Bare
# subagents-mcp cannot serve a call without an owner (609). The CHILD is a real Claude Code started by graftling,
# whose connection's base_url is a local recording endpoint (recorder.py, 127.0.0.1, random port). The child runs
# the user's Claude Code in the default home, so the user's keychain login MAY BE READABLE by it; it MUST NOT reach
# the recorder, and step B checks exactly that from the headers the recorder saw (names and equal-to-dummy flags
# only; no value is stored or printed).
# What Claude Code itself may write (not these scripts): ~/.claude.json bookkeeping; the child's Session transcript
# under ~/.claude/projects/-private-tmp-graftling-613-proj-b/ (graftling needs a child's Session file); the Main uses
# --no-session-persistence. These scripts never write ~/.claude, ~/.claude.json, the keychain or any dotfile.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   00  Preflight. zsh; versions (claude, git, python); ROOT must not exist (STOP with the exact rm); the bundle
#       verifies against the local graftling repository and holds GCOMMIT (else STOP with the exact fetch command);
#       the owner answers a ONE-LINE prompt in a scratch directory, reporting from its init its model and login
#       source (apiKeySource 'none' = the user's keychain/.credentials.json login, no key variable).
#       Login: the user's Claude login (owner only). Dialog: at most one, macOS keychain access for
#       'Claude Code-credentials' if macOS asks: the user chooses Allow. Network: Anthropic (owner). ~30 s.
#   I   Install. ROOT/venv: graftling GCOMMIT from the bundle as a WHEEL (no network: PyYAML and websockets are
#       copied from <Harness>/.venv-runtime). CHECK: installed version, commit and file location.
#       Login: none. Dialog: none. Network: none. ~30 s.
#   A   Refusal. Recorder started; ROOT/proj-a's config.yml: connection gw {runtime claude, base_url <recorder>,
#       models [claude-haiku-5-5]}, NO api_key_env. The owner Main calls models, then create. CHECK lines: models
#       and create refused invalid-config naming "base_url needs api_key_env"; no Agent record; recorder count 0.
#       Login: the user's Claude login (owner only). Dialog: none expected (same as 00). Network: Anthropic (owner).
#   B   Key only. Recorder started; ROOT/proj-b's config.yml: the same connection plus api_key_env
#       GATEWAY613_TEST_KEY, which this step sets to a FIXED NON-SECRET dummy (not a key of any service). The owner
#       Main calls create (one-line prompt, model claude-haiku-5-5, tools [Read]), wait, retire. CHECK lines: create
#       returned an Agent; retire succeeded; the recorder saw >= 1 request; every request carried only x-api-key, equal
#       to the dummy (no authorization/bearer, no other auth-like header). The recorder answers 'ready'.
#       Login: the user's Claude login (owner); the child holds only the dummy. Dialog: none expected.
#       Network: Anthropic (owner); the child talks only to 127.0.0.1. ~1-3 min.
# Credentials: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) and every ANTHROPIC_*,
# CLAUDE_CODE_USE_* and *_BASE_URL variable, printing the removed NAMES. Every started process then runs through
# allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG and the variables the step names (B: the dummy).
# No key or token value is printed or passed as an argument (the dummy is fixed and not secret).
# VERIFY613_ROOT / _GCOMMIT / _BUNDLE / _REHEARSAL / _CHILD / _OWNER_STUB / _NO_BIND / _HOME are for the Engineer's rehearsal only: with
# VERIFY613_REHEARSAL=1, A and B run the same calls through the installed graftling's bound subagents function
# (judge613.py rehearse) with a stub child and the real recorder (or, with _NO_BIND where no port may be bound,
# the stub child writes the recorder's record line itself), and 00 uses a stub owner; that is not acceptance.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)     # this Task Worktree
H=${WT:h:h:h:h}                                      # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY613_ROOT:-/private/tmp/graftling-613}
GREPO=$H/graftling                                   # the local graftling repository (read only): holds BASE
BASE=026267b5804d660caf1ea4f76610e9a73257c169        # graftling dev (608 + 609), this Task's base
BRANCH=agent/613-graftling-claude-gateway-login-leak
GCOMMIT=${VERIFY613_GCOMMIT:-60f61df27bffad896d786962480edfbfb51c20bb}  # the graftling candidate (parent BASE)
BUNDLE=${VERIFY613_BUNDLE:-$WT/scripts/verify-613/graftling-613.bundle}
RTSP=$H/.venv-runtime/lib/python3.13/site-packages
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
HERE=${0:A:h}
THIS=${0:A}
STEP=${1:-}
REHEARSAL=${VERIFY613_REHEARSAL:-}
DKEY=GATEWAY613_TEST_KEY
DVAL=graftling-613-dummy-not-a-secret                # fixed, non-secret
TOOL=mcp__graftling__subagents
PYTMP=${TMPDIR:-/tmp}
V=$ROOT/venv

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
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL ]]; then unset $k; removed+=$k; fi
  done
  print -r -- "scrubbed at start (names only): ${removed:-none}"
}
scrub
CLAUDE=${VERIFY613_OWNER_STUB:-$(command -v claude || true)}
APATH=${CLAUDE:h}:/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables plus NAME=value pairs before '--'.
allow() {
  local -a add=(); while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  /usr/bin/env -i HOME=${VERIFY613_HOME:-$HOME} USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=$PYTMP LANG=en_US.UTF-8 "${add[@]}" "$@"
}
carried() {  # the credential-class names a step's processes hold
  print -r -- "credentials carried by started processes: ${*:-none} (plus the user's own Claude login, read by Claude Code itself, for the owner)"
}
stop() { print -r -- "STOP: $*"; exit 1; }
need_venv() { [[ -x $V/bin/python && -f $V/installed ]] || stop "$V missing; run: zsh $THIS I"; }

# Start the recorder; sets RPID, RPORT, RECORDS.
recorder_start() {  # label
  RECORDS=$ROOT/recorder-$1.jsonl; local portfile=$ROOT/recorder-$1.port
  rm -f $RECORDS $portfile
  if [[ -n $REHEARSAL && -n ${VERIFY613_NO_BIND:-} ]]; then  # rehearsal only: this sandbox forbids binding a port
    RPID=; RPORT=9; : > $RECORDS; STEPVARS+=(VERIFY613_STUB_RECORDS=$RECORDS VERIFY613_STUB_DUMMY=$DKEY)
    print -r -- "REHEARSAL no-bind: no recorder listens; the stub child writes the record the recorder would write to $RECORDS"
    return
  fi
  allow $DKEY=$DVAL -- $CONDA -I $HERE/recorder.py serve $RECORDS $portfile $DKEY 900 > $ROOT/recorder-$1.log 2>&1 &
  RPID=$!
  local i; for i in {1..50}; do [[ -s $portfile ]] && break; sleep 0.1; done
  [[ -s $portfile ]] || stop "the recorder did not start (log: $ROOT/recorder-$1.log)"
  RPORT=$(<$portfile); print -r -- "recorder: pid $RPID, http://127.0.0.1:$RPORT, records $RECORDS (header names and equal-to-dummy flags only)"
}
recorder_stop() { [[ -n $RPID ]] || return 0; kill $RPID 2>/dev/null; wait $RPID 2>/dev/null; print -r -- "recorder stopped"; }

# Project P with the given connection lines; writes graftling's Claude Code host files.
project() {  # P connection-lines
  local P=$1; rm -rf $P; mkdir -p $P/.agents-control
  print -r -- "connections:
  gw:
    runtime: claude
$2" > $P/.agents-control/config.yml
  print -r -- "config.yml:"; sed 's/^/  /' $P/.agents-control/config.yml
  (cd $P && allow -- $V/bin/python -I -m graftling.claude.host configuration --project $P --claude $CLAUDE --write > /dev/null) \
    || stop "configuration --write failed in $P"
  print -r -- "host files: $(cd $P && print -l -- .mcp.json(N) .agents-control/claude-host.json(N) .claude/skills/agents-claude-host(N) | tr '\n' ' ')"
}
# The owner Main makes the calls; CALLS gets the calls' documents.
owner_calls() {  # P step prompt
  local P=$1 step=$2 out=$ROOT/main-$2.jsonl; CALLS=$ROOT/calls-$2.json
  shift 2
  if [[ -n $REHEARSAL ]]; then
    allow ${STEPVARS[@]} -- $V/bin/python -I $HERE/judge613.py rehearse $P/.agents-control $P ${VERIFY613_CHILD:?} $step $CALLS
    return
  fi
  say "owner Main in $P: claude -p --setting-sources project,local --strict-mcp-config --mcp-config $P/.mcp.json --plugin-dir $P/.claude/skills/agents-claude-host --allowedTools $TOOL --no-session-persistence --output-format stream-json --verbose"
  (cd $P && allow ${STEPVARS[@]} -- perl -e 'alarm shift; exec @ARGV' 600 $CLAUDE -p --setting-sources project,local \
     --strict-mcp-config --mcp-config $P/.mcp.json --plugin-dir $P/.claude/skills/agents-claude-host \
     --allowedTools $TOOL --no-session-persistence --output-format stream-json --verbose "$1" < /dev/null > $out 2> $out.err)
  print -r -- "Main exit=$? (stream: $out; stderr: $out.err)"
  $CONDA -I $HERE/judge613.py main $out $CALLS
}
prompt() {  # numbered calls
  print -r -- "Use the MCP tool $TOOL (not any built-in Task or Agent tool of yours). Its input is {\"action\":\"execute\",\"feature\":<name>,\"arguments\":{...}}. Make exactly these calls in order:
$1
Do not retry or change any argument. Then report: AGENT: the agent id or NONE; RESULT: one line with what the calls returned, and any error verbatim."
}

case $STEP in
00)
  say "[00] Preflight. Login: the user's Claude login (owner only). Dialog: at most the macOS keychain prompt for 'Claude Code-credentials' (choose Allow). Network: Anthropic."
  [[ -n $ZSH_VERSION ]] && print -r -- "PASS: run by zsh $ZSH_VERSION"
  [[ -e $ROOT ]] && stop "$ROOT exists; run: rm -rf $ROOT && zsh $THIS 00"
  [[ -x $CLAUDE ]] || stop "no claude on PATH (the user's Claude Code)"
  print -r -- "claude: $CLAUDE $(allow -- $CLAUDE --version 2>&1 | head -1)"
  print -r -- "git: $(git --version) | python: $($CONDA --version 2>&1)"
  [[ -d $RTSP/yaml && -d $RTSP/websockets ]] && print -r -- "PASS: PyYAML and websockets present in $RTSP" || stop "$RTSP lacks yaml or websockets"
  git -C $GREPO cat-file -e "$BASE^{commit}" 2>/dev/null || stop "graftling base $BASE missing; run: git -C $GREPO fetch origin dev && zsh $THIS 00"
  git -C $GREPO bundle verify $BUNDLE > /dev/null 2>&1 || stop "bundle does not verify against $GREPO: git -C $GREPO bundle verify $BUNDLE"
  [[ $(git bundle list-heads $BUNDLE) == *$GCOMMIT* ]] && print -r -- "PASS: bundle verifies; its head is GCOMMIT $GCOMMIT" \
    || stop "bundle head is not $GCOMMIT; fetch it with: git -C $GREPO fetch $BUNDLE ${BRANCH}:refs/remotes/bundle-613/candidate"
  carried
  local S=$(mktemp -d ${ROOT}-probe.XXXXXX)
  (cd $S && allow -- perl -e 'alarm shift; exec @ARGV' 120 $CLAUDE -p --setting-sources project,local --strict-mcp-config \
     --no-session-persistence --output-format stream-json --verbose 'Reply in one line: OK.' < /dev/null > $S/out.jsonl 2> $S/err.txt)
  print -r -- "owner one-line prompt exit=$?"
  $CONDA -I -c 'import json, sys
init = res = None
for raw in open(sys.argv[1], errors="replace"):
    try: e = json.loads(raw)
    except ValueError: continue
    if e.get("type") == "system" and e.get("subtype") == "init": init = e
    if e.get("type") == "result": res = e
print("owner model:", init and init.get("model"), "| login (apiKeySource):", init and init.get("apiKeySource"),
      "| answer:", res and str(res.get("result"))[:120])
ok = bool(init and res and not res.get("is_error") and init.get("apiKeySource") == "none")
print("CHECK 613 00: the owner answered with the user\x27s own login and no key variable:", "PASS" if ok else "FAIL")' $S/out.jsonl
  rm -rf $S
  print -r -- "next: zsh $THIS I"
  ;;
I)
  say "[I] Install GCOMMIT $GCOMMIT as a wheel into $V. Login: none. Dialog: none. Network: none."
  [[ -e $V ]] && stop "$V exists; run: rm -rf $ROOT && zsh $THIS 00"
  mkdir -p $ROOT; carried
  local S=$ROOT/src
  git clone -q --bare --template= $GREPO $S/repo.git && git --git-dir=$S/repo.git fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" \
    || stop "fetch from the bundle failed"
  mkdir -p $S/graftling $S/wheels && git --git-dir=$S/repo.git archive $GCOMMIT | tar -x -C $S/graftling || stop "graftling $GCOMMIT not in the bundle"
  $CONDA -m venv $V || stop "venv failed"
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ || stop "copying dependencies failed"
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  allow -- $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null && allow -- $V/bin/python -m pip install $pip $S/wheels/graftling-*.whl \
    || stop "building or installing the wheel failed"
  local got=$(cd / && $V/bin/python -I -c 'import graftling; print(graftling.__version__, graftling.__file__)')
  print -r -- "$GCOMMIT $got" > $V/installed
  [[ $got == *$V/* ]] && print -r -- "CHECK 613 I: graftling $got from GCOMMIT $GCOMMIT: PASS" || print -r -- "CHECK 613 I: graftling imports from $got: FAIL"
  print -r -- "next: zsh $THIS A"
  ;;
A)
  say "[A] base_url without api_key_env is refused. Login: the user's Claude login (owner only). Dialog: none expected. Network: Anthropic (owner)."
  need_venv; typeset -ga STEPVARS=(); carried
  recorder_start A
  local P=$ROOT/proj-a
  project $P "    base_url: http://127.0.0.1:$RPORT
    models: [claude-haiku-5-5]"
  owner_calls $P A "$(prompt '1) {"action":"execute","feature":"models","arguments":{"runtime":"claude"}}
2) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"claude-haiku-5-5","tools":["Read"],"instruction":"Answer with exactly one word: ready."}}')"
  sleep 1; recorder_stop
  $CONDA -I $HERE/judge613.py check $CALLS A $P/.agents-control
  $CONDA -I $HERE/recorder.py check $RECORDS none
  print -r -- "host.log refusal line: $(grep -m1 -o 'base_url needs api_key_env[^"]*' $P/.agents-control/host.log 2>/dev/null || print none)"
  print -r -- "follow-ups: cat $CALLS; cat $RECORDS; next: zsh $THIS B"
  ;;
B)
  say "[B] base_url with api_key_env: only the dummy reaches the recorder. Login: the user's Claude login (owner); the child holds only $DKEY (dummy). Dialog: none expected. Network: Anthropic (owner), 127.0.0.1 (child)."
  need_venv; typeset -ga STEPVARS=($DKEY=$DVAL); carried "$DKEY (fixed non-secret dummy)"
  recorder_start B
  local P=$ROOT/proj-b
  project $P "    base_url: http://127.0.0.1:$RPORT
    api_key_env: $DKEY
    models: [claude-haiku-5-5]"
  owner_calls $P B "$(prompt '1) {"action":"execute","feature":"create","arguments":{"runtime":"claude","model":"claude-haiku-5-5","tools":["Read"],"instruction":"Answer with exactly one word: ready."}}
2) only if create returned an agent id: {"action":"execute","feature":"wait","arguments":{"agent":"<that agent id>","timeout_seconds":180}}
3) only if create returned an agent id: {"action":"execute","feature":"retire","arguments":{"agent":"<that agent id>"}}')"
  sleep 1; recorder_stop
  $CONDA -I $HERE/judge613.py check $CALLS B $P/.agents-control
  $CONDA -I $HERE/recorder.py check $RECORDS dummy
  print -r -- "follow-ups: cat $CALLS; cat $RECORDS; rm -rf $ROOT  (when done)"
  ;;
*)
  print -r -- "usage: zsh $THIS 00|I|A|B"; exit 2 ;;
esac
