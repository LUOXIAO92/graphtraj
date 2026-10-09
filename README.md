# GraphTraj

GraphTraj coordinates Agent work in your own project. It tracks which tasks
need which results, runs the Agents you configure, and keeps the submitted
versions, decisions and execution history together.

Use it when work spans several tasks or Agents and you need to know what is
ready, what is still blocked, and which results have actually been accepted and
integrated. Research, documents, data and software can use the same workflow.
A task can have a single Agent; you choose the roles and methods.

## Get started

You need Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/)
for the installation below. Start with an existing Git repository that has a
commit and whose primary worktree is on `main`.

Choose a tag or commit to install, replacing `<tag-or-commit>`:

```sh
uv tool install "git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>"
cd /path/to/your-project
graphtraj setup
graphtraj doctor
graphtraj ticket graph
```

Setup shows its plan and asks before creating the `dev` branch. It creates or
registers a separate worktree for integration and stores configuration and task
history under `.graphtraj/`. Your primary worktree stays on `main`. A new
project has no tasks or Agent roles yet, so its first graph is empty.

Running setup again preserves existing configuration and history. For a layout
with a separate source repository, or other project conventions, see the
[setup guide](manuals/setup-project/guide.md).

## Use it with your Agent

Your main Agent runs in the host you already use. To delegate work, install and
authenticate the chosen Agent Runtime separately; GraphTraj does not supply
model credentials or change your host's global settings.

For a first Codex child Agent, add this preset to `.graphtraj/roles.yml`, replacing
`your-selected-model` with a model available to your Codex installation:

```yaml
roles:
  researcher:
    runtime: codex
    model: your-selected-model
    worktree_access: write
role_tree:
  researcher: {}
```

Merge it into existing configuration if the file already contains roles.
`role_tree` allows this role to receive work directly from your main Agent; an
empty child mapping gives it no further dispatch roles. Run `graphtraj doctor`
after editing. Optional `instructions` can point to your own UTF-8 role file.
Keep credentials in the Runtime's native configuration or an environment
variable named by `api_key_env`.

Your host must expose the `graphtraj` tool. If it supports MCP, register
`graphtraj-mcp` as a stdio server with the project root as its working directory.
For hosts using TOML MCP configuration:

```toml
[mcp_servers.graphtraj]
command = "graphtraj-mcp"
args = []
cwd = "/absolute/path/to/your-project"
```

Use your host's normal configuration and trust controls, and open or reload the
session as that host requires. The optional [GraphTraj Skill](skills/graphtraj/SKILL.md)
introduces the workflow; installing a Skill alone does not register the tool.

With the tool available, start from a task you have agreed to do, for example:

> Use GraphTraj to deliver the research task in this GitHub Issue: [issue URL].
> Use the researcher role, retain the sources with the document, and show me
> the result and any remaining work.

The [task delivery guide](manuals/task-delivery/guide.md) covers registration,
dispatch, result decisions and integration. The tool can describe each operation
and its inputs when needed. Current Ticket registration requires a GitHub Issue
URL; provide its accepted scope and completion criteria to your Agent.

## How work progresses

1. **Define the work.** Tasks are registered as Tickets with completion criteria
   and dependencies on the results they need.
2. **Run ready tasks.** Configured Agents work in Ticket worktrees. Independent
   tasks can run in parallel within the project's concurrency and budget limits.
3. **Assess the result.** An Agent submits a committed version and evidence;
   its authorized parent accepts it or requests a correction. An Agent finishing
   its turn does not by itself complete the task.
4. **Integrate.** Accepted results are merged and validated in `dev`. Successful
   integration satisfies dependencies and makes subsequent work ready.

GraphTraj retains the original inputs, reports, native Session records and
project event history so work can be inspected or continued. Your project
chooses who validates and accepts results; a coding team or review process is
not required for every kind of work.

These commands give you an overview from the project root:

```sh
graphtraj ticket graph    # Tasks, dependencies and readiness
agent-runner status      # Agent tree and current activity
graphtraj worldline read # Recorded project events
```

For direct CLI use, start with `graphtraj --help` and `agent-runner --help`.
Individual command help includes its input schema; the
[command input reference](manuals/task-delivery/references/command-inputs.md)
explains the files used for registration, result decisions and integration.

## Runtimes and host integration

Child Agents can use different Runtimes without changing your main Agent's host.

| Runtime | Preparation and limits |
| --- | --- |
| Codex (`codex`) | An installed, authenticated Codex CLI. Native permissions and approvals remain in effect. |
| Pi (`pi`) | An installed Pi backend, existing Pi configuration, and an `asb` sandbox with `srt`. The role's optional `pi.sandbox_python`, `pi.sandbox_path` and `pi.agent_dir` select those locations. |
| DeepSeek Harness (`dsh`) | DSH `0.2.0-rc.2` and a host that supports its native subprocess sandbox. Native replacement and recovery approval routes are unavailable; its native file tools can read outside the task worktree. |

The execution host needs access to the chosen Runtime executable, credentials,
project files and subprocess sandbox. Role permissions do not replace the
Runtime's filesystem restrictions.

For custom hosts, [the local tool binding](src/graphtraj/interfaces/local_tool.py)
provides a Python callback and the `graphtraj-tool` JSON-lines process interface.
MCP is optional. CLI or MCP access alone does not connect background events or
completion hooks to an existing conversation; those require integration with
the host that owns the session. See
[completion checking](manuals/task-delivery/guide.md#main-completion-checking)
and [recovery](manuals/task-delivery/references/recovery.md).

GraphTraj currently manages one source repository per project. It does not
provide a job queue, automatic crash recovery, or automatic promotion from
`dev` to `main`.

## Optional desktop

The development app in [desktop/](desktop/) offers a project graph and settings
for existing role presets and dispatch relationships. The CLI works without
Node or Electron; the desktop is an optional monitoring and configuration window.
It does not provide task execution controls or a complete usage dashboard.

To run it from a source checkout, install the matching Python GraphTraj version
and make `graphtraj-tool` available on `PATH` (or set `GRAPHTRAJ_TOOL` to its
executable). With Node 22.18+ and a graphical desktop session:

```sh
cd desktop
npm ci
npm exec -- install-electron
npm start
```

Choose **Add project** and select an existing GraphTraj project root. Removing
an entry removes it from the app's list; it does not delete the project.
Packaged cross-platform installers are not yet provided.

## More documentation

- [Project setup](manuals/setup-project/guide.md): paths, tracking and resources.
- [Task breakdown](manuals/task-breakdown/guide.md): scope, dependencies and work sizing.
- [Task delivery](manuals/task-delivery/guide.md): execution through integration.
- [Recovery](manuals/task-delivery/references/recovery.md): interruptions, failures and continuation.
- [Research](manuals/research/guide.md) and [concept clarification](manuals/concept-clarification/guide.md): optional methods for your project.
- [Coding Skill examples](examples/coding-skills/README.md): optional development methods, separate from the Runtime installation.
