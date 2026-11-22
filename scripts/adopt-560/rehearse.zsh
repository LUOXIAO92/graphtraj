#!/bin/zsh
# Rehearsal of adopt-560/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (modelled on adopt-532's).
# Starts no real host and never touches production, <Harness>/graftling or GraphTraj dev:
# - graftling: a scratch clone of <Harness>/graftling (dev = 9f962bc as at dispatch); rel fetches the bundle into it.
# - GraphTraj: a scratch clone of this Worktree whose local dev is 3b9c2af7 WITHOUT the candidate (Correction 1:
#   integration comes after the Leader's acceptance; B must not depend on it).
# - fake production: graphtraj wheel of a7b20447 + graftling wheel of the real v0.6.2 (git archive, read only), click,
#   yaml and websockets copied from production .venv-runtime (read only), and a copy (APFS clone) of production's Task
#   state: every Task's task.yml, task.md, definitions/, the Worldline and the task index (read only).
# - `claude`, `codex` and `ps` are stubs on PATH. The MCP server and the Codex hooks entry are the REAL entries of the
#   scratch venv and of the fake production venv.
# - G is rehearsed through its real entry (run_test_shards.py, 6 shards) with `-k` selecting real tests that use the
#   repository's fixtures (not --collect-only); GR then reads that record.
#   zsh scripts/adopt-560/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${${TMPDIR:-/tmp}:A}/${ADOPT560_REHEARSAL_NAME:-adopt560-rehearsal}
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/560
OB=$FH/tmp/532   # 532's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=$REALH/graftling
REALSTATE=$REALH/.graphtraj/core/state
GC=ef7c37db15f4e6318fd5b6bf5bd79321b876eac5
GBASE=9f962bcff91c37fc2aef177b4ab1457f3de5680b
NEW=8949caff74156d14625f45d7d6b762a04cef87eb
OLD=a7b20447ce9c4ffeee62aba026265f6a1e0f10d2
FG=$F/graftling          # scratch graftling repository
FWT=$F/wt                # scratch GraphTraj clone (dev = 3b9c2af7, without the candidate)
export ADOPT560_H=$FH ADOPT560_BASE=$FB ADOPT560_RT=$FRT ADOPT560_PNPM_SHIM=$F/no-shim ADOPT560_STUB=$F/stub ADOPT560_WT=$FWT ADOPT560_PROJECTS=$F/projects/-fake ADOPT560_WAIT=1 ADOPT560_OLDBASE=$OB ADOPT560_G=$FG ADOPT560_VPROJECT=$FB/vproject
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=560-graftling-0-6-3-release-and-production-adoption
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-${NEW[1,8]}
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "empty base: $F removed; zsh -n of every zsh file"
[[ -e $F ]] && chmod -R u+w $F; rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldg $F/oldwheels $FH $OB/backup $F/projects/-fake
for z in $SD/*.zsh; do zsh -n $z; check "zsh -n ${z:t}" [ $? -eq 0 ]; done
check "base $FB absent before 00" [ ! -e $FB ]
print "Worktree HEAD $(git -C $WT rev-parse HEAD) | candidate $NEW | graftling repository read only: $REALG (dev $(git -C $REALG rev-parse dev), main $(git -C $REALG rev-parse main))"

head1 "setup: scratch graftling clone (dev = $GBASE, main = v0.6.2), scratch GraphTraj clone (dev = 3b9c2af7, without the candidate)"
# The real repository may already be released (Main ran rel): the scratch clone is put back to the state before rel
# (dev = 9f962bc, main = v0.6.2, no v0.6.3, no release branch). The real refs are recorded and compared at the end.
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-before.txt
git clone -q --no-hardlinks $REALG $FG && git -C $FG checkout -q --detach && git -C $FG branch -q -f main 4a002129f8b97f32980afd59e5a1a64c428fe684 && git -C $FG checkout -q main && git -C $FG branch -q -f dev $GBASE
git -C $FG tag -d v0.6.3 > /dev/null 2>&1; git -C $FG branch -q -D agent/560-graftling-0.6.3 > /dev/null 2>&1; true
git -C $FG config user.name rehearsal; git -C $FG config user.email rehearsal@invalid
print "scratch graftling: dev $(git -C $FG rev-parse dev) main $(git -C $FG rev-parse main) v0.6.3 $(git -C $FG rev-parse -q --verify refs/tags/v0.6.3 || print absent)"
git clone -q --shared --no-checkout $WT $FWT && git -C $FWT checkout -q -b cand $(git -C $WT rev-parse HEAD) && git -C $FWT branch -q -f dev 3b9c2af758dd7ff29d7482a03ebb4dec1477ddd1
print "scratch GraphTraj: HEAD $(git -C $FWT rev-parse HEAD) dev $(git -C $FWT rev-parse dev)"

head1 "setup: fake production = graphtraj $OLD + graftling v0.6.2, plugin, configuration, production Task state copy"
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
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-560-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.171.0 (stub)" ;;
  exec) print -u2 "model: gpt-5.5-codex (stub configured model)"; print "CODEX-560-OK" ;;
  *) print "stub codex: $*" ;;
esac
EOF
chmod +x $F/stub/claude $F/stub/codex
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
# production keeps its Task state in .graphtraj/core/state (STATE in steps.zsh); the fake configuration says the same
for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
  $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c
done
grep -h 'state:' $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N)
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
$CONDA -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["enabledMcpjsonServers"]=["graphtraj"]; d["enableAllProjectMcpServers"]=True; open(p,"w").write(json.dumps(d, indent=2)+"\n")' $FH/.claude/settings.local.json
print "fake production .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json)"
# production Task state (read only; APFS clones): what the 563 migration reads and writes
FS=$FH/.graphtraj/core/state
rm -rf $FS/tasks $FS/worldline; mkdir -p $FS/tasks
cp -cRp $REALSTATE/worldline $FS/ && cp -cp $REALSTATE/task-index.json(N) $FS/
for d in $REALSTATE/tasks/[^.]*(N/); do
  mkdir $FS/tasks/$d:t && cp -cp $d/task.yml $d/task.md(N) $FS/tasks/$d:t/
  [[ -d $d/definitions ]] && cp -cRp $d/definitions $FS/tasks/$d:t/
done
print 'stopped: false' > $ST/$TASK/execution-budget.yml
print "fake production Task state: $(print -l $FS/tasks/[^.]*(N/) | wc -l | tr -d ' ') Tasks, $(print -l $FS/tasks/*/task.md(N) | wc -l | tr -d ' ') task.md"
print "532 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/532 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
mkdir -p $FH/.graphtraj/swarm/sessions $FH/.graphtraj/swarm/control
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

head1 "00 (Claude and Codex answer; TMPDIR outside; 560 markers absent in production; unmigrated state counted)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|isolation:|answer check|Claude Code installed|codex|CHECK 560|TMPDIR|Task directories|Version|532 backup)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: Claude answer check OK and Codex CHECK PASS" sh -c "grep -q 'answer check (expect clean): OK' $F/00.out && grep -q 'CHECK 560 Codex answers CODEX-560-OK (configured model, logged in): PASS' $F/00.out"
check "00: TMPDIR outside the Harness, zsh interpreter" sh -c "grep -q '(outside the Harness)' $F/00.out && grep -q 'interpreter: zsh' $F/00.out"
check "00: 560 markers absent in production (6/6), graftling 0.6.2" sh -c "grep -q 'markers expected absent: PASS (6/6)' $F/00.out && grep -q '^Version: 0.6.2' $F/00.out"
check "00: unmigrated task.md counted" grep -qE 'task.md: [1-9][0-9]*' $F/00.out
check "00 next is rel" grep -q "next.*: zsh $SD/steps.zsh rel" $F/00.out

head1 "B before rel (no v0.6.3 tag yet) refuses"
steps B > $F/B-norel.out 2>&1; BN=$?
check "B negative: without rel, v0.6.3 is missing -> STOP" sh -c "[ $BN -ne 0 ] && grep -q 'STOP: v0.6.3^{commit} is missing' $F/B-norel.out"

head1 "rel negatives on second scratch clones: dev moved; a wrong v0.6.3 tag"
git clone -q --no-hardlinks $FG $F/gmoved && git -C $F/gmoved checkout -q main && git -C $F/gmoved branch -q -f dev 53b96aa
ADOPT560_G=$F/gmoved steps rel > $F/rel-moved.out 2>&1; RM=$?
check "rel negative: graftling dev not at 9f962bc -> STOP, nothing changed" sh -c "[ $RM -ne 0 ] && grep -q 'STOP: graftling dev is 53b96aa' $F/rel-moved.out && [ \$(git -C $F/gmoved rev-parse dev) = \$(git -C $F/gmoved rev-parse 53b96aa) ] && ! git -C $F/gmoved rev-parse -q --verify refs/tags/v0.6.3 > /dev/null"
git clone -q --no-hardlinks $FG $F/gwrong && git -C $F/gwrong checkout -q main && git -C $F/gwrong branch -q -f dev $GBASE && git -C $F/gwrong -c user.name=x -c user.email=x@invalid tag -a v0.6.3 $GBASE -m wrong
ADOPT560_G=$F/gwrong steps rel > $F/rel-wrong.out 2>&1; RW1=$?
check "rel negative: an existing v0.6.3 at another commit -> STOP" sh -c "[ $RW1 -ne 0 ] && grep -q 'STOP: v0.6.3 exists at' $F/rel-wrong.out"

head1 "rel (scratch graftling): fetch the bundle, dev and main fast-forward, annotated noreply tag"
steps rel > $F/rel.out 2>&1; RRC=$?; grep -E 'CHECK|version at|= $GC|dev:' $F/rel.out
check "rel exit 0 with three CHECK PASS" sh -c "[ $RRC -eq 0 ] && [ \$(grep '^CHECK 560 .*: PASS' $F/rel.out | sort -u | wc -l) -eq 3 ] && ! grep -q '^CHECK 560 .*: FAIL' $F/rel.out"
check "rel: v0.6.3 = dev = main = $GC, tagger noreply" sh -c "[ \$(git -C $FG rev-parse 'v0.6.3^{commit}') = $GC ] && [ \$(git -C $FG rev-parse dev) = $GC ] && [ \$(git -C $FG rev-parse main) = $GC ] && git -C $FG for-each-ref --format='%(taggeremail)' refs/tags/v0.6.3 | grep -q '89069722+LUOXIAO92@users.noreply.github.com'"
check "rel: prints the push as a separate confirmed step and the GraphTraj integration" sh -c "grep -q 'ADOPT560_PUSH_CONFIRMED=yes' $F/rel.out && grep -q 'GraphTraj 集成' $F/rel.out"
steps rel > $F/rel2.out 2>&1
check "rel again: already released, nothing to do" grep -q 'already released' $F/rel2.out
steps rp > $F/rp.out 2>&1; RP=$?
check "rp without the USER's confirmation refuses (no push)" sh -c "[ $RP -ne 0 ] && grep -q 'STOP: the push is outward-facing' $F/rp.out"

head1 "B: wheels from git archive v0.6.3 (archive root) and of the candidate; layout proof; requirement pairs"
steps B > $F/B.out 2>&1; BRC=$?; check "B exit 0" [ $BRC -eq 0 ]
grep -E 'whl|leaked|peels|annotated|archive root|CHECK|RESULT|markers expected|GraphTraj dev' $F/B.out
check "B: GraphTraj dev reported as information only; v0.6.3 annotated, peels to $GC" sh -c "grep -q 'dev contains ${NEW[1,8]}: no' $F/B.out && ! grep -q 'GraphTraj dev product = candidate' $F/B.out && grep -q 'v0.6.3 peels to $GC: yes' $F/B.out && grep -q 'v0.6.3 is an annotated tag (cat-file -t: tag): yes' $F/B.out"
check "B: root layout and the six layout CHECKs PASS" sh -c "grep -q 'archive root pyproject.toml: yes | src/graftling/pyproject.toml: absent' $F/B.out && [ \$(grep '^CHECK 560 layout .*: PASS' $F/B.out | sort -u | wc -l) -eq 5 ] && grep -q '^RESULT 560 layout: PASS' $F/B.out"
check "B: Requires-Dist satisfied by 0.6.3 and NOT by 0.6.2" sh -c "grep -q 'CHECK 560 Requires-Dist graftling<0.7,>=0.6.3 satisfied by 0.6.3: PASS' $F/B.out && grep -q 'CHECK 560 Requires-Dist graftling<0.7,>=0.6.3 NOT satisfied by 0.6.2: PASS' $F/B.out"
check "B: both wheels = their archives; markers present 6/6; leaked 0" sh -c "grep -q 'CHECK 560 graphtraj wheel equals git archive ${NEW[1,8]}: PASS' $F/B.out && grep -q 'CHECK 560 graftling wheel equals git archive v0.6.3: PASS' $F/B.out && grep -q 'markers expected present: PASS (6/6)' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: the install directory holds exactly graphtraj-0.1.0 and graftling-0.6.3" sh -c "[ \$(ls $W/wheels-${NEW[1,8]}/*.whl | wc -l) -eq 2 ] && ls $W/wheels-${NEW[1,8]}/graftling-0.6.3-*.whl > /dev/null"
VERIFY560_GCOMMIT=$GBASE steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the expected commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.3^{commit} is $GC, not $GBASE' $F/B-tag.out"
VERIFY560_TARGET=$OLD steps B > $F/B-commit.out 2>&1; BC=$?
check "B negative: a wrong GraphTraj target commit STOPs at the guard" sh -c "[ $BC -ne 0 ] && grep -q 'STOP: the Worktree.s src tests plugins pyproject.toml differ from ${OLD[1,8]}' $F/B-commit.out"
steps B > $F/B-dev.out 2>&1; BDV=$?
check "B positive (Correction 1): GraphTraj dev without the candidate does not gate B; it prints 'dev contains ${NEW[1,8]}: no'" sh -c "[ $BDV -eq 0 ] && grep -q 'dev contains ${NEW[1,8]}: no' $F/B-dev.out && grep -q '^RESULT 560 layout: PASS' $F/B-dev.out"
print '# drift' >> $FWT/src/graphtraj/execution/runner_worker.py
steps B > $F/B-dirty.out 2>&1; BD=$?
check "guard negative: an uncommitted src change STOPs" sh -c "[ $BD -ne 0 ] && grep -q 'STOP: uncommitted changes in the Worktree.s src tests plugins pyproject.toml' $F/B-dirty.out"
git -C $FWT checkout -q -- src
steps B > /dev/null 2>&1

head1 "G through its real entry (6 shards, -k selects real tests with repository fixtures), then GR on that record"
ADOPT560_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_graphtraj_uses_only_published_agents_names or test_every_public_name_is_listed_in_the_contract'" steps G > $F/G.out 2>&1; GRC=$?
GO=$(sed -n 's/.*ADOPT560_GREC=\([^ ]*\) zsh.*/\1/p' $F/G.out | tail -1); print "G record: $GO"; cat $GO/run.txt 2>/dev/null
check "G started: pytest temp under TMPDIR, dependencies recorded (click 8.5.0)" sh -c "[ $GRC -eq 0 ] && grep -q 'pytest temp root: ${${TMPDIR:-/tmp}:A}/adopt-560-G-' $GO/run.txt && grep -q 'click 8.5.0' $GO/run.txt"
[[ -n $GO ]] && for i in {1..90}; do grep -q '^exit=' $GO/suite.txt 2>/dev/null && break; sleep 5; done; sleep 3
tail -3 $GO/suite.txt; grep -hE '^[0-9]+ passed|passed' $GO/shards/*.log | tail -6
check "G rehearsal: the three selected real tests PASSED (not collect-only), '3 passed', no FAILED line" sh -c "[ \$(grep -hoE '^PASSED tests/(test_runtime_distribution|test_graphtraj_public_agents_api)\.py::[a-z_]+' $GO/shards/*.log | sort -u | wc -l) -eq 3 ] && grep -q '^3 passed' $GO/suite.txt && ! grep -qE '^(FAILED|ERROR) ' $GO/failures.txt"
check "G rehearsal: shards with nothing selected end 'exit 5' (pytest: no tests), so the run's exit is 1" sh -c "grep -q '^exit=1' $GO/suite.txt && ! grep 'ABNORMAL' $GO/suite.txt | grep -v 'exit 5' | grep -q ."
ADOPT560_GREC=$GO steps GR > $F/GR-G.out 2>&1; GRG=$?
check "GR on the G rehearsal record: candidate, graftling commit and click accepted; exit=1 without classed lines -> FAIL (GR never accepts a nonzero exit by itself)" sh -c "[ $GRG -ne 0 ] && grep -q 'same product: yes' $F/GR-G.out && grep -q '= v0.6.3 ($GC): yes' $F/GR-G.out && grep -q 'click = production.s 8.5.0: yes' $F/GR-G.out && grep -q 'exit: 1' $F/GR-G.out && grep -q 'no new failure: FAIL' $F/GR-G.out"

head1 "GR mechanics on a REHEARSAL FIXTURE record (the known failures as observed in the Engineer's run), and negatives on copies"
# The fixture is not evidence of a suite result: it holds this candidate, the v0.6.3 commit, production's click, and
# the known failure blocks copied from the committed G-record when present. The committed record's own GR verdict is
# printed after the checks (information; it is the evidence, reported in engineer.md).
GX=$F/grec; mkdir -p $GX
print -l "pytest temp root: ${${TMPDIR:-/tmp}:A}/fixture (REHEARSAL FIXTURE)" "candidate: $(git -C $FWT rev-parse HEAD) | graftling wheel from git archive $GC (REHEARSAL FIXTURE)" \
  "test interpreter dependencies: click 8.5.0 (fixture) | PyYAML 6.0.3 (fixture) | websockets 16.1.1 (fixture) | pytest 9.1.1 (fixture)" > $GX/run.txt
print -l "REHEARSAL FIXTURE" "4 failed, 3690 passed, 48 skipped" "exit=1" > $GX/suite.txt
for t in 'helper-main' 'thread-1-main' 'helper-independent' 'thread-1-independent'; do
  print -l "FAILED tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[$t]" '    E       assert False' '    at tests/test_native_gateway.py:88'
done > $GX/failures.txt
print -l 'FAILED tests/test_mcp_host_tools.py::test_installed_mcp_server_keeps_the_continue_path_on_the_request_caller' '    E           assert 1.0 < 0.9' '    at tests/test_mcp_host_tools.py:1489' >> $GX/failures.txt
ADOPT560_GREC=$GX steps GR > $F/GR.out 2>&1; GRR=$?; grep -E '^(product guard|candidate|graftling commit|totals|test interpreter|  known|  NEW|failed tests|CHECK)' $F/GR.out
check "GR on the fixture: the four gateway params known (551/556, :88), the 516 helper failure known flaky; PASS" sh -c "[ $GRR -eq 0 ] && [ \$(grep '^  known: tests/test_native_gateway.py' $F/GR.out | sort -u | wc -l) -eq 4 ] && grep -q 'names the helper _assert_native_budget_stop' $F/GR.out && grep -q '^CHECK 560 GR (guard + G record): PASS' $F/GR.out"
mkdir -p $F/gneg && cp -Rp $GX $F/gneg/a && print -l 'FAILED tests/test_x.py::test_y' '    E       AssertionError: boom' >> $F/gneg/a/failures.txt
ADOPT560_GREC=$F/gneg/a steps GR > $F/GR-n1.out 2>&1; GN1=$?
check "GR negative: an unknown FAILED test -> NEW, FAIL, and no PASS left in GR.txt" sh -c "[ $GN1 -ne 0 ] && grep -q '  NEW: tests/test_x.py::test_y' $F/GR-n1.out && ! grep -q 'GR (guard + G record): PASS' $RW/GR.txt"
cp -Rp $GX $F/gneg/b &&print -l 'FAILED tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[helper-main]' '    E       KeyError: other' '    at tests/test_native_gateway.py:70' >> $F/gneg/b/failures.txt
ADOPT560_GREC=$F/gneg/b steps GR > $F/GR-n2.out 2>&1; GN2=$?
check "GR negative: a known test failing for another reason -> NEW" sh -c "[ $GN2 -ne 0 ] && grep -q 'NEW (known test, other cause' $F/GR-n2.out"
cp -Rp $GX $F/gneg/c &&sed -i '' -E 's/git archive [0-9a-f]{40}/git archive 4a002129f8b97f32980afd59e5a1a64c428fe684/' $F/gneg/c/run.txt
ADOPT560_GREC=$F/gneg/c steps GR > $F/GR-n3.out 2>&1; GN3=$?
check "GR negative: a G run with another graftling commit (0.6.2) -> FAIL" sh -c "[ $GN3 -ne 0 ] && grep -q 'graftling commit of the wheel: 4a002129.* NO' $F/GR-n3.out"
cp -Rp $GX $F/gneg/d &&sed -i '' 's/click 8\.5\.0/click 8.2.1/' $F/gneg/d/run.txt
ADOPT560_GREC=$F/gneg/d steps GR > $F/GR-n4.out 2>&1; GN4=$?
check "GR negative: a test interpreter with Miniconda's click 8.2.1 -> FAIL" sh -c "[ $GN4 -ne 0 ] && grep -q 'not production.s 8.5.0 (564): NO' $F/GR-n4.out"
ADOPT560_GREC=$GX steps GR > /dev/null 2>&1   # the fixture's PASS stands in for the record in the I/R rehearsal below
check "GR: earlier GR.txt kept as GR-<time>.txt" sh -c "ls $RW/GR-*.txt > /dev/null 2>&1"

head1 "V: plugin change only host_context.mjs; real MCP tools/list and Codex hooks entry; 563 demo on a copy of the state"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK|RESULT|^(PASS|FAIL):|markers expected|preview rc|migrate rc|again rc|planned renames|renamed:|state copy|plugin dialog' $F/V.out
check "V: plugin CHECK PASS (only hooks/host_context.mjs may change)" grep -q 'CHECK 560 candidate plugin changes only hooks/host_context.mjs (533): PASS' $F/V.out
check "V: real graphtraj-mcp lists exactly agents, tasks; Codex hooks entry two CHECKs PASS" sh -c "grep -q 'CHECK 560 scratch-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/V.out && [ \$(grep '^CHECK 560 Codex hooks entry .*: PASS' $F/V.out | sort -u | wc -l) -eq 2 ]"
check "V: 563 demo: preview, migrate, again renames nothing, all hashes equal" sh -c "grep -q 'CHECK 560 563 second run renames nothing: PASS' $F/V.out && grep -q '^RESULT: PASS' $F/V.out && grep -q 'CHECK 560 563 migration: every Task.s current definition and all versions hash-equal: PASS' $F/V.out"
check "V: markers present in the candidate and absent in production (6/6)" sh -c "grep -q 'markers expected present: PASS (6/6)' $F/V.out && grep -q 'markers expected absent: PASS (6/6)' $F/V.out"
check "V: read check of the migrated copy (task graph)" grep -q 'task graph of the clone: tasks =' $F/V.out
check "V wrote nothing to production entry files; fake production state still unmigrated" sh -c "shasum -a 256 -c --quiet $F/entries0.sha256 && ls $FS/tasks/*/task.md > /dev/null 2>&1"

head1 "negatives: migration hash mismatch; 0.6.2 left installed; markers both ways"
DM=$FB/demo/h/.graphtraj/core/state
t=$F/hneg/missing; mkdir -p $F/hneg && cp -cRp $DM $F/hneg/state && t=$(print -l $F/hneg/state/tasks/*/definitions/*.md(N[1])); chmod u+w $t; print 'tampered' >> $t
(cd $TMPDIR && $FB/vvenv-${NEW[1,8]}/bin/python -I $SD/defs563.py hashes $F/hneg/state $F/hneg/after.json > /dev/null && $FB/vvenv-${NEW[1,8]}/bin/python -I $SD/defs563.py compare $FB/demo/V-before.json $F/hneg/after.json $F/hneg/state > $F/hneg.out 2>&1); HN=$?
check "migration negative: one changed definition -> hash compare FAIL" sh -c "[ $HN -ne 0 ] && grep -q '^FAIL: every Task keeps all version contents' $F/hneg.out && grep -q '^RESULT: FAIL' $F/hneg.out"
VS=($FB/vvenv-${NEW[1,8]}/lib/python*/site-packages(N))
mkdir -p $F/lneg && cp -Rp $VS[1] $F/lneg/site && cp -Rp $D/graftling-0.6.2.dist-info $F/lneg/site/
$CONDA -I $SD/proddiff.py $F/lneg/site $F/lneg $W/wheels-${NEW[1,8]} > $F/lneg.out 2>&1; LN=$?
check "proddiff negative: graftling 0.6.2's dist-info left beside 0.6.3 -> FAIL (LEFTOVER)" sh -c "[ $LN -ne 0 ] && grep -q 'LEFTOVER' $F/lneg.out"
check "markers 'present' on production fails; 'absent' on the candidate fails" sh -c "! $CONDA -I $SD/markers.py $D present > /dev/null && ! $CONDA -I $SD/markers.py $VS[1] absent > /dev/null"

head1 "Vu / Vc (stub claude: plugin not loaded, so Vc asks for Vu)"
steps Vu > $F/Vu.out 2>&1
check "Vu names the isolated path and 'Yes, proceed'" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc setup: isolated .mcp.json CHECK PASS and answer check OK" sh -c "grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc with the stub asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok   # rehearsal only: the real plugin load is not rehearsable

head1 "guard refusal, I refusal without GR PASS, then Mpre / I (USER): backup, pair install, migration"
print -r -- "77 1 $FRT/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $F/ps.txt
steps _backup > $F/I-busy.out 2>&1; IB=$?
check "guard negative: a member Worker under the venv -> BLOCKING, no backup made" sh -c "[ $IB -ne 0 ] && grep -q 'guard: BLOCKING 1' $F/I-busy.out && [ ! -e $FB/backup ]"
: > $F/ps.txt   # Main has exited, no member runs
cp -p $RW/GR.txt $F/GR-good.txt; print 'CHECK 560 GR (guard + G record): FAIL' > $RW/GR.txt
print | steps I > $F/I-noGR.out 2>&1; INR=$?
check "I negative: refuses while GR.txt has no PASS, and creates no backup" sh -c "[ $INR -ne 0 ] && grep -q 'GR 还不是 PASS' $F/I-noGR.out && [ ! -e $FB/backup ]"
cp -p $F/GR-good.txt $RW/GR.txt
print -r -- "$HOSTLINE" > $F/ps.txt
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: GR PASS shown; restart reason names the migrated state" sh -c "grep -q '^GR: PASS (CHECK 560 GR (guard + G record): PASS)' $F/Mpre.out && grep -q 'Task 状态已迁移' $F/Mpre.out"
: > $F/ps.txt
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|CHECK|RESULT|direct_url|built from|configuration --write rc|plugin files|SAME-AS-VALIDATED|markers expected|bytes unchanged|state copy|preview rc|migrate rc|again rc|renamed:|backup:' $F/I.out
check "I: both wheels installed together, proddiff PASS, 0.6.2 dist-info gone, markers 6/6" sh -c "grep -q '^Successfully installed graftling-0.6.3 graphtraj-0.1.0' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'CHECK 560 graftling 0.6.2 dist-info gone: PASS' $F/I.out && grep -q 'markers expected present: PASS (6/6)' $F/I.out"
check "I: direct_url of both names wheels-${NEW[1,8]}; built from both archives" sh -c "grep -q 'CHECK 560 direct_url of both names the wheels-${NEW[1,8]} wheels: PASS' $F/I.out && grep -q 'built from: graphtraj git archive $NEW, graftling git archive v0.6.3 $GC' $F/I.out"
check "I: configuration --write rc=0, plugin change only host_context.mjs, .mcp.json PASS, SAME-AS-VALIDATED" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 560 installed plugin changes only hooks/host_context.mjs: PASS' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out"
check "I: real entries of the installed venv: MCP tools/list and Codex hooks PASS" sh -c "grep -q 'CHECK 560 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/I.out && [ \$(grep '^CHECK 560 Codex hooks entry .*: PASS' $F/I.out | sort -u | wc -l) -eq 2 ]"
check "I: migration of the fake production: again renames nothing, hashes equal, backup copy = state before" sh -c "grep -q 'CHECK 560 563 second run renames nothing: PASS' $F/I.out && grep -q 'CHECK 560 563 migration: every Task.s current definition and all versions hash-equal: PASS' $F/I.out && grep -q 'CHECK 560 backup state copy equals the state just before the migration: PASS' $F/I.out && ! ls $FS/tasks/*/task.md > /dev/null 2>&1"
check "I: backup holds venv, plugin, entries, tools, pre-migration state; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/defs563.py ] && [ -f $FB/backup/state/links.tsv ] && [ -s $FB/backup/state.hashes.json ]"
check "I: prints the restart command and the expected dialog from V" sh -c "grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: plugin dialog expected at claude --continue' $F/I.out"

head1 "M / Mp after the restart; done"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt: upgraded by Task 560, tools present, task_graph reads the migrated state" sh -c "grep -q 'Production was just upgraded by Task 560' $F/M.out && grep -q 'execute task_graph' $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"
steps N > $F/N.out 2>&1
check "N: one advisor member of Task 560 creates n560" sh -c "grep -q '\"task_id\":\"560\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n560' $F/N.out"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: versions, direct_urls, no 0.6.2 left, state migrated, real entries PASS, no key value" sh -c "grep -q '^Version: 0.6.3' $F/done.out && grep -q 'graftling direct_url: .*wheels-${NEW[1,8]}' $F/done.out && grep -q 'graftling 0.6.2 dist-info left: 0' $F/done.out && grep -q 'Task state now: task.md 0' $F/done.out && grep -q 'CHECK 560 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/done.out && grep -q 'raw files containing an exported key value: 0' $F/done.out"

head1 "R (rollback from the backup's own tools): both packages and the pre-migration Task state restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK|graphtraj package|before R|Tasks created after|task.md files' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling and graphtraj restored (vs backup)" sh -c "grep -q 'CHECK 560 graftling restored (after R vs backup): PASS' $F/R.out && grep -q 'CHECK 560 graphtraj restored (after R vs backup): PASS' $F/R.out"
check "R: Task state equals the pre-migration copy; task.md files back" sh -c "grep -q 'CHECK 560 Task state after R equals the pre-migration copy .*: PASS' $F/R.out && ls $FS/tasks/*/task.md > /dev/null 2>&1"
check "R: production graftling 0.6.2 and markers absent again" sh -c "$FRT/bin/python -m pip show graftling 2>/dev/null | grep -q 'Version: 0.6.2' && $CONDA -I $SD/markers.py $D absent > /dev/null"
check "R: the old code reads the restored state (task graph loads)" sh -c "cd $FH && $FRT/bin/python -I -c 'from pathlib import Path; from graphtraj.graph.task_graph import read_graph; g = read_graph(Path(\"$FS\"), view=\"full\"); print(\"old code task graph:\", len(g[\"tasks\"]))'"
check "532's backup under tmp/532 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-after.txt
check "real <Harness>/graftling untouched by the rehearsal (every branch and tag as at the start)" cmp -s $F/realg-refs-before.txt $F/realg-refs-after.txt

head1 "information (not a rehearsal check): GR's verdict on the committed record $SD/G-record"
[[ -f $SD/G-record/run.txt ]] && { ADOPT560_GREC=$SD/G-record steps GR 2>&1 | grep -E '^(candidate|graftling commit|test interpreter click|totals|  known|  NEW|failed tests|CHECK)'; } || print "no committed record"

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
