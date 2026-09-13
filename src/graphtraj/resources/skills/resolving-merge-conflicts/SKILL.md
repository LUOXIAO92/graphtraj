---
name: resolving-merge-conflicts
description: "Resolve software implementation conflicts in an in-progress Git merge or rebase."
---

1. **See the current state** of the merge/rebase. Check git history, and the conflicting files.

2. **Find the primary sources** for each conflict. Understand deeply why each change was made, and what the original intent was. Read the commit messages, check the PRs, check original issues/tickets.

3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Resolve within the accepted requirements; report incompatible requirements to the caller. Do not `--abort` the caller’s operation.

4. Validate the resolved behavior with the relevant automated checks and fix
   anything the merge broke. In a GraphTraj dispatch, Main's integration command
   owns the supplied final validation command; return focused results and let
   that command run once. For standalone work, run the required merge/rebase
   checks. Reuse valid evidence for unaffected paths.

5. **Finish the assigned work.** When dispatched as a GraphTraj Merge Resolver,
   stage the reconciliation and return it to Main; Main’s integration command
   completes the merge and records the commit. If accepted requirements cannot
   both be satisfied, report that incompatibility to Main. For standalone
   merge/rebase work, stage the resolved files and commit, or continue the rebase
   until all commits are rebased.
