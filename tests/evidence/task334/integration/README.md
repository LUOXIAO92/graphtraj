# Task334 integration reconciliation

Fixed parents: dev `8ec86c366b07d84638078450f63ea6da87af5e93` and incoming
`7afc514e0d866cb95daeaabd8e6f141e14070418`. This evidence belongs to the merge
commit containing this file. Only the assigned merge was continued.

## Resolution

- `agent_swarm/connection.py`, `agent_swarm/mcp.py`, `interfaces/hosted_cli.py`
  and `interfaces/mcp.py` retain dev's shared call_owner, metadata, native
  authorizer and universally progressive agents/tasks entries. These already
  include incoming DSH context checks. Removed the redundant auto-merged MCP
  discovery filter that still referenced the retired progressive_entry variable.
- `execution/agent_driver.py` supports Claude, Codex, DSH and Pi together,
  preserving each existing owner binding and dev's explicit configuration
  selection. Default Pi selection retains incoming's Pi-only preset filter.
- Inspected the automatic merges in control.py, sessions/archive.py and
  sessions/protocol.py: configuration forwarding coexists with receive_children
  and notification outside the lock; history/replacement coexists with native
  seq and pending-final observation associations. No changes to those automatic
  merges were necessary.
- Added controlled-peer checks for Pi default/explicit configuration with an
  unrelated unavailable connection, archive-off operation and same-Session
  resume, and Codex metadata verification through the shared MCP connection.
  Existing DSH checks exercise the same connection and optional archive binding.

## Development checks

Python 3.13.11 and pytest 9.1.1 from the existing dedicated
`/private/tmp/task331-venv`; no dependency installation or environment changes.
Exact argv, working directories and results are in `commands.json`.
Retained text logs remove trailing whitespace only for Git patch hygiene.

- Focused combination: 66 passed, 12 skipped (9.65 s). The skipped cases require
  an explicitly pinned official Claude SDK; none was enabled for this task.
- Hosted CLI, common control and CLI/MCP: 25 passed, 1 failed (7.17 s).
- Pi configuration/resume: 2 passed (1.77 s).
- Codex metadata/common owner: 1 passed.
- `python -m compileall -q src tests` and `git diff --check`: passed in the
  assigned Integration Worktree before committing.

The one host-control failure is
`test_native_submission_errors_identify_wrong_reference_and_git_failure`:
it expects the full `git cat-file -t <commit>:absent.md` string, whereas the
existing error contains `git cat-file in <cwd> exited 128`. Reproduced on the
exact dev parent (1 failed, 0.65 s); see `dev-baseline-failure.txt`. It is not a
merge regression and remains unresolved outside this reconciliation's scope.

Pytest's ancestor discovery was denied access to the parent `.agent-worktrees`
directory even with an explicit root/confcutdir. Both collection attempts had
the same error; the first is retained in `collection-permission.txt`. Tests
therefore ran on a disposable source/test copy in `/private/tmp`, not another
Git Worktree. `snapshot-sha256.json` records checked byte-identical final Python
source/test files and pyproject.toml. The initial focused suite preceded the
new Codex metadata test, which was then run separately. No product source
changed after the snapshot was made.

The new Pi fixture initially used the Harness root as cwd and correctly hit
`RUNTIME_ACCESS_DENIED: Pi needs a Worktree outside private state`; both failures
are retained in `pi-fixture-cwd-failure.txt`. Changing only the fixture cwd to
`worktrees/research` yielded the two passes above. Product isolation is unchanged.

## Handoff

Retain validation argv exactly: `["git", "diff", "--check", "HEAD^", "HEAD"]`.
The actual parent must decide the submitted exact commit; integration then
runs retained validation. These are development checks, not Leader acceptance.
No model/UI runs, new Runtime, extra integration source, role/identity edits,
Task-state edits, cleanup/retirement or changes to Harness documents occurred.
Earlier Task334 real-client evidence remains intact in the incoming history.
The existing baseline failure and optional SDK skips are explicitly retained.
