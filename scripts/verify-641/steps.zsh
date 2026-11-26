#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 641 Main-run steps: task_backup recreates an Issue whose mapped Issue was deleted (GitHub HTTP 410), names the
# deleted number, relinks the Sub-issue and never creates a second Issue on a repeat. Candidate = this Worktree's HEAD
# (GraphTraj dev c18b4beb + 641); graftling 0.10.2 (v0.10.2 = 57bca736) from <Harness>/graftling, as a WHEEL.
# Modelled on scripts/verify-614/steps.zsh (isolated ROOT, wheels, setup, host configuration, trust, real claude -p,
# judge) and scripts/adopt-612/steps.zsh (G waits for its shards and ends with the verdict; SR against Task 516's
# CURRENT definition; suite-base). Production (<Harness>/.venv-runtime) is only read (click, PyYAML, websockets
# copied). graftling is not changed. Nothing is pushed. README.md says what each step proves.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre     Main. ROOT must not exist (STOP with the exact rm). zsh, HEAD, base c18b4beb and graftling v0.10.2; no
#           uncommitted change; TMPDIR outside the Harness; your locations listed into ROOT/user-before.txt. ONE one-line
#           `claude -p` (no MCP, no tool): the init record names model and login. `gh auth status` for github.com with
#           your HOME AND with the MCP server's environment (HOME=ROOT/home, GH_CONFIG_DIR=your gh config directory);
#           the repository (from this Worktree's origin) answers with admin permission (needed to delete Issues).
#           LOGIN: your Claude login and your gh login (Main asks the user first). Dialog: none. ~30 s.
#   install Main. ROOT/venv: HEAD + graftling v0.10.2, both WHEELS, offline. Dialog: none. No login. ~1 min.
#   setup   Main. ROOT/proj (own git) through public `graphtraj setup`; probe Tasks 1 (parent) and 2 (child) through
#           public `graphtraj task register`, then shown ready through public task_graph; Claude host material through
#           `host configuration --write`; ROOT/mcp-641.json. Dialog: none. No login. <1 min.
#   trust   USER, once per ROOT path. Dialog: "Do you trust the files in this folder?" -> "Yes, proceed"; then /exit.
#   real    Main. Two `claude -p` runs in ROOT/proj (--allowedTools mcp__graphtraj__tasks only) with the gh login,
#           creating disposable Issues in the repository: run 1 backs up 1 and 2 (created, 2 linked); `gh issue
#           delete` deletes 2's Issue (answers 410); run 2 backs up 2 twice (recreated naming the old number and
#           linked under 1, then unchanged); the marker search finds exactly one Issue for 2 and the parent's
#           sub_issues list it. ALWAYS (also after a FAIL): every Issue it created is deleted and shown to answer 410.
#           LOGIN: your Claude and gh logins. Dialog: none. Network: Claude, GitHub. ~2-4 min.
#   post    Main. Your locations vs pre (names, sizes, mtimes). <5 s.
#   G       Main. Full suite of HEAD + the v0.10.2 wheel (6 shards, scripts/run_test_shards.py); waits for other test
#           runs first, then for its shards; its LAST lines are the verdict, counts and next command. pytest temp
#           under TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Dialog: none. No login. ~25-30 min.
#   SR      Main, read only: the newest G record classed against 516's CURRENT definition (+ the known start-an-agent id).
#   suite-base  Main, only for SR's NEW ids: base c18b4beb vs candidate, both with the v0.10.2 wheel.
# Credentials: before any step, every exported credential-class variable (names ending KEY, TOKEN, SECRET(S),
# PASSWORD, CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) is unset and its NAME printed, so gh uses only your stored
# login. Every started process gets an ALLOWLIST environment (clean(): PATH HOME USER TERM TMPDIR LANG and the step's
# own NAME=value). Claude and the script's own gh get your HOME; GraphTraj processes get HOME=ROOT/home; the MCP server
# gets HOME=ROOT/home plus GH_CONFIG_DIR (a directory name, never a token). No token is written anywhere.
# Rehearsal only (Engineer; Main leaves all unset): VERIFY641_ROOT, VERIFY641_T, VERIFY641_OUT, VERIFY641_USERHOME,
# VERIFY641_DEPS, VERIFY641_PYTEST_ARGS, VERIFY641_GWAIT, VERIFY641_NO_PS=1, VERIFY641_CLAUDE and VERIFY641_GH
# (stand-ins), VERIFY641_GHCONFIG, VERIFY641_REPO. A run with any of them set prints REHEARSAL and is not evidence.
# No zsh special parameter name is used as a variable (path, status, argv, prompt, reply, match, ...).
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
STEP=${1:-}
TASKDIR=641-task-backup-recreate-deleted-issue
GREPO=$H/graftling                                  # read only
GCOMMIT=57bca73657d3135a4504904fcc3f1898c2419766    # graftling 0.10.2, tag v0.10.2
GVERSION=0.10.2
GTBASE=c18b4bebd42d9c7801fd5ba26a290d585a021118    # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: deps are copied from here
DEPS=(${=${VERIFY641_DEPS:-$RTSP}})
CONDA=$HOME/miniconda3/bin/python3.13               # builds the wheels and venvs; runs x641.py
ROOT=${VERIFY641_ROOT:-/private/tmp/graphtraj-641}  # isolated project, HOME and venv (outside the Harness)
T=${VERIFY641_T:-$H/tmp/641}                        # suite venvs, sources and records
OUT=${VERIFY641_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost}
UH=${VERIFY641_USERHOME:-$HOME}
HOMEDIR=$ROOT/home
P=$ROOT/proj
VENV=$ROOT/venv
MAP=$P/.graphtraj/state/task-backups.yml           # the isolated project's backup mappings (never production's)
X641=$SD/x641.py
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN_EXTRA=("tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]")   # 611; base too
PYTEST_TMP=${TMPDIR:-/tmp}
BASEPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
GHCFG=${VERIFY641_GHCONFIG:-${GH_CONFIG_DIR:-${XDG_CONFIG_HOME:-$UH/.config}/gh}}   # where your gh login is kept
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
REHEARSAL=$(print -r -- ${(k)parameters[(I)VERIFY641_*]})

say()  { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
# Allowlist environment: PATH HOME USER TERM TMPDIR LANG and the given NAME=value words, then the command.
clean() { env -i PATH=$VENV/bin:$HOME/.local/bin:$BASEPATH HOME=$HOMEDIR USER=${USER:-user} TERM=${TERM:-xterm} \
            TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8 "$@"; }
claude_bin() {  # the user's Claude CLI (absolute); VERIFY641_CLAUDE only in a rehearsal (a stand-in)
  local c=${VERIFY641_CLAUDE:-$HOME/.local/bin/claude}; [[ -x $c ]] || c=$(command -v claude 2>/dev/null)
  print -r -- ${c:-NOT-FOUND}
}
gh_bin() {  # the user's gh (absolute); VERIFY641_GH only in a rehearsal (a stand-in)
  local g=${VERIFY641_GH:-}; [[ -n $g ]] || g=$(PATH=$BASEPATH command -v gh 2>/dev/null)
  print -r -- ${g:-NOT-FOUND}
}
ugh() { clean HOME=$UH $(gh_bin) "$@"; }            # the script's own gh: your HOME, your stored login
repo() {  # owner/name from this Worktree's origin (VERIFY641_REPO only in a rehearsal)
  [[ -n ${VERIFY641_REPO:-} ]] && { print -r -- $VERIFY641_REPO; return; }
  local u=$(git -C $WT remote get-url origin 2>/dev/null); u=${${u%.git}#*github.com[:/]}
  print -r -- $u
}
inproj() { (cd $P && clean "$@"); }
user_state() {  # names, sizes and mtimes only, never contents
  local d; for d in $UH/.graphtraj $UH/.codex $UH/.pi/agent $UH/.dsh; do
    ls -laT $d 2>&1 | awk -v d=${d#$UH/} 'NF >= 10 && $10 != ".." {print d, $5, $6, $7, $8, $9, $10}'
  done
}
outside() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
copy_deps() {  # venv: click, PyYAML, websockets copied from production (read only) when the venv lacks them
  local V=$1 D m s found
  D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    found=0
    for s in $DEPS; do
      [[ -d $s/$m ]] || continue
      case $m in
        yaml) cp -Rp $s/yaml $s/_yaml(N) $s/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
        *) cp -Rp $s/$m $s/$m-*.dist-info(N) $D/ ;;
      esac && { found=1; break; }
    done
    (( found )) || { print -r -- "STOP: $m not found in ${DEPS[*]}"; return 1; }
  done
}
graftling_wheel() {  # $1 dir: graftling v0.10.2 built offline from git archive into $1/wheels
  local S=$1
  rm -rf -- $S/graftling && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  clean $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null
}
venv_ready() { [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]] || { print -r -- "STOP: $VENV is not HEAD $HEAD; run: zsh $THIS install"; return 1; } }
other_suites() {  # exit 2 when ps cannot list (never read as "none")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then
    [[ ${VERIFY641_NO_PS:-} == 1 ]] && { print -u2 -r -- "REHEARSAL: ps cannot list processes here; other-run check skipped (VERIFY641_NO_PS=1)"; return 0; }
    print -r -- "ps cannot list processes"; return 2
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E' ; return 0
}
cdef_516() {  # Task 516's CURRENT definition file, through its task.yml current_definition
  local c=${${${(M)${(f)"$(cat $D516/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- ${c:+$D516/$c}
}
grec() { print -r -- ${$(print -l $T/G-*(N/om[1])):-$T/G-none}; }
sr_classify() {  # $1 = G record; sets SR_NEW SR_ANY SR_IDS; writes <record>/new-ids.txt
  local rec=$1 line t id K=$(cdef_516); SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): ${K:-unreadable}"
  [[ -f $K ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if (( ${KNOWN_EXTRA[(Ie)$id]} )); then print -r -- "  known (611, fails on base too; graftling's models description says 'starts no Agent'): $id"
    elif grep -qF -- "${t##*::}" $K; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print -r -- "  (no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL ' $rec/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *': exit 5') grep -q '^REHEARSAL' $rec/run.txt && print -r -- "  rehearsal filter, nothing collected: $line" || { print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1; } ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -l -- $SR_IDS > $rec/new-ids.txt
}
g_venv() {  # $1 venv, $2 checkout: graftling v0.10.2 WHEEL + the checkout editable (the suite needs its metadata)
  local V=$1 S=$1-src
  [[ $(cat $V/installed 2>/dev/null) == "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" ]] && { print -r -- "reusing $V"; return 0; }
  rm -rf -- $V $S && mkdir -p $S || return 1
  graftling_wheel $S || return 1
  clean $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  clean $V/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && clean $V/bin/python -m pip install $PIP -e $2 > /dev/null || return 1
  print -r -- "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" > $V/installed
}
# --- real: Issue bookkeeping -------------------------------------------------------------------------------------
CREATED=()   # every Issue number this run created (from results, the mapping file and the repository listing)
listing() {  # $1 out: the repository's Issues updated since STARTED - 5 min (GraphTraj's own marker-search query)
  local since=$(clean $CONDA -I -c 'import sys, datetime as d; t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")) - d.timedelta(minutes=5); print(t.strftime("%Y-%m-%dT%H:%M:%SZ"))' $STARTED)
  ugh api --method GET "repos/$R/issues?state=all&sort=created&direction=desc&per_page=100&since=$since" > $1 2> $1.err
}
answers_410() {  # $1 number: 0 when GitHub answers that Issue deleted (HTTP 410)
  ugh api --method GET repos/$R/issues/$1 > /dev/null 2> $ROOT/get-$1.err && return 1
  grep -q '(HTTP 410)' $ROOT/get-$1.err
}
remember() { local n; for n in "$@"; do [[ $n == <-> ]] && (( ! ${CREATED[(Ie)$n]} )) && CREATED+=$n; done; return 0; }
cleanup() {  # ALWAYS: delete every Issue this run created, then show each answers 410
  say "cleanup (always runs): delete every Issue this run created"
  local n bad=0
  [[ -n ${R:-} ]] || return 0
  remember ${=$(clean $CONDA -I $X641 numbers $MAP 2>/dev/null)}
  for n in $ROOT/run-*-summary.json(N); do remember ${=$(clean $CONDA -I -c 'import json, sys; print(" ".join(str(v) for v in json.load(open(sys.argv[1])).values() if v))' $n)}; done
  listing $ROOT/cleanup-listing.json && remember ${=$(clean $CONDA -I $X641 ours $ROOT/cleanup-listing.json $STARTED)} \
    || print -r -- "listing for cleanup failed: $(head -c 200 $ROOT/cleanup-listing.json.err)"
  print -r -- "Issues created by this run: ${CREATED:-none} (in $R)"
  for n in ${(on)CREATED}; do
    if answers_410 $n; then print -r -- "  #$n: already deleted (answers HTTP 410)"; continue; fi
    ugh issue delete $n --repo $R --yes > $ROOT/delete-$n.txt 2>&1 || print -r -- "  #$n: gh issue delete failed: $(head -c 200 $ROOT/delete-$n.txt)"
    answers_410 $n && print -r -- "  #$n: deleted now (answers HTTP 410)" || { print -r -- "  #$n: NOT deleted: $(head -c 200 $ROOT/get-$n.err)"; bad=1; }
  done
  (( bad )) && { fail "an Issue this run created is not deleted (above); delete it with: gh issue delete <number> --repo $R --yes"; } \
            || pass "every Issue this run created now answers HTTP 410: ${CREATED:-none}"
  print -r -- "Issues deleted: ${CREATED:-none}" > $ROOT/issues-created-and-deleted.txt
}
claude_run() {  # $1 run number: one claude -p in P with only mcp__graphtraj__tasks; stream ROOT/run-$1.jsonl
  local PR=$(clean $CONDA -I $X641 prompt $1 $R) C=$(claude_bin)
  print -r -- "run $1 prompt (one line): $PR"
  rm -f $ROOT/run-$1.jsonl $ROOT/run-$1-stderr.txt
  (cd $P && clean HOME=$UH /usr/bin/perl -e 'alarm shift; exec @ARGV' 600 $C -p --output-format stream-json --verbose \
     --mcp-config $ROOT/mcp-641.json --strict-mcp-config --allowedTools mcp__graphtraj__tasks \
     <<< $PR > $ROOT/run-$1.jsonl 2> $ROOT/run-$1-stderr.txt); print -r -- "claude -p run $1 exit=$?"
  local -a si=(); [[ -n ${VERIFY641_CLAUDE:-} ]] && si=(--stand-in)
  clean $CONDA -I $X641 judge $1 $ROOT/run-$1.jsonl $R $ROOT/run-$1-summary.json ${2:-} $si | tee $ROOT/run-$1-judge.txt
  local jrc=${pipestatus[1]}
  cp $ROOT/run-$1.jsonl $ROOT/run-$1-stderr.txt $ROOT/run-$1-judge.txt $OUT/ 2>/dev/null
  return $jrc
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT; ONE one-line claude -p (no MCP, no tool); gh auth status (read only). LOGIN: your Claude and gh logins (Main asks the user first). Dialog: none."
  OK=1
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists (an earlier run). Look at it, then run exactly:"; print -r -- "  rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  mkdir -p $ROOT $HOMEDIR $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT merge-base --is-ancestor $GTBASE $HEAD 2>/dev/null && pass "base GraphTraj $GTBASE is an ancestor of HEAD" || fail "base $GTBASE is not an ancestor of HEAD"
  [[ $(git -C $GREPO rev-parse -q --verify 'v0.10.2^{commit}' 2>/dev/null) == $GCOMMIT ]] \
    && pass "graftling v0.10.2 = $GCOMMIT in $GREPO (wheel source)" || fail "graftling v0.10.2 is not $GCOMMIT in $GREPO"
  local dirty=$(git -C $WT status --porcelain -- src tests scripts/verify-641/steps.zsh scripts/verify-641/x641.py pyproject.toml)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, the step files" || fail "uncommitted changes: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m s d; for m in click yaml websockets; do s=0; for d in $DEPS; do [[ -d $d/$m ]] && s=1; done
    (( s )) && pass "$m present in ${DEPS[*]}" || fail "$m missing in ${DEPS[*]}"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/ 2>/dev/null
  print -r -- "your locations before (names, sizes, mtimes): $(wc -l < $ROOT/user-before.txt | xargs) lines in $ROOT/user-before.txt (~/.claude, ~/.claude.json and the gh config are not compared)"
  local C=$(claude_bin) G=$(gh_bin) R=$(repo)
  [[ -x $C ]] && pass "claude: $C" || fail "no Claude CLI at ~/.local/bin/claude or on PATH"
  [[ -x $G ]] && pass "gh: $G ($(ugh --version 2>&1 | head -1))" || fail "no gh in $BASEPATH"
  print -r -- "claude's environment (names only): $(clean HOME=$UH /usr/bin/env | cut -d= -f1 | sort | xargs)"
  (cd $ROOT && clean HOME=$UH /usr/bin/perl -e 'alarm shift; exec @ARGV' 180 $C -p --output-format stream-json --verbose --strict-mcp-config \
     <<< 'Reply in one line: the exact model id you run as, and whether you are signed in with a Claude account or an API key.' \
     > $ROOT/pre-stream.jsonl 2> $ROOT/pre-stderr.txt); print -r -- "claude -p exit=$?"
  clean $CONDA -I -c 'import json, sys
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "system" and d.get("subtype") == "init": print("init: model", d.get("model"), "| apiKeySource", d.get("apiKeySource"))
    if d.get("type") == "result": print("answer:", str(d.get("result"))[:200], "| is_error", d.get("is_error")); sys.exit(1 if d.get("is_error") else 0)
sys.exit(1)' $ROOT/pre-stream.jsonl && pass "the Claude host answered (model and login above)" \
    || fail "no answer from claude -p; stderr: $(head -c 300 $ROOT/pre-stderr.txt). If it says login: the USER signs in with 'claude' in Terminal, then rm -rf ${(qq)ROOT} && zsh $THIS pre"
  cp $ROOT/pre-stream.jsonl $ROOT/pre-stderr.txt $OUT/ 2>/dev/null
  # gh: the account name is not printed; only whether a login answers for github.com.
  ugh auth status --hostname github.com > $ROOT/gh-auth.txt 2>&1 \
    && pass "gh auth status (your HOME): logged in to github.com" || fail "gh auth status (your HOME) failed: the USER runs 'gh auth login' in Terminal"
  clean HOME=$HOMEDIR GH_CONFIG_DIR=$GHCFG $G auth status --hostname github.com > $ROOT/gh-auth-mcp.txt 2>&1 \
    && pass "gh auth status with the MCP server's environment (HOME=$HOMEDIR, GH_CONFIG_DIR=$GHCFG): logged in" \
    || fail "gh does not reach your login with HOME=$HOMEDIR and GH_CONFIG_DIR=$GHCFG: $(grep -v -i account $ROOT/gh-auth-mcp.txt | head -2 | xargs)"
  local admin=$(ugh api --method GET repos/$R --jq .permissions.admin 2> $ROOT/gh-repo.err)
  [[ $admin == true ]] && pass "repository $R (this Worktree's origin) answers; your login is admin there (needed by gh issue delete)" \
                       || fail "repository $R: admin=${admin:-?} $(head -c 200 $ROOT/gh-repo.err)"
  print -r -- "writes: $ROOT and copies in $OUT only. GitHub: read only. dialog: none."
  (( OK )) && print -r -- "RESULT 641 pre: PASS" || print -r -- "RESULT 641 pre: FAIL (lines above)"
  (( OK )) && print -r -- "next (paste): zsh $THIS install" || print -r -- "next: report the FAIL lines (then: rm -rf ${(qq)ROOT} && zsh $THIS pre)"
  (( OK ))
  ;;
install)
  say "[install] Main. $VENV: GraphTraj $HEAD (wheel) + graftling $GVERSION ($GCOMMIT wheel), offline. Dialog: none. No login."
  OK=1
  need $ROOT/user-before.txt pre || return 1
  local S=$ROOT/venv-src
  if [[ $(cat $VENV/installed 2>/dev/null) == $HEAD ]]; then print -r -- "reusing $VENV (graphtraj $HEAD)"
  else
    rm -rf -- $VENV $S && mkdir -p $S/graphtraj || return 1
    git -C $WT archive $HEAD | tar -x -C $S/graphtraj || return 1
    graftling_wheel $S || return 1
    clean $CONDA -m pip wheel $PIP -w $S/wheels $S/graphtraj > /dev/null || { print -r -- "STOP: GraphTraj wheel build failed"; return 1; }
    clean $CONDA -m venv $VENV && copy_deps $VENV || return 1
    clean $VENV/bin/python -m pip install $PIP $S/wheels/graftling-*.whl $S/wheels/graphtraj-*.whl || return 1
    print -r -- $HEAD > $VENV/installed
  fi
  (cd $ROOT && clean $VENV/bin/python -I -c 'import sys, graphtraj, graftling, importlib.metadata as m
from pathlib import Path
url = m.distribution("graphtraj").read_text("direct_url.json") or ""
site = Path(sys.argv[1]).resolve()
ok = Path(graphtraj.__file__).resolve().is_relative_to(site) and "editable" not in url
print("graphtraj", graphtraj.__file__, "| wheel:", ok, "| graftling", graftling.__version__, graftling.__file__)
sys.exit(0 if ok and graftling.__version__ == sys.argv[2] and Path(graftling.__file__).resolve().is_relative_to(site) else 1)' $VENV $GVERSION) \
    && pass "venv imports graphtraj $HEAD (wheel) and graftling $GVERSION ($GCOMMIT wheel)" || fail "venv does not import both wheels"
  grep -q 'class IssueDeleted' $VENV/lib/python3.13/site-packages/graphtraj/graph/github_backup.py \
    && pass "installed GraphTraj has the 641 change (IssueDeleted)" || fail "installed GraphTraj lacks the 641 change"
  for m in graphtraj graphtraj-mcp; do [[ -x $VENV/bin/$m ]] && pass "$VENV/bin/$m" || fail "$VENV/bin/$m missing"; done
  print -r -- "writes: $VENV and $S only. dialog: none."
  (( OK )) && print -r -- "RESULT 641 install: PASS" || print -r -- "RESULT 641 install: FAIL (lines above)"
  (( OK )) && print -r -- "next (paste): zsh $THIS setup" || print -r -- "next: fix the FAIL lines, then: zsh $THIS install"
  (( OK ))
  ;;
setup)
  say "[setup] Main. Project $P, probe Tasks 1 (parent) and 2 (child), Claude host material, $ROOT/mcp-641.json. Dialog: none. No login."
  OK=1
  venv_ready || return 1
  [[ -e $P ]] && { print -r -- "STOP: $P exists (an earlier setup). Start over: rm -rf ${(qq)ROOT} && zsh $THIS pre"; return 1; }
  mkdir -p $P || return 1
  (cd $P && git init -q -b main && print -r -- "# 641 probe: task_backup recreates a deleted Issue" > README.md && git add README.md \
     && git -c user.name=641 -c user.email=641@invalid commit -qm "Initial source") || return 1
  print y | inproj $VENV/bin/graphtraj setup 2>&1 | tail -2
  [[ -d $P/.graphtraj ]] && pass "graphtraj setup created $P/.graphtraj" || fail "graphtraj setup made no $P/.graphtraj"
  local id parent
  for id parent in 1 - 2 1; do
    clean $CONDA -I $X641 task $id $parent $ROOT/task-$id.yml || return 1
    inproj $VENV/bin/graphtraj task register --task-file $ROOT/task-$id.yml > $ROOT/register-$id.txt 2>&1 \
      && pass "public task register: Task $id ($(tail -1 $ROOT/register-$id.txt))" || fail "task register $id: $(tail -2 $ROOT/register-$id.txt)"
  done
  inproj $VENV/bin/python -I $X641 graph && pass "probe Tasks are ready in the isolated task graph (public task_graph): 1 parent, 2 its child" \
    || fail "the isolated task graph does not hold probe Tasks 1 and 2 (above)"
  local C=$(claude_bin) G=$(gh_bin)
  [[ -x $C ]] || { fail "no Claude CLI at ~/.local/bin/claude or on PATH (the host configuration names it)"; return 1; }
  inproj $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write > $ROOT/host-configuration.txt 2>&1 \
    && pass "Claude host material written: $(tr -d '\n ' < $ROOT/host-configuration.txt | cut -c1-200)" || fail "host configuration --write failed ($ROOT/host-configuration.txt)"
  clean $VENV/bin/python -I $X641 mcpconfig $P/.mcp.json $ROOT/mcp-641.json $HOMEDIR $GHCFG ${G:h} || OK=0
  [[ -e $MAP ]] && fail "a backup mapping already exists: $MAP" || pass "no backup mapping yet ($MAP absent)"
  cp $ROOT/mcp-641.json $ROOT/task-1.yml $ROOT/task-2.yml $OUT/ 2>/dev/null
  print -r -- "writes: $ROOT only. dialog: none."
  (( OK )) && print -r -- "RESULT 641 setup: PASS" || print -r -- "RESULT 641 setup: FAIL (lines above)"
  (( OK )) && print -r -- "next: the USER runs the trust step once (zsh $THIS trust prints it), then Main: zsh $THIS real" \
           || print -r -- "next: report the FAIL lines"
  (( OK ))
  ;;
trust)
  say "[trust] USER, once per path $P (Main cannot: it needs a terminal and a dialog). In a plain macOS Terminal:"
  print -r -- "  cd ${(qq)P} && $(claude_bin) --strict-mcp-config"
  print -r -- "Dialog: 'Do you trust the files in this folder?' naming $P. Choose 'Yes, proceed'."
  print -r -- "If a second dialog asks about this project's plugin graphtraj-claude-host or its hooks, approve it for this project."
  print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print -r -- "Why: Claude Code loads a project's plugin (the graphtraj-claude-host hook that prepares each native call)"
  print -r -- "only in a trusted folder, and records trust only through this dialog; claude -p never asks."
  print -r -- "RESULT 641 trust: instructions printed (nothing was run)"
  print -r -- "next (Main, after the USER's /exit): zsh $THIS real"
  ;;
real)
  say "[real] Main. Two claude -p runs in $P (mcp__graphtraj__tasks only) and gh with your login; disposable Issues in $(repo), ALL deleted at the end (also after a FAIL). LOGIN: your Claude and gh logins. Dialog: none. ~2-4 min."
  OK=1
  venv_ready && need $ROOT/mcp-641.json setup || return 1
  [[ -e $MAP ]] && { print -r -- "STOP: $MAP exists (an earlier real run; its Issues were deleted by its cleanup). Look at it, then run exactly:"
                     print -r -- "  rm ${(qq)MAP} && zsh $THIS real"; return 1; }
  R=$(repo); STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ); CREATED=()
  rm -f $ROOT/run-*-summary.json(N)
  print -r -- "repository: $R | started $STARTED | MCP: $(clean $CONDA -I -c 'import json, sys; e = json.load(open(sys.argv[1]))["mcpServers"]["graphtraj"]; print("env names:", sorted(e.get("env", {})))' $ROOT/mcp-641.json)"
  print -r -- "claude's environment (names only): $(clean HOME=$UH /usr/bin/env | cut -d= -f1 | sort | xargs) | allowed tools: mcp__graphtraj__tasks"
  {
    say "run 1: back up parent 1 and child 2 through the real host"
    if claude_run 1; then
      local parent=$(clean $CONDA -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["parent"])' $ROOT/run-1-summary.json)
      local child=$(clean $CONDA -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["child"])' $ROOT/run-1-summary.json)
      remember $parent $child
      say "delete child 2's Issue #$child with gh (your login), as a user would"
      ugh issue delete $child --repo $R --yes > $ROOT/delete-$child.txt 2>&1 || print -r -- "gh issue delete: $(head -c 200 $ROOT/delete-$child.txt)"
      answers_410 $child && pass "#$child now answers HTTP 410 (deleted)" || fail "#$child does not answer 410: $(head -c 200 $ROOT/get-$child.err)"
      say "run 2: back up child 2 twice through the real host"
      if (( OK )) && claude_run 2 $child; then
        local fresh=$(clean $CONDA -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["recreated"])' $ROOT/run-2-summary.json)
        remember $fresh
        listing $ROOT/listing.json || fail "listing failed: $(head -c 200 $ROOT/listing.json.err)"
        local marked=$(clean $CONDA -I $X641 marked $ROOT/listing.json $MAP 2)
        [[ $marked == 1 ]] && pass "GraphTraj's marker search finds exactly one Issue for Task 2's current marker (#$fresh)" \
                           || fail "Issues carrying Task 2's current marker: $marked (expected 1)"
        local kids=$(ugh api --method GET repos/$R/issues/$parent/sub_issues 2> $ROOT/subs.err > $ROOT/subs.json && clean $CONDA -I $X641 subs $ROOT/subs.json)
        [[ $kids == $fresh ]] && pass "GitHub lists #$fresh as the only Sub-issue of parent #$parent" \
                              || fail "Sub-issues of #$parent: '${kids}' (expected $fresh) $(head -c 200 $ROOT/subs.err)"
        cp $MAP $ROOT/listing.json $ROOT/subs.json $OUT/ 2>/dev/null
      else OK=0; fi
    else OK=0; fi
  } always {
    cleanup
    cp $ROOT/issues-created-and-deleted.txt $OUT/ 2>/dev/null
  }
  local hostlog=$(tail -3 $P/.graphtraj/claude-host/host.log 2>/dev/null | tr '\n' ' ' | cut -c1-300)
  print -r -- "host log (last lines): ${${hostlog% }:-none}"
  print -r -- "writes: $ROOT (project mapping, streams) and copies in $OUT; GitHub: Issues created in $R and deleted again. dialog: none."
  print -r -- "re-judge (paste): $CONDA -I $X641 judge 2 $ROOT/run-2.jsonl $R $ROOT/run-2-summary.json ${child:-<old>}"
  (( OK )) && print -r -- "RESULT 641 real: PASS (created and deleted: ${CREATED:-none})" || print -r -- "RESULT 641 real: FAIL (lines above; created and deleted: ${CREATED:-none})"
  (( OK )) && print -r -- "next (paste): zsh $THIS post" || print -r -- "next: report the FAIL lines; to rerun: rm ${(qq)MAP} && zsh $THIS real"
  (( OK ))
  ;;
post)
  say "[post] Main. Your ~/.graphtraj, ~/.codex, ~/.pi/agent, ~/.dsh vs pre (names, sizes, mtimes). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "your locations are unchanged" || fail "a location changed (diff above)"
  print -r -- "outputs: $ROOT (copies in $OUT). To remove everything afterwards: rm -rf ${(qq)ROOT}"
  (( OK )) && print -r -- "RESULT 641 post: PASS" || print -r -- "RESULT 641 post: FAIL"
  print -r -- "next (paste): zsh $THIS G"
  (( OK ))
  ;;
G)
  say "[G] Main. Full GraphTraj suite: HEAD $HEAD (editable) + graftling $GVERSION ($GCOMMIT wheel), 6 shards. This process waits for any other test run, then for its shards, then judges; its LAST lines are the verdict, counts and next command. pytest temp under TMPDIR=$PYTEST_TMP (outside the Harness). Dialog: none. No login. ~25-30 min."
  outside || return 1
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  local busy; busy=$(other_suites) || { print -r -- "STOP: $busy (nothing started)"; return 1; }
  local GV=$T/gvenv-641 O=$T/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${PYTEST_TMP:A}/verify-641-G-$(date +%Y%m%dT%H%M%S)
  mkdir -p $T $O $RUNTMP || return 1
  g_venv $GV $WT || { print -r -- "STOP: suite venv"; return 1; }
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
    print -r -- "launch environment: PATH HOME USER TERM TMPDIR LANG only (clean(); no provider credential)"
    print -r -- "candidate: $HEAD | graftling wheel from git archive $GCOMMIT (v$GVERSION)"
    (cd $RUNTMP && clean $GV/bin/python -I -c 'import importlib.metadata as m; print("test interpreter:", " | ".join(f"{n} {m.version(n)}" for n in ("click", "PyYAML", "websockets", "pytest", "graftling", "graphtraj")))')
    [[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not evidence): $REHEARSAL"; } > $O/run.txt
  local -a extra=(${(Q)${(z)${VERIFY641_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${extra[*]}" >> $O/run.txt
  cat $O/run.txt; print -r -- "record: $O"
  while true; do
    busy=$(other_suites) || { print -r -- "STOP: ps failed; G did not start"; return 1; }
    [[ -z $busy ]] && break
    print -r -- "$(date +%T) waiting for another test run: $(print -r -- $busy | awk '{print $1}' | xargs)" | tee -a $O/wait.txt; sleep ${VERIFY641_GWAIT:-60}
  done
  print -r -- "$(date +%T) started (6 shards; this step waits for them)" | tee -a $O/wait.txt
  (cd $WT && clean TMPDIR=$RUNTMP $GV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra \
     > $O/suite.txt 2>&1 < /dev/null)
  print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended: $(tail -1 $O/suite.txt)" | tee -a $O/wait.txt
  STEP=GR; run_step; return $?
  ;;
GR)
  say "[GR] read only: the newest G record judged (G runs this at its end; Main may rerun it)."
  local rec=$(grec); print -r -- "G record: $rec"
  [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "RESULT 641 G: NOT ENDED (no exit= line in $rec/suite.txt)"; return 1; }
  sed 's/^/  run.txt: /' $rec/run.txt
  local tot=$(grep -hE '^=*.* (passed|failed)' $rec/shards/*(N.) | sed "s#^#  #") ex=$(sed -n 's/^exit=//p' $rec/suite.txt | tail -1)
  print -r -- "shard totals:"; print -r -- $tot
  sr_classify $rec
  local rf=0; grep -q '^REHEARSAL' $rec/run.txt && rf=1
  local verdict=FAIL; (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && ( $SR_ANY == 1 || $rf == 1 ) ) ]] && verdict=PASS
  cp -R $rec $OUT/ 2>/dev/null
  local kn=$(sr_classify $rec | grep -c '^  known') nw=$#SR_IDS
  print -r -- ""
  print -r -- "RESULT 641 G: $verdict | exit $ex | known non-blocking ids: $kn | NEW ids: $nw$( (( rf )) && print ' | REHEARSAL (not evidence)')"
  if [[ $verdict == PASS ]]; then print -r -- "next: report RESULT 641 G (record $rec)"
  else print -r -- "next (paste): zsh $THIS SR"; return 1; fi
  ;;
SR)
  say "[SR] Main, read only: the newest G record's FAILED/ERROR ids and ABNORMAL shards against 516's current definition. Dialog: none."
  local rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no ended G record ($rec)"; return 1; }
  tail -4 $rec/suite.txt; sr_classify $rec
  print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else print -r -- "next: none for suite-base (no NEW id)"; fi
  return $SR_NEW
  ;;
suite-base)
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file"; return 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; return 2; }
  say "[suite-base] Main, only for SR's NEW ids ($#ids): base GraphTraj $GTBASE vs candidate HEAD $HEAD, both with graftling $GVERSION (wheel). pytest temp under TMPDIR (outside the Harness). Dialog: none."
  outside || return 1
  local o; o=$(other_suites) || { print -r -- "STOP: $o"; return 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; return 1; }
  local B=$T/graphtraj-base VB=$T/sbvenv-${GTBASE[1,8]} VC=$T/gvenv-641
  if [[ ! -d $B/.git ]]; then rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
     && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1; fi
  g_venv $VB $B && g_venv $VC $WT || return 1
  local RS=$T/suite-base-$(date +%Y%m%dT%H%M%S) side dir V src RUNTMP f; local -a files run; mkdir -p $RS; print -l -- $ids > $RS/ids.txt
  for side dir V in base $B $VB candidate $WT $VC; do
    RUNTMP=${PYTEST_TMP:A}/verify-641-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $dir | temp $RUNTMP"
    files=(); for f in ${(u)${ids%%::*}}; do [[ -e $dir/$f ]] && files+=$f; done   # a file absent on a side is not collected there
    if (( $#files )); then (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only $files > $RS/$side-collected.txt 2>&1)
    else : > $RS/$side-collected.txt; fi
    clean $CONDA -I $SUITEIDS present $RS/$side-collected.txt $RS/ids.txt > $RS/$side-ids.txt 2> $RS/$side-missing.txt
    run=(${(f)"$(<$RS/$side-ids.txt)"}); run=(${run:#})
    if (( $#run )); then (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $RS/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $RS/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $RS/$side.txt | tail -1) ($RS/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $RS/ids.txt $RS/base.txt $RS/candidate.txt | tee $RS/classification.txt; local fails=${pipestatus[1]}
  cp -R $RS $OUT/ 2>/dev/null
  print -r -- ""; print -r -- "RESULT 641 suite-base: $( (( fails == 0 )) && print 'PASS (no candidate-only failure)' || print 'FAIL (classification above)') | ids: $#ids | record: $RS"
  print -r -- "next: report the classification; a candidate-only id is a regression of this Task"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|install|setup|trust|real|post|G|GR|SR|suite-base --from <file>|<ids>..."; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n $REHEARSAL ]] || { print "STOP: $H is not the Harness root"; exit 1; }
scrub() {  # unset every exported credential-class name; print the names removed
  local k u part; local -a gone=()
  for k in ${(k)parameters[(R)*export*]}; do
    u=${(U)k}; [[ $u == GIT_CONFIG_KEY_<-> ]] && continue
    for part in ${(s:_:)u}; do
      [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && { gone+=$k; unset $k; break; }
    done
  done
  print -r -- "credential scrub: removed from this script's environment (names only): ${gone:-none}"
}
scrub
[[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not acceptance evidence): $REHEARSAL"
OK=1
R=
STARTED=
IDS=("${(@)@[2,-1]}")
mkdir -p $OUT 2>/dev/null
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
