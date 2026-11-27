#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 650 (W8-W11): Claude Code, Pi and DSH as graftling hosts on real Windows x64, each creating a DSH child through
# graftling's MCP tool with its real model; the Claude and Pi child refusals; DSH's own host, children, stop and owner
# death; and the 629 section 6 items these touch (process shape, session end, pipe identity, code page, rule syntax).
# Runs on a fresh real Windows Server x64 VM in the user's cloud project, by Main from the user's Mac with the user's
# logged-in gcloud. Modelled on verify-644/steps.zsh (accepted): the same cloud settings, firewall rules, scrub,
# credential, evidence, D and driver-STOP rules; every case in VM_USER's interactive console session as a scheduled
# task started from SSH (no RDP, no new port, UAC unchanged). The cases come from the 647, 648 and 649 handoffs
# (scripts/verify-64{7,8,9}/handoff-650.md): O1-O9, H1-H11, D1-D9.
#
# SETTINGS: every value of the user's environment is read from ONE local, git-ignored file,
# scripts/verify-650/local/settings.zsh (template: settings.example.zsh; override: VERIFY650_SETTINGS). Each step STOPs,
# naming the variable, when a required one is missing or empty, when an optional one is not assigned (empty is fine),
# and when the file is not git-ignored or is tracked. The steps never echo a settings value. The firewall source
# address is detected at run time and never written to a file.
# LOGIN: the user's gcloud login only. Every gcloud command names --project (and --zone where it applies); no step
# changes any gcloud default; CLOUDSDK_CORE_DISABLE_PROMPTS=1. Only this Task's resources are created or deleted: the
# VM (with its boot disk) and two firewall rules that target only the VM's tag: <VM_NAME>-deny (DENY all ingress from
# 0.0.0.0/0, priority 1000) and <VM_NAME>-ssh (ALLOW tcp:22 from the current public IPv4/32, priority 900), made and
# checked BEFORE the VM exists; their descriptions name Task 650. No other port is opened (no RDP). Every SSH step
# re-checks them and moves the -ssh source to the current address if it changed. Metadata is set on the instance only.
# SSH: a Task key pair in scripts/verify-650/local/ssh/ (git-ignored), put in the instance's ssh-keys metadata.
# CREDENTIALS: at start the script unsets every exported credential-class and provider variable (count printed); every
# started process runs through allow() with an allowlisted environment and no provider credential. The ONE temporary
# key all three Runtimes use exists only in the VM user's environment (step K, by the USER, hidden input, sent on the
# ssh session's stdin); the driver hands it to each Runtime it starts under the variable that Runtime reads. The
# user's Claude account never enters the VM. The autologon password of step I is generated ON the VM, never printed,
# never leaves it (Winlogon reads it there).
# EVIDENCE: scanned on the VM for the key's value AND the autologon password (found: the step fails without printing
# it, nothing is fetched); every settings value (VM_USER too: VM paths contain it) and IP address is replaced with a
# placeholder; fetched with tar over gcloud compute ssh into scripts/verify-650/evidence/live/<case>/ (git-ignored),
# scrubbed again on the Mac.
# DIALOGS: none in any step. K reads the key at a hidden terminal prompt, which is not a dialog.
# ARRANGEMENT (fixed): graftling dev containing 0e5c92a6 (647-649), installed on the VM as its README says (uv tool
# install --managed-python, uv 0.13.10, from the bundle's checkout of the candidate); Claude Code 2.1.314 by its native
# installer (claude.exe; >= 2.1.296, the Windows stdio stop, 647 O5); Pi @earendil-works/pi-coding-agent 1.4.0
# (graftling's docs/install/pi.md); Node 24.22.3, pnpm 12.21.0, DSH @deepseek-ai/dsh 0.2.2-rc.5; Git for Windows 2.47.1.
# Each host's child is a DSH child (a connection with runtime dsh, api_key_env = KEY_ENV): DSH runs on native Windows
# (649), it reads the one shared key, and it is the child 649's D5 asks for. A Codex child would need a Responses API
# endpoint and a second provider set-up that the one shared key need not serve.
# HOST ENTRIES: print modes keep each Runtime's real process (claude.exe -p --output-format stream-json; npm's pi.cmd
# -p --mode json; npm's dsh.cmd --profile headless). The host start, the MCP server and the mod's context call are the
# same as interactive (graftling's code at 0e5c92a6 does not look at the mode); the session END differs: it is the end
# of the print run, not /exit or /quit. Each case's end item says so; the interactive /exit and /quit are not run.
# THE CASES, each printing `CASE <case> <item>: PASS|FAIL|OBSERVED <observable>` and `RESULT <case> ...`:
#   r0 (R0)  each host answers one line with its configured model and login (claude, pi, dsh); versions.
#   C   venv (H2/I1, I6, D2), claude (O1, O2, O3, O5, required result 1), claude-refuse (O6, O7, O5 without a child),
#       claude-caller (O4, 629 s6.1), claude-probe (O8), claude-market (O9).
#   P   pi (H1, H3, H4, H5, H6, H9, required result 2), pi-refuse (H8), pi-caller (H6 status, H7, 629 s6.1),
#       pi-nonascii (H11), pi-kill (H10).
#   S   dsh (D3, D4, D5, required result 3), dsh-nonascii (D9, 629 s6.6), dsh-stop (D5 stop, D8), dsh-kill (D6, D7).
#   D1 (install time) is measured by V's provisioning (evidence V: d1.json, npm-dsh.txt).
# Run one step at a time, in this order:  zsh scripts/verify-650/steps.zsh <STEP>
#   00, V, K, I, R0, C, P, S, D       (case <name> reruns one case; E <name> refetches evidence any time)
#   00  Preflight, read only: settings, gcloud account, project, scrub values distinctive, image family, no Task VM
#       yet, project rules opening 22/3389 (STOP at priority <= 1000), graftling dev contains the candidate, the Claude
#       Code pin, cost per hour (console only). ~20 s.
#   V   Create and provision the VM. CLOUD COST STARTS HERE. Task rules first, then the VM; wait for SSH (bound 20
#       min); upload by tar (drive650.py, provision.ps1, setkey.ps1, autologon.ps1, trace.ps1, mcp_probe.py,
#       settings.json without secret, the graftling bundle); provision.ps1 (bound 90 min: DSH's npm install took 18 min
#       in CI); fetch out/V. ~35-60 min. On an existing VM, V creates nothing: it re-checks the rules, re-uploads by tar
#       (files in C:\v650 overwritten, settings.json too) and re-runs provision.ps1, which skips what is installed and
#       repeats only idempotent work. The key (K) and the automatic logon (I) stay. This is how a fix is uploaded.
#   K   USER ONLY, in their own terminal: the temporary key at a hidden prompt, sent on the ssh session's stdin to
#       setkey.ps1 (stored as the VM user's environment variable KEY_ENV). Prints "stored" and the length.
#   I   Interactive logon: a new random password for VM_USER generated on the VM (never printed), Winlogon automatic
#       logon (autologon.ps1); one reboot; wait (bounded) for SSH; then (bounded 5 min) VM_USER must have an Active
#       console session (`query user`). UAC, RDP and every security setting stay unchanged. ~4-8 min.
#   R0  Preflight in the console session: each host answers a one-line prompt; the model each reports is printed (as
#       its placeholder). Before I, R0 STOPs naming I (it needs the console session). Bound 15 min.
#   C   The Claude host's cases (6 scheduled tasks, bound 15 min each). ~10-25 min.
#   P   The Pi host's cases (5 scheduled tasks, bound 15 min each). ~8-20 min.
#   S   The DSH host's cases (4 scheduled tasks, bound 15 min each). ~10-30 min.
#   case <name>  One case again (offered after NO-TOOL-CALL, which allows one rerun).
#   E <V|I|name>  Scan, fetch and scrub that evidence again.
#   D   Delete the VM with all its disks and both Task firewall rules; idempotent; verifies nothing remains (by name,
#       tag and labels) and prints that last; removes the local Task SSH key pair. ~2-4 min. Afterwards the user
#       revokes the temporary key.
# Every step waits for all its work, prints ready-to-paste next commands and `VERDICT 650 <step>: ...` last. A step
# with several cases ends at the first STOP. A STOP that is not an environment condition the steps name themselves
# (no console session: run I; no key: run K) is a driver error: do NOT run D, ask the Leader; a fix is uploaded with V
# on this same VM, then the step is rerun.
# Rehearsal knobs (Engineer only): VERIFY650_GCLOUD, VERIFY650_SETTINGS, VERIFY650_EVIDENCE, VERIFY650_GRAFTLING,
# VERIFY650_K_STDIN=1, VERIFY650_WAIT_S / _POLL_S / _REBOOT_S / _SESSION_S / _CASE_S (bounds), VERIFY650_IP. Unset,
# every step runs the real commands.
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)
THIS=${0:A}
HERE=${0:A:h}
REL=scripts/verify-650/steps.zsh
STEP=${1:-}
ARG=${2:-}
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
GRAFT=${VERIFY650_GRAFTLING:-$HARNESS/graftling}
# graftling dev at 0e5c92a6: W0-W7, 645, and 647 (Claude), 648 (Pi), 649 (DSH) for Windows. Not changed by this Task.
CANDIDATE=0e5c92a602005ba0c0e53b887ff612dfd28180fd
GBRANCH=dev
CLAUDE_VERSION=2.1.314   # native installer; the docs' real runs; >= CLAUDE_MIN
CLAUDE_MIN=2.1.296       # Claude Code's documented Windows stdio stop (647 handoff O5)
PI_VERSION=1.4.0         # @earendil-works/pi-coding-agent, as graftling's docs/install/pi.md
DSH_VERSION=0.2.2-rc.5   # @deepseek-ai/dsh, as 649
PNPM_VERSION=12.21.0     # pnpm for dsh plugin add, as graftling's docs/install/dsh.md's walk
SETTINGS=${VERIFY650_SETTINGS:-$HERE/local/settings.zsh}
KEYDIR=${SETTINGS:h}/ssh
KEY=$KEYDIR/v650-key
LIVE=${VERIFY650_EVIDENCE:-$HERE/evidence/live}
GCLOUD=${VERIFY650_GCLOUD:-$(whence -p gcloud || print -r -- gcloud)}
GIT=$(whence -p git)
PY=/Users/luoxiao/miniconda3/bin/python3.13
[[ -x $PY ]] || PY=/usr/bin/python3
WAIT_S=${VERIFY650_WAIT_S:-1200}
POLL_S=${VERIFY650_POLL_S:-30}
REBOOT_S=${VERIFY650_REBOOT_S:-60}     # I: pause after the reboot command before polling SSH
SESSION_S=${VERIFY650_SESSION_S:-300}  # I: bound for the console session to appear after SSH answers
CASE_S=${VERIFY650_CASE_S:-900}        # each case: bound for its scheduled task's done file
PROVISION_S=5400                       # V: provision.ps1 (DSH's npm install alone took 18 min in CI)
STEPNAME="$STEP${ARG:+ $ARG}"
PYTMP=${TMPDIR:-/tmp}
[[ ${PYTMP:A} == ${HARNESS}(|/*) ]] && PYTMP=/tmp
REMOTE='C:\v650'
DRIVER='C:\v650\driver.cmd'
CASES=(r0 venv claude claude-refuse claude-caller claude-probe claude-market pi pi-refuse pi-caller pi-nonascii pi-kill
       dsh dsh-nonascii dsh-stop dsh-kill)
GROUP_C=(venv claude claude-refuse claude-caller claude-probe claude-market)
GROUP_P=(pi pi-refuse pi-caller pi-nonascii pi-kill)
GROUP_S=(dsh dsh-nonascii dsh-stop dsh-kill)
REQUIRED=(PROJECT ZONE MACHINE_TYPE VCPUS VM_NAME VM_LABELS VM_USER NETWORK IMAGE_FAMILY IMAGE_PROJECT DISK_GB
          KEY_ENV CLAUDE_BASE_URL CLAUDE_AUTH_VAR CLAUDE_MODEL PI_ROUTE PI_PROVIDER PI_MODEL DSH_CHILD_MODEL
          DSH_MAIN_KEY_VAR
          PRICE_VM_USD_H PRICE_WINLIC_USD_VCPU_H PRICE_DISK_USD_GB_MONTH PRICE_IP_USD_H EST_CURRENCY EST_RATE BUDGET)
OPTIONAL=(CLAUDE_HAIKU_MODEL CLAUDE_SONNET_MODEL CLAUDE_OPUS_MODEL CLAUDE_SUBAGENT_MODEL CLAUDE_API_TIMEOUT_MS
          PI_KEY_VAR PI_BASE_URL PI_API DSH_CHILD_PROVIDER DSH_CHILD_BASE_URL DSH_MAIN_BASE_URL DSH_MAIN_APP_ARGS)

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
    if is_cred $k || [[ $k == ANTHROPIC_* || $k == OPENAI_* || $k == CODEX_* || $k == CLAUDE_CODE_* || $k == *_BASE_URL || $k == GRAFTLING_* || $k == PI_* || $k == DSH_* ]]; then
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
stop() { print -r -- "STOP: $*"; print -r -- "VERDICT 650 $STEPNAME: STOP"; exit 1; }
WORK=$(mktemp -d $PYTMP/verify650.XXXXXX)
trap 'rm -rf $WORK' EXIT

# --- settings ----------------------------------------------------------------------------------------------------
# Both take one (possibly empty) argument; callers quote it, so an empty optional value is refused, not lost.
is_url() { [[ ${1:-} == http(|s)://[^/@?#[:space:]]##(|/*) && ${1:-} != *[?#[:space:]]* ]]; }
is_env_name() { [[ ${1:-} == [A-Za-z_][A-Za-z0-9_]# ]]; }
load_settings() {
  [[ -f $SETTINGS ]] || stop "no settings file at scripts/verify-650/local/settings.zsh (copy settings.example.zsh there and fill it in)"
  allow $GIT -C $WT check-ignore -q -- $SETTINGS 2> /dev/null \
    || stop "the settings file is not git-ignored here (it must sit under scripts/verify-650/local/); nothing done"
  allow $GIT -C $WT ls-files --error-unmatch -- $SETTINGS > /dev/null 2>&1 \
    && stop "the settings file is tracked by git; remove it from the index first (git rm --cached); nothing done"
  local name
  for name in $REQUIRED; do typeset -g $name=; done
  for name in $OPTIONAL; do unset $name; done
  source $SETTINGS || stop "the settings file did not load"
  for name in $REQUIRED; do [[ -n ${(P)name} ]] || stop "settings variable $name is missing or empty"; done
  for name in $OPTIONAL; do (( ${+parameters[$name]} )) || stop "settings variable $name is missing (it may be empty: $name=)"; done
  [[ $VM_NAME == [a-z]([-a-z0-9](#c0,61)[a-z0-9]|) ]] || stop "settings variable VM_NAME is not a valid instance name"
  (( ${#VM_USER} <= 20 )) || stop "settings variable VM_USER is longer than 20 characters"
  [[ $CLAUDE_BASE_URL == https://* ]] && is_url "$CLAUDE_BASE_URL" || stop "settings variable CLAUDE_BASE_URL is not an https URL"
  [[ $CLAUDE_AUTH_VAR == (ANTHROPIC_AUTH_TOKEN|ANTHROPIC_API_KEY) ]] || stop "settings variable CLAUDE_AUTH_VAR is neither ANTHROPIC_AUTH_TOKEN nor ANTHROPIC_API_KEY"
  [[ -z $CLAUDE_API_TIMEOUT_MS || $CLAUDE_API_TIMEOUT_MS == <-> ]] || stop "settings variable CLAUDE_API_TIMEOUT_MS is not a number of milliseconds"
  for name in KEY_ENV DSH_MAIN_KEY_VAR; do is_env_name "${(P)name}" || stop "settings variable $name is not an environment variable name"; done
  case $PI_ROUTE in
    builtin) is_env_name "$PI_KEY_VAR" || stop "settings variable PI_KEY_VAR is missing or not an environment variable name (PI_ROUTE=builtin needs it)"
             [[ -z $PI_BASE_URL && -z $PI_API ]] || stop "settings variables PI_BASE_URL and PI_API must be empty with PI_ROUTE=builtin" ;;
    custom)  is_url "$PI_BASE_URL" || stop "settings variable PI_BASE_URL is missing or not an http(s) URL (PI_ROUTE=custom needs it)"
             [[ -n $PI_API ]] || stop "settings variable PI_API is missing or empty (PI_ROUTE=custom needs it)"
             [[ -z $PI_KEY_VAR ]] || stop "settings variable PI_KEY_VAR must be empty with PI_ROUTE=custom (models.json names KEY_ENV)" ;;
    *) stop "settings variable PI_ROUTE is neither builtin nor custom" ;;
  esac
  for name in DSH_CHILD_BASE_URL DSH_MAIN_BASE_URL; do
    [[ -z ${(P)name} ]] || is_url "${(P)name}" || stop "settings variable $name is not an http(s) URL without user, query or fragment"
  done
  REGION=${ZONE%-*}
  FW=$VM_NAME-ssh     # Task rule: ALLOW tcp:22 from the current public IPv4/32, priority 900, target tag VM_NAME
  FWD=$VM_NAME-deny   # Task rule: DENY all from 0.0.0.0/0, priority 1000, target tag VM_NAME
  TARGET=$VM_USER@$VM_NAME
}
host_of() { local u=${1#*://}; print -r -- ${u%%/*}; }
# <NAME> <value> pairs of every scrubbed setting (empty optional values skipped), for the check and the scrub.
scrub_list() {
  local name one
  local -a out=(PROJECT $PROJECT ZONE $ZONE REGION $REGION VM_NAME $VM_NAME MACHINE_TYPE $MACHINE_TYPE VM_USER $VM_USER
                KEY_ENV $KEY_ENV)
  for one in ${(s:,:)VM_LABELS}; do out+=(VM_LABEL ${one#*=}); done
  local -a scrubbed=(CLAUDE_MODEL CLAUDE_HAIKU_MODEL CLAUDE_SONNET_MODEL CLAUDE_OPUS_MODEL CLAUDE_SUBAGENT_MODEL
                     PI_PROVIDER PI_MODEL PI_KEY_VAR DSH_CHILD_MODEL DSH_CHILD_PROVIDER DSH_MAIN_KEY_VAR)
  for name in $scrubbed; do
    [[ -n ${(P)name} ]] && out+=($name ${(P)name})
  done
  for name in CLAUDE_BASE_URL PI_BASE_URL DSH_CHILD_BASE_URL DSH_MAIN_BASE_URL; do
    [[ -n ${(P)name} ]] && out+=($name ${(P)name} $name ${${(P)name}%/} ${name}_HOST $(host_of ${(P)name}))
  done
  for one in ${(z)DSH_MAIN_APP_ARGS}; do [[ $one == -* ]] || out+=(DSH_MAIN_ARG $one); done
  print -rl -- $out
}
# STOP, naming only the variable, when a value the evidence scrub would replace is shorter than 4 characters or occurs
# (any case) in the committed drive650.py or steps.zsh: such a value is ordinary text and would garble the evidence.
check_scrub_values() {
  local -a checks=("${(@f)$(scrub_list)}")
  local bad=$(allow $PY -I -c 'import sys
text = (open(sys.argv[1], encoding="utf-8").read() + open(sys.argv[2], encoding="utf-8").read()).lower()
a = sys.argv[3:]
bad = []
for name, value in zip(a[::2], a[1::2]):
    name = name[:-5] if name.endswith("_HOST") else name
    if (len(value) < 4 or value.lower() in text) and name not in bad:
        bad.append(name)
print(" ".join(bad))' $HERE/vm/drive650.py $THIS $checks)
  [[ -z $bad ]] || stop "settings variable(s) ${bad} hold ordinary text (shorter than 4 characters, or found in drive650.py or steps.zsh); the evidence scrub would garble the evidence. Choose a more distinctive value"
  print -r -- "PASS: every value the evidence scrub replaces is distinctive (4+ characters, absent from drive650.py and steps.zsh)"
}
# A JSON list of [placeholder, value] pairs: every scrubbed settings value and derived form, plus the active account.
scrub_values() {
  local account=$(allow $GCLOUD auth list --filter=status:ACTIVE --format='value(account)' --project=$PROJECT 2> /dev/null | head -1)
  local -a pairs=("${(@f)$(scrub_list)}")
  pairs+=(VM_NAME ${VM_NAME[1,15]})
  [[ -n $account ]] && pairs+=(ACCOUNT $account)
  allow $PY -I -c 'import json, sys; a = sys.argv[1:]; print(json.dumps([["<" + a[i] + ">", a[i + 1]] for i in range(0, len(a), 2) if a[i + 1]]))' $pairs
}
vm_settings() {  # settings.json for the VM: the Runtimes' settings, the pins and the scrub pairs (no secret)
  allow $PY -I -c 'import json, sys
v = dict(item.split("=", 1) for item in sys.argv[2:])
print(json.dumps({
    "key_env": v["KEY_ENV"], "candidate": v["CANDIDATE"],
    "pins": {"claude": v["CLAUDE_VERSION"], "pi": v["PI_VERSION"], "dsh": v["DSH_VERSION"], "pnpm": v["PNPM_VERSION"]},
    "claude": {"base_url": v["CLAUDE_BASE_URL"], "auth_var": v["CLAUDE_AUTH_VAR"], "model": v["CLAUDE_MODEL"],
               "haiku": v["CLAUDE_HAIKU_MODEL"], "sonnet": v["CLAUDE_SONNET_MODEL"], "opus": v["CLAUDE_OPUS_MODEL"],
               "subagent": v["CLAUDE_SUBAGENT_MODEL"], "api_timeout_ms": v["CLAUDE_API_TIMEOUT_MS"]},
    "pi": {"route": v["PI_ROUTE"], "provider": v["PI_PROVIDER"], "model": v["PI_MODEL"], "key_var": v["PI_KEY_VAR"],
           "base_url": v["PI_BASE_URL"], "api": v["PI_API"]},
    "dsh_child": {"model": v["DSH_CHILD_MODEL"], "provider": v["DSH_CHILD_PROVIDER"], "base_url": v["DSH_CHILD_BASE_URL"]},
    "dsh_main": {"key_var": v["DSH_MAIN_KEY_VAR"], "base_url": v["DSH_MAIN_BASE_URL"], "app_args": v["DSH_MAIN_APP_ARGS"].split()},
    "scrub": json.loads(sys.argv[1])}))' "$(scrub_values)" \
    KEY_ENV=$KEY_ENV CANDIDATE=$CANDIDATE CLAUDE_VERSION=$CLAUDE_VERSION PI_VERSION=$PI_VERSION DSH_VERSION=$DSH_VERSION \
    PNPM_VERSION=$PNPM_VERSION CLAUDE_BASE_URL=$CLAUDE_BASE_URL CLAUDE_AUTH_VAR=$CLAUDE_AUTH_VAR CLAUDE_MODEL=$CLAUDE_MODEL \
    CLAUDE_HAIKU_MODEL=$CLAUDE_HAIKU_MODEL CLAUDE_SONNET_MODEL=$CLAUDE_SONNET_MODEL CLAUDE_OPUS_MODEL=$CLAUDE_OPUS_MODEL \
    CLAUDE_SUBAGENT_MODEL=$CLAUDE_SUBAGENT_MODEL CLAUDE_API_TIMEOUT_MS=$CLAUDE_API_TIMEOUT_MS PI_ROUTE=$PI_ROUTE \
    PI_PROVIDER=$PI_PROVIDER PI_MODEL=$PI_MODEL PI_KEY_VAR=$PI_KEY_VAR PI_BASE_URL=$PI_BASE_URL PI_API=$PI_API \
    DSH_CHILD_MODEL=$DSH_CHILD_MODEL DSH_CHILD_PROVIDER=$DSH_CHILD_PROVIDER DSH_CHILD_BASE_URL=$DSH_CHILD_BASE_URL \
    DSH_MAIN_KEY_VAR=$DSH_MAIN_KEY_VAR DSH_MAIN_BASE_URL=$DSH_MAIN_BASE_URL DSH_MAIN_APP_ARGS=$DSH_MAIN_APP_ARGS
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
fwpath, net, port, tag, *ours = sys.argv[1:]
def opens(rule):
    for allowed in rule.get("allowed", []):
        if allowed.get("IPProtocol") not in ("tcp", "all"):
            continue
        for item in allowed.get("ports") or ["0-65535"]:
            low, _, high = item.partition("-")
            if int(low) <= int(port) <= int(high or low):
                return True
    return False
for rule in json.load(open(fwpath)):
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
      --description='Task 650: deny all ingress to the Task VM (deleted by D)' --format=none
    print -r -- "PASS: created <VM_NAME>-deny (DENY all from everyone, priority 1000, only this VM's tag)"
    state=$(check_rule $FWD deny $ip)
  fi
  [[ $state == ABSENT ]] && stop "the Task firewall rules are missing; run: zsh $REL V   (or delete everything: zsh $REL D)"
  [[ $state == OK ]] || stop "<VM_NAME>-deny is not as specified (${state#BAD }); nothing else done. Delete with: zsh $REL D"
  state=$(check_rule $FW ssh $ip)
  if [[ $state == ABSENT && $1 == create ]]; then
    gc_or_stop "Task ssh rule" compute firewall-rules create $FW --project=$PROJECT --network=$NETWORK --direction=INGRESS \
      --action=ALLOW --rules=tcp:22 --source-ranges=$ip/32 --target-tags=$VM_NAME --priority=900 \
      --description='Task 650: SSH from the user (deleted by D)' --format=none
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
  if [[ -n ${VERIFY650_IP:-} ]]; then print -r -- $VERIFY650_IP; return 0; fi
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
# fetch <step>: scan on the VM (key or password: fail, never printed; values and IPs replaced; it prints the file
# count), tar over ssh to evidence/live/<step> (the extracted count must equal the VM's), scrub again on the Mac.
# Sets FETCHED (PASS/FAIL text).
FETCHED=
fetch() {
  local step=$1 dest=$LIVE/$1 out
  say "evidence of $step: scan on the VM, fetch, scrub on the Mac"
  out=$(bounded 600 rsh "$DRIVER scan $step" 2>&1)
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
  print -r -- "  \$ gcloud compute ssh ... --command=\"tar -cf - -C C:/v650/out $step\" | tar -xf - -C evidence/live   (Windows' own tar.exe)"
  rsh "tar -cf - -C C:/v650/out $step" 2> $WORK/tar.err | allow tar -xf - -C $LIVE 2>> $WORK/tar.err \
    || { sed 's/^/  | /' $WORK/tar.err; FETCHED="FAIL (fetch failed)"; return 1; }
  [[ -d $dest ]] || { FETCHED="FAIL (no $step directory arrived)"; return 1; }
  local got=$(find $dest -type f | wc -l | tr -d ' ')
  # The Mac pass runs on whatever arrived, before the count verdict, so a partial fetch is scrubbed too.
  [[ -f $WORK/console.txt ]] && cp $WORK/console.txt $dest/mac-console.txt
  scrub_values > $WORK/scrub.json
  out=$(allow env V650_HOME=$WORK $PY -I $HERE/vm/drive650.py scrub $dest $WORK/scrub.json 2>&1)
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
    if bounded 120 rsh "echo v650-ssh-ok" > $WORK/ssh.out 2>&1 && grep -q v650-ssh-ok $WORK/ssh.out; then
      print -r -- "PASS: SSH answers after $((SECONDS - start))s"; return 0
    fi
    print -r -- "  [$(date +%H:%M:%S)] not yet: $(tail -1 $WORK/ssh.out | cut -c1-160)"
    sleep $POLL_S
  done
  return 1
}
# one_case <case>: its scheduled task in the console session (bounded on the VM by CASE_S, here by CASE_S + 300),
# then the cleanup of its leftovers, then its evidence. Sets CASE_VERDICT (PASS | FAIL ... | NO-TOOL-CALL ... |
# STOP <reason>) and CASE_FETCHED; prints the case's item lines.
CASE_VERDICT= CASE_FETCHED=
one_case() {
  local label=$1
  say "case $label: a scheduled task in VM_USER's console session (bound ${CASE_S}s on the VM)"
  print -r -- "\$ gcloud compute ssh ... --command=\"C:\\v650\\driver.cmd schedule $label $CASE_S\"   (bound $((CASE_S + 300))s)"
  bounded $((CASE_S + 300)) rsh "$DRIVER schedule $label $CASE_S" 2>&1 | tr -d '\r' | tee $WORK/console.txt
  local result=$(grep -E "^RESULT $label " $WORK/console.txt | tail -1)
  print -r -- "\$ gcloud compute ssh ... --command=\"C:\\v650\\driver.cmd cleanup $label\"   (bound 180s)"
  bounded 180 rsh "$DRIVER cleanup $label" 2>&1 | tr -d '\r' | grep -E '^CLEANUP ' | sed 's/^/  /'
  fetch $label || print -r -- "evidence: $FETCHED"
  CASE_FETCHED=$FETCHED
  local -a lines=(${(f)"$(grep -E "^CASE $label " $WORK/console.txt)"})
  print -r -- "--- case $label: one line per item (${#lines}):"
  print -lr -- $lines | sed 's/^/  /'
  CASE_VERDICT=${result#RESULT $label }
  [[ -n $result ]] || CASE_VERDICT="STOP no RESULT line (the remote run ended early; see the console above)"
  print -r -- "--- RESULT $label $CASE_VERDICT"
}
# A STOP that is not an environment condition the steps name themselves (no console session: run I; no key: run K)
# is a defect of the steps or driver: the VM is kept for a fix, which V uploads by tar on this same VM.
env_stop() { [[ $1 == *'no Active console session'* || $1 == *'key variable is not set'* ]]; }
driver_stop_next() {
  print -r -- "next: do NOT run D: this STOP is a driver error; the VM stays as it is. Ask the Leader; a fix is uploaded with:"
  next_cmds V
  print -r -- "next: (V resumes on this existing VM: re-uploads by tar and re-runs the idempotent provisioning; then rerun:)"
  next_cmds "$STEPNAME"
}
group_next() {  # the step after the group <case> belongs to
  if [[ $1 == r0 ]]; then print -r -- C
  elif (( ${GROUP_C[(Ie)$1]} )); then print -r -- P
  elif (( ${GROUP_P[(Ie)$1]} )); then print -r -- S
  else print -r -- D; fi
}
# run_cases <case...>: each case in turn (ending at the first STOP); then the next commands and the verdict, last.
run_cases() {
  local one stopped= verdict
  local -a summary=() norerun=() failed=() evid=()
  for one in "$@"; do
    one_case $one
    summary+="$one ${CASE_VERDICT%% *}"
    evid+="$one ${CASE_FETCHED%% *}"
    [[ $CASE_FETCHED == PASS* ]] || failed+="$one-evidence"
    case $CASE_VERDICT in
      STOP*) stopped=$CASE_VERDICT; break ;;
      NO-TOOL-CALL*) norerun+=$one ;;
      FAIL*) failed+=$one ;;
    esac
  done
  print -r -- "=== step $STEPNAME: ${(j:, :)summary} (evidence: ${(j:, :)evid})"
  if [[ -n $stopped ]]; then
    if env_stop $stopped; then
      [[ $stopped == *console\ session* ]] && next_cmds I "$STEPNAME" D || next_cmds K "$STEPNAME"
    else
      driver_stop_next
    fi
    print -r -- "VERDICT 650 $STEPNAME: STOP ($stopped; ${(j:, :)summary})"
    exit 1
  fi
  for one in $norerun; do
    print -r -- "next: case $one: the model made no tool call; rerun it once:"
    next_cmds "case $one"
  done
  local after=$(group_next $1)
  if [[ $STEPNAME == R0 && ${(j: :)summary} != *'r0 PASS'* ]]; then
    print -r -- "next: a Runtime did not answer as configured: read the item lines above (raw errors in the evidence); the user decides (no other model or endpoint is tried). A settings fix is uploaded with V on this VM, then R0 again:"
    next_cmds V R0 D
  elif [[ $after == D ]]; then
    next_cmds D
  else
    next_cmds $after D
  fi
  verdict=PASS
  (( ${#norerun} )) && verdict=NO-TOOL-CALL
  (( ${#failed} )) && verdict=FAIL
  print -r -- "VERDICT 650 $STEPNAME: $verdict (${(j:, :)summary}; evidence: ${(j:, :)evid})"
  [[ $verdict == PASS ]] || exit 1
}

case $STEP in
00)
  say "[00] Preflight, read only. Login: gcloud (account not shown). Dialog: none."
  print -r -- "PASS: run by zsh $ZSH_VERSION"
  load_settings
  print -r -- "PASS: settings file is git-ignored and untracked; variables read (names only): ${(j:, :)REQUIRED}; optional (assigned, may be empty): ${(j:, :)OPTIONAL}"
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
  allow $PY -I -c 'import sys; t = lambda v: tuple(map(int, v.split("."))); sys.exit(0 if t(sys.argv[1]) >= t(sys.argv[2]) else 1)' $CLAUDE_VERSION $CLAUDE_MIN \
    && print -r -- "PASS: Claude Code pin $CLAUDE_VERSION >= $CLAUDE_MIN (the Windows stdio stop); Pi $PI_VERSION, DSH $DSH_VERSION, pnpm $PNPM_VERSION" \
    || stop "Claude Code pin $CLAUDE_VERSION is below $CLAUDE_MIN"
  print -r -- "PASS: Pi route $PI_ROUTE; the DSH child's provider $([[ -n $DSH_CHILD_PROVIDER ]] && print set || print 'DSH built-in'), base_url $([[ -n $DSH_CHILD_BASE_URL ]] && print set || print 'the route'"'"'s own'); every host's child is a DSH child (api_key_env = KEY_ENV)"
  [[ -f $KEY ]] && print -r -- "NOTE: the Task SSH key already exists (V reuses it)" || print -r -- "PASS: no Task SSH key yet (V creates one under local/ssh)"
  allow $PY -I -c 'import sys
vm, lic, vcpu, disk, gb, ip, rate, budget = map(float, sys.argv[1:9])
usd = vm + lic * vcpu + disk * gb / 730 + ip
print(f"cost estimate (console only): {usd * rate:.0f} {sys.argv[9]}/hour (USD {usd:.3f}/h: VM, Windows licence, disk, IP); the budget covers about {budget / (usd * rate):.0f} h of VM time")' \
    $PRICE_VM_USD_H $PRICE_WINLIC_USD_VCPU_H $VCPUS $PRICE_DISK_USD_GB_MONTH $DISK_GB $PRICE_IP_USD_H $EST_RATE $BUDGET $EST_CURRENCY
  if [[ $vmstate == absent ]]; then next_cmds V; else next_cmds V D; fi
  print -r -- "VERDICT 650 00: PASS (Task VM: $vmstate)"
  ;;
V)
  say "[V] Create and provision the VM. CLOUD COST STARTS HERE (until D). Login: gcloud. Dialog: none."
  load_settings
  ssh_flags
  check_scrub_values
  mkdir -p $KEYDIR $LIVE
  if [[ ! -f $KEY ]]; then
    allow ssh-keygen -q -t ed25519 -N '' -C v650 -f $KEY || stop "ssh-keygen failed"
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
  ssh_answers $WAIT_S || stop "no SSH answer within ${WAIT_S}s (last: $(tail -2 $WORK/ssh.out)). Retry: zsh $REL V   or delete: zsh $REL D"
  mkdir -p $WORK/v650
  cp $HERE/vm/drive650.py $HERE/vm/provision.ps1 $HERE/vm/setkey.ps1 $HERE/vm/autologon.ps1 $HERE/vm/trace.ps1 \
     $HERE/vm/mcp_probe.py $WORK/v650/
  vm_settings > $WORK/v650/settings.json || stop "settings.json for the VM could not be made"
  make_bundle $WORK/v650/graftling.bundle
  # tar over ssh is the only transfer; files in C:\v650 are overwritten on a rerun.
  print -r -- "\$ tar -cf - v650 | gcloud compute ssh <VM_USER>@<VM_NAME> ... --command=\"tar -xf - -C C:/\"   (drive650.py, provision.ps1, setkey.ps1, autologon.ps1, trace.ps1, mcp_probe.py, settings.json without secret, graftling.bundle)"
  allow tar -cf - -C $WORK v650 | rsh "tar -xf - -C C:/" > $WORK/up.out 2>&1 || { sed 's/^/  | /' $WORK/up.out; stop "upload failed; retry: zsh $REL V"; }
  print -r -- "PASS: uploaded to C:\\v650"
  say "provisioning on the VM (bound $((PROVISION_S / 60)) min): Git, Node, uv, graftling ${CANDIDATE[1,12]} (uv tool install), Claude Code $CLAUDE_VERSION, pnpm, Pi $PI_VERSION, DSH $DSH_VERSION, pi install, dsh plugin add"
  bounded $PROVISION_S rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\provision.ps1" 2>&1 | tee $WORK/console.txt
  grep -q '^PROVISION PASS' $WORK/console.txt || stop "provisioning did not pass (last lines above). Retry: zsh $REL V   or delete: zsh $REL D"
  fetch V || stop "the V evidence: $FETCHED"
  if [[ -n $st ]]; then
    print -r -- "next: V resumed on the existing VM (re-uploaded, provisioning re-run); the key from K and the automatic logon of I stay: rerun the step that stopped"
  fi
  next_cmds K I D
  print -r -- "next: K is run by the USER in their own terminal (hidden key input); Main runs I, then R0, after it"
  print -r -- "VERDICT 650 V: PASS (VM provisioned; evidence $FETCHED)"
  ;;
K)
  say "[K] Store the one temporary key on the VM. USER ONLY, in your own terminal. Login: gcloud. Dialog: none (a hidden prompt)."
  load_settings
  ssh_flags
  ensure_rules check
  [[ -t 0 || ${VERIFY650_K_STDIN:-} == 1 ]] || stop "K reads the key at a hidden terminal prompt; the user runs it in their own terminal: zsh $REL K"
  local st=$(instance_state)
  [[ $st == RUNNING ]] || stop "the Task VM is not running (status: ${st:-absent}); run V first"
  local secret=
  print -n -- "Paste the temporary key (hidden), then press Enter: "
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
  next_cmds I
  print -r -- "VERDICT 650 K: PASS (key stored as the VM user's environment variable; R0 proves it with real calls)"
  ;;
I)
  say "[I] Interactive logon of VM_USER: a random VM-only password, Winlogon automatic logon, one reboot, wait, verify the console session. Login: gcloud. Dialog: none."
  running_vm
  print -r -- "\$ gcloud compute ssh ... --command=\"powershell ... -File C:\\v650\\autologon.ps1\"   (the password is generated on the VM and never printed)"
  bounded 300 rsh "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $REMOTE\\autologon.ps1" > $WORK/al.out 2>&1
  tr -d '\r' < $WORK/al.out | sed 's/^/  /'
  grep -q '^AUTOLOGON SET' $WORK/al.out || { next_cmds I D; stop "the automatic logon was not configured (see the lines above); nothing rebooted"; }
  print -r -- "\$ gcloud compute ssh ... --command=\"shutdown /r /t 10\"   (reboot, so that Winlogon logs VM_USER on at the console)"
  rsh 'shutdown /r /t 10 /c "Task 650: reboot for the automatic logon"' > $WORK/rb.out 2>&1 \
    || { sed 's/^/  | /' $WORK/rb.out; next_cmds I D; stop "the reboot command failed"; }
  print -r -- "rebooting; first SSH poll in ${REBOOT_S}s (bound ${WAIT_S}s, poll ${POLL_S}s)"
  sleep $REBOOT_S
  ssh_answers $WAIT_S || { next_cmds I D; stop "no SSH answer within ${WAIT_S}s after the reboot (last: $(tail -1 $WORK/ssh.out))"; }
  print -r -- "waiting for VM_USER's Active console session (query user; bound ${SESSION_S}s)"
  local start=$SECONDS found=
  while true; do
    bounded 120 rsh "$DRIVER session" 2>&1 | tr -d '\r' > $WORK/session.out
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
    stop "the interactive logon was not established (${found:-no session answer}); every case needs it. Retry I once, or delete: zsh $REL D"
  fi
  next_cmds R0
  print -r -- "VERDICT 650 I: PASS (VM_USER has an Active console session: ${found#SESSION ACTIVE }; evidence ${FETCHED%% *})"
  [[ $FETCHED == PASS* ]] || exit 1
  ;;
R0)
  say "[R0] Preflight in VM_USER's console session: Claude Code, Pi and DSH each answer a one-line prompt with the configured model and login (a scheduled task; bound $((CASE_S / 60)) min). Login: gcloud. Dialog: none."
  running_vm
  run_cases r0
  ;;
C)
  say "[C] The Claude Code host: cases ${(j:, :)GROUP_C} in VM_USER's console session (a scheduled task each; bound $((CASE_S / 60)) min each, $((${#GROUP_C} * CASE_S / 60)) min at most). Login: gcloud. Dialog: none."
  running_vm
  run_cases $GROUP_C
  ;;
P)
  say "[P] The Pi host: cases ${(j:, :)GROUP_P} in VM_USER's console session (a scheduled task each; bound $((CASE_S / 60)) min each, $((${#GROUP_P} * CASE_S / 60)) min at most). Login: gcloud. Dialog: none."
  running_vm
  run_cases $GROUP_P
  ;;
S)
  say "[S] DSH: cases ${(j:, :)GROUP_S} in VM_USER's console session (a scheduled task each; bound $((CASE_S / 60)) min each, $((${#GROUP_S} * CASE_S / 60)) min at most). Login: gcloud. Dialog: none."
  running_vm
  run_cases $GROUP_S
  ;;
case)
  (( ${CASES[(Ie)$ARG]} )) || { print -r -- "usage: zsh $REL case ${(j:|:)CASES}"; print -r -- "VERDICT 650 $STEPNAME: STOP"; exit 2; }
  say "[case $ARG] One case again in VM_USER's console session (bound $((CASE_S / 60)) min). Login: gcloud. Dialog: none."
  running_vm
  run_cases $ARG
  ;;
E)
  [[ $ARG == (V|I) ]] || (( ${CASES[(Ie)$ARG]} )) || { print -r -- "usage: zsh $REL E V|I|${(j:|:)CASES}"; print -r -- "VERDICT 650 $STEPNAME: STOP"; exit 2; }
  say "[E] Scan, fetch and scrub the evidence of $ARG. Login: gcloud. Dialog: none."
  load_settings
  ssh_flags
  ensure_rules check
  fetch $ARG
  next_cmds D
  print -r -- "VERDICT 650 E $ARG: ${FETCHED%% *} ($FETCHED)"
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
  print -r -- "reminder: the user now revokes the temporary key at its provider"
  print -r -- "note: gcloud keeps the VM's host key in ~/.ssh/google_compute_known_hosts (alias compute.<instance id>); harmless after deletion"
  if (( ${#left} )); then
    next_cmds D
    print -r -- "VERDICT 650 D: FAIL (still present, by name/tag/labels: ${(j:; :)left})"
    exit 1
  fi
  print -r -- "VERDICT 650 D: PASS (nothing of this Task remains: 0 instances, 0 disks, 0 firewall rules by name, tag and labels)"
  ;;
*)
  print -r -- "usage: zsh $REL 00|V|K|I|R0|C|P|S|case <name>|E <name>|D"; exit 2 ;;
esac
