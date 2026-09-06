# GraphTraj

GraphTraj is a Harness for delivering a graph of accepted Tickets through
Teams. Main manages the whole request, dependencies and integration. Each
Team Leader coordinates one Engineer, two Reviewers and the Team's decisions.
The installed commands provide setup, isolated execution and durable evidence.

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
the `dev` Integration Worktree, and installs missing supported Harness Skills
after confirmation. It does not clone a repository, configure credentials,
modify Runtime-global settings or promote `dev` to `main`.

The default layout is:

```text
<harness-project-root>/                  also the Source Repository by default
├── AGENTS.md                           Harness Guidance
├── CONTEXT.md                          shared vocabulary
├── docs/                               Project Documents
├── .agents/skills/                     Harness Skills
├── .codex/                             Main's project-local Runtime resources
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
read-only `CONTEXT.md` and `docs/` views. Main owns Project Document changes.

## Configuration and roles

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

`.graphtraj/roles.yml` contains a `roles` mapping. Each preset selects `runtime`
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
    role: team-leader
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

Each Team Leader schedules its Engineer and both Reviewers through the same
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

The current Adapter supports Codex. Formal implementation and Review always
use Runner. Main and permitted Team Leaders may use Runtime-native helpers
only for temporary read-only investigation; those helpers have no independent
GraphTraj Trace and cannot occupy a Team seat. Engineers and Reviewers cannot
dispatch child Agents or start another Runtime.

GraphTraj has no queue, daemon, automatic crash-recovery service or automatic
release promotion. One Harness Project contains one Source Repository.


The test suite exercises installed commands with controlled Runtime behavior.
With an authenticated supported Codex executable, run the narrow live Adapter
probe explicitly:

```text
CODEX_REAL_ACCEPTANCE=1 pytest -p no:cacheprovider -q tests/test_harness_root_runtime.py -k test_real_codex --tb=short
```
