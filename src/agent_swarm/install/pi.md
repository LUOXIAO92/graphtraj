# agents on Pi

This makes a Pi Session the host of its child Agents, through a Pi extension. Back to
the [README](../README.md).

## Prerequisites

- Python 3.12 or later.
- Pi, installed, with a model selected and logged in. There is no version floor in
  agents; the sources and real runs are Pi `1.4.0`.
- A Pi child also needs [its sandbox tools](../README.md#what-a-pi-child-needs). A
  Claude, Codex or DSH child of a Pi host does not.

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

## Distribution: `pi install`

The installed directory `agent_swarm/pi/` is a Pi package. Install it with Pi's own
command, from the agents environment Pi should use. It is not on a public market.

```sh
PI_PACKAGE="$("$AGENTS_VENV/bin/python" -c 'import agent_swarm.pi, pathlib; print(pathlib.Path(agent_swarm.pi.__file__).parent)')"
pi install "$PI_PACKAGE"       # for you; add -l for this project only
```

> Not yet walked on a real host: `pi install` of this directory. The real runs used
> `-e`, below.

## Local files: `-e` for one invocation

Nothing is installed; the extension loads for this one run:

```sh
pi -e "$PI_PACKAGE/extension.mjs" --agents-config /absolute/pi-host.json
```

## Minimal configuration

`/absolute/pi-host.json`:

```json
{"root": "/absolute/agents-data"}
```

Allowed keys: `root` (required, absolute), `pi`, `claude`, `codex` and `dsh`. Any other
key stops the start.

`config.yml` for connections and presets goes in `root`. See
[Configuration](../README.md#configuration).

## Start it

```sh
AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" pi --agents-config /absolute/pi-host.json
```

Add `-e "$PI_PACKAGE/extension.mjs"` if you did not `pi install`. `AGENT_SWARM_PYTHON`
names the Python that has `agent-swarm`; without it the Session start fails.

A refused start shows as the extension's error, with one `{"error": {"code",
"message"}}` line, and the Session has no `agents` tool.

> Not yet walked on a real host from a wheel-only install: these steps run as written
> in a clean environment. The same host ran on real Pi 1.4.0 with `-e` in earlier checks.

## See that it worked

- The model can call the `agents` tool, through the MCP server `agents`.
- Ask it to create a Claude child that answers one word. A message appears in the Pi
  Session titled `[agents notice from <agent> · completed]`.
- `status` then shows `last_result.notification: delivered`, and `last_message: null`
  because the body was already shown.

Print mode works too, but a Session with no UI delivers held notices only once a turn
has started.

## Children on other Runtimes

`create`'s `runtime` selects the driver. `claude` needs nothing more. A `pi` child
needs its sandbox settings, and `dsh` a model. The sections below set defaults for each:

```json
{
  "root": "/absolute/agents-data",
  "claude": {"model": "claude-sonnet-5-5"},
  "dsh": {"model": "deepseek-flash", "api_key_env": "DEEPSEEK_API_KEY"},
  "codex": {
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
  },
  "pi": {
    "sandbox_python": "/absolute/pi-sandbox/venv/bin/python",
    "sandbox_path": "/absolute/pi-sandbox/srt/node_modules/.bin:/absolute/node/bin:/absolute/ripgrep/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  }
}
```

- `claude`: the keys of the [Claude host's `settings`](claude-code.md#minimal-configuration).
  Children default to read access. Needs Claude Code 2.1.299 or later.
- `dsh`: `model` is required. Children default to the `read-only` sandbox. Needs DSH
  0.2.0-rc.2 or later.
- `codex`: the document [`agent_swarm.codex.host --settings`](codex.md) reads. Without
  it a Codex `create` fails with `invalid-config`.
- `pi`: overrides of the child's defaults. Without it a child inherits the parent's
  provider, model and Pi. It also takes `sandbox_python`, the Python that has
  `agent_sandbox`, and `sandbox_path`, which must reach `srt` and `node`, and `rg`.
  Children default to `worktree_access: read`. The data root must lie outside the
  directory the Pi child works in, so keep `root` outside the directory you start Pi
  from.

Set a model at `create` to choose another one for one child.

> Not yet walked on a real host: Codex, DSH and Pi children of this host. Claude children
> have run on a real host.

## Upgrade

1. Install the new wheel into the same environment, as above.
2. If you used `pi install`, run it again with the same directory, so Pi loads the new
   extension. With `-e` there is nothing else to do.
3. Start Pi with the same configuration. Resuming the same Session binds a new host,
   which delivers what was held.

> Not yet walked on a real host: `pi install` over an earlier install of this package.

## Limits

- A notice to a Pi parent that is mid-turn is taken at the end of that turn. A
  permission-request notice can therefore arrive after the parent has answered the
  request, and then costs one more model turn. The real run saw this once.
- On `session_shutdown` (quit, reload, new, resume or fork), the host stops every child
  within 10 seconds in total. An Agent it cannot confirm stopped is named in a
  `stop-unconfirmed` line on stderr, the host exits non-zero, and the extension's
  shutdown handler rejects with that text.
- Held notices belong to their Session: a new or forked Session does not get them.
- `agents` calls run one at a time on this host.
- A connection without `base_url` support on Pi: declare the endpoint as a provider in
  Pi's own `models.json` in that connection's home.
- An extension in a connection's home can change a call's input after review, and a
  `mcp.json` server named `agents` there gets the name the review exempts. That home is
  your own trust decision.
- Pi's custom message type is still `graphtraj:agent-communication` until the rename.
</content>
