#!/bin/zsh
# Task 612 rehearsal (Engineer's sandbox only; Main does not run this). Runs the whole ordered list of steps.zsh against
# scratch copies; real production, <Harness>/graftling, the Harness state and GitHub are only read.
#   graftling: a clone of <Harness>/graftling (main = v0.9.1 checked out; dev at ddc506b0 in a second worktree); its
#     origin is a scratch bare repository standing in for GitHub (main = dev = e8c2e802 = v0.9.1, HEAD -> main, so the
#     tagless C5 install takes main).
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 604's REAL graphtraj wheel (1fdbbca5)
#     + 600's REAL graftling 0.9.1 wheel (copied into the same state paths) + production's click/yaml/websockets;
#     `graphtraj setup` and the product's own `configuration --write` write .mcp.json, settings.local.json, config.json
#     and the hook copy. Task state: copies (task.yml, definitions) of Tasks 612 and 516.
#   STUBS (fixtures): `claude` (--version; -p answers READY-612; a stream-json `initialize` answers a model catalog, as
#     graftling's Claude discovery reads it) and `ps` (the sandbox refuses /bin/ps; prints $SB/ps.txt).
#   USER CATALOG (fixture): $SB/home/.graphtraj/connections.yml (a Claude entry without base_url or key, a Pi entry keyed
#     by OPENCODE_API_KEY); P reads it through ADOPT612_CATALOG_HOME. A second fixture catalog without either kind of entry
#     rehearses P's STOP.
#   REAL: rel/rp/gh git operations; both wheel builds; C5's uv install from git+file:// WITHOUT a tag (the sandbox proxy
#     refuses git to GitHub); G through run_test_shards.py with -k selecting real tests, incl. repository fixtures
#     (test_wheels_have_separate_owners: the built wheel's Requires-Dist against the installed graftling 0.10.0) and
#     611's discovery tests; GR/SR; suite-base on one real id; V's product regeneration of the hook copy, graphtraj-mcp
#     and mcp612.py; I's backup and pip --force-reinstall of both wheels; P's catalog read; R's restore from the backup's
#     own copy of steps.zsh.
#   STAND-IN for Main's MCP call (labelled): the installed candidate's public CLI `graphtraj connections --action discover`
#     from the fake production venv (the same invoke_tool("runtime_connections") as Main's tasks call), with the stub claude.
#   FIXTURES (labelled): Mr's Main transcript lines, Nr's child/member records and Main's saved notice, reply and swarm result.
# Outputs: rehearsal/console-*.txt, rehearsal/raw/, rehearsal/raw-stop/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
OUTD=${ADOPT612_ROUT:-$SD/rehearsal}             # a debug run may name another (absolute) directory
SB=${${TMPDIR:-/tmp}:A}/${ADOPT612_RNAME:-r612}
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
GBASE=ddc506b0a7f87372baf8edc2347c26eebc2a251c
GMAIN0=e8c2e80241dff1151f2122e8957fca5598ec987b
T600=600-graftling-0-9-1-release; T604=604-graphtraj-603-production-adoption
T612=612-graftling-provider-release-and-production-adoption; T516=516-low-priority-flaky-tests
MAINID=11111111-2222-3333-4444-555555555612         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB/stub $SB/projects/-fake $SB/home/.graphtraj $SB/home2/.graphtraj $OUTD
S=$SD/steps.zsh
# Every product command of the setup and the stand-in runs in an allowlist environment: this Engineer's own session
# variables (for example GRAPHTRAJ_CLI_CONNECTION) must not reach the scratch project's product.
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
{ print "## setup: graftling scratch clone + bare origin (GitHub stand-in)"
  git clone -q --bare --no-hardlinks $REALH/graftling $SB/origin.git && git -C $SB/origin.git update-ref refs/heads/dev $GMAIN0 \
    && git -C $SB/origin.git update-ref refs/heads/main $GMAIN0 && git -C $SB/origin.git symbolic-ref HEAD refs/heads/main || exit 1
  git clone -q --no-hardlinks $REALH/graftling $SB/g && git -C $SB/g branch -q dev $GBASE && git -C $SB/g worktree add -q $SB/gdev dev || exit 1
  git -C $SB/g remote set-url origin $SB/origin.git
  print -r -- "scratch graftling: main $(git -C $SB/g rev-parse main) | dev $(git -C $SB/g rev-parse dev) | origin main $(git -C $SB/origin.git rev-parse main) dev $(git -C $SB/origin.git rev-parse dev) HEAD -> $(git -C $SB/origin.git symbolic-ref HEAD)"
  print "## setup: STUB claude and ps (fixtures)"
  print -l '#!/bin/zsh' '# STUB claude (rehearsal fixture)' 'case " $* " in' \
    '  *" --version "*) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  *" --input-format stream-json "*) cat > /dev/null; print -r -- '"'"'{"type":"control_response","response":{"subtype":"success","request_id":"catalog","response":{"models":[{"value":"default","displayName":"Default (stub)"},{"value":"opus","displayName":"Opus (stub)","resolvedModel":"claude-opus-5-5","supportedEffortLevels":["low","high"]}]}}}'"'"' ;;' \
    '  *" -p "*) cat > /dev/null; print "READY-612 claude-opus-5-5 LOGGED-IN (stub, rehearsal fixture)" ;;' \
    '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 604's graphtraj wheel and 600's graftling 0.9.1 wheel)"
  W604=$FST/$T604/adoption/wheels-1fdbbca5 W600=$FST/$T600/adoption/wheels-0.9.1; mkdir -p $W604 $W600
  cp -p $REALSTATE/tasks/$T604/adoption/wheels-1fdbbca5/* $W604/ && cp -p $REALSTATE/tasks/$T600/adoption/wheels-0.9.1/* $W600/ || exit 1
  git -C $FH init -q --initial-branch=main 2>/dev/null || { mkdir -p $FH && git -C $FH init -q --initial-branch=main; } || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W604/graphtraj-0.1.0-*.whl $W600/graftling-0.9.1-*.whl || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d $D/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T612 $T516; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ')"
  print "## setup: FIXTURE user catalogs (P)"
  print -l 'version: 1' 'runtimes:' '  claude-main:' '    runtime: claude' '    providers:' '      anthropic:' '        models:' \
    '          opus: {id: claude-opus-5-5, source: manual}' '  pi-opencode:' '    runtime: pi' '    providers:' '      opencode:' \
    '        api_key_env: OPENCODE_API_KEY' '        models:' '          glm: {id: glm-5, source: manual}' > $SB/home/.graphtraj/connections.yml
  print -l 'version: 1' 'runtimes:' '  codex-main:' '    runtime: codex' '    providers:' '      openai:' '        models:' \
    '          gpt: {id: gpt-5, source: manual}' > $SB/home2/.graphtraj/connections.yml
  print -r -- "catalog (choice expected: claude-main anthropic):"; sed 's/^/  /' $SB/home/.graphtraj/connections.yml
} 2>&1 | tee $OUTD/console-setup.txt
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT612_H=$FH ADOPT612_WT=$WT ADOPT612_STUB=$SB/stub ADOPT612_PROJECTS=$SB/projects/-fake ADOPT612_VPROJECT=$SB/vproject
        ADOPT612_SCRATCH=$SB/scr ADOPT612_G=$SB/g ADOPT612_GDEV=$SB/gdev ADOPT612_GURL=$SB/origin.git ADOPT612_UVT=$SB/uvtool-612
        ADOPT612_NOSNAP=1 ADOPT612_GWAIT=2 ADOPT612_CATALOG_HOME=$SB/home "ADOPT612_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print; print -r -- "######## rehearsal: $tag"; env $common ADOPT612_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
RAW=$OUTD/raw; STOPS=$OUTD/raw-stop
{ print "## script hygiene"
  specials=(${(k)parameters[(R)*special*]})
  assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local )?[A-Za-z_][A-Za-z0-9_]*=' $S | sed -E 's/^[ ;({]//; s/^local //; s/=$//')"}})
  hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
  print -r -- "assigned names: ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array, as 593/600/604): ${other:-none}"
  print "\$NAME: followed by a letter (zsh modifier trap): $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "git diff 6c0756c3 78f929ee --name-only: $(git -C $WT diff --name-only 6c0756c3 78f929ee | tr '\n' ' ')| git diff 78f929ee HEAD -- src tests plugins manuals pyproject.toml: $(git -C $WT diff --name-only 78f929ee HEAD -- src tests plugins manuals pyproject.toml | tr '\n' ' ')(empty = TARGET's product)"
  print "## STOP: rel with dev moved"
  echo moved > $SB/gdev/moved.txt && git -C $SB/gdev add moved.txt && git -C $SB/gdev -c user.name=x -c user.email=x@invalid commit -q -m 'dev moved (rehearsal)'
  run $STOPS "rel, dev moved" zsh $S rel
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag v0.10.0 $(git -C $SB/g rev-parse -q --verify refs/tags/v0.10.0 || print absent) branch agent/612 $(git -C $SB/g rev-parse -q --verify refs/heads/agent/612-graftling-0.10.0 || print absent)"
  git -C $SB/gdev reset -q --hard $GBASE
  run $STOPS "rp before rel" zsh $S rp
  run $STOPS "P with a catalog that has no usable entry (STOP)" env ADOPT612_CATALOG_HOME=$SB/home2 zsh $S P
} 2>&1 | tee $OUTD/console-stops.txt
{ for st in 00 rel rel B; do run $RAW $st zsh $S $st; done
  run $STOPS "I before V/GR (STOP, nothing changed)" zsh -fc "print | zsh $S I"
  run $RAW "G (-k: real tests incl. repository fixtures and 611's discovery)" env ADOPT612_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_graphtraj_uses_only_published_agents_names or test_the_mcp_server_lists_subagents_and_tasks_only or test_graphtraj_discovery_keeps_its_document or test_claude_uses_only_the_initialize_catalog or test_native_claude_lifecycle_without_a_task'" zsh $S G
  run $STOPS "rp unconfirmed" zsh $S rp
  run $RAW "rp confirmed" env ADOPT612_PUSH_CONFIRMED=yes zsh $S rp
  run $RAW gh zsh $S gh
  run $RAW "C5 (source git+file:// scratch origin, no tag)" env ADOPT612_SOURCE="git+file://$SB/origin.git" zsh $S C5
} 2>&1 | tee $OUTD/console-release.txt
{ GREC=$(print -l $FST/$T612/adoption/G-*(N/om[1])); print "G record: $GREC"
  [[ -n $GREC ]] && for i in {1..400}; do grep -q '^exit=' $GREC/suite.txt 2>/dev/null && break; sleep 3; done
  print "G suite.txt tail:"; tail -4 $GREC/suite.txt; print "wait.txt:"; cat $GREC/wait.txt
  print "PASSED ids through G's entry:"; grep -hoE '^PASSED tests/[^ ]+' $GREC/shards/*.log(N) | sort -u
  run $RAW GR zsh $S GR
  run $RAW SR zsh $S SR
  run $RAW "suite-base (one real id)" zsh $S suite-base tests/test_runtime_distribution.py::test_wheels_have_separate_owners
  run $RAW V zsh $S V
  print -r -- "77 0:10 $FH/.venv-runtime/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $SB/ps.txt
  run $RAW "STOP: Mpre with a member Worker running (ps FIXTURE line)" zsh $S Mpre; cp -p $RAW/Mpre.txt $STOPS/Mpre.txt
  print -r -- $PSIDLE > $SB/ps.txt
  run $RAW Mpre zsh $S Mpre
  run $RAW I zsh -fc "print | zsh $S I"
  run $STOPS "STOP: I again (backup exists)" zsh -fc "print | zsh $S I"
  run $RAW M zsh $S M
  print "## FIXTURE: Main's transcript after I (M[b] calls), timestamps now"
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ); sleep 1
  print -r -- '{"type":"assistant","timestamp":"'$now'","message":{"content":[{"type":"tool_use","id":"m1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"status","arguments":{}}},{"type":"tool_use","id":"m2","name":"mcp__graphtraj__tasks","input":{"action":"execute","feature":"task_graph","arguments":{"view":"current","details":["612"]}}}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$now'","message":{"content":[{"type":"tool_result","tool_use_id":"m1","content":[{"type":"text","text":"{\"agents\":[]} (fixture)"}]},{"type":"tool_result","tool_use_id":"m2","content":[{"type":"text","text":"{\"tasks\":[] } (fixture)"}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "## FIXTURE: Nr's child record n612, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/612-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n612","agent":"ag-1","parent":"612-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-24T12:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "612"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-24T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-24T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n612-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-612"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -l -- '[Graftling notice from 612-x@advisor · completed · execution 0a1b2c3d]' 'done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"612-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  run $RAW P zsh $S P
  run $RAW "STOP: Pr before P.txt exists (Pr.txt is rewritten by the Pr below)" zsh $S Pr
  print "## REHEARSAL STAND-IN for Main's MCP call: the installed candidate's public CLI from the fake production venv"
  ch=(${=$(sed -n 's/^CHOICE //p' $RAW/P-pre.txt | tail -1)})
  print -r -- "command: (cd $FH && HOME=$SB/home PATH=$SB/stub:... $FRT/bin/graphtraj connections --action discover --runtime ${ch[1]} --provider ${ch[2]}) > $RAW/P.txt"
  (cd $FH && env -i HOME=$SB/home USER=${USER:-x} PATH=$SB/stub:/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 $FRT/bin/graphtraj connections --action discover --runtime ${ch[1]} --provider ${ch[2]}) > $RAW/P.txt 2>$SB/P.err
  print -r -- "graphtraj connections exit=$? | stdout:"; cat $RAW/P.txt; print -r -- "stderr: $(cat $SB/P.err)"
  run $RAW Pr zsh $S Pr
  run $RAW done zsh $S done
  print "## R (rollback) after the adoption, run from the backup's own copy of steps.zsh"
  run $RAW R zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "after R: fake production $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | graphtraj direct_url: $(sed -E 's/.*"url": "([^"]+)".*/\1/' $FRT/lib/python3.13/site-packages/graphtraj-0.1.0.dist-info/direct_url.json)"
} 2>&1 | tee $OUTD/console-adopt.txt
