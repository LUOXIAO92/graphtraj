#!/bin/zsh
# Rehearsal of adopt-532/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (copied from adopt-528's).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Fake production: graphtraj wheel of 8267f9e5 + graftling wheel of the REAL <Harness>/graftling tag v0.6.2 (read only,
# git archive), i.e. what 525 + 528 installed; click, yaml and websockets copied from production .venv-runtime (read
# only). B reads the real annotated v0.6.2 (read only). GR reads 531's real G record (read only); its negatives use
# copies under $TMPDIR. No pytest step exists (532 reuses 531's G), so no test run is rehearsed.
#   zsh scripts/adopt-532/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt532-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/532
OB=$FH/tmp/528   # 528's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=$REALH/graftling
REALGR=$REALH/.graphtraj/core/state/tasks/531-child-create-runner-record-walk/realhost/G-83e84fba-20261120T204653
GC=4a002129f8b97f32980afd59e5a1a64c428fe684
NEW=a7b20447ce9c4ffeee62aba026265f6a1e0f10d2
OLD=8267f9e5a89dd8f504e5da916e6102b4bbff23c3
export ADOPT532_H=$FH ADOPT532_BASE=$FB ADOPT532_RT=$FRT ADOPT532_PNPM_SHIM=$F/no-shim ADOPT532_STUB=$F/stub ADOPT532_WT=$WT ADOPT532_PROJECTS=$F/projects/-fake ADOPT532_WAIT=1 ADOPT532_OLDBASE=$OB ADOPT532_G=$REALG ADOPT532_VPROJECT=$FB/vproject ADOPT532_REUSEG=$REALGR
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=532-production-adoption-graphtraj-531
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-a7b20447
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "empty base: $F removed; zsh -n of every zsh file"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldg $F/oldwheels $FH $OB/backup $F/projects/-fake
for z in $SD/*.zsh; do zsh -n $z; check "zsh -n ${z:t}" [ $? -eq 0 ]; done
check "base $FB absent before 00" [ ! -e $FB ]
print "Worktree HEAD $(git -C $WT rev-parse HEAD) | graftling repository (read only): $REALG | v0.6.2 type $(git -C $REALG cat-file -t refs/tags/v0.6.2) -> $(git -C $REALG rev-parse 'v0.6.2^{commit}')"

head1 "setup: fake production = graphtraj $OLD + graftling v0.6.2 (real repository, git archive), plugin, configuration"
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
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-532-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $OLD | tar -x -C $F/oldsrc
git -C $REALG archive v0.6.2 | tar -x -C $F/oldg
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
print "528 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/528 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
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

head1 "00 (Main found through claude --continue; 532 markers absent in production; .mcp.json graphtraj only)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|\.mcp.json servers|CHECK 515|isolation:|answer check|Claude Code installed|REPORT 532|528 backup|Version|production .*direct_url)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: Claude Code version recorded" sh -c "grep -q '^Claude Code installed: 2.1.325 (stub Claude Code)' $F/00.out && [ -s $FB/cc.version ]"
check "00: 532 markers absent in production (5/5)" grep -q 'markers expected absent: PASS (5/5)' $F/00.out
check "00: production graftling 0.6.2 and 528's backup listed COMPLETE" sh -c "grep -q '^Version: 0.6.2' $F/00.out && grep -q '528 backup COMPLETE marker: present' $F/00.out"
check "00: .mcp.json CHECK PASS (graphtraj only)" grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/00.out
check "00: isolated vproject OK and answer check OK" sh -c "grep -q '^isolation: OK' $F/00.out && grep -q 'answer check (expect clean): OK' $F/00.out"
check "00 next is B with the real path" grep -q "next.*: zsh $SD/steps.zsh B" $F/00.out

head1 "B (graphtraj from git archive $NEW; graftling from git archive v0.6.2 for the scratch venv only)"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked|peels|annotated|wheel version|Requires|satisfies|carries|product guard|product diff|CHECK 532|531.s fixes' $F/B.out
check "B: product guard PASS (HEAD = $NEW outside scripts/; diff 83e84fba..a7b20447 empty)" sh -c "grep -q 'product guard: PASS' $F/B.out && grep -q 'git diff 83e84fba a7b20447 -- src tests plugins pyproject.toml (basis for reusing 531.s G): empty' $F/B.out"
check "B: product diff 8267f9e5 -> a7b20447 is exactly the three 531 files" grep -q 'product diff is exactly the three 531 files: yes' $F/B.out
check "B: v0.6.2 annotated, peels to 4a002129; graftling wheel (scratch) 0.6.2" sh -c "grep -q 'v0.6.2 peels to $GC…: yes' $F/B.out && grep -q 'v0.6.2 is an annotated tag (cat-file -t: tag): yes' $F/B.out && grep -q '^graftling wheel version (scratch only): 0.6.2' $F/B.out"
check "B: new graphtraj requires graftling<0.7,>=0.6.0, satisfied by 0.6.2" sh -c "grep -q '^graphtraj wheel Requires-Dist: graftling<0.7,>=0.6.0' $F/B.out && grep -q 'production graftling 0.6.2 satisfies graftling<0.7,>=0.6.0: yes' $F/B.out"
check "B: graphtraj wheel = git archive a7b20447, carries 531's fixes, no graftling/, leaked 0" sh -c "grep -q 'CHECK 532 graphtraj wheel equals git archive a7b20447: PASS' $F/B.out && grep -q 'any_ownership_held: 1 | 496cec58 .history = None.: 1' $F/B.out && grep -q 'graphtraj wheel carries graftling/: 0 files' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: the install directory holds only the graphtraj wheel; graftling wheel elsewhere" sh -c "[ \$(ls $W/wheels-a7b20447/*.whl | wc -l) -eq 1 ] && ls $W/wheels-a7b20447/graphtraj-0.1.0-*.whl > /dev/null && ls $W/glwheel-0.6.2/graftling-0.6.2-*.whl > /dev/null"
VERIFY532_TARGET=$OLD steps B > $F/B-commit.out 2>&1; BC=$?
check "B negative: a wrong target commit (production's 8267f9e5) STOPs at the guard" sh -c "[ $BC -ne 0 ] && grep -q 'STOP: the Worktree.s src tests plugins pyproject.toml differ from 8267f9e5' $F/B-commit.out"
VERIFY532_GCOMMIT=deadbeef steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a graftling tag that does not peel to production's 0.6.2 commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.2^{commit} is .*, not deadbeef' $F/B-tag.out"
steps B > /dev/null 2>&1

head1 "product guard negatives on a scratch clone of the Worktree (src change committed; src change uncommitted)"
git clone -q --shared --no-checkout $WT $F/wtsrc && git -C $F/wtsrc checkout -q -b neg $NEW
print '# drift' >> $F/wtsrc/src/graphtraj/execution/runner_worker.py
ADOPT532_WT=$F/wtsrc steps B > $F/B-dirty.out 2>&1; BD=$?
check "guard negative: an uncommitted src change STOPs" sh -c "[ $BD -ne 0 ] && grep -q 'STOP: uncommitted changes in the Worktree.s src tests plugins pyproject.toml' $F/B-dirty.out"
git -C $F/wtsrc -c user.name=x -c user.email=x@invalid commit -qam 'drift'
ADOPT532_WT=$F/wtsrc steps B > $F/B-src.out 2>&1; BS=$?
check "guard negative: a committed src change STOPs (only scripts/ may differ)" sh -c "[ $BS -ne 0 ] && grep -q 'STOP: the Worktree.s src tests plugins pyproject.toml differ from a7b20447 (only scripts/ may differ): src/graphtraj/execution/runner_worker.py' $F/B-src.out"
git clone -q --shared --no-checkout $WT $F/wtscr && git -C $F/wtscr checkout -q -b scr $NEW
mkdir -p $F/wtscr/scripts/x; print x > $F/wtscr/scripts/x/a; git -C $F/wtscr add scripts; git -C $F/wtscr -c user.name=x -c user.email=x@invalid commit -qm 'scripts only'
ADOPT532_WT=$F/wtscr steps GR > $F/GR-scripts.out 2>&1
check "guard positive: a scripts-only commit on top of a7b20447 passes the guard" grep -q 'product guard: PASS' $F/GR-scripts.out

head1 "GR (read only): reuse 531's G at 83e84fba with graftling 4a002129"
steps GR > $F/GR.out 2>&1; GRR=$?; grep -E '^(product guard|reused G|candidate|graftling commit|totals|FAILED|CHECK)' $F/GR.out
check "GR exit 0: guard PASS and 'CHECK 532 reused G (531 83e84fba) no failure: PASS'" sh -c "[ $GRR -eq 0 ] && grep -q 'product guard: PASS' $F/GR.out && grep -q '^CHECK 532 reused G (531 83e84fba) no failure: PASS' $F/GR.out && grep -q '^CHECK 532 GR (guard + reused G): PASS' $F/GR.out"
check "GR: totals 3608 passed, 48 skipped, exit 0, 0 FAILED/ERROR lines" sh -c "grep -q 'totals: 3608 passed, 48 skipped | exit: 0' $F/GR.out && grep -q 'FAILED/ERROR lines (suite.txt, shards/\*.log, failures.txt): 0' $F/GR.out"
mkdir -p $F/gneg1 && cp -Rp $REALGR $F/gneg1/G && print 'FAILED tests/test_x.py::test_y - boom' >> $F/gneg1/G/shards/shard-0.log
$CONDA -I $SD/greuse532.py $F/gneg1/G 83e84fba8b450a3101f991936e41bfbfec17cc5d $GC > $F/gneg1.out 2>&1; GN1=$?
check "GR negative: a FAILED line in a shard log -> CHECK FAIL" sh -c "[ $GN1 -ne 0 ] && grep -q 'CHECK 532 reused G (531 83e84fba) no failure: FAIL' $F/gneg1.out"
mkdir -p $F/gneg2 && cp -Rp $REALGR $F/gneg2/G && sed -i '' 's/^candidate: 83e84fba[0-9a-f]*/candidate: 805ec01bb7b08f0d8f2e8d2a7e0d2b7c1a9e4f00/' $F/gneg2/G/run.txt
$CONDA -I $SD/greuse532.py $F/gneg2/G 83e84fba8b450a3101f991936e41bfbfec17cc5d $GC > $F/gneg2.out 2>&1; GN2=$?
check "GR negative: a G of another candidate -> CHECK FAIL" sh -c "[ $GN2 -ne 0 ] && grep -q '^candidate: 805ec01b.* NO' $F/gneg2.out && grep -q 'no failure: FAIL' $F/gneg2.out"
mkdir -p $F/gneg3 && cp -Rp $REALGR $F/gneg3/G && sed -i '' -e 's/^3608 passed, 48 skipped$/1 failed, 3607 passed, 48 skipped/' -e 's/^exit=0$/exit=1/' $F/gneg3/G/suite.txt
$CONDA -I $SD/greuse532.py $F/gneg3/G 83e84fba8b450a3101f991936e41bfbfec17cc5d $GC > $F/gneg3.out 2>&1; GN3=$?
check "GR negative: totals with a failure and exit=1 -> CHECK FAIL" sh -c "[ $GN3 -ne 0 ] && grep -q 'totals: 1 failed, 3607 passed, 48 skipped | exit: 1' $F/gneg3.out && grep -q 'no failure: FAIL' $F/gneg3.out"
$CONDA -I $SD/greuse532.py $REALGR 83e84fba8b450a3101f991936e41bfbfec17cc5d 483b16a8d6e05b1c866e69439fada8478791f1fb > $F/gneg4.out 2>&1; GN4=$?
check "GR negative: G run with another graftling commit (0.6.1's) -> CHECK FAIL" sh -c "[ $GN4 -ne 0 ] && grep -q 'no failure: FAIL' $F/gneg4.out"
ADOPT532_REUSEG=$F/gneg1/G steps GR > $F/GR-fail.out 2>&1; GRF=$?
check "GR step negative: exit != 0 and no PASS line written to GR.txt" sh -c "[ $GRF -ne 0 ] && ! grep -q 'no failure: PASS' $RW/GR.txt"
check "GR: earlier GR.txt kept as GR-<time>.txt" sh -c "ls $RW/GR-*.txt > /dev/null 2>&1"

head1 "V (stub plugin validate): plugin SAME; graftling unchanged; graphtraj differs in exactly the 531 files; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK 5|^  (expected|UNEXPECTED) |^graftling |^graphtraj |markers expected|503 layout|node resolves' $F/V.out
check "V: three plugin files SAME and the CHECK PASS (no trust dialog expected)" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)' $RW/V.txt) -eq 3 ] && grep -q \"CHECK 532 candidate plugin bytes equal production's (no plugin trust dialog expected): PASS\" $F/V.out"
check "V: graftling wheel = archive v0.6.2 and production graftling unchanged" sh -c "grep -q 'CHECK 532 graftling wheel equals git archive v0.6.2: PASS' $F/V.out && grep -q 'CHECK 532 graftling unchanged (production = v0.6.2 0.6.2): PASS' $F/V.out"
check "V: graphtraj wheel differs from production in exactly the three 531 files" sh -c "grep -q 'CHECK 532 graphtraj wheel a7b20447 differs from production 8267f9e5 in exactly the 531 files: PASS' $F/V.out && [ \$(grep -cE '^  expected graphtraj/(execution/runner_heartbeat|execution/runner_status|runtimes/claude/adapter).py' $RW/V-gtdiff.txt) -eq 3 ]"
check "V: markers present in the candidate and absent in production (5/5)" sh -c "grep -q 'markers expected present: PASS (5/5)' $F/V.out && grep -q 'markers expected absent: PASS (5/5)' $F/V.out"
check "V: one graftling and node resolution in the scratch venv" sh -c "grep -q '^503 layout: PASS' $F/V.out && [ \$(grep -c 'node resolves .*: PASS' $F/V.out) -ge 2 ]"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256

head1 "pkgdiff / markers negatives"
GTWH=($W/wheels-a7b20447/graphtraj-*.whl); GLWH=($W/glwheel-0.6.2/graftling-*.whl)
mkdir -p $F/aneg && cp -Rp $W/src-a7b20447/src $F/aneg/ && print '# changed after the commit' >> $F/aneg/src/graphtraj/execution/runner_status.py
$CONDA -I $SD/pkgdiff532.py graphtraj $GTWH[1] archive:$F/aneg/src "graphtraj wheel equals git archive a7b20447" - > $F/aneg.out 2>&1; AN=$?
check "pkgdiff negative: a wheel file that differs from the archive -> FAIL" sh -c "[ $AN -eq 1 ] && grep -q 'UNEXPECTED graphtraj/execution/runner_status.py (bytes differ)' $F/aneg.out && grep -q 'equals git archive a7b20447: FAIL' $F/aneg.out"
mkdir -p $F/glneg && cp -Rp $D/graftling $F/glneg/ && print '# production drift' >> $F/glneg/graftling/control.py
$CONDA -I $SD/pkgdiff532.py graftling $GLWH[1] $F/glneg "graftling unchanged (production = v0.6.2 0.6.2)" - > $F/glneg.out 2>&1; GL=$?
check "pkgdiff negative: a graftling differing from v0.6.2 -> unchanged CHECK FAIL" sh -c "[ $GL -eq 1 ] && grep -q 'UNEXPECTED graftling/control.py' $F/glneg.out && grep -q 'graftling unchanged .*: FAIL' $F/glneg.out"
mkdir -p $F/glneg2/a $F/glneg2/b && cp -Rp $D/graftling $D/graftling-0.6.2.dist-info $F/glneg2/a/ && cp -Rp $D/graftling $D/graftling-0.6.2.dist-info $F/glneg2/b/ && print '# x' >> $F/glneg2/b/graftling/locks.py
$CONDA -I $SD/pkgdiff532.py graftling $F/glneg2/b $F/glneg2/a "graftling unchanged (installed vs backup)" - > $F/glneg2.out 2>&1; GL2=$?
check "pkgdiff negative: installed graftling differing from the backup -> FAIL (I would STOP)" sh -c "[ $GL2 -eq 1 ] && grep -q 'UNEXPECTED graftling/locks.py' $F/glneg2.out"
mkdir -p $F/gtneg && cp -Rp $D/graphtraj $F/gtneg/ && cp -p $W/src-a7b20447/src/graphtraj/execution/runner_status.py $F/gtneg/graphtraj/execution/runner_status.py
$CONDA -I $SD/pkgdiff532.py graphtraj $GTWH[1] $F/gtneg "graphtraj wheel differs in exactly the 531 files" graphtraj/execution/runner_heartbeat.py,graphtraj/execution/runner_status.py,graphtraj/runtimes/claude/adapter.py > $F/gtneg.out 2>&1; GT=$?
check "pkgdiff negative: an expected 531 file that does not differ -> FAIL (expected but equal)" sh -c "[ $GT -eq 1 ] && grep -q \"expected but equal: \['graphtraj/execution/runner_status.py'\]\" $F/gtneg.out"
check "markers 'present' on production fails" sh -c "! $CONDA -I $SD/markers.py $D present > /dev/null"
VS=($FB/vvenv-a7b20447/lib/python*/site-packages(N))
check "markers 'absent' on the candidate fails" sh -c "! $CONDA -I $SD/markers.py $VS[1] absent > /dev/null"

head1 "Vu / Vc (stub claude: plugin not loaded, so Vc asks for Vu; setup shows graphtraj only in the isolated .mcp.json)"
steps Vu > $F/Vu.out 2>&1
check "Vu names the isolated path and 'Yes, proceed'" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc setup: isolated .mcp.json CHECK PASS and answer check OK" sh -c "grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc with the stub asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok   # rehearsal only: the real plugin load is not rehearsable

head1 "I refusal without GR PASS, then Mpre / I (USER): guard idle, backup, graphtraj-only install, graftling unchanged"
: > $F/ps.txt   # Main has exited
print | steps I > $F/I-noGR.out 2>&1; INR=$?
check "I negative: refuses while GR.txt has no PASS (last GR failed), and creates no backup" sh -c "[ $INR -ne 0 ] && grep -q 'GR 还不是 PASS' $F/I-noGR.out && [ ! -e $FB/backup ]"
steps GR > /dev/null 2>&1   # GR PASS again
print | ADOPT532_WT=$F/wtsrc steps I > $F/I-guard.out 2>&1; IGR=$?
check "I negative: with GR PASS, a Worktree src change makes I refuse at the guard, before any backup" sh -c "[ $IGR -ne 0 ] && grep -q 'Worktree 守卫 STOP' $F/I-guard.out && [ ! -e $FB/backup ]"
print -r -- "$HOSTLINE" > $F/ps.txt
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: GR PASS shown and the restart reason with file:line" sh -c "grep -q '^GR: PASS (CHECK 532 reused G (531 83e84fba) no failure: PASS)' $F/Mpre.out && grep -q 'host.py:115 与 interfaces/agents.py:825 导入 graphtraj.execution.runner_status' $F/Mpre.out"
: > $F/ps.txt   # Main has exited
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|^532 |CHECK 532|direct_url|built from|CHECK 515|configuration --write rc|plugin bytes|SAME-AS-VALIDATED|markers expected|changed:|bytes unchanged' $F/I.out
check "I: installed only graphtraj (force-reinstall), proddiff PASS, markers present 5/5" sh -c "grep -q '^Successfully installed graphtraj-0.1.0\$' $F/I.out && ! grep -qE '^ *Successfully (installed|uninstalled).*graftling' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'markers expected present: PASS (5/5)' $F/I.out"
check "I: installed graftling unchanged against the backup" grep -q 'CHECK 532 graftling unchanged (installed vs backup): PASS' $F/I.out
check "I: 531 fixes by name in the installed code" sh -c "grep -q '^532 805ec01b any_ownership_held: any_ownership_held | caller lookup uses it: True' $F/I.out && grep -q '^532 496cec58 Claude preflight reads history only for protected grants: True' $F/I.out"
check "I: sources: direct_url names the wheels-a7b20447 graphtraj wheel; built from a7b20447" sh -c "grep -q 'graphtraj-0.1.0.dist-info direct_url: .*wheels-a7b20447/graphtraj-0.1.0' $F/I.out && grep -q 'CHECK 532 graphtraj direct_url names the wheels-a7b20447 wheel: PASS' $F/I.out && grep -q 'built from: graphtraj git archive $NEW' $F/I.out"
check "I: configuration --write rc=0, .mcp.json CHECK PASS, SAME-AS-VALIDATED, plugin as before, 3 entries unchanged" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out && grep -q 'plugin bytes as before the install' $F/I.out && [ \$(grep -c '^bytes unchanged: ' $RW/I.txt) -eq 3 ]"
check "I: backup holds entries, plugin, tools (with pkgdiff532.py); COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/pkgdiff532.py ]"
check "I: prints the restart command and 'no dialog expected'" sh -c "grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: 无' $F/I.out"
check "I: graftling still the v0.6.2 wheel's bytes after the install" sh -c "$CONDA -I $SD/pkgdiff532.py graftling $GLWH[1] $D x - > /dev/null"

head1 "M / Mp after the restart"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt asks for notices since the resume and the mcp__graphtraj__ tools; next Mp" sh -c "grep -q 'Production was just upgraded by Task 532' $F/M.out && grep -q 'already seen that same notice' $F/M.out && grep -q \"next.*: zsh $SD/steps.zsh Mp\" $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"
steps inbox > $F/inbox.out 2>&1
check "inbox: next is Nw" grep -q "next.*: zsh $SD/steps.zsh Nw" $F/inbox.out

head1 "N text and the Worker CPU window (fixture samples; not blocking)"
steps N > $F/N.out 2>&1
check "N: one advisor member creates n532 through mcp__graphtraj__agents, waits, retires" sh -c "grep -q '\"task_id\":\"532\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n532' $F/N.out && grep -q 'Retire the child' $F/N.out"
T0=$(date +%s)
for i in 0 1 2 3 4 5 6; do
  at=$(( T0 + i * 10 )); run=$([[ $i -ge 3 ]] && print true || print null); cpu=$(( i < 3 ? i * 9 : 18 + (i - 3) ))
  print -r -- "{\"at\": $at, \"child_running\": $run, \"ps\": \"6161 1 1.0 0:$(printf %02d $cpu).00 01:00 python -m graphtraj.execution.runner_worker\"}"
done > $RW/Nw468-ps.txt
steps Nr > $F/Nr.out 2>&1; grep -E '^REPORT' $F/Nr.out
check "Nr: Worker CPU before 0.600 / after 0.100 reported, beside 528's 0.559/0.107 and 531's 0.488 -> 0.116" sh -c "grep -q 'before child creation: 0.600' $F/Nr.out && grep -q 'after child creation: 0.100' $F/Nr.out && grep -q '30 s before child creation 0.559, after 0.107' $F/Nr.out && grep -q '0.488 -> 0.116' $F/Nr.out"
check "Nr: without notices the one-notice CHECK is PENDING (never PASS)" grep -q 'CHECK 532 Main got exactly one completed notice of the member: PENDING' $F/Nr.out
print -l '# Main notices of the member' '[Graftling notice from 532-x-advisor@advisor · completed · execution e1] done' > $RW/N-main-notice.txt
steps Nr > $F/Nr2.out 2>&1
check "Nr: one completed notice line of an alias-less fixture is counted, not silently PASS" grep -qE 'CHECK 532 Main got exactly one completed notice of the member: (PASS|FAIL) \([0-9]+ notice lines' $F/Nr2.out
rm -f $RW/N-main-notice.txt

head1 "done: graftling unchanged, sources, no exported key value in raw files"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: graftling unchanged vs backup PASS, direct_url a7b20447, markers 5/5" sh -c "grep -q 'CHECK 532 graftling unchanged (installed vs backup): PASS' $F/done.out && grep -q 'graphtraj direct_url: .*wheels-a7b20447' $F/done.out && grep -q 'markers expected present: PASS (5/5)' $F/done.out"
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out

head1 "R (rollback from the backup's own tools): venv, plugin and entry files restored; graphtraj back to $OLD"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK 532|graphtraj package' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling identical to the backup before and after R" sh -c "grep -q 'CHECK 532 graftling identical to the backup before R (installed vs backup): PASS' $F/R.out && grep -q 'CHECK 532 graftling unchanged (after R vs backup): PASS' $F/R.out"
check "R: before R the graphtraj package differed in the three 531 files" sh -c "grep -q 'graphtraj package installed vs backup: .*runner_heartbeat.py.*runner_status.py.*adapter.py' $F/R.out || grep -q 'graphtraj package installed vs backup: .*adapter.py.*runner_heartbeat.py.*runner_status.py' $F/R.out"
check "R: production graphtraj markers absent again (8267f9e5), graftling 0.6.2" sh -c "$CONDA -I $SD/markers.py $D absent > /dev/null && $FRT/bin/python -m pip show graftling 2>/dev/null | grep 'Version: 0.6.2' > /dev/null"
check "528's backup under tmp/528 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
