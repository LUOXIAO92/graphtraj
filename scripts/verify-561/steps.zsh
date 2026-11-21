#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 561 (graftling): the DSH relay service agentMessages declares its own inject (sessionQuery, agents).
#   zsh scripts/verify-561/steps.zsh <STEP> [pytest args for T/TB]   (Main's Bash, from this Task's Worktree)
# Order: 00 -> R -> T -> TB -> C
#   00  versions; the installed dsh answers one line (model + login) from an isolated project with a scratch DSH_HOME;
#       candidate (git archive of SRC's HEAD) -> BASE/src + BASE/venv, baseline dev (BASELINE) -> BASE/base-src +
#       BASE/base-venv, both editable without dependencies (--system-site-packages of the driver Python; websockets
#       copied read only from the Harness .venv-runtime when missing).
#   R   real entry, baseline then candidate: drv561.py starts the INSTALLED dsh (`dsh --profile web --patch ... web`)
#       through graftling's own DshService with graftling's plugin.mjs loaded (scratch DSH_HOME under BASE), creates
#       and follows one native Session and sends the agentMessages/receive request graftling's owning host sends
#       (execution.py completion notice / receive; plugin.mjs host notices call the same receive). Observable:
#       `OBSERVABLE: DELIVERED|NOT DELIVERED` + the native result envelope + the Session inbox line.
#       Then, for the reported error itself, graftling's native relay fixture (tests/fixtures/dsh_communication.mjs,
#       installCommunication on a root context without inject) against each copy's communication.mjs, and
#       probe561.mjs (graftling's plugin.mjs loaded as a cordis plugin, Gateway invoke, no listener).
#   T   graftling pytest -rfE on the candidate copy with TMPDIR=${TMPDIR:-/tmp} (printed; must be outside the
#       Harness). Extra args go to pytest (none: the full suite) and are remembered for TB.
#   TB  the same pytest arguments on the baseline copy.
#   C   read only on the logs: NEW (candidate-only) failures, baseline-only, both; copies BASE/logs to
#       <Worktree>/.state/realhost/561/.
# Layout: BASE=/private/tmp/gl-561 (VERIFY561_BASE overrides): src/ venv/ base-src/ base-venv/ runs/ projects/ logs/.
# Never written: the user's DSH install, ~/.dsh, ~/ dotfiles (~/.zshrc is only read for DEEPSEEK_API_KEY in 00), the
# Harness (except C's copy into this Worktree's .state/realhost), .venv-runtime, <Harness>/graftling.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY561_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY561_H:-${WT:h:h:h:h}}
SRC=${VERIFY561_SRC:-$WT/.scratch/561/graftling}         # candidate clone (branch agent/561-...)
BASE=${VERIFY561_BASE:-/private/tmp/gl-561}
PY=${VERIFY561_PY:-$HOME/miniconda3/bin/python3.13}
DEST=${VERIFY561_DEST:-$WT/.state/realhost/561}           # override: rehearsal only
BASELINE=${VERIFY561_BASELINE:-6794ce02b6210ec88837437affb8d7b525612804}   # graftling dev the candidate is based on
V=$BASE/venv; BV=$BASE/base-venv
STEP=${1:-}; (( $# )) && shift
path=(/opt/homebrew/bin $path)

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
# Clean environment; $1 is the venv whose bin leads PATH.
clean() { local venv=$1; shift; env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$venv/bin:/opt/homebrew/bin:/usr/bin:/bin \
  TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

[[ -d $H/.graphtraj || -n ${VERIFY561_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/logs

# prepare <commit> <copy dir> <venv>: git archive of <commit> from SRC, installed editable without dependencies.
prepare() {
  local commit=$1 copy=$2 venv=$3
  rm -rf $copy && mkdir -p $copy
  git -C $SRC archive $commit | tar -x -C $copy || return 1
  git -C $SRC rev-parse $commit > $copy/CANDIDATE
  [[ -x $venv/bin/python ]] || $PY -m venv --system-site-packages $venv || return 1
  (cd $BASE && clean $venv $venv/bin/python -m pip install -q --no-deps --no-build-isolation --no-cache-dir \
    -e $copy/src/graftling 2>&1 | grep -v 'not owned or is not writable' ) || true
  if ! (cd $BASE && clean $venv $venv/bin/python -I -c 'import websockets' 2>/dev/null); then
    local site=$($venv/bin/python -c 'import site; print(site.getsitepackages()[0])')
    local runtime=$H/.venv-runtime/lib/python3.13/site-packages
    print -r -- "websockets: copied read only from $runtime"
    cp -R $runtime/websockets $runtime/websockets-*.dist-info $site/ || return 1
  fi
  (cd $BASE && clean $venv $venv/bin/python -I -c '
import graftling, websockets, yaml
print("graftling", graftling.__version__, "from", graftling.__file__)
print("websockets", websockets.__version__, "| PyYAML", yaml.__version__)')
  print -r -- "agentMessages static inject in this copy: $(grep -c "static inject = \['sessionQuery', 'agents'\]" $copy/src/graftling/dsh/communication.mjs)"
}

load_key() {
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
}

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | driver python: $($PY --version 2>&1) ($PY) | node $(node --version 2>&1)"
  print -r -- "dsh $(dsh --version 2>&1 | tail -1) ($(command -v dsh) -> ${$(command -v dsh):A})"
  print -r -- "installed cordis: $(node -p "require('${${$(command -v dsh):A}:h:h}/node_modules/@deepseek-ai/cordis/package.json').version" 2>&1)"
  print -r -- "TMPDIR=${TMPDIR:-/tmp} (pytest's temp root in T/TB; must be outside $H) | BASE $BASE"
  print -r -- "candidate: $SRC @ $(git -C $SRC rev-parse HEAD) ($(git -C $SRC rev-parse --abbrev-ref HEAD))"
  print -r -- "candidate author: $(git -C $SRC log -1 --format='%an <%ae>')"
  print -r -- "baseline:  $(git -C $SRC rev-parse $BASELINE) ($(git -C $SRC log -1 --format='%s' $BASELINE))"
  print -r -- "baseline is an ancestor of the candidate: $(git -C $SRC merge-base --is-ancestor $BASELINE HEAD && print yes || print NO)"

  say "the installed DSH answers one line from an isolated project, scratch DSH_HOME (dialog: none; at most 120 s)"
  local p=$BASE/projects/ready dh=$BASE/dsh-home-00
  mkdir -p $p $dh
  print -r -- "- id: llm-deepseek
  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}" > $BASE/llm.patch.yml
  if [[ -n ${VERIFY561_NOMODEL:-} ]]; then print "VERIFY561_NOMODEL: no model call (rehearsal)"
  else
    load_key
    (cd $p && env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=${TMPDIR:-/tmp} \
      LANG=${LANG:-en_US.UTF-8} DSH_HOME=$dh ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} \
      $BOUND 120 dsh --profile headless --patch $BASE/llm.patch.yml --permission-mode read-only \
      'Reply with one line: READY-561-DSH, your exact model name, and the provider or login you answer through. Use no tool.' \
      < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$? (142 = 120 s timeout)"
  fi

  say "candidate copy BASE/src and venv BASE/venv (dialog: none)"
  prepare HEAD $BASE/src $V || return 1
  say "baseline copy BASE/base-src and venv BASE/base-venv (dialog: none)"
  prepare $BASELINE $BASE/base-src $BV || return 1
  print -r -- "
READY when: a READY-561-DSH line naming the model and login, dsh 0.2.2-rc.5 (or newer), two 'graftling 0.6.2 from'
lines (BASE/src and BASE/base-src), static inject 1 (candidate) and 0 (baseline), the noreply candidate author."
  next "zsh $THIS R"
}

step_R() {
  [[ -x $V/bin/python && -x $BV/bin/python ]] || { print "STOP: run step 00 first"; return 1; }
  local label venv copy rc
  for label in baseline candidate; do
    if [[ $label == baseline ]]; then venv=$BV copy=$BASE/base-src; else venv=$V copy=$BASE/src; fi
    say "[$label $(cat $copy/CANDIDATE | cut -c1-10)] real entry: installed dsh web + graftling plugin.mjs, agentMessages/receive (dialog: none; no browser is opened: --no-open)"
    (cd $BASE && clean $venv $BOUND 120 $venv/bin/python -I $SD/drv561.py $label $BASE/runs/$label $BASE/projects/$label) \
      2>&1 | tee $BASE/logs/R-$label.out
    say "[$label] graftling's native relay fixture (installCommunication on a root context without inject; dialog: none)"
    (cd $BASE && clean $venv $BOUND 30 node $BASE/src/tests/fixtures/dsh_communication.mjs ${$(command -v dsh):A} \
      $copy/src/graftling/dsh/communication.mjs > $BASE/logs/F-$label.out 2>&1); rc=$?
    print -r -- "[$label] fixture exit $rc$( ((rc)) && print -r -- ": $(grep -m1 -E '^Error|Error:' $BASE/logs/F-$label.out)")"
    grep -m2 -E 'at Proxy\.(deliver|receive)' $BASE/logs/F-$label.out | sed "s/^ */[$label]   /"
    say "[$label] graftling's plugin.mjs as a cordis plugin, Gateway invoke (probe561.mjs, no listener; dialog: none)"
    (cd $BASE && clean $venv $BOUND 30 node $SD/probe561.mjs $label ${$(command -v dsh):A} \
      $copy/src/graftling/dsh/plugin.mjs) 2>&1 | tee $BASE/logs/P-$label.out
  done
  say "summary"
  for label in baseline candidate; do
    print -r -- "$label: real entry $(grep -ho 'OBSERVABLE: [A-Z ]*' $BASE/logs/R-$label.out 2>/dev/null | head -1 || print '(no line)') | fixture $(grep -q '^{' $BASE/logs/F-$label.out && print PASS || print "FAIL ($(grep -m1 -o 'cannot get property[^)]*inject' $BASE/logs/F-$label.out || print other))") | plugin path $(grep -ho 'OBSERVABLE: [A-Z ]*' $BASE/logs/P-$label.out | head -1)"
  done
  print -r -- "Expected: candidate DELIVERED on all three; baseline fixture FAIL (cannot get property \"sessionQuery\" without inject).
Baseline on the real entry and plugin path: DELIVERED is expected too (plugin.mjs injects sessionQuery and agents), i.e. the
reported error did not reach a real DSH Session through graftling's plugin; NOT DELIVERED there would mean it does."
  next "zsh $THIS T"
}

# suite <label> <copy dir> <venv> <log> [pytest args]: one pytest run with failing ids in the log (-rfE).
suite() {
  local label=$1 copy=$2 venv=$3 log=$4; shift 4
  local tmp=${TMPDIR:-/tmp}
  [[ -x $venv/bin/python ]] || { print "STOP: run step 00 first"; return 1; }
  case ${tmp:A}/ in ${H:A}/*) print "STOP: TMPDIR $tmp is inside the Harness"; return 1 ;; esac
  print -r -- "$label $(cat $copy/CANDIDATE) in $copy | TMPDIR=$tmp | args: ${*:-<full suite>}"
  (cd $copy && clean $venv TMPDIR=$tmp $venv/bin/python -m pytest -p no:cacheprovider -q -rfE "$@") 2>&1 | tee $log
  local code=$?
  print -r -- "($label pytest exit $code)"
}

step_T() {
  say "graftling pytest on the candidate (dialog: none)"
  print -r -- "${(j: :)${(q)@}}" > $BASE/logs/T.args
  suite candidate $BASE/src $V $BASE/logs/T.out "$@"
  next "zsh $THIS TB${*:+ ${(j: :)${(q)@}}}"
}

step_TB() {
  say "graftling pytest on the baseline (dialog: none)"
  (( $# )) || { [[ -s $BASE/logs/T.args ]] && set -- ${(Q)${(z)"$(<$BASE/logs/T.args)"}} }
  print -r -- "${(j: :)${(q)@}}" > $BASE/logs/TB.args
  suite baseline $BASE/base-src $BV $BASE/logs/TB.out "$@"
  next "zsh $THIS C"
}

# Failing or erroring test ids of one -rfE log, sorted.
failing() { [[ -f $1 ]] && grep -E '^(FAILED|ERROR) ' $1 | awk '{print $2}' | sort -u; }

step_C() {
  say "compare candidate and baseline failures (read only; dialog: none)"
  local t=$BASE/logs/T.out tb=$BASE/logs/TB.out
  print -r -- "candidate args: $(cat $BASE/logs/T.args 2>/dev/null) | baseline args: $(cat $BASE/logs/TB.args 2>/dev/null)"
  [[ "$(cat $BASE/logs/T.args 2>/dev/null)" == "$(cat $BASE/logs/TB.args 2>/dev/null)" ]] \
    || print -r -- "NOTE: T and TB ran different pytest arguments"
  print -r -- "candidate summary: $(tail -1 $t 2>/dev/null)"
  print -r -- "baseline summary:  $(tail -1 $tb 2>/dev/null)"
  failing $t > $BASE/logs/T.failing; failing $tb > $BASE/logs/TB.failing
  local new=$(comm -23 $BASE/logs/T.failing $BASE/logs/TB.failing) old=$(comm -13 $BASE/logs/T.failing $BASE/logs/TB.failing)
  local both=$(comm -12 $BASE/logs/T.failing $BASE/logs/TB.failing)
  print -r -- "failing in candidate: $(wc -l < $BASE/logs/T.failing | tr -d ' ') | in baseline: $(wc -l < $BASE/logs/TB.failing | tr -d ' ') | in both: $(print -n -- $both | grep -c .)"
  print -r -- "NEW (candidate only): $(print -n -- $new | grep -c .)"; [[ -n $new ]] && print -r -- $new
  print -r -- "baseline only: $(print -n -- $old | grep -c .)"; [[ -n $old ]] && print -r -- $old
  [[ -n $both ]] && { print -r -- "in both (pre-existing):"; print -r -- $both }

  say "copy logs to $DEST (dialog: none)"
  mkdir -p $DEST && cp -R $BASE/logs/. $DEST/ || return 1
  [[ -f $BASE/src/CANDIDATE ]] && cp $BASE/src/CANDIDATE $DEST/
  [[ -f $BASE/base-src/CANDIDATE ]] && cp $BASE/base-src/CANDIDATE $DEST/BASELINE
  ls -l $DEST
}

case $STEP in
  00|R|T|TB|C) step_$STEP "$@" ;;
  *) print "usage: zsh $THIS <00|R|T|TB|C> [pytest args for T/TB]"; return 2 ;;
esac
