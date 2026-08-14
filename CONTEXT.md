# Pure-Agent Harness

This context describes the shared language for a soft Agent Harness that lets
Main orchestrate planning and delivery while narrow hard Modules provide safe
execution support.

## Language

**Harness Project**:
One isolated unit operated by the Harness, containing one Source Repository,
all of that repository's Worktrees, its Runtime resources, and durable delivery
state.
_Avoid_: Workspace, Source Repository

**Harness Project Root**:
The filesystem boundary that contains exactly one Harness Project and isolates
its resources from every other Harness Project.
_Avoid_: Repository root, Workspace root

**Source Repository**:
The Git repository whose code is delivered by a Harness Project, including its
Primary Worktree and linked Worktrees. The entire repository belongs to one
Harness Project.
_Avoid_: Harness Project, Primary Worktree, Repository directory

**Primary Worktree**:
The operator-cloned initial Worktree of the Source Repository, distinct from
the linked Integration Worktree and Ticket Worktrees.
_Avoid_: Source Repository, Primary checkout, Repository directory

**Worktree Directory**:
The project-private filesystem home for the linked Integration Worktree and
Ticket Worktrees, separate from the Primary Worktree and from other Harness
Projects.
_Avoid_: Shared worktree root, Workspace worktrees

**Harness State Directory**:
The durable project-level home for Delivery Run ledgers, task maps, batch
inputs, and evidence, independent of any Worktree's lifecycle.
_Avoid_: Scratch directory, Integration Worktree state

**Harness Runtime Store**:
The Harness Project-owned control-plane source for Main configuration, Harness
roles, Harness Skills, and Runtime policy, independent of Source Repository
history and Worktree lifecycles.
_Avoid_: Source Repository Runtime configuration, Integration Worktree
configuration

**Harness Skill**:
A Skill installed and owned by a Harness Project for Main or selected Harness
roles.
_Avoid_: Repository Skill

**Repository Skill**:
A Skill authored by the Source Repository and made available to an Engineer
only through explicit task selection or Harness Project policy.
_Avoid_: Harness Skill, Automatically trusted Skill

**Engineer Runtime Context**:
The immutable Adapter-resolved role, Runtime settings, selected Skills, and
task access used to launch or resume one Engineer session.
_Avoid_: Runtime profile, Source Repository configuration
