---
name: resolving-merge-conflicts
description: "Resolve software implementation conflicts in an in-progress Git merge or rebase."
---

1. **See the current state** of the merge/rebase. Check git history, and the conflicting files.

2. **Find the primary sources** for each conflict. Understand deeply why each change was made, and what the original intent was. Read the commit messages, check the PRs, check original issues/tickets.

3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Resolve within the accepted requirements; report incompatible requirements to the caller. Do not `--abort` the caller’s operation.

4. Validate changed behavior using the project's assigned executor and relevant
   checks. Reuse valid evidence for unaffected paths. In a GraphTraj dispatch,
   retain the supplied integration validation command so the caller can repeat
   it after the exact result is accepted. A role name does not assign testing
   authority; follow the project's responsibilities.

5. **Finish the assigned work.** Commit the resolved merge before handoff. For a
   GraphTraj assignment, submit the committed version through `submit-result`;
   the actual authorized parent records `decide-result`, then the caller repeats
   the original integration validation to finish. Report incompatible accepted
   requirements to the caller. For standalone work, commit the resolved merge
   or continue the rebase until all commits are rebased.
