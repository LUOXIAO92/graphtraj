#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 20-dsh-plugin: install/dsh.md as written, with the renamed package graftling-dsh.
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/20-dsh-plugin.zsh
#
# dsh plugin add (DSH runs pnpm in the profile directory) into a scratch DSH_HOME, so the user's DSH profiles
# are neither read nor changed; then the start line without any --patch for the plugin: a DSH main Session
# whose agents tool creates a Claude child, waits for it and reads its status; then --session-id continues.
# 392's step 65, which said CANNOT only because pnpm was missing.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
# Homebrew's pnpm 12.16.1 is a file without a shebang: zsh runs it, Node's spawn (DSH's) gets ENOEXEC.
# A shim the user made (leader.md update 3, M1) goes before common.zsh's /opt/homebrew/bin, for this step only.
PNPM_SHIM=$AG/pnpm-shim
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
step_begin 20-dsh-plugin 10 none 'dsh plugin add exits 0 and lists graftling-dsh; the DSH Session started without a plugin patch creates a Claude child that completes, and status shows it'
prepare_checks
AGENTS_VENV=$VENV
export DSH_HOME=$WORK/dsh-home
mkdir -p $DSH_HOME $WORK/project $WORK/data
cd $WORK/project
git init -q .
if [[ -x $PNPM_SHIM/pnpm ]]; then
  note "pnpm shim: $PNPM_SHIM is first on PATH for this step"
else
  note "pnpm shim: $PNPM_SHIM/pnpm is not there; the pnpm on PATH is used as it is"
fi
PNPM=$(command -v pnpm) || fail "pnpm is not on PATH ($PATH); dsh plugin add needs it"
note "pnpm: $PNPM $(pnpm --version 2>&1 | tail -1); dsh: $DSH $($DSH --version 2>&1 | tail -1)"
# DSH starts pnpm through Node's child_process: the same spawn, with this step's PATH, must work.
NODE=$(command -v node) || fail "node is not on PATH ($PATH); DSH needs it"
SPAWN=$($NODE -e 'const r = require("child_process").spawnSync("pnpm", ["--version"], {encoding: "utf8"});
console.log(r.error ? "ERROR " + r.error.code : r.status === 0 ? "OK " + r.stdout.trim() : "EXIT " + r.status + " " + (r.stderr || "").trim().split("\n").pop())' 2>&1 || true)
print -r -- "$SPAWN" > $OUT/node-spawn-pnpm.txt
if [[ $SPAWN == OK\ * ]]; then
  check PASS "Node can spawn the pnpm DSH will use: ${SPAWN#OK } ($PNPM)"
else
  check FAIL "Node cannot spawn the pnpm DSH will use ($PNPM): $SPAWN"
  info "Fallback: create the shim with leader.md update 3's M1 command, then run this step again:"
  info "  zsh -c 'D=$PNPM_SHIM; mkdir -p \$D; printf \"#!/bin/sh\\nexec /opt/homebrew/bin/node /opt/homebrew/lib/node_modules/pnpm/bin/pnpm.mjs \\\"\\\$@\\\"\\n\" > \$D/pnpm; chmod +x \$D/pnpm; cat \$D/pnpm'"
  fail "Node's spawn of pnpm gives ${SPAWN:-nothing}; dsh plugin add would fail the same way (spawn ENOEXEC). Create $PNPM_SHIM/pnpm (leader.md update 3, M1) and run: zsh $HERE/20-dsh-plugin.zsh"
fi

say "dsh.md: dsh plugin add, as written"
DSH_PACKAGE="$("$AGENTS_VENV/bin/python" -c 'import graftling.dsh, pathlib; print(pathlib.Path(graftling.dsh.__file__).parent)')"
info "DSH_PACKAGE=$DSH_PACKAGE"
CODE=0
dsh plugin --profile headless add "$DSH_PACKAGE" > $OUT/plugin-add.txt 2>&1 || CODE=$?
cat $OUT/plugin-add.txt
judge $CODE "dsh plugin --profile headless add \$DSH_PACKAGE: exit $CODE; $(tail -1 $OUT/plugin-add.txt | cut -c1-200)"
(( CODE == 0 )) || fail "dsh plugin add failed; its output is in plugin-add.txt. Nothing else in this step can show the plugin route"
CODE=0
dsh plugin --profile headless list --depth 0 > $OUT/plugin-list.txt 2>&1 || CODE=$?
grep -q 'graftling-dsh' $OUT/plugin-list.txt && check PASS "dsh plugin --profile headless list shows graftling-dsh: $(grep -m1 graftling-dsh $OUT/plugin-list.txt | cut -c1-200)" \
  || check FAIL "dsh plugin --profile headless list (exit $CODE) does not show graftling-dsh; see plugin-list.txt"
CODE=0
dsh plugin --profile headless add "$DSH_PACKAGE" > $OUT/plugin-add-again.txt 2>&1 || CODE=$?
judge $CODE "dsh plugin add over an earlier add: exit $CODE; $(tail -1 $OUT/plugin-add-again.txt | cut -c1-200)"

say "dsh.md: the start line, the plugin from the profile and no plugin patch"
print -r -- "{\"root\": \"$WORK/data\", \"claude\": {\"model\": \"$CLAUDE_MODEL\"}}" > $WORK/dsh-host.json
PROMPT="Use the agents tool, not DSH's own subagents, to create a Claude child that answers one word, and wait for it with timeout_seconds 240 before ending the task. Then read its status. Reply with one line."
ROUTE=()
# `final_of <file>`: the final event's kind and session id.
final_of() {
  $VENV/bin/python -I -c 'import json, sys
for line in open(sys.argv[1]):
    try: e = json.loads(line)
    except ValueError: continue
    if e.get("type") == "final": print((e.get("reason") or {}).get("kind"), e.get("sessionId"))' $1 | tail -1 || true
}
CODE=0
bounded 420 env GRAFTLING_PYTHON="$AGENTS_VENV/bin/python" GRAFTLING_DSH_CONFIG=$WORK/dsh-host.json \
  env -u DEEPSEEK_BASE_URL dsh --profile headless --json "$PROMPT" </dev/null > $OUT/start-as-written.jsonl 2> $OUT/start-as-written.stderr || CODE=$?
FINAL=$(final_of $OUT/start-as-written.jsonl)
note "start as written: exit $CODE, final: $FINAL"
if [[ $FINAL != completed* ]]; then
  # The scratch home has no DSH login. dsh.md's prerequisite is a login or an API key; this names the key.
  note "the start line on a home with no login did not complete; next, the key named in a patch, as 392's real runs did (no plugin patch)"
  print -rl -- '- id: llm-deepseek' '  config:' '    apiKeyEnv: DEEPSEEK_API_KEY' > $WORK/key.patch.yml
  ROUTE=(--patch $WORK/key.patch.yml)
  CODE=0
  bounded 420 env GRAFTLING_PYTHON="$AGENTS_VENV/bin/python" GRAFTLING_DSH_CONFIG=$WORK/dsh-host.json \
    env -u DEEPSEEK_BASE_URL dsh --profile headless $ROUTE --json "$PROMPT" </dev/null > $OUT/start-with-key.jsonl 2> $OUT/start-with-key.stderr || CODE=$?
  cp $OUT/start-with-key.jsonl $OUT/start.jsonl
else
  cp $OUT/start-as-written.jsonl $OUT/start.jsonl
fi
# The public agents results in the Session's tool results: create, wait, status.
$VENV/bin/python -I - $OUT/start.jsonl > $OUT/start-results.txt 2>&1 <<'PYEOF' || true
import json, sys

def documents(value):
    if isinstance(value, str):
        try:
            value = json.loads(value.removeprefix('Error: '))
        except ValueError:
            return
    if isinstance(value, dict):
        if isinstance(value.get('action'), str) and ('result' in value or 'error' in value):
            yield value
            return
        for item in value.values():
            yield from documents(item)
    elif isinstance(value, list):
        for item in value:
            yield from documents(item)

session = None
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    session = event.get('sessionId') or session
    if event.get('type') != 'tool_result':
        continue
    for d in documents(event):
        r = d.get('result') or {}
        last = r.get('last_result') or {}
        print(d.get('action'), d.get('agent') or r.get('agent') or '-', r.get('runtime') or '-',
              r.get('state') or '-', last.get('outcome') or '-', (d.get('error') or {}).get('code') or '-')
print('session', session)
PYEOF
cat $OUT/start-results.txt
SESSION=$(sed -n 's/^session //p' $OUT/start-results.txt | tail -1)
[[ $SESSION == None ]] && SESSION=
judge $CODE "a DSH main Session ran: exit $CODE, session ${SESSION:-none}"
CHILD=$(awk '$1 == "create" && $2 != "-" && $3 == "claude" {print $2; exit}' $OUT/start-results.txt)
[[ -n $CHILD ]] && check PASS "the agents tool from the plugin created a Claude child: agent $CHILD" \
  || check FAIL "no successful create of a Claude child in the Session; see start-results.txt and start.jsonl"
if [[ -n $CHILD ]]; then
  awk -v a=$CHILD '($1 == "wait" || $1 == "status") && $2 == a && $5 == "completed" {f=1} END {exit !f}' $OUT/start-results.txt \
    && check PASS "the child $CHILD completed: wait or status shows last_result outcome completed" \
    || check FAIL "no wait or status shows the child $CHILD completed; see start-results.txt"
  awk -v a=$CHILD '$1 == "status" && $2 == a && $4 == "standby" {f=1} END {exit !f}' $OUT/start-results.txt \
    && check PASS "status shows the child $CHILD standby" || note "no status line shows the child $CHILD standby; see start-results.txt"
fi
CONTINUE=(env GRAFTLING_PYTHON="$AGENTS_VENV/bin/python" GRAFTLING_DSH_CONFIG=$WORK/dsh-host.json DSH_HOME=$DSH_HOME
          env -u DEEPSEEK_BASE_URL dsh --profile headless $ROUTE --session-id "$SESSION")
if [[ -n $SESSION ]]; then
  CODE=0
  (cd $WORK/project && bounded 300 $CONTINUE --json "Reply with one word: next." </dev/null > $OUT/continue.jsonl 2> $OUT/continue.stderr) || CODE=$?
  FINAL=$(final_of $OUT/continue.jsonl)
  [[ $CODE == 0 && $FINAL == completed* ]] && check PASS "--session-id $SESSION continues the Session: exit $CODE, final $FINAL" \
    || check FAIL "--session-id $SESSION: exit $CODE, final ${FINAL:-none}"
  FOLLOW=${(j: :)${(q-)CONTINUE}}
  print -r -- "To look at this Session yourself (not needed for the result): cd $WORK/project && $FOLLOW 'Reply with one word: next.'" > $OUT/follow-up.txt
  cat $OUT/follow-up.txt
fi
old_names
step_end
