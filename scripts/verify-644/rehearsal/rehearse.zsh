#!/bin/zsh
# Task 644 rehearsal (Engineer), from 643's: every step through `zsh scripts/verify-644/steps.zsh <STEP>` against the gcloud
# stand-in (fake-gcloud.zsh), with a settings file of RANDOM dummy values generated here (so no committed file can
# hold them) in the git-ignored local/ area, and a random dummy key. Each run's console goes to
# rehearsal/<round>/<NN>-<name>.txt (round: $1, default c1); the checks at the end print counts and yes/no only,
# never a dummy value or address.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
REL=scripts/verify-644/steps.zsh
FAKE=$HERE/rehearsal/fake-gcloud.zsh
OUT=$HERE/rehearsal/${1:-c1}
TAG=$(openssl rand -hex 4)
LOCALDIR=$HERE/local/rehearsal
SET=$LOCALDIR/settings.zsh
EVID=$TMPDIR/v644-rehearsal-evidence
S=$TMPDIR/fake644
IP1=198.51.100.9 IP2=198.51.100.77   # RFC 5737 documentation addresses
rm -rf $LOCALDIR $EVID $S
mkdir -p $LOCALDIR $S $OUT
typeset -A V
V=(PROJECT p-$TAG-proj ZONE z$TAG-east9-q MACHINE_TYPE mt-$TAG-std2 VCPUS 2 VM_NAME vm-$TAG-x VM_LABELS lbl$TAG=val$TAG
   VM_USER u$TAG NETWORK stand-in-net IMAGE_FAMILY fake-family IMAGE_PROJECT stand-in-images DISK_GB 64
   PROVIDER_ID prov$TAG PROVIDER_NAME "Prov$TAG Name" BASE_URL https://api.h$TAG.invalid/v7/ WIRE_API responses
   MODEL model-$TAG-flash KEY_ENV K${(U)TAG}_API_KEY PRICE_VM_USD_H 0.1 PRICE_WINLIC_USD_VCPU_H 0.05
   PRICE_DISK_USD_GB_MONTH 0.1 PRICE_IP_USD_H 0.005 EST_CURRENCY XXX EST_RATE 100 BUDGET 1000)
write_settings() {  # [NAME=override ...]
  local k; : > $SET
  for k in ${(ok)V}; do print -r -- "$k=${(q)V[$k]}" >> $SET; done
  for k in "$@"; do print -r -- "${k%%=*}=${(q)k#*=}" >> $SET; done
}
project_rules() {  # <priority>: the network's allow-all SSH and RDP rules at that priority
  print -r -- "[{\"name\": \"default-allow-ssh\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": $1, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"22\"]}]},
 {\"name\": \"default-allow-rdp\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": 65534, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"3389\"]}]}]" > $S/project-rules.json
}
DUMMYKEY=sk-dummy-$TAG-$(openssl rand -hex 16)
export VERIFY644_GCLOUD=$FAKE VERIFY644_SETTINGS=$SET VERIFY644_EVIDENCE=$EVID
export VERIFY644_WAIT_S=8 VERIFY644_POLL_S=1 VERIFY644_REBOOT_S=1 VERIFY644_SESSION_S=3 VERIFY644_CASE_S=60 VERIFY644_IP=$IP1
chmod +x $FAKE
N=0
typeset -a SUMMARY CHECK
step() {  # step <name> <expect: PASS|FAIL|STOP|NO-TOOL-CALL> <args...>
  local name=$1 expect=$2; shift 2
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$name.txt
  print -r -- "\$ zsh $REL $*" > $file
  (cd $WT && zsh $REL "$@") >> $file 2>&1
  local rc=$?
  print -r -- "(exit $rc)" >> $file
  local got=$(grep -E '^VERDICT 644 ' $file | tail -1)
  local ok=no; [[ $got == *": $expect"* && $(tail -2 $file | head -1) == 'VERDICT 644 '* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $name: expected $expect, got '${got:-no verdict}' (verdict is the last line) -> $ok"
  LAST=$file
}
stepk() {  # K with the dummy key on stdin (no terminal), as the user's paste would arrive
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$1.txt expect=$2
  print -r -- "\$ <dummy key on stdin> | VERIFY644_K_STDIN=1 zsh $REL K" > $file
  (cd $WT && print -r -- $DUMMYKEY | VERIFY644_K_STDIN=1 zsh $REL K) >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^VERDICT 644 ' $file | tail -1) ok=no
  [[ $got == *": $expect"* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $1: expected $expect, got '${got:-no verdict}' -> $ok"
  LAST=$file
}
yn() { "$@" && print yes || print no; }
has() { grep -q -F -- "$1" $LAST && print yes || print no; }
rm -f $OUT/[0-9][0-9]-*.txt(N)

# Settings guards.
rm -f $SET; step 00-missing-settings STOP 00
write_settings MODEL=; step 00-empty-variable STOP 00
UNIGN=$HERE/rehearsal/unignored-settings.zsh; write_settings; cp $SET $UNIGN
VERIFY644_SETTINGS=$UNIGN step 00-settings-not-ignored STOP 00; rm -f $UNIGN
write_settings VM_USER=work; step 00-vm-user-ordinary-word STOP 00
CHECK+="an ordinary VM_USER (a word in drive644.py) is refused naming VM_USER: $(has 'settings variable(s) VM_USER hold ordinary text')"
write_settings
project_rules 65534; step 00-preflight PASS 00
step C1-vm-absent STOP C1
CHECK+="C1 with no VM (and no Task rules) names V: $(yn grep -q -E 'run( V first)?: zsh scripts/verify-644/steps.zsh V' $LAST)"
step D-vm-absent PASS D
# The flow.
step V-full PASS V
CHECK+="uploaded by tar: $(tr '\n' ' ' < $S/upload.txt)"
CHECK+="Task rules existing when instances create ran: $(grep -c . $S/rules-at-create.txt) (deny and ssh); their descriptions name Task 644: $(grep -c 'description=Task 644' $S/argv.log) of 2"
CHECK+="VM_USER is a scrub pair sent to the VM: $(/usr/bin/python3 -I -c 'import json, sys; print("yes" if ["<VM_USER>", sys.argv[2]] in json.load(open(sys.argv[1]))["scrub"] else "no")' $S/uploaded-settings.json ${V[VM_USER]})"
touch $S/no-key; step R0-before-K STOP R0; rm -f $S/no-key
CHECK+="R0 without the key names K: $(has 'next: zsh scripts/verify-644/steps.zsh K')"
stepk K-dummy-key PASS
step R0 PASS R0
step C1-before-I STOP C1
CHECK+="C1 before I: env STOP (no console session), next I then C1, no 'do NOT run D': $(has 'next: zsh scripts/verify-644/steps.zsh I'), $(has 'next: zsh scripts/verify-644/steps.zsh C1'), $(grep -c 'do NOT run D' $LAST)"
touch $S/autologon-fail; step I-autologon-refused STOP I; rm -f $S/autologon-fail
CHECK+="I refused before any reboot: $([[ -f $S/rebooted ]] && print 'rebooted (wrong)' || print 'no reboot')"
touch $S/no-session; step I-not-established STOP I
CHECK+="I not established: observable and next I/D printed: $(has 'the observable: query user shows no Active console session'), $(has 'next: zsh scripts/verify-644/steps.zsh D')"
rm -f $S/no-session; step I PASS I
: > $S/schedules.log; : > $S/cleanups.log
step C1 PASS C1
CHECK+="C1: item lines tool $(grep -c '^  CASE tool ' $LAST), nonascii $(grep -c '^  CASE nonascii ' $LAST); a cleanup after each case: $(grep -c . $S/cleanups.log) of $(grep -c . $S/schedules.log)"
print -r -- 'NO-TOOL-CALL (rollout rollout-x.jsonl: the model made no shell call)' > $S/want-nonascii
step C1-no-tool-call NO-TOOL-CALL C1; rm -f $S/want-nonascii
CHECK+="C1 NO-TOOL-CALL offers one rerun of that case: $(has 'next: zsh scripts/verify-644/steps.zsh case nonascii')"
step case-nonascii-rerun PASS case nonascii
# A driver STOP keeps the VM (no D), names V for the fix and the step to rerun; the step ends at the first STOP.
print -r -- 'STOP driver error: RuntimeError: the owner process ended during wait (stand-in)' > $S/want-takeover
: > $S/schedules.log
step C2-driver-stop STOP C2; rm -f $S/want-takeover
CHECK+="C2 driver STOP: 'do NOT run D' $(has 'next: do NOT run D'); names V $(yn grep -q 'next: zsh scripts/verify-644/steps.zsh V$' $LAST); rerun C2 named $(yn grep -q 'next: zsh scripts/verify-644/steps.zsh C2$' $LAST); offers D: $(grep -c 'steps.zsh D$' $LAST); cases scheduled: $(tr '\n' ' ' < $S/schedules.log)(caller not run after the STOP)"
c0=$(grep -c 'compute instances create' $S/argv.log); u0=$(grep -c 'tar -xf - -C C:/' $S/argv.log); p0=$(grep -c 'provision.ps1' $S/argv.log); a0=$(grep -c -e 'autologon.ps1' -e 'shutdown /r' $S/argv.log)
step V-resume-on-existing-VM PASS V
CHECK+="V on the existing VM: instances create calls $(( $(grep -c 'compute instances create' $S/argv.log) - c0 )); re-uploads by tar $(( $(grep -c 'tar -xf - -C C:/' $S/argv.log) - u0 )); provisioning re-run $(( $(grep -c 'provision.ps1' $S/argv.log) - p0 )); autologon.ps1 or reboot run during V: $(( $(grep -c -e 'autologon.ps1' -e 'shutdown /r' $S/argv.log) - a0 ))"
step C2 PASS C2
CHECK+="C2: item lines stop $(grep -c '^  CASE stop ' $LAST), takeover $(grep -c '^  CASE takeover ' $LAST), caller $(grep -c '^  CASE caller ' $LAST)"
print -r -- 'FAIL (job after stop, every job process ended)' > $S/want-stop
step C2-stop-fails FAIL C2; rm -f $S/want-stop
CHECK+="C2 with a FAIL still runs every case and names D: $(has 'stop FAIL, takeover PASS, caller PASS'), $(has 'next: zsh scripts/verify-644/steps.zsh D')"
touch $S/no-session; step C2-env-stop STOP C2; rm -f $S/no-session
CHECK+="C2 env STOP: next I and C2, no 'do NOT run D': $(has 'next: zsh scripts/verify-644/steps.zsh I'), $(has 'next: zsh scripts/verify-644/steps.zsh C2'), $(grep -c 'do NOT run D' $LAST)"
step case-bad-argument STOP case foo
step E-tool PASS E tool
touch $S/tar-short; step E-stop-one-file-lost FAIL E stop; rm -f $S/tar-short
touch $S/disk-left; step D-disk-survives FAIL D; rm -f $S/disk-left
step D-clean PASS D
CHECK+="after D: Task rules left $(ls $S | grep -c '^rule-'), instance $([[ -f $S/instance ]] && print present || print absent)"
step C1-after-D STOP C1

# Checks (counts and yes/no only).
firstnext() { grep -h -m1 '^next: ' $OUT/[0-9][0-9]-$1.txt 2> /dev/null | sed 's/^next: zsh scripts\/verify-644\/steps.zsh //' ; }
CHECK+="run order by each step's first next line: 00 -> $(firstnext 00-preflight); V -> $(firstnext V-full); K -> $(firstnext K-dummy-key); R0 -> $(firstnext R0); I -> $(firstnext I); C1 -> $(firstnext C1); C2 -> $(firstnext C2)"
lines=$(grep -c . $S/argv.log)
noproj=$(grep -v -c -- '--project=' $S/argv.log)
other=$(grep -v -- "--project=${V[PROJECT]}" $S/argv.log | grep -v -c -- "compute images describe-from-family .*--project=${V[IMAGE_PROJECT]}")
cfg=$(grep -c -E '(^| )config( |$)' $S/argv.log)
CHECK+="gcloud calls: $lines; without --project: $noproj; naming another project than <PROJECT>, other than the public image read: $other; 'config' calls: $cfg; compute scp calls: $(grep -c 'compute scp' $S/argv.log)"
ipc=$(grep -l -F -e $IP1 -e $IP2 $OUT/*.txt 2> /dev/null | wc -l | tr -d ' ')
CHECK+="consoles showing either address: $ipc"
k_argv=$(grep -c -F -- $DUMMYKEY $S/argv.log)
k_env=$(grep -c -F -- $DUMMYKEY $S/env.log)
k_files=$(grep -r -l -F -- $DUMMYKEY $HERE $S $EVID 2> /dev/null | wc -l | tr -d ' ')
want="length=${#DUMMYKEY} sha256=$(print -rn -- $DUMMYKEY | shasum -a 256 | cut -d' ' -f1)"
k_stdin=$(grep -c -F -- "$want" $S/stdin.log)
CHECK+="dummy key: in gcloud argv $k_argv, in gcloud environments $k_env, in files (verify-644 tree incl. local/ and rehearsal, stand-in state, evidence) $k_files; arrived on gcloud's stdin (length+SHA-256 match) $k_stdin time(s)"
ev_files=$(find $EVID -type f | wc -l | tr -d ' ')
leak=0
for k in PROJECT ZONE MACHINE_TYPE VM_NAME PROVIDER_ID PROVIDER_NAME BASE_URL MODEL KEY_ENV VM_USER; do
  n=$(grep -r -i -l -F -- ${V[$k]} $EVID 2> /dev/null | wc -l | tr -d ' '); (( leak += n ))
done
ips=$(grep -r -l -E '203\.0\.113\.7|2001:db8::7' $EVID | wc -l | tr -d ' ')
holders=$(grep -r -h -o -E '<(PROJECT|ZONE|REGION|VM_NAME|MACHINE_TYPE|PROVIDER_ID|PROVIDER_NAME|BASE_URL|BASE_URL_HOST|MODEL|KEY_ENV|ACCOUNT|VM_LABEL|VM_USER|IP)>' $EVID | sort | uniq -c | awk '{printf "%s %s, ", $2, $1}')
CHECK+="fetched evidence: $ev_files files; files still holding a settings value incl. VM_USER (any case, UTF-8): $leak; files holding the sample IPv4/IPv6: $ips; placeholders now present: ${holders%, }"
committed=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e ${V[PROJECT]} -e ${V[ZONE]} -e ${V[MACHINE_TYPE]} -e ${V[VM_NAME]} -e lbl$TAG -e ${V[PROVIDER_ID]} -e ${V[MODEL]} -e api.h$TAG.invalid -e ${V[KEY_ENV]} -e ${V[VM_USER]} -e $DUMMYKEY -- . | wc -l | tr -d ' ')
CHECK+="committed-or-committable files (tracked + untracked not ignored) holding any dummy value or the dummy key: $committed"
{
  print -r -- "Task 644 steps rehearsal (stand-in gcloud; random dummy settings and key; consoles 01-$(printf %02d $N) in ${OUT:t}/)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/00-summary.txt
rm -rf $LOCALDIR
