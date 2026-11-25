#!/bin/zsh
# Task 616 rehearsal (Engineer's sandbox only; Main does not run this). Runs the ordered list of steps.zsh through
# `zsh steps.zsh <step>` against scratch copies; the Harness state, <Harness>/graftling and Task 614's record are only read.
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 612's REAL graphtraj wheel (78f929ee)
#     + 612's REAL graftling 0.10.0 wheel (copied into the same state paths) + conda's click and PyYAML + websockets 16.1.1
#     from PyPI (FIXTURE: this sandbox may not read production's site-packages; the version production's test
#     interpreter recorded in 614's run.txt; sha256 = PyPI's digest). `graphtraj setup` and the product's own
#     `configuration --write` write .mcp.json, settings.local.json, config.json and the hook copy.
#     Task state: copies (task.yml, definitions) of Tasks 616 and 516.
#   FIXTURE roles and catalog for P: roles.yml (claude -> catalog anthropic, routed -> a gateway keyed by the NAME
#     FIXTURE616_KEY, inline without a provider) and $SB/home/.graphtraj/connections.yml.
#   STUBS (fixtures): `claude` (--version; -p answers a stream-json init + READY-616) and `ps` (prints $SB/ps.txt).
#   REAL: B's wheel build and comparisons (incl. 612's graftling wheel vs git archive v0.10.0 of <Harness>/graftling);
#     GR614 on Task 614's REAL record; V (product regeneration of the hook copy, graphtraj-mcp, v616.py mcp and bound);
#     I's backup and force-reinstall of the graphtraj wheel; P's code/contract/catalog read and role_models; R from the
#     backup's own copy; I0's move after R.
#   STAND-IN for Main's MCP call (labelled): graftling's handle_request bound to GraphTraj's backend in the fake
#     production venv (the native host's binding of a Main), execute models {runtime: claude}; its document is P.txt.
#   FIXTURES (labelled): Main's transcript lines (Mr: ToolSearch select: + M[b] calls; Pr: ToolSearch + the models
#     call), Nr's child/member records and Main's saved notice, reply and swarm result.
# Outputs: rehearsal/console.txt, rehearsal/raw/, rehearsal/raw-stop/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
CS=/Users/luoxiao/miniconda3/lib/python3.13/site-packages
WS=${ADOPT616R_WS:-${TMPDIR:A}/ws-dl-616/websockets-16.1.1-cp313-cp313-macosx_11_0_arm64.whl}
WSSHA=cd2ca96a082a36964aca83e992f72abeb61b7306c1a6cba4c7d06a7b93750cac
OUTD=$SD/rehearsal
SB=${${TMPDIR:-/tmp}:A}/r616
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
T612=612-graftling-provider-release-and-production-adoption; T616=616-graphtraj-614-production-adoption; T516=516-low-priority-flaky-tests
R614=$REALSTATE/tasks/614-graphtraj-subagents-models-discovery/realhost/G-20261125T030159
MAINID=11111111-2222-3333-4444-555555555616         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB/stub $SB/projects/-fake $SB/home/.graphtraj $OUTD
S=$SD/steps.zsh
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
{ print "## setup: STUB claude and ps (fixtures)"
  print -l '#!/bin/zsh' '# STUB claude (rehearsal fixture)' 'case " $* " in' \
    '  *" --version "*) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  *" -p "*) cat > /dev/null; print -r -- '"'"'{"type":"system","subtype":"init","model":"claude-opus-5-5","apiKeySource":"none"}'"'"'; print -r -- '"'"'{"type":"result","result":"READY-616 claude-opus-5-5 (stub, rehearsal fixture)"}'"'"' ;;' \
    '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 612's graphtraj 78f929ee and graftling 0.10.0 wheels)"
  W612=$FST/$T612/adoption; mkdir -p $W612/wheels-78f929ee $W612/wheels-0.10.0
  cp -p $REALSTATE/tasks/$T612/adoption/wheels-78f929ee/* $W612/wheels-78f929ee/ && cp -p $REALSTATE/tasks/$T612/adoption/wheels-0.10.0/* $W612/wheels-0.10.0/ || exit 1
  [[ $(shasum -a 256 $WS | cut -d' ' -f1) == $WSSHA ]] || { print "STOP: websockets fixture wheel $WS missing or not $WSSHA"; exit 1; }
  mkdir -p $FH && git -C $FH init -q --initial-branch=main || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps \
    $W612/wheels-78f929ee/graphtraj-0.1.0-*.whl $W612/wheels-0.10.0/graftling-0.10.0-*.whl $WS || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info'; do cp -Rp $CS/$~d $D/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T616 $T516; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"), "websockets", m.version("websockets"))') | pip check: $($FRT/bin/python -m pip check --disable-pip-version-check 2>&1) | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ')"
  print "## setup: FIXTURE user catalog and roles (P)"
  print -l 'version: 1' 'runtimes:' '  claude-main:' '    runtime: claude' '    providers:' '      anthropic:' '        models:' \
    '          opus: {id: claude-opus-5-5, source: manual, supported_efforts: [low, medium, high]}' \
    '      gw616:' '        base_url: https://gateway-616.invalid/v1' '        api_key_env: FIXTURE616_KEY' '        models:' \
    '          sonnet: {id: claude-sonnet-5-5, source: manual}' > $SB/home/.graphtraj/connections.yml
  sed 's/^/  /' $SB/home/.graphtraj/connections.yml
  (cd $FH && cl HOME=$SB/home $FRT/bin/python -I -c 'import sys, yaml
from pathlib import Path
from graphtraj.configuration.project_roles import roles_file
p = roles_file(Path(sys.argv[1]))
names = {"claude": {"connection": "claude-main/anthropic/opus"}, "routed": {"connection": "claude-main/gw616/sonnet"},
         "inline": {"runtime": "claude", "model": "claude-haiku-5-5"}}
print("roles before (setup):", p, sorted((yaml.safe_load(p.read_text()) or {}).get("roles", {})) if p.exists() else "none")
p.write_text(yaml.safe_dump({"roles": names, "role_tree": {n: {} for n in names}}, sort_keys=False))
print("roles fixture written:", sorted(names))' $FH) || exit 1
} 2>&1 | tee $OUTD/console.txt
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT616_H=$FH ADOPT616_WT=$WT ADOPT616_STUB=$SB/stub ADOPT616_PROJECTS=$SB/projects/-fake ADOPT616_VPROJECT=$SB/vproject
        ADOPT616_VHOME=$SB/vhome-616 ADOPT616_SCRATCH=$SB/scr ADOPT616_G=$REALH/graftling ADOPT616_R614=$R614
        ADOPT616_CATALOG_HOME=$SB/home "ADOPT616_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print; print -r -- "######## rehearsal: $tag"; env $common ADOPT616_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
RAW=$OUTD/raw; STOPS=$OUTD/raw-stop
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
tl() {  # FIXTURE transcript lines: $1 = id, $2 = tool name, $3 = input json, $4 = result text (json-escaped)
  local t=$(now)
  print -r -- '{"type":"assistant","timestamp":"'$t'","message":{"content":[{"type":"tool_use","id":"'$1'","name":"'$2'","input":'$3'}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$t'","message":{"content":[{"type":"tool_result","tool_use_id":"'$1'","content":[{"type":"text","text":'$4'}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
}
{ print "\n## script hygiene"
  for f in $S $0; do
    specials=(${(k)parameters[(R)*special*]})
    assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local (-a )?)?[A-Za-z_][A-Za-z0-9_]*=' $f | sed -E 's/^[ ;({]//; s/^local (-a )?//; s/=$//')"}})
    hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
    print -r -- "${f:t}: assigned names ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array): ${other:-none}"
  done
  print "zsh -n steps.zsh: $(zsh -n $S 2>&1 || true)(empty = OK) | python compile v616.py p616.py: $($CONDA -I -m py_compile $SD/v616.py $SD/p616.py 2>&1)(empty = OK)"
  print "git diff 78f929ee 4ef36426 --name-only -- src tests plugins manuals pyproject.toml: $(git -C $WT diff --name-only 78f929ee 4ef36426 -- src tests plugins manuals pyproject.toml | tr '\n' ' ')"
  run $RAW 00 zsh $S 00
  run $RAW B zsh $S B
  run $STOPS "STOP: I before V/GR614 (nothing changed)" zsh -fc "print | zsh $S I"
  run $RAW "GR614 (Task 614's REAL record)" zsh $S GR614
  run $RAW V zsh $S V
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
  tl m2 mcp__graphtraj__tasks '{"action":"execute","feature":"task_graph","arguments":{"view":"current","details":["616"]}}' '"{\"tasks\":[]} (fixture)"'
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "\n## FIXTURE: Nr's child record n616, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/616-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n616","agent":"ag-1","parent":"616-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-25T12:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "616"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-25T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-25T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n616-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-616"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -r -- '[Graftling notice from 616-x@advisor · completed · execution 0a1b2c3d] done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"616-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  run $RAW P zsh $S P
  run $STOPS "STOP: Pr before P.txt exists (Pr.txt is rewritten by the Pr below)" zsh $S Pr; cp -p $RAW/Pr.txt $STOPS/Pr.txt
  print "\n## REHEARSAL STAND-IN for Main's MCP call: graftling's handle_request bound to GraphTraj's backend in the fake production venv (4ef36426 after I), as the native host binds a Main; execute models {runtime: claude}"
  sleep 1
  (cd $FH && cl HOME=$SB/home $FRT/bin/python -I -c 'import json, sys
from pathlib import Path
from graftling import Caller, bind
from graftling.discovery import handle_request
from graphtraj.interfaces.agents import GraphTrajAgents
root = Path(sys.argv[1]).resolve()
call = bind(GraphTrajAgents(root, root), Caller("claude-native", None, "stand-in-616", "claude"))
answer = handle_request({"action": "execute", "feature": "models", "arguments": {"runtime": "claude"}}, call)
print(json.dumps(answer.document))
print("is_error", answer.failed, file=sys.stderr)' $FH) > $RAW/P.txt 2> $SB/P.err
  print -r -- "stand-in exit=$? | stderr: $(cat $SB/P.err) | P.txt:"; cat $RAW/P.txt
  print "## FIXTURE: Main's transcript lines for that call (ToolSearch select: + the models call; result = P.txt)"
  tl ts2 ToolSearch '{"query":"select:mcp__graphtraj__subagents","max_results":1}' '"(fixture)"'
  tl p1 mcp__graphtraj__subagents '{"action":"execute","feature":"models","arguments":{"runtime":"claude"}}' "$($CONDA -I -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' $RAW/P.txt)"
  run $RAW Pr zsh $S Pr
  run $RAW done zsh $S done
  print "\n## R (rollback) after the adoption, run from the backup's own copy of steps.zsh"
  run $RAW R zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "after R: fake production $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | graphtraj direct_url: $(sed -E 's/.*"url": "([^"]+)".*/\1/' $FRT/lib/python3.13/site-packages/graphtraj-0.1.0.dist-info/direct_url.json)"
  print "\n## I0 after R (sets the rolled-back run aside by MOVES), then I0 again (nothing to set aside)"
  run $RAW I0 zsh $S I0
  print -r -- "after I0: $(ls $SB/scr | tr '\n' ' ') | run1: $(ls $RAW/run1 2>/dev/null | tr '\n' ' ')"
  cp -p $RAW/I0.txt $RAW/I0-first.txt
  run $RAW "I0 again (I0.txt is rewritten; the first is I0-first.txt)" zsh $S I0
} 2>&1 | tee -a $OUTD/console.txt
