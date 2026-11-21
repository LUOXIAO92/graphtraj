#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: fake Harness root, stub `codex`, real candidate build from the
# Worktree HEAD + graftling dev, real `graphtraj setup` of the isolated project, the steps up to (not including)
# the USER's interactive turn, R's refusal before that turn, and G through its own entry with real tests.
# Never touches production, ~/.codex or the Codex install.
#   zsh rehearse.zsh <empty or absent directory>
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
mkdir -p $F/H/.graphtraj $F/stub $F/codex-home/sessions
export VERIFY541_H=$F/H VERIFY541_WT=${SD:h:h} VERIFY541_BASE=$F/base VERIFY541_W=$F/w \
  VERIFY541_VPROJECT=$F/vproject VERIFY541_GL=$REALH/graftling VERIFY541_RT=$REALH/.venv-runtime \
  VERIFY541_CODEX=$F/stub/codex VERIFY541_CODEX_HOME=$F/codex-home
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.169.0 (stub)" ;;
  login) print "Logged in using ChatGPT (stub)" ;;
  exec) cat > /dev/null; print "model: gpt-6-luna"; print "CODEX-541-OK gpt-6-luna" ;;
  *) print "stub codex: $*" ;;
esac
EOF
chmod +x $F/stub/codex
S() { zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
expect() {  # $1 label, $2 expected rc, rest: the step
  local label=$1 want=$2; shift 2
  print -r -- "
======== rehearsal: $label (expect rc=$want)"
  S "$@"; local rc=$?
  if (( rc == want )); then print -r -- "==== $label: PASS (rc=$rc)"; (( pass++ ))
  else print -r -- "==== $label: FAIL (rc=$rc, expected $want)"; (( fail++ )); fi
}
expect "usage" 2 help
expect "00 preflight (stub codex; real build and setup)" 0 00
expect "T prints the USER folder-trust instructions" 0 T
expect "R before the USER turn refuses (no U stamp)" 1 R
expect "U Main part: project hooks from the candidate, then the USER instructions" 0 U
print -r -- "hooks.json written by U:"; cat $F/vproject/.codex/hooks.json
expect "R without the USER turn: no Main claim" 1 R
# Synthetic records in the shape the real hook and Codex write (claim, binding, rollout): R must PASS, and FAIL
# once a checker is bound. Only the record reading is rehearsed here; the real turn is the USER's.
$F/base/venv-cand/bin/python -I - $F/vproject $F/codex-home/sessions <<'FAKE'
import hashlib, json, sys, time
from pathlib import Path
project, sessions = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
runner = project / '.graphtraj/runner/main-sessions'
runner.mkdir(parents=True, exist_ok=True)
with (runner / 'continuity.jsonl').open('a') as stream:
    stream.write(json.dumps({'at': time.time() + 1, 'session': 'rehearsal-main', 'entry': 'codex:SessionStart:startup'}) + '\n')
binding = runner / ('finalize_' + hashlib.sha256(b'codex:rehearsal-main').hexdigest())
binding.mkdir(exist_ok=True)
(binding / 'session.yml').write_text('runtime: codex\nsession: rehearsal-main\n')
day = sessions / '2026/11/21'
day.mkdir(parents=True, exist_ok=True)
(day / 'rollout-rehearsal-main.jsonl').write_text('\n'.join(json.dumps(r) for r in (
    {'type': 'session_meta', 'payload': {'id': 'rehearsal-main', 'cwd': str(project)}},
    {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Reply with exactly one line: HELLO-541.'}},
)) + '\n')
FAKE
expect "R on synthetic records: bound Main, no checker" 0 R
bound=($F/vproject/.graphtraj/runner/main-sessions/finalize_*(/)); mkdir -p ${bound[1]}/checks/rehearsal-checker
expect "R on synthetic records with a bound checker: FAIL" 1 R
VERIFY541_TESTS="tests/test_main_finalize.py::test_project_without_tasks_ends_without_a_checker tests/test_external_session_entry.py::test_dsh_check_without_tasks_needs_no_checker tests/test_main_finalize.py::test_main_end_decision" \
  expect "G rehearsal: real tests through G's entry" 0 G
print -r -- "G suite output:"; cat $(cat $F/w/G-latest)/suite.txt | tail -5
expect "GR classifies the rehearsal G" 0 GR
grep -q '^exit=0' $(cat $F/w/G-latest)/suite.txt && { print "==== G rehearsal tests: PASS (exit=0)"; (( pass++ )); } \
  || { print "==== G rehearsal tests: FAIL"; (( fail++ )); }
print -r -- "
REHEARSAL SUMMARY: $pass passed, $fail failed (directory $F)"
(( fail == 0 ))
