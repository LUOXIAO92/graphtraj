#!/bin/zsh
# Rehearsal of adopt-528/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (copied from adopt-525's).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Fake production: graphtraj wheel of 8267f9e5 + graftling wheel of the REAL <Harness>/graftling tag v0.6.1 (read only,
# git archive), i.e. what 525 installed; click, yaml and websockets copied from production .venv-runtime (read only).
# B reads the REAL annotated tag v0.6.2 of <Harness>/graftling (read only; Main created it on the phase-A commit
# 4a002129); no tag is created anywhere. G runs through the same entry with
# VERIFY528_TESTS=tests/test_agent_runner_cleanup.py (real tests using the repository's conftest fixtures).
#   zsh scripts/adopt-528/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt528-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/528
OB=$FH/tmp/525   # 525's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=${REHEARSE528_G:-$REALH/graftling}
GC=4a002129f8b97f32980afd59e5a1a64c428fe684
G61=483b16a8d6e05b1c866e69439fada8478791f1fb
NEW=8267f9e5a89dd8f504e5da916e6102b4bbff23c3
export ADOPT528_H=$FH ADOPT528_BASE=$FB ADOPT528_RT=$FRT ADOPT528_PNPM_SHIM=$F/no-shim ADOPT528_STUB=$F/stub ADOPT528_WT=$WT ADOPT528_PROJECTS=$F/projects/-fake ADOPT528_WAIT=1 ADOPT528_OLDBASE=$OB ADOPT528_G=$REALG ADOPT528_VPROJECT=$FB/vproject ADOPT528_KNOWN=$REALH/.graphtraj/core/state/tasks
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=528-production-adoption-graftling-0-6-2
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-8267f9e5
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "empty base: $F removed; zsh -n of every zsh file"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldg $F/oldwheels $FH $OB/backup $F/projects/-fake
for z in $SD/*.zsh; do zsh -n $z; check "zsh -n ${z:t}" [ $? -eq 0 ]; done
check "base $FB absent before 00" [ ! -e $FB ]
print "graftling repository (read only): $REALG | v0.6.2 type $(git -C $REALG cat-file -t refs/tags/v0.6.2) -> $(git -C $REALG rev-parse 'v0.6.2^{commit}')"
check "the graftling repository read is the real one (no stand-in)" [ $REALG = $REALH/graftling ]

head1 "setup: fake production = graphtraj $NEW + graftling v0.6.1 (real repository, git archive), plugin, configuration"
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
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-528-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $NEW | tar -x -C $F/oldsrc
git -C $REALG archive v0.6.1 | tar -x -C $F/oldg
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldg/src/graftling
ls $F/oldwheels
git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
$CONDA -m venv $FRT
$FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
D=$FRT/lib/python3.13/site-packages
for d in click click-8.5.0.dist-info yaml _yaml pyyaml-6.0.3.dist-info websockets websockets-16.1.1.dist-info; do cp -Rp $REALS/$d $D/; done
(cd $FH && print y | $FRT/bin/graphtraj setup) | tail -2
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
$CONDA -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["enabledMcpjsonServers"]=["graphtraj"]; d["enableAllProjectMcpServers"]=True; open(p,"w").write(json.dumps(d, indent=2)+"\n")' $FH/.claude/settings.local.json
print "fake production .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json)"
mkdir -p $ST/$TASK/definitions $ST/$TASK/teams/1; cp $WT/.state/task.yml $ST/$TASK/; print 'stopped: false' > $ST/$TASK/execution-budget.yml
def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
for f in $WT/.state/task.md ${def:+$WT/.state/$def}; do   # dependencies and parent removed: the fake state has no other Tasks
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $ST/$TASK/${f#$WT/.state/}
done
print "525 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/525 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
mkdir -p $FH/.graphtraj/swarm/sessions $FH/.graphtraj/swarm/control   # 526 REPORT targets (data root as in production)
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

head1 "00 (Main found through claude --continue; 528 markers absent in production; .mcp.json graphtraj only)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|\.mcp.json servers|CHECK 515|isolation:|answer check|Claude Code installed|REPORT 528|525 backup|Version)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: 528 markers absent in production (8/8)" grep -q 'markers expected absent: PASS (8/8)' $F/00.out
check "00: production graftling 0.6.1 and 525's backup listed COMPLETE" sh -c "grep -q '^Version: 0.6.1' $F/00.out && grep -q '525 backup COMPLETE marker: present' $F/00.out"
check "00: .mcp.json CHECK PASS (graphtraj only, as 515 left it)" grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/00.out
check "00: isolated vproject OK and answer check OK" sh -c "grep -q '^isolation: OK' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out"
check "00: 526 REPORT lists the data roots (no .gitignore with 0.6.1)" sh -c "grep -q 'REPORT 528 526 .gitignore .graphtraj/swarm/sessions: no .gitignore' $F/00.out"
check "00 next is B with the real path" grep -q "next.*: zsh $SD/steps.zsh B" $F/00.out

head1 "B (graftling from git archive v0.6.2 of <Harness>/graftling; graphtraj $NEW only for the scratch venv)"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked|peels|annotated|tagger|author|wheel version|ignore_in_git|Requires|carries|git diff' $F/B.out
check "B: Worktree src/tests/plugins = $NEW; production graphtraj requires graftling<0.7,>=0.6.0" sh -c "grep -q 'git diff 8267f9e5 HEAD -- src tests plugins: empty' $F/B.out && grep -q '^production graphtraj Requires-Dist: graftling<0.7,>=0.6.0' $F/B.out"
check "B: v0.6.2 annotated, peels to 4a002129…, graftling 0.6.2 with ignore_in_git and no toolview, carries 0, leaked 0" sh -c "grep -q 'v0.6.2 peels to $GC…: yes' $F/B.out && grep -q 'v0.6.2 is an annotated tag (cat-file -t: tag): yes' $F/B.out && grep -q '^graftling wheel version: 0.6.2' $F/B.out && grep -q 'def ignore_in_git): 1 | 527 client.mjs lines naming tool.call.toolview/AgentsRow: 0' $F/B.out && grep -q 'graphtraj wheel carries graftling/: 0 files' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: tagger and commit identity are the noreply LUOXIAO92" sh -c "grep -q '^v0.6.2 tagger: LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>' $F/B.out && grep -q '^v0.6.2 commit author / committer: LUOXIAO92 89069722+LUOXIAO92@users.noreply.github.com / LUOXIAO92 89069722+LUOXIAO92@users.noreply.github.com' $F/B.out"
check "B: the install directory holds only the graftling wheel" sh -c "[ \$(ls $W/wheels-8267f9e5/*.whl | wc -l) -eq 1 ] && ls $W/wheels-8267f9e5/graftling-0.6.2-*.whl > /dev/null && ls $W/gtwheel-8267f9e5/graphtraj-0.1.0-*.whl > /dev/null"
VERIFY528_GCOMMIT=deadbeef steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the phase-A commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.2^{commit} is .*, not deadbeef' $F/B-tag.out"
VERIFY528_GTAG=v0.6.1 VERIFY528_GCOMMIT=$G61 steps B > $F/B-old.out 2>&1; BO=$?
check "B negative: the 0.6.1 tag (no 526/527, version 0.6.1) STOPs at the version" sh -c "[ $BO -ne 0 ] && grep -q 'STOP: graftling wheel version 0.6.1, not 0.6.2' $F/B-old.out"
VERIFY528_GTAG=$GC steps B > $F/B-light.out 2>&1; BL=$?
check "B negative: a ref that peels to the commit but is no annotated tag (the commit id) STOPs" sh -c "[ $BL -ne 0 ] && grep -q 'STOP: $GC is not an annotated tag' $F/B-light.out"
steps B > /dev/null 2>&1

head1 "G through the real entry, limited by VERIFY528_TESTS to tests/test_agent_runner_cleanup.py (conftest fixtures; not --collect-only)"
VERIFY528_TESTS=tests/test_agent_runner_cleanup.py steps G > $F/G.out 2>&1; GRC=$?; cat $F/G.out
OUTG=$(cat $W/G-latest 2>/dev/null)
[[ -n $OUTG && -d $OUTG ]] && for i in {1..120}; do grep -q '^exit=' $OUTG/suite.txt 2>/dev/null && break; sleep 5; done
check "G started: graftling 0.6.2 with ignore_in_git from the B wheel, new temp root outside the Harness" sh -c "[ $GRC -eq 0 ] && grep -q 'graftling 0.6.2 .*| 526 ignore_in_git: True' $F/G.out && grep -q \"pytest temp root (new for this run; TMPDIR of every shard): ${${TMPDIR:-/tmp}:A}/verify-528-G-\" $F/G.out && grep -q 'TMPDIR of the run is outside the Harness: yes' $F/G.out && grep -q 'REHEARSAL: tests limited to tests/test_agent_runner_cleanup.py' $F/G.out"
check "G imported graphtraj from the Worktree" grep -q "^graphtraj $WT/src/graphtraj/__init__.py" $F/G.out
tail -4 $OUTG/suite.txt
check "G ran real tests: passed > 0, exit=0" sh -c "grep -qE '[0-9]+ passed' $OUTG/suite.txt && grep -q '^exit=0' $OUTG/suite.txt"
steps GR > $F/GR.out 2>&1; GRR=$?; grep -E 'CHECK|known source|G failures' $F/GR.out
check "GR: known sources read (516, 523 F, 521 F, 518 G, 525 G + decision) and no NEW failure" sh -c "[ $GRR -eq 0 ] && grep -q 'CHECK 528 G no NEW failure .*: PASS' $F/GR.out && grep -q 'known source 523 F: 2 failures listed; files read: 1/1' $F/GR.out && grep -q 'known source 521 F: 1 failures listed; files read: 1/1' $F/GR.out && grep -q 'known source 518 G: 0 failures listed; files read: 7/7' $F/GR.out && grep -q 'known source 525 G: 1 failures listed; files read: 7/7' $F/GR.out && grep -q 'test_interrupt_returns_after_slow_terminal_record as known: yes' $F/GR.out"
mkdir -p $F/grneg/shards; print -l 'FAILED tests/test_pi_generic_execution.py::test_graphtraj_member_launch_matches_base - x' 'FAILED tests/test_claude_native_host.py::test_anything - empty output' 'FAILED tests/test_team_replacement.py::test_interrupt_returns_after_slow_terminal_record - Failed: timeout' 'FAILED tests/test_new_thing.py::test_x - boom' 'FAILED tests/test_y.py::test_z - RuntimeError: system time precedes the chronologically last event' '1 failed, 2 passed' 'exit=1' > $F/grneg/suite.txt
$CONDA -I $SD/gr528.py $REALH/.graphtraj/core/state/tasks $F/grneg > $F/grneg.out 2>&1; GN=$?; cat $F/grneg.out | grep -E '^  |^CHECK'
check "GR negative: known (521 F / 516 file / 525 G / 516 clock) and one NEW -> FAIL" sh -c "[ $GN -ne 0 ] && grep -q 'known (521 F)  tests/test_pi_generic' $F/grneg.out && grep -q 'known (516)  tests/test_claude_native_host' $F/grneg.out && grep -q 'known (525 G)  tests/test_team_replacement.py::test_interrupt_returns_after_slow_terminal_record' $F/grneg.out && grep -q 'known (516)  tests/test_y.py' $F/grneg.out && grep -q 'NEW  tests/test_new_thing.py::test_x' $F/grneg.out && grep -q 'CHECK 528 G no NEW failure .*: FAIL' $F/grneg.out"

head1 "V (stub plugin validate): plugin SAME; graftling files = 526/527 + version + docs; graphtraj unchanged; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK 5|528 graftling|graftling wheel vs|^graphtraj |  UNEXPECTED |markers expected|503 layout|node resolves' $F/V.out
check "V: three plugin files SAME and the CHECK PASS (no trust dialog expected)" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)' $RW/V.txt) -eq 3 ] && grep -q \"CHECK 528 candidate plugin bytes equal production's (no plugin trust dialog expected): PASS\" $F/V.out"
check "V: graftling CODE/VERSION/DOC exactly as expected (OK x3) and wheel = git archive v0.6.2" sh -c "grep -q \"528 graftling CODE files 0.6.1 -> 0.6.2: \['graftling/control.py', 'graftling/dsh/client.mjs', 'graftling/dsh/package.json', 'graftling/locks.py', 'graftling/sessions/archive.py'\] | unexpected 0 | expected but equal 0: OK\" $F/V.out && grep -q \"528 graftling VERSION files 0.6.1 -> 0.6.2: \['graftling/__init__.py', 'graftling/pi/package.json'\] | unexpected 0 | expected but equal 0: OK\" $F/V.out && grep -q \"528 graftling DOC files 0.6.1 -> 0.6.2: \['graftling/CHANGELOG.md', 'graftling/README.md'\] | unexpected 0 | expected but equal 0: OK\" $F/V.out && grep -q 'graftling wheel vs .*differing 0: SAME' $F/V.out"
check "V: graphtraj wheel $NEW equals production file by file" grep -q 'CHECK 528 graphtraj unchanged (wheel 8267f9e5 vs production): PASS' $F/V.out
check "V: markers present in the candidate and absent in production (8/8)" sh -c "grep -q 'markers expected present: PASS (8/8)' $F/V.out && grep -q 'markers expected absent: PASS (8/8)' $F/V.out"
check "V: one graftling and node resolution in the scratch venv" sh -c "grep -q '^503 layout: PASS' $F/V.out && [ \$(grep -c 'node resolves .*: PASS' $F/V.out) -ge 2 ]"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256

head1 "graftcode / gtdiff / markers negatives"
GW=($W/wheels-8267f9e5/graftling-*.whl); mkdir -p $F/gneg/src; cp -Rp $W/gsrc-0.6.2/src/graftling $F/gneg/src/
print '# changed after the tag' >> $F/gneg/src/graftling/control.py
$CONDA -I $SD/graftcode.py $GW[1] $D $F/gneg/src > $F/gcneg.out 2>&1; GN=$?
check "graftcode negative: a wheel file that differs from the archive STOPs" sh -c "[ $GN -eq 1 ] && grep -q 'WHEEL-DIFFERS graftling/control.py (bytes differ)' $F/gcneg.out && grep -q 'differing 1: STOP' $F/gcneg.out"
mkdir -p $F/prodneg; cp -Rp $D/graftling $F/prodneg/; print '# production drift' >> $F/prodneg/graftling/tool.py
$CONDA -I $SD/graftcode.py $GW[1] $F/prodneg $W/gsrc-0.6.2/src > $F/gcneg2.out 2>&1; GN2=$?
check "graftcode negative: an extra CODE difference against production STOPs" sh -c "[ $GN2 -eq 1 ] && grep -q \"528 graftling CODE files .*unexpected 1 \['graftling/tool.py'\].*: STOP\" $F/gcneg2.out"
mkdir -p $F/prodneg3; cp -Rp $D/graftling $F/prodneg3/; cp -p $W/gsrc-0.6.2/src/graftling/locks.py $F/prodneg3/graftling/locks.py
$CONDA -I $SD/graftcode.py $GW[1] $F/prodneg3 $W/gsrc-0.6.2/src > $F/gcneg3.out 2>&1; GN3=$?
check "graftcode negative: an expected CODE file that does not differ STOPs (expected but equal)" sh -c "[ $GN3 -eq 1 ] && grep -q \"expected but equal 1 \['graftling/locks.py'\]: STOP\" $F/gcneg3.out"
GTW=($W/gtwheel-8267f9e5/graphtraj-*.whl); mkdir -p $F/gtneg; cp -Rp $D/graphtraj $F/gtneg/; print '# drift' >> $F/gtneg/graphtraj/execution/runner_worker.py
$CONDA -I $SD/gtdiff528.py $GTW[1] $F/gtneg > $F/gtneg.out 2>&1; GT=$?
check "gtdiff negative: a differing graphtraj file FAILs" sh -c "[ $GT -eq 1 ] && grep -q 'UNEXPECTED graphtraj/execution/runner_worker.py' $F/gtneg.out && grep -q 'CHECK 528 graphtraj unchanged .*: FAIL' $F/gtneg.out"
check "markers 'present' on production fails" sh -c "! $CONDA -I $SD/markers.py $D present > /dev/null"
VS=($FB/vvenv-8267f9e5/lib/python*/site-packages(N))
check "markers 'absent' on the candidate fails" sh -c "! $CONDA -I $SD/markers.py $VS[1] absent > /dev/null"

head1 "Vu / Vc (stub claude: plugin not loaded, so Vc asks for Vu; setup shows graphtraj only in the isolated .mcp.json)"
steps Vu > $F/Vu.out 2>&1
check "Vu names the isolated path and 'Yes, proceed'" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc setup: isolated .mcp.json CHECK PASS and answer check OK" sh -c "grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc with the stub asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok   # rehearsal only: the real plugin load is not rehearsable

head1 "Mpre / I (USER): GR shown, guard idle, backup, graftling-only install, graphtraj unchanged, configuration --write"
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: GR PASS shown and the restart reason with file:line" sh -c "grep -q '^GR: PASS' $F/Mpre.out && grep -q 'host.py:25 graftling.claude、:28 graftling → graftling/__init__.py:47 graftling.control → control.py:70 graftling.locks' $F/Mpre.out"
: > $F/ps.txt   # Main has exited
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|^528 |CHECK 528|direct_url|built from|CHECK 515|configuration --write rc|plugin bytes|SAME-AS-VALIDATED|markers expected|changed:|bytes unchanged' $F/I.out
check "I: installed only graftling 0.6.2, proddiff PASS, markers present 8/8" sh -c "grep -q '^Successfully installed graftling-0.6.2\$' $F/I.out && ! grep -qE '^ *Successfully (installed|uninstalled).*graphtraj' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'markers expected present: PASS (8/8)' $F/I.out"
check "I: installed graphtraj unchanged against the backup" grep -q 'CHECK 528 graphtraj unchanged (installed vs backup): PASS' $F/I.out
check "I: 526/527 by name in the installed code" sh -c "grep -q '^528 526 ignore_in_git: ignore_in_git | control uses it: True | archive uses it: True' $F/I.out && grep -q '^528 527 client.mjs registers AgentsRow/toolview: False | package.json injects dsh-client-ui-tool: False' $F/I.out"
check "I: sources: direct_url names the wheels-8267f9e5 graftling wheel; built from v0.6.2 $GC" sh -c "grep -q 'graftling-0.6.2.dist-info direct_url: .*wheels-8267f9e5/graftling-0.6.2' $F/I.out && grep -q 'built from: graftling git archive v0.6.2 $GC' $F/I.out"
check "I: configuration --write rc=0, .mcp.json CHECK PASS, SAME-AS-VALIDATED, plugin as before, 3 entries unchanged" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out && grep -q 'plugin bytes as before the install' $F/I.out && [ \$(grep -c '^bytes unchanged: ' $RW/I.txt) -eq 3 ]"
check "I: backup holds entries, plugin, tools; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/gtdiff528.py ]"
check "I: prints the restart command and 'no dialog expected'" sh -c "grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: 无' $F/I.out"

head1 "M / Mp after the restart"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt asks for notices since the resume and the mcp__graphtraj__ tools; next Mp" sh -c "grep -q 'Production was just upgraded by Task 528' $F/M.out && grep -q 'already seen that same notice' $F/M.out && grep -q \"next.*: zsh $SD/steps.zsh Mp\" $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"
steps inbox > $F/inbox.out 2>&1
check "inbox: next is Nw (D/C/Cc dropped)" grep -q "next.*: zsh $SD/steps.zsh Nw" $F/inbox.out

head1 "N text, the 468 CPU window and the 526 .gitignore REPORT (fixture samples; not blocking)"
steps N > $F/N.out 2>&1
check "N: one advisor member creates n528 through mcp__graphtraj__agents, waits, retires" sh -c "grep -q '\"task_id\":\"528\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n528' $F/N.out && grep -q 'Retire the child' $F/N.out"
T0=$(date +%s)
for i in 0 1 2 3 4 5 6; do
  at=$(( T0 + i * 10 )); run=$([[ $i -ge 3 ]] && print true || print null); cpu=$(( i < 3 ? i * 9 : 18 + (i - 3) ))
  print -r -- "{\"at\": $at, \"child_running\": $run, \"ps\": \"6161 1 1.0 0:$(printf %02d $cpu).00 01:00 python -m graphtraj.execution.runner_worker\"}"
done > $RW/Nw468-ps.txt
# the installed 0.6.2 writes .gitignore when it next writes there; simulate it for sessions/ only (control/ stays without)
$FRT/bin/python -I -c 'import sys, pathlib, graftling.locks as l; l.ignore_in_git(pathlib.Path(sys.argv[1]))' $FH/.graphtraj/swarm/sessions
steps Nr > $F/Nr.out 2>&1; grep -E '^REPORT' $F/Nr.out
check "Nr: 468 window before 0.600 / after 0.100 reported, with 525's 0.538/0.112 for comparison" sh -c "grep -q 'before child creation: 0.600' $F/Nr.out && grep -q 'after child creation: 0.100' $F/Nr.out && grep -q '30 s before 0.538, after 0.112' $F/Nr.out"
check "Nr: 526 REPORT per directory (sessions present '*', control no .gitignore, live/native directory absent)" sh -c "grep -q \"REPORT 528 526 .gitignore .graphtraj/swarm/sessions: present ('\*'\" $F/Nr.out && grep -q 'REPORT 528 526 .gitignore .graphtraj/swarm/control: no .gitignore' $F/Nr.out && grep -q 'REPORT 528 526 .gitignore .graphtraj/swarm/live: directory absent' $F/Nr.out"
check "Nr: without notices the one-notice CHECK is PENDING (never PASS)" grep -q 'CHECK 528 Main got exactly one completed notice of the member: PENDING' $F/Nr.out
print -l '# Main notices of the member' '[Graftling notice from 528-x-advisor@advisor · completed · execution e1] done' > $RW/N-main-notice.txt
steps Nr > $F/Nr2.out 2>&1
check "Nr: one completed notice line of an alias-less fixture is counted, not silently PASS" grep -qE 'CHECK 528 Main got exactly one completed notice of the member: (PASS|FAIL) \([0-9]+ notice lines' $F/Nr2.out
rm -f $RW/N-main-notice.txt

head1 "R (rollback from the backup's own tools): venv, plugin and entry files restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version|graftling/sessions|expected|REPORT 528' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling/sessions differs only in archive.py (expected)" sh -c "grep -q 'graftling/sessions installed vs backup: Files .*archive.py differ' $F/R.out && grep -q '^expected (526' $F/R.out"
check "R: production graftling is 0.6.1 again, graphtraj still installed" sh -c "$FRT/bin/python -m pip show graftling | grep -q 'Version: 0.6.1' && $FRT/bin/python -m pip show graphtraj | grep -q 'Version: 0.1.0'"
check "R: the .gitignore 0.6.2 wrote is listed and kept" grep -q "REPORT 528 526 .gitignore .graphtraj/swarm/sessions: present" $F/R.out
check "525's backup under tmp/525 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"

head1 "done: no exported key value in raw files"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
