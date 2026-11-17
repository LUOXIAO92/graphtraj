#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-492/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv). Test directories are under the fake Harness ($FH/tmp/499).
# 503: the old production is 871aaaa9's wheels; <Harness>/graftling is a stand-in repository (see setup).
#   zsh scripts/adopt-503/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt503-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/503
OB=$FH/tmp/499   # 499's backup base (under the Harness): listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
ISO=$SD/../verify-common/claude_isolation.py
OLD=871aaaa9ea7f63998990cb6600ca098d320e18c8   # production now: 499's wheels
NEW=6115c72491a238cc672d88ec539cda800e4c3651
export ADOPT503_NW468_SECONDS=3 ADOPT503_H=$FH ADOPT503_BASE=$FB ADOPT503_RT=$FRT ADOPT503_PNPM_SHIM=$F/no-shim ADOPT503_STUB=$F/stub ADOPT503_WT=$WT ADOPT503_PROJECTS=$F/projects ADOPT503_WAIT=1 ADOPT503_OLDBASE=$OB
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=503-production-adoption-graftling-split
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-6115c724
SESSIONS=$FH/.graphtraj/core/runner/sessions
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
lst() { LC_ALL=C date -r $1 '+%a %b %e %H:%M:%S %Y'; }   # ps lstart form (steps.zsh runs ps with LC_ALL=C)
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "setup: old wheels from $OLD, fake production venv, plugin, configuration"
rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldwheels $FH $OB/backup
# Stub claude: -p reads the prompt and answers in stream-json with the prompt's tag (claude_isolation.py judges it).
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "2.1.325 (stub Claude Code)" ;;
  plugin) print "✔ Validation passed (stub)" ;;
  -p) in=$(cat); tag=$(print -r -- "$in" | sed -n 's/.*Line 1: \([A-Z-]*\) followed.*/\1/p')
      # echo mode (a file next to the stub): answer with the prompt itself, as the Task 489 failure did.
      if [[ -e ${0:A:h}/echo-mode ]]; then
        print -r -- '{"type":"system","subtype":"init","plugins":[]}'
        /Users/luoxiao/miniconda3/bin/python3.13 -I -c 'import json, sys; print(json.dumps({"type": "result", "is_error": False, "result": sys.argv[1], "modelUsage": {}}))' "$in"
        exit 0
      fi
      print -r -- '{"type":"system","subtype":"init","plugins":[]}'
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-stub} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
chmod +x $F/stub/claude
git -C $WT archive $OLD | tar -x -C $F/oldsrc
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldsrc/src/graftling
ls $F/oldwheels
# Stand-in for <Harness>/graftling (not readable here): 871aaaa9's src/graftling with 395's version bump (__init__,
# the two package.json, the plugin manifest, a CHANGELOG entry), committed and tagged v0.5.2 (annotated), the layout
# 395's graftling_wheel builds ($G/src/graftling). A working-tree change after the tag must not reach the wheel.
GR=$F/graftling-repo; mkdir -p $GR
git -C $WT archive $OLD src/graftling | tar -x -C $GR
sed -i '' 's/^__version__ = "0.5.0"/__version__ = "0.5.2"/' $GR/src/graftling/__init__.py
for j in pi/package.json dsh/package.json claude-plugin/.claude-plugin/plugin.json; do sed -i '' 's/"version": "0.5.0"/"version": "0.5.2"/' $GR/src/graftling/$j; done
print -l '' '## 0.5.2' '- Split into its own repository (395).' >> $GR/src/graftling/CHANGELOG.md
git -C $GR init -q --initial-branch=main; git -C $GR add -A; git -C $GR -c user.name=x -c user.email=x@invalid commit -qm 'graftling 0.5.2'
git -C $GR -c user.name=x -c user.email=x@invalid tag -a v0.5.2 -m v0.5.2
print '# working tree only' >> $GR/src/graftling/control.py   # must not reach the wheel (B reads git archive v0.5.2)
export ADOPT503_G=$GR ADOPT503_GCOMMIT=$(git -C $GR rev-parse --short=8 v0.5.2^{commit})
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
for f in $WT/.state/task.md ${def:+$WT/.state/$def}; do
  sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $W:h/${f#$WT/.state/}
done
# Other Tasks for the waiting line: 465 integrated (not named), 466 and 470 pending (named).
for t in 465-x:integrated 466-y:pending 470-z:pending; do mkdir -p $ST/${t%%:*}; print "status: ${t#*:}" > $ST/${t%%:*}/task.yml; done
# 492's backup (tmp/497 under the Harness): must be listed and stay unchanged.
print "499 backup" > $OB/backup/COMPLETE; print kept > $OB/backup/venv.manifest
( cd $FH && find tmp/499 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256

MAINID=11111111-2222-3333-4444-555555555555
mkdir -p $F/projects; : > $F/projects/$MAINID.jsonl
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
OLDT_CMD="$FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $SESSIONS/451-x 0123abcd0123abcd 777"
OTHER_CMD="/usr/bin/python3 -I -m graphtraj.execution.budget_idle_timer /elsewhere/sessions/9-y 99999999aaaa 1"
TIMERLINE="5151 1 $OLDT_CMD"
WORKERLINE="6161 1 $FRT/bin/python -I -m graphtraj.execution.runner_worker $SESSIONS/466-session_read_in_agents-handover0-engineer@engineer/resume.yml"
T_OLD=$(( $(date +%s) - 7200 ))
print -l "# Fake Harness rules" "This distinctive Harness instruction line must never reach the isolated project answer." > $FH/AGENTS.md
cat > $F/stub/ps <<EOF2
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
if [[ "\$*" == *"lstart="* ]]; then [[ -e $F/pstimer.txt ]] && cat $F/pstimer.txt; exit 0; fi
if [[ "\$*" == *"stat="* ]]; then [[ -e $F/psstat.txt ]] && cat $F/psstat.txt; exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF2
chmod +x $F/stub/ps
# Stub sysctl: vm.loadavg from $F/load.txt when present (S's quiet wait), anything else from the real sysctl.
cat > $F/stub/sysctl <<EOF2
#!/bin/zsh
if [[ "\$*" == *vm.loadavg* && -e $F/load.txt ]]; then cat $F/load.txt; exit 0; fi
exec /usr/sbin/sysctl "\$@"
EOF2
chmod +x $F/stub/sysctl
# Timer listing fixture: an old production timer 5151 with a zombie child 5252, and a timer from another executable.
print -l -- "5151 1 S $(lst $T_OLD) $OLDT_CMD" "5252 5151 Z $(lst $T_OLD) <defunct>" "7777 1 S $(lst $T_OLD) $OTHER_CMD" > $F/pstimer.txt

head1 "README 3(a): no Python module of graphtraj or graftling changes in $OLD..$NEW (only graftling/__init__.py's version line)"
mkdir -p $F/timer/old $F/timer/new
git -C $WT archive $OLD src | tar -x -C $F/timer/old; git -C $WT archive $NEW src | tar -x -C $F/timer/new
git -C $GR archive v0.5.2 | tar -x -C $F/timer/new
(cd $F/timer && diff -rq old/src new/src | grep -E '\.py ' ) > $F/timer.out 2>&1; cat $F/timer.out
check "timer: the only Python file that differs between $OLD and $NEW + graftling v0.5.2 is graftling/__init__.py (a running timer meets the same code)" sh -c "[ \$(wc -l < $F/timer.out) -eq 1 ] && grep -q 'graftling/__init__.py' $F/timer.out"

head1 "markers on git-archive trees: present in $NEW + graftling v0.5.2, absent in $OLD"
check "markers present in $NEW (7/7)" sh -c "$CONDA -I $SD/markers.py $F/timer/new/src present | tail -1 | grep -q 'PASS (7/7)'"
check "markers absent in $OLD (7/7)" sh -c "$CONDA -I $SD/markers.py $F/timer/old/src absent | tail -1 | grep -q 'PASS (7/7)'"
check "markers negative: 'present' on $OLD fails" sh -c "! $CONDA -I $SD/markers.py $F/timer/old/src present > /dev/null"
check "markers negative: 'absent' on $NEW fails" sh -c "! $CONDA -I $SD/markers.py $F/timer/new/src absent > /dev/null"
cp -R $F/timer/new/src $F/timer/half; cp $F/timer/old/src/graphtraj/runtimes/pi/extension.mjs $F/timer/half/graphtraj/runtimes/pi/
check "markers negative: new tree with the old Pi extension (sibling import back) fails 'present'" sh -c "! $CONDA -I $SD/markers.py $F/timer/half present > /dev/null"

head1 "claude_isolation.py check (489, used for 00 and Vc): positive, prompt echo, Harness AGENTS.md path, distinctive line, no answer"
$CONDA -I $ISO prompt MODEL-OK > $F/ask.txt
mkans() { $CONDA -I -c 'import json, sys; print(json.dumps({"type":"system","subtype":"init","plugins":[{"name":p} for p in sys.argv[2:]]})); print(json.dumps({"type":"result","is_error":False,"result":sys.argv[1],"modelUsage":{"claude-opus-5-5":{}}}))' "$@"; }
mkans $'MODEL-OK claude-opus-5-5, logged in\nFILES: NONE' > $F/a-ok.jsonl
mkans "$(cat $F/ask.txt)" > $F/a-echo.jsonl
mkans $'MODEL-OK claude-opus-5-5, logged in\nFILES: '$FH/AGENTS.md cc-plugin-agents-md > $F/a-path.jsonl
mkans $'MODEL-OK claude-opus-5-5. This distinctive Harness instruction line must never reach the isolated project answer.\nFILES: NONE' > $F/a-line.jsonl
print -r -- '{"type":"system","subtype":"init","plugins":[]}' > $F/a-none.jsonl
for c in ok echo path line none; do $CONDA -I $ISO check $F/a-$c.jsonl MODEL-OK $FH $FB/vproject $F/ask.txt > $F/a-$c.out 2>&1; print "$c rc=$?: $(tail -1 $F/a-$c.out)"; done
check "isolation check: positive OK" grep -q 'answer check (expect clean): OK' $F/a-ok.out
check "isolation check: prompt echo STOP" sh -c "grep -q 'echo of the prompt: YES' $F/a-echo.out && grep -q 'answer check (expect clean): STOP' $F/a-echo.out"
check "isolation check: Harness AGENTS.md listed and cc-plugin-agents-md loaded STOP" sh -c "grep -q 'Harness files among them: \[' $F/a-path.out && grep -q 'cc-plugin-agents-md loaded: YES' $F/a-path.out && grep -q 'answer check (expect clean): STOP' $F/a-path.out"
check "isolation check: distinctive AGENTS.md line STOP (line never printed)" sh -c "grep -q 'distinctive Harness AGENTS.md line in the answer: YES' $F/a-line.out && grep -q 'answer check (expect clean): STOP' $F/a-line.out"
check "isolation check: no result record STOP" grep -q 'answer check (expect clean): STOP' $F/a-none.out
check "isolation settings refuses a project outside <harness>/tmp/" sh -c "$CONDA -I $ISO settings $FH $F/outside | grep -q REFUSED"

head1 "00 (host's parent is 'claude --continue'; Main from the newest transcript; isolated vproject under tmp/499; timers listed)"
print -l -- $HOSTLINE $TIMERLINE "5252 5151 $FRT/bin/python <defunct>" "5353 5151 $FRT/bin/python -I -m graphtraj.execution.runner_worker $SESSIONS/451-x/resume.yml" "7777 1 $OTHER_CMD" > $F/ps.txt
print -l -- "5151 1 S" "5252 5151 Z" "5353 5151 S" "7777 1 S" "$$ 1 S" > $F/psstat.txt
steps 00 > $F/00.out 2>&1; ZRC=$?
check "00 found Main through claude --continue + newest transcript" grep -q "MAIN=$MAINID" $F/00.out
check "00 listed every timer: pid, ppid, stat, start, production exe, session, token, children with stat (zombie)" sh -c "grep -q 'budget_idle_timer processes: 2 (production .venv-runtime 1' $F/00.out && grep -q 'timer pid 5151 ppid 1 stat S start .* exe production .venv-runtime | session $SESSIONS/451-x token 0123abcd… | children 1: 5252(Z)' $F/00.out && grep -q 'timer pid 7777 .* exe other: /usr/bin/python3 | session /elsewhere/sessions/9-y' $F/00.out"
check "00: a timer's zombie child is information only; a LIVE child Worker under \$RT is BLOCKING and named as the timer's child" sh -c "grep -q 'guard: zombies (ps stat Z; information only.*: 1' $F/00.out && ! grep -q '\] 5252 ' $F/00.out && grep -q 'child of budget_idle_timer 5151\] 5353 ' $F/00.out && grep -q 'the timers themselves never make I refuse' $F/00.out"
check "00: the timers themselves are never BLOCKING" sh -c "! grep -q '\] 5151 \|\] 7777 ' $F/00.out"
check "00: answer from the isolated vproject (claude_isolation check OK); vproject settings disable cc-plugin-agents-md" sh -c "grep -q 'answer check (expect clean): OK' $F/00.out && grep -q 'cc-plugin-agents-md@builtin: False' $F/00.out && grep -q '\"cc-plugin-agents-md@builtin\": false' $FB/vproject/.claude/settings.local.json && grep -q '$FH/AGENTS.md' $FB/vproject/.claude/settings.local.json"
check "00: control records snapshot 00.json" grep -q 'control records snapshot 00.json' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
check "00: the 497 markers are absent from the old production" grep -q 'markers expected absent: PASS (7/7)' $F/00.out
check "00 with Main's host under \$RT: exit 0, BLOCKING listed, the information line, no '00 STOP'" sh -c "[ $ZRC -eq 0 ] && grep -q 'guard: BLOCKING 2 ' $F/00.out && grep -q \"\\[Main's Claude host\\] \" $F/00.out && grep -q 'guard: BLOCKING at 00 is information only' $F/00.out && ! grep -q '00 STOP' $F/00.out"
check "00 printed its next step (B)" grep -q "next.*: zsh $SD/steps.zsh B" $F/00.out
touch $F/stub/echo-mode
steps 00 > $F/00-echo.out 2>&1; ZRC2=$?
rm -f $F/stub/echo-mode
grep -E 'answer|echo of the prompt|STOP' $F/00-echo.out
check "00 with a failing answer check (prompt echo): exit non-zero, STOP line and '00 STOP', no next step" sh -c "[ $ZRC2 -ne 0 ] && grep -q 'echo of the prompt: YES' $F/00-echo.out && grep -q '^STOP: claude -p answer check failed' $F/00-echo.out && grep -q '00 STOP（see the STOP line above' $F/00-echo.out && ! grep -q 'steps.zsh B' $F/00-echo.out"
check "the first 00.txt was kept as 00-first.txt, the rerun wrote a fresh 00.txt" sh -c "grep -q 'guard: BLOCKING at 00 is information only' $RW/00-first.txt && grep -q 'echo of the prompt: YES' $RW/00.txt && ! grep -q 'guard: BLOCKING at 00' $RW/00.txt"
check "00 printed claude --version and the binary" grep -q '^claude: .*stub/claude -> .* | version: 2.1.325' $F/00.out
check "00 made the read-only production task graph call for Task 503 (stub tree: rc printed)" sh -c "grep -q 'task graph rc=' $F/00.out && grep -q 'graph --task-id 503' $F/00.out"
check "00: isolation OK (vproject has its own git and .graphtraj)" grep -q '^isolation: OK' $F/00.out
check "00: Task 503 stopped: false" grep -q '^stopped: false' $F/00.out
check "00 listed 492's backup and its COMPLETE marker" sh -c "grep -q 'tmp/499/backup' $F/00.out && grep -q '499 backup COMPLETE marker: present' $F/00.out"
check "00 named the Tasks that may run now (466, 470; not 465)" sh -c "grep 'may run now' $F/00.out | grep -q '466, 470'"
grep -E '^claude:|inherited|MAIN=|isolat|may run now|^stopped|markers|timer pid|budget_idle|\[' $F/00.out | grep -v '^\[00\]'
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt; print -l -- "5151 1 S" "5252 5151 Z" "$$ 1 S" > $F/psstat.txt

head1 "B (two repositories: graftling from git archive v0.5.2 of the stand-in, graphtraj from git archive $NEW)"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked|peels|main:|wheel version|Requires|carries' $F/B.out
check "B: tag peels to the expected commit, full sha and main printed; graftling 0.5.2; Requires-Dist graftling<0.6,>=0.5.2; graphtraj carries no graftling/; leaked 0" sh -c "grep -q 'v0.5.2 peels to $ADOPT503_GCOMMIT…: yes' $F/B.out && grep -q '^v0.5.2^{commit}: [0-9a-f]\{40\}' $F/B.out && grep -q 'main points at v0.5.2: yes' $F/B.out && grep -q '^graftling wheel version: 0.5.2' $F/B.out && grep -q '^graphtraj Requires-Dist: graftling<0.6,>=0.5.2' $F/B.out && grep -q 'graphtraj wheel carries graftling/: 0 files' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: the stand-in's working-tree change after the tag is not in the wheel (git archive v0.5.2)" sh -c "! unzip -p $W/wheels-6115c724/graftling-0.5.2-py3-none-any.whl graftling/control.py | grep -q 'working tree only'"
ADOPT503_GCOMMIT=deadbeef steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to 395's commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.5.2^{commit} is .*, not deadbeef' $F/B-tag.out"
steps B > $F/B.out 2>&1

head1 "V (stub plugin validate)"
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
mkdir -p $F/aside; mv $ST/465-x $ST/466-y $ST/470-z $F/aside/
steps V > $F/V.out 2>&1; check "V exit 0" [ $? -eq 0 ]
mv $F/aside/* $ST/
grep -E '^(SAME|CHANGED)|source diff|plugin unchanged|graftling code|^  (VERSION|DOC|CODE)|markers expected|CHECK 503|layout:|STOP|✘|^next|下一步' $F/V.out
check "V: plugin files SAME x3, no trust dialog predicted" sh -c "[ \$(grep -cE '^SAME +(.claude-plugin/plugin.json|hooks/hooks.json|hooks/host_context.mjs)\$' $F/V.out) -ge 3 ] && ! grep -q '^CHANGED' $F/V.out && grep -q 'plugin unchanged: no plugin/hooks trust dialog' $F/V.out"
check "V: Claude hook/plugin source diff is only the plugin manifest's version line" sh -c "[ \$(grep -cE '^[<>]' $RW/V-source.diff) -eq 2 ] && [ \$(grep -E '^[<>]' $RW/V-source.diff | grep -cv '\"version\"') -eq 0 ]"
check "V: graftling code vs production SAME CODE: VERSION __init__.py and both package.json, DOC CHANGELOG.md, code-differences=0" sh -c "grep -q 'graftling code vs production: SAME CODE' $F/V.out && grep -q '  VERSION graftling/__init__.py' $F/V.out && grep -q '  VERSION graftling/pi/package.json' $F/V.out && grep -q '  DOC     graftling/CHANGELOG.md' $F/V.out && grep -q 'code-differences=0' $F/V.out"
check "V: markers present in the candidate, absent in production (7/7)" sh -c "grep -q 'markers expected present: PASS (7/7)' $F/V.out && grep -q 'markers expected absent: PASS (7/7)' $F/V.out"
check "V: one graftling in the scratch venv and node resolves both modules to the sibling" sh -c "grep -q '^503 layout: PASS' $F/V.out && [ \$(grep -c 'node resolves .*vvenv-6115c724/lib/python3.13/site-packages/graftling/: PASS' $F/V.out) -ge 2 ] && ! grep -q 'node resolves .*: FAIL' $F/V.out"
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
check "V's next is USER's Vu (S comes after Pr)" grep -q "USER: zsh $SD/steps.zsh Vu    （之后 Main: zsh $SD/steps.zsh Vc）" $F/V.out

head1 "graftcode.py negative: a real code change in the graftling wheel STOPs with the file and its diff"
mkdir -p $F/gcneg; (cd $F/gcneg && unzip -q $W/wheels-6115c724/graftling-0.5.2-py3-none-any.whl && print '    pass  # changed' >> graftling/control.py && rm graftling/pi/package.json && zip -qr ../gcneg.whl .)
$CONDA -I $SD/graftcode.py $F/gcneg.whl $FRT/lib/python3.13/site-packages > $F/gcneg.out 2>&1; GN=$?; grep -vE '^    ' $F/gcneg.out
check "graftcode negative: exit 1, CODE control.py with its diff, a production-only file listed, STOP" sh -c "[ $GN -eq 1 ] && grep -q '  CODE    graftling/control.py' $F/gcneg.out && grep -q '^--- diff \[CODE\] graftling/control.py' $F/gcneg.out && grep -q '+    pass  # changed' $F/gcneg.out && grep -q 'graftling/pi/package.json (only in production)' $F/gcneg.out && grep -q 'graftling code vs production: STOP' $F/gcneg.out"
mkdir -p $F/gcneg2; (cd $F/gcneg2 && unzip -q $W/wheels-6115c724/graftling-0.5.2-py3-none-any.whl && sed -i '' 's/^__version__ = "0.5.2"/__version__ = "0.5.2"\nEXTRA = 1/' graftling/__init__.py && zip -qr ../gcneg2.whl .)
$CONDA -I $SD/graftcode.py $F/gcneg2.whl $FRT/lib/python3.13/site-packages > $F/gcneg2.out 2>&1; GN=$?
check "graftcode negative: __init__.py with a line besides __version__ is CODE (STOP)" sh -c "[ $GN -eq 1 ] && grep -q '  CODE    graftling/__init__.py' $F/gcneg2.out"

head1 "onegraft.py negatives on a copy of the scratch venv: a second graftling dist-info; a .pth to a source checkout"
VV=$FB/vvenv-6115c724; VS=$VV/lib/python3.13/site-packages
cp -R $VS/graftling-0.5.2.dist-info $VS/graftling-0.5.0.dist-info; sed -i '' 's/^Version: 0.5.2/Version: 0.5.0/' $VS/graftling-0.5.0.dist-info/METADATA
$VV/bin/python -I $SD/onegraft.py $VV 0.5.2 > $F/og-dist.out 2>&1; OG=$?; grep -E 'one (distribution|package)|layout:' $F/og-dist.out
check "onegraft negative: second dist-info FAILs 'one distribution' and 'one package'" sh -c "[ $OG -ne 0 ] && grep -q 'CHECK 503 layout one distribution: FAIL (2 found' $F/og-dist.out && grep -q 'CHECK 503 layout one package: FAIL' $F/og-dist.out"
rm -rf $VS/graftling-0.5.0.dist-info
print -r -- $GR/src > $VS/zz-graftling-source.pth
$VV/bin/python -I $SD/onegraft.py $VV 0.5.2 > $F/og-pth.out 2>&1; OG=$?; grep -E 'source link|layout:' $F/og-pth.out
check "onegraft negative: a .pth to the graftling source checkout FAILs 'no source link'" sh -c "[ $OG -ne 0 ] && grep -q 'CHECK 503 layout no source link: FAIL (links \[.zz-graftling-source.pth: $GR/src' $F/og-pth.out"
rm -f $VS/zz-graftling-source.pth
print -r -- '{"url": "file:///x/graftling", "dir_info": {"editable": true}}' > $VS/graftling-0.5.2.dist-info/direct_url.json.neg
cp $VS/graftling-0.5.2.dist-info/direct_url.json $F/direct_url.keep; mv $VS/graftling-0.5.2.dist-info/direct_url.json.neg $VS/graftling-0.5.2.dist-info/direct_url.json
$VV/bin/python -I $SD/onegraft.py $VV 0.5.2 > $F/og-ed.out 2>&1; OG=$?
check "onegraft negative: an editable (directory) install FAILs 'wheel install'" sh -c "[ $OG -ne 0 ] && grep -q 'CHECK 503 layout wheel install: FAIL' $F/og-ed.out"
cp $F/direct_url.keep $VS/graftling-0.5.2.dist-info/direct_url.json
$VV/bin/python -I $SD/onegraft.py $VV 0.5.2 > /dev/null 2>&1; check "onegraft positive again after the negatives were removed" [ $? -eq 0 ]

head1 "node resolution negative: graftling missing beside graphtraj (empty environment: no python fallback) FAILs with the 395 text"
mv $VS/graftling $F/graftling.aside
(source <(sed -n '/^node_resolve() {/,/^}/p' $SD/steps.zsh); node_resolve $VV) > $F/node-neg.out 2>&1; NN=$?
mv $F/graftling.aside $VS/graftling; cat $F/node-neg.out | cut -c1-220
check "node_resolve negative: FAIL naming 'cannot find the installed graftling distribution'" sh -c "[ $NN -ne 0 ] && grep -q 'FAIL (.*GraphTraj cannot find the installed graftling distribution' $F/node-neg.out"

head1 "Vu prints the one dialog and /exit; Vc's isolation part (vc_setup) with the candidate venv"
steps Vu > $F/Vu.out 2>&1
check "Vu names the new path, 'Yes, proceed' and /exit" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out && grep -q '/exit' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc: isolation OK with the candidate code before claude -p" grep -q '^isolation: OK' $RW/Vc.txt
check "Vc: settings re-merged after configuration --write and the answer check OK (VC-OK)" sh -c "grep -q 'cc-plugin-agents-md@builtin: False' $RW/Vc.txt && grep -q 'answer: VC-OK' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc with the stub claude does not pass (no real plugin load) and asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok; print "NOT REHEARSED: Vc's real claude -p (real Claude Code); marker made by hand."

head1 "S quiet host (Correction 1): running suite from argv tokens only; pytest-of-* leftovers listed, not busy"
PT=/private/var/folders/xx/T/pytest-of-luoxiao
LEFT1="51001 1 2-22:01:10 $PT/pytest-968/installed-environment0/venv/bin/python -I -m graphtraj.execution.budget_idle_timer $PT/pytest-968/installed-environment0/project/.graphtraj/core/runner/sessions/1-a@b 0011aabb 4242"
LEFT2="51006 1 2-22:03:00 $PT/pytest-1794/test_x0/venv/bin/python -I -m graphtraj.execution.runner_worker $PT/pytest-1794/test_x0/project/.graphtraj/core/runner/sessions/1-a@b/resume.yml"
BUSY1="7272 1 01:00 /x/venv/bin/python -m pytest -q tests/test_x.py"
BUSY2="7171 1 02:00 /x/venv/bin/python /repo/scripts/run_test_shards.py --shards 6"
print -l -- "$LEFT1" "51002 1 2-22:01:10 ${LEFT1#* * * }" "51003 1 2-22:01:10 ${LEFT1#* * * }" "51004 1 2-22:01:10 ${LEFT1#* * * }" "51005 1 2-22:01:10 ${LEFT1#* * * }" "$LEFT2" \
  "7373 1 00:10 grep -E pytest|run_test_shards" "7474 1 00:10 vim /repo/tests/pytest.ini" > $F/busy-pos.txt
$CONDA -I $SD/busy499.py $F/busy-pos.txt 0 > $F/busy-pos.out; cat $F/busy-pos.out
check "busy499 positive: Main's 22:21 shapes (5 installed-environment timers, 1 Worker under pytest-of-*) are not a running suite, listed as 6 leftovers" sh -c "grep -q '^running suites: 0' $F/busy-pos.out && grep -q '^leftover test processes (information; never signalled; not a running suite): 6' $F/busy-pos.out && grep -q '  leftover: 51006 2-22:03:00 .*runner_worker' $F/busy-pos.out"
print -l -- "$BUSY1" "$BUSY2" "7575 1 00:05 /x/venv/bin/pytest -q tests" "7676 1 00:05 /usr/bin/python3 -mpytest tests" "7777 7272 00:01 /x/venv/bin/py.test -q" "9001 1 00:01 /x/venv/bin/python -m pytest own" "9002 9001 00:01 /x/venv/bin/pytest own-child" > $F/busy-neg.txt
$CONDA -I $SD/busy499.py $F/busy-neg.txt 9001 > $F/busy-neg.out; cat $F/busy-neg.out
check "busy499 negatives: '-m pytest', run_test_shards.py argument, pytest and py.test executables, -mpytest are running suites (5); own root 9001 and its child excluded" sh -c "grep -q '^running suites: 5' $F/busy-neg.out && ! grep -q ' 900[12] ' $F/busy-neg.out"
print -l -- $HOSTLINE $TIMERLINE "$LEFT1" "$LEFT2" > $F/ps.txt
head1 "503 S gate (499 lesson): refused before Pr unless Main states the host is idle; refused while P's children run, while the install runs, while Nw runs"
ADOPT503_S_NORUN=1 steps S > $F/S-gate0.out 2>&1; SG=$?
check "S refused before Pr without ADOPT503_S_IDLE (and names the idle override)" sh -c "[ $SG -ne 0 ] && grep -q 'STOP: Pr has not judged both children yet' $F/S-gate0.out && grep -q 'ADOPT503_S_IDLE=1 zsh' $F/S-gate0.out && ! grep -q 'fresh git checkout' $F/S-gate0.out"
date +%s > $RW/P.started; rm -f $RW/Pr.done
ADOPT503_S_IDLE=1 ADOPT503_S_NORUN=1 steps S > $F/S-gateP.out 2>&1; SG=$?
check "S refused while P's children run (P.started, no Pr.done), even with ADOPT503_S_IDLE" sh -c "[ $SG -ne 0 ] && grep -q 'P: the Pi/DSH children were started' $F/S-gateP.out && grep -q 'S refused: one of our steps runs' $F/S-gateP.out"
rm -f $RW/P.started; mkdir -p $FB/backup; touch $FB/backup/INSTALL-STARTED
ADOPT503_S_IDLE=1 ADOPT503_S_NORUN=1 steps S > $F/S-gateI.out 2>&1; SG=$?
check "S refused while the install runs (INSTALL-STARTED without I.ok)" sh -c "[ $SG -ne 0 ] && grep -q 'I: install started' $F/S-gateI.out"
rm -rf $FB/backup; print 'start: watching' > $RW/Nw.txt
ADOPT503_S_IDLE=1 ADOPT503_S_NORUN=1 steps S > $F/S-gateN.out 2>&1; SG=$?
check "S refused while N's watcher runs (Nw.txt without '== END')" sh -c "[ $SG -ne 0 ] && grep -q \"Nw: the watcher of N's child is still running\" $F/S-gateN.out"
rm -f $RW/Nw.txt
export ADOPT503_S_IDLE=1
head1 "S setup without the suite (ADOPT503_S_NORUN): fresh checkout of $NEW, test venv with graftling from B's wheel, nested check, TMPDIR outside"
ADOPT503_S_NORUN=1 steps S > $F/S2setup.out 2>&1; SRC_=$?; grep -E 'checkout|imports|nested|TMPDIR|NORUN|STOP|running suites|leftover|limit' $F/S2setup.out
half_cpus() { local l=$(grep -m1 '1-minute load limit:' $1) c lim; c=${${l#*CPUs: }%% *}; lim=${${l#*load limit: }%% *}; [[ $c == <-> ]] && (( lim == c / 2 )) && [[ $l == *'(half the CPU count; ADOPT503_LOADMAX overrides)'* ]]; }
check "S setup with the real leftover shapes present: not refused; leftovers listed as information; limit printed as half the CPUs" sh -c "grep -q '^running suites: 0' $F/S2setup.out && grep -q '^leftover test processes (information; never signalled; not a running suite): 2' $F/S2setup.out && grep -q 'waits for a quiet host .* every 30 s, up to 20 min' $F/S2setup.out"
check "S prints CPUs and a load limit of half of them (ADOPT503_LOADMAX unset)" half_cpus $F/S2setup.out
check "S setup exit 0" [ $SRC_ -eq 0 ]
check "503 S: the test venv's graftling is the B wheel's (site-packages, 0.5.2), the checkout has no src/graftling" sh -c "grep -q 'test venv graftling from the wheel: OK .*svenv-6115c724/lib/python3.13/site-packages/graftling/__init__.py 0.5.2' $F/S2setup.out && [ ! -e $FB/checkout-6115c724/src/graftling ]"
check "S: checkout at $NEW, test venv imports it, nested venv imports, pytest temp printed outside the Harness" sh -c "grep -q 'checkout $FB/checkout-6115c724 at $NEW (clean)' $F/S2setup.out && grep -q 'test venv imports the checkout: OK .*/tmp/503/checkout-6115c724/src/graphtraj/' $F/S2setup.out && grep -q 'nested venv imports: OK' $F/S2setup.out && grep -q 'pytest temp base TMPDIR=' $F/S2setup.out && ! grep -q '^STOP' $F/S2setup.out"
check "S: production dependencies linked into the test venv's own site-packages, never graphtraj/graftling" sh -c "ls $FB/sdeps | grep -q click && ! ls $FB/sdeps | grep -qE '^(graphtraj|graftling)' && [ -L \$(ls -d $FB/svenv-6115c724/lib/python*/site-packages)/click ]"

head1 "S refuses only while another S of ours runs (its _Srun job or its test venv's shard runner)"
print -l -- $HOSTLINE "8811 1 05:00 zsh $SD/steps.zsh _Srun" > $F/ps.txt
steps S > $F/S-ours.out 2>&1; SO=$?
check "S refused (our _Srun job), before any checkout" sh -c "[ $SO -ne 0 ] && grep -q 'STOP: another S of ours is running' $F/S-ours.out && ! grep -q 'fresh git checkout' $F/S-ours.out"
print -l -- $HOSTLINE "8812 1 05:00 $FB/svenv-6115c724/bin/python scripts/run_test_shards.py --shards 6" > $F/ps.txt
steps S > $F/S-ours2.out 2>&1; SO=$?
check "S refused (our test venv's shard runner)" sh -c "[ $SO -ne 0 ] && grep -q '^ours: 1' $F/S-ours2.out && grep -q 'STOP: another S of ours' $F/S-ours2.out"
# 499 (497 defect d): leftovers of S's own test venv (an installed-environment timer and a Worker an earlier S left)
# are listed as leftovers, never 'ours': S is not refused. A pytest of our venv still refuses.
print -l -- $HOSTLINE "8813 1 2:00:00 $FB/svenv-6115c724/bin/python -I -m graphtraj.execution.budget_idle_timer /x/sessions/1-a 0123abcd 5" \
  "8814 1 2:00:00 $FB/svenv-6115c724/bin/python -I -m graphtraj.execution.runner_worker /x/sessions/1-a/resume.yml" > $F/ps.txt
ADOPT503_S_NORUN=1 steps S > $F/S-left.out 2>&1; SO=$?
check "499 S not refused by our test venv's leftover timer and Worker (ours: 0; listed as leftovers)" sh -c "[ $SO -eq 0 ] && grep -q '^ours: 0' $F/S-left.out && grep -q '  leftover: 8813 .*budget_idle_timer' $F/S-left.out && grep -q '  leftover: 8814 .*runner_worker' $F/S-left.out && ! grep -q 'STOP: another S of ours' $F/S-left.out"
print -l -- $HOSTLINE "8815 1 00:30 $FB/svenv-6115c724/bin/python -m pytest -q tests/test_x.py" > $F/ps.txt
steps S > $F/S-ours3.out 2>&1; SO=$?
check "499 S refused by a pytest of our test venv (ours: 1)" sh -c "[ $SO -ne 0 ] && grep -q '^ours: 1' $F/S-ours3.out && grep -q 'STOP: another S of ours' $F/S-ours3.out"

head1 "S background quiet wait (_Srun, ADOPT503_S_DRYRUN: the suite itself is not run): high then low load starts; always high or a running suite STOPs"
QW=(ADOPT503_S_DRYRUN=1 ADOPT503_QUIET_STEP=1 ADOPT503_LOADMAX=4)
print -l -- $HOSTLINE "$LEFT1" "$LEFT2" > $F/ps.txt
print '{ 14.74 28.21 19.52 }' > $F/load.txt
( sleep 2.5; print '{ 1.10 9.00 12.00 }' > $F/load.txt ) &
env $QW ADOPT503_QUIET_SECONDS=20 zsh $SD/steps.zsh _Srun > $F/Sq-start.out 2>&1; SQ=$?; wait
cat $F/Sq-start.out
check "quiet wait: logged 'quiet check HH:MM:SS loadavg { 14.74 … } | running suites 0' while high, then '== quiet at … start'; leftovers listed; exit 0" sh -c "[ $SQ -eq 0 ] && grep -q '^quiet check [0-9:]* loadavg { 14.74 28.21 19.52 } | running suites 0' $F/Sq-start.out && grep -q '^quiet check [0-9:]* loadavg { 1.10 9.00 12.00 } | running suites 0' $F/Sq-start.out && grep -q '^== quiet at [0-9:]* start' $F/Sq-start.out && grep -q '^leftover test processes .*: 2' $F/Sq-start.out && grep -q '== DRYRUN' $F/Sq-start.out && grep -q 'load <= 4 ' $F/Sq-start.out"
print '{ 14.74 28.21 19.52 }' > $F/load.txt
env $QW ADOPT503_QUIET_SECONDS=2 zsh $SD/steps.zsh _Srun > $F/Sq-stop.out 2>&1; SQ=$?
cat $F/Sq-stop.out
check "quiet wait always high (limit shortened to 2 s): '== STOP not quiet within', exit non-zero, suite not started" sh -c "[ $SQ -ne 0 ] && grep -q '^== STOP not quiet within 0 min (2 s)' $F/Sq-stop.out && ! grep -q '== quiet at\|== DRYRUN\|== start' $F/Sq-stop.out && [ \$(grep -c '^quiet check' $F/Sq-stop.out) -ge 2 ]"
print '{ 0.50 0.50 0.50 }' > $F/load.txt
print -l -- $HOSTLINE "$BUSY1" "$BUSY2" > $F/ps.txt
env $QW ADOPT503_QUIET_SECONDS=2 zsh $SD/steps.zsh _Srun > $F/Sq-busy.out 2>&1; SQ=$?
check "quiet wait with another suite running at low load: 'running suites 2' listed, STOP" sh -c "[ $SQ -ne 0 ] && grep -q '^quiet check .* | running suites 2' $F/Sq-busy.out && grep -q '  running: 7272 ' $F/Sq-busy.out && grep -q '^== STOP not quiet within' $F/Sq-busy.out"
rm -f $F/load.txt; print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "S's labels on synthetic failures: ATTRIBUTED 488 race [3-True] and 492's 459 redaction test, one NEW; '== new failures: 1'"
zsh -c "source <(sed -n '/^ATTRIBUTED=(/,/^}/p' $SD/steps.zsh); ids=(tests/test_a.py::test_one 'tests/test_wait_handover_477.py::test_wait_and_push_racing_deliver_the_reply_exactly_once[3-True]' tests/test_tool_descendants_459.py::test_recorded_and_reported_command_lines_are_redacted 'tests/test_host_shutdown_stop.py::test_a_locked_parent_does_not_hide_or_hold_its_descendants[dsh]'); attributed=0; for id in \$ids; do label=\$(label_of \$id); if [[ \$label == ATTRIBUTED* ]]; then (( attributed++ )); print \"ATTRIBUTED \$id [\$label]\"; else print \"NEW \$id [\$label]\"; fi; done; print \"== new failures: \$(( \${#ids} - attributed ))\"" > $F/Slabel.out 2>&1
cat $F/Slabel.out
check "S labels: NEW test_one, ATTRIBUTED [3-True] (488), 459 redaction (492), host_shutdown [dsh] (491/495); '== new failures: 1'" sh -c "grep -q '^NEW tests/test_a.py::test_one \[unattributed\]' $F/Slabel.out && grep -q '^ATTRIBUTED .*3-True.*488 SUITE' $F/Slabel.out && grep -q '^ATTRIBUTED .*redacted.*492 adoption' $F/Slabel.out && grep -q '^ATTRIBUTED .*hold_its_descendants.*491 SUITE' $F/Slabel.out && grep -q '== new failures: 1' $F/Slabel.out"
check "S labels: the 477 race [6-True] (480/481 only) is NEW now" sh -c "zsh -c \"source <(sed -n '/^ATTRIBUTED=(/,/^}/p' $SD/steps.zsh); label_of 'x::test_wait_and_push_racing_deliver_the_reply_exactly_once[6-True]'\" | grep -q unattributed"
rm -rf $RW/S-shards

head1 "S2 counts leftovers of a finished suite (synthetic suite output; ps -E stub), never signals"
print 3 > $W/S-basetemp-before-6115c724
PR=$(env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=${TMPDIR:-/private/tmp} $CONDA -I -c 'import tempfile; print(tempfile.gettempdir())')/pytest-of-${USER:-luoxiao}
print -l "test run id: abcdef0123456789 (shard n carries PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-<n>)" "== DONE 12:00:00" > $RW/S-suite.txt
print -l -- $HOSTLINE $TIMERLINE "8181 1 1:00 /usr/bin/python3 -m graphtraj.execution.budget_idle_timer x PYTEST_GRAPHTRAJ_RUN=abcdef0123456789-2 HOME=/h" \
  "8282 1 1:00 $FB/svenv-6115c724/bin/python fake_runtime.py" "8383 1 1:00 sleep 99 PWD=$PR/pytest-1/old" > $F/ps.txt
steps S2 > $F/S2.out 2>&1; check "S2 exit 0" [ $? -eq 0 ]; grep -E '^(run id|leftover|  [0-9])' $F/S2.out
check "S2 counted 2 (run marker, suite venv under tmp/499; not an older basetemp)" grep -q 'leftover processes of the suite (never signalled): 2' $F/S2.out
print -l -- $HOSTLINE $TIMERLINE > $F/ps.txt

head1 "I waits while a Task 466 member Worker and Main's host run, then passes with only the old timers left"
print -l -- $HOSTLINE $TIMERLINE $WORKERLINE > $F/ps.txt
( sleep 3; print -l -- $TIMERLINE "5252 5151 $FRT/bin/python <defunct>" > $F/ps.txt.new; mv $F/ps.txt.new $F/ps.txt
  sleep 8; print -l -- $TIMERLINE > $F/ps.txt.new; mv $F/ps.txt.new $F/ps.txt ) &
REMOVER=$!
print | steps I > $F/I.out 2>&1; IRC=$?
wait $REMOVER
check "I exit 0" [ $IRC -eq 0 ]
check "I waited and named the active Tasks (466、470 / 466, 470), no kill, Ctrl-C safe, Chinese and English" sh -c "grep -q '正在等待：可能有成员在运行的 Task（466、470）' $F/I.out && grep -q 'Waiting for members of Tasks that may run now (466, 470)' $F/I.out && grep -q 'Do not kill them' $F/I.out && grep -q 'Ctrl-C 可以安全放弃' $F/I.out"
check "I listed the Worker as BLOCKING with its Task" grep -q '\[member Worker of Task 466 ' $F/I.out
check "I never listed a timer as BLOCKING" sh -c "! grep -q '\] 5151 \|\] 7777 ' $F/I.out"
check "I: timers listed before the backup, right before pip and after the install (old class after it); zombie child never BLOCKING" sh -c "[ \$(grep -c 'guard: budget_idle_timer processes: 2' $F/I.out) -ge 3 ] && grep -q 'timer pid 5151 .*\[old\] exe production .venv-runtime' $F/I.out && ! grep -q '\] 5252 ' $F/I.out && [ \$(grep -c 'guard: BLOCKING 0' $F/I.out) -ge 2 ]"
check "I: install window recorded (start <= end)" sh -c "[ \$(cat $RW/I-install-start.epoch) -le \$(cat $RW/I-install-end.epoch) ]"
check "I: control records snapshot I.json right before pip" sh -c "grep -q 'control records snapshot I.json' $F/I.out && test -f $RW/ctl/I.json"
check "I: the 497 import lines (488, 490, 494, 495)" sh -c "grep -q '^488 _worker_arguments _worker_arguments | _process_ended _process_ended' $F/I.out && grep -q '^490 _work_ended _work_ended | _collect_ended_children _collect_ended_children | SLICE_SECONDS 5.0 | cleanup uses process_is_zombie: True' $F/I.out && grep -q '^494 Claude host receiver defers_push: True | hold thread started in the lock: True' $F/I.out && grep -q '^495 argv refreshed each sample: True' $F/I.out"
check "I: the 492 import lines (481, 484, 486, 485, 480, 487)" sh -c "grep -q '^481 main_entry main_patch main_patch | 484 _push_error _push_error' $F/I.out && grep -q '^486 stop_owned_agents stop_owned_agents | _terminated _terminated' $F/I.out && grep -q '^485 finalize imports CHECKER_PERMISSION_PROFILE: False | 480 member_policy write_paths: True' $F/I.out && grep -q '^487 wait timeout pops its waiter: True' $F/I.out"
grep -E '正在等待|Waiting for|BLOCKING|^-rw|^PASS|^FAIL|Successfully|SAME-AS|markers expected|plugin bytes|^4[89][0-9] |timer pid|bytes unchanged|^changed|claude --continue' $F/I.out | uniq
check "proddiff PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $RW/I-verify.txt
check "I: markers present in the installed site-packages (8/8)" grep -q 'markers expected present: PASS (7/7)' $F/I.out
check "I: the 464, 465, 469, 478 import lines still print from .venv-runtime" sh -c "grep -q '^457 _stop_escaped | 459 SAMPLE_SECONDS 1.0' $F/I.out && grep -q '^465 Claude member settings call project_history_files: False' $F/I.out && grep -q '^469 UnknownTask _load_task_state _RegisteredTaskNames' $F/I.out && grep -q '^477 take_push take_push | _waited _waited' $F/I.out"
check "I: plugin bytes as before (no trust dialog)" grep -q 'plugin bytes as before the install: no trust dialog expected' $F/I.out
check "I: pip replaced graftling 0.5.0 with 0.5.2 (no leftover dist-info: proddiff PASS covers LEFTOVER-DIST-INFO)" sh -c "grep -q 'Successfully installed graftling-0.5.2 graphtraj-0.1.0' $F/I.out && ! grep -q LEFTOVER $RW/I-verify.txt && [ ! -e $FRT/lib/python3.13/site-packages/graftling-0.5.0.dist-info ]"
check "I: '395 layout' line (version 0.5.2, one distribution, beside graphtraj, graftling.mjs, requires >=0.5.2)" grep -q "^395 layout graftling 0.5.2 | distributions 1 | beside graphtraj: True | graftling.mjs: True | graphtraj requires \['graftling<0.6,>=0.5.2'\]" $F/I.out
check "I: one graftling in production from the wheel (503 layout: PASS) and node resolves both to production's sibling" sh -c "grep -q '^503 layout: PASS (0 failed)' $F/I.out && [ \$(grep -c 'node resolves .* to the sibling $FRT/lib/python3.13/site-packages/graftling/: PASS' $F/I.out) -ge 2 ] && ! grep -q 'node resolves .*: FAIL' $F/I.out"
check "backup entry copies are all -rw-------" sh -c "[ \$(ls -A $FB/backup/entries | wc -l) -eq 3 ] && ! stat -f '%Sp' $FB/backup/entries/.[!.]* $FB/backup/entries/* 2>/dev/null | grep -qv -- '-rw-------'"
check "backup is under tmp/499 and its tools include nr499.py, timers497.py, markers.py" test -f $FB/backup/tools/nr499.py -a -f $FB/backup/tools/timers497.py -a -f $FB/backup/tools/markers.py
check "I printed claude --continue" grep -q "cd $FH && claude --continue" $F/I.out

head1 "Nt (490): Task 503 Session timers after the install; present/absent per recorded timer; negatives"
ADV=503-production_adoption_graftling_split-handover0-advisor@advisor; LEAD=503-production_adoption_graftling_split-handover0-team_leader@team_leader
mkdir -p $SESSIONS/$ADV $SESSIONS/$LEAD
print -l 'token: feedbeeffeedbeef' 'pid: null' > $SESSIONS/$ADV/budget-timer.yml
print -l 'token: 1eade71eade7' 'pid: null' > $SESSIONS/$LEAD/budget-timer.yml
IEND=$(<$RW/I-install-end.epoch)
NEWT_CMD="$FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $SESSIONS/$ADV feedbeeffeedbeef 9090"
OLD497_CMD="$FRT/bin/python -I -m graphtraj.execution.budget_idle_timer $SESSIONS/$LEAD 1eade71eade7 9191"
# Negative first (own record file): only a pre-install timer of a 503 Session -> FAIL.
print -l -- "6464 1 S $(lst $T_OLD) $OLD497_CMD" > $F/nt-neg-ps.txt
$CONDA -I $SD/timers497.py nt $F/nt-neg-ps.txt $FRT $(<$RW/I-install-start.epoch) $IEND $SESSIONS 503 $F/nt-neg.json > $F/nt-neg.out 2>&1; NN=$?
cat $F/nt-neg.out
check "Nt negative: only an old timer of a 503 Session gives FAIL (exit 1)" sh -c "[ $NN -ne 0 ] && grep -q 'CHECK 490 a timer started by the new version .*: FAIL (0 new of 1 recorded' $F/nt-neg.out && grep -q 'timer pid 6464: present | start .* \[old\]' $F/nt-neg.out"
$CONDA -I $SD/timers497.py nt $F/nt-neg-ps.txt $FRT x x $SESSIONS 503 $F/nt-neg2.json > $F/nt-nowin.out 2>&1
check "Nt negative: no install window gives BLOCKED" grep -q 'CHECK 490 .*: BLOCKED (no install window' $F/nt-nowin.out
print -l -- "5151 1 S $(lst $T_OLD) $OLDT_CMD" "6464 1 S $(lst $T_OLD) $OLD497_CMD" "6363 1 S $(lst $(( IEND + 30 ))) $NEWT_CMD" "6565 6363 Z $(lst $(( IEND + 40 ))) <defunct>" > $F/pstimer.txt
steps Nt > $F/Nt.out 2>&1; NTRC=$?; cat $RW/Nt.txt
check "Nt positive: the new timer 6363 (after the install, production exe, current token) present; PASS" sh -c "[ $NTRC -eq 0 ] && grep -q 'Task 503 timer pid 6363: present | start .* \[new\] | production .venv-runtime | $ADV | token is the Session.s current one: True' $RW/Nt.txt && grep -q 'CHECK 490 a timer started by the new version for a Task 503 Session is listed .*: PASS (1 new of 2 recorded' $RW/Nt.txt"
check "Nt: the 451 timer (not a Task 503 Session) is not recorded" sh -c "! grep -q 'Task 503 timer pid 5151' $RW/Nt.txt"
print -l -- "5151 1 S $(lst $T_OLD) $OLDT_CMD" "6464 1 S $(lst $T_OLD) $OLD497_CMD" > $F/pstimer.txt
steps Nt > $F/Nt2.out 2>&1; tail -6 $RW/Nt.txt
check "Nt rerun after the member's retire: 6363 recorded as absent, the old 6464 still present, CHECK still PASS" sh -c "[ \$(grep -c 'Task 503 timer pid 6363: absent' $RW/Nt.txt) -eq 1 ] && grep -q 'Task 503 timer pid 6464: present' $RW/Nt.txt && [ \$(grep -c 'CHECK 490 a timer started .*: PASS' $RW/Nt.txt) -eq 2 ]"

head1 "T (490): after the Task end, every new-version timer of a 503 Session gone, no budget notice after the end; old ones not judged"
TY=$ST/$TASK/task.yml
sed 's/^status: .*/status: active/' $WT/.state/task.yml > $TY
steps T > $F/T-pend.out 2>&1
check "T before the Task end: PENDING, no end time recorded" sh -c "grep -q 'CHECK 490 every new-version timer .*: PENDING (status active' $RW/T.txt && [ ! -e $RW/T-end.epoch ]"
sed 's/^status: .*/status: awaiting-integration/' $WT/.state/task.yml > $TY
cat > $W:h/execution-budget.yml <<EOF3
stopped: false
parent_notices:
- key: elapsed_minutes:120
  delivered: true
  observer: $LEAD
  event: {occurred_at: '$(date -r $(( IEND - 600 )) '+%Y-%m-%dT%H:%M:%S%z' | sed 's/\(..\)$/:\1/')'}
EOF3
: > $RW/T.txt
steps T > $F/T.out 2>&1; TRC=$?; cat $RW/T.txt | head -30
check "T positive: end time recorded once from task.yml; 6363 gone; old 6464 listed, not judged; no notice after the end; exit 0" sh -c "[ $TRC -eq 0 ] && grep -q 'end time recorded from task.yml mtime at status awaiting-integration' $RW/T.txt && grep -q 'new-version timer pid 6363 ($ADV): gone' $RW/T.txt && grep -q 'old/not judged: timer pid 6464' $RW/T.txt && grep -q 'CHECK 490 every new-version timer of a Task 503 Session is gone after the Task end: PASS' $RW/T.txt && grep -q 'CHECK 490 no budget notice for Task 503 Sessions after the end: PASS' $RW/T.txt"
# Negative: the new timer still runs 100 s after the end, and a notice after the end was delivered.
print $(( $(date +%s) - 100 )) > $RW/T-end.epoch
print -l -- "6363 1 S $(lst $(( IEND + 30 ))) $NEWT_CMD" > $F/pstimer.txt
cat >> $W:h/execution-budget.yml <<EOF3
- key: additional_allowance:5
  delivered: true
  observer: $ADV
  event: {occurred_at: '$(date '+%Y-%m-%dT%H:%M:%S%z' | sed 's/\(..\)$/:\1/')'}
EOF3
: > $RW/T.txt
steps T > $F/T-neg.out 2>&1; TRC=$?; grep -E 'CHECK|PRESENT|after the end' $RW/T.txt
check "T negative: a new timer still PRESENT 100 s after the end FAIL; a delivered notice after the end FAIL; exit non-zero" sh -c "[ $TRC -ne 0 ] && grep -q 'new-version timer pid 6363 ($ADV): PRESENT' $RW/T.txt && grep -q 'CHECK 490 every new-version timer .*: FAIL (1 of 1 still present)' $RW/T.txt && grep -q 'CHECK 490 no budget notice for Task 503 Sessions after the end: FAIL (1 after the end, 1 delivered)' $RW/T.txt"
print $(( $(date +%s) - 5 )) > $RW/T-end.epoch; : > $RW/T.txt
steps T > $F/T-recent.out 2>&1
check "T within 30 s of the end with the timer still there: PENDING with a rerun hint (no foreground wait)" grep -q 'CHECK 490 every new-version timer .*: PENDING (1 of 1 still present; the end was < 30 s ago: rerun T in 30 s)' $RW/T.txt
sed 's/^status: .*/status: active/' $WT/.state/task.yml > $TY; rm -f $RW/T-end.epoch
print -l -- "5151 1 S $(lst $T_OLD) $OLDT_CMD" "5252 5151 Z $(lst $T_OLD) <defunct>" > $F/pstimer.txt
steps timers > $F/timers.out 2>&1
check "timers step: lists the old timer with class [old] after the install" grep -q 'timer pid 5151 .*\[old\] exe production .venv-runtime' $F/timers.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version|continue' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
check "after R the 497 markers are absent again" $CONDA -I $SD/markers.py $FRT/lib/python3.13/site-packages absent

head1 "Mpre / Mps (486): host from .venv-runtime under claude --continue, no graphtraj-mcp under Main, executions across the restart"
A=$FH/.graphtraj/swarm/control/agents; mkdir -p $A
print -r -- '{"agent":"r1","name":"other","parent":"470-z-member","retired_at":null,"executions":[{"id":"x1","state":"running","notification":"pending","process":{"worker_pid":4321}}]}' > $A/r1.json
steps Mpre > $F/Mpre.out 2>&1; check "Mpre snapshot written" sh -c "grep -q 'control records snapshot Mpre.json: agents=1 executions=1' $F/Mpre.out && grep -q 'USER（Main 已 /exit）: zsh .*steps.zsh I' $F/Mpre.out"
print -r -- '{"agent":"r1","name":"other","parent":"470-z-member","retired_at":null,"executions":[{"id":"x1","state":"ended","outcome":"completed","notification":"delivered","process":{"worker_pid":4321}}]}' > $A/r1.json
print -l -- $HOSTLINE > $F/ps.txt; mkdir -p $FH/.graphtraj/claude-host; print "x outcome=ok" >> $FH/.graphtraj/claude-host/host.log
steps Mps > $F/Mps.out 2>&1; grep -E '^(host uses|parent|claude:|486|CHECK|  x)|^  r1' $F/Mps.out
check "Mps: parent is claude --continue ... yes" grep -q 'parent is claude --continue or --resume .*: yes' $F/Mps.out
check "Mps: 486 host from .venv-runtime, no graphtraj-mcp under Main, no interrupted end" sh -c "grep -q '486 Main tool host: graphtraj-claude-host from .venv-runtime: yes' $F/Mps.out && grep -q 'CHECK 486 no graphtraj-mcp server under the Claude Main .*: PASS' $F/Mps.out && grep -q 'CHECK 486 no execution ended interrupted across the Main restart: PASS' $F/Mps.out"
rm -f $A/r1.json; print -l -- $HOSTLINE > $F/ps.txt

head1 "Nw: the read-only watcher copies the descendants record while the child runs, then ends by itself"
ND=$FH/.graphtraj/swarm/native/c1; mkdir -p $A $ND
SC1=$ND/tool-descendants-n1.json SC2=$ND/tool-descendants-n2.json
TOOLENTRY=$($CONDA -I -c "import sys, json, subprocess; sys.path.insert(0, '$W/gsrc-0.5.2/src'); from graftling.tool_descendants import identity
p = subprocess.Popen(['/bin/sleep', '1']); i = identity(p.pid); p.wait()
print(json.dumps({'pid': i.pid, 'ppid': i.ppid, 'pgid': i.pgid, 'uid': i.uid, 'start': i.start, 'argv': '/bin/zsh -c -l source snapshot && eval \"echo n503-tool && sleep 3\"'}))")
print -r -- '{"version":1,"runtime_pid":1,"entries":['$TOOLENTRY']}' > $SC1
print -r -- '{"agent":"c1","name":"n503","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"running","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json
rm -f $RW/Nw.txt
steps Nw > $F/Nw.out 2>&1; check "Nw exit 0 and started in the background" grep -q 'started at' $F/Nw.out
sleep 1
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1; print -r -- '{"version":1,"runtime_pid":2,"entries":[]}' > $SC2
print -r -- '{"agent":"c1","name":"n503","session":"sess-c","parent":"x","retired_at":null,"executions":[{"id":"e1","state":"ended","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}},{"id":"e2","state":"ended","process":{"tool_marker":"m-secret-marker-2","tool_descendants":"'$SC2'"}}]}' > $A/c1.json
for i in {1..50}; do grep -q '== END' $RW/Nw.txt 2>/dev/null && break; sleep 0.2; done
check "Nw ended by itself when every execution ended" grep -q '== END (every execution ended)' $RW/Nw.txt
for i in {1..30}; do grep -q '== END 468' $RW/Nw468.txt 2>/dev/null && break; sleep 0.2; done
check "Nw's 468 sampler started and ended by itself (bounded)" grep -q '== END 468 sampler' $RW/Nw468.txt
check "Nw snapshot kept the Bash tool command" grep -q 'n503-tool' $RW/Nw-snapshots.jsonl
check "Nw never copied the marker value" sh -c "! grep -q 'm-secret-marker' $RW/Nw-snapshots.jsonl $RW/Nw.txt"
print -l 'session_id: x' 'execution_id: n1' 'escaped_processes:' '  found: []' '  stopped: []' '  remaining: []' > $ND/claude-termination-n1.yml
print -l 'session_id: x' 'execution_id: n2' 'escaped_processes: null' > $ND/claude-termination-n2.yml

head1 "Nr positive: 494 (wait once, no deferred push, one Main notice), 495 (459 record, 466 masking) and 478/492's checks"
AL=$ADV
MS=$SESSIONS/$AL; SS=$FH/.graphtraj/swarm/sessions; mkdir -p $SS $MS
CHILDREC() { print -r -- '{"agent":"c1","name":"n503","session":"'$1'","parent":"'$AL'","selection":{"preset":null,"configuration":'$2',"model":'$3',"reasoning_effort":null},"retired_at":"x","executions":[{"id":"e1","session":"sess-c","state":"ended","outcome":"'$4'",'$5'"notification":"delivered","process":{"tool_marker":"m-secret-marker","tool_descendants":"'$SC1'"}}]}' > $A/c1.json; }
CHILDREC claude:sess-c '"opus_coding_team.advisor"' '"claude-opus-5-5"' completed ''
print -l 'session: claude:sess-m' 'task_id: "503"' 'role: advisor' 'execution_id: m1' > $MS/mapping.yml
print -l 'execution_id: m1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
print -l 'settings:' '  permissions:' '    allow: [Read]' '    deny: []' '    additionalDirectories: [/x/state]' '  sandbox:' '    filesystem:' '      allowRead: [/x/state, /x/docs]' '      denyRead: ['$HOME'/.claude]' '      allowWrite: []' '      denyWrite: []' > $MS/claude-settings.yml
$CONDA -I $SD/rehearse_fixtures.py $SS positive
print "{\"launch_status\":\"launched\",\"agent\":\"agent-497-adv-xyz\",\"alias\":\"$AL\"}" > $RW/N.txt
# 499 (497 defect b): Main's header line names 'completed' too; only the notice's own shape counts (expect 1).
NOTICE="[Graftling notice from $AL · completed · execution e01fe5e5f0e64286a614b789f63acc33] Session execution ended: {\"outcome\": \"completed\"}"
print -l "# Every notice of $AL that Main received (one per line). Exactly one completed notice was received." "$NOTICE" > $RW/N-main-notice.txt
$CONDA -I $SD/rehearse498.py $RW $ND positive
print -l '{"agent":"c1","name":"n503","configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'SESSION-READ-503 session=claude:sess-c events=30' 'member-bash-ok' > $RW/N-reply.txt
print -l '{"at": 1000, "child_running": true, "ps": "9191 1 3.0 0:10.00 02:00 python -m graphtraj.execution.runner_worker x"}' \
         '{"at": 1120, "child_running": true, "ps": "9191 1 3.0 0:22.00 04:00 python -m graphtraj.execution.runner_worker x"}' \
         '{"at": 1130, "child_running": false, "ps": "9191 1 9.0 0:40.00 04:10 python -m graphtraj.execution.runner_worker x"}' > $RW/Nw468-ps.txt
print -l -- $HOSTLINE > $F/ps.txt
steps Nr > $F/Nr.out 2>&1; NRC=$?; grep -E '^claude:|^child|CHECK|BLOCKED|^member|^494' $F/Nr.out
check "Nr exit 0 and no CHECK line is FAIL, BY HAND, PENDING, BLOCKED or NOT OBSERVED" sh -c "[ $NRC -eq 0 ] && ! grep '^CHECK' $RW/Nr.txt | grep -qE 'FAIL|BY HAND|PENDING|NOT OBSERVED|BLOCKED' && ! grep -q '^BLOCKED' $RW/Nr.txt"
check "Nr: 494 labels on 487/477 checks PASS" sh -c "grep -q 'CHECK 494 (487) first wait timed out while the child ran .*: PASS' $RW/Nr.txt && grep -q 'CHECK 494 (487) reply delivered once (DONE-503 .*: PASS' $RW/Nr.txt && grep -q 'CHECK 494 (477) child end not pushed .*: PASS' $RW/Nr.txt"
check "Nr: 494 control fields: delivered, no push_deferred/push_holder; one Main completed notice" sh -c "grep -q 'CHECK 494 child n503 ended execution has notification delivered: PASS' $RW/Nr.txt && grep -q 'CHECK 494 child n503 ended execution keeps no push_deferred/push_holder: PASS' $RW/Nr.txt && grep -q 'CHECK 494 Main got exactly one completed notice of the member: PASS (1 notice lines' $RW/Nr.txt"
check "Nr: 495 labels: 459 record lists the Bash command, 466 credential masked PASS; value never printed" sh -c "grep -q 'CHECK 495 (459) descendants record lists the Bash tool command: PASS' $RW/Nr.txt && grep -q 'CHECK 495 (466) credential masked .*: PASS' $RW/Nr.txt && ! grep -q 'probe503fakevalue' $RW/Nr.txt $F/Nr.out"
check "Nr: 459 child Bash started, 465, member Bash, 455, 452, 466 reads, 486 PASS" sh -c "grep -q 'CHECK 459 child Bash started (record lists the command): PASS' $RW/Nr.txt && grep -q 'CHECK 465 member claude-settings has no per-session-file grants: PASS' $RW/Nr.txt && grep -q 'CHECK member Bash started: PASS' $RW/Nr.txt && grep -q 'CHECK 455 stored record: configuration and model not null: PASS' $RW/Nr.txt && grep -q 'CHECK 466 default read = last 5: PASS' $RW/Nr.txt && grep -q 'CHECK 486 member end normal (execution.yml outcome completed): PASS' $RW/Nr.txt"
check "Nr: next is Nt after retire, then N484; retire prompt uses the swarm agent" sh -c "grep -q 'zsh $SD/steps.zsh Nt' $F/Nr.out && grep -q 'retire with {\"agent\":\"agent-497-adv-xyz\"}' $F/Nr.out"
check "Nr: marker value never printed" sh -c "! grep -q 'm-secret-marker' $RW/Nr.txt $F/Nr.out"

head1 "Nr negative 494: push_deferred/push_holder left on the ended child execution, notification queued, two Main notices"
CHILDREC claude:sess-c '"opus_coding_team.advisor"' '"claude-opus-5-5"' completed '"push_deferred":true,"push_holder":4242,'
print -l "# header: Main's note, not a notice" "$NOTICE" "$NOTICE" > $RW/N-main-notice.txt
steps Nr > $F/Nr494.out 2>&1; NRC=$?; grep -E '^CHECK 494' $RW/Nr.txt
check "Nr negative 494 exits non-zero: push fields FAIL, two notices FAIL" sh -c "[ $NRC -ne 0 ] && grep -q 'CHECK 494 child n503 ended execution keeps no push_deferred/push_holder: FAIL (1 with a field left)' $RW/Nr.txt && grep -q 'CHECK 494 Main got exactly one completed notice of the member: FAIL (2 notice lines' $RW/Nr.txt"
print -r -- '{"c1":{"name":"n503","parent":"x","retired":false,"executions":{"e1":{"state":"ended","notification":"queued","push_deferred":false,"push_holder":false}}}}' > $F/n494-q.json
$CONDA -I $SD/ctl497.py n494 $F/n494-q.json n503 > $F/n494-q.out 2>&1; check "ctl497 n494: notification not delivered FAIL" grep -q 'CHECK 494 child n503 ended execution has notification delivered: FAIL' $F/n494-q.out
print -r -- '{"c1":{"name":"n503","parent":"x","retired":false,"executions":{"e1":{"state":"running","notification":null}}}}' > $F/n494-r.json
$CONDA -I $SD/ctl497.py n494 $F/n494-r.json n503 > $F/n494-r.out 2>&1; check "ctl497 n494: child still running gives PENDING" grep -q 'CHECK 494 child n503 ended execution has notification delivered: PENDING' $F/n494-r.out
CHILDREC claude:sess-c '"opus_coding_team.advisor"' '"claude-opus-5-5"' completed ''
print -r -- "$NOTICE" > $RW/N-main-notice.txt

head1 "Nr negative 466/495: default last 4, no page back, keyword hit at the end, the fake key unredacted in results"
$CONDA -I $SD/rehearse_fixtures.py $SS bad466
steps Nr > $F/Nr466.out 2>&1; NRC=$?; grep -E '^CHECK 46|^CHECK 495' $RW/Nr.txt
check "Nr negative 466 exits non-zero; 495 (466) masking FAIL; value never printed" sh -c "[ $NRC -ne 0 ] && grep -q 'CHECK 466 default read = last 5: FAIL' $RW/Nr.txt && grep -q 'CHECK 495 (466) credential masked .*: FAIL' $RW/Nr.txt && ! grep -q 'probe503fakevalue' $RW/Nr.txt"

head1 "Nr negative 494/477: wait/status last_message null and the child's end pushed to the member after wait"
$CONDA -I $SD/rehearse_fixtures.py $SS bad477
steps Nr > $F/Nr477.out 2>&1; NRC=$?; grep -E '^CHECK (477|494)' $RW/Nr.txt
check "Nr negative 477 exits non-zero; 494 (477) pushed FAIL; 494 (487) reply once FAIL" sh -c "[ $NRC -ne 0 ] && grep -q 'CHECK 477 wait last_message .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 494 (477) child end not pushed .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 494 (487) reply delivered once .*: FAIL' $RW/Nr.txt"

head1 "Nr negative 494/487: the first wait already returned the end (no timed_out) and the end was also pushed"
$CONDA -I $SD/rehearse_fixtures.py $SS bad487
steps Nr > $F/Nr487.out 2>&1; NRC=$?; grep -E '^CHECK 494' $RW/Nr.txt
check "Nr negative 487 exits non-zero; first wait FAIL, reply once FAIL" sh -c "[ $NRC -ne 0 ] && grep -q 'CHECK 494 (487) first wait timed out while the child ran .*: FAIL' $RW/Nr.txt && grep -q 'CHECK 494 (487) reply delivered once .*: FAIL (wait/status results with DONE-503: 3; pushed inputs 1)' $RW/Nr.txt"

head1 "Nr negative 495/459: no Bash tool process ever recorded (E2BIG), member Bash failed"
$CONDA -I $SD/rehearse_fixtures.py $SS e2big
print -r -- '{"version":1,"runtime_pid":1,"entries":[]}' > $SC1
print -r -- '{"at":1,"agent":"c1","execution":"e1","sidecar":"'$SC1'","record":{"version":1,"runtime_pid":1,"entries":[]}}' > $RW/Nw-snapshots.jsonl
print -l '{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5"}' 'The child Bash failed: Error: spawn /bin/zsh E2BIG' > $RW/N-reply.txt
steps Nr > $F/NrB.out 2>&1; NRC=$?; grep -E '^CHECK.*FAIL|^BLOCKED' $RW/Nr.txt
check "Nr negative 495/459 exits non-zero; 495 (459) record FAIL; child Bash BLOCKED with E2BIG" sh -c "[ $NRC -ne 0 ] && grep -q 'CHECK 495 (459) descendants record lists the Bash tool command: FAIL' $RW/Nr.txt && grep -q '^BLOCKED: 459 child Bash started not observed - .*E2BIG' $RW/Nr.txt"

head1 "N484 (484): notification fields against I's snapshot"
$CONDA -I $SD/rehearse_fixtures.py $SS positive
steps N484 > $F/N484.out 2>&1; N4=$?; grep -E '^CHECK|^484|  new' $F/N484.out
check "N484 exit 0 and three CHECK 484 PASS" sh -c "[ $N4 -eq 0 ] && [ \$(grep -c '^CHECK 484 .*: PASS' $RW/N484.txt) -eq 3 ]"

head1 "M / N print real values"
steps M > $F/M.out; check "M names the active Tasks and says other Tasks' ends may arrive once and must not repeat" sh -c "grep -q '其它 Task（466, 470）' $F/M.out && grep -q \"Ends of other Tasks' members during the exit may arrive once; they must not repeat.\" $F/M.out"
steps N > $F/N.out
check "N prompt: Task 503, preset role, n503, KW503-ORCHID early, split fake key, DONE-503, sk-probe503 asked yes/no" sh -c "grep -q '\"task_id\":\"503\"' $F/N.out && grep -q 'named n503 with configuration opus_coding_team.advisor' $F/N.out && grep -q \"Step 02: write the sentence 'Now step 02, marker KW503-ORCHID.'\" $F/N.out && grep -qF \"echo api_key=sk-probe503fake''value0000\" $F/N.out && ! grep -q 'probe503fakevalue' $F/N.out && grep -q 'reply with exactly: DONE-503' $F/N.out && grep -q 'substring sk-probe503 appears' $F/N.out && ! grep -q '492' $F/N.out"
check "N prompt: 43 steps, one seq per step" [ $(grep -o "seq -f '503-[0-9][0-9]-%g' 1 400" $F/N.out | wc -l) -eq 41 ]
check "N prompt: first short wait (timed_out), repeated wait, status, five session_read calls, SESSION-READ-503, member Bash, retire; next is Nt" sh -c "grep -q 'call agents wait with arguments {agent: <agent id>, timeout_seconds: 5}' $F/N.out && grep -q 'it must show timed_out true' $F/N.out && grep -q 'SESSION-READ-503 session=' $F/N.out && grep -q 'echo member-bash-ok' $F/N.out && grep -q 'Retire the child by its agent id' $F/N.out && grep -q 'zsh $SD/steps.zsh Nt' $F/N.out && grep -q 'completed 必须恰好一条' $F/N.out"

check "503 N: the notice header and body are saved on one line (499 lesson c)" grep -q '每条通知的通知头与正文写在同一行' $F/N.out
check "503 Nr: 468 is printed as REPORT (Task 501), never a CHECK" sh -c "grep -q '^REPORT 468 (Task 501; not blocking)' $RW/Nr.txt && ! grep -q '^CHECK 468' $RW/Nr.txt"

head1 "P / Pr (Pi and DSH children of Main): prompts, positive, NOT OBSERVED, 'cannot find' text FAIL"
rm -f $RW/P-*.txt $RW/Pr.done $RW/S-suite.txt
steps P > $F/P.out 2>&1; PRC=$?
check "P prints both create prompts with runtime, configuration, name, one tool call (DSH arguments {}), replies DONE-503-PI/DSH; next is Pr" sh -c "[ $PRC -eq 0 ] && grep -qF '{\"runtime\":\"pi\",\"configuration\":\"pi_dsh_trial.team_leader\",\"name\":\"p503\"' $F/P.out && grep -qF '{\"runtime\":\"dsh\",\"configuration\":\"pi_dsh_trial.engineer\",\"name\":\"d503\"' $F/P.out && grep -qF 'arguments\\\":{}' $F/P.out && grep -q 'DONE-503-PI' $F/P.out && grep -q 'DONE-503-DSH' $F/P.out && grep -q \"zsh $SD/steps.zsh Pr\" $F/P.out && [ -e $RW/P.started ]"
print '== quiet at 1 start' > $RW/S-suite.txt
steps P > $F/P-S.out 2>&1; PRC=$?
check "P refuses while S runs (no '== DONE')" sh -c "[ $PRC -ne 0 ] && grep -q 'STOP: S 正在运行' $F/P-S.out"
rm -f $RW/S-suite.txt
A=$FH/.graphtraj/swarm/control/agents; mkdir -p $A $FH/.graphtraj/swarm/sessions/sp $FH/.graphtraj/swarm/sessions/sd
print -r -- '{"agent":"ap1","name":"p503","runtime":"pi","session":"pi:sess-p","selection":{"configuration":"pi_dsh_trial.team_leader","model":"deepseek-flash"},"executions":[{"id":"ep1","state":"ended","outcome":"completed","notification":"delivered"}]}' > $A/ap1.json
print -rl '{"type":"header","id":"pi:sess-p","execution":"ep1"}' '{"type":"assistant/message","data":{"content":[{"type":"tool_use","id":"t1","name":"tasks","input":{"action":"execute","feature":"task_graph"}}]}}' '{"type":"user/message","data":{"content":[{"type":"tool_result","tool_use_id":"t1","name":"tasks","content":"{\"task_id\":\"503\"}"}]}}' > $FH/.graphtraj/swarm/sessions/sp/session.jsonl
print -r -- '{"agent":"ap1","execution":"ep1"}' > $RW/P-pi-create.txt; print 'DONE-503-PI task_id=503 status=implementing model=deepseek-flash' > $RW/P-pi-reply.txt
print -r -- '{"error":"runtime dsh could not start: dsh: command not found"}' > $RW/P-dsh-create.txt
print -l -- $HOSTLINE "8701 8700 0:10 $FRT/bin/graphtraj-session pi --collect" > $F/ps.txt
steps Pr > $F/Pr.out 2>&1; PRC=$?; grep -E '^(CHECK 503|503 )' $F/Pr.out
check "Pr positive (pi): created, ended completed, tool call and result in the archive, reply with field, no 'cannot find', process from .venv-runtime -> '503 pi: PASS'" sh -c "grep -q '^503 pi: PASS' $F/Pr.out && grep -q 'CHECK 503 pi GraphTraj processes run from .venv-runtime: PASS (1 listed, 0 not under' $F/Pr.out && grep -q 'CHECK 503 pi GraphTraj tool call made and answered (archive): PASS' $F/Pr.out"
check "Pr NOT OBSERVED (dsh could not start): reason quoted, exit 0, Pr.done written, retire prompt for the Pi child, next is S" sh -c "[ $PRC -eq 0 ] && grep -q '^503 dsh: NOT OBSERVED' $F/Pr.out && grep -q 'no d503 record; the host did not start; create result: {\"error\":\"runtime dsh could not start' $F/Pr.out && [ -e $RW/Pr.done ] && grep -qF 'retire with {\"agent\":\"ap1\"}' $F/Pr.out && grep -q \"zsh $SD/steps.zsh S \" $F/Pr.out"
print -r -- '{"agent":"ad1","name":"d503","runtime":"dsh","session":"dsh:sess-d","selection":{"configuration":"pi_dsh_trial.engineer","model":"deepseek-flash"},"executions":[{"id":"ed1","state":"ended","outcome":"completed","notification":"delivered"}]}' > $A/ad1.json
print -r -- 'DONE-503-DSH ERROR Error: GraphTraj cannot find the installed graftling distribution; looked at /x (beside graphtraj)' > $RW/P-dsh-reply.txt
print -l -- $HOSTLINE "8801 8800 0:10 /Users/x/src/graphtraj/.venv/bin/python -I -m graphtraj.interfaces.mcp" > $F/ps.txt
steps Pr > $F/Pr-neg.out 2>&1; PRC=$?; grep -E '^(CHECK 503 dsh|503 dsh)' $F/Pr-neg.out
check "Pr negative (dsh): 'cannot find' in the reply FAILs, a GraphTraj process outside .venv-runtime FAILs, exit 1" sh -c "[ $PRC -ne 0 ] && grep -q \"CHECK 503 dsh no 'cannot find the installed graftling distribution' text: FAIL (found in \['reply'\])\" $F/Pr-neg.out && grep -q 'CHECK 503 dsh GraphTraj processes run from .venv-runtime: FAIL (1 listed, 1 not under' $F/Pr-neg.out && grep -q '^503 dsh: FAIL' $F/Pr-neg.out"
rm -f $RW/P-*.txt $A/ap1.json $A/ad1.json; print '{}' > $RW/P-pi-create.txt; rm -f $RW/Pr.done
steps Pr > $F/Pr-pend.out 2>&1
check "Pr PENDING (no record yet, dsh create not saved): Pr.done not written, next is Pr again" sh -c "grep -q '^503 dsh: PENDING' $F/Pr-pend.out && [ ! -e $RW/Pr.done ] && grep -q \"（稍后）zsh $SD/steps.zsh Pr\" $F/Pr-pend.out"
print -l -- $HOSTLINE > $F/ps.txt; rm -f $RW/P-*.txt $RW/P.started

head1 "done: no exported key value in raw files"
export ADOPT503_FAKE_TOKEN=rehearsal-secret-value-123456
steps done > $F/done.out 2>&1
check "done: raw files containing an exported key value: 0; next is T after acceptance" sh -c "grep -q 'raw files containing an exported key value: 0' $F/done.out && grep -q 'zsh $SD/steps.zsh T' $F/done.out"
print -r -- "rehearsal-secret-value-123456" > $RW/leak.txt
steps done > $F/done2.out 2>&1
check "done: a raw file with an exported key value is counted (1)" grep -q 'raw files containing an exported key value: 1' $F/done2.out
rm -f $RW/leak.txt; unset ADOPT503_FAKE_TOKEN

head1 "499: N's Step 01b (498), the notice count on 497's real files, session_id, I's 496/498 lines, ATTRIBUTED"
check "N prompt: Step 01b starts the subshell, sleep 1202 and sh -c with the split fake key, detached, then echoes n503-bg-started" grep -qF "Step 01b: write the sentence 'Now step 01b.' then call Bash with exactly: ( sleep 1201; true ) >/dev/null 2>&1 & sleep 1202 >/dev/null 2>&1 & sh -c 'sleep 1203; : api_key=sk-probe503fake''value0000' >/dev/null 2>&1 & sleep 4; echo n503-bg-started" $F/N.out
A497=${WT:h:h}/state/tasks/497-production-adoption-488-495/adoption/raw-2da634af
if [[ -r $A497/N-main-notice-with-header.txt ]]; then
  check "notices499: 497's real N-main-notice-with-header.txt counts 1 (497 counted 2)" [ "$($CONDA -I $SD/notices499.py $A497/N-main-notice-with-header.txt 497-production_adoption_488_495-handover0-advisor@advisor)" = 1 ]
  check "notices499: 497's real N-main-notice.txt counts 0 for another alias" [ "$($CONDA -I $SD/notices499.py $A497/N-main-notice.txt other@x)" = 0 ]
else print "497 raw notice files not readable here: $A497"; fi
check "Nr's by-hand session_read prompt uses session_id (installed schema: required session_id)" grep -qF 'session_read with {"session_id":"claude:sess-m","limit":400}' $F/Nr.out
check "I: 496 and 498 import lines" sh -c "grep -q '^496 has_exited has_exited | control._alive uses has_exited: True' $F/I.out && grep -q '^498 verdicts ours foreign provisional later | _verdict _executed _platform _beneath _settle | unsettled only under remaining: True' $F/I.out"
print -l 'FAILED tests/test_claude_native_host.py::test_graphtraj_session_end_is_one_stop_line[serving] - x' 'FAILED tests/test_x.py::test_brand_new - y' > $F/attr-failures.txt
check "ATTRIBUTED: a 498 accepted failure is attributed; an unknown one is not" zsh -c "source <(sed -n '/^ATTRIBUTED=(/,/^)/p; /^label_of() {/,/^}/p' $SD/steps.zsh); [[ \$(label_of 'tests/test_claude_native_host.py::test_graphtraj_session_end_is_one_stop_line[serving]') == 'ATTRIBUTED 498 SUITE'* && \$(label_of tests/test_x.py::test_brand_new) == unattributed ]]"

head1 "498: nr498.py positive was part of Nr above; negatives on the same child record and sidecar"
check "Nr positive: the six 498 CHECK lines PASS; Runtime readable with this marker reported; tool processes listed" sh -c "[ \$(grep -E '^CHECK 498 .*: PASS' $F/Nr.out | sort -u | wc -l) -eq 6 ] && ! grep -E '^CHECK 498' $F/Nr.out | grep -qv ': PASS' && grep -q \"environment readable from Main's watcher: \['readable'\]; carries this execution's marker: \['this'\]\" $F/Nr.out && grep -q '498 tool process subshell: pid 70010 ppid 70005 P_EXEC False platform True' $F/Nr.out"
nr498() { $CONDA -I $SD/nr498.py $FH $RW $W/gsrc-0.5.2/src n503 > $1 2>&1; }
$CONDA -I $SD/rehearse498.py $RW $ND foreign; nr498 $F/n498-foreign.out; R1=$?
check "498 negative: a recorded entry readable with another execution's marker FAILs 'no other execution's process'" sh -c "[ $R1 -ne 0 ] || true; grep -q \"CHECK 498 record contains no other execution's process: FAIL .*readable without this marker \['70020 marker other'\]\" $F/n498-foreign.out"
sleep 30 & LIVE=$!
LST=$($CONDA -I -c "import sys; sys.path.insert(0, '$W/gsrc-0.5.2/src'); from graftling.tool_descendants import identity; print(identity($LIVE).start)")
$CONDA -I $SD/rehearse498.py $RW $ND alive $LIVE $LST; nr498 $F/n498-alive.out
check "498 negative: a recorded process alive after the end (not in found) FAILs; its pid and own end are reported, no signal" sh -c "grep -q 'CHECK 498 recorded tool processes stopped at the execution end .*: FAIL (alive after the end, not stopped: \[$LIVE\]' $F/n498-alive.out && grep -q \"recorded pid $LIVE: alive\" $F/n498-alive.out && kill -0 $LIVE"
# Correction 1: a probe gone but not listed under stopped is an observation gap (NOT OBSERVED), not a defect.
$CONDA -I $SD/rehearse498.py $RW $ND mix $LIVE $LST; nr498 $F/n498-mix.out
check "498 Correction 1 mix: one probe gone at the end (not stopped) plus a recorded process alive after the end FAILs" sh -c "grep -q 'CHECK 498 recorded tool processes stopped at the execution end .*: FAIL (alive after the end, not stopped: \[$LIVE\]; signalled but still alive: \[\]; gone without the stop listing them: 70012: ended at the end' $F/n498-mix.out && kill -0 $LIVE"
$CONDA -I $SD/rehearse498.py $RW $ND unsettled-ok $LIVE $LST; nr498 $F/n498-unsok.out
check "498: an unsettled read only under remaining and still alive PASSes (not signalled)" sh -c "grep -q 'CHECK 498 unsettled reads only under remaining, not signalled: PASS' $F/n498-unsok.out && grep -q \"unsettled (remaining, not found) pid $LIVE: alive (not signalled)\" $F/n498-unsok.out && grep -q 'CHECK 498 recorded tool processes stopped .*: PASS' $F/n498-unsok.out"
kill $LIVE 2>/dev/null; wait $LIVE 2>/dev/null   # the rehearsal's own process
$CONDA -I $SD/rehearse498.py $RW $ND gone-running; nr498 $F/n498-goner.out
check "498 Correction 1 (a): a probe gone while the execution still ran, not under stopped, gives NOT OBSERVED with its reason" sh -c "grep -q \"CHECK 498 recorded tool processes stopped at the execution end .*: NOT OBSERVED (alive after the end, not stopped: \[\]; signalled but still alive: \[\]; gone without the stop listing them: 70012: ended before the execution end, not by this execution's stop\" $F/n498-goner.out && grep -q '    pid 70012 gone, not listed under stopped: ended before the execution end' $F/n498-goner.out"
$CONDA -I $SD/rehearse498.py $RW $ND gone-end; nr498 $F/n498-gonee.out
check "498 Correction 1 (b): a probe present until the end, gone after, not in found gives NOT OBSERVED with process_group_closed" grep -q 'CHECK 498 recorded tool processes stopped at the execution end .*: NOT OBSERVED (alive after the end, not stopped: \[\]; signalled but still alive: \[\]; gone without the stop listing them: 70012: ended at the end without the tool-process stop (process-group close?); process_group_closed=True)' $F/n498-gonee.out
$CONDA -I $SD/rehearse498.py $RW $ND unsettled; nr498 $F/n498-uns.out
check "498 negative: an unsettled (remaining-only) sleep 1202 gone before its own end FAILs (signalled)" grep -q 'CHECK 498 unsettled reads only under remaining, not signalled: FAIL (unsettled \[70012\]; gone before their own end (signalled): \[70012\])' $F/n498-uns.out
$CONDA -I $SD/rehearse498.py $RW $ND unreadable; nr498 $F/n498-unr.out
check "498: the Runtime's environment unreadable from the watcher is reported (env ['None'], marker ['n/a'])" grep -q "CHECK 498 Runtime environment and marker observed: PASS (env \['None'\] marker \['n/a'\])" $F/n498-unr.out
rm -f $RW/Nw498-samples.jsonl; nr498 $F/n498-none.out; R1=$?
check "498: no samples gives BLOCKED for every 498 check and exit 1 (unobserved is not met)" sh -c "[ $R1 -ne 0 ] && [ \$(grep -c '^CHECK 498 .*: BLOCKED (not observed' $F/n498-none.out) -eq 6 ]"

head1 "498: watch498.py on a live process tree started by the rehearsal (read only; it never signals)"
WD=$F/w498; mkdir -p $WD/agents-proj/.graphtraj/swarm/control/agents $WD/raw
# Short durations (61/62 s): if the cleanup below ever misses one, it ends by itself within a minute.
zsh -c '( sleep 61; true ) & sleep 62 & wait' & RTP=$!
sleep 1
print -r -- '{"version":1,"runtime_pid":'$RTP',"entries":[]}' > $WD/side.json
print -r -- '{"agent":"w1","name":"n503","retired_at":null,"executions":[{"id":"w1e","state":"running","process":{"runtime_pid":'$RTP',"tool_marker":"m-secret","tool_descendants":"'$WD/side.json'"}}]}' > $WD/agents-proj/.graphtraj/swarm/control/agents/w1.json
$CONDA -I $SD/watch498.py $WD/agents-proj $WD/raw $W/gsrc-0.5.2/src n503 20 1 > /dev/null 2>&1 &
WP=$!
sleep 2
print -r -- '{"agent":"w1","name":"n503","retired_at":null,"executions":[{"id":"w1e","state":"ended","process":{"runtime_pid":'$RTP',"tool_marker":"m-secret","tool_descendants":"'$WD/side.json'"}}]}' > $WD/agents-proj/.graphtraj/swarm/control/agents/w1.json
wait $WP
# Stop only the rehearsal's own tree: its descendants by ppid from libproc (pgrep is denied in the sandbox).
$CONDA -I - $W/gsrc-0.5.2/src $RTP > $F/w498.out <<'KILL'
import os, signal, sys
sys.path.insert(0, sys.argv[1])
from graftling.tool_descendants import _table
table, root = _table(), int(sys.argv[2])
kids = {}
for pid, item in table.items():
    kids.setdefault(item.ppid, []).append(pid)
todo, tree = [root], []
while todo:
    pid = todo.pop()
    tree.append(pid)
    todo += kids.get(pid, [])
for pid in reversed(tree):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
print('rehearsal tree stopped:', len(tree), 'processes')
KILL
wait $RTP 2>/dev/null
head -c 600 $WD/raw/Nw498-samples.jsonl; print; cat $WD/raw/Nw498.txt
check "watch498: sampled the live tree (subshell P_EXEC false, sleep 61 and 62), ended by itself, never wrote the marker value; the tree was stopped" sh -c "grep -q 'rehearsal tree stopped: 4 processes' $F/w498.out && grep -q '\"argv\": \"sleep 61\"' $WD/raw/Nw498-samples.jsonl && grep -q '\"argv\": \"sleep 62\"' $WD/raw/Nw498-samples.jsonl && grep -q '\"P_EXEC\": false' $WD/raw/Nw498-samples.jsonl && grep -q '== END (every execution ended)' $WD/raw/Nw498.txt && ! grep -q 'm-secret' $WD/raw/Nw498-samples.jsonl $WD/raw/Nw498.txt"

head1 "497's backup (tmp/497) is unchanged"
check "499 backup unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"
check "this run's backup is under tmp/503" test -d $FB/backup
ls $W | tr '\n' ' '; print
rm -f $F/ps.txt
print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED) ($COUNT checks)"
exit $FAILED
