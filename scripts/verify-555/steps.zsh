#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 555 (graftling): one call returns every input problem; execute takes its arguments from a JSON file.
#   zsh scripts/verify-555/steps.zsh <STEP> [pytest args for T]     (Main's Bash, from this Task's Worktree)
# Order: 00 -> D -> T -> C
#   00  versions; copies the candidate commit (git archive of SRC's HEAD) to BASE/src and installs it editable,
#       without dependencies, into BASE/venv (--system-site-packages of the driver Python). websockets, when the
#       driver Python lacks it, is copied read only from the Harness .venv-runtime. No model host is used.
#   D   through the REAL standalone entry: drv555.py stands in for the native DSH process only; it starts the real
#       owning host (python -m graftling.dsh.host) and the real stdio MCP entry BASE/venv/bin/agents-mcp, and sends
#       tools/call lines: several problems in one call, file arguments success, file content problems, missing file,
#       invalid JSON, non-object, outside the boundary (.. and a symlink). The boundary is the native Session cwd.
#   T   graftling's pytest in BASE/src with TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Extra args go to pytest.
#   C   copies BASE/logs to <Worktree>/.state/realhost/555/.
# Layout: BASE=/private/tmp/gl-555 (VERIFY555_BASE overrides it): src/ (candidate copy), venv/, demo/, logs/.
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
V=$BASE/venv
STEP=${1:-}; (( $# )) && shift

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$V/bin:/opt/homebrew/bin:/usr/bin:/bin TERM=${TERM:-xterm} \
  TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

[[ -d $H/.graphtraj || -n ${VERIFY555_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/logs

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | driver python: $($PY --version 2>&1) ($PY) | BASE $BASE"
  print -r -- "candidate: $SRC @ $(git -C $SRC rev-parse HEAD) ($(git -C $SRC rev-parse --abbrev-ref HEAD))"
  print -r -- "candidate author: $(git -C $SRC log -1 --format='%an <%ae>')"
  print -r -- "model host: none (no model is called by any step)"

  say "candidate copy BASE/src and venv BASE/venv (dialog: none)"
  rm -rf $BASE/src && mkdir -p $BASE/src
  git -C $SRC archive HEAD | tar -x -C $BASE/src || return 1
  git -C $SRC rev-parse HEAD > $BASE/src/CANDIDATE
  [[ -x $V/bin/python ]] || $PY -m venv --system-site-packages $V || return 1
  (cd $BASE && clean $V/bin/python -m pip install -q --no-deps --no-build-isolation --no-cache-dir \
    -e $BASE/src/src/graftling 2>&1 | grep -v 'not owned or is not writable' ) || true
  if ! (cd $BASE && clean $V/bin/python -I -c 'import websockets' 2>/dev/null); then
    local site=$($V/bin/python -c 'import site; print(site.getsitepackages()[0])')
    local runtime=$H/.venv-runtime/lib/python3.13/site-packages
    print -r -- "websockets: copied read only from $runtime"
    cp -R $runtime/websockets $runtime/websockets-*.dist-info $site/ || return 1
  fi
  (cd $BASE && clean $V/bin/python -I -c '
import graftling, websockets, yaml
print("graftling", graftling.__version__, "from", graftling.__file__)
print("websockets", websockets.__version__, "| PyYAML", yaml.__version__)
print("new public names:", all(name in graftling.__all__ for name in ("ValidationErrors", "schema_errors", "read_envelope_arguments")))') || return 1
  print -r -- "agents-mcp entry: $V/bin/agents-mcp"
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
  (cd $d/ws && clean GRAFTLING_DSH_NODE=$V/bin/python GRAFTLING_DSH_ENTRY=$d/dsh/lib/bin.py \
    $V/bin/python $d/dsh/lib/bin.py $d/demo.json $BASE/logs/D.transcript.jsonl) 2>&1 | tee $BASE/logs/D.out
  local code=$?
  print -r -- "
'secret-555' (file content) in any result: $(grep -q 'secret-555' <(grep received $BASE/logs/D.transcript.jsonl) && print YES || print no)"
  (( code == 0 )) || return $code
  next "zsh $THIS T"
}

step_T() {
  say "graftling pytest in $BASE/src (dialog: none)"
  [[ -x $V/bin/python ]] || { print "STOP: run step 00 first"; return 1; }
  local tmp=${TMPDIR:-/tmp}
  print -r -- "candidate $(cat $BASE/src/CANDIDATE) | TMPDIR=$tmp | args: ${*:-<full suite>}"
  (cd $BASE/src && clean TMPDIR=$tmp $V/bin/python -m pytest -p no:cacheprovider -q "$@") 2>&1 | tee $BASE/logs/T.out
  local code=$?
  print -r -- "(pytest exit $code)"
  next "zsh $THIS C"
  return $code
}

step_C() {
  say "copy logs to $DEST (dialog: none)"
  mkdir -p $DEST && cp -R $BASE/logs/. $DEST/ || return 1
  [[ -f $BASE/src/CANDIDATE ]] && cp $BASE/src/CANDIDATE $DEST/
  ls -l $DEST
}

case $STEP in
  00|D|T|C) step_$STEP "$@" ;;
  *) print "usage: zsh $THIS <00|D|T|C> [pytest args for T]"; return 2 ;;
esac
