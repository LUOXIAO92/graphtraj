#!/bin/zsh
# Task 640 rehearsal only: a gcloud stand-in for steps.zsh (VERIFY640_GCLOUD=<this file>). It records every argv
# (one line, quoted) and its environment, and simulates the commands the steps use. State lives in $TMPDIR/fake640/:
#   instance, fw              the Task VM / Task firewall rule exist
#   fail-create               instances create fails as a refused billing account would (gcloud-like error text)
#   open-ssh                  the network has a rule opening tcp:22 to everyone
#   ssh-fail                  compute ssh never answers
#   disk-left                 a disk named after the VM survives the delete (D must then FAIL)
# Logs: argv.log, env.log (names=values of each call's environment), stdin.log (for setkey: length and SHA-256 of
# what arrived on stdin, never the value). Fake evidence for scp downloads holds dummy values and a sample IP.
emulate -L zsh
setopt extended_glob
S=${TMPDIR:-/tmp}/fake640
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
'compute images list') print -r -- "windows-server-fake-dc-v20261111	X86_64	https://www.googleapis.com/compute/v1/projects/stand-in-images/global/images/windows-server-fake-dc-v20261111" ;;
'compute instances list')
  [[ -f $S/instance ]] && { [[ $args == *'value(status)'* ]] && print -r -- RUNNING || print -r -- $first; } ;;
'compute instances create')
  if [[ -f $S/fail-create ]]; then
    print -r -- "ERROR: (gcloud.compute.instances.create) Could not fetch resource:" >&2
    print -r -- " - Windows Server images are not available on free trial billing accounts (stand-in error text)" >&2
    exit 1
  fi
  touch $S/instance; print -r -- RUNNING ;;
'compute instances start') ;;
'compute instances delete') rm -f $S/instance; print -r -- "Deleted [stand-in instance]." ;;
'compute firewall-rules list')
  if [[ $args == *--format=json* ]]; then
    if [[ -f $S/open-ssh ]]; then
      print -r -- '[{"name": "default-allow-ssh", "network": "https://x/global/networks/stand-in-net", "direction": "INGRESS", "disabled": false, "sourceRanges": ["0.0.0.0/0"], "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]}]'
    else
      print -r -- '[]'
    fi
  else
    [[ -f $S/fw ]] && print -r -- $first
  fi ;;
'compute firewall-rules describe') [[ -f $S/fw ]] || { print -r -- "ERROR: not found" >&2; exit 1; }; print -r -- $3 ;;
'compute firewall-rules create') touch $S/fw ;;
'compute firewall-rules delete') rm -f $S/fw; print -r -- "Deleted [stand-in rule]." ;;
'compute disks list') [[ -f $S/disk-left ]] && print -r -- $first ;;
'compute ssh '*)
  [[ -f $S/ssh-fail ]] && { print -r -- "ssh: connect to host: Operation timed out (stand-in)" >&2; exit 255; }
  [[ -f $S/instance ]] || { print -r -- "ERROR: no instance (stand-in)" >&2; exit 1; }
  case $cmd in
  *v640-ssh-ok*) print -r -- v640-ssh-ok ;;
  *provision.ps1*) print -r -- "== Python 3.13.7"; print -r -- "PROVISION PASS" ;;
  *setkey.ps1*)
    IFS= read -r line
    print -r -- "length=${#line} sha256=$(print -rn -- $line | shasum -a 256 | cut -d' ' -f1)" >> $S/stdin.log
    [[ -n $line ]] && print -r -- "KEY STORED for this Windows user as a User environment variable (length ${#line}); the value is not printed" \
      || { print -r -- "KEY FAIL: nothing arrived on stdin; nothing stored"; exit 1; } ;;
  *drive640.py\ scan*) print -r -- 'SCAN PASS key checked; replacements: {"<MODEL>": 2, "<PROJECT>": 1}' ;;
  *drive640.py\ r0*) print -r -- "ITEM R0.answer PASS codex exec answered with PONG640"; print -r -- "RESULT R0 PASS" ;;
  *drive640.py\ run\ *) m=${cmd##* }; print -r -- "ITEM R1 PASS outcome completed (stand-in)"; print -r -- "RESULT R-$m PASS (PASS 1)" ;;
  *tar\ -*) ;;
  *) print -r -- "stand-in: unknown remote command" >&2; exit 2 ;;
  esac ;;
'compute scp '*)
  src=${@[-2]} dst=${@[-1]}
  if [[ $src == *:C:/v640/out/* ]]; then
    step=${src##*/}
    mkdir -p $dst/$step/agents
    # Every scrub value the steps uploaded, as written and upper-cased, plus sample addresses and a version string.
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
print(" | ".join(v for _, v in pairs) + " | " + " | ".join(v.upper() for _, v in pairs))
print("ip 203.0.113.7 ipv6 2001:db8::7 loopback 127.0.0.1 build 10.0.20348.2700")' $S/uploaded-settings.json > $dst/$step/console.txt
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
print(json.dumps({"values": [v for _, v in pairs]}).encode().decode())' $S/uploaded-settings.json > $dst/$step/agents/record.json
    /usr/bin/python3 -I -c 'import json, sys
pairs = json.load(open(sys.argv[1]))["scrub"]
open(sys.argv[2], "wb").write(" ".join(v for _, v in pairs).encode("utf-16-le"))' $S/uploaded-settings.json $dst/$step/utf16.txt
  else
    find $src -type f | sed "s|^${src:h}/||" | sort > $S/upload.txt
    cp $src/settings.json $S/uploaded-settings.json 2> /dev/null
  fi ;;
config*) print -r -- "stand-in: gcloud config is never expected from the steps" >&2; exit 3 ;;
*) print -r -- "stand-in: unhandled: $*" >&2; exit 2 ;;
esac
exit 0
