#!/bin/zsh
# Task 643 rehearsal (Engineer), from 640's: every step through `zsh scripts/verify-643/steps.zsh <STEP>` against the gcloud
# stand-in (fake-gcloud.zsh), with a settings file of RANDOM dummy values generated here (so no committed file can
# hold them) in the git-ignored local/ area, and a random dummy key. Each run's console goes to
# rehearsal/<round>/<NN>-<name>.txt (round: $1, default c1; one directory per rehearsal round); the
# checks at the end print counts and yes/no only, never a dummy value or address.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
REL=scripts/verify-643/steps.zsh
FAKE=$HERE/rehearsal/fake-gcloud.zsh
OUT=$HERE/rehearsal/${1:-c1}
TAG=$(openssl rand -hex 4)
LOCALDIR=$HERE/local/rehearsal
SET=$LOCALDIR/settings.zsh
EVID=$TMPDIR/v643-rehearsal-evidence
S=$TMPDIR/fake643
IP1=198.51.100.9 IP2=198.51.100.77   # RFC 5737 documentation addresses
rm -rf $LOCALDIR $EVID $S
mkdir -p $LOCALDIR $S $OUT
typeset -A V
V=(PROJECT p-$TAG-proj ZONE z$TAG-east9-q MACHINE_TYPE mt-$TAG-std2 VCPUS 2 VM_NAME vm-$TAG-x VM_LABELS lbl$TAG=val$TAG
   VM_USER v643user NETWORK stand-in-net IMAGE_FAMILY fake-family IMAGE_PROJECT stand-in-images DISK_GB 64
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
export VERIFY643_GCLOUD=$FAKE VERIFY643_SETTINGS=$SET VERIFY643_EVIDENCE=$EVID
export VERIFY643_WAIT_S=8 VERIFY643_POLL_S=1 VERIFY643_REBOOT_S=1 VERIFY643_SESSION_S=3 VERIFY643_CASE_S=60 VERIFY643_IP=$IP1
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
  local got=$(grep -E '^VERDICT 643 ' $file | tail -1)
  local ok=no; [[ $got == *": $expect"* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $name: expected $expect, got '${got:-no verdict}' -> $ok"
  LAST=$file
}
stepk() {  # K with the dummy key on stdin (no terminal), as the user's paste would arrive
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$1.txt expect=$2
  print -r -- "\$ <dummy key on stdin> | VERIFY643_K_STDIN=${3:-1} zsh $REL K" > $file
  (cd $WT && print -r -- $DUMMYKEY | VERIFY643_K_STDIN=${3:-1} zsh $REL K) >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^VERDICT 643 ' $file | tail -1) ok=no
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

# Settings guards.
rm -f $SET; step 00-missing-settings STOP 00
write_settings MODEL=; step 00-empty-variable STOP 00
UNIGN=$HERE/rehearsal/unignored-settings.zsh; write_settings; cp $SET $UNIGN
VERIFY643_SETTINGS=$UNIGN step 00-settings-not-ignored STOP 00; rm -f $UNIGN
write_settings
project_rules 65534; step 00-preflight PASS 00
# VM absent: every SSH step STOPs and names V.
step A-vm-absent STOP A
CHECK+="A with no VM names V as next: $(yn grep -q -E 'run( V first)?: zsh scripts/verify-643/steps.zsh V' $LAST)"
step D-vm-absent PASS D
# The flow.
step V-full PASS V
CHECK+="uploaded by tar: $(tr '\n' ' ' < $S/upload.txt)"
CHECK+="Task rules existing when instances create ran: $(grep -c . $S/rules-at-create.txt) (deny and ssh); their descriptions name Task 643: $(grep -c "description=Task 643" $S/argv.log) of 2"
stepk K-dummy-key PASS
step R0 PASS R0
step B-before-I STOP B
CHECK+="B before I: refused for no console session, next names I: $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh I' $LAST)"
step A-tool-failed TOOL-FAILED A
CHECK+="A prints its case lines and next I: $(grep -c '^  CASE A ' $LAST) line(s); $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh I' $LAST)"
print -r -- NO-TOOL-CALL > $S/want-A; step A-no-tool-call NO-TOOL-CALL A; rm -f $S/want-A
CHECK+="A NO-TOOL-CALL offers a rerun: $(yn grep -q 'rerun A once' $LAST)"
touch $S/autologon-fail; step I-autologon-refused STOP I; rm -f $S/autologon-fail
CHECK+="I refused before any reboot: $([[ -f $S/rebooted ]] && print 'rebooted (wrong)' || print 'no reboot')"
touch $S/no-session; step I-not-established STOP I
CHECK+="I not established: observable and next I/D printed: $(yn grep -q 'the observable: query user shows no Active console session' $LAST), $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh D' $LAST)"
rm -f $S/no-session; step I PASS I
step B-tool-failed TOOL-FAILED B
CHECK+="B TOOL-FAILED: next is C ssh, not C interactive: $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh C ssh' $LAST), $(grep -c 'next: zsh scripts/verify-643/steps.zsh C interactive' $LAST)"
step C-interactive-refused STOP C interactive
CHECK+="C interactive refused with the reason and next C ssh: $(yn grep -q "C interactive refused: case B's tool did not run" $LAST), $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh C ssh' $LAST); nothing scheduled for C-interactive: $(grep -c 'schedule C-interactive' $S/argv.log)"
print -r -- TOOL-RAN > $S/want-B; step B-tool-ran TOOL-RAN B
CHECK+="B TOOL-RAN: next C interactive: $(yn grep -q 'next: zsh scripts/verify-643/steps.zsh C interactive' $LAST)"
step C-interactive TOOL-FAILED C interactive
step C-ssh TOOL-FAILED C ssh
step C-bad-argument STOP C
step E-A PASS E A
touch $S/tar-short; step E-B-one-file-lost FAIL E B; rm -f $S/tar-short
touch $S/disk-left; step D-disk-survives FAIL D; rm -f $S/disk-left
step D-clean PASS D
CHECK+="after D: Task rules left $(ls $S | grep -c '^rule-'), instance $([[ -f $S/instance ]] && print present || print absent)"
step A-after-D STOP A

# Checks (counts and yes/no only).
firstnext() { grep -h -m1 '^next: ' $OUT/[0-9][0-9]-$1.txt 2> /dev/null | sed 's/^next: zsh scripts\/verify-643\/steps.zsh //' ; }
CHECK+="run order by each step's first next line: 00 -> $(firstnext 00-preflight); V -> $(firstnext V-full); K -> $(firstnext K-dummy-key); R0 -> $(firstnext R0); A -> $(firstnext A-tool-failed); I -> $(firstnext I); B (tool ran) -> $(firstnext B-tool-ran); C interactive -> $(firstnext C-interactive); C ssh -> $(firstnext C-ssh)"
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
CHECK+="dummy key: in gcloud argv $k_argv, in gcloud environments $k_env, in files (verify-643 tree incl. local/ and rehearsal, stand-in state, evidence) $k_files; arrived on gcloud's stdin (length+SHA-256 match) $k_stdin time(s)"
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
  print -r -- "Task 643 steps rehearsal (stand-in gcloud; random dummy settings and key; consoles 01-$(printf %02d $N) in ${OUT:t}/)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/00-summary.txt
rm -rf $LOCALDIR
