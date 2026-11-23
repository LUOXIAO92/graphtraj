#!/bin/zsh
# Rehearsal of adopt-593/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (modelled on adopt-579's).
# Starts no real host and never touches production, <Harness>/graftling, GitHub or GraphTraj dev:
# - graftling: a scratch clone of <Harness>/graftling put back to the state at dispatch (dev = 49f97004 checked out in a
#   linked worktree as on the real host, main = v0.8.0 in the main worktree, no v0.9.0, no release branch); its `origin`
#   is a scratch bare repository, so the confirmed rp pushes there and gh reads it with ls-remote in place of GitHub.
#   rel fetches the bundle into it. Further scratch clones rehearse dev moved (clean merge), a conflicting dev (worktree
#   and no-worktree paths), dev without the base and a wrong existing v0.9.0.
# - GraphTraj: a scratch clone of this Worktree whose local dev is 3eb21101 (the candidate's product: 593 changes none).
# - fake production: graphtraj wheel of eb009725 + graftling wheel of the real v0.8.0 (git archive root, read only),
#   click, yaml and websockets copied from production .venv-runtime (read only); its plugin written by that 0.8.0, so
#   V and I meet 591's real host_context.mjs change; every Task's task.yml and definitions copied (read only).
# - `claude`, `codex` and `ps` are stubs on PATH (ps can be made to fail for the G negative). The MCP server, the Codex
#   hooks entry, plugin regeneration and the old-name scan are REAL (scratch venv and fake production venv).
# - ADOPT593_PART=release stops after suite-base (the early HEAD: 00, scan, rel, rp, gh, B, G, GR, SR, suite-base).
# - G is rehearsed through its real entry (run_test_shards.py, 6 shards) with `-k` selecting real tests, including ones
#   that use the repository's fixtures (built_wheel, the Claude CLI fixture; not --collect-only), first queued behind a
#   simulated running suite, with a credential-like variable exported that must not reach it; GR then reads that record.
#   SR and suite-base run on fixture records and one real id. Nr runs on a fixture child record and archives.
#   zsh scripts/adopt-593/rehearse.zsh
set -u
setopt no_bg_nice   # the simulated suite runs in the background; renicing is refused in a sandbox
SD=${0:A:h}
WT=${SD:h:h}
F=${${TMPDIR:-/tmp}:A}/${ADOPT593_REHEARSAL_NAME:-adopt593-rehearsal}
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/593
OB=$FH/tmp/579   # 579's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=$REALH/graftling
REALSTATE=$REALH/.graphtraj/core/state
GC=7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9      # graftling 0.9.0 (593), in the bundle only
GBASE=49f97004a86cc245ad32515b9dd056d7092b08f7
GOLD=542a81df0c941f5b1a425d9807681b2a38daa87c    # v0.8.0
NEW=3eb21101b920d94da057566c9cfdc3c81b6acbfb     # the candidate's product = GraphTraj dev 3eb21101
OLD=eb00972580b0f8bb28dfc7f0da57a52ccafeb18f
DEV=3eb21101                                     # GraphTraj dev at dispatch
NR=89069722+LUOXIAO92@users.noreply.github.com
FG=$F/graftling          # scratch graftling repository (main worktree: main)
FGD=$F/graftling-dev     # its linked worktree with dev checked out
FWT=$F/wt                # scratch GraphTraj clone (dev = 3eb21101)
export ADOPT593_H=$FH ADOPT593_BASE=$FB ADOPT593_RT=$FRT ADOPT593_PNPM_SHIM=$F/no-shim ADOPT593_STUB=$F/stub ADOPT593_WT=$FWT ADOPT593_PROJECTS=$F/projects/-fake ADOPT593_WAIT=1 ADOPT593_OLDBASE=$OB ADOPT593_G=$FG ADOPT593_VPROJECT=$FB/vproject ADOPT593_GURL=$F/remote.git ADOPT593_GHROOT=$F/ghroot ADOPT593_GWAIT=2
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=593-graftling-0-9-0-release-and-production-adoption
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-${NEW[1,8]}
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }
# A scratch graftling clone at the dispatch state: main = v0.8.0 (main worktree), dev = $GBASE (linked worktree $2 when
# given), no v0.9.0, no release branch, origin = $3 when given.
gclone() {
  local d=$1 wt=${2:-} origin=${3:-}
  git clone -q --no-hardlinks $REALG $d || return 1
  git -C $d checkout -q --detach && git -C $d branch -q -f main $GOLD && git -C $d checkout -q main && git -C $d branch -q -f dev $GBASE
  git -C $d tag -d v0.9.0 > /dev/null 2>&1; git -C $d branch -q -D agent/593-graftling-0.9.0 > /dev/null 2>&1
  git -C $d config user.name rehearsal; git -C $d config user.email rehearsal@invalid
  [[ -n $wt ]] && git -C $d worktree add -q $wt dev
  if [[ -n $origin ]]; then git -C $d remote set-url origin $origin; else git -C $d remote remove origin; fi
  return 0
}

head1 "empty base: $F removed; zsh -n of every zsh file"
[[ -e $F ]] && chmod -R u+w $F; rm -rf $F; mkdir -p $F/stub $F/oldsrc $F/oldg $F/oldwheels $FH $OB/backup $F/projects/-fake
for z in $SD/*.zsh; do zsh -n $z; check "zsh -n ${z:t}" [ $? -eq 0 ]; done
check "base $FB absent before 00" [ ! -e $FB ]
print "Worktree HEAD $(git -C $WT rev-parse HEAD) | candidate $NEW | graftling repository read only: $REALG (dev $(git -C $REALG rev-parse dev), main $(git -C $REALG rev-parse main))"

head1 "setup: scratch graftling (dev = ${GBASE[1,8]} in a linked worktree, main = v0.8.0, origin = scratch bare), scratch GraphTraj (dev = $DEV)"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-before.txt
gclone $FG $FGD $F/remote.git
git clone -q --bare --no-hardlinks $FG $F/remote.git && git -C $F/remote.git symbolic-ref HEAD refs/heads/main
git -C $F/remote.git tag -d v0.9.0 > /dev/null 2>&1; true
print "scratch graftling: dev $(git -C $FG rev-parse dev) main $(git -C $FG rev-parse main) v0.9.0 $(git -C $FG rev-parse -q --verify refs/tags/v0.9.0 || print absent) | origin $(git -C $FG remote get-url origin) | worktrees: $(git -C $FG worktree list | wc -l | tr -d ' ')"
git clone -q --shared --no-checkout $WT $FWT && git -C $FWT checkout -q -b cand $(git -C $WT rev-parse HEAD) && git -C $FWT branch -q -f dev $DEV
print "scratch GraphTraj: HEAD $(git -C $FWT rev-parse HEAD) dev $(git -C $FWT rev-parse dev)"

head1 "setup: fake production = graphtraj ${OLD[1,8]} + graftling v0.8.0, plugin, configuration; stubs"
cat > $F/stub/claude <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "2.1.325 (stub Claude Code)" ;;
  plugin) print "✔ Validation passed (stub)" ;;
  -p) in=$(cat); tag=$(print -r -- "$in" | sed -n 's/.*Line 1: \([A-Z-]*\) followed.*/\1/p')
      /Users/luoxiao/miniconda3/bin/python3.13 -I -c '
import json, os
try: servers = sorted((json.load(open(".mcp.json")).get("mcpServers") or {}))
except Exception: servers = []
tools = ["Bash"] + [f"mcp__{s}__{t}" for s in servers for t in ("agents", "tasks")]
print(json.dumps({"type": "system", "subtype": "init", "plugins": [], "mcp_servers": [{"name": s, "status": "connected"} for s in servers], "tools": tools, "plugin_warnings": []}))'
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-593-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.171.0 (stub)" ;;
  exec) print -u2 "model: gpt-5.5-codex (stub configured model)"; print "CODEX-593-OK" ;;
  *) print "stub codex: $*" ;;
esac
EOF
# dsh stub: `dsh plugin --profile P add <url>` installs the default branch of <url> (here a local bare repository) the
# way DSH registers a package whose root package.json declares dsh.bundle; without it, a plain dependency.
cat > $F/stub/dsh <<'EOF'
#!/bin/zsh
if [[ $1 == --version ]]; then print "dsh 0.2.2-rc.5 (stub)"; exit 0; fi
if [[ $1 == plugin && $2 == --profile && $4 == add ]]; then
  P=$3 U=$5 D=$DSH_HOME/profiles/$3
  mkdir -p $D/node_modules/pkg || exit 1
  git --git-dir=$U archive HEAD | tar -x -C $D/node_modules/pkg || exit 1
  name=$(/Users/luoxiao/miniconda3/bin/python3.13 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["name"] if "dsh" in d and "bundle" in d["dsh"] else "")' $D/node_modules/pkg/package.json 2>/dev/null)
  if [[ -n $name ]]; then mv $D/node_modules/pkg $D/node_modules/$name; bundles="\"@deepseek-ai/dsh-base\", \"$name\""
    print "dependencies:\n+ $name (stub)"
  else rm -rf $D/node_modules/pkg; bundles='"@deepseek-ai/dsh-base"'; print "WARN declares no dsh.bundle — installed as a plain dependency (stub)"; name=placeholder; fi
  print "{\"dsh\": {\"profile\": {\"bundles\": [$bundles]}}, \"dependencies\": {\"$name\": \"$U\"}}" > $D/package.json
  exit 0
fi
if [[ $1 == --profile && $3 == --dump-config ]]; then print "# == graftling-dsh"; print "- id: agents-host"; print "  name: graftling-dsh"; exit 0; fi
print "stub dsh: $*"
EOF
chmod +x $F/stub/claude $F/stub/codex $F/stub/dsh
git -C $WT archive $OLD | tar -x -C $F/oldsrc
git -C $REALG archive v0.8.0 | tar -x -C $F/oldg
$CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $F/oldwheels $F/oldsrc $F/oldg
ls $F/oldwheels
git -C $FH init -q --initial-branch=main; print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
$CONDA -m venv $FRT
$FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $F/oldwheels/*.whl
D=$FRT/lib/python3.13/site-packages
for d in click click-8.5.0.dist-info yaml _yaml pyyaml-6.0.3.dist-info websockets websockets-16.1.1.dist-info; do cp -Rp $REALS/$d $D/; done
(cd $FH && print y | $FRT/bin/graphtraj setup) | tail -2
for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
  $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c
done
grep -h 'state:' $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N)
(cd $FH && $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $F/stub/claude --write) > /dev/null
$CONDA -I -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["enabledMcpjsonServers"]=["graphtraj"]; d["enableAllProjectMcpServers"]=True; open(p,"w").write(json.dumps(d, indent=2)+"\n")' $FH/.claude/settings.local.json
print "fake production .mcp.json servers: $($CONDA -I -c 'import json,sys; print(sorted(json.load(open(sys.argv[1]))["mcpServers"]))' $FH/.mcp.json)"
FS=$FH/.graphtraj/core/state
# production Task state (read only; APFS clones): every Task's task.yml and definitions/, the Worldline, the task index
rm -rf $FS/tasks $FS/worldline; mkdir -p $FS/tasks
cp -cRp $REALSTATE/worldline $FS/ && cp -cp $REALSTATE/task-index.json(N) $FS/
for d in $REALSTATE/tasks/[^.]*(N/); do
  mkdir $FS/tasks/$d:t && cp -cp $d/task.yml $d/task.md(N) $FS/tasks/$d:t/
  [[ -d $d/definitions ]] && cp -cRp $d/definitions $FS/tasks/$d:t/
done
print 'stopped: false' > $ST/$TASK/execution-budget.yml
print "fake production Task state: $(print -l $FS/tasks/[^.]*(N/) | wc -l | tr -d ' ') Task directories (copied, read only)"
print "579 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/579 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
mkdir -p $FH/.graphtraj/swarm/sessions $FH/.graphtraj/swarm/control
MAINID=11111111-2222-3333-4444-555555555555
: > $F/projects/-fake/$MAINID.jsonl
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
print -l "# Fake Harness rules" "This distinctive Harness instruction line must never reach the isolated project answer." > $FH/AGENTS.md
cat > $F/stub/ps <<EOF2
#!/bin/zsh
if [[ -e $F/ps.fail ]]; then print -u2 "ps: operation not permitted (rehearsal)"; exit 1; fi
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
if [[ "\$*" == *"lstart="* ]]; then exit 0; fi
if [[ "\$*" == *"stat="* ]]; then exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF2
chmod +x $F/stub/ps
print -r -- "$HOSTLINE" > $F/ps.txt
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256

head1 "00 (Claude and Codex answer; TMPDIR outside; 593 markers absent in production; Task state left alone)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|isolation:|answer check|Claude Code installed|codex|CHECK 593|TMPDIR|Task directories|Version|579 backup)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: Claude answer check OK and Codex CHECK PASS" sh -c "grep -q 'answer check (expect clean): OK' $F/00.out && grep -q 'CHECK 593 Codex answers CODEX-593-OK (configured model, logged in): PASS' $F/00.out"
check "00: TMPDIR outside the Harness, zsh interpreter" sh -c "grep -q '(outside the Harness)' $F/00.out && grep -q 'interpreter: zsh' $F/00.out"
check "00: 593 markers absent in production (8/8), graftling 0.8.0; production bin has agents and agents-mcp" sh -c "grep -q 'markers expected absent: PASS (8/8)' $F/00.out && grep -q '^Version: 0.8.0' $F/00.out && grep -q '^production bin: agents agents-mcp ' $F/00.out"
check "00: task.md counted 0 with count() (no 'print -l | wc -l' miscount)" grep -q 'task.md: 0 (expect 0)' $F/00.out
check "00: probe Task 593 ready; provider lines printed; conda and uv paths printed" sh -c "grep -q 'CHECK 593 probe Task 593 ready (current_definition definitions/.*md exists): PASS' $F/00.out && [ \$(grep -c '^provider used: ' $F/00.out) -eq 2 ] && grep -q '^conda: ' $F/00.out && grep -q '^uv: ' $F/00.out"
check "00 next is scan" grep -q "next.*: zsh $SD/steps.zsh scan" $F/00.out

head1 "scan before I (real scan593.py on the fake production): the 0.8.0 hook copy's TOOLS line and the agents console scripts are live hits"
steps scan > $F/scan-before.out 2>&1; SCB=$?; grep -E 'REPORT|LIVE|console scripts' $F/scan-before.out
check "scan before I: exit 0; hook copy TOOLS = [\"agents\", \"tasks\"] found as LIVE with file:line; console scripts agents, agents-mcp listed; next rel" sh -c "[ $SCB -eq 0 ] && grep -qE '^  LIVE \.claude/skills/graphtraj-claude-host/hooks/host_context\.mjs:[0-9]+: \[tool list naming agents\] const TOOLS = \[\"agents\", \"tasks\"\];' $F/scan-before.out && grep -q \"console scripts: \\['agents', 'agents-mcp'\\]\" $F/scan-before.out && grep -q 'REPORT 593 old-name scan \[before-I\]: live configuration hits [1-9]' $F/scan-before.out && grep -q \"next.*: zsh $SD/steps.zsh rel\" $F/scan-before.out"
check "scan reads no home file and writes only its raw output" sh -c "! grep -q '$HOME/.claude' $F/scan-before.out && [ -f $RW/scan-before-I.txt ]"
steps scanhome > $F/scanhome-no.out 2>&1; SHN=$?
check "scanhome refuses until Main has asked the USER (ADOPT593_HOME_ASKED=yes)" sh -c "[ $SHN -ne 0 ] && grep -q 'Main 先问 USER' $F/scanhome-no.out"
mkdir -p $F/home/.claude; print -r -- '{"permissions":{"allow":["mcp__graphtraj__agents","Bash(ls:*)"],"deny":["mcp__graphtraj__subagents"]},"env":{"SECRET_TOKEN":"sk-rehearsal-not-printed"}}' > $F/home/.claude/settings.json
print -r -- '{"projects":{"/p":{"allowedTools":["mcp__graftling__agents","Read"],"mcpServers":{"a":{"command":"/x/bin/agents-mcp"}}}}}' > $F/home/.claude.json
ADOPT593_HOME_ASKED=yes HOME=$F/home steps scanhome > $F/scanhome.out 2>&1; SHY=$?; cat $F/scanhome.out | grep -E '^  |REPORT'
check "scanhome (fixture home): prints only the three matching strings with their key paths, never other values" sh -c "[ $SHY -eq 0 ] && grep -q 'REPORT 593 USER allow rules naming the old tool or commands: 3' $F/scanhome.out && grep -q 'permissions.allow\[0\]: mcp__graphtraj__agents' $F/scanhome.out && ! grep -q 'sk-rehearsal-not-printed' $F/scanhome.out && ! grep -q 'Bash(ls' $F/scanhome.out && ! grep -q 'subagents\$' $F/scanhome.out"

head1 "B before rel (no v0.9.0 tag yet) refuses"
steps B > $F/B-norel.out 2>&1; BN=$?
check "B negative: without rel, v0.9.0 is missing -> STOP" sh -c "[ $BN -ne 0 ] && grep -q 'STOP: v0.9.0^{commit} is missing' $F/B-norel.out"

head1 "rel negatives: dev without the base; a wrong existing v0.9.0"
gclone $F/gnobase && git -C $F/gnobase branch -q -f dev $GOLD
ADOPT593_G=$F/gnobase steps rel > $F/rel-nobase.out 2>&1; RNB=$?
check "rel negative: dev does not contain ${GBASE[1,8]} -> STOP, nothing changed" sh -c "[ $RNB -ne 0 ] && grep -q 'does not contain $GBASE' $F/rel-nobase.out && [ \$(git -C $F/gnobase rev-parse dev) = $GOLD ] && [ \$(git -C $F/gnobase rev-parse main) = $GOLD ] && ! git -C $F/gnobase rev-parse -q --verify refs/tags/v0.9.0 > /dev/null"
gclone $F/gwrong && git -C $F/gwrong -c user.name=x -c user.email=x@invalid tag -a v0.9.0 $GBASE -m wrong
ADOPT593_G=$F/gwrong steps rel > $F/rel-wrong.out 2>&1; RW1=$?
check "rel negative: an existing v0.9.0 at another commit -> STOP" sh -c "[ $RW1 -ne 0 ] && grep -q 'STOP: v0.9.0 exists at' $F/rel-wrong.out"

head1 "rel with dev moved by 570 (clean): merge $GC into dev as the noreply identity"
gclone $F/gmoved $F/gmoved-dev
print -l "570 note (rehearsal)" > $F/gmoved-dev/docs/570-rehearsal.md && git -C $F/gmoved-dev add docs/570-rehearsal.md && git -C $F/gmoved-dev -c user.name=x -c user.email=x@invalid commit -qm "570 (rehearsal)"
MOVED=$(git -C $F/gmoved rev-parse dev)
ADOPT593_G=$F/gmoved steps rel > $F/rel-moved.out 2>&1; RMV=$?; grep -E 'CHECK|dev:|dev moved' $F/rel-moved.out
check "rel dev moved: exit 0, four CHECK PASS" sh -c "[ $RMV -eq 0 ] && [ \$(grep '^CHECK 593 .*: PASS' $F/rel-moved.out | sort -u | wc -l) -eq 4 ] && ! grep -q '^CHECK 593 .*: FAIL' $F/rel-moved.out"
check "rel dev moved: dev is a merge (parents $MOVED[1,8] + ${GC[1,8]}) by $NR; main = v0.9.0 = $GC; worktree clean" sh -c "[ \"\$(git -C $F/gmoved log -1 --format=%P dev)\" = '$MOVED $GC' ] && [ \"\$(git -C $F/gmoved log -1 --format='%ae %ce' dev)\" = '$NR $NR' ] && [ \$(git -C $F/gmoved rev-parse main) = $GC ] && [ \$(git -C $F/gmoved rev-parse 'v0.9.0^{commit}') = $GC ] && [ -z \"\$(git -C $F/gmoved-dev status --porcelain)\" ]"

gclone $F/gmovedp && git -C $F/gmovedp worktree add -q $F/gmovedp-edit dev
print -l "570 note (rehearsal)" > $F/gmovedp-edit/docs/570-rehearsal.md && git -C $F/gmovedp-edit add docs/570-rehearsal.md && git -C $F/gmovedp-edit -c user.name=x -c user.email=x@invalid commit -qm "570 (rehearsal)"
git -C $F/gmovedp worktree remove $F/gmovedp-edit; MOVEDP=$(git -C $F/gmovedp rev-parse dev)
ADOPT593_G=$F/gmovedp steps rel > $F/rel-movedp.out 2>&1; RMP=$?
check "rel dev moved, dev checked out nowhere: merge-tree + commit-tree merge by $NR (parents ${MOVEDP[1,8]} + ${GC[1,8]}), four CHECK PASS" sh -c "[ $RMP -eq 0 ] && grep -q 'dev checked out in: no worktree' $F/rel-movedp.out && [ \"\$(git -C $F/gmovedp log -1 --format=%P dev)\" = '$MOVEDP $GC' ] && [ \"\$(git -C $F/gmovedp log -1 --format='%an <%ae> / %cn <%ce>' dev)\" = 'LUOXIAO92 <$NR> / LUOXIAO92 <$NR>' ] && [ \$(grep '^CHECK 593 .*: PASS' $F/rel-movedp.out | sort -u | wc -l) -eq 4 ] && git -C $F/gmovedp diff --quiet dev $MOVEDP -- docs/570-rehearsal.md && [ \"\$(git -C $F/gmovedp show dev:src/graftling/__init__.py | grep ^__version__)\" = '__version__ = \"0.9.0\"' ]"

head1 "rel with a conflicting dev (CHANGELOG edited by 570): worktree path and no-worktree path STOP with nothing changed"
for kind in worktree plain; do
  r=$F/gconf-$kind; gclone $r ${${kind:#plain}:+$r-dev}
  if [[ $kind == worktree ]]; then e=$r-dev; else e=$F/gconf-edit; git -C $r worktree add -q $e dev; fi
  $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("## Unreleased (incompatible; to be released as 0.9.0)\n", "## Unreleased (rehearsal conflict: dev edited the heading the release renames)\n", 1))' $e/CHANGELOG.md
  git -C $e -c user.name=x -c user.email=x@invalid commit -qam "570 CHANGELOG (rehearsal)"
  [[ $kind == plain ]] && git -C $r worktree remove $e
  CONF=$(git -C $r rev-parse dev)
  ADOPT593_G=$r steps rel > $F/rel-conf-$kind.out 2>&1; RC=$?; grep -E 'conflicted|STOP|merge-tree' $F/rel-conf-$kind.out | head -3
  check "rel conflict ($kind): STOP; dev still ${CONF[1,8]}, main still v0.8.0, no v0.9.0" sh -c "[ $RC -ne 0 ] && grep -q 'STOP: merging $GC into dev conflicts' $F/rel-conf-$kind.out && [ \$(git -C $r rev-parse dev) = $CONF ] && [ \$(git -C $r rev-parse main) = $GOLD ] && ! git -C $r rev-parse -q --verify refs/tags/v0.9.0 > /dev/null"
done
check "rel conflict (plain): dev checked out nowhere, so rel used git merge-tree (no worktree touched)" sh -c "grep -q 'dev checked out in: no worktree' $F/rel-conf-plain.out && grep -q '^merge-tree: ' $F/rel-conf-plain.out"
check "rel conflict (worktree): the merge was aborted, dev's worktree clean" sh -c "[ -z \"\$(git -C $F/gconf-worktree-dev status --porcelain)\" ] && ! [ -e $F/gconf-worktree-dev/.git/MERGE_HEAD ] && ! git -C $F/gconf-worktree-dev rev-parse -q --verify MERGE_HEAD > /dev/null"

head1 "rel (scratch graftling, dev = base): fetch the bundle, dev and main fast-forward, annotated noreply tag"
steps rel > $F/rel.out 2>&1; RRC=$?; grep -E 'CHECK|version at|= $GC|dev:' $F/rel.out
check "rel exit 0 with four CHECK PASS" sh -c "[ $RRC -eq 0 ] && [ \$(grep '^CHECK 593 .*: PASS' $F/rel.out | sort -u | wc -l) -eq 4 ] && ! grep -q '^CHECK 593 .*: FAIL' $F/rel.out"
check "rel: v0.9.0 = dev = main = $GC (dev's linked worktree too), tagger noreply, version 0.9.0" sh -c "[ \$(git -C $FG rev-parse 'v0.9.0^{commit}') = $GC ] && [ \$(git -C $FG rev-parse dev) = $GC ] && [ \$(git -C $FG rev-parse main) = $GC ] && [ \$(git -C $FGD rev-parse HEAD) = $GC ] && git -C $FG for-each-ref --format='%(taggeremail)' refs/tags/v0.9.0 | grep -q '$NR' && grep -q 'version at v0.9.0: __version__ = \"0.9.0\"' $F/rel.out"
check "rel: prints the pre-approved push as the next separate step (with the decision id), then gh" sh -c "grep -q 'next.*ADOPT593_PUSH_CONFIRMED=yes zsh $SD/steps.zsh rp' $F/rel.out && grep -q 'zsh $SD/steps.zsh gh' $F/rel.out && grep -q '20261124T030105.522331+0900' $F/rel.out"
steps rel > $F/rel2.out 2>&1
check "rel again: already released, nothing to do" grep -q 'already released' $F/rel2.out

head1 "rp: refused without the USER's yes; with it, pushes to the scratch bare origin (never GitHub)"
steps gh > $F/gh-early.out 2>&1; GHE=$?
check "gh negative: before rp GitHub (the scratch bare) has no v0.9.0 and main is not $GC -> FAIL, nothing installed" sh -c "[ $GHE -ne 0 ] && grep -q 'CHECK 593 gh: GitHub graftling main = $GC: FAIL' $F/gh-early.out && grep -q 'installed: nothing' $F/gh-early.out"
steps rp > $F/rp.out 2>&1; RP=$?
check "rp without ADOPT593_PUSH_CONFIRMED refuses (no push); its header cites the USER's pre-approval" sh -c "[ $RP -ne 0 ] && grep -q 'STOP: the push is outward-facing. It is pre-approved by the USER' $F/rp.out && grep -q '预先同意' $F/rp.out && [ \$(git -C $F/remote.git rev-parse main) = $GOLD ]"
check "rp target is the scratch bare repository" sh -c "[ \$(git -C $FG remote get-url origin) = $F/remote.git ]"
ADOPT593_PUSH_CONFIRMED=yes steps rp > $F/rp-yes.out 2>&1; RPY=$?; grep -E 'remote|CHECK' $F/rp-yes.out
check "rp confirmed: remote main and v0.9.0 = $GC, remote dev = local dev" sh -c "[ $RPY -eq 0 ] && grep -q 'CHECK 593 remote main and v0.9.0 = $GC, remote dev = local dev: PASS' $F/rp-yes.out && [ \$(git -C $F/remote.git rev-parse 'v0.9.0^{commit}') = $GC ]"

head1 "gh (result 4): GitHub's (here the scratch bare's) main and v0.9.0 resolve to the release commit; nothing installed"
print -l $HOME/.dsh/profiles/*(N:t) > $F/dsh-before.txt
steps gh > $F/gh.out 2>&1; GHR=$?; grep -E 'GitHub|installed|CHECK' $F/gh.out
check "gh exit 0: three CHECK PASS (main, tag peels, the local annotated tag object)" sh -c "[ $GHR -eq 0 ] && [ \$(grep '^CHECK 593 gh: .*: PASS' $F/gh.out | sort -u | wc -l) -eq 3 ] && grep -q 'installed: nothing' $F/gh.out"
print -l $HOME/.dsh/profiles/*(N:t) > $F/dsh-after.txt
check "gh: ~/.dsh profiles unchanged; nothing installed" sh -c "cmp -s $F/dsh-before.txt $F/dsh-after.txt && grep -q '^installed: nothing' $F/gh.out"

head1 "B: wheels from git archive v0.9.0 (archive root) and of the candidate; version strings; requirement pairs"
steps B > $F/B.out 2>&1; BRC=$?; check "B exit 0" [ $BRC -eq 0 ]
check "B: guard says ${NEW[1,8]} pins graftling>=0.9.0,<0.10" grep -q "product guard: ${NEW[1,8]} pyproject pins \"graftling>=0.9.0,<0.10\"" $F/B.out
grep -E 'whl|leaked|peels|annotated|CHECK|markers expected|GraphTraj dev|CHANGELOG heading|main:|project.scripts' $F/B.out
check "B: GraphTraj dev reported as information only; v0.9.0 annotated, peels to $GC" sh -c "grep -q 'dev contains ${NEW[1,8]}: yes' $F/B.out && grep -q 'v0.9.0 peels to $GC: yes' $F/B.out && grep -q 'v0.9.0 is an annotated tag (cat-file -t: tag): yes' $F/B.out"
check "B: every version string 0.9.0; CHANGELOG heading 0.9.0" sh -c "grep -q 'CHECK 593 v0.9.0 version strings all 0.9.0: PASS' $F/B.out && grep -q '^CHANGELOG heading: ## 0.9.0 (incompatible)' $F/B.out"
check "B: no 0.7.0 install route in v0.9.0 (581); console scripts subagents, subagents-mcp only (591)" sh -c "grep -q 'CHECK 593 v0.9.0 has no 0.7.0 install route .*: PASS' $F/B.out && grep -q 'CHECK 593 v0.9.0 console scripts subagents, subagents-mcp and no agents, agents-mcp: PASS' $F/B.out"
check "B: Requires-Dist satisfied by 0.9.0 and NOT by 0.8.0 or 0.10.0" sh -c "grep -q 'CHECK 593 Requires-Dist graftling<0.10,>=0.9.0 satisfied by 0.9.0: PASS' $F/B.out && grep -q 'CHECK 593 Requires-Dist graftling<0.10,>=0.9.0 NOT satisfied by 0.8.0: PASS' $F/B.out && grep -q 'CHECK 593 Requires-Dist graftling<0.10,>=0.9.0 NOT satisfied by 0.10.0: PASS' $F/B.out"
check "B: both wheels = their archives; markers present 8/8; leaked 0" sh -c "grep -q 'CHECK 593 graphtraj wheel equals git archive ${NEW[1,8]}: PASS' $F/B.out && grep -q 'CHECK 593 graftling wheel equals git archive v0.9.0: PASS' $F/B.out && grep -q 'markers expected present: PASS (8/8)' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: the install directory holds exactly graphtraj-0.1.0 and graftling-0.9.0" sh -c "[ \$(ls $W/wheels-${NEW[1,8]}/*.whl | wc -l) -eq 2 ] && ls $W/wheels-${NEW[1,8]}/graftling-0.9.0-*.whl > /dev/null"
VERIFY593_GCOMMIT=$GBASE steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the expected commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.9.0^{commit} is $GC, not $GBASE' $F/B-tag.out"
VERIFY593_TARGET=$OLD steps B > $F/B-commit.out 2>&1; BC=$?
check "B negative: a wrong GraphTraj target commit STOPs at the guard" sh -c "[ $BC -ne 0 ] && grep -q 'STOP: the Worktree.s src tests plugins pyproject.toml differ from ${OLD[1,8]}' $F/B-commit.out"
print '# drift' >> $FWT/src/graphtraj/execution/runner_worker.py
steps B > $F/B-dirty.out 2>&1; BD=$?
check "guard negative: an uncommitted src change STOPs" sh -c "[ $BD -ne 0 ] && grep -q 'STOP: uncommitted changes in the Worktree.s src tests plugins pyproject.toml' $F/B-dirty.out"
git -C $FWT checkout -q -- src
steps B > /dev/null 2>&1

head1 "G negative: a ps that cannot list processes STOPs G (never read as 'no other suite')"
touch $F/ps.fail
steps G > $F/G-psfail.out 2>&1; GPF=$?
rm -f $F/ps.fail
check "G with a failing ps: STOP before anything starts, exit != 0" sh -c "[ $GPF -ne 0 ] && grep -q '^STOP: ps cannot list processes here' $F/G-psfail.out && ! grep -q 'in the background' $F/G-psfail.out"

head1 "G through its real entry (6 shards; -k selects real tests, two with repository fixtures), queued behind a running suite; then GR"
steps GR > $F/GR-none.out 2>&1; GNO=$?
check "GR before any G: STOP 'run G first', FAIL" sh -c "[ $GNO -ne 0 ] && grep -q 'run G first' $F/GR-none.out && grep -q 'CHECK 593 GR (guard + G record): FAIL' $F/GR-none.out"
print -r -- "$HOSTLINE" > $F/ps.txt; print -r -- "4242 1 /usr/bin/python3 scripts/run_test_shards.py --shards 6 (another Task's suite, simulated)" >> $F/ps.txt
( sleep 7; print -r -- "$HOSTLINE" > $F/ps.txt ) &!
export FAKE_PROVIDER_API_KEY=sk-rehearsal-g-123456   # must not reach the suite (clean launch environment)
ADOPT593_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_graphtraj_uses_only_published_agents_names or test_every_public_name_is_listed_in_the_contract or test_child_tool_descriptions_match_the_members_entry or test_native_claude_lifecycle_without_a_task or test_extension_still_hands_an_explicit_agents_session_to_graftling or test_the_mcp_server_lists_subagents_and_tasks_only or test_the_claude_hook_copy_names_subagents_and_tasks'" steps G > $F/G.out 2>&1; GRC=$?
unset FAKE_PROVIDER_API_KEY
GO=$(print -l $W/G-${NEW[1,8]}-*(N/om[1])); print "G record: $GO"; cat $GO/run.txt 2>/dev/null; grep -E 'WAITING|running:|queued|started' $F/G.out
check "G queued: says WAITING with the running suite, never stops (exit 0)" sh -c "[ $GRC -eq 0 ] && grep -q '^WAITING: Main.s suite queue is serial' $F/G.out && grep -q 'running: 4242' $F/G.out && grep -q '^queued in the background' $F/G.out"
check "G record: pytest temp under TMPDIR (outside the Harness), clean launch environment, candidate, graftling commit, click 8.5.0" sh -c "grep -q 'pytest temp root: ${${TMPDIR:-/tmp}:A}/adopt-593-G-.*outside the Harness' $GO/run.txt && grep -q '^launch environment: HOME USER PATH TERM TMPDIR LANG only' $GO/run.txt && grep -q 'candidate: $(git -C $FWT rev-parse HEAD)' $GO/run.txt && grep -q 'git archive $GC' $GO/run.txt && grep -q 'click 8.5.0' $GO/run.txt"
steps GR > $F/GR-running.out 2>&1; GRN=$?
check "GR while G waits or runs: 'not finished', FAIL" sh -c "[ $GRN -ne 0 ] && grep -q 'G has not finished yet' $F/GR-running.out"
[[ -n $GO ]] && for i in {1..120}; do grep -q '^exit=' $GO/suite.txt 2>/dev/null && break; sleep 5; done; sleep 3
cat $GO/wait.txt; tail -4 $GO/suite.txt
check "G waited then started by itself: wait.txt has 'waiting for another suite: 4242' then 'started' and 'ended'" sh -c "grep -q 'waiting for another suite: 4242' $GO/wait.txt && grep -q ' started' $GO/wait.txt && grep -q ' ended' $GO/wait.txt"
check "G rehearsal: the selected real tests PASSED through G's entry (not collect-only), incl. fixture users; no FAILED line" sh -c "[ \$(grep -hoE '^PASSED tests/[a-z_0-9]+\.py::[a-z_0-9]+' $GO/shards/*.log | sort -u | wc -l) -ge 4 ] && grep -qE '^[0-9]+ passed' $GO/suite.txt && ! grep -qhE '^(FAILED|ERROR) ' $GO/shards/*.log"
grep -hoE '^PASSED tests/[a-z_0-9]+\.py::[a-z_0-9]+' $GO/shards/*.log | sort -u
check "G: repository-fixture users PASSED through G's real entry (built_wheel; 592's hook copy test with tmp_path; the Pi attachment test, both params)" sh -c "grep -qh '^PASSED tests/test_runtime_distribution.py::test_wheels_have_separate_owners' $GO/shards/*.log && grep -qh '^PASSED tests/test_tool_name_592.py::test_the_claude_hook_copy_names_subagents_and_tasks' $GO/shards/*.log && grep -qh '^PASSED tests/test_tool_name_592.py::test_the_mcp_server_lists_subagents_and_tasks_only' $GO/shards/*.log && [ \$(grep -hoE '^PASSED tests/test_pi_attachment_private_paths\.py::test_extension_still_hands_an_explicit_agents_session_to_graftling\[(agents-config|connection)\]' $GO/shards/*.log | sort -u | wc -l) -eq 2 ]"
check "G rehearsal: no provider credential reached the suite environment (the exported FAKE_PROVIDER_API_KEY value is in no G file)" sh -c "! grep -rqF 'sk-rehearsal-g-123456' $GO"
steps GR > $F/GR-G.out 2>&1; GRG=$?
grep -E '^(node ids|  known|  NEW|  rehearsal|  ABNORMAL|totals|CHECK)' $F/GR-G.out
check "GR reads the newest G record by itself: same product, graftling $GC, click 8.5.0; ids from the shard logs; no NEW" sh -c "grep -q 'G record: $GO' $F/GR-G.out && grep -q 'same product: yes' $F/GR-G.out && grep -q '= v0.9.0 ($GC): yes' $F/GR-G.out && grep -q 'click = production.s 8.5.0: yes' $F/GR-G.out && grep -q '^node ids read from: 6 shard logs' $F/GR-G.out && ! grep -q '  NEW: ' $F/GR-G.out"
check "GR prints the two named tests: test_wheels_have_separate_owners PASSED (expected now); the budgets test not in 516 (not seen here)" sh -c "grep -q '^named: tests/test_runtime_distribution.py::test_wheels_have_separate_owners: PASSED  (PASS expected now)' $F/GR-G.out && grep -q '^named: tests/test_execution_budgets.py::test_installed_runner_delivers_elapsed_notices_to_final_leader: not seen (not in 516: a failure is NEW and goes to suite-base)' $F/GR-G.out"

head1 "GR / SR mechanics on REHEARSAL FIXTURE records (shard logs with whole ids), and negatives on copies"
# Fixtures are not evidence of a suite result: they hold this candidate, the v0.9.0 commit, production's click and
# FAILED lines in shard logs, one of a test 516's current definition names.
GX=$F/grec; mkdir -p $GX/shards
print -l "pytest temp root: ${${TMPDIR:-/tmp}:A}/fixture (TMPDIR, outside the Harness) (REHEARSAL FIXTURE)" "launch environment: HOME USER PATH TERM TMPDIR LANG only (REHEARSAL FIXTURE)" \
  "candidate: $(git -C $FWT rev-parse HEAD) | graftling wheel from git archive $GC (REHEARSAL FIXTURE)" \
  "test interpreter dependencies: click 8.5.0 (fixture) | PyYAML 6.0.3 (fixture) | websockets 16.1.1 (fixture) | pytest 9.1.1 (fixture)" > $GX/run.txt
print -l "REHEARSAL FIXTURE" "FAILED tests/test_mcp_host_tools.py::test_installed_mcp_server_returns_each_caller_its_own_stop" "1 failed, 3690 passed, 48 skipped" "exit=1" > $GX/suite.txt
print -l "FAILED tests/test_mcp_host_tools.py::test_installed_mcp_server_returns_each_caller_its_own_stop - assert 1.0 < 0.9" "1 failed, 600 passed in 300.00s" > $GX/shards/shard-1.log
ADOPT593_GREC=$GX steps GR > $F/GR.out 2>&1; GRR=$?; grep -E '^(product guard|candidate|graftling commit|totals|516|node ids|  known|  NEW|CHECK)' $F/GR.out
check "GR on the fixture: the 516-named test is known; PASS" sh -c "[ $GRR -eq 0 ] && grep -q '  known (516): tests/test_mcp_host_tools.py::test_installed_mcp_server_returns_each_caller_its_own_stop' $F/GR.out && grep -q '^CHECK 593 GR (guard + G record): PASS' $F/GR.out"
mkdir -p $F/gneg && cp -Rp $GX $F/gneg/a && print -l 'FAILED tests/test_x.py::test_y[fallback-unexplained-Runtime reason: a b] - AssertionError: boom' >> $F/gneg/a/shards/shard-1.log
ADOPT593_GREC=$F/gneg/a steps GR > $F/GR-n1.out 2>&1; GN1=$?
check "GR negative: an unknown FAILED id (with spaces in its parameter) -> NEW as the WHOLE id, FAIL, no PASS left in GR.txt" sh -c "[ $GN1 -ne 0 ] && grep -qF '  NEW: tests/test_x.py::test_y[fallback-unexplained-Runtime reason: a b]' $F/GR-n1.out && ! grep -q 'GR (guard + G record): PASS' $RW/GR.txt"
ADOPT593_GREC=$F/gneg/a steps SR > $F/SR-n1.out 2>&1; SN1=$?; grep -E 'NEW|verdict|next|or \(paste\)' $F/SR-n1.out
check "SR: FAIL with the NEW id; prints suite-base with the id as ONE quoted argument, and the --from form" sh -c "[ $SN1 -ne 0 ] && grep -qF \"suite-base 'tests/test_x.py::test_y[fallback-unexplained-Runtime reason: a b]'\" $F/SR-n1.out && grep -qF 'suite-base --from' $F/SR-n1.out && grep -qxF 'tests/test_x.py::test_y[fallback-unexplained-Runtime reason: a b]' $F/gneg/a/new-ids.txt"
cp -Rp $GX $F/gneg/e && print -l 'ABNORMAL shard-2.log: exit 2' >> $F/gneg/e/suite.txt
ADOPT593_GREC=$F/gneg/e steps GR > $F/GR-n5.out 2>&1; GN5=$?
check "GR negative: an ABNORMAL shard (exit 2) -> NEW, FAIL" sh -c "[ $GN5 -ne 0 ] && grep -q '  ABNORMAL shard (NEW): ABNORMAL shard-2.log: exit 2' $F/GR-n5.out"
cp -Rp $GX $F/gneg/t && print -l 'ABNORMAL /x/shards/shard-3.log: timed out after 1500 s' >> $F/gneg/t/suite.txt
ADOPT593_GREC=$F/gneg/t steps SR > $F/SR-timeout.out 2>&1; STO=$?; grep -E 'TIMED OUT|shard timeouts|verdict' $F/SR-timeout.out
check "SR (593): a shard that timed out ('timed out after') is flagged ABNORMAL TIMED OUT (NEW); SR FAILs" sh -c "[ $STO -ne 0 ] && grep -q '  ABNORMAL shard TIMED OUT (NEW): ABNORMAL /x/shards/shard-3.log: timed out after 1500 s' $F/SR-timeout.out && grep -q '  shard timeouts (.timed out after. lines): 1 (NEW' $F/SR-timeout.out && grep -q 'SR verdict: FAIL' $F/SR-timeout.out"
ADOPT593_GREC=$F/gneg/t steps GR > $F/GR-timeout.out 2>&1; GTO=$?
check "GR (593): the same timeout makes GR FAIL" sh -c "[ $GTO -ne 0 ] && grep -q 'CHECK 593 GR (guard + G record): FAIL' $F/GR-timeout.out"
ADOPT593_GREC=$GX steps GR > /dev/null 2>&1   # GR.txt back to the fixture's PASS
cp -Rp $GX $F/gneg/c && $CONDA -I -c 'import re, sys; p = sys.argv[1]; open(p + ".new", "w").write(re.sub(r"git archive [0-9a-f]{40}", "git archive " + sys.argv[2], open(p).read()))' $F/gneg/c/run.txt $GBASE && mv $F/gneg/c/run.txt.new $F/gneg/c/run.txt
ADOPT593_GREC=$F/gneg/c steps GR > $F/GR-n3.out 2>&1; GN3=$?
check "GR negative: a G run with another graftling commit -> FAIL" sh -c "[ $GN3 -ne 0 ] && grep -q 'graftling commit of the wheel: $GBASE.* NO' $F/GR-n3.out"
cp -Rp $GX $F/gneg/d && $CONDA -I -c 'import sys; p = sys.argv[1]; open(p + ".new", "w").write(open(p).read().replace("click 8.5.0", "click 8.2.1"))' $F/gneg/d/run.txt && mv $F/gneg/d/run.txt.new $F/gneg/d/run.txt
ADOPT593_GREC=$F/gneg/d steps GR > $F/GR-n4.out 2>&1; GN4=$?
check "GR negative: a test interpreter with Miniconda's click 8.2.1 -> FAIL" sh -c "[ $GN4 -ne 0 ] && grep -q 'not production.s 8.5.0 (564): NO' $F/GR-n4.out"

head1 "suite-base: one real id on GraphTraj ${DEV} + graftling ${GBASE[1,8]} (wheel) and on the candidate (G's venv)"
steps suite-base 'tests/test_runtime_distribution.py::test_wheels_have_separate_owners' > $F/SB.out 2>&1; SBR=$?
grep -E '^(base|candidate):|classification|tests/' $F/SB.out | head -12
# 593: the base pairs GraphTraj 3eb21101 (graftling>=0.9.0,<0.10) with graftling 49f97004, which still says 0.8.0, so
# this version-pair test fails on the base side only; the release commit is what makes it pass.
check "suite-base: both sides ran the id in a clean environment, temp root outside the Harness; classified base-only (base graftling 49f97004 says 0.8.0), candidate passes" sh -c "grep -q '^base: pytest exit=1' $F/SB.out && grep -q '^candidate: pytest exit=0' $F/SB.out && grep -q 'launch environment: HOME USER PATH TERM TMPDIR LANG only' $F/SB.out && grep -q 'outside the Harness' $F/SB.out && grep -q '^base-only (passes on the candidate): tests/test_runtime_distribution.py::test_wheels_have_separate_owners' $F/SB.out && grep -q '^candidate-only: 0' $F/SB.out"
ADOPT593_GREC=$GX steps GR > /dev/null 2>&1   # the fixture's PASS stands in for the record in the I/R rehearsal below
check "GR: earlier GR.txt kept as GR-<time>.txt" sh -c "ls $RW/GR-*.txt > /dev/null 2>&1"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-mid.txt
check "real <Harness>/graftling untouched so far (every branch and tag as at the start)" cmp -s $F/realg-refs-before.txt $F/realg-refs-mid.txt
if [[ ${ADOPT593_PART:-all} == release ]]; then
  print -r -- ""
  print -r -- "REHEARSAL SUMMARY (release part: 00, scan, scanhome, rel, rp, gh, B, G, GR, SR, suite-base): $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
  exit $FAILED
fi

head1 "V: plugin hooks/host_context.mjs changed by exactly 577 (predicted); real MCP tools/list and Codex hooks entry; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK|^(PASS|FAIL):|^INFO|markers expected|plugin dialog|^graftling v|^graphtraj [0-9a-f]|task graph|host_context.mjs differences' $F/V.out
check "V: plugin as predicted (plugin.json and hooks.json SAME, host_context.mjs CHANGED by 577 only); dialog expected" sh -c "grep -q 'CHECK 593 candidate plugin as predicted (only hooks/host_context.mjs, by 577): PASS' $F/V.out && grep -q \"CHECK 593 plugin hooks/host_context.mjs differs by exactly 577's --data-root change: PASS\" $F/V.out && [ \$(grep -E '^SAME +(\.claude-plugin/plugin\.json|hooks/hooks\.json)$' $F/V.out | sort -u | wc -l) -eq 2 ] && grep -q '^CHANGED hooks/host_context.mjs' $F/V.out && grep -q 'plugin dialog expected at claude --continue: yes' $RW/V-dialog.txt"
check "V (579 F3): information lines read as information, no 'FAIL (STOP)' on an INFO line" sh -c "[ \$(grep -c '^INFO .*differs (expected; information, not a check)' $F/V.out) -ge 2 ] && ! grep -q '^INFO .*FAIL' $F/V.out"
check "V: real graphtraj-mcp lists exactly agents, tasks; Codex hooks entry two CHECKs PASS" sh -c "grep -q 'CHECK 593 scratch-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/V.out && [ \$(grep '^CHECK 593 Codex hooks entry .*: PASS' $F/V.out | sort -u | wc -l) -eq 2 ]"
check "V: markers present in the candidate and absent in production (7/7)" sh -c "grep -q 'markers expected present: PASS (7/7)' $F/V.out && grep -q 'markers expected absent: PASS (7/7)' $F/V.out"
check "V: read check of production Task state (task graph) by the candidate" grep -q 'task graph of the clone: tasks =' $F/V.out
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256
cp -Rp $RW/../vplug-${NEW[1,8]}/graphtraj-claude-host $F/vneg-plugin && print '// drift' >> $F/vneg-plugin/hooks/host_context.mjs
$CONDA -I $SD/plugin593.py $FH/.claude/skills/graphtraj-claude-host/hooks/host_context.mjs $F/vneg-plugin/hooks/host_context.mjs > $F/vneg.out 2>&1; VN=$?
check "V negative: any change beyond 577's lines -> plugin593 FAIL (V would STOP)" sh -c "[ $VN -eq 1 ] && grep -q ': FAIL' $F/vneg.out"

head1 "negatives: 0.8.0 left installed; markers both ways"
VS=($FB/vvenv-${NEW[1,8]}/lib/python*/site-packages(N))
mkdir -p $F/lneg && cp -Rp $VS[1] $F/lneg/site && cp -Rp $D/graftling-0.8.0.dist-info $F/lneg/site/
$CONDA -I $SD/proddiff.py $F/lneg/site $F/lneg $W/wheels-${NEW[1,8]} > $F/lneg.out 2>&1; LN=$?
check "proddiff negative: graftling 0.8.0's dist-info left beside 0.9.0 -> FAIL (LEFTOVER)" sh -c "[ $LN -ne 0 ] && grep -q 'LEFTOVER' $F/lneg.out"
check "markers 'present' on production fails; 'absent' on the candidate fails" sh -c "! $CONDA -I $SD/markers.py $D present > /dev/null && ! $CONDA -I $SD/markers.py $VS[1] absent > /dev/null"

head1 "Vu / Vc (stub claude: plugin not loaded, so Vc asks for Vu)"
steps Vu > $F/Vu.out 2>&1
check "Vu names the isolated path and 'Yes, proceed'" sh -c "grep -q \"cd $FB/vproject && claude\" $F/Vu.out && grep -q 'Yes, proceed' $F/Vu.out"
steps Vc > $F/Vc.out 2>&1
check "Vc setup: isolated .mcp.json CHECK PASS and answer check OK" sh -c "grep -q 'CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS' $RW/Vc.txt && grep -q 'answer check (expect clean): OK' $RW/Vc.txt"
check "Vc with the stub asks for Vu" grep -q 'USER: zsh .*steps.zsh Vu' $F/Vc.out
touch $RW/Vc.ok   # rehearsal only: the real plugin load is not rehearsable

head1 "guard refusal, I refusal without GR PASS, then Mpre / I (USER): backup, pair install, real entries"
print -r -- "77 1 $FRT/bin/python -m graphtraj.execution.runner_worker $FH/.graphtraj/core/runner/sessions/999-x@engineer/launch.yml" > $F/ps.txt
steps _backup > $F/I-busy.out 2>&1; IB=$?
check "guard negative: a member Worker under the venv -> BLOCKING, no backup made" sh -c "[ $IB -ne 0 ] && grep -q 'guard: BLOCKING 1' $F/I-busy.out && [ ! -e $FB/backup ]"
: > $F/ps.txt   # Main has exited, no member runs
cp -p $RW/GR.txt $F/GR-good.txt; print 'CHECK 593 GR (guard + G record): FAIL' > $RW/GR.txt
print | steps I > $F/I-noGR.out 2>&1; INR=$?
check "I negative: refuses while GR.txt has no PASS, and creates no backup" sh -c "[ $INR -ne 0 ] && grep -q 'GR 还不是 PASS' $F/I-noGR.out && [ ! -e $FB/backup ]"
cp -p $F/GR-good.txt $RW/GR.txt
print -r -- "$HOSTLINE" > $F/ps.txt
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: the next command says Main asks the USER before I" sh -c "grep -q 'Main 先问 USER' $F/Mpre.out"
check "Mpre: GR PASS shown; restart reason names the loaded old modules" sh -c "grep -q '^GR: PASS (CHECK 593 GR (guard + G record): PASS)' $F/Mpre.out && grep -q '安装会在它运行时替换这些文件' $F/Mpre.out"
: > $F/ps.txt
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|CHECK|direct_url|built from|configuration --write rc|plugin files|SAME-AS-VALIDATED|markers expected|bytes unchanged' $F/I.out
check "I: both wheels installed together, proddiff PASS, 0.8.0 dist-info gone, markers 8/8" sh -c "grep -q '^Successfully installed graftling-0.9.0 graphtraj-0.1.0' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'CHECK 593 graftling 0.8.0 dist-info gone: PASS' $F/I.out && grep -q 'markers expected present: PASS (7/7)' $F/I.out"
check "I: direct_url of both names wheels-${NEW[1,8]}; built from both archives" sh -c "grep -q 'CHECK 593 direct_url of both names the wheels-${NEW[1,8]} wheels: PASS' $F/I.out && grep -q 'built from: graphtraj git archive $NEW, graftling git archive v0.9.0 $GC' $F/I.out"
check "I: configuration --write rc=0, plugin changed as V predicted (577 only), .mcp.json PASS, SAME-AS-VALIDATED" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 593 installed plugin changed as V predicted (only hooks/host_context.mjs): PASS' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out"
check "I: real entries of the installed venv: MCP tools/list and Codex hooks PASS" sh -c "grep -q 'CHECK 593 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/I.out && [ \$(grep '^CHECK 593 Codex hooks entry .*: PASS' $F/I.out | sort -u | wc -l) -eq 2 ]"
check "I: no Task-state migration ran (no migrate lines)" sh -c "! grep -qE 'migrate-task-definitions|CHECK 593 563|preview rc=' $F/I.out"
check "I: backup holds venv, plugin, entries, tools; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/pkgdiff532.py ] && [ -d $FB/backup/venv ]"
check "I: header says Main asks the USER first; prints the restart command, V's expected dialog (plugin/hooks trust: yes) and Ma next" sh -c "grep -q '\\[I\\] USER（Main 先问 USER' $F/I.out && grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: plugin dialog expected at claude --continue: yes' $F/I.out && grep -q 'steps.zsh Ma' $F/I.out"

head1 "M / Mp after the restart; N; done"
print -r -- "$HOSTLINE" > $F/ps.txt
steps Ma > $F/Ma.out 2>&1; MAR=$?; grep -E 'wrote|installed read_arguments_file|CHECK|arguments_file' $F/Ma.out
check "Ma (575): the arguments file is inside the fake project, read by the INSTALLED graphtraj as Main's host reads it" sh -c "[ $MAR -eq 0 ] && [ -f $FB/args-575.json ] && grep -q 'CHECK 593 575 arguments file readable by the installed graphtraj (project root, not .graphtraj): PASS' $F/Ma.out"
check "Ma: prints the exact call with the real path and the observable" sh -c "grep -qF '\"arguments_file\":\"$FB/args-575.json\"' $F/Ma.out && grep -q '成功的可观察结果' $F/Ma.out && grep -q 'definitions/' $F/Ma.out"
steps M > $F/M.out 2>&1
check "M[d]: the 575 call is in M's prompts with the real path" sh -c "grep -q '^\\[d 575' $F/M.out && grep -qF '\"arguments_file\":\"$FB/args-575.json\"' $F/M.out"
check "M prompt: upgraded by Task 593; task_graph with view current (560's 'summary' fixed)" sh -c "grep -q 'Production was just upgraded by Task 593' $F/M.out && grep -q '{\"view\":\"current\"}' $F/M.out && ! grep -q '\"view\":\"summary\"' $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"
steps N > $F/N.out 2>&1
check "N (576, 579 F1): the child is created WITHOUT tools and must run Bash and reply DONE-593" sh -c "grep -q 'WITHOUT a tools argument' $F/N.out && grep -q 'reply with exactly: DONE-593' $F/N.out"
check "N: one advisor member of Task 593 creates n593" sh -c "grep -q '\"task_id\":\"593\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n593' $F/N.out"
head1 "Nr (576 and 579 F2) on a REHEARSAL FIXTURE child record, member mapping and archives"
CA=$FH/.graphtraj/swarm/control/agents; mkdir -p $CA $FH/.graphtraj/core/runner/sessions/593-x@advisor $FH/.graphtraj/swarm/sessions/s-member $FH/.graphtraj/swarm/sessions/s-child
print -r -- '{"name":"n593","agent":"ag-1","parent":"593-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":null},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}]}' > $CA/ag-1.json
print -l 'session: {id: "claude:m-1"}' 'task_id: "593"' 'role: opus_coding_team.advisor' 'execution_id: me-1' > $FH/.graphtraj/core/runner/sessions/593-x@advisor/mapping.yml
print -l 'execution_id: me-1' 'outcome: completed' 'terminal_confirmed: true' > $FH/.graphtraj/core/runner/sessions/593-x@advisor/execution.yml
print -r -- '{"header":{"id":"claude:m-1"}}' > $FH/.graphtraj/swarm/sessions/s-member/session.jsonl
print -r -- '{"type":"assistant","timestamp":"2026-11-23T12:00:00Z","message":{"content":[{"type":"tool_use","id":"tu1","name":"mcp__graphtraj__agents","input":{"action":"execute","feature":"create"}},{"type":"tool_use","id":"tu2","name":"mcp__graphtraj__agents","input":{"action":"execute","feature":"answer"}}]}}' >> $FH/.graphtraj/swarm/sessions/s-member/session.jsonl
print -r -- '{"type":"user","timestamp":"2026-11-23T12:00:01Z","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":[{"type":"text","text":"{\"agent\":\"ag-1\"}"}]},{"type":"tool_result","tool_use_id":"tu2","is_error":true,"content":[{"type":"text","text":"not-running: The Agent is in standby; no native request is pending."}]}]}}' >> $FH/.graphtraj/swarm/sessions/s-member/session.jsonl
print -r -- '{"header":{"id":"claude:c-1","native":{"agentId":"ag-1"}}}' > $FH/.graphtraj/swarm/sessions/s-child/session.jsonl
print -r -- '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b1","name":"Bash","input":{"command":"echo n593-tool && sleep 20"}}]}}' >> $FH/.graphtraj/swarm/sessions/s-child/session.jsonl
print -r -- 'member reply (fixture): last_message "DONE-593"; configuration "opus_coding_team.advisor", model "claude-opus-5-5"' > $RW/N-reply.txt
print -r -- '[Graftling notice from 593-x@advisor · completed · execution me-1] done (fixture)' > $RW/N-main-notice.txt
print -r -- '{"agent": "ag-member"}' > $RW/N.txt
steps Nr > $F/Nr.out 2>&1; grep -E '^CHECK|^\[member' $F/Nr.out
check "Nr (576): created without tools, DONE-593 quoted, a Bash tool_use running echo n593-tool archived -> three PASS" sh -c "grep -q 'CHECK 576 child created without tools (stored selection.tools is null): PASS' $F/Nr.out && grep -q 'CHECK 576 child without tools ran Bash and replied DONE-593 (member quotes the last_message): PASS' $F/Nr.out && grep -q 'CHECK 576 a Bash tool_use running echo n593-tool is in a Session archive: PASS' $F/Nr.out"
check "Nr (579 F2): the member's informative not-running answer is not counted as an error" sh -c "grep -q 'CHECK 515 \[member 593-x@advisor\] mcp__graphtraj__agents called and answered without error or refusal: PASS (ok 1, errors/refusals 0)' $F/Nr.out && grep -q 'info: not-running' $F/Nr.out"
print -r -- '{"name":"n593","agent":"ag-1","parent":"593-x@advisor","selection":{"configuration":"opus_coding_team.advisor","model":"claude-opus-5-5","tools":["Read"]},"executions":[{"id":"ex-1","state":"ended","outcome":"completed","error":null,"notification":"delivered"}]}' > $CA/ag-1.json
print -r -- 'member reply (fixture): the child said it has no Bash' > $RW/N-reply.txt
steps Nr > $F/Nr-neg.out 2>&1; NRN=$?
check "Nr negative: a child created WITH tools, or without DONE-593, FAILs the 576 checks" sh -c "[ $NRN -ne 0 ] && grep -q 'CHECK 576 child created without tools (stored selection.tools is null): FAIL' $F/Nr-neg.out && grep -q 'CHECK 576 child without tools ran Bash and replied DONE-593 (member quotes the last_message): FAIL' $F/Nr-neg.out"
rm -rf $CA $FH/.graphtraj/core/runner/sessions/593-x@advisor $FH/.graphtraj/swarm/sessions/s-member $FH/.graphtraj/swarm/sessions/s-child $RW/N-reply.txt $RW/N-main-notice.txt $RW/N.txt

export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: versions, direct_urls, real entries PASS, no key value" sh -c "grep -q '^Version: 0.9.0' $F/done.out && grep -q 'graftling direct_url: .*wheels-${NEW[1,8]}' $F/done.out && grep -q 'CHECK 593 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/done.out && grep -q 'raw files containing an exported key value: 0' $F/done.out"
check "done: counts are 0 when nothing matches (560's miscount fixed): '0.8.0 dist-info left: 0', 'task.md 0'" sh -c "grep -q 'graftling 0.8.0 dist-info left: 0 (expect 0)' $F/done.out && grep -q 'Task state now: task.md 0 ' $F/done.out"

head1 "R (rollback from the backup's own tools): both packages, plugin and entries restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; check "R header says Main asks the USER first" grep -q "\[R\] USER（Main 先问 USER" $F/R.out; grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK|graphtraj package|before R' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling and graphtraj restored (vs backup); graftling is 0.8.0 again" sh -c "grep -q 'CHECK 593 graftling restored (after R vs backup): PASS' $F/R.out && grep -q 'CHECK 593 graphtraj restored (after R vs backup): PASS' $F/R.out && grep -q 'CHECK 593 R: graftling is 0.8.0 again: PASS' $F/R.out"
check "R: production graftling 0.8.0, graphtraj ${OLD[1,8]} markers absent again; entries as before" sh -c "$FRT/bin/python -m pip show graftling 2>/dev/null | grep -q 'Version: 0.8.0' && $CONDA -I $SD/markers.py $D absent > /dev/null && shasum -a 256 -c --quiet $F/entries0.sha256"
check "R: the old code still reads the state (task graph loads)" sh -c "cd $FH && $FRT/bin/python -I -c 'from pathlib import Path; from graphtraj.graph.task_graph import read_graph; g = read_graph(Path(\"$FS\"), view=\"full\"); print(\"old code task graph:\", len(g[\"tasks\"]))'"
check "579's backup under tmp/579 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-after.txt
check "real <Harness>/graftling untouched by the rehearsal (every branch and tag as at the start)" cmp -s $F/realg-refs-before.txt $F/realg-refs-after.txt

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
