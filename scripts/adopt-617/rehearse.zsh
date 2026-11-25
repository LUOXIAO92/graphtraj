#!/bin/zsh
# Task 617 rehearsal (Engineer's sandbox only; Main does not run this). Runs the ordered list of steps.zsh through
# `zsh steps.zsh <step>` against scratch copies; real production, <Harness>/graftling, the Harness state and GitHub are
# only read. Two stages, each in the FOREGROUND (612's background C5 lost uv's network):
#   zsh rehearse.zsh release   setup + 00 rel B G (real tests) GR rp gh C5 and their STOPs  -> rehearsal/console-release.txt
#   zsh rehearse.zsh adopt     V Mpre I M Mr N Nr Q Qr done R I0 and their STOPs (after release) -> rehearsal/console-adopt.txt
#   graftling: a clone of <Harness>/graftling (main = v0.10.0 6f4aeb8f checked out; dev at 3a35334e in a second
#     worktree); its origin is a scratch bare repository standing in for GitHub (main = dev = v0.10.0, HEAD -> main, so
#     the tagless C5 install takes main).
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 616's REAL graphtraj wheel (4ef36426)
#     + 612's REAL graftling 0.10.0 wheel (copied into the same state paths) + production's click, PyYAML and
#     websockets (copied from <Harness>/.venv-runtime, read only); `graphtraj setup` and the product's own
#     `configuration --write` write .mcp.json, settings.local.json, config.json and the hook copy.
#     Task state: copies (task.yml, definitions) of Tasks 617 and 516.
#   STUBS (fixtures): `claude` (--version; -p answers a stream-json init + READY-617) and `ps` (prints $SB/ps.txt).
#   REAL: rel/rp/gh git operations; the graftling wheel build and every B comparison (incl. 616's REAL graphtraj wheel
#     vs git archive 4ef36426); G through run_test_shards.py with -k selecting REAL tests: 615's intent test (all four
#     queries, incl. 'start an agent'), the repository-fixture test test_wheels_have_separate_owners (built_wheel: the
#     GraphTraj wheel's Requires-Dist against the installed graftling 0.10.1) and the MCP/discovery tests; GR on that
#     record; C5's uv install from git+file:// WITHOUT a tag (the sandbox refuses git to GitHub); V's product
#     regeneration of the hook copy, graphtraj-mcp, q617.py mcp; I's backup and force-reinstall of only the graftling
#     wheel; R from the backup's own copy; I0's move after R.
#   STAND-IN for Main's MCP call (labelled): the fake production's own graphtraj-mcp (after I), tools/call subagents
#     {action: discover, query: 'start an agent'}; its result text is Q.txt.
#   FIXTURES (labelled): Main's transcript lines (Mr: ToolSearch select: + M[b] calls; Qr: ToolSearch + the discover
#     call carrying Q.txt), Nr's child/member records and Main's saved notice, reply and swarm result; the STOP records.
# Outputs: rehearsal/console-*.txt, rehearsal/raw/, rehearsal/raw-stop/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
STAGE=${1:-}
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
OUTD=$SD/rehearsal
SB=${${TMPDIR:-/tmp}:A}/r617
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
GBASE=3a35334e977d5a9536a42d320e2a3243d3989f6d
GMAIN0=6f4aeb8fe9f47b71d81b9771486167b123308066
SAID="tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]"
T612=612-graftling-provider-release-and-production-adoption; T616=616-graphtraj-614-production-adoption
T617=617-graftling-0-10-1-release-and-production-adoption; T516=516-low-priority-flaky-tests
MAINID=11111111-2222-3333-4444-555555555617         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
S=$SD/steps.zsh
RAW=$OUTD/raw; STOPS=$OUTD/raw-stop
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT617_H=$FH ADOPT617_WT=$WT ADOPT617_STUB=$SB/stub ADOPT617_PROJECTS=$SB/projects/-fake ADOPT617_VPROJECT=$SB/vproject
        ADOPT617_SCRATCH=$SB/scr ADOPT617_G=$SB/g ADOPT617_GDEV=$SB/gdev ADOPT617_GURL=$SB/origin.git ADOPT617_UVT=$SB/uvtool-617
        ADOPT617_NOSNAP=1 ADOPT617_GWAIT=2 "ADOPT617_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print; print -r -- "######## rehearsal: $tag"; env $common ADOPT617_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
tl() {  # FIXTURE transcript lines: $1 = id, $2 = tool name, $3 = input json, $4 = result text (json-escaped)
  local t=$(now)
  print -r -- '{"type":"assistant","timestamp":"'$t'","message":{"content":[{"type":"tool_use","id":"'$1'","name":"'$2'","input":'$3'}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$t'","message":{"content":[{"type":"tool_result","tool_use_id":"'$1'","content":[{"type":"text","text":'$4'}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
}

case $STAGE in
release)
rm -rf $SB $RAW $STOPS; mkdir -p $SB/stub $SB/projects/-fake $RAW $STOPS
{ print "## setup: graftling scratch clone + bare origin (GitHub stand-in)"
  git clone -q --bare --no-hardlinks $REALH/graftling $SB/origin.git && git -C $SB/origin.git update-ref refs/heads/dev $GMAIN0 \
    && git -C $SB/origin.git update-ref refs/heads/main $GMAIN0 && git -C $SB/origin.git symbolic-ref HEAD refs/heads/main || exit 1
  git -C $SB/origin.git tag -d v0.10.1 > /dev/null 2>&1
  git clone -q --no-hardlinks $REALH/graftling $SB/g && git -C $SB/g checkout -q main && git -C $SB/g reset -q --hard $GMAIN0 \
    && git -C $SB/g branch -q -f dev $GBASE && git -C $SB/g worktree add -q $SB/gdev dev || exit 1
  git -C $SB/g remote set-url origin $SB/origin.git
  print -r -- "scratch graftling: main $(git -C $SB/g rev-parse main) | dev $(git -C $SB/g rev-parse dev) | origin main $(git -C $SB/origin.git rev-parse main) dev $(git -C $SB/origin.git rev-parse dev) HEAD -> $(git -C $SB/origin.git symbolic-ref HEAD)"
  print "## setup: STUB claude and ps (fixtures)"
  print -l '#!/bin/zsh' '# STUB claude (rehearsal fixture)' 'case " $* " in' \
    '  *" --version "*) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  *" -p "*) cat > /dev/null; print -r -- '"'"'{"type":"system","subtype":"init","model":"claude-opus-5-5","apiKeySource":"none"}'"'"'; print -r -- '"'"'{"type":"result","result":"READY-617 claude-opus-5-5 (stub, rehearsal fixture)"}'"'"' ;;' \
    '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 616's graphtraj 4ef36426 and 612's graftling 0.10.0 wheels)"
  W616=$FST/$T616/adoption/wheels-4ef36426 W612=$FST/$T612/adoption/wheels-0.10.0; mkdir -p $W616 $W612
  cp -p $REALSTATE/tasks/$T616/adoption/wheels-4ef36426/* $W616/ && cp -p $REALSTATE/tasks/$T612/adoption/wheels-0.10.0/* $W612/ || exit 1
  mkdir -p $FH && git -C $FH init -q --initial-branch=main || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W616/graphtraj-0.1.0-*.whl $W612/graftling-0.10.0-*.whl || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d(N) $D/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T617 $T516; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"), "click", m.version("click"), "websockets", m.version("websockets"))') | pip check: $($FRT/bin/python -m pip check --disable-pip-version-check 2>&1) | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ')"
  print "\n## script hygiene"
  for f in $S $0; do
    specials=(${(k)parameters[(R)*special*]})
    assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local (-a )?)?[A-Za-z_][A-Za-z0-9_]*=' $f | sed -E 's/^[ ;({]//; s/^local (-a )?//; s/=$//')"}})
    hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
    print -r -- "${f:t}: assigned names ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array): ${other:-none}"
  done
  print "\$NAME: followed by a letter (zsh modifier trap) in steps.zsh: $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "zsh -n steps.zsh: $(zsh -n $S 2>&1 || true)(empty = OK) | py_compile q617.py: $($CONDA -I -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' $SD/q617.py 2>&1)(empty = OK)"
  print "git diff 4ef36426 HEAD --name-only -- src tests plugins manuals pyproject.toml: $(git -C $WT diff --name-only 4ef36426 HEAD -- src tests plugins manuals pyproject.toml | tr '\n' ' ')(empty = production's product)"
  print "\n## STOP: rel with dev moved (then dev is reset to $GBASE)"
  echo moved > $SB/gdev/moved.txt && git -C $SB/gdev add moved.txt && git -C $SB/gdev -c user.name=x -c user.email=x@invalid commit -q -m 'dev moved (rehearsal)'
  run $STOPS "STOP: rel with dev moved" zsh $S rel
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag v0.10.1 $(git -C $SB/g rev-parse -q --verify refs/tags/v0.10.1 || print absent) branch agent/617 $(git -C $SB/g rev-parse -q --verify refs/heads/agent/617-graftling-0.10.1 || print absent)"
  git -C $SB/gdev reset -q --hard $GBASE
  for st in 00 rel; do run $RAW $st zsh $S $st; done
  run $RAW "rel again (already released)" zsh $S rel
  run $RAW B zsh $S B
  run $RAW "STOP: I before V/GR (nothing changed; no I.txt is written)" zsh -fc "print | zsh $S I"; print -r -- "I.txt in raw/ after the STOP: $([[ -e $RAW/I.txt ]] && print PRESENT || print absent)"
  run $RAW "STOP: rp (confirmed) before G/GR passed" env ADOPT617_PUSH_CONFIRMED=yes zsh $S rp; cp -p $RAW/rp.txt $STOPS/rp-before-GR.txt
  print -r -- "after the STOP: origin main $(git -C $SB/origin.git rev-parse main) dev $(git -C $SB/origin.git rev-parse dev) tag v0.10.1 $(git -C $SB/origin.git rev-parse -q --verify refs/tags/v0.10.1 || print absent)"
  print -r -- "\n## G: the step's own process starts at $(date +%T); it must exit only after its shards end, with the verdict as its last output"
  print -r -- "## G queue: a ps FIXTURE line shows another suite ('-m pytest') for ~5 s; G must wait for it in its own process"
  print -r -- "88 python -m pytest -q (ps FIXTURE: another suite)" > $SB/ps.txt; ( sleep 5; print -r -- $PSIDLE > $SB/ps.txt ) &
  run $RAW "G (-k: REAL tests incl. 615's intent test, a repository fixture and MCP/discovery tests)" env ADOPT617_PYTEST_ARGS="-k 'test_intent_queries_find_create or test_wheels_have_separate_owners or test_the_mcp_server_lists_subagents_and_tasks_only or test_graphtraj_discovery_keeps_its_document'" zsh $S G
  GREC=$(print -l $FST/$T617/adoption/G-*(N/om[1]))
  print -r -- "## G: the step's process exited at $(date +%T) | wait.txt: $(tr '\n' ';' < $GREC/wait.txt) | suite.txt last line: $(tail -1 $GREC/suite.txt)"
  print "## G record's PASSED lines (-rA, the per-test outcomes GR reads):"; grep -hoE '^PASSED tests/.*' $GREC/shards/*.log(N) | sort -u
  print "\n## STOP: GR on a COPY of that record whose start-an-agent outcome line is replaced by a FAILED line (FIXTURE)"
  FX=$FST/$T617/adoption/G-99999999T999999-fixture; cp -Rp $GREC $FX && touch $FX
  for f in $FX/shards/*.log(N); do $CONDA -I -c 'import sys; p, s = sys.argv[1], sys.argv[2]; t = open(p).read(); open(p, "w").write(t.replace("PASSED " + s, "FAILED " + s + " - AssertionError: [create, models] (FIXTURE)"))' $f "$SAID"; done
  print -r -- "fixture lines: $(grep -h -F -- "$SAID" $FX/shards/*.log | grep -E '^(PASSED|FAILED)' | tr '\n' ';')"
  run $STOPS "STOP: GR with the start-an-agent id FAILED (fixture record)" zsh $S GR
  mv $FX $SB/G-fixture-set-aside
  run $RAW "GR alone (re-judging the real rehearsal record; G already ran it at its end)" zsh $S GR
  run $RAW "STOP: rp unconfirmed (after GR passed; rp.txt is rewritten by the confirmed rp below)" zsh $S rp; cp -p $RAW/rp.txt $STOPS/rp-unconfirmed.txt
  run $RAW "rp confirmed" env ADOPT617_PUSH_CONFIRMED=yes zsh $S rp
  run $RAW gh zsh $S gh
  run $RAW "C5 (FOREGROUND; source git+file:// scratch origin, no tag)" env ADOPT617_SOURCE="git+file://$SB/origin.git" zsh $S C5
} 2>&1 | tee $OUTD/console-release.txt ;;

adopt)
[[ -d $FH && -e $RAW/GR.ok ]] || { print "run the release stage first"; exit 1; }
{ run $RAW V zsh $S V
  print -r -- "77 0:10 $FH/.venv-runtime/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $SB/ps.txt
  run $RAW "STOP: Mpre with a member Worker running (ps FIXTURE line)" zsh $S Mpre; cp -p $RAW/Mpre.txt $STOPS/Mpre.txt
  print -r -- $PSIDLE > $SB/ps.txt
  run $RAW Mpre zsh $S Mpre
  run $RAW I zsh -fc "print | zsh $S I"
  run $STOPS "STOP: I again (backup exists)" zsh -fc "print | zsh $S I"
  run $RAW M zsh $S M
  print "\n## FIXTURE: Main's transcript after I (M[b] calls, preceded by Claude Code's ToolSearch select:), timestamps now"
  sleep 1
  tl ts1 ToolSearch '{"query":"select:mcp__graphtraj__subagents","max_results":1}' '"(fixture)"'
  tl m1 mcp__graphtraj__subagents '{"action":"execute","feature":"status","arguments":{}}' '"{\"agents\":[]} (fixture)"'
  tl m2 mcp__graphtraj__tasks '{"action":"execute","feature":"task_graph","arguments":{"view":"current","details":["617"]}}' '"{\"tasks\":[]} (fixture)"'
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "\n## FIXTURE: Nr's child record n617, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/617-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n617","agent":"ag-1","parent":"617-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-25T12:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "617"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-25T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-25T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n617-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-617"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -r -- '[Graftling notice from 617-x@advisor · completed · execution 0a1b2c3d] done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"617-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  run $RAW Q zsh $S Q
  run $RAW "STOP: Qr before Q.txt exists (Qr.txt is rewritten by the Qr below; copy in raw-stop/)" zsh $S Qr; cp -p $RAW/Qr.txt $STOPS/Qr-before-Q.txt
  print "\n## REHEARSAL STAND-IN for Main's MCP call: the fake production's own graphtraj-mcp (graftling 0.10.1 after I), in the fake project; tools/call subagents {action: discover, query: 'start an agent'}; the result text is Q.txt"
  sleep 1
  (cd $FH && cl $FRT/bin/python -I -c 'import json, subprocess, sys
p = subprocess.Popen([sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "standin-617", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "subagents", "arguments": {"action": "discover", "query": "start an agent"}}}]
out, _ = p.communicate("".join(json.dumps(m) + "\n" for m in msgs), timeout=90)
for line in out.splitlines():
    r = json.loads(line)
    if r.get("id") == 2:
        res = r.get("result") or {}
        print(" ".join(i.get("text", "") for i in res.get("content", [])))
        print("isError", res.get("isError"), file=sys.stderr)' $FRT/bin/graphtraj-mcp) > $RAW/Q.txt 2> $SB/Q.err
  print -r -- "stand-in exit=$? | stderr: $(cat $SB/Q.err) | Q.txt:"; cat $RAW/Q.txt
  print "## FIXTURE: Main's transcript lines for that call (ToolSearch select: + the discover call; result = Q.txt)"
  tl ts2 ToolSearch '{"query":"select:mcp__graphtraj__subagents","max_results":1}' '"(fixture)"'
  tl q1 mcp__graphtraj__subagents '{"action":"discover","query":"start an agent"}' "$($CONDA -I -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' $RAW/Q.txt)"
  print "\n## STOP: Qr with a Q.txt listing create AND models (FIXTURE: production 0.10.0's answer), in raw-stop/ (copies of Q-pre.txt and Q.epoch)"
  cp -p $RAW/Q-pre.txt $RAW/Q.epoch $STOPS/ && print -l 'features:' '- feature: create' '  description: Create a child Agent on a Runtime; returns before its work finishes.' '- feature: models' "  description: List a Runtime's configured connections ...; read only, starts no Agent. (FIXTURE, YAML as GraphTraj's MCP text)" > $STOPS/Q.txt
  run $STOPS "STOP: Qr with create+models (fixture)" zsh $S Qr
  run $RAW Qr zsh $S Qr
  run $RAW done zsh $S done
  print "\n## R (rollback) after the adoption, run from the backup's own copy of steps.zsh"
  run $RAW R zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "after R: fake production $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | graftling direct_url: $(sed -E 's/.*"url": "([^"]+)".*/\1/' $FRT/lib/python3.13/site-packages/graftling-0.10.0.dist-info/direct_url.json 2>&1)"
  print "\n## I0 after R (sets the rolled-back run aside by MOVES), then I0 again (nothing to set aside)"
  run $RAW I0 zsh $S I0
  print -r -- "after I0: $(ls $SB/scr | tr '\n' ' ') | run1: $(ls $RAW/run1 2>/dev/null | tr '\n' ' ')"
  cp -p $RAW/I0.txt $RAW/I0-first.txt
  run $RAW "I0 again (I0.txt is rewritten; the first is I0-first.txt)" zsh $S I0
} 2>&1 | tee $OUTD/console-adopt.txt ;;

*) print "usage: zsh $0 release|adopt"; exit 2 ;;
esac
