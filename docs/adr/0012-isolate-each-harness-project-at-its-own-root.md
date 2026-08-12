---
status: accepted
---

# Isolate each Harness Project at its own root

The Harness Project Root, not a workspace directory and not the Primary
Worktree, is the isolation boundary for one Harness Project. V1 contains one
Source Repository whose existing Primary Worktree is at
`<harness-project-root>/<repository-directory>/`, one project-private Worktree
Directory at `<harness-project-root>/.agent-worktrees/`, and one persistent
Harness State Directory at `<harness-project-root>/state/`. The operator clones
the repository and chooses the Primary Worktree's directory name before setup,
then identifies that directory to the interactive setup command. Setup does
not clone a repository. It runs from the Harness Project Root and must not
discover, group, authorize, or share state with neighboring projects merely
because they have the same filesystem parent.

The Primary Worktree remains a normal operator-cloned Git checkout and
identifies the Source Repository through its `.git/` metadata. Reviewable
Runtime resources belong in that repository's history: Codex configuration and
role definitions use the repository-relative `.codex/` directory, and
project-local Skills use the repository-relative `.agents/skills/` directory.
Setup initially writes these resources in the `dev` Integration Worktree; once
reviewed and committed, later Ticket Worktrees inherit them. Keeping Runtime
resources in Git is independent of keeping linked Worktrees outside the Primary
Worktree and delivery state outside every Worktree.

The project-private Worktree Directory has no additional project-name layer:

```text
<harness-project-root>/
├── .agent-worktrees/
│   ├── integration/                         # dev checkout
│   └── runs/<run-id>/<ticket-id>-<ticket-name>/
├── <repository-directory>/                  # Primary Worktree on main
│   └── .git/
└── state/
```

V1 does not infer a multi-repository project from repositories being adjacent
in a general-purpose workspace. Supporting one Harness Project that coordinates
multiple Source Repositories requires an explicit later design.

## Considered options

- Treating the Primary Worktree as the Harness Project Root was rejected
  because Runtime transport state, disposable Worktrees, and durable delivery
  evidence have different lifecycles from product source.
- Sharing a workspace-level Worktree root between projects was rejected
  because filesystem adjacency does not establish a common ownership or trust
  boundary.
- Moving `.codex` outside Source Repository history was rejected as a
  requirement: committed project configuration is the normal way for Git
  Worktrees to inherit the same Codex roles and settings.
