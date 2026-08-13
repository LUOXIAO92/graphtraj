# you-are-a-product-architect

V1 is a soft delivery Harness: Main makes delivery decisions, while the
installed commands provide safe setup, isolated Engineer transport, and cleanup.

## Pinned installation

Install a reviewed tag or commit, never a moving branch. Python 3.12 or newer
is required.

```text
uv tool install "git+https://<repository-url>@<tag-or-commit>"
```

This installs the `you-are-a-product-architect` and `agent-runner` commands in
an isolated tool environment. It does not install project configuration into a
user-global Codex Runtime directory.

## Project layout

Run setup from the **Harness Project Root**, which contains one Source
Repository and its disposable and durable Harness material:

```text
<harness-project-root>/
├── <repository-directory>/                  Primary Worktree on main
├── .agent-worktrees/
│   ├── integration/                         Integration Worktree on dev
│   └── runs/<run-id>/<ticket-stem>/         Ticket Worktrees
└── state/                                   Harness State Directory
```

The Primary Worktree is the operator's existing clone and remains untouched by
setup. The Integration Worktree is the only normal development-integration
checkout; Ticket Worktrees are isolated, disposable Engineer checkouts.

## Diagnose and set up

From the Harness Project Root, first inspect the core Skill names:

```text
you-are-a-product-architect doctor
```

Then run the interactive setup:

```text
you-are-a-product-architect setup
```

Select the existing Primary Worktree when prompted. If required Skills are
missing, choose `project-local` to copy the release-supported Skills into the
Integration Worktree, or stop and install them through the Runtime's normal
user scope before rerunning setup. Setup creates or registers `dev`, writes
the Codex roles and Worktree Guard only in the Integration Worktree, and makes
`.scratch` point at the Harness State Directory. It does not clone a source
repository, write `~/.codex`, alter credentials, or change the Primary
Worktree.

Setup deliberately stops before committing. Review and commit the generated
`.codex/` and selected `.agents/skills/` resources on `dev` before dispatching
an Engineer. Runner preflight requires that clean, committed state so Ticket
Worktrees inherit the reviewed configuration.

Treat tracker binding, repository instructions, and domain documentation as
target-project concerns; setup does not impose this repository's choices on a
target project.

## Deliver a selected ticket

Main selects the ticket, tier, and integration order. The Runner is mechanical
transport only: it neither reads a tracker nor discovers a queue.

Create a YAML batch containing one `run_id` and one to four selected tasks
(`ticket_id`, `ticket_name`, `role`, `ticket_file`, and optionally a concise
`instruction`), then launch it from the Integration Worktree:

```text
agent-runner --batch-input <batch.yml>
```

The public Runner commands all emit one YAML result document on stdout:

```text
agent-runner status <alias> [<alias>...]
agent-runner send <alias> --instruction <text>
agent-runner interrupt <alias>
agent-runner cleanup --run-id <run-id> --ticket-id <ticket-id>
```

Use `status` only for aliases Main explicitly supplies. With the Codex V1
Runtime, `send` can resume an idle session but cannot inject live input into a
running turn; Main may explicitly interrupt and then send when that is the
intended recovery. A candidate is committed in its Ticket Worktree. After
review evidence is adjudicated by Main, Main merges the candidate into `dev`
in the Integration Worktree and runs the target project's validation there.

After that validation succeeds, run `agent-runner cleanup` for the stable run
and ticket IDs. It verifies that the branch is merged into `dev` and that the
Ticket Worktree is clean before removing the worktree, merged branch, aliases,
and transient Runtime diagnostics. Repeating successful cleanup reports an
idempotent already-cleaned result.

## Evidence and tracker portability

Persistent evidence stays outside Git Worktrees under
`state/task-delivery/<run-id>/`: exact retained batches, ticket metadata,
Engineer result and validation summaries, and raw reviewer reports remain after
cleanup. The Delivery State Agent owns the run ledger and task map; the Runner
owns only mechanical metadata. There is no deletion command: an operator may
manually delete a completed run's `state/task-delivery/<run-id>/` directory
through the filesystem or file manager when its retention period ends.

This repository itself uses GitHub Issues, but a target project chooses its own
tracker binding. GitHub, GitLab, local Markdown, and other project-local
workflows are all valid; Main must read or establish that target-specific
binding instead of inheriting this repository's tracker choice.

## V1 limitations

- Runtime support is Codex-only; other Adapters are future work.
- Core Skill discovery is name-only: contents are not locked or attested, and
  duplicate Skill names can resolve differently. Operators should avoid them.
- There is no hard scheduler or queue. Main selects readiness, tiers, dispatch,
  retry, escalation, and integration ordering.
- There is no automatic state watcher; Main asks the Delivery State Agent to
  synchronize durable evidence after meaningful events.
- One Harness Project contains one Source Repository. V1 does not coordinate
  multiple Source Repositories.
- There is no automatic promotion from `dev` to `main`; release promotion is a
  separate explicit operator action.
