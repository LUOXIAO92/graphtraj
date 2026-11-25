# Task 620 Round 1 — validation (Engineer)

(Intended for `.state/teams/1/rounds/1/validation.md`; that path was denied to this Session's file tools.)

Environment: macOS (Darwin 25.6.0), zsh 5.9, git 2.50.1, `/Users/luoxiao/miniconda3/bin/python3.13`. Sandbox: no network, Unix-socket bind EPERM, `<Harness>/tmp` not writable.
The fix is in 631f1fb6 (base 055669d9), and the rehearsal outputs were committed at 11beaf72.

| Check | Command | Result |
|---|---|---|
| Syntax | `python -I -c 'ast.parse(...)' tests/linux_adoption_runtime.py scripts/verify-620/rehearsal/*.py`; `zsh -n scripts/verify-620/steps.zsh` | ok |
| (a) base | `python -I scenario_driver.py base <055669d9 tests> <scratch>` | FileNotFoundError on `native-codex-home/...`; only session_meta and turn_context exist in the peer's `tests/codex-home` rollout (`console/a-scenario-base.txt`) |
| (a) fixed | `python -I scenario_driver.py fixed tests <scratch>` | 5 controlled records appended with turn_id equal to the turn/start id; fails only at the control-socket connect (`console/a-scenario-fixed.txt`) |
| (b) 00 / L / P success / 00 again / W | `zsh scripts/verify-620/rehearsal/rehearse.zsh $TMPDIR/r620` | PASS / log saved and matched / PASS / STOP→W / PASS (`console/b-*.txt`) |
| (b) P failure / P timeout | same | VERDICT FAIL exit 1 with log-failed tail and OTHER workflow / VERDICT FAIL appearance timeout |
| (b) default output dir | 00 without VERIFY620_OUT | derives `<Harness>=/Users/luoxiao/workspace/you-are-a-product-architect-delivery`, STOP not writable (sandbox) |
| Diff scope | `git diff --stat 055669d9 HEAD -- ':!scripts/verify-620'` | workflow (1 line), .gitignore (+3), tests/linux_adoption_runtime.py; no product code |

Not run: the real CI run (step P, Main and the user's approval), the full CI log (step L), and the full socket exchange (EPERM). Existing pytest does not cover this Linux-only fixture.
