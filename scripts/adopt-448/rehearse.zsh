#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR (taken from adopt-393/rehearse.zsh).
# Starts no real host and never touches production. `claude` and `ps` are stubs on PATH.
# Production's click/yaml come from Conda's site-packages; websockets is a stub package (Conda has none,
# and this sandbox cannot read production's venv).
#   zsh scripts/adopt-448/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt448-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$F/home/graphtraj-adoption-448
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CSITE=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
OLD=d11f3226422cb7a4de5e59d347f8d211d59350be   # production now: 393's wheels
export ADOPT448_H=$FH ADOPT448_BASE=$FB ADOPT448_RT=$FRT ADOPT448_PNPM_SHIM=$F/no-shim ADOPT448_STUB=$F/stub ADOPT448_WT=$WT
export PATH=$F/stub:$PATH
export GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere/.agents-control/claude-host.json   # 418: must be reported and unset
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
TASK=448-production-adoption-418-445-446
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

head1 "00 (stub ps lists a host whose parent is claude --resume <id>)"
print "4242 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json" > $F/ps.txt
cat > $F/stub/ps <<EOF
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --resume 11111111-2222-3333-4444-555555555555"; exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF
steps 00 > $F/00.out 2>&1
check "00 found Main from the host's parent" grep -q 'MAIN=11111111-2222-3333-4444-555555555555' $F/00.out
check "00 reported the inherited 418 variable by name and path" grep -q 'inherited: GRAFTLING_CLAUDE_HOST_CONFIG=/elsewhere' $F/00.out
grep -E 'inherited|MAIN=|running lines|^Version|guard' $F/00.out

head1 "B"
steps B > $F/B.out 2>&1; check "B exit 0" [ $? -eq 0 ]; grep -E 'whl|leaked' $F/B.out

head1 "V (stub plugin validate)"
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
steps V > $F/V.out 2>&1; check "V exit 0" [ $? -eq 0 ]
grep -E '^(SAME|CHANGED)|418|✘|差异' $F/V.out
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
touch $W/raw/Vc.ok; print "NOT REHEARSED: Vc (real Claude Code); marker made by hand."

head1 "guard: I refused while the host from the fake venv runs"
print | steps I > $F/guard.out 2>&1; check "I refused (host listed)" [ $? -ne 0 ]
check "no backup made" test ! -e $FB/backup
rm -f $F/ps.txt

head1 "I on the fake production"
print | steps I > $F/I.out 2>&1; check "I exit 0" [ $? -eq 0 ]
grep -E '^PASS|^FAIL|Successfully|SAME-AS|bytes unchanged|^changed|445 timer|claude --resume' $F/I.out
check "proddiff PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $W/raw/I-verify.txt
check "I printed the resume command with the real id" grep -q 'claude --resume 11111111-2222-3333-4444-555555555555' $F/I.out

head1 "R from the backup's own copy of the tools"
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; check "R exit 0" [ $? -eq 0 ]
grep -E '^(SAME|DIFF)|restored|already as|^Version' $F/R.out
check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT

head1 "Nr on synthetic records"
A=$FH/.graphtraj/swarm/control/agents; mkdir -p $A $FH/.graphtraj/swarm/sessions/sess-m
print '{"agent":"m@advisor","name":"m","session":"sess-m","executions":[]}' > $A/m.json
print '{"agent":"c1","name":"n448-stop","parent":"m@advisor","executions":[{"id":"e1","state":"ended","outcome":"interrupted","notification":"delivered","last_message":null}]}' > $A/c1.json
print '{"agent":"c2","name":"n448-ok","parent":"m@advisor","executions":[{"id":"e2","state":"ended","outcome":"completed","notification":"delivered","last_message":null}]}' > $A/c2.json
print -l '{"input":"notice e1 interrupted"}' '{"input":"notice e2 completed"}' > $FH/.graphtraj/swarm/sessions/sess-m/session.jsonl
steps Nr > $F/Nr.out 2>&1; grep -E '^child|CHECK|^parent|archive|retire the agent' $F/Nr.out
check "Nr: two delivered PASS" [ $(grep -c 'CHECK notification delivered: PASS' $W/raw/Nr.txt) -eq 2 ]
check "Nr printed the retire prompt with the member alias" grep -q 'retire the agent m@advisor' $F/Nr.out

head1 "M / N print real ids"
steps M | grep -c 11111111-2222-3333-4444-555555555555 | sed 's/^/M lines with the Main id: /'
steps N | grep -q '"task_id":"448"' && print "N prompt names task 448"

print "\nREHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED)"
exit $FAILED
