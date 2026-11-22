#!/bin/zsh
# Rehearsal of adopt-571/steps.zsh from an EMPTY base against a fake production tree in $TMPDIR (modelled on adopt-560's).
# Starts no real host and never touches production, <Harness>/graftling, GitHub or GraphTraj dev:
# - graftling: a scratch clone of <Harness>/graftling put back to the state at dispatch (dev = 00778d1 checked out in a
#   linked worktree as on the real host, main = v0.6.3 in the main worktree, no v0.6.4, no release branch); its `origin`
#   is a scratch bare repository, so the confirmed rp pushes there. rel fetches the bundle into it. Further scratch clones
#   rehearse dev moved by 570 (clean merge), a conflicting dev (worktree and no-worktree paths), dev without the base and
#   a wrong existing v0.6.4.
# - GraphTraj: a scratch clone of this Worktree whose local dev is 11f84ed6, WITHOUT the candidate (B must not need it).
# - fake production: graphtraj wheel of 8949caff + graftling wheel of the real v0.6.3 (git archive root, read only),
#   click, yaml and websockets copied from production .venv-runtime (read only); 516's task.yml and definitions copied.
# - `claude`, `codex`, `ps` and `dsh` are stubs on PATH (the dsh stub installs the default branch of the scratch bare
#   repository as DSH would install the GitHub address). The MCP server and the Codex hooks entry are the REAL entries
#   of the scratch venv and of the fake production venv.
# - G is rehearsed through its real entry (run_test_shards.py, 6 shards) with `-k` selecting real tests, including ones
#   that use the repository's fixtures (not --collect-only), first queued behind a simulated running suite; GR then
#   reads that record.
#   zsh scripts/adopt-571/rehearse.zsh
set -u
SD=${0:A:h}
WT=${SD:h:h}
F=${${TMPDIR:-/tmp}:A}/${ADOPT571_REHEARSAL_NAME:-adopt571-rehearsal}
FH=$F/project
FRT=$FH/.venv-runtime
FB=$FH/tmp/571
OB=$FH/tmp/560   # 560's backup base: listed only, never modified
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALG=$REALH/graftling
REALSTATE=$REALH/.graphtraj/core/state
GC=d5b334981e42eed43a27382447df6aeea06f4e8e
GBASE=00778d17a543f35d49e218de5f9ede061f977dac
GOLD=ef7c37db15f4e6318fd5b6bf5bd79321b876eac5   # v0.6.3
NEW=956c6ff9d53bc98ec37d1a1757c2dd66caef50f4
OLD=8949caff74156d14625f45d7d6b762a04cef87eb
DEV=11f84ed6                                     # GraphTraj dev at dispatch
NR=89069722+LUOXIAO92@users.noreply.github.com
FG=$F/graftling          # scratch graftling repository (main worktree: main)
FGD=$F/graftling-dev     # its linked worktree with dev checked out
FWT=$F/wt                # scratch GraphTraj clone (dev = 11f84ed6, without the candidate)
export ADOPT571_H=$FH ADOPT571_BASE=$FB ADOPT571_RT=$FRT ADOPT571_PNPM_SHIM=$F/no-shim ADOPT571_STUB=$F/stub ADOPT571_WT=$FWT ADOPT571_PROJECTS=$F/projects/-fake ADOPT571_WAIT=1 ADOPT571_OLDBASE=$OB ADOPT571_G=$FG ADOPT571_VPROJECT=$FB/vproject ADOPT571_GURL=$F/remote.git ADOPT571_GHROOT=$F/ghroot ADOPT571_GWAIT=2
export PATH=$F/stub:$PATH
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAFTLING_CONNECTION GRAPHTRAJ_PARENT_CONNECTION GRAPHTRAJ_PARENT_REGISTRATION GRAFTLING_CLAUDE_HOST_CONFIG
TASK=571-graftling-0-6-4-release-and-production-adoption
ST=$FH/.graphtraj/core/state/tasks
W=$ST/$TASK/adoption
RW=$W/raw-${NEW[1,8]}
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }
# A scratch graftling clone at the dispatch state: main = v0.6.3 (main worktree), dev = $GBASE (linked worktree $2 when
# given), no v0.6.4, no release branch, origin = $3 when given.
gclone() {
  local d=$1 wt=${2:-} origin=${3:-}
  git clone -q --no-hardlinks $REALG $d || return 1
  git -C $d checkout -q --detach && git -C $d branch -q -f main $GOLD && git -C $d checkout -q main && git -C $d branch -q -f dev $GBASE
  git -C $d tag -d v0.6.4 > /dev/null 2>&1; git -C $d branch -q -D agent/571-graftling-0.6.4 > /dev/null 2>&1
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

head1 "setup: scratch graftling (dev = ${GBASE[1,8]} in a linked worktree, main = v0.6.3, origin = scratch bare), scratch GraphTraj (dev = $DEV)"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-before.txt
gclone $FG $FGD $F/remote.git
git clone -q --bare --no-hardlinks $FG $F/remote.git && git -C $F/remote.git symbolic-ref HEAD refs/heads/main
git -C $F/remote.git tag -d v0.6.4 > /dev/null 2>&1; true
print "scratch graftling: dev $(git -C $FG rev-parse dev) main $(git -C $FG rev-parse main) v0.6.4 $(git -C $FG rev-parse -q --verify refs/tags/v0.6.4 || print absent) | origin $(git -C $FG remote get-url origin) | worktrees: $(git -C $FG worktree list | wc -l | tr -d ' ')"
git clone -q --shared --no-checkout $WT $FWT && git -C $FWT checkout -q -b cand $(git -C $WT rev-parse HEAD) && git -C $FWT branch -q -f dev $DEV
print "scratch GraphTraj: HEAD $(git -C $FWT rev-parse HEAD) dev $(git -C $FWT rev-parse dev)"

head1 "setup: fake production = graphtraj ${OLD[1,8]} + graftling v0.6.3, plugin, configuration; stubs"
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
      print -r -- "{\"type\":\"result\",\"is_error\":false,\"result\":\"${tag:-PROBE-571-OK} claude-opus-5-5, logged in\\nFILES: NONE\",\"modelUsage\":{\"claude-opus-5-5\":{}}}" ;;
  *) print "stub claude: $*" ;;
esac
EOF
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.171.0 (stub)" ;;
  exec) print -u2 "model: gpt-5.5-codex (stub configured model)"; print "CODEX-571-OK" ;;
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
git -C $REALG archive v0.6.3 | tar -x -C $F/oldg
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
print "560 backup" > $OB/backup/COMPLETE
( cd $FH && find tmp/560 -type f -exec shasum -a 256 {} + ) > $F/evidence0.sha256
mkdir -p $FH/.graphtraj/swarm/sessions $FH/.graphtraj/swarm/control
MAINID=11111111-2222-3333-4444-555555555555
: > $F/projects/-fake/$MAINID.jsonl
HOSTLINE="$$ 4241 $FRT/bin/python -m graphtraj.runtimes.claude.host serve --config $FH/.graphtraj/claude-host/config.json"
print -l "# Fake Harness rules" "This distinctive Harness instruction line must never reach the isolated project answer." > $FH/AGENTS.md
cat > $F/stub/ps <<EOF2
#!/bin/zsh
if [[ "\$*" == *"-p 4241"* ]]; then print "claude --continue"; exit 0; fi
if [[ "\$*" == *"lstart="* ]]; then exit 0; fi
if [[ "\$*" == *"stat="* ]]; then exit 0; fi
print "1 1 /sbin/launchd"; [[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0
EOF2
chmod +x $F/stub/ps
print -r -- "$HOSTLINE" > $F/ps.txt
shasum -a 256 $FH/.mcp.json $FH/.claude/settings.local.json $FH/.graphtraj/claude-host/config.json > $F/entries0.sha256

head1 "00 (Claude and Codex answer; TMPDIR outside; 571 markers absent in production; Task state left alone)"
steps 00 > $F/00.out 2>&1; ZRC=$?
grep -E '^(MAIN=|markers expected|isolation:|answer check|Claude Code installed|codex|CHECK 571|TMPDIR|Task directories|Version|560 backup)' $F/00.out
check "00 exit 0, MAIN found" sh -c "[ $ZRC -eq 0 ] && grep -q 'MAIN=$MAINID' $F/00.out"
check "00: Claude answer check OK and Codex CHECK PASS" sh -c "grep -q 'answer check (expect clean): OK' $F/00.out && grep -q 'CHECK 571 Codex answers CODEX-571-OK (configured model, logged in): PASS' $F/00.out"
check "00: TMPDIR outside the Harness, zsh interpreter" sh -c "grep -q '(outside the Harness)' $F/00.out && grep -q 'interpreter: zsh' $F/00.out"
check "00: 571 markers absent in production (8/8), graftling 0.6.3" sh -c "grep -q 'markers expected absent: PASS (8/8)' $F/00.out && grep -q '^Version: 0.6.3' $F/00.out"
check "00: task.md counted 0 with count() (no 'print -l | wc -l' miscount)" grep -q 'task.md: 0 (expect 0)' $F/00.out
check "00 next is rel" grep -q "next.*: zsh $SD/steps.zsh rel" $F/00.out

head1 "B before rel (no v0.6.4 tag yet) refuses"
steps B > $F/B-norel.out 2>&1; BN=$?
check "B negative: without rel, v0.6.4 is missing -> STOP" sh -c "[ $BN -ne 0 ] && grep -q 'STOP: v0.6.4^{commit} is missing' $F/B-norel.out"

head1 "rel negatives: dev without the base; a wrong existing v0.6.4"
gclone $F/gnobase && git -C $F/gnobase branch -q -f dev $GOLD
ADOPT571_G=$F/gnobase steps rel > $F/rel-nobase.out 2>&1; RNB=$?
check "rel negative: dev does not contain ${GBASE[1,8]} -> STOP, nothing changed" sh -c "[ $RNB -ne 0 ] && grep -q 'does not contain $GBASE' $F/rel-nobase.out && [ \$(git -C $F/gnobase rev-parse dev) = $GOLD ] && [ \$(git -C $F/gnobase rev-parse main) = $GOLD ] && ! git -C $F/gnobase rev-parse -q --verify refs/tags/v0.6.4 > /dev/null"
gclone $F/gwrong && git -C $F/gwrong -c user.name=x -c user.email=x@invalid tag -a v0.6.4 $GBASE -m wrong
ADOPT571_G=$F/gwrong steps rel > $F/rel-wrong.out 2>&1; RW1=$?
check "rel negative: an existing v0.6.4 at another commit -> STOP" sh -c "[ $RW1 -ne 0 ] && grep -q 'STOP: v0.6.4 exists at' $F/rel-wrong.out"

head1 "rel with dev moved by 570 (clean): merge $GC into dev as the noreply identity"
gclone $F/gmoved $F/gmoved-dev
print -l "570 note (rehearsal)" > $F/gmoved-dev/docs/570-rehearsal.md && git -C $F/gmoved-dev add docs/570-rehearsal.md && git -C $F/gmoved-dev -c user.name=x -c user.email=x@invalid commit -qm "570 (rehearsal)"
MOVED=$(git -C $F/gmoved rev-parse dev)
ADOPT571_G=$F/gmoved steps rel > $F/rel-moved.out 2>&1; RMV=$?; grep -E 'CHECK|dev:|dev moved' $F/rel-moved.out
check "rel dev moved: exit 0, four CHECK PASS" sh -c "[ $RMV -eq 0 ] && [ \$(grep '^CHECK 571 .*: PASS' $F/rel-moved.out | sort -u | wc -l) -eq 4 ] && ! grep -q '^CHECK 571 .*: FAIL' $F/rel-moved.out"
check "rel dev moved: dev is a merge (parents $MOVED[1,8] + ${GC[1,8]}) by $NR; main = v0.6.4 = $GC; worktree clean" sh -c "[ \"\$(git -C $F/gmoved log -1 --format=%P dev)\" = '$MOVED $GC' ] && [ \"\$(git -C $F/gmoved log -1 --format='%ae %ce' dev)\" = '$NR $NR' ] && [ \$(git -C $F/gmoved rev-parse main) = $GC ] && [ \$(git -C $F/gmoved rev-parse 'v0.6.4^{commit}') = $GC ] && [ -z \"\$(git -C $F/gmoved-dev status --porcelain)\" ]"

gclone $F/gmovedp && git -C $F/gmovedp worktree add -q $F/gmovedp-edit dev
print -l "570 note (rehearsal)" > $F/gmovedp-edit/docs/570-rehearsal.md && git -C $F/gmovedp-edit add docs/570-rehearsal.md && git -C $F/gmovedp-edit -c user.name=x -c user.email=x@invalid commit -qm "570 (rehearsal)"
git -C $F/gmovedp worktree remove $F/gmovedp-edit; MOVEDP=$(git -C $F/gmovedp rev-parse dev)
ADOPT571_G=$F/gmovedp steps rel > $F/rel-movedp.out 2>&1; RMP=$?
check "rel dev moved, dev checked out nowhere: merge-tree + commit-tree merge by $NR (parents ${MOVEDP[1,8]} + ${GC[1,8]}), four CHECK PASS" sh -c "[ $RMP -eq 0 ] && grep -q 'dev checked out in: no worktree' $F/rel-movedp.out && [ \"\$(git -C $F/gmovedp log -1 --format=%P dev)\" = '$MOVEDP $GC' ] && [ \"\$(git -C $F/gmovedp log -1 --format='%an <%ae> / %cn <%ce>' dev)\" = 'LUOXIAO92 <$NR> / LUOXIAO92 <$NR>' ] && [ \$(grep '^CHECK 571 .*: PASS' $F/rel-movedp.out | sort -u | wc -l) -eq 4 ] && git -C $F/gmovedp diff --quiet dev $MOVEDP -- docs/570-rehearsal.md && [ \"\$(git -C $F/gmovedp show dev:src/graftling/__init__.py | grep ^__version__)\" = '__version__ = \"0.6.4\"' ]"

head1 "rel with a conflicting dev (CHANGELOG edited by 570): worktree path and no-worktree path STOP with nothing changed"
for kind in worktree plain; do
  r=$F/gconf-$kind; gclone $r ${${kind:#plain}:+$r-dev}
  if [[ $kind == worktree ]]; then e=$r-dev; else e=$F/gconf-edit; git -C $r worktree add -q $e dev; fi
  $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("Task numbers.\n", "Task numbers.\n\n## Unreleased\n\n- 570 (rehearsal conflict)\n", 1))' $e/CHANGELOG.md
  git -C $e -c user.name=x -c user.email=x@invalid commit -qam "570 CHANGELOG (rehearsal)"
  [[ $kind == plain ]] && git -C $r worktree remove $e
  CONF=$(git -C $r rev-parse dev)
  ADOPT571_G=$r steps rel > $F/rel-conf-$kind.out 2>&1; RC=$?; grep -E 'conflicted|STOP|merge-tree' $F/rel-conf-$kind.out | head -3
  check "rel conflict ($kind): STOP; dev still ${CONF[1,8]}, main still v0.6.3, no v0.6.4" sh -c "[ $RC -ne 0 ] && grep -q 'STOP: merging $GC into dev conflicts' $F/rel-conf-$kind.out && [ \$(git -C $r rev-parse dev) = $CONF ] && [ \$(git -C $r rev-parse main) = $GOLD ] && ! git -C $r rev-parse -q --verify refs/tags/v0.6.4 > /dev/null"
done
check "rel conflict (plain): dev checked out nowhere, so rel used git merge-tree (no worktree touched)" sh -c "grep -q 'dev checked out in: no worktree' $F/rel-conf-plain.out && grep -q '^merge-tree: ' $F/rel-conf-plain.out"
check "rel conflict (worktree): the merge was aborted, dev's worktree clean" sh -c "[ -z \"\$(git -C $F/gconf-worktree-dev status --porcelain)\" ] && ! [ -e $F/gconf-worktree-dev/.git/MERGE_HEAD ] && ! git -C $F/gconf-worktree-dev rev-parse -q --verify MERGE_HEAD > /dev/null"

head1 "rel (scratch graftling, dev = base): fetch the bundle, dev and main fast-forward, annotated noreply tag"
steps rel > $F/rel.out 2>&1; RRC=$?; grep -E 'CHECK|version at|= $GC|dev:' $F/rel.out
check "rel exit 0 with four CHECK PASS" sh -c "[ $RRC -eq 0 ] && [ \$(grep '^CHECK 571 .*: PASS' $F/rel.out | sort -u | wc -l) -eq 4 ] && ! grep -q '^CHECK 571 .*: FAIL' $F/rel.out"
check "rel: v0.6.4 = dev = main = $GC (dev's linked worktree too), tagger noreply, version 0.6.4" sh -c "[ \$(git -C $FG rev-parse 'v0.6.4^{commit}') = $GC ] && [ \$(git -C $FG rev-parse dev) = $GC ] && [ \$(git -C $FG rev-parse main) = $GC ] && [ \$(git -C $FGD rev-parse HEAD) = $GC ] && git -C $FG for-each-ref --format='%(taggeremail)' refs/tags/v0.6.4 | grep -q '$NR' && grep -q 'version at v0.6.4: __version__ = \"0.6.4\"' $F/rel.out"
check "rel: prints the push as a separate step after the USER's yes, then gh, and the GraphTraj integration" sh -c "grep -q 'ADOPT571_PUSH_CONFIRMED=yes' $F/rel.out && grep -q 'zsh $SD/steps.zsh gh' $F/rel.out && grep -q 'GraphTraj 集成' $F/rel.out"
steps rel > $F/rel2.out 2>&1
check "rel again: already released, nothing to do" grep -q 'already released' $F/rel2.out

head1 "rp: refused without the USER's yes; with it, pushes to the scratch bare origin (never GitHub)"
steps gh > $F/gh-early.out 2>&1; GHE=$?
check "gh negative: before rp the remote main is not $GC -> STOP, nothing installed" sh -c "[ $GHE -ne 0 ] && grep -q 'STOP: GitHub main is not $GC' $F/gh-early.out && [ ! -e $F/ghroot ]"
steps rp > $F/rp.out 2>&1; RP=$?
check "rp without the USER's confirmation refuses (no push)" sh -c "[ $RP -ne 0 ] && grep -q 'STOP: the push is outward-facing' $F/rp.out && [ \$(git -C $F/remote.git rev-parse main) = $GOLD ]"
check "rp target is the scratch bare repository" sh -c "[ \$(git -C $FG remote get-url origin) = $F/remote.git ]"
ADOPT571_PUSH_CONFIRMED=yes steps rp > $F/rp-yes.out 2>&1; RPY=$?; grep -E 'remote|CHECK' $F/rp-yes.out
check "rp confirmed: remote main and v0.6.4 = $GC, remote dev = local dev" sh -c "[ $RPY -eq 0 ] && grep -q 'CHECK 571 remote main and v0.6.4 = $GC, remote dev = local dev: PASS' $F/rp-yes.out && [ \$(git -C $F/remote.git rev-parse 'v0.6.4^{commit}') = $GC ]"

head1 "gh (result 4): the bare address installs graftling-dsh 0.6.4 in an isolated DSH home (dsh stub)"
steps gh > $F/gh.out 2>&1; GHR=$?; grep -E 'GitHub main|exit=|bundles|installed|CHECK' $F/gh.out
check "gh exit 0: registered as a profile bundle, package.json says 0.6.4, ~/.dsh unchanged" sh -c "[ $GHR -eq 0 ] && grep -q 'CHECK 571 gh: bare $F/remote.git registers graftling-dsh as a profile bundle: PASS' $F/gh.out && grep -q 'CHECK 571 gh: installed graftling-dsh package.json says 0.6.4: PASS' $F/gh.out && grep -q 'CHECK 571 gh: ~/.dsh profiles unchanged: PASS' $F/gh.out"
check "gh: everything under the isolated root $F/ghroot" sh -c "[ -f $F/ghroot/home/profiles/gh571/node_modules/graftling-dsh/package.json ]"
steps gh > $F/gh-again.out 2>&1; GHA=$?
check "gh again: refuses while the isolated root exists" sh -c "[ $GHA -ne 0 ] && grep -q 'STOP: $F/ghroot exists' $F/gh-again.out"

head1 "B: wheels from git archive v0.6.4 (archive root) and of the candidate; version strings; requirement pairs"
steps B > $F/B.out 2>&1; BRC=$?; check "B exit 0" [ $BRC -eq 0 ]
grep -E 'whl|leaked|peels|annotated|CHECK|markers expected|GraphTraj dev|CHANGELOG heading|main:' $F/B.out
check "B: GraphTraj dev reported as information only; v0.6.4 annotated, peels to $GC" sh -c "grep -q 'dev contains ${NEW[1,8]}: no' $F/B.out && grep -q 'v0.6.4 peels to $GC: yes' $F/B.out && grep -q 'v0.6.4 is an annotated tag (cat-file -t: tag): yes' $F/B.out"
check "B: every version string 0.6.4; CHANGELOG heading 0.6.4" sh -c "grep -q 'CHECK 571 v0.6.4 version strings all 0.6.4: PASS' $F/B.out && grep -q '^CHANGELOG heading: ## 0.6.4 (incompatible)' $F/B.out"
check "B: Requires-Dist satisfied by 0.6.4 and NOT by 0.6.3" sh -c "grep -q 'CHECK 571 Requires-Dist graftling<0.7,>=0.6.4 satisfied by 0.6.4: PASS' $F/B.out && grep -q 'CHECK 571 Requires-Dist graftling<0.7,>=0.6.4 NOT satisfied by 0.6.3: PASS' $F/B.out"
check "B: both wheels = their archives; markers present 8/8; leaked 0" sh -c "grep -q 'CHECK 571 graphtraj wheel equals git archive ${NEW[1,8]}: PASS' $F/B.out && grep -q 'CHECK 571 graftling wheel equals git archive v0.6.4: PASS' $F/B.out && grep -q 'markers expected present: PASS (8/8)' $F/B.out && grep -q '^leaked: 0' $F/B.out"
check "B: the install directory holds exactly graphtraj-0.1.0 and graftling-0.6.4" sh -c "[ \$(ls $W/wheels-${NEW[1,8]}/*.whl | wc -l) -eq 2 ] && ls $W/wheels-${NEW[1,8]}/graftling-0.6.4-*.whl > /dev/null"
VERIFY571_GCOMMIT=$GBASE steps B > $F/B-tag.out 2>&1; BT=$?
check "B negative: a tag that does not peel to the expected commit STOPs" sh -c "[ $BT -ne 0 ] && grep -q 'STOP: v0.6.4^{commit} is $GC, not $GBASE' $F/B-tag.out"
VERIFY571_TARGET=$OLD steps B > $F/B-commit.out 2>&1; BC=$?
check "B negative: a wrong GraphTraj target commit STOPs at the guard" sh -c "[ $BC -ne 0 ] && grep -q 'STOP: the Worktree.s src tests plugins pyproject.toml differ from ${OLD[1,8]}' $F/B-commit.out"
print '# drift' >> $FWT/src/graphtraj/execution/runner_worker.py
steps B > $F/B-dirty.out 2>&1; BD=$?
check "guard negative: an uncommitted src change STOPs" sh -c "[ $BD -ne 0 ] && grep -q 'STOP: uncommitted changes in the Worktree.s src tests plugins pyproject.toml' $F/B-dirty.out"
git -C $FWT checkout -q -- src
steps B > /dev/null 2>&1

head1 "G through its real entry (6 shards; -k selects real tests, two with repository fixtures), queued behind a running suite; then GR"
GRECS0=$(print -l $W/G-${NEW[1,8]}-*(N/) | grep -c .)
steps GR > $F/GR-none.out 2>&1; GNO=$?
check "GR before any G: STOP 'run G first', FAIL" sh -c "[ $GNO -ne 0 ] && grep -q 'run G first' $F/GR-none.out && grep -q 'CHECK 571 GR (guard + G record): FAIL' $F/GR-none.out"
print -r -- "$HOSTLINE" > $F/ps.txt; print -r -- "4242 1 /usr/bin/python3 scripts/run_test_shards.py --shards 6 (another Task's suite, simulated)" >> $F/ps.txt
( sleep 7; print -r -- "$HOSTLINE" > $F/ps.txt ) &!
ADOPT571_PYTEST_ARGS="-k 'test_wheels_have_separate_owners or test_graphtraj_uses_only_published_agents_names or test_every_public_name_is_listed_in_the_contract or test_child_tool_descriptions_match_the_members_entry'" steps G > $F/G.out 2>&1; GRC=$?
GO=$(print -l $W/G-${NEW[1,8]}-*(N/om[1])); print "G record: $GO"; cat $GO/run.txt 2>/dev/null; grep -E 'WAITING|running:|queued|started' $F/G.out
check "G queued: says WAITING with the running suite, never stops (exit 0)" sh -c "[ $GRC -eq 0 ] && grep -q '^WAITING: Main.s suite queue is serial' $F/G.out && grep -q 'running: 4242' $F/G.out && grep -q '^queued in the background' $F/G.out"
check "G record: pytest temp under TMPDIR (outside the Harness), candidate, graftling commit, dependencies (click 8.5.0)" sh -c "grep -q 'pytest temp root: ${${TMPDIR:-/tmp}:A}/adopt-571-G-' $GO/run.txt && grep -q 'candidate: $(git -C $FWT rev-parse HEAD)' $GO/run.txt && grep -q 'git archive $GC' $GO/run.txt && grep -q 'click 8.5.0' $GO/run.txt"
steps GR > $F/GR-running.out 2>&1; GRN=$?
check "GR while G waits or runs: 'not finished', FAIL" sh -c "[ $GRN -ne 0 ] && grep -q 'G has not finished yet' $F/GR-running.out"
[[ -n $GO ]] && for i in {1..120}; do grep -q '^exit=' $GO/suite.txt 2>/dev/null && break; sleep 5; done; sleep 3
cat $GO/wait.txt; tail -3 $GO/suite.txt
check "G waited then started by itself: wait.txt has 'waiting for another suite: 4242' then 'started' and 'ended'" sh -c "grep -q 'waiting for another suite: 4242' $GO/wait.txt && grep -q ' started' $GO/wait.txt && grep -q ' ended' $GO/wait.txt"
check "G rehearsal: the four selected real tests PASSED (not collect-only), '4 passed', no FAILED line" sh -c "[ \$(grep -hoE '^PASSED tests/(test_runtime_distribution|test_graphtraj_public_agents_api|test_child_server_name_551)\.py::[a-z_0-9]+' $GO/shards/*.log | sort -u | wc -l) -eq 4 ] && grep -q '^4 passed' $GO/suite.txt && ! grep -qE '^(FAILED|ERROR) ' $GO/failures.txt"
check "G rehearsal: shards with nothing selected end 'exit 5' (pytest: no tests), so the run's exit is 1" sh -c "grep -q '^exit=1' $GO/suite.txt && ! grep 'ABNORMAL' $GO/suite.txt | grep -v 'exit 5' | grep -q ."
steps GR > $F/GR-G.out 2>&1; GRG=$?
check "GR reads the newest G record by itself: candidate, graftling commit and click accepted; exit=1 without classed lines -> FAIL (GR never accepts a nonzero exit by itself)" sh -c "[ $GRG -ne 0 ] && grep -q 'G record: $GO' $F/GR-G.out && grep -q 'same product: yes' $F/GR-G.out && grep -q '= v0.6.4 ($GC): yes' $F/GR-G.out && grep -q 'click = production.s 8.5.0: yes' $F/GR-G.out && grep -q 'exit: 1' $F/GR-G.out && grep -q 'no new failure: FAIL' $F/GR-G.out"

head1 "GR mechanics on a REHEARSAL FIXTURE record, and negatives on copies"
# The fixture is not evidence of a suite result: it holds this candidate, the v0.6.4 commit, production's click and one
# failure of a helper 516's current definition names.
GX=$F/grec; mkdir -p $GX
print -l "pytest temp root: ${${TMPDIR:-/tmp}:A}/fixture (REHEARSAL FIXTURE)" "candidate: $(git -C $FWT rev-parse HEAD) | graftling wheel from git archive $GC (REHEARSAL FIXTURE)" \
  "test interpreter dependencies: click 8.5.0 (fixture) | PyYAML 6.0.3 (fixture) | websockets 16.1.1 (fixture) | pytest 9.1.1 (fixture)" > $GX/run.txt
print -l "REHEARSAL FIXTURE" "1 failed, 3690 passed, 48 skipped" "exit=1" > $GX/suite.txt
print -l 'FAILED tests/test_mcp_host_tools.py::test_installed_mcp_server_keeps_the_continue_path_on_the_request_caller' '    E           assert 1.0 < 0.9' '    at tests/test_mcp_host_tools.py:1489' > $GX/failures.txt
ADOPT571_GREC=$GX steps GR > $F/GR.out 2>&1; GRR=$?; grep -E '^(product guard|candidate|graftling commit|totals|test interpreter|516|  known|  NEW|failed tests|CHECK)' $F/GR.out
check "GR on the fixture: the 516 helper failure known flaky; PASS" sh -c "[ $GRR -eq 0 ] && grep -q 'names the helper _assert_native_budget_stop' $F/GR.out && grep -q '^CHECK 571 GR (guard + G record): PASS' $F/GR.out"
mkdir -p $F/gneg && cp -Rp $GX $F/gneg/a && print -l 'FAILED tests/test_x.py::test_y' '    E       AssertionError: boom' >> $F/gneg/a/failures.txt
ADOPT571_GREC=$F/gneg/a steps GR > $F/GR-n1.out 2>&1; GN1=$?
check "GR negative: an unknown FAILED test -> NEW, FAIL, and no PASS left in GR.txt" sh -c "[ $GN1 -ne 0 ] && grep -q '  NEW: tests/test_x.py::test_y' $F/GR-n1.out && ! grep -q 'GR (guard + G record): PASS' $RW/GR.txt"
cp -Rp $GX $F/gneg/b && print -l 'FAILED tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[helper-main]' '    E       assert False' '    at tests/test_native_gateway.py:88' >> $F/gneg/b/failures.txt
ADOPT571_GREC=$F/gneg/b steps GR > $F/GR-n2.out 2>&1; GN2=$?
check "GR negative: a 560-known line that dev fixed (551) fails again -> NEW naming its source" sh -c "[ $GN2 -ne 0 ] && grep -q 'NEW (a 560-known line that dev fixed fails again; fixed by 551' $F/GR-n2.out"
cp -Rp $GX $F/gneg/c && $CONDA -I -c 'import re, sys; p = sys.argv[1]; open(p + ".new", "w").write(re.sub(r"git archive [0-9a-f]{40}", "git archive " + sys.argv[2], open(p).read()))' $F/gneg/c/run.txt $GBASE && mv $F/gneg/c/run.txt.new $F/gneg/c/run.txt
ADOPT571_GREC=$F/gneg/c steps GR > $F/GR-n3.out 2>&1; GN3=$?
check "GR negative: a G run with another graftling commit -> FAIL" sh -c "[ $GN3 -ne 0 ] && grep -q 'graftling commit of the wheel: $GBASE.* NO' $F/GR-n3.out"
cp -Rp $GX $F/gneg/d && $CONDA -I -c 'import sys; p = sys.argv[1]; open(p + ".new", "w").write(open(p).read().replace("click 8.5.0", "click 8.2.1"))' $F/gneg/d/run.txt && mv $F/gneg/d/run.txt.new $F/gneg/d/run.txt
ADOPT571_GREC=$F/gneg/d steps GR > $F/GR-n4.out 2>&1; GN4=$?
check "GR negative: a test interpreter with Miniconda's click 8.2.1 -> FAIL" sh -c "[ $GN4 -ne 0 ] && grep -q 'not production.s 8.5.0 (564): NO' $F/GR-n4.out"
ADOPT571_GREC=$GX steps GR > /dev/null 2>&1   # the fixture's PASS stands in for the record in the I/R rehearsal below
check "GR: earlier GR.txt kept as GR-<time>.txt" sh -c "ls $RW/GR-*.txt > /dev/null 2>&1"

head1 "V: plugin unchanged (predicted); real MCP tools/list and Codex hooks entry; markers both ways"
steps V > $F/V.out 2>&1; VRC=$?; check "V exit 0" [ $VRC -eq 0 ]
grep -E '^(SAME|CHANGED)|CHECK|^(PASS|FAIL):|markers expected|plugin dialog|^graftling v|^graphtraj [0-9a-f]|task graph' $F/V.out
check "V: plugin CHECK PASS (unchanged; no dialog expected); prediction lines printed" sh -c "grep -q 'CHECK 571 candidate plugin unchanged (predicted): PASS' $F/V.out && [ \$(grep -E '^SAME +(\.claude-plugin/plugin\.json|hooks/hooks\.json|hooks/host_context\.mjs)$' $F/V.out | sort -u | wc -l) -eq 3 ] && ! grep -q '^CHANGED ' $F/V.out && grep -q 'plugin dialog expected at claude --continue: no' $RW/V-dialog.txt && grep -q '^graftling v0.6.3..v0.6.4 under src/graftling/claude: src/graftling/claude/driver.py src/graftling/claude/execution.py' $F/V.out"
check "V: real graphtraj-mcp lists exactly agents, tasks; Codex hooks entry two CHECKs PASS" sh -c "grep -q 'CHECK 571 scratch-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/V.out && [ \$(grep '^CHECK 571 Codex hooks entry .*: PASS' $F/V.out | sort -u | wc -l) -eq 2 ]"
check "V: markers present in the candidate and absent in production (8/8)" sh -c "grep -q 'markers expected present: PASS (8/8)' $F/V.out && grep -q 'markers expected absent: PASS (8/8)' $F/V.out"
check "V: read check of production Task state (task graph) by the candidate" grep -q 'task graph of the clone: tasks =' $F/V.out
check "V wrote nothing to production entry files" shasum -a 256 -c --quiet $F/entries0.sha256

head1 "negatives: 0.6.3 left installed; markers both ways"
VS=($FB/vvenv-${NEW[1,8]}/lib/python*/site-packages(N))
mkdir -p $F/lneg && cp -Rp $VS[1] $F/lneg/site && cp -Rp $D/graftling-0.6.3.dist-info $F/lneg/site/
$CONDA -I $SD/proddiff.py $F/lneg/site $F/lneg $W/wheels-${NEW[1,8]} > $F/lneg.out 2>&1; LN=$?
check "proddiff negative: graftling 0.6.3's dist-info left beside 0.6.4 -> FAIL (LEFTOVER)" sh -c "[ $LN -ne 0 ] && grep -q 'LEFTOVER' $F/lneg.out"
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
cp -p $RW/GR.txt $F/GR-good.txt; print 'CHECK 571 GR (guard + G record): FAIL' > $RW/GR.txt
print | steps I > $F/I-noGR.out 2>&1; INR=$?
check "I negative: refuses while GR.txt has no PASS, and creates no backup" sh -c "[ $INR -ne 0 ] && grep -q 'GR 还不是 PASS' $F/I-noGR.out && [ ! -e $FB/backup ]"
cp -p $F/GR-good.txt $RW/GR.txt
print -r -- "$HOSTLINE" > $F/ps.txt
steps Mpre > $F/Mpre.out 2>&1
check "Mpre: GR PASS shown; restart reason names the loaded old modules" sh -c "grep -q '^GR: PASS (CHECK 571 GR (guard + G record): PASS)' $F/Mpre.out && grep -q '安装会在它运行时替换这些文件' $F/Mpre.out"
: > $F/ps.txt
print | steps I > $F/I.out 2>&1; IRC=$?; check "I exit 0" [ $IRC -eq 0 ]
grep -E 'Successfully|^PASS|^FAIL|CHECK|direct_url|built from|configuration --write rc|plugin files|SAME-AS-VALIDATED|markers expected|bytes unchanged' $F/I.out
check "I: both wheels installed together, proddiff PASS, 0.6.3 dist-info gone, markers 8/8" sh -c "grep -q '^Successfully installed graftling-0.6.4 graphtraj-0.1.0' $F/I.out && grep -q '^PASS' $F/I.out && grep -q 'CHECK 571 graftling 0.6.3 dist-info gone: PASS' $F/I.out && grep -q 'markers expected present: PASS (8/8)' $F/I.out"
check "I: direct_url of both names wheels-${NEW[1,8]}; built from both archives" sh -c "grep -q 'CHECK 571 direct_url of both names the wheels-${NEW[1,8]} wheels: PASS' $F/I.out && grep -q 'built from: graphtraj git archive $NEW, graftling git archive v0.6.4 $GC' $F/I.out"
check "I: configuration --write rc=0, plugin unchanged, .mcp.json PASS, SAME-AS-VALIDATED" sh -c "grep -q 'configuration --write rc=0' $F/I.out && grep -q 'CHECK 571 installed plugin unchanged: PASS' $F/I.out && grep -q 'CHECK 515 .mcp.json has graphtraj' $F/I.out && grep -q SAME-AS-VALIDATED $F/I.out"
check "I: real entries of the installed venv: MCP tools/list and Codex hooks PASS" sh -c "grep -q 'CHECK 571 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/I.out && [ \$(grep '^CHECK 571 Codex hooks entry .*: PASS' $F/I.out | sort -u | wc -l) -eq 2 ]"
check "I: no Task-state migration ran (no migrate lines)" sh -c "! grep -qE 'migrate-task-definitions|CHECK 571 563|preview rc=' $F/I.out"
check "I: backup holds venv, plugin, entries, tools; COMPLETE" sh -c "[ -e $FB/backup/COMPLETE ] && [ -f $FB/backup/entries/.mcp.json ] && [ -f $FB/backup/plugin/hooks/host_context.mjs ] && [ -f $FB/backup/tools/steps.zsh ] && [ -f $FB/backup/tools/pkgdiff532.py ] && [ -d $FB/backup/venv ]"
check "I: prints the restart command and V's expected dialog (none)" sh -c "grep -q \"cd $FH && claude --continue\" $F/I.out && grep -q '预期对话框: plugin dialog expected at claude --continue: no' $F/I.out"

head1 "M / Mp after the restart; N; done"
print -r -- "$HOSTLINE" > $F/ps.txt
steps M > $F/M.out 2>&1
check "M prompt: upgraded by Task 571; task_graph with view current (560's 'summary' fixed)" sh -c "grep -q 'Production was just upgraded by Task 571' $F/M.out && grep -q '{\"view\":\"current\"}' $F/M.out && ! grep -q '\"view\":\"summary\"' $F/M.out"
steps Mp > $F/Mp.out 2>&1; MPR=$?
check "Mp exit 0: four init CHECKs PASS" sh -c "[ $MPR -eq 0 ] && [ \$(grep -c 'CHECK 515 init .*: PASS' $RW/Mp.txt) -eq 4 ]"
steps N > $F/N.out 2>&1
check "N: one advisor member of Task 571 creates n571" sh -c "grep -q '\"task_id\":\"571\",\"role\":\"opus_coding_team.advisor\"' $F/N.out && grep -q 'create ONE claude child named n571' $F/N.out"
export FAKE_PROBE_API_KEY=sk-rehearsal-value-123456
steps done > $F/done.out 2>&1
check "done: versions, direct_urls, real entries PASS, no key value" sh -c "grep -q '^Version: 0.6.4' $F/done.out && grep -q 'graftling direct_url: .*wheels-${NEW[1,8]}' $F/done.out && grep -q 'CHECK 571 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS' $F/done.out && grep -q 'raw files containing an exported key value: 0' $F/done.out"
check "done: counts are 0 when nothing matches (560's miscount fixed): '0.6.3 dist-info left: 0', 'task.md 0'" sh -c "grep -q 'graftling 0.6.3 dist-info left: 0 (expect 0)' $F/done.out && grep -q 'Task state now: task.md 0 ' $F/done.out"

head1 "R (rollback from the backup's own tools): both packages, plugin and entries restored"
: > $F/ps.txt
print | zsh $FB/backup/tools/steps.zsh R > $F/R.out 2>&1; RR2=$?; grep -E '^(SAME|DIFF)|restored|already as|^Version|CHECK|graphtraj package|before R' $F/R.out
check "R exit 0; venv and plugin SAME" sh -c "[ $RR2 -eq 0 ] && [ \$(grep -c 'SAME differences=0' $F/R.out) -ge 2 ]"
check "R: graftling and graphtraj restored (vs backup); graftling is 0.6.3 again" sh -c "grep -q 'CHECK 571 graftling restored (after R vs backup): PASS' $F/R.out && grep -q 'CHECK 571 graphtraj restored (after R vs backup): PASS' $F/R.out && grep -q 'CHECK 571 R: graftling is 0.6.3 again: PASS' $F/R.out"
check "R: production graftling 0.6.3, graphtraj ${OLD[1,8]} markers absent again; entries as before" sh -c "$FRT/bin/python -m pip show graftling 2>/dev/null | grep -q 'Version: 0.6.3' && $CONDA -I $SD/markers.py $D absent > /dev/null && shasum -a 256 -c --quiet $F/entries0.sha256"
check "R: the old code still reads the state (task graph loads)" sh -c "cd $FH && $FRT/bin/python -I -c 'from pathlib import Path; from graphtraj.graph.task_graph import read_graph; g = read_graph(Path(\"$FS\"), view=\"full\"); print(\"old code task graph:\", len(g[\"tasks\"]))'"
check "560's backup under tmp/560 unchanged" sh -c "cd $FH && shasum -a 256 -c --quiet $F/evidence0.sha256"
git -C $REALG for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags > $F/realg-refs-after.txt
check "real <Harness>/graftling untouched by the rehearsal (every branch and tag as at the start)" cmp -s $F/realg-refs-before.txt $F/realg-refs-after.txt

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
