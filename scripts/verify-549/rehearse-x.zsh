#!/bin/zsh
# Task 549 rehearsal of step X's rollout selection, no real Codex and no model:
#   zsh scripts/verify-549/rehearse-x.zsh <rehearsal dir>      (after `steps.zsh 00` with the same VERIFY549_BASE)
# A stub `codex` (first on PATH via VERIFY549_STUB) writes, per run, an output carrying its id (human: stderr header
# 'session id: <id>' with a bold key; --json: thread.started) and its own rollout named with that id into a fake
# sessions directory (VERIFY549_CODEX_SESSIONS). Each run also writes a DECOY rollout with another id, newer than the
# step's marker, standing in for the user's interactive Codex session. Pass: X copies exactly the two own rollouts,
# prints both ids and both `codex resume` lines, and no 'decoy' file is copied.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; RH=${1:?usage: rehearse-x.zsh <rehearsal dir>}
: ${VERIFY549_BASE:?set VERIFY549_BASE to the base used for 00}
mkdir -p $RH/stub $RH/sessions/2026/11/21 $RH/fix
B=$(print -r -- $VERIFY549_BASE/*(/N[1])); S=($B/runs/S-*/server.json(Nom[1]))
[[ -n ${S:-} ]] || { print "STOP: no S result under $B; run steps.zsh 00 first"; exit 1; }
$B/venv/bin/python -I $SD/fixture549.py $S $RH/fix >/dev/null
ID1=11111111-1111-4111-8111-111111111111; ID2=22222222-2222-4222-8222-222222222222
DECOY=99999999-9999-4999-8999-999999999999
cat > $RH/stub/codex <<EOF
#!/bin/zsh
# stub codex for rehearse-x.zsh: never contacts a model
sessions=$RH/sessions/2026/11/21; fix=$RH/fix
if [[ " \$* " == *" --json "* ]]; then
  print -r -- '{"type":"thread.started","thread_id":"$ID2"}'
  cat \$fix/exec.jsonl
  cp \$fix/codex-rollout.jsonl \$sessions/rollout-2026-11-21T17-00-02-$ID2.jsonl
else
  print -r -- \$'\e[1msession id:\e[0m $ID1' >&2
  print -r -- 'mcp: graphtraj/agents started' >&2; print -r -- 'mcp: graphtraj/agents (completed)' >&2
  print -r -- 'DONE-549 ok ok ok ok ok ok'
  cp \$fix/codex-rollout.jsonl \$sessions/rollout-2026-11-21T17-00-01-$ID1.jsonl
fi
# the user's other, interactive session keeps writing its rollout (a doubled shape, to be noticed if copied)
cp \$fix/doubled.jsonl \$sessions/rollout-2026-11-21T17-00-03-$DECOY-decoy.jsonl
EOF
chmod +x $RH/stub/codex
VERIFY549_STUB=$RH/stub VERIFY549_CODEX_SESSIONS=$RH/sessions zsh $SD/steps.zsh X | tee $RH/X-stub.txt
D=$(grep -m1 '^evidence: ' $RH/X-stub.txt | cut -c11-)
copied=($D/rollouts/*(N:t))
names="${(j: :)copied}"
print -r -- "== rehearsal check: rollouts in sessions dir: $(ls $RH/sessions/2026/11/21 | tr '\n' ' '); copied (${#copied}): $names"
if (( ${#copied} == 2 )) && [[ $names == *$ID1* && $names == *$ID2* && $names != *decoy* ]] \
   && grep -q "codex resume $ID1" $RH/X-stub.txt && grep -q "codex resume $ID2" $RH/X-stub.txt; then
  print "REHEARSAL X PASS: only the two own rollouts copied, decoy $DECOY not copied, both resume lines printed"
else
  print "REHEARSAL X FAIL"; exit 1
fi
# missing id: a run whose output has no id must STOP for that run, not fall back
print -r -- '#!/bin/zsh
print -r -- "no header" >&2' > $RH/stub/codex
VERIFY549_STUB=$RH/stub VERIFY549_CODEX_SESSIONS=$RH/sessions zsh $SD/steps.zsh X > $RH/X-noid.txt 2>&1 || true
grep -E 'STOP \(X[12]\)|session id: MISSING|rollout copied' $RH/X-noid.txt
D2=$(grep -m1 '^evidence: ' $RH/X-noid.txt | cut -c11-)
n=($D2/rollouts/*(N))
(( ${#n} == 0 )) && [[ $(grep -c 'STOP (X' $RH/X-noid.txt) == 2 ]] \
  && print "REHEARSAL X-NOID PASS: both runs STOP, nothing copied (decoy present: $(ls $RH/sessions/2026/11/21 | grep -c decoy))" \
  || { print "REHEARSAL X-NOID FAIL"; exit 1; }
