#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: stub `codex`, fake Codex sessions dir, the REAL probe544.py through
# JSON-RPC initialize + tools/call (inside P), Pr on fake rollouts (structuredContent -> PASS, content body -> FAIL,
# a newer rollout of another cwd ignored). Never touches production, ~/.codex or the Codex install.
#   zsh rehearse.zsh <empty or absent directory>
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
mkdir -p $F/stub $F/codex-home/sessions/2026/11/21 $F/H
export VERIFY544_H=$F/H VERIFY544_BASE=$F/base VERIFY544_W=$F/w VERIFY544_VPROJECT=$F/vproject \
  VERIFY544_WT=${SD:h:h} VERIFY544_CODEX=$F/stub/codex VERIFY544_CODEX_HOME=$F/codex-home
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.171.0 (stub)" ;;
  login) print "Logged in using ChatGPT (stub)" ;;
  exec) cat > /dev/null; print "model: gpt-6-luna"; print "CODEX-544-OK gpt-6-luna" ;;
  *) print "stub codex: $*" ;;
esac
EOF
chmod +x $F/stub/codex
S() { zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
check() { local name=$1; shift; if "$@"; then print "REHEARSAL PASS $name"; ((pass++)); else print "REHEARSAL FAIL $name"; ((fail++)); fi; }
print "== rehearsal in $F (stub codex)"
S 00 > $F/00.out 2>&1; check "00: isolation OK, codex exec answer names gpt-6-luna, next = T" sh -c "grep -q 'isolation: OK' $F/00.out && grep -q 'header model: gpt-6-luna | answer: CODEX-544-OK gpt-6-luna' $F/00.out && grep -q 'steps.zsh T' $F/00.out"
grep -E 'codex:|codex login|header model|isolation' $F/00.out
S T > $F/T.out 2>&1; check "T: one dialog (folder trust), /exit, next = P" sh -c "grep -q 'Do you trust the contents of this directory' $F/T.out && grep -q '/exit' $F/T.out && grep -q 'steps.zsh P' $F/T.out"
S P > $F/P.out 2>&1; check "P: config.toml has ONLY the probe server, real probe544.py self-test PASS, USER command, the 543 prompt, screenshot paths, next = Pr" sh -c "
  [ \$(grep -c '^\[mcp_servers\.' $F/vproject/.codex/config.toml) -eq 1 ] && grep -q '^\[mcp_servers.probe\]' $F/vproject/.codex/config.toml && [ ! -e $F/vproject/.codex/hooks.json ] \
  && grep -q 'CHECK probe server self-test: PASS' $F/P.out && grep -q 'cd $F/vproject && codex -m gpt-6-luna' $F/P.out \
  && grep -qF 'call probe.send_note with to=member-x and a 5-line message including **bold**, then tell me exactly what the tool returned' $F/P.out \
  && grep -q '$F/w/probe-collapsed.png' $F/P.out && grep -q '$F/w/probe-expanded.png' $F/P.out && grep -q 'steps.zsh Pr' $F/P.out"
sed -n '/wrote /,/CHECK probe/p' $F/P.out
# Fake rollouts after P's stamp, in Codex's record shapes (session_meta, response_item function_call/_output, message).
R=$F/codex-home/sessions/2026/11/21
rollout() {  # $1 file $2 cwd $3 = sc|body
  /Users/luoxiao/miniconda3/bin/python3.13 -I -c 'import json, sys
out = json.dumps({"ok": True, "marker": "PROBE-SC-544"}) if sys.argv[3] == "sc" else "## Probe note PROBE-BODY-544\nstatus: sent"
rows = [{"type": "session_meta", "payload": {"id": "s-544", "cwd": sys.argv[2]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "mcp__probe__send_note", "call_id": "c1", "arguments": "{\"to\":\"member-x\",\"message\":\"l1\\nl2\"}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": out}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "The tool returned " + out}]}}]
open(sys.argv[1], "w").write("".join(json.dumps(r) + "\n" for r in rows))' $1 $2 $3
}
sleep 1
rollout $R/rollout-a-probe.jsonl $F/vproject sc; sleep 1; rollout $R/rollout-b-other.jsonl $F/elsewhere body
S Pr > $F/Pr-sc.out 2>&1; check "Pr: picks the project's rollout (not the newer other-cwd one); structuredContent -> PASS" sh -c "grep -q 'rollout-a-probe.jsonl' $F/Pr-sc.out && grep -q 'CHECK 544 probe model input: PASS' $F/Pr-sc.out"
sed -n '/^rollout/,$p' $F/Pr-sc.out
rollout $R/rollout-a-probe.jsonl $F/vproject body
S Pr > $F/Pr-body.out 2>&1; check "Pr: content body in the model input -> FAIL" grep -q 'CHECK 544 probe model input: FAIL' $F/Pr-body.out
[[ ${2:-} == A ]] && { print "== rehearsal (phase A only): $pass passed, $fail failed"; exit $(( fail > 0 )); }

# ---- Phase B: a scratch clone of the Worktree HEAD (plus, before the product commit, its uncommitted 544 files
# committed in the clone only), the real graftling dev, production's deps (read only), a stand-in user catalog.
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery; WTR=${SD:h:h}
git clone -q --no-hardlinks $WTR $F/wt && git -C $F/wt checkout -q $(git -C $WTR rev-parse HEAD) || { print "REHEARSAL FAIL clone"; exit 1; }
for f in src/graphtraj/interfaces/mcp.py src/graphtraj/runtimes/codex/display_hook.py tests/test_codex_agent_display.py tests/test_codex_agents_card_544.py scripts/verify-544; do
  rm -rf $F/wt/$f; cp -Rp $WTR/$f $F/wt/$f; done
if [[ -n $(git -C $F/wt status --porcelain) ]]; then
  git -C $F/wt add -A && git -C $F/wt -c user.name=rehearsal -c user.email=rehearsal@invalid commit -qm "rehearsal only: uncommitted 544 files"
  print "rehearsal clone: uncommitted 544 files committed in the clone only ($(git -C $F/wt rev-parse --short HEAD))"
fi
mkdir -p $F/home/.graphtraj
print -r -- "version: 1
runtimes:
  claude:
    runtime: claude
    providers:
      anthropic:
        models:
          opus-5_5: {id: claude-opus-5-5, source: native, supported_efforts: [high, max]}" > $F/home/.graphtraj/connections.yml
export HOME=$F/home VERIFY544_WT=$F/wt VERIFY544_RT=$REALH/.venv-runtime VERIFY544_GLDEV=$REALH/.graphtraj/core/worktrees/graftling-dev
S() { zsh $F/wt/scripts/verify-544/steps.zsh "$@"; }
S B > $F/B.out 2>&1; check "B: exact 544 diff vs f754d3a9, candidate wheels + venv, the candidate has _agents_card" sh -c "grep -q 'CHECK 544 product diff is exactly the 544 files: PASS' $F/B.out && grep -q 'venv pip check rc=0' $F/B.out && grep -q 'has _agents_card: True' $F/B.out && grep -q '^graftling 6794ce02' $F/B.out"
grep -E '^GraphTraj |^graftling |files changed|pip check' $F/B.out
S V > $F/V.out 2>&1; check "V: config.toml = graphtraj only (probe gone), hooks.json SessionStart+PostToolUse+Stop, role PASS, prompt (create, wait, send), screenshot paths, next = Vr" sh -c "
  [ \$(grep -c '^\[mcp_servers\.' $F/vproject/.codex/config.toml) -eq 1 ] && grep -q '^\[mcp_servers.graphtraj\]' $F/vproject/.codex/config.toml && grep -q 'base/active/venv/bin/graphtraj-mcp' $F/vproject/.codex/config.toml \
  && grep -q 'display_hook' $F/vproject/.codex/hooks.json && grep -q 'stop_hook' $F/vproject/.codex/hooks.json \
  && grep -q 'CHECK 535 child role resolves: PASS (runtime claude' $F/V.out && grep -q 'isolation: OK' $F/V.out \
  && grep -q \"name \$(cat $F/w/child-name)\" $F/w/V-prompt.txt && grep -q 'agents wait' $F/w/V-prompt.txt && ! grep -q 'agents →' $F/w/V-prompt.txt \
  && grep -q '$F/w/after-collapsed.png' $F/V.out && grep -q '$F/w/after-expanded.png' $F/V.out && grep -q 'steps.zsh Vr' $F/V.out"
grep -E 'CHECK 535|isolation|child name' $F/V.out
# Vr on CODE-MODE rollouts (the shape of the 544 probe rollout: custom_tool_call 'exec' -> item_completed McpToolCall
# -> custom_tool_call_output) carrying what the candidate's REAL _tool_call_response returns for a Codex create;
# 'body' = the content holds the message (the withdrawn draft), 'hook' = YAML content + the 535 hook copy.
CHILD=$(cat $F/w/child-name); MAIN=01a1f989-main-0000-0000-000000000544
mkdir -p $F/vproject/.graphtraj/runner/main-sessions
print -r -- "{\"at\": $(( $(cat $F/w/V.start) + 1 )), \"entry\": \"codex:SessionStart:startup\", \"runtime\": \"codex\", \"session\": \"$MAIN\"}" > $F/vproject/.graphtraj/runner/main-sessions/continuity.jsonl
vrollout() {  # $1 file, $2 = card|body|hook
  (cd $F && $F/base/active/venv/bin/python -I -c 'import json, sys
from contextlib import nullcontext
from types import SimpleNamespace
import graftling, yaml
from graphtraj.interfaces import mcp
child, path, mode, main, cwd = sys.argv[1:6]
document = {"action": "create", "agent": "agent-1a2b", "result": {"name": child, "execution_id": "e" * 32}}
mcp._caller_notices = lambda params: nullcontext(None)
graftling.handle_request = lambda arguments, dispatch: SimpleNamespace(document=document, failed=False)
body = "## Task 544 display check\n\nReply **without using any tool**, in Markdown."
given = {"runtime": "claude", "name": child, "instruction": body}
arguments = {"action": "execute", "feature": "create", "arguments": given}
result = mcp._tool_call_response(1, {"name": "agents", "arguments": arguments, "_meta": {"threadId": main}})["result"]
if mode == "body":
    result["content"][0]["text"] = body + "\n" + result["content"][0]["text"]
elif mode == "hook":
    result["content"][0]["text"] = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
script = "const r = await tools.mcp__graphtraj__agents(" + json.dumps(arguments) + ");\ntext(JSON.stringify(r));\n"
out = [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"},
       {"type": "input_text", "text": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}]
rows = [{"type": "session_meta", "payload": {"id": main, "cwd": cwd}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "status": "completed", "call_id": "c1", "name": "exec", "input": script}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "McpToolCall", "id": "exec-1", "server": "graphtraj", "tool": "agents", "arguments": arguments, "status": "completed", "result": result}}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": out}}]
if mode == "hook":
    rows.append({"type": "event_msg", "payload": {"type": "hook_output", "systemMessage": f"agents → {child}\n\n{body}"}})
open(path, "w").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))' $CHILD $1 $2 $MAIN $F/vproject)
}
vrollout $R/rollout-main-card.jsonl card
S Vr > $F/Vr-card.out 2>&1; check "Vr (code mode): the candidate's real Codex card -> PASS (no body, recipient last, structuredContent complete, no hook copy, sizes a/b/c printed)" sh -c "grep -q 'CHECK 544 rollout: PASS' $F/Vr-card.out && grep -q 'DERIVED, not observed' $F/Vr-card.out && grep -q 'calls mcp__graphtraj__agents: True' $F/Vr-card.out"
sed -n '/^Main session/,$p' $F/Vr-card.out
vrollout $R/rollout-main-card.jsonl body
S Vr > $F/Vr-body.out 2>&1; check "Vr (code mode): content holding the message body -> FAIL" sh -c "grep -q 'CHECK content lacks the message body: FAIL' $F/Vr-body.out && grep -q 'CHECK 544 rollout: FAIL' $F/Vr-body.out"
vrollout $R/rollout-main-card.jsonl hook
S Vr > $F/Vr-hook.out 2>&1; check "Vr (code mode): YAML content + 535 hook copy -> FAIL" sh -c "grep -q 'no 535 hook copy.*FAIL' $F/Vr-hook.out && grep -q 'CHECK 544 rollout: FAIL' $F/Vr-hook.out"
grep CHECK $F/Vr-body.out $F/Vr-hook.out
# Parser self-test on the REAL probe rollout (read only; sizes only, no verdict).
PROBE=$REALH/.graphtraj/core/state/tasks/544-codex-sent-message-collapsible-card/realhost/main-raw/probe-rollout.jsonl
/Users/luoxiao/miniconda3/bin/python3.13 -I $F/wt/scripts/verify-544/vr544.py --selftest $PROBE > $F/Vs.out 2>&1
check "Vr parser self-test on the real probe rollout: one McpToolCall probe.send_note via exec, sizes a/b/c" sh -c "grep -q 'line 24 probe.send_note (exec exec line 22)' $F/Vs.out && grep -q '(c) custom_tool_call_output the model got 316 B (line 25)' $F/Vs.out"
cat $F/Vs.out
# G's entry with real tests (test_codex_agent_display uses repository fixtures: result_project), then Gt (real focused list) and GR.
VERIFY544_TESTS="tests/test_codex_agents_card_544.py tests/test_codex_agent_display.py" S G > $F/G.out 2>&1
check "G (limited, real tests incl. repo fixtures): exit=0, TMPDIR outside the Harness printed" sh -c "grep -q 'pytest temp: TMPDIR=' $F/G.out && grep -q '^exit=0' \$(cat $F/w/G-latest)/suite.txt"
S Gt > $F/Gt.out 2>&1; S GR > $F/GR.out 2>&1
check "Gt (focused list, real) exit=0; GR classifies no failure in G and Gt" sh -c "grep -q '^exit=0' \$(cat $F/w/Gt-latest)/suite.txt && [ \$(grep -c '(no FAILED/ERROR lines)' $F/GR.out) -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out | head -4; tail -2 $(cat $F/w/G-latest)/suite.txt $(cat $F/w/Gt-latest)/suite.txt; grep -E 'NEW|known' $F/GR.out
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
