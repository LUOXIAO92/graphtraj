# Changelog

`agent-swarm` follows semantic versioning on its [public interface](PUBLIC_API.md);
section 7 there holds the rules. Each version is marked compatible or incompatible
with the version before it.

**Nothing has been published yet.** There is no tag and no PyPI release. The version
numbers mark points in the repository's `dev` history. Before 0.2.4 several fixes
merged without raising the number, so two commits with the same number can differ. A
wheel names only a version, so build it from a commit you know. 0.2.4 is the first
version that identifies everything listed under it.

The numbers in parentheses are the project's Task numbers.

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

- A DSH child no longer leaves `dsh web` and `agent_swarm.mcp` running when the process
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
  `agents` tool description says what it is for, and `agent_swarm.codex.host` adds a
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
- GraphTraj requires `agent-swarm>=0.2.7,<0.3` because it passes these to keep its own
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
- GraphTraj relies on this for its members, so it now requires `agent-swarm>=0.2.6,<0.3`.

## 0.2.5 (compatible)

- `agent_swarm.claude.host configuration --write` on a configured project (419) now
  updates only what the command owns: `command` and `args` of the `agents` MCP server,
  the two `GRAPHTRAJ_CLAUDE_HOST_*` variables, `cwd`, `claude` and the plugin files.
  Other keys of the `agents` entry, such as `env`, were lost before and are now kept.
- The same re-run no longer resets `root` and `channel_file`, so a host with Pi children
  still starts afterwards. If the project itself moved, a path inside its old directory
  moves with it. Without `--write`, the printed configuration shows the kept paths.
- An existing JSON file that does not parse or does not hold an object now raises
  `ValueError` naming it, and nothing is written.
- New public names `write_adoption` and `kept_host_paths` in `agent_swarm.claude`.
  GraphTraj's Claude host imports them, so GraphTraj now requires
  `agent-swarm>=0.2.5,<0.3`.

## 0.2.4 (compatible)

- New public names `stop_owned` and `exit_if_owned_unconfirmed` (415). GraphTraj's
  Claude host imports them, and commits numbered 0.2.3 may lack them, so GraphTraj now
  requires `agent-swarm>=0.2.4,<0.3`.
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
  agent_swarm` stopped loading the `agent_swarm.codex` package.
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
