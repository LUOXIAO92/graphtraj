#!/bin/zsh
# Task 592 Engineer rehearsal of steps.zsh (NOT acceptance evidence): stub pi (scripts/verify-592/stub/pi: no model, the
# real installed graphtraj-mcp), a dummy DEEPSEEK_API_KEY the stub never uses, ROOTs under $TMPDIR, outputs and the
# suite under <Worktree>/.scratch/592-b (never committed).
#   zsh scripts/verify-592/rehearse.zsh <GraphTraj candidate commit>
# Parts: (1) base bfed0c4c, expected FAIL in cli and pi-main; (2) the candidate, expected ALL PASS; (3) Claude gates
# STOP without the login flag; (4) judge hook on configuration --write material of both; (5) judge claude on synthetic
# stream-json built from part 2's real graphtraj-mcp answers, plus FAIL variants; (6) judge pi on Task 583's recorded
# real Pi Session (old names: FAIL); (7) suite filtered through the step, SR, and suite-base on one id.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel); S=${0:A:h}/steps.zsh; J=${0:A:h}/judge.py
H=${WT:h:h:h:h}; B=$WT/.scratch/592-b
CAND=$(git -C $WT rev-parse ${1:?usage: rehearse.zsh <candidate commit>}); BASE=$(git -C $WT rev-parse bfed0c4c)
# The suite's clones live in $TMPDIR: this sandbox refuses every .git/config write under the Worktree ("could not
# lock config file ...: Operation not permitted"); Main's T is <Harness>/tmp/592.
export VERIFY592_BIN=${0:A:h}/stub VERIFY592_USERHOME=$B/home VERIFY592_T=$TMPDIR/graphtraj-592-reh-T DEEPSEEK_API_KEY=rehearsal-dummy-not-a-key
mkdir -p $B/home/.pi/agent $B/home/.dsh $B/home/.codex; [[ -f $B/home/.pi/agent/settings.json ]] || print '{}' > $B/home/.pi/agent/settings.json
run() { print -r -- "######## $*"; zsh $S "$@" 2>&1 | grep -E '^(PASS|FAIL|STOP|NOTE|SUCCESS|pip install|STEP-END|judge|  (subagents|tasks)-|tools/list|written hook|graphtraj [0-9]|graftling [0-9]|SR verdict|listed in|not in 516|next \(paste\)|or \(paste\)|fails on|candidate-only|passes on|== base|== candidate|base:|candidate:|pytest temp|REHEARSAL|exit=)' | cut -c1-260; print -r -- "rc=${pipestatus[1]}"; }
side() {  # label commit
  export VERIFY592_ROOT=$TMPDIR/graphtraj-592-reh-$1 VERIFY592_OUT=$B/out-$1 VERIFY592_GCOMMIT=$2
  rm -rf $VERIFY592_ROOT $VERIFY592_OUT
  print -r -- "======== part: $1 = GraphTraj $2 + graftling 49f97004 (wheels); ROOT=$VERIFY592_ROOT"
  local s; for s in pre install cli pi-main post; do run $s; done
}
print -r -- "rehearsal of $S at $(git -C $WT log --oneline -1 -- scripts/verify-592) | candidate $CAND | $(date '+%F %T %Z')"
print -r -- "zsh $ZSH_VERSION | TMPDIR=$TMPDIR | stub pi: $VERIFY592_BIN/pi"
print -r -- "(base part: VERIFY592_NO_DIFF_CHECK=1, since this checkout differs from base by design)"
VERIFY592_NO_DIFF_CHECK=1 side base $BASE
side cand $CAND
print -r -- "======== part: pre's diff check against a commit whose tests differ (3f8207b6; expected FAIL + STOP)"
( export VERIFY592_ROOT=$TMPDIR/graphtraj-592-reh-diff VERIFY592_OUT=$B/out-diff VERIFY592_GCOMMIT=$(git -C $WT rev-parse 3f8207b6)
  rm -rf $VERIFY592_ROOT; zsh $S pre 2>&1 | grep -E '^(PASS|FAIL|STOP|STEP-END| [^ ].*\|)' | cut -c1-200; print -r -- "rc=${pipestatus[1]}" )
print -r -- "======== part: Claude gates (no login flag; claude is not on this sandbox's PATH)"
run claude-pre
run claude-main
print -r -- "======== part: judge hook on configuration --write material (--claude /usr/bin/true; nothing launched)"
local lab; for lab in base cand; do
  local R=$TMPDIR/graphtraj-592-reh-$lab PC=$TMPDIR/graphtraj-592-reh-$lab/hookproj
  rm -rf $PC; mkdir -p $PC
  (cd $PC && env -i PATH=/usr/bin:/bin HOME=$B/home $R/venv/bin/python -I -m graphtraj.runtimes.claude.host configuration --project $PC --claude /usr/bin/true --write > /dev/null) \
    && { print -r -- "######## judge hook ($lab)"; python3 -I $J hook $PC/.claude/skills/graphtraj-claude-host; print -r -- "rc=$?"; }
done
print -r -- "======== part: judge claude on synthetic stream-json from part cand's real graphtraj-mcp answers"
local SF=$(print -l -- $TMPDIR/graphtraj-592-reh-cand/sessions/pi-main/*.jsonl(N) | head -1) SY=$B/synthetic; mkdir -p $SY
python3 -I - $SF $SY <<'PY'
import json, sys
src, out = sys.argv[1], sys.argv[2]
msgs = [json.loads(l)['message'] for l in open(src) if '"message"' in l]
tools = [t['name'] for m in msgs if m.get('role') == 'system' for t in m['toolsAdded']]
def stream(tools, servers):
    ev = [{'type': 'system', 'subtype': 'init', 'model': 'claude-haiku-5-5', 'session_id': 'synthetic',
           'tools': tools, 'mcp_servers': servers, 'plugins': [{'name': 'graphtraj-claude-host', 'path': '/x'}]}]
    for m in msgs:
        if m.get('role') == 'assistant':
            for b in m['content']:
                if b.get('type') == 'toolCall':
                    ev.append({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': b['id'], 'name': b['name'], 'input': b['arguments']}]}})
        if m.get('role') == 'toolResult':
            ev.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': m['toolCallId'], 'is_error': m['isError'], 'content': m['content']}]}})
    ev.append({'type': 'result', 'is_error': False, 'result': 'CALL 1: ok ...'})
    return ''.join(json.dumps(e) + '\n' for e in ev)
base = [t for t in tools if not t.startswith('mcp__')] + ['mcp__graphtraj__subagents', 'mcp__graphtraj__tasks']
ok = [{'name': 'graphtraj', 'status': 'connected'}]
open(f'{out}/pass.jsonl', 'w').write(stream(base, ok))
open(f'{out}/other-old.jsonl', 'w').write(stream(base + ['mcp__other__agents'], ok + [{'name': 'other', 'status': 'connected'}]))
open(f'{out}/not-connected.jsonl', 'w').write(stream(base, [{'name': 'graphtraj', 'status': 'failed'}]))
PY
local f; for f in pass other-old not-connected; do
  print -r -- "######## judge claude synthetic/$f.jsonl (expected: $([[ $f == pass ]] && print 'ALL PASS' || print FAIL))"
  python3 -I $J claude $SY/$f.jsonl | grep -E '^(PASS|FAIL|NOTE|judge)' | cut -c1-200; print -r -- "rc=${pipestatus[1]}"
done
print -r -- "======== part: judge pi on Task 583's recorded REAL GraphTraj Pi Main Session (old names; expected FAIL)"
local R583=$H/.graphtraj/core/state/tasks/583-graphtraj-pi-extension-no-graftling-default-host/realhost
mkdir -p $SY/583 && cp $R583/main-after.session.jsonl $SY/583/ && python3 -I $J pi $SY/583 $R583/main-after.txt | grep -E '^(PASS|FAIL|judge)' | cut -c1-200
print -r -- "rc=${pipestatus[1]}"
print -r -- "======== part: suite through the step (FILTERED), SR, suite-base on one id"
export VERIFY592_GCOMMIT=$CAND VERIFY592_OUT=$B/out-suite VERIFY592_NO_PS=1
print -r -- "######## suite with an unwritable T (expected STOP before anything is written)"
VERIFY592_T=/var/empty/graphtraj-592-T zsh $S suite 2>&1 | grep -E '^(STOP|T=|STEP-END)' ; print -r -- "rc=${pipestatus[1]}"
export VERIFY592_PYTEST_ARGS="-k 'tool_name_592 or test_host_plugin_tools or test_mcp_adoption or test_wheels_have_separate_owners'"
run suite
[[ -f $VERIFY592_T/suite-latest ]] || { print -r -- "rehearsal stops: the suite step did not start (above)"; exit 1; }
local g=$(<$VERIFY592_T/suite-latest) i; for i in {1..180}; do grep -q '^exit=' $g/suite.txt 2>/dev/null && break; sleep 5; done
print -r -- "suite.txt tail: $(tail -4 $g/suite.txt | tr '\n' '|')"
run SR
# A copy of that run with one injected FAILED line, to show SR's suite-base command with a separately quoted id.
local F=$VERIFY592_T/suite-injected; rm -rf $F; cp -R $g $F; local id=$(grep -hE '^PASSED tests/test_host_plugin_tools' $F/shards/*.log | head -1 | cut -d' ' -f2)
print -r -- "FAILED $id - injected by rehearse.zsh" >> ${$(print -l -- $F/shards/*.log | head -1)}
print -r -- $F > $VERIFY592_T/suite-latest
run SR
print -r -- $g > $VERIFY592_T/suite-latest
run suite-base $id
