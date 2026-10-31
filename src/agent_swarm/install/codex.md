# agents on Codex

This runs a Codex Session as the host of its child Agents. Back to the
[README](../README.md).

## Prerequisites

- Python 3.12 or later.
- Codex, installed and logged in. There is no version floor in agents; the real runs
  used `codex-cli` 0.164.0, and some behaviour below is stated for that version.

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

There is no Codex plugin and nothing to install into Codex. The host is a command in
this wheel, `python -m agent_swarm.codex.host`. It starts its own Codex service and
one parent Session. That Session sees the `agents` tool because the host registers it
for that Session.

So it **cannot** attach to a Codex you already have open, in the terminal or an app.
You cannot talk to the parent while it runs: it takes one instruction per invocation,
and `--resume` gives it the next one.

## Local files

Nothing is generated into a project. You write one settings file and choose one
directory for the host's data.

## Minimal configuration

`native-settings.json`, with your model and an absolute working path:

```json
{
  "adapter_request": {
    "arguments": ["codex"],
    "worktree_path": "/absolute/work",
    "session_parameters": {
      "cwd": "/absolute/work",
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
}
```

`session_parameters.config` can also hold Codex's own provider, reasoning and network
options. A top-level `connection` may set `runtime_home`, `base_url` or `api_key_env`
(the name of a variable, never its value). Codex's own `auto_review` reviews approvals
unless your settings name another reviewer.

`config.yml` for connections and presets goes in the `--directory` you choose. See
[Configuration](../README.md#configuration).

## Run it

```sh
"$AGENTS_VENV/bin/python" -m agent_swarm.codex.host \
  --settings native-settings.json --directory /absolute/agents-data \
  --output /absolute/agents-data/last-run.json \
  'Use the agents tool to create a Codex child that answers one word, then wait for it.'
```

| Flag | Meaning |
| --- | --- |
| `--settings <file>` | Required. The settings above |
| `--directory <dir>` | Required. The data root and the parent's retained state |
| `--output <file>` | Optional. Writes the result document as JSON |
| `--resume` | Continue the retained parent Session in this `--directory` |
| `<instruction>` | Required. The parent's instruction |

Without `--resume`, a directory that already holds a parent Session is refused with
`session-exists`. A second host on the same directory is refused with `turn-running`.
A refused start prints `{"error": {"code", "message"}}` and exits `1`.

If the parent itself needs a native approval, the request prints to stderr as
`{"native_request": ...}` and the host reads one JSON response from stdin.

> Not yet walked on a real host from a wheel-only install: these steps run as written
> in a clean environment. The same host ran on real Codex 0.164.0 in earlier checks.

## See that it worked

- stderr starts with `{"parent_session": ..., "source": "thread/start"}`.
- stderr shows each exchange, as `┌ <parent session> → <agent>` for the instruction
  and `┌ <agent> → <parent session>` for the child's reply.
- stdout ends with the parent's last message, and the exit status is 0.
- `--output`'s `deliveries` lists each notice sent, and `stop_unconfirmed` is an empty
  list.

`deliveries` shows that a notice was submitted, not that the model read it. A notice
that arrives after the parent's turn ended is held, and the next `--resume` delivers it.

## Children on other Runtimes

Add a top-level `runtimes` object to the settings file. A Runtime without an entry
fails `create` with `unsupported-runtime`. All children run in
`adapter_request.worktree_path`, and each entry is checked when the host starts.

```json
{
  "adapter_request": {
    "arguments": ["codex"],
    "worktree_path": "/absolute/work",
    "session_parameters": {
      "cwd": "/absolute/work",
      "model": "your-codex-model",
      "developerInstructions": "",
      "config": {
        "default_permissions": "work",
        "permissions": {
          "work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}
        }
      }
    }
  },
  "runtimes": {
    "claude": {"model": "claude-sonnet-5-5"},
    "dsh": {"model": "deepseek-flash", "sandbox": "read-only", "api_key_env": "DEEPSEEK_API_KEY"},
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

`claude` takes the keys of the [Claude host's `settings`](claude-code.md#minimal-configuration)
and needs Claude Code 2.1.299 or later. `dsh` requires `model` and `sandbox` and needs
DSH 0.2.0-rc.2 or later. `pi` requires `provider` and `model`, and needs
[what a Pi child needs](../README.md#what-a-pi-child-needs).

**Pi children need `--directory` outside `worktree_path`.** A Pi child must not read
the data root, and its sandbox cannot deny a path inside a readable one, so the host
refuses that layout at start with `invalid-config`.

> Not yet walked on a real host: Pi children of this host. Claude and DSH children have
> run on a real host.

## Upgrade

Install the new wheel into the same environment, as above. Nothing else is generated,
so there is nothing to regenerate. Use `--resume` with the same `--directory` to
continue the parent; its children stay listed by `status`.

## Limits

- It is a headless parent: one instruction per invocation, no attaching to an open
  Codex.
- Under `auto_review`, Codex decides its children's approvals itself. Only a refusal
  or a reviewer failure reaches the parent, which can `accept` one retry or `decline`.
  The retry goes through auto review again. The accept path is shown by tests only.
- `agents` calls run one at a time on this host.
- A stop agents cannot confirm is reported on stderr as `{"error": {"code":
  "stop-unconfirmed", ...}}` and in `stop_unconfirmed` in `--output`, and the host
  exits non-zero. The parent cannot see it, because its run has ended. A run that
  raises writes no `--output`, so only the stderr line names those Agents.
- A notice not yet sent when a resumed turn ends waits for the next `--resume`.
- The native names `graphtraj` in Codex's `clientInfo` and MCP server name remain until
  the rename.
</content>
