#!/bin/zsh
# Task 650 rehearsal only (from 644's): a gcloud stand-in for steps.zsh (VERIFY650_GCLOUD=<this file>). It records every argv
# (one line, quoted) and its environment, and simulates the commands the steps use. State lives in $TMPDIR/fake650/:
#   instance, fw              the Task VM / Task firewall rule exist
#   fail-create               instances create fails as a refused billing account would (gcloud-like error text)
#   project-rules.json        the project's own firewall rules (Compute API Firewall resources), [] when absent
#   rule-<name>.json          a Task firewall rule, written from the create/update argv in the API's resource shape
#   rules-at-create.txt       the Task rules that existed when `instances create` ran (no-exposed-window check)
#   image-mismatch            describe-from-family answers with another family (as the -core family would)
#   ssh-fail                  compute ssh never answers
#   disk-left                 a disk named after the VM survives the delete (D must then FAIL)
# Logs: argv.log, env.log (names=values of each call's environment), stdin.log (for setkey: length and SHA-256 of
# what arrived on stdin, never the value). Transfers are tar over ssh; fake evidence holds dummy values and sample IPs.
#   tar-short                 the fetch tar loses one of the 3 evidence files (the count check must FAIL)
#   autologon / autologon-fail / no-session / rebooted   step I: configured / refused / no console session / reboot asked
#   want-<case>               the RESULT case <case> reports (default PASS), e.g. 'NO-TOOL-CALL (...)' or
#                             'STOP driver error: ...'; hang-<case>: the schedule never returns (the step's bound ends it)
# The case lines printed for `driver.cmd schedule <case>` have the real driver's format (one line per item); the
# driver itself is rehearsed by rehearse-driver.zsh.
emulate -L zsh
setopt extended_glob
S=${TMPDIR:-/tmp}/fake650
mkdir -p $S
print -r -- "${(j: :)${(q+)@}}" >> $S/argv.log
print -r -- "--- ${(j: :)${(q+)@[1,3]}}" >> $S/env.log
env >> $S/env.log
args="$*"
cmd= filt=
for a in "$@"; do [[ $a == --command=* ]] && cmd=${a#--command=}; [[ $a == --filter=* ]] && filt=${a#--filter=}; done
first=${${filt#name=}%% *}   # the first name in a 'name=X ...' filter (names are never written into this file)
case "$1 $2 $3" in
'version  '*|version*) print -r -- "Google Cloud SDK 999.0.0 (stand-in)" ;;
'auth list'*) print -r -- "fake-account@example.invalid" ;;
'projects describe'*) print -r -- ACTIVE ;;
'compute images describe-from-family')
  # value(name,family,architecture): gcloud's value() format, tab-separated, one line for the one image.
  fam=$4; [[ -f $S/image-mismatch ]] && fam=$4-core
  print -r -- "windows-server-fake-dc-v20261111	$fam	X86_64" ;;
'compute instances list')
  [[ -f $S/instance ]] && { [[ $args == *'value(status)'* ]] && print -r -- RUNNING || print -r -- $first; } ;;
'compute instances create')
  if [[ -f $S/fail-create ]]; then
    print -r -- "ERROR: (gcloud.compute.instances.create) Could not fetch resource:" >&2
    print -r -- " - Windows Server images are not available on free trial billing accounts (stand-in error text)" >&2
    exit 1
  fi
  ls $S | grep '^rule-' | sort > $S/rules-at-create.txt
  touch $S/instance; print -r -- RUNNING ;;
'compute instances start') ;;
'compute instances delete') rm -f $S/instance; print -r -- "Deleted [stand-in instance]." ;;
'compute firewall-rules list')
  if [[ $args == *--format=json* ]]; then
    /usr/bin/python3 -I -c 'import json, sys, pathlib
d = pathlib.Path(sys.argv[1])
own = json.loads((d / "project-rules.json").read_text()) if (d / "project-rules.json").exists() else []
print(json.dumps(own + [json.loads(p.read_text()) for p in sorted(d.glob("rule-*.json"))]))' $S
  else
    for f in $S/rule-*.json(N); do n=${f:t:r}; print -r -- ${n#rule-}; done
  fi ;;
'compute firewall-rules describe')
  [[ -f $S/rule-$4.json ]] || { print -r -- "ERROR: (gcloud.compute.firewall-rules.describe) Could not fetch resource: not found (stand-in)" >&2; exit 1; }
  [[ $args == *--format=json* ]] && cat $S/rule-$4.json || print -r -- $4 ;;
'compute firewall-rules create'|'compute firewall-rules update')
  [[ $3 == update && ! -f $S/rule-$4.json ]] && { print -r -- "ERROR: not found (stand-in)" >&2; exit 1; }
  /usr/bin/python3 -I -c 'import json, sys, pathlib
path = pathlib.Path(sys.argv[1]); verb = sys.argv[2]; opts = dict(a[2:].split("=", 1) for a in sys.argv[3:] if a.startswith("--") and "=" in a)
r = json.loads(path.read_text()) if verb == "update" else {"kind": "compute#firewall", "name": path.stem[5:], "direction": opts.get("direction", "INGRESS"),
     "priority": int(opts.get("priority", 1000)), "disabled": False,
     "network": "https://www.googleapis.com/compute/v1/projects/" + opts["project"] + "/global/networks/" + opts.get("network", "default")}
if "target-tags" in opts: r["targetTags"] = opts["target-tags"].split(",")
if "source-ranges" in opts: r["sourceRanges"] = opts["source-ranges"].split(",")
if "rules" in opts:
    entries = []
    for item in opts["rules"].split(","):
        proto, _, port = item.partition(":")
        entries.append({"IPProtocol": proto, **({"ports": [port]} if port else {})})
    r["denied" if opts.get("action") == "DENY" else "allowed"] = entries
path.write_text(json.dumps(r))' $S/rule-$4.json $3 "$@" ;;
'compute firewall-rules delete') rm -f $S/rule-$4.json; print -r -- "Deleted [stand-in rule]." ;;
'compute disks list') [[ -f $S/disk-left ]] && print -r -- $first ;;
'compute ssh '*)
  [[ -f $S/ssh-fail ]] && { print -r -- "ssh: connect to host: Operation timed out (stand-in)" >&2; exit 255; }
  [[ -f $S/instance ]] || { print -r -- "ERROR: no instance (stand-in)" >&2; exit 1; }
  case $cmd in
  *v650-ssh-ok*) print -r -- v650-ssh-ok ;;
  *provision.ps1*) print -r -- "== Git for Windows 2.47.1"; print -r -- "PROVISION PASS" ;;
  *setkey.ps1*)
    IFS= read -r line
    print -r -- "length=${#line} sha256=$(print -rn -- $line | shasum -a 256 | cut -d' ' -f1)" >> $S/stdin.log
    [[ -n $line ]] && print -r -- "KEY STORED for this Windows user as a User environment variable (length ${#line}); the value is not printed" \
      || { print -r -- "KEY FAIL: nothing arrived on stdin; nothing stored"; exit 1; } ;;
  *driver.cmd\ scan*) print -r -- 'SCAN PASS key checked, autologon password checked; replacements: {"<MODEL>": 2, "<VM_USER>": 3}; files 3'$'\r' ;;
  *autologon.ps1*)
    [[ -f $S/autologon-fail ]] && { print -r -- "AUTOLOGON FAIL: Set-LocalUser refused (stand-in)"; exit 1; }
    print -r -- "  password: a new random one set for the VM user (24 characters; not printed)"$'\r'
    print -r -- "  Winlogon: AutoAdminLogon 1; DefaultUserName is this user: True; DefaultDomainName is this computer: True; DefaultPassword set: True"$'\r'
    print -r -- "AUTOLOGON SET"$'\r'; touch $S/autologon ;;
  *shutdown\ /r*) touch $S/rebooted; print -r -- "" ;;
  *driver.cmd\ session*)
    if [[ -f $S/autologon && ! -f $S/no-session ]]; then
      print -r -- "SESSION line: <VM_USER> session console id 1 state Active"$'\r'; print -r -- "SESSION ACTIVE 1 console"$'\r'
    else
      print -r -- "SESSION line: No User exists for *"$'\r'; print -r -- "SESSION NONE"$'\r'
    fi ;;
  *driver.cmd\ cleanup\ *) c=${cmd##* }; print -r -- "CLEANUP $c: 0 leftover process(es) ended"$'\r'; print -r -- $c >> $S/cleanups.log ;;
  *driver.cmd\ schedule\ *)
    # schedule X <s>: the RESULT comes from $S/want-<X> (default PASS); without the console session it STOPs as the
    # driver does; hang-<X> never returns. Item lines in the driver's format.
    c=${${cmd#*driver.cmd schedule }%% *}
    print -r -- $c >> $S/schedules.log
    if [[ ! -f $S/autologon || -f $S/no-session ]]; then
      print -r -- "session of the VM user: NONE; query user: No User exists for *"$'\r'
      print -r -- "RESULT $c STOP the VM user has no Active console session (run step I first)"$'\r'; exit 2
    fi
    [[ -f $S/hang-$c ]] && { print -r -- "scheduled task v650-$c registered (stand-in); it never finishes"$'\r'; sleep 600; }
    v=$(cat $S/want-$c 2> /dev/null || print PASS)
    print -r -- "session of the VM user: ACTIVE 1 console (stand-in)"$'\r'
    print -r -- "scheduled task v650-$c registered (LogonType Interactive, RunLevel Highest) and started (stand-in)"$'\r'
    print -r -- "--- the task's console (out/$c/console.txt):"$'\r'
    print -r -- "CASE $c launcher: OBSERVED session 1 (console session 1); in a job True (Task Scheduler's: flags 0x3000 (SILENT_BREAKAWAY_OK, KILL_ON_JOB_CLOSE), active 1) (stand-in)"$'\r'
    if [[ $v != STOP* && $v != NO-TOOL-CALL* ]]; then
      # Two stand-in items per case in the driver's format (the real items are rehearsed by rehearse-driver.zsh).
      print -r -- "CASE $c first item: ${v%% *} (stand-in)"$'\r'
      print -r -- "CASE $c second item: OBSERVED (stand-in)"$'\r'
    fi
    print -r -- "RESULT $c $v"$'\r'
    [[ $v == STOP* ]] && exit 2 ;;
  *tar\ -xf*)   # upload: what arrived on stdin, listed; settings.json kept for the fake evidence
    rm -rf $S/up; mkdir -p $S/up; tar -xf - -C $S/up || exit 1
    (cd $S/up && find . -type f | sed 's|^\./||' | sort) > $S/upload.txt
    cp $S/up/v650/settings.json $S/uploaded-settings.json 2> /dev/null; rm -rf $S/up ;;
  *tar\ -cf*)   # fetch: the step's fake evidence (3 files) as a tar on stdout; tar-short drops one in transit
    step=${cmd##* }; d=$S/out; rm -rf $d; mkdir -p $d/$step/agents
    # Every scrub value the steps uploaded, as written and upper-cased, plus sample addresses and a version string.
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
print(" | ".join(v for _, v in pairs) + " | " + " | ".join(v.upper() for _, v in pairs))
print("ip 203.0.113.7 ipv6 2001:db8::7 loopback 127.0.0.1 build 10.0.20348.2700")' $S/uploaded-settings.json > $d/$step/console.txt
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
print(json.dumps({"values": [v for _, v in pairs]}))' $S/uploaded-settings.json > $d/$step/agents/record.json
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
open(sys.argv[2], "wb").write(" ".join(v for _, v in pairs).encode("utf-16-le"))' $S/uploaded-settings.json $d/$step/utf16.txt
    [[ -f $S/tar-short ]] && rm -f $d/$step/utf16.txt
    tar -cf - -C $d $step ;;
  *) print -r -- "stand-in: unknown remote command" >&2; exit 2 ;;
  esac ;;
'compute scp '*) print -r -- "stand-in: gcloud compute scp is not used by the steps any more" >&2; exit 4 ;;
config*) print -r -- "stand-in: gcloud config is never expected from the steps" >&2; exit 3 ;;
*) print -r -- "stand-in: unhandled: $*" >&2; exit 2 ;;
esac
exit 0
