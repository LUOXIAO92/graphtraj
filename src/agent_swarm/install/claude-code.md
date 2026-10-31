# agents on Claude Code

This makes a Claude Code Session the host of its child Agents. Back to the
[README](../README.md).

## Prerequisites

- Python 3.12 or later.
- Claude Code 2.1.299 or later, installed and logged in. Earlier versions are refused
  when a Claude child starts. The real runs used 2.1.312 and 2.1.314.
- A directory you will start Claude Code from. It does not need to be a Git
  repository.

## Install the wheel

In a checkout of the repository, or skip the `pip wheel` line and give `pip install`
the path of a wheel you were given:

```sh
AGENTS_VENV=/absolute/agents-venv
python3 -m venv "$AGENTS_VENV"
WHEELS="$(mktemp -d)"
"$AGENTS_VENV/bin/python" -m pip wheel --no-deps -w "$WHEELS" ./src/agent_swarm
"$AGENTS_VENV/bin/python" -m pip install "$WHEELS"/agent_swarm-*.whl
```

## Distribution

No marketplace package exists today: nothing is published to a Claude Code plugin
marketplace, and this repository holds no marketplace manifest. Generating the plugin
files, below, is the way to install.

## Generate the plugin files

```sh
PROJECT=/absolute/working-directory
"$AGENTS_VENV/bin/python" -m agent_swarm.claude.host configuration \
  --project "$PROJECT" --claude "$(command -v claude)" --write
```

Without `--write` the command only prints what it would write. With it, the command
prints the list of paths and writes:

| Path under the project | What it is |
| --- | --- |
| `.mcp.json` | The `agents` MCP server, started with this environment's Python |
| `.agents-control/claude-host.json` | The host configuration |
| `.claude/settings.local.json` | Two `env` entries that point the plugin at this Python and configuration |
| `.claude/skills/agents-claude-host/` | The plugin: its manifest, hooks and `host_context.mjs` |

Running it again on a configured project updates only what the command owns: `command`
and `args` of the `agents` server, the two `env` entries, `cwd` and `claude` in the host
configuration, and the plugin files. Everything else stays, including other keys of the
`agents` server such as `env`, other servers and `root`, `channel_file`, `settings` and
`runtimes` in the host configuration. Without `--write`, the printed host configuration
shows the `root` and `channel_file` that would be kept.

If you moved the project, a `root` or `channel_file` inside its old directory moves to
the same relative place in the new one. A path outside the old directory stays as it is.

An existing JSON file that does not parse or does not hold an object stops the command
with an error naming the file, and nothing is written. Fix or remove that file.

## Minimal configuration

The generated file is already enough to start Claude children:

```json
{
  "root": "/absolute/working-directory/.agents-control",
  "cwd": "/absolute/working-directory",
  "claude": "/absolute/path/to/claude",
  "channel_file": "/absolute/working-directory/.agents-control/live/channel.json",
  "settings": {}
}
```

`settings` applies to every Claude child unless `create` chooses otherwise. Its keys
are all optional: `model` (default `claude-opus-5-5`), `reasoning_effort`,
`runtime_home`, `instructions`, `read_paths`, `worktree_access` (default `write`),
`permission_mode` (`auto` by default, or `default`), `base_url` and `api_key_env` (the
name of a variable, never its value).

`config.yml` for connections and presets goes in the data root,
`.agents-control/config.yml`. See [Configuration](../README.md#configuration).

## Start it

```sh
cd "$PROJECT"
claude
```

Use the same `claude` you named in `--claude`. Approve Claude Code's ordinary folder
trust and project MCP server prompts. Start or resume Claude Code from this exact
directory: a host started from a subdirectory refuses, and elsewhere Claude Code does
not load this project's `.mcp.json`.

> Not yet walked on a real host from a wheel-only install: these steps run as written
> in a clean environment. The same host ran on real Claude Code in earlier checks.

## See that it worked

- In the Session, `/agents-context` prints the current Session, `MCP agents
  registered` and the state of notice push, without a model turn. `/mcp` lists `agents`.
- Ask the model to create a Claude child that answers one word, then to `wait` for it.
  The result shows `state: standby` and `last_result.outcome: completed`.
- After you quit, `.agents-control/host.log` ends with `agents host recorded its
  children stopped.`

If every `agents` call returns `host-unavailable`, the host refused to start.
`.agents-control/host.log` holds the reason as one JSON line; search for `did not
start`. Fix the cause and start Claude Code again.

## Children on other Runtimes

Add a `runtimes` object beside `settings`. A Runtime without an entry fails `create`
with `unsupported-runtime`. Each entry is checked when the host starts.

```json
{
  "root": "/absolute/working-directory/.agents-control",
  "cwd": "/absolute/working-directory",
  "claude": "/absolute/path/to/claude",
  "channel_file": "/absolute/working-directory/.agents-control/live/channel.json",
  "settings": {},
  "runtimes": {
    "codex": {
      "adapter_request": {
        "arguments": ["codex"],
        "worktree_path": "/absolute/working-directory",
        "session_parameters": {
          "cwd": "/absolute/working-directory",
          "model": "your-codex-model",
          "developerInstructions": "",
          "config": {
            "default_permissions": "work",
            "permissions": {
              "work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}
            }
          }
        }
      }
    },
    "dsh": {"model": "deepseek-flash", "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"}
  }
}
```

`codex` takes the document [`agent_swarm.codex.host --settings`](codex.md) reads. `dsh`
requires `model` and `sandbox` (`read-only` or `workspace-write`) and needs DSH
0.2.0-rc.2 or later.

For Pi children, first install [what a Pi child needs](../README.md#what-a-pi-child-needs).
Pi's entry requires `provider` and `model`, and `executable` defaults to `pi` on the
host's PATH:

```json
{
  "root": "/absolute/agents-data",
  "cwd": "/absolute/working-directory",
  "claude": "/absolute/path/to/claude",
  "channel_file": "/absolute/working-directory/.agents-control/live/channel.json",
  "settings": {},
  "runtimes": {
    "pi": {
      "provider": "deepseek",
      "model": "deepseek-flash",
      "api_key_env": "DEEPSEEK_API_KEY",
      "sandbox_python": "/absolute/pi-sandbox/venv/bin/python",
      "sandbox_path": "/absolute/pi-sandbox/srt/node_modules/.bin:/absolute/node/bin:/absolute/ripgrep/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
  }
}
```

**Pi children need `root` outside the project.** A Pi child must not read the data
root, and its sandbox cannot deny a path inside a readable one, so the host refuses
this layout at start with `invalid-config`. Set `root` as above and move `config.yml`
and any existing `control/`, `native/` and `sessions/` there. `channel_file` and
`host.log` may stay in the project.

> Not yet walked on a real host: Pi and DSH children of this host. Codex children have
> run on a real host.

## Upgrade

1. Install the new wheel into the same environment, as above.
2. Run `configuration --write` again. **This is required:** an earlier copy of the
   plugin never acknowledges a notice, so its pushed notices repeat once per host
   process.
3. Start a new Claude Code process.

## Limits

- A notice title reads `[GraphTraj notice from <alias> · <event>]` until the rename,
  and `.claude/settings.local.json` holds two `GRAPHTRAJ_` variables.
- Push needs prompt submission. In print mode (`claude -p`) a notice arrives only as
  `main_notices` on the next `agents` result.
- The host serves `agents` calls concurrently, so a long `wait` does not block a call
  Claude Code sends while it runs. Within one turn Claude Code itself runs the calls
  one at a time until it moves a long one to the background (up to 120 seconds, seen
  on 2.1.314); print mode showed no overlap. A call you cancel gets no response.
- Two identical calls in parallel share one association, and the second gets a
  refusal you can retry.
- A stop agents cannot confirm is reported in `host.log` only: the Session has closed
  and cannot see it. Read the state through `status` on the next host. If Claude Code
  kills the host before it finishes, a child can stay `running` with no notice until a
  later host process.
- Only one host can run per project at a time. Another start is refused like the
  cases above.
</content>
