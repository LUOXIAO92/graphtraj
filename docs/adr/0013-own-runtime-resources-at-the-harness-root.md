---
status: accepted
---

# Own Runtime resources at the Harness Project Root

The operator runs both setup and the normal Main session from the Harness
Project Root. Main must not enter the Integration Worktree or use a special
`-C` invocation merely to discover Harness configuration. The Harness Project
Root is therefore the control-plane root for one Harness Project, while the
Source Repository and its linked Worktrees remain the code-delivery plane.

The persistent layout is:

```text
<harness-project-root>/
├── .codex/
│   ├── config.toml
│   ├── agents/
│   ├── skills/
│   └── hooks/
├── .agent-worktrees/
│   ├── integration/
│   └── runs/<run-id>/<ticket-id>-<ticket-name>/
├── <repository-directory>/
│   └── .git/
└── state/
```

The root `.codex/` directory is the **Harness Runtime Store**. It owns Main's
project configuration, every Harness role definition, installed Harness
Skills, and Runtime-specific Hook sources. Skills under `.codex/skills/` are
selected explicitly through Runtime configuration; this location is a
Harness-owned store, not a claim that Codex discovers it as a repository Skill
directory automatically.

Setup creates the Harness Runtime Store and creates or registers `dev` and the
Integration Worktree in the same successful invocation. It does not install
these resources into `${HOME}/.codex`, and it does not commit them into the
Source Repository. The Source Repository may independently own `.codex/`,
`.agents/skills/`, and other development metadata; setup neither overwrites nor
uses those paths as the Harness control plane.

The Integration Worktree remains the long-lived `dev` checkout used for
serialized merge and validation. Ticket Worktrees remain isolated code
checkouts. Neither receives Harness-generated role definitions, installed
Harness Skills, or Hook sources. Ignored lifecycle links and evidence paths
required by ADR 0004 remain operational artifacts rather than Runtime
configuration.

Runner configuration must be discoverable from the Harness Project Root so
Main can invoke Runner there. This ADR does not choose the final filename or
physical location of that machine-local configuration.

This decision supersedes only the Runtime-placement and Main-working-directory
parts of ADRs 0002, 0007, 0009, 0010, 0011, and 0012. Their remaining package,
delivery, setup, Skill compatibility, project isolation, and Git integration
decisions remain accepted.

## Considered options

- Keeping Runtime resources in `dev` was rejected because Main launched from
  the Harness Project Root cannot discover configuration stored in a sibling
  Integration Worktree, and it makes an implementation checkout the accidental
  control plane.
- Requiring the operator to start Main inside the Integration Worktree was
  rejected because Integration is a merge and validation checkout, not the
  product entrypoint.
- Copying Harness Runtime resources into every linked Worktree was rejected
  because it duplicates ownership and can collide with Source Repository
  configuration.
