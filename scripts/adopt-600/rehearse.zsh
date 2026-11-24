#!/bin/zsh
# Task 600 rehearsal (Engineer's sandbox only; Main does not run this). Runs the whole ordered list of steps.zsh against
# scratch copies; real production, <Harness>/graftling, the graftling-dev Worktree and GitHub are only read.
#   graftling: a clone of <Harness>/graftling (main checked out; dev at 2b4a33ae in a second worktree); its origin is a
#     scratch bare repository standing in for GitHub (main = dev = 7b5f4e6b, as GitHub after 593).
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 593's REAL wheels (graphtraj 6fe8c8d9,
#     graftling 0.9.0, copied from 593's wheels dir) + production's click/yaml/websockets; `graphtraj setup` and the
#     product's own `configuration --write` write .mcp.json, settings.local.json, config.json and the hook copy. Task
#     state: copies of Tasks 600 and 516 (task.yml, definitions). Main's transcript: an empty FIXTURE file.
#   STUB (fixture): `claude` (--version; -p answers READY-600). No real Claude, Codex, Pi or DSH runs.
#   REAL: rel/rp/gh git operations, the wheel build, C5's uv install (from git+file://, the sandbox proxy refuses git to
#     GitHub), G through run_test_shards.py with -k selecting real tests (incl. repository fixtures), GR/SR, suite-base on
#     one real id, V's product regeneration of the hook copy and graphtraj-mcp, I's backup/pip install, R's restore.
#   FIXTURES (labelled): Mr's Main transcript lines, Nr's child/member records and Main's saved notice and reply files.
# Outputs: rehearsal/console-*.txt, rehearsal/raw/, rehearsal/raw-stop/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
OUTD=$SD/${ADOPT600_ROUT:-rehearsal}                 # rehearsal outputs (a debug run may name another directory)
SB=${${TMPDIR:-/tmp}:A}/${ADOPT600_RNAME:-r600}      # scratch root
FH=$SB/project; FRT=$FH/.venv-runtime
GBASE=2b4a33aef93dc45b953bd412e4d5dd61347c38ea
GMAIN0=7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9
T593=593-graftling-0-9-0-release-and-production-adoption; T600=600-graftling-0-9-1-release
MAINID=11111111-2222-3333-4444-555555555600         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB/stub $SB/projects/-fake $OUTD
S=$SD/steps.zsh
{ print "## setup: graftling scratch clone + bare origin"
  git clone -q --bare --no-hardlinks $REALH/graftling $SB/origin.git && git -C $SB/origin.git update-ref refs/heads/dev $GMAIN0 || exit 1
  git clone -q --no-hardlinks $REALH/graftling $SB/g && git -C $SB/g branch -q dev $GBASE && git -C $SB/g worktree add -q $SB/gdev dev || exit 1
  git -C $SB/g remote set-url origin $SB/origin.git
  print "## setup: STUB claude (fixture)"
  print -l '#!/bin/zsh' 'case ${1:-} in' '  --version) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  -p) cat > /dev/null; print "READY-600 claude-opus-5-5 LOGGED-IN (stub, rehearsal fixture)" ;;' '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 593's real wheels)"
  W593=$FH/.graphtraj/core/state/tasks/$T593/adoption/wheels-6fe8c8d9; mkdir -p $W593
  cp -p $REALSTATE/tasks/$T593/adoption/wheels-6fe8c8d9/{graphtraj-0.1.0,graftling-0.9.0}-*.whl $W593/ || exit 1
  git -C $FH init -q --initial-branch=main 2>/dev/null || { mkdir -p $FH && git -C $FH init -q --initial-branch=main; }
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W593/*.whl || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d $D/; done
  (cd $FH && print y | $FRT/bin/graphtraj setup) > /dev/null
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T600 516-low-priority-flaky-tests; do mkdir -p $FH/.graphtraj/core/state/tasks/$t && cp -p $REALSTATE/tasks/$t/task.yml $FH/.graphtraj/core/state/tasks/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FH/.graphtraj/core/state/tasks/$t/; done
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ')"
} 2>&1 | tee $OUTD/console-setup.txt
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT600_H=$FH ADOPT600_WT=$WT ADOPT600_STUB=$SB/stub ADOPT600_PROJECTS=$SB/projects/-fake ADOPT600_VPROJECT=$SB/vproject
        ADOPT600_G=$SB/g ADOPT600_GDEV=$SB/gdev ADOPT600_GURL=$SB/origin.git ADOPT600_UVT=$SB/uvtool-600 ADOPT600_NOSNAP=1
        ADOPT600_GWAIT=2 "ADOPT600_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print -r -- "\n######## rehearsal: $tag"; env $common ADOPT600_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
RAW=$OUTD/raw
{ print "## script hygiene"
  specials=(${(k)parameters[(R)*special*]})
  assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local )?[A-Za-z_][A-Za-z0-9_]*=' $S | sed -E 's/^[ ;({]//; s/^local //; s/=$//')"}})
  hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
  print -r -- "assigned names: ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array, as 593): ${other:-none}"
  print "\$NAME: followed by a letter (zsh modifier trap): $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "## STOP: rel with dev moved"
  echo moved > $SB/gdev/moved.txt && git -C $SB/gdev add moved.txt && git -C $SB/gdev commit -q -m 'dev moved (rehearsal)'
  run $OUTD/raw-stop "rel, dev moved" zsh $S rel
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag v0.9.1 $(git -C $SB/g rev-parse -q --verify refs/tags/v0.9.1 || print absent) branch agent/600 $(git -C $SB/g rev-parse -q --verify refs/heads/agent/600-graftling-0.9.1 || print absent)"
  git -C $SB/gdev reset -q --hard $GBASE
  print "## STOP: rp before rel; I before V/GR; Mr before I"
  run $OUTD/raw-stop "rp before rel" zsh $S rp
  print -r -- $MAINID > /dev/null
} 2>&1 | tee $OUTD/console-stops.txt
{ for st in 00 rel rel B; do run $RAW $st zsh $S $st; done
  run $OUTD/raw-stop "I before V/GR (STOP, nothing changed)" zsh -fc "print | zsh $S I"
  run $RAW "G (-k: real tests incl. repository fixtures)" env ADOPT600_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_graphtraj_uses_only_published_agents_names or test_every_public_name_is_listed_in_the_contract or test_the_mcp_server_lists_subagents_and_tasks_only or test_the_claude_hook_copy_names_subagents_and_tasks or test_native_claude_lifecycle_without_a_task'" zsh $S G
  run $RAW "rp unconfirmed" zsh $S rp
  run $RAW "rp confirmed" env ADOPT600_PUSH_CONFIRMED=yes zsh $S rp
  run $RAW gh zsh $S gh
  run $RAW "C5 (source git+file:// scratch origin @v0.9.1)" env ADOPT600_SOURCE="git+file://$SB/origin.git@v0.9.1" zsh $S C5
} 2>&1 | tee $OUTD/console-release.txt
{ GREC=$(print -l $FH/.graphtraj/core/state/tasks/$T600/adoption/G-*(N/om[1])); print "G record: $GREC"
  [[ -n $GREC ]] && for i in {1..300}; do grep -q '^exit=' $GREC/suite.txt 2>/dev/null && break; sleep 3; done
  print "G suite.txt tail:"; tail -4 $GREC/suite.txt; print "wait.txt:"; cat $GREC/wait.txt
  print "PASSED ids through G's entry:"; grep -hoE '^PASSED tests/[^ ]+' $GREC/shards/*.log(N) | sort -u
  run $RAW GR zsh $S GR
  run $RAW SR zsh $S SR
  run $RAW "suite-base (one real id)" zsh $S suite-base tests/test_runtime_distribution.py::test_wheels_have_separate_owners
  run $RAW V zsh $S V
  print -r -- "77 0:10 $FH/.venv-runtime/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $SB/ps.txt
  run $RAW "Mpre with a member Worker running (ps FIXTURE line): STOP" zsh $S Mpre
  print -r -- $PSIDLE > $SB/ps.txt
  run $RAW Mpre zsh $S Mpre
  run $RAW I zsh -fc "print | zsh $S I"
  run $OUTD/raw-stop "I again (backup exists: STOP)" zsh -fc "print | zsh $S I"
  run $RAW M zsh $S M
  print "## FIXTURE: Main's transcript after I (M[b] calls), timestamps now"
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ); sleep 1
  print -r -- '{"type":"assistant","timestamp":"'$now'","message":{"content":[{"type":"tool_use","id":"m1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"status","arguments":{}}},{"type":"tool_use","id":"m2","name":"mcp__graphtraj__tasks","input":{"action":"execute","feature":"task_graph"}}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$now'","message":{"content":[{"type":"tool_result","tool_use_id":"m1","content":[{"type":"text","text":"{\"agents\":[]} (fixture)"}]},{"type":"tool_result","tool_use_id":"m2","content":[{"type":"text","text":"{\"tasks\":[] } (fixture)"}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "## FIXTURE: Nr's child record n600, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/600-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n600","agent":"ag-1","parent":"600-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-24T12:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "600"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-24T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-24T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n600-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-600"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -r -- '[Graftling notice from 600-x@advisor · completed · execution 0a1b2c3d] done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"600-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  run $RAW done zsh $S done
  print "## R (rollback) after the adoption"
  run $RAW R zsh -fc "print | zsh $S R"
  print -r -- "after R: fake production graftling $($FRT/bin/python -I -c 'import graftling; print(graftling.__version__)')"
} 2>&1 | tee $OUTD/console-adopt.txt
