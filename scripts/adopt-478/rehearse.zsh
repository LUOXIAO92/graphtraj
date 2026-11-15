#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-464/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv). Test directories are under the fake Harness ($FH/tmp/478).
#   zsh scripts/adopt-478/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt478-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/478
OB=$FH/tmp/475   # 475's backup base (under the Harness): listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
OLD=4ca57419137a7593f9275da210cd4c9ed54a8b99   # production now: 475's wheels
NEW=a3fe1b92251d0510b962d8adddb49f690e1d1f07
export ADOPT478_NW468_SECONDS=3 ADOPT478_H=$FH ADOPT478_BASE=$FB ADOPT478_RT=$FRT ADOPT478_PNPM_SHIM=$F/no-shim ADOPT478_STUB=$F/stub ADOPT478_WT=$WT ADOPT478_PROJECTS=$F/projects ADOPT478_WAIT=1 ADOPT478_OLDBASE=$OB
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=478-production-adoption-466-477
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-a3fe1b92
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "setup: old wheels from $OLD, fake production venv, plugin, configuration"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldwheels $FH $OB/backup
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in --version) print "2.1.325 (stub Claude Code)" ;; plugin) print "✔ Validation passed (stub)" ;; *) print "stub claude: $*" ;; esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $OLD | tar -x -C $F/oldsrc
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldsrc/src/graftling
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
mkdir -p $W:h/definitions $W:h/teams/1; cp $WT/.state/task.yml $W:h/; print 'stopped: false' > $W:h/execution-budget.yml
def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
for f in $WT/.state/task.md $WT/.state/$def; do
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $W:h/${f#$WT/.state/}
done
# Other Tasks for the waiting line: 465 integrated (not named), 466 and 470 pending (named).
for t in 465-x:integrated 466-y:pending 470-z:pending; do mkdir -p $ST/${t%%:*}; print "status: ${t#*:}" > $ST/${t%%:*}/task.yml; done
# 475's backup (tmp/475 under the Harness): must be listed and stay unchanged.
print "475 backup" > $OB/backup/COMPLETE; print kept > $OB/backup/venv.manifest
( cd $FH && find tmp/475 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256

MAINID=11111111-2222-3333-4444-555555555555
mkdir -p $F/projects; : > $F/projects/$MAINID.jsonl
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
TIMERLINE="5151 1 $FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $FH/.graphtraj/core/runner/sessions/451-x 0123abcd 777"
WORKERLINE="6161 1 $FRT/bin/python -I -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/466-session_read_in_agents-handover0-engineer@engineer/resume.yml"
cat > $F/stub/ps <<EOF2
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF2
chmod +x $F/stub/ps

head1 "README 3(a): a timer started under $OLD wakes after the $NEW files replace it (sandbox import check)"
mkdir -p $F/timer/old $F/timer/new $F/timer/live
git -C $WT archive $OLD src | tar -x -C $F/timer/old; git -C $WT archive $NEW src | tar -x -C $F/timer/new
cp -R $F/timer/old/src/graphtraj $F/timer/old/src/graftling $F/timer/live/
(cd $F/timer && $CONDA -I $SD/timer_probe.py $F/timer/live $F/timer/new/src) > $F/timer.out 2>&1
cat $F/timer.out
check "timer: the lazy import at the threshold succeeds after the install" grep -q 'lazy import at the threshold: OK' $F/timer.out
check "timer: only execution_budget (467) is old in memory (README 3(a))" grep -q "OLD in memory before the install: \['graphtraj.execution.execution_budget'\]" $F/timer.out
check "timer: 469's changed runner_control uses the new single-Task loader" grep -q '469 runner_control from new file (uses _load_task_state): True' $F/timer.out
check "timer: _load_task_state works after the install" grep -q '469 _load_task_state after the install: OK UnknownTask' $F/timer.out

head1 "markers on git-archive trees: present in $NEW, absent in $OLD"
check "markers present in $NEW (16/16)" sh -c "$CONDA -I $SD/markers.py $F/timer/new/src present | tail -1 | grep -q 'PASS (16/16)'"
check "markers absent in $OLD (16/16)" sh -c "$CONDA -I $SD/markers.py $F/timer/old/src absent | tail -1 | grep -q 'PASS (16/16)'"

head1 "00 (host's parent is 'claude --continue'; Main from the newest transcript; isolated vproject under tmp/478)"
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt
steps 00 > $F/00.out 2>&1
check "00 found Main through claude --continue + newest transcript" grep -q "MAIN=$MAINID" $F/00.out
check "00 classified the timer as NON-BLOCKING" grep -q 'NON-BLOCKING' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
check "00: the 478 markers are absent from the old production" grep -q 'markers expected absent: PASS (16/16)' $F/00.out
check "00 printed claude --version and the binary" grep -q '^claude: .*stub/claude -> .* | version: 2.1.325' $F/00.out
check "00 made the read-only production task graph call for Task 478 (stub tree: not registered, rc printed)" sh -c "grep -q 'task graph rc=' $F/00.out && grep -q 'graph --task-id 478' $F/00.out"
check "00: isolation OK (vproject has its own git and .graphtraj)" grep -q '^isolation: OK' $F/00.out
check "00: Task 478 stopped: false" grep -q '^stopped: false' $F/00.out
check "00 listed 475's backup and its COMPLETE marker" sh -c "grep -q 'tmp/475/backup' $F/00.out && grep -q '475 backup COMPLETE marker: present' $F/00.out"
check "00 named the Tasks that may run now (466, 470; not 465)" sh -c "grep 'may run now' $F/00.out | grep -q '466, 470'"
grep -E '^claude:|inherited|MAIN=|isolat|may run now|^stopped|464 backup|markers|\[' $F/00.out | grep -v '^\[00\]'

head1 "B"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked' $F/B.out

head1 "V (stub plugin validate)"
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
# The fake 465/466/470 dirs hold only a status line (for the waiting line); V's full Task-graph read would refuse
# them, so they stand aside during V (production's Tasks are complete).
mkdir -p $F/aside; mv $ST/465-x $ST/466-y $ST/470-z $F/aside/
steps V > $F/V.out 2>&1; check "V exit 0" [ $? -eq 0 ]
mv $F/aside/* $ST/
grep -E '^(SAME|CHANGED)|source diff|plugin unchanged|markers expected|STOP|✘|^next|下一步' $F/V.out
check "V: plugin files SAME x3, no trust dialog predicted" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)\$' $F/V.out) -ge 3 ] && ! grep -q '^CHANGED' $F/V.out && grep -q 'plugin unchanged: no plugin/hooks trust dialog' $F/V.out"
check "V: plugin source diff 4ca57419..a3fe1b92 empty (Pi extension.mjs listed apart)" sh -c "grep -q 'source diff: empty' $F/V.out && grep -q 'Pi only (not the Claude plugin): .*extension.mjs' $F/V.out"
check "V: markers present in the candidate, absent in production (16/16)" sh -c "grep -q 'markers expected present: PASS (16/16)' $F/V.out && grep -q 'markers expected absent: PASS (16/16)' $F/V.out"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
check "V's next names S and then USER's Vu before Vc" grep -q "zsh $SD/steps.zsh S    （然后 USER: zsh $SD/steps.zsh Vu" $F/V.out

head1 "Vu prints the one dialog and /exit; Vc's isolation part (vc_setup) with the candidate venv"
steps Vu > $F/Vu.out 2>&1
check "Vu names the new path, 'Yes, proceed' and /exit" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out && grep -q '/exit' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc: isolation OK with the candidate code before claude -p" grep -q '^isolation: OK' $RW/Vc.txt
check "Vc with the stub claude does not pass (no real plugin load) and asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok; print "NOT REHEARSED: Vc's real claude -p (real Claude Code); marker made by hand."

head1 "S refuses while another run_test_shards runs (quiet-host check only; the suite itself is not run here)"
print -l -- "7171 1 python scripts/run_test_shards.py --shards 6" >> $F/ps.txt
steps S > $F/S.out 2>&1; check "S refused" [ $? -ne 0 ]; grep -E 'Worktree HEAD|loadavg|other pytest|STOP' $F/S.out
check "S: Worktree src/tests/pyproject equal the target" grep -q 'equal a3fe1b92' $F/S.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "S's labels on synthetic failures: one ATTRIBUTED (477/482 record), one NEW; '== new failures: 1'"
zsh -c "source <(sed -n '/^ATTRIBUTED=(/,/^}/p' $SD/steps.zsh); ids=(tests/test_a.py::test_one tests/test_interrupted_resolver_recovery.py::test_resume_with_restore_active_continues_the_same_session_to_integrated); attributed=0; for id in \$ids; do label=\$(label_of \$id); if [[ \$label == ATTRIBUTED* ]]; then (( attributed++ )); print \"ATTRIBUTED \$id [\$label]\"; else print \"NEW \$id [\$label]\"; fi; done; print \"== new failures: \$(( \${#ids} - attributed ))\"" > $F/Slabel.out 2>&1
cat $F/Slabel.out
check "S labels: NEW test_one [unattributed], ATTRIBUTED resolver test [476, 477, 482], '== new failures: 1'" sh -c "grep -q '^NEW tests/test_a.py::test_one \[unattributed\]' $F/Slabel.out && grep -q '^ATTRIBUTED .*476, 477, 482' $F/Slabel.out && grep -q '== new failures: 1' $F/Slabel.out"
check "S: pytest temp is outside the fake Harness" sh -c "grep -q 'pytest temporary root: .*(outside the Harness' $F/S.out || grep -q 'STOP: another run_test_shards' $F/S.out"
rm -rf $RW/S-shards

head1 "S2 counts leftovers of a finished suite (synthetic suite output; ps -E stub), never signals"
print 3 > $W/S-basetemp-before-a3fe1b92
PR=$(env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=${TMPDIR:-/private/tmp} $CONDA -I -c 'import tempfile; print(tempfile.gettempdir())')/pytest-of-${USER:-luoxiao}
print -l "test run id: abcdef0123456789 (shard n carries PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-<n>)" "== DONE 12:00:00" > $RW/S-suite.txt
print -l -- $HOSTLINE $TIMERLINE "8181 1 1:00 /usr/bin/python3 -m graphtraj.execution.budget_idle_timer x PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-2 HOME=/h" \
  "8282 1 1:00 $FB/svenv-a3fe1b92/bin/python fake_runtime.py" "8383 1 1:00 sleep 99 PWD=$PR/pytest-1/old" > $F/ps.txt
steps S2 > $F/S2.out 2>&1; check "S2 exit 0" [ $? -eq 0 ]; grep -E '^(run id|leftover|  [0-9])' $F/S2.out
check "S2 counted 2 (run marker, suite venv under tmp/478; not an older basetemp)" grep -q 'leftover processes of the suite (never signalled): 2' $F/S2.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "I waits while a Task 466 member Worker and Main's host run, then passes with only the idle timer left"
print -l -- $HOSTLINE $TIMERLINE $WORKERLINE > $F/ps.txt
( sleep 3; print -l -- $TIMERLINE > $F/ps.txt.new; mv $F/ps.txt.new $F/ps.txt ) &
REMOVER=$!
print | steps I > $F/I.out 2>&1; IRC=$?
wait $REMOVER
check "I exit 0" [ $IRC -eq 0 ]
check "I waited and named the active Tasks (466、470 / 466, 470), no kill, Ctrl-C safe, Chinese and English" sh -c "grep -q '正在等待：可能有成员在运行的 Task（466、470）' $F/I.out && grep -q 'Waiting for members of Tasks that may run now (466, 470)' $F/I.out && grep -q 'Do not kill them' $F/I.out && grep -q 'Ctrl-C 可以安全放弃' $F/I.out"
check "I listed the Worker as BLOCKING with its Task" grep -q '\[member Worker of Task 466 ' $F/I.out
check "I never listed the timer as BLOCKING" sh -c "! grep -q 'BLOCKING.*budget_idle_timer\|\] .*budget_idle_timer' $F/I.out"
grep -E '正在等待|Waiting for|BLOCKING|^-rw|^PASS|^FAIL|Successfully|SAME-AS|markers expected|plugin bytes|^457 _stop|^460 tool|^465 |^469 |bytes unchanged|^changed|claude --continue' $F/I.out | uniq
check "proddiff PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $RW/I-verify.txt
check "I: markers present in the installed site-packages (16/16)" grep -q 'markers expected present: PASS (16/16)' $F/I.out
check "I: the 464 import lines still print from .venv-runtime" sh -c "grep -q '^457 _stop_escaped | 459 SAMPLE_SECONDS 1.0' $F/I.out && grep -q '^460 tool-processes-{0}.yml _reclaim_tool_processes' $F/I.out"
check "I: the 465 import line (no project_history_files; history param)" grep -q '^465 Claude member settings call project_history_files: False | Codex development reads history param: True' $F/I.out
check "I: the 469 import line" grep -q '^469 UnknownTask _load_task_state _RegisteredTaskNames' $F/I.out
check "I: the 478 import lines (466, 468, 477)" sh -c "grep -q '^466 session_read DEFAULT_COUNT 5 | agents _member_session: _member_session' $F/I.out && grep -q '^468 archive _identity _identity | BUDGET_SAMPLE_SECONDS 1.0' $F/I.out && grep -q '^477 take_push take_push | _waited _waited' $F/I.out"
check "I: plugin bytes as before (no trust dialog)" grep -q 'plugin bytes as before the install: no trust dialog expected' $F/I.out
check "backup entry copies are all -rw-------" sh -c "[ \$(ls -A $FB/backup/entries | wc -l) -eq 3 ] && ! stat -f '%Sp' $FB/backup/entries/.[!.]* $FB/backup/entries/* 2>/dev/null | grep -qv -- '-rw-------'"
check "backup is under tmp/478 and its tools include nr478.py, markers.py, watch459.py" test -f $FB/backup/tools/nr478.py -a -f $FB/backup/tools/markers.py -a -f $FB/backup/tools/watch459.py
check "I printed claude --continue" grep -q "cd $FH && claude --continue" $F/I.out
check "I printed claude --version" grep -q '^claude: .*version: 2.1.325' $F/I.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version|continue' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
check "after R the 478 markers are absent again" $CONDA -I $SD/markers.py $FRT/lib/python3.13/site-packages absent

head1 "Mps accepts a host whose parent is claude --continue"
print -l -- $HOSTLINE > $F/ps.txt; mkdir -p $FH/.graphtraj/claude-host; print "x outcome=ok" >> $FH/.graphtraj/claude-host/host.log
steps Mps > $F/Mps.out 2>&1; grep -E '^(host uses|parent|claude:)' $F/Mps.out
check "Mps: parent is claude --continue ... yes" grep -q 'parent is claude --continue or --resume .*: yes' $F/Mps.out

head1 "Nw: the read-only watcher copies the descendants record while the child runs, then ends by itself"
A=$FH/.graphtraj/swarm/control/agents; ND=$FH/.graphtraj/swarm/native/c1; mkdir -p $A $ND
SC1=$ND/tool-descendants-n1.json SC2=$ND/tool-descendants-n2.json
TOOLENTRY=$($CONDA -I -c "import sys, json, subprocess; sys.path.insert(0, '$W/src-a3fe1b92/src'); from graftling.tool_descendants import identity
p = subprocess.Popen(['/bin/sleep', '1']); i = identity(p.pid); p.wait()
print(json.dumps({'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/zsh -c -l source snapshot && eval \"echo n478-tool && sleep 3\"'}))")
print -r -- '{"version":1,"runtime_pid":1,"entries":['$TOOLENTRY']}' > $SC1
print -r -- '{"agent":"c1","name":"n478","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"running","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json
rm -f $RW/Nw.txt
steps Nw > $F/Nw.out 2>&1; check "Nw exit 0 and started in the background" grep -q 'started at' $F/Nw.out
sleep 1
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1; print -r -- '{"version":1,"runtime_pid":2,"entries":[]}' > $SC2
print -r -- '{"agent":"c1","name":"n478","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"ended","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
for i in {1..50}; do grep -q '== END' $RW/Nw.txt 2>/dev/null && break; sleep 0.2; done
cat $RW/Nw.txt
check "Nw ended by itself when every execution ended (no background process left)" grep -q '== END (every execution ended)' $RW/Nw.txt
for i in {1..30}; do grep -q '== END 468' $RW/Nw468.txt 2>/dev/null && break; sleep 0.2; done
check "Nw's 468 sampler started and ended by itself (bounded)" grep -q '== END 468 sampler' $RW/Nw468.txt
check "Nw snapshot kept the Bash tool command" grep -q 'n478-tool' $RW/Nw-snapshots.jsonl
check "Nw never copied the marker value" sh -c "! grep -q 'm-secret-marker' $RW/Nw-snapshots.jsonl $RW/Nw.txt"
print -l 'session_id: x' 'execution_id: n1' 'escaped_processes:' '  found: []' '  stopped: []' '  remaining: []' > $ND/claude-termination-n1.yml
print -l 'session_id: x' 'execution_id: n2' 'escaped_processes: null' > $ND/claude-termination-n2.yml

head1 "Nr positive: 475's checks (459, 465, member Bash, 455, 452) and 478's 466/477/468 on header-format archives"
AL=478-production_adoption_466_477-handover0-advisor@advisor
MS=$FH/.graphtraj/core/runner/sessions/$AL; SS=$FH/.graphtraj/swarm/sessions; mkdir -p $SS $MS
CHILDREC() { print -r -- '{"agent":"c1","name":"n478","session":"'$1'","parent":"'$AL'","selection":{"preset":null,"configuration":'$2',"model":'$3',"reasoning_effort":null},"retired_at":"x","executions":[{"id":"e1","session":"sess-c","state":"ended","outcome":"'$4'",'$5'"notification":"delivered","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json; }
CHILDREC claude:sess-c '"opus_coding_team.advisor"' '"claude-opus-5-5"' completed ''
print -l 'session: claude:sess-m' 'task_id: "478"' 'role: advisor' 'execution_id: m1' > $MS/mapping.yml
print -l 'execution_id: m1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
print -l 'settings:' '  permissions:' '    allow: [Read]' '    deny: []' '    additionalDirectories: [/x/state]' '  sandbox:' '    filesystem:' '      allowRead: [/x/state, /x/docs]' '      denyRead: ['$HOME'/.claude]' '      allowWrite: []' '      denyWrite: []' > $MS/claude-settings.yml
$CONDA -I $SD/rehearse_fixtures.py $SS positive
print "{\"launch_status\":\"launched\",\"agent\":\"agent-478-adv-xyz\",\"alias\":\"$AL\"}" > $RW/N.txt
print "[Graftling notice from $AL · completed · execution m1]" > $RW/N-main-notice.txt
print -l '{"agent":"c1","name":"n478","configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'SESSION-READ-478 session=claude:sess-c events=30' 'member-bash-ok' > $RW/N-reply.txt
# 468 samples: one Worker, 120 s while the child ran, 12 CPU-s (0.1 CPU-s per wall-s)
print -l '{"at": 1000, "child_running": true, "ps": "9191 1 3.0 0:10.00 02:00 python -m graphtraj.execution.runner_worker x"}' \
         '{"at": 1120, "child_running": true, "ps": "9191 1 3.0 0:22.00 04:00 python -m graphtraj.execution.runner_worker x"}' \
         '{"at": 1130, "child_running": false, "ps": "9191 1 9.0 0:40.00 04:10 python -m graphtraj.execution.runner_worker x"}' > $RW/Nw468-ps.txt
print -l -- $HOSTLINE > $F/ps.txt
steps Nr > $F/Nr.out 2>&1; NRC=$?; grep -E '^claude:|^child|CHECK|BLOCKED|^member|archive|^466|^468|^478' $F/Nr.out
check "Nr exit 0 and no CHECK line is FAIL, BY HAND, PENDING, BLOCKED or NOT OBSERVED; no BLOCKED line" sh -c "[ $NRC -eq 0 ] && ! grep '^CHECK' $RW/Nr.txt | grep -qE 'FAIL|BY HAND|PENDING|NOT OBSERVED|BLOCKED' && ! grep -q '^BLOCKED' $RW/Nr.txt"
check "Nr: 459 child Bash started PASS (tool_result answering the Bash call)" grep -q 'CHECK 459 child Bash started (record lists the command): PASS' $RW/Nr.txt
check "Nr: 465 settings PASS, counts only" sh -c "grep -q 'CHECK 465 member claude-settings has no per-session-file grants: PASS' $RW/Nr.txt && ! grep -q '/x/state' $RW/Nr.txt"
check "Nr (fixed 475 defect 1): 'claude:'-prefixed session id accepted" grep -q "CHECK 465 member session_read returned the child's Session (id match): PASS (events=30)" $RW/Nr.txt
check "Nr (fixed 475 defect 2): member archive found by its header; member Bash PASS" sh -c "grep -q 'CHECK member Bash started: PASS' $RW/Nr.txt && grep -q 'archive mdir: execution e1' $RW/Nr.txt"
check "Nr: 455 and 452 child PASS" sh -c "grep -q 'CHECK 455 stored record: configuration and model not null: PASS' $RW/Nr.txt && grep -q 'CHECK 452 child execution e1 ended completed, not owner-exited: PASS' $RW/Nr.txt"
check "Nr: 466 default = last 5, page back [-10:-5], keyword hit PASS" sh -c "grep -q 'CHECK 466 default read = last 5: PASS' $RW/Nr.txt && grep -q 'CHECK 466 page back \[-10:-5\]: PASS' $RW/Nr.txt && grep -q 'CHECK 466 keyword search hits .*: PASS' $RW/Nr.txt"
check "Nr: 466 fake key redacted and absent from the member transcript, value never printed" sh -c "grep -q 'CHECK 466 fake key redacted .*: PASS' $RW/Nr.txt && ! grep -q 'probe478fakevalue' $RW/Nr.txt $F/Nr.out"
check "Nr: 477 wait and status last_message PASS; no push (0) PASS twice" sh -c "grep -q 'CHECK 477 wait last_message == the child reply DONE-478: PASS' $RW/Nr.txt && grep -q 'CHECK 477 status last_message == DONE-478: PASS' $RW/Nr.txt && grep -q 'CHECK 477 child end not pushed .*: PASS' $RW/Nr.txt && grep -q 'CHECK 477 no parent input pushed for waited execution e1: PASS' $RW/Nr.txt"
check "Nr: 468 0.100 CPU-s per wall-s PASS against 0.84-0.97" grep -q "CHECK 468 Worker CPU below 475's 0.84-0.97 and < 0.25: PASS (0.100)" $RW/Nr.txt
check "Nr: retire prompt uses the swarm agent" grep -q 'retire with {"agent":"agent-478-adv-xyz"}' $F/Nr.out
check "Nr: marker value never printed" sh -c "! grep -q 'm-secret-marker' $RW/Nr.txt $F/Nr.out"

head1 "Nr negative 466: default last 4, no page back, keyword hit at the end, the fake key unredacted in results"
$CONDA -I $SD/rehearse_fixtures.py $SS bad466
steps Nr > $F/Nr466.out 2>&1; NRC=$?; grep -E '^CHECK 466' $RW/Nr.txt
check "Nr negative 466 exits non-zero" [ $NRC -ne 0 ]
check "Nr negative 466: default FAIL, page back BLOCKED, keyword FAIL, redaction FAIL; value never printed" sh -c "grep -q 'CHECK 466 default read = last 5: FAIL' $RW/Nr.txt && grep -q 'CHECK 466 page back \[-10:-5\]: BLOCKED' $RW/Nr.txt && grep -q 'CHECK 466 keyword search hits .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 466 fake key redacted .*: FAIL' $RW/Nr.txt && ! grep -q 'probe478fakevalue' $RW/Nr.txt"

head1 "Nr negative 477: wait/status last_message null and the child's end pushed to the member after wait"
$CONDA -I $SD/rehearse_fixtures.py $SS bad477
steps Nr > $F/Nr477.out 2>&1; NRC=$?; grep -E '^CHECK 477' $RW/Nr.txt
check "Nr negative 477 exits non-zero" [ $NRC -ne 0 ]
check "Nr negative 477: wait FAIL, status FAIL, pushed input FAIL" sh -c "grep -q 'CHECK 477 wait last_message .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 477 status last_message .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 477 child end not pushed .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 477 no parent input pushed for waited execution e1: CHECK BY HAND (count 1' $RW/Nr.txt"

head1 "Nr negative 468: Worker at 0.9 CPU-s per wall-s (475's level), then too few samples"
print -l '{"at": 1000, "child_running": true, "ps": "9191 1 90.0 0:10.00 02:00 w"}' '{"at": 1120, "child_running": true, "ps": "9191 1 90.0 2:00.00 04:00 w"}' > $RW/Nw468-ps.txt
$CONDA -I $SD/cpu468.py report $RW > $F/cpu1.out 2>&1; C1=$?
print -l '{"at": 1000, "child_running": true, "ps": "9191 1 1.0 0:10.00 02:00 w"}' > $RW/Nw468-ps.txt
$CONDA -I $SD/cpu468.py report $RW > $F/cpu2.out 2>&1; C2=$?
cat $F/cpu1.out $F/cpu2.out
check "468 at 0.917 FAIL; one sample BLOCKED" sh -c "[ $C1 -ne 0 ] && grep -q 'PASS\|FAIL (0.917)' $F/cpu1.out && grep -q ': FAIL (0.917)' $F/cpu1.out && [ $C2 -ne 0 ] && grep -q 'CHECK 468 .*: BLOCKED' $F/cpu2.out"

head1 "Nr negative B (464's production case, header-format): no Bash started (E2BIG), settings grant a history file, no SESSION-READ line"
$CONDA -I $SD/rehearse_fixtures.py $SS e2big
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1
print -r -- '{"at":1,"agent":"c1","execution":"e1","sidecar":"'$SC1'","record":{"version":1,"runtime_pid":1,"entries":[]}}' > $RW/Nw-snapshots.jsonl
print -l 'settings:' '  sandbox:' '    filesystem:' '      allowRead: ['$HOME'/.claude/projects/-x/abcd.jsonl, '$HOME'/.codex/sessions/2026/11/rollout-x.jsonl]' > $MS/claude-settings.yml
print -l '{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'The child Bash failed: Error: spawn /bin/zsh E2BIG' > $RW/N-reply.txt
steps Nr > $F/NrB.out 2>&1; NRC=$?; grep -E '^CHECK.*FAIL|^BLOCKED' $RW/Nr.txt
check "Nr negative B exits non-zero" [ $NRC -ne 0 ]
check "Nr negative B: child Bash BLOCKED with E2BIG and its archive file, FAIL" sh -c "grep -q \"^BLOCKED: 459 child Bash started not observed - .*E2BIG.*(emitted in $SS/cdir/session.jsonl)\" $RW/Nr.txt && grep -q 'CHECK 459 child Bash started (record lists the command): FAIL' $RW/Nr.txt"
check "Nr negative B: member Bash BLOCKED with the error and where, FAIL" sh -c "grep -q \"^BLOCKED: member Bash started not observed - .*E2BIG.*(emitted in $SS/mdir/session.jsonl)\" $RW/Nr.txt && grep -q 'CHECK member Bash started: FAIL' $RW/Nr.txt"
check "Nr negative B: settings with history files FAIL, values never printed" sh -c "grep -q 'CHECK 465 member claude-settings has no per-session-file grants: FAIL (2 such entries' $RW/Nr.txt && ! grep -q 'abcd.jsonl\|rollout-x' $RW/Nr.txt"
check "Nr negative B: SESSION-READ line missing gives BLOCKED and FAIL" sh -c "grep -q '^BLOCKED: 465 member session_read not observed' $RW/Nr.txt && grep -q \"CHECK 465 member session_read returned the child's Session (id match): FAIL\" $RW/Nr.txt"

head1 "M / N print real values"
steps M > $F/M.out; check "M names the active Tasks and says other Tasks' ends may arrive once and must not repeat" sh -c "grep -q '其它 Task（466, 470）' $F/M.out && grep -q \"Ends of other Tasks' members during the exit may arrive once; they must not repeat.\" $F/M.out"
steps N > $F/N.out
check "N prompt: Task 478, preset role, n478, KW478-ORCHID early, split fake key, DONE-478" sh -c "grep -q '\"task_id\":\"478\"' $F/N.out && grep -q 'named n478 with configuration opus_coding_team.advisor' $F/N.out && grep -q \"Step 02: write the sentence 'Now step 02, marker KW478-ORCHID.'\" $F/N.out && grep -qF \"echo api_key=sk-probe478fake''value0000\" $F/N.out && ! grep -q 'probe478fakevalue' $F/N.out && grep -q 'reply with exactly: DONE-478' $F/N.out"
check "N prompt: 43 steps, one seq per step" [ $(grep -o "seq -f '478-[0-9][0-9]-%g' 1 400" $F/N.out | wc -l) -eq 41 ]
check "N prompt: wait (finite, repeat), status last_message, three session_read calls, SESSION-READ-478, member Bash, no submit, retire" sh -c "grep -q 'agents wait on that agent id with a finite timeout, repeating' $F/N.out && grep -q 'agents status with arguments {agent: <agent id>} and quote its last_message' $F/N.out && grep -q '{agent: <agent id>, start: -10, stop: -5}' $F/N.out && grep -q '{agent: <agent id>, search: KW478-ORCHID}' $F/N.out && grep -q 'SESSION-READ-478 session=' $F/N.out && grep -q 'echo member-bash-ok' $F/N.out && grep -q 'Do NOT call submit_result or submit_report' $F/N.out && grep -q 'Retire the child by its agent id' $F/N.out"

head1 "done: no exported key value in raw files"
export ADOPT478_FAKE_TOKEN=rehearsal-secret-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out
print -r -- "rehearsal-secret-value-123456" > $RW/leak.txt
steps done > $F/done2.out 2>&1
check "done: a raw file with an exported key value is counted (1)" grep -q 'raw files containing an exported key value: 1' $F/done2.out
rm -f $RW/leak.txt; unset ADOPT478_FAKE_TOKEN

head1 "475's backup (tmp/475) is unchanged"
check "475 backup unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"
check "this run's backup is under tmp/478" test -d $FB/backup
ls $W | tr '\n' ' '; print
rm -f $F/ps.txt
print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED) ($COUNT checks)"
exit $FAILED
