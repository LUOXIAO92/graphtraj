#!/bin/zsh
# Task 640 rehearsal (Engineer) of the VM-side driver vm/drive640.py on macOS (POSIX branches):
#   - graftling is cloned from a bundle of <Harness>/graftling dev and the candidate checked out, as provision.ps1 does;
#   - R0's logic against a fake `codex` (answer, provider, configured and reported model; a provider refusal STOPs with
#     the raw error scrubbed; no key set STOPs);
#   - R1-R4 and the R5 items against graftling's own stand-in Codex peer (tests/codex_stdio_peer.py), V640_STANDIN;
#   - scan: the key planted in the evidence fails the scan without printing it; scrub counts.
# Settings values and the key are RANDOM per run, so no committed file can hold them. Consoles: rehearsal/drv-NN-*.txt.
emulate -L zsh
setopt pipe_fail no_unset
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
OUT=$HERE/rehearsal
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
PY=$HARNESS/.venv-runtime/bin/python   # has PyYAML and websockets (graftling's runtime needs); graftling from PYTHONPATH
CANDIDATE=2ee706eb749355afc3f73f03a1b0de4cd48da1f2
TAG=$(openssl rand -hex 4)
H=$(mktemp -d $TMPDIR/v640drv.XXXXXX)   # not named after TAG, so a TAG hit means a settings value
mkdir -p $H/bin $H/codex-home
KEYENV=K${(U)TAG}_API_KEY
KEYVAL=sk-dummy-$TAG-$(openssl rand -hex 16)
MODEL=model-$TAG-flash PROV=prov$TAG URL=https://api.h$TAG.invalid/v7/
git -C $HARNESS/graftling bundle create -q $H/graftling.bundle refs/heads/dev
git clone -q --template= --no-checkout $H/graftling.bundle $H/graftling && git -C $H/graftling checkout -q --detach $CANDIDATE
$PY -I -c 'import json, sys
t, model, prov, url, keyenv, cand = sys.argv[2:8]
pairs = [["<PROJECT>", f"p-{t}-proj"], ["<ZONE>", f"z{t}-east9-q"], ["<VM_NAME>", f"vm-{t}-x"], ["<MACHINE_TYPE>", f"mt-{t}-std2"],
         ["<PROVIDER_ID>", prov], ["<PROVIDER_NAME>", f"Prov{t} Name"], ["<BASE_URL>", url], ["<BASE_URL>", url.rstrip("/")],
         ["<BASE_URL_HOST>", url.split("/")[2]], ["<MODEL>", model], ["<KEY_ENV>", keyenv]]
json.dump({"provider": {"id": prov, "name": f"Prov{t} Name", "base_url": url, "wire_api": "responses", "model": model, "key_env": keyenv},
           "codex_version": "0.172.0", "candidate": cand, "scrub": pairs}, open(sys.argv[1], "w"))' \
  $H/settings.json $TAG $MODEL $PROV $URL $KEYENV $CANDIDATE
cat > $H/bin/codex <<EOF
#!$PY -I
import json, os, sys, time, tomllib, pathlib
if sys.argv[1:2] == ['--version']:
    print('codex-cli 0.172.0 (stand-in)'); sys.exit(0)
home = pathlib.Path(os.environ['CODEX_HOME'])
config = tomllib.loads((home / 'config.toml').read_text())
provider = config['model_providers'][config['model_provider']]
if os.environ.get('FAKE_CODEX_FAIL'):
    print('ERROR: unexpected status 400 Bad Request: {"error": "model ' + config['model'] + ' is not served over Responses at ' + provider['base_url'] + '"}', file=sys.stderr)
    sys.exit(1)
day = home / 'sessions' / '2026' / '11' / '26'; day.mkdir(parents=True, exist_ok=True)
records = [{'type': 'session_meta', 'payload': {'model_provider': config['model_provider']}},
           {'type': 'turn_context', 'payload': {'model': config['model']}}]
if os.environ.get('FAKE_CODEX_REPORTED'):
    records.append({'type': 'event_msg', 'payload': {'type': 'token_count', 'model': os.environ['FAKE_CODEX_REPORTED']}})
(day / f'rollout-{time.time_ns()}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
for event in ({'type': 'thread.started'}, {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'PONG640'}},
              {'type': 'turn.completed'}):
    print(json.dumps(event))
EOF
chmod +x $H/bin/codex
BASEENV=(HOME=$HOME PATH=$H/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$TMPDIR LANG=en_US.UTF-8 PYTHONPATH=$H/graftling/src
         V640_HOME=$H CODEX_HOME=$H/codex-home)
N=0
typeset -a SUMMARY
drv() {  # drv <name> <expect-regex> <extra env...> -- <driver args...>
  local name=$1 expect=$2; shift 2
  local -a extra=()
  while [[ $1 != -- ]]; do extra+=$1; shift; done; shift
  (( N++ ))
  local file=$OUT/drv-$(printf %02d $N)-$name.txt
  print -r -- "\$ <venv python> scripts/verify-640/vm/drive640.py $*   (env names: ${(j: :)${${extra%%=*}/$KEYENV/<KEY_ENV>}})" > $file
  /usr/bin/env -i $BASEENV $extra $PY $HERE/vm/drive640.py "$@" >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^(RESULT|SCAN|SCRUB) ' $file | tail -1) ok=no
  [[ $got =~ $expect ]] && ok=yes
  SUMMARY+="drv-$(printf %02d $N) $name: expected /$expect/, got '${got:-none}' -> $ok"
}
rm -f $OUT/drv-[0-9][0-9]-*.txt(N)
drv r0-no-key 'RESULT R0 STOP' -- r0
drv r0-provider-refuses 'RESULT R0 STOP' $KEYENV=$KEYVAL FAKE_CODEX_FAIL=1 -- r0
drv r0-reported-model-differs 'RESULT R0 FAIL' $KEYENV=$KEYVAL FAKE_CODEX_REPORTED=other-model -- r0
drv r0-pass 'RESULT R0 PASS' $KEYENV=$KEYVAL FAKE_CODEX_REPORTED=$MODEL -- r0
drv scan-r0 'SCAN PASS' $KEYENV=$KEYVAL -- scan R0
print -r -- "planted $KEYVAL" > $H/out/R0/planted.txt
drv scan-finds-planted-key 'SCAN FAIL' $KEYENV=$KEYVAL -- scan R0
rm -f $H/out/R0/planted.txt
drv run-mxc-standin 'RESULT R-mxc PASS' $KEYENV=$KEYVAL V640_STANDIN=$H/graftling/tests -- run mxc
drv scan-run 'SCAN PASS' $KEYENV=$KEYVAL -- scan R-mxc
typeset -a CHECK
k=$(grep -r -l -F -- $KEYVAL $OUT 2> /dev/null | wc -l | tr -d ' ')
hits=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e $TAG -e $KEYVAL -- .)
v=$(print -rn -- $hits | grep -c .)
[[ -n $hits ]] && CHECK+="files with a hit (names only): ${(f)hits}"
raw=$(grep -c -E '<MODEL>|<BASE_URL>' $OUT/drv-02-r0-provider-refuses.txt)
left=$(grep -r -i -l -F -e $MODEL -e api.h$TAG.invalid $H/out | wc -l | tr -d ' ')
CHECK+="consoles holding the key: $k; committed-or-committable files holding a random value or the key: $v"
CHECK+="provider refusal console: raw error printed with placeholders ($raw line(s) with <MODEL>/<BASE_URL>)"
CHECK+="VM-side evidence (out/) files still holding the model or base-URL host after the scans: $left"
{
  print -r -- "Task 640 driver rehearsal on macOS (POSIX branches; graftling ${CANDIDATE[1,12]} cloned from a bundle of dev)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/drv-00-summary.txt
rm -rf $H
