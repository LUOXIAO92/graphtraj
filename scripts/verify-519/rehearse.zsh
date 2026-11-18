#!/bin/zsh
# Task 519 rehearsal of steps.zsh's non-model parts, from an empty scratch directory (as verify-517 did):
#   zsh scripts/verify-519/rehearse.zsh [scratch]      (default: $TMPDIR/rehearse-519; output: rehearsal-output.txt)
# A stub `claude` stands in for the model: the gate answer (init naming graphtraj, its tools and the host plugin), and
# for the A/C Main prompts it runs obs519.py sim (graftling's own ClaudeJsonlCollector) with the step's own marker on
# the scratch project's swarm, then prints SWARM-RESULT/SESSION-READ/MEMBER lines. The production .venv-runtime is
# only imported (python -I -B). Nothing outside the scratch directory is written.
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}
X=${1:-${TMPDIR:-/tmp}/rehearse-519}
rm -rf $X; mkdir -p $X/stub $X/projects/-private-tmp-standby-519-project
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
cat > $X/stub/claude <<EOF
#!/bin/zsh
# rehearsal stub
[[ \$1 == --version ]] && { print '0.0.0 (rehearsal stub)'; exit 0; }
input=\$(cat)
P=$X/base/project; OBS=$SD/obs519.py; PY=$H/.venv-runtime/bin/python
init='{"type":"system","subtype":"init","model":"claude-opus-5-5","mcp_servers":[{"name":"graphtraj","status":"connected"}],"tools":["mcp__graphtraj__agents","mcp__graphtraj__tasks"],"plugins":[{"name":"graphtraj-claude-host"}],"plugin_warnings":[]}'
print -r -- \$init
marker=\$(print -r -- \$input | grep -oE 'STANDBY519-[0-9]+-R[12]' | tail -1)
if [[ \$input == *'execute swarm'* ]]; then
  \$PY -I -B \$OBS sim \$P/.graphtraj first \$marker >/dev/null
  ln -sf \$P/.graphtraj/native.jsonl $X/projects/-private-tmp-standby-519-project/s.jsonl
  text="SWARM-RESULT {stub}\nSESSION-READ-A {stub: hits 1}\nMEMBER agent-stub 1-standby_probe-claude_member@claude_member s"
elif [[ \$input == *'feature\\": \\"resume'* || \$input == *'"resume"'* ]]; then
  \$PY -I -B \$OBS sim \$P/.graphtraj resume \$marker >/dev/null
  text="RESUME-RESULT {stub}\nSESSION-READ-C1 {stub}\nSESSION-READ-C2 {stub}"
elif [[ \$input == *PROBE-519* ]]; then text="PROBE-519 claude-opus-5-5 logged in\nFILES: NONE"
else text="READY-519 claude-opus-5-5"; fi
print -r -- "{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false,\"result\":\"\$text\"}"
EOF
chmod +x $X/stub/claude
export VERIFY519_BASE=$X/base VERIFY519_OUT=$X/out VERIFY519_STUB=$X/stub VERIFY519_PROJECTS=$X/projects VERIFY519_WAIT=2
run() { print "\n######## rehearsal: zsh steps.zsh $*"; zsh $SD/steps.zsh "$@"; print "######## rc=$?"; }
{
  print "rehearsal scratch: $X (stub claude; VERIFY519_BASE/OUT/STUB/PROJECTS/WAIT=2)"
  run
  run B
  run S
  run P
  run Tu
  run A
  run B
  run C
} 2>&1 | sed "s|$X|<scratch>|g"
