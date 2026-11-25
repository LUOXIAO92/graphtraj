# Task 620 Round 1 — Engineer report

(Intended for `.state/teams/1/rounds/1/engineer.md`. That path and its resolved state path were denied to this Session's file tools,
and no `submit_report` feature is installed, so this report is committed here instead.)

Worktree `.graphtraj/core/worktrees/620-linux-adoption-codex-fixture`, branch `agent/620-linux-adoption-codex-fixture`, base 055669d9.
Commits: 631f1fb6 (fix, trigger, .gitignore, steps and rehearsal tools), 11beaf72 (rehearsal outputs) and the commit that adds this report. Nothing pushed.

## Cause (confirmed locally; the CI log has not been fetched yet)
Since 7ad94f6a, `tests/runner_codex_peer.py:117` (the Leader's line 101 sits in the same thread/start block) writes the rollout to
`Path(scenario).parent / 'codex-home/sessions/fake/rollout-<session>.jsonl'`. `tests/linux_adoption_runtime.py` still
read `$CODEX_HOME/sessions/fake/...` through `LINUX_ADOPTION_ROLLOUT`, which raised FileNotFoundError and made the scenario exit 1.
The peer then reported 'scenario failed', and `linux_adoption_input.py:88` hit the 30 s accept timeout. Rehearsal (a) reproduces this at base.

## Changes (no product code)
- `tests/linux_adoption_runtime.py`: the `exec` branch now reads `Path(__file__).parent / 'codex-home/sessions/fake' / ('rollout-' + FAKE_CODEX_SESSION_ID + '.jsonl')`.
  This is the peer's rule: `scenario` is this file, and the peer passes `FAKE_CODEX_SESSION_ID=session` to the scenario, so the
  rule also holds when FAKE_CODEX_EVENTS renames the session. `LINUX_ADOPTION_ROLLOUT` and the CODEX_HOME lookup are removed.
  Nothing else referenced them (grep). `runner_codex_peer.py` is unchanged.
- `.gitignore`: `tests/codex-home/` was **not** covered before. I added that one entry (two lines including its comment).
- `.github/workflows/desktop-linux-adoption.yml`: the only change is the push branches line, with `agent/620-linux-adoption-codex-fixture` appended.
  The other three workflows (macos, repair-package, win) do not list the branch, and none of them triggers on all branches. Step 00 checks this at HEAD.
- `scripts/verify-620/steps.zsh`: steps 00, L, P and W, modelled on verify-618. It has the same credential scrub, the `allow()` environment, a
  fast-forward-only push, the knobs `VERIFY620_REMOTE/_GH/_APPEAR_S/_DONE_S/_POLL_S` and **one added knob, `VERIFY620_OUT`**.
  `VERIFY620_OUT` replaces `<Harness>/tmp/620` only in rehearsal, because that directory is not writable from this sandbox.
  `<Harness>` is derived as the git common dir's `:h:h` and checked: it must hold `.graphtraj` and contain this worktree under `.graphtraj/core/worktrees/`.
  P/W wait in-process (appearance 300 s, completion 1800 s, poll 30 s), save `run-<id>.log`, print `--log-failed` tail on failure, other
  workflows for the SHA, next commands with real IDs, VERDICT last. L prints byte/line counts and ≤200 lines of bounded matches, next command last.
  No zsh special parameter names are used as variables. I replaced `status` with `runstate` after I noticed it.

## Rehearsal (outputs in `scripts/verify-620/rehearsal/console/`, driver `rehearsal/rehearse.zsh`)
- (a) `scenario_driver.py`: Unix-socket bind is EPERM here, so the exchange runs up to the connect.
  - base: FileNotFoundError on `native-codex-home/...` while the file is under `tests/codex-home/...`; turn/completed failed 'scenario failed'.
  - fixed: the peer's rollout gains turn_context(turn_id = the turn/start id), message, function_call, function_call_output and token_count.
    It then fails only at `connection.connect(LINUX_ADOPTION_CONTROL)`.
- (b) steps through `zsh scripts/verify-620/steps.zsh <step>` with a local bare remote and `fakegh.py`. Every case gives the expected result:

  | Case | Result |
  |---|---|
  | 00 | PASS |
  | L | log saved, matches shown |
  | P success | PASS |
  | 00 again | STOP; suggests W with the real SHA |
  | W | PASS |
  | P failure | FAIL with the log-failed tail and the OTHER workflow |
  | P appearance timeout | FAIL |
  | 00 without VERIFY620_OUT | derives `<Harness>/tmp/620` and STOPs (not writable here, as expected) |

## Unresolved / for the Leader and Main
- Main must still run step L (the user's gh login) to confirm the cause from the full CI log, and step P (outward-facing; Main asks the user first).
- Once the fixture reaches the control socket in CI, the run continues into `desktop/tests/adoption-linux.mjs`.
  I did not examine its drift against the D UI. That decision stays with Main, and a P failure there would be a separate scope.
- The full socket exchange was not run locally because bind is EPERM in the sandbox.
- The assigned `.state/teams/1/rounds/1/{engineer,validation}.md` were not writable from this Session, so the Leader may copy these two files there.
