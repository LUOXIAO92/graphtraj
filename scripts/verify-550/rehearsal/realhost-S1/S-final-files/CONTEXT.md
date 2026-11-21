# GraphTraj

This context describes the shared language for GraphTraj's task graph and
trajectories. This Harness uses hierarchical Agents to execute its work, with
narrow hard Modules providing execution support. The accepted domain boundary
is recorded in `docs/design/skill-decoupling.md`; current implementation progress
is recorded in `docs/specs/generic-task-decoupling.md`. The language below incorporates the accepted
2026-09-19 target architecture in
[ADR 0044](docs/adr/0044-bind-agent-ownership-and-control-descendant-execution.md)
and its [design revision](docs/design/agent-hierarchy-and-execution-control.md).
Accepted definitions do not imply all corresponding behavior is implemented.
The 2026-09-25 clarification in
[ADR 0042](docs/adr/0042-share-an-organized-core-between-cli-and-host-tools.md)
requires the same delivery, acceptance, completion-state and trajectory
mechanisms for coding and other tasks. Domain differences are work content,
methods, acceptance criteria and evidence, not separate task lifecycles.
The same clarification allows one-Agent Teams and separates task acceptance
authority from the Team Leader role. Existing Team/Round grouping may remain;
this project's chosen member roles and reports are not required for all tasks.

## Language

**Harness Project**:
One isolated unit operated by the Harness, containing one Source Repository,
all of that repository's Worktrees, its Runtime resources, and durable delivery
state.
_Avoid_: Workspace, Source Repository

**Project Development Material**:
Documents, source, Task results, reports, diagnostics and associated Session
history that concern development of the Harness Project. Authorship and native
Session provenance remain attributed; project read scope is distinct from
Agent control authority and default display scope.
_Avoid_: Own-Agent-only history, Control permission, All user history

**Harness Project Root**:
The filesystem boundary that contains exactly one Harness Project and isolates
its resources from every other Harness Project.
_Avoid_: Repository root, Workspace root

**Source Repository**:
The Git repository whose file-based results are managed by a Harness Project,
including its Primary Worktree and linked Worktrees. The entire repository belongs to one
Harness Project.
_Avoid_: Harness Project, Primary Worktree, Repository directory

**Primary Worktree**:
The operator-cloned initial Worktree of the Source Repository, distinct from
the linked Integration Worktree and Task Worktrees.
_Avoid_: Source Repository, Primary checkout, Repository directory

**Worktree Directory**:
The project-private filesystem home for the linked Integration Worktree and
Task Worktrees, separate from the Primary Worktree and from other Harness
Projects.
_Avoid_: Shared worktree root, Workspace worktrees

**Harness State Directory**:
The authoritative, durable project-level home for the Project Worldline,
retained Batches, Task and Team state, and execution evidence needed to
resume work independently of any Task Worktree's lifecycle.
_Avoid_: Harness Scratch Directory, Integration Worktree state

**Harness Scratch Directory**:
The non-authoritative project-level home for disposable user/Main discussion,
design drafts, and investigations whose loss cannot change delivery truth.
_Avoid_: Harness State Directory, Delivery evidence

**Harness Project Document**:
A Main-owned, durable control-plane document beneath the Harness Project Root
that records shared language, requirements, decisions, design, or operation.
_Avoid_: Source Repository document, Harness State evidence, Harness Scratch
material

**Harness Guidance**:
Harness-specific Main guidance rooted at the Harness Project Root and kept
separate from Source Repository instructions.
_Avoid_: Repository Guidance, Runtime configuration, Skill procedure

**Repository Guidance**:
Concise, stable, project-general instructions in the Source Repository root
`AGENTS.md` that apply across ordinary repository tasks.
_Avoid_: Harness Guidance, Task instruction, Review finding ledger

**Soft Plan**:
Main's default read-only authorization state before the user explicitly asks
it to execute a state-changing action. It is a developer-instruction policy,
not an Agent Runtime's formal Plan mode.
_Avoid_: Plan mode, Pending execution approval

**Agent Runtime**:
The execution environment that hosts an Agent, such as Codex, independently of
the logical role the Agent performs or the model it uses.
_Avoid_: Agent Runner, Runtime Adapter, Model

**Agent Runner**:
The Harness execution boundary that dispatches the exact logical roles
selected by an authorized calling Agent through supported Runtime Adapters.
_Avoid_: Agent Runtime, Main

**Runtime Adapter**:
The Harness binding that translates a logical role and task access into one
Agent Runtime's native launch and session mechanics.
_Avoid_: Agent Runtime, Agent Runner

**Runtime Selection**:
The Agent Runtime named by a resolved child-role configuration for a launch.
Main's own Runtime and model remain user-selected.
_Avoid_: Runtime discovery, Main Runtime configuration

**Task Graph**:
The current, revisable structure of goals, Tasks, dependencies, state,
parallel work, and completion conditions for one long-running task. Delivery
evidence may correct this structure without changing the product goal.
_Avoid_: Fixed workflow, Delivery Run

**Trajectory**:
The retained history and evidence of work managed through Agent Runner,
including successful and failed execution, artifact delivery, acceptance
decisions and state changes, independently of the work's domain.
_Avoid_: Task Graph, Runtime-native helper history

**Task**:
One locally identified unit of work using the shared delivery lifecycle and
owning its definition, current state, evidence and any Worktree or Team selected
for the work. Its stable numeric ID belongs to its Harness Project, independently
of any remote Issue number; local records are authoritative.
It may be decomposed into finer Tasks, merged, or corrected when evidence
shows the current boundary is not independently deliverable. Decomposition
does not itself retire or replace the parent Task.
_Avoid_: Tracker Ticket, Remote Issue, Delivery Run, Batch task

**Remote Issue**:
An object owned by an external tracker. A Task may reference or back up to one
through an explicit mapping; unrelated bug reports and requests do not become
local Tasks automatically. Remote changes do not overwrite local task facts.
_Avoid_: Task, Local Task ID

**Summary Task**:
A Task whose independently deliverable goal is decomposed into child
Tasks. It retains its own title, scope and acceptance; child completion alone
does not establish that the parent result is accepted. It is not merely a visual
collection inferred from external issue text. This is the user's required task
model; the accepted protocol and migration design are in
[the task hierarchy specification](docs/specs/native-task-hierarchy-and-dag.md).
_Avoid_: Display group, Issue label

**Task Parent**:
The task whose scope is refined by another task. This relationship expresses
decomposition, whereas a dependency identifies a result needed from another
task, and replacement identifies work that supersedes an earlier task.
_Avoid_: Dependency, Replacement, Agent parent

**Team**:
One or more actual Agents assigned to an active Task, with members
selected for its scope and no universally required Leader, Engineer, Reviewer
or state-maintainer seat.
_Avoid_: Batch, Delivery Run

**Team Leader**:
The member that coordinates a selected Team. Task acceptance may be assigned
to this member, but this role is not a universal prerequisite or exclusive
authority for accepting tasks; project-specific instructions define its duties.
_Avoid_: Main, Project manager

**Team Generation**:
One successive Team assigned to a Task. New aliases express handover
generation starting at zero; a Worker restart or individual member replacement
does not advance it. Existing historical ordinals and records remain unchanged.
_Avoid_: Session generation, Retry count

**Team Round**:
One work cycle of a Team, including a one-Agent Team, without a required set
of role-named reports. Applicable coding Review limits remain Task-scoped
and do not reset with a new Round.
_Avoid_: Review Round, Turn

**Agent Entity**:
One Agent registered and identified by GraphTraj. GraphTraj establishes its
direct parent and Main, member or completion-checker purpose through managed
creation or authorized host adoption. Runtime conversation handles are execution
associations, not the Agent's identity or authority. Replacing a Worker does not
create or reparent the Agent. This is the accepted target of
[unified identity management](docs/specs/graphtraj-agent-identity-and-completion.md),
not a claim that the current implementation has completed that migration.
_Avoid_: Role preset, Worker, PID, Current execution

**Agent Alias**:
A readable handle for one Agent Entity, used for launch results and subsequent
interaction. Its text is not proof of identity, role authority or ownership.
_Avoid_: Role reference, Session ID, Permission credential

**Session**:
One Agent Runtime's conversation and memory, associated with an Agent Entity
through its Runtime Adapter. The unified Session protocol preserves native
provenance, fork ancestry and opaque content; neither its representation nor a
native handle grants authority or changes Agent or Task parentage.
_Avoid_: Live Session, Turn

**Session Worker**:
The execution carrier that runs or controls a native Session. Restarting the
Worker may resume the same Agent; it does not itself create another Session.
_Avoid_: Agent Entity, Native Session

**Trace**:
The append-only execution history and final output retained for one Session.
Later scores, probability observations and supplemented content retain their
source and target without replacing original events or ciphertext.
_Avoid_: Project Worldline, Turn log

**Batch**:
The historical retained input for one Agent Runner dispatch, possibly covering
several Tasks. Existing implementation still uses it; the accepted new launch
surface is swarm, and historical Batch evidence remains unchanged.
_Avoid_: Delivery Run, Task Graph

**swarm launch interface**:
The Agent activation interface accepting role aliases and launch instructions
for multiple children. Task context comes from the current Task projection,
dependencies from the Task Graph, and later interaction uses Agent aliases.
_Avoid_: Conversation channel, Second Task Graph, Batch lifecycle

**Project Worldline**:
The authoritative append-only causal history linking meaningful new facts and
their retained evidence across Batches, Tasks, Teams, and Sessions.
_Avoid_: Trace, Ledger, Activity log

**Harness Skill**:
A Skill installed and owned by a Harness Project for Main or selected Harness
roles. When the Harness and Source roots coincide, the Skill is absent from
Source Repository history.
_Avoid_: Repository Skill

**Repository Skill**:
A Skill authored by the Source Repository. The selected Runtime and project
policy determine its discovery, explicit use and access; GraphTraj does not
select or trust it by name. A Skill in Source Repository history remains a
Repository Skill when both roots coincide.
_Avoid_: Harness Skill, Automatically trusted Skill

**Runtime Context**:
The retained role, Runtime settings, selected resources and task access for one
Session. Original captured context remains evidence; supported recovery uses
the applicable resource and approval configuration while preserving Session
identity and permission guarantees. Older records may call this an Engineer
Runtime Context; it applies to any configured role.
_Avoid_: Runtime profile, Source Repository configuration

**Reviewer**:
An Agent assigned to examine task artifacts and evidence against the relevant
criteria. Selected coding-team review uses Standards or Spec Agents to examine
the same fixed candidate; that team arrangement is not required for all review.
_Avoid_: Mandatory Team seat, Automatic acceptance authority
