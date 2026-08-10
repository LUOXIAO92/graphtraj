# Pure-Agent Harness

This context describes the shared language for a soft Agent Harness that lets
Main orchestrate planning and delivery while narrow hard Modules provide safe
execution support.

## Language

**Harness Project**:
One isolated unit operated by the Harness, containing its Runtime resources,
Source Repository, Worktrees, and durable delivery state.
_Avoid_: Workspace, Source Repository

**Harness Project Root**:
The filesystem boundary that contains exactly one Harness Project and isolates
its resources from every other Harness Project.
_Avoid_: Repository root, Workspace root

**Source Repository**:
The Git repository whose code is delivered by a Harness Project. It is a child
of the Harness Project Root rather than the project root itself.
_Avoid_: Harness Project, Project root

**Worktree Directory**:
The project-private home for the Integration Worktree and Ticket Worktrees,
separate from the Source Repository and from other Harness Projects.
_Avoid_: Shared worktree root, Workspace worktrees

**Harness State Directory**:
The durable project-level home for Delivery Run ledgers, task maps, batch
inputs, and evidence, independent of any Worktree's lifecycle.
_Avoid_: Scratch directory, Integration Worktree state
