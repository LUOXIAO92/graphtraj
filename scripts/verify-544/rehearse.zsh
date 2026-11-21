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
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
