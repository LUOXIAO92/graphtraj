# Task 615 verification

graftling candidate `3a35334e977d5a9536a42d320e2a3243d3989f6d` on base `2fdc0d38d8aa25ff22145a8d534911d38cf6bb01`
(dev), in `graftling-615.bundle` (branch `agent/615-graftling-models-description-intent-match`).
Change: `models`' description ends "read only." instead of "read only, starts no Agent."; new test
`tests/test_discovery_intents_615.py`; CHANGELOG Unreleased "Fixed" entry.

Main runs `zsh steps.zsh 00`, then `I`, `R`, optionally `T`. Login: none for every step (see the header of steps.zsh).

## Files

- `rehearsal/{00,I,R,T}.txt`: the Engineer's rehearsal of every step through `zsh steps.zsh <step>`, with
  `VERIFY615_ROOT=/private/tmp/claude-501/graftling-615` (the rehearsal sandbox cannot write
  `/private/tmp/graftling-615`). All PASS.
- `rehearsal/contrast-base-{I,R,T}.txt`: the same steps with `VERIFY615_GCOMMIT=2fdc0d38` (base): R's
  `start an agent` gives `['create', 'models']` (FAIL) and T has 1 failed, 8 passed.
- `rehearsal/T-run1-no-graphtraj-pth.txt`, `rehearsal/T-run2-pth-without-metadata.txt`: earlier T attempts that
  GraphTraj's conftest refused (no graphtraj; then a .pth without distribution metadata); T now installs the
  Worktree editable, as verify-614 does.
- `tests/test615-before.txt` / `tests/test615-after.txt`: the new graftling test on the base source (1 failed,
  11 passed: `[start an agent]` gives `['create', 'models']`) and on the fix (12 passed). Run from the graftling
  checkout, editable in a scratch venv: `TMPDIR=${TMPDIR:-/tmp} <venv>/bin/python -m pytest -p no:cacheprovider -q -rA
  tests/test_discovery_intents_615.py`.
- `tests/suite-base.txt` / `tests/suite-cand.txt`: graftling full suite, `pytest -p no:cacheprovider -q -rfE tests`,
  TMPDIR=/tmp/claude-501 (outside the Harness), both run at the same time. Base: 5 failed, 905 passed, 21 skipped.
  Candidate: 3 failed, 919 passed, 21 skipped. Every candidate failure also fails on base
  (`test_codex_tool_reclaim_462.py`, process-identity assertions in this sandbox); no new failure.
- `tests/graphtraj-intents-{candidate,base}.txt`: the full pytest output of step T for each.
