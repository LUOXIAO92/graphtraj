#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 585 Main-run steps: a Pi subagent child (PI_SUBAGENT_CHILD=1, PI_SUBAGENT_DEPTH>0, or no Session file) no longer
# starts a graftling host; a plain Pi Main still does and can create and wait for a child. graftling only, no GraphTraj.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre           Main. ROOT must not exist (STOP with the exact rm command otherwise) and is created. Versions (zsh,
#                 node, pi); the bundle verifies; DEEPSEEK_API_KEY set (never printed); the allowlisted environment's
#                 variable NAMES; 'before' state of ~/.pi/agent (names + sha256 prefixes), ~/.dsh (listing) and of
#                 /private/tmp/pi-584's two plugin agent dirs (listing; only read); the deepseek flash id from
#                 `pi --list-models deepseek`; a one-line Pi prompt naming its model. Dialog: none. ~1 min.
#   install       Main. In this order: ROOT/venv-cand (candidate, from the bundle) as a WHEEL, graftling only
#                 (graphtraj must not import; no network: PyYAML, websockets copied from <Harness>/.venv-runtime);
#                 graftling's DSH model discovery (candidate venv, DSH_HOME=ROOT/dsh-home) picks the dsh child's
#                 model for main-cand; then, BEFORE any graftling step, a ONE-LINE DSH PROMPT with that model
#                 (`dsh --profile headless --patch ROOT/dsh-preflight.patch.yml`, DSH_HOME=ROOT/dsh-home, allowlisted
#                 env: DEEPSEEK_API_KEY the only credential, DEEPSEEK_BASE_URL absent) printing the configured model,
#                 DSH's answer and its login source (the env key, never printed); STOP with the fix and the rerun
#                 command if DSH cannot answer. Then ROOT/venv-base (graftling a4f008f, wheel) and per variant an
#                 isolated PI_CODING_AGENT_DIR=ROOT/agent-<variant>: `pi install <that venv's graftling/pi>` (a local
#                 directory) and Pi's bundled subagent example copied from the installed Pi package with its agents'
#                 model: lines removed. No `dsh plugin add` (no pnpm): a dsh child's profile is written by graftling
#                 itself; nothing is written outside ROOT (post checks ~/.dsh). Dialog: none.
#                 Network: api.deepseek.com only (discovery's model list and the DSH prompt). ~1-2 min.
#   bundled-base  Main. Pi Main (base graftling) uses the bundled subagent (agent worker) in a fresh git project;
#                 GRAFTLING_PYTHON is a shim that logs every graftling launch (pid, ppid, markers). PASS = the defect
#                 reproduces: a child-owned graftling.pi.host launch and 'Extension error' in the subagent tool result.
#                 Dialog: none. ~1-2 min. Model calls: DeepSeek only.
#   bundled-cand  Main. The same with the candidate. PASS: exactly one graftling.pi.host launch, owned by the Main; no
#                 'Extension error' in the output or the subagent tool result; the subagent ran; Main answers ready.
#   main-cand     Main. Plain Pi Main with the candidate (no flag, no GRAFTLING_DATA_ROOT, no GRAFTLING_PYTHON):
#                 the host starts, <project>/.agents-control is created, the Main creates ONE dsh child through the
#                 agents tool (DeepSeek, DEEPSEEK_API_KEY only, isolated DSH_HOME=ROOT/dsh-home) and waits for its
#                 completed answer (as 577's pi-default). Then a `pi --no-session` Main in another fresh project:
#                 no host launch, no .agents-control, no error (the documented side effect). Dialog: none. ~2-4 min.
#   third-party   Main, ONLY with VERIFY585_THIRD_PARTY=1 (Main sets it after asking the user). mjakl/pi-subagent and
#                 nicobailon/pi-subagents with the candidate: their already-installed code is COPIED from
#                 /private/tmp/pi-584/agent-{mjakl,nicobailon} into ROOT (pi-584 only read; no network expected),
#                 graftling replaced by the candidate. PASS: only the Main's graftling.pi.host launch; the subagent
#                 ran. Third-party plugin code runs in these Sessions. Dialog: none. ~2-4 min.
#   post          Main. ~/.pi/agent, ~/.dsh and the two pi-584 agent dirs vs pre (any difference FAILs). <5 s.
#   push          Main, ONLY after asking the user. Pushes the candidate branch to LUOXIAO92/graftling from the bundle.
#                 Dialog: none expected; git uses your usual GitHub login (github.com). ~30 s.
#   suite         Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a fresh venv
#                 under <Harness>/tmp/585 with graftling built as a WHEEL from the candidate bundle and GraphTraj
#                 editable. pytest's temp root is under TMPDIR=${TMPDIR:-/tmp}, outside the Harness (checked).
#                 Dialog: none. No login. VERIFY585_PYTEST_ARGS='<args>' appends pytest args (rehearsal only).
#   SR            Read only: the newest suite's FAILED/ERROR lines classed known (Task 516's CURRENT definition, via its
#                 task.yml current_definition, plus test_extension_in_a_worktree_never_spawns_the_collector) or NEW;
#                 prints the ready-to-paste suite-base command for NEW node ids. Dialog: none.
#   suite-base    Main, only if SR reports NEW: reruns exactly those node ids on GraphTraj GTBASE with graftling a4f008f
#                 (wheel); per node id 'also fails on base' or 'candidate-only'. Dialog: none. No login.
# Order: pre, install, bundled-base, bundled-cand, main-cand, [third-party], post (push: separately, after asking).
# suite, SR (and suite-base) need no ROOT and no key; they write only <Harness>/tmp/585 and pytest's temp root.
# Preflight: every host answers a one-line prompt with its configured model and login before the graftling steps:
# Pi in pre, DSH (the host of main-cand's dsh child) in install, right after the model discovery.
# Credentials: every pi and dsh process (Main, its subagent children, graftling's children) starts from an ALLOWLISTED
# environment: PATH, HOME=ROOT/home, TMPDIR, LANG, PI_CODING_AGENT_DIR, DEEPSEEK_API_KEY and the step's own variables
# (shown by name). DEEPSEEK_API_KEY is the only credential; it is never printed and never on a command line. Every
# Pi step prints the provider/model it asks for and counts "provider" values in its Session files (expect deepseek).
# Writes outside ROOT: none expected (HOME, PI_CODING_AGENT_DIR, DSH_HOME and --session-dir are under ROOT).
# VERIFY585_ROOT / _OUT / _BIN (stub pi and dsh first on PATH) / _USERHOME / _PIPKG / _P584 / _DMODEL / _PIMODEL / _T are for
# the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset extended_glob
zmodload zsh/system                                 # $sysparams[pid]: the Main pi's pid
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
ROOT=${VERIFY585_ROOT:-/private/tmp/pi-585}
OUT=${VERIFY585_OUT:-$H/.graphtraj/core/state/tasks/585-graftling-pi-subagent-child-no-default-host/realhost}
URL=https://github.com/LUOXIAO92/graftling.git
BASE=a4f008f3712614cbdcae714ae46cad07c1f8de6e       # graftling dev before 585 (572 + 577 + 578)
GREPO=$H/graftling                                  # the local graftling repository (read only): holds BASE
BRANCH=agent/585-graftling-pi-subagent-child-no-default-host
GCOMMIT=0b37aeab58ed9282fbf9bc68ed6f1799c03e9996                        # the graftling candidate (base: dev a4f008f)
BUNDLE=$WT/.scratch/585/graftling-585.bundle
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
JUDGE=$WT/scripts/verify-570/judge.py               # records on disk + the answer's lines (Task 570, unchanged)
PIPKG=${VERIFY585_PIPKG:-/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent}   # read only
P584=${VERIFY585_P584:-/private/tmp/pi-584}         # third-party plugin code installed by 584 (read only)
UH=${VERIFY585_USERHOME:-$HOME}                     # your home: its .pi/agent and .dsh are only read
DH=$ROOT/dsh-home                                   # isolated DSH home of the dsh child and model discovery
MODELF=$ROOT/pi-model.txt                           # the Pi Main's deepseek model id (pre)
DMODELF=$ROOT/dsh-model.txt                         # the dsh child's model (install)
THIS=${0:A}
STEP=${1:-}
# suite / SR / suite-base (as verify-577).
T=${VERIFY585_T:-$H/tmp/585}
GTREPO=$H/graphtraj                                 # the GraphTraj repository (read only): holds GTBASE
GTBASE=24674e308d9747f05bdaacded00ffabf83183857     # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN_EXTRA=test_extension_in_a_worktree_never_spawns_the_collector
PIDFILE=''                                          # pimain: where allow writes the Main pi's pid
PIPATH=${VERIFY585_BIN:+$VERIFY585_BIN:}/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
path=(${VERIFY585_BIN:+$VERIFY585_BIN} /opt/homebrew/bin ${path:#$ROOT/*})

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
need() { [[ -e $1 ]] || { print -r -- "STOP: $1 missing; run: zsh $THIS $2"; return 1; } }
key_ready() {
  [[ -n ${DEEPSEEK_API_KEY:-} ]] && return 0
  print -r -- "STOP: DEEPSEEK_API_KEY is not set. Fix: export DEEPSEEK_API_KEY=<your DeepSeek API key>; zsh $THIS $STEP"
  return 1
}
# Run "$@" with ONLY the allowlisted variables. Usage: allow <agent dir> [NAME=value...] -- command...
# The key stays in this shell's environment (exported, never an argument), every other exported name is removed.
allow() {
  local a=$1; shift; local -a add=()
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  ( local k
    for k in ${(k)parameters[(R)*export*]}; do [[ $k == DEEPSEEK_API_KEY ]] || unset $k 2>/dev/null; done
    export PATH=$PIPATH HOME=$ROOT/home TMPDIR=${PYTEST_TMP} LANG=en_US.UTF-8 PI_CODING_AGENT_DIR=$a
    (( $#add )) && export "${add[@]}"
    [[ -n $PIDFILE ]] && print -r -- $sysparams[pid] > $PIDFILE   # the pid pi keeps (perl and env exec in place)
    # Exactly these names remain (some inherited names cannot be unset in zsh); the key is never an argument.
    exec /usr/bin/perl -e 'my %k = map { $_ => 1 } split /,/, shift; delete $ENV{$_} for grep { !$k{$_} } keys %ENV;
      exec @ARGV or die "exec $ARGV[0]: $!\n"' \
      PATH,HOME,TMPDIR,LANG,PI_CODING_AGENT_DIR,DEEPSEEK_API_KEY${add:+,${(j:,:)${add%%=*}}} "$@" )
}
# The user's locations: names (+ sha256 prefixes for ~/.pi/agent files, mtimes for ~/.dsh), never contents; the two
# pi-584 plugin agent dirs this file copies from.
user_state() {
  local f; for f in $UH/.pi/agent/*(N.D); do print -r -- "pi ${f:t} $(shasum -a 256 < $f | cut -c1-16)"; done
  print -r -- "pi directories: $(print -l -- $UH/.pi/agent/*(N/D:t) | tr '\n' ' ')"
  ls -laT $UH/.dsh $UH/.dsh/profiles 2>&1 | awk 'NF >= 10 && $10 != ".." {print "dsh", $6, $7, $8, $9, $10}'
  ls -laTR $P584/agent-mjakl $P584/agent-nicobailon 2>&1 | awk 'NF >= 10 && $10 != ".." && $10 != "." {print "pi-584", $5, $6, $7, $8, $9, $10}' \
    | shasum -a 256 | cut -c1-16 | sed 's/^/pi-584 plugin agent dirs listing hash: /'
}
pimodel() { [[ -s $MODELF ]] && print -r -- "$(<$MODELF)" || { print -r -- "STOP: $MODELF missing; run: rm -rf $ROOT && zsh $THIS pre" >&2; return 1; } }
venv() { print -r -- $ROOT/venv-$1; }
pkg() { print -r -- $(venv $1)/lib/python3.13/site-packages/graftling/pi; }
mkproj() { rm -rf $1 && mkdir -p $1 && git -C $1 init -q; }
# The shim: logs every graftling Python launch (time pid ppid cwd markers args), then runs that venv's python.
write_shim() {  # variant
  local s=$ROOT/shim-$1
  print -r -- "#!/bin/sh
printf '%s pid=%s ppid=%s CHILD=%s DEPTH=%s args=%s\\n' \"\$(date +%H:%M:%S)\" \"\$\$\" \"\$PPID\" \"\${PI_SUBAGENT_CHILD:-}\" \"\${PI_SUBAGENT_DEPTH:-}\" \"\$*\" >> \"\${SHIM_LOG:-/dev/null}\"
exec $(venv $1)/bin/python \"\$@\"" > $s && chmod +x $s && print -r -- $s
}
# The provider values in a Session directory (never a secret), and the subagent tool results' exit and stderr.
providers() {
  local n=$(cat $1/**/*.jsonl(N.) /dev/null | grep -o '"provider":"[^"]*"' | sort | uniq -c | xargs)
  print -r -- "provider values in $1: ${n:-none}"
  [[ -z $n ]] && return 0
  [[ $(cat $1/**/*.jsonl(N.) | grep -o '"provider":"[^"]*"' | sort -u) == '"provider":"deepseek"' ]] \
    && pass "deepseek is the only provider in the Session files" || fail "a provider other than deepseek in $1"
}
subagent_results() {  # session dir -> prints one line per subagent tool result; sets NRES and NERR
  local r; r=$(python3 -I - $1 <<'EOF'
import json, sys
from pathlib import Path
n = e = 0
for f in sorted(Path(sys.argv[1]).rglob('*.jsonl')):
    for line in f.read_text().splitlines():
        try: m = json.loads(line).get('message')
        except ValueError: continue
        if isinstance(m, dict) and m.get('role') == 'toolResult' and 'subagent' in str(m.get('toolName', '')):
            for r in (m.get('details') or {}).get('results') or [{}]:
                n += 1; err = r.get('stderr') or ''
                e += 'Extension error' in err
                print(f"  {f.name[:40]} tool {m.get('toolName')} exit {r.get('exitCode')} stderr {err[:300]!r}")
print(f'COUNTS {n} {e}')
EOF
)
  print -r -- "${r%COUNTS*}"; local c=(${=${r##*COUNTS }}); NRES=$c[1]; NERR=$c[2]
}
# The graftling.pi.host launches in a shim log, split by owner: the Main (pid in $2) or another process.
host_launches() {  # log mainpid -> sets NHOST NMAIN
  print -r -- "-- graftling launches ($1):"; cat $1 2>/dev/null || print -r -- "  none"
  NHOST=$(cat $1 2>/dev/null | grep -c 'graftling.pi.host'); NMAIN=$(cat $1 2>/dev/null | grep 'graftling.pi.host' | grep -c " ppid=$2 ")
  print -r -- "graftling.pi.host launches: $NHOST, owned by the Main (pid $2): $NMAIN, by another process: $(( NHOST - NMAIN ))"
}
# One real Pi Main. Usage: pimain <name> <project> <agent dir> [NAME=value...] -- pi options... ; sets SOUT SRC MAINPID SD
pimain() {
  local name=$1 dir=$2 a=$3; shift 3; local -a add=()
  while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done; shift
  SOUT=$ROOT/$name.txt; SD=$ROOT/sessions-$name; rm -rf $SD; mkdir -p $SD
  local model; model=$(pimodel) || return 1
  say "$name: pi -p --provider deepseek --model $model in $dir; PI_CODING_AGENT_DIR=$a; allowlisted env + ${add:-nothing}"
  PIDFILE=$ROOT/$name.pid
  ( cd $dir && allow $a $add -- perl -e 'alarm shift; exec @ARGV' 600 pi -p --provider deepseek --model $model --approve "$@" ) \
    < /dev/null > $SOUT 2>&1; SRC=$?
  PIDFILE=''; MAINPID=$(<$ROOT/$name.pid)
  tail -12 $SOUT; print -r -- "exit=$SRC (Main pi pid $MAINPID; full output: $SOUT)"
  mkdir -p $OUT 2>/dev/null && cp $SOUT $OUT/ 2>/dev/null; return 0
}
ASK_BUNDLED="Use your subagent tool with agent worker to answer: 'Answer with exactly one word: ready.' Then tell me its answer."
ASK_PLUGIN="Use your subagent tool to delegate this to ONE subagent and then tell me its answer: 'Answer with exactly one word: ready.'"
# The subagent comparison of one variant (base or cand) or plugin agent dir.
subagent_run() {  # name agent-dir shim-variant prompt expect(defect|fixed)
  local name=$1 a=$2 v=$3 ask=$4 expect=$5 P=$ROOT/proj-$1 LOG=$ROOT/shim-$1.log
  mkproj $P; rm -f $LOG
  local shim; shim=$(write_shim $v) || return 1
  pimain $name $P $a GRAFTLING_PYTHON=$shim SHIM_LOG=$LOG -- --session-dir $ROOT/sessions-$name "$ask" || return 1
  say "evidence"
  host_launches $LOG $MAINPID
  print -r -- "-- subagent tool results in the Main's Session file:"; subagent_results $SD
  providers $SD
  print -r -- "-- 'Extension error' lines in the Main's output: $(grep -c 'Extension error' $SOUT)"
  print -r -- "-- $P/.agents-control: $(print -l -- $P/.agents-control/*(N:t) $P/.agents-control/live/*(N:t) | tr '\n' ' ')"
  say "verdict (computed)"
  (( SRC == 0 )) && pass "the Main exited 0" || fail "the Main exited $SRC"
  (( NRES > 0 )) && pass "the subagent tool ran ($NRES result(s))" || fail "no subagent tool result: the child did not run"
  if [[ $expect == defect ]]; then
    (( NHOST - NMAIN > 0 )) && pass "REPRO: a child-owned graftling.pi.host launch" || fail "no child-owned host launch (defect not reproduced)"
    (( NERR > 0 )) && pass "REPRO: Extension error in the subagent tool result" || fail "no Extension error in the subagent tool result"
  else
    (( NHOST == 1 && NMAIN == 1 )) && pass "exactly one graftling.pi.host launch, the Main's" || fail "$NHOST host launches, $NMAIN the Main's"
    (( NERR == 0 )) && pass "no Extension error in the subagent tool results" || fail "Extension error in a subagent tool result"
    grep -q 'Extension error' $SOUT && fail "Extension error in the Main's output" || pass "no Extension error in the Main's output"
    grep -qi 'ready' $SOUT && pass "the Main answered (ready)" || fail "the Main's answer lacks 'ready'"
  fi
  print -r -- "Session files: $SD; shim log: $LOG"
}
# Builds a venv with graftling installed as a WHEEL from commit $2 (bundle supplies the candidate); graftling only.
build_venv() {  # dir commit
  local v=$1 c=$2 S=$1-src
  [[ -f $v/installed ]] && { print -r -- "reusing $v ($(<$v/installed))"; return 0; }
  rm -rf $v $S && mkdir -p $S/graftling $S/wheels || return 1
  git clone -q --no-checkout $GREPO $S/repo && git -C $S/repo fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $S/repo archive $c | tar -x -C $S/graftling || { print -r -- "STOP: graftling $c not found"; return 1; }
  $CONDA -m venv $v || return 1
  local D=$($v/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RTSP/websockets $RTSP/websockets-*.dist-info(N) $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ || return 1
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $v/bin/python -m pip install $pip $S/wheels/graftling-*.whl || return 1
  local got; got=$(cd / && $v/bin/python -I -c 'import graftling, yaml, websockets, importlib.util as u; print(graftling.__version__, graftling.__file__, "| graphtraj importable:", u.find_spec("graphtraj") is not None)') \
    || { print -r -- "STOP: $v cannot import graftling with its dependencies"; return 1; }
  [[ $got == *'graphtraj importable: False' ]] || { print -r -- "STOP: graphtraj is importable in $v: $got"; return 1; }
  print -r -- "$c $got" > $v/installed; print -r -- "$v: $(<$v/installed)"
}
# An isolated Pi agent dir for a variant: graftling's Pi package and Pi's bundled subagent example (model: lines removed).
agent_dir() {  # variant
  local a=$ROOT/agent-$1 model; model=$(pimodel) || return 1
  rm -rf $a && mkdir -p $a/extensions/subagent $a/agents || return 1
  say "PI_CODING_AGENT_DIR=$a pi install $(pkg $1)"
  allow $a -- pi install $(pkg $1) < /dev/null 2>&1 | tail -3
  cp $PIPKG/examples/extensions/subagent/{index.ts,agents.ts} $a/extensions/subagent/ && cp $PIPKG/examples/extensions/subagent/agents/*.md $a/agents/ || return 1
  local f; for f in $a/agents/*.md; do grep -v '^model:' $f > $f.new && mv $f.new $f; done
  print -r -- "bundled agents copied: $(print -l -- $a/agents/*.md(:t) | tr '\n' ' '); model: lines left (expect 0): $(cat $a/agents/*.md | grep -c '^model:')"
  defaults $a $model
  allow $a -- pi list < /dev/null 2>&1 | head -6
}
defaults() {  # agent dir, model: Pi's default provider/model there, so a child started without --model uses DeepSeek
  python3 -I -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "settings.json"; s = json.loads(p.read_text()) if p.exists() else {}
s.update(defaultProvider="deepseek", defaultModel=sys.argv[2]); p.write_text(json.dumps(s, indent=2))
print("settings.json: packages", s.get("packages"), "| default", s["defaultProvider"], s["defaultModel"])' $1 $2
}
# One-line DSH prompt (as verify-577 pre), with the dsh child's model, before any graftling step: DSH_HOME=$DH,
# allowlisted env (DEEPSEEK_API_KEY the only credential; DEEPSEEK_BASE_URL absent). The model is pinned by a patch
# overlay in ROOT (llm-deepseek's config is replaced wholesale: models = that one), as graftling does for a manual model.
dsh_preflight() {  # model
  local m=$1 patch=$ROOT/dsh-preflight.patch.yml log=$ROOT/dsh-preflight.txt rc
  print -r -- "- id: llm-deepseek
  config:
    models:
      - id: $m" > $patch
  say "one-line DSH prompt: dsh --profile headless --patch $patch (DSH_HOME=$DH; allowlisted env)"
  local dumped; dumped=$(cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- dsh --profile headless --patch $patch --dump-config < /dev/null 2>&1)
  print -r -- "configured models of llm-deepseek (from --dump-config): $(print -r -- $dumped | awk '/^- id: llm-deepseek$/ {f=1; next} f && /^- id:/ {exit} f && /- id:/ {print $3}' | xargs)"
  print -r -- "login: DEEPSEEK_API_KEY from the allowlisted environment (set, ${#DEEPSEEK_API_KEY} characters, not printed); DEEPSEEK_BASE_URL absent; $DH/.credentials.yaml $([[ -e $DH/.credentials.yaml ]] && print PRESENT || print absent), $DH/.env $([[ -e $DH/.env ]] && print PRESENT || print absent)"
  (cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 180 dsh --profile headless --patch $patch \
     "Reply in one line with the exact model id you are running as, nothing else." < /dev/null) > $log 2>&1; rc=$?
  tail -5 $log; print -r -- "exit=$rc (full output: $log)"
  if (( rc != 0 )); then
    print -r -- "STOP: DSH could not answer with model $m (output above). Check DEEPSEEK_API_KEY (export DEEPSEEK_API_KEY=<your DeepSeek API key>),"
    print -r -- "  the network to api.deepseek.com and that '$m' is listed by the discovery above; then rerun exactly: zsh $THIS install"
    return 1
  fi
  pass "DSH answered as configured model $m (login: DEEPSEEK_API_KEY)"
}
# A fresh pytest temp root under TMPDIR, outside the Harness, with no Harness marker above it; sets RUNTMP.
run_root() {  # label
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  RUNTMP=${PYTEST_TMP:A}/verify-585-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp: TMPDIR=$PYTEST_TMP -> run root $RUNTMP (outside the Harness)"
}
# A venv with graftling as a WHEEL built from commit $2 and GraphTraj editable from checkout $3 (no network).
suite_venv() {  # venv graftling-commit graphtraj-checkout
  local V=$1 c=$2 gt=$3 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf $V $S && mkdir -p $S/graftling $S/wheels || return 1
  git clone -q --no-checkout $GREPO $S/repo && git -C $S/repo fetch -q $BUNDLE "${BRANCH}:refs/remotes/bundle/candidate" || return 1
  git -C $S/repo archive $c | tar -x -C $S/graftling || { print -r -- "STOP: graftling $c not found"; return 1; }
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $V/bin/python -m pip install $pip $S/wheels/graftling-*.whl && $V/bin/python -m pip install $pip -e $gt || return 1
  print -r -- "graftling $c (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
create_prompt() {  # dsh model
  print -r -- 'Use the tool mcp__graftling__agents, not your own subagents. Its input is {"action":"execute","feature":<name>,"arguments":{...}}. Make exactly these calls in order:
1) {"action":"execute","feature":"create","arguments":{"runtime":"dsh","model":"'$1'","instruction":"Answer with exactly one word: ready."}}
2) {"action":"execute","feature":"wait","arguments":{"agent":"<the agent id that create returned>","timeout_seconds":240}}
3) {"action":"execute","feature":"status","arguments":{"agent":"<that agent id>"}}
4) {"action":"execute","feature":"status","arguments":{}}
Then report exactly four lines: AGENT: the agent id; ANSWER: the child'"'"'s answer; STATUS: the state and last_result.notification from call 3; LISTED: every agent id that call 4 lists. If any call returns an error, also print it verbatim on a line prefixed ERROR:.'
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight; creates $ROOT. Dialog: none. ~1 min."
  [[ -e $ROOT ]] && { print -r -- "STOP: $ROOT exists; its 'before' state must be fresh. Run exactly:"
                      print -r -- "  rm -rf $ROOT && zsh $THIS pre"; return 1; }
  key_ready || return 1
  mkdir -p $ROOT/home $ROOT/agent-probe $DH $OUT || return 1
  print -r -- "zsh $ZSH_VERSION ($THIS)"
  local t; for t in node pi git; do print -r -- "$t: $(command -v $t) $($t --version 2>&1 | head -1)"; done
  print -r -- "Pi package (bundled subagent example source): $PIPKG; example files: $(print -l -- $PIPKG/examples/extensions/subagent/*(N:t) | tr '\n' ' ')"
  [[ -f $PIPKG/examples/extensions/subagent/index.ts ]] || { print -r -- "STOP: no bundled subagent example under $PIPKG"; return 1; }
  [[ -d $RTSP/websockets && -d $RTSP/yaml ]] || { print -r -- "STOP: $RTSP lacks websockets or yaml"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 && pass "bundle $BUNDLE verifies" || { print -r -- "STOP: bundle does not verify"; return 1; }
  [[ $(git bundle list-heads $BUNDLE | cut -d' ' -f1) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head is not $GCOMMIT"; return 1; }
  print -r -- "DEEPSEEK_API_KEY: set (${#DEEPSEEK_API_KEY} characters; not printed)."
  print -r -- "allowlisted environment of every pi process (names only): $(allow $ROOT/agent-probe EXAMPLE_STEP_VAR=1 -- /usr/bin/env | cut -d= -f1 | sort | xargs)"
  user_state > $ROOT/user-before.txt; cp $ROOT/user-before.txt $OUT/
  print -r -- "your locations before (read only; names, hashes, mtimes):"; cat $ROOT/user-before.txt
  say "the Pi Main's model: pi --list-models deepseek (PI_CODING_AGENT_DIR=$ROOT/agent-probe)"
  local listed; listed=$(cd $ROOT && allow $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi --list-models deepseek < /dev/null 2>&1)
  print -r -- "$listed" | tail -8
  if [[ -n ${VERIFY585_PIMODEL:-} ]]; then print -r -- $VERIFY585_PIMODEL > $MODELF
  else print -r -- "$listed" | awk '$1 == "deepseek" && $2 ~ /flash/ {print $2; exit}' > $MODELF; fi
  [[ -s $MODELF ]] || { print -r -- "STOP: no deepseek flash model listed (above). Report it, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  say "one-line Pi prompt: pi -p --provider deepseek --model $(<$MODELF) --no-session --no-extensions --no-tools"
  (cd $ROOT && allow $ROOT/agent-probe -- perl -e 'alarm shift; exec @ARGV' 120 pi -p --provider deepseek --model $(<$MODELF) \
     --no-session --no-extensions --no-tools "Reply in one line: the exact model id and the provider you are running as, nothing else." \
     < /dev/null) 2>&1 | tail -5
  local rc=$?; print -r -- "exit=$rc"
  (( rc == 0 )) || { print -r -- "STOP: Pi could not answer; check DEEPSEEK_API_KEY and the network, then: rm -rf $ROOT && zsh $THIS pre"; return 1; }
  pass "Pi Main model: deepseek/$(<$MODELF)"
  print -r -- "next: zsh $THIS install"
  ;;
install)
  say "[install] Main. venv-cand ($GCOMMIT), DSH model discovery, one-line DSH prompt, venv-base ($BASE), agent-base and agent-cand. Dialog: none."
  need $MODELF pre && key_ready || return 1
  build_venv $(venv cand) $GCOMMIT || return 1
  if [[ -n ${VERIFY585_DMODEL:-} ]]; then print -r -- $VERIFY585_DMODEL > $DMODELF; else
    say "graftling's DSH model discovery for main-cand's dsh child ($(venv cand)/bin/python; DSH_HOME=$DH)"
    (cd $ROOT && allow $ROOT/agent-probe DSH_HOME=$DH -- perl -e 'alarm shift; exec @ARGV' 180 $(venv cand)/bin/python -I -c '
import sys
from graftling.models import discover_models
found = discover_models({"runtime": "dsh"})
models = found.get("models") or []
print("status", found.get("status"), "|", found.get("message") or "")
for m in models: print("  model", m["id"], "| alias", m.get("alias"))
flash = [m["id"] for m in models if "flash" in (m["id"] + " " + str(m.get("alias"))).lower()]
if flash: open(sys.argv[1], "w").write(flash[0]); print("chosen", flash[0])
' $DMODELF) 2>&1 | tail -12
  fi
  [[ -s $DMODELF ]] || { print -r -- "STOP: no flash DSH model; see above. Then: zsh $THIS install"; return 1; }
  dsh_preflight $(<$DMODELF) || return 1
  build_venv $(venv base) $BASE || return 1
  grep -c 'PI_SUBAGENT_CHILD' $(pkg base)/extension.mjs | sed 's/^/base extension lines naming PI_SUBAGENT_CHILD (expect 1, sessionEnvironment only): /'
  grep -c 'PI_SUBAGENT_CHILD' $(pkg cand)/extension.mjs | sed 's/^/candidate extension lines naming PI_SUBAGENT_CHILD (expect 2): /'
  agent_dir base || return 1
  agent_dir cand || return 1
  pass "installed; dsh child model for main-cand: $(<$DMODELF) (DSH answered with it above)"
  print -r -- "next: zsh $THIS bundled-base"
  ;;
bundled-base|bundled-cand)
  key_ready && need $ROOT/agent-${STEP#bundled-}/settings.json install || return 1
  local v=${STEP#bundled-}
  say "[$STEP] Main. Pi's bundled subagent example with graftling $v; expect $([[ $v == base ]] && print 'the defect' || print 'no child host'). Dialog: none."
  OK=1; subagent_run $STEP $ROOT/agent-$v $v $ASK_BUNDLED $([[ $v == base ]] && print defect || print fixed) || return 1
  (( OK )) || { print -r -- "next: inspect $SOUT and $SD, then rerun: zsh $THIS $STEP"; return 1; }
  print -r -- "next: zsh $THIS $([[ $v == base ]] && print bundled-cand || print main-cand)"
  ;;
main-cand)
  key_ready && need $ROOT/agent-cand/settings.json install && need $DMODELF install || return 1
  say "[main-cand] Main. Plain Pi Main with the candidate (no flag, no GRAFTLING_DATA_ROOT, no GRAFTLING_PYTHON); one dsh child (model $(<$DMODELF), DEEPSEEK_API_KEY) in $ROOT/proj-main/.agents-control. Dialog: none."
  local P=$ROOT/proj-main root=$ROOT/proj-main/.agents-control snap=$ROOT/main-cand-before.ids
  mkproj $P; : > $snap; OK=1
  pimain main-cand $P $ROOT/agent-cand DSH_HOME=$DH -- --session-dir $ROOT/sessions-main-cand "$(create_prompt $(<$DMODELF))" || return 1
  say "evidence"
  print -r -- "$root: $(print -l -- $root/*(N:t) | tr '\n' ' '); live: $(print -l -- $root/live/*(N:t) | tr '\n' ' ')"
  providers $SD
  say "verdict (computed)"
  (( SRC == 0 )) && pass "the Pi Main exited 0" || fail "the Pi Main exited $SRC"
  [[ -d $root/live/pi-host ]] && pass "the host served $root/live/pi-host" || fail "no $root/live/pi-host"
  grep -q 'Extension error' $SOUT && fail "Extension error: $(grep -m1 'Extension error' $SOUT)"
  python3 -I $JUDGE create $SOUT $root $snap pi-native ready || OK=0
  local agent=$(python3 -I $JUDGE snap $root | head -1)
  [[ -n $agent ]] && print -r -- "follow-up (paste): python3 -m json.tool $root/control/agents/$agent.json"
  say "[main-cand] side effect: a user's own 'pi --no-session' Main gets no host (documented)."
  local N=$ROOT/proj-nosession LOG=$ROOT/shim-main-nosession.log shim; mkproj $N; rm -f $LOG; shim=$(write_shim cand) || return 1
  pimain main-nosession $N $ROOT/agent-cand GRAFTLING_PYTHON=$shim SHIM_LOG=$LOG -- --no-session "Answer with exactly one word: ready." || return 1
  host_launches $LOG $MAINPID
  (( SRC == 0 )) && pass "the --no-session Main exited 0" || fail "the --no-session Main exited $SRC"
  (( NHOST == 0 )) && pass "no graftling.pi.host launch" || fail "$NHOST host launch(es) for a --no-session Main"
  [[ ! -e $N/.agents-control ]] && pass "no $N/.agents-control" || fail "$N/.agents-control was created"
  grep -q 'Extension error' $SOUT && fail "Extension error in the --no-session output" || pass "no Extension error"
  grep -qi ready $SOUT && pass "the --no-session Main answered (ready)" || fail "the --no-session Main's answer lacks 'ready'"
  (( OK )) || { print -r -- "next: inspect $ROOT/main-cand.txt, $root/control/agents/ and $ROOT/main-nosession.txt"; return 1; }
  print -r -- "next: zsh $THIS post   (third-party only if the user agreed: VERIFY585_THIRD_PARTY=1 zsh $THIS third-party)"
  ;;
third-party)
  [[ ${VERIFY585_THIRD_PARTY:-} == 1 ]] || { print -r -- "STOP: runs third-party plugin code; Main asks the user first, then: VERIFY585_THIRD_PARTY=1 zsh $THIS third-party"; return 1; }
  key_ready && need $ROOT/agent-cand/settings.json install || return 1
  say "[third-party] Main. mjakl and nicobailon (code copied from $P584, which is only read) with the candidate. Dialog: none."
  OK=1; local s a model; model=$(pimodel) || return 1
  for s in mjakl nicobailon; do
    a=$ROOT/agent-$s
    [[ -d $P584/agent-$s ]] || { print -r -- "STOP: $P584/agent-$s missing (584's installed plugin code)"; return 1; }
    rm -rf $a && cp -Rp $P584/agent-$s $a && rm -rf $a/extensions/recorder || return 1
    python3 -I -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "settings.json"; s = json.loads(p.read_text())
s["packages"] = [x for x in s.get("packages", []) if "graftling" not in str(x)]; p.write_text(json.dumps(s, indent=2))' $a || return 1
    allow $a -- pi install $(pkg cand) < /dev/null 2>&1 | tail -2
    defaults $a $model
    subagent_run third-$s $a cand $ASK_PLUGIN fixed || return 1
  done
  (( OK )) || { print -r -- "next: inspect $ROOT/third-*.txt and $ROOT/sessions-third-*"; return 1; }
  print -r -- "next: zsh $THIS post"
  ;;
post)
  say "[post] Main. Your ~/.pi/agent, ~/.dsh and the pi-584 plugin agent dirs vs pre (any difference FAILs). <5 s."
  need $ROOT/user-before.txt pre || return 1
  user_state > $ROOT/user-after.txt; cp $ROOT/user-after.txt $OUT/ 2>/dev/null
  OK=1
  diff $ROOT/user-before.txt $ROOT/user-after.txt && pass "~/.pi/agent, ~/.dsh and $P584's plugin agent dirs unchanged" || fail "a location changed (diff above)"
  print -r -- "Session files: $ROOT/sessions-*; outputs: $ROOT/*.txt (copied to $OUT). To remove everything afterwards: rm -rf $ROOT"
  (( OK ))
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $GCOMMIT -> $URL $BRANCH. Dialog: none expected."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && { pass "already on GitHub"; return 0; }
  local tmp=$ROOT/push-clone.git; rm -rf $tmp; git clone -q --bare $GREPO $tmp || return 1
  git -C $tmp fetch -q $BUNDLE "${BRANCH}:refs/heads/${BRANCH}" || return 1
  [[ $(git -C $tmp rev-parse $BRANCH) == $GCOMMIT ]] && pass "bundle head is $GCOMMIT" || { print -r -- "STOP: bundle head differs"; return 1; }
  print -r -- "authors and committers: $(git -C $tmp log --format='%an <%ae> | %cn <%ce>' $BASE..$BRANCH | sort -u)"
  git -C $tmp push $URL "${GCOMMIT}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $GCOMMIT ]] && pass "GitHub $BRANCH = $GCOMMIT" || fail "GitHub $BRANCH is not $GCOMMIT"
  rm -rf $tmp
  ;;
suite)
  setopt local_options no_bg_nice
  say "[suite] GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $others; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  git -C $GREPO bundle verify $BUNDLE >/dev/null 2>&1 || { print -r -- "STOP: $BUNDLE does not verify"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $GCOMMIT $WT || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))') || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY585_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra" | tee -a $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: newest suite; FAILED/ERROR lines classed against 516's current definition (+ $KNOWN_EXTRA). Dialog: none."
  local K=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- "516 current definition: $K"; [[ -f $K ]] || { print -r -- "STOP: cannot read $K"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet)"; return 1; }
  local line t id new=0 any=0; local -a ids=()
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; id=${line#* }; t=${id%%\[*}
    if [[ ${t##*::} == $KNOWN_EXTRA ]]; then print -r -- "known (585 brief): $line"
    elif grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $line"; else print -r -- "NEW: $line"; new=1; ids+=$id; fi
  done
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; new=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; new=1 ;;
    esac
  done
  print -r -- "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  (( $#ids )) && print -r -- "next (paste): zsh $THIS suite-base ${(j: :)${(q)ids}}"
  return $new
  ;;
suite-base)
  setopt local_options no_bg_nice
  local -a ids=("${(@)IDS}")
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base <node id>...   (SR prints the command with its NEW node ids)"; return 2; }
  say "[suite-base] the NEW node ids on GraphTraj $GTBASE with graftling $BASE (wheel). Dialog: none. No login."
  run_root base || return 1
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf $B && git clone -q --no-checkout $GTREPO $B && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  print -r -- "base checkout: $B (a git clone; $(git -C $B log --oneline -1))"
  local V=$T/venv-base-${BASE[1,8]}
  suite_venv $V $BASE $B || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  (cd $B && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${ids[@]}" > $R/base.txt 2>&1); local rc=$?
  tail -4 $R/base.txt; print -r -- "pytest exit=$rc (output: $R/base.txt)"
  local id fails=0
  for id in $ids; do
    if grep -qE "^(FAILED|ERROR) ${(b)id}( |\$)" $R/base.txt; then print -r -- "also fails on base: $id"
    elif grep -qE "^PASSED ${(b)id}\$" $R/base.txt; then print -r -- "candidate-only: $id"; fails=1
    else print -r -- "NOT RUN on base (missing there?): $id"; fails=1; fi
  done
  print -r -- "writes: $T ($B, $V, $R) and $RUNTMP only"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|install|bundled-base|bundled-cand|main-cand|third-party|post|push|suite|SR|suite-base <ids>"; return 2 ;;
esac
}
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
