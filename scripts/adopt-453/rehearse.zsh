#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-448/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv).
#   zsh scripts/adopt-453/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt453-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$F/home/graphtraj-adoption-453
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
OLD=2be27dd664ce2388c969156c8238f63774567246   # production now: 448's wheels
export ADOPT453_H=$FH ADOPT453_BASE=$FB ADOPT453_RT=$FRT ADOPT453_PNPM_SHIM=$F/no-shim ADOPT453_STUB=$F/stub ADOPT453_WT=$WT ADOPT453_PROJECTS=$F/projects ADOPT453_WAIT=1
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=453-production-adoption-449-450
W=$FH/.graphtraj/core/state/tasks/$TASK/adoption
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0
check() { local what=$1; shift; if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "setup: old wheels from $OLD, fake production venv, plugin, configuration"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldwheels $FH $FB
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in --version) print "stub-claude 0.0" ;; plugin) print "✔ Validation passed (stub)" ;; *) print "stub claude: $*" ;; esac
EOF
cat > $F/stub/ps <<EOF
#!/bin/zsh
print "1 1 /sbin/launchd"
[[ -e $F/ps.txt ]] && cat $F/ps.txt
exit 0
EOF
chmod +x $F/stub/claude $F/stub/ps
git -C $WT archive $OLD | tar -x -C $F/oldsrc
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldsrc/src/graftling
ls $F/oldwheels
git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
$CONDA -m venv $FRT
$FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
D=$FRT/lib/python3.13/site-packages
cp -Rp $CSITE/click $CSITE/click-*.dist-info(N) $CSITE/yaml $CSITE/_yaml(N) $CSITE/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/
# Import-only stub of the websockets names the source imports (no network is ever opened here).
mkdir -p $D/websockets/asyncio $D/websockets/sync $D/websockets-16.1.1.dist-info
print -l 'Metadata-Version: 2.1' 'Name: websockets' 'Version: 16.1.1' > $D/websockets-16.1.1.dist-info/METADATA; : > $D/websockets-16.1.1.dist-info/RECORD; print '__version__ = "0.0-stub"' > $D/websockets/__init__.py
for m in client frames http http11 protocol uri exceptions asyncio/__init__ asyncio/client sync/__init__ sync/client; do
  print -l 'class _S:' '    def __init__(self, *a, **k): pass' \
    'ClientProtocol = Frame = Opcode = ConnectionClosed = _S' 'OPEN = 1' 'Request = Response = _S' 'def connect(*a, **k): raise OSError("stub")' 'def parse_uri(u): return u' > $D/websockets/$m.py
done
(cd $FH && print y | $FRT/bin/graphtraj setup) | tail -2
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
mkdir -p $W:h/definitions $W:h/teams/1; cp $WT/.state/task.yml $W:h/; print 'stopped: false' > $W:h/execution-budget.yml
def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
for f in $WT/.state/task.md $WT/.state/$def; do
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $W:h/${f#$WT/.state/}
done

MAINID=11111111-2222-3333-4444-555555555555
mkdir -p $F/projects; : > $F/projects/$MAINID.jsonl
HOSTLINE="4242 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
TIMERLINE="5151 1 $FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $FH/.graphtraj/core/runner/sessions/451-x 0123abcd 777"
WORKERLINE="6161 1 $FRT/bin/python -I -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/452-y/resume.yml"
# ps stub: '-p 4241' is the host's parent (claude --continue, no id in argv); otherwise ps.txt.
cat > $F/stub/ps <<EOF
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF
chmod +x $F/stub/ps

head1 "00 (host's parent is 'claude --continue'; Main from the newest transcript)"
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt
steps 00 > $F/00.out 2>&1
check "00 found Main through claude --continue + newest transcript" grep -q "MAIN=$MAINID" $F/00.out
check "00 classified the timer as NON-BLOCKING" grep -q 'NON-BLOCKING' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
grep -E 'inherited|MAIN=|claude --continue|running lines|^Version|guard|\[' $F/00.out | grep -v '^\[00\]'

head1 "B"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked' $F/B.out

head1 "V (stub plugin validate)"
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
steps V > $F/V.out 2>&1; check "V exit 0" [ $? -eq 0 ]
grep -E '^(SAME|CHANGED)|449|STOP|✘|差异' $F/V.out
check "V: 449 notice-title change recognised, local form kept" grep -q "449 hook change: notice title gains" $F/V.out
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
grep -E '^[<>]' $W/raw/V-plugin.diff
touch $W/raw/Vc.ok; print "NOT REHEARSED: Vc (real Claude Code); marker made by hand."

head1 "S refuses while another run_test_shards runs (quiet-host check only; the suite itself is not run here)"
print -l -- "7171 1 python scripts/run_test_shards.py --shards 6" >> $F/ps.txt
steps S > $F/S.out 2>&1; check "S refused" [ $? -ne 0 ]; grep -E 'loadavg|other pytest|STOP' $F/S.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "I waits while a member Worker and Main's host run, then passes with only the idle timer left"
print -l -- $HOSTLINE $TIMERLINE $WORKERLINE > $F/ps.txt
( sleep 3; print -l -- $TIMERLINE > $F/ps.txt.new; mv $F/ps.txt.new $F/ps.txt ) &
REMOVER=$!
print | steps I > $F/I.out 2>&1; IRC=$?
wait $REMOVER
check "I exit 0" [ $IRC -eq 0 ]
check "I waited (printed the waiting line at least once)" grep -q '正在等待' $F/I.out
check "I listed the member Worker as BLOCKING" grep -q '\[member Worker\]' $F/I.out
check "I never listed the timer as BLOCKING" sh -c "! grep -q 'BLOCKING.*budget_idle_timer\|\] .*budget_idle_timer' $F/I.out"
grep -E '正在等待|BLOCKING|NON-BLOCKING|^-rw|^PASS|^FAIL|Successfully|SAME-AS|449 installed|450 member|bytes unchanged|^changed|claude --continue' $F/I.out | uniq
check "proddiff PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $W/raw/I-verify.txt
check "backup entry copies are all -rw-------" sh -c "[ \$(ls -A $FB/backup/entries | wc -l) -eq 3 ] && ! stat -f '%Sp' $FB/backup/entries/.[!.]* $FB/backup/entries/* 2>/dev/null | grep -qv -- '-rw-------'"
stat -f '%Sp %N' $FB/backup/entries/*(D)
check "I printed claude --continue" grep -q "cd $FH && claude --continue" $F/I.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version|continue' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT

head1 "Mps accepts a host whose parent is claude --continue"
print -l -- $HOSTLINE > $F/ps.txt; mkdir -p $FH/.graphtraj/claude-host; print "x outcome=ok" >> $FH/.graphtraj/claude-host/host.log
steps Mps > $F/Mps.out 2>&1; grep -E '^(host uses|parent)' $F/Mps.out
check "Mps: parent is claude --continue ... yes" grep -q 'parent is claude --continue or --resume .*: yes' $F/Mps.out

head1 "Nr on synthetic records (member found by alias; swarm agent parsed from raw/N.txt)"
A=$FH/.graphtraj/swarm/control/agents; mkdir -p $A $FH/.graphtraj/swarm/sessions/sess-m $FH/.graphtraj/core/runner/sessions/453-adv
print '{"agent":"c1","name":"n453","parent":"453-adv","executions":[{"id":"e1","state":"ended","outcome":"completed","notification":"delivered"},{"id":"e2","state":"ended","outcome":"completed","notification":"delivered"}]}' > $A/c1.json
print -l 'session: sess-m' 'task_id: "453"' 'role: opus_coding_team.advisor' > $FH/.graphtraj/core/runner/sessions/453-adv/mapping.yml
print -l '{"input":"{\"source\":\"graphtraj\",\"alias\":\"c1\",\"execution\":\"e1\"}"}' '{"input":"{\"source\":\"graphtraj\",\"alias\":\"c1\",\"execution\":\"e2\"}"}' > $FH/.graphtraj/swarm/sessions/sess-m/session.jsonl
print '{"launch_status":"started","agent":"agent-453-adv-xyz","alias":"453-adv"}' > $W/raw/N.txt
print '[GraphTraj notice from 453-adv · completed · execution ex-9]' > $W/raw/N-main-notice.txt
steps Nr > $F/Nr.out 2>&1; grep -E '^child|CHECK|^member|archive|retire with' $F/Nr.out
check "Nr: two executions PASS" grep -q 'CHECK two executions: PASS' $W/raw/Nr.txt
check "Nr: member record found by alias" grep -q 'member 453-adv: record=.*mapping.yml session=sess-m' $W/raw/Nr.txt
check "Nr: one notice per execution" [ $(grep -c 'CHECK one notice for execution .*: PASS' $W/raw/Nr.txt) -eq 2 ]
check "Nr: retire prompt uses the swarm agent, not the alias" grep -q 'retire with {"agent":"agent-453-adv-xyz"}' $F/Nr.out
check "Nr: Main notice title names the execution" grep -q "CHECK Main's notice title names the execution: PASS" $W/raw/Nr.txt

head1 "M / N print real values"
steps M | grep -c 'claude --continue\|451/452' | sed 's/^/M lines naming --continue or 451\/452: /'
steps N | grep -q '"task_id":"453"' && print "N prompt names task 453"
steps N | grep -q 'configuration opus_coding_team.advisor' && print "N prompt requires the preset role"
rm -f $F/ps.txt
print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED)"
exit $FAILED
