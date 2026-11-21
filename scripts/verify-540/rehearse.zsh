#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: fake Harness root, stub `codex`, real builds from the real BEFORE
# and AFTER commits pinned in steps.zsh, the real child-role resolution, and the REAL hook commands that
# Vb/V write into .codex/hooks.json, fired as Codex fires it: once for the Main's rollout (source cli) and once for
# a child's rollout (source exec) whose environment carries GRAFTLING_MEMBER_RUN, as graftling's Codex child owner
# sets it. Without a live Codex app-server the hook cannot finish a Main claim (it verifies the thread natively), so
# the rehearsal checks what the hook does with the marked child: BEFORE it goes on to Main association (and fails at
# the missing app-server), AFTER it is skipped ({}) before any native contact. continuity.jsonl, the child control
# record and the Main's notice record are stand-ins written here in the shape of 535's real evidence.
# Never touches production, ~/.codex or the Codex install.
#   zsh rehearse.zsh <empty or absent directory>      (VERIFY540_BEFORE_ONLY=1 stops after the BEFORE half)
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
mkdir -p $F/H/.graphtraj $F/stub $F/st $F/codex-home/sessions/2026/11/21 $F/home/.graphtraj
cat > $F/home/.graphtraj/connections.yml <<'EOF'
version: 1
runtimes:
  codex:
    runtime: codex
    providers:
      openai:
        models:
          gpt-6-astra: {id: gpt-6-astra, source: native, supported_efforts: [low, medium, high, xhigh]}
          gpt-6-luna: {id: gpt-6-luna, source: native, supported_efforts: [low, medium, high, xhigh]}
EOF
export HOME=$F/home
export VERIFY540_H=$F/H VERIFY540_BASE=$F/base VERIFY540_ST=$F/st VERIFY540_VPROJECT=$F/vproject \
  VERIFY540_RT=$REALH/.venv-runtime VERIFY540_WT=${SD:h:h} VERIFY540_CODEX=$F/stub/codex \
  VERIFY540_CODEX_HOME=$F/codex-home VERIFY540_GLDEV=$REALH/.graphtraj/core/worktrees/graftling-dev
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.169.0 (stub)" ;;
  login) print "Logged in using ChatGPT (stub)" ;;
  exec) cat > /dev/null; print "model: gpt-6-luna"; print "CODEX-540-OK gpt-6-luna" ;;
  *) print "stub codex: $*" ;;
esac
EOF
chmod +x $F/stub/codex
S() { zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
check() { local name=$1; shift; if "$@"; then print "REHEARSAL PASS $name"; ((pass++)); else print "REHEARSAL FAIL $name"; ((fail++)); fi; }
R=$F/codex-home/sessions/2026/11/21
# Fire the SessionStart command of the project's hooks.json, as Codex does, for one rollout ($1 session, $2 source,
# $3 'child' = with the marker graftling's Codex child owner puts in the child's environment).
fire() {
  local rollout=$R/rollout-$1.jsonl
  print -r -- "{\"type\": \"session_meta\", \"payload\": {\"id\": \"$1\", \"source\": \"$2\", \"cwd\": \"$F/vproject\"}}" > $rollout
  local cmd event="{\"hook_event_name\": \"SessionStart\", \"source\": \"startup\", \"cwd\": \"$F/vproject\", \"session_id\": \"$1\", \"transcript_path\": \"$rollout\"}"
  for cmd in ${(f)"$($F/base/active/venv/bin/python -I -c 'import json, sys; [print(x["command"]) for x in json.load(open(sys.argv[1]))["hooks"]["SessionStart"][0]["hooks"]]' $F/vproject/.codex/hooks.json)"}; do
    if [[ $3 == child ]]; then
      (cd $F/vproject && print -r -- $event | env CODEX_HOME=$F/codex-home GRAFTLING_MEMBER_RUN=58c9791461b54a149d5f290b05e9f675 ${(z)cmd})
    else
      # A user-started Main has no marker, even when this rehearsal runs inside an Agent that carries one.
      (cd $F/vproject && print -r -- $event | env -u GRAFTLING_MEMBER_RUN CODEX_HOME=$F/codex-home ${(z)cmd})
    fi
  done
}
# Stand-in for the agents control record of the child (the shape of 535's real record) and, for AFTER, the Main's
# pushed notice record. $1 main session, $2 child session, $3 notification, $4 'notice' to append the notice.
standins() {
  local child=$(cat $F/st/540/child-name) start=$(cat $F/st/540/V*.start(om[1]))
  mkdir -p $F/vproject/.graphtraj/swarm/control/agents $F/vproject/.graphtraj/runner/main-sessions
  $F/base/active/venv/bin/python -I -c 'import json, sys
main, child_session, notification, name, path, rollout, notice, continuity, start = sys.argv[1:10]
claims = [{"at": float(start) + 1, "entry": "codex:SessionStart:startup", "runtime": "codex", "session": main, "previous": None}]
if notice != "notice":  # BEFORE: the child claim of 535 continuity.jsonl line 2
    claims.append({"at": float(start) + 2, "entry": "codex:SessionStart:startup", "runtime": "codex", "session": child_session,
                   "previous": {"runtime": "codex", "session": main}})
open(continuity, "w").write("".join(json.dumps(c) + "\n" for c in claims))
error = None if notification == "pushed" else {"code": "RUNTIME_RPC_ERROR", "message": f"thread not found: {child_session}"}
json.dump({"agent": "agent-540rehearsal", "name": name, "runtime": "codex", "creator": {"host": "graphtraj-gateway", "session": main},
           "selection": {"model": "gpt-6-luna"}, "session": child_session,
           "executions": [{"id": "e" * 32, "outcome": "completed", "notification": notification, "notification_error": error}]}, open(path, "w"))
if notice == "notice":
    open(rollout, "a").write(json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "name": "graftling",
        "output": f"[Graftling notice from {name} · completed · execution " + "e" * 32 + "]\n\nCHILD-540-OK"}}) + "\n")' \
    $1 $2 $3 $child $F/vproject/.graphtraj/swarm/control/agents/agent-540rehearsal.json $R/rollout-$1.jsonl ${4:-none} \
    $F/vproject/.graphtraj/runner/main-sessions/continuity.jsonl $start
}
print "== rehearsal in $F (stub codex; real BEFORE and AFTER commits pinned in steps.zsh)"
S 00 > $F/00.out 2>&1; check "00: isolation OK, codex exec answer names gpt-6-luna" sh -c "grep -q 'isolation: OK' $F/00.out && grep -q 'header model: gpt-6-luna | answer: CODEX-540-OK gpt-6-luna' $F/00.out && grep -q 'steps.zsh B0' $F/00.out"
S B0 > $F/B0.out 2>&1; check "B0: BEFORE wheels + venv from f754d3a9 and 6794ce02" sh -c "grep -q 'venv pip check rc=0' $F/B0.out && grep -q '^GraphTraj f754d3a9' $F/B0.out && grep -q '^graftling 6794ce02' $F/B0.out"
grep -E '^GraphTraj |^graftling ' $F/B0.out
S T > $F/T.out 2>&1; check "T: one dialog (directory trust), /exit" sh -c "grep -q 'Do you trust the contents of this directory' $F/T.out && grep -q '/exit' $F/T.out"
S Vb > $F/Vb.out 2>&1; check "Vb: hooks via active link, role codex = gpt-6-luna resolves, USER command + prompt (runtime codex), at most one dialog" sh -c "grep -q 'CHECK 540 child role resolves: PASS (runtime codex, model gpt-6-luna, reasoning_effort medium' $F/Vb.out && grep -q 'base/active/venv/bin/graphtraj-mcp' $F/Vb.out && grep -q 'cd $F/vproject && codex -m gpt-6-luna' $F/Vb.out && grep -q 'runtime codex, name n540' $F/Vb.out && grep -q '最多一个' $F/Vb.out"
cp $F/vproject/.codex/hooks.json $F/hooks-vb.json
check "Vb hooks.json: exactly GraphTraj's SessionStart + SessionEnd stop_hook via the active venv" \
  $F/base/active/venv/bin/python -I -c 'import json, sys
h = json.load(open(sys.argv[1]))["hooks"]
cmds = {e: [x["command"] for g in h[e] for x in g["hooks"]] for e in h}
print("hooks.json:", cmds)
sys.exit(0 if sorted(h) == ["SessionEnd", "SessionStart"] and all(c == [sys.argv[2] + "/venv/bin/python -m graphtraj.runtimes.codex.stop_hook"] for c in cmds.values()) else 1)' $F/vproject/.codex/hooks.json $F/base/active
MAIN=01a1f989-df2b-7792-956b-e0329f5daf4f CHILDS=01a1f98a-5102-7340-9bc5-b432b0995473
fire $MAIN cli main > $F/fire-b-main.out 2>&1; fire $CHILDS exec child > $F/fire-b-child.out 2>&1
check "BEFORE hook: the marked exec child is NOT skipped; it goes on to Main association (stops only at the missing app-server)" \
  sh -c "grep -q 'app-server-control.sock' $F/fire-b-child.out && ! grep -qx '{}' $F/fire-b-child.out"
standins $MAIN $CHILDS unavailable
S C > $F/C-before.out 2>&1
check "C (BEFORE) on stand-ins shaped as 535's evidence (child claim, thread not found, no notice) -> VERDICT REPRODUCED; copies in st/before" sh -c "grep -q 'VERDICT 540: REPRODUCED' $F/C-before.out && [ -f $F/st/before/continuity.jsonl ] && [ -f $F/st/before/summary.json ] && [ -f $F/st/before/agent-540rehearsal.json ]"
sed -n '/^continuity/,/^VERDICT/p' $F/C-before.out
if [[ -z ${VERIFY540_BEFORE_ONLY:-} ]]; then
  S B > $F/B.out 2>&1; check "B: exact 540 diff, AFTER wheels + venv" sh -c "grep -q 'CHECK 540 GraphTraj product diff is exactly the 540 files: PASS' $F/B.out && grep -q 'venv pip check rc=0' $F/B.out"
  grep -E '^GraphTraj |^graftling |files changed' $F/B.out
  S V > $F/V.out 2>&1; check "V: active -> cand, role PASS, main-sessions cleared, at most one dialog (hook review)" sh -c "grep -q 'active -> $F/base/cand' $F/V.out && grep -q 'CHECK 540 child role resolves: PASS' $F/V.out && [ ! -e $F/vproject/.graphtraj/runner/main-sessions ] && grep -q '比 Vb 多了 540 探针钩子' $F/V.out"
  check "V hooks.json = Vb's + exactly one probe540.py command appended to SessionStart" \
    $F/base/active/venv/bin/python -I -c 'import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
extra = b["hooks"]["SessionStart"][0]["hooks"].pop()
print("probe hook:", extra["command"])
sys.exit(0 if a == b and "probe540.py" in extra["command"] else 1)' $F/hooks-vb.json $F/vproject/.codex/hooks.json
  rm -f $R/rollout-*.jsonl
  fire $MAIN cli main > $F/fire-a-main.out 2>&1; fire $CHILDS exec child > $F/fire-a-child.out 2>&1
  check "AFTER hooks: the Main still goes on to Main association; the marked child is skipped ({}) before any native contact" \
    sh -c "grep -q 'app-server-control.sock' $F/fire-a-main.out && grep -qx '{}' $F/fire-a-child.out"
  standins $MAIN $CHILDS pushed notice
  S C > $F/C-after.out 2>&1
  check "C (AFTER): probe saw the child hook fire WITH the marker and the Main's without; no child claim, no notification_error, notice in the Main rollout -> VERDICT FIXED" \
    sh -c "grep -q 'CHECK 540 the child SessionStart hook fired and saw GRAFTLING_MEMBER_RUN: PASS' $F/C-after.out && grep -q 'CHECK 540 the Main SessionStart hook fired without GRAFTLING_MEMBER_RUN: PASS' $F/C-after.out && grep -q 'VERDICT 540: FIXED' $F/C-after.out && [ -f $F/st/after/summary.json ] && [ -f $F/st/after/graphtraj-540-probe.jsonl ]"
  sed -n '/^continuity/,/^VERDICT/p' $F/C-after.out
  VERIFY540_TESTS="tests/test_main_finalize.py::test_agents_launched_codex_child_never_continues_main tests/test_external_session_entry.py::test_pi_and_dsh_agents_children_never_continue_main" S G > $F/G.out 2>&1
  S GR > $F/GR.out 2>&1
  check "G: TMPDIR stated outside the Harness; the limited real-fixture run exit=0" sh -c "grep -q 'TMPDIR=\${TMPDIR:-/tmp} ->' $F/G.out && grep -q '^exit=0' $F/st/540/G-*/graphtraj.txt"
  grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/st/540/G-*/graphtraj.txt; grep -E 'known|NEW|no FAILED' $F/GR.out
fi
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
