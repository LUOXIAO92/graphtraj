#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-453/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv).
#   zsh scripts/adopt-464/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt464-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$F/home/graphtraj-adoption-464
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
OLD=4e3aafce010c1bc88353d502714cea5bb5c874bd   # production now: 458's wheels
NEW=b3d522ad6f1a90c33dad19f81babc9c1d587d24f
export ADOPT464_H=$FH ADOPT464_BASE=$FB ADOPT464_RT=$FRT ADOPT464_PNPM_SHIM=$F/no-shim ADOPT464_STUB=$F/stub ADOPT464_WT=$WT ADOPT464_PROJECTS=$F/projects ADOPT464_WAIT=1
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=464-production-adoption-457-459
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
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
TIMERLINE="5151 1 $FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $FH/.graphtraj/core/runner/sessions/451-x 0123abcd 777"
WORKERLINE="6161 1 $FRT/bin/python -I -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/460-runner_member_killed_worker_tool_reclaim-handover0-engineer@engineer/resume.yml"
# ps stub: '-p 4241' is the host's parent (claude --continue, no id in argv); otherwise ps.txt.
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
check "timer: graftling.control._stop_escaped's lazy imports (tool_descendants) succeed after the install" grep -q '_stop_escaped lazy imports after the install: OK' $F/timer.out
check "timer: no changed module was old in memory" grep -q "OLD in memory before the install: none" $F/timer.out

head1 "00 (host's parent is 'claude --continue'; Main from the newest transcript)"
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt
steps 00 > $F/00.out 2>&1
check "00 found Main through claude --continue + newest transcript" grep -q "MAIN=$MAINID" $F/00.out
check "00 classified the timer as NON-BLOCKING" grep -q 'NON-BLOCKING' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
check "00: the 464 markers are absent from the old production" grep -q 'markers expected absent: PASS (11/11)' $F/00.out
grep -E 'inherited|MAIN=|claude --continue|running lines|^Version|guard|markers|\[' $F/00.out | grep -v '^\[00\]'

head1 "B"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked' $F/B.out

head1 "V (stub plugin validate)"
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
steps V > $F/V.out 2>&1; check "V exit 0" [ $? -eq 0 ]
grep -E '^(SAME|CHANGED)|source diff|plugin unchanged|markers expected|STOP|✘|^(ok|BAD) ' $F/V.out
check "V: plugin files SAME x3, no trust dialog predicted" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)\$' $F/V.out) -ge 3 ] && ! grep -q '^CHANGED' $F/V.out && grep -q 'plugin unchanged: no plugin/hooks trust dialog' $F/V.out"
check "V: plugin source diff 4e3aafce..b3d522ad empty" grep -q 'source diff: empty' $F/V.out
check "V: markers present in the candidate, absent in production" sh -c "grep -q 'markers expected present: PASS' $F/V.out && grep -q 'markers expected absent: PASS' $F/V.out"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
touch $W/raw/Vc.ok; print "NOT REHEARSED: Vc (real Claude Code); marker made by hand."

head1 "S refuses while another run_test_shards runs (quiet-host check only; the suite itself is not run here)"
print -l -- "7171 1 python scripts/run_test_shards.py --shards 6" >> $F/ps.txt
steps S > $F/S.out 2>&1; check "S refused" [ $? -ne 0 ]; grep -E 'Worktree HEAD|loadavg|other pytest|STOP' $F/S.out
check "S: Worktree src/tests/pyproject equal the target" grep -q 'equal b3d522ad' $F/S.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "S2 counts leftovers of a finished suite (synthetic suite output; ps -E stub), never signals"
mkdir -p $W/raw; print 3 > $W/S-basetemp-before
PR=$(env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=${TMPDIR:-/tmp} $CONDA -I -c 'import tempfile; print(tempfile.gettempdir())')/pytest-of-${USER:-luoxiao}
print -l "test run id: abcdef0123456789 (shard n carries PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-<n>)" "== DONE 12:00:00" > $W/raw/S-suite.txt
print -l -- $HOSTLINE $TIMERLINE "8181 1 1:00 /usr/bin/python3 -m graphtraj.execution.budget_idle_timer x PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-2 HOME=/h" \
  "8282 1 1:00 $FB/svenv/bin/python fake_runtime.py" "8383 1 1:00 sleep 99 PWD=$PR/pytest-1/old" > $F/ps.txt
steps S2 > $F/S2.out 2>&1; check "S2 exit 0" [ $? -eq 0 ]; grep -E '^(run id|leftover|  [0-9])' $F/S2.out
check "S2 counted 2 (run marker, suite venv; not an older basetemp)" grep -q 'leftover processes of the suite (never signalled): 2' $F/S2.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "I waits while a Task 460 member Worker and Main's host run, then passes with only the idle timer left"
print -l -- $HOSTLINE $TIMERLINE $WORKERLINE > $F/ps.txt
( sleep 3; print -l -- $TIMERLINE > $F/ps.txt.new; mv $F/ps.txt.new $F/ps.txt ) &
REMOVER=$!
print | steps I > $F/I.out 2>&1; IRC=$?
wait $REMOVER
check "I exit 0" [ $IRC -eq 0 ]
check "I waited and named Tasks 460-463, no kill, Ctrl-C safe" sh -c "grep -q '正在等待：Task 460、461、462、463' $F/I.out && grep -q 'Waiting for Task 460, 461, 462, 463' $F/I.out && grep -q 'Do not kill them' $F/I.out && grep -q 'Ctrl-C 可以安全放弃' $F/I.out"
check "I listed the Worker as BLOCKING with its Task" grep -q '\[member Worker of Task 460 ' $F/I.out
check "I never listed the timer as BLOCKING" sh -c "! grep -q 'BLOCKING.*budget_idle_timer\|\] .*budget_idle_timer' $F/I.out"
grep -E '正在等待|Waiting for|BLOCKING|NON-BLOCKING|^-rw|^PASS|^FAIL|Successfully|SAME-AS|markers expected|plugin bytes|^457 _stop|bytes unchanged|^changed|claude --continue' $F/I.out | uniq
check "proddiff PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $W/raw/I-verify.txt
check "I: markers present in the installed site-packages" grep -q 'markers expected present: PASS (11/11)' $F/I.out
check "I: the import line prints 457/459 names from .venv-runtime" grep -q '^457 _stop_escaped | 459 SAMPLE_SECONDS 1.0 DescendantSampler | 459 correction shown_command' $F/I.out
check "I: plugin bytes as before (no trust dialog)" grep -q 'plugin bytes as before the install: no trust dialog expected' $F/I.out
check "backup entry copies are all -rw-------" sh -c "[ \$(ls -A $FB/backup/entries | wc -l) -eq 3 ] && ! stat -f '%Sp' $FB/backup/entries/.[!.]* $FB/backup/entries/* 2>/dev/null | grep -qv -- '-rw-------'"
stat -f '%Sp %N' $FB/backup/entries/*(D)
check "backup tools include markers.py, nr459.py and watch459.py" test -f $FB/backup/tools/markers.py -a -f $FB/backup/tools/nr459.py -a -f $FB/backup/tools/watch459.py
check "I printed claude --continue" grep -q "cd $FH && claude --continue" $F/I.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version|continue' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
check "after R the 464 markers are absent again" $CONDA -I $SD/markers.py $FRT/lib/python3.13/site-packages absent

head1 "Mps accepts a host whose parent is claude --continue"
print -l -- $HOSTLINE > $F/ps.txt; mkdir -p $FH/.graphtraj/claude-host; print "x outcome=ok" >> $FH/.graphtraj/claude-host/host.log
steps Mps > $F/Mps.out 2>&1; grep -E '^(host uses|parent)' $F/Mps.out
check "Mps: parent is claude --continue ... yes" grep -q 'parent is claude --continue or --resume .*: yes' $F/Mps.out

head1 "Nw: the read-only watcher copies the descendants record while the child runs, then ends by itself"
A=$FH/.graphtraj/swarm/control/agents; ND=$FH/.graphtraj/swarm/native/c1; mkdir -p $A $ND
SC1=$ND/tool-descendants-n1.json SC2=$ND/tool-descendants-n2.json
# A real process that has already ended stands for the Bash tool shell: its identity is recorded, it is not alive.
TOOLENTRY=$($CONDA -I -c "import sys, json, subprocess; sys.path.insert(0, '$W/src/src'); from graftling.tool_descendants import identity
p = subprocess.Popen(['/bin/sleep', '1']); i = identity(p.pid); p.wait()
print(json.dumps({'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/zsh -c -l source snapshot && eval \"echo n464-tool && sleep 3\"'}))")
print -r -- '{"version":1,"runtime_pid":1,"entries":['$TOOLENTRY']}' > $SC1
print -r -- '{"agent":"c1","name":"n464","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"running","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json
rm -f $W/raw/Nw.txt
steps Nw > $F/Nw.out 2>&1; check "Nw exit 0 and started in the background" grep -q 'started at' $F/Nw.out
sleep 1
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1; print -r -- '{"version":1,"runtime_pid":2,"entries":[]}' > $SC2
print -r -- '{"agent":"c1","name":"n464","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"ended","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
for i in {1..50}; do grep -q '== END' $W/raw/Nw.txt 2>/dev/null && break; sleep 0.2; done
cat $W/raw/Nw.txt
check "Nw ended by itself when both executions ended (no background process left)" grep -q '== END (both executions ended)' $W/raw/Nw.txt
check "Nw snapshot kept the Bash tool command" grep -q 'n464-tool' $W/raw/Nw-snapshots.jsonl
check "Nw never copied the marker value" sh -c "! grep -q 'm-secret-marker' $W/raw/Nw-snapshots.jsonl $W/raw/Nw.txt"
print -l 'session_id: x' 'execution_id: n1' 'escaped_processes:' '  found: []' '  stopped: []' '  remaining: []' > $ND/claude-termination-n1.yml
print -l 'session_id: x' 'execution_id: n2' 'escaped_processes: null' > $ND/claude-termination-n2.yml

head1 "Nr on synthetic records (455 configuration, 452 ends, one user/message input per execution)"
AL=464-production_adoption_457_459-handover0-advisor@advisor
A=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/$AL; mkdir -p $A $FH/.graphtraj/swarm/sessions/sess-m $MS
print '{"agent":"c1","name":"n464","parent":"'$AL'","selection":{"preset":null,"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","reasoning_effort":null},"retired_at":"x","executions":[{"id":"e1","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","outcome":"completed","notification":"delivered","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
print -l 'session: sess-m' 'task_id: "464"' 'role: advisor' 'execution_id: m1' > $MS/mapping.yml
print -l 'execution_id: m1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
# Each execution: one delivered user/message input, plus a tool result and an assistant quote naming it (453's noise).
for e in e1 e2; do
  print -r -- '{"type":"tool/result","data":{"text":"{\"execution\":\"'$e'\",\"source\":\"graphtraj\"}"}}'
  print -r -- '{"type":"user/message","data":{"content":"{\"source\":\"graphtraj\",\"agent\":\"c1\",\"execution\":\"'$e'\",\"outcome\":\"completed\"}"}}'
  print -r -- '{"type":"assistant/message","data":{"content":"received {\"source\":\"graphtraj\",\"execution\":\"'$e'\"}"}}'
done > $FH/.graphtraj/swarm/sessions/sess-m/session.jsonl
print "{\"launch_status\":\"launched\",\"agent\":\"agent-464-adv-xyz\",\"alias\":\"$AL\"}" > $W/raw/N.txt
print "[Graftling notice from $AL · completed · execution m1]" > $W/raw/N-main-notice.txt
print '{"agent":"c1","name":"n464","configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' > $W/raw/N-reply.txt
print -l -- $HOSTLINE > $F/ps.txt
steps Nr > $F/Nr.out 2>&1; grep -E '^child|CHECK|^member|member end|archive|stored selection|retire with' $F/Nr.out
check "Nr: no CHECK line is FAIL, BY HAND or PENDING" sh -c "! grep '^CHECK' $W/raw/Nr.txt | grep -qE 'FAIL|BY HAND|PENDING'"
check "Nr: 455 stored record PASS" grep -q 'CHECK 455 stored record: configuration and model not null: PASS' $W/raw/Nr.txt
check "Nr: one parent input per execution counted by event type" [ $(grep -c 'CHECK 449/451 one parent input for execution .*: PASS' $W/raw/Nr.txt) -eq 2 ]
check "Nr: retire prompt uses the swarm agent, not the alias" grep -q 'retire with {"agent":"agent-464-adv-xyz"}' $F/Nr.out
check "Nr: 459 facts recorded PASS" grep -q 'CHECK 459 create execution recorded tool_marker and tool_descendants: PASS' $W/raw/Nr.txt
check "Nr: 459 record lists the Bash tool command (from the Nw snapshot) PASS" grep -q 'CHECK 459 descendants record lists the Bash tool command: PASS' $W/raw/Nr.txt
check "Nr: 459 no recorded tool process alive PASS (the recorded one has ended)" grep -q 'CHECK 459 no recorded tool process alive after the end: PASS' $W/raw/Nr.txt
check "Nr: the owner's normal-end escaped_processes printed with its file" grep -q "normal-end reclaim ($FH/.graphtraj/swarm/native/c1/claude-termination-n1.yml): escaped_processes found=0" $W/raw/Nr.txt
check "Nr: the marker value is never printed" sh -c "! grep -q 'm-secret-marker' $W/raw/Nr.txt $F/Nr.out"

head1 "Nr negative: a null configuration, an owner-exited end and a live member Worker are reported"
print '{"agent":"c1","name":"n464","parent":"'$AL'","selection":{"configuration":null,"model":null},"retired_at":null,"executions":[{"id":"e1","state":"ended","outcome":"failed","error":{"code":"owner-exited"},"notification":"delivered","process":{"tool_descendants":"'$SC1'"},"escaped_processes":{"found":[],"stopped":[],"remaining":[]}},{"id":"e2","state":"ended","outcome":"completed","notification":"delivered"}]}' > $A/c1.json
print '{"configuration": null, "model": null}' > $W/raw/N-reply.txt
print -l -- $HOSTLINE "9191 1 1:00 $FRT/bin/python -I -m graphtraj.execution.runner_worker $MS/resume.yml" "7777 /bin/zsh -c echo n464-tool && sleep 3" > $F/ps.txt
# 459 negative: a recorded entry still alive with its start time (a real sleep this rehearsal started), no tool command
# in any snapshot, no tool_marker recorded.
/bin/sleep 120 & LIVE=$!
$CONDA -I -c "import sys, json; sys.path.insert(0, '$W/src/src'); from graftling.tool_descendants import identity; i = identity($LIVE); print(json.dumps({'version': 1, 'runtime_pid': 1, 'entries': [{'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/sleep 120'}]}))" > $SC1
print -r -- '{"at":1,"agent":"c1","execution":"e1","sidecar":"'$SC1'","record":{"version":1,"runtime_pid":1,"entries":[]}}' > $W/raw/Nw-snapshots.jsonl
steps Nr > $F/Nr2.out 2>&1; grep -E '^CHECK' $W/raw/Nr.txt | grep -E 'FAIL'
check "Nr negative: 455 FAIL, 452 owner-exited FAIL, live Worker FAIL" sh -c "grep -q 'CHECK 455 stored record.*: FAIL' $W/raw/Nr.txt && grep -q 'CHECK 452 child execution e1 .*: FAIL' $W/raw/Nr.txt && grep -q 'CHECK 452 no runner_worker .*: FAIL' $W/raw/Nr.txt && grep -q 'CHECK 455 create/status .*: FAIL' $W/raw/Nr.txt"
check "Nr negative 459: no tool_marker recorded gives FAIL" grep -q 'CHECK 459 create execution recorded tool_marker and tool_descendants: FAIL' $W/raw/Nr.txt
check "Nr negative 459: Nw ran but no record named the command gives FAIL" grep -q 'CHECK 459 descendants record lists the Bash tool command: FAIL' $W/raw/Nr.txt
check "Nr negative 459: a recorded entry alive with its start time (and a process naming n464-tool) gives FAIL" sh -c "grep -q 'CHECK 459 no recorded tool process alive after the end: FAIL (1 alive, 1 named' $W/raw/Nr.txt && grep -q \"ALIVE pid $LIVE \" $W/raw/Nr.txt"
check "Nr negative 459: the record's escaped_processes (owner-exited reconcile) printed" grep -q 'execution e1: record escaped_processes = {"found": \[\]' $W/raw/Nr.txt
check "Nr never signalled the live recorded process" kill -0 $LIVE
kill $LIVE; wait $LIVE 2>/dev/null

head1 "M / N print real values"
steps M > $F/M.out; check "M names Tasks 460-463 (may arrive once, must not repeat)" grep -q 'Task 460、461、462、463' $F/M.out
steps N > $F/N.out
check "N prompt names task 464, the preset role and the exact Bash command" sh -c "grep -q '\"task_id\":\"464\"' $F/N.out && grep -q 'named n464 with configuration opus_coding_team.advisor' $F/N.out && grep -qF 'Use the Bash tool once to run exactly: echo n464-tool && sleep 3 . Then reply DONE-464.' $F/N.out"
check "N prompt forbids submit_result and submit_report" grep -q 'Do NOT call submit_result or submit_report' $F/N.out
check "N prompt asks for source graphtraj inputs verbatim" grep -q 'whose JSON has source graphtraj, in order, verbatim' $F/N.out
rm -f $F/ps.txt
print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED)"
exit $FAILED
