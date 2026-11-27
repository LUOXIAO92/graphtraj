#!/bin/zsh
# Task 650 rehearsal (Engineer) of the VM-side driver vm/drive650.py on macOS (POSIX branches; the Win32 facts read
# NOT-WINDOWS; the trace, job APIs and the scheduled task cannot run here):
#   - graftling cloned from a bundle of <Harness>/graftling dev, the candidate checked out (as provision.ps1 does);
#     the real graftling writes the Claude plugin files (configuration --write) and refuses the O4 context call and
#     the subagents CLI from a shell caller;
#   - every case through stand-in Runtimes (rehearsal/standin_runtime.py): PASS paths, NO-TOOL-CALL, no key (STOP),
#     a driver error (STOP driver error), schedule with and without a console session, cleanup of a planted leftover;
#   - the parsers on stand-in data and on REAL data: npm's summary line from Task 649's runner log (D1), and Task
#     649's real DSH --help text is not parsed (only saved);
#   - scan: the key and the autologon password planted in the evidence fail the scan without printing them; VM_USER
#     in a VM path is replaced.
# Settings values, the key and the password are RANDOM per run. Consoles: rehearsal/<round>/drv-NN-*.txt.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
HERE=${0:A:h:h}
OUT=$HERE/rehearsal/${1:-c1}
mkdir -p $OUT
rm -f $OUT/drv-*.txt(N)
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
PY=$HARNESS/.venv-runtime/bin/python   # has PyYAML and websockets (graftling's runtime needs); graftling from PYTHONPATH
CANDIDATE=0e5c92a602005ba0c0e53b887ff612dfd28180fd
REAL649=$HERE/../verify-649/evidence/run-45996884900-a1/dsh/npm-install.txt
TAG=$(openssl rand -hex 4)
H=$(mktemp -d ${TMPDIR:-/tmp}/v650drv.XXXXXX)
mkdir -p $H/home $H/venv/bin $H/venv/site $H/userhome
KEYENV=K${(U)TAG}_SHARED
KEYVAL=sk-dummy-$TAG-$(openssl rand -hex 16)
PASSWD=Pw-$(openssl rand -hex 12)
VMUSER=u$TAG
git -C $HARNESS/graftling bundle create -q $H/graftling.bundle refs/heads/dev
git clone -q --template= --no-checkout $H/graftling.bundle $H/home/graftling && git -C $H/home/graftling checkout -q --detach $CANDIDATE
ln -s $PY $H/venv/bin/python
print -r -- "#!/bin/sh
exec $PY -m graftling.cli \"\$@\"" > $H/venv/bin/subagents
chmod +x $H/venv/bin/subagents
cp $HERE/vm/mcp_probe.py $H/home/
$PY -I -c 'import json, sys
t, keyenv, user, cand = sys.argv[2:6]
pairs = [["<CLAUDE_MODEL>", f"cm-{t}-pro"], ["<PI_MODEL>", f"pm-{t}-chat"], ["<DSH_CHILD_MODEL>", f"dm-{t}-flash"],
         ["<KEY_ENV>", keyenv], ["<VM_USER>", user], ["<PI_KEY_VAR>", f"PK{t.upper()}_KEY"], ["<PI_PROVIDER>", "eepsee"],
         ["<DSH_MAIN_KEY_VAR>", f"DK{t.upper()}_KEY"], ["<CLAUDE_BASE_URL>", f"https://cl.h{t}.invalid/anth"]]
json.dump({"key_env": keyenv, "candidate": cand, "pins": {"claude": "2.1.314", "pi": "1.4.0", "dsh": "0.2.2-rc.5", "pnpm": "12.21.0"},
           "claude": {"base_url": f"https://cl.h{t}.invalid/anth", "auth_var": "ANTHROPIC_AUTH_TOKEN", "model": f"cm-{t}-pro",
                      "haiku": "", "sonnet": "", "opus": "", "subagent": "", "api_timeout_ms": ""},
           "pi": {"route": "builtin", "provider": "eepsee", "model": f"pm-{t}-chat", "key_var": f"PK{t.upper()}_KEY", "base_url": "", "api": ""},
           "dsh_child": {"model": f"dm-{t}-flash", "provider": "", "base_url": ""},
           "dsh_main": {"key_var": f"DK{t.upper()}_KEY", "base_url": "", "app_args": []}, "scrub": pairs},
          open(sys.argv[1], "w"))' $H/home/settings.json $TAG $KEYENV $VMUSER $CANDIDATE
BASE=(env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$H/home/graftling/src V650_HOME=$H/home V650_VENV=$H/venv HOME=$H/userhome
      V650_PASSWORD=$PASSWD $KEYENV=$KEYVAL USER=${USER:-} PYTHONUTF8=1 PATH=/usr/bin:/bin:/usr/sbin:/sbin)
SA=(V650_STANDIN=$HERE/rehearsal/standin_runtime.py)
DRV=$HERE/vm/drive650.py
N=0
typeset -a SUMMARY
run() {  # run <name> <expect substring> <env/command...>
  local name=$1 expect=$2; shift 2
  (( N++ ))
  local file=$OUT/drv-$(printf %02d $N)-$name.txt
  print -r -- "\$ ${(j: :)${@:#*=*}}" | sed "s|$DRV|vm/drive650.py|g; s|$PY|<python>|g; s|${H:A}|<tmp>|g; s|$H|<tmp>|g;
    s|$HERE|scripts/verify-650|g; s|$VMUSER|<VM_USER>|g" > $file
  "$@" 2>&1 | sed "s|${H:A}|<tmp>|g; s|$H|<tmp>|g; s|$PY|<python>|g; s|$HARNESS|<harness>|g" \
    | sed -E "s#/Users/[^ '\\\";),]*#<mac-path>#g" >> $file   # scratch paths <tmp>; other Mac paths <mac-path>
  print -r -- "(exit ${pipestatus[1]})" >> $file
  local ok=no; grep -q -F -- "$expect" $file && ok=yes
  SUMMARY+="drv-$(printf %02d $N) $name: expects '$expect' -> $ok"
}
run npm-summary-real-649 "added 670 packages in 14m" $BASE $PY -I -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("d", sys.argv[1]); d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
print("npm_added (real 649 runner log):", d.npm_added(open(sys.argv[2], encoding="utf-8", errors="replace").read()))
print("npm_added (none):", d.npm_added("npm ERR! code E404"))' $DRV $REAL649
run parsers-stand-in-data "parsers: init ['graftling=connected'], uses 2, results 1, models ['m1'], subagent calls 2, models_in ['pm', 'pm2'], records 1" $BASE $PY -I -c 'import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("d", sys.argv[1]); d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
stream = "\n".join(json.dumps(e) for e in [
  {"type": "system", "subtype": "init", "mcp_servers": [{"name": "graftling", "status": "connected"}, {"name": "x", "status": "failed"}]},
  {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "a", "name": "mcp__graftling__subagents", "input": {}},
                                               {"type": "tool_use", "id": "b", "name": "Bash", "input": {}}]}},
  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": "unsupported-runtime"}]}]}},
  {"type": "result", "result": "done", "modelUsage": {"m1": {}}}]) + "\nnot json\n"
c = d.claude_stream(stream)
events = d.json_events("\n".join(json.dumps(e) for e in [{"type": "x", "toolName": "mcp__graftling__subagents"},
  {"message": {"model": "pm", "content": [{"name": "subagents"}]}}, {"model": "pm2"}]))
import tempfile, pathlib
root = pathlib.Path(tempfile.mkdtemp()); (root / "control/agents").mkdir(parents=True)
(root / "control/agents/a.json").write_text(json.dumps({"runtime": "dsh", "executions": [{"last_result": {"outcome": "completed", "last_message": "T-1"}}]}))
print("parsers: init", d.mcp_status(c["init"], "graftling"), end=", ")
print("uses", len(c["uses"]), end=", "); print("results", len(c["results"]), end=", "); print("models", c["models"], end=", ")
print("subagent calls", d.subagent_calls(events), end=", "); print("models_in", d.models_in(events), end=", ")
print("records", len(d.agent_records(root)))
print("child_answer:", d.child_answer(d.agent_records(root), "T-1"))' $DRV
run venv "RESULT venv PASS" $BASE $SA $PY $DRV case venv
run r0 "RESULT r0 PASS" $BASE $SA $PY $DRV case r0
run claude "RESULT claude PASS" $BASE $SA $PY $DRV case claude
run claude-no-tool-call "RESULT claude NO-TOOL-CALL" $BASE $SA V650_STANDIN_MODE=no-tool $PY $DRV case claude
run claude-refuse "RESULT claude-refuse PASS" $BASE $SA $PY $DRV case claude-refuse
run claude-caller-real-graftling-refusals "RESULT claude-caller FAIL (O4 context from a Bash-tool caller)" $BASE $SA $PY $DRV case claude-caller
run claude-probe "expanded with the variable" $BASE $SA $PY $DRV case claude-probe
run claude-market "RESULT claude-market PASS" $BASE $SA $PY $DRV case claude-market
run pi "RESULT pi PASS" $BASE $SA $PY $DRV case pi
run pi-refuse "RESULT pi-refuse PASS" $BASE $SA $PY $DRV case pi-refuse
run pi-refuse-no-tool-call "RESULT pi-refuse NO-TOOL-CALL" $BASE $SA V650_STANDIN_MODE=no-tool $PY $DRV case pi-refuse
run pi-caller-real-graftling-cli "RESULT pi-caller FAIL (H7 caller under Pi's bash tool refused)" $BASE $SA $PY $DRV case pi-caller
run pi-nonascii "RESULT pi-nonascii PASS" $BASE $SA $PY $DRV case pi-nonascii
run pi-kill "RESULT pi-kill PASS" $BASE $SA $PY $DRV case pi-kill
run dsh "RESULT dsh PASS" $BASE $SA $PY $DRV case dsh
run dsh-nonascii "RESULT dsh-nonascii PASS" $BASE $SA $PY $DRV case dsh-nonascii
run dsh-stop "RESULT dsh-stop PASS" $BASE $SA $PY $DRV case dsh-stop
run dsh-kill "RESULT dsh-kill PASS" $BASE $SA $PY $DRV case dsh-kill
print -r -- " USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
>${USER:-x}               console             1  Active      none   11/27/2026 9:00 AM" > $H/quser.txt
run schedule-claude-refuse "RESULT claude-refuse PASS" $BASE $SA V650_QUSER_FILE=$H/quser.txt $PY $DRV schedule claude-refuse 120
run schedule-no-session "RESULT claude STOP the VM user has no Active console session" $BASE $SA $PY $DRV schedule claude 120
run no-key "RESULT pi STOP the key variable is not set" env PYTHONPATH=$H/home/graftling/src V650_HOME=$H/home V650_VENV=$H/venv HOME=$H/userhome $SA $PY $DRV case pi
run driver-error "RESULT dsh STOP driver error" $BASE V650_STANDIN=$H/no-such-standin.py $PY $DRV case dsh
/bin/sleep 6502 &
run cleanup-planted-leftover "CLEANUP dsh-kill: 1 leftover" $BASE $SA $PY $DRV cleanup dsh-kill
mkdir -p $H/home/out/claude/agents-control
print -r -- "work dir C:\\Users\\$VMUSER\\AppData\\Roaming\\uv\\tools\\graftling" > $H/home/out/claude/agents-control/path.txt
run scan-clean-vm-user-replaced "SCAN PASS" $BASE $PY $DRV scan claude
run scan-no-vm-user-left "count 0" $BASE /usr/bin/python3 -I -c 'import sys, pathlib; print("count", sum(sys.argv[2].lower() in p.read_text(errors="replace").lower() for p in pathlib.Path(sys.argv[1]).rglob("*") if p.is_file()))' $H/home/out/claude $VMUSER
# Correction 1: the dummy PI_PROVIDER (a substring of the protected DSH scope token) beside DSH package paths, in UTF-8
# and UTF-16-LE: the scan keeps every package path byte for byte and replaces every other occurrence of the dummy.
/usr/bin/python3 -I -c 'import sys, pathlib
lines = [r"node C:\npm\node_modules\@deepseek-ai\dsh\lib\bin.js", "@DeepSeek-AI/dsh@0.2.2-rc.5",
         "https://registry.npmjs.org/@deepseek-ai%2fdsh", r"C:\npm\node_modules\@DEEPSEEK-AI\dsh\package.json",
         "provider eepsee EEPSEE_API_KEY eepsee-official Eepsee"]
d = pathlib.Path(sys.argv[1]); (d / "pkg.txt").write_text("\n".join(lines) + "\n"); (d / "pkg16.txt").write_bytes("\n".join(lines).encode("utf-16-le"))
(d / "pkg.orig").write_text("\n".join(lines[:4]) + "\n")' $H/home/out/claude/agents-control
run scan-keeps-dsh-package-paths "SCAN PASS" $BASE $PY $DRV scan claude
run package-paths-intact-dummy-gone "paths intact True True; dummy left outside protected names 0 0; placeholders 4 4" /usr/bin/python3 -I -c 'import pathlib, re, sys
d = pathlib.Path(sys.argv[1]); orig = (d / "pkg.orig").read_text().splitlines()
one = (d / "pkg.txt").read_text(); two = (d / "pkg16.txt").read_bytes().decode("utf-16-le")
left = [len(re.findall("eepsee", re.sub("(?i)deepseek-ai", "", t), re.I)) for t in (one, two)]
print("paths intact", all(o in one for o in orig), all(o in two for o in orig), end="; ")
print("dummy left outside protected names", *left, end="; ")
print("placeholders", one.count("<PI_PROVIDER>"), two.count("<PI_PROVIDER>"))
print(one.splitlines()[-1])' $H/home/out/claude/agents-control
rm -f $H/home/out/claude/agents-control/pkg*
print -r -- "leaked $KEYVAL" > $H/home/out/claude/agents-control/leak.txt
run scan-finds-planted-key "SCAN FAIL the key or the autologon password is in 1 file(s)" $BASE $PY $DRV scan claude
rm -f $H/home/out/claude/agents-control/leak.txt
print -r -- "leaked $PASSWD" > $H/home/out/claude/agents-control/leak.txt
run scan-finds-planted-password "SCAN FAIL the key or the autologon password is in 1 file(s)" $BASE $PY $DRV scan claude
rm -f $H/home/out/claude/agents-control/leak.txt
pth=$(ls $H/venv/site 2> /dev/null | wc -l | tr -d ' ')
leaks=$(grep -l -F -e $KEYVAL -e $PASSWD -e $VMUSER -e $TAG $OUT/drv-*.txt 2> /dev/null | wc -l | tr -d ' ')
home=$(grep -l -e '/Users/' $OUT/drv-*.txt 2> /dev/null | wc -l | tr -d ' ')
{
  print -r -- "Task 650 driver rehearsal (macOS, stand-in Runtimes; random dummy settings, key and password; consoles drv-01-$(printf %02d $N) in ${OUT:t}/)"
  print -lr -- $SUMMARY
  print -r -- "record .pth files left in the venv's site directory after all cases: $pth"
  print -r -- "consoles holding the dummy key, password, VM user or settings tag: $leaks; consoles holding a /Users/ path: $home"
} | tee $OUT/drv-00-summary.txt
pkill -f 'sleep 650[123]' 2> /dev/null
rm -rf $H
