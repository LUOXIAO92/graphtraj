#!/bin/zsh
# Task 640 rehearsal (Engineer): every step through `zsh scripts/verify-640/steps.zsh <STEP>` against the gcloud
# stand-in (fake-gcloud.zsh), with a settings file of RANDOM dummy values generated here (so no committed file can
# hold them) in the git-ignored local/ area, and a random dummy key. Each run's console goes to
# rehearsal/<NN>-<name>.txt; the checks at the end print counts only, never a dummy value.
emulate -L zsh
setopt pipe_fail no_unset
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
REL=scripts/verify-640/steps.zsh
OUT=$HERE/rehearsal
TAG=$(openssl rand -hex 4)
LOCALDIR=$HERE/local/rehearsal
SET=$LOCALDIR/settings.zsh
EVID=$TMPDIR/v640-rehearsal-evidence
S=$TMPDIR/fake640
rm -rf $LOCALDIR $EVID $S
mkdir -p $LOCALDIR $S
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
DUMMYKEY=sk-dummy-$TAG-$(openssl rand -hex 16)
export VERIFY640_GCLOUD=$OUT/fake-gcloud.zsh VERIFY640_SETTINGS=$SET VERIFY640_EVIDENCE=$EVID
export VERIFY640_WAIT_S=8 VERIFY640_POLL_S=1 VERIFY640_IP=198.51.100.9
chmod +x $OUT/fake-gcloud.zsh
N=0
typeset -a SUMMARY
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
}
rm -f $OUT/[0-9][0-9]-*.txt(N)

# Settings file guards.
rm -f $SET; step 00-missing-settings STOP 00
write_settings MODEL=; step 00-empty-variable STOP 00
UNIGN=$OUT/unignored-settings.zsh; cp /dev/null $UNIGN; write_settings; cp $SET $UNIGN
VERIFY640_SETTINGS=$UNIGN step 00-settings-not-ignored STOP 00; rm -f $UNIGN
write_settings
step 00-preflight PASS 00
# V refused by gcloud, then D alone; V with no SSH answer (partial), then D.
touch $S/fail-create; step V-create-refused STOP V; rm -f $S/fail-create
step D-after-refused-create PASS D
touch $S/ssh-fail; step V-no-ssh-answer STOP V; rm -f $S/ssh-fail
PARTIAL="instance $([[ -f $S/instance ]] && print present || print absent), Task firewall rule $([[ -f $S/fw ]] && print present || print absent)"
step D-after-partial-V PASS D
# The full sequence.
step V-full PASS V
stepk K-no-terminal STOP 0
stepk K-dummy-key PASS
step R0 PASS R0
step R-mxc PASS R mxc
step E-R0 PASS E R0
touch $S/disk-left; step D-disk-survives FAIL D; rm -f $S/disk-left
step D-clean PASS D
touch $S/open-ssh; step V-project-opens-ssh PASS V; rm -f $S/open-ssh
step D-after-open-ssh PASS D

# Checks (counts only).
typeset -a CHECK
lines=$(grep -c . $S/argv.log)
noproj=$(grep -v -c -- "--project=${V[PROJECT]}" $S/argv.log)
cfg=$(grep -c -E '(^| )config( |$)' $S/argv.log)
CHECK+="gcloud calls: $lines; without --project=<PROJECT>: $noproj; 'config' calls: $cfg"
k_argv=$(grep -c -F -- $DUMMYKEY $S/argv.log)
k_env=$(grep -c -F -- $DUMMYKEY $S/env.log)
k_files=$(grep -r -l -F -- $DUMMYKEY $HERE $S $EVID 2> /dev/null | wc -l | tr -d ' ')
want="length=${#DUMMYKEY} sha256=$(print -rn -- $DUMMYKEY | shasum -a 256 | cut -d' ' -f1)"
k_stdin=$(grep -c -F -- "$want" $S/stdin.log)
CHECK+="dummy key: in gcloud argv $k_argv, in gcloud environments $k_env, in files (verify-640 tree incl. local/ and rehearsal, stand-in state, evidence) $k_files; arrived on gcloud's stdin (length+SHA-256 match) $k_stdin time(s)"
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
holders=$(grep -r -h -o -E '<(PROJECT|ZONE|REGION|VM_NAME|MACHINE_TYPE|PROVIDER_ID|PROVIDER_NAME|BASE_URL|BASE_URL_HOST|MODEL|KEY_ENV|ACCOUNT|VM_LABEL|IP)>' $EVID | sort | uniq -c | awk '{printf "%s %s, ", $2, $1}')
CHECK+="fetched evidence: $ev_files files; files still holding a settings value (any case, UTF-8): $leak; files holding the sample IPv4/IPv6: $ips; settings values left in the UTF-16 sample: $u16; placeholders now present: ${holders%, }"
committed=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e ${V[PROJECT]} -e ${V[ZONE]} -e ${V[MACHINE_TYPE]} -e ${V[VM_NAME]} -e lbl$TAG -e ${V[PROVIDER_ID]} -e ${V[MODEL]} -e api.h$TAG.invalid -e ${V[KEY_ENV]} -e $DUMMYKEY -- . | wc -l | tr -d ' ')
CHECK+="committed-or-committable files (tracked + untracked not ignored) holding any dummy value or the dummy key: $committed"
CHECK+="after D-after-partial-V's V: $PARTIAL; stand-in state now: instance $([[ -f $S/instance ]] && print present || print absent), firewall rule $([[ -f $S/fw ]] && print present || print absent)"
{
  print -r -- "Task 640 steps rehearsal (stand-in gcloud; random dummy settings and key; consoles 01-$(printf %02d $N))"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/00-summary.txt
rm -rf $LOCALDIR
