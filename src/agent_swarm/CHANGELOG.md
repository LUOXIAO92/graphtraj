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

## 0.2.7 (compatible)

- A resumed Claude execution no longer loses its reply from the archive (422). A reply
  that reached the transcript before the history boundary was read counted as history,
  and `messages()` raised `Unresolved observations remain`. The boundary is now measured
  before Claude's hook is answered, so what Claude writes afterwards is always new. Only
  the controlled test peer has shown this; a real Claude would need the same delay.
- Records written after the hook, including off-chain ones, are now collected however
  late the archive's first read runs. A late read used to drop them as history. A resume
  without delay and a first start archive the same content as before.

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
