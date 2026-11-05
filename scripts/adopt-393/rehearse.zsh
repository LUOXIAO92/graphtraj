#!/bin/zsh
# Rehearsal of steps.zsh against a fake production tree in $TMPDIR. Starts no real host and never
# writes to production: the real .venv-runtime is only read for its click, yaml and websockets.
#   zsh scripts/adopt-393/rehearse.zsh [phase...]     phases: setup B V guard I R half refuse      default: all
#
# `claude` and `ps` are stubs on PATH: the sandbox it was written in refuses the real ps, and real
# hosts must not run. So the refusal is a real process from the fake venv seen through a stub listing.
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${TMPDIR:-/tmp}/adopt393-rehearsal
FH=$F/project
FRT=$FH/.venv-runtime
FB=$F/home/graphtraj-adoption-393
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REAL_SITE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
OLD=1a648ca32d651ce379dbfaa89040a35745c182af   # production now: agent-swarm 0.2.4 (417)
export ADOPT393_H=$FH ADOPT393_BASE=$FB ADOPT393_RT=$FRT ADOPT393_PI_SANDBOX=$F/no-pi-sandbox ADOPT393_PNPM_SHIM=$F/no-shim ADOPT393_STUB=$F/stub
export PATH=$F/stub:$PATH
# A plain Terminal has none of these; this harness may run inside a Session that has them.
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION
W=$FH/.graphtraj/core/state/tasks/393-graphtraj-adoption-after-agents-release/adoption
steps() { zsh $SD/steps.zsh "$@"; }
SESS=$FH/.graphtraj/swarm/sessions
head1() { print -r -- ""; print -r -- "======== $*"; }
ok() { print -r -- "REHEARSAL PASS: $*"; }
no() { print -r -- "REHEARSAL FAIL: $*"; FAILED=1; }
FAILED=0
check() { local what=$1; shift; if "$@"; then ok $what; else no $what; fi; }
oldpy() { $FRT/bin/python -I "$@"; }

phase_setup() {
  head1 "setup: old wheels from $OLD, fake production venv, plugin, configuration, archives"
  rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldwheels $FH $FB:h
  cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in --version) print "stub-claude 0.0" ;; plugin) print "✔ Validation passed (stub)" ;; *) print "stub claude: $*" ;; esac
EOF
  cat > $F/stub/ps <<EOF
#!/bin/zsh
print "1 /sbin/launchd"
[[ -e $F/ps.txt ]] && cat $F/ps.txt
exit 0
EOF
  chmod +x $F/stub/claude $F/stub/ps
  git -C $WT archive $OLD | tar -x -C $F/oldsrc
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldsrc/src/agent_swarm
  ls $F/oldwheels
  git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT
  $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
  local D=$FRT/lib/python3.13/site-packages
  cp -Rp $REAL_SITE/click $REAL_SITE/click-*.dist-info(N) $REAL_SITE/yaml $REAL_SITE/_yaml $REAL_SITE/pyyaml-*.dist-info(N) $REAL_SITE/websockets $REAL_SITE/websockets-*.dist-info(N) $D/
  ls $D | grep -E 'dist-info' ; $FRT/bin/python -m pip check --disable-pip-version-check
  (cd $FH && print y | $FRT/bin/graphtraj setup) | tail -3
  (cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) >/dev/null
  # What production holds: the past sed of the forwarding line, and LANGUAGE in the agents entry.
  sed -i '' "s/'agent_swarm.claude.host'/'graphtraj.runtimes.claude.host'/" $FH/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs
  oldpy - $FH <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
mcp = json.loads((root / '.mcp.json').read_text())
mcp['mcpServers']['agents']['env'] = {'LANGUAGE': 'zh_CN'}
mcp['mcpServers']['other'] = {'command': '/bin/true', 'env': {'OTHER_API_KEY': 'fake-value-not-to-be-printed'}}
(root / '.mcp.json').write_text(json.dumps(mcp, indent=1))
settings = root / '.claude' / 'settings.local.json'
document = json.loads(settings.read_text())
document['permissions'] = {'allow': ['Bash(ls)']}
settings.write_text(json.dumps(document, indent=1))
PY
  # 0.2.4 writes version 5 (and reads 4); production holds both.
  oldpy $SD/rehearse_archive.py create $SESS 5 aaa bbb
  # W lives in this Task's state directory, so the fake state needs its record for the graph read.
  # The current definition is the record's source; its dependencies are removed, as no other Task exists here.
  mkdir -p $W:h/definitions; cp $WT/.state/task.yml $W:h/
  local def=$(sed -n 's/^current_definition: //p' $WT/.state/task.yml)
  for f in $WT/.state/task.md $WT/.state/$def; do
    sed -e "/^  - '[0-9]*'$/d" -e "s/^  dependencies:\$/  dependencies: []/" -e "s/^  parent_id:.*/  parent_id: null/" $f > $W:h/${f#$WT/.state/}
  done
  $CONDA -I $SD/adopt_tree.py versions $SESS
}

phase_B() {
  head1 "step B (rehearsed: real build of the target commit)"
  steps B; check "B exit 0" [ $? -eq 0 ]
  check "wheels are graphtraj-0.1.0 and graftling-0.5.0" test -f $W/wheels/graphtraj-0.1.0-py3-none-any.whl -a -f $W/wheels/graftling-0.5.0-py3-none-any.whl
}

phase_V() {
  head1 "step V with a stub claude (the real plugin validate is NOT rehearsed)"
  shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256
  steps V; check "V exit 0" [ $? -eq 0 ]
  check "V.ok written" test -e $W/raw/V.ok
  check "production plugin not written by V (still reads GRAPHTRAJ_CLAUDE_HOST_*)" grep -q "GRAPHTRAJ_CLAUDE_HOST_PYTHON" $FH/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs
  check "candidate reads GRAFTLING_CLAUDE_HOST_*" grep -q "GRAFTLING_CLAUDE_HOST_PYTHON" $W/vplug/graphtraj-claude-host/hooks/host_context.mjs
  check "candidate no longer reads GRAPHTRAJ_CLAUDE_HOST_*" test -z "$(grep GRAPHTRAJ_CLAUDE_HOST_ $W/vplug/graphtraj-claude-host/hooks/host_context.mjs)"
  check "V predicted settings.local.json" test -s $W/ventries/.claude__settings.local.json
  check "V wrote nothing to production entry files" shasum -a 256 -c $F/entries0.sha256
  check "candidate declares both tools" grep -q 'const TOOLS = \["agents", "tasks"\];' $W/vplug/graphtraj-claude-host/hooks/host_context.mjs
  print "NOT REHEARSED: Vc needs real Claude Code. Its marker is made by hand here so I can be rehearsed."
  touch $W/raw/Vc.ok
}

phase_guard() {
  head1 "guard: a real process from the fake venv is refused; a listing that cannot be read is refused"
  $FRT/bin/python -c 'import time; time.sleep(120)' &
  local pid=$!
  print "$pid $FRT/bin/python -c import time; time.sleep(120)" > $F/ps.txt
  print | steps I 2>&1 | tee $F/guard1.txt; local rc=${pipestatus[2]}
  check "I refused while a process runs from the venv (rc=$rc)" [ $rc -ne 0 ]
  check "the refusal names that process" grep -q "$pid $FRT/bin/python" $F/guard1.txt
  check "no backup was made" test ! -e $FB/backup
  kill $pid; wait $pid 2>/dev/null; rm -f $F/ps.txt
  print -r -- "--- the same with the sandbox's real, refused ps:"
  (export PATH=${PATH#$F/stub:}; unset ADOPT393_STUB; print | steps I 2>&1 | tee $F/guard2.txt; exit ${pipestatus[2]}); rc=$?
  check "I refused when the process list cannot be read (rc=$rc)" [ $rc -ne 0 ]
  check "the refusal says the list could not be read" grep -q "无法列出进程" $F/guard2.txt
  check "still no backup" test ! -e $FB/backup
}

phase_I() {
  head1 "step I, end to end on the fake production"
  shasum -a 256 $FH/.mcp.json $FH/.graphtraj/claude-host/config.json > $F/before.sha256
  cp $FH/.claude/settings.local.json $F/settings.before
  print | steps I; check "I exit 0" [ $? -eq 0 ]
  grep -E '^PASS' $W/raw/I-verify.txt
  check "PASS n FAIL 0" grep -Eq '^PASS [1-9][0-9]* FAIL 0$' $W/raw/I-verify.txt
  check "agent_swarm gone from the venv" test -z "$(ls -d $FRT/lib/python3.13/site-packages/agent_swarm* 2>/dev/null)"
  check ".mcp.json and config.json keep their bytes" shasum -a 256 -c $F/before.sha256
  check "settings.local.json: GRAFTLING_ names added, GRAPHTRAJ_CLAUDE_HOST_ names removed, permissions kept" $FRT/bin/python -I -c '
import json,sys; d=json.load(open(sys.argv[1])); e=d["env"]
assert e["GRAFTLING_CLAUDE_HOST_PYTHON"].endswith("/.venv-runtime/bin/python"), e
assert e["GRAFTLING_CLAUDE_HOST_CONFIG"].endswith("/claude-host/config.json"), e
assert not any(k.startswith("GRAPHTRAJ_CLAUDE_HOST_") for k in e), e
assert d["permissions"] == {"allow": ["Bash(ls)"]}, d' $FH/.claude/settings.local.json
  check "I printed the before/after of settings.local.json" grep -q 'GRAFTLING_CLAUDE_HOST_PYTHON' $W/raw/I.txt
  print "agents entry now: $($CONDA -I $SD/adopt_tree.py mcp $FH/.mcp.json | head -1)"
  check "LANGUAGE survives" grep -q '"LANGUAGE": "zh_CN"' $FH/.mcp.json
  check "the other entry's value is not in the raw evidence" test -z "$(grep -rl fake-value-not-to-be-printed $W/raw 2>/dev/null)"
  check "backup mode is 700" test "$(stat -f %Lp $FB/backup)" = 700
  print | steps I; check "a second I refuses to overwrite the backup" [ $? -ne 0 ]
  check "config.json keys are what the installed host demands" $FRT/bin/python -I -c '
import json,sys; assert set(json.load(open(sys.argv[1])))=={"root","cwd","claude","channel_file"}' $FH/.graphtraj/claude-host/config.json
  # The context path the written plugin calls, with GraphTraj's config.json.
  print "plugin forwards to: $(grep -oE "'-m', '[a-z_.]+'" $FH/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs | head -1)"
  print '{}' | (cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host context --config $FH/.graphtraj/claude-host/config.json) > $F/context.txt 2>&1
  print "context with no host running, rc=$?: $(tail -1 $F/context.txt)"
  check "context accepted the config, then named the missing host or channel" grep -qiE "host|channel" $F/context.txt
}

phase_R() {
  head1 "graftling 0.5.0 at work on the archives, then step R back to 0.2.4"
  $FRT/bin/python -I $SD/rehearse_archive.py upgrade $SESS bbb
  $FRT/bin/python -I $SD/rehearse_archive.py create $SESS 5 ccc
  # A version 0.2.4 cannot read: R must keep it and move it out of the old glob.
  $FRT/bin/python -I $SD/rehearse_archive.py create $SESS 5 ddd
  sed -i '' '1s/"version": *5/"version": 99/' $SESS/ddd/session.jsonl
  $CONDA -I $SD/adopt_tree.py versions $SESS
  mkdir -p $FH/.graphtraj/claude-host/live; print '{"stale":true}' > $FH/.graphtraj/claude-host/live/channel.json
  mkdir -p $FH/.graphtraj/swarm/control/agents; print '{"last":{"notification":"held"}}' > $FH/.graphtraj/swarm/control/agents/agent-x.json
  print | zsh $FB/backup/tools/steps.zsh R; check "R (from the backup's copy of the tools) exit 0" [ $? -eq 0 ]
  check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
  check "plugin equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/plugin.manifest $FH/.claude/skills/graphtraj-claude-host
  check "settings.local.json is byte-identical to before the install" cmp $FH/.claude/settings.local.json $F/settings.before
  check "stale channel moved out" test ! -e $FH/.graphtraj/claude-host/live/channel.json
  local keep=($FB/backup/after-install-*(N/))
  print "kept: ${keep[-1]}"; find ${keep[-1]} -type f | sed "s|${keep[-1]}/||"
  check "the version-99 archive was kept and left the old glob" test -f ${keep[-1]}/archives/ddd/session.jsonl -a ! -e $SESS/ddd/session.jsonl
  check "the graftling-written v5 archive stays in place" test -f $SESS/ccc/session.jsonl
  check "the graftling-rewritten archive keeps its post-install event" grep -q after-install $SESS/bbb/session.jsonl
  check "aaa is byte-identical to the snapshot" cmp $SESS/aaa/session.jsonl $FB/backup/archives/sessions/aaa/session.jsonl
  print "the restored 0.2.4 reads every archive graftling wrote, including the native_header lookup:"
  check "old reader works after R" oldpy $SD/rehearse_archive.py oldread $SESS
  oldpy -c 'import agent_swarm; print("agent_swarm", agent_swarm.__version__)'
  print -r -- "--- control: put the kept version-99 file back beside them; the old reader must fail, or the check above proves nothing"
  mkdir -p $F/control/sessions; cp -Rp $SESS/aaa $F/control/sessions/; cp -Rp ${keep[-1]}/archives/ddd $F/control/sessions/
  oldpy $SD/rehearse_archive.py oldread $F/control/sessions 2>&1 | tail -1
  check "the old reader refuses a directory holding one unreadable file" test ${pipestatus[1]} -ne 0
}

phase_fail() {
  head1 "a failure after the backup: I stops, names R, and R restores"
  cp $W/wheels/SHA256SUMS $F/SHA256SUMS.good; print "0000000000000000000000000000000000000000000000000000000000000000  graphtraj-0.1.0-py3-none-any.whl" > $W/wheels/SHA256SUMS
  rm -rf $FB/backup
  print | steps I 2>&1 | tee $F/fail.txt | tail -3; check "I failed (rc=${pipestatus[2]})" [ ${pipestatus[2]} -ne 0 ]
  check "I named R as the next step" grep -q "立刻运行回退" $F/fail.txt
  cp $F/SHA256SUMS.good $W/wheels/SHA256SUMS
  print | zsh $FB/backup/tools/steps.zsh R > $F/fail-R.txt 2>&1; check "R after a failed I exit 0" [ $? -eq 0 ]
  check "venv equals the pre-install manifest" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
}

phase_half() {
  head1 "half-way install, then R: only one wheel installed, a package file removed, a stray file added"
  rm -rf $FB/backup $W/raw/I.txt
  steps _backup; check "backup alone exit 0" [ $? -eq 0 ]
  $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $W/wheels/graphtraj-0.1.0-py3-none-any.whl
  rm -f $FRT/lib/python3.13/site-packages/agent_swarm/control.py; print junk > $FRT/lib/python3.13/site-packages/agent_swarm/stray.py
  # The other half: graftling alone installed beside the damaged agent_swarm.
  $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-deps --no-index $W/wheels/graftling-0.5.0-py3-none-any.whl
  $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT | tail -4
  print | zsh $FB/backup/tools/steps.zsh R; check "R after a half-way install exit 0" [ $? -eq 0 ]
  check "venv equals the pre-install manifest after the half-way install" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
  check "old code imports again" oldpy -c 'import agent_swarm.control, graphtraj.runtimes.claude.host'
  print "--- venv so broken its python is gone: R runs from the Conda helper"
  rm -rf $FRT/bin $FRT/pyvenv.cfg
  print | zsh $FB/backup/tools/steps.zsh R; check "R with a broken venv exit 0" [ $? -eq 0 ]
  check "venv equals the pre-install manifest after a broken venv" $CONDA -I $SD/adopt_tree.py compare $FB/backup/venv.manifest $FRT
}

phase_shell() {
  head1 "the shell paths of 0, Vc, Mps and done, with stub hosts: this proves the script runs, nothing about the hosts"
  print -r -- '#!/bin/zsh
print "stub-host $*"; exit 0' > $F/stub/codex; cp $F/stub/codex $F/stub/pi; cp $F/stub/codex $F/stub/dsh; chmod +x $F/stub/codex $F/stub/pi $F/stub/dsh
  cat > $F/stub/claude <<'EOF2'
#!/bin/zsh
case "$1" in
  --version) print "stub-claude 0.0" ;;
  plugin) print "✔ Validation passed (stub)" ;;
  -p) cat >/dev/null
    print '{"message":{"content":[{"type":"tool_use","id":"1","name":"mcp__agents__tasks"},{"type":"tool_use","id":"2","name":"mcp__agents__agents"}]}}'
    print '{"message":{"content":[{"type":"tool_result","tool_use_id":"1","content":"ok"},{"type":"tool_result","tool_use_id":"2","content":[{"type":"text","text":"ok"}]}]}}' ;;
  *) print start >> $STUB_START_LOG; print stub-interactive-screen; exit ${STUB_START_RC:-0} ;;
esac
exit 0
EOF2
  steps 0 2>&1 | tail -32; check "0 runs (rc=${pipestatus[1]})" [ ${pipestatus[1]} -eq 0 ]
  local VPJ=$FB/vproject T=$FB/vproject/.git/adopt393-trust-start-ok
  export STUB_START_LOG=$F/starts.txt; : > $STUB_START_LOG
  local VCLOG=$W/raw/Vc.txt
  starts() { wc -l < $STUB_START_LOG | tr -d ' '; }
  print -r -- "--- Vc 1: stopped right after git init; not a terminal: setup is reached, the start is refused"
  rm -f $W/raw/Vc.ok $VCLOG; rm -rf $VPJ; mkdir -p $VPJ; git -C $VPJ init -q --initial-branch=main
  steps Vc < /dev/null > $F/vc1.txt 2>&1; local rc=$?; tail -4 $F/vc1.txt
  check "Vc refuses when stdin and stdout are not a terminal (rc=$rc)" [ $rc -ne 0 ]
  check "it says so, and asks for the screen output" grep -q "拒绝启动" $F/vc1.txt
  check "the failure asks for the screen output" grep -q "屏幕上 Claude Code 的输出" $F/vc1.txt
  check "no start was made" test "$(starts)" = 0
  check "the two instruction lines are in Vc.txt" grep -q "Yes, proceed" $VCLOG
  check "this is the user's state: git and setup done, no trust marker, no .mcp.json, no Vc.ok" \
    test "$(git -C $VPJ rev-parse -q --verify refs/heads/dev)" -a ! -e $T -a ! -e $VPJ/.mcp.json -a ! -e $W/raw/Vc.ok
  print -r -- "--- Vc 2: from that exact state, the start exits 3 and the answer is n"
  (export ADOPT393_NO_TTY=1 STUB_START_RC=3; print n | steps Vc) > $F/vc2.txt 2>&1; rc=$?; tail -5 $F/vc2.txt
  check "answering no fails (rc=$rc)" [ $rc -ne 0 ]
  check "setup was not repeated" test -z "$(grep 'Setup plan' $F/vc2.txt)"
  check "one start, and it was not under the log" test "$(starts)" = 1 -a -n "$(grep stub-interactive-screen $F/vc2.txt)" -a -z "$(grep stub-interactive-screen $VCLOG)"
  check "Vc.txt has the rc and the answer" grep -q "trust start rc=3" $VCLOG
  check "no marker, no configuration" test ! -e $T -a ! -e $VPJ/.mcp.json
  print -r -- "--- Vc 3: the same, with no answer at all (end of input)"
  (export ADOPT393_NO_TTY=1 STUB_START_RC=3; steps Vc < /dev/null) > $F/vc3.txt 2>&1; rc=$?
  check "no answer counts as no (rc=$rc)" [ $rc -ne 0 -a ! -e $T ]
  print -r -- "--- Vc 4: the start exits 3 and the answer is y: the stream check decides"
  (export ADOPT393_NO_TTY=1 STUB_START_RC=3; print y | steps Vc) > $F/vc4.txt 2>&1; rc=$?; tail -12 $F/vc4.txt
  check "answering yes continues (rc=$rc)" [ $rc -eq 0 ]
  check "Vc.txt records the yes" grep -q "user answered yes" $VCLOG
  check "Vc.ok, trust marker and configuration written" test -e $W/raw/Vc.ok -a -e $T -a -e $VPJ/.mcp.json
  check "three starts so far" test "$(starts)" = 3
  print -r -- "--- Vc 5: configuration lost, no terminal: rewritten with no new start"
  rm -f $VPJ/.mcp.json
  steps Vc < /dev/null > $F/vc5.txt 2>&1; rc=$?; check "Vc rewrites the configuration without a new start (rc=$rc)" [ $rc -eq 0 -a -e $VPJ/.mcp.json ]
  check "still three starts" test "$(starts)" = 3
  print -r -- "--- Vc 6: a normal start, rc=0: no question"
  rm -f $T $W/raw/Vc.ok
  (export ADOPT393_NO_TTY=1; steps Vc < /dev/null) > $F/vc6.txt 2>&1; rc=$?
  check "rc=0 passes without asking (rc=$rc)" [ $rc -eq 0 -a -e $T -a -e $W/raw/Vc.ok ]
  check "the question did not appear" test -z "$(grep '按 y 表示是' $F/vc6.txt)"
  print -r -- '{"message":{"content":[{"type":"tool_use","id":"1","name":"mcp__agents__tasks"},{"type":"tool_result","tool_use_id":"1","content":"denied","is_error":true}]}}' > $F/bad.jsonl
  $CONDA -I $SD/adopt_tree.py stream $F/bad.jsonl mcp__agents__tasks; check "a refused tool call does not pass the stream check" [ $? -ne 0 ]
  print "4242 1 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json" > $F/ps.txt
  steps Mps 2>&1 | head -4; rm -f $F/ps.txt
  steps done 2>&1 | grep -E '^PASS|OK$|archives=|含密钥'; check "done runs (rc=${pipestatus[1]})" [ ${pipestatus[1]} -eq 0 ]
}

phase_refuse() {
  head1 "R with no complete backup refuses and says production was not touched by the install"
  mv $FB/backup/COMPLETE $F/COMPLETE.moved
  print | zsh $FB/backup/tools/steps.zsh R; check "R refused without COMPLETE" [ $? -ne 0 ]
  mv $F/COMPLETE.moved $FB/backup/COMPLETE
  head1 "steps that only print: M, P with and without a Pi sandbox; zsh -n"
  steps M > /dev/null; check "M prints" [ $? -eq 0 ]
  steps P | grep -A1 '^\[pi\]'
  mkdir -p $F/pisb; print 'sandbox_python=/x/venv/bin/python\nsandbox_path=/x/srt:/usr/bin' > $F/pisb/pi-sandbox.env
  (export ADOPT393_PI_SANDBOX=$F/pisb; steps P) > $F/p-none.txt; grep -A1 '^\[pi\]' $F/p-none.txt
  check "no rg anywhere: the note says the Pi launch is expected to fail" grep -q "里没有 rg，预期 Pi 启动失败" $F/p-none.txt
  check "and the role is unchanged" grep -q '"sandbox_path": "/x/srt:/usr/bin"' $F/p-none.txt
  mkdir -p $F/pisb/bin $F/rgreal; print '#!/bin/sh' > $F/rgreal/rg; chmod +x $F/rgreal/rg; ln -s $F/rgreal/rg $F/pisb/bin/rg
  cp $F/pisb/pi-sandbox.env $F/env.before
  (export ADOPT393_PI_SANDBOX=$F/pisb; steps P) > $F/p-rg.txt; grep -A1 '^\[pi\]' $F/p-rg.txt
  check "rg link present: \$PISBX/bin is prepended in the printed role" grep -q "\"sandbox_path\": \"$F/pisb/bin:/x/srt:/usr/bin\"" $F/p-rg.txt
  check "the note names the rg it finds" grep -q "pisb/bin/rg" $F/p-rg.txt
  check "the env file is unchanged" cmp $F/pisb/pi-sandbox.env $F/env.before
  print "sandbox_python=/x/venv/bin/python\nsandbox_path=$F/pisb/bin:/usr/bin" > $F/pisb/pi-sandbox.env
  (export ADOPT393_PI_SANDBOX=$F/pisb; steps P) > $F/p-has.txt
  check "already named: not added twice" grep -q "\"sandbox_path\": \"$F/pisb/bin:/usr/bin\"" $F/p-has.txt
  local K=$(print -rn -- 'claude:1845493c-4a13-43d4-b4ea-c5864f8b22cb' | shasum -a 256 | cut -d' ' -f1)
  mkdir -p $FH/.graphtraj/core/runner/main-sessions/inbox
  print '{"at":1,"event":{"alias":"p","event":"completed","execution":"e"},"id":"n1"}\n{"at":2,"event":{"alias":"p","event":"completed","execution":"e"},"id":"n1"}' > $FH/.graphtraj/core/runner/main-sessions/inbox/$K.jsonl
  steps inbox; check "inbox counts a duplicate id" grep -q 'duplicate ids: 1' $W/raw/inbox.txt
  print '{"at":1,"event":{"alias":"old","event":"completed"}}\n{"at":2,"event":{"alias":"old2","event":"completed"}}\n{"at":3,"event":{"alias":"p","event":"completed","execution":"e"},"id":"n2"}' > $FH/.graphtraj/core/runner/main-sessions/inbox/$K.jsonl
  rm -f $W/raw/inbox.txt; steps inbox; check "417 fix 1: id-less records are not one shared id" grep -q 'duplicate ids: 0' $W/raw/inbox.txt
  check "and they are counted" grep -q 'records without id (not compared): 2' $W/raw/inbox.txt
  head1 "printing steps: every one prints, names the next command, and fills real IDs"
  local s; for s in help M P F H1 H2 H3 H5; do steps $s > $F/print-$s.txt 2>&1; check "$s prints (rc=$?)" [ $? -eq 0 ]; done
  check "417 fix 2: M has no service block" test -z "$(grep -i 'service block' $F/print-M.txt)"
  check "417 fix 3: M retires by agent id" grep -q 'by that agent id' $F/print-M.txt
  check "every Codex use is $( print gpt-6-luna )" test -z "$(grep -h 'gpt-6-astra' $F/print-*.txt | grep -v 'gpt-6-astra 连接不用')"
  check "codex start passes -m gpt-6-luna" grep -q 'codex -m gpt-6-luna' $F/print-H2.txt
  check "Main swaps print how to get back" grep -q "claude --resume 1845493c-4a13-43d4-b4ea-c5864f8b22cb" $F/print-H2.txt
  check "no <placeholder> in printed text" test -z "$(grep -hE '<(alias|id|session|placeholder)>' $F/print-*.txt)"
  check "the Claude Main inbox key is filled" grep -q "$K.jsonl" $F/print-H1.txt
  head1 "H4a/H4b with a stub dsh that prints a session id in --json"
  print -r -- '#!/bin/zsh
print -r -- "{\"type\":\"start\",\"session\":{\"id\":\"dsh-sess-123\"}}"; print -r -- "{\"argv\":\"$*\"}"' > $F/stub/dsh; chmod +x $F/stub/dsh
  rm -f $W/raw/H4.session; steps H4b > $F/h4b-none.txt 2>&1; check "H4b refuses without H4a's session id" [ $? -ne 0 ]
  steps H4a > $F/h4a.txt 2>&1; check "H4a runs (rc=$?)" [ $? -eq 0 ]
  check "H4a saved the real session id" grep -qx 'dsh-sess-123' $W/raw/H4.session
  steps H4b > $F/h4b.txt 2>&1; check "H4b resumes with --session-id dsh-sess-123" grep -q -- '--session-id dsh-sess-123' $W/raw/H4b.json
  check "zsh -n steps.zsh" zsh -n $SD/steps.zsh
}

(( $# )) || set -- setup B V guard I R fail half refuse shell
for name in "$@"; do phase_$name; done
head1 "rehearsal result"
(( FAILED == 0 )) && print "ALL REHEARSAL CHECKS PASS" || print "SOME REHEARSAL CHECKS FAILED"
exit $FAILED
