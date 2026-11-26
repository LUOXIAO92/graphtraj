#!/bin/zsh
# Task 640 rehearsal (Engineer): every step through `zsh scripts/verify-640/steps.zsh <STEP>` against the gcloud
# stand-in (fake-gcloud.zsh), with a settings file of RANDOM dummy values generated here (so no committed file can
# hold them) in the git-ignored local/ area, and a random dummy key. Each run's console goes to
# rehearsal/<round>/<NN>-<name>.txt (round: $1, default c1; round 1's consoles stay in rehearsal/ as committed); the
# checks at the end print counts and yes/no only, never a dummy value or address.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
REL=scripts/verify-640/steps.zsh
FAKE=$HERE/rehearsal/fake-gcloud.zsh
OUT=$HERE/rehearsal/${1:-c1}
TAG=$(openssl rand -hex 4)
LOCALDIR=$HERE/local/rehearsal
SET=$LOCALDIR/settings.zsh
EVID=$TMPDIR/v640-rehearsal-evidence
S=$TMPDIR/fake640
IP1=198.51.100.9 IP2=198.51.100.77   # RFC 5737 documentation addresses
rm -rf $LOCALDIR $EVID $S
mkdir -p $LOCALDIR $S $OUT
typeset -A V
V=(PROJECT p-$TAG-proj ZONE z$TAG-east9-q MACHINE_TYPE mt-$TAG-std2 VCPUS 2 VM_NAME vm-$TAG-x VM_LABELS lbl$TAG=val$TAG
   VM_USER v640user NETWORK stand-in-net IMAGE_FAMILY fake-family IMAGE_PROJECT stand-in-images DISK_GB 64
   PROVIDER_ID prov$TAG PROVIDER_NAME "Prov$TAG Name" BASE_URL https://api.h$TAG.invalid/v7/ WIRE_API responses
   MODEL model-$TAG-flash KEY_ENV K${(U)TAG}_API_KEY PRICE_VM_USD_H 0.1 PRICE_WINLIC_USD_VCPU_H 0.05
   PRICE_DISK_USD_GB_MONTH 0.1 PRICE_IP_USD_H 0.005 EST_CURRENCY XXX EST_RATE 100 BUDGET 1000)
write_settings() {  # [NAME=override ...]
  local k; : > $SET
  for k in ${(ok)V}; do print -r -- "$k=${(q)V[$k]}" >> $SET; done
  for k in "$@"; do print -r -- "${k%%=*}=${(q)k#*=}" >> $SET; done
}
project_rules() {  # <priority>: the default network's allow-all SSH and RDP rules at that priority
  print -r -- "[{\"name\": \"default-allow-ssh\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": $1, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"22\"]}]},
 {\"name\": \"default-allow-rdp\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": 65534, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"3389\"]}]}]" > $S/project-rules.json
}
DUMMYKEY=sk-dummy-$TAG-$(openssl rand -hex 16)
export VERIFY640_GCLOUD=$FAKE VERIFY640_SETTINGS=$SET VERIFY640_EVIDENCE=$EVID
export VERIFY640_WAIT_S=8 VERIFY640_POLL_S=1 VERIFY640_IP=$IP1
chmod +x $FAKE
N=0
typeset -a SUMMARY CHECK
step() {  # step <name> <expect: PASS|FAIL|STOP> <args...>
  local name=$1 expect=$2; shift 2
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$name.txt
  print -r -- "\$ zsh $REL $*" > $file
  (cd $WT && zsh $REL "$@") >> $file 2>&1
  local rc=$?
  print -r -- "(exit $rc)" >> $file
  local got=$(grep -E '^VERDICT 640 ' $file | tail -1)
  local ok=no; [[ $got == *": $expect"* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $name: expected $expect, got '${got:-no verdict}' -> $ok"
  LAST=$file
}
stepk() {  # K with the dummy key on stdin (no terminal), as the user's paste would arrive
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$1.txt expect=$2
  print -r -- "\$ <dummy key on stdin> | VERIFY640_K_STDIN=${3:-1} zsh $REL K" > $file
  (cd $WT && print -r -- $DUMMYKEY | VERIFY640_K_STDIN=${3:-1} zsh $REL K) >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^VERDICT 640 ' $file | tail -1) ok=no
  [[ $got == *": $expect"* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $1: expected $expect, got '${got:-no verdict}' -> $ok"
  LAST=$file
}
yn() { "$@" && print yes || print no; }
rule() {  # rule <name-suffix> <python expression on r>: yes/no
  local f=$S/rule-${V[VM_NAME]}-$1.json
  [[ -f $f ]] || { print absent; return; }
  /usr/bin/python3 -I -c "import json, sys; r = json.load(open(sys.argv[1])); ip1, ip2 = sys.argv[2:4]; print('yes' if ($2) else 'no')" $f $IP1 $IP2
}
rm -f $OUT/[0-9][0-9]-*.txt(N)

# Settings guards (file, variables, ordinary scrub values).
rm -f $SET; step 00-missing-settings STOP 00
write_settings MODEL=; step 00-empty-variable STOP 00
UNIGN=$HERE/rehearsal/unignored-settings.zsh; write_settings; cp $SET $UNIGN
VERIFY640_SETTINGS=$UNIGN step 00-settings-not-ignored STOP 00; rm -f $UNIGN
write_settings VM_LABELS=lbl$TAG=permissions; step 00-label-value-ordinary-word STOP 00
CHECK+="ordinary label value: console names VM_LABELS: $(yn grep -q 'settings variable(s) VM_LABELS hold ordinary text' $LAST)"
write_settings VM_LABELS=lbl$TAG=ab; step 00-label-value-too-short STOP 00
write_settings
# Image check.
touch $S/image-mismatch; step 00-image-other-family STOP 00; rm -f $S/image-mismatch
CHECK+="image mismatch: gcloud's raw line printed: $(yn grep -q '  | windows-server-fake' $LAST)"
# Project rules: allow-all at 65534 (default network) is fine; one at priority <= 1000 STOPs 00 and V before anything.
project_rules 65534; step 00-project-allow-all-65534 PASS 00
CHECK+="00 NOTE names the project rules with priorities: $(yn grep -q 'default-allow-ssh 65534' $LAST)"
project_rules 1000; step 00-project-rule-priority-1000 STOP 00
step V-project-rule-priority-1000 STOP V
CHECK+="V stopped before creating anything: instance $([[ -f $S/instance ]] && print present || print absent), Task rules ${#${(@f)$(ls $S | grep '^rule-')}}"
project_rules 65534
# V refused by gcloud (rules already made), then D alone; V with no SSH answer, then D.
touch $S/fail-create; step V-create-refused STOP V; rm -f $S/fail-create
CHECK+="after the refused create: Task rules present $(ls $S | grep -c '^rule-') (D removes them)"
step D-after-refused-create PASS D
touch $S/ssh-fail; step V-no-ssh-answer STOP V; rm -f $S/ssh-fail
step D-after-partial-V PASS D
# The full sequence.
step V-full PASS V
c0=$(grep -c 'compute instances create' $S/argv.log)
step V-again-on-existing-VM PASS V
CHECK+="V on the existing RUNNING VM: instances create calls during it $(( $(grep -c 'compute instances create' $S/argv.log) - c0 )); said it resumes: $(yn grep -q 'provisioning resumes on it' $LAST); rules re-checked: $(yn grep -q 'Task firewall rules in place' $LAST); upload overwrote (tar): $(yn grep -q 'tar -xf - -C C:/' $LAST); provision ran: $(yn grep -q '^PROVISION PASS' $LAST)"
CHECK+="uploaded by tar: $(tr '\n' ' ' < $S/upload.txt)"
CHECK+="Task rules existing when instances create ran: $(grep -c . $S/rules-at-create.txt) (deny and ssh)"
CHECK+="deny rule as specified (DENY all, 0.0.0.0/0, priority 1000, only the VM tag, enabled): $(rule deny 'r["denied"] == [{"IPProtocol": "all"}] and r["sourceRanges"] == ["0.0.0.0/0"] and r["priority"] == 1000 and r["targetTags"] == [sys.argv[1].split("rule-")[1][:-10]] and not r["disabled"]')"
CHECK+="ssh rule as specified (ALLOW tcp:22, source = first address/32, priority 900): $(rule ssh 'r["allowed"] == [{"IPProtocol": "tcp", "ports": ["22"]}] and r["sourceRanges"] == [ip1 + "/32"] and r["priority"] == 900')"
stepk K-no-terminal STOP 0
VERIFY640_IP=$IP2 stepk K-dummy-key-after-address-change PASS
CHECK+="address change: K updated the ssh rule: $(yn grep -q "source was not the current public IPv4; updated" $LAST); its source is now the new address/32: $(rule ssh 'r["sourceRanges"] == [ip2 + "/32"]')"
VERIFY640_IP=$IP2 step R0 PASS R0
CHECK+="R0 with an unchanged address made no update: $(yn grep -qv 'updated (address not shown)' $LAST)"
VERIFY640_IP=$IP2 step R-mxc PASS R mxc
VERIFY640_IP=$IP2 step R-unelevated PASS R unelevated
VERIFY640_IP=$IP2 step R-none-fallback PASS R none
CHECK+="R none console says Codex's sandbox is off: $(yn grep -q "Codex's own sandbox OFF" $LAST)"
VERIFY640_IP=$IP2 step E-R0 PASS E R0
CHECK+="fetch count check printed: $(yn grep -q 'PASS: 3 of 3 evidence files arrived' $LAST)"
touch $S/tar-short; VERIFY640_IP=$IP2 step E-R0-one-file-lost FAIL E R0; rm -f $S/tar-short
CHECK+="lost file reported: $(yn grep -q 'the VM counted 3 evidence files, 2 arrived' $LAST)"
touch $S/disk-left; step D-disk-survives FAIL D; rm -f $S/disk-left
step D-clean PASS D
CHECK+="after D: Task rules left $(ls $S | grep -c '^rule-'), instance $([[ -f $S/instance ]] && print present || print absent)"
step R0-after-D STOP R0

# Checks (counts and yes/no only).
lines=$(grep -c . $S/argv.log)
noproj=$(grep -v -c -- '--project=' $S/argv.log)
other=$(grep -v -- "--project=${V[PROJECT]}" $S/argv.log | grep -v -c -- "compute images describe-from-family .*--project=${V[IMAGE_PROJECT]}")
cfg=$(grep -c -E '(^| )config( |$)' $S/argv.log)
CHECK+="gcloud compute scp calls: $(grep -c 'compute scp' $S/argv.log)"
CHECK+="gcloud calls: $lines; without --project: $noproj; naming another project than <PROJECT>, other than the public image read: $other; 'config' calls: $cfg"
ipc=$(grep -l -F -e $IP1 -e $IP2 $OUT/*.txt 2> /dev/null | wc -l | tr -d ' ')
CHECK+="consoles showing either address: $ipc"
k_argv=$(grep -c -F -- $DUMMYKEY $S/argv.log)
k_env=$(grep -c -F -- $DUMMYKEY $S/env.log)
k_files=$(grep -r -l -F -- $DUMMYKEY $HERE $S $EVID 2> /dev/null | wc -l | tr -d ' ')
want="length=${#DUMMYKEY} sha256=$(print -rn -- $DUMMYKEY | shasum -a 256 | cut -d' ' -f1)"
k_stdin=$(grep -c -F -- "$want" $S/stdin.log)
CHECK+="dummy key: in gcloud argv $k_argv, in gcloud environments $k_env, in files (verify-640 tree incl. local/ and rehearsal, stand-in state, evidence) $k_files; arrived on gcloud's stdin (length+SHA-256 match) $k_stdin time(s)"
nonet=$(/usr/bin/python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); vals = [v for _, v in d["scrub"]]; hs = {h for h, _ in d["scrub"]}
print("yes" if sys.argv[2] not in vals and sys.argv[3] not in vals and "<NETWORK>" not in hs else "no")' $S/uploaded-settings.json ${V[NETWORK]} lbl$TAG)
CHECK+="scrub list on the VM leaves out the network name and label keys: $nonet"
ev_files=$(find $EVID -type f | wc -l | tr -d ' ')
leak=0
for k in PROJECT ZONE MACHINE_TYPE VM_NAME PROVIDER_ID PROVIDER_NAME BASE_URL MODEL KEY_ENV; do
  n=$(grep -r -i -l -F -- ${V[$k]} $EVID 2> /dev/null | wc -l | tr -d ' '); (( leak += n ))
done
n=$(grep -r -i -l -F -- api.h$TAG.invalid $EVID | wc -l | tr -d ' '); (( leak += n ))
ips=$(grep -r -l -E '203\.0\.113\.7|2001:db8::7' $EVID | wc -l | tr -d ' ')
u16=$(/usr/bin/python3 -I -c 'import sys, pathlib
vals = sys.argv[2:]
bad = 0
for p in pathlib.Path(sys.argv[1]).rglob("utf16.txt"):
    t = p.read_bytes().decode("utf-16-le").lower()
    bad += sum(v.lower() in t for v in vals)
print(bad)' $EVID ${V[PROJECT]} ${V[MODEL]} ${V[VM_NAME]} ${V[BASE_URL]})
holders=$(grep -r -h -o -E '<(PROJECT|ZONE|REGION|VM_NAME|MACHINE_TYPE|PROVIDER_ID|PROVIDER_NAME|BASE_URL|BASE_URL_HOST|MODEL|KEY_ENV|ACCOUNT|VM_LABEL|NETWORK|IP)>' $EVID | sort | uniq -c | awk '{printf "%s %s, ", $2, $1}')
CHECK+="fetched evidence: $ev_files files; files still holding a settings value (any case, UTF-8): $leak; files holding the sample IPv4/IPv6: $ips; settings values left in the UTF-16 sample: $u16; placeholders now present: ${holders%, }"
committed=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e ${V[PROJECT]} -e ${V[ZONE]} -e ${V[MACHINE_TYPE]} -e ${V[VM_NAME]} -e lbl$TAG -e ${V[PROVIDER_ID]} -e ${V[MODEL]} -e api.h$TAG.invalid -e ${V[KEY_ENV]} -e $DUMMYKEY -- . | wc -l | tr -d ' ')
CHECK+="committed-or-committable files (tracked + untracked not ignored) holding any dummy value or the dummy key: $committed"
{
  print -r -- "Task 640 steps rehearsal (stand-in gcloud; random dummy settings and key; consoles 01-$(printf %02d $N) in ${OUT:t}/)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/00-summary.txt
rm -rf $LOCALDIR
