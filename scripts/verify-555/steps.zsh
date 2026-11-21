#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 555 (graftling): one call returns every input problem; execute takes its arguments from a JSON file.
#   zsh scripts/verify-555/steps.zsh <STEP> [pytest args for T/TB]  (Main's Bash, from this Task's Worktree)
# Order: 00 -> D -> T -> TB -> C
#   00  versions; copies the candidate commit (git archive of SRC's HEAD) to BASE/src and installs it editable,
#       without dependencies, into BASE/venv (--system-site-packages of the driver Python); the baseline dev commit
#       (BASELINE) the same way into BASE/base-src and BASE/base-venv. websockets, when the driver Python lacks it,
#       is copied read only from the Harness .venv-runtime. No model host is used.
#   D   through the REAL standalone entry: drv555.py stands in for the native DSH process only; it starts the real
#       owning host (python -m graftling.dsh.host) and the real stdio MCP entry BASE/venv/bin/agents-mcp, and sends
#       tools/call lines: several problems in one call, file arguments success, file content problems, missing file,
#       invalid JSON, non-object, outside the boundary (.. and a symlink). The boundary is the native Session cwd.
#   T   graftling's pytest -rfE in BASE/src with TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Extra args go to
#       pytest (none: the full suite) and are remembered for TB.
#   TB  the same pytest arguments on the baseline copy BASE/base-src (other args may be given explicitly).
#   C   read only on the logs: failing/erroring test ids in the candidate only (= new failures), in the baseline
#       only, and both summaries; then copies BASE/logs to <Worktree>/.state/realhost/555/.
# Layout: BASE=/private/tmp/gl-555 (VERIFY555_BASE overrides it): src/ + venv/ (candidate), base-src/ + base-venv/
# (baseline), demo/, logs/.
# Never written: ~/, dotfiles, the Harness (except C's copy into this Worktree's .state/realhost), .venv-runtime.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY555_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY555_H:-${WT:h:h:h:h}}
SRC=${VERIFY555_SRC:-$WT/.scratch/555/graftling}         # candidate clone (branch agent/555-...)
BASE=${VERIFY555_BASE:-/private/tmp/gl-555}
PY=${VERIFY555_PY:-$HOME/miniconda3/bin/python3.13}
DEST=${VERIFY555_DEST:-$WT/.state/realhost/555}           # override: rehearsal only
BASELINE=${VERIFY555_BASELINE:-6794ce02b6210ec88837437affb8d7b525612804}   # graftling dev the candidate is based on
V=$BASE/venv; BV=$BASE/base-venv
STEP=${1:-}; (( $# )) && shift

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
# Clean environment; $1 is the venv whose bin leads PATH.
clean() { local venv=$1; shift; env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$venv/bin:/opt/homebrew/bin:/usr/bin:/bin \
  TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

[[ -d $H/.graphtraj || -n ${VERIFY555_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
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
print("websockets", websockets.__version__, "| PyYAML", yaml.__version__)
print("555 public names:", all(name in graftling.__all__ for name in ("ValidationErrors", "schema_errors", "read_envelope_arguments")))')
}

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | driver python: $($PY --version 2>&1) ($PY) | BASE $BASE"
  print -r -- "candidate: $SRC @ $(git -C $SRC rev-parse HEAD) ($(git -C $SRC rev-parse --abbrev-ref HEAD))"
  print -r -- "candidate author: $(git -C $SRC log -1 --format='%an <%ae>')"
  print -r -- "baseline:  $(git -C $SRC rev-parse $BASELINE) ($(git -C $SRC log -1 --format='%s' $BASELINE))"
  print -r -- "baseline is an ancestor of the candidate: $(git -C $SRC merge-base --is-ancestor $BASELINE HEAD && print yes || print NO)"
  print -r -- "model host: none (no model is called by any step)"

  say "candidate copy BASE/src and venv BASE/venv (dialog: none)"
  prepare HEAD $BASE/src $V || return 1
  print -r -- "agents-mcp entry: $V/bin/agents-mcp"

  say "baseline copy BASE/base-src and venv BASE/base-venv (dialog: none)"
  prepare $BASELINE $BASE/base-src $BV || return 1
  next "zsh $THIS D"
}

step_D() {
  say "demo through agents-mcp and its owning DSH host (dialog: none)"
  [[ -x $V/bin/agents-mcp ]] || { print "STOP: run step 00 first"; return 1; }
  local d=$BASE/demo
  rm -rf $d && mkdir -p $d/dsh/lib $d/ws/args $d/data
  print -r -- '{"name": "@deepseek-ai/dsh", "version": "0.2.2-alpha.2"}' > $d/dsh/package.json
  cp $SD/drv555.py $d/dsh/lib/bin.py
  print -r -- "{\"root\": \"$d/data\"}" > $d/host.json
  print -r -- '{}' > $d/ws/args/status.json
  print -r -- '{"runtime": "dsh", "colour": "secret-555", "name": 5}' > $d/ws/args/create.json
  print -r -- '{"agent": "secret-555",' > $d/ws/args/broken.json
  print -r -- '["secret-555"]' > $d/ws/args/list.json
  print -r -- '{"agent": "secret-555"}' > $d/outside.json
  ln -s $d/outside.json $d/ws/args/link.json
  $V/bin/python -I - $d <<'EOF'
import json, sys
d = sys.argv[1]
cases = [
    ('several problems in one call (envelope + arguments)',
     {'action': 'execute', 'feature': 'create', 'query': 'x', 'arguments': {'runtime': 1, 'name': [], 'colour': 'red'}}),
    ('file arguments success (args/status.json = {})',
     {'action': 'execute', 'feature': 'status', 'arguments_file': 'args/status.json'}),
    ('file content problems, with an envelope problem, in one call',
     {'action': 'execute', 'feature': 'create', 'schema': True, 'arguments_file': 'args/create.json'}),
    ('missing file', {'action': 'execute', 'feature': 'status', 'arguments_file': 'args/missing.json'}),
    ('invalid JSON', {'action': 'execute', 'feature': 'status', 'arguments_file': 'args/broken.json'}),
    ('not an object', {'action': 'execute', 'feature': 'status', 'arguments_file': 'args/list.json'}),
    ('outside the boundary (..)', {'action': 'execute', 'feature': 'status', 'arguments_file': '../outside.json'}),
    ('outside the boundary (symlink in ws)', {'action': 'execute', 'feature': 'status', 'arguments_file': 'args/link.json'}),
]
json.dump({'config': f'{d}/host.json', 'workspace': f'{d}/ws', 'agents_mcp': sys.prefix + '/bin/agents-mcp',
           'cases': [{'name': name, 'request': request} for name, request in cases]}, open(f'{d}/demo.json', 'w'))
EOF
  print -r -- "workspace (boundary = native Session cwd): $d/ws | outside file: $d/outside.json | ws/args/link.json -> $d/outside.json"
  (cd $d/ws && clean $V GRAFTLING_DSH_NODE=$V/bin/python GRAFTLING_DSH_ENTRY=$d/dsh/lib/bin.py \
    $V/bin/python $d/dsh/lib/bin.py $d/demo.json $BASE/logs/D.transcript.jsonl) 2>&1 | tee $BASE/logs/D.out
  local code=$?
  print -r -- "
'secret-555' (file content) in any result: $(grep -q 'secret-555' <(grep received $BASE/logs/D.transcript.jsonl) && print YES || print no)"
  (( code == 0 )) || return $code
  next "zsh $THIS T"
}

# suite <label> <copy dir> <venv> <log> [pytest args]: one pytest run with failing ids in the log (-rfE).
suite() {
  local label=$1 copy=$2 venv=$3 log=$4; shift 4
  local tmp=${TMPDIR:-/tmp}
  [[ -x $venv/bin/python ]] || { print "STOP: run step 00 first"; return 1; }
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
  00|D|T|TB|C) step_$STEP "$@" ;;
  *) print "usage: zsh $THIS <00|D|T|TB|C> [pytest args for T/TB]"; return 2 ;;
esac
