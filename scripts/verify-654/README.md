# Task 654: graftling test race in `test_a_request_notice_returns_promptly_while_pi_holds_it`

## Cause

`PiNotices.acknowledge` (graftling `src/graftling/pi/host.py`) settles a shown, awaited notice on its own daemon thread (`self.settling`, target `AgentControl.settle_notice`). The test read `held_notices` right after `acknowledge`. On a slow runner the thread had not settled yet, so the acknowledged request was still held. 653's Windows run 46114515028 attempt 1 failed at `tests/test_pi_dsh_notice_holding.py:603` with `['token-1', 'd21ad…'] == ['d21ad…']`. Attempt 2 of the same run passed.

## Change (graftling, test only)

The commit is `0dad0db948f5a7ec5f069b4910a8d19282634a1e` on graftling dev `67b0fe9a` (= main = v0.11.0), branch `agent/654-graftling-pi-notice-test-race`.
- Author and committer: `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`.
- It changes one file, `tests/test_pi_dsh_notice_holding.py`, with 4 added lines.
- After `acknowledge`, the test waits with the file's own `wait_until` (default bound 5 s) until the acknowledged request is no longer held. The exact assertion that follows is unchanged: the held list must equal exactly the second request.
- No product code, other test or workflow changes.

The commit is in `graftling-654.bundle` (`67b0fe9a..agent/654-…`, sha256 `e9ec81fda434cd4bcaa505c8e2b1c4d68449e265e13298c28ec778ed173fc2aa`).

## Steps for Main

Run `zsh <Worktree>/scripts/verify-654/steps.zsh <step>`. The script finds the Worktree and the Harness from its own location. No step opens a dialog.

| step | what it does |
|---|---|
| `00` | Read only. Checks zsh, TMPDIR, gh login (prints the account only), `<Harness>/graftling` origin and dev = `67b0fe9a`, the bundle (sha256, verify, head), the commit (parent, noreply identity, exactly the one test file, the test defined), and that the local and remote agent branch are each absent, the commit, or its ancestor. Also checks `scripts/verify-632/windows-expected.txt`: present, parses, and identical to GraphTraj dev's. |
| `P` | Outward-facing, under Worldline user-decision `20261127T190418.319112+0900`. Fetches only `refs/heads/agent/654-…` from the bundle into `<Harness>/graftling`. Pushes only that branch to `LUOXIAO92/graftling`, fast-forward only, never forced. Dispatches `windows.yml` on it by `workflow_dispatch`, because the push trigger does not list this branch and the workflow is not edited. If a dispatch run of the commit already exists, it observes that run instead. It waits in this process for the run to finish, then judges it. dev, main and tags are never pushed. |
| `W [run-id]` | Observes and judges only. |
| `X <run-id>` | Re-runs the failed jobs (`gh run rerun --failed`), only for a transient runner or download fault, never for a test result. Then it waits and judges. |

**The judge.** It is 653's judge, with the 652 new-tests check replaced by this Task's fixed test. VERDICT PASS needs all of these:
- the run's head is the commit;
- windows-tests passes, judged by 632's `wincheck.py` against the unchanged `windows-expected.txt` (this Task owns no line in it): 0 unexpected failures, passes or hangs;
- the fixed test PASSED in windows-tests' JUnit (`wincheck654.py fixed`);
- dsh-windows-tests and claude-real-entry succeeded, with every step;
- claude-real-entry's `results.json` has every item PASS on win32 (652's `realentry`).

Each job's evidence comes from the attempt that ran it (653's `evidence653.py`).

**Environment and output.** Every process the steps start gets an allowlist environment, and a guard stops the step if a credential-like or provider-like name gets in. Evidence goes to `scripts/verify-654/evidence/`, which is git-ignored. Every step prints its VERDICT and the next command, with real IDs, last.

## Rehearsal (`zsh rehearse.zsh`; outputs in `rehearsal/`, scrubbed of this machine's paths)

- **The judge, offline, through `zsh steps.zsh W 46114515028`** on Main's retained records of run 46114515028. A gh stand-in (`gh-standin.zsh`) serves them. The run object (head_sha = this commit, run_attempt, run_started_at) and the artifact names carrying this commit are fixtures; jobs, logs, JUnit and real-entry results are Main's records.
  - Attempt 1: `VERDICT 654 W: FAIL`. Results show 1 unexpected failure, and the fixed test is FAILED with the race's assertion (`W-46114515028-a1.txt`, `W-a1-fixed-test.txt`).
  - Attempt 2: `VERDICT 654 W: PASS`. windows-tests comes from attempt 2; claude-real-entry and dsh-windows-tests come from attempt 1 (`W-46114515028-a2.txt`).
- **`00` in the Engineer's sandbox:** 16 of 18 checks PASS. The 2 that fail are sandbox limits, not findings: gh cannot read its config, and github.com does not resolve for `git ls-remote`. Main's real 00 covers them (`00.txt`).
