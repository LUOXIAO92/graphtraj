#!/bin/zsh
# Rehearsal of adopt-525/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (copied from adopt-515's).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Fake production: graphtraj wheel of 4ad22e90 + graftling wheel of the REAL <Harness>/graftling tag v0.6.0 (read only,
# git archive), i.e. what 515 installed; click, yaml and websockets copied from production .venv-runtime (read only).
# B reads the REAL annotated tag v0.6.1 of <Harness>/graftling (read only; Main created it from the phase-A commit
# 483b16a8); no tag is created anywhere. G runs through the same entry with
# VERIFY525_TESTS=tests/test_agent_runner_cleanup.py (real tests using the repository's conftest fixtures).
#   zsh scripts/adopt-525/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt525-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/525
OB=$FH/tmp/515   # 515's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=$REALH/graftling
GC=483b16a8d6e05b1c866e69439fada8478791f1fb
OLD=4ad22e9065cf38bc3c976eed184d29b1a299413a
NEW=8267f9e5a89dd8f504e5da916e6102b4bbff23c3
export ADOPT525_H=$FH ADOPT525_BASE=$FB ADOPT525_RT=$FRT ADOPT525_PNPM_SHIM=$F/no-shim ADOPT525_STUB=$F/stub ADOPT525_WT=$WT ADOPT525_PROJECTS=$F/projects/-fake ADOPT525_WAIT=1 ADOPT525_OLDBASE=$OB ADOPT525_G=$REALG ADOPT525_VPROJECT=$FB/vproject ADOPT525_KNOWN=$REALH/.graphtraj/core/state/tasks
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=525-production-adoption-graftling-0-6-1
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
print "graftling repository (read only): $REALG | v0.6.1 type $(git -C $REALG cat-file -t refs/tags/v0.6.1) -> $(git -C $REALG rev-parse 'v0.6.1^{commit}')"

head1 "setup: fake production = graphtraj $OLD + graftling v0.6.0 (real repository, git archive), plugin, configuration"
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
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-525-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $OLD | tar -x -C $F/oldsrc
git -C $REALG archive v0.6.0 | tar -x -C $F/oldg
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldg/src/graftling
ls $F/oldwheels
git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
$CONDA -m venv $FRT
$FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
D=$FRT/lib/python3.13/site-packages
cp -Rp $REALS/click $REALS/click-*.dist-info(N) $REALS/yaml $REALS/_yaml(N) $REALS/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $REALS/websockets $REALS/websockets-*.dist-info(N) $D/
(cd $FH && print y | $FRT/bin/graphtraj setup) | tail -2
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
$CONDA -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["enabledMcpjsonServers"]=["graphtraj"]; d["enableAllProjectMcpServers"]=True; open(p,"w").write(json.dumps(d, indent=2)+"\n")' $FH/.claude/settings.local.json
print "fake production .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json)"
mkdir -p $ST/$TASK/definitions $ST/$TASK/teams/1; cp $WT/.state/task.yml $ST/$TASK/; print 'stopped: false' > $ST/$TASK/execution-budget.yml
def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
for f in $WT/.state/task.md ${def:+$WT/.state/$def}; do   # dependencies and parent removed: the fake state has no other Tasks
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $ST/$TASK/${f#$WT/.state/}
done
# 523's cleanup targets in the fake state: 519 and 520 integrated, with a Worktree each (C/Cc rehearsal).
for t in 519-standby 520-unobserved; do mkdir -p $ST/$t $FH/.graphtraj/core/worktrees/$t; print 'status: integrated' > $ST/$t/task.yml; done
print "515 backup" > $OB/backup/COMPLETE
FAKE519=($ST/519-standby $ST/520-unobserved)   # state records only for 00's listing; removed after 00 (V's Task graph needs valid records)
( cd $FH && find tmp/515 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
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

head1 "00 (Main found through claude --continue; 525 markers absent in production; .mcp.json graphtraj only)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|\.mcp.json servers|CHECK 515|isolation:|answer check|Claude Code installed|5(19|20): )' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: 525 markers absent in production (8/8)" grep -q 'markers expected absent: PASS (8/8)' $F/00.out
check "00: .mcp.json CHECK PASS (graphtraj only, as 515 left it)" grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/00.out
check "00: 519 and 520 listed integrated with their Worktree" sh -c "grep -q '^519: status: integrated | worktree: 519-standby' $F/00.out && grep -q '^520: status: integrated | worktree: 520-unobserved' $F/00.out"
check "00: isolated vproject OK and answer check OK" sh -c "grep -q '^isolation: OK' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out"
check "00 next is B with the real path" grep -q "next.*: zsh $SD/steps.zsh B" $F/00.out
rm -rf $FAKE519

head1 "B (graftling from git archive v0.6.1 of <Harness>/graftling; graphtraj from git archive $NEW)"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked|peels|wheel version|_archived_header|Requires|carries|git diff|product files' $F/B.out
check "B: Worktree HEAD = $NEW in src/tests/plugins; plugins and runtimes/claude unchanged since 4ad22e90" sh -c "grep -q 'git diff 8267f9e5 HEAD -- src tests plugins: empty' $F/B.out && grep -q 'git diff 4ad22e90 8267f9e5 -- plugins src/graphtraj/runtimes/claude: empty' $F/B.out"
check "B: v0.6.1 peels to 483b16a8…, graftling 0.6.1 with _archived_header, Requires-Dist graftling<0.7,>=0.6.0, carries 0, leaked 0" sh -c "grep -q 'v0.6.1 peels to $GC…: yes' $F/B.out && grep -q 'v0.6.1 is an annotated tag (cat-file -t: tag): yes' $F/B.out && grep -q '^graftling wheel version: 0.6.1' $F/B.out && grep -q 'def _archived_header): 1' $F/B.out && grep -q '^graphtraj Requires-Dist: graftling<0.7,>=0.6.0' $F/B.out && grep -q 'graphtraj wheel carries graftling/: 0 files' $F/B.out && grep -q '^leaked: 0' $F/B.out"
VERIFY525_GCOMMIT=deadbeef steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the phase-A commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.1^{commit} is .*, not deadbeef' $F/B-tag.out"
VERIFY525_GTAG=v0.6.0 VERIFY525_GCOMMIT=a51e1004a0fe77fe492681faa2f278d80b3d725e steps B > $F/B-old.out 2>&1; BO=$?
check "B negative: the 0.6.0 tag (no 518 fix, version 0.6.0) STOPs at the version" sh -c "[ $BO -ne 0 ] && grep -q 'STOP: graftling wheel version 0.6.0, not 0.6.1' $F/B-old.out"
VERIFY525_GTAG=main steps B > $F/B-light.out 2>&1; BL=$?
check "B negative: a ref that peels to the commit but is no annotated tag (main) STOPs" sh -c "[ $BL -ne 0 ] && grep -q 'STOP: main is not an annotated tag' $F/B-light.out"
steps B > /dev/null 2>&1

head1 "G through the real entry, limited by VERIFY525_TESTS to tests/test_agent_runner_cleanup.py (conftest fixtures; not --collect-only)"
VERIFY525_TESTS=tests/test_agent_runner_cleanup.py steps G > $F/G.out 2>&1; GRC=$?; cat $F/G.out
OUTG=$(cat $W/G-latest 2>/dev/null)
[[ -n $OUTG && -d $OUTG ]] && for i in {1..120}; do grep -q '^exit=' $OUTG/suite.txt 2>/dev/null && break; sleep 5; done
check "G started: graftling 0.6.1 with _archived_header from the B wheel, new temp root outside the Harness" sh -c "[ $GRC -eq 0 ] && grep -q 'graftling 0.6.1 .*| 518 _archived_header: True' $F/G.out && grep -q \"pytest temp root (new for this run; TMPDIR of every shard): ${${TMPDIR:-/tmp}:A}/verify-525-G-\" $F/G.out && grep -q 'REHEARSAL: tests limited to tests/test_agent_runner_cleanup.py' $F/G.out"
check "G imported graphtraj from the Worktree" grep -q "^graphtraj $WT/src/graphtraj/__init__.py" $F/G.out
tail -4 $OUTG/suite.txt
check "G ran real tests: passed > 0, exit=0" sh -c "grep -qE '[0-9]+ passed' $OUTG/suite.txt && grep -q '^exit=0' $OUTG/suite.txt"
steps GR > $F/GR.out 2>&1; GRR=$?; grep -E 'CHECK|known source|G failures' $F/GR.out
check "GR: known sources read (516, 523 F, 521 F, 518 G) and no NEW failure" sh -c "[ $GRR -eq 0 ] && grep -q 'CHECK 525 G no NEW failure .*: PASS' $F/GR.out && grep -q 'known source 523 F: 2 failures listed; files read: 1/1' $F/GR.out && grep -q 'known source 521 F: 1 failures listed; files read: 1/1' $F/GR.out && grep -q 'known source 518 G: 0 failures listed; files read: 7/7' $F/GR.out"
mkdir -p $F/grneg/shards; print -l 'FAILED tests/test_pi_generic_execution.py::test_graphtraj_member_launch_matches_base - x' 'FAILED tests/test_claude_native_host.py::test_anything - empty output' 'FAILED tests/test_new_thing.py::test_x - boom' 'FAILED tests/test_y.py::test_z - RuntimeError: system time precedes the chronologically last event' '1 failed, 2 passed' 'exit=1' > $F/grneg/suite.txt
$CONDA -I $SD/gr525.py $REALH/.graphtraj/core/state/tasks $F/grneg > $F/grneg.out 2>&1; GN=$?; cat $F/grneg.out | grep -E '^  '
check "GR negative: known (521 F / 516 file / 516 clock) and one NEW -> FAIL" sh -c "[ $GN -ne 0 ] && grep -q 'known (521 F)  tests/test_pi_generic' $F/grneg.out && grep -q 'known (516)  tests/test_claude_native_host' $F/grneg.out && grep -q 'known (516)  tests/test_y.py' $F/grneg.out && grep -q 'NEW  tests/test_new_thing.py::test_x' $F/grneg.out"

head1 "V (stub plugin validate): plugin SAME; graftling CODE = archive.py only; graphtraj = the 521/523 files; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK 5|525 graftling CODE|graftling wheel vs|graphtraj wheel vs|  (expected|UNEXPECTED) |markers expected|503 layout|node resolves' $F/V.out
check "V: three plugin files SAME and the CHECK PASS (no trust dialog expected)" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)' $RW/V.txt) -eq 3 ] && grep -q \"CHECK 525 candidate plugin bytes equal production's (no plugin trust dialog expected): PASS\" $F/V.out"
check "V: graftling CODE only archive.py (OK) and wheel = git archive v0.6.1" sh -c "grep -q \"525 graftling CODE files 0.6.0 -> 0.6.1: \['graftling/sessions/archive.py'\] .*unexpected 0: OK\" $F/V.out && grep -q 'graftling wheel vs .*differing 0: SAME' $F/V.out"
check "V: graphtraj differs in exactly runner_results, runner_status, tools" sh -c "[ \$(grep -c '^  expected graphtraj/' $RW/V.txt) -eq 3 ] && grep -q 'CHECK 525 graphtraj differs from production in exactly the 521/523 files: PASS' $F/V.out"
check "V: markers present in the candidate and absent in production (8/8)" sh -c "grep -q 'markers expected present: PASS (8/8)' $F/V.out && grep -q 'markers expected absent: PASS (8/8)' $F/V.out"
check "V: one graftling and node resolution in the scratch venv" sh -c "grep -q '^503 layout: PASS' $F/V.out && [ \$(grep -c 'node resolves .*: PASS' $F/V.out) -ge 2 ]"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256

head1 "graftcode / gtdiff / markers negatives"
GW=($W/wheels-8267f9e5/graftling-*.whl); mkdir -p $F/gneg/src; cp -Rp $W/gsrc-0.6.1/src/graftling $F/gneg/src/
print '# changed after the tag' >> $F/gneg/src/graftling/control.py
$CONDA -I $SD/graftcode.py $GW[1] $D $F/gneg/src > $F/gcneg.out 2>&1; GN=$?
check "graftcode negative: a wheel file that differs from the archive STOPs" sh -c "[ $GN -eq 1 ] && grep -q 'WHEEL-DIFFERS graftling/control.py (bytes differ)' $F/gcneg.out && grep -q 'differing 1: STOP' $F/gcneg.out"
mkdir -p $F/prodneg; cp -Rp $D/graftling $F/prodneg/; print '# production drift' >> $F/prodneg/graftling/control.py
$CONDA -I $SD/graftcode.py $GW[1] $F/prodneg $W/gsrc-0.6.1/src > $F/gcneg2.out 2>&1; GN2=$?
check "graftcode negative: a second CODE difference against production STOPs" sh -c "[ $GN2 -eq 1 ] && grep -q 'unexpected 1: STOP' $F/gcneg2.out"
GTW=($W/wheels-8267f9e5/graphtraj-*.whl); mkdir -p $F/gtneg; cp -Rp $D/graphtraj $F/gtneg/; print '# drift' >> $F/gtneg/graphtraj/execution/runner_worker.py
$CONDA -I $SD/gtdiff525.py $GTW[1] $F/gtneg > $F/gtneg.out 2>&1; GT=$?
check "gtdiff negative: an unexpected differing file FAILs" sh -c "[ $GT -eq 1 ] && grep -q 'UNEXPECTED graphtraj/execution/runner_worker.py' $F/gtneg.out && grep -q 'exactly the 521/523 files: FAIL' $F/gtneg.out"
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

head1 "Mpre / I (USER): GR shown, guard idle, backup, install, configuration --write, no entry or plugin change"
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: GR PASS shown and the restart reason with file:line" sh -c "grep -q '^GR: PASS' $F/Mpre.out && grep -q 'host.py:33 → claude/mcp.py:20 → gateway.py:12 → tools.py:14 → runner_control.py:41' $F/Mpre.out"
: > $F/ps.txt   # Main has exited
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|^525 |direct_url|built from|CHECK 515|configuration --write rc|plugin bytes|SAME-AS-VALIDATED|markers expected|changed:|bytes unchanged' $F/I.out
check "I: installed graftling 0.6.1, proddiff PASS, markers present 8/8" sh -c "grep -q 'Successfully installed graftling-0.6.1' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'markers expected present: PASS (8/8)' $F/I.out"
check "I: 518/521/523 by name in the installed code" sh -c "grep -q '^525 518 header-only lookup: _archived_header | native_header uses it: True' $F/I.out && grep -q '^525 521 session_worktree_access: session_worktree_access | submit_result names the own report: True' $F/I.out && grep -q '^525 523 cleanup skips non-alias names: True' $F/I.out"
check "I: sources: direct_url names the wheels-8267f9e5 wheels; built from v0.6.1 $GC" sh -c "grep -q 'graphtraj-0.1.0.dist-info direct_url: .*wheels-8267f9e5/graphtraj-0.1.0' $F/I.out && grep -q 'graftling-0.6.1.dist-info direct_url: .*wheels-8267f9e5/graftling-0.6.1' $F/I.out && grep -q 'built from: graphtraj git archive $NEW | graftling git archive v0.6.1 $GC' $F/I.out"
check "I: configuration --write rc=0, .mcp.json CHECK PASS, SAME-AS-VALIDATED, plugin as before, 3 entries unchanged" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out && grep -q 'plugin bytes as before the install' $F/I.out && [ \$(grep -c '^bytes unchanged: ' $RW/I.txt) -eq 3 ]"
check "I: backup holds entries, plugin, tools; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/gtdiff525.py ]"
check "I: prints the restart command and 'no dialog expected'" sh -c "grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: 无' $F/I.out"

head1 "M / Mp after the restart"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt asks for notices since the resume and the mcp__graphtraj__ tools; next Mp" sh -c "grep -q 'Production was just upgraded by Task 525' $F/M.out && grep -q 'already seen that same notice' $F/M.out && grep -q \"next.*: zsh $SD/steps.zsh Mp\" $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"

head1 "D / C / Cc (523's cleanup on the fake 519/520)"
steps D > $F/D.out 2>&1; tail -5 $F/D.out
check "D runs diag523 on the installed site-packages" grep -q "graphtraj source: $D/graphtraj" $F/D.out
steps C > $F/C.out 2>&1
check "C prints 523's public cleanup calls for 519 and 520" sh -c "grep -q '\"task_id\": \"519\"' $F/C.out && grep -q '\"task_id\": \"520\"' $F/C.out && grep -q 'zsh $SD/steps.zsh Cc' $F/C.out"
steps Cc > $F/Cc-none.out 2>&1; CN=$?
check "Cc negative: no saved results -> NOT OBSERVED, exit 1" sh -c "[ $CN -ne 0 ] && [ \$(grep -c '^CHECK.*NOT OBSERVED' $RW/Cc.txt) -eq 2 ]"
print '{"cleanup_status": "cleaned", "standby_aliases": []}' > $RW/C-519.txt; print '{"cleanup_status": "worktree-busy"}' > $RW/C-520.txt
mv $FH/.graphtraj/core/worktrees/519-standby $F/519-moved
steps Cc > $F/Cc.out 2>&1; CC=$?; grep -E '^(5|CHECK)' $F/Cc.out
check "Cc: 519 cleaned + Worktree gone PASS; 520 not cleaned FAIL; exit 1" sh -c "[ $CC -ne 0 ] && grep -q 'cleanup of 519 returns cleaned and its Worktree is gone: PASS' $F/Cc.out && grep -q 'cleanup of 520 returns cleaned and its Worktree is gone: FAIL' $F/Cc.out"

head1 "N text and the 518 CPU window report (fixture samples; not blocking)"
steps N > $F/N.out 2>&1
check "N: one advisor member creates $([[ 1 ]] && print n525) through mcp__graphtraj__agents, waits, retires" sh -c "grep -q '\"task_id\":\"525\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n525' $F/N.out && grep -q 'Retire the child' $F/N.out"
T0=$(date +%s)
for i in 0 1 2 3 4 5 6; do
  at=$(( T0 + i * 10 )); run=$([[ $i -ge 3 ]] && print true || print null); cpu=$(( i < 3 ? i * 9 : 18 + (i - 3) ))
  print -r -- "{\"at\": $at, \"child_running\": $run, \"ps\": \"6161 1 1.0 0:$(printf %02d $cpu).00 01:00 python -m graphtraj.execution.runner_worker\"}"
done > $RW/Nw468-ps.txt
steps Nr > $F/Nr.out 2>&1; grep -E '^REPORT' $F/Nr.out
check "Nr: 468 window before 0.600 / after 0.100 reported, with 515's 0.626/0.969 for comparison" sh -c "grep -q 'before child creation: 0.600' $F/Nr.out && grep -q 'after child creation: 0.100' $F/Nr.out && grep -q '0.626, after 0.969' $F/Nr.out"
check "Nr: without notices the one-notice CHECK is PENDING (never PASS)" grep -q 'CHECK 525 Main got exactly one completed notice of the member: PENDING' $F/Nr.out

head1 "R (rollback from the backup's own tools): venv, plugin and entry files restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version|graftling/sessions|expected' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling/sessions differs only in archive.py (expected)" sh -c "grep -q 'graftling/sessions installed vs backup: Files .*archive.py differ' $F/R.out && grep -q '^expected (518' $F/R.out"
check "R: production graftling is 0.6.0 again" sh -c "$FRT/bin/python -m pip show graftling | grep -q 'Version: 0.6.0'"
check "515's backup under tmp/515 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"

head1 "done: no exported key value in raw files"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
