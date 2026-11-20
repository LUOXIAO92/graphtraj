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
S Vb > $F/Vb.out 2>&1; check "Vb: project .codex written via active link, role (astra engineer -> luna, effort medium) resolves (no model), USER command + prompt" sh -c "grep -q 'CHECK 535 child role resolves: PASS (runtime codex, model gpt-6-luna, reasoning_effort medium' $F/Vb.out && grep -q 'role codex = production astra_coding_team.engineer' $F/Vb.out && grep -q 'codex/deepseek/deepseek-flash | does not resolve' $F/Vb.out &&grep -q 'base/active/venv/bin/graphtraj-mcp' $F/Vb.out && grep -q 'codex.display_hook' $F/Vb.out && grep -q 'codex -m gpt-6-luna' $F/Vb.out && grep -q 'Pass NO model' $F/Vb.out"
sed -n '/^production presets/,/CHECK 535 child role/p' $F/Vb.out
# Without gpt-6-luna in the catalog Vb STOPs before the USER part and says why.
catalog without > $F/home/.graphtraj/connections.yml
S Vb > $F/Vb-noluna.out 2>&1; check "Vb without gpt-6-luna in the catalog: FAIL with the reason, STOP before the USER part" sh -c "grep -q 'CHECK 535 child role resolves: FAIL (ValueError: the catalog has no codex model with id or key gpt-6-luna)' $F/Vb-noluna.out && grep -q 'codex/openai/gpt-6-astra: id gpt-6-astra' $F/Vb-noluna.out && grep -q 'STOP: the child role does not resolve' $F/Vb-noluna.out && ! grep -q '粘贴下面整段提示' $F/Vb-noluna.out"
grep -E 'CHECK 535|STOP' $F/Vb-noluna.out
catalog with > $F/home/.graphtraj/connections.yml
cp $F/vproject/.codex/hooks.json $F/hooks-vb.json
# Correction round 1: hooks.json holds no Stop completion checker or SessionEnd, and the SessionStart claim ignores
# ONLY an `exec` child (its session would otherwise become the current Main); every other source reaches stop_hook
# (here 'appServer': the wrapper hands it on, so its output is stop_hook's, not the wrapper's {}); stale main-sessions
# removed; fresh child name.
print -r -- '{"type":"session_meta","payload":{"source":"exec"}}' > $F/child-rollout.jsonl
CLAIM=$(print -r -- "{\"hook_event_name\":\"SessionStart\",\"source\":\"startup\",\"session_id\":\"x\",\"cwd\":\"$F/vproject\",\"transcript_path\":\"$F/child-rollout.jsonl\"}" \
  | (cd $F/vproject && $F/base/active/venv/bin/python -I $SD/main_start535.py))
# A non-exec source is handed to stop_hook (stub codex on PATH, rehearsal CODEX_HOME: no real host is contacted).
print -r -- '{"type":"session_meta","payload":{"source":"appServer"}}' > $F/main-rollout.jsonl
print -r -- "{\"hook_event_name\":\"SessionStart\",\"source\":\"startup\",\"session_id\":\"x\",\"cwd\":\"$F/vproject\",\"transcript_path\":\"$F/main-rollout.jsonl\"}" \
  | (cd $F/vproject && env PATH=$F/stub:/usr/bin:/bin CODEX_HOME=$F/codex-home /usr/bin/perl -e 'alarm 60; exec @ARGV' \
       $F/base/active/venv/bin/python -I $SD/main_start535.py) > $F/claim-main.out 2>&1
print "claim for a non-exec source (handed to stop_hook; output and exit code are stop_hook's): rc=$? $(tail -c 300 $F/claim-main.out)"
check "SessionStart of a non-exec source is handed to stop_hook (not the wrapper's {})" sh -c "[ \"\$(cat $F/claim-main.out)\" != '{}' ]"
check "Vb hooks: SessionStart claim + display only; an exec child's SessionStart is ignored; main-sessions cleared; fresh child name" sh -c "! grep -q 'stop_hook' $F/vproject/.codex/hooks.json && ! grep -q SessionEnd $F/vproject/.codex/hooks.json && grep -q main_start535.py $F/vproject/.codex/hooks.json && [ '$CLAIM' = '{}' ] && [ ! -e $F/vproject/.graphtraj/runner/main-sessions ] && grep -qE 'child name for this run .*: n535[0-9]{4}' $F/Vb.out && grep -q \"name \$(cat $F/w/child-name)\" $F/w/V-prompt.txt"
S B > $F/B.out 2>&1; check "B: exact 535 diff, candidate wheels + venv, send_host_event takes text" sh -c "grep -q 'CHECK 535 GraphTraj product diff is exactly the 535 files: PASS' $F/B.out && grep -q 'venv pip check rc=0' $F/B.out && grep -q 'candidate send_host_event takes text: True' $F/B.out"
grep -E '^GraphTraj |^graftling |files changed' $F/B.out
S V > $F/V.out 2>&1; check "V: same hooks.json as Vb (no new hook review), active -> cand" sh -c "cmp -s $F/hooks-vb.json $F/vproject/.codex/hooks.json && grep -q 'active -> $F/base/cand' $F/V.out && grep -q 'CHECK 535 child role resolves: PASS' $F/V.out"
# Vr on rollouts holding what the REAL send_event of each venv writes.
R=$F/codex-home/sessions/2026/11/21
(cd $F/vproject && $F/base/base/venv/bin/python -I $SD/fake_push535.py $R/rollout-old.jsonl $F/vproject) > $F/push-old.out 2>&1
S Vr > $F/Vr-old.out 2>&1; check "Vr on the BASELINE push (escaped JSON): FAIL (the check can fail)" grep -q '^CHECK 535 notices: FAIL' $F/Vr-old.out
grep -E 'CHECK' $F/Vr-old.out | head -6
rm $R/rollout-old.jsonl
(cd $F/vproject && $F/base/cand/venv/bin/python -I $SD/fake_push535.py $R/rollout-new.jsonl $F/vproject) > $F/push-new.out 2>&1
cat $F/push-new.out
S Vr > $F/Vr-new.out 2>&1; check "Vr on the CANDIDATE push (notice text): PASS" grep -q '^CHECK 535 notices: PASS' $F/Vr-new.out
sed -n '/---- notice/,/CHECK 535 notices/p' $F/Vr-new.out
# G's entry with real tests (GraphTraj tests using repository fixtures; graftling's tests of the change).
VERIFY535_TESTS="tests/test_current_host_events.py tests/test_codex_main_root_notice_401.py tests/test_codex_agent_display.py" \
VERIFY535_GLTESTS="tests/test_codex_host_event_text.py tests/test_notice_text.py" S G > $F/G.out 2>&1
S GR > $F/GR.out 2>&1
check "G: TMPDIR outside the Harness printed; both limited runs exit=0" sh -c "grep -q 'TMPDIR of the runs (outside the Harness)' $F/G.out && [ \$(grep -c '^exit=0' $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt | awk -F: '{s+=\$2} END {print s}') -eq 2 ]"
grep -E 'TMPDIR|^graphtraj |^graftling ' $F/G.out; tail -2 $F/w/G-*/graphtraj.txt $F/w/G-*/graftling.txt
print "== rehearsal: $pass passed, $fail failed"
exit $(( fail > 0 ))
