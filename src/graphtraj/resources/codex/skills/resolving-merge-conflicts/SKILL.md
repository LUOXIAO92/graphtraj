---
name: resolving-merge-conflicts
description: "Use when you need to resolve an in-progress git merge/rebase conflict."
---

1. **See the current state** of the merge/rebase. Check git history, and the conflicting files.

2. **Find the primary sources** for each conflict. Understand deeply why each change was made, and what the original intent was. Read the commit messages, check the PRs, check original issues/tickets.

3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Resolve within the accepted requirements; report incompatible requirements to the caller. Do not `--abort` the caller’s operation.

4. Discover the project's **automated checks** and run them, typically typecheck, then tests, then format. Fix anything the merge broke.

5. **Finish the assigned work.** When dispatched as a GraphTraj Merge Resolver,
   stage the reconciliation and return it to Main; Main’s integration command
   completes the merge and records the commit. If accepted requirements cannot
   both be satisfied, report that incompatibility to Main. For standalone
   merge/rebase work, stage the resolved files and commit, or continue the rebase
   until all commits are rebased.
