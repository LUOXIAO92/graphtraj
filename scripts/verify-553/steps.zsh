#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 553: the candidate concept-clarification guide under 552's setup: the same four agents under test (S = sonnet |
# haiku | dsh | codex, all effort high), U = Fable 5.2 high simulated user, A = Sonnet 5.5 cheating auditor, the same
# answer key (scripts/verify-550/design.md, unchanged), texts (scripts/verify-552/design-552.md, unchanged), runs and
# probes. Differences from verify-552: README.md "Differences from 552".
#   zsh scripts/verify-553/steps.zsh <STEP> [args]          (Main's own non-sandboxed Bash, from this Worktree)
# Order: V -> 00 -> F -> R all all -> W (repeat) -> A all -> W -> C -> T; full suite G -> Gt -> GR (any time after V)
#   V [commit]  isolated venv <H>/tmp/553/venv from git archive of <commit> (default: this Worktree's HEAD) + graftling
#       wheel from git archive of graftling dev; production .venv-runtime only read. No dialog.
#   00  versions; isolated project BASE/project set up with the CANDIDATE venv; READY U and A; Codex/dsh Seatbelt
#       checks without a model; per agent S READY + probes (a)-(d) with the exact run flags. A FAIL blocks that agent.
#   P <agent>...  re-probe only these agents (no U/A, no runs touched).
#   F   copies 552's retained research notes into BASE/u/research (U input identical to 552; no model).
#   R <agent|all> <S#|all> [runs, default 3] [cap, default 8]   relay runs in the background
#   W   status (read only)
#   A <agent|all|run id> [cap, default 8]   audits of finished runs (background)
#   C   copies every run to <Worktree>/.state/realhost/<agent>/<S#>-r<k>/ (552 layout) + u-research, step-logs, table
#   T   writes <Worktree>/.state/realhost/compare-552.md (mechanical metrics beside 552's runs; no judgment)
#   G [pytest args]  full suite of this Worktree's HEAD with graftling dev (background, 6 shards); with args: plain
#       pytest on those args through the same venv and temp root (foreground)
#   Gt  focused tests (manual packaging and gateway) through G's venv, foreground
#   GR  read only: newest G and Gt; FAILED/ERROR lines classed known (554's integrated G, 516) or NEW
# BASE=/private/tmp/cc-553 (VERIFY553_BASE overrides it: rehearsal only). Never written: ~/.claude, ~/.codex (Codex
# itself writes each run's rollout into ~/.codex/sessions, normal Codex behaviour; the driver copies only the
# rollouts named by its own thread ids), DSH user config, dotfiles, .venv-runtime, the Harness except tmp/553 and C/T/G.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice no_hup
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY553_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY553_H:-${WT:h:h:h:h}}
BASE=${VERIFY553_BASE:-/private/tmp/cc-553}
T=${VERIFY553_T:-$H/tmp/553}                         # candidate venv, G's venv, wheels and sources
VENV=$T/venv                                         # the candidate install S's MCP server runs from
RT=$H/.venv-runtime                                  # production: only read
CONDA=$HOME/miniconda3/bin/python3.13
PY=${VERIFY553_PY:-$CONDA}                           # runs drv553.py (standard library only)
GL=${VERIFY553_GL:-$H/graftling}                     # graftling repository; only `git archive dev` is read
P=$BASE/project
OUT=${VERIFY553_DEST:-$WT/.state/realhost}
S552=${VERIFY553_S552:-$H/.graphtraj/core/state/tasks/552-concept-clarification-model-comparison/realhost}
KNOWN554=$H/.graphtraj/core/state/tasks/554-task-sync-manual-and-retire-harness-duplicate/realhost/G-a19d75b3-20261121T222317/suite.txt
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
FOCUSED=(tests/test_gateway.py tests/test_wheel_installation.py)
DSH_EXPECT=0.2.2-rc.5
PYTEST_TMP=${TMPDIR:-/tmp}
STEP=${1:-}; A1=${2:-}; A2=${3:-}; A3=${4:-}; A4=${5:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY553_STUBBIN:-} ]] && path=($VERIFY553_STUBBIN $path)   # rehearsal only: stub hosts first
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
CODEX=$(command -v codex || print codex); DSH=$(command -v dsh || print dsh)
SBX=${VERIFY553_SBX:-/usr/bin/sandbox-exec}
export V553_BASE=$BASE V553_WT=$WT V553_H=$H V553_CLAUDE=$CLAUDE V553_CODEX=$CODEX V553_DSH=$DSH V553_SBX=$SBX \
  V553_VENV=$VENV V553_PROD=$RT V553_MCP=$VENV/bin/graphtraj-mcp V553_PY=$PY V553_TURN_S=${VERIFY553_TURN_S:-900} \
  V553_DENYROOT=${VERIFY553_DENYROOT:-${H:h}} V553_CONTEXT=$H/CONTEXT.md \
  V553_CODEX_SESSIONS=${VERIFY553_CODEX_SESSIONS:-$HOME/.codex/sessions}
[[ -n ${VERIFY553_STUB_STATE:-} ]] && export STUB553_STATE=$VERIFY553_STUB_STATE

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
drv() { $PY -I $SD/drv553.py "$@"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
sha() { shasum -a 256 $1 2>/dev/null | cut -c1-64; }
load_key() {  # verify-549 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
}
need_venv() { [[ -x $VENV/bin/graphtraj-mcp && -f $VENV/installed-553 ]] || { print "STOP: no candidate venv; run: zsh $THIS V"; return 1; }; }
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host; as verify-531)
  local R=$RT/lib/python3.13/site-packages D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $R/click $R/click-*.dist-info(N) $R/yaml $R/_yaml(N) $R/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $R/websockets $R/websockets-*.dist-info(N) $D/
}
gl_wheel() {  # graftling wheel from git archive of graftling dev (never the working tree) into $T/wheels-gl-<id>; sets GLC, GLW
  GLC=$(git -C $GL rev-parse --verify dev^{commit}) || { print "STOP: no graftling dev in $GL"; return 1; }
  GLW=$T/wheels-gl-${GLC[1,8]}
  local have=($GLW/graftling-*.whl(N))
  if (( ! ${#have} )); then
    rm -rf $T/gsrc-${GLC[1,8]} $GLW; mkdir -p $T/gsrc-${GLC[1,8]}
    git -C $GL archive $GLC | tar -x -C $T/gsrc-${GLC[1,8]} || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $GLW $T/gsrc-${GLC[1,8]}/src/graftling >/dev/null || { print "STOP: graftling wheel build failed"; return 1; }
  fi
  print -r -- "graftling dev $GLC -> $(print -l $GLW/graftling-*.whl)"
}

[[ -d $H/.graphtraj || -n ${VERIFY553_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/logs $T

step_V() {
  say "V: candidate venv $VENV from git archive of a named commit + graftling dev wheel (dialog: none)"
  local ref=${A1:-HEAD} C
  C=$(git -C $WT rev-parse --verify "$ref^{commit}") || { print "STOP: $ref is not a commit in $WT"; return 1; }
  local prod_before=$(sha $RT/share/graphtraj/manuals/concept-clarification/guide.md)
  print -r -- "candidate commit: $C ($(git -C $WT log -1 --format=%s $C | cut -c1-100))"
  print -r -- "uncommitted changes in the Worktree (not used; the venv is built from the commit): $(git -C $WT status --porcelain | wc -l | tr -d ' ') path(s)"
  gl_wheel || return 1
  local SRC=$T/src-${C[1,8]} W=$T/wheels-${C[1,8]}
  rm -rf $SRC $W $VENV; mkdir -p $SRC
  git -C $WT archive $C | tar -x -C $SRC || return 1
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $W $SRC \
    >/dev/null || { print "STOP: graphtraj wheel build failed"; return 1; }
  $CONDA -m venv $VENV && copy_deps $VENV || return 1
  $VENV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps \
    $W/graphtraj-*.whl $GLW/graftling-*.whl || { print "STOP: install into $VENV failed"; return 1; }
  print -r -- "$C" > $VENV/installed-553
  (cd ${TMPDIR:-/tmp} && $VENV/bin/python -I -c 'import graphtraj, graftling, sys; print("venv imports: graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__)')
  say "observables: installed manuals vs the commit's files (sha256)"
  local f rel ok=1 n=0
  for rel in ${(f)"$(git -C $WT ls-tree -r --name-only $C -- manuals)"}; do
    local want=$(git -C $WT show $C:$rel | shasum -a 256 | cut -c1-64) got=$(sha $VENV/share/graphtraj/$rel)
    (( n++ ))
    if [[ $want == $got ]]; then print -r -- "MATCH $rel $got"; else print -r -- "DIFF  $rel installed ${got:-missing} commit $want"; ok=0; fi
  done
  for f in $VENV/share/graphtraj/manuals/**/*(N.); do
    rel=${f#$VENV/share/graphtraj/}
    git -C $WT cat-file -e $C:$rel 2>/dev/null || { print -r -- "EXTRA $rel (installed, not in the commit)"; ok=0; }
  done
  local cand=$(sha $VENV/share/graphtraj/manuals/concept-clarification/guide.md) prod_after=$(sha $RT/share/graphtraj/manuals/concept-clarification/guide.md)
  print -r -- "candidate guide sha256 (installed): $cand"
  print -r -- "production .venv-runtime guide sha256: before $prod_before, after $prod_after ($([[ $prod_before == $prod_after ]] && print unchanged || print CHANGED))"
  [[ $prod_before == $prod_after ]] || ok=0
  [[ $cand != $prod_after ]] || print "NOTE: the candidate guide equals production's"
  print -r -- "CHECK 553 V: $( (( ok )) && print PASS || print FAIL) ($n manual files compared; candidate $C)"
  (( ok )) || return 1
  next "zsh $THIS 00"
}

step_00() {
  need_venv || return 1
  say "versions (dialog: none). Newer claude/codex versions are recorded, not refused."
  print -r -- "zsh $ZSH_VERSION | $(git --version) | claude $CLAUDE: $($CLAUDE --version 2>&1 | head -1)"
  local dv=$($DSH --version 2>&1 | tail -1)
  print -r -- "codex $CODEX: $($CODEX --version 2>&1 | grep -v WARNING | tail -1) | dsh $DSH: $dv (expected $DSH_EXPECT: $([[ $dv == *$DSH_EXPECT* ]] && print yes || print 'NO - the session-record parser was checked on rc.5 only; probe (c) below shows whether it reads this version'))"
  print -r -- "zstd: $(zstd --version 2>&1 | head -1) | node $(node --version 2>&1) | sandbox-exec: $SBX"
  (cd $BASE && $VENV/bin/python -I -c 'import importlib.metadata as m; print("candidate venv graphtraj", m.version("graphtraj"), "| graftling", m.version("graftling"))')
  print -r -- "candidate commit (V): $(cat $VENV/installed-553) | Worktree HEAD $(git -C $WT rev-parse HEAD)"
  print -r -- "driver python: $($PY --version 2>&1) ($PY) | BASE $BASE"
  say "isolated project $P (own git; CANDIDATE venv graphtraj setup + claude host configuration)"
  mkdir -p $P
  if [[ ! -d $P/.git ]]; then
    (cd $P && git init -q -b main && print -r -- "# 553 scratch project" > README.md && git add README.md \
      && git -c user.name=553 -c user.email=553@invalid commit -qm "Initial source") || return 1
  fi
  if [[ ! -f $P/.graphtraj/config.yml ]]; then (cd $P && print y | clean $VENV/bin/graphtraj setup | tail -2) || return 1; fi
  (cd $P && clean $VENV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $CLAUDE --write >/dev/null) \
    && print "claude host configuration written: $P/.mcp.json, $P/.claude/" || { print "STOP: claude host configuration failed"; return 1; }
  $PY -I $SD/../verify-common/claude_isolation.py settings $H $P || return 1
  say "candidate guide as S's MCP server gives it (no model)"
  drv guide || return 1
  say "logins (d): codex login status; DSH key from the environment or ~/.zshrc (never printed)"
  print -r -- "codex: $(clean $CODEX login status 2>&1 | grep -v WARNING | tail -1)"
  load_key
  say "READY-553-U (Fable high) and READY-553-A (Sonnet; medium, else high, else low): one-line answer with model and login"
  drv ready U || { print "STOP: U is not ready"; return 1; }
  drv ready A || { print "STOP: A is not ready"; return 1; }
  probe_agents sonnet haiku dsh codex
  next "zsh $THIS F"
}

probe_agents() {  # $@: agents. No-model Seatbelt checks (codex, dsh), then S READY + probes with the exact run flags
  local ag fails=()
  [[ ${@[(Ie)codex]} -gt 0 ]] && { say "Codex Seatbelt without a model: the run's permission profile applied by 'codex sandbox' to plain commands"
    drv codex-sandbox 2>&1 | tee $BASE/codex-sandbox.txt; }
  [[ ${@[(Ie)dsh]} -gt 0 ]] && { say "dsh outer Seatbelt without a model: the run's dsh.sb applied by sandbox-exec to plain commands"
    drv dsh-sandbox 2>&1 | tee $BASE/dsh-sandbox.out; }
  for ag in $@; do
    rm -f $BASE/ready-$ag.ok
    say "READY-553-S-$ag + probes (a) (b) (c) (d) with the exact run flags (dialog: none)"
    drv ready-s $ag 2>&1 | tee $BASE/probes-$ag.txt
    (( ${pipestatus[1]} == 0 )) || fails+=($ag)
    local a=($BASE/logs/ready-$ag/01-S.argv.json(N)); [[ -n ${a[-1]:-} ]] && { print "S argv/config:"; cat ${a[-1]}; }
    [[ -f $BASE/logs/ready-$ag/dsh-patch.yml ]] && { print "dsh patch:"; cat $BASE/logs/ready-$ag/dsh-patch.yml; print "dsh outer Seatbelt profile:"; cat $BASE/logs/ready-$ag/dsh.sb; }
    [[ -f $BASE/logs/ready-$ag/s-settings.json ]] && print "claude settings: $BASE/logs/ready-$ag/s-settings.json ($(grep -c '"' $BASE/logs/ready-$ag/s-settings.json) lines), MCP: $(tr -d '\n ' < $BASE/logs/ready-$ag/s-mcp.json)"
  done
  say "summary"
  for ag in $@; do print -r -- "$ag: $([[ -f $BASE/ready-$ag.ok ]] && print 'PASS (R allowed)' || print 'FAIL (blocked from R; Main reports the probe lines above to the Leader)')"; done
  (( ${#fails} == 0 )) || print "STOP for: ${fails[*]}"
  for ag in $@; do [[ -f $BASE/ready-$ag.ok ]] && next "zsh $THIS R $ag all   (after F)"; done
  return 0
}

step_P() {  # re-probe only the named agents; U/A READY and other agents' runs are not touched
  local ag list=(${A1:-} ${A2:-} ${A3:-} ${A4:-}); list=(${list:#})
  (( ${#list} )) || { print "usage: P <sonnet|haiku|dsh|codex>...   (e.g. P codex dsh)"; return 2; }
  for ag in $list; do [[ $ag == (sonnet|haiku|dsh|codex) ]] || { print "usage: P <sonnet|haiku|dsh|codex>..."; return 2; }; done
  [[ -f $BASE/effort-A.txt && -d $P/.graphtraj ]] || { print "STOP: run 00 first"; return 1; }
  need_venv || return 1
  say "versions: codex $($CODEX --version 2>&1 | grep -v WARNING | tail -1) | dsh $($DSH --version 2>&1 | tail -1) (expected $DSH_EXPECT) | node $(node --version 2>&1)"
  [[ ${list[(Ie)codex]} -gt 0 ]] && print -r -- "codex: $(clean $CODEX login status 2>&1 | grep -v WARNING | tail -1)"
  [[ ${list[(Ie)dsh]} -gt 0 ]] && load_key
  probe_agents $list
}

step_F() {
  say "F: 552's retained research notes -> $BASE/u/research as U's RESEARCH NOTES (no model; dialog: none)"
  local s src
  mkdir -p $BASE/u/research
  for s in S1 S2 S3 S4; do
    src=$S552/u-research/$s.md
    [[ -f $src ]] || { print "STOP: $src missing"; return 1; }
    cp $src $BASE/u/research/$s.md
    print -r -- "$s: $src sha256 $(sha $src) -> $BASE/u/research/$s.md sha256 $(sha $BASE/u/research/$s.md)"
  done
  next "zsh $THIS R all all"
}

step_R() {
  local ag=${A1:-} sc=${A2:-} runs=${A3:-3} cap=${A4:-8}
  [[ $ag == (all|sonnet|haiku|dsh|codex) && $sc == (all|S[1-4]) && $runs == <1-9> && $cap == <1-64> ]] \
    || { print "usage: R <all|sonnet|haiku|dsh|codex> <all|S1..S4> [runs 1-9, default 3] [cap, default 8]"; return 2; }
  [[ -f $BASE/effort-A.txt ]] || { print "STOP: run 00 first"; return 1; }
  need_venv || return 1
  local s list=(S1 S2 S3 S4); [[ $sc == all ]] || list=($sc)
  for s in $list; do [[ -f $BASE/u/research/$s.md ]] || { print "STOP: $BASE/u/research/$s.md missing: run F"; return 1; }; done
  [[ $ag == (all|dsh) ]] && load_key
  say "relay runs in the background (dialog: none): agent $ag, scenario $sc, $runs run(s) each, at most $cap at once"
  $PY -I $SD/drv553.py batch $ag $sc $runs $cap < /dev/null > $BASE/logs/R-batch-$(date +%H%M%S).out 2>&1 &!
  print -r -- "batch started (pid $!), output $BASE/logs/R-batch-*.out; per run $BASE/logs/R-<run>.out and $BASE/logs/<run>/driver.log"
  next "zsh $THIS W"
}

step_W() {
  say "status (read only; dialog: none)"
  local s f
  for s in S1 S2 S3 S4; do
    print -r -- "research notes $s: $([[ -f $BASE/u/research/$s.md ]] && print "present, sha256 $(sha $BASE/u/research/$s.md)" || print 'missing (run F)')"
  done
  local total=0 ended=0 audited=0
  for f in $BASE/logs/(sonnet|haiku|dsh|codex)-S?-r<->(N/); do
    (( total++ ))
    local r=${f:t}
    if [[ -f $f/status.json ]]; then (( ended++ )); print -r -- "$r: ended $(tr -d '\n ' < $f/status.json | cut -c1-160) | audit: $(head -1 $f/audit.md 2>/dev/null || print -)"
      [[ -f $f/audit.md ]] && (( audited++ ))
    elif [[ -f $f/driver.log ]]; then print -r -- "$r: running | $(tail -1 $f/driver.log | cut -c1-160)"
    else print -r -- "$r: queued"; fi
  done
  print -r -- "runs: $total known, $ended ended, $audited audited"
  if (( total == 0 )); then next "zsh $THIS R all all   (after F)"
  elif (( ended < total )); then next "zsh $THIS W   (again in a few minutes)"
  elif (( audited < ended )); then next "zsh $THIS A all"
  else next "zsh $THIS C"; fi
}

step_A() {
  local which=${A1:-} cap=${A2:-8}
  [[ -n $which && $cap == <1-64> ]] || { print "usage: A <all|sonnet|haiku|dsh|codex|run id> [cap, default 8]"; return 2; }
  say "cheating audits (Sonnet, read only; dialog: none) in the background: $which, at most $cap at once"
  $PY -I $SD/drv553.py audits $which $cap < /dev/null > $BASE/logs/A-batch-$(date +%H%M%S).out 2>&1 &!
  print -r -- "audits started (pid $!), output $BASE/logs/A-batch-*.out -> $BASE/logs/<run>/audit.md"
  next "zsh $THIS W"
}

step_C() {
  say "copy to $OUT (read only on $BASE; dialog: none)"
  drv collect $OUT
  [[ -f $VENV/installed-553 ]] && print -r -- "candidate $(cat $VENV/installed-553) | guide sha256 $(sha $VENV/share/graphtraj/manuals/concept-clarification/guide.md)" | tee $OUT/candidate.txt
  next "zsh $THIS T"
}

step_T() {
  say "compare with 552 (read only on both; writes $OUT/compare-552.md; dialog: none)"
  [[ -f $S552/runs-table.md ]] || { print "STOP: $S552/runs-table.md missing"; return 1; }
  drv compare $OUT $S552
  next "Leader: read $OUT/compare-552.md, $OUT/runs-table.md and $OUT/<agent>/<S#>-r<k>/digest.md (+ logs/, audit.md, S-final-files/)"
}

# ---------------------------------------------------------------- full suite (modelled on verify-531 G/Gt/GR)
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
g_venv() {  # conda --system-site-packages (pytest) + production's click/yaml/websockets + graftling dev wheel + this Worktree editable. Sets V.
  gl_wheel || return 1
  V=$T/venv-g-gl-${GLC[1,8]}
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V (graftling dev ${GLC[1,8]}; this Worktree editable)"
  else
    rm -rf $V
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $GLW/graftling-*.whl || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT 2>&1 | grep -vi cache
    print -r -- $GLC > $V/installed
  fi
}
new_runtmp() {  # a new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-553-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
g_common() {  # guard + venv + imports
  local dirty=$(git -C $WT status --porcelain -- src tests plugins manuals pyproject.toml)
  print "uncommitted in src/tests/plugins/manuals/pyproject.toml: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  new_runtmp $1 || return 1
  g_venv || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive of graftling dev $GLC"
}
classify() {  # FAILED/ERROR lines of files $@ as known (554's integrated G, 516) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $KNOWN554 2>/dev/null; then print -r -- "known (554 integrated G a19d75b3; also 516 item 6): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

step_G() {
  local V RUNTMP R args=(${@:2})
  if (( ${#args} )); then say "G: pytest on the given args through G's venv and a new temp root (foreground; dialog: none)"
  else say "G: full suite of this Worktree's HEAD, 6 shards, --timeout 1500, -rA, background ~25 min (dialog: none). Run nothing else meanwhile."; fi
  g_common G || return 1
  R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling dev $GLC"; } > $R/run.txt
  if (( ${#args} )); then
    print -r -- "args: ${args[*]}" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt ${args[@]} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
    tail -4 $R/suite.txt; classify $R/suite.txt
    print -r -- "output: $R/suite.txt"
    next "zsh $THIS G   (complete suite)"
    return 0
  fi
  (cd $WT && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  next "zsh $THIS Gt   (after G ends: zsh $THIS GR)"
}

step_Gt() {
  say "Gt: focused tests (${FOCUSED[*]}) through G's venv, foreground (dialog: none; ~1 min)"
  local V RUNTMP; g_common Gt || return 1
  local R=$OUT/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED | pytest temp root $RUNTMP" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt $FOCUSED > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  tail -3 $R/suite.txt; classify $R/suite.txt
  print -r -- $R > $OUT/Gt-latest
  next "zsh $THIS GR   (when G's suite.txt ends with exit=)"
}

step_GR() {
  say "GR: read only. Newest G and Gt; FAILED/ERROR lines classed known or NEW (dialog: none)"
  print -r -- "known lists: $KNOWN554 (Task 554, integrated, latest full suite: 1 failed / 3623 passed) and $KNOWN516"
  local g=$(cat $OUT/G-latest 2>/dev/null) t=$(cat $OUT/Gt-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet"; next "zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify $t/suite.txt; }
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line in G or Gt."
  next "report this output to the Leader"
}

case $STEP in
  V) step_V ;;
  00) step_00 ;;
  P) step_P ;;
  F) step_F ;;
  R) step_R ;;
  W) step_W ;;
  A) step_A ;;
  C) step_C ;;
  T) step_T ;;
  G) step_G "$@" ;;
  Gt) step_Gt ;;
  GR) step_GR ;;
  *) print "usage: zsh $THIS <V [commit] | 00 | P <agent>... | F | R <agent|all> <S#|all> [runs] [cap] | W | A <agent|all|run id> [cap] | C | T | G [pytest args] | Gt | GR>"; return 2 ;;
esac
