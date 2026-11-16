# verify-486: a headless DSH Main's root Agent stops with it; the end is queued and delivered once

Main runs each step as `zsh scripts/verify-486/steps.zsh <step> 2>&1 | tee <OUT>/<step>.txt`. Each step
prints the next command, ready to paste. Base `<Harness>/tmp/486`:
- isolated project `tmp/486/project`, with its own git and `.graphtraj`;
- candidate venv `tmp/486/venv`, the commit archived to `tmp/486/candidate` and installed editable from
  there; dependencies are linked read-only from production `.venv-runtime`.

Evidence goes to `.graphtraj/core/state/tasks/486-dsh-main-root-agent-end-after-exit/realhost`. The DSH
turns use the README "DSH as Main" form `dsh --profile headless --patch <file>`, as verify-481 does.
Verdicts are read from records:
- `x486.py`: the control record's `executions[-1]` and each Main queue's notices of that execution id;
- `verify-444/probe.py`: `queued`, `delivered` and `inbox`.

| Step | Does | Dialog | Success lines | Wait limit |
| --- | --- | --- | --- | --- |
| 00 | production Main and `.venv-runtime` recorded; candidate venv; isolated project with its own runner directory; probe Task 1 ready; patch written, `graphtraj-main` row in the composed headless tree; `claude -p` and `dsh` each answer one line, judged as not the prompt echo (last line starts with the tag and has no `<`); model, login and instruction files printed; ONE `tasks` discover through the patched headless DSH Main | none | `PASS 00` | 120 + 120 + 300 s |
| D1 | DSH Main creates g398 (sleep 60) and exits at once, which stops g398 | none | `PASS 486 queued` (end `interrupted`, one PENDING notice for `dsh:<session>`, none elsewhere), probe `QUEUED` | 300 + 60 + 5 s |
| D2 | resume with `--session-id` | none | `PASS 486 delivered` (one notice id, delivered, none elsewhere), probe `397 record delivered once: PASS` | 300 s |
| X | read only: record and queues | none | diagnosis only | 0 |
| SUITE | full suite of the candidate commit, from a git checkout `tmp/486/checkout-SUITE` (shared clone) with its own test venv, 6 shards, `TMPDIR=${TMPDIR:-/tmp}` outside the Harness | none | totals; comparison once SUITEB exists | 1500 s |
| SUITEB | the same for dev `5a451267`; compares failure sets | none | `PASS SUITE no new failures against dev 5a451267` | 1500 s |
| F | production Main and `.venv-runtime` unchanged; each pid this script started has ended; PASS/FAIL summary | none | `PASS F production Main`, `PASS F production .venv-runtime unchanged` | 0 |

Since Task 489, step 00 runs `scripts/verify-common/claude_isolation.py settings` on the project after its setup and judges `claude -p` (stream-json) with `check --expect clean`: 00 STOPs when a Harness instruction file is loaded (see `scripts/verify-common/README.md`).

`VERIFY486_NO_MODEL=1` stops 00 before any model call, and stops SUITE/SUITEB before the suite runs.
`VERIFY486_STUB_BIN`, `VERIFY486_BASE` and `VERIFY486_OUT` serve the rehearsal only.
