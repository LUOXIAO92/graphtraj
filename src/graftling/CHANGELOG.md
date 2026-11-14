# Changelog

`graftling` follows semantic versioning on its [public interface](PUBLIC_API.md);
section 7 there holds the rules. Each version is marked compatible or incompatible
with the version before it.

**Nothing has been published yet.** There is no tag and no PyPI release. The version
numbers mark points in the repository's `dev` history. Before 0.2.4 several fixes
merged without raising the number, so two commits with the same number can differ. A
wheel names only a version, so build it from a commit you know. 0.2.4 is the first
version that identifies everything listed under it.

The numbers in parentheses are the project's Task numbers.

## Unreleased (compatible)

- A DSH execution's tool processes are reclaimed the same way (463). DSH starts each
  Bash tool in its own session and on shutdown stops only those groups, so a process a
  tool moved into yet another session (`setsid`) outlived both a normal end and a
  killed owner. The `dsh web` service now gets this execution's `GRAFTLING_MEMBER_RUN`
  marker, its descendants are recorded as for Claude, and both drivers record
  `tool_marker` and `tool_descendants`. After a normal end or stop the owner stops the
  survivors once the service has exited and keeps the report in
  `dsh-termination-<execution>.yml` and the result's `escaped_processes`; reconciling an
  `owner-exited` execution stops them as for Claude.
- New public names `read_tool_descendants` and `stop_tool_processes` (section 1.3), so a
  host can stop a killed owner's recorded tool processes the way owner-exited
  reconciliation does (460). The functions themselves are unchanged.
- A Codex child's tool processes are now stopped after its owner or its service ends
  (462). Codex runs a tool shell in its own session below its app-server and stops it
  when its stdin closes, but a killed app-server leaves the shell and its command
  running. The Codex owner now starts its owned app-server with the execution's own
  `GRAFTLING_MEMBER_RUN` value (the parent's is still removed, 450) and sets it for
  tool shells, records the app-server's descendants as 459 does, and stops what is left
  once the app-server has exited, on its own thread so the end is not delayed
  (`codex-termination-<turn>.yml`, possibly written after the end is reported). The Codex driver and GraphTraj's agents
  driver record `tool_marker` and `tool_descendants`, so reconciling an `owner-exited`
  Codex execution stops them too. Limits are 459's; in addition a user-started
  `CodexHost` and a service reached through a proxy or an existing WebSocket are not
  covered, and Pi and DSH executions are unchanged.
- A Pi execution's tool processes are now stopped the same way as a Claude
  execution's (461): Pi starts its bash tool detached as `/bin/bash` and stops the
  running tool's process group itself when it shuts down; a background job left by an
  earlier tool call, or any tool process when Pi is killed without shutting down, is
  stopped through the recorded descendants. The Pi driver and GraphTraj's agents driver
  now record `tool_marker` and `tool_descendants` for Pi too.
- A Claude execution's tool processes that are Apple platform binaries are now stopped
  too (459): Claude Code's `/bin/zsh` Bash tool shell and commands such as
  `/bin/sleep`, whose environment macOS hides from the 457 marker scan. While the
  Runtime runs, its owner records the Runtime's descendants about once a second (pid,
  process group, uid, start time) in a file whose absolute path is the new process fact
  `tool_descendants`. Reconciling an `owner-exited` execution, and the owner's own
  reclaim after a normal end or stop, stop the recorded processes still alive with the
  same uid and start time, and their current descendants, along with the marked ones,
  and list them in `escaped_processes`. An unreadable record or a failed scan appears
  in its `error` field. Recorded command lines (the record file and `escaped_processes`)
  are redacted and cut to 300 characters; redaction covers only recognizable
  credentials. A readable descendant without this execution's marker (another
  execution's child Runtime, a Runner Worker) is not recorded or followed. Known limits:
  a process started and detached between two samples (about one second) is found only
  by the marker, so not when it is a platform binary; a process below a readable
  process without the marker is left alone by design; Windows is not covered. Older
  records, and Codex (until 462), Pi and DSH executions, are unchanged. The macOS pid listing also
  retries when its buffer was full, instead of returning a cut-short list.
- Reconciling an owner-exited Claude execution now stops the tool processes it left
  (457). The Claude driver and GraphTraj's agents driver record the execution's
  `GRAFTLING_MEMBER_RUN` value as the process fact `tool_marker`. The call that ends
  the execution `owner-exited` stops same-user processes carrying exactly that value
  and records them as `escaped_processes`. Before, a killed owner left the child's
  Bash tool shell and its command running, since they run outside the Runtime's
  process group. Older records, and Codex, Pi and DSH executions, are unchanged. On
  macOS this does not reach Apple platform binaries, whose environment cannot be read:
  Claude Code's `/bin/zsh` tool shell and commands such as `/bin/sleep` stay running.
- A process that runs `create` now keeps the execution's owner until it reports its end
  (452). The Claude, Codex, Pi and DSH drivers start that owner as a non-daemon thread, so
  a `create` answered on a daemon thread no longer loses its end when the process exits.
- The Agent document gains `configuration`, the configuration a driver applied at
  `create` (455). A driver may return `applied` (`configuration`, `model`,
  `reasoning_effort`) from `prepare`; the core records it and fills `model` and
  `reasoning_effort` only where `config.yml` chose none. GraphTraj's driver reports
  the role preset it resolved, so a child created with `configuration` (or the
  Runtime's own preset) no longer shows `null` for its model. Other drivers and older
  records show `null` as before.
- An end found by reconciliation now notifies the parent once without `hold_notices`
  too (451). When a call finds a running execution whose owner and Runtime are gone,
  it ends it `failed` with error `owner-exited` and records it `held` in the same write.
  A control with a receiver claims it and calls the receiver once, after the record
  lock is released, as for any other failed end. Before, only `hold_notices` hosts
  recorded such an end, and other hosts notified nobody. `last_result.notification`
  can now be `held` for such an end on a host without `hold_notices`, a value the
  field already had. GraphTraj's Runner Worker now checks a running Task member's
  children every 15 seconds, so such an end reaches the member within about that time.
  A Task member that is not running holds the end, and its next run receives it once;
  a read never resumes it. The claimed notice names the end's `error` for a host
  receiver, as `finished()` does.
- Each end notice names the execution it reports (449). The Codex host event gains
  `execution`, the same ID as the end's `last_result.id`; the Claude Code queue record,
  the Pi `details` and the DSH notice already held it. The text shown to the model ends
  its title with `· execution <id>` on the Claude Code, Pi and DSH hosts, for example
  `[Graftling notice from <alias> · completed · execution <id>]`. A new field and a longer
  title are compatible under section 7; a reader matching the title up to the event is
  unaffected.
- A Claude Code marketplace package (418): `.claude-plugin/marketplace.json` at the
  repository root lists the plugin `graftling` in `src/graftling/claude-plugin/`. It
  starts the `agents` host without `configuration --write`, finds its Python through
  `GRAFTLING_PYTHON` and then `python3` on `PATH`, and says what to install when neither
  imports `graftling`. `graftling.claude.host serve --project` and
  `context --project-from` are its entries. A project with `configuration --write`
  material keeps that host; the plugin's host refuses there. Seen on a real host in
  `claude -p` only: installed from a local marketplace at project scope, it created a
  Claude child and `wait` returned it completed. Interactive use, `/agents-context` and
  notice push are untried.

## 0.5.0 (incompatible)

The distribution is renamed Graftling (394). Every renamed name below is part of the
public interface, so the minor version rises. Old names are not read any more; the
README's *Moving from agent-swarm 0.4* lists the steps. Entries below 0.5.0 use the new
names; the distribution was then called `agent-swarm` and imported as `agent_swarm`.

- Distribution and Python package `graftling`; the host entry point group is
  `graftling.hosts`. The `agents` and `agents-mcp` commands and the `agents` tool keep
  their names. The Pi and DSH packages are `graftling-pi` and `graftling-dsh`.
- Environment variables: `AGENT_SWARM_<NAME>` became `GRAFTLING_<NAME>` (for example
  `GRAFTLING_CONNECTION`, `GRAFTLING_PYTHON`, `GRAFTLING_DSH_CONFIG`, `GRAFTLING_PI_REVIEW`),
  and the variables that carried the GraphTraj prefix became `GRAFTLING_NATIVE_RUNTIME`,
  `GRAFTLING_NATIVE_SESSION`, `GRAFTLING_NATIVE_SESSION_FILE`, `GRAFTLING_CLAUDE_HOST_PYTHON`,
  `GRAFTLING_CLAUDE_HOST_CONFIG` and `GRAFTLING_DSH_PACKAGE`. Run the Claude Code host
  install again so `.claude/settings.local.json` holds the new names.
- Native names: Codex's MCP server, `clientInfo` and `toolOutput` are `graftling`, so the
  Codex model sees `mcp__graftling__agents`; Pi's custom message type is
  `graftling:agent-communication`; Claude's hook callbacks are `graftling_start`,
  `graftling_collect_child` and `graftling_agents_display`; the Claude host's notice title
  is `[Graftling notice from <alias> · <event>]`, `graftling` when a notice names no sender.
  A resumed native Session keeps the entries it already holds under the old names.
- graftling no longer names a consumer's variables. A consumer declares its own channel
  variable and name prefix in the new entry point group `graftling.environment`
  (`PUBLIC_API.md` 1.4); without one, children lose only graftling's own channel. New
  public attributes let a consumer keep its own names: `ClaudeExecution.connection_env`,
  `CodexManagedExecution.mcp_server`, `registerAgents(pi, {displayServers})` and the DSH
  plugin's `mcpEnv` setting.
- `PiExecution` reads the project root from the request field `project_root`
  (default `worktree_path`); it read GraphTraj's `harness_root` before.
- Codex refuses every dynamic tool call, as it did for the retired names: no
  dynamic tool is registered.
- GraphTraj adopts it in the same change: its range becomes `graftling>=0.5.0,<0.6`, and
  it declares its own names through the points above, so its behaviour is unchanged.
- Version 4 Session archives stay readable: their `graphtraj` namespace is still read as
  `extra_fields.graphtraj`.

## 0.4.0 (incompatible)

Classified under `PUBLIC_API.md` section 7 as a new rejection of a request that used to
succeed, so the minor version rises. GraphTraj adopts it in the same change: its range
becomes `graftling>=0.4.0,<0.5`.

- A child Agent's `create` now refuses a new Agent whose connection uses a key the child
  does not hold, with `authority-denied` (440). A child holds its own connection's key
  (DSH's `DEEPSEEK_API_KEY` when it names none) and its connection's `pass_env`. The
  message names the key and says to add it to `pass_env` of the child's connection in
  your own configuration. A grandchild on the child's own connection is unaffected, and
  so are creates by a host or a GraphTraj Task member. Before, the owner ran the create
  with its own environment, so a child could start a grandchild on a key it was never given.
- GraphTraj: a DSH child started by `agents` can create a grandchild again (440). Its
  `agents` tool ran GraphTraj's own MCP entry, which ignored the child's channel and ran the
  create inside the MCP server as the Task member. DSH strips credential names from an MCP
  server's environment, so the launch failed with `RUNTIME_CREDENTIAL_MISSING`. The child
  now runs `graftling.mcp`, and its create runs in its owner as the child.

## 0.3.1 (compatible)

- A Codex host you start yourself (`CodexHost`) again runs its own Codex with your
  environment: 0.3.0 had applied the child rule and the credential shell exclude to it
  too, so its tool shell lost names such as `GH_TOKEN`. Children it starts still get the
  0.3.0 rule and exclude. This matches the README and `PUBLIC_API.md` 3.1, which leave a
  top-level host's environment to the user, so it is a compatible fix. (439)

## 0.3.0 (incompatible)

Classified under `PUBLIC_API.md` section 7 as a default that changes observable
behaviour, so the minor version rises. GraphTraj adopts it in the same change: its
range becomes `graftling>=0.3.0,<0.4`.

- A child Agent now receives only its own connection's key (433). Every launch path of
  all four Runtimes and of GraphTraj's Runner members calls one function,
  `graftling.child_environment`, on first start and on resume. Other credential-class
  variables, chosen by `graftling.is_credential_name`, no longer reach the child.
- `pass_env`, a list of variable names, declares more variables on a connection or at the
  top level of `config.yml` for a child with no connection. It is user configuration only:
  `create` still refuses it as an unexpected parameter. It never brings back a reviewer's
  key. GraphTraj takes it on a connection provider and on a role in `roles.yml`.
- A Codex child's tool shell now excludes credential names through
  `shell_environment_policy`, including exports reloaded from dotfiles and written to Codex's
  shell snapshot (433). `~/.zshenv` is not stopped, and `~/.zprofile` and `~/.zlogin` are not
  stopped before the snapshot is ready. The child's own key stays with Codex's process and leaves
  its shell. A declared credential name travels to Codex in the Session parameters.
- A GraphTraj inline role on a new dispatch refuses `pass_env` and `api_key_env` with
  `ROLE_NOT_CONFIGURED`; select a `connection:` instead (433). A retained Batch keeps loading.
- A Pi connection naming no key keeps the variable its home's `models.json` or `auth.json` names
  for the selected provider (433).
- **What a user may need to change:** a child that used an unrelated key from its parent's
  environment must now declare it. That covers tools in its shell such as `gh` with
  `GH_TOKEN`, a Codex MCP server with `bearer_token_env_var`, and DSH's official web search
  beside a connection naming another key (`pass_env: [DEEPSEEK_API_KEY]`).

## 0.2.20 (compatible)

- A Bash `cd` no longer ends a Claude child or loses its result (437). A native helper
  that finished while the child's working directory was moved raised `Hook working
  directory differs from collection entry`, and the execution failed with
  `RUNTIME_WORKER_FAILED`. The execution now compares the hook's Session with the Session
  it owns and ignores the hook's working directory. This is stricter: a hook naming another
  Session now fails the execution and archives nothing, where it used to be accepted.
  `hook_source` and `collect_hook_event` gain a `native_id` keyword for this; without it
  they keep comparing the working directory.
- A Claude host's `agents` call no longer fails with `Native Session/cwd/request is invalid`
  after a `cd` inside the project (437); the call still runs with the project's directory.
  A `cd` outside the project is still refused, with `authority-denied` and a message naming
  both directories and how to return.

## 0.2.19 (compatible)

- One blocked call no longer holds a closing Pi or DSH host (434). With another process
  holding one Agent's record lock, or a driver's `interrupt` that never returns, the other
  children are still interrupted and seen to end, only that Agent is named in the
  `stop-unconfirmed` line, and the process ends within 20 seconds of its pipe closing instead
  of when the lock is released. A model request in flight at the close and the notice flusher
  can add up to 3 seconds each; that request's caller is told the operation is unconfirmed.
  The line no longer says every other Agent stopped when a `status` went unanswered and no
  Agent was seen stopped.
  New: `worker_connection` and `agents_connection` take `close_seconds` (default: unchanged),
  and `AgentControl.visible_agents` names a caller's Agents without taking a record lock.
  The Pi host's stdin loop no longer writes a shown notice's record itself, so a held lock
  cannot stop it reading the close. A notice still locked when the host ends stays `held`, and
  the next host pushes it again.
  Claude and Codex hosts are unchanged.

## 0.2.18 (compatible)

- A Pi child that ends by itself before its first prompt, for example because a sandbox
  tool is missing, now fails with `RUNTIME_START_FAILED`, and the message opens with
  `Pi did not start:` and Pi's stderr (438). It used to read `RUNTIME_SHUTDOWN_FAILED`,
  `Pi native stop is unconfirmed`. That stop is still not certified.
- Esc on a running Claude host call no longer leaves that call's association prepared or
  shows `agents context cleanup failed` (438). A later hook ends it. A failure outside the
  interrupted hook is still shown, once.
- The `invalid-model` error for a model off the list now says to list its id under
  `models` of a connection in `config.yml` (438).
- The README states what a reviewer's `allow` means for a Claude child with
  `permission_mode: default`. `PUBLIC_API.md` warns that a `write` Pi child can read a token
  held in a remote URL in the repository's `config` (438).

## 0.2.17 (compatible)

- A DSH child no longer leaves `dsh web` and `graftling.mcp` running when the process
  that owns it dies before closing it (436). Every `dsh web` now comes with one small
  watcher process, with no inherited environment, that stops the process group if its
  owner ends without closing it, and writes `stopped` or `could not stop` to the owner's
  stderr: `host.log` in a Claude Code host. It keeps that stderr open until it ends,
  about 15 seconds at most. A normal close behaves as before and writes nothing.
- `agents host recorded its children stopped.` is no longer written while an Agent
  started by an earlier host still has a running Runtime (436). The host names those
  Agents in `host.log` instead. Its exit code does not change.

## 0.2.16 (compatible)

- A refused `reply` on a Claude child no longer makes the agents tool of a Pi, DSH or Codex
  host stop answering (435). The call returns its failure at once, with the code and the
  reason, and the request stays pending, so a reply in the right form still answers it. The
  refusal now names the form: a `claude/can_use_tool` request takes `{"behavior": "allow"}`
  or `{"behavior": "deny"}`. Any other unexpected failure while the channel handles a call,
  including a result it cannot serialise, is also answered as an error, with the traceback
  on the host's stderr.
- `send` to a Claude child that refuses the input now records the delivery as `rejected`
  and returns the Runtime's code and reason, as on Pi, Codex and DSH. It was recorded as
  `unknown` (435).

## 0.2.15 (compatible)

- A DSH launch can name extra writable directories (428). `DshExecution` adds the
  request's `additional_writable_roots` to the `sandbox-policy` row as DSH's own
  `additionalWritableRoots`. A launch that names none, which includes every independent
  DSH child, writes the same row as before. The package does not choose these
  directories; GraphTraj's member launch does, which is why GraphTraj now needs this
  version.

## 0.2.14 (compatible)

- The Codex install note's example could leave the parent using Codex's own `spawn_agent`,
  with `operations: []` and a last message saying the child had answered (432). The
  example now gives the literal `create` and `wait` calls and excludes `spawn_agent`. The
  `agents` tool description says what it is for, and `graftling.codex.host` adds a
  passage after the parent's `developerInstructions` naming `agents` as the way to make
  children. Children's settings are unchanged, and Codex's native tools stay available.
- A Codex host run now shows when a child did not come through `agents` (432). Stderr ends
  with `{"run_summary": {"agents_calls": N, "native_subagents": M}}`, with a note when N is
  0. A `collabAgentToolCall` `spawnAgent` item prints one `{"native_subagent": ...}` line and
  adds an entry to the new `native_subagents` in `--output` and `CodexHost.run`. stdout and
  the exit status are unchanged: a native subagent is not a failure. Which tool the model
  chooses can only be observed in a real run, and no real run has yet shown that item.
- The Claude Code, DSH and Pi install notes' examples now name the `agents` tool (432).
  This is the same wording risk; no bypass was seen on those hosts.

## 0.2.13 (compatible)

- A DSH connection that names no `api_key_env`, beside a reviewer whose `api_key_env` is
  `DEEPSEEK_API_KEY`, is now refused at `create` with `ROLE_CONFIG_INVALID` when no key
  file of the child's own exists (430). The child never receives the reviewer's key and
  DSH's default key is that same variable, so such a child could only fail at start with
  `session/model-unavailable`. The message names the reviewer, the variable and the fixes.
  A file that exists but holds no DeepSeek key still fails at start, because it is not read.
- A Pi connection with no `api_key_env`, beside a reviewer whose key is the only one that
  authenticates its model, is now refused at `create` with `invalid-config` (430). Such a
  child could only fail at its first prompt with `No API key found`. `create` asks Pi's own
  model listing with and without the reviewer's variable, so no credential is read and a
  login in the connection's home is not refused. The message names the reviewer, the
  variable, the provider and the fixes.

## 0.2.12 (compatible)

- A Codex parent no longer receives one child answer twice when its `wait` or `status`
  meets the host event carrying that answer (431). While the event is on its way, or a
  held end is being sent on `--resume`, these results show `notification: queueing` and
  `last_message: null`, as on the Pi and DSH hosts. An event that could not be written
  leaves the end `held`, so the next `status` or `--resume` still gives the answer.

## 0.2.11 (compatible)

- A Pi child with `worktree_access: write` can now commit in a linked worktree (429). It
  had write access to the Git common directory but could not read it, and Git also stopped
  on the `~/.gitconfig` the sandbox denies. The child now reads that directory, so it can
  read every branch's objects and refs, other worktrees' Git metadata and the repository's
  `config` and `hooks`, but no other worktree's working files. Its environment sets
  `GIT_CONFIG_GLOBAL` to the null device and carries the `user.name` and `user.email` the
  host's Git reports, as the `GIT_AUTHOR_*` and `GIT_COMMITTER_*` variables. Without a value
  no variable is added, and Git reports the missing identity. A `read` child is unchanged.

## 0.2.10 (compatible)

- A resumed Claude Session with a full archive no longer raises `Unresolved observations
  remain` for good because its transcript holds a record outside the conversation, such
  as an attachment (427). Only conversation messages the resume really left out now count
  as missing. A resume with no archive, and a message really missing, still make
  `messages()` raise. An archive that already holds this false gap stays pending, because
  it cannot be told from a real one.
- A Claude first start that reads a half-written last line no longer loses its messages
  (427). A resume that reads one, including a `SessionStart` hook with `source=resume`,
  now counts that line as history instead of collecting the whole history as new. A bad
  line before the last is still reported.

## 0.2.9 (compatible)

- Reading a Claude transcript while a line is still being written no longer leaves a
  resumed archive stuck (426). The failed read stayed pending once the line completed,
  and `messages()` raised `Unresolved observations remain` for good. The next successful
  read now clears it, and the partial line stays in `observations()`. History that was
  really left out, and a line that never completes, still make `messages()` raise.
- A read that failed and later cleared no longer hides a later gap in the same archive.
- A failed read now appears under the archive locator `read-gap:<n>`, not `history-gap`.
  An archive saved by an earlier version recovers its old read failures on the next
  successful read, unless history is missing from that resume too.

## 0.2.8 (compatible)

- A resumed Claude execution no longer loses its reply from the archive (422). A reply
  that reached the transcript before the history boundary was read counted as history,
  and `messages()` raised `Unresolved observations remain`. The boundary is now measured
  before Claude's hook is answered, so what Claude writes afterwards is always new. Only
  the controlled test peer has shown this; a real Claude would need the same delay.
- Records written after the hook, including off-chain ones, are now collected however
  late the archive's first read runs. A late read used to drop them as history. A resume
  without delay and a first start archive the same content as before.

## 0.2.7 (compatible)

- A standalone Pi attachment under `.graphtraj` is now copied (424). agents read it as
  missing because it named that directory itself; it no longer does.
- New keyword `private_paths` on `PiArchive` and new attribute `archive_private_paths` on
  `PiExecution`: further directories kept out of attachment copies. The data root,
  `<project>/.codex` and `~/.codex` stay protected, and the rule is now in the public
  interface (1.5).
- A `.codex` that is itself a link now stays protected. It used to be compared unresolved,
  so its files were copied if the link's target lay inside the authorized directory.
- GraphTraj requires `graftling>=0.2.7,<0.3` because it passes these to keep its own
  `.graphtraj` protected.

## 0.2.6 (compatible)

- A failure while closing up no longer replaces the failure already on its way to the
  parent (421). A DSH child that could not start used to report an empty
  `RUNTIME_TRACE_FAILED` on a resume with session saving on; it now reports
  `RUNTIME_START_FAILED` with DSH's own words. The second failure goes to the child's
  `stderr.log`, and a stop that could not be confirmed still gives
  `terminal_confirmed: false`.
- The same holds for Claude and Pi. Codex keeps `RUNTIME_SHUTDOWN_FAILED` for a service
  that will not exit, and its message now ends with the original failure.
- A DSH Trace that is empty after a completed turn reports `RUNTIME_TRACE_FAILED` with
  text; its message used to be empty.
- GraphTraj relies on this for its members, so it now requires `graftling>=0.2.6,<0.3`.

## 0.2.5 (compatible)

- `graftling.claude.host configuration --write` on a configured project (419) now
  updates only what the command owns: `command` and `args` of the `agents` MCP server,
  the two `GRAFTLING_CLAUDE_HOST_*` variables, `cwd`, `claude` and the plugin files.
  Other keys of the `agents` entry, such as `env`, were lost before and are now kept.
- The same re-run no longer resets `root` and `channel_file`, so a host with Pi children
  still starts afterwards. If the project itself moved, a path inside its old directory
  moves with it. Without `--write`, the printed configuration shows the kept paths.
- An existing JSON file that does not parse or does not hold an object now raises
  `ValueError` naming it, and nothing is written.
- New public names `write_adoption` and `kept_host_paths` in `graftling.claude`.
  GraphTraj's Claude host imports them, so GraphTraj now requires
  `graftling>=0.2.5,<0.3`.

## 0.2.4 (compatible)

- New public names `stop_owned` and `exit_if_owned_unconfirmed` (415). GraphTraj's
  Claude host imports them, and commits numbered 0.2.3 may lack them, so GraphTraj now
  requires `graftling>=0.2.4,<0.3`.
- Claude Code and Codex host shutdown (415): each child's stop is tried on its own, so
  one failed or blocked interrupt no longer leaves the others running. A stop still
  unconfirmed after 10 seconds is named in one `stop-unconfirmed` line, and the process
  exits non-zero. Before, the Codex host exited 0 and recorded nothing, and Claude Code
  hosts raised an error naming no Agent.
- The Codex host's `--output` document gains `stop_unconfirmed`.
- `interrupt_owned` no longer raises when one Agent's interrupt fails, and returns
  while one is blocked.
- This README, `CHANGELOG.md` and the host notes under `install/`, all in the wheel
  (391).

## 0.2.3 (compatible)

- The review plugin now covers Pi and DSH children (387). A Pi or DSH connection with
  `review` was refused with `invalid-config`, and is now accepted. Both adapters hold
  the tool call until it is answered.

## 0.2.2 (compatible)

- Public names for building a host or a consumer on agents (400): stoppable calls, the
  owner connection, the progressive envelope, MCP server parts, notices, processes and
  locks, Runtime executions, and per-Runtime packages. JavaScript exports. `import
  graftling` stopped loading the `graftling.codex` package.
- A package can declare a tool beside `agents` in its own Claude Code host:
  `claude_host_plugin` and `NativeCalls` with `tools` (400).
- `request_notices="decisions"` applies request notices to `ask_parent` only (400).
- A Pi child that is itself a parent receives its children's ends and permission
  requests, once each, held while it is stopped (410). `ExecutionEvents.return_notice`
  is new for that.
- A Pi child's key is off the command line and out of files, and its command reaches
  `srt` as one quoted word, so paths with spaces work (412).
- A DSH child no longer inherits `DEEPSEEK_BASE_URL` or `DEEPSEEK_SEARCH_BASE_URL`, and
  a failed DSH turn's message includes the native error (411). A setup that relied on
  those variables must declare `base_url`.
- `discover_models` for DSH follows the connection's `base_url` and `api_key_env`, and
  for Pi no longer writes into the home. So does Pi's keyless `pi_destination` (413).
- A DSH connection with `DEEPSEEK_API_KEY` at another origin sends web search to that
  endpoint, not to official search (413). To keep official search beside a gateway,
  name the gateway's key in another variable.
- Pi and DSH host shutdown with an unanswered request no longer abandons the other
  children or hangs (414). 10 seconds in total, all interrupts first. An Agent still
  unconfirmed is named in a `stop-unconfirmed` line, with a non-zero exit.

## 0.2.1 (compatible)

- Review plugin core and the Claude and Codex adapters (386): `reviewers`, a
  connection's `review`, the Agent document's `review`, and the error
  `review-unavailable`.
- Host notice holding (403): `last_result.notification` gains `held`, and
  `AgentControl(hold_notices=...)` with `held_notices`, `settle_notice`, `settle_shown`,
  `notice_open` and `close_notices`. All four hosts enable it, so a notice for a stopped
  parent is delivered once when it next runs. On the Claude Code host, a body shown by
  `wait` or `status` is then `delivered`, so a second read shows `last_message: null`.
  Adopting this means running `configuration --write` again.
- A Codex child that is itself a parent receives its children's notices (403).
- The Claude Code and Codex hosts accept a `pi` entry in `runtimes` (408). A Pi child
  needs the data root outside the worktree.

## 0.2.0 (incompatible)

- **Incompatible:** the normalized Session archive moves to `header.version` 5 (384).
  Readers older than 0.2.0 refuse it. Version 4 files stay readable and are rewritten
  whole as version 5 on their next change.
- Archives work in every independent host, with no refusal (384). `extra_fields`
  namespaces are new, on `create` and in the archive.
- Pi host, as a Pi extension (382), and DSH host, as a DSH plugin (383). The DSH gate is
  now a floor: 0.2.0-rc.2 or later.
- The Claude Code and Codex hosts accept a `dsh` entry in `runtimes` (383).
- Approval layers (385): `workspace` on `create`, `ask_parent`, the `reply` checks, and
  the relay of Codex's `auto_review` refusals to the direct parent.
- The Claude Code host serves `agents` calls concurrently (404). The code
  `call-cancelled` comes with it.

## 0.1.2 (compatible)

- The Claude Code and Codex hosts run children on each other's Runtime through
  `runtimes` (381).
- The notice event `request` and `AgentControl(request_notices=...)` (381).
- A Codex model mismatch at start or resume, or a `model/rerouted` notification, ends
  the child `failed` with `RUNTIME_REQUEST_FAILED` under every host, naming both models
  and the reason (381, a fix).

## 0.1.1 (compatible)

- `create` takes `preset`, `model` and `reasoning_effort`. `config.yml` gains
  `connections` and `presets`. `discover_models` and `read_connections` are new. The
  Agent document gains `preset`, `connection`, `model` and `reasoning_effort` (380).

## 0.1.0

- The first numbered version: the public interface and these version rules (379),
  around the existing `agents` tool, its CLI and MCP entries, and the independent
  Claude Code and Codex hosts. Each host ran children on its own Runtime only.
- Merged later without a bump (388, fixes): `send` with `reports_only: true` is rejected
  with `not-implemented` by agents' own backend, which used to ignore the field and
  start new work, and envelope validation errors use the coded error structure.
</content>
