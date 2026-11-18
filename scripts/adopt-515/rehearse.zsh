#!/bin/zsh
# Rehearsal of adopt-515/steps.zsh from an EMPTY base (514 retro) against a fake production tree in $TMPDIR.
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Fake production: graphtraj wheel of 6115c724 + graftling wheel of the REAL <Harness>/graftling tag v0.5.2 (read only,
# git archive), i.e. what 503 installed. B reads the real tag v0.6.0 (read only). Steps not changed from 503 (Nw, N,
# Nt, N484, T, Mps, inbox, the 499/498 Nr helpers) are covered by adopt-503's rehearsal and not rerun here.
#   zsh scripts/adopt-515/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt515-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/515
OB=$FH/tmp/503   # 503's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
REALG=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
OLD=6115c72491a238cc672d88ec539cda800e4c3651
NEW=4ad22e9065cf38bc3c976eed184d29b1a299413a
export ADOPT515_H=$FH ADOPT515_BASE=$FB ADOPT515_RT=$FRT ADOPT515_PNPM_SHIM=$F/no-shim ADOPT515_STUB=$F/stub ADOPT515_WT=$WT ADOPT515_PROJECTS=$F/projects/-fake ADOPT515_WAIT=1 ADOPT515_OLDBASE=$OB ADOPT515_G=$REALG ADOPT515_VPROJECT=$FB/vproject
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=515-production-adoption-mcp-server-names
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-4ad22e90
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "empty base: $F removed; zsh -n of every zsh file"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldg $F/oldwheels $FH $OB/backup $F/projects/-fake
for z in $SD/*.zsh; do zsh -n $z; check "zsh -n ${z:t}" [ $? -eq 0 ]; done
check "base $FB absent before 00" [ ! -e $FB ]

head1 "setup: fake production = graphtraj $OLD + graftling v0.5.2 (real repository, git archive), plugin, configuration"
# Stub claude: -p answers the isolation prompt's tag; its init lists the MCP servers of ./.mcp.json (or --mcp-config).
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "2.1.325 (stub Claude Code)" ;;
  plugin) print "✔ Validation passed (stub)" ;;
  -p) in=$(cat); tag=$(print -r -- "$in" | sed -n 's/.*Line 1: \([A-Z-]*\) followed.*/\1/p')
      /Users/luoxiao/miniconda3/bin/python3.13 -I -c '
import json, os
try: servers = sorted((json.load(open(".mcp.json")).get("mcpServers") or {}))
except Exception: servers = []
tools = ["Bash"] + [f"mcp__{s}__{t}" for s in servers for t in ("agents", "tasks")]
print(json.dumps({"type": "system", "subtype": "init", "plugins": [], "mcp_servers": [{"name": s, "status": "connected"} for s in servers], "tools": tools, "plugin_warnings": []}))'
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-515-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $OLD | tar -x -C $F/oldsrc
git -C $REALG archive v0.5.2 | tar -x -C $F/oldg
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldg/src/graftling
ls $F/oldwheels
git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
$CONDA -m venv $FRT
$FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
D=$FRT/lib/python3.13/site-packages
cp -Rp $CSITE/click $CSITE/click-*.dist-info(N) $CSITE/yaml $CSITE/_yaml(N) $CSITE/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/
mkdir -p $D/websockets/asyncio $D/websockets/sync $D/websockets-16.1.1.dist-info
print -l 'Metadata-Version: 2.1' 'Name: websockets' 'Version: 16.1.1' > $D/websockets-16.1.1.dist-info/METADATA; : > $D/websockets-16.1.1.dist-info/RECORD; print '__version__ = "0.0-stub"' > $D/websockets/__init__.py
for m in client frames http http11 protocol uri exceptions asyncio/__init__ asyncio/client sync/__init__ sync/client; do
  print -l 'class _S:' '    def __init__(self, *a, **k): pass' \
    'ClientProtocol = Frame = Opcode = ConnectionClosed = _S' 'OPEN = 1' 'Request = Response = _S' 'def connect(*a, **k): raise OSError("stub")' 'def parse_uri(u): return u' > $D/websockets/$m.py
done
(cd $FH && print y | $FRT/bin/graphtraj setup) | tail -2
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
# Main-owned settings as in production (Main's read-only report): both names enabled, all project servers enabled.
$CONDA -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["enabledMcpjsonServers"]=["graphtraj","agents"]; d["enableAllProjectMcpServers"]=True; open(p,"w").write(json.dumps(d, indent=2)+"\n")' $FH/.claude/settings.local.json
print "fake production .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json)"
mkdir -p $ST/$TASK/definitions $ST/$TASK/teams/1; cp $WT/.state/task.yml $ST/$TASK/; print 'stopped: false' > $ST/$TASK/execution-budget.yml
def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
for f in $WT/.state/task.md ${def:+$WT/.state/$def}; do   # dependencies and parent removed: the fake state has no other Tasks
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $ST/$TASK/${f#$WT/.state/}
done
print "503 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/503 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
MAINID=11111111-2222-3333-4444-555555555555
: > $F/projects/-fake/$MAINID.jsonl
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
print -l "# Fake Harness rules" "This distinctive Harness instruction line must never reach the isolated project answer." > $FH/AGENTS.md
cat > $F/stub/ps <<EOF2
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
if [[ "\$*" == *"lstart="* ]]; then exit 0; fi
if [[ "\$*" == *"stat="* ]]; then exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF2
chmod +x $F/stub/ps
print -r -- "$HOSTLINE" > $F/ps.txt
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256

head1 "00 (Main found through claude --continue; production markers absent; .mcp.json 'agents' listed; settings shown)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|\.mcp.json servers|enabledMcpjsonServers|isolation:|answer check|Claude Code installed|CHECK 515)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: 515 markers absent in production (7/7)" grep -q 'markers expected absent: PASS (7/7)' $F/00.out
check "00: .mcp.json shows the old 'agents' server (information) and the settings view" sh -c "grep -q \"^.mcp.json servers: \['agents'\]\" $F/00.out && grep -q \"^enabledMcpjsonServers: \['graphtraj', 'agents'\]\" $F/00.out"
check "00: the pre-install .mcp.json is a state line ('not yet'), never a CHECK/FAIL line" sh -c "grep -q '^state before I (not a check.*): .mcp.json has only graphtraj: not yet' $F/00.out && ! grep -q '^CHECK 515 .mcp.json' $F/00.out && ! grep -q '^CHECK.*FAIL' $F/00.out"
check "00: isolated vproject OK and answer check OK" sh -c "grep -q '^isolation: OK' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out"
check "00 next is B with the real path" grep -q "next.*: zsh $SD/steps.zsh B" $F/00.out

head1 "B (graftling from git archive v0.6.0 of the real repository; graphtraj from git archive $NEW)"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked|peels|wheel version|Requires|carries' $F/B.out
check "B: v0.6.0 peels to a51e1004…, graftling 0.6.0, Requires-Dist graftling<0.7,>=0.6.0, carries 0, leaked 0" sh -c "grep -q 'v0.6.0 peels to a51e1004a0fe77fe492681faa2f278d80b3d725e…: yes' $F/B.out && grep -q '^graftling wheel version: 0.6.0' $F/B.out && grep -q '^graphtraj Requires-Dist: graftling<0.7,>=0.6.0' $F/B.out && grep -q 'graphtraj wheel carries graftling/: 0 files' $F/B.out && grep -q '^leaked: 0' $F/B.out"
ADOPT515_GCOMMIT=deadbeef steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the expected commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.0^{commit} is .*, not deadbeef' $F/B-tag.out"
steps B > /dev/null 2>&1

head1 "V (stub plugin validate): plugin change limited to SERVER/PREFIX; wheel = archive; CODE listed; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|plugin bytes change|CHECK 515|graftling wheel vs|515 graftling CODE|markers expected|503 layout|node resolves' $F/V.out
check "V: host_context.mjs CHANGED, only const SERVER/PREFIX (and version) lines" sh -c "grep -q '^CHANGED hooks/host_context.mjs' $F/V.out && grep -q 'lines other than const SERVER/PREFIX and \"version\": 0' $F/V.out"
check "V: candidate SERVER graphtraj PASS" grep -q 'CHECK 515 candidate host_context.mjs const SERVER = "graphtraj": PASS' $F/V.out
check "V: graftling wheel = git archive v0.6.0 (differing 0: SAME); CODE files 0.5.2 -> 0.6.0 listed, not a STOP" sh -c "grep -q 'graftling wheel vs .*differing 0: SAME' $F/V.out && grep -q '515 graftling CODE files 0.5.2 -> 0.6.0 (expected; information): [1-9]' $F/V.out && ! grep -q '^STOP' $F/V.out"
check "V: markers present in the candidate and absent in production (7/7)" sh -c "grep -q 'markers expected present: PASS (7/7)' $F/V.out && grep -q 'markers expected absent: PASS (7/7)' $F/V.out"
check "V: one graftling and node resolution in the scratch venv" sh -c "grep -q '^503 layout: PASS' $F/V.out && [ \$(grep -c 'node resolves .*: PASS' $F/V.out) -ge 2 ]"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
check "V next is S" grep -q "next.*: zsh $SD/steps.zsh S" $F/V.out

head1 "graftcode negative: a wheel file that differs from the archive STOPs"
GW=($W/wheels-4ad22e90/graftling-*.whl); rm -rf $F/gneg; mkdir -p $F/gneg/src; cp -Rp $W/gsrc-0.6.0/src/graftling $F/gneg/src/
print '# changed after the tag' >> $F/gneg/src/graftling/control.py
$CONDA -I $SD/graftcode.py $GW[1] $D $F/gneg/src > $F/gcneg.out 2>&1; GN=$?
check "graftcode negative: exit 1, WHEEL-DIFFERS control.py, STOP" sh -c "[ $GN -eq 1 ] && grep -q 'WHEEL-DIFFERS graftling/control.py (bytes differ)' $F/gcneg.out && grep -q 'differing 1: STOP' $F/gcneg.out"

head1 "markers negatives"
check "markers 'present' on production fails" sh -c "! $CONDA -I $SD/markers.py $D present > /dev/null"
VS=($FB/vvenv-4ad22e90/lib/python*/site-packages(N))
check "markers 'absent' on the candidate fails" sh -c "! $CONDA -I $SD/markers.py $VS[1] absent > /dev/null"

head1 "S: reused suite evidence; no src change 142bdd8e..$NEW"
steps S > $F/S.out 2>&1; check "S exit 0" [ $? -eq 0 ]; grep -E 'CHECK|reused|pytest' $F/S.out
check "S: no src change PASS, 3587 passed and 4 passed printed, no pytest run" sh -c "grep -q 'CHECK 515 no src change between .*: PASS' $F/S.out && grep -q '3587 passed' $F/S.out && grep -q '4 passed' $F/S.out && grep -q 'pytest: none run' $F/S.out"

head1 "Vu / Vc (stub claude: plugin not loaded, so Vc asks for Vu; its setup must show only graphtraj in the isolated .mcp.json)"
steps Vu > $F/Vu.out 2>&1
check "Vu names the isolated path, 'Yes, proceed', /exit and graphtraj" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out && grep -q \"MCP server 'graphtraj'\" $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc setup: isolated .mcp.json has graphtraj only (CHECK PASS) and answer check OK" sh -c "grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc stream init (stub) lists graphtraj only and the new tools" sh -c "grep -q 'CHECK 515 init mcp server graphtraj only: PASS' $RW/Vc.txt && grep -q 'CHECK 515 init no mcp__agents__\* tool: PASS' $RW/Vc.txt"
check "Vc with the stub does not pass (no real plugin load) and asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok   # rehearsal only: the real plugin load is not rehearsable

head1 "I (USER): guard idle, backup, install, configuration --write, 515 CHECKs, settings not written, restart text"
steps Mpre > $F/Mpre.out 2>&1
: > $F/ps.txt   # Main has exited
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|CHECK 515|configuration --write rc|plugin bytes|SAME-AS-VALIDATED|markers expected|changed:|bytes unchanged|enabledMcpjson' $F/I.out
check "I: installed graftling 0.6.0, proddiff PASS, markers present 7/7" sh -c "grep -q 'Successfully installed graftling-0.6.0' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'markers expected present: PASS (7/7)' $F/I.out"
check "I: configuration --write rc=0, .mcp.json CHECK PASS, SERVER CHECK PASS, SAME-AS-VALIDATED" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/I.out && grep -q 'CHECK 515 host_context.mjs const SERVER = \"graphtraj\": PASS' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out"
check "I: .mcp.json now has graphtraj only" sh -c "$CONDA -I -c 'import json,sys; s=sorted(json.load(open(sys.argv[1]))[\"mcpServers\"]); sys.exit(0 if s==[\"graphtraj\"] else 1)' $FH/.mcp.json"
check "I: settings.local.json bytes unchanged (enabledMcpjsonServers still lists agents; Main edits it)" sh -c "grep -q 'CHECK 515 settings.local.json bytes unchanged by configuration --write: PASS' $F/I.out && grep -q '\"agents\"' $FH/.claude/settings.local.json"
check "I: backup holds .mcp.json, settings.local.json, plugin, tools; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/entries/.claude__settings.local.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/rec515.py ]"
check "I: prints Main's settings edit, the restart command and the expected hooks dialog" sh -c "grep -q 'enabledMcpjsonServers 只保留 \[\"graphtraj\"\]' $F/I.out && grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '插件/hooks 信任框' $F/I.out"

head1 "M / Mp (after the restart): prompt names the new tools; probe init must list graphtraj only"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt names mcp__graphtraj__agents/tasks and asks about mcp__agents__*" sh -c "grep -q 'your GraphTraj tools are now mcp__graphtraj__agents and mcp__graphtraj__tasks' $F/M.out && grep -q 'starts with mcp__agents__' $F/M.out && grep -q \"next.*: zsh $SD/steps.zsh Mp\" $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?; grep -E 'CHECK|init' $F/Mp.out
check "Mp exit 0: four init CHECKs PASS (stub reads the Harness .mcp.json), none FAIL" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ] && ! grep -q 'FAIL' $RW/Mp.txt"
print -rl -- '{"type":"system","subtype":"init","mcp_servers":[{"name":"graphtraj","status":"connected"},{"name":"agents","status":"connected"}],"tools":["mcp__graphtraj__agents","mcp__graphtraj__tasks","mcp__agents__agents"],"plugin_warnings":[{"plugin":"graphtraj-claude-host","message":"untrusted"}]}' > $F/init-neg.jsonl
$CONDA -I $SD/rec515.py init $F/init-neg.jsonl > $F/init-neg.out 2>&1; INR=$?
check "rec515 init negative: second server, old tool and untrusted warning FAIL" sh -c "[ $INR -ne 0 ] && grep -q 'mcp server graphtraj only: FAIL' $F/init-neg.out && grep -q 'no mcp__agents__\* tool: FAIL' $F/init-neg.out && grep -q 'no untrusted-plugin warning: FAIL' $F/init-neg.out"

head1 "rec515 calls on Claude record shapes (graftling archive events and Claude transcript lines)"
mkdir -p $F/rec
# Positive: archive event shape (data.content) with an ok result whose text contains 'not available' (514's misjudged shape).
print -rl -- '{"header":{"id":"claude:aaaa"}}' \
  '{"type":"assistant/message","data":{"content":[{"type":"tool_use","id":"t1","name":"mcp__graphtraj__agents","input":{"action":"execute"}}]}}' \
  '{"type":"user/message","data":{"content":[{"type":"tool_result","tool_use_id":"t1","content":[{"type":"text","text":"{\"agents\":[], \"note\":\"model not available\"}"}]}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"mcp__graphtraj__tasks","input":{}}]}}' \
  '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t2","content":"features: x"}]}}' > $F/rec/pos.jsonl
$CONDA -I $SD/rec515.py calls pos --need agents,tasks $F/rec/pos.jsonl > $F/rec-pos.out 2>&1; check "rec515 calls positive (ok despite 'not available' in content)" [ $? -eq 0 ]
print -rl -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t3","name":"mcp__agents__agents","input":{}}]}}' > $F/rec/old.jsonl
$CONDA -I $SD/rec515.py calls old --need agents $F/rec/pos.jsonl $F/rec/old.jsonl > $F/rec-old.out 2>&1; RO=$?
check "rec515 calls negative: an old-name call FAILs" sh -c "[ $RO -ne 0 ] && grep -q 'no mcp__agents__\* call: FAIL (1)' $F/rec-old.out"
print -rl -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t4","name":"mcp__graphtraj__agents","input":{}}]}}' \
  '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t4","is_error":true,"content":"Claude requested permissions to use mcp__graphtraj__agents, but you haven'"'"'t granted it yet."}]}}' > $F/rec/refused.jsonl
$CONDA -I $SD/rec515.py calls ref --need agents $F/rec/refused.jsonl > $F/rec-ref.out 2>&1; RR=$?
check "rec515 calls negative: a refused agents call FAILs and shows the refusal text" sh -c "[ $RR -ne 0 ] && grep -q 'errors/refusals 1' $F/rec-ref.out && grep -q \"haven't granted\" $F/rec-ref.out"

head1 "Rs / Rsr: standby Leader and Engineer Sessions; only records after Rs count"
SESSD=$FH/.graphtraj/swarm/sessions; RUN=$FH/.graphtraj/core/runner/sessions
LA=515-production_adoption_mcp_server_names-handover0-team_leader@team_leader; EA=515-production_adoption_mcp_server_names-handover0-engineer@engineer
for a in ${LA}:bbbb ${EA}:cccc; do   # braces: a bare $EA:c would be zsh's :c modifier
  mkdir -p $RUN/${a%%:*} $SESSD/s-${a#*:}; print "session: claude:${a#*:}" > $RUN/${a%%:*}/mapping.yml
  print -rl -- "{\"header\":{\"id\":\"claude:${a#*:}\"}}" '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"old1","name":"mcp__agents__agents","input":{}}]}}' > $SESSD/s-${a#*:}/session.jsonl
done
print -r -- $LA > $RW/Rs-leader.txt; print -r -- $EA > $RW/Rs-engineer.txt   # task members of the fake venv lists none
steps Rs > $F/Rs.out 2>&1; RSR=$?
check "Rs exit 0: leader alias in Main's prompt, sizes of 2 archives recorded" sh -c "[ $RSR -eq 0 ] && grep -q \"send to the retained Session $LA\" $F/Rs.out && grep -q 'recorded sizes of 2 record file' $F/Rs.out && grep -q 'DONE-515-RESUMED' $F/Rs.out"
print -rl -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"l1","name":"mcp__graphtraj__agents","input":{}}]}}' '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"l1","content":"ok"}]}}' >> $SESSD/s-bbbb/session.jsonl
print -rl -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"e1","name":"mcp__graphtraj__agents","input":{}},{"type":"tool_use","id":"e2","name":"mcp__graphtraj__tasks","input":{}}]}}' '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"e1","content":"ok"},{"type":"tool_result","tool_use_id":"e2","content":"ok"}]}}' >> $SESSD/s-cccc/session.jsonl
steps Rsr > $F/Rsr.out 2>&1; RSRR=$?; grep -E '^CHECK|record files' $F/Rsr.out
check "Rsr exit 0: new-name calls after Rs ok; the old-name call before Rs is not counted" sh -c "[ $RSRR -eq 0 ] && [ \$(grep -c 'CHECK 515 .*: PASS' $RW/Rsr.txt) -eq 5 ] && ! grep -q 'FAIL' $RW/Rsr.txt"
print -rl -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"e3","name":"mcp__agents__tasks","input":{}}]}}' >> $SESSD/s-cccc/session.jsonl
steps Rsr > $F/Rsr-neg.out 2>&1; RSN=$?
check "Rsr negative: an old-name call after Rs FAILs" sh -c "[ $RSN -ne 0 ] && grep -q 'engineer .*no mcp__agents__\* call: FAIL (1)' $F/Rsr-neg.out"

head1 "468 window report (fixture samples; not blocking)"
T0=$(date +%s); mkdir -p $F/cpu
for i in 0 1 2 3 4 5 6; do
  at=$(( T0 + i * 10 )); run=$([[ $i -ge 3 ]] && print true || print null); cpu=$(( i < 3 ? i * 9 : 18 + (i - 3) ))
  print -r -- "{\"at\": $at, \"child_running\": $run, \"ps\": \"6161 1 1.0 0:$(printf %02d $cpu).00 01:00 python -m graphtraj.execution.runner_worker\"}"
done > $F/cpu/Nw468-ps.txt
$CONDA -I $SD/cpu468.py window $F/cpu > $F/cpu.out 2>&1; cat $F/cpu.out
check "468 window: before 0.600 (18 s over 30 s) and after 0.100 CPU-s per wall-s reported" sh -c "grep -q 'before child creation: 0.600' $F/cpu.out && grep -q 'after child creation: 0.100' $F/cpu.out"

head1 "R (rollback from the backup's own tools): venv, plugin, .mcp.json and settings restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version' $F/R.out
check "R exit 0; venv and plugin SAME; entry files restored and OK" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ] && grep -q 'restored: .mcp.json' $F/R.out"
check "R: archive code compared before the restore (graftling/sessions 0.5.2 vs 0.6.0: 0 differing files); no 'same code' claim" sh -c "grep -q 'graftling/sessions (archive writer/reader) installed vs backup: 0 differing files' $F/R.out && ! grep -q 'same code' $F/R.out"
check "I/R texts carry no stale 0.5.0 version" sh -c "! grep -q '0\.5\.0' $F/I.out && ! grep -q '0\.5\.0' $F/R.out && grep -q 'pip 卸载 graftling-0.5.2' $F/I.out && grep -q \"395 layout graftling 0.6.0 .*>=0.6.0\" $F/I.out"
check "R: production .mcp.json is 'agents' again and graftling is 0.5.2" sh -c "$CONDA -I -c 'import json,sys; s=sorted(json.load(open(sys.argv[1]))[\"mcpServers\"]); sys.exit(0 if s==[\"agents\"] else 1)' $FH/.mcp.json && $FRT/bin/python -m pip show graftling | grep -q 'Version: 0.5.2'"
check "503's backup under tmp/503 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"

head1 "done: no exported key value in raw files"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
