#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 643: where Codex's tool-process exit -1073741502 (0xC0000142, STATUS_DLL_INIT_FAILED) on Windows comes from:
# the SSH (non-interactive) logon, or graftling. Runs on a fresh real Windows Server x64 VM in the user's cloud
# project, by Main from the user's Mac with the user's logged-in gcloud. Modelled on verify-640/steps.zsh (accepted at
# af26c972): the same settings variables, firewall rules, scrub, credential, evidence and D rules, Codex pin and
# provider config; tar over ssh is the only transfer.
#
# SETTINGS: every value of the user's environment is read from ONE local, git-ignored file,
# scripts/verify-643/local/settings.zsh (template: settings.example.zsh; override: VERIFY643_SETTINGS). Each step STOPs,
# naming the variable, when it is missing or empty, and when the file is not git-ignored or is tracked. The steps never
# echo a settings value. The firewall source address is detected at run time and never written to a file.
# LOGIN: the user's gcloud login only. Every gcloud command names --project (and --zone where it applies); no step
# changes any gcloud default; CLOUDSDK_CORE_DISABLE_PROMPTS=1. Only this Task's resources are created or deleted: the
# VM (with its boot disk) and two firewall rules that target only the VM's tag: <VM_NAME>-deny (DENY all ingress from
# 0.0.0.0/0, priority 1000) and <VM_NAME>-ssh (ALLOW tcp:22 from the current public IPv4/32, priority 900), made and
# checked BEFORE the VM exists; their descriptions name Task 643. No other port is opened (no RDP). Every SSH step
# re-checks them and moves the -ssh source to the current address if it changed. Metadata is set on the instance only.
# SSH: a Task key pair in scripts/verify-643/local/ssh/ (git-ignored), put in the instance's ssh-keys metadata.
# CREDENTIALS: at start the script unsets every exported credential-class and provider variable (count printed); every
# started process runs through allow() with an allowlisted environment and no provider credential. The provider key
# exists only in the VM user's environment (step K, by the USER, hidden input, sent on the ssh session's stdin). The
# autologon password of step I is generated ON the VM, never printed, never leaves it (Winlogon reads it there).
# EVIDENCE: scanned on the VM for the key's value AND the autologon password (found: the step fails without printing
# it, nothing is fetched); every settings value and IP address is replaced with a placeholder; fetched with tar over
# gcloud compute ssh into scripts/verify-643/evidence/live/<step>/ (git-ignored), scrubbed again on the Mac.
# DIALOGS: none in any step. K reads the key at a hidden terminal prompt, which is not a dialog.
# THE CASES (definition 1 a-c): Codex 0.172.0, [windows] sandbox = "unelevated", the same provider config, the SAME
# tool command `Set-Content -Path marker-643.txt -Value tool-ran` in a fresh ASCII work dir per case:
#   A              codex exec over SSH, outside graftling (definition a);
#   B              the same in the VM user's interactive console session (definition b), through a scheduled task
#                  (LogonType Interactive, RunLevel Highest: elevated like the SSH session) started from SSH;
#   C interactive  in that same session, a graftling Codex child (AgentControl + CodexDriver, as 640's R1) running the
#                  command (definition c; only when B's tool ran, otherwise refused with the reason);
#   C ssh          the same graftling child over SSH (reproduces 640 on this VM; the direct graftling comparison).
# Every case prints one line per observable, `CASE <case> <observable>: <value>`: the launching process's session id,
# window station, desktop, integrity, elevation, logon type, logon-type SIDs (INTERACTIVE S-1-5-4, NETWORK S-1-5-2,
# BATCH S-1-5-3, SERVICE S-1-5-6, CONSOLE LOGON S-1-2-1) and job membership (with its limit and UI-restriction flags
# when in a job); the rollout's tool calls with their exit codes; the marker file and its content; the wall time;
# optionally the same command through `codex sandbox windows` (OBSERVED, never blocks). The case verdict is
# TOOL-RAN | TOOL-FAILED <exit code> | NO-TOOL-CALL (the step offers a rerun) | STOP <reason>.
# Run one step at a time, in this order:  zsh scripts/verify-643/steps.zsh <STEP>
#   00, V, K, R0, A, I, B, C interactive (only if B's tool ran), C ssh, D       (E <step> refetches evidence any time)
#   00  Preflight, read only, as 640's: settings, gcloud account, project, scrub values distinctive, image family,
#       no Task VM yet, project rules opening 22/3389 (STOP at priority <= 1000), graftling dev contains the candidate,
#       Codex pin, cost per hour (console only). ~20 s.
#   V   Create and provision the VM, as 640's. CLOUD COST STARTS HERE. Task rules first, then the VM; wait for SSH
#       (bound 20 min); upload by tar (drive643.py, provision.ps1, setkey.ps1, autologon.ps1, settings.json without
#       secret, the graftling bundle); provision.ps1 (bound 40 min); fetch out/V. ~25-40 min.
#   K   USER ONLY, in their own terminal: the temporary provider key at a hidden prompt, sent on the ssh session's
#       stdin to setkey.ps1 (stored as the VM user's environment variable). Prints "stored" and the length.
#   R0  One codex exec with a one-line prompt: the answer, provider and model as configured (as 640). ~2-5 min.
#   A   Case A over SSH (bound 20 min). ~2-5 min.
#   I   Interactive logon: on the VM, a new random password for VM_USER (generated there, never printed) and Winlogon
#       automatic logon for VM_USER (autologon.ps1); reboot; wait (bounded) for SSH; then (bounded 5 min) VM_USER
#       must have an Active console session (`query user`). Not established: STOP with the observable and the next
#       commands. UAC, RDP and every security setting stay unchanged; the password stays only in the VM's Winlogon
#       value until D deletes the VM with its disk. ~4-8 min.
#   B   Case B in the console session through the scheduled task; the step waits (bound 15 min) for the task's done
#       file, prints the case lines, removes the task. ~3-6 min.
#   C interactive | C ssh   Case C in the console session (as B) or over SSH. ~3-6 min each.
#   E <step>  Scan, fetch and scrub one step's evidence again (V, R0, A, I, B, C-interactive, C-ssh).
#   D   Delete the VM with all its disks and both Task firewall rules; idempotent; verifies nothing remains (by name,
#       tag and labels) and prints that last; removes the local Task SSH key pair. ~2-4 min. Afterwards the user
#       revokes the temporary provider key.
# Every step prints ready-to-paste next commands and `VERDICT 643 <step>: ...` last.
# Rehearsal knobs (Engineer only): VERIFY643_GCLOUD, VERIFY643_SETTINGS, VERIFY643_EVIDENCE, VERIFY643_GRAFTLING,
# VERIFY643_K_STDIN=1, VERIFY643_WAIT_S / _POLL_S / _REBOOT_S / _SESSION_S / _CASE_S (bounds), VERIFY643_IP. Unset,
# every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
REL=scripts/verify-643/steps.zsh
STEP=${1:-}
ARG=${2:-}
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY643_GRAFTLING:-$HARNESS/graftling}
# graftling dev at 2ee706eb: W0-W6 and Task 639 (Codex on Windows, M17, the Codex parent host opened).
CANDIDATE=2ee706eb749355afc3f73f03a1b0de4cd48da1f2
GBRANCH=dev
CODEX_VERSION=0.172.0   # npm @openai/codex, pinned (latest on 2026-11-24); the provider needs >= 0.164.0
CODEX_MIN=0.164.0
SETTINGS=${VERIFY643_SETTINGS:-$HERE/local/settings.zsh}
KEYDIR=${SETTINGS:h}/ssh
KEY=$KEYDIR/v643-key
LIVE=${VERIFY643_EVIDENCE:-$HERE/evidence/live}
GCLOUD=${VERIFY643_GCLOUD:-$(whence -p gcloud || print -r -- gcloud)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
WAIT_S=${VERIFY643_WAIT_S:-1200}
POLL_S=${VERIFY643_POLL_S:-30}
REBOOT_S=${VERIFY643_REBOOT_S:-60}     # I: pause after the reboot command before polling SSH
SESSION_S=${VERIFY643_SESSION_S:-300}  # I: bound for the console session to appear after SSH answers
CASE_S=${VERIFY643_CASE_S:-900}        # B, C interactive: bound for the scheduled task's done file
STEPNAME="$STEP${ARG:+ $ARG}"
PYTMP=${TMPDIR:-/tmp}
[[ ${PYTMP:A} == ${HARNESS}(|/*) ]] && PYTMP=/tmp
REMOTE='C:\v643'
VPY='C:\v643\venv\Scripts\python.exe'
REQUIRED=(PROJECT ZONE MACHINE_TYPE VCPUS VM_NAME VM_LABELS VM_USER NETWORK IMAGE_FAMILY IMAGE_PROJECT DISK_GB
          PROVIDER_ID PROVIDER_NAME BASE_URL WIRE_API MODEL KEY_ENV
          PRICE_VM_USD_H PRICE_WINLIC_USD_VCPU_H PRICE_DISK_USD_GB_MONTH PRICE_IP_USD_H EST_CURRENCY EST_RATE BUDGET)

say() { print -r -- "== $*"; }
is_cred() {  # graftling's is_credential_name, restated
  local name=${(U)1} part
  [[ $name == GIT_CONFIG_KEY_<-> ]] && return 1
  for part in ${(s:_:)name}; do [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && return 0; done
  return 1
}
scrub_env() {
  local k; local -a removed=()
  for k in ${(k)parameters[(R)*export*]}; do
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == OPENAI_* || $k == CODEX_* || $k == CLAUDE_CODE_USE_* || $k == *_BASE_URL || $k == GRAFTLING_CONNECTION ]]; then
      unset $k; removed+=$k
    fi
  done
  # A count only: the names would show which providers this environment is set up for.
  print -r -- "scrubbed at start: ${#removed} credential-class or provider variable(s) removed (names not shown)"
}
scrub_env
APATH=${GCLOUD:h}:${GIT:h}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
# Run "$@" with only the allowlisted variables.
allow() {
  local -a extra=()
  [[ -n ${SSH_AUTH_SOCK:-} ]] && extra+=SSH_AUTH_SOCK=$SSH_AUTH_SOCK
  [[ -n ${CLOUDSDK_CONFIG:-} ]] && extra+=CLOUDSDK_CONFIG=$CLOUDSDK_CONFIG
  [[ -n ${CLOUDSDK_PYTHON:-} ]] && extra+=CLOUDSDK_PYTHON=$CLOUDSDK_PYTHON
  /usr/bin/env -i HOME=$HOME USER=${USER:-} LOGNAME=${LOGNAME:-${USER:-}} PATH=$APATH TERM=${TERM:-dumb} \
    TMPDIR=$PYTMP LANG=en_US.UTF-8 CLOUDSDK_CORE_DISABLE_PROMPTS=1 $extra "$@"
}
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 643 $STEPNAME: STOP"; exit 1; }
WORK=$(mktemp -d $PYTMP/verify643.XXXXXX)
trap 'rm -rf $WORK' EXIT

# --- settings ----------------------------------------------------------------------------------------------------
load_settings() {
  [[ -f $SETTINGS ]] || stop "no settings file at scripts/verify-643/local/settings.zsh (copy settings.example.zsh there and fill it in)"
  allow $GIT -C $WT check-ignore -q -- $SETTINGS 2> /dev/null \
    || stop "the settings file is not git-ignored here (it must sit under scripts/verify-643/local/); nothing done"
  allow $GIT -C $WT ls-files --error-unmatch -- $SETTINGS > /dev/null 2>&1 \
    && stop "the settings file is tracked by git; remove it from the index first (git rm --cached); nothing done"
  local name
  for name in $REQUIRED; do typeset -g $name=; done
  source $SETTINGS || stop "the settings file did not load"
  for name in $REQUIRED; do [[ -n ${(P)name} ]] || stop "settings variable $name is missing or empty"; done
  [[ $VM_NAME == [a-z]([-a-z0-9](#c0,61)[a-z0-9]|) ]] || stop "settings variable VM_NAME is not a valid instance name"
  [[ $BASE_URL == https://* ]] || stop "settings variable BASE_URL is not an https URL"
  [[ $KEY_ENV == [A-Za-z_][A-Za-z0-9_]# ]] || stop "settings variable KEY_ENV is not an environment variable name"
  (( ${#VM_USER} <= 20 )) || stop "settings variable VM_USER is longer than 20 characters"
  REGION=${ZONE%-*}
  FW=$VM_NAME-ssh     # Task rule: ALLOW tcp:22 from the current public IPv4/32, priority 900, target tag VM_NAME
  FWD=$VM_NAME-deny   # Task rule: DENY all from 0.0.0.0/0, priority 1000, target tag VM_NAME
  TARGET=$VM_USER@$VM_NAME
}
# STOP, naming only the variable, when a value the evidence scrub would replace is shorter than 4 characters or occurs
# (any case) in the committed drive643.py or steps.zsh: such a value is ordinary text and would garble the evidence.
check_scrub_values() {
  local host=${${BASE_URL#*://}%%/*} one
  local -a checks=(PROJECT $PROJECT ZONE $ZONE ZONE $REGION VM_NAME $VM_NAME MACHINE_TYPE $MACHINE_TYPE
                   PROVIDER_ID $PROVIDER_ID PROVIDER_NAME $PROVIDER_NAME BASE_URL $BASE_URL BASE_URL $host MODEL $MODEL
                   KEY_ENV $KEY_ENV)
  for one in ${(s:,:)VM_LABELS}; do checks+=(VM_LABELS ${one#*=}); done
  local bad=$(allow $PY -I -c 'import sys
text = (open(sys.argv[1], encoding="utf-8").read() + open(sys.argv[2], encoding="utf-8").read()).lower()
a = sys.argv[3:]
bad = []
for name, value in zip(a[::2], a[1::2]):
    if (len(value) < 4 or value.lower() in text) and name not in bad:
        bad.append(name)
print(" ".join(bad))' $HERE/vm/drive643.py $THIS $checks)
  [[ -z $bad ]] || stop "settings variable(s) ${bad} hold ordinary text (shorter than 4 characters, or found in drive643.py or steps.zsh); the evidence scrub would garble the evidence. Choose a more distinctive value"
  print -r -- "PASS: every value the evidence scrub replaces is distinctive (4+ characters, absent from drive643.py and steps.zsh)"
}
# A JSON list of [placeholder, value] pairs: every settings value and derived form, plus the active account.
scrub_values() {
  local account=$(allow $GCLOUD auth list --filter=status:ACTIVE --format='value(account)' --project=$PROJECT 2> /dev/null | head -1)
  local host=${${BASE_URL#*://}%%/*}
  local -a labels=(${(s:,:)VM_LABELS}) pairs=()
  local one
  # Not the network name or label keys: they are generic words (a scrub of them garbles JSON keys and text).
  pairs=('<PROJECT>' $PROJECT '<ZONE>' $ZONE '<REGION>' $REGION '<VM_NAME>' $VM_NAME '<VM_NAME>' ${VM_NAME[1,15]}
         '<MACHINE_TYPE>' $MACHINE_TYPE '<PROVIDER_ID>' $PROVIDER_ID '<PROVIDER_NAME>' $PROVIDER_NAME
         '<BASE_URL>' $BASE_URL '<BASE_URL>' ${BASE_URL%/} '<BASE_URL_HOST>' $host '<MODEL>' $MODEL '<KEY_ENV>' $KEY_ENV)
  for one in $labels; do pairs+=('<VM_LABEL>' ${one#*=}); done
  [[ -n $account ]] && pairs+=('<ACCOUNT>' $account)
  allow $PY -I -c 'import json, sys; a = sys.argv[1:]; print(json.dumps([[a[i], a[i + 1]] for i in range(0, len(a), 2) if a[i + 1]]))' $pairs
}
vm_settings() {  # settings.json for the VM: the provider, the pins and the scrub pairs (no secret)
  allow $PY -I -c 'import json, sys
p = dict(zip(["id", "name", "base_url", "wire_api", "model", "key_env"], sys.argv[1:7]))
print(json.dumps({"provider": p, "codex_version": sys.argv[7], "candidate": sys.argv[8], "scrub": json.loads(sys.argv[9])}))' \
    $PROVIDER_ID $PROVIDER_NAME $BASE_URL $WIRE_API $MODEL $KEY_ENV $CODEX_VERSION $CANDIDATE "$(scrub_values)"
}

# --- gcloud ------------------------------------------------------------------------------------------------------
gc() { allow $GCLOUD "$@"; }
# gc_or_stop <label> <args...>: run gcloud with its output in $WORK/gc.out; on failure print gcloud's own error
# verbatim and STOP. Always called in the main shell (never in $(...) or a pipe), so the STOP ends the step.
gc_or_stop() {
  local label=$1; shift
  gc "$@" > $WORK/gc.out 2> $WORK/gc.err && return 0
  print -r -- "gcloud failed ($label); its own error, verbatim:"
  sed 's/^/  | /' $WORK/gc.err
  stop "$label failed; see gcloud's error above. Nothing else was done after it. If anything was created, run: zsh $REL D"
}
SSHF=()
ssh_flags() {
  SSHF=(--project=$PROJECT --zone=$ZONE --ssh-key-file=$KEY --strict-host-key-checking=no --quiet
        --ssh-flag=-oBatchMode=yes --ssh-flag=-oConnectTimeout=20 --ssh-flag=-oServerAliveInterval=30)
}
rsh() { gc compute ssh $TARGET $SSHF --command="$1"; }
# bounded <seconds> <cmd...>: run it, wait at most <seconds>, then end it (status 124).
bounded() {
  local limit=$1 pid start=$SECONDS; shift
  "$@" &
  pid=$!
  while kill -0 $pid 2> /dev/null; do
    if (( SECONDS - start >= limit )); then
      kill $pid 2> /dev/null; sleep 3; kill -9 $pid 2> /dev/null; wait $pid 2> /dev/null
      print -r -- "(bound of ${limit}s reached; the remote command was ended from this side)"
      return 124
    fi
    sleep 2
  done
  wait $pid
}
instance_state() {  # RUNNING/TERMINATED/... or empty when absent; ERR on a failed query
  local out
  out=$(gc compute instances list --project=$PROJECT --filter="name=$VM_NAME AND zone:$ZONE" --format='value(status)' 2> $WORK/list.err) \
    || { print -r -- ERR; return 0; }
  print -r -- ${out%%$'\n'*}
}
# Existing rules (not this Task's) on NETWORK that open tcp:<port> to 0.0.0.0/0 for this VM (no target, or its tag, or
# a service-account target): "<name> <priority>" per line; "ERR <text>" when the list fails.
open_rules() {
  gc compute firewall-rules list --project=$PROJECT --format=json > $WORK/fw.json 2> $WORK/fw.err \
    || { print -r -- "ERR $(<$WORK/fw.err)"; return 0; }
  allow $PY -I -c 'import json, sys
path, net, port, tag, *ours = sys.argv[1:]
def opens(rule):
    for allowed in rule.get("allowed", []):
        if allowed.get("IPProtocol") not in ("tcp", "all"):
            continue
        for item in allowed.get("ports") or ["0-65535"]:
            low, _, high = item.partition("-")
            if int(low) <= int(port) <= int(high or low):
                return True
    return False
for rule in json.load(open(path)):
    if (rule.get("name") not in ours and rule.get("network", "").rsplit("/", 1)[-1] == net
            and rule.get("direction", "INGRESS") == "INGRESS" and not rule.get("disabled")
            and "0.0.0.0/0" in rule.get("sourceRanges", [])
            and (not rule.get("targetTags") or tag in rule.get("targetTags", [])) and opens(rule)):
        print(rule["name"], rule.get("priority", 1000))' $WORK/fw.json $NETWORK $1 $VM_NAME $FW $FWD
}
# guard_open_rules: print the project's rules that open 22/3389 to everyone with their priorities; STOP if one has a
# priority <= 1000 (the Task deny at 1000 would then not take precedence).
guard_open_rules() {
  local port lines one
  local -a low=()
  for port in 22 3389; do
    lines=$(open_rules $port)
    [[ $lines == ERR* ]] && stop "firewall-rules list failed: ${lines#ERR }"
    if [[ -n $lines ]]; then
      print -r -- "NOTE: project rule(s) opening tcp:$port to everyone (name priority): ${(j:, :)${(f)lines}}; not changed by this Task"
      for one in ${(f)lines}; do (( ${${(z)one}[2]} <= 1000 )) && low+=${${(z)one}[1]}; done
    else
      print -r -- "PASS: no project rule opens tcp:$port to everyone"
    fi
  done
  (( ${#low} == 0 )) || stop "project rule(s) ${(j:, :)low} open SSH/RDP to everyone at priority <= 1000, so the Task deny rule (priority 1000) would not take precedence; nothing created. The user decides (this Task never changes project rules)"
  print -r -- "PASS: every project rule opening SSH/RDP to everyone has a priority above 1000; the Task deny rule (1000) takes precedence"
}
# check_rule <name> <deny|ssh> <ip>: OK | SOURCE (only the ssh source differs) | ABSENT | BAD <reason>. Never prints ip.
check_rule() {
  gc compute firewall-rules describe $1 --project=$PROJECT --format=json > $WORK/rule.json 2> /dev/null || { print -r -- ABSENT; return 0; }
  allow $PY -I -c 'import json, sys
r = json.load(open(sys.argv[1])); kind, net, tag, ip = sys.argv[2:6]
bad = []
if r.get("disabled"): bad.append("disabled")
if r.get("direction", "INGRESS") != "INGRESS": bad.append("not INGRESS")
if r.get("network", "").rsplit("/", 1)[-1] != net: bad.append("other network")
if r.get("targetTags") != [tag]: bad.append("target is not exactly the VM tag")
if kind == "deny":
    if r.get("priority") != 1000: bad.append("priority not 1000")
    if r.get("sourceRanges") != ["0.0.0.0/0"]: bad.append("source not 0.0.0.0/0")
    if [d.get("IPProtocol") for d in r.get("denied", [])] != ["all"] or r.get("allowed"): bad.append("not DENY all")
else:
    if r.get("priority") != 900: bad.append("priority not 900")
    if r.get("allowed") != [{"IPProtocol": "tcp", "ports": ["22"]}] or r.get("denied"): bad.append("not ALLOW tcp:22")
print("BAD " + ", ".join(bad) if bad else ("SOURCE" if kind == "ssh" and r.get("sourceRanges") != [ip + "/32"] else "OK"))' \
    $WORK/rule.json $2 $NETWORK $VM_NAME $3
}
# ensure_rules <create|check>: the two Task rules exist, are enabled and as specified, and the ssh rule's source is the
# current public IPv4 (updated when it changed; the address is never printed). <create> (V) makes missing rules.
ensure_rules() {
  local ip=$(my_ip) state
  [[ -n $ip ]] || stop "the current public IPv4 could not be found through Google's DNS (dig); nothing changed"
  state=$(check_rule $FWD deny $ip)
  if [[ $state == ABSENT && $1 == create ]]; then
    gc_or_stop "Task deny rule" compute firewall-rules create $FWD --project=$PROJECT --network=$NETWORK --direction=INGRESS \
      --action=DENY --rules=all --source-ranges=0.0.0.0/0 --target-tags=$VM_NAME --priority=1000 \
      --description='Task 643: deny all ingress to the Task VM (deleted by D)' --format=none
    print -r -- "PASS: created <VM_NAME>-deny (DENY all from everyone, priority 1000, only this VM's tag)"
    state=$(check_rule $FWD deny $ip)
  fi
  [[ $state == ABSENT ]] && stop "the Task firewall rules are missing; run: zsh $REL V   (or delete everything: zsh $REL D)"
  [[ $state == OK ]] || stop "<VM_NAME>-deny is not as specified (${state#BAD }); nothing else done. Delete with: zsh $REL D"
  state=$(check_rule $FW ssh $ip)
  if [[ $state == ABSENT && $1 == create ]]; then
    gc_or_stop "Task ssh rule" compute firewall-rules create $FW --project=$PROJECT --network=$NETWORK --direction=INGRESS \
      --action=ALLOW --rules=tcp:22 --source-ranges=$ip/32 --target-tags=$VM_NAME --priority=900 \
      --description='Task 643: SSH from the user (deleted by D)' --format=none
    print -r -- "PASS: created <VM_NAME>-ssh (ALLOW tcp:22 from the current public IPv4 only, priority 900, only this VM's tag)"
    state=$(check_rule $FW ssh $ip)
  fi
  if [[ $state == SOURCE ]]; then
    gc_or_stop "Task ssh rule source update" compute firewall-rules update $FW --project=$PROJECT --source-ranges=$ip/32 --format=none
    print -r -- "NOTE: <VM_NAME>-ssh's source was not the current public IPv4; updated (address not shown)"
    state=$(check_rule $FW ssh $ip)
  fi
  unset ip
  [[ $state == ABSENT ]] && stop "the Task firewall rules are missing; run: zsh $REL V   (or delete everything: zsh $REL D)"
  [[ $state == OK ]] || stop "<VM_NAME>-ssh is not as specified (${state#BAD }); nothing else done. Delete with: zsh $REL D"
  print -r -- "PASS: Task firewall rules in place and enabled: <VM_NAME>-deny (DENY all, 1000) and <VM_NAME>-ssh (tcp:22 from the current public IPv4 only, 900), both only for this VM's tag"
}
my_ip() {  # the current public IPv4, through Google's DNS; never printed
  if [[ -n ${VERIFY643_IP:-} ]]; then print -r -- $VERIFY643_IP; return 0; fi
  local out=$(allow dig +short -4 TXT o-o.myaddr.l.google.com @ns1.google.com 2> /dev/null | tr -d '"' | head -1)
  [[ $out == <->.<->.<->.<-> ]] && print -r -- $out
}

# --- graftling bundle --------------------------------------------------------------------------------------------
make_bundle() {  # <file>: a bundle of graftling dev (contains the candidate); verified
  [[ -d $GRAFT ]] || stop "no graftling clone at $GRAFT"
  allow $GIT -C $GRAFT merge-base --is-ancestor $CANDIDATE refs/heads/$GBRANCH 2> /dev/null \
    || stop "graftling $GBRANCH does not contain the candidate ${CANDIDATE[1,12]}"
  allow $GIT -C $GRAFT bundle create -q $1 refs/heads/$GBRANCH 2> $WORK/bundle.err || stop "git bundle create failed: $(<$WORK/bundle.err)"
  allow $GIT -C $GRAFT bundle verify -q $1 > /dev/null 2>&1 || stop "the bundle does not verify"
  print -r -- "PASS: bundle of graftling $GBRANCH $(allow $GIT -C $GRAFT rev-parse --short refs/heads/$GBRANCH) made and verified; it contains the candidate ${CANDIDATE[1,12]} (the VM checks out the candidate)"
}

# --- evidence ----------------------------------------------------------------------------------------------------
# fetch <step>: scan on the VM (key: fail, never printed; values and IPs replaced; it prints the file count), tar over
# ssh to evidence/live/<step> (the extracted count must equal the VM's), scrub again on the Mac. Sets FETCHED (PASS/FAIL text).
FETCHED=
fetch() {
  local step=$1 dest=$LIVE/$1 out
  say "evidence of $step: scan on the VM, fetch, scrub on the Mac"
  out=$(bounded 600 rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive643.py scan $step" 2>&1)
  print -r -- $out | grep -E '^SCAN ' | sed 's/^/  /'
  if [[ $out != *"SCAN PASS"* ]]; then
    FETCHED="FAIL (the VM-side scan did not pass; nothing was fetched)"; return 1
  fi
  mkdir -p $LIVE
  if [[ -e $dest ]]; then
    local prev=$dest-prev-$(date +%Y%m%d%H%M%S); mv $dest $prev; print -r -- "  an earlier fetch of $step kept as ${prev:t}"
  fi
  local -a sl=(${(M)${(f)out}:#SCAN PASS*})
  local want=${${${sl[-1]:-}##*files }%%[^0-9]#}   # the VM prints CRLF over ssh
  [[ $want == <-> ]] || { FETCHED="FAIL (the VM-side scan printed no file count)"; return 1; }
  print -r -- "  \$ gcloud compute ssh ... --command=\"tar -cf - -C C:/v643/out $step\" | tar -xf - -C evidence/live   (Windows' own tar.exe)"
  rsh "tar -cf - -C C:/v643/out $step" 2> $WORK/tar.err | allow tar -xf - -C $LIVE 2>> $WORK/tar.err \
    || { sed 's/^/  | /' $WORK/tar.err; FETCHED="FAIL (fetch failed)"; return 1; }
  [[ -d $dest ]] || { FETCHED="FAIL (no $step directory arrived)"; return 1; }
  local got=$(find $dest -type f | wc -l | tr -d ' ')
  # The Mac pass runs on whatever arrived, before the count verdict, so a partial fetch is scrubbed too.
  [[ -f $WORK/console.txt ]] && cp $WORK/console.txt $dest/mac-console.txt
  scrub_values > $WORK/scrub.json
  out=$(allow env V643_HOME=$WORK $PY -I $HERE/vm/drive643.py scrub $dest $WORK/scrub.json 2>&1)
  print -r -- "  Mac pass: $out"
  [[ $out == SCRUB* ]] || { FETCHED="FAIL (the Mac scrub did not run)"; return 1; }
  [[ $got == $want ]] || { FETCHED="FAIL (the VM counted $want evidence files, $got arrived)"; return 1; }
  print -r -- "  PASS: $got of $want evidence files arrived"
  FETCHED="PASS (evidence/live/$step, $(find $dest -type f | wc -l | tr -d ' ') files; scanned on the VM, scrubbed twice)"
}

next_cmds() { local one; for one in "$@"; do print -r -- "next: zsh $REL $one"; done; }
running_vm() {  # the common start of every SSH step
  load_settings
  ssh_flags
  ensure_rules check
  local st=$(instance_state)
  [[ $st == RUNNING ]] || stop "the Task VM is not running (status: ${st:-absent}); run V first: zsh $REL V"
}
# ssh_answers <bound>: poll until gcloud compute ssh answers (0) or the bound passes (1).
ssh_answers() {
  local start=$SECONDS
  while (( SECONDS - start < $1 )); do
    if bounded 120 rsh "echo v643-ssh-ok" > $WORK/ssh.out 2>&1 && grep -q v643-ssh-ok $WORK/ssh.out; then
      print -r -- "PASS: SSH answers after $((SECONDS - start))s"; return 0
    fi
    print -r -- "  [$(date +%H:%M:%S)] not yet: $(tail -1 $WORK/ssh.out | cut -c1-160)"
    sleep $POLL_S
  done
  return 1
}
# run_case <case> <remote drive643.py arguments> <bound s>: run it on the VM, fetch its evidence, print its CASE lines
# (one per observable) and set CASE_VERDICT (TOOL-RAN | TOOL-FAILED <code> | NO-TOOL-CALL | STOP <reason>).
CASE_VERDICT=
run_case() {
  local label=$1 remote=$2 limit=$3
  print -r -- "\$ gcloud compute ssh ... --command=\"<venv python> C:\\v643\\drive643.py $remote\"   (bound ${limit}s)"
  bounded $limit rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive643.py $remote" 2>&1 | tr -d '\r' | tee $WORK/console.txt
  local result=$(grep -E "^RESULT $label " $WORK/console.txt | tail -1)
  fetch $label || print -r -- "evidence: $FETCHED"
  local -a lines=(${(f)"$(grep -E "^CASE $label " $WORK/console.txt)"})
  print -r -- "--- case $label: one line per observable (${#lines}):"
  print -lr -- $lines | sed 's/^/  /'
  CASE_VERDICT=${result#RESULT $label }
  [[ -n $result ]] || CASE_VERDICT="STOP no RESULT line (the remote run ended early; see the console above)"
}
case_verdict() {  # print the step's verdict (last line); a STOP or failed evidence ends the step with exit 1
  print -r -- "VERDICT 643 $STEPNAME: $CASE_VERDICT (evidence ${FETCHED%% *})"
  [[ $CASE_VERDICT != STOP* && $FETCHED == PASS* ]] || exit 1
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: gcloud (account not shown). Dialog: none."
  print -r -- "PASS: run by zsh $ZSH_VERSION"
  load_settings
  print -r -- "PASS: settings file is git-ignored and untracked; variables read (names only): ${(j:, :)REQUIRED}"
  print -r -- "gcloud: $(gc version --project=$PROJECT 2> /dev/null | head -1) | path: $GCLOUD | TMPDIR for started processes: $PYTMP"
  local acct=$(gc auth list --filter=status:ACTIVE --format='value(account)' --project=$PROJECT 2> /dev/null | head -1)
  [[ -n $acct ]] && print -r -- "PASS: gcloud has an active account (not shown)" \
    || stop "gcloud has no active account; the user logs in with: gcloud auth login   then  zsh $REL 00"
  gc_or_stop "project describe" projects describe $PROJECT --project=$PROJECT --format='value(lifecycleState)'
  local life=$(<$WORK/gc.out)
  [[ $life == ACTIVE ]] && print -r -- "PASS: the project is reachable and ACTIVE" || stop "the project state is '$life', not ACTIVE"
  check_scrub_values
  # A read of the PUBLIC image project (its --project names that project; image names are public).
  gc_or_stop "image lookup" compute images describe-from-family $IMAGE_FAMILY --project=$IMAGE_PROJECT --format='value(name,family,architecture)'
  local -a outl=("${(@f)$(<$WORK/gc.out)}")
  local line=${outl[1]:-}
  local -a img=("${(@ps:\t:)line}")
  if [[ ${img[2]:-} != $IMAGE_FAMILY || ${img[3]:-} != X86_64 ]]; then
    print -r -- "gcloud's output (name, family, architecture), raw:"; sed 's/^/  | /' $WORK/gc.out
    stop "the image family does not resolve to an X86_64 image of exactly that family"
  fi
  print -r -- "PASS: the Windows image family resolves to ${img[1]} (family as set, X86_64)"
  local st=$(instance_state)
  [[ $st == ERR ]] && { sed 's/^/  | /' $WORK/list.err; stop "instances list failed"; }
  local vmstate=absent
  if [[ -n $st ]]; then
    vmstate=$st; print -r -- "NOTE: the Task VM already exists (status $st); V resumes provisioning on it, D deletes it"
  else
    print -r -- "PASS: no VM of this Task exists yet"
  fi
  guard_open_rules
  local r1=$(check_rule $FWD deny x) r2=$(check_rule $FW ssh x)
  print -r -- "Task firewall rules now: <VM_NAME>-deny ${${r1/OK/present}/ABSENT/absent}, <VM_NAME>-ssh ${${${r2/SOURCE/present}/OK/present}/ABSENT/absent}; V creates missing ones before the VM, D deletes both"
  make_bundle $WORK/check.bundle
  allow $PY -I -c 'import sys; t = lambda v: tuple(map(int, v.split("."))); sys.exit(0 if t(sys.argv[1]) >= t(sys.argv[2]) else 1)' $CODEX_VERSION $CODEX_MIN \
    && print -r -- "PASS: Codex pin $CODEX_VERSION >= $CODEX_MIN" || stop "Codex pin $CODEX_VERSION is below $CODEX_MIN"
  [[ -f $KEY ]] && print -r -- "NOTE: the Task SSH key already exists (V reuses it)" || print -r -- "PASS: no Task SSH key yet (V creates one under local/ssh)"
  allow $PY -I -c 'import sys
vm, lic, vcpu, disk, gb, ip, rate, budget = map(float, sys.argv[1:9])
usd = vm + lic * vcpu + disk * gb / 730 + ip
print(f"cost estimate (console only): {usd * rate:.0f} {sys.argv[9]}/hour (USD {usd:.3f}/h: VM, Windows licence, disk, IP); the budget covers about {budget / (usd * rate):.0f} h of VM time")' \
    $PRICE_VM_USD_H $PRICE_WINLIC_USD_VCPU_H $VCPUS $PRICE_DISK_USD_GB_MONTH $DISK_GB $PRICE_IP_USD_H $EST_RATE $BUDGET $EST_CURRENCY
  if [[ $vmstate == absent ]]; then next_cmds V; else next_cmds V D; fi
  print -r -- "VERDICT 643 00: PASS (Task VM: $vmstate)"
  ;;
V)
  say "[V] Create and provision the VM. CLOUD COST STARTS HERE (until D). Login: gcloud. Dialog: none."
  load_settings
  ssh_flags
  check_scrub_values
  mkdir -p $KEYDIR $LIVE
  if [[ ! -f $KEY ]]; then
    allow ssh-keygen -q -t ed25519 -N '' -C v643 -f $KEY || stop "ssh-keygen failed"
    print -r -- "PASS: Task SSH key pair created under local/ssh (git-ignored)"
  fi
  local st=$(instance_state)
  [[ $st == ERR ]] && { sed 's/^/  | /' $WORK/list.err; stop "instances list failed"; }
  # The Task rules exist and are enabled BEFORE the VM exists, so it is never reachable from everyone.
  guard_open_rules
  ensure_rules create
  if [[ -z $st ]]; then
    print -r -- "$VM_USER:$(<$KEY.pub)" > $WORK/ssh-keys
    print -r -- 'googet -noconfirm=true install google-compute-engine-ssh' > $WORK/sysprep.cmd
    print -r -- "\$ gcloud compute instances create <VM_NAME> --project=<PROJECT> --zone=<ZONE> (image family, machine type, disk, labels, tag, instance metadata from settings)"
    gc_or_stop "VM creation" compute instances create $VM_NAME --project=$PROJECT --zone=$ZONE \
      --machine-type=$MACHINE_TYPE --image-family=$IMAGE_FAMILY --image-project=$IMAGE_PROJECT \
      --boot-disk-size=${DISK_GB}GB --boot-disk-type=pd-balanced --boot-disk-auto-delete --network=$NETWORK \
      --labels=$VM_LABELS --tags=$VM_NAME \
      --metadata=enable-windows-ssh=TRUE,block-project-ssh-keys=TRUE,enable-oslogin=FALSE \
      --metadata-from-file=ssh-keys=$WORK/ssh-keys,sysprep-specialize-script-cmd=$WORK/sysprep.cmd \
      --format='value(status)'
    sed 's/^/  status: /' $WORK/gc.out
    print -r -- "PASS: VM created (labels and tag from settings; instance metadata only)"
  else
    print -r -- "NOTE: the Task VM exists (status $st); provisioning resumes on it"
    [[ $st == RUNNING ]] || gc_or_stop "VM start" compute instances start $VM_NAME --project=$PROJECT --zone=$ZONE --format=none
  fi
  print -r -- "waiting for gcloud compute ssh to answer (bound ${WAIT_S}s, poll ${POLL_S}s; Windows first boot and sysprep take ~5-10 min)"
  local start=$SECONDS answered=no
  while (( SECONDS - start < WAIT_S )); do
    if bounded 120 rsh "echo v643-ssh-ok" > $WORK/ssh.out 2>&1 && grep -q v643-ssh-ok $WORK/ssh.out; then answered=yes; break; fi
    print -r -- "  [$(date +%H:%M:%S)] not yet: $(tail -1 $WORK/ssh.out | cut -c1-160)"
    sleep $POLL_S
  done
  [[ $answered == yes ]] || stop "no SSH answer within ${WAIT_S}s (last: $(tail -2 $WORK/ssh.out)). Retry: zsh $REL V   or delete: zsh $REL D"
  print -r -- "PASS: SSH answers after $((SECONDS - start))s"
  mkdir -p $WORK/v643
  cp $HERE/vm/drive643.py $HERE/vm/provision.ps1 $HERE/vm/setkey.ps1 $HERE/vm/autologon.ps1 $WORK/v643/
  vm_settings > $WORK/v643/settings.json || stop "settings.json for the VM could not be made"
  make_bundle $WORK/v643/graftling.bundle
  # tar over ssh is the only transfer (gcloud compute scp closed its connection on the real VM); files in C:\v643
  # are overwritten on a rerun.
  print -r -- "\$ tar -cf - v643 | gcloud compute ssh <VM_USER>@<VM_NAME> ... --command=\"tar -xf - -C C:/\"   (drive643.py, provision.ps1, setkey.ps1, autologon.ps1, settings.json without secret, graftling.bundle)"
  allow tar -cf - -C $WORK v643 | rsh "tar -xf - -C C:/" > $WORK/up.out 2>&1 || { sed 's/^/  | /' $WORK/up.out; stop "upload failed; retry: zsh $REL V"; }
  print -r -- "PASS: uploaded to C:\\v643"
  say "provisioning on the VM (bound 40 min): Python, Node, Git, Developer Mode, Codex $CODEX_VERSION, graftling ${CANDIDATE[1,12]}, config.toml"
  bounded 2400 rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\provision.ps1" 2>&1 | tee $WORK/console.txt
  grep -q '^PROVISION PASS' $WORK/console.txt || stop "provisioning did not pass (last lines above). Retry: zsh $REL V   or delete: zsh $REL D"
  fetch V || stop "the V evidence: $FETCHED"
  next_cmds K R0 D
  print -r -- "next: K is run by the USER in their own terminal (hidden key input); Main runs R0 after it"
  print -r -- "VERDICT 643 V: PASS (VM provisioned; evidence $FETCHED)"
  ;;
K)
  say "[K] Store the temporary provider key on the VM. USER ONLY, in your own terminal. Login: gcloud. Dialog: none (a hidden prompt)."
  load_settings
  ssh_flags
  ensure_rules check
  [[ -t 0 || ${VERIFY643_K_STDIN:-} == 1 ]] || stop "K reads the key at a hidden terminal prompt; the user runs it in their own terminal: zsh $REL K"
  local st=$(instance_state)
  [[ $st == RUNNING ]] || stop "the Task VM is not running (status: ${st:-absent}); run V first"
  local secret=
  print -n -- "Paste the temporary provider key (hidden), then press Enter: "
  read -rs secret
  print
  [[ -n $secret ]] || stop "nothing was entered; nothing sent"
  [[ $secret != *[[:space:]]* ]] || { secret=; stop "the key contains white space; nothing sent"; }
  print -r -- "sending it on the ssh session's stdin only (not on any command line, not to any file)"
  print -r -- "$secret" | rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\setkey.ps1" > $WORK/k.out 2>&1
  local rc=${pipestatus[2]}
  secret=
  unset secret
  grep -E '^KEY ' $WORK/k.out | sed 's/^/  /'
  [[ $rc == 0 ]] && grep -q '^KEY STORED' $WORK/k.out || { tail -5 $WORK/k.out | grep -v '^KEY' | sed 's/^/  | /'; stop "the key was not stored; run K again"; }
  next_cmds R0
  print -r -- "VERDICT 643 K: PASS (key stored as the VM user's environment variable; R0 proves it with a real call)"
  ;;
R0)
  say "[R0] versions and one real codex exec call (bound 10 min). Login: gcloud. Dialog: none."
  running_vm
  bounded 600 rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive643.py r0" 2>&1 | tr -d '\r' | tee $WORK/console.txt
  local result=$(grep -E "^RESULT R0 " $WORK/console.txt | tail -1)
  fetch R0 || print -r -- "evidence: $FETCHED"
  local -a items=(${(f)"$(grep -E '^ITEM ' $WORK/console.txt)"})
  print -r -- "--- items (${#items}):"; print -lr -- $items | sed 's/^/  /'
  [[ $result == *PASS* ]] && next_cmds A D || next_cmds R0 D
  [[ $result == *STOP* ]] && print -r -- "next: the provider refused or failed: read the raw error above; the user decides (no other model, no proxy)"
  [[ -n $result ]] || result="RESULT R0 FAIL (no RESULT line; the remote run ended early)"
  print -r -- "VERDICT 643 R0: ${${(z)result}[3]} (${result#RESULT R0 }; evidence ${FETCHED%% *})"
  [[ $result == *" PASS"* && $FETCHED == PASS* ]] || exit 1
  ;;
A)
  say "[A] Case a: codex exec over SSH, outside graftling, [windows] sandbox = unelevated (bound 20 min). Login: gcloud. Dialog: none."
  running_vm
  run_case A "case A" 1200
  case $CASE_VERDICT in
    NO-TOOL-CALL*) print -r -- "next: the model made no tool call; rerun A once before going on"; next_cmds A I D ;;
    STOP*) next_cmds A "E A" D ;;
    *) next_cmds I D ;;
  esac
  case_verdict
  ;;
I)
  say "[I] Interactive logon of VM_USER: a random VM-only password, Winlogon automatic logon, reboot, wait, verify the console session. Login: gcloud. Dialog: none."
  running_vm
  print -r -- "\$ gcloud compute ssh ... --command=\"powershell ... -File C:\\v643\\autologon.ps1\"   (the password is generated on the VM and never printed)"
  bounded 300 rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\autologon.ps1" > $WORK/al.out 2>&1
  tr -d '\r' < $WORK/al.out | sed 's/^/  /'
  grep -q '^AUTOLOGON SET' $WORK/al.out || { next_cmds I D; stop "the automatic logon was not configured (see the lines above); nothing rebooted"; }
  print -r -- "\$ gcloud compute ssh ... --command=\"shutdown /r /t 10\"   (reboot, so that Winlogon logs VM_USER on at the console)"
  rsh 'shutdown /r /t 10 /c "Task 643: reboot for the automatic logon"' > $WORK/rb.out 2>&1 \
    || { sed 's/^/  | /' $WORK/rb.out; next_cmds I D; stop "the reboot command failed"; }
  print -r -- "rebooting; first SSH poll in ${REBOOT_S}s (bound ${WAIT_S}s, poll ${POLL_S}s)"
  sleep $REBOOT_S
  ssh_answers $WAIT_S || { next_cmds I D; stop "no SSH answer within ${WAIT_S}s after the reboot (last: $(tail -1 $WORK/ssh.out))"; }
  print -r -- "waiting for VM_USER's Active console session (query user; bound ${SESSION_S}s)"
  local start=$SECONDS found=
  while true; do
    bounded 120 rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive643.py session" 2>&1 | tr -d '\r' > $WORK/session.out
    found=$(grep -E '^SESSION (ACTIVE|NONE)' $WORK/session.out | tail -1)
    [[ $found == 'SESSION ACTIVE'* ]] && break
    (( SECONDS - start >= SESSION_S )) && break
    print -r -- "  [$(date +%H:%M:%S)] not yet: ${found:-no answer}"
    sleep $POLL_S
  done
  grep -E '^SESSION ' $WORK/session.out | sed 's/^/  /'
  cp $WORK/session.out $WORK/console.txt
  fetch I || print -r -- "evidence: $FETCHED"
  if [[ $found != 'SESSION ACTIVE'* ]]; then
    print -r -- "the observable: query user shows no Active console session of VM_USER $((SECONDS - start))s after SSH answered (lines above)"
    next_cmds I D
    stop "the interactive logon was not established (${found:-no session answer}); B and C interactive need it. Retry I once, or delete: zsh $REL D"
  fi
  next_cmds B
  print -r -- "VERDICT 643 I: PASS (VM_USER has an Active console session: ${found#SESSION ACTIVE }; evidence ${FETCHED%% *})"
  [[ $FETCHED == PASS* ]] || exit 1
  ;;
B)
  say "[B] Case b: codex exec in VM_USER's interactive console session (scheduled task, Interactive, Highest; bound $((CASE_S / 60)) min). Login: gcloud. Dialog: none."
  running_vm
  run_case B "schedule B $CASE_S" $((CASE_S + 300))
  case $CASE_VERDICT in
    TOOL-RAN*) next_cmds "C interactive" "C ssh" D ;;
    NO-TOOL-CALL*) print -r -- "next: the model made no tool call; rerun B once before going on"; next_cmds B "C ssh" D ;;
    TOOL-FAILED*) print -r -- "next: C interactive is not run (B's tool did not run; the step would refuse)"; next_cmds "C ssh" D ;;
    *console\ session*) next_cmds I B D ;;
    *) next_cmds B "E B" D ;;
  esac
  case_verdict
  ;;
C)
  [[ $ARG == (interactive|ssh) ]] || { print -r -- "usage: zsh $REL C interactive|ssh"; print -r -- "VERDICT 643 $STEPNAME: STOP"; exit 2; }
  running_vm
  if [[ $ARG == interactive ]]; then
    say "[C interactive] Case c: a graftling Codex child in VM_USER's interactive console session (scheduled task; bound $((CASE_S / 60)) min). Login: gcloud. Dialog: none."
    local bv=$(bounded 120 rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive643.py verdict B" 2>&1 | tr -d '\r' | grep -E '^VERDICT-OF B ' | tail -1)
    bv=${bv#VERDICT-OF B }
    if [[ $bv != TOOL-RAN* ]]; then
      print -r -- "C interactive is required only when case B's tool ran; B's verdict on the VM: ${bv:-none (B has not run)}"
      if [[ $bv == (none|NO-TOOL-CALL*|STOP*|) ]]; then next_cmds B "C ssh" D; else next_cmds "C ssh" D; fi
      stop "C interactive refused: case B's tool did not run (B: ${bv:-not run}); next: zsh $REL C ssh"
    fi
    print -r -- "PASS: case B's tool ran (B: $bv); C interactive goes ahead"
    run_case C-interactive "schedule C-interactive $CASE_S" $((CASE_S + 300))
    case $CASE_VERDICT in
      NO-TOOL-CALL*) print -r -- "next: the model made no tool call; rerun once"; next_cmds "C interactive" "C ssh" D ;;
      STOP*) next_cmds "C interactive" "E C-interactive" "C ssh" D ;;
      *) next_cmds "C ssh" D ;;
    esac
  else
    say "[C ssh] Case c over SSH: a graftling Codex child (as 640's R1) on this VM (bound 20 min). Login: gcloud. Dialog: none."
    run_case C-ssh "case C-ssh" 1200
    case $CASE_VERDICT in
      NO-TOOL-CALL*) print -r -- "next: the model made no tool call; rerun once"; next_cmds "C ssh" D ;;
      STOP*) next_cmds "C ssh" "E C-ssh" D ;;
      *) next_cmds D ;;
    esac
  fi
  case_verdict
  ;;
E)
  [[ $ARG == (V|R0|A|I|B|C-interactive|C-ssh) ]] || { print -r -- "usage: zsh $REL E V|R0|A|I|B|C-interactive|C-ssh"; print -r -- "VERDICT 643 $STEPNAME: STOP"; exit 2; }
  load_settings
  ssh_flags
  ensure_rules check
  say "[E] Scan, fetch and scrub the evidence of $ARG. Login: gcloud. Dialog: none."
  fetch $ARG
  next_cmds D
  print -r -- "VERDICT 643 E $ARG: ${FETCHED%% *} ($FETCHED)"
  [[ $FETCHED == PASS* ]] || exit 1
  ;;
D)
  say "[D] Delete this Task's resources (VM with all disks, both Task firewall rules). Login: gcloud. Dialog: none."
  load_settings
  local st=$(instance_state) bad=0
  [[ $st == ERR ]] && { sed 's/^/  | /' $WORK/list.err; stop "instances list failed; nothing deleted. Retry: zsh $REL D"; }
  if [[ -n $st ]]; then
    print -r -- "\$ gcloud compute instances delete <VM_NAME> --project=<PROJECT> --zone=<ZONE> --delete-disks=all --quiet"
    gc compute instances delete $VM_NAME --project=$PROJECT --zone=$ZONE --delete-disks=all --quiet 2>&1 | sed 's/^/  /'
    (( ${pipestatus[1]} == 0 )) || print -r -- "  (gcloud reported a failure; the verification below decides)"
  else
    print -r -- "no Task VM exists"
  fi
  local rule label
  for rule label in $FW '<VM_NAME>-ssh' $FWD '<VM_NAME>-deny'; do
    if gc compute firewall-rules describe $rule --project=$PROJECT --format='value(name)' > /dev/null 2>&1; then
      print -r -- "\$ gcloud compute firewall-rules delete $label --project=<PROJECT> --quiet"
      gc compute firewall-rules delete $rule --project=$PROJECT --quiet 2>&1 | sed 's/^/  /'
    else
      print -r -- "no Task firewall rule $label exists"
    fi
  done
  say "verification: nothing of this Task remains"
  local -a lf=()
  local one
  for one in ${(s:,:)VM_LABELS}; do lf+="labels.${one%%=*}=${one#*=}"; done
  local inst=$(gc compute instances list --project=$PROJECT --filter="name=$VM_NAME OR (${(j: AND :)lf})" --format='value(name)' 2> $WORK/v.err) || inst="ERR"
  local disks=$(gc compute disks list --project=$PROJECT --filter="name=$VM_NAME OR users~/instances/$VM_NAME\$" --format='value(name)' 2>> $WORK/v.err) || disks="ERR"
  local rules=$(gc compute firewall-rules list --project=$PROJECT --filter="name=$FW OR name=$FWD OR targetTags:$VM_NAME" --format='value(name)' 2>> $WORK/v.err) || rules="ERR"
  [[ -s $WORK/v.err ]] && sed 's/^/  | /' $WORK/v.err
  local -a left=()
  # Counts only: the names come from the settings (the console shows gcloud's own listing above when it failed).
  local -a ni=(${(f)inst}) nd=(${(f)disks}) nr=(${(f)rules})
  (( ${#ni} )) && left+="instances: ${#ni}"
  (( ${#nd} )) && left+="disks: ${#nd}"
  (( ${#nr} )) && left+="firewall rules: ${#nr}"
  if [[ -f $KEY ]]; then rm -f $KEY $KEY.pub && print -r -- "local Task SSH key pair removed"; fi
  print -r -- "reminder: the user now revokes the temporary provider key in the provider's console"
  print -r -- "note: gcloud keeps the VM's host key in ~/.ssh/google_compute_known_hosts (alias compute.<instance id>); harmless after deletion"
  if (( ${#left} )); then
    next_cmds D
    print -r -- "VERDICT 643 D: FAIL (still present, by name/tag/labels: ${(j:; :)left})"
    exit 1
  fi
  print -r -- "VERDICT 643 D: PASS (nothing of this Task remains: 0 instances, 0 disks, 0 firewall rules by name, tag and labels)"
  ;;
*)
  print -r -- "usage: zsh $REL 00|V|K|R0|A|I|B|C interactive|C ssh|E <step>|D"; exit 2 ;;
esac
