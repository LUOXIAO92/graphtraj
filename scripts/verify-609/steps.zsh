#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 609 Main-run steps: graftling's models listing by provider and create's provider, on a real host, through
# graftling's INSTALLED public entry: the subagents MCP server `graftling` that graftling's Pi host gives a Pi Session
# (PUBLIC_API 1.6 Routing; the model calls mcp__graftling__subagents). One step at a time:  zsh <this file> <STEP>
#
# Why a Pi Main and not the bare `subagents-mcp` or claude -p: `subagents-mcp` serves only a bound child; without an
# owner every tools/call returns authority-denied "The owning Agent connection is unavailable." (graftling
# src/graftling/connection.py call_owner), so it has no standalone root caller. The Claude Code host needs a Claude
# login and a trust dialog, which are not approved. A `pi --mode json` Main with graftling's Pi extension needs only
# the one approved key, OPENCODE_API_KEY, and no dialog.
#
# The two connections: ONE Runtime (pi), two Pi built-in providers keyed by the same variable: `opencode` and
# `opencode-go`. Pi 1.4.0 maps both to OPENCODE_API_KEY (pi-ai dist/env-api-keys.js lines 106-107; docs/providers.md
# "OpenCode Zen and Go | OPENCODE_API_KEY"). Model ids are never hardcoded: L reads them from the listing at run time.
#
#   00  Main. Read only. Prints the graftling branch HEAD in <Harness>/graftling (STOP with the fetch command if
#       absent), pi/node/npm/git versions, the rg this step links (DSH's vendored ripgrep), that Pi's package maps
#       opencode and opencode-go to OPENCODE_API_KEY, OPENCODE_API_KEY SET/UNSET (name only), the names of other
#       credential-like variables in Main's shell (they never reach a started process), and that $T is absent.
#       Login: none. Key: none passed. Dialog: none. Observable: every CHECK PASS.
#   I   Main. Installs into $T only: graftling from the branch HEAD (git archive -> venv, pip from PyPI), the Pi
#       sandbox (scripts/real-host/install-pi-sandbox.sh at $T/pi-sandbox: agent-sandbox from GitHub, srt from npm;
#       rg linked from DSH's install), an empty isolated Pi home $T/pi-home, the data root $T/data with config.yml
#       (two Pi connections), the Pi host configuration $T/pi-host.json, the Pi Session cwd $T/work.
#       Login: none. Key: none passed. Dialog: none. Network: PyPI, github.com, registry.npmjs.org. No inference.
#       Observable: "CHECK 609 I ...: PASS" lines and "VERIFIED: $T/pi-sandbox".
#   L   Main. Key: OPENCODE_API_KEY (Main asks the USER first). Login: none. Dialog: none. ~2-5 min, small inference.
#       (a) installed graftling's discover_models for each connection (no inference; what `models` calls) prints
#           each connection's groups and picks the Pi Main's model and C's provider/model into $R/choice.env;
#       (b) one `pi --mode json` Main with graftling's Pi extension calls mcp__graftling__subagents: execute models
#           {runtime: pi}; create without provider; create with the undeclared provider "anthropic".
#       Observable: CHECK lines PASS: both connections listed as separate provider groups with model counts;
#       ambiguous-connection; invalid-provider; no Agent record; no key value in any record.
#   C   Main. Key: OPENCODE_API_KEY (same approval). Login: none. Dialog: none. ~3-8 min, small inference.
#       Args: [provider model] (default: $R/choice.env from L). One `pi --mode json` Main creates a Pi child with
#       runtime pi + provider + model through mcp__graftling__subagents, waits until it ends, reads its status,
#       retires it. Observable: CHECK lines PASS: the provider's connection and the model were selected; the wait
#       result has outcome completed with last_message C609-CHILD-OK; the child's record runs that provider/model
#       with api_key_env OPENCODE_API_KEY; retired; no key value in any record.
# Order: 00, I, L, C. Nothing is pushed or published. ~/.pi ~/.dsh ~/.codex ~/.claude ~/.graphtraj are never read or
# written: Pi gets PI_CODING_AGENT_DIR=$T/pi-home, graftling's data root is $T/data.
# Credentials: every started process gets an ALLOWLIST environment (run_env: HOME USER PATH TERM TMPDIR LANG plus the
# step's own variables). cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL, *_AUTH* or *SECRET* name other than
# the step's approved OPENCODE_API_KEY is in it (names only). The key travels by inheritance, never on a command line.
# No step prints a key value. No pytest step: the Engineer's development runs are in validation.md.
# Rehearsal only (Engineer): P609_T, P609_OUT, P609_GREPO, P609_KEEP (extra variable NAMES to keep: the sandbox's
# proxy variables), P609_OFFLINE_SITE (a site-packages dir holding websockets: install graftling without PyPI),
# P609_SKIP_SANDBOX=1 (I skips the Pi sandbox install). Main leaves all of them unset.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
STEP=${1:-}
TASKDIR=609-graftling-provider-listing-and-create
GREPO=${P609_GREPO:-$H/graftling}                   # read only
GBRANCH=agent/609-graftling-provider-listing-and-create
GBUNDLE=$SD/graftling-609.bundle
T=${P609_T:-/private/tmp/graftling-609}
R=${P609_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost/main-raw}
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only: makes the venv, runs x609.py with -I
PIPKG=/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent
RGSRC=/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/node_modules/@vscode/ripgrep-darwin-arm64/bin/rg
KEY=OPENCODE_API_KEY                                # the only approved credential (Worldline 20261124T210658)
BASEPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
TOKEN=C609-CHILD-OK
X=$SD/x609.py

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
bounded() { local s=$1; shift; /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' $s "$@"; }
# run_env <key name or -> [VAR=value ...] -- command...: a subshell that drops every exported variable except the
# allowlist (and the named key, which is inherited, so its value is on no command line), then execs the command.
run_env() {
  local keep=$1; shift
  (
    local -a sets keepers
    while [[ $1 != -- ]]; do sets+=($1); shift; done; shift
    keepers=(HOME USER PATH TERM TMPDIR LANG ${=P609_KEEP:-})
    [[ $keep != - ]] && keepers+=($keep)
    local n
    for n in ${(f)"$(/usr/bin/env | /usr/bin/sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p')"}; do
      (( ${keepers[(Ie)$n]} )) || unset $n 2>/dev/null
    done
    export PATH=$BASEPATH TERM=${TERM:-xterm} LANG=${LANG:-en_US.UTF-8} TMPDIR=${TMPDIR:-/tmp}
    local s; for s in $sets; do export $s; done
    exec "$@"
  )
}
cred_guard() {  # $1 = the approved key name for this step, or -
  local names; names=$(run_env $1 -- /usr/bin/env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH|SECRET' | grep -vx -- "$1" | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the started processes' environment: $names"; exit 97; }
  local carried; carried=$(run_env $1 -- /usr/bin/env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH|SECRET' | tr '\n' ' ')
  print -r -- "cred_guard: credential-like names the started processes carry: ${${carried% }:-none}"
}
need_key() {
  [[ -n ${(P)KEY:-} ]] || { print "STOP: $KEY is UNSET in this shell. Main asks the USER, sets it, and reruns this step."; exit 1; }
  print "$KEY: SET (value not shown)"
}
need_install() {
  [[ -x $T/venv/bin/python && -f $T/data/config.yml && -f $T/pi-host.json ]] || { print "STOP: run I first (no install under $T)"; exit 1; }
}
EXT() { $T/venv/bin/python -I -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent / "pi" / "extension.mjs")'; }
# One Pi Main: pi --mode json with graftling's Pi extension and host configuration. $1 run dir, $2 provider/model.
pi_main() {
  local D=$1 M=$2 ID=r609-$(uuidgen | cut -c1-8 | tr A-Z a-z)
  mkdir -p $D/sessions
  print -r -- "pi Main: --model $M, session $ID, cwd $T/work, PI_CODING_AGENT_DIR=$T/pi-home, GRAFTLING_PYTHON=$T/venv/bin/python, -e $(EXT), --agents-config $T/pi-host.json"
  (cd $T/work && run_env $KEY PI_CODING_AGENT_DIR=$T/pi-home GRAFTLING_PYTHON=$T/venv/bin/python -- \
     /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"' 900 \
     pi --mode json --session-dir $D/sessions --session-id $ID --model $M -e $(EXT) --agents-config $T/pi-host.json \
     "$(<$D/prompt.txt)" < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt)
  print "pi rc=$? (142 = 900 s limit)"
  cp -R $T/data $D/data 2>/dev/null
  print -r -- "records: $D/stdout.jsonl, $D/sessions/, $D/stderr.txt, $D/data/ (copy of the data root)"
}

mkdir -p $R || exit 1
case $STEP in
00) print "[00] Main. Read only. Login: none. Key: none passed (OPENCODE_API_KEY reported SET/UNSET only). Dialog: none."
  { cred_guard -
    GH=$(git -C $GREPO rev-parse --verify -q $GBRANCH)
    if [[ -z $GH ]]; then print -r -- "CHECK 609 00 graftling branch $GBRANCH in $GREPO: FAIL (absent; fetch it: git -C $GREPO fetch $GBUNDLE $GBRANCH:$GBRANCH)"
    else print -r -- "CHECK 609 00 graftling branch $GBRANCH in $GREPO: PASS ($GH $(git -C $GREPO log -1 --format=%s $GH | cut -c1-90))"; fi
    print -r -- "pi: $(command -v pi) $(run_env - -- pi --version 2>&1 | head -1) | node: $(run_env - -- node --version 2>&1) | npm: $(run_env - -- npm --version 2>&1) | git: $(git --version)"
    print -r -- "conda python (venv base, read only): $CONDA $($CONDA -V 2>&1)"
    [[ -x $RGSRC ]] && print -r -- "CHECK 609 00 rg to link for the Pi sandbox: PASS ($RGSRC: $($RGSRC --version | head -1))" \
      || print -r -- "CHECK 609 00 rg to link for the Pi sandbox: FAIL (no $RGSRC)"
    keys=$PIPKG/node_modules/@earendil-works/pi-ai/dist/env-api-keys.js
    grep -qE '^ *opencode: "OPENCODE_API_KEY"' $keys && grep -qE '^ *"opencode-go": "OPENCODE_API_KEY"' $keys \
      && print -r -- "CHECK 609 00 Pi maps providers opencode and opencode-go to $KEY: PASS ($keys)" \
      || print -r -- "CHECK 609 00 Pi maps providers opencode and opencode-go to $KEY: FAIL ($keys)"
    print -r -- "$KEY: $([[ -n ${(P)KEY:-} ]] && print SET || print UNSET) (name only; L and C need it SET)"
    others=$(env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH|SECRET' | grep -vx $KEY | tr '\n' ' ')
    print -r -- "other credential-like names in Main's shell (never passed on): ${${others% }:-none}"
    [[ -e $T ]] && print -r -- "CHECK 609 00 $T absent: FAIL (move it aside first: mv $T $T.old-\$(date +%s))" \
      || print -r -- "CHECK 609 00 $T absent: PASS"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL\|^STOP' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above)."; exit 1; }
  summary 00 "$(grep -E '^(CHECK|pi:|OPENCODE)' $R/00.txt)"
  print "Success: every CHECK PASS."
  next "zsh $THIS I" ;;

I) print "[I] Main. Install into $T only. Login: none. Key: none passed. Dialog: none. Network: PyPI, github.com, registry.npmjs.org. No inference. ~2-4 min."
  { cred_guard -
    [[ -e $T/venv ]] && { print "STOP: $T/venv exists (an earlier I). Move $T aside: mv $T $T.old-\$(date +%s)"; exit 1; }
    GH=$(git -C $GREPO rev-parse --verify -q $GBRANCH) || { print "STOP: no $GBRANCH in $GREPO; run 00"; exit 1; }
    mkdir -p $T/src $T/pi-home $T/data $T/work $T/pi-sandbox/bin || exit 1
    say "graftling $GH from $GREPO (git archive) into $T/venv"
    git -C $GREPO archive $GH | tar -x -C $T/src || exit 1
    if [[ -n ${P609_OFFLINE_SITE:-} ]]; then   # rehearsal only: no PyPI in the Engineer's sandbox
      run_env - -- $CONDA -m venv --system-site-packages $T/venv || exit 1
      run_env - -- $T/venv/bin/python -m pip install -q --no-deps --no-build-isolation $T/src 2>&1 | grep -v 'Caches/pip' | tail -3
      cp -R $P609_OFFLINE_SITE/websockets $T/venv/lib/python3.13/site-packages/ || exit 1
    else
      run_env - -- $CONDA -m venv $T/venv || exit 1
      run_env - -- $T/venv/bin/python -m pip install -q --disable-pip-version-check $T/src 2>&1 | tail -3
    fi
    print $GH > $T/installed-commit
    v=$(run_env - -- $T/venv/bin/python -I -c 'import graftling, pathlib; print(graftling.__version__, pathlib.Path(graftling.__file__).parent)' 2>&1)
    print -r -- "installed graftling: $v"
    run_env - -- $T/venv/bin/python -I -c 'from graftling.tool import ACTION_FIELDS as A; import sys; sys.exit(0 if "models" in A and "provider" in A["create"][1] else 1)' \
      && print "CHECK 609 I installed graftling has the models feature and create's provider: PASS" \
      || print "CHECK 609 I installed graftling has the models feature and create's provider: FAIL"
    say "Pi sandbox at $T/pi-sandbox (scripts/real-host/install-pi-sandbox.sh); rg linked from DSH's install"
    ln -sf $RGSRC $T/pi-sandbox/bin/rg
    if [[ -n ${P609_SKIP_SANDBOX:-} ]]; then print "Pi sandbox install: skipped (P609_SKIP_SANDBOX, rehearsal only)"
      printf 'sandbox_python=%s\nsandbox_path=%s\n' $T/pi-sandbox/venv/bin/python $T/pi-sandbox/srt/node_modules/.bin:/opt/homebrew/bin:$T/pi-sandbox/bin:/usr/bin:/bin:/usr/sbin:/sbin > $T/pi-sandbox.rehearsal.env
    else
      run_env - -- /bin/bash $WT/scripts/real-host/install-pi-sandbox.sh $T/pi-sandbox > $R/I-pi-sandbox.txt 2>&1; src=$?
      tail -12 $R/I-pi-sandbox.txt; print "install-pi-sandbox.sh rc=$src (full output: $R/I-pi-sandbox.txt)"
      (( src == 0 )) || exit 1
    fi
    ENVF=$T/pi-sandbox/pi-sandbox.env; [[ -n ${P609_SKIP_SANDBOX:-} ]] && ENVF=$T/pi-sandbox.rehearsal.env
    SBP=$(sed -n 's/^sandbox_python=//p' $ENVF) SBX=$(sed -n 's/^sandbox_path=//p' $ENVF)
    say "data root $T/data/config.yml: two Pi connections, one per provider, the same key variable (a name)"
    cat > $T/data/config.yml <<EOF
connections:
  pi-opencode:
    runtime: pi
    home: $T/pi-home
    provider: opencode
    api_key_env: $KEY
  pi-opencode-go:
    runtime: pi
    home: $T/pi-home
    provider: opencode-go
    api_key_env: $KEY
EOF
    cat $T/data/config.yml
    run_env - -- $T/venv/bin/python -I -c 'import json, sys
root, home, sbp, sbx, out = sys.argv[1:6]
json.dump({"root": root, "pi": {"agent_dir": home, "sandbox_python": sbp, "sandbox_path": sbx,
           "worktree_access": "read"}}, open(out, "w"), indent=2)' $T/data $T/pi-home $SBP $SBX $T/pi-host.json
    print -r -- "Pi host configuration $T/pi-host.json: $(tr -d '\n' < $T/pi-host.json | tr -s ' ')"
    run_env - -- $T/venv/bin/python -I -c 'import sys; from graftling import read_connections; c = read_connections(sys.argv[1])["connections"]; sys.exit(0 if {n: e["provider"] for n, e in c.items()} == {"pi-opencode": "opencode", "pi-opencode-go": "opencode-go"} else 1)' $T/data \
      && print "CHECK 609 I config.yml declares pi-opencode (opencode) and pi-opencode-go (opencode-go): PASS" \
      || print "CHECK 609 I config.yml declares pi-opencode (opencode) and pi-opencode-go (opencode-go): FAIL"
  } 2>&1 | tee $R/I.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL\|^STOP' $R/I.txt || { print "\nI STOP (see above). Hand $R/I.txt to the Team."; exit 1; }
  summary I "$(grep -E '^(installed|CHECK|install-pi-sandbox|VERIFIED|NOT VERIFIED|Pi host)' $R/I.txt)"
  print "Success: every 'CHECK 609 I ...: PASS' and 'install-pi-sandbox.sh rc=0'."
  next "Main asks the USER to approve $KEY for L and C, sets it, then: zsh $THIS L" ;;

L) print "[L] Main. Key: $KEY (approved by the USER; Main asks first). Login: none. Dialog: none. ~2-5 min, small inference."
  need_install; D=$R/L-$(date +%Y%m%dT%H%M%S); mkdir -p $D
  { need_key; cred_guard $KEY
    say "(a) installed graftling's discover_models for each declared connection (no inference)"
    run_env $KEY PI_CODING_AGENT_DIR=$T/pi-home -- $T/venv/bin/python -I $X discover $T/data $D/choice.env || { print "STOP: the listing gave nothing to choose (see above)"; exit 1; }
    cp $D/choice.env $R/choice.env
    MP=$(sed -n 's/^provider=//p' $D/choice.env) MM=$(sed -n 's/^model=//p' $D/choice.env)
    say "(b) pi Main ($MP/$MM) with graftling's Pi extension: models, create without provider, create with an undeclared provider"
    print -r -- 'Use only the MCP tool mcp__graftling__subagents, not your own subagents. Make these calls one at a time, in this order, exactly as written. Calls 2 and 3 are expected to return errors; make every call anyway.
1. {"action": "execute", "feature": "models", "arguments": {"runtime": "pi"}}
2. {"action": "execute", "feature": "create", "arguments": {"runtime": "pi", "name": "l609-no-provider", "instruction": "Reply with exactly: L609"}}
3. {"action": "execute", "feature": "create", "arguments": {"runtime": "pi", "provider": "anthropic", "name": "l609-undeclared", "instruction": "Reply with exactly: L609"}}
Then reply with one line: DONE, and stop.' > $D/prompt.txt
    pi_main $D $MP/$MM
    say "checks"
    $CONDA -I $X L $T/data $D/stdout.jsonl $D/sessions
    run_env $KEY -- $CONDA -I $X nokey $KEY $D
  } 2>&1 | tee $D/L.txt; cp $D/L.txt $R/L.txt
  rc=0; grep -q '^CHECK 609 .*: FAIL\|^CHECK 609 .*: CANNOT\|^STOP' $D/L.txt && rc=1
  summary L "$(grep -E '^(CHECK|models:|create errors|choice|connection |  group|pi rc)' $D/L.txt)"
  print "Success: every 'CHECK 609 ...: PASS'. Records: $D"
  (( rc == 0 )) && next "zsh $THIS C $(sed -n 's/^provider=//p' $R/choice.env) $(sed -n 's/^model=//p' $R/choice.env)"
  exit $rc ;;

C) print "[C] Main. Key: $KEY (same approval as L). Login: none. Dialog: none. ~3-8 min, small inference."
  need_install; [[ -f $R/choice.env ]] || { print "STOP: run L first ($R/choice.env missing)"; exit 1; }
  CP=${2:-$(sed -n 's/^provider=//p' $R/choice.env)} CM=${3:-$(sed -n 's/^model=//p' $R/choice.env)}
  MP=$(sed -n 's/^provider=//p' $R/choice.env) MM=$(sed -n 's/^model=//p' $R/choice.env)
  D=$R/C-$(date +%Y%m%dT%H%M%S); mkdir -p $D
  { need_key; cred_guard $KEY
    print -r -- "child: runtime pi, provider $CP, model $CM | Pi Main: $MP/$MM"
    print -r -- 'Use only the MCP tool mcp__graftling__subagents, not your own subagents. Make these calls one at a time, in this order. Where an argument says <agent from 1>, use the "agent" field returned by call 1.
1. {"action": "execute", "feature": "create", "arguments": {"runtime": "pi", "provider": "'$CP'", "model": "'$CM'", "name": "c609", "instruction": "Reply with exactly: '$TOKEN'"}}
2. {"action": "execute", "feature": "wait", "arguments": {"agent": "<agent from 1>", "timeout_seconds": 300}} - repeat this call while its result says timed_out true.
3. {"action": "execute", "feature": "status", "arguments": {"agent": "<agent from 1>"}}
4. {"action": "execute", "feature": "retire", "arguments": {"agent": "<agent from 1>"}}
A notice from subagents may arrive at any time and changes nothing. Then reply with the child'"'"'s answer and stop.' > $D/prompt.txt
    pi_main $D $MP/$MM
    say "checks"
    $CONDA -I $X C $T/data $CP $CM $TOKEN $D/stdout.jsonl $D/sessions
    run_env $KEY -- $CONDA -I $X nokey $KEY $D
  } 2>&1 | tee $D/C.txt; cp $D/C.txt $R/C.txt
  rc=0; grep -q '^CHECK 609 .*: FAIL\|^CHECK 609 .*: CANNOT\|^STOP' $D/C.txt && rc=1
  summary C "$(grep -E '^(CHECK|child:|create:|wait:|status:|record:|pi rc)' $D/C.txt)"
  print "Success: every 'CHECK 609 ...: PASS'. Records: $D"
  next "Main: hand $R/L.txt, $R/C.txt and the L-*/C-* directories to the Team; done"; exit $rc ;;

*) print "usage: zsh $THIS 00|I|L|C [provider model]"; exit 2 ;;
esac
