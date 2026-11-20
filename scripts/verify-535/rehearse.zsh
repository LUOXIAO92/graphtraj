#!/bin/zsh
# Rehearsal of steps.zsh from an empty directory: fake Harness root (only its roles.yml), stub `codex`, real builds
# from the real baseline and candidate commits, the real child-role resolution, Vr on rollouts holding what GraphTraj's
# REAL send_event writes (fake_push535.py), real pytest through G's entry (limited test lists).
# Never touches production, ~/.codex or the Codex install.
#   zsh rehearse.zsh <empty or absent directory>
set -u
SD=${0:A:h}
F=${1:?usage: zsh rehearse.zsh <empty directory>}; F=${F:A}
[[ -e $F && -n "$(ls -A $F 2>/dev/null)" ]] && { print "STOP: $F is not empty"; exit 1; }
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
FH=$F/H; mkdir -p $FH/.graphtraj $F/stub $F/w $F/codex-home/sessions
# Stand-ins with the REAL layout (correction round 1): production roles use catalog connections and NO preset uses
# gpt-6-luna (astra presets: codex/openai/gpt-6-astra, effort medium; coding_team: codex/deepseek/deepseek-flash);
# the user's catalog ~/.graphtraj/connections.yml (HOME=$F/home here) holds codex/openai/gpt-6-luna.
cat > $FH/.graphtraj/roles.yml <<'EOF'
roles:
  astra_coding_team:
    team_leader: {connection: codex/openai/gpt-6-astra, reasoning_effort: medium, instructions: AGENTS.md}
    engineer: {connection: codex/openai/gpt-6-astra, reasoning_effort: medium, instructions: AGENTS.md, reports: [engineer.md]}
  coding_team:
    engineer: {connection: codex/deepseek/deepseek-flash, reasoning_effort: medium}
  opus_coding_team:
    engineer: {connection: claude/anthropic/opus-5_5, reasoning_effort: high, claude: {permission_mode: auto}}
EOF
mkdir -p $F/home/.graphtraj
catalog() {  # $1 = with|without gpt-6-luna
  print -r -- "version: 1
runtimes:
  codex:
    runtime: codex
    providers:
      openai:
        models:
          gpt-6-astra: {id: gpt-6-astra, source: native, supported_efforts: [low, medium, high, xhigh]}"
  [[ $1 == with ]] && print -r -- "          gpt-6-luna: {id: gpt-6-luna, source: native, supported_efforts: [low, medium, high, xhigh]}"
  print -r -- "  claude:
    runtime: claude
    providers:
      anthropic:
        models:
          opus-5_5: {id: claude-opus-5-5, source: native, supported_efforts: [high, max]}"
}
catalog with > $F/home/.graphtraj/connections.yml
export HOME=$F/home
export VERIFY535_H=$FH VERIFY535_PRODH=$FH VERIFY535_BASE=$F/base VERIFY535_W=$F/w VERIFY535_VPROJECT=$F/vproject \
  VERIFY535_RT=$REALH/.venv-runtime VERIFY535_WT=${SD:h:h} VERIFY535_CODEX=$F/stub/codex \
  VERIFY535_CODEX_HOME=$F/codex-home VERIFY535_GLDEV=$REALH/.graphtraj/core/worktrees/graftling-dev
cat > $F/stub/codex <<'EOF'
#!/bin/zsh
case "$1" in
  --version) print "codex-cli 0.169.0 (stub)" ;;
  login) print "Logged in using ChatGPT (stub)" ;;
  exec) cat > /dev/null; print "model: gpt-6-luna"; print "CODEX-535-OK gpt-6-luna" ;;
  *) print "stub codex: $*" ;;
esac
EOF
chmod +x $F/stub/codex
S() { zsh $SD/steps.zsh "$@"; }
pass=0 fail=0
check() { local name=$1; shift; if "$@"; then print "REHEARSAL PASS $name"; ((pass++)); else print "REHEARSAL FAIL $name"; ((fail++)); fi; }
print "== rehearsal in $F (stub codex; real baseline and candidate commits)"
S 00 > $F/00.out 2>&1; check "00: isolation OK, codex exec answer names gpt-6-luna" sh -c "grep -q 'isolation: OK' $F/00.out && grep -q 'header model: gpt-6-luna | answer: CODEX-535-OK gpt-6-luna' $F/00.out && grep -q 'steps.zsh B0' $F/00.out"
grep -E 'codex:|codex login|header model' $F/00.out
S B0 > $F/B0.out 2>&1; check "B0: baseline wheels + venv from 8ac35e31 and f67d147a" sh -c "grep -q 'venv pip check rc=0' $F/B0.out && grep -q '^GraphTraj 8ac35e31' $F/B0.out && grep -q '^graftling f67d147a' $F/B0.out && grep -q 'steps.zsh T' $F/B0.out"
S T > $F/T.out 2>&1; check "T: one dialog (directory trust), no prompt, /exit" sh -c "grep -q 'Do you trust the contents of this directory' $F/T.out && grep -q '/exit' $F/T.out && grep -q 'steps.zsh Vb' $F/T.out"
S Vb > $F/Vb.out 2>&1; check "Vb: project .codex via active link, ONE role claude (533's) resolves without a model, USER command + prompt (runtime claude), one dialog" sh -c "grep -q 'CHECK 535 child role resolves: PASS (runtime claude, model claude-opus-5-5, reasoning_effort high' $F/Vb.out && grep -q 'base/active/venv/bin/graphtraj-mcp' $F/Vb.out && grep -q 'codex -m gpt-6-luna' $F/Vb.out && grep -q 'runtime claude, name n535' $F/Vb.out && grep -q \"the project's one role 'claude'\" $F/Vb.out && grep -q '恰好一个' $F/Vb.out && grep -q 'CLAUDE.md/CLAUDE.local.md at or above (Codex Main, Claude child): none' $F/Vb.out"
grep -E 'CHECK 535|roles file written|at or above' $F/Vb.out
cp $F/vproject/.codex/hooks.json $F/hooks-vb.json
check "Vb hooks.json: exactly SessionStart(stop_hook) + PostToolUse(display) + Stop(display); no checker, no SessionEnd; main-sessions cleared; fresh child name" \
  $F/base/active/venv/bin/python -I -c 'import json, sys
h = json.load(open(sys.argv[1]))["hooks"]
cmd = lambda e: [x["command"].split(" -m ")[1].split()[0] for g in h[e] for x in g["hooks"]]
ok = sorted(h) == ["PostToolUse", "SessionStart", "Stop"] and cmd("SessionStart") == ["graphtraj.runtimes.codex.stop_hook"] \
  and cmd("PostToolUse") == cmd("Stop") == ["graphtraj.runtimes.codex.display_hook"]
print("hooks.json:", {e: cmd(e) for e in sorted(h)}); sys.exit(0 if ok else 1)' $F/vproject/.codex/hooks.json
check "Vb: stale main-sessions cleared; fresh child name in the prompt" sh -c "[ ! -e $F/vproject/.graphtraj/runner/main-sessions ] && grep -qE 'child name for this run .*: n535[0-9]{4}' $F/Vb.out && grep -q \"name \$(cat $F/w/child-name)\" $F/w/V-prompt.txt"
S B > $F/B.out 2>&1; check "B: exact 535 diff, candidate wheels + venv, send_host_event takes text" sh -c "grep -q 'CHECK 535 GraphTraj product diff is exactly the 535 files: PASS' $F/B.out && grep -q 'venv pip check rc=0' $F/B.out && grep -q 'candidate send_host_event takes text: True' $F/B.out"
grep -E '^GraphTraj |^graftling |files changed' $F/B.out
S V > $F/V.out 2>&1; check "V: same hooks.json as Vb (no new hook review), active -> cand, role PASS" sh -c "cmp -s $F/hooks-vb.json $F/vproject/.codex/hooks.json && grep -q 'active -> $F/base/cand' $F/V.out && grep -q 'CHECK 535 child role resolves: PASS' $F/V.out"
# Vr picks the MAIN's rollout by its continuity claim, even with a NEWER decoy rollout of the same cwd (a child's).
# Each case: the Main's rollout holds one venv's REAL send_event output, the decoy the other's.
R=$F/codex-home/sessions/2026/11/21; MAIN=01a1f989-main-0000-0000-000000000535; DECOY=01a1f99f-child-000-0000-000000000535
mkdir -p $F/vproject/.graphtraj/runner/main-sessions
claims() {  # an older claim before V's stamp (ignored), then the Main's codex:SessionStart claim after it
  print -r -- "{\"at\": 1, \"entry\": \"codex:SessionStart:startup\", \"runtime\": \"codex\", \"session\": \"$DECOY\"}
{\"at\": $(( $(cat $F/w/Vcand.start) + 1 )), \"entry\": \"codex:SessionStart:startup\", \"runtime\": \"codex\", \"session\": \"$MAIN\"}" > $F/vproject/.graphtraj/runner/main-sessions/continuity.jsonl
}
push() { (cd $F/vproject && $F/base/$1/venv/bin/python -I $SD/fake_push535.py $R/$2 $F/vproject $3) >> $F/push.out 2>&1; }
claims; push base rollout-main-old.jsonl $MAIN; sleep 1; push cand rollout-decoy-new.jsonl $DECOY
S Vr > $F/Vr-old.out 2>&1; check "Vr picks the Main's rollout (not the newer decoy) and FAILs on the BASELINE push" sh -c "grep -q 'Main session $MAIN: rollout .*rollout-main-old.jsonl' $F/Vr-old.out && grep -q '^CHECK 535 notices: FAIL' $F/Vr-old.out"
grep -E 'Main session|CHECK' $F/Vr-old.out | head -7
rm $R/rollout-*.jsonl
push cand rollout-main-new.jsonl $MAIN; sleep 1; push base rollout-decoy-old.jsonl $DECOY
S Vr > $F/Vr-new.out 2>&1; check "Vr picks the Main's rollout (not the newer decoy) and PASSes on the CANDIDATE push" sh -c "grep -q 'Main session $MAIN: rollout .*rollout-main-new.jsonl' $F/Vr-new.out && grep -q '^CHECK 535 notices: PASS' $F/Vr-new.out"
rm $F/vproject/.graphtraj/runner/main-sessions/continuity.jsonl
S Vr > $F/Vr-none.out 2>&1; check "Vr without a Main claim: FAIL" grep -q 'FAIL: no codex:SessionStart Main claim' $F/Vr-none.out
sed -n '/---- notice/,/CHECK 535 notices/p' $F/Vr-new.out
# G's entry with real tests (GraphTraj tests using repository fixtures; graftling's tests of the change).
VERIFY535_TESTS="tests/test_current_host_events.py tests/test_codex_main_root_notice_401.py tests/test_codex_agent_display.py" \
VERIFY535_GLTESTS="tests/test_codex_host_event_text.py tests/test_notice_text.py" S G > $F/G.out 2>&1
S GR > $F/GR.out 2>&1
check "G: TMPDIR outside the Harness printed; both limited runs exit=0" sh -c "grep -q 'TMPDIR of the runs (outside the Harness)' $F/G.out && [ \$(grep -c '^exit=0' $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt | awk -F: '{s+=\$2} END {print s}') -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
