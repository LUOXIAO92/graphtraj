# GraphTraj

GraphTraj is a Harness for delivering a graph of accepted Tickets through
Teams. Main manages the whole request, dependencies and integration. Each
Team Leader coordinates one Engineer, two Reviewers and the Team's decisions.
The installed commands provide setup, isolated execution and durable evidence.
This coding Team protocol applies to dispatched `coding-team.*` members.
Shared Delivery State and temporary Batch specialists retain their own duties
and permissions.

Main is started and configured by the user. It follows the user's instructions
and the `AGENTS.md` files applicable to the task, reading Skills as needed.
GraphTraj does not generate, install, append or restore developer instructions
for Main, and using GraphTraj does not assign Main to a coding Team. Setup
preserves existing user Runtime configuration and prompts without using them
as template validation conditions. It does not distribute this development
repository's `AGENTS.md` or operating procedures to user projects.

## Install and set up

Python 3.12 or newer is required. Install a reviewed tag or commit:

```text
uv tool install "git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>"
graphtraj doctor
graphtraj setup
```

Run setup from the Harness Project Root. An existing Git repository is the
default: its Primary Worktree remains on `main`, and the current directory
becomes both the Harness Project Root and Source Repository. In the separated layout, setup selects the sole direct Git
child, or asks for an explicit choice when there are zero or several candidates.
Later commands use the recorded paths.

Setup is interactive and checks conflicts before writing. It preserves
project-owned content and valid operator configuration, creates or registers
the `dev` Integration Worktree, and installs every missing core Skill into the Harness Project Root’s
`.agents/skills` after confirmation, even when a user-global copy exists.
Existing project Skills are preserved; project-local copies take precedence
over user-global Skills. It does not clone a repository, configure credentials,
modify Runtime-global settings or promote `dev` to `main`.

The default layout is:

```text
<harness-project-root>/                  also the Source Repository by default
├── AGENTS.md                           user/project instructions
├── CONTEXT.md                          shared vocabulary
├── docs/                               Project Documents
├── .agents/skills/                     Harness Skills
├── .codex/                             Runner Hooks and user Runtime configuration
└── .graphtraj/
    ├── config.yml                      paths and Runner limits
    ├── roles.yml                       child-role Runtime settings
    ├── .agent-worktrees/
    │   ├── dev/                        Integration Worktree
    │   └── <ticket-id>-<ticket-name>/   disposable Ticket Worktree
    └── state/
        ├── batches/                    exact dispatch inputs
        ├── tickets/                    definitions, Team state and evidence
        └── worldline/                  append-only event shards
```

Runner-private execution records also live beneath `.graphtraj`, outside
durable state. Their filenames are implementation details. The separated
layout keeps the Source Repository in its configured child directory while
Project Documents remain at the Harness Project Root. Linked Worktrees expose
`CONTEXT.md` and `docs/` from their checkout when those already exist. Setup
and Runner preserve their contents and Git tracking; they create links to the
shared project documents only where those paths are absent. Existing documents
are the basis for later updates. Delegated Agents retain read-only document
access, and Main owns Project Document changes.

Generated document links use Worktree-specific Git ignore rules. Existing
repository documents and new files beneath them remain visible to Git unless
user rules exclude them. Setup preserves user ignore files and includes their
current rules in the Worktree-local copy, refreshed when setup or Worktree
preparation runs. Setup migrates the old installer's complete shared ignore
rule group; standalone user rules remain unchanged.

## Core Skills and their sources

After `graphtraj setup` installs the core Skills, invoke `$setup-project` to
configure task tracking and domain documents. It explicitly asks whether the
project includes work needing software engineering delivery. Small helper
scripts remain direct work with proportionate validation, even in a project
that also has engineering tasks.
`setup-project` is GraphTraj's name for its adaptation of Matt Pocock's
`setup-matt-pocock-skills`. `graphtraj setup` prepares the Harness; the Skill
guides the project-document configuration.

The release bundles these 18 core Skills. The table describes the bundled
workflows and their GraphTraj adaptations; user-installed Skills outside this
set are managed separately. Matt Pocock sources are from
[mattpocock/skills](https://github.com/mattpocock/skills).

| Project Skill | Source | GraphTraj adaptation |
| --- | --- | --- |
| `setup-project` | Matt Pocock: `setup-matt-pocock-skills` | Asks which work the project includes; shared setup stays in the entrypoint, coding setup is read conditionally. Project Documents belong to the Harness Project Root. |
| `grill-with-docs` | Matt Pocock: same name | Retains the interview and domain-modeling composition. |
| `grilling` | Matt Pocock: same name | Retains the decision-tree interview workflow. |
| `domain-modeling` | Matt Pocock: same name | Shared terminology and decisions in the entrypoint; code checks and architecture examples in a conditional reference. Main owns Project Documents. |
| `to-spec` | Matt Pocock: same name | Retains the software specification workflow; refers to `setup-project` for configuration. |
| `to-tickets` | Matt Pocock: same name | Code tickets preserve accepted task nodes, acceptance and dependencies; add justified difficulty and execution budgets as YAML front matter. |
| `implement` | Matt Pocock: same name | Team Engineers self-review and return evidence to their Leader, who schedules Reviewers; standalone work retains the code-review step. |
| `code-review` | Matt Pocock: same name | Distinguishes Leader-owned Team Review from standalone review orchestration; assigned Reviewers perform only their supplied axis. |
| `resolving-merge-conflicts` | Matt Pocock: same name | A dispatched Resolver stages the result for Main to commit and validate; incompatible accepted requirements return to Main. |
| `handoff` | Matt Pocock: same name | Project-specific Team continuation instructions covering scope, candidate, evidence and unfinished work in the final Session response. |
| `tdd` | Matt Pocock: same name | Retains the upstream test-driven development workflow. |
| `ponytail` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | Bundled minimal-implementation guidance, with no GraphTraj-specific changes to its instructions. |
| `task-delivery` | GraphTraj | General readiness, executor selection, dispatch, acceptance and integration; coding dispatch is conditional and the coding Leader owns its specialist workflow. |
| `task-breakdown` | GraphTraj | General goal-to-task decomposition with observable results, completion criteria and genuine blocking dependencies. |
| `research` | Matt Pocock: same name | Primary-source investigation; software source checks are a conditional reference. |
| `retro` | Matt Pocock: same name | Session-based improvements to Agent work; coding checks and review standards are a conditional reference. |
| `wayfinder` | Matt Pocock: same name | Retains the shared decision map; general rough artifacts do not automatically invoke software prototyping. |
| `prototype` | Matt Pocock: same name | Retains the software UI and logic prototype workflows with an explicitly software-scoped description. |

General Skill entrypoints load only their shared method. They read a domain
reference when the current task calls for it; they do not load all references
before choosing. Software-specific Skills remain independent and are selected
for the coding role's work. Existing explicit-only invocation policies are
preserved; a returned Skill name is not assumed to activate another Skill.

## Configuration and roles

All bundled Skill bodies and references live in `resources/skills` and install
through the same path. GraphTraj child definitions in `resources/roles` hold
responsibilities and required Skills independently of Codex configuration
syntax. `role_definitions.py` resolves these definitions and their logical
dispatch constraints with the Runtime, model and connection settings selected
in `.graphtraj/roles.yml`.

Runner passes the resolved child role to the Codex Adapter. The Adapter
locates its Skills and translates that role into native launch arguments,
permissions, Hooks and session calls. `resources/codex` contains only the
Codex integration: native child permission/Hook settings, reasoning settings
and tool-event handling. Main has no Runner child preset or managed Runtime
configuration template.

The default `.graphtraj/config.yml` is:

```yaml
version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state
agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
```

Paths resolve from the Harness Project Root. `dispatch_depth` limits formal
descendants below Main; a Team Leader is depth 1 and its children depth 2.
`max_concurrency` limits executing Agents across the project. Operating-system
locks enforce capacity; lock-file presence is not occupancy. A normal Batch
starts all its tasks or none. Team delivery also works at capacity one, with
the two Reviewers running sequentially in the same Round.

`.graphtraj/roles.yml` groups coding presets under `roles.coding-team`; shared
`delivery-state` remains directly under `roles`. Batch references use names such
as `coding-team.team-leader` or `coding-team.spec-reviewer`. Each preset selects `runtime`
and `model`, with optional `base_url` and `api_key_env`. The latter names an
environment variable, never stores the credential. Omitted settings use the
Runtime's defaults. Team Leader additionally supports `allow_runtime_swarm`,
which defaults to true. Presets include Team Leader, Engineer tiers, both
Reviewer axes, Delivery State and Merge Resolver. Main's already selected
Runtime is outside these presets.

A task can use a preset name or a one-entry inline role with the same Runtime
settings. Inline roles stay in their Batch and never become presets
automatically. Fixed role instructions, file access and dispatch permissions
are bundled policy; role settings cannot replace them. Setup does not generate
Runtime-specific child-role directories.

Engineer child tasks select Repository Skills explicitly through their `skills`
list. Other role tasks do not accept that field; Session resumption preserves
the original Adapter selection.
In the default same-directory layout, Source history distinguishes a tracked
Repository Skill from a Harness-owned Skill at the same physical path.

## Deliver accepted Tickets

Use the installed `task-delivery` Skill for the full workflow. Main registers
accepted GitHub Issue definitions and dependencies, generates the current
graph with `graphtraj ticket graph`, and selects ready Tickets and difficulty.
Only validated `dev` integration satisfies a dependency.

Main dispatches ready Tickets to Team Leaders with a block-style YAML Batch:

```yaml
tasks:
  - ticket_id: "123"
    ticket_name: example-feature
    role: coding-team.team-leader
    instruction: Senior difficulty. Deliver the current accepted Ticket.
```

The Ticket must already be registered. The Batch selects work; its optional
instruction adds concise dispatch details to the accepted definition. Several
ready Tickets may share one Batch when capacity permits. It has no Delivery
Run identifier or Batch-level Runtime setting.

Run public commands from the Harness Project Root:

```text
agent-runner --batch-input batch.yml
agent-runner status <alias> [<alias>...]
agent-runner send <alias> --instruction <text> --caused-by-event-id <event-id>
agent-runner interrupt <alias>
agent-runner replace <leader-alias> --actor main --caused-by-event-id <event-id>
graphtraj ticket graph
graphtraj worldline read
graphtraj worldline render
graphtraj ticket integrate --ticket-id <id> -- <validation-command> <arguments>
agent-runner cleanup --ticket-id <id>
```

Each coding Team Leader schedules its Engineer and both Reviewers through the same
Runner, against a fixed candidate and comparison point, then makes the final
adversarial decision. Process corrections stay in the current Team Round.
Only a compliant implementation rejection confirmed by the Leader opens the
next Round. Main or the user can retire a Team; replacement retains the
Ticket branch and Worktree, and reads handoff from the prior Leader's Trace.
Replacing another member changes only that seat.

Main corrects Ticket boundaries or dependencies when delivery evidence
disproves them, using `graphtraj ticket revise --revision-file <revision.yml>`.
Product-preserving graph corrections retain prior definitions and evidence;
product changes or new external authority require user direction. Delivery
State records supplied semantic decisions through validated commands; Runner
records only the execution facts it observes.

Main integrates accepted candidates serially into `dev` and supplies the
project's validation command. For an actual textual or semantic conflict,
the integration command accepts `--resolve-conflict <diagnosis>` to dispatch
a Merge Resolver. Successful Team Review alone does not merge a candidate.
Cleanup verifies integration and a clean disposable Worktree, removes safe
live mappings and the Ticket Worktree/branch, and preserves durable evidence.

## Evidence and limits

Each Ticket retains its initial definition, accepted revisions, current state,
successive Teams, closed Round reports and append-only Session Traces. Exact
Batches and the sharded Project Worldline connect the causal history.
Readiness and ledger-shaped views are generated on request; they are not
additional persisted state. Session aliases identify historical conversations,
not processes or invocation counters.

Historical `state/<run-id>` directories are left byte-for-byte untouched.
GraphTraj does not migrate them, read them as fallback or offer compatibility
for the old project command, Run-based Batch syntax or configuration sources.

The current Adapter supports Codex. Dispatched coding Teams use Runner for
formal implementation and Review. Permitted Team Leaders may use Runtime-native
helpers only for temporary read-only investigation; those helpers have no
independent GraphTraj Trace and cannot occupy a Team seat. Engineers and
Reviewers cannot dispatch child Agents or start another Runtime. Main's
Runtime and helper settings remain under user control.

GraphTraj has no queue, daemon, automatic crash-recovery service or automatic
release promotion. One Harness Project contains one Source Repository.


The test suite exercises installed commands with controlled Runtime behavior.
With an authenticated supported Codex executable, run the narrow live Adapter
probe explicitly:

```text
CODEX_REAL_ACCEPTANCE=1 pytest -p no:cacheprovider -q tests/test_harness_root_runtime.py -k test_real_codex --tb=short
```
