#!/bin/zsh
# Task 653 rehearsal (Engineer's sandbox only; Main does not run this). Runs the ordered list of steps.zsh through
# `zsh steps.zsh <step>` against scratch copies; real production, <Harness>/graftling, the Harness state and GitHub are
# only read. Two stages, each in the FOREGROUND:
#   zsh rehearse.zsh release   setup + 00 P rel B G (real tests) GR rp gh C5 and their STOPs  -> rehearsal/console-release.txt
#   zsh rehearse.zsh adopt     V Mpre I M Mr N Nr done R I0 and their STOPs (after release) -> rehearsal/console-adopt.txt
#   graftling: a clone of <Harness>/graftling (main = v0.10.2 57bca736 checked out; dev at 9650361e in a second
#     worktree); its origin is a scratch bare repository standing in for GitHub (main = dev = v0.10.2, HEAD -> main, so
#     the tagless C5 install takes main).
#   gh STAND-IN (fixture): answers the Actions API from Task 652's RETAINED run record (run 46041409568, windows-tests,
#     dsh-windows-tests and claude-real-entry, all real Windows results of 9650361e, whose tree equals the release
#     commit's apart from the 6 version/CHANGELOG/PUBLIC_API files), presented as the workflow_dispatch run of the
#     release commit after P's `gh workflow run`. P's push goes to the scratch origin; the judge is real.
#   FAKE PRODUCTION (fixture, built by the real product): $FH with .venv-runtime = 616's REAL graphtraj wheel (4ef36426)
#     + 625's REAL graftling 0.10.2 wheel (copied into the same state paths) + production's click, PyYAML and
#     websockets (copied from <Harness>/.venv-runtime, read only); `graphtraj setup` and the product's own
#     `configuration --write` write .mcp.json, settings.local.json, config.json and the hook copy (from 0.10.2).
#     Task state: copies (task.yml, definitions) of Tasks 653 and 516. One FIXTURE other backup tmp/625/backup, so 00
#     and I report it and I checks it stays untouched.
#   STUBS (fixtures): `claude` (--version; -p answers a stream-json init + READY-653) and `ps` (prints $SB/ps.txt).
# Outputs: rehearsal/console-*.txt, rehearsal/raw/, rehearsal/raw-stop/, with the user's home, the Harness path and
# the scratch root replaced by <HOME>, <Harness> and <SCRATCH> (no user environment detail in committed files).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
STAGE=${1:-}
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${REHEARSE653_REALH:-${WT:h:h:h:h}}           # correction 2: set when rehearsing from a scratch clone of the Worktree
RUN653=$REALH/.graphtraj/core/state/tasks/653-graftling-0-11-0-release-and-production-adoption/realhost/main-raw/windows   # Main's real X records
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=$HOME/miniconda3/bin/python3.13
OUTD=$SD/rehearsal
SB=${${TMPDIR:-/tmp}:A}/r653
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
GBASE=9650361e13d6ef9981c753038469ff3b9e44cfa6
GMAIN0=57bca73657d3135a4504904fcc3f1898c2419766
GCOMMIT=67b0fe9aacc868c9c6b5a2818adc8449514221c4
RUN652=$REALSTATE/tasks/652-graftling-windows-claude-host-polish/realhost/evidence/live/run-46041409568-a1
NEWFX=test_wheels_have_separate_owners             # the GR STOP fixture turns this test's PASSED line into FAILED
T616=616-graphtraj-614-production-adoption; T625=625-graftling-0-10-2-release-and-production-adoption
T653=653-graftling-0-11-0-release-and-production-adoption; T516=516-low-priority-flaky-tests
MAINID=11111111-2222-3333-4444-555555555653         # Main's Session (FIXTURE transcript name)
PSIDLE="1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)"
S=$SD/steps.zsh
RAW=$SB/out/raw; STOPS=$SB/out/raw-stop
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT653_H=$FH ADOPT653_WT=$WT ADOPT653_STUB=$SB/stub ADOPT653_PROJECTS=$SB/projects/-fake ADOPT653_VPROJECT=$SB/vproject
        ADOPT653_SCRATCH=$SB/scr ADOPT653_G=$SB/g ADOPT653_GDEV=$SB/gdev ADOPT653_GURL=$SB/origin.git ADOPT653_UVT=$SB/uvtool-653
        ADOPT653_GH=$SB/stub/gh ADOPT653_POLL_S=1 ADOPT653_APPEAR_S=10 ADOPT653_DONE_S=30
        ADOPT653_NOSNAP=1 ADOPT653_GWAIT=2 "ADOPT653_CLEAN_EXTRA=${extra# }")
run() { local out=$1 tag=$2; shift 2; print; print -r -- "######## rehearsal: $tag"; env $common ADOPT653_OUT=$out "$@"; print -r -- "######## exit=$? ($tag)"; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
tl() {  # FIXTURE transcript lines: $1 = id, $2 = tool name, $3 = input json, $4 = result text (json-escaped)
  local t=$(now)
  print -r -- '{"type":"assistant","timestamp":"'$t'","message":{"content":[{"type":"tool_use","id":"'$1'","name":"'$2'","input":'$3'}]}}' >> $SB/projects/-fake/$MAINID.jsonl
  print -r -- '{"type":"user","timestamp":"'$t'","message":{"content":[{"type":"tool_result","tool_use_id":"'$1'","content":[{"type":"text","text":'$4'}]}]}}' >> $SB/projects/-fake/$MAINID.jsonl
}
scrub() {  # $1 = file or directory under $SB/out -> the same under $OUTD, with user paths replaced
  local src=$1 dst=$OUTD/${1#$SB/out/} f
  # The run's artifacts and job logs are copies of Task 652's retained record: not copied again (the judgements are).
  [[ -d $src ]] && { mkdir -p $dst; for f in $src/**/*(N.); do
      [[ $f == */windows/run-*/(junit|real-entry)(|-a<->)/* || $f == */windows/run-*/*.log || $f == */windows/run-*/jobs.json ]] && continue
      mkdir -p ${$(print -r -- $OUTD/${f#$SB/out/}):h}; scrub $f; done; return; }
  mkdir -p ${dst:h}
  LC_ALL=C sed -e "s|$SB|<SCRATCH>|g" -e "s|${TMPDIR:A}|<TMPDIR>|g" -e "s|$REALH|<Harness>|g" -e "s|$HOME|<HOME>|g" -e "s|${USER:-nouser}|<USER>|g" $src > $dst
}

case $STAGE in
release)
rm -rf $SB $OUTD/raw $OUTD/raw-stop; mkdir -p $SB/stub $SB/gh $SB/projects/-fake $RAW $STOPS
{ print "## setup: graftling scratch clone + bare origin (GitHub stand-in)"
  git clone -q --bare --no-hardlinks $REALH/graftling $SB/origin.git && git -C $SB/origin.git update-ref refs/heads/dev $GMAIN0 \
    && git -C $SB/origin.git update-ref refs/heads/main $GMAIN0 && git -C $SB/origin.git symbolic-ref HEAD refs/heads/main || exit 1
  git -C $SB/origin.git tag -d v0.11.0 > /dev/null 2>&1
  git clone -q --no-hardlinks $REALH/graftling $SB/g && git -C $SB/g checkout -q main && git -C $SB/g reset -q --hard $GMAIN0 \
    && git -C $SB/g branch -q -f dev $GBASE && git -C $SB/g worktree add -q $SB/gdev dev || exit 1
  git -C $SB/g tag -d v0.11.0 > /dev/null 2>&1   # the real repository has it once Main's rel ran; the scratch starts before rel
  git -C $SB/g remote set-url origin $SB/origin.git
  print -r -- "scratch graftling: main $(git -C $SB/g rev-parse main) | dev $(git -C $SB/g rev-parse dev) | origin main $(git -C $SB/origin.git rev-parse main) dev $(git -C $SB/origin.git rev-parse dev) HEAD -> $(git -C $SB/origin.git symbolic-ref HEAD)"
  print "## setup: STUB claude and ps; gh STAND-IN serving Task 652's retained run record (fixtures)"
  print -l '#!/bin/zsh' '# STUB claude (rehearsal fixture)' 'case " $* " in' \
    '  *" --version "*) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' \
    '  *" -p "*) cat > /dev/null; print -r -- '"'"'{"type":"system","subtype":"init","model":"claude-opus-5-5","apiKeySource":"none"}'"'"'; print -r -- '"'"'{"type":"result","result":"READY-653 claude-opus-5-5 (stub, rehearsal fixture)"}'"'"' ;;' \
    '  *) print "stub claude: $*" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "# STUB ps (fixture): the sandbox refuses /bin/ps; prints the fixture listing $SB/ps.txt" "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- $PSIDLE > $SB/ps.txt
  RUNJSON='{"id": 46041409568, "name": "Windows tests", "path": ".github/workflows/windows.yml", "event": "workflow_dispatch", "status": "completed", "conclusion": "success", "head_sha": "'$GCOMMIT'", "run_attempt": 1, "run_started_at": "2026-11-27T17:23:05Z", "html_url": "https://github.com/LUOXIAO92/graftling/actions/runs/46041409568 (FIXTURE: 652 run record)"}'
  print -r -- $RUNJSON > $SB/gh/run.json
  cat > $SB/stub/gh <<EOF
#!/bin/zsh
# gh STAND-IN (rehearsal fixture): Task 652's retained run 46041409568 stands in for the dispatch run of $GCOMMIT.
print -r -- "gh \$*" >> $SB/gh/calls.txt
case "\$1 \$2" in
  "--version "*) print "gh version 0.0.0 (stand-in)" ;;
  "auth status") print "  Logged in to github.com account fixture (stand-in)" ;;
  "workflow run") touch $SB/gh/dispatched; print "Created workflow_dispatch event for windows.yml (stand-in)" ;;
  "run download") n=\${@[(i)-n]}; d=\${@[(i)-D]}; name=\${@[\$((n + 1))]}; dir=\${@[\$((d + 1))]}; mkdir -p \$dir
    case \$name in graftling-windows-junit-*) cp -Rp $RUN652/junit/. \$dir/ ;; graftling-claude-real-entry-*) cp -Rp $RUN652/real-entry/. \$dir/ ;; *) exit 1 ;; esac ;;
  "run rerun") touch $SB/gh/rerun ;;
  api*) ep=\${@[-1]}
    case \$ep in
      *"/actions/runs?head_sha="*) [[ -e $SB/gh/dispatched ]] && print -r -- "{\"workflow_runs\": [\$(<$SB/gh/run.json)]}" || print -r -- '{"workflow_runs": []}' ;;
      */attempts/*/jobs*) cat $RUN652/jobs.json ;;
      */jobs/140649778126/logs) cat $RUN652/windows-tests.log ;;
      */jobs/140649778142/logs) cat $RUN652/claude-real-entry.log ;;
      */actions/runs/46041409568/artifacts*) print -r -- '{"artifacts": [{"name": "graftling-windows-junit-'$GCOMMIT'-1", "expired": false}, {"name": "graftling-claude-real-entry-'$GCOMMIT'-1", "expired": false}]}' ;;
      */actions/runs/46041409568) cat $SB/gh/run.json ;;
      *) print -u2 "stand-in: unknown endpoint \$ep"; exit 1 ;;
    esac ;;
  *) print -u2 "stand-in: unknown gh \$*"; exit 1 ;;
esac
EOF
  chmod +x $SB/stub/claude $SB/stub/ps $SB/stub/gh
  print "## setup: FAKE PRODUCTION $FH (fixture built by the real product from 616's graphtraj 4ef36426 and 625's graftling 0.10.2 wheels)"
  W616=$FST/$T616/adoption/wheels-4ef36426 W625=$FST/$T625/adoption/wheels-0.10.2; mkdir -p $W616 $W625
  cp -p $REALSTATE/tasks/$T616/adoption/wheels-4ef36426/* $W616/ && cp -p $REALSTATE/tasks/$T625/adoption/wheels-0.10.2/* $W625/ || exit 1
  mkdir -p $FH && git -C $FH init -q --initial-branch=main || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W616/graphtraj-0.1.0-*.whl $W625/graftling-0.10.2-*.whl || exit 1
  D=$FRT/lib/python3.13/site-packages; for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d(N) $D/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T653 $T516; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  mkdir -p $FH/tmp/625/backup && print "other backup 625 (FIXTURE)" > $FH/tmp/625/backup/NOTE && touch $FH/tmp/625/backup/COMPLETE
  mkdir -p $FH/.graphtraj/swarm/sessions; : > $SB/projects/-fake/$MAINID.jsonl
  print "fake production: $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"), "click", m.version("click"), "websockets", m.version("websockets"))') | pip check: $($FRT/bin/python -m pip check --disable-pip-version-check 2>&1) | .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json) | hook copy: $(ls $FH/.claude/skills/graphtraj-claude-host/hooks | tr '\n' ' ') | other backups (fixture): $(ls -d $FH/tmp/*/backup | tr '\n' ' ')"
  print "\n## script hygiene"
  for f in $S $0; do
    specials=(${(k)parameters[(R)*special*]})
    assigned=(${(u)${(f)"$(grep -oE '(^|[ ;({])(local (-a )?)?[A-Za-z_][A-Za-z0-9_]*=' $f | sed -E 's/^[ ;({]//; s/^local (-a )?//; s/=$//')"}})
    hits=(${assigned:*specials}); intended=(HOME PATH TERM LANG TMPDIR USER path); other=(${hits:|intended})
    print -r -- "${f:t}: assigned names ${#assigned} | special names among them: ${hits:-none} | other than the intended (clean()'s env -i pass-throughs; path = the PATH array): ${other:-none}"
  done
  print "\$NAME: followed by a letter (zsh modifier trap) in steps.zsh: $(grep -cE '\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]' $S) occurrences"
  print "zsh -n steps.zsh: $(zsh -n $S 2>&1 || true)(empty = OK) | zsh -n rehearse.zsh: $(zsh -n $0 2>&1 || true)(empty = OK)"
  print "user environment details in scripts/adopt-653 (home, user name): $(grep -rlE "$HOME|${USER:-nouser}" $SD --include='*.zsh' --include='*.py' --include='*.md' 2>/dev/null | tr '\n' ' ')(empty = none)"
  print "git diff 5a17543e afaaca41 --name-only: $(git -C $WT diff --name-only 5a17543e afaaca41 | tr '\n' ' ')(= pyproject.toml only)"
  print "git diff afaaca41 HEAD --name-only outside scripts/adopt-653/: $(git -C $WT diff --name-only afaaca41 HEAD | grep -v '^scripts/adopt-653/' | tr '\n' ' ')(= exactly correction 1's tests/test_dsh_runtime.py tests/test_runtime_connections.py)"
  run $RAW "00 pre-rel" zsh $S 00; cp -p $RAW/00.txt $RAW/00-pre-rel.txt
  print "\n## STOP: rel with dev moved (then dev is reset to $GBASE)"
  echo moved > $SB/gdev/moved.txt && git -C $SB/gdev add moved.txt && git -C $SB/gdev -c user.name=x -c user.email=x@invalid commit -q -m 'dev moved (rehearsal)'
  run $STOPS "STOP: rel with dev moved" zsh $S rel
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag v0.11.0 $(git -C $SB/g rev-parse -q --verify refs/tags/v0.11.0 || print absent) branch agent/653 $(git -C $SB/g rev-parse -q --verify refs/heads/agent/653-graftling-0.11.0 || print absent)"
  git -C $SB/gdev reset -q --hard $GBASE
  run $RAW rel zsh $S rel
  run $RAW "rel again (already released)" zsh $S rel
  print "\n## correction 2: 00 after rel (post-rel state: dev = main = release commit, annotated v0.11.0); raw/00.txt is this run"
  run $RAW "00 post-rel" zsh $S 00
  print "\n## STOP (correction 2): 00 in a MIXED state (dev = the release commit, main reset to v0.10.2, the tag present); then main is restored"
  git -C $SB/g reset -q --hard $GMAIN0
  run $STOPS "STOP: 00 mixed (dev = 67b0fe9a, main = 57bca736, v0.11.0 present)" zsh $S 00; mv $STOPS/00.txt $STOPS/00-mixed.txt
  git -C $SB/g reset -q --hard $GCOMMIT
  print -r -- "after the STOP: dev $(git -C $SB/g rev-parse dev) main $(git -C $SB/g rev-parse main) tag $(git -C $SB/g rev-parse -q --verify 'refs/tags/v0.11.0^{commit}')"
  run $RAW B zsh $S B
  run $RAW "STOP: I before V/GR/Windows (nothing changed; no I.txt is written)" zsh -fc "print | zsh $S I"; print -r -- "I.txt in raw/ after the STOP: $([[ -e $RAW/I.txt ]] && print PRESENT || print absent)"
  run $RAW "STOP: rp (confirmed) before the Windows workflow and G/GR passed" env ADOPT653_PUSH_CONFIRMED=yes zsh $S rp; cp -p $RAW/rp.txt $STOPS/rp-before-windows.txt
  print -r -- "after the STOP: origin main $(git -C $SB/origin.git rev-parse main) dev $(git -C $SB/origin.git rev-parse dev) tag v0.11.0 $(git -C $SB/origin.git rev-parse -q --verify refs/tags/v0.11.0 || print absent)"
  run $RAW "P (push the branch to the scratch origin; dispatch and judge through the gh stand-in on 652's retained run record)" zsh $S P
  print -r -- "after P: origin agent/653-graftling-0.11.0 $(git -C $SB/origin.git rev-parse -q --verify refs/heads/agent/653-graftling-0.11.0 || print absent) | origin main $(git -C $SB/origin.git rev-parse main) | gh stand-in calls: $(grep -c . $SB/gh/calls.txt)"
  run $RAW "W (observe the dispatch run again; no push, no dispatch)" zsh $S W
  print "\n## correction 2: W on Main's REAL retained run 46114515028 records (attempt 2 after gh run rerun --failed re-ran only windows-tests), offline through a second gh stand-in"
  print -r -- "## stand-in serves: a2's jobs.json (all jobs labelled run_attempt 2; claude-real-entry and dsh-windows-tests keep started_at 05:59 of attempt 1), the a2 junit artifact, the a1 claude-real-entry artifact under its real name; artifacts list junit-1, junit-2, claude-real-entry-1 (no claude-real-entry-2, as X saw); run_started_at 06:21:58Z (FIXTURE, just before a2's jobs' created_at 06:22:00)"
  mkdir -p $SB/gh2
  print -r -- '{"id": 46114515028, "name": "Windows tests", "path": ".github/workflows/windows.yml", "event": "workflow_dispatch", "status": "completed", "conclusion": "success", "head_sha": "'$GCOMMIT'", "run_attempt": 2, "run_started_at": "2026-11-28T06:21:58Z", "html_url": "https://github.com/LUOXIAO92/graftling/actions/runs/46114515028 (FIXTURE run object; jobs and artifacts are the retained records of Main)"}' > $SB/gh2/run.json
  cat > $SB/stub/gh2 <<EOF2
#!/bin/zsh
# gh STAND-IN 2 (rehearsal fixture): Main's retained records of run 46114515028, attempts 1 and 2.
print -r -- "gh \$*" >> $SB/gh2/calls.txt
A1=$RUN653/run-46114515028-a1 A2=$RUN653/run-46114515028-a2
case "\$1 \$2" in
  "run download") n=\${@[(i)-n]}; d=\${@[(i)-D]}; name=\${@[\$((n + 1))]}; dir=\${@[\$((d + 1))]}; mkdir -p \$dir
    case \$name in
      graftling-windows-junit-$GCOMMIT-2) cp -Rp \$A2/junit/. \$dir/ ;;
      graftling-windows-junit-$GCOMMIT-1) cp -Rp \$A1/junit/. \$dir/ ;;
      graftling-claude-real-entry-$GCOMMIT-1) cp -Rp \$A1/real-entry/. \$dir/ ;;
      *) print -u2 "no artifact matches any of the names or patterns provided"; exit 1 ;;
    esac ;;
  api*) ep=\${@[-1]}
    case \$ep in
      */attempts/2/jobs*) if [[ -e $SB/gh2/rerun-missing ]]; then $CONDA -I -c 'import json, sys; d = json.load(open(sys.argv[1])); [j.update(started_at="2026-11-28T06:22:05Z") for j in d["jobs"] if j["name"] == "claude-real-entry"]; print(json.dumps(d))' \$A2/jobs.json; else cat \$A2/jobs.json; fi ;;
      */jobs/140890686467/logs) cat \$A2/windows-tests.log ;;
      */jobs/140890687998/logs) cat \$A2/claude-real-entry.log ;;
      */actions/runs/46114515028/artifacts*) print -r -- '{"artifacts": [{"name": "graftling-windows-junit-$GCOMMIT-1", "expired": false}, {"name": "graftling-windows-junit-$GCOMMIT-2", "expired": false}, {"name": "graftling-claude-real-entry-$GCOMMIT-1", "expired": false}]}' ;;
      */actions/runs/46114515028) cat $SB/gh2/run.json ;;
      *) print -u2 "stand-in 2: unknown endpoint \$ep"; exit 1 ;;
    esac ;;
  *) print -u2 "stand-in 2: unknown gh \$*"; exit 1 ;;
esac
EOF2
  chmod +x $SB/stub/gh2
  run $SB/out/raw-w2 "W 46114515028 (Main's real records; expected PASS, windows-tests from attempt 2, claude-real-entry and dsh-windows-tests from attempt 1)" env ADOPT653_GH=$SB/stub/gh2 zsh $S W 46114515028
  grep -h '^EVIDENCE \|^VERDICT ' $SB/out/raw-w2/W.txt
  print "\n## STOP (correction 2): the same run, but claude-real-entry RE-RAN in attempt 2 (its started_at moved after run_started_at, FIXTURE) and its own artifact -2 is missing: the attempt-1 artifact must NOT stand in"
  touch $SB/gh2/rerun-missing
  run $STOPS/w2-rerun-missing "STOP: W with a re-run job whose own artifact is missing (expected FAIL)" env ADOPT653_GH=$SB/stub/gh2 zsh $S W 46114515028
  grep -h '^EVIDENCE \|^VERDICT ' $STOPS/w2-rerun-missing/W.txt
  rm -f $SB/gh2/rerun-missing
  run $RAW "STOP: rp (confirmed) before G/GR passed (Windows passed)" env ADOPT653_PUSH_CONFIRMED=yes zsh $S rp; cp -p $RAW/rp.txt $STOPS/rp-before-GR.txt
  print -r -- "\n## G: the step's own process starts at $(date +%T); it must exit only after its shards end, with the verdict as its last output"
  print -r -- "## G queue: a ps FIXTURE line shows another suite ('-m pytest') for ~5 s; G must wait for it in its own process"
  print -r -- "88 python -m pytest -q (ps FIXTURE: another suite)" > $SB/ps.txt; ( sleep 5; print -r -- $PSIDLE > $SB/ps.txt ) &
  run $RAW "G (-k: REAL tests incl. a repository fixture, correction 1's 3 ids, 641's github_backup tests, the intent and MCP/discovery tests)" env ADOPT653_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_host_operation_os_error_keeps_reply_and_logs_traceback or test_agents_control_dsh_without_task_or_archive or test_intent_queries_find_create or test_the_mcp_server_lists_subagents_and_tasks_only or test_graphtraj_discovery_keeps_its_document or test_github_backup'" zsh $S G
  GREC=$(print -l $FST/$T653/adoption/G-*(N/om[1]))
  print -r -- "## G: the step's process exited at $(date +%T) | wait.txt: $(tr '\n' ';' < $GREC/wait.txt) | suite.txt last line: $(tail -1 $GREC/suite.txt)"
  print "## G record's PASSED lines (-rA, the per-test outcomes):"; grep -hoE '^PASSED tests/.*' $GREC/shards/*.log(N) | sort -u
  print "\n## STOP: GR on a COPY of that record in which $NEWFX's PASSED line is replaced by a FAILED line (FIXTURE: a NEW failure)"
  FX=$FST/$T653/adoption/G-99999999T999999-fixture; cp -Rp $GREC $FX && touch $FX
  for f in $FX/shards/*.log(N); do $CONDA -I -c 'import re, sys; p, s = sys.argv[1], sys.argv[2]; t = open(p).read(); open(p, "w").write(re.sub(r"(?m)^PASSED (\S*" + s + r"\S*)$", r"FAILED \1 - AssertionError (FIXTURE)", t))' $f $NEWFX; done
  print -r -- "fixture lines: $(grep -h -F -- "$NEWFX" $FX/shards/*.log | grep -E '^(PASSED|FAILED)' | tr '\n' ';')"
  run $STOPS "STOP: GR with a NEW failure (fixture record)" zsh $S GR
  mv $FX $SB/G-fixture-set-aside
  run $RAW "GR alone (re-judging the real rehearsal record; G already ran it at its end)" zsh $S GR
  print "\n## STOP (correction 1): the product guard with one EXTRA changed file beyond scripts/adopt-653/ and the two allowed tests (a scratch clone of this Worktree's HEAD plus one commit to tests/test_tool_name_592.py)"
  git clone -q $WT $SB/wt-extra && print "# extra change (rehearsal)" >> $SB/wt-extra/tests/test_tool_name_592.py \
    && git -C $SB/wt-extra -c user.name=x -c user.email=x@invalid commit -qam 'extra change (rehearsal)' || exit 1
  run $STOPS "STOP: B with an extra changed file (guard; nothing built)" env ADOPT653_WT=$SB/wt-extra zsh $SB/wt-extra/scripts/adopt-653/steps.zsh B
  print -r -- "wheels after the STOP (unchanged since B): $(ls $FST/$T653/adoption/wheels-0.11.0 $FST/$T653/adoption/wheels-afaaca41 | tr '\n' ' ')"
  run $RAW "STOP: rp unconfirmed (after Windows and GR passed; rp.txt is rewritten by the confirmed rp below)" zsh $S rp; cp -p $RAW/rp.txt $STOPS/rp-unconfirmed.txt
  run $RAW "rp confirmed" env ADOPT653_PUSH_CONFIRMED=yes zsh $S rp
  run $RAW gh zsh $S gh
  run $RAW "C5 (FOREGROUND; source git+file:// scratch origin, no tag)" env ADOPT653_SOURCE="git+file://$SB/origin.git" zsh $S C5
} > $SB/out/console-release.txt 2>&1
scrub $SB/out/console-release.txt; scrub $RAW; scrub $STOPS; scrub $SB/out/raw-w2; tail -3 $OUTD/console-release.txt ;;

adopt)
[[ -d $FH && -e $RAW/GR.ok ]] || { print "run the release stage first"; exit 1; }
{ run $RAW V zsh $S V
  print -r -- "77 0:10 $FH/.venv-runtime/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $SB/ps.txt
  run $RAW "STOP: Mpre with a member Worker running (ps FIXTURE line)" zsh $S Mpre; cp -p $RAW/Mpre.txt $STOPS/Mpre.txt
  print -r -- $PSIDLE > $SB/ps.txt
  run $RAW Mpre zsh $S Mpre
  run $RAW I zsh -fc "print | zsh $S I"
  print -r -- "hook copy after I: $(diff -rq $SB/scr/backup/plugin $FH/.claude/skills/graphtraj-claude-host 2>&1 | tr '\n' ' ')"
  run $STOPS "STOP: I again (backup exists)" zsh -fc "print | zsh $S I"
  run $RAW M zsh $S M
  print "\n## FIXTURE: Main's transcript after I (M[b] calls, preceded by Claude Code's ToolSearch select:), timestamps now"
  sleep 1
  tl ts1 ToolSearch '{"query":"select:mcp__graphtraj__subagents","max_results":1}' '"(fixture)"'
  tl m1 mcp__graphtraj__subagents '{"action":"execute","feature":"status","arguments":{}}' '"{\"agents\":[]} (fixture)"'
  tl m2 mcp__graphtraj__tasks '{"action":"execute","feature":"task_graph","arguments":{"view":"current","details":["653"]}}' '"{\"tasks\":[]} (fixture)"'
  run $RAW Mr zsh $S Mr
  run $RAW N zsh $S N
  print "\n## FIXTURE: Nr's child record n653, member mapping/end, archives, Main's saved notice/reply/swarm result"
  CA=$FH/.graphtraj/swarm/control/agents; MS=$FH/.graphtraj/core/runner/sessions/653-x@advisor; SS=$FH/.graphtraj/swarm/sessions
  mkdir -p $CA $MS $SS/s-member $SS/s-child
  print -r -- '{"name":"n653","agent":"ag-1","parent":"653-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}],"retired_at":"2026-11-28T16:00:00Z"}' > $CA/ag-1.json
  print -l 'session: {id: "claude:m-1"}' 'task_id: "653"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $MS/mapping.yml
  print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $MS/execution.yml
  print -r -- '{"header":{"id":"claude:m-1"}}' > $SS/s-member/session.jsonl
  print -r -- '{"type":"assistant","timestamp":"2026-11-28T16:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__subagents","input":{"action":"execute","feature":"create"}}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"type":"user","timestamp":"2026-11-28T16:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]}]}}' >> $SS/s-member/session.jsonl
  print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $SS/s-child/session.jsonl
  print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n653-tool && sleep 20"}}]}}' >> $SS/s-child/session.jsonl
  print -r -- 'member reply (fixture): last_message "DONE-653"; status: {"configuration": "opus_coding_team.advisor", "model": "claude-opus-5-5"}' > $RAW/N-reply.txt
  print -r -- '[Graftling notice from 653-x@advisor · completed · execution 0a1b2c3d] done (fixture)' > $RAW/N-main-notice.txt
  print -r -- '{"tasks":[{"agent":"ag-member-1","alias":"653-x@advisor"}]} (fixture)' > $RAW/N.txt
  run $RAW Nr zsh $S Nr
  run $RAW done zsh $S done
  print "\n## R (rollback) after the adoption, run from the backup's own copy of steps.zsh"
  run $RAW R zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "after R: fake production $($FRT/bin/python -I -c 'import importlib.metadata as m; print("graphtraj", m.version("graphtraj"), "graftling", m.version("graftling"))') | graftling direct_url: $(sed -E 's/.*"url": "([^"]+)".*/\1/' $FRT/lib/python3.13/site-packages/graftling-0.10.2.dist-info/direct_url.json 2>&1)"
  print "\n## I0 after R (sets the rolled-back run aside by MOVES), then I0 again (nothing to set aside)"
  run $RAW I0 zsh $S I0
  print -r -- "after I0: $(ls $SB/scr | tr '\n' ' ') | run1: $(ls $RAW/run1 2>/dev/null | tr '\n' ' ') | other backups (fixture): $(ls $FH/tmp/*/backup | tr '\n' ' ')"
  cp -p $RAW/I0.txt $RAW/I0-first.txt
  run $RAW "I0 again (I0.txt is rewritten; the first is I0-first.txt)" zsh $S I0
} > $SB/out/console-adopt.txt 2>&1
scrub $SB/out/console-adopt.txt; rm -rf $OUTD/raw $OUTD/raw-stop; scrub $RAW; scrub $STOPS; tail -3 $OUTD/console-adopt.txt ;;

*) print "usage: zsh $0 release|adopt"; exit 2 ;;
esac
