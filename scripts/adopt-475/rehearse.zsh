#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-464/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv). Test directories are under the fake Harness ($FH/tmp/475).
#   zsh scripts/adopt-475/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt475-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/475
OB=$F/home/graphtraj-adoption-464
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
OLD=44729d5b9ed59a2a8f3bedc3fdcb54eca3b31d9a   # production now: 464's wheels
NEW=4ca57419137a7593f9275da210cd4c9ed54a8b99
export ADOPT475_H=$FH ADOPT475_BASE=$FB ADOPT475_RT=$FRT ADOPT475_PNPM_SHIM=$F/no-shim ADOPT475_STUB=$F/stub ADOPT475_WT=$WT ADOPT475_PROJECTS=$F/projects ADOPT475_WAIT=1 ADOPT475_OLDBASE=$OB
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=475-production-adoption-465-469
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-4ca57419
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "setup: old wheels from $OLD, fake production venv, plugin, configuration"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldwheels $FH $OB/backup
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in --version) print "2.1.323 (stub Claude Code)" ;; plugin) print "✔ Validation passed (stub)" ;; *) print "stub claude: $*" ;; esac
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
# 464's backup (outside the Harness): must be listed and stay unchanged.
print "464 backup" > $OB/backup/COMPLETE; print kept > $OB/backup/venv.manifest
( cd $F && find home/graphtraj-adoption-464 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256

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
check "timer: no changed module was old in memory" grep -q "OLD in memory before the install: none" $F/timer.out
check "timer: 469's changed runner_control uses the new single-Task loader" grep -q '469 runner_control from new file (uses _load_task_state): True' $F/timer.out
check "timer: _load_task_state works after the install" grep -q '469 _load_task_state after the install: OK UnknownTask' $F/timer.out

head1 "markers on git-archive trees: present in $NEW, absent in $OLD"
check "markers present in $NEW (15/15)" sh -c "$CONDA -I $SD/markers.py $F/timer/new/src present | tail -1 | grep -q 'PASS (15/15)'"
check "markers absent in $OLD (15/15)" sh -c "$CONDA -I $SD/markers.py $F/timer/old/src absent | tail -1 | grep -q 'PASS (15/15)'"

head1 "00 (host's parent is 'claude --continue'; Main from the newest transcript; isolated vproject under tmp/475)"
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt
steps 00 > $F/00.out 2>&1
check "00 found Main through claude --continue + newest transcript" grep -q "MAIN=$MAINID" $F/00.out
check "00 classified the timer as NON-BLOCKING" grep -q 'NON-BLOCKING' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
check "00: the 475 markers are absent from the old production" grep -q 'markers expected absent: PASS (15/15)' $F/00.out
check "00 printed claude --version and the binary" grep -q '^claude: .*stub/claude -> .* | version: 2.1.323' $F/00.out
check "00: isolation OK (vproject has its own git and .graphtraj)" grep -q '^isolation: OK' $F/00.out
check "00: Task 475 stopped: false" grep -q '^stopped: false' $F/00.out
check "00 listed 464's backup and its COMPLETE marker" sh -c "grep -q 'graphtraj-adoption-464/backup' $F/00.out && grep -q '464 backup COMPLETE marker: present' $F/00.out"
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
check "V: plugin source diff 44729d5b..4ca57419 empty" grep -q 'source diff: empty' $F/V.out
check "V: markers present in the candidate, absent in production (15/15)" sh -c "grep -q 'markers expected present: PASS (15/15)' $F/V.out && grep -q 'markers expected absent: PASS (15/15)' $F/V.out"
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
check "S: Worktree src/tests/pyproject equal the target" grep -q 'equal 4ca57419' $F/S.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "S's _Srun summary on a synthetic shards result (no suite run): NEW lines and the count line"
mkdir -p $RW/S-shards
print -l 'FAILED tests/test_a.py::test_one - AssertionError' 'ERROR tests/test_b.py::test_two - boom' > $RW/S-shards/failures.txt
zsh -c "source <(sed -n '/^ATTRIBUTED=(/,/^}/p' $SD/steps.zsh); ids=(tests/test_a.py::test_one tests/test_b.py::test_two); attributed=0; for id in \$ids; do label=\$(label_of \$id); [[ \$label == ATTRIBUTED* ]] && (( attributed++ )); print \"NEW \$id [\$label]\"; done; print \"== new failures: \${#ids} (of which ATTRIBUTED: \$attributed)\"" > $F/Slabel.out 2>&1
cat $F/Slabel.out
check "S labels: NEW <id> [unattributed] and '== new failures: 2 (of which ATTRIBUTED: 0)'" sh -c "grep -q '^NEW tests/test_a.py::test_one \[unattributed\]' $F/Slabel.out && grep -q '== new failures: 2 (of which ATTRIBUTED: 0)' $F/Slabel.out"
rm -rf $RW/S-shards

head1 "S2 counts leftovers of a finished suite (synthetic suite output; ps -E stub), never signals"
print 3 > $W/S-basetemp-before-4ca57419
PR=$(env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=${TMPDIR:-/tmp} $CONDA -I -c 'import tempfile; print(tempfile.gettempdir())')/pytest-of-${USER:-luoxiao}
print -l "test run id: abcdef0123456789 (shard n carries PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-<n>)" "== DONE 12:00:00" > $RW/S-suite.txt
print -l -- $HOSTLINE $TIMERLINE "8181 1 1:00 /usr/bin/python3 -m graphtraj.execution.budget_idle_timer x PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-2 HOME=/h" \
  "8282 1 1:00 $FB/svenv-4ca57419/bin/python fake_runtime.py" "8383 1 1:00 sleep 99 PWD=$PR/pytest-1/old" > $F/ps.txt
steps S2 > $F/S2.out 2>&1; check "S2 exit 0" [ $? -eq 0 ]; grep -E '^(run id|leftover|  [0-9])' $F/S2.out
check "S2 counted 2 (run marker, suite venv under tmp/475; not an older basetemp)" grep -q 'leftover processes of the suite (never signalled): 2' $F/S2.out
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
check "I: markers present in the installed site-packages (15/15)" grep -q 'markers expected present: PASS (15/15)' $F/I.out
check "I: the 464 import lines still print from .venv-runtime" sh -c "grep -q '^457 _stop_escaped | 459 SAMPLE_SECONDS 1.0' $F/I.out && grep -q '^460 tool-processes-{0}.yml _reclaim_tool_processes' $F/I.out"
check "I: the 465 import line (no project_history_files; history param)" grep -q '^465 Claude member settings call project_history_files: False | Codex development reads history param: True' $F/I.out
check "I: the 469 import line" grep -q '^469 UnknownTask _load_task_state _RegisteredTaskNames' $F/I.out
check "I: plugin bytes as before (no trust dialog)" grep -q 'plugin bytes as before the install: no trust dialog expected' $F/I.out
check "backup entry copies are all -rw-------" sh -c "[ \$(ls -A $FB/backup/entries | wc -l) -eq 3 ] && ! stat -f '%Sp' $FB/backup/entries/.[!.]* $FB/backup/entries/* 2>/dev/null | grep -qv -- '-rw-------'"
check "backup is under tmp/475 and its tools include nr475.py, markers.py, watch459.py" test -f $FB/backup/tools/nr475.py -a -f $FB/backup/tools/markers.py -a -f $FB/backup/tools/watch459.py
check "I printed claude --continue" grep -q "cd $FH && claude --continue" $F/I.out
check "I printed claude --version" grep -q '^claude: .*version: 2.1.323' $F/I.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version|continue' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
check "after R the 475 markers are absent again" $CONDA -I $SD/markers.py $FRT/lib/python3.13/site-packages absent

head1 "Mps accepts a host whose parent is claude --continue"
print -l -- $HOSTLINE > $F/ps.txt; mkdir -p $FH/.graphtraj/claude-host; print "x outcome=ok" >> $FH/.graphtraj/claude-host/host.log
steps Mps > $F/Mps.out 2>&1; grep -E '^(host uses|parent|claude:)' $F/Mps.out
check "Mps: parent is claude --continue ... yes" grep -q 'parent is claude --continue or --resume .*: yes' $F/Mps.out

head1 "Nw: the read-only watcher copies the descendants record while the child runs, then ends by itself"
A=$FH/.graphtraj/swarm/control/agents; ND=$FH/.graphtraj/swarm/native/c1; mkdir -p $A $ND
SC1=$ND/tool-descendants-n1.json SC2=$ND/tool-descendants-n2.json
TOOLENTRY=$($CONDA -I -c "import sys, json, subprocess; sys.path.insert(0, '$W/src-4ca57419/src'); from graftling.tool_descendants import identity
p = subprocess.Popen(['/bin/sleep', '1']); i = identity(p.pid); p.wait()
print(json.dumps({'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/zsh -c -l source snapshot && eval \"echo n475-tool && sleep 3\"'}))")
print -r -- '{"version":1,"runtime_pid":1,"entries":['$TOOLENTRY']}' > $SC1
print -r -- '{"agent":"c1","name":"n475","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"running","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json
rm -f $RW/Nw.txt
steps Nw > $F/Nw.out 2>&1; check "Nw exit 0 and started in the background" grep -q 'started at' $F/Nw.out
sleep 1
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1; print -r -- '{"version":1,"runtime_pid":2,"entries":[]}' > $SC2
print -r -- '{"agent":"c1","name":"n475","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"ended","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
for i in {1..50}; do grep -q '== END' $RW/Nw.txt 2>/dev/null && break; sleep 0.2; done
cat $RW/Nw.txt
check "Nw ended by itself when both executions ended (no background process left)" grep -q '== END (both executions ended)' $RW/Nw.txt
check "Nw snapshot kept the Bash tool command" grep -q 'n475-tool' $RW/Nw-snapshots.jsonl
check "Nw never copied the marker value" sh -c "! grep -q 'm-secret-marker' $RW/Nw-snapshots.jsonl $RW/Nw.txt"
print -l 'session_id: x' 'execution_id: n1' 'escaped_processes:' '  found: []' '  stopped: []' '  remaining: []' > $ND/claude-termination-n1.yml
print -l 'session_id: x' 'execution_id: n2' 'escaped_processes: null' > $ND/claude-termination-n2.yml

head1 "Nr positive: Bash started (child and member), 465 settings and session_read, 455, 452, 449/451"
AL=475-production_adoption_465_469-handover0-advisor@advisor
MS=$FH/.graphtraj/core/runner/sessions/$AL; SS=$FH/.graphtraj/swarm/sessions; mkdir -p $SS/sess-m $SS/sess-c $MS
print '{"agent":"c1","name":"n475","session":"sess-c","parent":"'$AL'","selection":{"preset":null,"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","reasoning_effort":null},"retired_at":"x","executions":[{"id":"e1","session":"sess-c","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","session":"sess-c","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
print -l 'session: sess-m' 'task_id: "475"' 'role: advisor' 'execution_id: m1' > $MS/mapping.yml
print -l 'execution_id: m1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
# 465: the member's settings name only directories, never a history file.
print -l 'settings:' '  permissions:' '    allow: [Read]' '    deny: []' '    additionalDirectories: [/x/state]' '  sandbox:' '    filesystem:' '      allowRead: [/x/state, /x/docs]' '      denyRead: ['$HOME'/.claude]' '      allowWrite: []' '      denyWrite: []' > $MS/claude-settings.yml
{ for e in e1 e2; do
    print -r -- '{"type":"tool/result","data":{"text":"{\"execution\":\"'$e'\",\"source\":\"graphtraj\"}"}}'
    print -r -- '{"type":"user/message","data":{"content":"{\"source\":\"graphtraj\",\"agent\":\"c1\",\"execution\":\"'$e'\",\"outcome\":\"completed\"}"}}'
    print -r -- '{"type":"assistant/message","data":{"content":"received {\"source\":\"graphtraj\",\"execution\":\"'$e'\"}"}}'
  done
  print -r -- '{"type":"tool/call","data":{"name":"Bash","input":{"command":"echo member-bash-ok"}}}'
  print -r -- '{"type":"tool/result","data":{"text":"member-bash-ok\n"}}'
} > $SS/sess-m/session.jsonl
print -l '{"type":"tool/call","data":{"name":"Bash","input":{"command":"echo n475-tool && sleep 3"}}}' '{"type":"tool/result","data":{"text":"n475-tool\n"}}' > $SS/sess-c/session.jsonl
print "{\"launch_status\":\"launched\",\"agent\":\"agent-475-adv-xyz\",\"alias\":\"$AL\"}" > $RW/N.txt
print "[Graftling notice from $AL · completed · execution m1]" > $RW/N-main-notice.txt
print -l '{"agent":"c1","name":"n475","configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'SESSION-READ-475 session=sess-c events=2' 'member-bash-ok' > $RW/N-reply.txt
print -l -- $HOSTLINE > $F/ps.txt
steps Nr > $F/Nr.out 2>&1; NRC=$?; grep -E '^claude:|^child|CHECK|BLOCKED|^member|member settings|member quoted|archive|stored selection|retire with' $F/Nr.out
check "Nr exit 0 and no CHECK line is FAIL, BY HAND, PENDING or NOT OBSERVED; no BLOCKED line" sh -c "[ $NRC -eq 0 ] && ! grep '^CHECK' $RW/Nr.txt | grep -qE 'FAIL|BY HAND|PENDING|NOT OBSERVED' && ! grep -q '^BLOCKED' $RW/Nr.txt"
check "Nr: 459 child Bash started PASS" grep -q 'CHECK 459 child Bash started (record lists the command): PASS' $RW/Nr.txt
check "Nr: 465 member settings PASS (counts only)" sh -c "grep -q 'CHECK 465 member claude-settings has no per-session-file grants: PASS (0 such entries; values not printed)' $RW/Nr.txt && grep -q '\"allowRead\": 2' $RW/Nr.txt && ! grep -q '/x/state' $RW/Nr.txt"
check "Nr: 465 session_read id match PASS" grep -q "CHECK 465 member session_read returned the child's Session (id match): PASS (events=2)" $RW/Nr.txt
check "Nr: member Bash started PASS (from the member archive)" grep -q 'CHECK member Bash started: PASS' $RW/Nr.txt
check "Nr: 455 stored record PASS" grep -q 'CHECK 455 stored record: configuration and model not null: PASS' $RW/Nr.txt
check "Nr: one parent input per execution counted by event type" [ $(grep -c 'CHECK 449/451 one parent input for execution .*: PASS' $RW/Nr.txt) -eq 2 ]
check "Nr: 459 record lists the Bash tool command and nothing recorded is alive" sh -c "grep -q 'CHECK 459 descendants record lists the Bash tool command: PASS' $RW/Nr.txt && grep -q 'CHECK 459 no recorded tool process alive after the end: PASS' $RW/Nr.txt"
check "Nr: retire prompt uses the swarm agent, not the alias" grep -q 'retire with {"agent":"agent-475-adv-xyz"}' $F/Nr.out
check "Nr: the marker value is never printed" sh -c "! grep -q 'm-secret-marker' $RW/Nr.txt $F/Nr.out"
check "Nr printed claude --version" grep -q '^claude: .*version: 2.1.323' $RW/Nr.txt

head1 "Nr negative A: the command was recorded, but a recorded entry is alive, 455 null, owner-exited end, live Worker"
print '{"agent":"c1","name":"n475","session":"sess-c","parent":"'$AL'","selection":{"configuration":null,"model":null},"retired_at":null,"executions":[{"id":"e1","state":"ended","outcome":"failed","error":{"code":"owner-exited"},"notification":"delivered","process":{"tool_descendants":"'$SC1'"},"escaped_processes":{"found":[],"stopped":[],"remaining":[]}},{"id":"e2","state":"ended","outcome":"completed","notification":"delivered"}]}' > $A/c1.json
print -l '{"configuration": null, "model": null}' 'SESSION-READ-475 session=sess-c events=2' 'member-bash-ok' > $RW/N-reply.txt
print -l -- $HOSTLINE "9191 1 1:00 $FRT/bin/python -I -m graphtraj.execution.runner_worker $MS/resume.yml" "7777 /bin/zsh -c echo n475-tool && sleep 3" > $F/ps.txt
/bin/sleep 120 & LIVE=$!
$CONDA -I -c "import sys, json; sys.path.insert(0, '$W/src-4ca57419/src'); from graftling.tool_descendants import identity; i = identity($LIVE); print(json.dumps({'version': 1, 'runtime_pid': 1, 'entries': [{'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/sleep 120'}]}))" > $SC1
steps Nr > $F/NrA.out 2>&1; NRC=$?; grep -E '^CHECK' $RW/Nr.txt | grep -E 'FAIL'
check "Nr negative A exits non-zero" [ $NRC -ne 0 ]
check "Nr negative A: 455 FAIL, 452 owner-exited FAIL, live Worker FAIL" sh -c "grep -q 'CHECK 455 stored record.*: FAIL' $RW/Nr.txt && grep -q 'CHECK 452 child execution e1 .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 452 no runner_worker .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 455 create/status .*: FAIL' $RW/Nr.txt"
check "Nr negative A: no tool_marker recorded gives FAIL" grep -q 'CHECK 459 create execution recorded tool_marker and tool_descendants: FAIL' $RW/Nr.txt
check "Nr negative A: a recorded entry alive with its start time (and a process naming n475-tool) gives FAIL" sh -c "grep -q 'CHECK 459 no recorded tool process alive after the end: FAIL (1 alive, 1 named' $RW/Nr.txt && grep -q \"ALIVE pid $LIVE \" $RW/Nr.txt"
check "Nr negative A: the record's escaped_processes (owner-exited reconcile) printed" grep -q 'execution e1: record escaped_processes = {"found": \[\]' $RW/Nr.txt
check "Nr never signalled the live recorded process" kill -0 $LIVE
kill $LIVE; wait $LIVE 2>/dev/null

head1 "Nr negative B (464's production case): no Bash started (E2BIG), settings grant a history file, no session_read line"
print '{"agent":"c1","name":"n475","session":"sess-c","parent":"'$AL'","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"},"retired_at":"x","executions":[{"id":"e1","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1
print -r -- '{"at":1,"agent":"c1","execution":"e1","sidecar":"'$SC1'","record":{"version":1,"runtime_pid":1,"entries":[]}}' > $RW/Nw-snapshots.jsonl
print -l '{"type":"tool/call","data":{"name":"Bash","input":{"command":"echo n475-tool && sleep 3"}}}' '{"type":"tool/result","data":{"error":"spawn /bin/zsh E2BIG","is_error":true}}' > $SS/sess-c/session.jsonl
print -l '{"type":"tool/call","data":{"name":"Bash","input":{"command":"echo member-bash-ok"}}}' '{"type":"tool/result","data":{"error":"spawn /bin/zsh E2BIG","is_error":true}}' > $SS/sess-m/session.jsonl
print -l 'settings:' '  sandbox:' '    filesystem:' '      allowRead: ['$HOME'/.claude/projects/-x/abcd.jsonl, '$HOME'/.codex/sessions/2026/11/rollout-x.jsonl]' > $MS/claude-settings.yml
print -l '{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'The child Bash failed: Error: spawn /bin/zsh E2BIG' > $RW/N-reply.txt
print -l -- $HOSTLINE > $F/ps.txt
steps Nr > $F/NrB.out 2>&1; NRC=$?; grep -E '^CHECK.*FAIL|^BLOCKED' $RW/Nr.txt
check "Nr negative B exits non-zero" [ $NRC -ne 0 ]
check "Nr negative B: child Bash BLOCKED with the E2BIG text and the child archive file, and FAIL" sh -c "grep -q \"^BLOCKED: 459 child Bash started not observed - .*E2BIG.*(emitted in $SS/sess-c/session.jsonl)\" $RW/Nr.txt && grep -q 'CHECK 459 child Bash started (record lists the command): FAIL' $RW/Nr.txt"
check "Nr negative B: 459 'no recorded tool process alive' is BLOCKED and FAIL, never PASS" sh -c "grep -q '^BLOCKED: 459 no recorded tool process alive after the end not observed' $RW/Nr.txt && grep -q 'CHECK 459 no recorded tool process alive after the end: FAIL (NOT OBSERVED' $RW/Nr.txt"
check "Nr negative B: Nw ran but no record named the command gives FAIL" grep -q 'CHECK 459 descendants record lists the Bash tool command: FAIL' $RW/Nr.txt
check "Nr negative B: member Bash BLOCKED with the error and where, and FAIL" sh -c "grep -q \"^BLOCKED: member Bash started not observed - .*E2BIG.*(emitted in $SS/sess-m/session.jsonl)\" $RW/Nr.txt && grep -q 'CHECK member Bash started: FAIL' $RW/Nr.txt"
check "Nr negative B: settings with history files FAIL, values never printed" sh -c "grep -q 'CHECK 465 member claude-settings has no per-session-file grants: FAIL (2 such entries' $RW/Nr.txt && ! grep -q 'abcd.jsonl\|rollout-x' $RW/Nr.txt"
check "Nr negative B: session_read BLOCKED and FAIL" sh -c "grep -q '^BLOCKED: 465 member session_read not observed' $RW/Nr.txt && grep -q \"CHECK 465 member session_read returned the child's Session (id match): FAIL\" $RW/Nr.txt"
check "Nr negative B: no CHECK line says NOT OBSERVED as a verdict (every unobserved one is FAIL)" sh -c "! grep -E '^CHECK [^:]*(: [^:]*)?: NOT OBSERVED' $RW/Nr.txt | grep -q ."

head1 "M / N print real values"
steps M > $F/M.out; check "M names the active Tasks and says other Tasks' ends may arrive once and must not repeat" sh -c "grep -q '其它 Task（466, 470）' $F/M.out && grep -q \"Ends of other Tasks' members during the exit may arrive once; they must not repeat.\" $F/M.out"
steps N > $F/N.out
check "N prompt names task 475, the preset role, n475 and the exact Bash command" sh -c "grep -q '\"task_id\":\"475\"' $F/N.out && grep -q 'named n475 with configuration opus_coding_team.advisor' $F/N.out && grep -qF \"Use the Bash tool once to run exactly: echo n475-tool && sleep 3 . Then reply DONE-475.\" $F/N.out"
check "N prompt asks for session_read on the child's Session and the exact SESSION-READ-475 line, no contents" sh -c "grep -q 'call session_read on the child' $F/N.out && grep -q 'SESSION-READ-475 session=<session id> events=<count>' $F/N.out && grep -q 'Do not quote event contents' $F/N.out"
check "N prompt asks for the member's own Bash 'echo member-bash-ok' and error text" sh -c "grep -q 'run exactly: echo member-bash-ok' $F/N.out && grep -q 'exact error text' $F/N.out"
check "N prompt forbids submit_result and submit_report, retires the child" sh -c "grep -q 'Do NOT call submit_result or submit_report' $F/N.out && grep -q 'retire the child by its agent id' $F/N.out"

head1 "done: no exported key value in raw files"
export ADOPT475_FAKE_TOKEN=rehearsal-secret-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0" grep -q 'raw files containing an exported key value: 0' $F/done.out
print -r -- "rehearsal-secret-value-123456" > $RW/leak.txt
steps done > $F/done2.out 2>&1
check "done: a raw file with an exported key value is counted (1)" grep -q 'raw files containing an exported key value: 1' $F/done2.out
rm -f $RW/leak.txt; unset ADOPT475_FAKE_TOKEN

head1 "464's backup (outside the Harness) is unchanged; nothing was written to ~/graphtraj-adoption-*"
check "464 backup unchanged" sh -c "cd $F && shasum -a 256 -c --quiet evidence0.sha256"
check "this run wrote under tmp/475 only (no home base)" sh -c "[ -d $FB/backup ] && [ ! -e $F/home/graphtraj-adoption-475 ]"
ls $W | tr '\n' ' '; print
rm -f $F/ps.txt
print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED) ($COUNT checks)"
exit $FAILED
