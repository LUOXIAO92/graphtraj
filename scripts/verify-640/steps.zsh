#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 640 (W7, part two): real Codex through graftling on a real Windows x64 VM in the user's cloud project, run by
# Main from the user's Mac with the user's logged-in gcloud. Modelled on verify-639/steps.zsh (accepted).
#
# SETTINGS: every value of the user's environment (project, zone, machine type, VM name, labels, network, provider id,
# name, base URL, model, key variable name, prices) is read from ONE local, git-ignored file,
# scripts/verify-640/local/settings.zsh (template: settings.example.zsh; override: VERIFY640_SETTINGS). Each step STOPs,
# naming the variable, when it is missing or empty, and when the file is not git-ignored or is tracked. The steps never
# echo a settings value; gcloud's own output may show some on the console. The firewall source address is detected at
# run time and never written to a file.
# LOGIN: the user's gcloud login only (00 shows that an active account exists, not which). Every gcloud command names
# --project (and --zone where it applies); no step runs `gcloud config set` or changes any gcloud default;
# CLOUDSDK_CORE_DISABLE_PROMPTS=1. Only this Task's resources are created or deleted: the VM (with its boot disk) and,
# when the project has no SSH ingress rule already, one firewall rule <VM_NAME>-ssh. Metadata is set on the instance
# only (enable-windows-ssh, the install of google-compute-engine-ssh at sysprep, block-project-ssh-keys,
# enable-oslogin=FALSE, and this Task's own SSH public key); nothing project-wide is changed.
# SSH: a Task key pair in scripts/verify-640/local/ssh/ (git-ignored), passed with --ssh-key-file; the key is put in
# the instance's ssh-keys metadata at creation, so gcloud does not touch project metadata. gcloud keeps the VM's host
# key in its own ~/.ssh/google_compute_known_hosts (not the user's known_hosts).
# CREDENTIALS: at start the script unsets every exported credential-class variable (a '_'-separated part ending in
# KEY, TOKEN, SECRET(S), PASSWORD or CREDENTIAL(S); so every provider's *_API_KEY) and every ANTHROPIC_*, OPENAI_*,
# CODEX_*, CLAUDE_CODE_USE_*, *_BASE_URL and GRAFTLING_CONNECTION variable, printing how many were removed. Every started process
# runs through allow(): only HOME, USER, LOGNAME, PATH, TERM, TMPDIR, LANG, CLOUDSDK_CORE_DISABLE_PROMPTS and, when
# set, SSH_AUTH_SOCK, CLOUDSDK_CONFIG, CLOUDSDK_PYTHON. The provider key exists only in the VM user's environment:
# step K (the USER, in their own terminal) reads it with hidden input and sends it only on the ssh session's stdin.
# EVIDENCE: VM-side evidence is scanned on the VM for the key's value (found: the step fails without printing it, and
# nothing is fetched) and every settings value and IP address is replaced with a placeholder (<PROJECT>, <MODEL>,
# <BASE_URL>, <IP>, ...); it is fetched with gcloud compute scp into scripts/verify-640/evidence/live/<step>/
# (git-ignored) and scrubbed again on the Mac. Counts of replacements are printed, never values.
# DIALOGS: none in any step (gcloud runs with prompts disabled; no browser or keychain dialog is expected). K reads the
# key at a hidden terminal prompt, which is not a dialog.
# Run one step at a time, in this order:  zsh scripts/verify-640/steps.zsh <STEP>
#   00  Preflight, read only. zsh; settings file present, ignored, untracked, complete (names printed); gcloud version;
#       an active gcloud account; the project is reachable; the Windows image family resolves (x86_64); no VM of this
#       Task exists (else: reported, with D as next); SSH ingress rules of the network (whether the project already
#       opens tcp:22 to everyone); graftling dev contains the candidate and the bundle can be made; the Codex pin is
#       >= 0.164.0; the cost estimate per hour (console only). Login: gcloud. Dialog: none. ~20 s.
#   V   Create and provision the VM. CLOUD COST STARTS HERE. Creates the VM (SSH enabled at boot); if gcloud refuses
#       (billing, quota, policy), prints gcloud's own error and STOPs. If the network has no rule opening tcp:22,
#       creates <VM_NAME>-ssh allowing tcp:22 only from the current public IPv4 (detected through Google's DNS, never
#       printed). Waits (bounded 20 min) until gcloud compute ssh answers; uploads drive640.py, provision.ps1,
#       setkey.ps1, settings.json (no secret) and the graftling bundle; runs provision.ps1 (bounded 40 min); fetches
#       out/V. Login: gcloud. Dialog: none. ~25-40 min.
#   K   USER ONLY, in their own terminal: reads the temporary provider key with hidden input (zsh read -s) and sends
#       it only through the ssh session's stdin to setkey.ps1, which stores it as the VM user's environment variable.
#       Prints only "stored" and the length. Never on a command line, in a step argument, a file, or the evidence.
#       Login: gcloud. Dialog: none (a hidden terminal prompt).
#   R0  On the VM: versions and one `codex exec` with a one-line prompt: the answer, the provider and the model in
#       Codex's rollout equal the configured ones; the provider-reported model is recorded when Codex exposes it. A
#       provider refusal STOPs with the raw error (scrubbed); no other model and no proxy is tried. Then the evidence
#       is scanned, fetched and scrubbed. Login: gcloud. Dialog: none. ~2-5 min.
#   R mxc | R elevated | R unelevated
#       On the VM with [windows] sandbox = <mode> (Codex 0.172 WindowsSandboxModeToml): R1 child create + tool +
#       end; R2 stop (with cmd start /b and Start-Process descendants); R3 takeover after the owner is killed; R4
#       the Codex parent host's real MCP call; R5 the 629 sec. 6 Codex items (pipe identity incl. a caller in
#       Codex's sandbox, a forged same-user caller outside the job and one named-parent caller; job behaviour;
#       process shape; session end at stdin EOF; app-server stdio and graftling's profile under <mode>). Each item
#       prints PASS / FAIL / OBSERVED with its observable. Bounded 75 min. Then scan, fetch, scrub.
#       Login: gcloud. Dialog: none. ~20-45 min per mode. Run `R mxc` and `R elevated` (629 sec. 6 item 8).
#   E <step>
#       Scan, fetch and scrub one step's evidence again (V, R0, R-mxc, R-elevated, R-unelevated). Login: gcloud.
#   D   Delete this Task's resources: the VM with all its disks and the Task firewall rule; runnable alone at any
#       time, idempotent; then verifies that no instance, disk or firewall rule of this Task remains (by name, tag and
#       labels) and prints that last; removes the local Task SSH key pair. Login: gcloud. Dialog: none. ~2-4 min.
#       Afterwards the user revokes the temporary provider key.
# Rehearsal knobs (Engineer only): VERIFY640_GCLOUD (a gcloud stand-in), VERIFY640_SETTINGS (another settings file,
# which must still be git-ignored), VERIFY640_EVIDENCE (evidence root), VERIFY640_GRAFTLING (graftling clone),
# VERIFY640_K_STDIN=1 (K accepts a non-terminal stdin), VERIFY640_WAIT_S / _POLL_S (bounds), VERIFY640_IP (skip the
# DNS lookup). Unset, every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
REL=scripts/verify-640/steps.zsh
STEP=${1:-}
ARG=${2:-}
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY640_GRAFTLING:-$HARNESS/graftling}
# graftling dev at 2ee706eb: W0-W6 and Task 639 (Codex on Windows, M17, the Codex parent host opened).
CANDIDATE=2ee706eb749355afc3f73f03a1b0de4cd48da1f2
GBRANCH=dev
CODEX_VERSION=0.172.0   # npm @openai/codex, pinned (latest on 2026-11-24); the provider needs >= 0.164.0
CODEX_MIN=0.164.0
SETTINGS=${VERIFY640_SETTINGS:-$HERE/local/settings.zsh}
KEYDIR=${SETTINGS:h}/ssh
KEY=$KEYDIR/v640-key
LIVE=${VERIFY640_EVIDENCE:-$HERE/evidence/live}
GCLOUD=${VERIFY640_GCLOUD:-$(whence -p gcloud || print -r -- gcloud)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
WAIT_S=${VERIFY640_WAIT_S:-1200}
POLL_S=${VERIFY640_POLL_S:-30}
PYTMP=${TMPDIR:-/tmp}
[[ ${PYTMP:A} == ${HARNESS}(|/*) ]] && PYTMP=/tmp
REMOTE='C:\v640'
VPY='C:\v640\venv\Scripts\python.exe'
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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 640 $STEP: STOP"; exit 1; }
WORK=$(mktemp -d $PYTMP/verify640.XXXXXX)
trap 'rm -rf $WORK' EXIT

# --- settings ----------------------------------------------------------------------------------------------------
load_settings() {
  [[ -f $SETTINGS ]] || stop "no settings file at scripts/verify-640/local/settings.zsh (copy settings.example.zsh there and fill it in)"
  allow $GIT -C $WT check-ignore -q -- $SETTINGS 2> /dev/null \
    || stop "the settings file is not git-ignored here (it must sit under scripts/verify-640/local/); nothing done"
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
  FW=$VM_NAME-ssh
  TARGET=$VM_USER@$VM_NAME
}
# A JSON list of [placeholder, value] pairs: every settings value and derived form, plus the active account.
scrub_values() {
  local account=$(allow $GCLOUD auth list --filter=status:ACTIVE --format='value(account)' --project=$PROJECT 2> /dev/null | head -1)
  local host=${${BASE_URL#*://}%%/*}
  local -a labels=(${(s:,:)VM_LABELS}) pairs=()
  local one
  pairs=('<PROJECT>' $PROJECT '<ZONE>' $ZONE '<REGION>' $REGION '<VM_NAME>' $VM_NAME '<VM_NAME>' ${VM_NAME[1,15]}
         '<MACHINE_TYPE>' $MACHINE_TYPE '<PROVIDER_ID>' $PROVIDER_ID '<PROVIDER_NAME>' $PROVIDER_NAME
         '<BASE_URL>' $BASE_URL '<BASE_URL>' ${BASE_URL%/} '<BASE_URL_HOST>' $host '<MODEL>' $MODEL '<KEY_ENV>' $KEY_ENV
         '<NETWORK>' $NETWORK)
  for one in $labels; do pairs+=('<VM_LABEL>' ${one#*=} '<VM_LABEL>' ${one%%=*}); done
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
# The network's enabled ingress rules that open tcp:22 to 0.0.0.0/0 for every instance (names only).
open_ssh_rules() {
  gc compute firewall-rules list --project=$PROJECT --format=json > $WORK/fw.json 2> $WORK/fw.err \
    || { print -r -- "ERR $(<$WORK/fw.err)"; return 0; }
  allow $PY -I -c 'import json, sys
net, port = sys.argv[2], sys.argv[3]
def opens(rule):
    for allowed in rule.get("allowed", []):
        if allowed.get("IPProtocol") not in ("tcp", "all"):
            continue
        ports = allowed.get("ports") or ["0-65535"]
        for item in ports:
            low, _, high = item.partition("-")
            if int(low) <= int(port) <= int(high or low):
                return True
    return False
for rule in json.load(open(sys.argv[1])):
    if (rule.get("network", "").rsplit("/", 1)[-1] == net and rule.get("direction") == "INGRESS" and not rule.get("disabled")
            and "0.0.0.0/0" in rule.get("sourceRanges", []) and not rule.get("targetTags") and not rule.get("targetServiceAccounts")
            and opens(rule)):
        print(rule["name"])' $WORK/fw.json $NETWORK $1
}
my_ip() {  # the current public IPv4, through Google's DNS; never printed
  if [[ -n ${VERIFY640_IP:-} ]]; then print -r -- $VERIFY640_IP; return 0; fi
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
# fetch <step>: scan on the VM (key: fail, never printed; values and IPs replaced), scp to evidence/live/<step>,
# scrub again on the Mac. Sets FETCHED (PASS/FAIL text).
FETCHED=
fetch() {
  local step=$1 dest=$LIVE/$1 out
  say "evidence of $step: scan on the VM, fetch, scrub on the Mac"
  out=$(bounded 600 rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive640.py scan $step" 2>&1)
  print -r -- $out | grep -E '^SCAN ' | sed 's/^/  /'
  if [[ $out != *"SCAN PASS"* ]]; then
    FETCHED="FAIL (the VM-side scan did not pass; nothing was fetched)"; return 1
  fi
  mkdir -p $LIVE
  if [[ -e $dest ]]; then
    local prev=$dest-prev-$(date +%Y%m%d%H%M%S); mv $dest $prev; print -r -- "  an earlier fetch of $step kept as ${prev:t}"
  fi
  if ! gc compute scp --recurse $SSHF[1,5] "$TARGET:C:/v640/out/$step" $LIVE/ > $WORK/scp.out 2>&1; then
    print -r -- "  gcloud compute scp failed; its output:"; sed 's/^/  | /' $WORK/scp.out
    print -r -- "  trying the same through ssh with tar (Windows' own tar.exe)"
    mkdir -p $dest
    rsh "tar -cf - -C C:/v640/out $step" 2> $WORK/tar.err | tar -xf - -C $LIVE 2>> $WORK/tar.err \
      || { sed 's/^/  | /' $WORK/tar.err; FETCHED="FAIL (fetch failed)"; return 1; }
  fi
  [[ -d $dest ]] || { FETCHED="FAIL (no $step directory arrived)"; return 1; }
  [[ -f $WORK/console.txt ]] && cp $WORK/console.txt $dest/mac-console.txt
  scrub_values > $WORK/scrub.json
  out=$(allow env V640_HOME=$WORK $PY -I $HERE/vm/drive640.py scrub $dest $WORK/scrub.json 2>&1)
  print -r -- "  Mac pass: $out"
  [[ $out == SCRUB* ]] || { FETCHED="FAIL (the Mac scrub did not run)"; return 1; }
  FETCHED="PASS (evidence/live/$step, $(find $dest -type f | wc -l | tr -d ' ') files; scanned on the VM, scrubbed twice)"
}

next_cmds() { local one; for one in "$@"; do print -r -- "next: zsh $REL $one"; done; }

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
  gc_or_stop "image lookup" compute images list --project=$PROJECT --filter="family=$IMAGE_FAMILY" --format='value(name,architecture,selfLink)'
  local img=$(<$WORK/gc.out)
  local -a imgs=(${(f)img})
  local hit=${${(M)imgs:#*/projects/$IMAGE_PROJECT/*}[1]:-}
  [[ -n $hit ]] || stop "the image family does not resolve in the image project (images list returned ${#imgs} line(s))"
  [[ $hit == *X86_64* ]] && print -r -- "PASS: the Windows image family resolves to an X86_64 image (${${(z)hit}[1]})" \
    || print -r -- "NOTE: the image's architecture field is not X86_64 here: ${${(z)hit}[2]:-unset}"
  local st=$(instance_state)
  [[ $st == ERR ]] && { sed 's/^/  | /' $WORK/list.err; stop "instances list failed"; }
  local vmstate=absent
  if [[ -n $st ]]; then
    vmstate=$st; print -r -- "NOTE: the Task VM already exists (status $st); V resumes provisioning on it, D deletes it"
  else
    print -r -- "PASS: no VM of this Task exists yet"
  fi
  local opens=$(open_ssh_rules 22) rdp=$(open_ssh_rules 3389)
  [[ $opens == ERR* ]] && stop "firewall-rules list failed: ${opens#ERR }"
  if [[ -n $opens ]]; then
    print -r -- "NOTE: the network already opens tcp:22 to everyone through rule(s): ${(f)opens}. V creates no Task rule; the VM accepts only this Task's key (the project's rules are not changed)."
  else
    print -r -- "PASS: no rule opens tcp:22 to everyone; V creates <VM_NAME>-ssh (tcp:22 from the current public IPv4 only; D deletes it)"
  fi
  [[ -n $rdp ]] && print -r -- "NOTE: rule(s) ${(f)rdp} open tcp:3389 to everyone; the steps set no Windows password, so RDP has no usable login"
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
  print -r -- "VERDICT 640 00: PASS (Task VM: $vmstate)"
  ;;
V)
  say "[V] Create and provision the VM. CLOUD COST STARTS HERE (until D). Login: gcloud. Dialog: none."
  load_settings
  ssh_flags
  mkdir -p $KEYDIR $LIVE
  if [[ ! -f $KEY ]]; then
    allow ssh-keygen -q -t ed25519 -N '' -C v640 -f $KEY || stop "ssh-keygen failed"
    print -r -- "PASS: Task SSH key pair created under local/ssh (git-ignored)"
  fi
  local st=$(instance_state)
  [[ $st == ERR ]] && { sed 's/^/  | /' $WORK/list.err; stop "instances list failed"; }
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
  local opens=$(open_ssh_rules 22)
  [[ $opens == ERR* ]] && stop "firewall-rules list failed: ${opens#ERR }; the VM exists, delete it with: zsh $REL D"
  if [[ -n $opens ]]; then
    print -r -- "NOTE: tcp:22 is already open on the network through the project's rule(s) ${(f)opens}; no Task rule made"
  elif gc compute firewall-rules describe $FW --project=$PROJECT --format='value(name)' > /dev/null 2>&1; then
    print -r -- "NOTE: the Task firewall rule exists; kept (D deletes it)"
  else
    local ip=$(my_ip)
    [[ -n $ip ]] || stop "the current public IPv4 could not be found through Google's DNS (dig); nothing opened. The VM exists: zsh $REL D, or retry V"
    gc_or_stop "firewall rule" compute firewall-rules create $FW --project=$PROJECT --network=$NETWORK --direction=INGRESS \
      --action=ALLOW --rules=tcp:22 --source-ranges=$ip/32 --target-tags=$VM_NAME --description='Task 640 SSH (deleted by D)' --format=none
    unset ip
    print -r -- "PASS: Task firewall rule created: tcp:22 from the current public IPv4 only, to this VM's tag"
  fi
  print -r -- "waiting for gcloud compute ssh to answer (bound ${WAIT_S}s, poll ${POLL_S}s; Windows first boot and sysprep take ~5-10 min)"
  local start=$SECONDS answered=no
  while (( SECONDS - start < WAIT_S )); do
    if bounded 120 rsh "echo v640-ssh-ok" > $WORK/ssh.out 2>&1 && grep -q v640-ssh-ok $WORK/ssh.out; then answered=yes; break; fi
    print -r -- "  [$(date +%H:%M:%S)] not yet: $(tail -1 $WORK/ssh.out | cut -c1-160)"
    sleep $POLL_S
  done
  [[ $answered == yes ]] || stop "no SSH answer within ${WAIT_S}s (last: $(tail -2 $WORK/ssh.out)). Retry: zsh $REL V   or delete: zsh $REL D"
  print -r -- "PASS: SSH answers after $((SECONDS - start))s"
  mkdir -p $WORK/v640
  cp $HERE/vm/drive640.py $HERE/vm/provision.ps1 $HERE/vm/setkey.ps1 $WORK/v640/
  vm_settings > $WORK/v640/settings.json || stop "settings.json for the VM could not be made"
  make_bundle $WORK/v640/graftling.bundle
  print -r -- "\$ gcloud compute scp --recurse <stage>/v640 <VM_USER>@<VM_NAME>:C:/   (drive640.py, provision.ps1, setkey.ps1, settings.json without secret, graftling.bundle)"
  if ! gc compute scp --recurse $SSHF[1,5] $WORK/v640 "$TARGET:C:/" > $WORK/up.out 2>&1; then
    print -r -- "  gcloud compute scp failed; its output:"; sed 's/^/  | /' $WORK/up.out
    print -r -- "  uploading the same through ssh with tar (Windows' own tar.exe)"
    allow tar -cf - -C $WORK v640 | rsh "tar -xf - -C C:/" > $WORK/up2.out 2>&1 || { sed 's/^/  | /' $WORK/up2.out; stop "upload failed; retry: zsh $REL V"; }
  fi
  print -r -- "PASS: uploaded to C:\\v640"
  say "provisioning on the VM (bound 40 min): Python, Node, Git, Developer Mode, Codex $CODEX_VERSION, graftling ${CANDIDATE[1,12]}, config.toml"
  bounded 2400 rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\provision.ps1" 2>&1 | tee $WORK/console.txt
  grep -q '^PROVISION PASS' $WORK/console.txt || stop "provisioning did not pass (last lines above). Retry: zsh $REL V   or delete: zsh $REL D"
  fetch V || stop "the V evidence: $FETCHED"
  next_cmds K R0 D
  print -r -- "next: K is run by the USER in their own terminal (hidden key input); Main runs R0 after it"
  print -r -- "VERDICT 640 V: PASS (VM provisioned; evidence $FETCHED)"
  ;;
K)
  say "[K] Store the temporary provider key on the VM. USER ONLY, in your own terminal. Login: gcloud. Dialog: none (a hidden prompt)."
  load_settings
  ssh_flags
  [[ -t 0 || ${VERIFY640_K_STDIN:-} == 1 ]] || stop "K reads the key at a hidden terminal prompt; the user runs it in their own terminal: zsh $REL K"
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
  print -r -- "VERDICT 640 K: PASS (key stored as the VM user's environment variable; R0 proves it with a real call)"
  ;;
R0|R)
  load_settings
  ssh_flags
  local mode= label=R0 cmd
  if [[ $STEP == R ]]; then
    [[ $ARG == (mxc|elevated|unelevated) ]] || stop "usage: zsh $REL R mxc|elevated|unelevated"
    mode=$ARG label=R-$ARG cmd="run $ARG"
    say "[$label] R1-R4 and the 629 sec. 6 Codex items with windows.sandbox = $mode (bound 75 min). Login: gcloud. Dialog: none."
  else
    cmd=r0
    say "[R0] versions and one real codex exec call (bound 10 min). Login: gcloud. Dialog: none."
  fi
  local st=$(instance_state)
  [[ $st == RUNNING ]] || stop "the Task VM is not running (status: ${st:-absent}); run V first"
  bounded $([[ $STEP == R ]] && print 4500 || print 600) rsh "set PYTHONUTF8=1&& $VPY $REMOTE\\drive640.py $cmd" 2>&1 | tee $WORK/console.txt
  local result=$(grep -E "^RESULT $label " $WORK/console.txt | tail -1)
  fetch $label || print -r -- "evidence: $FETCHED"
  local -a items=(${(f)"$(grep -E '^ITEM ' $WORK/console.txt)"})
  print -r -- "--- items (${#items}):"; print -lr -- $items | sed 's/^/  /'
  if [[ $STEP == R0 ]]; then
    [[ $result == *PASS* ]] && next_cmds "R mxc" "R elevated" D || next_cmds R0 D
    [[ $result == *STOP* ]] && print -r -- "next: the provider refused or failed: read the raw error above; the user decides (no other model, no proxy)"
  else
    next_cmds "R mxc" "R elevated" "E $label" D
  fi
  [[ -n $result ]] || result="RESULT $label FAIL (no RESULT line; the remote run ended early)"
  local verdict=${${(z)result}[3]}
  [[ $FETCHED == PASS* ]] || verdict="$verdict, evidence $FETCHED"
  print -r -- "VERDICT 640 $label: ${verdict} (${result#RESULT $label }; evidence ${FETCHED%% *})"
  [[ $result == *" PASS"* && $FETCHED == PASS* ]] || exit 1
  ;;
E)
  load_settings
  ssh_flags
  [[ $ARG == (V|R0|R-mxc|R-elevated|R-unelevated) ]] || stop "usage: zsh $REL E V|R0|R-mxc|R-elevated|R-unelevated"
  say "[E] Scan, fetch and scrub the evidence of $ARG. Login: gcloud. Dialog: none."
  fetch $ARG
  next_cmds D
  print -r -- "VERDICT 640 E: ${FETCHED%% *} ($ARG: $FETCHED)"
  [[ $FETCHED == PASS* ]] || exit 1
  ;;
D)
  say "[D] Delete this Task's resources (VM with all disks, Task firewall rule). Login: gcloud. Dialog: none."
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
  if gc compute firewall-rules describe $FW --project=$PROJECT --format='value(name)' > /dev/null 2>&1; then
    print -r -- "\$ gcloud compute firewall-rules delete <VM_NAME>-ssh --project=<PROJECT> --quiet"
    gc compute firewall-rules delete $FW --project=$PROJECT --quiet 2>&1 | sed 's/^/  /'
  else
    print -r -- "no Task firewall rule exists"
  fi
  say "verification: nothing of this Task remains"
  local -a lf=()
  local one
  for one in ${(s:,:)VM_LABELS}; do lf+="labels.${one%%=*}=${one#*=}"; done
  local inst=$(gc compute instances list --project=$PROJECT --filter="name=$VM_NAME OR (${(j: AND :)lf})" --format='value(name)' 2> $WORK/v.err) || inst="ERR"
  local disks=$(gc compute disks list --project=$PROJECT --filter="name=$VM_NAME OR users~/instances/$VM_NAME\$" --format='value(name)' 2>> $WORK/v.err) || disks="ERR"
  local rules=$(gc compute firewall-rules list --project=$PROJECT --filter="name=$FW OR targetTags:$VM_NAME" --format='value(name)' 2>> $WORK/v.err) || rules="ERR"
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
    print -r -- "VERDICT 640 D: FAIL (still present, by name/tag/labels: ${(j:; :)left})"
    exit 1
  fi
  print -r -- "VERDICT 640 D: PASS (nothing of this Task remains: 0 instances, 0 disks, 0 firewall rules by name, tag and labels)"
  ;;
*)
  print -r -- "usage: zsh $REL 00|V|K|R0|R mxc|R elevated|R unelevated|E <step>|D"; exit 2 ;;
esac
