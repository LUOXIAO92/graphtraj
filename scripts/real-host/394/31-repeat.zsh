#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 31-repeat: step 30's one new failure, run 5 times at COMMIT and 5 times at the base.
# Run in a plain macOS Terminal, outside any sandbox, after step 30:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/31-repeat.zsh
#
# tests/test_codex_app_server.py::test_unhandled_server_requests_fail_visibly_without_blocking_peers failed at COMMIT
# in its [raised-RUNTIME_REQUEST_FAILED] variant with `Codex initialize request 1 timed out` (request_timeout=0.5);
# its [cancelled] variant failed the same way at COMMIT and at the base. This counts each variant's failures in
# both of step 30's trees, as they are: no clone, no install. No model, no key.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 31-repeat 5 none "every variant's failures at COMMIT are at most the base's plus one, out of 5 runs each"
TEST='tests/test_codex_app_server.py::test_unhandled_server_requests_fail_visibly_without_blocking_peers'
RUNS=5
HEAD_DIR=$AG/suite
BASE_DIR=$AG/suite-base
for pair in "$HEAD_DIR:$COMMIT" "$BASE_DIR:$BASE"; do
  dir=${pair%%:*} want=${pair#*:}
  [[ -x $dir/venv/bin/python && -d $dir/clone && -f $dir/installed-commit ]] \
    || fail "$dir is not a tree step 30 built; run: zsh $HERE/30-suite.zsh"
  [[ $(<$dir/installed-commit) == $want ]] || fail "$dir was built from $(<$dir/installed-commit), not $want; run: zsh $HERE/30-suite.zsh"
done
check PASS "step 30's trees: $HEAD_DIR at $COMMIT, $BASE_DIR at $BASE"
# Step 30's form: a short TMPDIR (Unix sockets) and the allowlisted environment.
SHORT=${AGENTS_394_DRY_SHORT:-/tmp/agents-394-repeat}
[[ -e $SHORT ]] && mv $SHORT $SHORT.$STAMP
mkdir -p $SHORT
test_env() {
  TESTENV=(env -i HOME=$1/home PATH=$1/venv/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$SHORT
           LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1)
}

for label in head base; do
  [[ $label == head ]] && dir=$HEAD_DIR || dir=$BASE_DIR
  test_env $dir
  say "$TEST at $label ($(<$dir/installed-commit)), $RUNS runs"
  for n in {1..$RUNS}; do
    (cd $dir/clone && bounded 600 $TESTENV $dir/venv/bin/python -m pytest -p no:cacheprovider -q -rA $TEST) \
      > $OUT/$label-$n.txt 2>&1 || true
    info "$label run $n: $(tail -1 $OUT/$label-$n.txt)"
  done
done

say "failures per variant, out of $RUNS runs each"
# `-rA` lists every variant as `PASSED|FAILED|ERROR <id>`.
VARIANTS=($(cat $OUT/head-*.txt $OUT/base-*.txt | sed -E -n 's/^(PASSED|FAILED|ERROR) [^[]*(\[[^]]*\]).*/\2/p' | sort -u))
(( ${#VARIANTS} )) || fail "no variant of $TEST was reported in any run; see head-1.txt"
WORSE=()
for variant in $VARIANTS; do
  typeset -A count=()
  for label in head base; do
    count[$label]=$(cat $OUT/$label-*.txt | grep -F -- "$variant" | grep -c -E '^(FAILED|ERROR) ' || true)
  done
  LINE="$variant: COMMIT ${count[head]} of $RUNS failed, base ${count[base]} of $RUNS failed"
  print -r -- $LINE | tee -a $OUT/counts.txt
  note $LINE
  (( count[head] <= count[base] + 1 )) || WORSE+=("$LINE")
done
if (( ${#WORSE} )); then
  check FAIL "COMMIT fails more than the base plus one: ${(j:; :)WORSE}"
else
  check PASS "no difference between COMMIT and the base: $(tr '\n' ';' < $OUT/counts.txt)"
fi
step_end
