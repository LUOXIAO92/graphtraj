#!/bin/zsh
# Task 650 rehearsal (Engineer), from 644's: every step through `zsh scripts/verify-650/steps.zsh <STEP>` against the gcloud
# stand-in (fake-gcloud.zsh), with a settings file of RANDOM dummy values generated here (so no committed file can
# hold them) in the git-ignored local/ area, and a random dummy key. Each run's console goes to
# rehearsal/<round>/<NN>-<name>.txt (round: $1, default c1); the checks at the end print counts and yes/no only,
# never a dummy value or address.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
REL=scripts/verify-650/steps.zsh
FAKE=$HERE/rehearsal/fake-gcloud.zsh
OUT=$HERE/rehearsal/${1:-c1}
TAG=$(openssl rand -hex 4)
LOCALDIR=$HERE/local/rehearsal
SET=$LOCALDIR/settings.zsh
EVID=$TMPDIR/v650-rehearsal-evidence
S=$TMPDIR/fake650
IP1=198.51.100.9 IP2=198.51.100.77   # RFC 5737 documentation addresses
rm -rf $LOCALDIR $EVID $S
mkdir -p $LOCALDIR $S $OUT
typeset -A V
V=(PROJECT p-$TAG-proj ZONE z$TAG-east9-q MACHINE_TYPE mt-$TAG-std2 VCPUS 2 VM_NAME vm-$TAG-x VM_LABELS lbl$TAG=val$TAG
   VM_USER u$TAG NETWORK stand-in-net IMAGE_FAMILY fake-family IMAGE_PROJECT stand-in-images DISK_GB 64
   KEY_ENV K${(U)TAG}_SHARED CLAUDE_BASE_URL https://cl.h$TAG.invalid/anth/ CLAUDE_AUTH_VAR ANTHROPIC_AUTH_TOKEN
   CLAUDE_MODEL cm-$TAG-pro CLAUDE_HAIKU_MODEL cm-$TAG-mini CLAUDE_SONNET_MODEL '' CLAUDE_OPUS_MODEL '' CLAUDE_SUBAGENT_MODEL ''
   CLAUDE_API_TIMEOUT_MS 600000 PI_ROUTE builtin PI_PROVIDER pp$TAG PI_MODEL pm-$TAG-chat PI_KEY_VAR PK${(U)TAG}_KEY
   PI_BASE_URL '' PI_API '' DSH_CHILD_MODEL dm-$TAG-flash DSH_CHILD_PROVIDER '' DSH_CHILD_BASE_URL https://ds.h$TAG.invalid
   DSH_MAIN_KEY_VAR DK${(U)TAG}_KEY DSH_MAIN_BASE_URL '' DSH_MAIN_APP_ARGS "--flag dmm-$TAG-arg"
   PRICE_VM_USD_H 0.1 PRICE_WINLIC_USD_VCPU_H 0.05 PRICE_DISK_USD_GB_MONTH 0.1 PRICE_IP_USD_H 0.005 EST_CURRENCY XXX
   EST_RATE 100 BUDGET 1000)
write_settings() {  # [NAME=override ...] [-NAME (left out)]
  local k; : > $SET
  for k in ${(ok)V}; do (( ${@[(Ie)-$k]} )) || print -r -- "$k=${(q)V[$k]}" >> $SET; done
  for k in "$@"; do [[ $k == -* ]] || print -r -- "${k%%=*}=${(q)k#*=}" >> $SET; done
}
project_rules() {  # <priority>: the network's allow-all SSH and RDP rules at that priority
  print -r -- "[{\"name\": \"default-allow-ssh\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": $1, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"22\"]}]},
 {\"name\": \"default-allow-rdp\", \"network\": \"https://x/global/networks/stand-in-net\", \"direction\": \"INGRESS\", \"priority\": 65534, \"disabled\": false, \"sourceRanges\": [\"0.0.0.0/0\"], \"allowed\": [{\"IPProtocol\": \"tcp\", \"ports\": [\"3389\"]}]}]" > $S/project-rules.json
}
DUMMYKEY=sk-dummy-$TAG-$(openssl rand -hex 16)
export VERIFY650_GCLOUD=$FAKE VERIFY650_SETTINGS=$SET VERIFY650_EVIDENCE=$EVID
export VERIFY650_WAIT_S=8 VERIFY650_POLL_S=1 VERIFY650_REBOOT_S=1 VERIFY650_SESSION_S=3 VERIFY650_CASE_S=60 VERIFY650_IP=$IP1
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
  local got=$(grep -E '^VERDICT 650 ' $file | tail -1)
  local ok=no; [[ $got == *": $expect"* && $(tail -2 $file | head -1) == 'VERDICT 650 '* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $name: expected $expect, got '${got:-no verdict}' (verdict is the last line) -> $ok"
  LAST=$file
}
stepk() {  # K with the dummy key on stdin (no terminal), as the user's paste would arrive
  (( N++ ))
  local file=$OUT/$(printf %02d $N)-$1.txt expect=$2
  print -r -- "\$ <dummy key on stdin> | VERIFY650_K_STDIN=1 zsh $REL K" > $file
  (cd $WT && print -r -- $DUMMYKEY | VERIFY650_K_STDIN=1 zsh $REL K) >> $file 2>&1
  print -r -- "(exit $?)" >> $file
  local got=$(grep -E '^VERDICT 650 ' $file | tail -1) ok=no
  [[ $got == *": $expect"* ]] && ok=yes
  SUMMARY+="$(printf %02d $N) $1: expected $expect, got '${got:-no verdict}' -> $ok"
  LAST=$file
}
yn() { "$@" && print yes || print no; }
has() { grep -q -F -- "$1" $LAST && print yes || print no; }
rm -f $OUT/[0-9][0-9]-*.txt(N)

# Settings guards.
rm -f $SET; step 00-missing-settings STOP 00
write_settings CLAUDE_MODEL=; step 00-empty-required STOP 00
CHECK+="an empty required variable is named: $(has 'settings variable CLAUDE_MODEL is missing or empty')"
write_settings -DSH_MAIN_APP_ARGS; step 00-optional-not-assigned STOP 00
CHECK+="an unassigned optional variable is named, empty allowed: $(has 'settings variable DSH_MAIN_APP_ARGS is missing (it may be empty: DSH_MAIN_APP_ARGS=)')"
write_settings PI_ROUTE=custom PI_KEY_VAR=; step 00-pi-custom-without-base-url STOP 00
CHECK+="PI_ROUTE=custom without PI_BASE_URL is named: $(has 'settings variable PI_BASE_URL is missing or not an http(s) URL')"
write_settings CLAUDE_AUTH_VAR=ANTHROPIC_SOMETHING; step 00-claude-auth-var STOP 00
UNIGN=$HERE/rehearsal/unignored-settings.zsh; write_settings; cp $SET $UNIGN
VERIFY650_SETTINGS=$UNIGN step 00-settings-not-ignored STOP 00; rm -f $UNIGN
write_settings VM_USER=work; step 00-vm-user-ordinary-word STOP 00
CHECK+="an ordinary VM_USER (a word in drive650.py) is refused naming VM_USER: $(has 'settings variable(s) VM_USER hold ordinary text')"
write_settings DSH_CHILD_MODEL=claude; step 00-model-ordinary-word STOP 00
CHECK+="a model value found in the committed files is refused naming it: $(has 'settings variable(s) DSH_CHILD_MODEL hold ordinary text')"
write_settings
project_rules 65534; step 00-preflight PASS 00
step C-vm-absent STOP C
CHECK+="C with no VM (and no Task rules) names V: $(yn grep -q -E 'run( V first)?: zsh scripts/verify-650/steps.zsh V' $LAST)"
step D-vm-absent PASS D
# The flow.
step V-full PASS V
CHECK+="uploaded by tar: $(tr '\n' ' ' < $S/upload.txt)"
CHECK+="Task rules existing when instances create ran: $(grep -c . $S/rules-at-create.txt) (deny and ssh); their descriptions name Task 650: $(grep -c 'description=Task 650' $S/argv.log) of 2"
CHECK+="settings.json sent to the VM: $(/usr/bin/python3 -I -c 'import json, sys
s = json.load(open(sys.argv[1])); pairs = s["scrub"]; names = sorted({p for p, _ in pairs})
print("scrub placeholders", " ".join(names) + ";", "VM_USER pair", ["<VM_USER>", sys.argv[2]] in pairs, "; pins", s["pins"], "; dsh_main app_args", len(s["dsh_main"]["app_args"]), "word(s); the flag not scrubbed", not any(v == "--flag" for _, v in pairs))' $S/uploaded-settings.json ${V[VM_USER]})"
stepk K-dummy-key PASS
step R0-before-I STOP R0
CHECK+="R0 before I: env STOP (no console session), next I then R0, no 'do NOT run D': $(has 'next: zsh scripts/verify-650/steps.zsh I'), $(has 'next: zsh scripts/verify-650/steps.zsh R0'), $(grep -c 'do NOT run D' $LAST)"
touch $S/autologon-fail; step I-autologon-refused STOP I; rm -f $S/autologon-fail
CHECK+="I refused before any reboot: $([[ -f $S/rebooted ]] && print 'rebooted (wrong)' || print 'no reboot')"
touch $S/no-session; step I-not-established STOP I
CHECK+="I not established: observable and next I/D printed: $(has 'the observable: query user shows no Active console session'), $(has 'next: zsh scripts/verify-650/steps.zsh D')"
rm -f $S/no-session; step I PASS I
print -r -- 'STOP the key variable is not set for this user; run step K first' > $S/want-r0
step R0-no-key STOP R0; rm -f $S/want-r0
CHECK+="R0 without the key names K then R0, no 'do NOT run D': $(has 'next: zsh scripts/verify-650/steps.zsh K'), $(has 'next: zsh scripts/verify-650/steps.zsh R0'), $(grep -c 'do NOT run D' $LAST)"
print -r -- 'FAIL (claude model)' > $S/want-r0
step R0-model-differs FAIL R0; rm -f $S/want-r0
CHECK+="R0 FAIL names the user's decision, V for a settings fix, then R0: $(has 'the user decides'), $(has 'next: zsh scripts/verify-650/steps.zsh V'), $(has 'next: zsh scripts/verify-650/steps.zsh R0')"
step R0 PASS R0
: > $S/schedules.log; : > $S/cleanups.log
step C PASS C
CHECK+="C: cases scheduled $(tr '\n' ' ' < $S/schedules.log); a cleanup after each case: $(grep -c . $S/cleanups.log) of $(grep -c . $S/schedules.log)"
print -r -- 'NO-TOOL-CALL (the model made no subagents create call (tool uses: []))' > $S/want-claude-refuse
step C-no-tool-call NO-TOOL-CALL C; rm -f $S/want-claude-refuse
CHECK+="C NO-TOOL-CALL offers one rerun of that case: $(has 'next: zsh scripts/verify-650/steps.zsh case claude-refuse')"
step case-claude-refuse-rerun PASS case claude-refuse
CHECK+="a rerun of a C case points on to P: $(yn grep -q -m1 '^next: zsh scripts/verify-650/steps.zsh P$' $LAST)"
# A driver STOP keeps the VM (no D), names V for the fix and the step to rerun; the step ends at the first STOP.
print -r -- 'STOP driver error: RuntimeError: pi: the Runtime did not start (stand-in)' > $S/want-pi-caller
: > $S/schedules.log
step P-driver-stop STOP P; rm -f $S/want-pi-caller
CHECK+="P driver STOP: 'do NOT run D' $(has 'next: do NOT run D'); names V $(yn grep -q 'next: zsh scripts/verify-650/steps.zsh V$' $LAST); rerun P named $(yn grep -q 'next: zsh scripts/verify-650/steps.zsh P$' $LAST); offers D: $(grep -c 'steps.zsh D$' $LAST); cases scheduled: $(tr '\n' ' ' < $S/schedules.log)(none after the STOP)"
c0=$(grep -c 'compute instances create' $S/argv.log); u0=$(grep -c 'tar -xf - -C C:/' $S/argv.log); p0=$(grep -c 'provision.ps1' $S/argv.log); a0=$(grep -c -e 'autologon.ps1' -e 'shutdown /r' $S/argv.log)
step V-resume-on-existing-VM PASS V
CHECK+="V on the existing VM: instances create calls $(( $(grep -c 'compute instances create' $S/argv.log) - c0 )); re-uploads by tar $(( $(grep -c 'tar -xf - -C C:/' $S/argv.log) - u0 )); provisioning re-run $(( $(grep -c 'provision.ps1' $S/argv.log) - p0 )); autologon.ps1 or reboot run during V: $(( $(grep -c -e 'autologon.ps1' -e 'shutdown /r' $S/argv.log) - a0 ))"
step P PASS P
step S PASS S
CHECK+="S: item lines per case $(for c in dsh dsh-nonascii dsh-stop dsh-kill; do print -n "$c $(grep -c "^  CASE $c " $LAST) "; done)"
print -r -- 'FAIL (D6 the DSH service ends with its owner)' > $S/want-dsh-kill
step S-kill-fails FAIL S; rm -f $S/want-dsh-kill
CHECK+="S with a FAIL still runs every case and names D: $(has 'dsh PASS, dsh-nonascii PASS, dsh-stop PASS, dsh-kill FAIL'), $(has 'next: zsh scripts/verify-650/steps.zsh D')"
touch $S/no-session; step S-env-stop STOP S; rm -f $S/no-session
CHECK+="S env STOP: next I and S, no 'do NOT run D': $(has 'next: zsh scripts/verify-650/steps.zsh I'), $(has 'next: zsh scripts/verify-650/steps.zsh S'), $(grep -c 'do NOT run D' $LAST)"
step case-bad-argument STOP case foo
step E-claude PASS E claude
touch $S/tar-short; step E-dsh-stop-one-file-lost FAIL E dsh-stop; rm -f $S/tar-short
touch $S/disk-left; step D-disk-survives FAIL D; rm -f $S/disk-left
step D-clean PASS D
CHECK+="after D: Task rules left $(ls $S | grep -c '^rule-'), instance $([[ -f $S/instance ]] && print present || print absent)"
step C-after-D STOP C

# Checks (counts and yes/no only).
firstnext() { grep -h -m1 '^next: ' $OUT/[0-9][0-9]-$1.txt 2> /dev/null | sed 's/^next: zsh scripts\/verify-650\/steps.zsh //' ; }
CHECK+="run order by each step's first next line: 00 -> $(firstnext 00-preflight); V -> $(firstnext V-full); K -> $(firstnext K-dummy-key); I -> $(firstnext I); R0 -> $(firstnext R0); C -> $(firstnext C); P -> $(firstnext P); S -> $(firstnext S)"
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
CHECK+="dummy key: in gcloud argv $k_argv, in gcloud environments $k_env, in files (verify-650 tree incl. local/ and rehearsal, stand-in state, evidence) $k_files; arrived on gcloud's stdin (length+SHA-256 match) $k_stdin time(s)"
ev_files=$(find $EVID -type f | wc -l | tr -d ' ')
leak=0
typeset -a scrubbed=(PROJECT ZONE MACHINE_TYPE VM_NAME VM_USER KEY_ENV CLAUDE_MODEL CLAUDE_HAIKU_MODEL PI_PROVIDER PI_MODEL
                     PI_KEY_VAR DSH_CHILD_MODEL DSH_MAIN_KEY_VAR)
for k in $scrubbed; do
  n=$(grep -r -i -l -F -- ${V[$k]} $EVID 2> /dev/null | wc -l | tr -d ' '); (( leak += n ))
done
for k in cl.h$TAG.invalid ds.h$TAG.invalid dmm-$TAG-arg val$TAG; do
  n=$(grep -r -i -l -F -- $k $EVID 2> /dev/null | wc -l | tr -d ' '); (( leak += n ))
done
ips=$(grep -r -l -E '203\.0\.113\.7|2001:db8::7' $EVID | wc -l | tr -d ' ')
holders=$(grep -r -h -o -E '<[A-Z_]+>' $EVID | sort | uniq -c | awk '{printf "%s %s, ", $2, $1}')
CHECK+="fetched evidence: $ev_files files; files still holding a scrubbed settings value incl. VM_USER, URL hosts, label value, app-arg word (any case, UTF-8): $leak; files holding the sample IPv4/IPv6: $ips; placeholders now present: ${holders%, }"
committed=$(cd $WT && git grep --untracked --exclude-standard -i -l -F -e $TAG -e $DUMMYKEY -- . | wc -l | tr -d ' ')
CHECK+="committed-or-committable files (tracked + untracked not ignored) holding the dummy settings tag or the dummy key: $committed"
{
  print -r -- "Task 650 steps rehearsal (stand-in gcloud; random dummy settings and key; consoles 01-$(printf %02d $N) in ${OUT:t}/)"
  print -r -- "--- runs"; print -lr -- $SUMMARY
  print -r -- "--- checks"; print -lr -- $CHECK
} | tee $OUT/00-summary.txt
rm -rf $LOCALDIR
