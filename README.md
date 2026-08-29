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
├── .codex/                               Harness Runtime Store
│   ├── agents/                            canonical Harness roles
│   └── hooks/                             Harness Worktree Guard
├── .agents/skills/                        supported Harness Skills
├── <repository-directory>/                  Primary Worktree on main
├── .agent-worktrees/
│   ├── integration/                         Integration Worktree on dev
│   └── runs/<run-id>/<ticket-stem>/         Ticket Worktrees
├── state/<run-id>/                          authoritative Delivery Run state
└── .scratch/                                disposable working material
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
missing, setup asks once whether to install the supported copies in the
Harness Project's `.agents/skills/`; declining stops before setup writes
anything. Setup
creates or registers `dev`, installs configuration, roles, and Hooks under the
root `.codex/` Runtime Store, installs supported Skills under the root
`.agents/skills/`, makes the Integration Worktree's ignored `.state` point at
the Harness State Directory, and makes its ignored `.scratch` point at the
distinct Harness Scratch Directory. It does
not clone a source repository, write `~/.codex`, alter credentials, or change
the Primary Worktree or Source Repository Runtime files.

The Runtime Store is Harness-owned rather than committed into `dev`; Ticket
Worktrees do not inherit Harness roles, Hooks, or Harness Skills. Runner still
requires a clean `dev` Integration Worktree before dispatching a role.

Treat tracker binding, surrounding repository instructions, and domain
documentation as target-project concerns. Setup manages only the marked
Reviewer-guidance section in the Source Repository root `AGENTS.md`, as defined
by [ADR 0026](docs/adr/0026-manage-inherited-reviewer-guidance.md); it does not
impose this repository's other choices on a target project.

## Deliver a selected ticket

Main selects the ticket, Engineer tier, optional Reviewers, Runtime, and
integration order. The Runner is mechanical transport only: it neither reads a
tracker nor discovers a queue.

Create a YAML batch containing one `run_id`, one selected `runtime`, and one
to four selected tasks
(`ticket_id`, `ticket_name`, `role`, `ticket_file`, optional semantic `skills`,
and optionally a concise `instruction`). Reviewer tasks additionally carry a
positive `review_round` and one exact relative `report_file`; Engineer tasks
carry neither. Runtime, model, configuration, Hook, and command details never
belong in task objects. Then launch it from the Harness Project Root:

```text
agent-runner --batch-input <batch.yml>
```

Run every public Runner command from the Harness Project Root; each emits one
YAML result document on stdout:

```text
agent-runner status <alias> [<alias>...]
agent-runner send <alias> --instruction <text> \
  --caused-by-worldline-seq <seq> [--caused-by-worldline-seq <seq> ...]
agent-runner interrupt <alias>
agent-runner cleanup --run-id <run-id> --ticket-id <ticket-id>
```

Repository Skills are disabled by default. A task may name only the Repository
Skills it needs; Runner resolves each name in the Ticket Worktree and records
both requested and effective selections in durable ticket evidence. The
root-owned Runner configuration exposes a persistent Repository Skill allowlist
for Main, but allowlisting never enables a Skill by itself.

Engineer tasks use `engineer-junior`, `engineer-senior`, or `engineer-expert`.
After an Engineer returns a fixed candidate and validation evidence, Main may
omit review or launch `standards-reviewer` and `spec-reviewer` concurrently
as separate tasks against that same Ticket Worktree. Neither axis gates the
other. Main supplies the same exact candidate and comparison point in each
instruction. Reviewer roles receive a read-only candidate and are limited to
their exact raw-report paths; Main waits for both reports and verifies the
candidate and Git state before one round decision. Merge and integration
actions do not use Reviewers.

The minimum finding policy is inherited from the managed `## Reviewer
guidance` section in the Source Repository root `AGENTS.md`; setup ownership is
defined by [ADR 0026](docs/adr/0026-manage-inherited-reviewer-guidance.md).
Runtime role prompts and Skills reference that policy instead of copying its
body.

Use `status` only for aliases Main explicitly supplies. With the Codex V1
Runtime, `send` can resume an idle session but cannot inject live input into a
running turn. A resume names the prior Worldline sequence or sequences that
caused it; Main may explicitly interrupt and then send when that is the intended
recovery. Review and commit the candidate in its Ticket Worktree.
Main adjudicates any dispatched Standards and Spec reports; when it omits
review, it records that decision without inventing a review verdict. Main then
merges the accepted candidate into `dev` in the Integration Worktree and runs
the target project's validation there.

After that validation succeeds, run `agent-runner cleanup` for the stable run
and ticket IDs. It verifies that the branch is merged into `dev` and that the
Ticket Worktree is clean before removing the worktree, merged branch, aliases,
and transient Runtime diagnostics. Repeating successful cleanup reports an
idempotent already-cleaned result.

## Evidence and tracker portability

Persistent evidence stays outside Git Worktrees under
`state/<run-id>/`: exact retained batches, ticket metadata,
Engineer result and validation summaries, and Main-retained raw Reviewer
reports remain after cleanup. Review Diversity is recorded only when the
selected Reviewer Runtime or model actually differs from the Engineer's; using
the same Runtime and model is valid. ADR 0025 owns the append-only Worldline and
derived `ledger.yml`; ADR 0003 owns current `task-map.yml` and `dag.md`; ADR
0004 owns retained batch input. The Runner owns only mechanical metadata. There
is no deletion command: an operator may
manually delete a completed run's `state/<run-id>/` directory
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
