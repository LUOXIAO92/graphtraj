#!/bin/zsh
# Task 604 rehearsal (Engineer's sandbox only; Main does not run this). Runs the ordered list of steps.zsh against scratch
# copies; real production, the Harness state and this Worktree are only read.
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 593's REAL graphtraj wheel (6fe8c8d9)
#     + 600's REAL graftling 0.9.1 wheel (copied into the same state paths) + production's click/yaml/websockets;
#     `graphtraj setup` and the product's own `configuration --write` write .mcp.json, settings.local.json, config.json
#     and the hook copy. Task state: copies (task.yml, definitions) of Tasks 593, 600, 603 (+ its realhost record), 604,
#     516 and 601 (+ execution-budget.yml and teams/). 601 is real state data: cancelled, never integrated.
#   SCRATCH CANCELLED TASK: in $FH's own git, branch agent/601-graftling-changelog-intro-stale (one fixture commit on the
#     scratch dev) checked out in the registered Worktree .graphtraj/core/worktrees/601-graftling-changelog-intro-stale.
#     After I, it is cleaned through the INSTALLED CANDIDATE's public cleanup: `agent-runner cleanup --task-id 601` from
#     the fake production venv (the CLI stands in for Main's MCP tasks cleanup call; the same invoke_tool("cleanup")).
#   STUBS (fixtures): `claude` (--version; -p answers READY-604) and `ps` (the sandbox refuses /bin/ps; prints $SB/ps.txt).
#   FIXTURES (labelled): Mr's Main transcript lines, Nr's child/member records, Main's saved notice/reply/swarm result, and
#     for one STOP a copy of 603's record with an id not named in 516.
# No step runs pytest (S reads 603's record), so the pytest-fixture rehearsal rule does not apply.
# Outputs: rehearsal/console-*.txt, rehearsal/raw/, rehearsal/raw-stop/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
OUTD=${ADOPT604_ROUT:-$SD/rehearsal}             # a debug run may name another (absolute) directory
SB=${${TMPDIR:-/tmp}:A}/${ADOPT604_RNAME:-r604}
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
T593=593-graftling-0-9-0-release-and-production-adoption; T600=600-graftling-0-9-1-release
T601=601-graftling-changelog-intro-stale; T603=603-cancelled-task-timer-and-cleanup; T604=604-graphtraj-603-production-adoption
T516=516-low-priority-flaky-tests
MAINID=11111111-2222-3333-4444-555555555604         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB/stub $SB/projects/-fake $OUTD
S=$SD/steps.zsh
# Every product command of the setup and the cleanup stand-in runs in an allowlist environment: this Engineer's own
# session variables (for example GRAPHTRAJ_CLI_CONNECTION) must not reach the scratch project's product.
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
{ print "## setup: STUB claude and ps (fixtures)"
  print -l '#!/bin/zsh' 'case ${1:-} in' '  --version) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  -p) cat > /dev/null; print "READY-604 claude-opus-5-5 LOGGED-IN (stub, rehearsal fixture)" ;;' '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 593's graphtraj wheel and 600's graftling 0.9.1 wheel)"
  W593=$FST/$T593/adoption/wheels-6fe8c8d9 W600=$FST/$T600/adoption/wheels-0.9.1; mkdir -p $W593 $W600
  cp -p $REALSTATE/tasks/$T593/adoption/wheels-6fe8c8d9/* $W593/ && cp -p $REALSTATE/tasks/$T600/adoption/wheels-0.9.1/* $W600/ || exit 1
  git -C $FH init -q --initial-branch=main || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W593/graphtraj-0.1.0-*.whl $W600/graftling-0.9.1-*.whl || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d $D/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state").replace("agent_worktrees: .graphtraj/.agent-worktrees", "agent_worktrees: .graphtraj/core/worktrees"))' $c; done
  print -r -- "fake project paths (production layout, as the real 601 state records its Worktree): $(grep -E 'agent_worktrees|state:' $FH/.graphtraj/config.yml | tr -s ' ' | tr '\n' ';')"
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T593 $T600 $T603 $T604 $T516 $T601; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  cp -Rp $REALSTATE/tasks/$T603/realhost $FST/$T603/ && cp -p $REALSTATE/tasks/$T601/execution-budget.yml $FST/$T601/ && cp -Rp $REALSTATE/tasks/$T601/teams $FST/$T601/ || exit 1
  print "## setup: SCRATCH cancelled Task 601 (real state copy; fixture branch and Worktree in the scratch project's git)"
  git -C $FH branch -q agent/$T601 dev && WT601=$FH/.graphtraj/core/worktrees/$T601 && git -C $FH worktree add -q $WT601 agent/$T601 || exit 1
  print "fixture change (rehearsal)" > $WT601/CHANGELOG-fixture.md && git -C $WT601 add CHANGELOG-fixture.md && git -C $WT601 -c user.name=x -c user.email=x@invalid commit -qm "601 fixture commit (rehearsal)" || exit 1
  print -r -- "601 scratch: worktree $WT601 | branch tip $(git -C $FH rev-parse agent/$T601) | dev $(git -C $FH rev-parse dev) | 601 task.yml status $(sed -n 's/^status: //p' $FST/$T601/task.yml)"
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ')"
  print "## setup: FIXTURE copy of 603's record with one id not named in 516 (S STOP)"
  mkdir -p $SB/s603-fixture && cp -p $REALSTATE/tasks/$T603/realhost/{run.txt,new-ids.txt} $SB/s603-fixture/ || exit 1
  sed -e 's|^FAILED tests/test_claude_runner.py::test_second.*|&\nFAILED tests/test_fixture_604.py::test_not_named_in_516 (FIXTURE)|' -e 's/^2 failed, 3717 passed/3 failed, 3716 passed/' \
    $REALSTATE/tasks/$T603/realhost/suite-suite-1fdbbca5-20261124T185824.txt > $SB/s603-fixture/suite-suite-1fdbbca5-20261124T185824.txt
} 2>&1 | tee $OUTD/console-setup.txt
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT604_H=$FH ADOPT604_WT=$WT ADOPT604_STUB=$SB/stub ADOPT604_PROJECTS=$SB/projects/-fake ADOPT604_VPROJECT=$SB/vproject
        ADOPT604_SCRATCH=$SB/scr ADOPT604_REPO=$FH ADOPT604_DEV=$(git -C $FH rev-parse dev) "ADOPT604_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print; print -r -- "######## rehearsal: $tag"; env $common ADOPT604_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
RAW=$OUTD/raw; STOPS=$OUTD/raw-stop
{ print "## script hygiene"
  specials=(${(k)parameters[(R)*special*]})
  assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local )?[A-Za-z_][A-Za-z0-9_]*=' $S | sed -E 's/^[ ;({]//; s/^local //; s/=$//')"}})
  hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
  print -r -- "assigned names: ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array, as 593/600): ${other:-none}"
  print "\$NAME: followed by a letter (zsh modifier trap): $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "git diff 1fdbbca5 HEAD -- src tests plugins manuals pyproject.toml: $(git -C $WT diff --name-only 1fdbbca5 HEAD -- src tests plugins manuals pyproject.toml | tr '\n' ' ')(empty = product unchanged)"
} 2>&1 | tee $OUTD/console-stops.txt
{ run $RAW 00 zsh $S 00
  run $STOPS "STOP: I before S/V (nothing changed)" zsh -fc "print | zsh $S I"
  run $STOPS "STOP: S with a FIXTURE record carrying an id not named in 516" env ADOPT604_S603=$SB/s603-fixture zsh $S S
  for st in S B V; do run $RAW $st zsh $S $st; done
  print -r -- "77 0:10 $FH/.venv-runtime/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $SB/ps.txt
  run $RAW "STOP: Mpre with a member Worker running (ps FIXTURE line)" zsh $S Mpre; cp -p $RAW/Mpre.txt $STOPS/Mpre.txt
  print -r -- $PSIDLE > $SB/ps.txt
  run $RAW Mpre zsh $S Mpre
  run $RAW I zsh -fc "print | zsh $S I"
  run $STOPS "STOP: I again (backup exists)" zsh -fc "print | zsh $S I"
  run $RAW M zsh $S M
  print "## FIXTURE: Main's transcript after I (M[b] calls), timestamps now"
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ); sleep 1
  print -r -- '{"type":"assistant","timestamp":"'$now'","message":{"content":[{"type":"tool_use","id":"m1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"status","arguments":{}}},{"type":"tool_use","id":"m2","name":"mcp__graphtraj__tasks","input":{"action":"execute","feature":"task_graph","arguments":{"view":"current","details":["604"]}}}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$now'","message":{"content":[{"type":"tool_result","tool_use_id":"m1","content":[{"type":"text","text":"{\"agents\":[]} (fixture)"}]},{"type":"tool_result","tool_use_id":"m2","content":[{"type":"text","text":"{\"tasks\":[] } (fixture)"}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "## FIXTURE: Nr's child record n604, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/604-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n604","agent":"ag-1","parent":"604-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-24T12:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "604"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-24T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-24T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n604-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-604"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -r -- '[Graftling notice from 604-x@advisor · completed · execution 0a1b2c3d] done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"604-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  rm -rf $FH/.graphtraj/core/runner/sessions/604-x@advisor   # the Nr fixture mapping is not a 601 resource; removed before C601
  run $RAW C601 zsh $S C601
  run $RAW "STOP: C601r before C601.txt exists" zsh $S C601r
  print "## REHEARSAL STAND-IN for Main's MCP call: the installed candidate's public cleanup CLI from the fake production venv"
  print -r -- "command: (cd $FH && $FRT/bin/agent-runner cleanup --task-id 601) > $RAW/C601.txt"
  (cd $FH && cl $FRT/bin/agent-runner cleanup --task-id 601) > $RAW/C601.txt 2>$SB/C601.err
  print -r -- "agent-runner cleanup exit=$? | stdout:"; cat $RAW/C601.txt; print -r -- "stderr: $(cat $SB/C601.err)"
  run $RAW C601r zsh $S C601r
  run $RAW done zsh $S done
  print "## R (rollback) after the adoption, run from the backup's own copy of steps.zsh"
  run $RAW R zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "after R: fake production $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | graphtraj direct_url: $(sed -E 's/.*"url": "([^"]+)".*/\1/' $FRT/lib/python3.13/site-packages/graphtraj-0.1.0.dist-info/direct_url.json)"
} 2>&1 | tee $OUTD/console-adopt.txt
