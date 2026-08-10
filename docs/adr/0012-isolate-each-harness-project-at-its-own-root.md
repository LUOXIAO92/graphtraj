---
status: accepted
---

# Isolate each Harness Project at its own root

The Harness Project Root, not a workspace directory and not the Source
Repository, is the isolation boundary for one Harness Project. V1 contains one
Source Repository at `<harness-project-root>/repo/`, one project-private
Worktree Directory at `<harness-project-root>/.agent-worktrees/`, and one
persistent Harness State Directory at `<harness-project-root>/state/`. Setup is
run from the Harness Project Root and must not discover, group, authorize, or
share state with neighboring projects merely because they have the same
filesystem parent.

The Source Repository remains a normal Git repository with its own `.git/`.
Reviewable Runtime resources belong with that repository: Codex configuration
and role definitions live under `repo/.codex/`, and project-local Skills use
the repository's normal project-local Skill layout. These resources are
reviewed and committed so the Integration Worktree and Ticket Worktrees inherit
them. Keeping Runtime resources in Git is independent of keeping Runner
worktrees and delivery state outside Git.

The project-private Worktree Directory has no additional project-name layer:

```text
<harness-project-root>/
├── .agent-worktrees/
│   ├── integration/
│   └── runs/<run-id>/<ticket-id>-<ticket-name>/
├── repo/
│   ├── .git/
│   └── .codex/
└── state/
```

V1 does not infer a multi-repository project from repositories being adjacent
in a general-purpose workspace. Supporting one Harness Project that coordinates
multiple Source Repositories requires an explicit later design.

## Considered options

- Treating the Source Repository as the Harness Project Root was rejected
  because Runtime transport state, disposable Worktrees, and durable delivery
  evidence have different lifecycles from product source.
- Sharing a workspace-level Worktree root between projects was rejected
  because filesystem adjacency does not establish a common ownership or trust
  boundary.
- Moving `.codex` outside the Source Repository was rejected as a requirement:
  committed project configuration is the normal way for Git Worktrees to
  inherit the same Codex roles and settings.
